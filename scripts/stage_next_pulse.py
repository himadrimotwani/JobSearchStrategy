#!/usr/bin/env python3
"""
Autonomous 6x-Daily Outreach Pulse Stager (75 leads/pulse, 450/day cap-safe).
Sources strictly verified, named US corporate engineering leads from:
  1. Official HN "Who is hiring?" threads (2024-2026, newest first)
  2. HN Founder / Launch HN / Show HN hiring comments
  3. YC OSS active hiring startups (publicly published non-generic domain emails)

Enforces zero duplicates, zero generic mailboxes, zero academic/personal domains,
and respects pending staged queue thresholds + 24-hour Gmail rolling safety limits.
"""

import argparse
import html
import json
import os
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER_PATH = os.path.join(WORKSPACE_ROOT, "outputs/outreach/outreach-ledger.json")
OUTREACH_ROOT = os.path.join(WORKSPACE_ROOT, "outputs/outreach")
PDF_PATH = os.path.join(WORKSPACE_ROOT, "resumess/Himadri_Motwani_AI_Software_Engineering_Outreach.pdf")
if not os.path.exists(PDF_PATH):
    resumes_dir = os.path.join(WORKSPACE_ROOT, "resumess")
    if os.path.exists(resumes_dir):
        pdfs = [os.path.join(resumes_dir, f) for f in os.listdir(resumes_dir) if f.lower().endswith(".pdf")]
        if pdfs:
            PDF_PATH = pdfs[0]

BANNED_DOMAINS = [
    ".edu", ".ac.uk", ".edu.cn", ".ac.in", ".dk", ".au.dk", "gmail.com", "gmai.com", "gmial.com",
    "yahoo.com", "yaho.com", "hotmail.com", "hotmal.com", "outlook.com", "icloud.com",
    "protonmail.com", "proton.me", "anonaddy.com", "simplelogin.com", "example.com", "domain.com", "sentry.io"
]
BANNED_USERNAMES = {
    "career", "careers", "jobs", "hiring", "talent", "team", "hr", "support", "info", "sales",
    "hn", "press", "contact", "apply", "admin", "my-last-name", "hi", "hello", "recruiting",
    "recruitment", "work", "join", "help", "founders", "founder", "joinus", "eng", "engineering",
    "dev", "office", "people", "staff", "hey", "recruit", "opportunities", "opportunity",
    "role", "roles", "resume", "resumes", "cv", "applications", "application", "campus",
    "university", "intern", "interns", "internship", "internships", "backend", "frontend",
    "ml", "ai", "data", "tech", "software", "platform", "systems", "ops", "security",
    "product", "design", "growth", "marketing", "finance", "legal", "billing", "noreply", "no-reply",
    "first", "firstname", "yourname", "name", "email", "firstname.lastname", "first.last", "first_last",
    "first-last", "f.last", "your.name", "us", "here", "me", "check", "out", "website", "company",
    "visit", "find", "our", "this", "them", "you", "your", "reach", "agency", "draftpicks",
    "hiring-eng", "jobs-us", "join-us", "hackernews", "ycombinator", "firstname_lastname", "bullet",
    "humancapital", "mail", "principal4hire", "otherling", "everflow-hn", "jobpost", "privacy", "abuse",
    "service", "services", "inquiry", "inquiries", "wave", "investors", "investor", "submissions",
    "submission", "clinics", "clinic", "connect", "licensing", "license", "ask", "partnerships",
    "partnership", "partner", "partners", "letsbuild", "inbound", "reviewee", "reviews", "review",
    "complaints", "complaint", "concierge", "feedback", "general", "media", "pr", "ir", "community",
    "customers", "customer", "members", "demo", "book", "welcome", "start", "subscribe", "news",
    "newsletter", "events", "waitlist", "beta", "alpha", "ping", "talk", "chat", "learn", "orders",
    "order", "store", "shop", "bookings", "booking", "reservations", "reservation", "appointments",
    "devrel", "ecosystem", "enterprise", "compliance", "trust", "accounts", "accounting", "payroll",
    "onboarding", "care", "concierge", "relations", "editorial", "research", "fellows", "fellowship"
}
GENERIC_SUBSTRINGS = [
    "jobs", "career", "hiring", "recruit", "talent", "apply", "campus", "university",
    "joinus", "founders", "talent-", "hackernews", "join-", "first.", "firstname", "-hn", "jobpost",
    "noreply", "no-reply", "support", "privacy", "security", "inquir", "complaint", "partner", "invest"
]
TECH_KEYWORDS = [
    "software engineer", "ml engineer", "ai engineer", "machine learning", "backend",
    "full stack", "full-stack", "fullstack", "data engineer", "systems engineer",
    "infrastructure", "founding engineer", "python", "llm"
]
NON_US_MARKERS = [
    "remote india", "remote (india)", "remote (eu)", "remote eu", "on-site in bremen", "paris, france",
    "on site toronto", "london, uk", "london (uk)", "uk - onsite", "berlin, germany", "munich, germany",
    "amsterdam", "zurich", "singapore only", "uk only", "eu only", "europe only", "canada only",
    "bangalore", "bengaluru", "hyderabad", "oslo, norway", "noida, india", "antwerp"
]
NON_TECH_HEADERS = [
    "independent sales representative", "account executive", "sales representative", "business development"
]
JOB_SEEKER_MARKERS = ["willing to relocate:", "résumé:", "resume:", "technologies:"]

