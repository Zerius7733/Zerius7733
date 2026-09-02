import os
from pathlib import Path
from zoneinfo import ZoneInfo


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE settings without overriding the environment."""
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

# Runtime settings are read once here so every script behaves consistently.
OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "Zerius7733").strip() or "Zerius7733"
TOKEN = os.environ.get("GH_TOKEN", "").strip()
SGT = ZoneInfo("Asia/Singapore")
SUPPORTED_WINDOWS = (90, 180, 365)

# Shared GitHub API settings.
GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_ACCEPT = "application/vnd.github+json"
GITHUB_USER_AGENT = "language-project-chart-bot"
API_TIMEOUT_SECONDS = 30
GRAPHQL_TIMEOUT_SECONDS = 20
REPOSITORY_PAGE_SIZE = 100
CONTRIBUTOR_PAGE_SIZE = 100
COMMIT_PAGE_SIZE = 25

# Shared generated-file locations.
OUTPUT_DIR = REPO_ROOT / "img"
LANGUAGE_PROJECT_COUNTS_CSV = OUTPUT_DIR / "language-project-counts.csv"
LANGUAGE_PROJECT_COUNTS_JSON = OUTPUT_DIR / "language-project-counts.json"
LANGUAGE_PROJECT_CHART_SVG = OUTPUT_DIR / "language-project-chart.svg"
LOC_ANALYSIS_JSON = OUTPUT_DIR / "loc-analysis.json"


def coding_days_csv_path(days: int) -> Path:
    return OUTPUT_DIR / f"coding-days-{days}d.csv"


def coding_days_json_path(days: int) -> Path:
    return OUTPUT_DIR / f"coding-days-{days}d.json"


def coding_days_svg_path(days: int) -> Path:
    return OUTPUT_DIR / f"coding-days-{days}d.svg"


def github_stats_svg_path(days: int) -> Path:
    return OUTPUT_DIR / f"github-stats-{days}d.svg"


def loc_analysis_svg_path(days: int) -> Path:
    return OUTPUT_DIR / f"loc-analysis-{days}d.svg"
