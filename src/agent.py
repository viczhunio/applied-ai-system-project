"""
Phase 2 agent pipeline for the Music Recommender Simulation.

Wires the "Understand" step (parse_request_heuristic) to the "Act" step
(recommend_songs) with nothing smarter in between -- no critique, no revise
(those are Phase 3/4). The existing recommender is used COMPLETELY UNMODIFIED;
this module only connects two pieces that already exist.

    sentence -> parse_request_heuristic -> preferences -> recommend_songs -> results
"""

# Support both `python src/agent.py` (src/ on the path) and
# `python -m src.agent` (run as a package from the repo root) -- same dual
# import pattern used by src/main.py.
try:
    from src.recommender import load_songs, recommend_songs
    from src.understand import parse_request_heuristic
    from src.logger import log_trace
except ModuleNotFoundError:
    from recommender import load_songs, recommend_songs
    from understand import parse_request_heuristic
    from logger import log_trace


# ---------------------------------------------------------------------------
# Phase 3: self-critique
# ---------------------------------------------------------------------------

# Tolerance for the numeric (energy / acousticness) checks: the average across
# the returned songs must land within this band of the requested value.
NUMERIC_TOLERANCE = 0.25

# Pass threshold on the confidence score. 0.6 means "strictly more than half of
# the preferences the listener actually expressed were satisfied":
#   - genre + mood only (2 set)      -> need both (1.0); 1/2 = 0.5 fails.
#   - genre + mood + energy (3 set)  -> 2/3 = 0.67 passes, 1/3 = 0.33 fails.
# i.e. a single satisfied field is never enough to call the run a success.
CONFIDENCE_THRESHOLD = 0.6


