"""Render commit-time timelines from the cached LOC commit records.

Run from the repository root:
    python scripts/render_commit_times.py

Optionally render one cached window:
    python scripts/render_commit_times.py 90
"""

import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from config import LOC_CACHE_JSON, OWNER, SGT, SUPPORTED_WINDOWS, commit_times_svg_path


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SGT)


def read_cached_records(path: Path, owner: str) -> list[dict]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict) or payload.get("owner") != owner:
        return []

    records: list[dict] = []
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return records

    for record in raw_records:
        if not isinstance(record, dict):
            continue
        committed_at = parse_timestamp(record.get("committed_at"))
        if committed_at is None:
            continue
        records.append(
            {
                "commit_id": str(record.get("commit_id") or ""),
                "committed_at": committed_at,
                "repository": str(record.get("repository") or "Unknown repository"),
            }
        )
    return records


def dot_y(commit_id: str, index: int, axis_y: float, spread: float = 31.0) -> float:
    seed = hashlib.sha256(f"{commit_id}:{index}".encode("utf-8")).digest()
    normalized = int.from_bytes(seed[:2], "big") / 65535
    return axis_y + (normalized * 2 - 1) * spread


def build_svg(owner: str, records: list[dict], window_days: int, now: datetime | None = None) -> str:
    now_sgt = (now or datetime.now(SGT)).astimezone(SGT)
    start_day = now_sgt.date() - timedelta(days=window_days - 1)
    commits = [
        record
        for record in records
        if isinstance(record.get("committed_at"), datetime)
        and start_day <= record["committed_at"].date() <= now_sgt.date()
    ]
    commits.sort(key=lambda record: (record["committed_at"], record.get("commit_id", "")))

    weekday_count = sum(1 for record in commits if record["committed_at"].weekday() < 5)
    weekend_count = len(commits) - weekday_count
    weekend_percent = round((weekend_count / len(commits)) * 100) if commits else 0
    hour_counts = Counter(record["committed_at"].hour for record in commits)
    peak_hour, peak_count = max(hour_counts.items(), key=lambda item: (item[1], -item[0])) if hour_counts else (None, 0)
    peak_label = f"{peak_hour:02d}:00–{(peak_hour + 1) % 24:02d}:00" if peak_hour is not None else "No data"

    width = 1200
    height = 300
    foreground = "#F0F6FC"
    muted = "#8B949E"
    panel = "#161B22"
    border = "#30363D"
    grid = "#21262D"
    weekday_color = "#39D353"
    weekend_color = "#58A6FF"
    font_family = "Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif"
    period_label = "Last Year" if window_days == 365 else f"Last {window_days} Days"

    panel_x = 20
    panel_y = 55
    panel_width = 1160
    panel_height = 195
    axis_left = 72
    axis_right = 1128
    axis_y = 157
    plot_top = 116
    plot_bottom = 190
    axis_width = axis_right - axis_left

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Commit time timeline for {escape(owner)} for the {escape(period_label)}">',
        '<defs><clipPath id="commit-time-plot"><rect x="72" y="116" width="1056" height="74" /></clipPath></defs>',
        f'<rect width="{width}" height="{height}" rx="8" fill="#0D1117" />',
        f'<text x="40" y="35" fill="{foreground}" font-family="{font_family}" font-size="27">Commit Times</text>',
        f'<text x="1160" y="35" text-anchor="end" fill="{muted}" font-family="{font_family}" font-size="15">{escape(period_label)}</text>',
        f'<rect x="{panel_x}" y="{panel_y}" width="{panel_width}" height="{panel_height}" rx="6" fill="{panel}" stroke="{border}" stroke-width="1" />',
        f'<text x="40" y="84" fill="{muted}" font-family="{font_family}" font-size="15">{len(commits):,} commits · Peak hour: {escape(peak_label)} ({peak_count:,}) · Weekend: {weekend_percent}%</text>',
        f'<text x="40" y="105" fill="{muted}" font-family="{font_family}" font-size="12">Each dot represents one commit · Times shown in Singapore Time (SGT)</text>',
    ]

    for hour in range(0, 25, 4):
        x = axis_left + axis_width * (hour / 24)
        lines.append(f'<line x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_bottom}" stroke="{grid}" stroke-width="1" />')
        anchor = "middle"
        if hour == 0:
            anchor = "start"
        elif hour == 24:
            anchor = "end"
        label = "24:00" if hour == 24 else f"{hour:02d}:00"
        lines.append(
            f'<text x="{x:.1f}" y="{plot_bottom + 22}" text-anchor="{anchor}" fill="{foreground}" font-family="{font_family}" font-size="13">{label}</text>'
        )

    lines.append(f'<line x1="{axis_left}" y1="{axis_y}" x2="{axis_right}" y2="{axis_y}" stroke="{muted}" stroke-width="1" />')
    lines.append('<g clip-path="url(#commit-time-plot)">')
    for index, record in enumerate(commits):
        committed_at = record["committed_at"]
        decimal_hour = committed_at.hour + committed_at.minute / 60 + committed_at.second / 3600
        x = axis_left + axis_width * (decimal_hour / 24)
        y = dot_y(str(record.get("commit_id", "")), index, axis_y)
        color = weekend_color if committed_at.weekday() >= 5 else weekday_color
        timestamp = committed_at.strftime("%Y-%m-%d %H:%M:%S SGT")
        tooltip = f"{timestamp} · {record.get('repository', 'Unknown repository')}"
        lines.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.2" fill="{color}" fill-opacity="0.82"><title>{escape(tooltip)}</title></circle>'
        )
    lines.append("</g>")

    legend_y = 238
    lines.extend(
        [
            f'<circle cx="42" cy="{legend_y - 4}" r="4" fill="{weekday_color}" />',
            f'<text x="54" y="{legend_y}" fill="{muted}" font-family="{font_family}" font-size="12">Weekday</text>',
            f'<circle cx="130" cy="{legend_y - 4}" r="4" fill="{weekend_color}" />',
            f'<text x="142" y="{legend_y}" fill="{muted}" font-family="{font_family}" font-size="12">Weekend</text>',
            f'<text x="1160" y="{legend_y}" text-anchor="end" fill="{muted}" font-family="{font_family}" font-size="12">Updated: {now_sgt.strftime("%Y-%m-%d %H:%M SGT")}</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def requested_windows() -> list[int]:
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python scripts/render_commit_times.py [90|180|365]")
    if len(sys.argv) == 1:
        return list(SUPPORTED_WINDOWS)
    try:
        window_days = int(sys.argv[1])
    except ValueError:
        raise SystemExit(f"Window must be one of: {', '.join(map(str, SUPPORTED_WINDOWS))}")
    if window_days not in SUPPORTED_WINDOWS:
        raise SystemExit(f"Window must be one of: {', '.join(map(str, SUPPORTED_WINDOWS))}")
    return [window_days]


def main() -> None:
    records = read_cached_records(LOC_CACHE_JSON, OWNER)
    if not records:
        raise SystemExit(
            f"No commit timestamps found in {LOC_CACHE_JSON}. Run scripts/generate_language_project_chart.py once to refresh the cache."
        )

    now_sgt = datetime.now(SGT)
    for window_days in requested_windows():
        output_file = commit_times_svg_path(window_days)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(build_svg(OWNER, records, window_days, now_sgt), encoding="utf-8")
        print(f"Saved {output_file}")


if __name__ == "__main__":
    main()
