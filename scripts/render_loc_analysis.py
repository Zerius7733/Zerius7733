import json
import math
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from config import (
    COMMIT_PAGE_SIZE,
    GITHUB_API_BASE_URL,
    LOC_ANALYSIS_JSON,
    OUTPUT_DIR,
    OWNER,
    SGT,
    SUPPORTED_WINDOWS,
    TOKEN,
    loc_analysis_svg_path,
)
from fetch_language_counts import fetch_repos, github_get, user_is_contributor
LANGUAGE_COLORS = ["#2F81F7", "#F78166", "#2EA043", "#F85149", "#A371F7", "#8B949E"]
LANGUAGE_BY_EXTENSION = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".dart": "Dart",
    ".go": "Go",
    ".h": "C/C++",
    ".hpp": "C++",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".json": "JSON",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".md": "Markdown",
    ".php": "PHP",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".pyw": "Python",
    ".r": "R",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
}


def as_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def commit_day(commit: dict) -> date | None:
    commit_data = commit.get("commit") if isinstance(commit, dict) else None
    author_data = commit_data.get("author") if isinstance(commit_data, dict) else None
    date_text = author_data.get("date") if isinstance(author_data, dict) else None
    if not isinstance(date_text, str) or len(date_text) < 10:
        return None
    try:
        return date.fromisoformat(date_text[:10])
    except ValueError:
        return None


def has_commit_details(commit: dict) -> bool:
    return isinstance(commit.get("stats"), dict) and isinstance(commit.get("files"), list)


def fetch_repo_commits(full_name: str, owner: str, start_day: date, end_day: date) -> list[dict]:
    since = datetime.combine(start_day, time.min, tzinfo=SGT).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    until = datetime.combine(end_day, time.max, tzinfo=SGT).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    records: list[dict] = []
    seen_shas: set[str] = set()
    page = 1

    while True:
        params = urlencode(
            {
                "author": owner,
                "since": since,
                "until": until,
                "per_page": COMMIT_PAGE_SIZE,
                "page": page,
            }
        )
        payload = github_get(f"{GITHUB_API_BASE_URL}/repos/{full_name}/commits?{params}")
        if not isinstance(payload, list) or not payload:
            break

        for commit in payload:
            if not isinstance(commit, dict):
                continue
            sha = commit.get("sha")
            if not isinstance(sha, str) or sha in seen_shas:
                continue
            seen_shas.add(sha)
            day_value = commit_day(commit)
            if day_value is None or not (start_day <= day_value <= end_day):
                continue

            details = commit
            if not has_commit_details(details):
                try:
                    fetched = github_get(f"{GITHUB_API_BASE_URL}/repos/{full_name}/commits/{sha}")
                except RuntimeError as error:
                    message = str(error).lower()
                    if "401" in message or "bad credentials" in message or "rate limit" in message:
                        raise
                    print(f"Warning: skipped commit stats for {full_name}@{sha[:7]}: {error}")
                    continue
                if isinstance(fetched, dict):
                    details = fetched

            stats = details.get("stats") if isinstance(details, dict) else None
            files = details.get("files") if isinstance(details, dict) else None
            records.append(
                {
                    "date": day_value.isoformat(),
                    "repository": full_name,
                    "additions": as_int((stats or {}).get("additions")),
                    "deletions": as_int((stats or {}).get("deletions")),
                    "files": [
                        {
                            "filename": file.get("filename"),
                            "additions": as_int(file.get("additions")),
                            "deletions": as_int(file.get("deletions")),
                        }
                        for file in (files or [])
                        if isinstance(file, dict) and isinstance(file.get("filename"), str)
                    ],
                }
            )

        if len(payload) < COMMIT_PAGE_SIZE:
            break
        page += 1

    return records


def scoped_repositories(repos: list[dict], owner: str) -> list[dict]:
    owner_lc = owner.lower()
    selected: list[dict] = []
    seen: set[str] = set()
    for repo in repos:
        full_name = repo.get("full_name") if isinstance(repo, dict) else None
        if not isinstance(full_name, str) or full_name in seen:
            continue
        seen.add(full_name)
        repo_owner = (repo.get("owner") or {}).get("login")
        owned_by_user = isinstance(repo_owner, str) and repo_owner.lower() == owner_lc
        if repo.get("fork") or not owned_by_user:
            if not TOKEN or not user_is_contributor(full_name, owner):
                continue
        selected.append(repo)
    return selected