def critique_results(preferences: dict, results: list, k_check: int = 5,
                     strict_mode: bool = False) -> dict:
    """
    Checks the agent's own output against what was actually requested.
    Returns a verdict dict, does not modify results.

    Only preferences that were actually SET are evaluated: parse_request_heuristic
    omits energy/acousticness when no cue is found and leaves genre/mood as None
    when nothing matched, so an absent/None field is treated as "not requested"
    and never counted for or against the agent.

    Checks (all over the top `k_check` results, or fewer if results is shorter):
        genre / mood      -> requested value appears ANYWHERE in that top slice.
        energy / acoustic -> average of that feature is within NUMERIC_TOLERANCE
                             of the requested value.

    strict_mode (default False -> unchanged behavior): when True AND both genre
    and mood were requested, the genre and mood checks are satisfied only if a
    SINGLE song in the top slice matches BOTH (co-occurrence), instead of being
    satisfied independently by two different songs. When only one of genre/mood
    is set, strict_mode has no effect on it. run_agent does not use strict_mode
    yet; it exists for the Phase 6 test harness to exercise.

    confidence = (# set preferences satisfied) / (# set preferences).

    Special cases (never divide by zero, never crash on []):
        * results == []        -> verdict "fail", confidence 0.0.
        * no preferences set   -> verdict "fail", confidence 0.0.
    """
    # Which preferences did the listener actually express? genre/mood count only
    # when not None; energy/acousticness count only when present in the dict.
    requested_genre = preferences.get("genre")
    requested_mood = preferences.get("mood")
    has_energy = "energy" in preferences and preferences["energy"] is not None
    has_acoustic = "acousticness" in preferences and preferences["acousticness"] is not None
    num_set = (
        (1 if requested_genre is not None else 0)
        + (1 if requested_mood is not None else 0)
        + (1 if has_energy else 0)
        + (1 if has_acoustic else 0)
    )

    # 5. Empty results is a legitimate, explicit outcome -- bail out before any
    #    averaging so we never touch an empty list.
    if not results:
        return {
            "verdict": "fail",
            "confidence": 0.0,
            "checks": {},
            "summary": "no results returned to evaluate",
        }

    # 2 (special case). Nothing was parsed -> nothing to evaluate against.
    if num_set == 0:
        return {
            "verdict": "fail",
            "confidence": 0.0,
            "checks": {},
            "summary": "no preferences could be parsed from the request",
        }

    # Evaluate over the top slice (anywhere in it counts as satisfied).
    top = results[:k_check]
    n = len(top)
    genres = [song["genre"] for song, _score, _why in top]
    moods = [song["mood"] for song, _score, _why in top]

    # For strict_mode: does a SINGLE top-slice song match both requested fields?
    both_requested = requested_genre is not None and requested_mood is not None
    co_occurs = both_requested and any(
        song["genre"] == requested_genre and song["mood"] == requested_mood
        for song, _s, _w in top
    )
    use_strict = strict_mode and both_requested  # strict only bites when both set

    checks: dict = {}
    satisfied_count = 0

    # --- genre: present anywhere in top slice (or co-occurring in strict mode) --
    if requested_genre is not None:
        if use_strict:
            ok = co_occurs
            reason = (f"a top-{n} song is both '{requested_genre}' and "
                      f"'{requested_mood}'" if ok else
                      f"no single top-{n} song is both '{requested_genre}' and "
                      f"'{requested_mood}'")
        else:
            ok = requested_genre in genres
            reason = (f"'{requested_genre}' found in top {n} results" if ok else
                      f"'{requested_genre}' not present in top {n} results")
        satisfied_count += 1 if ok else 0
        checks["genre"] = {"requested": requested_genre, "satisfied": ok, "reason": reason}

    # --- mood: same idea (co-occurring with genre in strict mode) --------------
    if requested_mood is not None:
        if use_strict:
            ok = co_occurs
            reason = (f"a top-{n} song is both '{requested_genre}' and "
                      f"'{requested_mood}'" if ok else
                      f"no single top-{n} song is both '{requested_genre}' and "
                      f"'{requested_mood}'")
        else:
            ok = requested_mood in moods
            reason = (f"'{requested_mood}' found in top {n} results" if ok else
                      f"'{requested_mood}' not present in top {n} results")
        satisfied_count += 1 if ok else 0
        checks["mood"] = {"requested": requested_mood, "satisfied": ok, "reason": reason}

    # --- energy: average within tolerance of the requested value ---------------
    if has_energy:
        requested = preferences["energy"]
        actual_avg = sum(song["energy"] for song, _s, _w in top) / n
        ok = abs(actual_avg - requested) <= NUMERIC_TOLERANCE
        satisfied_count += 1 if ok else 0
        checks["energy"] = {
            "requested": requested,
            "actual_avg": round(actual_avg, 3),
            "satisfied": ok,
            "reason": (f"avg energy {actual_avg:.2f} within {NUMERIC_TOLERANCE} "
                       f"of requested {requested:.2f}" if ok else
                       f"avg energy {actual_avg:.2f} off from requested {requested:.2f} "
                       f"by more than {NUMERIC_TOLERANCE}"),
        }

    # --- acousticness: same tolerance-based check ------------------------------
    if has_acoustic:
        requested = preferences["acousticness"]
        actual_avg = sum(song["acousticness"] for song, _s, _w in top) / n
        ok = abs(actual_avg - requested) <= NUMERIC_TOLERANCE
        satisfied_count += 1 if ok else 0
        checks["acousticness"] = {
            "requested": requested,
            "actual_avg": round(actual_avg, 3),
            "satisfied": ok,
            "reason": (f"avg acousticness {actual_avg:.2f} within {NUMERIC_TOLERANCE} "
                       f"of requested {requested:.2f}" if ok else
                       f"avg acousticness {actual_avg:.2f} off from requested {requested:.2f} "
                       f"by more than {NUMERIC_TOLERANCE}"),
        }

    confidence = satisfied_count / num_set
    verdict = "pass" if confidence >= CONFIDENCE_THRESHOLD else "fail"
    summary = (f"{verdict.upper()}: {satisfied_count}/{num_set} requested "
               f"preferences satisfied (confidence {confidence:.2f})")

    return {
        "verdict": verdict,
        "confidence": confidence,
        "checks": checks,
        "summary": summary,
    }


