#!/usr/bin/env python3
"""
gh_repo_scan.py - scan GitHub repos or local paths for leaked secrets (current files + git history).

Reuses the scanning engine from scan.py (same directory).

Usage:
    python gh_repo_scan.py --user octocat                      # all repos of a user
    python gh_repo_scan.py --user octocat --repo hello-world   # one repo
    python gh_repo_scan.py --repo octocat/hello-world          # same, owner/name form
    python gh_repo_scan.py --path ./my-project                 # local repo, folder or file
    python gh_repo_scan.py --path ./a --path ./b               # several local paths

    python gh_repo_scan.py --user octocat --token $GITHUB_TOKEN --jobs 8
    python gh_repo_scan.py --user octocat --no-history --min medium
    python gh_repo_scan.py --user octocat --include-forks --include-archived
    python gh_repo_scan.py --user octocat --json > report.json
    python gh_repo_scan.py --user octocat --repo 'api-*'       # glob on repo names

Modes (pick one):
    --user [--repo]   GitHub: all repos of USER, or only REPO (name, glob, or owner/name)
    --repo owner/name GitHub: a single repo, no --user needed
    --path            Local: file, folder, or git repo (repeatable). Cannot be mixed with --user/--repo.

Auth (GitHub modes):
    --token or env GITHUB_TOKEN. Without it you get 60 req/hour (API) and
    anonymous clones (only public repos).

Output:
    Printed live AND written to scan.log (change with --log). Exit code 1 if anything was found.

Requires:
    requests, git, and scan.py in the same folder.
"""
import argparse
import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    sys.exit("Please install requests:  pip install requests")


