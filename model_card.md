# 🎧 Model Card: AmbiVibe — Agentic Music Recommender

## 1. Model Name

**AmbiVibe** — Agentic Music Recommender System
*Project 4 extension of the Module 3 Music Recommender Simulation*

---

## 2. Intended Use

AmbiVibe is designed to accept a plain-English listener request ("I want something chill and acoustic for studying") and return a ranked list of song recommendations with a confidence score and honest verdict about whether the results actually matched what was asked. It is intended for classroom exploration and portfolio demonstration. The catalog is a curated 41-song dataset; this is not a production music service.

---

## 3. How the System Works

The system runs a four-step agentic loop around the original Module 3 content-based scoring engine, which is left completely unmodified:

1. **Understand** — `parse_request_heuristic()` in `src/understand.py` scans the sentence for genre words, mood words, and intensity cues using a keyword/synonym lookup table. No API calls, no ML model — pure pattern matching. It returns a sparse preferences dict (fields absent when no cue found) plus a keyword trace for logging.

2. **Act** — the unchanged `recommend_songs()` from Module 3 scores all 41 songs using: genre match (+2.0), mood match (+1.0), energy similarity (×1.5), and averaged numeric features (×0.5). Returns top-k with scores and explanations.

3. **Critique** — `critique_results()` in `src/agent.py` checks whether each set preference was actually satisfied in the results. Builds a confidence score (satisfied ÷ set preferences). Verdict is `pass` if confidence ≥ 0.6, `fail` otherwise.

4. **Revise** — if critique fails, `revise_preferences()` attempts one bounded fix in priority order: relax energy toward center, drop genre, drop mood, or skip if nothing was parsed. Re-runs the recommender and re-critiques. Never loops. Reports honestly if the retry still fails.

Every run is logged to `ai_interactions.md` as a full step-by-step markdown trace.

---

## 4. Data

The catalog is `data/songs.csv` — 41 songs, 13 genres, 10 moods.

**Audio feature sourcing:**
- **14 songs** have real, measured audio-feature values sourced from a pre-2024 Kaggle dataset snapshot that captured Spotify's audio-features API before it was deprecated in November 2024 (energy, valence, danceability, acousticness, instrumentalness, tempo, popularity all real). These include: Sunday Kind of Love, Work Song, Evergreen, Big Black Car, Fourth of July, Sweet Child O' Mine, November Rain, Smells Like Teen Spirit, September, Can't Stop, Under the Bridge, Don't Know Why, At Last, and Three Little Birds.
- **27 songs** use AI-estimated values based on each track's known genre, production style, tempo, and general sound character. These are reasonable approximations, not measured data. This is documented as a known limitation.

**Why estimated values exist:** Spotify's audio-features endpoint (energy, valence, danceability, etc.) was deprecated for new applications in November 2024 with no official replacement. Building this project in 2025-2026 means real per-track audio-feature data is no longer publicly accessible for a new application.

**Genre and mood labels:** All genre and mood values were assigned by the developer based on each song's known style. One data-quality issue was caught during development: a Kaggle dataset labeled several Latin pop songs (Bad Bunny, Manuel Turizo) under the `reggae` genre tag. These were rejected and replaced with genuinely reggae-tagged tracks (Bob Marley, UB40, Shaggy) after manual review — a concrete example of why retrieved data should be validated rather than trusted blindly.

---

## 5. Limitations and Biases

**Genre filter bubble (inherited from Module 3, unchanged):**
The +2.0 genre bonus dominates scoring. A song matching the listener's genre but mismatching mood and energy will almost always outrank a song from an adjacent genre that's a better overall fit. A listener asking for "chill indie pop" will rarely see a great chill folk or ambient song even if it's a closer match on every numeric feature. This is a documented design trade-off, not a bug — but it's a real limitation for discovery.

**Exact-string genre matching:**
`"indie pop"` does not match `"pop"`. Closely related subgenres are treated as completely different categories. This penalizes cross-genre similarity in a way that doesn't reflect how real listeners experience genre boundaries.

**Heuristic parser brittleness:**
`parse_request_heuristic()` is substring pattern matching, not language understanding. It can only recognize phrasing someone explicitly coded into the keyword table. "Something with a late-night feel" returns no genre or mood. "Vibes for a road trip" returns nothing useful. Any synonym or phrase not in the lookup table is invisible to the parser. This is the core reason a Gemini-powered understand step (Phase 9, optional) would improve the system — not because it's smarter about music, but because it actually reads for meaning rather than matching substrings.

**Three greedy-matching bugs found and fixed during development:**
During Phase 1 testing, three overly broad keyword rules were identified and corrected:
- `"house"` matched `"electronic"` on bare word — fired on "at my house tonight." Fixed to require "house music."
- `"down"` matched `"sad"` on bare word — fired on "calm down," overriding the "calm → relaxed" match because it appeared later in the sentence. Fixed to require specific phrases like "feeling down."
- `"heavy"` matched `"aggressive"` on bare word — fired on "feeling heavy after a long day." Fixed to require "heavy metal" or "heavy bass."

These are documented as regression tests in `tests/test_agent.py` and will permanently flag if the behavior regresses.

**Thin genre coverage:**
With 41 songs across 13 genres (~3 per genre), some genre requests return little variety. A listener asking for jazz will see at most 3 songs, and the ranking differences between them are small. This limits the practical value of the recommender for less-common genres.

**No personalization or listening history:**
The system knows only what the listener types in a single sentence. It has no memory across sessions, no listening history, no implicit feedback, no collaborative filtering. Two listeners typing the same sentence get identical results.

**Instrumentalness is misnamed:**
The `instrumentalness` feature measures the probability a track has *no vocals* (closer to 1.0 = likely purely instrumental). It does not measure production quality or instrumental richness. This is a known Spotify API naming quirk documented in the project for anyone reading the CSV.

