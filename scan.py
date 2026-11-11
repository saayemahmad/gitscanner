#!/usr/bin/env python3
"""
scan.py - find leaked secrets in a git repo (URL) or a local directory.

Usage:
    python scan.py https://github.com/user/repo
    python scan.py git@github.com:user/private-repo.git
    python scan.py /path/to/local/repo
    python scan.py . --no-history        # current files only
    python scan.py ~/proj --include-ignored  # also scan git-ignored files (e.g. local .env)
    python scan.py ./config.py           # a single file
    python scan.py <target> --show       # print full secret values
    python scan.py <target> --min medium # hide LOW-confidence findings
    python scan.py <target> --json       # machine-readable output

What it checks
  * ~60 known token/key formats (cloud, git hosts, payments, AI, chat, ...)
  * Secret-looking assignments in any format: KEY=val, "key": "val", key: val,
    define('KEY','val'), --password=val ... (including weak passwords)
  * EVERY real value inside .env files
  * High-entropy quoted strings
  * Sensitive files (.env, private keys, tfstate, .pgpass ...)
  * Full git history: all branches, tags, stashes, GitHub PR refs (single
    login prompt) and unreachable (dangling) commits in local repos
  * Credentials stored in .git/config remote URLs

Confidence: HIGH = known format / very likely real, MEDIUM = probable,
LOW = weak password or entropy-only (review manually).
Exit code: 0 clean, 1 findings, 2 error.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

VERSION = "3.4 (telegram URL rule, 2026-11-05)"
HIGH, MED, LOW = 3, 2, 1
CONF = {HIGH: "HIGH", MED: "MEDIUM", LOW: "LOW"}
R = re.compile

# ------------------------------------------------------------------ rules
# (name, regex, confidence, group-with-secret)
RULES = [
    ("AWS access key ID", R(r"(?<![A-Za-z0-9])(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}(?![A-Za-z0-9])"), HIGH, 0),
    ("AWS secret key", R(r"(?i)aws.{0,25}?(?:secret|private).{0,25}?['\"=: ]+([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])"), HIGH, 1),
    ("GitHub token", R(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}(?![A-Za-z0-9])"), HIGH, 0),
    ("GitHub fine-grained token", R(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{50,}(?![A-Za-z0-9])"), HIGH, 0),
    ("GitLab token", R(r"(?<![A-Za-z0-9])gl(?:pat|dt|rt|ptt|cbt|soat)-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Telegram bot token", R(r"(?<!\d)\d{6,12}(?::|%3[Aa])[A-Za-z0-9_-]{30,45}(?![A-Za-z0-9])"), HIGH, 0),
    ("Telegram bot token (API URL)", R(r"(?i)api\.telegram\.org[\\/]+(?:file[\\/]+)?bot(\d{4,}(?::|%3A)[A-Za-z0-9_-]{16,})"), HIGH, 1),
    ("Slack token", R(r"(?<![A-Za-z0-9])xox[abprso]-[A-Za-z0-9-]{10,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Slack webhook", R(r"https://hooks\.slack\.com/(?:services|workflows)/[A-Za-z0-9/_-]{20,}"), HIGH, 0),
    ("Discord webhook", R(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}"), HIGH, 0),
    ("Discord bot token", R(r"(?<![A-Za-z0-9])[MNO][A-Za-z\d]{23,25}\.[\w-]{6}\.[\w-]{27,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Google API key", R(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9])"), HIGH, 0),
    ("Google OAuth client secret", R(r"(?<![A-Za-z0-9])GOCSPX-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Google OAuth access token", R(r"(?<![A-Za-z0-9])ya29\.[0-9A-Za-z_-]{30,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Firebase/FCM server key", R(r"(?<![A-Za-z0-9])AAAA[A-Za-z0-9_-]{7}:[A-Za-z0-9_-]{140,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Stripe live key", R(r"(?<![A-Za-z0-9])[sr]k_live_[0-9a-zA-Z]{20,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Stripe test key", R(r"(?<![A-Za-z0-9])[sr]k_test_[0-9a-zA-Z]{20,}(?![A-Za-z0-9])"), MED, 0),
    ("Stripe webhook secret", R(r"(?<![A-Za-z0-9])whsec_[A-Za-z0-9]{24,}(?![A-Za-z0-9])"), HIGH, 0),
    ("OpenAI API key", R(r"(?<![A-Za-z0-9])sk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Anthropic API key", R(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9])"), HIGH, 0),
    ("HuggingFace token", R(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{34,}(?![A-Za-z0-9])"), HIGH, 0),
    ("npm token", R(r"(?<![A-Za-z0-9])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"), HIGH, 0),
    ("PyPI token", R(r"(?<![A-Za-z0-9])pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Twilio API key", R(r"(?<![A-Za-z0-9])SK[0-9a-fA-F]{32}(?![A-Za-z0-9])"), HIGH, 0),
    ("SendGrid key", R(r"(?<![A-Za-z0-9])SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Mailgun key", R(r"(?<![A-Za-z0-9])key-[0-9a-f]{32}(?![A-Za-z0-9])"), HIGH, 0),
    ("Mailchimp key", R(r"(?<![A-Za-z0-9])[0-9a-f]{32}-us\d{1,2}(?![A-Za-z0-9])"), HIGH, 0),
    ("DigitalOcean token", R(r"(?<![A-Za-z0-9])do[por]_v1_[a-f0-9]{64}(?![A-Za-z0-9])"), HIGH, 0),
    ("Shopify token", R(r"(?<![A-Za-z0-9])shp(?:at|ca|pa|ss)_[a-fA-F0-9]{32}(?![A-Za-z0-9])"), HIGH, 0),
    ("Square token", R(r"(?<![A-Za-z0-9])sq0(?:atp|csp)-[A-Za-z0-9_-]{22,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Postman key", R(r"(?<![A-Za-z0-9])PMAK-[a-f0-9]{24}-[a-f0-9]{34}(?![A-Za-z0-9])"), HIGH, 0),
    ("Notion token", R(r"(?<![A-Za-z0-9])(?:secret_[A-Za-z0-9]{43}|ntn_[A-Za-z0-9]{40,})(?![A-Za-z0-9])"), HIGH, 0),
    ("Linear key", R(r"(?<![A-Za-z0-9])lin_api_[A-Za-z0-9]{40}(?![A-Za-z0-9])"), HIGH, 0),
    ("Facebook access token", R(r"(?<![A-Za-z0-9])EAA[A-Za-z0-9]{60,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Twitter bearer token", R(r"(?<![A-Za-z0-9])AAAAAAAAAAAAAAAAAAAAA[A-Za-z0-9%]{30,}(?![A-Za-z0-9])"), HIGH, 0),
    ("Azure storage key", R(r"AccountKey=([A-Za-z0-9+/=]{40,})"), HIGH, 1),
    ("Sentry DSN", R(r"https://[a-f0-9]{32}@[\w.-]+/\d+"), MED, 0),
    ("Private key block", R(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"), HIGH, 0),
    ("JWT", R(r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9])"), MED, 0),
    ("Basic auth header", R(r"(?i)authorization['\"]?\s*[:=]\s*['\"]?basic\s+([A-Za-z0-9+/=]{12,})"), MED, 1),
    ("Bearer token", R(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{20,})"), MED, 1),
    ("Credentials in URL", R(r"(?<![A-Za-z0-9])[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:([^\s/@'\"]{3,})@[^\s'\"]+"), HIGH, 1),
]

PLACEHOLDER = R(
    r"(?i)^(?:x{3,}|\*{3,}|\.{3,}|<[^>]*>|\$\{[^}]*\}|\{\{.*\}\}|%\(.*\)s|your[\w\s.-]*|"
    r"my[_-]?(?:secret|password|token|api[_-]?key)\w*|change[_-]?me\w*|replace[_-]?me\w*|"
    r"insert[\w\s-]*|enter[\w\s-]*|put[_-]?[\w-]*here|example\w*|placeholder\w*|dummy\w*|sample\w*|"
    r"none|null|nil|undefined|true|false|todo|tbd|redacted\w*|secret|password|passwd|pass|token|"
    r"string|required|optional|empty|1234567?8?9?0?|abcdefg?h?i?j?|test|testing|foo|bar|foobar|default|0{4,})$"
)
REFERENCE = R(
    r"(?i)^(?:[\$\{<@%]|https?://|\.{0,2}/|~/|process\.env|os\.(?:environ|getenv)|getenv|env\(|env\[|"
    r"config\.|settings\.|self\.|this\.|args\.|request\.|params\[|ENV\[|System\.getenv|Environment\.|secrets?\.)"
)
CALL = R(r"^[\w.]+\(.*\)$")

KEY_RE = R(
    r"(?i)pass(?:word|wd|phrase)|(?<![a-z])pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|[_-]key$|(?<![a-z])auth(?![a-z])|credential|(?<![a-z])creds?(?![a-z])|signing|"
    r"(?<![a-z])salt(?![a-z])|bearer|jwt|(?<![a-z])otp(?![a-z])|(?<![a-z])dsn(?![a-z])|encryption|master[_-]?key"
)
CAMEL_KEY = R(r"[a-z]Key$")
STRONG_KEY = R(r"(?i)pass(?:word|wd|phrase)|(?<![a-z])pwd|secret")
NAME_EXCL = R(
    r"(?i)tokeniz|(?:max|min|num|total|prompt|completion|input|output)_?tokens|"
    r"token_?(?:count|limit|type|ttl|expir\w*|length|len|id|name|url|uri|endpoint|field|header|prefix|path|file|size)|"
    r"csrf|xsrf|public|primary|foreign|sort_?key|cache_?key|partition|"
    r"[_-]?(?:path|file|name|url|uri|id|type|header|length|size|field|prompt|label|hint|placeholder|message|msg|"
    r"text|title|expires?|ttl|timeout|count|env|var|ref|regex|pattern|format|algorithm|alg|mode|scheme|class|param|input)$"
)

# key = value, "key": "value", key: value, key => value, key := value
ASSIGN = R(
    r"""(?P<name>[A-Za-z_][\w.\-]{0,80})["'`]?\s*(?::=|=>|=|:)\s*"""
    r"""(?:"(?P<dq>[^"\n]{6,})"|'(?P<sq>[^'\n]{6,})'|`(?P<bt>[^`\n]{6,})`|(?P<raw>[^\s"'`,;]{6,}))"""
)
# define('DB_PASSWORD', 'x')  /  put("password", "x")
COMMA_ASSIGN = R(
    r"""["'](?P<name>[A-Za-z_][\w.\-]{2,80})["']\s*,\s*(?:"(?P<dq>[^"\n]{6,})"|'(?P<sq>[^'\n]{6,})')"""
)
ENV_LINE = R(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(.*?)\s*$")
BENIGN_ENV_KEY = R(r"(?i)(?:^|_)(?:host|hostname|port|env|environment|mode|level|debug|name|url|uri|region|domain|path|dir|file|timeout|log\w*)$")
BENIGN_ENV_VAL = R(
    r"(?i)^(?:\d{1,6}|true|false|yes|no|on|off|localhost|127\.0\.0\.1|0\.0\.0\.0|development|production|staging|"
    r"dev|prod|test|debug|info|warn|warning|error|utf-?8|https?://[^@]*|/[\w./-]*)$"
)
BLOB = R(r"""["'`]([A-Za-z0-9+/_\-=]{24,})["'`]""")

SENSITIVE_NAMES = R(
    r"(?i)(?:^|/)(?:\.env(?:\.[\w.-]+)?|[\w.-]+\.env|id_(?:rsa|dsa|ecdsa|ed25519)|"
    r"[\w.-]+\.(?:pem|p12|pfx|jks|keystore|ppk|p8|key)|credentials(?:\.json)?|service[-_]?account[\w.-]*\.json|"
    r"\.npmrc|\.pypirc|\.netrc|\.pgpass|\.my\.cnf|\.htpasswd|\.git-credentials|\.dockercfg|keystore\.properties|"
    r"terraform\.tfstate(?:\.backup)?|[\w.-]+\.tfvars|secrets?\.(?:ya?ml|json|toml))$"
)
SAFE_NAMES = R(r"(?i)\.(?:example|sample|template|dist|tpl)$")
ENV_NAME = R(r"(?i)^(?:\.env(?:\.[\w.-]+)?|[\w.-]+\.env)$")

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".vscode", ".next", "vendor"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".mp3", ".mp4", ".mov",
            ".woff", ".woff2", ".ttf", ".eot", ".so", ".dll", ".exe", ".class", ".jar", ".apk", ".svg", ".map", ".lock"}
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "composer.lock", "cargo.lock", "go.sum"}
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php", ".cs", ".c", ".cpp", ".h", ".rs",
            ".kt", ".swift", ".scala", ".dart", ".vue"}
