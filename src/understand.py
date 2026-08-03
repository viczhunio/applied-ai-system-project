"""
Phase 1 heuristic request parser for the Music Recommender Simulation.

Turns a plain-English listener sentence (e.g. "I want some chill lo-fi to study
to") into a `preferences` dict that the existing `recommend_songs()` can consume
UNCHANGED, using nothing but keyword rules and the standard library -- no API
calls, no model, no new pip dependencies.

Design notes
------------
* The `preferences` dict is intentionally SPARSE:
    - `genre` and `mood` are ALWAYS present (possibly None) per the spec.
    - `energy` and `acousticness` are OMITTED entirely when no cue is found.
  This matches how `score_song()` reads user_prefs: an absent numeric key simply
  drops that term from the weighted score instead of injecting a fake 0.5
  default that would silently bias every ranking.

* Alongside `preferences` we return a parallel `matches` dict recording which
  keyword(s) fired each decision. Nothing consumes it yet; it is the hook a
  later critique / logging-trace phase will read, so it is built now.

* CONTRADICTIONS ("angry but relaxed", "chill workout") are resolved by
  LAST MENTION WINS: the keyword appearing latest in the sentence takes the
  field (a longer phrase breaks a tie at the same position). We deliberately do
  NOT average two opposing cues into a meaningless middle value. See `_resolve`.

* GENRE is resolved with the same last-mention rule, plus one special case for
  the ambiguous word "indie" (see `parse_request_heuristic`).

This module does not modify recommend_songs(), score_song(), load_songs(), the
Song/UserProfile dataclasses, or the CSV. Its only job is to produce a dict
compatible with `recommend_songs()`'s `user_prefs` argument.
"""

import re
from typing import Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Controlled vocabularies + synonym/slang tables
#
# Every surface phrase is lowercase; matching is done against a lowercased copy
# of the sentence. The OUTPUT values on the left are the exact, case-sensitive
# strings the recommender expects ("hip-hop", "soul/r&b", ...).
# ---------------------------------------------------------------------------

# 1. GENRE -- canonical genre -> phrases that imply it.
# Multi-word / more specific phrases (e.g. "indie pop", "chill beats") are safe
# to list next to shorter ones because `_drop_contained` prevents the shorter
# phrase inside a longer one from being counted twice.
GENRE_SYNONYMS: Dict[str, List[str]] = {
    "pop": ["pop"],
    "lofi": ["lofi", "lo-fi", "lo fi", "chill beats", "chilled beats", "study beats"],
    "rock": ["rock"],
    "ambient": ["ambient", "atmospheric"],
    "jazz": ["jazz", "jazzy"],
    "indie pop": ["indie pop", "indie-pop"],          # "indie" ALONE handled separately
    "hip-hop": ["hip-hop", "hip hop", "hiphop", "rap", "trap"],
    "soul/r&b": ["soul/r&b", "r&b", "rnb", "r and b", "soul", "rhythm and blues"],
    "electronic": ["electronic", "edm", "house music", "techno", "trance"],  # "house music", not bare "house"
    "folk": ["folk"],
    "funk": ["funk"],
    "metal": ["metal"],
    "reggae": ["reggae"],
}

# 2. MOOD -- canonical mood -> direct words + common synonyms.
MOOD_SYNONYMS: Dict[str, List[str]] = {
    "aggressive": ["aggressive", "angry", "heavy metal", "heavy bass", "heavy bass drop", "rage"],  # "heavy <context>", not bare "heavy"
    "chill": ["chill", "chilled", "chilling", "chillin"],
    "energetic": ["energetic", "hype", "pumped", "pumped up", "upbeat", "lively"],
    "happy": ["happy", "joyful", "cheerful", "feel good", "feel-good", "good vibes"],
    "intense": ["intense", "powerful"],
    "moody": ["moody", "melancholic", "melancholy", "brooding"],
    "nostalgic": ["nostalgic", "throwback", "throw back", "reminds me of",
                  "reminiscing", "memories"],
    "relaxed": ["relaxed", "relaxing", "calm", "mellow", "laid back",
                "laid-back", "soothing", "peaceful"],
    "romantic": ["romantic", "in love", "love song", "date night"],
    "sad": ["sad", "heartbroken", "heartbreak", "feeling down", "down about",
            "down in the dumps", "depressed", "blue", "lonely", "crying"],  # specific "down" phrases, not bare "down"
}