EMAIL_REGEX = re.compile(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")
OBF_BRACKET = re.compile(
    r"([a-zA-Z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\{at\}|<at>)\s*"
    r"([a-zA-Z0-9.-]+(?:\s*(?:\[dot\]|\(dot\)|\{dot\}|\.)\s*[a-zA-Z]{2,})+)",
    re.I
)
OBF_WORDS = re.compile(
    r"\b([a-zA-Z0-9._-]+)\s+at\s+([a-zA-Z0-9-]+)\s+dot\s+(com|ai|io|co|dev|us|org|net)\b",
    re.I
)


def normalize_email(raw):
    em = (raw or "").lower().strip().rstrip(".,;:)>]\"'")
    if "@" not in em:
        return "", "", ""
    user, dom = em.split("@", 1)
    base_user = user.split("+")[0]
    return em, f"{base_user}@{dom}", base_user


def load_blocked_and_rolling_count():
    all_blocked = set()
    sent_last_24h = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH) as f:
            records = json.load(f).get("records", [])
        for r in records:
            for key in ("email", "recipient_email"):
                raw_em, clean_em, _ = normalize_email(r.get(key))
                if raw_em:
                    all_blocked.add(raw_em)
                    all_blocked.add(clean_em)
            if r.get("status") == "SENT" and r.get("sent_at"):
                try:
                    dt = datetime.fromisoformat(r["sent_at"].replace("Z", "+00:00"))
                    if dt >= cutoff:
                        sent_last_24h += 1
                except Exception:
                    pass

    # Load all delivery-suppressions.json files across date folders
    for entry in os.listdir(OUTREACH_ROOT):
        supp_path = os.path.join(OUTREACH_ROOT, entry, "delivery-suppressions.json")
        if os.path.exists(supp_path):
            try:
                with open(supp_path) as f:
                    for x in json.load(f).get("addresses", []):
                        raw_em, clean_em, _ = normalize_email(x)
                        if raw_em:
                            all_blocked.add(raw_em)
                            all_blocked.add(clean_em)
            except Exception:
                pass

    return all_blocked, sent_last_24h


def is_valid_email(clean_em, user_part, all_blocked, seen):
    if not clean_em or "@" not in clean_em:
        return False
    if clean_em in all_blocked or clean_em in seen:
        return False
    if user_part in BANNED_USERNAMES or any(sub in user_part for sub in GENERIC_SUBSTRINGS):
        return False
    if len(user_part) < 2 or not user_part[0].isalpha():
        return False
    if any(clean_em.endswith(bd) for bd in BANNED_DOMAINS):
        return False
    if not clean_em.endswith((".com", ".ai", ".io", ".co", ".dev", ".us", ".org", ".net", ".health", ".care", ".energy")):
        return False
    return True