MAX_SIZE = 5_000_000


# ---------------------------------------------------------------- helpers
def entropy(s):
    if not s:
        return 0.0
    return -sum((s.count(c) / len(s)) * math.log2(s.count(c) / len(s)) for c in set(s))


def redact(s, show):
    if show:
        return s
    return "*" * len(s) if len(s) <= 8 else s[:4] + "*" * min(len(s) - 4, 12)


GIT_BASE = ["git", "-c", "core.quotepath=off", "-c", "safe.directory=*"]


def warn(msg):
    print(f"[!] {msg}", file=sys.stderr)


def info(msg):
    print(f"[i] {msg}", file=sys.stderr)


TIMEOUT = int(os.environ.get("SCAN_TIMEOUT", "900"))  # seconds per git command (0 = no limit)


def run(cmd, cwd=None, timeout=None):
    timeout = TIMEOUT or None if timeout is None else timeout
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", "git not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout}s")


def git(root, *args):
    return run([*GIT_BASE, *args], cwd=root)


def skip_file(path):
    base = os.path.basename(path).lower()
    return (os.path.splitext(base)[1] in SKIP_EXT or base in SKIP_NAMES
            or base.endswith((".min.js", ".min.css")))


def is_code(path):
    return os.path.splitext(path)[1].lower() in CODE_EXT


