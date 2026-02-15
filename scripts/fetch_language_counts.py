import csv
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
OUTPUT_CSV = OUTPUT_DIR / "language-project-counts.csv"
OUTPUT_JSON = OUTPUT_DIR / "language-project-counts.json"
SGT = ZoneInfo("Asia/Singapore")
_FORK_RATE_LIMIT_WARNED = False
_LANG_RATE_LIMIT_WARNED = False
_COMMIT_RATE_LIMIT_WARNED = False


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


def github_graphql(query: str, variables: dict) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "language-project-chart-bot",
        "Content-Type": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = Request(
        "https://api.github.com/graphql",
        headers=headers,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"GitHub GraphQL request failed: {error}") from error
    except URLError as error:
        raise RuntimeError(f"GitHub GraphQL request failed: {error}") from error

    if "errors" in payload:
        raise RuntimeError(f"GitHub GraphQL error: {payload['errors']}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected GitHub GraphQL response format.")
    return data


def fetch_repos(owner: str) -> list[dict]:
    repos: list[dict] = []
    page = 1
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
    global _FORK_RATE_LIMIT_WARNED
    page = 1
    owner_lc = owner.lower()

    while True:
        url = f"https://api.github.com/repos/{full_name}/contributors?per_page=100&page={page}"
        try:
            payload = github_get(url)
        except RuntimeError as error:
            if "rate limit exceeded" in str(error).lower():
                if not _FORK_RATE_LIMIT_WARNED:
                    print("Warning: rate limit exceeded while checking fork contributors; skipping remaining fork checks.")
                    _FORK_RATE_LIMIT_WARNED = True
                return False
            raise

        if not isinstance(payload, list) or not payload:
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
            if not TOKEN:
                continue
            full_name = repo.get("full_name")
            if not isinstance(full_name, str) or not owner_is_contributor(full_name, owner):
                continue

        full_name = repo.get("full_name")
        detected_languages: set[str] = set()

        if isinstance(full_name, str):
            try:
                payload = github_get(f"https://api.github.com/repos/{full_name}/languages")
                if isinstance(payload, dict):
                    detected_languages = {
                        lang for lang, byte_count in payload.items() if isinstance(lang, str) and byte_count
                    }
            except RuntimeError as error:
                if "rate limit exceeded" in str(error).lower():
                    if not _LANG_RATE_LIMIT_WARNED:
                        print("Warning: rate limit exceeded while fetching per-repo languages; using primary-language fallback.")
                        _LANG_RATE_LIMIT_WARNED = True
                else:
                    raise

        if not detected_languages:
            primary = repo.get("language")
            detected_languages = {primary} if isinstance(primary, str) and primary else {"Other"}

        for language in detected_languages:
            counts[language] += 1

    return counts


def count_contributions_by_day(owner: str, days: int = 90) -> dict[str, int]:
    global _COMMIT_RATE_LIMIT_WARNED
    now_sgt = datetime.now(SGT)
    start_day = now_sgt.date() - timedelta(days=days - 1)
    start_dt_sgt = datetime.combine(start_day, datetime.min.time(), tzinfo=SGT)
    from_iso = start_dt_sgt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    to_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    try:
        data = github_graphql(query, {"login": owner, "from": from_iso, "to": to_iso})
    except RuntimeError as error:
        msg = str(error).lower()
        if "rate limit" in msg and not _COMMIT_RATE_LIMIT_WARNED:
            print("Warning: rate limit exceeded while fetching contribution calendar; contribution metric may be partial.")
            _COMMIT_RATE_LIMIT_WARNED = True
        raise

    contribution_counts: dict[str, int] = {}
    user = data.get("user") if isinstance(data, dict) else None
    collection = (user or {}).get("contributionsCollection") if isinstance(user, dict) else None
    calendar = (collection or {}).get("contributionCalendar") if isinstance(collection, dict) else None
    weeks = (calendar or {}).get("weeks") if isinstance(calendar, dict) else []
    if not isinstance(weeks, list):
        weeks = []
    for week in weeks:
        days_payload = (week or {}).get("contributionDays")
        if not isinstance(days_payload, list):
            continue
        for day_entry in days_payload:
            day = (day_entry or {}).get("date")
            count = (day_entry or {}).get("contributionCount", 0)
            if isinstance(day, str):
                try:
                    contribution_counts[day] = int(count)
                except (TypeError, ValueError):
                    contribution_counts[day] = 0

    filtered_counts: dict[str, int] = {}
    for i in range(days):
        day = (start_day + timedelta(days=i)).isoformat()
        filtered_counts[day] = contribution_counts.get(day, 0)

    today_sgt = now_sgt.date().isoformat()
    latest_graphql_day = max(contribution_counts.keys()) if contribution_counts else "N/A"
    latest_graphql_count = contribution_counts.get(latest_graphql_day, 0) if contribution_counts else 0
    print(f"[debug] GraphQL contributions for {today_sgt} SGT (window={days}d): {filtered_counts.get(today_sgt, 0)}")
    print(f"[debug] Latest GraphQL day/count (window={days}d): {latest_graphql_day} -> {latest_graphql_count}")
    return filtered_counts


def write_outputs(owner: str, counts: Counter) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sorted_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["language", "count"])
        writer.writerows(sorted_counts)

    metadata = {
        "owner": owner,
        "generated_at_sgt": datetime.now(SGT).isoformat(),
        "counting_mode": "repo_presence",
        "total_counted_repos": sum(counts.values()),
        "csv_file": OUTPUT_CSV.name,
    }
    OUTPUT_JSON.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Saved {OUTPUT_CSV} and {OUTPUT_JSON}")


def write_coding_outputs(owner: str, daily_contribution_counts: dict[str, int], days: int) -> None:
    coding_csv = OUTPUT_DIR / f"coding-days-{days}d.csv"
    coding_json = OUTPUT_DIR / f"coding-days-{days}d.json"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now_sgt = datetime.now(SGT)
    start_day = now_sgt.date() - timedelta(days=days - 1)
    rows: list[tuple[str, int]] = []
    for i in range(days):
        day = (start_day + timedelta(days=i)).isoformat()
        rows.append((day, daily_contribution_counts.get(day, 0)))

    with coding_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "contribution_count"])
        writer.writerows(rows)

    coded_days = sum(1 for _, count in rows if count > 0)
    total_contributions = sum(count for _, count in rows)
    percent = round((coded_days / days) * 100, 1) if days else 0.0

    metadata = {
        "owner": owner,
        "generated_at_sgt": datetime.now(SGT).isoformat(),
        "window_days": days,
        "coded_days": coded_days,
        "coded_days_percent": percent,
        "total_contributions": total_contributions,
        "csv_file": coding_csv.name,
    }
    coding_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved {coding_csv} and {coding_json}")


def main() -> None:
    try:
        repos = fetch_repos(OWNER)
        counts = count_languages(repos, OWNER)
    except RuntimeError as error:
        msg = str(error).lower()
        if "rate limit exceeded" in msg:
            raise RuntimeError(
                "GitHub API rate limit exceeded. Ensure GH_TOKEN is set (PAT) to include private repos reliably."
            ) from error
        raise

    write_outputs(OWNER, counts)
    for window_days in (90, 180, 365):
        contribution_counts = count_contributions_by_day(OWNER, days=window_days)
        write_coding_outputs(OWNER, contribution_counts, days=window_days)


if __name__ == "__main__":
    main()
