"""
Phase 5 structured logging for the Music Recommender Simulation.

"Nothing is a black box": every agent run is written out twice --
    * a concise one-line-per-step summary to the CONSOLE, and
    * a full, human-readable markdown entry APPENDED to ai_interactions.md
      (a required deliverable for the Agentic Workflow stretch feature).

log_trace() consumes the trace dict produced by run_agent() (Phases 2-4) and
never raises: a logging failure warns on stderr but must not crash the agent.
"""

import os
import sys
import json
from datetime import datetime

# Header written once, only when ai_interactions.md does not yet exist.
_LOG_HEADER = (
    "# AI Interactions Log\n"
    "_Agentic reasoning traces for the Music Recommender system._\n"
    "_Each entry records one full Understand → Act → Critique → Revise cycle._\n"
)


def _fmt_results(results: list, limit: int = 5) -> list:
    """Render recommend_songs() output as numbered markdown lines (top `limit`)."""
    lines = []
    for i, (song, score, _why) in enumerate(results[:limit], start=1):
        lines.append(
            f"{i}. {song['title']} — {song['artist']} "
            f"({song['genre']}/{song['mood']}) | score: {score:.2f}"
        )
    return lines or ["(no results)"]


def _top_label(results: list, sep: str = "—") -> str:
    """
    'Title <sep> Artist' for the #1 result, or a placeholder when empty.
    `sep` defaults to an em dash for the markdown file; the console passes a
    plain hyphen since Windows consoles (cp1252) can't render em dashes.
    """
    if not results:
        return "(no results)"
    song = results[0][0]
    return f"{song['title']} {sep} {song['artist']}"


def _build_markdown(trace: dict, timestamp: str) -> str:
    """Assemble the full markdown section for one run (does no I/O)."""
    preferences = trace["preferences"]
    matches = trace["matches"]
    results = trace["results"]
    critique = trace["critique"]

    lines = []
    lines.append("")
    lines.append("---")
    lines.append(f"## Run — {timestamp}")
    lines.append(f"**Input:** \"{trace['sentence']}\"")

    # --- Step 1: Understand ---------------------------------------------------
    lines.append("")
    lines.append("### Step 1 — Understand")
    lines.append(f"- Parsed genre: {preferences.get('genre')}")
    lines.append(f"- Parsed mood: {preferences.get('mood')}")
    energy = preferences["energy"] if "energy" in preferences else "not specified"
    lines.append(f"- Parsed energy: {energy}")
    if "acousticness" in preferences:
        lines.append(f"- Parsed acousticness: {preferences['acousticness']}")
    lines.append(f"- Matched on: {json.dumps(matches)}")

    # --- Step 2: Act ----------------------------------------------------------
    lines.append("")
    lines.append("### Step 2 — Act")
    lines.append(f"Top {min(5, len(results))} results:" if results else "Top results:")
    lines.extend(_fmt_results(results))

    # --- Step 3: Critique -----------------------------------------------------
    lines.append("")
    lines.append("### Step 3 — Critique")
    lines.append(f"- Verdict: {critique['verdict']}")
    lines.append(f"- Confidence: {critique['confidence']:.2f}")
    lines.append(f"- Summary: \"{critique['summary']}\"")

    # --- Step 4: Revise -------------------------------------------------------
    lines.append("")
    lines.append("### Step 4 — Revise")
    if trace.get("revised_preferences") is None:
        # No retry happened (critique passed, or nothing was actionable).
        lines.append(f"- Skipped ({trace.get('revision_note', 'no revision')})")
    else:
        revised_critique = trace["revised_critique"]
        revised_results = trace["revised_results"]
        # What changed:
        lines.append(f"- Changed: {trace['revision_note']}")
        lines.append(f"- Revised preferences: {trace['revised_preferences']}")
        # Revised results:
        lines.append(f"- Revised top {min(5, len(revised_results))} results:"
                     if revised_results else "- Revised results:")
        lines.extend("  " + ln for ln in _fmt_results(revised_results))
        # Revised critique verdict/confidence:
        lines.append(f"- Revised verdict: {revised_critique['verdict']} "
                     f"| Confidence: {revised_critique['confidence']:.2f}")
        # Did it help? Compare original vs revised.
        helped = (critique["verdict"] == "fail"
                  and revised_critique["verdict"] == "pass")
        lines.append(f"- Revision helped: {'yes' if helped else 'no'} "
                     f"({critique['verdict']} → {revised_critique['verdict']})")

    # --- Final Output ---------------------------------------------------------
    final_critique = trace["final_critique"]
    final_results = trace["final_results"]
    lines.append("")
    lines.append("### Final Output")
    lines.append(f"- Verdict: {final_critique['verdict']} "
                 f"| Confidence: {final_critique['confidence']:.2f}")
    lines.append(f"- Top result: {_top_label(final_results)}")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def _print_console(trace: dict) -> None:
    """Emit the short one-line-per-step summary to the console."""
    preferences = trace["preferences"]
    results = trace["results"]
    critique = trace["critique"]
    final_critique = trace["final_critique"]
    final_results = trace["final_results"]

    # [UNDERSTAND]
    parts = [f"genre={preferences.get('genre')}", f"mood={preferences.get('mood')}"]
    if "energy" in preferences:
        parts.append(f"energy={preferences['energy']}")
    if "acousticness" in preferences:
        parts.append(f"acousticness={preferences['acousticness']}")
    print(f"[UNDERSTAND] {' '.join(parts)}")

    # [ACT]
    if results:
        top_song, top_score, _ = results[0]
        print(f"[ACT]        {len(results)} results returned, "
              f"top: {top_song['title']} (score {top_score:.2f})")
    else:
        print("[ACT]        0 results returned")

    # [CRITIQUE] -- ASCII-only console line (file keeps unicode)
    print(f"[CRITIQUE]   {critique['verdict']} "
          f"(confidence {critique['confidence']:.2f}) - {critique['summary']}")

    # [REVISE]
    if trace.get("revised_preferences") is None:
        print("[REVISE]     skipped")
    else:
        revised_critique = trace["revised_critique"]
        print(f"[REVISE]     {trace['revision_note']} "
              f"-> {revised_critique['verdict']} "
              f"(confidence {revised_critique['confidence']:.2f})")

    # [FINAL]
    print(f"[FINAL]      {final_critique['verdict']} - "
          f"serving top result: {_top_label(final_results, sep='-')}")


def log_trace(trace: dict, log_path: str = "ai_interactions.md") -> None:
    """
    Appends one agent run as a structured, human-readable markdown entry
    to ai_interactions.md. Also prints a concise summary to console.
    Never raises -- logging failure should warn but not crash the agent.
    """
    try:
        # 1. Console summary (short, one line per step).
        _print_console(trace)

        # 2. Append the full markdown entry, creating the file + header if new.
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = _build_markdown(trace, timestamp)

        file_exists = os.path.exists(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write(_LOG_HEADER)
            f.write(entry)
    except Exception as exc:  # never let logging break the agent
        print(f"[logger] WARNING: failed to write trace to {log_path!r}: {exc}",
              file=sys.stderr)