def is_envfile(path):
    base = os.path.basename(path)
    return bool(ENV_NAME.match(base)) and not SAFE_NAMES.search(base)


# ------------------------------------------------------------ line scanner
def check_assignment(name, val, out, found):
    if not (KEY_RE.search(name) or CAMEL_KEY.search(name)) or NAME_EXCL.search(name):
        return
    val = val.strip()
    if len(val) < 6 or re.search(r"\s", val) or PLACEHOLDER.match(val) or REFERENCE.match(val) or CALL.match(val):
        return
    if re.sub(r"[^a-z0-9]", "", val.lower()) == re.sub(r"[^a-z0-9]", "", name.lower()):
        return
    if any(val in s or s in val for s in found):
        return
    strong = bool(STRONG_KEY.search(name))
    if not strong and re.fullmatch(r"[A-Za-z]+", val) and (val.islower() or val.isupper()):
        return  # a plain word, not a credential
    e, n = entropy(val), len(val)
    if e >= 3.5 and n >= 16:
        conf, label = HIGH, "Secret assignment"
    elif e >= 2.8 or (n >= 8 and re.search(r"[\d\W]", val)):
        conf, label = MED, "Secret assignment"
    elif strong:
        conf, label = LOW, "Weak/simple password"
    else:
        return
    out.append((f"{label} ({name})", val, conf))
    found.add(val)


