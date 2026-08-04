"""
Phase 6 pytest suite for the agentic pipeline.

Covers:
    * understand.py  -> parse_request_heuristic()
    * agent.py       -> critique_results()  (there is no separate critique.py;
                        the critique lives in agent.py)
    * agent.py       -> run_agent()  (integration, against the real CSV)

The existing tests/test_recommender.py is left untouched and must keep passing.
All run_agent() calls here pass log_path=None so the suite never writes to the
real ai_interactions.md deliverable.
"""

import os
import pytest

from src.understand import parse_request_heuristic
from src.agent import critique_results, run_agent
from src.recommender import load_songs

# Real catalog, resolved relative to this file so cwd doesn't matter.
_DATA = os.path.join(os.path.dirname(__file__), "..", "data", "songs.csv")


@pytest.fixture(scope="module")
def songs():
    """Load the real song catalog once for the integration tests."""
    return load_songs(_DATA)


def _prefs(sentence):
    """Convenience: just the preferences dict from the parser."""
    return parse_request_heuristic(sentence)["preferences"]


def _fake_result(genre, mood, energy=0.5, acousticness=0.5, score=1.0):
    """
    Minimal (song_dict, score, explanation) tuple for critique unit tests --
    only the fields critique_results() reads need to be present.
    """
    song = {
        "title": "T", "artist": "A",
        "genre": genre, "mood": mood,
        "energy": energy, "acousticness": acousticness,
    }
    return (song, score, "why")


# ===========================================================================
# 1. parse_request_heuristic() -- unit tests
# ===========================================================================

# --- 1a. Clear genre matches ------------------------------------------------
@pytest.mark.parametrize("sentence, expected_genre", [
    ("I want some hip-hop", "hip-hop"),
    ("play me some lofi", "lofi"),
    ("rap music", "hip-hop"),      # slang synonym
    ("lo-fi beats", "lofi"),       # hyphenated synonym
])
def test_genre_matches(sentence, expected_genre):
    assert _prefs(sentence)["genre"] == expected_genre


def test_genre_jazzy_synonym():
    # "jazzy" is now a jazz synonym in understand.py, so the adjective form
    # resolves to the jazz genre.
    assert _prefs("something jazzy")["genre"] == "jazz"


# --- 1b. Clear mood matches -------------------------------------------------
@pytest.mark.parametrize("sentence, expected_mood", [
    ("something happy", "happy"),
    ("feeling nostalgic", "nostalgic"),
    ("I'm heartbroken", "sad"),        # synonym
    ("hype me up", "energetic"),       # synonym
])
def test_mood_matches(sentence, expected_mood):
    assert _prefs(sentence)["mood"] == expected_mood


# --- 1c. Energy detection ---------------------------------------------------
def test_energy_low_cue():
    prefs = _prefs("chill and relaxed")
    assert "energy" in prefs and prefs["energy"] <= 0.35


def test_energy_high_cue():
    prefs = _prefs("intense workout music")
    assert "energy" in prefs and prefs["energy"] >= 0.80


def test_energy_absent_when_no_cue():
    # No intensity word -> energy must be omitted entirely (not a fake default).
    assert "energy" not in _prefs("something for background")


# --- 1d. Acousticness bonus -------------------------------------------------
def test_acousticness_high_cue():
    prefs = _prefs("acoustic guitar music")
    assert "acousticness" in prefs and prefs["acousticness"] >= 0.75


def test_acousticness_low_cue():
    prefs = _prefs("electronic beats")
    assert "acousticness" in prefs and prefs["acousticness"] <= 0.20


# --- 1e. Guardrails ---------------------------------------------------------
@pytest.mark.parametrize("bad_input", ["", None, "asdkfjh qwoeiru"])
def test_guardrails_no_crash_none_values(bad_input):
    prefs = parse_request_heuristic(bad_input)["preferences"]
    assert prefs["genre"] is None
    assert prefs["mood"] is None


def test_contradiction_returns_shape_without_crashing():
    # Contradiction behavior is implementation-defined (last-mention-wins); we
    # only assert it returns the right shape and doesn't raise.
    result = parse_request_heuristic("angry but relaxed")
    assert isinstance(result, dict)
    assert "preferences" in result and "matches" in result
    assert "genre" in result["preferences"] and "mood" in result["preferences"]


# --- 1f. Regression cases (the three greedy-keyword bugs we fixed) ----------
def test_regression_calm_down_not_sad():
    assert _prefs("I want to relax and calm down after work")["mood"] != "sad"


