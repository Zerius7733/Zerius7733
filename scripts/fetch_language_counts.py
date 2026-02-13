import csv
import json
import os
from collections import Counter
from datetime import datetime
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


if __name__ == "__main__":
    main()