# ----------------------------------------------------------- load scan.py
def load_scanner():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "scan.py")
    if not os.path.exists(path):
        sys.exit(f"scan.py not found next to this script ({path}).")
    spec = importlib.util.spec_from_file_location("scan_engine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SCAN = load_scanner()


# ------------------------------------------------------------------ logger
class Logger:
    """Thread-safe: every message goes to the console AND the log file, whole blocks at a time."""

    def __init__(self, path, to_stderr=False):
        self.lock = threading.Lock()
        self.stream = sys.stderr if to_stderr else sys.stdout
        self.fh = open(path, "w", encoding="utf-8")
        self.tls = threading.local()

    def __call__(self, *parts):
        text = " ".join(str(p) for p in parts)
        stamp = time.strftime("%H:%M:%S")
        tag = getattr(self.tls, "repo", None)
        with self.lock:
            shown = f"[{tag}] {text}" if tag and "\n" not in text else text
            print(shown, file=self.stream, flush=True)
            for line in text.split("\n"):
                self.fh.write(f"{stamp} {('[' + tag + '] ') if tag else ''}{line}\n")
            self.fh.flush()

    def close(self):
        self.fh.close()


# -------------------------------------------------------- GitHub API layer
API = "https://api.github.com"


def api_headers(token):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "gh-repo-scan"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def list_repos(username, token=None, include_forks=False, include_archived=False):
    """Return the list of repos (dicts) for a user."""
    repos, page, headers = [], 1, api_headers(token)
    own = False
    if token:  # /users/<name>/repos only returns PUBLIC repos; /user/repos includes your private ones
        me = requests.get(f"{API}/user", headers=headers, timeout=30)
        own = me.status_code == 200 and me.json().get("login", "").lower() == username.lower()
    while True:
        if own:
            url = f"{API}/user/repos"
            params = {"per_page": 100, "page": page, "sort": "updated", "affiliation": "owner", "visibility": "all"}
        else:
            url = f"{API}/users/{username}/repos"
            params = {"per_page": 100, "page": page, "sort": "updated", "type": "owner"}
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 404:
            sys.exit(f"User '{username}' not found.")
        if r.status_code == 401:
            sys.exit("GitHub API returned 401 - bad or expired token.")
        if r.status_code != 200:
            sys.exit(f"GitHub API error {r.status_code}: {r.text[:300]}")
        batch = r.json()
        if not batch:
            break
        for repo in batch:
            if repo.get("fork") and not include_forks:
                continue
            if repo.get("archived") and not include_archived:
                continue
            repos.append(repo)
        page += 1
    return repos


def get_repo(owner, name, token=None):
    """Fetch one repo by exact name (works for forks/archived too - you asked for it explicitly)."""
    r = requests.get(f"{API}/repos/{owner}/{name}", headers=api_headers(token), timeout=30)
    if r.status_code == 404:
        sys.exit(f"Repo '{owner}/{name}' not found (private repos need a --token that can see them).")
    if r.status_code == 401:
        sys.exit("GitHub API returned 401 - bad or expired token.")
    if r.status_code != 200:
        sys.exit(f"GitHub API error {r.status_code}: {r.text[:300]}")
    return r.json()


# -------------------------------------------------------- local scan
def scan_local(path, no_history=False, include_ignored=False):
    """Scan a local file, folder or git repo with the engine from scan.py."""
    path = os.path.abspath(os.path.expanduser(path))
    fnd = SCAN.Findings()
    if not os.path.exists(path):
        return None, f"path not found: {path}"
    if os.path.isfile(path):
        rel = os.path.basename(path)
        if SCAN.SENSITIVE_NAMES.search(rel) and not SCAN.SAFE_NAMES.search(rel):
            fnd.file(rel, rel, "current")
        SCAN.scan_file(path, rel, fnd)
        return fnd, None

    if os.path.basename(path.rstrip(os.sep)) == ".git":
        path = os.path.dirname(path)
    inside = SCAN.git(path, "rev-parse", "--is-inside-work-tree")
    bare = SCAN.git(path, "rev-parse", "--is-bare-repository")
    is_bare = bare.stdout.strip() == "true"
    is_git = inside.stdout.strip() == "true" or is_bare
    if not is_git and os.path.isdir(os.path.join(path, ".git")):
        SCAN.warn(f"{path} has a .git folder but git cannot read it - history will NOT be scanned")
    if not is_bare:
        SCAN.scan_worktree(path, is_git, fnd, local=True, include_ignored=include_ignored)
    if is_git and not no_history:
        # unlike a fresh mirror clone, a local repo can hold unreachable commits (old force-pushes, resets)
        SCAN.scan_history(path, fnd, SCAN.unreachable_commits(path))
    elif not is_git:
        SCAN.info(f"{path} is not a git repo - history scan skipped")
    return fnd, None


# -------------------------------------------------------- per-repo scan
def scan_remote(url, no_history=False, include_ignored=False, token=None):
    """Mirror-clone `url` and scan it with the engine from scan.py."""
    tmp = tempfile.mkdtemp(prefix="ghscan_")
    fnd = SCAN.Findings()
    try:
        mirror = os.path.join(tmp, "mirror.git")
        work = os.path.join(tmp, "work")
        auth = []
        if token and url.startswith("https://"):
            b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            auth = ["-c", f"http.extraHeader=Authorization: Basic {b64}"]
        r = SCAN.run([*SCAN.GIT_BASE, *auth, "clone", "--quiet", "--mirror", url, mirror])
        if r.returncode != 0:
            err = r.stderr.strip()
            if token:
                err = err.replace(token, "***")
            return None, err[:300]

        r = SCAN.run([*SCAN.GIT_BASE, "clone", "--quiet", mirror, work])
        if r.returncode == 0:
            SCAN.scan_worktree(work, True, fnd, local=False, include_ignored=include_ignored)

        if not no_history:
            # A fresh --mirror clone only contains reachable objects, so `git fsck --unreachable`
            # (very slow on big repos) would find nothing. Skip it.
            SCAN.scan_history(mirror, fnd, [])

        return fnd, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Scan all repos of a GitHub user for leaked secrets.")
    ap.add_argument("--user", metavar="GITHUB_USER", help="GitHub username whose repos to scan")
    ap.add_argument("--repo", metavar="NAME",
                    help="only this repo of --user (name, glob like 'api-*', or owner/name)")
    ap.add_argument("--path", metavar="FILEPATH", action="append",
                    help="scan a local file, folder or git repo (repeatable)")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                    help="GitHub personal access token (or env GITHUB_TOKEN)")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--include-ignored", action="store_true")
    ap.add_argument("--include-forks", action="store_true")
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--show", action="store_true", help="print full secrets")
    ap.add_argument("--min", choices=["low", "medium", "high"], default="low")
    ap.add_argument("--json", action="store_true", help="JSON on stdout (text log goes to stderr + file)")
    ap.add_argument("--jobs", type=int, default=4, help="parallel repo scans (default 4)")
    ap.add_argument("--timeout", type=int, default=None,
                    help="max seconds per git command, 0 = unlimited (default 900, or env SCAN_TIMEOUT)")
    ap.add_argument("--log", default="scan.log", help="log file (default scan.log)")
    ap.add_argument("--version", action="version", version=f"gh_repo_scan (engine scan.py {SCAN.VERSION})")
    args = ap.parse_args()

    if args.path and (args.user or args.repo):
        ap.error("--path cannot be combined with --user/--repo")
    if not args.path and not args.user and not (args.repo and "/" in args.repo):
        ap.error("give --user (optionally with --repo), --repo owner/name, or --path")

    log = Logger(args.log, to_stderr=args.json)
    SCAN.warn = lambda m: log(f"[!] {m}")   # route engine messages through the logger too
    SCAN.info = lambda m: log(f"[i] {m}")
    if args.timeout is not None:
        SCAN.TIMEOUT = args.timeout
    os.environ["GIT_TERMINAL_PROMPT"] = "0"  # fail fast instead of hanging on a login prompt

    if not shutil.which("git"):
        sys.exit("git is required.")
    if not args.token:
        log("[!] No token - 60 API requests/hour and only public repos.")

    log(f"[*] scan engine: scan.py {SCAN.VERSION}  (git timeout: {SCAN.TIMEOUT or 'none'}s)")
    def remote_unit(repo):
        return {"name": repo["full_name"], "url": repo["html_url"], "private": repo.get("private", False),
                "clone_url": repo["clone_url"]}

    if args.path:
        units = [{"name": p, "url": os.path.abspath(os.path.expanduser(p)), "private": False, "path": p}
                 for p in args.path]
        log(f"[*] Local mode: {len(units)} path(s)")
    else:
        owner, repo_arg = args.user, args.repo
        if repo_arg and "/" in repo_arg:                       # owner/name form
            owner, repo_arg = repo_arg.split("/", 1)
            if args.user and args.user.lower() != owner.lower():
                sys.exit(f"--user '{args.user}' and --repo '{args.repo}' name different owners.")
        glob_chars = set("*?[")
        if repo_arg and not (glob_chars & set(repo_arg)):
            log(f"[*] Fetching {owner}/{repo_arg} ...")
            repos = [get_repo(owner, repo_arg, args.token)]
        else:
            log(f"[*] Listing repos for {owner} ...")
            repos = list_repos(owner, args.token, args.include_forks, args.include_archived)
            if repo_arg:
                import fnmatch
                repos = [r for r in repos if fnmatch.fnmatch(r["name"], repo_arg)
                         or fnmatch.fnmatch(f"{r['owner']['login']}/{r['name']}", repo_arg)]
        units = [remote_unit(r) for r in repos]

    if not units:
        log("Nothing to scan.")
        log.close()
        return 0

    min_conf = {"low": SCAN.LOW, "medium": SCAN.MED, "high": SCAN.HIGH}[args.min]
    total_n = len(units)
    jobs = max(1, min(args.jobs, total_n))
    log(f"[*] Scanning {total_n} target(s) with {jobs} parallel worker(s) ...")
    t0 = time.time()

    def scan_one(unit):
        log.tls.repo = unit["name"]             # tag every log line from this thread
        log("-> start")
        t = time.time()
        if "path" in unit:
            fnd, err = scan_local(unit["path"], args.no_history, args.include_ignored)
        else:
            fnd, err = scan_remote(unit["clone_url"], args.no_history, args.include_ignored, args.token)
        return unit, fnd, err, time.time() - t

    results, failed = [], []
    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(scan_one, u): u for u in units}
        for fut in as_completed(futures):
            done += 1
            name = futures[fut]["name"]
            try:
                unit, fnd, err, secs = fut.result()
            except Exception as e:  # noqa
                failed.append(name)
                log(f"[{done}/{total_n}] [!] {name}: unexpected error: {e!r}")
                continue
            if err:
                failed.append(name)
                log(f"[{done}/{total_n}] [!] {name}: scan error: {err}")
                continue
            items = fnd.report(args.show, min_conf)
            rec = {"repo": unit["name"], "url": unit["url"],
                   "private": unit["private"], "items": items}
            results.append(rec)
            log(f"[{done}/{total_n}] [done] {name}: {len(items)} finding(s) in {secs:.0f}s")
            if items:
                log(format_repo(rec))        # stream details right away

    log(format_summary(results, failed, time.time() - t0))

    if args.json:
        print(json.dumps(results, indent=2))

    log(f"[*] Log written to {os.path.abspath(args.log)}")
    log.close()
    return 1 if any(r["items"] for r in results) else 0


