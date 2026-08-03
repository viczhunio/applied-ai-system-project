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
except ModuleNotFoundError:
    from recommender import load_songs, recommend_songs
    from understand import parse_request_heuristic


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


def critique_results(preferences: dict, results: list, k_check: int = 5) -> dict:
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

    checks: dict = {}
    satisfied_count = 0

    # --- genre: requested genre present anywhere in the top slice --------------
    if requested_genre is not None:
        ok = requested_genre in genres
        satisfied_count += 1 if ok else 0
        checks["genre"] = {
            "requested": requested_genre,
            "satisfied": ok,
            "reason": (f"'{requested_genre}' found in top {n} results"
                       if ok else f"'{requested_genre}' not present in top {n} results"),
        }

    # --- mood: same idea -------------------------------------------------------
    if requested_mood is not None:
        ok = requested_mood in moods
        satisfied_count += 1 if ok else 0
        checks["mood"] = {
            "requested": requested_mood,
            "satisfied": ok,
            "reason": (f"'{requested_mood}' found in top {n} results"
                       if ok else f"'{requested_mood}' not present in top {n} results"),
        }

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


def run_agent(sentence: str, songs: list, k: int = 5) -> dict:
    """
    Understand -> Act pipeline (no critique/revise yet -- that's Phase 3/4).

    Steps:
        1. parse_request_heuristic(sentence) -> {"preferences", "matches"}
        2. recommend_songs(preferences, songs, k) using the EXISTING recommender
        3. bundle everything into one stable trace dict for later phases

    Returns:
        {
            "sentence":    <the original input string>,
            "preferences": {...},   # from parse_request_heuristic
            "matches":     {...},   # keyword trace from parse_request_heuristic
            "results":     [...],   # recommend_songs() output:
                                    #   list of (song_dict, score, explanation)
            "critique":    {...},   # Phase 3 self-check verdict over the results
        }

    Notes:
        * An empty "results" list is a LEGITIMATE outcome (empty catalog, or
          genuinely nothing to rank). run_agent returns normally in that case;
          Phase 3's critique step is where "no results" gets reacted to.
        * Exceptions from parse_request_heuristic() or recommend_songs() are
          intentionally NOT caught here -- if something upstream genuinely
          breaks, it should surface during testing rather than be papered over.
    """
    # 1. Understand: plain-English sentence -> sparse preferences (+ trace).
    parsed = parse_request_heuristic(sentence)
    preferences = parsed["preferences"]
    matches = parsed["matches"]

    # 2. Act: hand the preferences straight to the unmodified recommender.
    #    recommend_songs() already returns [] for an empty catalog, so the
    #    "no results" case needs no special handling -- it just flows through.
    results = recommend_songs(preferences, songs, k)

    # 3. Critique: score how well the results satisfy what was asked. This does
    #    NOT change or fix the results (that's Phase 4's revise step) -- a
    #    failing critique simply rides along in the trace so it's visible.
    critique = critique_results(preferences, results)

    # 4. Bundle the full pipeline state so far. Key names are kept simple and
    #    stable because later phases (revise/trace) read from this dict.
    return {
        "sentence": sentence,
        "preferences": preferences,
        "matches": matches,
        "results": results,
        "critique": critique,
    }


# ---------------------------------------------------------------------------
# Manual harness -- eyeball that returned songs make sense for each request.
# Run:  python src/agent.py   (or  python -m src.agent)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    songs = load_songs("data/songs.csv")
    print(f"Loaded songs: {len(songs)}\n")

    samples = [
        "I want some chill lo-fi beats to study to",   # reused from Phase 1 (expect pass)
        "hype rap for the gym",                        # reused from Phase 1 (expect pass)
        "romantic soul for a date night",              # new (expect pass)
        "slow pop",                                    # mismatch: pop is high-energy, so energy check fails -> fail
        "asdkfjh qwoeiru",                             # gibberish: nothing parsed -> fail
    ]

    for sentence in samples:
        trace = run_agent(sentence, songs, k=5)
        prefs = trace["preferences"]
        results = trace["results"]
        critique = trace["critique"]

        print("=" * 60)
        print(f"SENTENCE:    {sentence!r}")
        print(f"PREFERENCES: {prefs}")
        if results:
            top_song, top_score, _explanation = results[0]
            print(f"TOP RESULT:  {top_song['title']} - {top_song['artist']} "
                  f"({top_song['genre']} / {top_song['mood']})  score={top_score:.2f}")
        else:
            print("TOP RESULT:  (no results)")
        print(f"CRITIQUE:    verdict={critique['verdict']}  "
              f"confidence={critique['confidence']:.2f}")
        print(f"             {critique['summary']}")
    print("=" * 60)
