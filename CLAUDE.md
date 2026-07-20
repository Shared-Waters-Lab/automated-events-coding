# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repository is in the pre-implementation / spec phase. There is no application
code yet — only planning docs under `docs/` and a `.gitignore` indicating the
implementation will be Python. There are no build, lint, or test commands yet
because no code or tooling has been added. Update this section (and add the
relevant commands) once a package layout, dependency manager, and test runner
are chosen.

## What this project is

A pipeline that extracts structured events from news articles about water/groundwater
conflict and cooperation, in the style of political event-coding schemes
(CAMEO/ICEWS-like: entity codes, dyad codes, a BAR intensity scale). The
authoritative design docs are:

- `docs/pr-data-pipeline-spec.md` — step-by-step implementation spec
- `docs/pr-data-pipeline.mmd` — Mermaid flowchart of the same pipeline (node
  colors encode which steps are LLM calls vs. classifier vs. rule-based)

Read both before making architectural changes — the spec doc explicitly calls
out unresolved implementation questions at its end; check whether they've been
resolved before assuming an answer.

## Pipeline architecture

The pipeline processes one article at a time through numbered steps. Each step maps
1:1 to a node in `docs/pr-data-pipeline.mmd`. Steps are deliberately split across
three different mechanisms — do not default to "just call the LLM" for a step that
belongs to one of the other two:

- **LLM-governed** (steps 1, 2, 3, 4, 5.1, 5.2) — prompt-driven calls to a local
  LLM served via `llama-server` (llama.cpp) on a university cluster node/port,
  invoked through the OpenAI-compatible client.
- **Classifier-governed** (step 0, relevance check) — a fine-tuned BERT classifier
  trained on existing gold-standard labeled data. Not an LLM call. Model is not
  yet trained.
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
     (rule-based, unconditional) and **2.2** aquifer lookup (rule-based, gated
     on a "GW mentioned" flag whose exact source step is still unconfirmed) →
     **Step 3** (LLM) event-lead extraction (date, multiday, issue area/scale,
     groundwater infrastructure).
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

## Pending inputs (not yet in repo)

- **Codebook**: entity codes, dyad codes, and BAR scale definitions — exists,
  will be added.
- **Gazetteer**: country/basin and aquifer lookup data backing steps 2.1/2.2 —
  exists, will be added.

Check for these before assuming they need to be built from scratch.
