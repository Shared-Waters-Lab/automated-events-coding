# PR Data Extraction Pipeline — Implementation Spec

Companion to `pr-data-pipeline.mmd`. Each step below maps to a node in that diagram.
Steps marked **(LLM)** are prompt-driven calls to a local LLM; steps marked
**(rule-based)** are deterministic lookups (no LLM call).

## Legend (from source whiteboard)
- `—` (dash/text) = plain text data
- Parallelogram/rounded box = LLM call with a prompt

Steps marked **(LLM)** are prompt-driven calls to a local LLM (served via
`llama-server` / llama.cpp, called through the OpenAI-compatible client).
Steps marked **(rule-based)** are deterministic lookups or key/similarity
matching (no model call). Steps marked **(classifier)** are calls to a
separately trained, non-LLM model.

---

## Step 0 · Relevance Check (classifier)
- **Input:** raw PR data (text)
- **Output:** `relevant: Y/N`, `meta: {...}`
- **Notes:** Handled by a fine-tuned BERT classifier (gold-standard labeled
  data available), not the LLM. Still feeds Step 1 alongside the raw text.
  Classifier is yet to be trained.

## Step 1 · Event Extraction (LLM)
- **Input:** PR data (text) + Step 0 metadata
- **Output:** `events: Event[]` — list of discrete events found in the text
- **Downstream:** loop "for each Event" over Steps 2 and 4

## Step 2 · Location Extraction (LLM)
- **Input:** single Event
- **Output:** `place_names: string[]`
- **Downstream:** feeds Steps 2.1 and 2.2

### Step 2.1 · Country / Basin Lookup (rule-based)
- **Input:** `place_names`
- **Output:** resolved country/basin identifiers
- **Condition:** runs unconditionally on place names from Step 2

### Step 2.2 · Aquifer Lookup (rule-based)
- **Input:** `place_names`
- **Output:** resolved aquifer identifier(s)
- **Condition:** **only runs if groundwater (GW) is mentioned = Y** — this flag should
  come from Step 2 or Step 0/1 output; confirm which step actually emits it during
  implementation, since the diagram doesn't pin down the exact source field.

## Step 3 · Event-lead Extraction (LLM)
- **Input:** Event + Step 2.1 + Step 2.2 outputs
- **Output:**
  - `multiday: bool`
  - `date: {day, month, year}`
  - `issue_area_and_scale_of_impact: string`
  - `groundwater_infrastructure: string`
- **Downstream:** feeds Step 6

## Step 4 · (Inter)action Extraction (LLM)
- **Input:** single Event (parallel branch off the same "for each Event" loop as Step 2)
- **Output:**
  - `interactions: Pair[]`
  - `actors: {a, b}`
  - `summary: string`
  - `type: "action" | "interaction"`
- **Downstream:** loop "for each actor/interaction" over Step 5

### Step 5.1 · Action ID (LLM)
- **Condition:** `type == "action"`
- **Input:** actor from Step 4
- **Output:** `entity_name: string`, `entity_code: string`

### Step 5.2 · Interaction ID (LLM)
- **Condition:** `type == "interaction"` (else branch)
- **Input:** actor pair from Step 4
- **Output:**
  - `entity_names: string[]`
  - `entity_codes: string[]`
  - `dyad_pairs: [string, string]` (2 entities)
  - `dyad_code: string` — per entity
  - `bar_scale: number` — for the interaction

## Step 6 · Event Deduplication (rule-based / similarity match)
- **Input:** Step 3 output + Step 5.1/5.2 output
- **Behavior:** looks up similar previously-collected events/facts and checks for
  duplicates before accepting a new record. Not an LLM call — a deterministic
  key-match (with fuzzy/similarity matching as a fallback, to be finalized once
  real data quality is known).
- **Matching tiers:**
  - **6.1 Primary keys:** `date`, `entity_list`, `bcode`
  - **6.2 Secondary-ary keys:** `dyad_pairs`, `issue_area`, `bar_scale`
- **Outcome:**
  - Duplicate found / ambiguous → flag for human review
  - No match → store as new event/fact

---

## Open implementation questions
- Confirm exact source of the "GW mentioned = Y" flag gating Step 2.2 (Step 1, 2, or 3 output?).
- Confirm whether Steps 2/2.1/2.2 must complete before Step 4 starts, or if they run
  fully in parallel (diagram shows both branching off the same per-event loop with no
  cross-dependency).
- Define the exact `Event`, `Pair`, and entity schemas as shared types before wiring
  the LLM prompts, since several steps pass structured objects downstream (e.g. Step 4
  actors feed directly into 5.1/5.2 conditionals).
- Step 6 dedup matching strategy (exact key match vs. fuzzy/similarity threshold) is
  TBD pending real example data and its quality.
