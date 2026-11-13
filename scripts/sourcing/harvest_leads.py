#!/usr/bin/env python3
"""
Master Lead Harvester & Stager CLI.
Combines:
  1. Venture Capital AI Portfolios (Baseten, Anyscale, Fireworks, Modal, Codeium, Galileo)
  2. GitHub Commercial Open-Source Maintainers (vLLM, LangChain, LlamaIndex, Chroma, Deno, Bun)
  3. Y Combinator Recent Batch Founders (W24–S26 US AI & Systems)
Outputs fully staged, cap-safe outreach JSON ready for the autonomous dispatcher daemon.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    from verifier import (
        is_valid_corporate_email,
        normalize_email,
        has_valid_mx,
        load_historical_exclusions
    )
    from source_vc_portfolios import harvest_vc_portfolio_leads
    from source_github_maintainers import harvest_github_leads
    from source_yc_founders import harvest_yc_founders
except ImportError:
    from scripts.sourcing.verifier import (
        is_valid_corporate_email,
        normalize_email,
        has_valid_mx,
        load_historical_exclusions
    )
    from scripts.sourcing.source_vc_portfolios import harvest_vc_portfolio_leads
    from scripts.sourcing.source_github_maintainers import harvest_github_leads
    from scripts.sourcing.source_yc_founders import harvest_yc_founders

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PDF_PATH = os.path.join(WORKSPACE_ROOT, "resumess/Himadri_Motwani_AI_Software_Engineering_Outreach.pdf")
if not os.path.exists(PDF_PATH):
    resumes_dir = os.path.join(WORKSPACE_ROOT, "resumess")
    if os.path.exists(resumes_dir):
        pdfs = [os.path.join(resumes_dir, f) for f in os.listdir(resumes_dir) if f.lower().endswith(".pdf")]
        if pdfs:
            PDF_PATH = pdfs[0]
OUTREACH_ROOT = os.path.join(WORKSPACE_ROOT, "outputs/outreach")


def generate_email_body(first_name, company, role):
    """Generate strictly compliant outreach email matching approved facts."""
    return f"""Hi {first_name},

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


def harvest_and_stage(source="all", count=75, date_str=None, append=True):
    """Collect verified leads from requested sources and format into staged batch."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    all_blocked_emails, all_blocked_names, sent_last_24h = load_historical_exclusions()
    print(f"Historical exclusions: {len(all_blocked_emails)} emails | Rolling 24h sends: {sent_last_24h}/465")

    collected = []
    seen = set()

    # 1. VC Portfolios
    if source in ("all", "vc"):
        vc_leads = harvest_vc_portfolio_leads(max_leads=count)
        for l in vc_leads:
            if l["email"] not in seen and l["email"] not in all_blocked_emails:
                seen.add(l["email"])
                collected.append(l)

    # 2. GitHub Maintainers
    if len(collected) < count and source in ("all", "github"):
        needed = count - len(collected)
        gh_leads = harvest_github_leads(max_leads=needed + 20)
        for l in gh_leads:
            if l["email"] not in seen and l["email"] not in all_blocked_emails:
                seen.add(l["email"])
                collected.append(l)

    # 3. YC Batch Founders
    if len(collected) < count and source in ("all", "yc"):
        needed = count - len(collected)
        yc_leads = harvest_yc_founders(max_leads=needed + 20)
        for l in yc_leads:
            if l["email"] not in seen and l["email"] not in all_blocked_emails:
                seen.add(l["email"])
                collected.append(l)

    selected = collected[:count]
    print(f"Total pristine leads collected: {len(selected)} (Target: {count})")

    if not selected:
        print("No new uncontacted leads found.")
        return 0

    date_dir = os.path.join(OUTREACH_ROOT, date_str)
    os.makedirs(date_dir, exist_ok=True)
    staged_path = os.path.join(date_dir, "outreach-batch-staged.json")

    existing_records = []
    if os.path.exists(staged_path) and append:
        try:
            with open(staged_path) as f:
                existing_records = json.load(f).get("records", [])
        except Exception:
            existing_records = []

    start_idx = len(existing_records) + 1
    new_staged = []

    for offset, lead in enumerate(selected):
        idx = start_idx + offset
        prefix = f"O{date_str[5:7]}{date_str[8:10]}"
        draft_id = f"{prefix}_{idx:02d}"

        name = lead.get("name", "Engineering Leader")
        first_name = lead.get("first_name") or name.split()[0]
        company = lead["company"]
        role = lead.get("role") or "Engineering Leader"
        email = lead["email"]

        body = generate_email_body(first_name, company, role)

        new_staged.append({
            "id": draft_id,
            "batch": date_str,
            "draft_id": draft_id,
            "company": company,
            "person_name": name,
            "title": role,
            "email": email,
            "source_url": lead.get("source", "Corporate Engineering Lead"),
            "one_sentence_fit": "Engineered containerized multi-agent LLM platform, scientific ML data pipelines on A100 GPUs, and cut backend query latency by 40%.",
            "one_request": "Would your team consider my background for an engineering internship in January 2027 or full-time start in May 2027?",
            "subject": f"{company} Software Engineering (Early Career 2027) — systems & AI",
            "body": body,
            "attachment_paths": [PDF_PATH],
            "attachment_filename": "Himadri_Motwani_AI_Software_Engineering_Outreach.pdf",
            "status": "STAGED",
            "notes": f"Verified corporate lead ({lead.get('source', '')}): {name} <{email}>"
        })

    combined = existing_records + new_staged
    payload = {
        "date": date_str,
        "total_staged": len(combined),
        "confirmed_sends": sum(1 for r in combined if r.get("status") == "SENT"),
        "target_new_emails_per_day": 450,
        "daily_target": 450,
        "per_run_target": 75,
        "pulses_per_day": 6,
        "status": "STAGED_READY",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "records": combined
    }

    with open(staged_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Successfully staged {len(new_staged)} leads into {staged_path} (Total batch: {len(combined)}).")
    return len(new_staged)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Source Enterprise Lead Harvester")
    parser.add_argument("--source", default="all", choices=["all", "vc", "github", "yc"], help="Source to harvest from")
    parser.add_argument("--count", type=int, default=75, help="Number of verified leads to stage")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--no-append", action="store_true", help="Overwrite instead of appending")
    args = parser.parse_args()

    harvest_and_stage(
        source=args.source,
        count=args.count,
        date_str=args.date,
        append=not args.no_append
    )