def language_for_filename(filename: str, fallback: str) -> str:
    suffix = Path(filename).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(suffix, fallback or "Other")


def aggregate(records: list[dict], window_days: int, today: date) -> dict:
    start_day = today - timedelta(days=window_days - 1)
    window_records = [
        record
        for record in records
        if start_day <= date.fromisoformat(record["date"]) <= today
    ]
    language_totals: Counter[str] = Counter()
    repository_totals: Counter[str] = Counter()
    additions = 0
    deletions = 0
    commit_additions: list[int] = []
    commit_deletions: list[int] = []

    for record in window_records:
        record_additions = as_int(record.get("additions"))
        record_deletions = as_int(record.get("deletions"))
        additions += record_additions
        deletions += record_deletions
        commit_additions.append(record_additions)
        commit_deletions.append(record_deletions)
        repository = str(record.get("repository", "Unknown"))
        primary_language = str(record.get("primary_language") or "Other")
        changed = record_additions + record_deletions
        repository_totals[repository] += changed

        files = record.get("files") if isinstance(record.get("files"), list) else []
        file_lines = 0
        for file in files:
            if not isinstance(file, dict):
                continue
            file_changed = as_int(file.get("additions")) + as_int(file.get("deletions"))
            file_lines += file_changed
            language = language_for_filename(str(file.get("filename", "")), primary_language)
            language_totals[language] += file_changed
        if not files or file_lines == 0:
            language_totals[primary_language] += changed

    total_changed = additions + deletions
    active_days = len({record["date"] for record in window_records})
    typical_additions = round(median(commit_additions)) if commit_additions else 0
    typical_deletions = round(median(commit_deletions)) if commit_deletions else 0

    def top_items(counter: Counter[str], limit: int = 5) -> list[dict]:
        return [{"name": name, "lines": value} for name, value in counter.most_common(limit)]

    return {
        "window_days": window_days,
        "commit_count": len(window_records),
        "active_days": active_days,
        "additions": additions,
        "deletions": deletions,
        "lines_changed": total_changed,
        "lines_changed_per_day": round(total_changed / window_days) if window_days else 0,
        "typical_commit_additions": typical_additions,
        "typical_commit_deletions": typical_deletions,
        "languages": top_items(language_totals),
        "repositories": top_items(repository_totals),
    }


def format_name(name: str, maximum: int = 18) -> str:
    if name == "Private repositories":
        return "Private repos"
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    if len(name) <= maximum:
        return name
    return f"{name[: maximum - 1]}..."


def item_color(index: int) -> str:
    return LANGUAGE_COLORS[index % len(LANGUAGE_COLORS)]


def donut_lines(
    items: list[dict],
    center_x: int,
    center_y: int,
    outer_radius: int,
    inner_radius: int,
    panel: str,
    font_family: str,
) -> list[str]:
    total = sum(as_int(item.get("lines")) for item in items)
    if not items or total <= 0:
        return [
            f'<text x="{center_x}" y="{center_y}" text-anchor="middle" fill="#8B949E" font-family="{font_family}" font-size="14">No LOC data</text>'
        ]

    lines: list[str] = []
    start_angle = -math.pi / 2
    middle_radius = (outer_radius + inner_radius) / 2
    stroke_width = outer_radius - inner_radius
    for index, item in enumerate(items):
        value = as_int(item.get("lines"))
        if value <= 0:
            continue
        fraction = value / total
        end_angle = start_angle + fraction * 2 * math.pi
        color = item_color(index)
        if fraction >= 0.999999:
            lines.append(
                f'<circle cx="{center_x}" cy="{center_y}" r="{middle_radius:.2f}" fill="none" stroke="{color}" stroke-width="{stroke_width}" />'
            )
        else:
            outer_start = (center_x + outer_radius * math.cos(start_angle), center_y + outer_radius * math.sin(start_angle))
            outer_end = (center_x + outer_radius * math.cos(end_angle), center_y + outer_radius * math.sin(end_angle))
            inner_start = (center_x + inner_radius * math.cos(start_angle), center_y + inner_radius * math.sin(start_angle))
            inner_end = (center_x + inner_radius * math.cos(end_angle), center_y + inner_radius * math.sin(end_angle))
            large_arc = 1 if end_angle - start_angle > math.pi else 0
            path = (
                f"M {outer_start[0]:.2f} {outer_start[1]:.2f} "
                f"A {outer_radius} {outer_radius} 0 {large_arc} 1 {outer_end[0]:.2f} {outer_end[1]:.2f} "
                f"L {inner_end[0]:.2f} {inner_end[1]:.2f} "
                f"A {inner_radius} {inner_radius} 0 {large_arc} 0 {inner_start[0]:.2f} {inner_start[1]:.2f} Z"
            )
            lines.append(f'<path d="{path}" fill="{color}" stroke="{panel}" stroke-width="2" />')

        start_angle = end_angle

    lines.append(f'<circle cx="{center_x}" cy="{center_y}" r="{inner_radius}" fill="{panel}" />')
    return lines


