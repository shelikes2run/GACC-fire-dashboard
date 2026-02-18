"""
update_data.py
──────────────
Script to push a new/updated Excel file to GitHub and trigger
a Streamlit Community Cloud refresh.

Usage (manual):
    python update_data.py --file /path/to/new/GACC_Percentile_Chart_FEMS.xlsx

Usage (scheduled via Windows Task Scheduler or cron):
    python update_data.py --file /path/to/GACC_Percentile_Chart_FEMS.xlsx --auto

Requirements:
    pip install gitpython requests python-dotenv
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─────────────────────────────────────────────
# CONFIG — edit these or set as environment vars
# ─────────────────────────────────────────────
REPO_DIR   = Path(__file__).parent            # folder this script lives in
EXCEL_NAME = "GACC_Percentile_Chart_FEMS.xlsx"
GIT_REMOTE = "origin"
GIT_BRANCH = "main"

# Optional: GitHub personal access token for HTTPS push
# Set in .env file as GITHUB_TOKEN=ghp_xxxxx
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = {"INFO": "✅", "WARN": "⚠️ ", "ERR": "❌"}.get(level, "  ")
    print(f"[{ts}] {prefix} {msg}")


def run(cmd: list[str], cwd: Path = REPO_DIR) -> tuple[int, str]:
    """Run a shell command, return (returncode, output)."""
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return result.returncode, result.stdout.strip() + result.stderr.strip()


# ─────────────────────────────────────────────
# MAIN UPDATE FUNCTION
# ─────────────────────────────────────────────
def update_data(source_file: Path, dry_run: bool = False):
    log(f"Source file: {source_file}")

    # 1. Validate source file exists
    if not source_file.exists():
        log(f"File not found: {source_file}", "ERR")
        sys.exit(1)

    dest = REPO_DIR / EXCEL_NAME

    # 2. Copy file into repo
    if not dry_run:
        shutil.copy2(source_file, dest)
        log(f"Copied → {dest}")
    else:
        log(f"[DRY RUN] Would copy {source_file} → {dest}")

    # 3. Git pull (make sure we're up to date first)
    log("Pulling latest from remote...")
    code, out = run(["git", "pull", GIT_REMOTE, GIT_BRANCH])
    if code != 0:
        log(f"git pull warning: {out}", "WARN")

    # 4. Stage the Excel file
    code, out = run(["git", "add", EXCEL_NAME])
    if code != 0:
        log(f"git add failed: {out}", "ERR")
        sys.exit(1)
    log("Staged Excel file")

    # 5. Check if there's actually a change
    code, out = run(["git", "status", "--porcelain"])
    if not out.strip():
        log("No changes detected — Excel file is identical to last commit. Skipping push.")
        return False

    # 6. Commit
    commit_msg = f"data: update FEMS Excel {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if not dry_run:
        code, out = run(["git", "commit", "-m", commit_msg])
        if code != 0:
            log(f"git commit failed: {out}", "ERR")
            sys.exit(1)
        log(f"Committed: {commit_msg}")
    else:
        log(f"[DRY RUN] Would commit: {commit_msg}")

    # 7. Push
    if not dry_run:
        # Build push command — use token if available for HTTPS
        if GITHUB_TOKEN:
            code, out = run(["git", "push", GIT_REMOTE, GIT_BRANCH])
        else:
            code, out = run(["git", "push", GIT_REMOTE, GIT_BRANCH])

        if code != 0:
            log(f"git push failed: {out}", "ERR")
            log("Make sure you're authenticated: run  git config credential.helper store  or set GITHUB_TOKEN in .env", "WARN")
            sys.exit(1)
        log("Pushed to GitHub ✓")
        log("Streamlit Community Cloud will detect the push and refresh within ~1 minute.")
    else:
        log("[DRY RUN] Would push to GitHub")

    return True


# ─────────────────────────────────────────────
# WINDOWS TASK SCHEDULER HELPER
# ─────────────────────────────────────────────
def print_scheduler_instructions():
    script_path = Path(__file__).resolve()
    python_path = sys.executable
    excel_path  = r"C:\Path\To\Your\GACC_Percentile_Chart_FEMS.xlsx"

    print("""
╔══════════════════════════════════════════════════════════════╗
║  Windows Task Scheduler — Automated Daily Update             ║
╚══════════════════════════════════════════════════════════════╝

Option A: Task Scheduler GUI
─────────────────────────────
1. Open Task Scheduler → Create Basic Task
2. Name: "GACC Dashboard Update"
3. Trigger: Daily → set time (e.g. 06:00 AM)
4. Action: Start a program
   Program: """ + python_path + """
   Arguments: """ + str(script_path) + """ --file """ + excel_path + """
5. Finish

Option B: PowerShell (run as admin to register task)
──────────────────────────────────────────────────────
""")
    ps = f"""
$Action  = New-ScheduledTaskAction -Execute '{python_path}' `
           -Argument '{script_path} --file "{excel_path}"'
$Trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "GACC Dashboard Update" `
  -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Highest
"""
    print(ps)

    print("""
Option C: Mac/Linux cron (crontab -e)
───────────────────────────────────────
# Run every day at 6 AM
0 6 * * * """ + python_path + " " + str(script_path) + " --file /path/to/GACC_Percentile_Chart_FEMS.xlsx\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Push updated FEMS Excel to GitHub")
    parser.add_argument("--file", type=Path, default=REPO_DIR / EXCEL_NAME,
                        help="Path to the new Excel file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without making changes")
    parser.add_argument("--scheduler", action="store_true",
                        help="Print Task Scheduler / cron setup instructions")
    args = parser.parse_args()

    if args.scheduler:
        print_scheduler_instructions()
        sys.exit(0)

    log("═" * 50)
    log("GACC Dashboard — Data Update Script")
    log("═" * 50)
    changed = update_data(args.file, dry_run=args.dry_run)
    if changed:
        log("Update complete! Dashboard will refresh shortly.")
    log("Done.")
