import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape


OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "Zerius7733")
TOKEN = os.environ.get("GH_TOKEN", "")
OUTPUT_DIR = Path("img")
OUTPUT_SVG = OUTPUT_DIR / "language-project-chart.svg"
OUTPUT_JSON = OUTPUT_DIR / "language-project-counts.json"
MAX_BARS = 8


def fetch_repos(owner: str) -> list[dict]:
    repos: list[dict] = []
    page = 1

    while True:
        url = f"https://api.github.com/users/{owner}/repos?per_page=100&page={page}&sort=updated"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "language-project-chart-bot",
        }
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"

        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as error:
            raise RuntimeError(f"Failed to fetch repositories from GitHub API: {error}") from error

        if not payload:
            break

        repos.extend(payload)
        page += 1

    return repos


def count_languages(repos: list[dict]) -> Counter:
    counts: Counter = Counter()
    for repo in repos:
        if repo.get("fork"):
            continue
        language = repo.get("language") or "Other"
        counts[language] += 1
    return counts


def build_svg(owner: str, counts: Counter) -> str:
    sorted_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    top = sorted_counts[:MAX_BARS]
    max_count = max((count for _, count in top), default=1)

    width = 860
    chart_x = 240
    chart_w = 560
    row_h = 44
    top_padding = 98
    bottom_padding = 54
    height = top_padding + (row_h * max(1, len(top))) + bottom_padding

    bg = "#0D1117"
    card = "#161B22"
    fg = "#C9D1D9"
    muted = "#8B949E"
    bar = "#58A6FF"
    bar_bg = "#30363D"

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Projects by language chart">',
        f'<rect width="100%" height="100%" fill="{bg}" />',
        f'<rect x="14" y="14" width="{width - 28}" height="{height - 28}" rx="14" fill="{card}" stroke="#30363D" />',
        f'<text x="34" y="54" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="28" font-weight="700">Projects by Primary Language</text>',
        f'<text x="34" y="79" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">Public non-fork repositories • {escape(owner)}</text>',
    ]

    if not top:
        lines.append(
            f'<text x="34" y="{top_padding + 18}" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16">No repositories found.</text>'
        )
    else:
        for idx, (language, count) in enumerate(top):
            y = top_padding + idx * row_h
            bar_width = int((count / max_count) * chart_w)
            lines.extend(
                [
                    f'<text x="34" y="{y + 24}" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16">{escape(language)}</text>',
                    f'<rect x="{chart_x}" y="{y + 8}" width="{chart_w}" height="18" rx="9" fill="{bar_bg}" />',
                    f'<rect x="{chart_x}" y="{y + 8}" width="{bar_width}" height="18" rx="9" fill="{bar}" />',
                    f'<text x="{chart_x + chart_w + 12}" y="{y + 23}" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">{count}</text>',
                ]
            )

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(
        f'<text x="34" y="{height - 22}" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12">Updated: {updated}</text>'
    )
    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    repos = fetch_repos(OWNER)
    counts = count_languages(repos)
    svg = build_svg(OWNER, counts)

    data = {
        "owner": OWNER,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_counts_by_language": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))),
        "total_public_non_fork_repos": sum(counts.values()),
    }

    OUTPUT_SVG.write_text(svg, encoding="utf-8")
    OUTPUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Generated {OUTPUT_SVG} and {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