US_LOCATION_REGEX = re.compile(
    r"\b(san francisco|sf\b|bay area|nyc|new york|brooklyn|seattle|boston|cambridge, ma|austin|chicago|"
    r"los angeles|la\b|mountain view|palo alto|menlo park|sunnyvale|redwood city|san mateo|santa clara|"
    r"denver|boulder|atlanta|miami|washington,?\s*dc|raleigh|durham|pittsburgh|philadelphia|"
    r"usa|u\.s\.|united states|remote\s*\(?us|us\s+remote|us\s+only|americas|est|pst)\b",
    re.I
)
MX_CACHE = {}


def has_valid_mx(domain):
    dom = (domain or "").lower().strip()
    if not dom:
        return False
    if dom in MX_CACHE:
        return MX_CACHE[dom]
    try:
        res = subprocess.run(["dig", "+short", "MX", dom], capture_output=True, text=True, timeout=4)
        ok = bool(res.stdout.strip())
    except Exception:
        ok = True  # Don't fail closed if dig binary unavailable
    MX_CACHE[dom] = ok
    return ok


def fetch_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_text(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


ALL_HN_THREADS = [
    50338728, 49922569, 49522897, 49156683, 48747976, 48357725, 47975571,
    47601859, 47219668, 46857488, 46466074, 46108941, 45800465, 45438503,
    45093192, 44757794, 44434576, 44159528, 43858554, 43547611, 43243024,
    42919502, 42575537, 42297424, 42017580, 41709301, 41425910, 41129813,
    40845348, 40546995, 40224647, 39893901, 39562986, 39217088, 38837330,
    38490408, 38096086, 37737332, 37346857, 36956869, 36551101, 36152054,
    35773721, 35402377, 35025737, 34614136, 34204595, 33827438
]


def discover_hn_hiring_threads(all_blocked, seen, target_pool_size, start_slice=0, end_slice=48):
    pool = []
    # Dynamic discovery of Who is hiring threads via Algolia
    search_url = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=100"
    thread_ids = []
    try:
        hits = fetch_json(search_url).get("hits", [])
        thread_ids = [
            int(h["objectID"]) for h in hits
            if "who is hiring" in (h.get("title") or "").lower()
        ][start_slice:end_slice]
    except Exception:
        pass
    if not thread_ids:
        thread_ids = ALL_HN_THREADS[start_slice:end_slice]

    def fetch_thread(tid):
        try:
            return fetch_json(f"https://hn.algolia.com/api/v1/items/{tid}", timeout=10)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=16) as ex:
        threads = list(ex.map(fetch_thread, thread_ids))

    for t in threads:
        if not t:
            continue
        for c in t.get("children", []):
            raw_html = c.get("text") or ""
            if not raw_html:
                continue
            unescaped = html.unescape(raw_html)
            clean_text = re.sub(r"<[^>]*>", "\n", unescaped)
            clean_text = re.sub(r"\n+", "\n", clean_text).strip()
            lower_text = clean_text.lower()
            header = clean_text.split("\n")[0][:220].lower()

            if any(m in header for m in NON_US_MARKERS) or any(m in lower_text[:320] for m in NON_US_MARKERS):
                continue
            if not US_LOCATION_REGEX.search(clean_text[:450]):
                continue
            if any(nt in header for nt in NON_TECH_HEADERS):
                continue
            if any(js in lower_text[:400] for js in JOB_SEEKER_MARKERS):
                continue
            if not any(k in lower_text for k in TECH_KEYWORDS):
                continue

            candidates = list(EMAIL_REGEX.findall(unescaped))
            for u, d in OBF_BRACKET.findall(clean_text):
                d_clean = re.sub(r"\s*(?:\[dot\]|\(dot\)|\{dot\})\s*", ".", d, flags=re.I)
                candidates.append(f"{u}@{d_clean}")
            for u, d, tld in OBF_WORDS.findall(clean_text):
                candidates.append(f"{u}@{d}.{tld}")

            for raw_em in candidates:
                _, clean_em, user_part = normalize_email(raw_em)
                if not is_valid_email(clean_em, user_part, all_blocked, seen):
                    continue
                seen.add(clean_em)
                pool.append({
                    "source": f"https://news.ycombinator.com/item?id={c.get('id')}",
                    "by": c.get("author") or "Engineering Leader",
                    "email": clean_em,
                    "rawText": clean_text[:500]
                })
                if len(pool) >= target_pool_size:
                    return pool
    return pool


