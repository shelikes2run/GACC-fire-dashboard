"""
update_data.py
──────────────
Pushes updated dashboard files to GitHub to trigger a Streamlit Cloud refresh.

Files pushed:
  • gacc_climo_baseline.json  ← primary — climo thresholds the dashboard reads
  • GACC_Percentile_Chart_FEMS.xlsx  ← optional reference copy

Usage (manual):
    python update_data.py
    python update_data.py --json /path/to/gacc_climo_baseline.json
    python update_data.py --json /path/to/gacc_climo_baseline.json --excel /path/to/GACC_Percentile_Chart_FEMS.xlsx

Usage (dry run — shows what would happen, makes no changes):
    python update_data.py --dry-run

Usage (Windows Task Scheduler / cron setup instructions):
    python update_data.py --scheduler

Requirements:
    pip install requests python-dotenv
    (gitpython NOT required — uses subprocess git directly)
"""

import argparse
import os
import re
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
REPO_DIR    = Path(__file__).parent         # folder this script lives in
JSON_NAME   = 'gacc_climo_baseline.json'    # ← what the dashboard reads
EXCEL_NAME  = 'GACC_Percentile_Chart_FEMS.xlsx'
GIT_REMOTE  = 'origin'
GIT_BRANCH  = 'main'

# GitHub personal access token — set in .env file as GITHUB_TOKEN=ghp_xxxxx
# Used to embed credentials in HTTPS remote URL for token-based push.
# Not needed if you use SSH keys or have git credential manager configured.
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def log(msg: str, level: str = 'INFO'):
    ts     = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = {'INFO': '✅', 'WARN': '⚠️ ', 'ERR': '❌'}.get(level, '  ')
    print(f'[{ts}] {prefix} {msg}')


def run(cmd: list, cwd: Path = REPO_DIR) -> tuple:
    """Run a shell command, return (returncode, combined_output)."""
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def _inject_token_in_remote(token: str) -> bool:
    """
    Temporarily rewrite the remote URL to embed the GitHub token so that
    `git push` succeeds without a credential prompt.

    Remote URL is restored to the original (token-free) form afterwards.
    Returns True if the URL was patched, False if SSH or already has token.
    """
    rc, url = run(['git', 'remote', 'get-url', GIT_REMOTE])
    if rc != 0 or not url:
        return False

    # Only patch HTTPS URLs without an existing token
    if not url.startswith('https://') or '@' in url:
        return False

    # Insert token:  https://github.com/...  →  https://TOKEN@github.com/...
    patched = url.replace('https://', f'https://{token}@')
    run(['git', 'remote', 'set-url', GIT_REMOTE, patched])
    return True


def _restore_remote(original_url: str):
    """Remove embedded token from remote URL after push."""
    run(['git', 'remote', 'set-url', GIT_REMOTE, original_url])


