#!/usr/bin/env python3
"""Reads all session JSONs from session_states/ and embeds them into session_debugger.html."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "session_states"
HTML_FILE = Path(__file__).resolve().parent / "session_debugger.html"

MARKER_START = "const SESSIONS = ["
MARKER_END = "];\n\n// ── State ──"


def main():
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            if "session_id" in data:
                sessions.append(data)
        except (json.JSONDecodeError, KeyError):
            print(f"  skipping {f.name}")

    html = HTML_FILE.read_text()
    start = html.index(MARKER_START)
    end = html.index(MARKER_END) + len(MARKER_END)

    embedded = json.dumps(sessions, indent=2, ensure_ascii=False)
    new_block = f"const SESSIONS = {embedded};\n\n// ── State ──"

    HTML_FILE.write_text(html[:start] + new_block + html[end:])
    print(f"Embedded {len(sessions)} sessions into {HTML_FILE.name}")


if __name__ == "__main__":
    main()