def scan_line(line, path=""):
    """Return [(rule, secret, confidence)] for one line of text."""
    out = []
    line = line[:200_000]
    for name, rx, conf, grp in RULES:
        for m in rx.finditer(line):
            secret = m.group(grp)
            if not secret:
                continue
            if name == "Credentials in URL" and (PLACEHOLDER.match(secret) or secret[0] in "${<%"):
                continue
            if name.startswith("Telegram bot token"):
                tail = re.split(r":|%3[Aa]", secret, maxsplit=1)[1]
                if "ABC-DEF1234ghIkl-zyx57W2v1u123ew11" in tail:
                    continue  # the example token from Telegram's own docs
                if sum(bool(re.search(p, tail)) for p in (r"\d", r"[A-Z]", r"[a-z]")) < 2:
                    continue
            out.append((name, secret, conf))
    if len(line) > 2000:  # minified/data lines: known formats only
        return out
    found = {s for _, s, _ in out}

    if path and is_envfile(path):
        m = ENV_LINE.match(line)
        if m and not line.lstrip().startswith("#"):
            key, raw = m.groups()
            if raw[:1] in "\"'" and raw[-1:] == raw[:1] and len(raw) >= 2:
                val = raw[1:-1]
            else:
                val = re.split(r"\s+#", raw)[0].strip()
            secretish = bool(KEY_RE.search(key) or CAMEL_KEY.search(key))
            if (len(val) >= 4 and not PLACEHOLDER.match(val) and not BENIGN_ENV_VAL.match(val)
                    and not (BENIGN_ENV_KEY.search(key) and not secretish)
                    and not any(val in s or s in val for s in found)
                    and (secretish or len(val) >= 8 or entropy(val) >= 2.5)):
                conf = HIGH if secretish and len(val) >= 16 and entropy(val) >= 3.5 else MED
                out.append((f"Value in env file ({key})", val, conf))
                found.add(val)

    for m in ASSIGN.finditer(line):
        val = m.group("dq") or m.group("sq") or m.group("bt")
        if val is None:
            if is_code(path):
                continue  # unquoted value in source code is a variable, not a literal
            val = m.group("raw").rstrip(")}]>")
        check_assignment(m.group("name"), val, out, found)
    for m in COMMA_ASSIGN.finditer(line):
        check_assignment(m.group("name"), m.group("dq") or m.group("sq"), out, found)

    if not re.search(r"integrity|sha(?:256|512)-|data:image|base64,", line):
        for m in BLOB.finditer(line):
            s = m.group(1)
            e = entropy(s)
            if (re.search(r"[a-z]", s) and re.search(r"[A-Z]", s) and re.search(r"\d", s)
                    and ((e >= 4.3 and len(s) >= 24) or (e >= 4.0 and len(s) >= 32))
                    and not any(s in x or x in s for x in found)):
                out.append(("High-entropy string", s, LOW))
                found.add(s)
    return out


