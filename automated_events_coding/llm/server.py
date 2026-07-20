"""Start and manage a llama.cpp `llama-server` subprocess.

Wraps the manual "ssh to the node, load a module, run llama-server" workflow
so the pipeline can start/stop the model server itself.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


class LlamaServerError(RuntimeError):
    """Raised when llama-server fails to start or exits unexpectedly."""


@dataclass
class LlamaServerConfig:
    model_path: str
    host: str = "127.0.0.1"
    port: int = 8080

    n_ctx: int | None = None
    n_gpu_layers: int | None = None
    threads: int | None = None
    batch_size: int | None = None

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    repeat_penalty: float | None = None
    seed: int | None = None

    api_key: str | None = None
    binary: str = "llama-server"
    startup_timeout: float = 120.0
    extra_args: list[str] = field(default_factory=list)
    log_path: str | Path | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    def to_cli_args(self) -> list[str]:
        args = ["--model", str(self.model_path), "--host", self.host, "--port", str(self.port)]
        flag_map = {
            "--ctx-size": self.n_ctx,
            "--n-gpu-layers": self.n_gpu_layers,
            "--threads": self.threads,
            "--batch-size": self.batch_size,
            "--temp": self.temperature,
            "--top-p": self.top_p,
            "--top-k": self.top_k,
            "--repeat-penalty": self.repeat_penalty,
            "--seed": self.seed,
            "--api-key": self.api_key,
        }
        for flag, value in flag_map.items():
            if value is not None:
                args += [flag, str(value)]
        args += self.extra_args
        return args


class LlamaServer:
    """Manages a single llama-server subprocess.

    Usage:
        with LlamaServer(config) as server:
            client = server.get_client()
            ...
    """

    def __init__(self, config: LlamaServerConfig):
        self.config = config
        self.log_path: Path | None = None
        self._process: subprocess.Popen | None = None
        self._log_file = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.is_running:
            return

        if self.config.log_path:
            log_path = Path(self.config.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, name = tempfile.mkstemp(prefix="llama-server-", suffix=".log")
            os.close(fd)
            log_path = Path(name)
        self.log_path = log_path
        self._log_file = open(log_path, "w")

        cmd = [self.config.binary, *self.config.to_cli_args()]
        try:
            self._process = subprocess.Popen(
                cmd, stdout=self._log_file, stderr=subprocess.STDOUT
            )
        except FileNotFoundError as exc:
            self._log_file.close()
            self._log_file = None
            raise LlamaServerError(
                f"'{self.config.binary}' not found on PATH"
            ) from exc

        try:
            self._wait_until_healthy()
        except Exception:
            self.stop()
            raise

    def _wait_until_healthy(self) -> None:
        health_url = f"http://{self.config.host}:{self.config.port}/health"
        deadline = time.monotonic() + self.config.startup_timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise LlamaServerError(
                    f"llama-server exited early (code {self._process.returncode}); "
                    f"see log at {self.log_path}"
                )
            try:
                with urllib.request.urlopen(health_url, timeout=2) as resp:
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(1.0)
        raise LlamaServerError(
            f"llama-server did not become healthy within "
            f"{self.config.startup_timeout}s; see log at {self.log_path}"
        )

    def stop(self, timeout: float = 10.0) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=timeout)
        self._process = None
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def __enter__(self) -> "LlamaServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
