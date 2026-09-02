"""Render GitHub stats cards from cached files without contacting GitHub.

Run from the repository root:
    python scripts/render_github_stats_local.py

Optionally render one cached window:
    python scripts/render_github_stats_local.py 365
"""

import sys

from config import OWNER, OUTPUT_DIR, coding_days_csv_path, coding_days_json_path, github_stats_svg_path
from render_github_stats_card import build_svg, read_metadata, read_rows


def cached_windows() -> list[int]:
    available: list[int] = []
    for metadata_file in OUTPUT_DIR.glob("coding-days-*.json"):
        metadata = read_metadata(metadata_file)
        try:
            window_days = int(metadata.get("window_days"))
        except (TypeError, ValueError):
            continue
        if window_days > 0:
            available.append(window_days)
    return sorted(set(available))


def main() -> None:
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python scripts/render_github_stats_local.py [window_days]")

    try:
        requested_window = int(sys.argv[1]) if len(sys.argv) == 2 else None
    except ValueError:
        raise SystemExit("Usage: python scripts/render_github_stats_local.py [window_days]")

    available_windows = cached_windows()
    if not available_windows:
        raise SystemExit(f"No cached GitHub stats data found in {OUTPUT_DIR}")
    requested_windows = [requested_window] if requested_window is not None else available_windows
    invalid_windows = [window for window in requested_windows if window not in available_windows]
    if invalid_windows:
        available = ", ".join(map(str, available_windows))
        raise SystemExit(f"Window is not in the cached data. Available windows: {available}")

    for window_days in requested_windows:
        metadata = read_metadata(coding_days_json_path(window_days))
        output_file = github_stats_svg_path(window_days)
        output_file.write_text(
            build_svg(
                str(metadata.get("owner") or OWNER),
                read_rows(coding_days_csv_path(window_days)),
                metadata,
                window_days,
            ),
            encoding="utf-8",
        )
        print(f"Saved {output_file}")


if __name__ == "__main__":
    main()
