"""Render LOC charts from the cached JSON file without contacting GitHub.

Run from the repository root:
    python scripts/render_loc_analysis_local.py

Optionally render one cached window:
    python scripts/render_loc_analysis_local.py 365
"""

import json
import sys

from config import LOC_ANALYSIS_JSON, loc_analysis_svg_path
from render_loc_analysis import build_svg


def cached_windows(windows: dict) -> list[int]:
    available: list[int] = []
    for key, summary in windows.items():
        if not isinstance(summary, dict):
            continue
        try:
            window_days = int(key)
        except (TypeError, ValueError):
            continue
        if window_days > 0:
            available.append(window_days)
    return sorted(set(available))


def main() -> None:
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python scripts/render_loc_analysis_local.py [window_days]")

    try:
        requested_windows = [int(sys.argv[1])] if len(sys.argv) == 2 else None
    except ValueError:
        raise SystemExit("Usage: python scripts/render_loc_analysis_local.py [window_days]")
    if not LOC_ANALYSIS_JSON.exists():
        raise SystemExit(f"Cached data not found: {LOC_ANALYSIS_JSON}. Run the GitHub-backed generator once first.")

    try:
        payload = json.loads(LOC_ANALYSIS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid cached LOC data in {LOC_ANALYSIS_JSON}: {error}") from error

    owner = str(payload.get("owner", "Zerius7733"))
    windows = payload.get("windows")
    if not isinstance(windows, dict):
        raise SystemExit(f"Cached LOC data has no windows: {LOC_ANALYSIS_JSON}")
    available_windows = cached_windows(windows)
    if not available_windows:
        raise SystemExit(f"Cached LOC data has no usable windows: {LOC_ANALYSIS_JSON}")
    if requested_windows is None:
        requested_windows = available_windows
    invalid_windows = [window for window in requested_windows if window not in available_windows]
    if invalid_windows:
        available = ", ".join(map(str, available_windows))
        raise SystemExit(f"Window is not in the cached data. Available windows: {available}")

    for window_days in requested_windows:
        summary = windows.get(str(window_days))
        if not isinstance(summary, dict):
            raise SystemExit(f"Cached LOC data has no {window_days}-day summary: {LOC_ANALYSIS_JSON}")
        output_file = loc_analysis_svg_path(window_days)
        output_file.write_text(build_svg(summary, owner), encoding="utf-8")
        print(f"Saved {output_file}")


if __name__ == "__main__":
    main()