# 3. ENERGY -- representative 0-1 value -> intensity cue phrases.
# Low ~0.25 (chill), medium 0.5 (moderate), high ~0.90 (hype/workout).
ENERGY_CUES: Dict[float, List[str]] = {
    0.25: ["chill", "chilled", "relaxed", "relaxing", "calm", "mellow",
           "laid back", "laid-back", "sleepy", "slow"],
    0.50: ["medium energy", "moderate", "medium"],
    0.90: ["hype", "intense", "pumped", "pumped up", "workout", "gym",
           "energetic", "party", "banger"],
}

# 4. ACOUSTICNESS (optional) -- representative 0-1 value -> production cue phrases.
# High ~0.85 (acoustic/unplugged), low ~0.10 (electronic/produced).
ACOUSTIC_CUES: Dict[float, List[str]] = {
    0.85: ["acoustic", "acoustics", "unplugged", "stripped down", "stripped-down"],
    0.10: ["electronic", "synth", "synths", "produced", "autotune", "digital"],
}


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

# A "phrase" must sit on token boundaries so "pop" does not fire inside
# "popular" and "rock" does not fire inside "rocket". We use lookarounds rather
# than \b because several phrases contain non-word characters ("r&b", "lo-fi").
_BOUNDARY_BEFORE = r"(?<![a-z0-9])"
_BOUNDARY_AFTER = r"(?![a-z0-9])"

# One hit = (decision_value, surface_phrase, start_index, phrase_length).
Hit = Tuple[Union[str, float], str, int, int]


def _find_phrase_hits(text: str, phrase_map: Dict) -> List[Hit]:
    """
    Return every place a phrase from `phrase_map` occurs in `text` as a whole
    token/phrase (never as a substring of a larger word).

    `phrase_map` maps a decision value (a genre/mood string, or an energy/
    acousticness float) to the surface phrases that imply it.
    """
    hits: List[Hit] = []
    for value, phrases in phrase_map.items():
        for phrase in phrases:
            pattern = _BOUNDARY_BEFORE + re.escape(phrase) + _BOUNDARY_AFTER
            for match in re.finditer(pattern, text):
                hits.append((value, phrase, match.start(), len(phrase)))
    return hits


def _drop_contained(hits: List[Hit]) -> List[Hit]:
    """
    Remove any hit whose matched span sits entirely inside a longer hit's span.

    This is what lets "pop" inside "indie pop" (or "beats" inside "chill beats")
    be ignored, so the specific multi-word phrase wins instead of both firing.
    """
    kept: List[Hit] = []
    for value, phrase, start, length in hits:
        end = start + length
        contained = any(
            start >= o_start and end <= o_start + o_len and o_len > length
            for (_, _, o_start, o_len) in hits
            if not (o_start == start and o_len == length)
        )
        if not contained:
            kept.append((value, phrase, start, length))
    return kept


def _resolve(hits: List[Hit]) -> Tuple[Optional[Union[str, float]], List[str]]:
    """
    Collapse one category's hits to a single decision using LAST MENTION WINS.

    The hit whose keyword appears latest in the sentence takes the field; a
    longer phrase breaks a tie at the same start position. Returns
    (value, matched_on) or (None, []) when there are no hits. `matched_on` lists
    every surface phrase that pointed at the winning value, in sentence order.
    """
    hits = _drop_contained(hits)
    if not hits:
        return None, []

    # Latest start position wins; longer phrase breaks a same-position tie.
    winner_value = max(hits, key=lambda h: (h[2], h[3]))[0]

    matched_on: List[str] = []
    for _, phrase in sorted(
        [(h[2], h[1]) for h in hits if h[0] == winner_value]
    ):
        if phrase not in matched_on:  # de-dupe while preserving order
            matched_on.append(phrase)
    return winner_value, matched_on


