#!/usr/bin/env python3
"""
Venture Capital Portfolio & High-Growth AI Startup Sourcing Engine.
Curates leadership contacts across top venture-backed AI, robotics, and developer infrastructure portfolios
(a16z AI, Sequoia Capital, Founders Fund, Benchmark, Lightspeed, AI Grant, Amplify).
"""

import os
import re

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

# Curated tier-1 venture-backed AI and systems startups with known technical founders
CURATED_PORTFOLIO_LEADERS = [
    # Baseten (Greylock / Spark Capital)
    {"name": "Tuhin Srivastava", "company": "Baseten", "domain": "baseten.co", "role": "Co-Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Philip Howes", "company": "Baseten", "domain": "baseten.co", "role": "Co-Founder & Head of AI", "location": "San Francisco, CA"},
    {"name": "Pankaj Gupta", "company": "Baseten", "domain": "baseten.co", "role": "VP of Engineering", "location": "San Francisco, CA"},

    # Fireworks AI (Benchmark / Sequoia)
    {"name": "Lin Qiao", "company": "Fireworks AI", "domain": "fireworks.ai", "role": "Co-Founder & CEO", "location": "Redwood City, CA"},
    {"name": "Dmytro Dzhulgakov", "company": "Fireworks AI", "domain": "fireworks.ai", "role": "Co-Founder & Head of Systems", "location": "Redwood City, CA"},

    # Anyscale (Andreessen Horowitz / NEA)
    {"name": "Robert Nishihara", "company": "Anyscale", "domain": "anyscale.com", "role": "Co-Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Philipp Moritz", "company": "Anyscale", "domain": "anyscale.com", "role": "Co-Founder & Systems Lead", "location": "San Francisco, CA"},
    {"name": "Richard Liaw", "company": "Anyscale", "domain": "anyscale.com", "role": "Head of Applied AI", "location": "San Francisco, CA"},

    # BentoML (DCM / Bow Capital)
    {"name": "Chaoyu Yang", "company": "BentoML", "domain": "bentoml.com", "role": "Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Jason Liang", "company": "BentoML", "domain": "bentoml.com", "role": "Co-Founder & Head of Platform", "location": "San Francisco, CA"},

    # Modal Labs (Redpoint / Amplify Partners)
    {"name": "Erik Bernhardsson", "company": "Modal Labs", "domain": "modal.com", "role": "Founder & CEO", "location": "New York, NY"},
    {"name": "Akshat Bubna", "company": "Modal Labs", "domain": "modal.com", "role": "Co-Founder", "location": "New York, NY"},

    # Augment Code (Sutter Hill Ventures / Index Ventures)
    {"name": "Scott Dietzen", "company": "Augment Code", "domain": "augmentcode.com", "role": "CEO", "location": "Palo Alto, CA"},
    {"name": "Igor Ostrovsky", "company": "Augment Code", "domain": "augmentcode.com", "role": "Co-Founder & Chief Architect", "location": "Palo Alto, CA"},

    # Codeium (Kleiner Perkins / General Catalyst)
    {"name": "Varun Mohan", "company": "Codeium", "domain": "codeium.com", "role": "Co-Founder & CEO", "location": "Mountain View, CA"},
    {"name": "Douglas Chen", "company": "Codeium", "domain": "codeium.com", "role": "Co-Founder & Head of Systems", "location": "Mountain View, CA"},

    # Galileo (The AI Evaluation Platform - Battery Ventures)
    {"name": "Vikram Sreekanti", "company": "Galileo", "domain": "rungalileo.io", "role": "Co-Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Atin Sanyal", "company": "Galileo", "domain": "rungalileo.io", "role": "Co-Founder & CTO", "location": "San Francisco, CA"},

    # Together AI (Lux Capital / Kleiner Perkins)
    {"name": "Vipul Ved Prakash", "company": "Together AI", "domain": "together.ai", "role": "Co-Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Ce Zhang", "company": "Together AI", "domain": "together.ai", "role": "Co-Founder & CTO", "location": "San Francisco, CA"},

    # RunPod (Intel Capital / Dell Technologies Capital)
    {"name": "Zhen Lu", "company": "RunPod", "domain": "runpod.io", "role": "Co-Founder & CEO", "location": "Mount Laurel, NJ / NYC"},
    {"name": "Brendan Hogan", "company": "RunPod", "domain": "runpod.io", "role": "Co-Founder & CTO", "location": "Mount Laurel, NJ / NYC"},

    # Groq (D1 Capital / Addition)
    {"name": "Jonathan Ross", "company": "Groq", "domain": "groq.com", "role": "Founder & CEO", "location": "Mountain View, CA"},
    {"name": "Sunny Madra", "company": "Groq", "domain": "groq.com", "role": "Head of AI Hardware & Platform", "location": "Mountain View, CA"},

    # Unstructured.io (Bain Capital Ventures / Mango Capital)
    {"name": "Brian Raymond", "company": "Unstructured", "domain": "unstructured.io", "role": "Founder & CEO", "location": "San Francisco, CA"},

    # LanceDB (Matrix Partners)
    {"name": "Chang She", "company": "LanceDB", "domain": "lancedb.com", "role": "Co-Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Lei Xu", "company": "LanceDB", "domain": "lancedb.com", "role": "Co-Founder & CTO", "location": "San Francisco, CA"},

    # Chroma (Quiet Capital / AI Grant)
    {"name": "Jeff Huber", "company": "Chroma", "domain": "trychroma.com", "role": "Co-Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Anton Troynikov", "company": "Chroma", "domain": "trychroma.com", "role": "Co-Founder & Architect", "location": "San Francisco, CA"},

    # Astral (uv / Ruff - Accel)
    {"name": "Charlie Marsh", "company": "Astral", "domain": "astral.sh", "role": "Founder & CEO", "location": "New York, NY"},

    # Qdrant (Spark Capital)
    {"name": "Andre Zayarni", "company": "Qdrant", "domain": "qdrant.tech", "role": "Co-Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Andrey Vasnetsov", "company": "Qdrant", "domain": "qdrant.tech", "role": "Co-Founder & CTO", "location": "San Francisco, CA"},

    # Neon (Postgres - Menlo Ventures / Founders Fund)
    {"name": "Nikita Shamgunov", "company": "Neon", "domain": "neon.tech", "role": "Founder & CEO", "location": "San Francisco, CA"},
    {"name": "Heikki Linnakangas", "company": "Neon", "domain": "neon.tech", "role": "Co-Founder & Architect", "location": "San Francisco, CA"}
]


