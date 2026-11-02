"""Start and manage a llama.cpp `llama-server` subprocess.

Wraps the manual "ssh to the node, load a module, run llama-server" workflow
so the pipeline can start/stop the model server itself.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import json
import time
import urllib.error
import urllib.request
import warnings
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
    # If a llama-server is already listening on host:port, attach to it
    # instead of launching a new one. An attached server is never stopped
    # by this class, so the model stays loaded between runs.
    reuse_existing: bool = True
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
    """Manages a single llama-server subprocess, or attaches to one that is
    already running on the configured host/port.

    Usage:
        with LlamaServer(config) as server:
            client = server.get_client()
            ...

    If a server is already listening on the port (for example one you started
    yourself in a terminal or a separate job) and ``config.reuse_existing`` is
    True, it is reused and left running on exit.
    """

    def __init__(self, config: LlamaServerConfig):
        self.config = config
        self.log_path: Path | None = None
        self._process: subprocess.Popen | None = None
        self._log_file = None
        self._attached = False

    @property
    def is_attached(self) -> bool:
        """True if using a server this object did not start."""
        return self._attached

    @property
    def is_running(self) -> bool:
        if self._attached:
            return self._health_status() == 200
        return self._process is not None and self._process.poll() is None

    def _url(self, path: str) -> str:
        return f"http://{self.config.host}:{self.config.port}{path}"

    def _health_status(self) -> int | None:
        """HTTP status of /health, or None if nothing is listening.

        llama-server answers 503 while a model is still loading and 200 once
        it is ready.
        """
        try:
            with urllib.request.urlopen(self._url("/health"), timeout=2) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            return None

    def _check_existing_model(self) -> None:
        """Warn if the attached server seems to have a different model loaded."""
        req = urllib.request.Request(self._url("/v1/models"))
        if self.config.api_key:
            req.add_header("Authorization", f"Bearer {self.config.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.load(resp)
        except Exception:
            return  # can't tell; don't block on it
        ids = [m.get("id", "") for m in data.get("data", [])]
        wanted = Path(self.config.model_path).name
        if ids and not any(Path(i).name == wanted for i in ids):
            warnings.warn(
                f"Reusing llama-server on port {self.config.port}, but it reports "
                f"model(s) {ids}, not '{wanted}'. Stop that server or use a "
                f"different port if this is not the model you want.",
                stacklevel=3,
            )

    def start(self) -> None:
        if self.is_running:
            return

        if self.config.reuse_existing and self._health_status() is not None:
            # Something is already answering on this port: attach to it,
            # waiting if it is still loading the model.
            self._attached = True
            try:
                self._wait_until_healthy()
            except Exception:
                self._attached = False
                raise
            self._check_existing_model()
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
        deadline = time.monotonic() + self.config.startup_timeout
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise LlamaServerError(
                    f"llama-server exited early (code {self._process.returncode}); "
                    f"see log at {self.log_path}"
                )
            if self._health_status() == 200:
                return
            time.sleep(1.0)
        where = (
            f"existing server on port {self.config.port}"
            if self._attached
            else f"log at {self.log_path}"
        )
        raise LlamaServerError(
            f"llama-server did not become healthy within "
            f"{self.config.startup_timeout}s; see {where}"
        )

    def stop(self, timeout: float = 10.0) -> None:
        if self._attached:
            # Not ours to stop; just detach.
            self._attached = False
            return
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