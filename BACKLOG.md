# ScriptFalcon Backlog

Work logged for later sprints. **Do not start these until the item's sprint is reached.**

## Execution priority

1. **Now:** finish the remaining AI agents (Gap Falcon and the next agents in the suite).
2. **Next sprint (ScriptFalcon final polish):** SF-001 and SF-002 below.

---

## SF-001 — "Video Explanation / Short Description" input field

**Status:** Backlog (Phase 2 polish sprint) · **Source:** TL feedback, 2026-11-27

**What:** An optional textarea where the user briefly describes what the video is about, the core message, and format/style hints.

**Where in the UI:** Sidebar → *2. Topic*, directly below the *Conversion Objective* field.

**Example**

| Field | Value |
|---|---|
| Topic | SEO Myth Breaking Series Episode 1 |
| Short Description | Cover 3 common SEO myths in a punchy myth-vs-fact format, crisp short body lines, conversational tone. |

**Expected behaviour:** The description is passed into the research and script-generation prompts so the script's structure, tone and depth follow the user's format hints. It must not override the Topic Lock (the topic still decides the subject) or the rule that the conversion objective appears only in the CTA.

**Implementation notes**

- UI: [`frontend-react/src/components/Sidebar.jsx`](frontend-react/src/components/Sidebar.jsx) (`TopicSection`, after `objectiveInput`). Add the field to `INITIAL_FORM_BASE` and the request body in [`App.jsx`](frontend-react/src/App.jsx); clear it on **New** like the other per-script fields.
- API: add an optional `video_description` to `GenerateScriptRequest` in [`src/models.py`](src/models.py) with the same length/sanitising validation as other text fields (suggest max ~500 chars), and carry it on `ScriptInput`.
- Prompts: inject it into the research prompt ([`src/agents/research_agent.py`](src/agents/research_agent.py)) and the script prompt ([`src/agents/script_agent.py`](src/agents/script_agent.py)), labelled as *format and style guidance*, plus the quality audit so it checks the requested format was followed.
- Treat it as user data inside the prompt (clearly delimited), not as instructions that can change system rules.
- Include it in the dedup key and in saved deliverables / Markdown export.
- Tests: description reaches both prompts; an empty description changes nothing; a myth-vs-fact hint produces that structure (live check).

**Acceptance criteria**

- [ ] Optional field visible under Conversion Objective; empty by default; reset by **New**.
- [ ] Format hints are reflected in the generated script (e.g. myth-vs-fact pairs).
- [ ] Topic, language mode, word-count limits and CTA-only objective rules still hold.

---

## SF-002 — Tanglish / spoken-Tamil naturalness tuning

**Status:** Backlog (Phase 2 polish sprint) · **Source:** TL feedback, 2026-11-27

**Problem:** Some Tanglish lines sound awkward, overly literal or grammatically broken.

Example of broken phrasing:

> Unga site-la traffic irundhalum, conversion roadblocks irundha, alternate-ko solla vara enquiry-um varadhu

Issues in it: invented hybrid words (`alternate-ko`), clauses joined incoherently, and literal English-to-Tamil translation.

**Action**

- Update [`src/prompts.py`](src/prompts.py) (script writer + 7-criteria audit, criterion 4 *Unnatural Tamil*) to require natural, colloquial spoken Tamil/Tanglish and reject:
  - unnatural hybrid words (English word + random Tamil suffix, e.g. `alternate-ko`);
  - sentences joining 2+ conditional clauses that no speaker would say in one breath;
  - literal translations of English business phrases.
- Add few-shot pairs (awkward → natural) to the prompts, e.g. the example above rewritten as natural Tanglish.
- Extend the deterministic checks in [`src/agents/quality_agent.py`](src/agents/quality_agent.py) (next to `fix_tanglish_spelling_slips`) with a small list of known-bad hybrids to flag in criterion 4.
- Build a regression set of 20–30 real generated lines (good and bad) and review a fixed batch of topics across Tanglish, conversational spoken Tamil and Tamil before/after tuning.

**Acceptance criteria**

- [ ] The example sentence and similar hybrids are flagged and rewritten by the audit.
- [ ] Reviewer (native speaker) rates a fixed sample batch as natural; no regressions in word counts or language-mode rules.
- [ ] Existing tests keep passing; new tests cover the hybrid-word checks.
