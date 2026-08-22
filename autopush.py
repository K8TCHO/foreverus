#!/usr/bin/env python3
"""
ForeverUs Auto-Push Script
===========================
Watch index.html for changes, auto-commit + push to main + gh-pages.

Usage:
  python autopush.py                    # Watch mode (default)
  python autopush.py --once             # Single push (no watch)
  python autopush.py --message "V26"    # Custom commit message
  python autopush.py --repo /path/to    # Custom repo path

Requirements:
  - Git configured with remote 'origin'
  - SSH key or credential helper set up
"""

import os
import sys
import time
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────
REPO_PATH = r"C:\Users\k8t0\Desktop\isaac-victoria"
FILE_WATCH = "index.html"
POLL_INTERVAL = 2  # seconds between checks
MAX_RETRIES = 3
REMOTE = "origin"
BRANCHES = ("main", "gh-pages")
# ─────────────────────────────────────────────────────────────────


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    colors = {"INFO": "\033[36m", "OK": "\033[32m", "ERR": "\033[31m", "WARN": "\033[33m"}
    reset = "\033[0m"
    color = colors.get(level, "")
    print(f"{color}[{ts}] [{level}] {msg}{reset}")


def run(cmd, cwd=None, check=True):
    """Run a shell command and return (stdout, returncode)."""
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd or REPO_PATH,
            capture_output=True, text=True, timeout=30
        )
        if check and r.returncode != 0:
            log(f"Command failed: {cmd}", "ERR")
            log(f"  stderr: {r.stderr.strip()}", "ERR")
            return None, r.returncode
        return r.stdout.strip(), 0
    except subprocess.TimeoutExpired:
        log(f"Timeout: {cmd}", "ERR")
        return None, -1
    except Exception as e:
        log(f"Error: {e}", "ERR")
        return None, -1


def get_file_hash(filepath):
    """Get mtime + size as change fingerprint."""
    try:
        st = os.stat(filepath)
        return f"{st.st_mtime_ns}_{st.st_size}"
    except:
        return None


def get_version(filepath):
    """Extract VER from index.html."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if "var VER" in line:
                    return line.split("'")[1] if "'" in line else "unknown"
    except:
        pass
    return "unknown"


def validate(filepath):
    """Quick validation before push."""
    errors = []

    # 1. Check syntax with node --check
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        import re
        script_match = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
        if script_match:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False)
            tmp.write(script_match.group(1))
            tmp.close()
            r = subprocess.run(
                ["node", "--check", tmp.name],
                capture_output=True, text=True, timeout=10
            )
            os.unlink(tmp.name)
            if r.returncode != 0:
                errors.append(f"JS syntax error: {r.stderr.strip()[:200]}")
    except Exception as e:
        errors.append(f"Validation error: {e}")

    # 2. Check for bad chars (mojibake)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        bad_patterns = ["\u00c3\u0083", "\u00c2"]
        for bp in bad_patterns:
            if bp in content:
                errors.append(f"Bad chars detected: {repr(bp)}")
    except:
        pass

    # 3. Check VER exists
    ver = get_version(filepath)
    if ver == "unknown":
        errors.append("VER not found in file")

    return errors, ver


def git_push(filepath):
    """Commit + push to main, then sync + push to gh-pages."""
    ver = get_version(filepath)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"{ver} - auto-push ({timestamp})"

    log(f"Deploying {ver}...")

    # Validate first
    errors, ver = validate(filepath)
    if errors:
        for e in errors:
            log(f"VALIDATION FAILED: {e}", "ERR")
        return False

    # Stage
    out, rc = run(f'git add "{FILE_WATCH}"')
    if rc != 0:
        return False

    # Check if there's actually a change
    out, rc = run("git diff --cached --stat")
    if out and "0 files changed" in out:
        log("No changes to commit", "WARN")
        return True

    # Commit on main
    out, rc = run(f'git commit -m "{msg}"')
    if rc != 0:
        log("Nothing to commit or commit failed", "WARN")
        return True

    log("Committed on main", "OK")

    # Push main
    for attempt in range(MAX_RETRIES):
        out, rc = run(f"git push {REMOTE} main")
        if rc == 0:
            log("Pushed main", "OK")
            break
        log(f"Push attempt {attempt+1} failed, retrying...", "WARN")
        time.sleep(2)
    else:
        log("Failed to push main after retries", "ERR")
        return False

    # Sync to gh-pages
    out, rc = run("git checkout gh-pages")
    if rc != 0:
        log("Failed to checkout gh-pages", "ERR")
        return False

    out, rc = run(f"git checkout main -- {FILE_WATCH}")
    if rc != 0:
        log("Failed to copy file to gh-pages", "ERR")
        run("git checkout main")
        return False

    out, rc = run(f'git commit -m "{msg} [gh-pages]"')
    if rc != 0 and "nothing to commit" not in (out or ""):
        log("Nothing to commit on gh-pages (normal)", "WARN")

    # Push gh-pages
    for attempt in range(MAX_RETRIES):
        out, rc = run(f"git push {REMOTE} gh-pages")
        if rc == 0:
            log("Pushed gh-pages", "OK")
            break
        log(f"gh-pages push attempt {attempt+1} failed, retrying...", "WARN")
        time.sleep(2)
    else:
        log("Failed to push gh-pages after retries", "ERR")
        run("git checkout main")
        return False

    # Return to main
    run("git checkout main")

    log(f"Deploy complete: {ver}", "OK")
    return True


def watch_mode(filepath):
    """Watch file for changes and auto-push."""
    log(f"Watching {FILE_WATCH} for changes (poll every {POLL_INTERVAL}s)")
    log(f"Repository: {REPO_PATH}")
    log("Press Ctrl+C to stop\n")

    last_hash = get_file_hash(filepath)
    log(f"Current fingerprint: {last_hash}")

    while True:
        try:
            time.sleep(POLL_INTERVAL)
            current_hash = get_file_hash(filepath)

            if current_hash and current_hash != last_hash:
                log(f"Change detected! ({last_hash[:16]}... -> {current_hash[:16]}...)")
                last_hash = current_hash

                # Small delay to let file finish writing
                time.sleep(0.5)
                current_hash = get_file_hash(filepath)
                if current_hash != last_hash:
                    last_hash = current_hash
                    continue

                success = git_push(filepath)
                if success:
                    last_hash = get_file_hash(filepath)
                else:
                    log("Push failed, will retry on next change", "ERR")

        except KeyboardInterrupt:
            log("\nStopped watching.", "INFO")
            break
        except Exception as e:
            log(f"Watch error: {e}", "ERR")
            time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="ForeverUs Auto-Push")
    parser.add_argument("--once", action="store_true", help="Single push, no watch")
    parser.add_argument("--repo", type=str, help="Repository path")
    parser.add_argument("--message", type=str, help="Custom commit message")
    args = parser.parse_args()

    if args.repo:
        global REPO_PATH
        REPO_PATH = args.repo

    filepath = os.path.join(REPO_PATH, FILE_WATCH)
    if not os.path.exists(filepath):
        log(f"File not found: {filepath}", "ERR")
        sys.exit(1)

    if args.once:
        success = git_push(filepath)
        sys.exit(0 if success else 1)
    else:
        watch_mode(filepath)


if __name__ == "__main__":
    main()
