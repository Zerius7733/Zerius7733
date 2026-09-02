import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import (
    API_TIMEOUT_SECONDS,
    CONTRIBUTOR_PAGE_SIZE,
    GITHUB_API_ACCEPT,
    GITHUB_API_BASE_URL,
    GITHUB_USER_AGENT,
    GRAPHQL_TIMEOUT_SECONDS,
    LANGUAGE_PROJECT_COUNTS_CSV,
    LANGUAGE_PROJECT_COUNTS_JSON,
    OUTPUT_DIR,
    OWNER,
    REPOSITORY_PAGE_SIZE,
    SGT,
    SUPPORTED_WINDOWS,
    TOKEN,
    coding_days_csv_path,
    coding_days_json_path,
)
_CONTRIBUTOR_RATE_LIMIT_WARNED = False
_LANG_RATE_LIMIT_WARNED = False
_COMMIT_RATE_LIMIT_WARNED = False


def github_get(url: str) -> list[dict] | dict:
    headers = {
        "Accept": GITHUB_API_ACCEPT,
        "User-Agent": GITHUB_USER_AGENT,
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    for attempt in range(4):
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
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
        except (IncompleteRead, URLError, TimeoutError, OSError) as error:
            if attempt == 3:
                raise RuntimeError(f"GitHub API response was incomplete after retries for {url}: {error}") from error
            delay = 2**attempt
            print(f"Warning: interrupted GitHub API response; retrying in {delay}s ({attempt + 1}/4)")
            sleep(delay)

    raise RuntimeError(f"GitHub API request failed for {url}")


def github_graphql(query: str, variables: dict) -> dict:
    headers = {
        "Accept": GITHUB_API_ACCEPT,
        "User-Agent": GITHUB_USER_AGENT,
        "Content-Type": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = Request(
        f"{GITHUB_API_BASE_URL}/graphql",
        headers=headers,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        method="POST",
    )
    try:
        with urlopen(request, timeout=GRAPHQL_TIMEOUT_SECONDS) as response:
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
                f"{GITHUB_API_BASE_URL}/user/repos"
                f"?visibility=all&affiliation=owner,collaborator,organization_member&per_page={REPOSITORY_PAGE_SIZE}&page={page}&sort=updated"
            )
        else:
            url = f"{GITHUB_API_BASE_URL}/users/{owner}/repos?per_page={REPOSITORY_PAGE_SIZE}&page={page}&sort=updated"
        payload = github_get(url)

        if not isinstance(payload, list):
            raise RuntimeError("Unexpected GitHub API response format while fetching repositories.")
        if not payload:
            break

        repos.extend(payload)
        page += 1

    return repos


def user_is_contributor(full_name: str, username: str) -> bool:
    global _CONTRIBUTOR_RATE_LIMIT_WARNED
    page = 1
    username_lc = username.lower()

    while True:
        url = f"{GITHUB_API_BASE_URL}/repos/{full_name}/contributors?per_page={CONTRIBUTOR_PAGE_SIZE}&page={page}"
        try:
            payload = github_get(url)
        except RuntimeError as error:
            if "rate limit exceeded" in str(error).lower():
                if not _CONTRIBUTOR_RATE_LIMIT_WARNED:
                    print("Warning: rate limit exceeded while checking repository contributors; skipping remaining contributor checks.")
                    _CONTRIBUTOR_RATE_LIMIT_WARNED = True
                return False
            raise

        if not isinstance(payload, list) or not payload:
            return False

        for contributor in payload:
            login = (contributor or {}).get("login")
            contributions = (contributor or {}).get("contributions", 0)
            if isinstance(login, str) and login.lower() == username_lc and contributions > 0:
                return True
        page += 1


def count_languages(repos: list[dict], owner: str) -> Counter:
    global _LANG_RATE_LIMIT_WARNED
    counts: Counter = Counter()
    owner_lc = owner.lower()

    for repo in repos:
        repo_owner = (repo.get("owner") or {}).get("login")
        owned_by_user = isinstance(repo_owner, str) and repo_owner.lower() == owner_lc

        # Keep all repositories owned by the profile owner, but only include
        # collaborator- or organization-owned repositories when the profile
        # owner has actually contributed commits to them. This prevents every
        # accessible team repository from inflating the language chart.
        if repo.get("fork") or not owned_by_user:
            if not TOKEN:
                continue
            full_name = repo.get("full_name")
            if not isinstance(full_name, str) or not user_is_contributor(full_name, owner):
                continue

        full_name = repo.get("full_name")
        detected_languages: set[str] = set()

        if isinstance(full_name, str):
            try:
                payload = github_get(f"{GITHUB_API_BASE_URL}/repos/{full_name}/languages")
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

    with LANGUAGE_PROJECT_COUNTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["language", "count"])
        writer.writerows(sorted_counts)

    metadata = {
        "owner": owner,
        "generated_at_sgt": datetime.now(SGT).isoformat(),
        "counting_mode": "repo_presence_owner_plus_contributor_repos",
        "repository_scope": (
            "owner,collaborator,organization_member"
            if TOKEN
            else "public_owner_only"
        ),
        "total_counted_repos": sum(counts.values()),
        "csv_file": LANGUAGE_PROJECT_COUNTS_CSV.name,
    }
    LANGUAGE_PROJECT_COUNTS_JSON.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Saved {LANGUAGE_PROJECT_COUNTS_CSV} and {LANGUAGE_PROJECT_COUNTS_JSON}")


def write_coding_outputs(owner: str, daily_contribution_counts: dict[str, int], days: int) -> None:
    coding_csv = coding_days_csv_path(days)
    coding_json = coding_days_json_path(days)
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
    for window_days in SUPPORTED_WINDOWS:
        contribution_counts = count_contributions_by_day(OWNER, days=window_days)
        write_coding_outputs(OWNER, contribution_counts, days=window_days)


if __name__ == "__main__":
    main()
