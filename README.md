# GitScanner 🔍

GitScanner is an automated tool designed to detect leaked secrets, API keys, credentials, and sensitive configurations in Git repositories and local filesystems—checking both current files and full Git commit history.

---

## ⚡ Features

- **60+ High-Confidence Rule Signatures**: Detects AWS keys, GitHub tokens, Cloudflare keys, Stripe keys, Telegram bot tokens, Slack webhooks, OpenAI / Anthropic API keys, private keys, etc.
- **Assignment & Entropy Detection**: Flags variable assignments containing credentials (`KEY=value`, JSON fields, CLI parameters) and high-entropy secret strings.
- **Deep Git History Analysis**: Analyzes current commits, all branches, tags, stashes, GitHub PR refs, and dangling commits.
- **Batch GitHub Scanning**: Automatically scan all repositories of an organization or user concurrently with configurable parallel workers (`--jobs`).
- **Flexible Targets**: Supports remote Git URLs, local folders, single files, or GitHub accounts.

---

## 🚀 Installation & Requirements

- Python 3.8+
- Git installed and available in your `PATH`

```bash
git clone https://github.com/saayemahmad/gitscanner.git
cd gitscanner
pip install -r requirements.txt
```

---

## 🛠️ Usage

### 1. Batch Scanning via GitHub (`main.py`)

Scan all public repositories for a GitHub user:
```bash
python main.py --user octocat
```

Scan a single GitHub repository:
```bash
python main.py --repo octocat/hello-world
```

Scan local projects / paths:
```bash
python main.py --path ./my-project
python main.py --path ./dir1 --path ./dir2
```

Using a GitHub personal access token for higher rate limits and private repositories:
```bash
python main.py --user octocat --token $GITHUB_TOKEN --jobs 8
```

Output as JSON:
```bash
python main.py --user octocat --json > report.json
```

---

### 2. Single Target Scanning (`scan.py`)

Scan a remote repository directly:
```bash
python scan.py https://github.com/owner/repo
```

Scan local directory without history (current files only):
```bash
python scan.py /path/to/local/repo --no-history
```

Filter confidence levels:
```bash
python scan.py /path/to/local/repo --min medium
```

Show unredacted secret values:
```bash
python scan.py /path/to/local/repo --show
```

---

## 📁 Repository Structure

```
gitscanner/
├── main.py                 # Multi-repo batch scanner and CLI orchestrator
├── scan.py                 # Core scanning engine & secret detection rules
├── requirements.txt        # Python dependencies
├── scan.log                # Sample scan execution log
├── renewal-blood-network/  # Included sample scanned project
└── README.md               # Documentation
```

---

## 🛡️ License

MIT License