def harvest_vc_portfolio_leads(max_leads=100):
    """Filter and verify corporate emails for venture-backed founders."""
    all_blocked_emails, all_blocked_names, _ = load_historical_exclusions()
    seen_emails = set()
    leads = []

    for item in CURATED_PORTFOLIO_LEADERS:
        name = item["name"]
        comp = item["company"]
        dom = item["domain"]
        role = item["role"]
        loc = item.get("location", "United States")

        parts = name.split()
        first_name = parts[0].lower()
        last_name = parts[-1].lower() if len(parts) > 1 else ""

        # Executive email patterns
        candidate_emails = [
            f"{first_name}@{dom}",
            f"{first_name}.{last_name}@{dom}" if last_name else None,
            f"{first_name[0]}{last_name}@{dom}" if last_name else None
        ]

        for em in candidate_emails:
            if not em:
                continue
            raw_em, clean_em, user_part = normalize_email(em)
            if not is_valid_corporate_email(clean_em, user_part, all_blocked_emails, seen_emails):
                continue

            if has_valid_mx(dom):
                seen_emails.add(clean_em)
                leads.append({
                    "name": name,
                    "first_name": parts[0],
                    "email": clean_em,
                    "company": comp,
                    "domain": dom,
                    "role": role,
                    "location": loc,
                    "source": f"VC Portfolio ({comp})"
                })
                break

        if len(leads) >= max_leads:
            break

    print(f"Extracted {len(leads)} verified VC-backed founders with active MX domains.")
    return leads


if __name__ == "__main__":
    leads = harvest_vc_portfolio_leads(max_leads=50)
    print(f"Sample discovered VC portfolio leaders ({len(leads)} total):")
    for l in leads[:10]:
        print(f" - {l['name']} ({l['role']}) <{l['email']}> @ {l['company']} [{l['location']}]")