def discover_hn_founder_comments(all_blocked, seen, needed):
    pool = []
    if needed <= 0:
        return pool
    queries = [
        "%40%20founder", "%40%20%22reach%20out%22", "%40%20%22shoot%20me%22",
        "%40%20%22email%20me%22", "%40%20%22we%20are%20hiring%22"
    ]

    def run_q(q):
        hits = []
        for page in range(4):
            url = (
                f"https://hn.algolia.com/api/v1/search_by_date?query={q}"
                f"&tags=comment&numericFilters=created_at_i>1735689600&hitsPerPage=100&page={page}"
            )
            try:
                res = fetch_json(url, timeout=10).get("hits", [])
                if not res:
                    break
                hits.extend(res)
            except Exception:
                break
        return hits

    with ThreadPoolExecutor(max_workers=5) as ex:
        all_hits = sum(ex.map(run_q, queries), [])

    for h in all_hits:
        raw_html = h.get("comment_text") or ""
        if not raw_html:
            continue
        clean_text = re.sub(r"<[^>]*>", "\n", html.unescape(raw_html)).strip()
        low = clean_text.lower()
        if any(m in low[:320] for m in NON_US_MARKERS) or any(js in low[:400] for js in JOB_SEEKER_MARKERS):
            continue
        if not any(k in low for k in ["hiring", "engineer", "developer", "ml ", "ai ", "software", "founding"]):
            continue
        for raw_em in EMAIL_REGEX.findall(clean_text):
            _, clean_em, user_part = normalize_email(raw_em)
            if not is_valid_email(clean_em, user_part, all_blocked, seen):
                continue
            seen.add(clean_em)
            pool.append({
                "source": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "by": h.get("author") or "Founder",
                "email": clean_em,
                "rawText": clean_text[:500]
            })
            if len(pool) >= needed:
                return pool
    return pool


def discover_yc_oss_sites(all_blocked, seen, needed):
    """Fallback & expansion: scan actively hiring US YC companies for published named/contact corporate emails."""
    pool = []
    if needed <= 0:
        return pool
    try:
        companies = fetch_json("https://yc-oss.github.io/api/companies/hiring.json", timeout=15)
    except Exception:
        return pool

    us_hiring = [
        c for c in companies
        if "United States of America" in (c.get("regions") or [])
        and c.get("website")
    ]
    # Prioritize newest batches first
    us_hiring.sort(key=lambda c: c.get("launched_at", 0), reverse=True)

    def scan_company(c):
        site = c["website"].rstrip("/")
        domain = re.sub(r"^https?://(www\.)?", "", site).split("/")[0].lower()
        for suffix in ("", "/about", "/team", "/careers", "/contact"):
            try:
                page = fetch_text(site + suffix, timeout=3)
                for raw_em in EMAIL_REGEX.findall(html.unescape(page)):
                    _, clean_em, user_part = normalize_email(raw_em)
                    # Verify email belongs to that company's domain (prevents third-party tracker emails)
                    if clean_em.endswith("@" + domain) and is_valid_email(clean_em, user_part, all_blocked, seen):
                        return {
                            "source": c.get("url") or site,
                            "by": c["name"],
                            "company_override": c["name"],
                            "email": clean_em,
                            "rawText": f"{c['name']} ({c.get('batch')}) | {c.get('one_liner', '')}"
                        }
            except Exception:
                continue
        return None

    # Scan batches of 80 until satisfied
    for start in range(0, len(us_hiring), 80):
        chunk = us_hiring[start:start + 80]
        with ThreadPoolExecutor(max_workers=40) as ex:
            results = list(ex.map(scan_company, chunk))
        for res in results:
            if res and res["email"] not in seen:
                seen.add(res["email"])
                pool.append(res)
                if len(pool) >= needed:
                    return pool
    return pool