def test_regression_house_not_electronic():
    assert _prefs("just chilling at my house tonight")["genre"] != "electronic"


def test_regression_feeling_heavy_not_aggressive():
    assert _prefs("feeling heavy after a long day")["mood"] != "aggressive"


def test_regression_heavy_metal_is_metal_or_rock():
    assert _prefs("heavy metal to lift weights")["genre"] in ("metal", "rock")


# ===========================================================================
# 2. critique_results() -- unit tests (isolated, fake results)
# ===========================================================================

def test_critique_all_satisfied():
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.8}
    results = [_fake_result("pop", "happy", energy=0.8)]
    verdict = critique_results(prefs, results)
    assert verdict["verdict"] == "pass"
    assert verdict["confidence"] == 1.0


def test_critique_genre_missing_fails():
    prefs = {"genre": "jazz", "mood": "happy"}
    results = [_fake_result("pop", "happy")]  # no jazz anywhere
    verdict = critique_results(prefs, results)
    assert verdict["verdict"] == "fail"
    assert verdict["confidence"] < 1.0


def test_critique_energy_outside_tolerance_fails():
    prefs = {"genre": "pop", "energy": 0.2}
    results = [_fake_result("pop", "happy", energy=0.9)]  # avg 0.9 vs 0.2
    verdict = critique_results(prefs, results)
    assert verdict["verdict"] == "fail"


def test_critique_empty_results():
    verdict = critique_results({"genre": "pop"}, [])
    assert verdict["verdict"] == "fail"
    assert verdict["confidence"] == 0.0
    assert "no results" in verdict["summary"].lower()


def test_critique_no_preferences_set():
    verdict = critique_results({"genre": None, "mood": None},
                               [_fake_result("pop", "happy")])
    assert verdict["verdict"] == "fail"
    assert verdict["confidence"] == 0.0
    assert "no preferences" in verdict["summary"].lower()


def test_critique_strict_mode_requires_cooccurrence():
    # genre in song A, mood in song B, but no single song has both.
    prefs = {"genre": "pop", "mood": "happy"}
    results = [_fake_result("pop", "sad"), _fake_result("jazz", "happy")]

    lenient = critique_results(prefs, results, strict_mode=False)
    strict = critique_results(prefs, results, strict_mode=True)

    assert lenient["verdict"] == "pass"   # satisfied independently
    assert strict["verdict"] == "fail"    # not co-occurring in one song


# ===========================================================================
# 3. run_agent() -- integration tests (real CSV, logging suppressed)
# ===========================================================================

@pytest.mark.parametrize("sentence", [
    "chill lo-fi beats to study to",
    "hype rap for the gym",
    "romantic soul for a date night",
])
def test_run_agent_clear_requests_pass(songs, sentence):
    trace = run_agent(sentence, songs, log_path=None)
    assert trace["final_critique"]["verdict"] == "pass"


def test_run_agent_gibberish_fails_and_skips_revision(songs):
    trace = run_agent("asdkfjh qwoeiru", songs, log_path=None)
    assert trace["final_critique"]["verdict"] == "fail"
    assert trace["revised_preferences"] is None  # revision skipped


def test_run_agent_clamps_out_of_range_energy(songs, monkeypatch):
    # Force an out-of-range energy (2.0) into the pipeline by faking the parser.
    # The agent's defensive clamp should bound it to <= 1.0 so no result ends up
    # with a negative score (unclamped, energy 2.0 vs a 0.0-energy song yields a
    # -1.5 energy term that can drive the total below zero).
    import src.agent as agent_mod

    def fake_parse(sentence):
        return {
            "preferences": {"genre": "pop", "mood": "happy", "energy": 2.0},
            "matches": {
                "genre": {"value": "pop", "matched_on": []},
                "mood": {"value": "happy", "matched_on": []},
                "energy": {"value": 2.0, "matched_on": []},
                "acousticness": {"value": None, "matched_on": []},
            },
        }

    monkeypatch.setattr(agent_mod, "parse_request_heuristic", fake_parse)
    trace = agent_mod.run_agent("out of range energy", songs, log_path=None)

    assert trace["preferences"]["energy"] <= 1.0            # clamp applied
    for _song, score, _why in trace["results"]:             # no negative scores
        assert score >= 0.0


def test_run_agent_trace_shape(songs):
    trace = run_agent("anything at all", songs, log_path=None)
    expected_keys = {
        "sentence", "preferences", "matches", "results", "critique",
        "revised_preferences", "revised_results", "revised_critique",
        "final_results", "final_critique", "revision_note",
    }
    assert expected_keys.issubset(trace.keys())