def legend_lines(
    items: list[dict],
    panel_x: int,
    panel_y: int,
    panel_width: int,
    font_family: str,
) -> list[str]:
    valid_items = [
        (index, item)
        for index, item in enumerate(items)
        if as_int(item.get("lines")) > 0
    ]
    if not valid_items:
        return []

    total = sum(as_int(item.get("lines")) for _, item in valid_items)
    columns = 2
    column_width = (panel_width - 32) / columns
    first_baseline = panel_y + 245
    row_gap = 15
    lines: list[str] = []
    for legend_index, (item_index, item) in enumerate(valid_items):
        column = legend_index % columns
        row = legend_index // columns
        x = panel_x + 16 + column * column_width
        baseline = first_baseline + row * row_gap
        percentage = round((as_int(item.get("lines")) / total) * 100) if total else 0
        label = f"{format_name(str(item.get('name', 'Other')), maximum=14)} - {percentage}%"
        color = item_color(item_index)
        tooltip = f"{item.get('name', 'Other')}: {as_int(item.get('lines')):,} lines changed"
        lines.extend(
            [
                f'<rect x="{x:.1f}" y="{baseline - 10:.1f}" width="10" height="10" rx="2" fill="{color}"><title>{escape(tooltip)}</title></rect>',
                f'<text x="{x + 16:.1f}" y="{baseline:.1f}" fill="#C9D1D9" font-family="{font_family}" font-size="11">{escape(label)}</text>',
            ]
        )
    return lines


