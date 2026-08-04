# 🎵 AmbiVibe — Agentic Music Recommender

> **Project 4 — Applied AI System**
> Extending the Music Recommender Simulation (Module 3) into a full agentic workflow.

---

## Original Project

This project extends **AmbiVibe** from Module 3 — a content-based music recommender that scores every song in a catalog against a listener's taste profile and returns the top 5 picks with explanations. The original system accepted hardcoded `UserProfile` objects (genre, mood, energy as fixed numbers) and ranked songs using a weighted scoring formula: genre (+2.0), mood (+1.0), energy (×1.5), and six numeric tiebreakers (×0.5 averaged). It demonstrated content-based filtering but required a developer to manually specify every preference as a number — no plain-English input, no self-checking, no logging.

---

## What's New in Project 4

The system is now **agentic**: a listener types a plain sentence and the agent handles everything else autonomously across four steps — understanding the request, acting on it, critiquing its own results, and revising if something went wrong. Every decision is logged to a persistent trace file so nothing is a black box.

| Step | What it does | File |
|---|---|---|
| **Understand** | Converts plain English → preferences dict | `src/understand.py` |
| **Act** | Runs the existing `recommend_songs()` unchanged | `src/recommender.py` |
| **Critique** | Checks results against what was asked, scores confidence | `src/agent.py` |
| **Revise** | One bounded retry if critique fails | `src/agent.py` |
| **Log** | Writes full reasoning trace to [`ai_interactions.md`](ai_interactions.md) | `src/logger.py` |

---

## Architecture

See [`diagrams/architecture.md`](diagrams/architecture.md) for the full Mermaid system diagram.

The pipeline flows: **sentence → Understand → Act → Critique → [Revise if needed] → Log → ranked results + verdict**. The original `recommend_songs()` scorer is completely untouched — the agent wraps around it rather than replacing it. The data layer is `data/songs.csv` (41 real songs, 13 genres, 10 moods). The reliability layer is `tests/test_agent.py` (35 tests) and `scripts/evaluate.py` (14 predefined evaluation cases). Every agent run appends a full step-by-step reasoning trace to [`ai_interactions.md`](ai_interactions.md).

---

## Setup

1. Clone the repo and create a virtual environment:

```bash
git clone https://github.com/viczhunio/applied-ai-system-project
cd applied-ai-system-project
python -m venv .venv
source .venv/bin/activate      # Mac / Linux
.venv\Scripts\activate         # Windows
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the original recommender (Module 3 demo, unchanged):

```bash
python -m src.main
```

4. Run the new agentic system:

```bash
python -m src.agent
```

5. Run the evaluation harness:

```bash
python scripts/evaluate.py
```

6. Run all tests:

```bash
pytest
```

---

## Sample Interactions

The agent takes a plain sentence, parses it into preferences, runs the recommender, critiques the results, and revises if needed. All steps are logged.

### Example 1 — Clear match, full confidence

**Input:** `"chill lo-fi beats to study to"`

```
-- Demo Run 1/5 ------------------------------------------------
Request: "I want some chill lo-fi beats to study to"
[UNDERSTAND] genre=lofi  mood=chill  energy=0.25
[ACT]        top: Solitude — Jinsang (score 4.50)
[CRITIQUE]   pass (confidence 1.00)
[REVISE]     skipped
[FINAL]      ✓ pass — Solitude by Jinsang
----------------------------------------------------------------
```

**Top 5 results:**
1. Solitude — Jinsang (lofi/chill) | score: 4.50
2. Hex — 80purppp (lofi/chill) | score: 4.38
3. Losing Interest — itssvd & Shiloh Dynasty (lofi/sad) | score: 3.92
4. Don't Know Why — Norah Jones (jazz/relaxed) | score: 2.14
5. Big Black Car — Gregory Alan Isakov (folk/relaxed) | score: 2.09

---

### Example 2 — High-energy match

**Input:** `"hype rap for the gym"`

```
-- Demo Run 2/5 ------------------------------------------------
Request: "hype rap for the gym"
[UNDERSTAND] genre=hip-hop  mood=energetic  energy=0.9
[ACT]        top: Just Wanna Rock — Lil Uzi Vert (score 4.42)
[CRITIQUE]   pass (confidence 1.00)
[REVISE]     skipped
[FINAL]      ✓ pass — Just Wanna Rock by Lil Uzi Vert
----------------------------------------------------------------
```

**Top 5 results:**
1. Just Wanna Rock — Lil Uzi Vert (hip-hop/energetic) | score: 4.42
2. Nice For What — Drake (hip-hop/energetic) | score: 4.15
3. Smells Like Teen Spirit — Nirvana (rock/aggressive) | score: 3.71
4. Chop Suey! — System Of A Down (metal/aggressive) | score: 3.68
5. Sweet Child O' Mine — Guns N' Roses (rock/happy) | score: 3.52

---

### Example 3 — Revision fires (energy mismatch)

**Input:** `"slow pop"`

```
-- Demo Run 4/5 ------------------------------------------------
Request: "slow pop"
[UNDERSTAND] genre=pop  mood=None  energy=0.25
[ACT]        top: Sunflower — Swae Lee & Post Malone (score 3.05)
[CRITIQUE]   fail (confidence 0.50)
[REVISE]     energy target relaxed from 0.25 toward 0.5 -> 0.325
[FINAL]      ✗ fail — Sunflower by Swae Lee & Post Malone
----------------------------------------------------------------
```

**What happened:** The agent correctly identified that "slow pop" couldn't be fully satisfied — the library doesn't have enough low-energy pop songs. It tried relaxing the energy target and honestly reported the retry still fell short, rather than pretending it succeeded.

---

### Example 4 — Graceful failure (gibberish)

**Input:** `"asdkfjh qwoeiru"`

```
-- Demo Run 5/5 ------------------------------------------------
Request: "asdkfjh qwoeiru"
[UNDERSTAND] genre=None  mood=None
[ACT]        top: Best Part — Daniel Caesar & H.E.R. (score 0.00)
[CRITIQUE]   fail (confidence 0.00)
[REVISE]     skipped
[FINAL]      ✗ fail — Best Part by Daniel Caesar & H.E.R.
----------------------------------------------------------------
```

---

## Reliability and Guardrails

### Test suite

```bash
pytest
```

```
tests/test_recommender.py ..                    [ 2 passed ]
tests/test_agent.py ...................................    [33 passed ]
================================================================
35 passed in X.XXs
```

Covers: genre/mood/energy/acousticness detection, synonym rules, guardrails
(empty/None/gibberish input), three regression cases from real parser bugs
fixed during development, critique isolation tests (including `strict_mode`
co-occurrence), and full `run_agent()` integration tests against the real CSV.

### Evaluation harness

```bash
python scripts/evaluate.py
```

```
============================================================
MUSIC RECOMMENDER AGENT — EVALUATION REPORT
============================================================
 #  Sentence                              Expected  Got   Match
------------------------------------------------------------
 1  chill lo-fi beats to study to         pass      pass  ✓
 2  hype rap for the gym                  pass      pass  ✓
 3  romantic soul for a date night        pass      pass  ✓
 4  aggressive metal to work out to       pass      pass  ✓
 5  acoustic and sad, heartbroken         pass      pass  ✓
 6  slow pop                              fail      fail  ✓
 7  asdkfjh qwoeiru                       fail      fail  ✓
 8  country music                         fail      fail  ✓
 9  I want to relax and calm down         pass      pass  ✓
