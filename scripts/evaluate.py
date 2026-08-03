"""
Standalone evaluation harness for the Music Recommender agent (Phase 6).

Run directly:
    python scripts/evaluate.py

Runs a fixed battery of sentences through the full run_agent() pipeline and
prints a pass/fail summary table plus aggregate confidence/revision stats.
Exits 0 if every expected outcome matched, 1 otherwise (CI-friendly).

Logging is suppressed (log_path=None) so evaluation never writes to the real
ai_interactions.md deliverable.
"""

import os
import sys

# Make `src` importable no matter where the script is launched from.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Unicode check marks in the table; keep stdout from crashing on cp1252 consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.recommender import load_songs        # noqa: E402
from src.agent import run_agent                # noqa: E402

_CSV = os.path.join(_ROOT, "data", "songs.csv")


# Each case: sentence, expected_verdict ("pass"/"fail"/"any"),
#            expected_genre (None = don't check), expected_mood (None = don't check)
TEST_CASES = [
    # --- Clear matches (should pass) ---------------------------------------
    {"sentence": "chill lo-fi beats to study to", "verdict": "pass",
     "genre": "lofi", "mood": "chill"},
    {"sentence": "hype rap for the gym", "verdict": "pass",
     "genre": "hip-hop", "mood": "energetic"},
    {"sentence": "romantic soul for a date night", "verdict": "pass",
     "genre": "soul/r&b", "mood": "romantic"},
    {"sentence": "happy pop music", "verdict": "pass",
     "genre": "pop", "mood": "happy"},
    {"sentence": "aggressive metal to work out to", "verdict": "pass",
     "genre": "metal", "mood": "aggressive"},

    # --- Known hard cases (may fail -- honest/expected) --------------------
    {"sentence": "slow pop", "verdict": "fail",
     "genre": "pop", "mood": None},                      # pop is high-energy
    {"sentence": "aggressive jazz please", "verdict": "any",
     "genre": "jazz", "mood": "aggressive"},             # obscure combo

    # --- Adversarial inputs -------------------------------------------------
    {"sentence": "", "verdict": "fail", "genre": None, "mood": None},
    {"sentence": "asdkfjh qwoeiru", "verdict": "fail",
     "genre": None, "mood": None},
    {"sentence": "angry but relaxed", "verdict": "any",
     "genre": None, "mood": None},                       # contradiction

    # --- Regression sentences (the three greedy-keyword bug fixes) ----------
    {"sentence": "I want to relax and calm down after work", "verdict": "pass",
     "genre": None, "mood": "relaxed"},                  # not 'sad'
    {"sentence": "just chilling at my house tonight", "verdict": "pass",
     "genre": None, "mood": "chill"},                    # not 'electronic'
    {"sentence": "feeling heavy after a long day", "verdict": "fail",
     "genre": None, "mood": None},                       # 'heavy' no longer fires
    {"sentence": "heavy metal to lift weights", "verdict": "pass",
     "genre": "metal", "mood": None},                    # still detects metal
]


def _truncate(text, width):
    label = text if text else "(empty)"
    return label if len(label) <= width else label[:width - 3] + "..."


def main():
    songs = load_songs(_CSV)

    rows = []
    confidences = []
    revision_fired = 0
    revision_helped = 0

    for case in TEST_CASES:
        trace = run_agent(case["sentence"], songs, log_path=None)
        prefs = trace["preferences"]
        got_verdict = trace["final_critique"]["verdict"]

        # Match = verdict aligns (or "any") AND any specified genre/mood align.
        verdict_ok = case["verdict"] == "any" or got_verdict == case["verdict"]
        genre_ok = case["genre"] is None or prefs.get("genre") == case["genre"]
        mood_ok = case["mood"] is None or prefs.get("mood") == case["mood"]
        match = verdict_ok and genre_ok and mood_ok

        # Aggregate stats.
        confidences.append(trace["final_critique"]["confidence"])
        if trace["revised_preferences"] is not None:
            revision_fired += 1
            if (trace["critique"]["verdict"] == "fail"
                    and trace["revised_critique"]["verdict"] == "pass"):
                revision_helped += 1

        rows.append({
            "sentence": case["sentence"],
            "expected": case["verdict"],
            "got": got_verdict,
            "match": match,
            "verdict_ok": verdict_ok,
            "genre_ok": genre_ok,
            "mood_ok": mood_ok,
            "parsed_genre": prefs.get("genre"),
            "parsed_mood": prefs.get("mood"),
        })

    # ---- Print the table ---------------------------------------------------
    width = 60
    print("=" * width)
    print("MUSIC RECOMMENDER AGENT — EVALUATION REPORT")
    print("=" * width)
    print(f"{'#':>2}  {'Sentence':<33} {'Expected':<9} {'Got':<5} Match")
    print("-" * width)
    for i, row in enumerate(rows, start=1):
        mark = "✓" if row["match"] else "✗"
        print(f"{i:>2}  {_truncate(row['sentence'], 33):<33} "
              f"{row['expected']:<9} {row['got']:<5} {mark}")
    print("-" * width)

    passed = sum(1 for r in rows if r["match"])
    total = len(rows)
    accuracy = 100.0 * passed / total if total else 0.0
    print(f"PASSED: {passed}/{total}   FAILED: {total - passed}/{total}   "
          f"ACCURACY: {accuracy:.1f}%")
    print("=" * width)

    # ---- Detail any mismatches (why a row got ✗) ---------------------------
    mismatches = [r for r in rows if not r["match"]]
    if mismatches:
        print("Mismatches:")
        for r in mismatches:
            reasons = []
            if not r["verdict_ok"]:
                reasons.append(f"verdict {r['got']} != expected {r['expected']}")
            if not r["genre_ok"]:
                reasons.append(f"genre parsed {r['parsed_genre']!r}")
            if not r["mood_ok"]:
                reasons.append(f"mood parsed {r['parsed_mood']!r}")
            print(f"  - {r['sentence']!r}: {'; '.join(reasons)}")
        print("=" * width)

    # ---- Aggregate confidence / revision summary --------------------------
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    print(f"Average agent confidence: {avg_conf:.2f} | "
          f"Revision fired: {revision_fired}/{total} | "
          f"Revision helped: {revision_helped}/{revision_fired}")
    print("=" * width)

    # Exit 0 only if every expected outcome matched.
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
