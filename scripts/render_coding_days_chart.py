import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SGT = ZoneInfo("Asia/Singapore")


def read_daily_counts(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        return []
    rows: list[tuple[str, int]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            day = (row.get("date") or "").strip()
            count_raw = (row.get("contribution_count") or row.get("commit_count") or "").strip()
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


def build_svg(owner: str, rows: list[tuple[str, int]], metadata: dict) -> str:
    total_days = int(metadata.get("window_days", len(rows) or 90))
    coded_days = int(metadata.get("coded_days", sum(1 for _, c in rows if c > 0)))
    percent = float(metadata.get("coded_days_percent", round((coded_days / total_days) * 100, 1) if total_days else 0))
    total_contributions = int(metadata.get("total_contributions", metadata.get("total_commits", sum(c for _, c in rows))))
    generated_at = metadata.get("generated_at_sgt") or datetime.now(SGT).isoformat()
    try:
        generated_dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).astimezone(SGT)
        generated_label = generated_dt.strftime("%Y-%m-%d %H:%M SGT")
    except ValueError:
        generated_label = str(generated_at).replace("T", " ").replace("+08:00", " SGT")

    width = 1200
    fg = "#C9D1D9"
    muted = "#8B949E"
    accent = "#2EA043"
    bar_bg = "#30363D"

    progress_w = 1080
    progress_h = 20
    progress_x = 0
    progress_y = 128
    fill_w = int((max(0.0, min(100.0, percent)) / 100.0) * progress_w)

    square_size = 10
    square_gap = 3
    columns = 30
    squares_x = 0
    squares_y = 176
    grid_rows = max(1, (min(len(rows), total_days) + columns - 1) // columns)
    grid_height = grid_rows * square_size + (grid_rows - 1) * square_gap
    footer_y = squares_y + grid_height + 24
    height = footer_y + 16

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Coding consistency last 90 days">',
        f'<text x="0" y="46" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="30" font-weight="700">Coding Consistency (Last {total_days} Days)</text>',
        f'<text x="0" y="76" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16">{escape(owner)} coded on {coded_days}/{total_days} days ({percent:.1f}%)</text>',
        f'<text x="0" y="102" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">Total contributions in window: {total_contributions}</text>',
        f'<rect x="{progress_x}" y="{progress_y}" width="{progress_w}" height="{progress_h}" rx="10" fill="{bar_bg}" />',
        f'<rect x="{progress_x}" y="{progress_y}" width="{fill_w}" height="{progress_h}" rx="10" fill="{accent}" />',
        f'<text x="{progress_x + progress_w + 12}" y="{progress_y + 15}" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">{percent:.1f}%</text>',
    ]

    # 90-day presence grid: green means at least one commit on that day.
    for i in range(min(len(rows), total_days)):
        _, count = rows[i]
        col = i % columns
        row = i // columns
        x = squares_x + col * (square_size + square_gap)
        y = squares_y + row * (square_size + square_gap)
        color = accent if count > 0 else bar_bg
        lines.append(f'<rect x="{x}" y="{y}" width="{square_size}" height="{square_size}" rx="2" fill="{color}" />')

    lines.append(
        f'<text x="0" y="{footer_y}" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12">Updated: {escape(generated_label)}</text>'
    )
    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    days = 90
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            raise SystemExit("Usage: python render_coding_days_chart.py [90|180|365]")

    input_csv = REPO_ROOT / "img" / f"coding-days-{days}d.csv"
    meta_json = REPO_ROOT / "img" / f"coding-days-{days}d.json"
    output_svg = REPO_ROOT / "img" / f"coding-days-{days}d.svg"

    rows = read_daily_counts(input_csv)
    metadata = read_metadata(meta_json)
    owner = metadata.get("owner", "Zerius7733")

    output_svg.parent.mkdir(parents=True, exist_ok=True)
    svg = build_svg(owner, rows, metadata)
    output_svg.write_text(svg, encoding="utf-8")
    print(f"Saved {output_svg}")


if __name__ == "__main__":
    main()