def clean_company_name(raw_first_line, domain_part):
    parts = [p.strip() for p in raw_first_line.split("|")]
    comp = parts[0] if parts else ""
    comp = re.sub(r"\(.*?\)", "", comp)
    comp = comp.split("(")[0].split("[")[0].split("--")[0].strip()
    comp = re.sub(r"https?://\S+", "", comp).strip(" -–—:,.[")
    comp = re.sub(r"^(At|at|We are|Hiring)\s+", "", comp).strip()

    domain_base = domain_part.split(".")[0]
    for prefix in ("get", "try", "use"):
        if domain_base.startswith(prefix) and len(domain_base) > len(prefix) + 2:
            domain_base = domain_base[len(prefix):]
    domain_cap = domain_base.capitalize()

    role_or_bad = [
        "engineer", "developer", "lead", "founding", "manager", "scientist",
        "remote", "hiring", "multiple positions", "stealth", "erica holloway",
        "hello", "hey", "hi ", "looking for", "we're"
    ]
    if not comp or len(comp) < 2 or len(comp) > 32 or any(w in comp.lower() for w in role_or_bad):
        if "@" in raw_first_line and " @ " in raw_first_line:
            after_at = raw_first_line.split(" @ ")[1].split("|")[0].strip()
            if 2 <= len(after_at) <= 30:
                return after_at
        if "onefootprint" in domain_part:
            return "Footprint"
        return domain_cap
    return comp


