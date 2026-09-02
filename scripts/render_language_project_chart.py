import csv
import json
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from config import (
    LANGUAGE_PROJECT_CHART_SVG,
    LANGUAGE_PROJECT_COUNTS_CSV,
    LANGUAGE_PROJECT_COUNTS_JSON,
    SGT,
)


def read_counts(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        return []
    rows: list[tuple[str, int]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            language = (row.get("language") or "").strip()
            count_raw = (row.get("count") or "").strip()
            if not language:
                continue
            try:
                count = int(count_raw)
            except ValueError:
                continue
            rows.append((language, count))
    return rows


def read_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def build_svg(
    owner: str,
    counts: list[tuple[str, int]],
    generated_at: str,
    repository_scope: str,
) -> str:
    rows = sorted(counts, key=lambda item: (-item[1], item[0].lower()))
    max_count = max((count for _, count in rows), default=1)

    width = 1200
    chart_x = 150
    chart_w = 1000
    row_h = 44
    top_padding = 110
    bottom_padding = 54
    height = top_padding + (row_h * max(1, len(rows))) + bottom_padding

    fg = "#C9D1D9"
    muted = "#8B949E"
    bar = "#58A6FF"
    bar_bg = "#30363D"
    scope_label = (
        "Owner repos plus accessible repos with your commits"
        if repository_scope == "owner,collaborator,organization_member"
        else "Public repositories owned by the profile"
    )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Projects by detected languages chart">',
        f'<text x="0" y="54" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="28" font-weight="700">Projects by Detected Languages</text>',
        f'<text x="0" y="79" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">Each detected repo language counts once - {escape(owner)}</text>',
        f'<text x="0" y="98" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">{escape(scope_label)}</text>',
    ]

    if not rows:
        lines.append(
            f'<text x="0" y="{top_padding + 18}" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16">No language data found. Run fetch_language_counts.py first.</text>'
        )
    else:
        for idx, (language, count) in enumerate(rows):
            y = top_padding + idx * row_h
            bar_width = int((count / max_count) * chart_w)
            lines.extend(
                [
                    f'<text x="0" y="{y + 24}" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16">{escape(language)}</text>',
                    f'<rect x="{chart_x}" y="{y + 8}" width="{chart_w}" height="18" rx="9" fill="{bar_bg}" />',
                    f'<rect x="{chart_x}" y="{y + 8}" width="{bar_width}" height="18" rx="9" fill="{bar}" />',
                    f'<text x="{chart_x + chart_w + 12}" y="{y + 23}" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">{count}</text>',
                ]
            )

    lines.append(
        f'<text x="0" y="{height - 22}" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12">Updated: {escape(generated_at)}</text>'
    )
    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    counts = read_counts(LANGUAGE_PROJECT_COUNTS_CSV)
    metadata = read_metadata(LANGUAGE_PROJECT_COUNTS_JSON)
    owner = metadata.get("owner", "Zerius7733")
    generated_at = metadata.get("generated_at_sgt") or datetime.now(SGT).strftime("%Y-%m-%d %H:%M:%S+08:00")
    generated_label = generated_at.replace("T", " ").replace("+08:00", " SGT")
    repository_scope = metadata.get("repository_scope", "public_owner_only")

    LANGUAGE_PROJECT_CHART_SVG.parent.mkdir(parents=True, exist_ok=True)
    svg = build_svg(owner, counts, generated_label, repository_scope)
    LANGUAGE_PROJECT_CHART_SVG.write_text(svg, encoding="utf-8")
    print(f"Saved {LANGUAGE_PROJECT_CHART_SVG}")


if __name__ == "__main__":
    main()