# --------------------------------------------------------------- findings
class Findings:
    def __init__(self):
        self.secrets, self.files = {}, {}

    @staticmethod
    def _loc(rec, src, where):
        lst = rec["locs"][src]
        if where not in lst and len(lst) < 50:
            lst.append(where)

    def secret(self, rule, value, conf, where, src):
        rec = self.secrets.setdefault(value, {"rule": rule, "conf": conf, "locs": {"current": [], "history": []}})
        if conf > rec["conf"]:
            rec["rule"], rec["conf"] = rule, conf
        self._loc(rec, src, where)

    def file(self, path, where, src):
        rec = self.files.setdefault(path, {"locs": {"current": [], "history": []}})
        self._loc(rec, src, where)

    def report(self, show, min_conf):
        items = []
        for value, r in self.secrets.items():
            if r["conf"] >= min_conf:
                items.append({"type": "secret", "rule": r["rule"], "confidence": CONF[r["conf"]], "_c": r["conf"],
                              "value": redact(value, show), "in_current_files": r["locs"]["current"],
                              "in_history": r["locs"]["history"]})
        if MED >= min_conf:
            for path, r in self.files.items():
                items.append({"type": "sensitive file", "rule": "Sensitive file", "confidence": "MEDIUM", "_c": MED,
                              "value": path, "in_current_files": r["locs"]["current"],
                              "in_history": r["locs"]["history"]})
        items.sort(key=lambda x: -x["_c"])
        for i in items:
            del i["_c"]
        return items


# ---------------------------------------------------------------- scanners
def list_files(root, is_git, include_ignored=False):
    if is_git and not include_ignored:
        r = git(root, "ls-files", "-co", "--exclude-standard", "-z")
        if r.returncode == 0:
            yield from (p for p in r.stdout.split("\0") if p)
            return
        warn(f"git ls-files failed ({r.stderr.strip()[:200]}) - falling back to a plain directory walk")
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            yield os.path.relpath(os.path.join(d, f), root)


