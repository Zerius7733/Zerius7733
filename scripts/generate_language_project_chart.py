import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
load_dotenv(REPO_ROOT / ".env")

OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "Zerius7733")
TOKEN = os.environ.get("GH_TOKEN", "")
OUTPUT_DIR = REPO_ROOT / "img"
OUTPUT_SVG = OUTPUT_DIR / "language-project-chart.svg"
OUTPUT_JSON = OUTPUT_DIR / "language-project-counts.json"
SGT = ZoneInfo("Asia/Singapore")
_RATE_LIMIT_WARNED = False
_LANG_RATE_LIMIT_WARNED = False


def github_get(url: str) -> list[dict] | dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "language-project-chart-bot",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 403:
            body = ""
            try:
                body = error.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            if "rate limit exceeded" in body.lower():
                raise RuntimeError(f"GitHub API rate limit exceeded for {url}") from error
        raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error
    except (HTTPError, URLError) as error:
        raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error


def fetch_repos(owner: str) -> list[dict]:
    repos: list[dict] = []
    page = 1

    # With a token, use authenticated endpoint so private repos can be included.
    # Without a token, fall back to public repos only.
    use_authenticated_endpoint = bool(TOKEN)

    while True:
        if use_authenticated_endpoint:
            url = (
                "https://api.github.com/user/repos"
                f"?visibility=all&affiliation=owner&per_page=100&page={page}&sort=updated"
            )
        else:
            url = f"https://api.github.com/users/{owner}/repos?per_page=100&page={page}&sort=updated"
        payload = github_get(url)

        if not isinstance(payload, list):
            raise RuntimeError("Unexpected GitHub API response format while fetching repositories.")

        if not payload:
            break

        if use_authenticated_endpoint:
            repos.extend(
                [
                    repo
                    for repo in payload
                    if (repo.get("owner") or {}).get("login", "").lower() == owner.lower()
                ]
            )
        else:
            repos.extend(payload)

        page += 1

    return repos


def owner_is_contributor(full_name: str, owner: str) -> bool:
    global _RATE_LIMIT_WARNED
    page = 1
    owner_lc = owner.lower()

    while True:
        url = f"https://api.github.com/repos/{full_name}/contributors?per_page=100&page={page}"
        try:
            payload = github_get(url)
        except RuntimeError as error:
            # If we are rate-limited while checking fork contributors, skip this fork.
            if "rate limit exceeded" in str(error).lower():
                if not _RATE_LIMIT_WARNED:
                    print("Warning: GitHub API rate limit exceeded while checking fork contributors; skipping remaining fork checks.")
                    _RATE_LIMIT_WARNED = True
                return False
            raise

        if not isinstance(payload, list):
            return False
        if not payload:
            return False

        for contributor in payload:
            login = (contributor or {}).get("login")
            contributions = (contributor or {}).get("contributions", 0)
            if isinstance(login, str) and login.lower() == owner_lc and contributions > 0:
                return True

        page += 1


def count_languages(repos: list[dict], owner: str) -> Counter:
    global _LANG_RATE_LIMIT_WARNED
    counts: Counter = Counter()

    for repo in repos:
        if repo.get("fork"):
            # Contributor checks for forks can trigger many API calls.
            # Only perform them when authenticated.
            if not TOKEN:
                continue
            full_name = repo.get("full_name")
            if not isinstance(full_name, str) or not owner_is_contributor(full_name, owner):
                continue

        full_name = repo.get("full_name")
        detected_languages: set[str] = set()

        if isinstance(full_name, str):
            url = f"https://api.github.com/repos/{full_name}/languages"
            try:
                payload = github_get(url)
                if isinstance(payload, dict):
                    detected_languages = {
                        lang for lang, byte_count in payload.items() if isinstance(lang, str) and byte_count
                    }
            except RuntimeError as error:
                # If per-repo language breakdown gets rate-limited, fall back to primary language.
                if "rate limit exceeded" in str(error).lower():
                    if not _LANG_RATE_LIMIT_WARNED:
                        print("Warning: GitHub API rate limit exceeded while fetching per-repo languages; using primary-language fallback.")
                        _LANG_RATE_LIMIT_WARNED = True
                else:
                    raise

        if not detected_languages:
            primary = repo.get("language")
            detected_languages = {primary} if isinstance(primary, str) and primary else {"Other"}

        for language in detected_languages:
            counts[language] += 1

    return counts


def build_svg(owner: str, counts: Counter) -> str:
    sorted_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    rows = sorted_counts
    max_count = max((count for _, count in rows), default=1)

    width = 860
    chart_x = 240
    chart_w = 560
    row_h = 44
    top_padding = 98
    bottom_padding = 54
    height = top_padding + (row_h * max(1, len(rows))) + bottom_padding

    fg = "#C9D1D9"
    muted = "#8B949E"
    bar = "#58A6FF"
    bar_bg = "#30363D"

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Projects by detected languages chart">',
        f'<text x="34" y="54" fill="{fg}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="28" font-weight="700">Projects by Detected Languages</text>',
        f'<text x="34" y="79" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">Each detected repo language counts once - {escape(owner)}</text>',
        f'<text x="34" y="94" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14">Contributed Repositories • {escape(owner)}</text>',
    ]

    if not rows:
        lines.append(
            f'<text x="34" y="{top_padding + 18}" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16">No repositories found.</text>'
        )
    else:
        for idx, (language, count) in enumerate(rows):
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

    updated = datetime.now(SGT).strftime("%Y-%m-%d %H:%M SGT")
    lines.append(
        f'<text x="34" y="{height - 22}" fill="{muted}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12">Updated: {updated}</text>'
    )
    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        repos = fetch_repos(OWNER)
        counts = count_languages(repos, OWNER)
    except RuntimeError as error:
        msg = str(error)
        if "rate limit exceeded" in msg.lower():
            raise RuntimeError(
                "GitHub API rate limit exceeded. Set GH_TOKEN to a PAT and rerun to include private repos reliably."
            ) from error
        raise

    svg = build_svg(OWNER, counts)

    data = {
        "owner": OWNER,
        "generated_at_sgt": datetime.now(SGT).isoformat(),
        "counting_mode": "repo_presence",
        "project_counts_by_language": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))),
        "total_counted_repos": sum(counts.values()),
    }

    OUTPUT_SVG.write_text(svg, encoding="utf-8")
    OUTPUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Generated {OUTPUT_SVG} and {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
