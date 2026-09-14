# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Implementation has started. The project is a `uv`-managed Python project
(`pyproject.toml`, `uv.lock`, `.python-version`); the `automated_events_coding/`
package holds application code, split into `llm/` (model-serving infrastructure)
and `pipeline/` (the Steps 0-6 pipeline logic itself, see below). Most step
modules are scaffolded but not functional yet — they're wired to call the LLM
and parse its response, but the actual prompts (`pipeline/prompts.py`) are
still empty placeholders, and the Step 2.1/2.2 gazetteer
lookups are unimplemented stubs pending their backing data.
Steps 0 and 6 are the two step modules that are fully implemented already. There is
no test runner configured yet and no lint/format tooling has been chosen;
update this section once those are added.

## Development commands

- `uv sync` — install/update dependencies from `uv.lock`.
- `uv add <package>` — add a runtime dependency (updates `pyproject.toml` + `uv.lock`).
- `uv run python -c "..."` / `uv run main.py` — run code inside the project's venv.

## What this project is

A pipeline that extracts structured events from news articles about water/groundwater
conflict and cooperation, in the style of political event-coding schemes
(CAMEO/ICEWS-like: entity codes, dyad codes, a BAR intensity scale). The
authoritative design docs are:

- `docs/pr-data-pipeline-spec.md` — step-by-step implementation spec
- `docs/pr-data-pipeline.mmd` — Mermaid flowchart of the same pipeline (node
  colors encode which steps are LLM calls vs. classifier vs. rule-based)