def scan_file(path_on_disk, rel, fnd, src="current"):
    try:
        if not os.path.isfile(path_on_disk) or os.path.getsize(path_on_disk) > MAX_SIZE:
            return
        with open(path_on_disk, "rb") as fb:
            head = fb.read(8000)
        enc = "utf-8"
        if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
            enc = "utf-16"
        elif head[:3] == b"\xef\xbb\xbf":
            enc = "utf-8-sig"
        elif b"\0" in head:
            return  # real binary
        with open(path_on_disk, "r", encoding=enc, errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                for rule, secret, conf in scan_line(line.rstrip("\r\n"), rel):
                    fnd.secret(rule, secret, conf, f"{rel}:{n}", src)
    except OSError:
        pass


def scan_worktree(root, is_git, fnd, local, include_ignored=False):
    n = 0
    for rel in list_files(root, is_git, include_ignored):
        n += 1
        rel_posix = rel.replace(os.sep, "/")
        if SENSITIVE_NAMES.search(rel_posix) and not SAFE_NAMES.search(rel_posix):
            fnd.file(rel_posix, rel_posix, "current")
        if not skip_file(rel_posix):
            scan_file(os.path.join(root, rel), rel_posix, fnd)
    if n == 0:
        warn("no files found to scan - is the path correct?")
    if is_git and local:
        scan_file(os.path.join(root, ".git", "config"), ".git/config", fnd)  # tokens in remote URLs
        if not include_ignored:
            r = git(root, "ls-files", "-oi", "--exclude-standard", "--directory", "-z")
            ign = [p for p in r.stdout.split("\0") if p] if r.returncode == 0 else []
            if ign:
                sens = [p for p in ign if SENSITIVE_NAMES.search(p) and not SAFE_NAMES.search(p)]
                msg = f"{len(ign)} git-ignored path(s) not scanned (they are not part of the repo)"
                if sens:
                    msg += f", including: {', '.join(sens[:5])}"
                info(msg + ". Use --include-ignored to scan them too.")


def unreachable_commits(root):
    r = git(root, "fsck", "--unreachable", "--no-reflogs", "--no-progress")
    return [l.split()[-1] for l in r.stdout.splitlines() if l.startswith("unreachable commit")]


def scan_history(root, fnd, extra):
    r = git(root, "log", "--all", *extra, "--name-only", "--pretty=format:%x00%h")
    if r.returncode != 0:
        warn(f"git log failed, history NOT scanned: {r.stderr.strip()[:300]}")
        return
    commit = ""
    for line in r.stdout.splitlines():
        if line.startswith("\0"):
            commit = line[1:]
        elif line and SENSITIVE_NAMES.search(line) and not SAFE_NAMES.search(line):
            fnd.file(line, f"{line} @ {commit}", "history")

    with tempfile.TemporaryFile() as err:
        p = subprocess.Popen(
            [*GIT_BASE, "log", "--all", *extra, "-p", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
             "--pretty=format:@@COMMIT %h"],
            cwd=root, stdout=subprocess.PIPE, stderr=err, text=True, errors="replace")
        watchdog = threading.Timer(TIMEOUT, p.kill) if TIMEOUT else None
        if watchdog:
            watchdog.daemon = True
            watchdog.start()
        commit, path, lineno, skip = "", "", 0, False
        for line in p.stdout:
            line = line.rstrip("\n")
            if line.startswith("@@COMMIT "):
                commit = line[9:]
            elif line.startswith("+++ "):
                path = line[4:].split("\t")[0]
                path = path[2:] if path.startswith("b/") else path
                skip = path == "/dev/null" or skip_file(path)
            elif line.startswith("@@ "):
                m = re.search(r"\+(\d+)", line)
                lineno = int(m.group(1)) if m else 0
            elif line.startswith("+") and not skip:
                for rule, secret, conf in scan_line(line[1:], path):
                    fnd.secret(rule, secret, conf, f"{path}:{lineno} @ {commit}", "history")
                lineno += 1
        p.wait()
        if watchdog:
            watchdog.cancel()
        if p.returncode != 0:
            err.seek(0)
            warn("git log -p reported errors, history scan may be incomplete: "
                 + err.read().decode(errors="replace").strip()[:300])


# -------------------------------------------------------------------- main
def looks_like_remote(t):
    return bool(re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://|[\w.-]+@[\w.-]+:)", t))


def main():
    ap = argparse.ArgumentParser(description="Scan a git repo, directory or file for leaked secrets.")
    ap.add_argument("target", help="repo URL, local repo/directory, or a single file")
    ap.add_argument("--no-history", action="store_true", help="skip git history scan")
    ap.add_argument("--include-ignored", action="store_true", help="also scan git-ignored files on disk")
    ap.add_argument("--show", action="store_true", help="print full secrets instead of redacting")
    ap.add_argument("--min", choices=["low", "medium", "high"], default="low", help="minimum confidence to report")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--version", action="version", version=f"scan.py {VERSION}")
    args = ap.parse_args()
    log = (lambda *a: print(*a, file=sys.stderr)) if args.json else print
    log(f"[*] scan.py {VERSION}")

    path = os.path.abspath(os.path.expanduser(args.target))
    remote = looks_like_remote(args.target) and not os.path.exists(path)
    if not remote and not os.path.exists(path):
        print(f"Path not found: {args.target}", file=sys.stderr)
        return 2
    if remote and not shutil.which("git"):
        print("git is required to scan a URL", file=sys.stderr)
        return 2

    tmp = None
    fnd = Findings()
    try:
        work_root = hist_root = None
        extra = []
        if remote:
            # ONE network operation (one login prompt): a mirror clone has every branch, tag and PR ref.
            tmp = tempfile.mkdtemp(prefix="scan_")
            mirror, work = os.path.join(tmp, "mirror.git"), os.path.join(tmp, "work")
            log(f"[*] Cloning {args.target} (all branches, tags and PR refs) ...")
            r = run([*GIT_BASE, "clone", "--quiet", "--mirror", args.target, mirror])
            if r.returncode != 0:
                print("Clone failed:\n" + r.stderr, file=sys.stderr)
                return 2
            r = run([*GIT_BASE, "clone", "--quiet", mirror, work])  # local, no login needed
            if r.returncode != 0:
                warn("could not check out the default branch (empty repo?): " + r.stderr.strip()[:200])
            else:
                work_root = work
            hist_root, is_git, local_repo = mirror, True, False
        elif os.path.isfile(path):
            rel = os.path.basename(path)
            if SENSITIVE_NAMES.search(rel) and not SAFE_NAMES.search(rel):
                fnd.file(rel, rel, "current")
            log(f"[*] Scanning file {path} ...")
            scan_file(path, rel, fnd)
            is_git = local_repo = False
        else:
            if os.path.basename(path.rstrip(os.sep)) == ".git":
                path = os.path.dirname(path)
            inside = git(path, "rev-parse", "--is-inside-work-tree")
            bare = git(path, "rev-parse", "--is-bare-repository")
            is_bare = bare.stdout.strip() == "true"
            is_git = inside.stdout.strip() == "true" or is_bare
            local_repo = True
            if not is_git and os.path.isdir(os.path.join(path, ".git")):
                warn(f"{path} has a .git folder but git cannot read it: "
                     f"{(inside.stderr or bare.stderr).strip()[:300]} - history will NOT be scanned")
            work_root = None if is_bare else path
            hist_root = path if is_git else None
            if is_git:
                top = git(path, "rev-parse", "--show-toplevel").stdout.strip()
                if top and os.path.realpath(top) != os.path.realpath(path):
                    info(f"{path} is inside the repo at {top}; files are limited to this folder, "
                         "but history covers the whole repo.")
                extra = unreachable_commits(path)

        if work_root:
            log("[*] Scanning current files ...")
            scan_worktree(work_root, is_git and (remote or not is_bare_dir(work_root)), fnd, local_repo,
                          args.include_ignored)
        if hist_root and not args.no_history:
            if git(hist_root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
                warn("this is a SHALLOW repo - older history is missing; run `git fetch --unshallow` first")
            log(f"[*] Scanning git history{f' (+{len(extra)} unreachable commits)' if extra else ''} ...")
            scan_history(hist_root, fnd, extra)
        elif not is_git and not os.path.isfile(path):
            log("[!] Not a git repo - history scan skipped")

        items = fnd.report(args.show, {"low": LOW, "medium": MED, "high": HIGH}[args.min])
        if args.json:
            print(json.dumps(items, indent=2))
            return 1 if items else 0
        if not items:
            print("\n[OK] No secrets found (regex scanning can still miss unusual formats).")
            return 0

        counts = {c: sum(1 for i in items if i["confidence"] == c) for c in ("HIGH", "MEDIUM", "LOW")}
        print(f"\n[!] {len(items)} finding(s): {counts['HIGH']} HIGH, {counts['MEDIUM']} MEDIUM, {counts['LOW']} LOW\n")
        for i in items:
            cur, hist = i["in_current_files"], i["in_history"]
            status = "STILL IN CURRENT FILES" if cur else "removed, but STILL IN GIT HISTORY"
            print(f"  [{i['confidence']}] {i['rule']}\n    value  : {i['value']}\n    status : {status}")
            for label, locs in (("files  ", cur), ("history", hist)):
                if locs:
                    more = f"  (+{len(locs) - 3} more)" if len(locs) > 3 else ""
                    print(f"    {label}: {', '.join(locs[:3])}{more}")
            print()
        print("Next: rotate/revoke every real secret first. Deleting the file is not enough,")
        print("because git history keeps it. Then purge history with git filter-repo or BFG.")
        return 1
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def is_bare_dir(p):
    return git(p, "rev-parse", "--is-bare-repository").stdout.strip() == "true"


if __name__ == "__main__":
    sys.exit(main())