def _has_word(text: str, word: str) -> bool:
    """True if `word` appears in `text` as a standalone token."""
    return re.search(_BOUNDARY_BEFORE + re.escape(word) + _BOUNDARY_AFTER, text) is not None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_request_heuristic(sentence: str) -> dict:
    """
    Rule-based parser: plain-English listener request -> preference dict.
    No API calls, no external dependencies beyond the standard library.

    Returns a dict with two keys:
        {
          "preferences": {...},   # ready to pass straight to recommend_songs()
          "matches":     {...},   # per-field trace of which keyword(s) fired
        }

    `preferences` always contains "genre" and "mood" (each a controlled-vocab
    string or None), and contains "energy"/"acousticness" ONLY when a cue was
    found (absent keys are intentionally left out so the scorer ignores them).

    Guardrails:
        * Any non-string input (including None) is treated as an empty string.
        * Empty / gibberish input yields genre=None, mood=None, no energy or
          acousticness, and an all-empty `matches` -- never an exception.
        * Contradictions resolve by last-mention-wins (see module docstring);
          we never average opposing cues.
    """
    # 0. Normalize. Treat any non-string (including None) as empty input so this
    #    function can never raise on bad input.
    if not isinstance(sentence, str):
        sentence = ""
    text = sentence.lower()

    # 1. GENRE -----------------------------------------------------------------
    genre, genre_matched = _resolve(_find_phrase_hits(text, GENRE_SYNONYMS))

    # Special "indie" rule: bare "indie" is ambiguous, so we do NOT guess
    # "indie pop" from it. Only promote when "indie" is accompanied by
    # pop-adjacent context (the word "pop" somewhere in the sentence).
    if genre != "indie pop" and _has_word(text, "indie") and _has_word(text, "pop"):
        genre = "indie pop"
        genre_matched = [kw for kw in ("indie", "pop")]

    # 2. MOOD ------------------------------------------------------------------
    mood, mood_matched = _resolve(_find_phrase_hits(text, MOOD_SYNONYMS))

    # 3. ENERGY (float, omitted when absent) -----------------------------------
    energy, energy_matched = _resolve(_find_phrase_hits(text, ENERGY_CUES))

    # 4. ACOUSTICNESS (optional float, omitted when absent) --------------------
    acousticness, acoustic_matched = _resolve(_find_phrase_hits(text, ACOUSTIC_CUES))

    # 5. Assemble the SPARSE preferences dict. genre/mood always present;
    #    energy/acousticness only when actually detected.
    preferences: Dict[str, Union[str, float, None]] = {
        "genre": genre,
        "mood": mood,
    }
    if energy is not None:
        preferences["energy"] = energy
    if acousticness is not None:
        preferences["acousticness"] = acousticness

    # 6. Transparency hook for later phases: what triggered each decision.
    matches = {
        "genre": {"value": genre, "matched_on": genre_matched},
        "mood": {"value": mood, "matched_on": mood_matched},
        "energy": {"value": energy, "matched_on": energy_matched},
        "acousticness": {"value": acousticness, "matched_on": acoustic_matched},
    }

    return {"preferences": preferences, "matches": matches}


# ---------------------------------------------------------------------------
# Manual sanity-check harness (NOT a test suite -- just eyeball the output).
# Run:  python src/understand.py   (or  python -m src.understand)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    samples = [
        "I want some chill lo-fi beats to study to",   # genre+mood+energy
        "Give me hype rap for the gym",                # slang genre + high energy
        "Something acoustic and sad, I'm heartbroken", # mood + acousticness, no genre
        "angry but relaxed indie pop",                 # contradiction: last mention wins
        "asdkfjh qwoeiru",                             # gibberish -> graceful empty
        "",                                            # empty -> graceful empty
        # Regression checks for the tightened greedy rules:
        "I want to relax and calm down after work",    # "calm down" -> NOT sad
        "just chilling at my house tonight",           # "house" -> NOT electronic
        "feeling heavy after a long day",              # "heavy" -> NOT aggressive
        "heavy metal to lift weights",                 # "heavy metal" -> STILL metal
    ]

    for s in samples:
        result = parse_request_heuristic(s)
        print("=" * 62)
        print(f"INPUT: {s!r}")
        print(json.dumps(result, indent=2))
    print("=" * 62)