---

## 6. Could This System Be Misused?

The system recommends songs from a fixed catalog — the misuse risk is low. A few honest notes:

- **Homogenization:** A production version of this system (if deployed at scale with a large catalog) could reinforce genre filter bubbles — showing listeners only what they already like rather than encouraging discovery. The +2.0 genre weight is the primary driver of this risk.
- **Data quality:** If the catalog were expanded without careful curation, mislabeled genre/mood values (like the reggae misclassification caught during development) could surface wrong results without any visible error.
- **Parser over-triggering:** In theory, a cleverly worded sentence could trigger multiple genre or mood keywords and produce a confusing result. The last-mention-wins contradiction rule is documented but not always intuitive.

None of these risks are severe for a classroom project. In a production context, human review of catalog data and confidence thresholds would be important guardrails.

---

## 7. Evaluation and Testing

### Automated tests
35 pytest tests across two files. 33 in `tests/test_agent.py` (new), 2 in `tests/test_recommender.py` (original, untouched).

### Evaluation harness
```
python scripts/evaluate.py
```
14 predefined cases. Results:
```
PASSED: 14/14   ACCURACY: 100.0%
Average agent confidence: 0.75 | Revision fired: 1/14 | Revision helped: 0/1
```

### What worked
- Genre, mood, and energy detection works reliably for direct, unambiguous sentences.
- The critique step correctly identifies when results don't match the request.
- The revision step correctly skips when there's nothing actionable (gibberish, out-of-vocab genre).
- Graceful degradation: a genre not in the vocabulary causes the system to fall back to mood/energy ranking without crashing.

### What didn't work / honest gaps
- "Slow pop" fails even after revision — the library genuinely lacks low-energy pop songs. The system reports this honestly rather than pretending to succeed.
- Revision helped 0 out of 1 times it fired across 14 test cases. This reflects reality: when a genre exists in the catalog but energy is mismatched, relaxing energy by 30% is often not enough to change the verdict.
- Ambiguous or creative phrasing ("late-night vibes," "road trip energy") produces no preferences — the heuristic parser simply has no rules for these.

### What surprised me during testing
The most surprising finding was how fast the three greedy-matching bugs emerged from a small set of natural test sentences. "I want to relax and calm down" and "just chilling at my house" are completely ordinary things a person would type, but they triggered wrong genre and mood classifications because the parser matched substrings without context. This showed the core limitation of heuristic parsing: the system isn't reading your sentence, it's scanning it for specific strings. Any word that appears in both a music context and an everyday context is a potential false positive.

---

## 8. AI Collaboration Reflection

### How I used AI during this project

I used Claude as a collaborator throughout the development of this project as a planning and code-review partner. The workflow was that I described what I wanted to build, Claude produced a structured plan and then detailed prompts, I sent those prompts to Claude Code (a separate agentic coding tool), Claude Code produced the implementation, and I reviewed the output and brought observations back to Claude for the next step.

Specific uses: planning the 9-phase build sequence, designing the `parse_request_heuristic()` output schema, writing the Phase 3-4 agent prompts, building the full songs.csv dataset, including looking up real audio-feature values from a Kaggle dataset and estimating values for songs not found.

### One instance where the AI suggestion was helpful

When building the song dataset, I asked about using the Spotify API to get real audio-feature values. Claude searched for current information and found that Spotify had deprecated its audio-features, recommendations, and audio-analysis endpoints in November 2024 which is something I didn't know. This was a genuine, time-saving catch: if I'd tried to build an API integration and only discovered the deprecation after setting up authentication, I would have lost significant time. The suggestion to use a pre-2024 Kaggle dataset snapshot instead was practical and directly applicable.

### One instance where the AI suggestion was flawed

During the dataset-building phase, Claude suggested using "La Bachata" by Manuel Turizo as a reggae song because the Kaggle dataset tagged it under the `reggae` genre. This was factually wrong, "La Bachata" is bachata, a Dominican genre with no connection to reggae. The Kaggle dataset's genre labels were apparently bucketing several Latin genres together under "reggae" based on superficial tempo or rhythm characteristics. I caught this because I knew the song and recognized the mismatch. This was a good reminder that retrieved data should be validated by someone with domain knowledge, not trusted because it came from a structured dataset. The fix was to manually search for actually-reggae artists (Bob Marley, UB40, Shaggy) and use their tracks instead.

### System limitations going forward

The biggest limitation is the heuristic parser's brittleness on natural, creative language — anything outside the keyword table is invisible. A production version of this system would need either a much larger synonym table (brittle, hard to maintain) or an LLM-powered understand step (reliable, but API-dependent). The optional Phase 9 Gemini integration was designed with this gap in mind: replace only the understand step, leave everything else unchanged, fall back to heuristic mode if the API is unavailable.

---

## 9. Future Work

- **Clamp energy input** fixed in Project 4: run_agent() now clamps energy to [0, 1] before passing to recommend_songs(), closing the negative-score bug identified during Module 3 adversarial testing
- **Soften genre matching** — allow partial credit for related genres (e.g. "indie pop" gets 50% of the genre bonus when the request is "pop") to reduce the filter bubble effect.
- **Expand the synonym table** — common phrases like "road trip," "late night," "workout," "morning coffee" could map to mood/energy presets, making the parser useful for more natural requests without requiring an LLM.
- **Gemini-powered understand step (Phase 9)** — swap in Gemini for `parse_request_heuristic()` with automatic fallback to heuristic mode when the API key is absent or the response is malformed. This would handle creative/ambiguous phrasing without changing anything else in the pipeline.
- **Multi-turn memory** — let the listener refine their request ("more upbeat," "not that one") rather than starting fresh each time.