def revise_preferences(preferences: dict, critique: dict, songs: list) -> dict:
    """
    Given a failed critique, make ONE bounded, sensible adjustment to
    preferences and return the revision decision. Never loops.

    Fixes are tried in priority order; the FIRST that applies wins:
        (a) energy check failed  -> nudge the energy target 30% toward the
            neutral middle 0.5 (e.g. 0.25 -> 0.325): more achievable without
            abandoning the original intent.
        (b) genre check failed   -> drop genre entirely so mood/energy drive the
            retry instead of staying stuck on an unrepresented genre.
        (c) mood check failed (and genre did NOT fail) -> drop mood.
        (d) nothing actionable   -> skip; retrying identical preferences would
            just reproduce the same result.

    We never drop BOTH genre and mood in one pass: if both fail we drop genre
    (b) and merely note that mood is left for a hypothetical second retry that
    is deliberately not performed.

    Returns:
        {
            "preferences": <prefs dict to retry with (or a copy of the original)>,
            "applied":     <bool>,   # False => caller must NOT retry (no-op)
            "action":      <str>,    # energy_relaxed | genre_dropped |
                                     #   mood_dropped | skipped
            "note":        <str>,    # human-readable log line for the trace
        }

    `songs` is accepted for a stable signature and possible future
    library-aware revisions; the current bounded fixes don't inspect it.
    """
    checks = critique.get("checks", {})

    def failed(name: str) -> bool:
        return name in checks and not checks[name]["satisfied"]

    energy_failed = failed("energy")
    genre_failed = failed("genre")
    mood_failed = failed("mood")

    # (a) Energy mismatch -- move the target 30% of the way toward 0.5.
    if energy_failed:
        original = preferences["energy"]
        relaxed = round(original + 0.3 * (0.5 - original), 3)
        revised = dict(preferences)
        revised["energy"] = relaxed
        return {
            "preferences": revised,
            "applied": True,
            "action": "energy_relaxed",
            "note": f"energy target relaxed from {original:.2f} toward 0.5 -> {relaxed:.3f}",
        }

    # (b) Genre not represented -- drop it so mood/energy can drive the retry.
    if genre_failed:
        revised = dict(preferences)
        revised.pop("genre", None)
        note = "genre dropped (requested genre not present in results)"
        if mood_failed:
            note += ("; mood also failing, left for a hypothetical second retry "
                     "(not performed)")
        return {
            "preferences": revised,
            "applied": True,
            "action": "genre_dropped",
            "note": note,
        }

    # (c) Mood not represented while genre is fine -- drop mood.
    if mood_failed and not genre_failed:
        revised = dict(preferences)
        revised.pop("mood", None)
        return {
            "preferences": revised,
            "applied": True,
            "action": "mood_dropped",
            "note": "mood dropped (requested mood not present in results)",
        }

    # (d) Nothing actionable (e.g. gibberish parsed to nothing, or only an
    #     unrevisable check failed) -- retrying would reproduce the same result.
    num_set = sum(
        1 for key in ("genre", "mood", "energy", "acousticness")
        if preferences.get(key) is not None
    )
    note = ("revision skipped: no preferences to adjust" if num_set == 0
            else "revision skipped: no applicable adjustment for the failing check(s)")
    return {
        "preferences": dict(preferences),
        "applied": False,
        "action": "skipped",
        "note": note,
    }


def run_agent(sentence: str, songs: list, k: int = 5,
              log_path: str = "ai_interactions.md") -> dict:
    """
    Understand -> Act -> Critique -> (one bounded) Revise pipeline.

    log_path is forwarded to log_trace(); pass log_path=None to suppress all
    logging (used by the test suite and the evaluation harness so they don't
    write to the real ai_interactions.md).

    Steps:
        1. parse_request_heuristic(sentence) -> {"preferences", "matches"}
        2. recommend_songs(preferences, songs, k) using the EXISTING recommender
        3. critique_results() scores how well results satisfy the request
        4. if the critique FAILS, revise_preferences() makes ONE adjustment,
           recommend_songs() is re-run, and the new results are re-critiqued.
           This is the ONLY retry -- there is no loop.

    Returns a stable trace dict:
        {
            "sentence":             ...,
            "preferences":          {...},   # original parsed preferences
            "matches":              {...},   # keyword trace from understand step
            "results":              [...],   # original results
            "critique":             {...},   # original critique
            "revised_preferences":  {...} | None,  # what changed (None if no revision)
            "revised_results":      [...] | None,  # results after revision
            "revised_critique":     {...} | None,  # critique of revised results
            "final_results":        [...],   # results to surface (revised if revised, else original)
            "final_critique":       {...},   # the critique that applies to final_results
            "revision_note":        "...",   # human-readable log of the revise decision
        }

    Honesty: if the single retry still fails, final_results is the revised
    (best-effort) results but final_critique still reports "fail" -- with a
    summary that says the results are best-effort, never a fake pass.

    Exceptions from parse_request_heuristic() or recommend_songs() are
    intentionally NOT caught -- upstream breakage should surface in testing.
    """
    # 1. Understand.
    parsed = parse_request_heuristic(sentence)
    preferences = parsed["preferences"]
    matches = parsed["matches"]

    # Defensive clamp (Module 3 out-of-range energy bug): parse_request_heuristic
    # should only ever emit energy in [0.0, 1.0], but recommend_songs()/score_song()
    # compare energy RAW and do not validate its range, so a stray out-of-range
    # value would distort scoring (and can push scores negative). We clamp here in
    # the agent layer rather than modifying the frozen recommender.
    if "energy" in preferences:
        preferences["energy"] = max(0.0, min(1.0, preferences["energy"]))

    # 2. Act.
    results = recommend_songs(preferences, songs, k)

    # 3. Critique.
    critique = critique_results(preferences, results)

    # Defaults assume no revision (critique passed, or nothing to revise).
    revised_preferences = None
    revised_results = None
    revised_critique = None
    final_results = results
    final_critique = critique
    revision_note = "no revision needed (critique passed)"

    # 4. Revise -- only on failure, and only once.
    if critique["verdict"] == "fail":
        revision = revise_preferences(preferences, critique, songs)
        revision_note = revision["note"]

        if revision["applied"]:
            revised_preferences = revision["preferences"]
            revised_results = recommend_songs(revised_preferences, songs, k)
            revised_critique = critique_results(revised_preferences, revised_results)
            # Surface the best-effort revised results either way...
            final_results = revised_results
            final_critique = revised_critique
            # ...but stay honest if the one retry still didn't satisfy the request.
            if revised_critique["verdict"] == "fail":
                still_failing = [
                    name for name, chk in revised_critique.get("checks", {}).items()
                    if not chk["satisfied"]
                ]
                fields = "/".join(still_failing) if still_failing else "preferences"
                revised_critique["summary"] = (
                    f"results are best-effort -- requested {fields} not well "
                    f"represented in library")
        # else: skipped -- final_* stay as the original results/critique.

    trace = {
        "sentence": sentence,
        "preferences": preferences,
        "matches": matches,
        "results": results,
        "critique": critique,
        "revised_preferences": revised_preferences,
        "revised_results": revised_results,
        "revised_critique": revised_critique,
        "final_results": final_results,
        "final_critique": final_critique,
        "revision_note": revision_note,
    }

    # 5. Log the full reasoning trace (console + ai_interactions.md). This never
    #    raises -- a logging failure warns but does not break the run.
    log_trace(trace, log_path)

    return trace