def format_repo(r):
    lines = [f"\n--- {r['repo']} ({r['url']}) ---"]
    for i in r["items"]:
        cur, hist = i["in_current_files"], i["in_history"]
        status = "STILL IN CURRENT FILES" if cur else "removed, but STILL IN GIT HISTORY"
        lines.append(f"  [{i['confidence']}] {i['rule']}")
        lines.append(f"    value  : {i['value']}")
        lines.append(f"    status : {status}")
        for label, locs in (("files  ", cur), ("history", hist)):
            if locs:
                more = f"  (+{len(locs) - 3} more)" if len(locs) > 3 else ""
                lines.append(f"    {label}: {', '.join(locs[:3])}{more}")
    return "\n".join(lines)


def format_summary(results, failed, secs):
    total = sum(len(r["items"]) for r in results)
    dirty = sorted((r for r in results if r["items"]), key=lambda r: r["repo"])
    out = [f"\n===== Summary over {len(results)} repo(s) in {secs:.0f}s: "
           f"{total} finding(s) in {len(dirty)} repo(s) ====="]
    for r in dirty:
        c = {k: sum(1 for i in r["items"] if i["confidence"] == k) for k in ("HIGH", "MEDIUM", "LOW")}
        vis = " (private)" if r["private"] else ""
        out.append(f"  {r['repo']}{vis}: {c['HIGH']} HIGH, {c['MEDIUM']} MEDIUM, {c['LOW']} LOW")
    if not dirty:
        out.append("  [OK] No findings.")
    if failed:
        out.append(f"\n  {len(failed)} target(s) FAILED / timed out and were NOT scanned: " + ", ".join(sorted(failed)))
    if dirty:
        out.append("\nNext: rotate/revoke every real secret first. Deleting the file is not enough,")
        out.append("because git history keeps it. Then purge history with git filter-repo or BFG.")
        out.append("Also consider making affected repos private until cleaned.")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())