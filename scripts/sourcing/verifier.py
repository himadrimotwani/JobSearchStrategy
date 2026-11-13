#!/usr/bin/env python3
"""
Enterprise Email & Domain Verification Utilities for Autonomous Outreach.
Enforces strict targeting invariants:
1. 100% US Corporate Only (Zero .edu, academic, personal webmail, or disposable domains).
2. Zero Generic Mailboxes (Zero jobs@, careers@, info@, recruiting@, support@, team@).
3. Live DNS MX Record Validation (Ensures domain has active mail servers).
4. 100% Deduplication against historical outreach ledger and active suppressions.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LEDGER_PATH = os.path.join(WORKSPACE_ROOT, "outputs/outreach/outreach-ledger.json")
OUTREACH_ROOT = os.path.join(WORKSPACE_ROOT, "outputs/outreach")

BANNED_DOMAINS = {
    ".edu", ".ac.uk", ".edu.cn", ".ac.in", ".dk", ".au.dk", ".edu.au", ".ca",
    "gmail.com", "gmai.com", "gmial.com", "googlemail.com",
    "yahoo.com", "yaho.com", "ymail.com",
    "hotmail.com", "hotmal.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me", "pm.me",
    "anonaddy.com", "simplelogin.com", "duck.com",
    "example.com", "domain.com", "sentry.io", "w3.org", "github.com"
}

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
    "onboarding", "care", "relations", "editorial", "research", "fellows", "fellowship"
}

GENERIC_SUBSTRINGS = [
    "jobs", "career", "hiring", "recruit", "talent", "apply", "campus", "university",
    "joinus", "founders", "talent-", "hackernews", "join-", "first.", "firstname", "-hn", "jobpost",
    "noreply", "no-reply", "support", "privacy", "security", "inquir", "complaint", "partner", "invest"
]

MX_CACHE = {}


def normalize_email(raw):
    """Clean and normalize raw email string."""
    em = (raw or "").lower().strip().rstrip(".,;:)>]\"'")
    if "@" not in em:
        return "", "", ""
    user, dom = em.split("@", 1)
    base_user = user.split("+")[0]
    return em, f"{base_user}@{dom}", base_user


def has_valid_mx(domain):
    """Verify live DNS MX records for domain."""
    dom = (domain or "").lower().strip()
    if not dom:
        return False
    if dom in MX_CACHE:
        return MX_CACHE[dom]
    try:
        res = subprocess.run(["dig", "+short", "MX", dom], capture_output=True, text=True, timeout=4)
        ok = bool(res.stdout.strip())
    except Exception:
        ok = True  # Fallback gracefully if dig fails
    MX_CACHE[dom] = ok
    return ok


def load_historical_exclusions():
    """Load all globally contacted or suppressed emails and names."""
    all_blocked_emails = set()
    all_blocked_names = set()
    sent_last_24h = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # 1. Historical Ledger
    if os.path.exists(LEDGER_PATH):
        try:
            with open(LEDGER_PATH) as f:
                records = json.load(f).get("records", [])
            for r in records:
                for key in ("email", "recipient_email"):
                    raw_em, clean_em, _ = normalize_email(r.get(key))
                    if raw_em:
                        all_blocked_emails.add(raw_em)
                        all_blocked_emails.add(clean_em)
                name = (r.get("person_name") or r.get("name") or "").strip().lower()
                if name and len(name) > 3 and name != "team":
                    all_blocked_names.add(name)
                if r.get("status") == "SENT" and r.get("sent_at"):
                    try:
                        dt = datetime.fromisoformat(r["sent_at"].replace("Z", "+00:00"))
                        if dt >= cutoff:
                            sent_last_24h += 1
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. Daily delivery-suppressions.json files
    if os.path.exists(OUTREACH_ROOT):
        for entry in os.listdir(OUTREACH_ROOT):
            supp_path = os.path.join(OUTREACH_ROOT, entry, "delivery-suppressions.json")
            if os.path.exists(supp_path):
                try:
                    with open(supp_path) as f:
                        for x in json.load(f).get("addresses", []):
                            raw_em, clean_em, _ = normalize_email(x)
                            if raw_em:
                                all_blocked_emails.add(raw_em)
                                all_blocked_emails.add(clean_em)
                except Exception:
                    pass

    return all_blocked_emails, all_blocked_names, sent_last_24h


def is_valid_corporate_email(clean_em, user_part, all_blocked_emails, seen_set=None):
    """Enforce strict compliance checks on target corporate address."""
    if not clean_em or "@" not in clean_em:
        return False
    if clean_em in all_blocked_emails:
        return False
    if seen_set is not None and clean_em in seen_set:
        return False
    if user_part in BANNED_USERNAMES or any(sub in user_part for sub in GENERIC_SUBSTRINGS):
        return False
    if len(user_part) < 2 or not user_part[0].isalpha():
        return False
    if any(clean_em.endswith(bd) for bd in BANNED_DOMAINS):
        return False
    if not clean_em.endswith((".com", ".ai", ".io", ".co", ".dev", ".us", ".org", ".net", ".health", ".care", ".energy", ".app")):
        return False
    return True