# ---------------------------------------------------------------------------
# Manual harness -- eyeball that returned songs make sense for each request.
# Run:  python src/agent.py   (or  python -m src.agent)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The markdown file we echo back at the end contains unicode (em dashes,
    # arrows); make stdout utf-8 so printing it can't crash on a cp1252 console.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    songs = load_songs("data/songs.csv")
    print(f"Loaded songs: {len(songs)}\n")

    # Same 4-5 sentences as Phase 4. run_agent() now prints the per-step console
    # summary and appends a full markdown entry to ai_interactions.md itself.
    samples = [
        "I want some chill lo-fi beats to study to",   # pass, no revision
        "hype rap for the gym",                        # pass, no revision
        "romantic soul for a date night",              # pass, no revision
        "slow pop",                                    # FAILS -> energy revision fires (Step 4 populated)
        "asdkfjh qwoeiru",                             # gibberish -> revision skipped
    ]

    for sentence in samples:
        print("=" * 60)
        print(f"RUN: {sentence!r}")
        run_agent(sentence, songs, k=5)  # console summary + ai_interactions.md logging happen inside
    print("=" * 60)

    # ------------------------------------------------------------------
    # Interactive CLI (runs AFTER the reproducible harness demo above).
    # Logging is suppressed (log_path=None) so live sessions don't flood
    # the ai_interactions.md deliverable.
    # ------------------------------------------------------------------
    print("\n" + "=" * 48)
    print("🎵 AmbiVibe — Ask for music in plain English")
    print('Type a request like: "chill lofi to study to"')
    print("Type 'quit' or press Ctrl+C to exit.")
    print("=" * 48)

    try:
        while True:
            sentence = input("You: ").strip()
            if sentence.lower() in ("quit", "exit"):
                print("Goodbye! 🎵")
                break
            if not sentence:
                continue

            trace = run_agent(sentence, songs, k=5, log_path=None)
            final_results = trace["final_results"]
            final_critique = trace["final_critique"]

            print("\nTop picks:")
            if final_results:
                for rank, (song, score, _why) in enumerate(final_results[:3], start=1):
                    print(f"  {rank}. {song['title']} — {song['artist']} "
                          f"({song['genre']}/{song['mood']}) | score: {score:.2f}")
            else:
                print("  (no results)")
            print(f"Verdict: {final_critique['verdict']} "
                  f"(confidence {final_critique['confidence']:.2f})\n")
    except KeyboardInterrupt:
        print("\nGoodbye! 🎵")
