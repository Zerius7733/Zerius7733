import csv
import json
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
INPUT_CSV = REPO_ROOT / "img" / "coding-days-365d.csv"
META_JSON = REPO_ROOT / "img" / "coding-days-365d.json"
OUTPUT_SVG = REPO_ROOT / "img" / "github-stats.svg"


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


def build_calendar(rows: list[tuple[str, int]]) -> tuple[list[list[tuple[date, int]]], int]:
    counts: dict[date, int] = {}
    for day_text, count in rows:
        try:
            counts[date.fromisoformat(day_text)] = count
        except ValueError:
            continue

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
        return "#161B22"
    ratio = count / maximum if maximum else 0
    if ratio <= 0.25:
        return "#0E4429"
    if ratio <= 0.5:
        return "#006D32"
    if ratio <= 0.75:
        return "#26A641"
    return "#39D353"


def build_svg(owner: str, rows: list[tuple[str, int]], metadata: dict) -> str:
    total_contributions = sum(count for _, count in rows)
    generated_at = str(metadata.get("generated_at_sgt", "")).replace("T", " ").replace("+08:00", " SGT")
    if not generated_at:
        generated_at = "latest generated data"

    weeks, maximum = build_calendar(rows)

    width = 1200
    height = 292
    card_x = 0
    card_y = 42
    card_w = width
    card_h = height - card_y - 8
    card_bg = "#0D1117"
    border = "#30363D"
    foreground = "#F0F6FC"
    muted = "#8B949E"
    link = "#58A6FF"
    grid_x = 82
    grid_y = 80
    cell_size = 16
    gap = 4
    font_family = "Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif"
    footer_y = grid_y + 7 * (cell_size + gap) + 30

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="GitHub contributions for {escape(owner)} in the last year">',
        f'<text x="0" y="28" fill="{foreground}" font-family="{font_family}" font-size="25">{escape(f"{total_contributions:,} contributions in the last year")}</text>',
        f'<rect x="{card_x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="8" fill="{card_bg}" stroke="{border}" stroke-width="1" />',
        f'<text x="1035" y="27" fill="{muted}" font-family="{font_family}" font-size="15">Contribution settings</text>',
        f'<path d="M1174 20 l7 0 l-3.5 5 z" fill="{muted}" />',
    ]

    for row_index, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = grid_y + row_index * (cell_size + gap) + cell_size - 2
        lines.append(
            f'<text x="63" y="{y}" text-anchor="end" fill="{foreground}" font-family="{font_family}" font-size="15">{label}</text>'
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
            f'<text x="{x}" y="{grid_y - 12}" fill="{foreground}" font-family="{font_family}" font-size="15">{month_day.strftime("%b")}</text>'
        )

    if weeks:
        for week_index, week in enumerate(weeks):
            for row_index, (day_value, count) in enumerate(week):
                x = grid_x + week_index * (cell_size + gap)
                y = grid_y + row_index * (cell_size + gap)
                tooltip = f"{day_value.isoformat()}: {count} contributions"
                lines.append(
                    f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="3" fill="{color_for_count(count, maximum)}"><title>{escape(tooltip)}</title></rect>'
                )
    else:
        lines.append(
            f'<text x="{grid_x}" y="{grid_y + 50}" fill="{muted}" font-family="{font_family}" font-size="15">No contribution data available.</text>'
        )

    lines.extend(
        [
            f'<text x="{grid_x}" y="{footer_y}" fill="{link}" font-family="{font_family}" font-size="15">Learn how we count contributions</text>',
            f'<text x="930" y="{footer_y}" fill="{muted}" font-family="{font_family}" font-size="15">Less</text>',
            f'<text x="1135" y="{footer_y}" fill="{muted}" font-family="{font_family}" font-size="15">More</text>',
        ]
    )

    legend_x = 966
    legend_y = footer_y - 13
    legend_colors = ["#161B22", "#0E4429", "#006D32", "#26A641", "#39D353"]
    for index, color in enumerate(legend_colors):
        x = legend_x + index * (cell_size + 4)
        lines.append(
            f'<rect x="{x}" y="{legend_y}" width="{cell_size}" height="{cell_size}" rx="3" fill="{color}" />'
        )

    lines.extend(
        [
            f'<text x="0" y="{height - 4}" fill="{muted}" font-family="{font_family}" font-size="11">Updated: {escape(generated_at)}</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    rows = read_rows(INPUT_CSV)
    metadata = read_metadata(META_JSON)
    owner = str(metadata.get("owner", "Zerius7733"))
    OUTPUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_SVG.write_text(build_svg(owner, rows, metadata), encoding="utf-8")
    print(f"Saved {OUTPUT_SVG}")


if __name__ == "__main__":
    main()