- `docs/SandboxEventsCodingProtocol_2026Update.pdf` — the human coding
  protocol/codebook this pipeline automates (entity codes, dyad/IRMO codes,
  BAR scale, issue area and scale-of-impact vocabularies, etc.). Deliberately
  gitignored (not committed pending the authors' approval) but present
  locally — read it directly. Much of it documents the human annotation
  tool/spreadsheet (auto-generated IDs, "Applies to Coding with Google Web
  App Form" fields) and isn't relevant to prompt design; the substantive
  parts are cross-referenced into `pipeline/schemas.py`.

Read all three before making architectural changes — the spec doc explicitly
calls out unresolved implementation questions at its end, several of which
were refined (not fully resolved) by cross-referencing the codebook; check
whether they've been resolved before assuming an answer.

## Pipeline architecture

The pipeline processes one article at a time through numbered steps. Each step maps
1:1 to a node in `docs/pr-data-pipeline.mmd`. Steps are deliberately split across
three different mechanisms — do not default to "just call the LLM" for a step that
belongs to one of the other two:

- **LLM-governed** (steps 1, 2, 3, 4, 5.1, 5.2) — prompt-driven calls to a local
  LLM served via `llama-server` (llama.cpp) on a university cluster node/port,
  invoked through the OpenAI-compatible client.
- **Classifier-governed** (step 0, relevance check) — a fine-tuned BERT classifier
  trained on existing gold-standard labeled data. Not an LLM call. The final
  model lives at https://huggingface.co/pnadel/article-classifier (private repo;
  `step0_relevance.py` loads it via `transformers` with the `HF_TOKEN` from `.env`
  at the project root — add your token there). Its `meta` (relevance label +
  score) is passed into Step 1.
- **Rule-based** (steps 2.1/2.2 gazetteer lookups; step 6 dedup) — deterministic,
  no model call. Country/basin and aquifer lookups run against gazetteer data
  (to be added to the repo). Step 6 dedup matching strategy (exact key match vs.
  fuzzy/similarity threshold) is undecided pending real example data.

Control flow, in order:

1. **Step 0** (classifier) — relevance gate + metadata, gating Step 1.
2. **Step 1** (LLM) — extracts a list of discrete `Event`s from the article text.
   Everything below runs once per event ("for each Event").
3. Two branches run per event:
   - **Step 2** (LLM) place-name extraction → **2.1** country/basin lookup
     (rule-based, unconditional, resolves a `bcode` basin code + country
     codes) and **2.2** aquifer lookup (rule-based, gated on a "GW mentioned"
     flag whose exact source step is still unconfirmed — the codebook
     suggests it may actually need to depend on 2.1's `bcode == "GRND"`
     instead, see the spec's open questions) → **Step 3** (LLM) event-lead
     extraction (date, multiday, issue area, scale of impact, groundwater,
     infrastructure involved, JBI, non-basin entity).
   - **Step 4** (LLM) (inter)action extraction → per actor/interaction, either
     **5.1** action ID or **5.2** interaction ID (LLM), producing entity/dyad
     codes and the BAR scale.
   - Whether these two branches must run sequentially or can run fully in
     parallel is unresolved — see spec's open questions.
4. **Step 6** (rule-based) — dedup against previously stored events using
   tiered matching: primary keys (`date`, `entity_list`, `bcode`), then
   secondary keys (`dyad_pairs`, `issue_area`, `bar_scale`). Ambiguous/duplicate
   → flag for human review; no match → store as new event/fact.

`Event`, `Pair`, and entity schemas are not yet formally defined as shared types —
this needs to happen before wiring the LLM prompts, since structured objects (e.g.
Step 4's actors) flow directly into downstream conditionals (5.1 vs 5.2).

## LLM server module (`automated_events_coding/llm/`)

Manages the `llama-server` (llama.cpp) subprocess that backs every LLM-governed
step, so it no longer has to be started manually as a separate step:

- `server.py` — `LlamaServerConfig` (dataclass covering model path, host/port,
  `n_ctx`, `n_gpu_layers`, threads, batch size, sampling params like
  `temperature`/`top_p`/`top_k`/`repeat_penalty`/`seed`, plus an `extra_args`
  passthrough for any other llama-server flag) and `LlamaServer`, which launches
  the binary via `subprocess.Popen`, redirects its output to a log file (never
  an unread `PIPE` — that deadlocks once llama-server's log output fills the OS
  pipe buffer), and blocks in `start()` polling the `/health` endpoint until the
  server is ready or `startup_timeout` elapses. Use as a context manager
  (`with LlamaServer(config) as server: ...`) so the process is always cleaned
  up, including on startup failure.
- `client.py` — `get_client(config)` returns an `openai.OpenAI` pointed at the
  server's `base_url`, since all LLM steps talk to it through the
  OpenAI-compatible API.
- Assumes `llama-server` is already on `PATH` (handled by cluster module/env
  setup outside this repo) — `LlamaServerConfig.binary` can override this if needed.

## Pipeline package (`automated_events_coding/pipeline/`)

Organized by pipeline **step** (matching the spec/diagram 1:1), not by
mechanism — `llm/` stays restricted to server/client code only; every step's
logic (whether it's an LLM call, the classifier, or a rule-based lookup) lives
here instead:

- `schemas.py` — shared Pydantic models for every step's input/output (`Event`,
  `PlaceNames`, `EventLead`, `InteractionExtraction`, `ActionID`/`InteractionID`,
  `EventRecord`, `DedupResult`, etc.), used both to build request payloads and
  to validate/parse LLM JSON responses via `Model.model_validate_json(...)`.
  Field shapes are cross-referenced against the codebook where the spec was
  ambiguous: `CountryBasinLookup.bcode` is the TFDD basin code (with `GRND`/
  `UNKN`/`GNRL` special values), `InteractionID.irmo_codes` is the codebook's
  per-entity IRMO role code (what the spec's "`dyad_code` per entity" turned
  out to mean), and `EventLead` splits the spec's single
  `issue_area_and_scale_of_impact`/`groundwater_infrastructure` strings into
  the codebook's actual typed fields (`issue_area`, `scale_of_impact`,
  `groundwater`, `infrastructure_involved`, plus `jbi_*`/`non_basin_entity_*`
  attributes the spec didn't mention at all). Still a first draft, not a final
  contract — remaining ambiguities (e.g. the Step 2.2 gating question above)
  are marked with inline `TODO`s. Reconcile these before treating the schemas
  as stable.
- `prompts.py` — one placeholder constant per LLM-governed step (currently
  empty strings) for the actual prompt text to be filled in.
- `step0_relevance.py` … `step6_dedup.py` — one module per step (2.1/2.2 live
  inside `step2_location.py`; 5.1/5.2 live inside `step5_identification.py`,
  since that's how they're grouped in the spec). LLM-governed step functions
  follow a consistent shape: build a chat message from the matching `prompts.py`
  constant, call `client.chat.completions.create`, parse the response into the
  matching `schemas.py` type. `step0_relevance.py` and the gazetteer lookups in
  `step2_location.py` are `NotImplementedError` stubs pending their backing
  classifier/data. `step6_dedup.py` is fully implemented: tiered exact-key
  matching (primary keys, then secondary keys, then ambiguous) per
  `docs/pr-data-pipeline-spec.md` — revisit if a fuzzy/similarity fallback
  turns out to be needed once real data quality is known.
- `orchestrator.py` — wires the step modules together into
  `process_article(...)`, following the spec's control flow. Runs the Step
  2/2.1/2.2 and Step 4 branches sequentially (the spec leaves open whether they
  could run in parallel — see its open questions). Has a `TODO` where
  `EventRecord` assembly (feeding Step 6) needs the schema ambiguities above
  resolved first.

## Pending inputs (not yet in repo)

- **Codebook**: `docs/SandboxEventsCodingProtocol_2026Update.pdf` — now in the
  repo (gitignored, see above).
- **Gazetteer**: country/basin and aquifer lookup data backing steps 2.1/2.2 —
  not yet added. The codebook references `Geospatial Reference List 2025.xlsx`
  (basin/country codes) and `Entity Code Reference List 2025.xlsx` (entity
  codes, backing Steps 5.1/5.2 too) — confirm whether these are the same
  gazetteer files already planned or additional ones to source.

Check for these before assuming they need to be built from scratch.
