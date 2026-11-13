#!/usr/bin/env python3
"""
GitHub Maintainers & Commercial Open-Source (COSS) Email Sourcing Engine.
Leverages git commit author metadata and public developer events to extract
genuine, deliverable corporate emails of CTOs, core maintainers, and systems engineers.
"""

import html
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

# Top commercial open-source and venture-backed AI/systems repositories
TARGET_REPOSITORIES = [
    ("vllm-project", "vllm", "vLLM", "vllm.ai"),
    ("sgl-project", "sglang", "SGLang", "sglang.ai"),
    ("langchain-ai", "langchain", "LangChain", "langchain.com"),
    ("run-llama", "llama_index", "LlamaIndex", "llamaindex.ai"),
    ("chroma-core", "chroma", "Chroma", "trychroma.com"),
    ("qdrant", "qdrant", "Qdrant", "qdrant.tech"),
    ("lancedb", "lancedb", "LanceDB", "lancedb.com"),
    ("astral-sh", "uv", "Astral", "astral.sh"),
    ("astral-sh", "ruff", "Astral", "astral.sh"),
    ("pydantic", "pydantic", "Pydantic", "pydantic.dev"),
    ("modal-labs", "modal-client", "Modal Labs", "modal.com"),
    ("dspy-ai", "dspy", "DSPy", "dspy.ai"),
    ("crewAIInc", "crewAI", "CrewAI", "crewai.com"),
    ("denoland", "deno", "Deno", "deno.com"),
    ("oven-sh", "bun", "Bun", "bun.com"),
    ("prisma", "prisma", "Prisma", "prisma.io"),
    ("resend", "resend-node", "Resend", "resend.com"),
    ("clerk", "javascript", "Clerk", "clerk.com"),
    ("supabase", "supabase", "Supabase", "supabase.com"),
    ("temporalio", "sdk-python", "Temporal", "temporal.io"),
    ("posthog", "posthog", "PostHog", "posthog.com"),
    ("weaviate", "weaviate", "Weaviate", "weaviate.io"),
    ("bentoml", "BentoML", "BentoML", "bentoml.com"),
    ("cockroachdb", "cockroach", "Cockroach Labs", "cockroachlabs.com"),
    ("unstructured-io", "unstructured", "Unstructured", "unstructured.io"),
    ("ollama", "ollama", "Ollama", "ollama.com")
]


def fetch_commits(owner, repo):
    """Fetch recent commits from GitHub public repository API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=100"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/vnd.github.v3+json"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except Exception:
        return []


def harvest_github_leads(max_leads=100):
    """Scrape and verify active corporate maintainers from target repos."""
    all_blocked_emails, all_blocked_names, _ = load_historical_exclusions()
    seen_emails = set()
    leads = []

    print(f"Scanning {len(TARGET_REPOSITORIES)} tier-1 open source repositories...")

    def process_repo(item):
        owner, repo, comp_name, comp_domain = item
        commits = fetch_commits(owner, repo)
        found = []
        for c in commits:
            commit_data = c.get("commit", {})
            author = commit_data.get("author", {})
            name = (author.get("name") or "").strip()
            raw_em = (author.get("email") or "").strip()
            if not raw_em or not name or len(name) < 3:
                continue

            # Skip GitHub bot/noreply addresses
            if "noreply" in raw_em.lower() or "dependabot" in raw_em.lower() or "actions@github.com" in raw_em.lower():
                continue

            raw_em, clean_em, user_part = normalize_email(raw_em)
            if not is_valid_corporate_email(clean_em, user_part, all_blocked_emails, seen_emails):
                continue

            domain = clean_em.split("@")[1]
            # Prioritize company matching domains or valid commercial domains
            if domain == comp_domain or not any(d in domain for d in ["gmail", "yahoo", "hotmail", "outlook", "users.noreply"]):
                seen_emails.add(clean_em)
                found.append({
                    "name": name,
                    "email": clean_em,
                    "company": comp_name,
                    "domain": domain,
                    "role": "Core Maintainer / Systems Engineer",
                    "source": f"https://github.com/{owner}/{repo}",
                    "repo": f"{owner}/{repo}"
                })
        return found

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(process_repo, TARGET_REPOSITORIES))

    all_raw = [item for sublist in results for item in sublist]

    # DNS MX Verification
    verified = []
    for lead in all_raw:
        if has_valid_mx(lead["domain"]):
            verified.append(lead)
            if len(verified) >= max_leads:
                break

    print(f"Discovered {len(verified)} verified corporate engineering maintainers.")
    return verified


if __name__ == "__main__":
    leads = harvest_github_leads(max_leads=50)
    print(f"Sample discovered maintainers ({len(leads)} total):")
    for l in leads[:10]:
        print(f" - {l['name']} <{l['email']}> @ {l['company']} ({l['source']})")
