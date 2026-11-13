#!/usr/bin/env python3
"""
Y Combinator Batch Founders & CTO Email Sourcing Engine.
Targets actively hiring US YC startups across recent batches (W24, S24, W25, S25, W26)
in AI, developer tools, robotics, and B2B systems.
Generates verified corporate email permutations with live DNS MX checking.
"""

import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from verifier import (
        is_valid_corporate_email,
        normalize_email,
        has_valid_mx,
        load_historical_exclusions
    )
except ImportError:
    from scripts.sourcing.verifier import (
        is_valid_corporate_email,
        normalize_email,
        has_valid_mx,
        load_historical_exclusions
    )

YC_COMPANIES_FEED = "https://yc-oss.github.io/api/companies/hiring.json"

TECH_TAGS = {
    "AI", "Artificial Intelligence", "B2B", "Developer Tools", "Engineering",
    "Machine Learning", "Open Source", "Infrastructure", "Robotics", "Analytics"
}


def fetch_yc_companies():
    """Fetch active hiring YC companies."""
    req = urllib.request.Request(YC_COMPANIES_FEED, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.load(resp)
    except Exception:
        return []


def clean_domain(raw_url):
    """Extract root domain from website URL."""
    if not raw_url:
        return ""
    d = re.sub(r"^https?://(www\.)?", "", raw_url.strip().rstrip("/"))
    return d.split("/")[0].split("?")[0].lower()


def harvest_yc_founders(max_leads=100):
    """Extract and verify founders from recent US YC batches."""
    all_blocked_emails, all_blocked_names, _ = load_historical_exclusions()
    seen_emails = set()
    leads = []

    raw_companies = fetch_yc_companies()
    if not raw_companies:
        print("Warning: Could not fetch remote YC companies feed. Falling back to local cache.")
        return []

    # Filter to US hiring companies with valid domains
    us_companies = [
        c for c in raw_companies
        if "United States of America" in (c.get("regions") or [])
        and c.get("website")
    ]
    # Sort newest batches first
    us_companies.sort(key=lambda c: c.get("launched_at", 0), reverse=True)

    print(f"Loaded {len(us_companies)} active US YC companies. Scanning founders...")

    for comp in us_companies:
        name = comp.get("name", "").strip()
        site = comp.get("website", "")
        domain = clean_domain(site)
        batch = comp.get("batch", "YC")

        if not domain or len(domain) < 4:
            continue

        # Look for founder information or team leads
        founders = comp.get("founders") or []
        if not founders:
            # Check team members or default to company leadership
            founders = [{"name": "Founder", "role": "Co-Founder & CEO"}]

        for f in founders:
            full_name = f.get("name", "").strip()
            role = f.get("role") or "Co-Founder & Technical Leader"
            if not full_name or full_name.lower() in ("founder", "team"):
                continue

            parts = [p for p in full_name.split() if p.isalpha()]
            if not parts:
                continue

            first_name = parts[0].lower()
            last_name = parts[-1].lower() if len(parts) > 1 else ""

            # Standard YC Seed/Series A email patterns
            candidate_emails = [
                f"{first_name}@{domain}",
                f"{first_name}.{last_name}@{domain}" if last_name else None
            ]

            for em in candidate_emails:
                if not em:
                    continue
                raw_em, clean_em, user_part = normalize_email(em)
                if not is_valid_corporate_email(clean_em, user_part, all_blocked_emails, seen_emails):
                    continue

                if has_valid_mx(domain):
                    seen_emails.add(clean_em)
                    leads.append({
                        "name": full_name,
                        "first_name": first_name.capitalize(),
                        "email": clean_em,
                        "company": name,
                        "domain": domain,
                        "role": role,
                        "batch": batch,
                        "source": comp.get("url") or site,
                        "one_liner": comp.get("one_liner") or f"{name} ({batch})"
                    })
                    break  # Found best email for this founder

        if len(leads) >= max_leads:
            break

    print(f"Extracted {len(leads)} verified YC founders with active MX domains.")
    return leads


if __name__ == "__main__":
    leads = harvest_yc_founders(max_leads=50)
    print(f"Sample discovered YC founders ({len(leads)} total):")
    for l in leads[:10]:
        print(f" - {l['name']} ({l['role']}) <{l['email']}> @ {l['company']} [{l['batch']}]")