def build_svg(summary: dict, owner: str) -> str:
    window_days = as_int(summary.get("window_days"))
    period_label = "Last Year" if window_days == 365 else f"Last {window_days} Days"
    width = 1200
    height = 410
    panel = "#161B22"
    border = "#30363D"
    foreground = "#F0F6FC"
    muted = "#8B949E"
    font_family = "Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif"
    language_items = summary.get("languages") if isinstance(summary.get("languages"), list) else []
    repository_items = summary.get("repositories") if isinstance(summary.get("repositories"), list) else []
    additions = as_int(summary.get("additions"))
    deletions = as_int(summary.get("deletions"))
    typical_additions = as_int(summary.get("typical_commit_additions"))
    typical_deletions = as_int(summary.get("typical_commit_deletions"))
    lines_per_day = as_int(summary.get("lines_changed_per_day"))

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Lines of Code analysis for {escape(owner)} for {escape(period_label)}">',
        f'<rect width="{width}" height="{height}" rx="8" fill="#0D1117" />',
        f'<text x="28" y="35" fill="{foreground}" font-family="{font_family}" font-size="27">Lines of Code (LOC) Analysis</text>',
        f'<text x="1170" y="35" text-anchor="end" fill="{muted}" font-family="{font_family}" font-size="15">{escape(period_label)}</text>',
        f'<rect x="20" y="55" width="390" height="280" rx="6" fill="{panel}" stroke="{border}" stroke-width="1" />',
        f'<rect x="420" y="55" width="390" height="280" rx="6" fill="{panel}" stroke="{border}" stroke-width="1" />',
        f'<rect x="820" y="55" width="175" height="135" rx="6" fill="{panel}" stroke="{border}" stroke-width="1" />',
        f'<rect x="1005" y="55" width="175" height="135" rx="6" fill="{panel}" stroke="{border}" stroke-width="1" />',
        f'<rect x="820" y="200" width="175" height="135" rx="6" fill="{panel}" stroke="{border}" stroke-width="1" />',
        f'<rect x="1005" y="200" width="175" height="135" rx="6" fill="{panel}" stroke="{border}" stroke-width="1" />',
        f'<text x="36" y="84" fill="{foreground}" font-family="{font_family}" font-size="18" font-weight="700">Most Used Languages</text>',
        f'<text x="36" y="105" fill="{muted}" font-family="{font_family}" font-size="14">By LOC Changed</text>',
        f'<text x="436" y="84" fill="{foreground}" font-family="{font_family}" font-size="18" font-weight="700">Most Active Repositories</text>',
        f'<text x="436" y="105" fill="{muted}" font-family="{font_family}" font-size="14">By LOC Changed</text>',
    ]
    lines.extend(donut_lines(language_items, 215, 190, 84, 45, panel, font_family))
    lines.extend(donut_lines(repository_items, 615, 190, 84, 45, panel, font_family))
    lines.extend(legend_lines(language_items, 20, 55, 390, font_family))
    lines.extend(legend_lines(repository_items, 420, 55, 390, font_family))

    lines.extend(
        [
            f'<text x="907" y="111" text-anchor="middle" fill="#2EA043" font-family="{font_family}" font-size="20" font-weight="700">+{additions:,}</text>',
            f'<text x="907" y="133" text-anchor="middle" fill="#2EA043" font-family="{font_family}" font-size="14">LOC Additions</text>',
            f'<text x="1092" y="111" text-anchor="middle" fill="#F85149" font-family="{font_family}" font-size="20" font-weight="700">-{deletions:,}</text>',
            f'<text x="1092" y="133" text-anchor="middle" fill="#F85149" font-family="{font_family}" font-size="14">LOC Deletions</text>',
            f'<text x="907" y="257" text-anchor="middle" fill="#2EA043" font-family="{font_family}" font-size="20" font-weight="700">{typical_additions} <tspan fill="{muted}">/</tspan> <tspan fill="#F85149">{typical_deletions}</tspan></text>',
            f'<text x="907" y="280" text-anchor="middle" fill="{muted}" font-family="{font_family}" font-size="14">Typical Commit</text>',
            f'<text x="1092" y="257" text-anchor="middle" fill="{foreground}" font-family="{font_family}" font-size="20" font-weight="700">{lines_per_day}</text>',
            f'<text x="1092" y="280" text-anchor="middle" fill="{muted}" font-family="{font_family}" font-size="14">Lines Changed / Day</text>',
            f'<text x="28" y="373" fill="{muted}" font-family="{font_family}" font-size="12">Based on authenticated GitHub commit file statistics across accessible repositories</text>',
            f'<text x="1170" y="373" text-anchor="end" fill="{muted}" font-family="{font_family}" font-size="12">{as_int(summary.get("commit_count")):,} commits | {as_int(summary.get("active_days")):,} active days</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def collect_records(owner: str, today: date) -> list[dict]:
    start_day = today - timedelta(days=max(SUPPORTED_WINDOWS) - 1)
    repos = scoped_repositories(fetch_repos(owner), owner)
    print(f"Collecting LOC statistics from {len(repos)} accessible repositories")
    records: list[dict] = []
    for index, repo in enumerate(repos, start=1):
        full_name = str(repo.get("full_name"))
        primary_language = str(repo.get("language") or "Other")
        print(f"[{index}/{len(repos)}] Reading commits from {full_name}")
        repo_records = fetch_repo_commits(full_name, owner, start_day, today)
        display_repository = "Private repositories" if repo.get("private") else full_name
        for record in repo_records:
            record["repository"] = display_repository
            record["primary_language"] = primary_language
        records.extend(repo_records)
    return records


def main() -> None:
    today = datetime.now(SGT).date()
    records = collect_records(OWNER, today)
    summaries = {str(window_days): aggregate(records, window_days, today) for window_days in SUPPORTED_WINDOWS}
    metadata = {
        "owner": OWNER,
        "generated_at_sgt": datetime.now(SGT).isoformat(),
        "repository_scope": "owner,collaborator,organization_member" if TOKEN else "public_owner_only",
        "source": "GitHub REST commit file statistics",
        "windows": summaries,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOC_ANALYSIS_JSON.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    for window_days in SUPPORTED_WINDOWS:
        output_svg = loc_analysis_svg_path(window_days)
        output_svg.write_text(build_svg(summaries[str(window_days)], OWNER), encoding="utf-8")
        print(f"Saved {output_svg}")
    print(f"Saved {LOC_ANALYSIS_JSON}")


if __name__ == "__main__":
    main()