def stage_pulse(date_str, count, force=False):
    all_blocked, sent_last_24h = load_blocked_and_rolling_count()
    print(f"Blocked addresses: {len(all_blocked)} | Sent in rolling 24h: {sent_last_24h}/465")

    if sent_last_24h >= 460 and not force:
        print(f"Rolling 24h cap threshold approached ({sent_last_24h}/465). Deferring pulse staging.")
        return 0

    date_dir = os.path.join(OUTREACH_ROOT, date_str)
    os.makedirs(date_dir, exist_ok=True)
    staged_file = os.path.join(date_dir, "outreach-batch-staged.json")

    existing_records = []
    if os.path.exists(staged_file):
        with open(staged_file) as f:
            existing_records = json.load(f).get("records", [])

    pending_existing = [r for r in existing_records if r.get("status") == "STAGED"]
    if len(pending_existing) >= count and not force:
        print(f"Queue already has {len(pending_existing)} STAGED leads (>= {count}). Skipping duplicate stage.")
        return 0

    for r in existing_records:
        for key in ("email", "recipient_email"):
            raw_em, clean_em, _ = normalize_email(r.get(key))
            if raw_em:
                all_blocked.add(raw_em)
                all_blocked.add(clean_em)

    seen = set()
    buffer_target = count + 40
    pool = discover_hn_hiring_threads(all_blocked, seen, buffer_target, start_slice=0, end_slice=48)
    print(f"Source 1 (HN Who is Hiring Threads 1-48, US verified): {len(pool)} leads")

    if len(pool) < buffer_target:
        extra = discover_hn_founder_comments(all_blocked, seen, buffer_target - len(pool))
        pool.extend(extra)
        print(f"Source 2 (HN Founder/Hiring Comments): +{len(extra)} leads (Total: {len(pool)})")

    # Parallel DNS MX validation to eliminate dead/non-deliverable domains pre-send
    unique_domains = list({c["email"].split("@", 1)[1] for c in pool if "@" in c["email"]})
    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(has_valid_mx, unique_domains))

    verified_pool = [c for c in pool if has_valid_mx(c["email"].split("@", 1)[1])]
    dropped_mx = len(pool) - len(verified_pool)
    if dropped_mx > 0:
        print(f"DNS MX pre-check dropped {dropped_mx} dead/non-MX domains.")

    selected = verified_pool[:count]
    if not selected:
        print("Warning: No fresh uncontacted leads discovered in this cycle.")
        return 0

    prefix = "O811" if date_str == "2026-11-11" else f"O{date_str[5:7]}{date_str[8:10]}"
    start_idx = len(existing_records) + 1
    new_records = []

    for offset, c in enumerate(selected):
        idx = start_idx + offset
        draft_id = f"{prefix}_{idx:02d}"
        em = c["email"]
        user_part, domain_part = em.split("@", 1)

        text = c["rawText"]
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        first_line = lines[0] if lines else ""
        parts = [p.strip() for p in first_line.split("|")]
        company = c.get("company_override") or clean_company_name(first_line, domain_part)

        name = c.get("by", "Leader")
        first_name = "Team"
        if "." in user_part:
            p_parts = [p for p in user_part.split(".") if p]
            if p_parts and p_parts[0].isalpha() and len(p_parts[0]) > 1:
                first_name = p_parts[0].capitalize()
                name = f"{first_name} {p_parts[1].capitalize()}" if len(p_parts) > 1 and p_parts[1].isalpha() else first_name
        elif len(user_part) > 2 and user_part.isalpha():
            first_name = user_part.capitalize()
            name = first_name
        else:
            first_name = name.capitalize() if name and name.isalpha() else "Team"

        title = "Engineering Leader"
        if len(parts) > 1:
            potential_title = parts[1]
            if any(w in potential_title.lower() for w in ["engineer", "cto", "head", "lead", "manager", "developer", "director", "founder"]):
                title = potential_title[:60]

        body = f"""Hi {first_name},

I saw that you lead engineering/talent at {company}. I’m Himadri Motwani, an MS in Information Technology student at RPI graduating in May 2027 (available for a January 2027 internship or May 2027 full-time start).

My technical background aligns with scalable backend systems and AI infrastructure:
• Built a containerized multi-agent LLM platform (github.com/himadrimotwani/URP-Full-Project) coordinating autonomous agents with tool execution and multi-user evaluation.
• Engineered backend data services at Trackk-N-Tracee in Python, FastAPI, and PostgreSQL, cutting query retrieval latency by 40% via SQL indexing.
• Implemented automated scientific ML data pipelines processing 1,199 dataset cases across 22 physical fields, training neural operators on A100 GPUs (51% pressure, 83% temperature, 84% Mach relative error reduction).

Would your team consider my profile for an early-career software engineering internship in January 2027 or a new-grad role in May 2027?

I’ve attached my resume for review.
GitHub: https://github.com/himadrimotwani
LinkedIn: https://www.linkedin.com/in/himadri-motwani

Best regards,
Himadri Motwani"""

        new_records.append({
            "id": draft_id,
            "batch": date_str,
            "draft_id": draft_id,
            "company": company,
            "person_name": name,
            "title": title,
            "email": em,
            "source_url": c["source"],
            "one_sentence_fit": "Engineered containerized multi-agent LLM platform, scientific ML data pipelines on A100 GPUs, and cut backend query latency by 40%.",
            "one_request": "Would your team consider my background for an engineering internship in January 2027 or full-time start in May 2027?",
            "subject": f"{company} Software Engineering (Early Career 2027) — systems & AI",
            "body": body,
            "attachment_paths": [PDF_PATH],
            "attachment_filename": "Himadri_Motwani_AI_Software_Engineering_Outreach.pdf",
            "status": "STAGED",
            "notes": f"Verified hiring lead ({c['source']}): {first_line[:90]}"
        })

    combined = existing_records + new_records
    batch_output = {
        "date": date_str,
        "total_staged": len(combined),
        "confirmed_sends": sum(1 for r in combined if r.get("status") == "SENT"),
        "target_new_emails_per_day": 450,
        "daily_target": 450,
        "per_run_target": 75,
        "pulses_per_day": 6,
        "pulse_hours_est": [8, 11, 14, 17, 20, 23],
        "status": "STAGED_READY",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "records": combined
    }

    with open(staged_file, "w") as f:
        json.dump(batch_output, f, indent=2)

    run_status_path = os.path.join(date_dir, "run-status.json")
    if not os.path.exists(run_status_path):
        with open(run_status_path, "w") as f:
            json.dump({
                "date": date_str,
                "timezone": "America/New_York",
                "per_run_target": 75,
                "daily_target": 450,
                "pulses_per_day": 6,
                "daily_confirmed_outreach_sends": 0,
                "daily_confirmed_qualifying_sends": 0,
                "confirmed_sends": 0,
                "sent_count": 0,
                "shortfall": 450,
                "sends_today": [],
                "status": "IN_PROGRESS",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }, f, indent=2)

    with open(os.path.join(OUTREACH_ROOT, "outreach-batch-staged.json"), "w") as f:
        json.dump(batch_output, f, indent=2)

    print(f"Staged {len(new_records)} new records into {staged_file} (Total={len(combined)}).")
    return len(new_records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=75)
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    stage_pulse(args.date, args.count, args.force)
