# Autonomous Job Search Strategy & Cold Outreach Engine

An automated outbound pipeline for engineering and AI roles. It scrapes verified hiring leads from top-tier tech sources, validates recipient mail server DNS MX records, and dispatches personalized cold outreach emails with attached PDF resumes via Google Chrome Remote Debugging (Chrome DevTools Protocol - CDP) with dynamic sleep management (`caffeinate`).

---

## 1. Repository Layout

```
job-search-workspace/
├── scripts/
│   ├── run_outreach_dispatcher.js   # CDP background daemon (Chrome port 9222 + caffeinate)
│   ├── launch_dispatcher.sh         # Background nohup process manager
│   ├── stop_daemon.sh               # Safe daemon killer & PID cleaner
│   ├── stage_next_pulse.py          # 48-thread Algolia HN scraper + MX validator
│   └── sourcing/                    # Multi-channel sourcing suite
│       ├── verifier.py              # DNS MX verification & ledger deduplication
│       ├── source_github_maintainers.py # Scrapes 26 open-source AI repo commit emails
│       ├── source_yc_founders.py    # Scrapes YC W24–S26 batch founders
│       ├── source_vc_portfolios.py  # Top AI VC portfolio leaders (Baseten, Fireworks, etc.)
│       └── harvest_leads.py         # Unified CLI lead harvester
├── outputs/outreach/
│   ├── outreach-ledger.json         # Master deduplication ledger (starts as {"records": []})
│   └── pulse-tracker.json           # Clock tracker (configured for 4 pulses/day)
└── resumess/
    └── Friend_Resume.pdf            # 1-page PDF attached to every outgoing email
```

---

## 2. Prerequisites

- **macOS** (utilizes native macOS `caffeinate` for background sleep assertion during dispatching)
- **Google Chrome**
- **Node.js** (v18+ recommended, uses built-in standard modules — no external npm dependencies required)
- **Python** (3.9+ recommended, uses standard library modules — no external pip packages required)
- **DNS MX lookup utility**: `dig` (installed by default on macOS and Linux)

---

## 3. Quickstart Guide

### Step 1: Add Your Resume
Place your 1-page PDF resume in `resumess/`:
```bash
cp /path/to/your/resume.pdf resumess/Friend_Resume.pdf
```
The dispatcher automatically detects and attaches any `.pdf` file located in the `resumess/` folder.

### Step 2: Customize Your Pitch & Profile
Open `scripts/stage_next_pulse.py` (around line 500) and `scripts/sourcing/harvest_leads.py` (around line 43) to customize:
- Your name, school, degree, and graduation timeline
- Your top 3 technical project/experience bullets
- Your GitHub and LinkedIn links

### Step 3: Launch Google Chrome in Remote Debugging Mode
Close existing Chrome instances (or run with an isolated user data directory) with port `9222` enabled:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --remote-allow-origins="*" &
```
1. Open `https://mail.google.com` in this Chrome instance.
2. Log into your dedicated outreach email account.
3. Keep the Gmail tab open (it can run in the background).

### Step 4: Harvest & Stage Leads
Choose either of the two lead generation methods:

**Option A — Fast Hacker News Staging (Recommended for immediate pulses):**
```bash
python3 scripts/stage_next_pulse.py
```
This queries 48 official Hacker News "Who is Hiring?" threads concurrently, filters out banned/academic/generic domains, performs live DNS MX checks, and stages verified hiring leads in seconds.

**Option B — Multi-Source Harvester (GitHub OSS, YC Founders, AI VC Portfolios):**
```bash
python3 scripts/sourcing/harvest_leads.py --sources github yc vc --target 75
```

### Step 5: Start the Dispatcher Daemon
Launch the background daemon:
```bash
./scripts/launch_dispatcher.sh
```
The daemon runs in the background (`nohup`), automatically manages sleep prevention (`caffeinate -dimsu`), connects to Chrome via WebSocket CDP, fills recipient details, attaches your resume PDF, verifies rendering, and clicks send with randomized human-like delays (20–45s).

### Step 6: Monitor & Stop
- **Check live progress**:
  ```bash
  tail -f outputs/outreach/dispatcher.log
  ```
- **Stop the daemon immediately**:
  ```bash
  ./scripts/stop_daemon.sh
  ```

---

## 4. Pulse Schedule Configuration

The automated pulse schedule is managed in `outputs/outreach/pulse-tracker.json`:
- **Pulses per day**: 4
- **Emails per pulse**: 75
- **Daily target**: 300 emails
- **Default pulse hours (EST)**: `[9, 12, 15, 18]` (9:00 AM, 12:00 PM, 3:00 PM, 6:00 PM)

You can adjust these parameters in `outputs/outreach/pulse-tracker.json` to suit your schedule.

---

## 5. Critical Infrastructure & Safety Rules

> [!WARNING]
> **NEVER USE YOUR PRIMARY PERSONAL GMAIL OR UNIVERSITY (.EDU) EMAIL FOR BULK AUTOMATED OUTREACH.**

1. **Consumer Gmail Limits**: Sending 100+ automated cold emails per day from a personal `@gmail.com` will trigger Google's automated abuse filters and temporarily or permanently disable the account.
2. **Academic (.EDU) Risks**: Bulk outreach from university accounts violates campus Acceptable Use Policies (AUP) and can lead to IT suspension, LMS/grades lockout, and disciplinary action.
3. **The Recommended Pro Setup**:
   - Purchase a dedicated secondary domain (e.g., `yourname-tech.com` or `firstname-eng.com`).
   - Configure **SPF**, **DKIM**, and **DMARC** DNS records.
   - Use Google Workspace or a transactional email provider with a progressive warm-up schedule (10 emails/day -> 25 -> 50 -> 75 -> 100+ over 2–3 weeks).