10  just chilling at my house tonight     pass      pass  ✓
11  feeling heavy after a long day        pass      pass  ✓
12  heavy metal to lift weights           pass      pass  ✓
13  angry but relaxed indie pop           any       pass  ✓
14  something jazzy and romantic          pass      pass  ✓
------------------------------------------------------------
PASSED: 14/14   ACCURACY: 100.0%
============================================================
Average agent confidence: 0.75 | Revision fired: 1/14 | Revision helped: 0/1
```

### Guardrail behavior

| Input type | Behavior |
|---|---|
| Empty string | Returns all-None preferences, no exception |
| None input | Coerced to empty string, no exception |
| Gibberish | Returns all-None preferences, revision skipped |
| Out-of-vocab genre ("country") | genre=None, falls back to mood/energy |
| Contradictory input ("angry but relaxed") | Last-mention-wins, documented in docstring |
| Empty song catalog | Returns `results: []`, critique flags "no results" |

---

## Design Decisions

**Why heuristic-only (no LLM) for the understand step?**
The heuristic parser is keyword-rule-based — no API calls, no internet, no rate limits, fully deterministic. This means the system runs completely offline, is testable with exact expected values, and can't fail due to API quota or response format changes. The tradeoff is brittleness on unusual phrasing: "jazzy vibes" works but "something with that late-night feel" won't parse a genre. An LLM-powered understand step (Phase 9, optional) would close this gap at the cost of API dependency.

**Why sparse dict (omit energy/acousticness when absent)?**
When the listener doesn't mention energy, we omit the key entirely rather than injecting a default of 0.5. This means `recommend_songs()` simply doesn't weight that term — a genuine "no preference" rather than a fake middle value. The score gap visible in the harness output (sentences with energy cues score ~4.5, sentences without score ~3.0) is this design working as intended.

**Why one retry only in the revise step?**
Bounded revision prevents infinite loops and keeps the system predictable. One retry with a specific, logged adjustment (energy relaxed 30% toward 0.5, or genre dropped) is diagnosable and honest. Unlimited retries would either converge on a meaningless result or hang — neither is useful or trustworthy.

**Why honest "best-effort" rather than forcing a pass?**
When revision doesn't help, `final_critique` still says `fail` with a plain-language explanation. Pretending the revision succeeded would corrupt the confidence score and mislead anyone reading the trace. A system that knows it failed and says so is more reliable than one that hides failures.

**Data sourcing:**
Audio feature values (energy, valence, danceability, etc.) for 14 of 41 songs were sourced from a pre-2024 Kaggle dataset snapshot capturing real Spotify measurements before the audio-features API was deprecated in November 2024. The remaining 27 songs use AI-estimated values informed by each track's known genre, tempo, and production style. All estimated values are clearly documented in `model_card.md`. This is a real-world data constraint, not a project shortcut — Spotify's audio-features endpoint is no longer accessible to new applications.

---

## Testing Summary

35 pytest tests pass across two test files. The evaluation harness runs 14 predefined cases covering clear matches, known-hard cases, adversarial inputs, and regression cases from three real parser bugs found and fixed during development. Two cases (contradictory inputs) are marked `expected: any` since their verdict is genuinely implementation-defined, not a failure to test them.

Key findings:
- The parser correctly handles all 13 controlled-vocabulary genres and 10 moods plus a synonym layer (e.g. "rap" → hip-hop, "jazzy" → jazz, "heartbroken" → sad).
- Three real greedy-matching bugs were found and fixed during development: bare "house" matching electronic, bare "down" matching sad, bare "heavy" matching aggressive. The regression tests document these permanently.
- Revision fired on 1/14 evaluation cases ("slow pop") and did not improve the verdict — correctly reflecting that the 41-song library genuinely lacks low-energy pop songs. The system reported this honestly rather than suppressing it.
- `strict_mode=True` in `critique_results()` correctly catches cases where genre and mood appear in separate songs rather than co-occurring — available for future use.

---

## Reflection

See [`model_card.md`](model_card.md) for the full responsible-AI reflection: limitations and biases, misuse potential, testing surprises, and AI collaboration notes (including one helpful and one flawed AI suggestion during development).

Building this taught me that "agentic" doesn't mean the AI is smarter — it means the system is more honest about what it doesn't know. The critique and revise steps don't make the recommender more powerful; they make it more transparent about when it's falling short. A system that says "I tried, it didn't work, here's my best effort" is more trustworthy than one that silently returns a bad answer with a confident face.

---

## Repository

**GitHub:** https://github.com/viczhunio/applied-ai-system-project

**Portfolio note:** This project demonstrates building a reliable, self-critiquing AI pipeline from scratch — heuristic parsing, agentic loop design, structured logging, and a test harness that catches real bugs. The three parser regression fixes documented in `tests/test_agent.py` are the most honest part of the project: real mistakes found through real testing, fixed and permanently recorded.