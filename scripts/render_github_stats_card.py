import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from config import SUPPORTED_WINDOWS, coding_days_csv_path, coding_days_json_path, github_stats_svg_path


def read_rows(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        return []

    rows: list[tuple[str, int]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            day = (row.get("date") or "").strip()
            count_raw = (row.get("contribution_count") or "").strip()
            if not day:
                continue
            try:
                count = int(count_raw)
            except ValueError:
                count = 0
            rows.append((day, count))
    return rows


def read_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def daily_counts(rows: list[tuple[str, int]]) -> list[tuple[date, int]]:
    parsed: dict[date, int] = {}
    for day_text, count in rows:
        try:
            parsed[date.fromisoformat(day_text)] = count
        except ValueError:
            continue

    if not parsed:
        return []

    first_day = min(parsed)
    last_day = max(parsed)
    return [
        (day_value, parsed.get(day_value, 0))
        for day_offset in range((last_day - first_day).days + 1)
        for day_value in [first_day + timedelta(days=day_offset)]
    ]


def build_calendar(rows: list[tuple[str, int]]) -> tuple[list[list[tuple[date, int]]], int]:
    counts = dict(daily_counts(rows))
    if not counts:
        return [], 0

    first_day = min(counts)
    last_day = max(counts)
    start_day = first_day - timedelta(days=(first_day.weekday() + 1) % 7)
    end_day = last_day + timedelta(days=6 - ((last_day.weekday() + 1) % 7))
    week_count = ((end_day - start_day).days + 1) // 7

    weeks: list[list[tuple[date, int]]] = []
    for week_index in range(week_count):
        week: list[tuple[date, int]] = []
        for row_index in range(7):
            day_value = start_day + timedelta(days=week_index * 7 + row_index)
            week.append((day_value, counts.get(day_value, 0)))
        weeks.append(week)
    return weeks, max(counts.values(), default=0)


def color_for_count(count: int, maximum: int) -> str:
    if count <= 0:
        return "#21262D"
    ratio = count / maximum if maximum else 0
    if ratio <= 0.25:
        return "#0E4429"
    if ratio <= 0.5:
        return "#006D32"
    if ratio <= 0.75:
        return "#26A641"
    return "#39D353"


def calculate_metrics(rows: list[tuple[str, int]]) -> tuple[int, int, int, int, int, date | None]:
    days = daily_counts(rows)
    if not days:
        return 0, 0, 0, 0, 0, None

    active_days = sum(1 for _, count in days if count > 0)
    longest_streak = 0
    longest_gap = 0
    active_run = 0
    gap_run = 0
    for _, count in days:
        if count > 0:
            active_run += 1
            gap_run = 0
        else:
            gap_run += 1
            active_run = 0
        longest_streak = max(longest_streak, active_run)
        longest_gap = max(longest_gap, gap_run)

    total_contributions = sum(count for _, count in days)
    weekend_contributions = sum(count for day_value, count in days if day_value.weekday() >= 5)
    weekend_activity = round((weekend_contributions / total_contributions) * 100) if total_contributions else 0
    busiest_day, busiest_count = max(days, key=lambda item: (item[1], item[0]))
    return active_days, longest_streak, longest_gap, weekend_activity, busiest_count, busiest_day


def ring_lines(
    center_x: int,
    center_y: int,
    value: str,
    progress: float,
    color: str,
    label: str,
    foreground: str,
    muted: str,
    font_family: str,
    radius: int = 31,
) -> list[str]:
    circumference = 2 * math.pi * radius
    bounded_progress = max(0.0, min(1.0, progress))
    active_length = circumference * bounded_progress
    remaining_length = circumference - active_length
    return [
        f'<circle cx="{center_x}" cy="{center_y}" r="{radius}" fill="none" stroke="#30363D" stroke-width="9" />',
        f'<circle cx="{center_x}" cy="{center_y}" r="{radius}" fill="none" stroke="{color}" stroke-width="9" stroke-linecap="round" stroke-dasharray="{active_length:.2f} {remaining_length:.2f}" transform="rotate(-90 {center_x} {center_y})" />',
        f'<text x="{center_x}" y="{center_y + 7}" text-anchor="middle" fill="{foreground}" font-family="{font_family}" font-size="20" font-weight="700">{escape(value)}</text>',
        f'<text x="{center_x}" y="{center_y + 61}" text-anchor="middle" fill="{muted}" font-family="{font_family}" font-size="15">{escape(label)}</text>',
    ]


def build_svg(owner: str, rows: list[tuple[str, int]], metadata: dict, window_days: int) -> str:
    total_contributions = sum(count for _, count in rows)
    active_days, longest_streak, longest_gap, weekend_activity, busiest_count, busiest_date = calculate_metrics(rows)
    generated_at = str(metadata.get("generated_at_sgt", "")).replace("T", " ").replace("+08:00", " SGT")
    if not generated_at:
        generated_at = "latest generated data"

    weeks, maximum = build_calendar(rows)
    period_label = "last year" if window_days == 365 else f"last {window_days} days"
    width = 1200
    height = 400
    foreground = "#F0F6FC"
    muted = "#8B949E"
    panel = "#161B22"
    panel_border = "#30363D"
    green = "#2EA043"
    font_family = "Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif"

    calendar_x = 40
    calendar_y = 55
    calendar_w = 920
    calendar_h = 185
    grid_y = 115
    cell_size = 13
    gap = 3
    calendar_grid_width = len(weeks) * (cell_size + gap) - gap if weeks else 0
    grid_x = calendar_x+10 + (calendar_w - calendar_grid_width) / 2 if calendar_grid_width else calendar_x + 52
    footer_y = height - 12

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="GitHub contribution calendar for {escape(owner)} for the {period_label}">',
        f'<rect width="{width}" height="{height}" rx="8" fill="#0D1117" />',
        f'<text x="40" y="32" fill="{foreground}" font-family="{font_family}" font-size="26">Contribution Calendar</text>',
        f'<text x="1160" y="32" text-anchor="end" fill="{muted}" font-family="{font_family}" font-size="15">{escape(period_label.title())}</text>',
        f'<rect x="{calendar_x}" y="{calendar_y}" width="{calendar_w}" height="{calendar_h}" rx="6" fill="{panel}" stroke="{panel_border}" stroke-width="1" />',
        f'<rect x="980" y="{calendar_y}" width="180" height="{calendar_h}" rx="6" fill="{panel}" stroke="{panel_border}" stroke-width="1" />',
        f'<text x="58" y="80" fill="{muted}" font-family="{font_family}" font-size="15">{total_contributions:,} Contributions</text>',
    ]

    for row_index, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = grid_y + row_index * (cell_size + gap) + cell_size - 1
        lines.append(
            f'<text x="{grid_x - 10:.1f}" y="{y}" text-anchor="end" fill="{foreground}" font-family="{font_family}" font-size="13">{label}</text>'
        )

    previous_month = ""
    for week_index, week in enumerate(weeks):
        month_day = week[0][0] + timedelta(days=3)
        month_key = month_day.strftime("%Y-%m")
        if month_key == previous_month:
            continue
        previous_month = month_key
        x = grid_x + week_index * (cell_size + gap)
        lines.append(
            f'<text x="{x}" y="{grid_y - 13}" fill="{foreground}" font-family="{font_family}" font-size="13">{month_day.strftime("%b")}</text>'
        )

    if weeks:
        for week_index, week in enumerate(weeks):
            for row_index, (day_value, count) in enumerate(week):
                x = grid_x + week_index * (cell_size + gap)
                y = grid_y + row_index * (cell_size + gap)
                tooltip = f"{day_value.isoformat()}: {count} contributions"
                lines.append(
                    f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="2" fill="{color_for_count(count, maximum)}"><title>{escape(tooltip)}</title></rect>'
                )
    else:
        lines.append(
            f'<text x="{grid_x}" y="{grid_y + 44}" fill="{muted}" font-family="{font_family}" font-size="14">No contribution data available.</text>'
        )

    active_progress = active_days / max(1, len(daily_counts(rows)))
    lines.extend(
        [
            *ring_lines(1070, 132, str(active_days), active_progress, green, "Active Days", foreground, muted, font_family, radius=34),
        ]
    )

    card_y = 255
    card_w = 270
    card_h = 120
    content_left = 40
    content_right = 1160
    card_gap = (content_right - content_left - card_w * 4) / 3
    card_centers = [content_left + index * (card_w + card_gap) + card_w / 2 for index in range(4)]
    for index in range(4):
        card_x = content_left + index * (card_w + card_gap)
        lines.append(
            f'<rect x="{card_x:.1f}" y="{card_y}" width="{card_w}" height="{card_h}" rx="6" fill="{panel}" stroke="{panel_border}" stroke-width="1" />'
        )

    total_days = max(1, len(daily_counts(rows)))
    lines.extend(ring_lines(card_centers[0], 296, str(longest_streak), longest_streak / total_days, green, "Longest Streak", foreground, muted, font_family))
    lines.extend(ring_lines(card_centers[1], 296, str(longest_gap), longest_gap / total_days, "#F85149", "Longest Gap", foreground, muted, font_family))
    lines.extend(ring_lines(card_centers[2], 296, f"{weekend_activity}%", weekend_activity / 100, "#58A6FF", "Weekend Activity", foreground, muted, font_family))

    busiest_date_text = busiest_date.strftime("%m/%d/%Y") if busiest_date else "No data"
    lines.extend(
        [
            f'<text x="{card_centers[3]}" y="294" text-anchor="middle" fill="{green}" font-family="{font_family}" font-size="19" font-weight="700">{busiest_count} Contributions</text>',
            f'<text x="{card_centers[3]}" y="318" text-anchor="middle" fill="{foreground}" font-family="{font_family}" font-size="16" font-weight="600">on {busiest_date_text}</text>',
            f'<text x="{card_centers[3]}" y="357" text-anchor="middle" fill="{muted}" font-family="{font_family}" font-size="15">Busiest Day</text>',
            f'<text x="40" y="{footer_y}" fill="{muted}" font-family="{font_family}" font-size="11">Updated: {escape(generated_at)}</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    try:
        window_days = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    except ValueError:
        raise SystemExit(f"Window must be one of: {', '.join(map(str, SUPPORTED_WINDOWS))}")
    if window_days not in SUPPORTED_WINDOWS:
        raise SystemExit(f"Window must be one of: {', '.join(map(str, SUPPORTED_WINDOWS))}")

    input_csv = coding_days_csv_path(window_days)
    metadata_json = coding_days_json_path(window_days)
    output_svg = github_stats_svg_path(window_days)
    rows = read_rows(input_csv)
    metadata = read_metadata(metadata_json)
    owner = str(metadata.get("owner", "Zerius7733"))
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    output_svg.write_text(build_svg(owner, rows, metadata, window_days), encoding="utf-8")
    print(f"Saved {output_svg}")


if __name__ == "__main__":
    main()
