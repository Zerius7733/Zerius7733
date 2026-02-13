import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def run(script_name: str) -> None:
    script_path = SCRIPT_DIR / script_name
    result = subprocess.run([sys.executable, str(script_path)], check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    run("fetch_language_counts.py")
    run("render_language_project_chart.py")
    run("render_coding_days_chart.py")


if __name__ == "__main__":
    main()