# ─────────────────────────────────────────────
# MAIN UPDATE FUNCTION
# ─────────────────────────────────────────────
def update_data(json_src: Path, excel_src: Path | None = None,
                dry_run: bool = False) -> bool:
    """
    Copy updated files into the repo, commit, and push.

    Parameters
    ----------
    json_src  : path to gacc_climo_baseline.json (required)
    excel_src : path to GACC_Percentile_Chart_FEMS.xlsx (optional)
    dry_run   : if True, print what would happen but make no changes
    """
    log('═' * 50)
    log('GACC Dashboard — Data Update Script')
    log('═' * 50)

    # 1. Validate source files
    if not json_src.exists():
        log(f'JSON not found: {json_src}', 'ERR')
        log('Run GACC_Climo_Download.ipynb first to generate gacc_climo_baseline.json', 'WARN')
        sys.exit(1)

    if excel_src and not excel_src.exists():
        log(f'Excel not found: {excel_src} — skipping Excel update', 'WARN')
        excel_src = None

    files_to_stage = []

    # 2. Copy files into repo
    json_dest  = REPO_DIR / JSON_NAME
    if not dry_run:
        shutil.copy2(json_src, json_dest)
        log(f'Copied {json_src.name} → {json_dest}')
    else:
        log(f'[DRY RUN] Would copy {json_src} → {json_dest}')
    files_to_stage.append(JSON_NAME)

    if excel_src:
        excel_dest = REPO_DIR / EXCEL_NAME
        if not dry_run:
            shutil.copy2(excel_src, excel_dest)
            log(f'Copied {excel_src.name} → {excel_dest}')
        else:
            log(f'[DRY RUN] Would copy {excel_src} → {excel_dest}')
        files_to_stage.append(EXCEL_NAME)

    # 3. Git pull (stay in sync with remote before committing)
    log('Pulling latest from remote...')
    code, out = run(['git', 'pull', GIT_REMOTE, GIT_BRANCH])
    if code != 0:
        log(f'git pull warning (continuing): {out}', 'WARN')

    # 4. Stage files
    for fname in files_to_stage:
        code, out = run(['git', 'add', fname])
        if code != 0:
            log(f'git add {fname} failed: {out}', 'ERR')
            sys.exit(1)
    log(f'Staged: {", ".join(files_to_stage)}')

    # 5. Check if there are actual changes to commit
    code, out = run(['git', 'status', '--porcelain'])
    if not out.strip():
        log('No changes detected — files are identical to last commit. Nothing to push.')
        return False

    # 6. Commit
    ts         = datetime.now().strftime('%Y-%m-%d %H:%M')
    commit_msg = f'data: update climo baseline + reference {ts}'
    if not dry_run:
        code, out = run(['git', 'commit', '-m', commit_msg])
        if code != 0:
            log(f'git commit failed: {out}', 'ERR')
            sys.exit(1)
        log(f'Committed: {commit_msg}')
    else:
        log(f'[DRY RUN] Would commit: {commit_msg}')
        return True

    # 7. Push
    # If GITHUB_TOKEN is set, temporarily embed it in the remote URL for auth.
    # This is the correct way to use a PAT with HTTPS — the other approach
    # (passing via env var or --token flag) is not supported by git directly.
    original_url = None
    patched      = False
    if GITHUB_TOKEN:
        rc, url      = run(['git', 'remote', 'get-url', GIT_REMOTE])
        original_url = url if rc == 0 else None
        patched      = _inject_token_in_remote(GITHUB_TOKEN)
        if patched:
            log('Using GITHUB_TOKEN for push authentication')

    try:
        code, out = run(['git', 'push', GIT_REMOTE, GIT_BRANCH])
    finally:
        # Always restore clean remote URL (never leave token in git config)
        if patched and original_url:
            _restore_remote(original_url)

    if code != 0:
        log(f'git push failed: {out}', 'ERR')
        log('Troubleshooting:', 'WARN')
        log('  • SSH: ensure ~/.ssh/id_rsa is added to GitHub', 'WARN')
        log('  • HTTPS: set GITHUB_TOKEN=ghp_xxx in .env file', 'WARN')
        log('  • Or run: git config credential.helper store', 'WARN')
        sys.exit(1)

    log('✓ Pushed to GitHub')
    log('Streamlit Cloud will detect the push and refresh within ~1 minute.')
    return True


# ─────────────────────────────────────────────
# WINDOWS TASK SCHEDULER HELPER
# ─────────────────────────────────────────────
def print_scheduler_instructions():
    script_path = Path(__file__).resolve()
    python_path = sys.executable
    json_path   = r'C:\Path\To\Your\gacc_climo_baseline.json'

    print("""
╔══════════════════════════════════════════════════════════════╗
║  Automated Daily Update — Setup Instructions                  ║
╚══════════════════════════════════════════════════════════════╝

NOTE: Run GACC_Climo_Download.ipynb once manually first to generate
      gacc_climo_baseline.json. This script only pushes that file
      to GitHub — it does not regenerate it.

──────────────────────────────────────────────────────────────
Option A: Windows Task Scheduler (GUI)
──────────────────────────────────────────────────────────────
1. Open Task Scheduler → Create Basic Task
2. Name: "GACC Dashboard Push"
3. Trigger: Daily → set time (e.g. 07:00 AM, after notebook runs)
4. Action: Start a program
""")
    print(f"   Program : {python_path}")
    print(f"   Arguments: {script_path} --json \"{json_path}\"")
    print("""
──────────────────────────────────────────────────────────────
Option B: PowerShell (run as admin to register)
──────────────────────────────────────────────────────────────""")
    print(f"""
$Action  = New-ScheduledTaskAction \\
           -Execute '{python_path}' \\
           -Argument '{script_path} --json "{json_path}"'
$Trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "GACC Dashboard Push" \\
  -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Highest
""")
    print("""──────────────────────────────────────────────────────────────
Option C: Mac/Linux cron (crontab -e)
──────────────────────────────────────────────────────────────""")
    print(f"# Run every day at 7 AM")
    print(f"0 7 * * * {python_path} {script_path} --json /path/to/gacc_climo_baseline.json\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Push updated gacc_climo_baseline.json to GitHub')
    parser.add_argument(
        '--json', type=Path,
        default=REPO_DIR / JSON_NAME,
        help=f'Path to gacc_climo_baseline.json (default: {JSON_NAME} in repo)')
    parser.add_argument(
        '--excel', type=Path,
        default=None,
        help='Path to GACC_Percentile_Chart_FEMS.xlsx (optional)')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Print what would happen without making changes')
    parser.add_argument(
        '--scheduler', action='store_true',
        help='Print Task Scheduler / cron setup instructions')
    args = parser.parse_args()

    if args.scheduler:
        print_scheduler_instructions()
        sys.exit(0)

    changed = update_data(args.json, args.excel, dry_run=args.dry_run)
    if changed:
        log('Update complete — dashboard will refresh shortly.')
    log('Done.')
