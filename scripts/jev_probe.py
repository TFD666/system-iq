"""
jev_probe.py – Send a single TypeSafe System One request through the
OpenCode /zen/ proxy and print the raw result.

Request format (from https://docs.typesafe.ai/api/system-one):

    POST /v1/systemone
    Authorization: Bearer <API_KEY>
    Content-Type: application/json

    {
      "model":     "<model name>",
      "state":     "<text or structured content>",
      "questions": {
        "<name>": {
          "type": "noul" | "choice" | "score",
          "instructions": "<what to evaluate>",
          "criteria": <dict for choice | list for score | optional for noul>
        },
        ...
      }
    }

Response:
    {
      "model":   "<resolved model>",
      "answers": { "<name>": { "type": "...", ... }, ... },
      "usage":   { "input_tokens": N, "output_tokens": N }
    }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ── Load key from backend/.env ──────────────────────────────────────────
ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"
load_dotenv(ENV_PATH)

api_key = os.environ.get("OPENCODE_API_KEY")
if not api_key:
    sys.exit("ERROR: OPENCODE_API_KEY not found in environment or backend/.env")

# ── Build request ───────────────────────────────────────────────────────
ENDPOINT = "https://opencode.ai/inference/systemone/v1/systemone"

payload = {
    "model": "jev-1.13-free",
    "state": "app to find nearby bars",
    "questions": {
        # Noul – yes/no probability
        "is_location_based": {
            "type": "noul",
            "instructions": "Does this app concept rely on the user's geographic location?",
        },
        # Score – ordered rubric (0-2)
        "market_saturation": {
            "type": "score",
            "instructions": "How saturated is the market for this kind of app?",
            "criteria": [
                "Niche – very few competitors",
                "Moderate – some well-known players",
                "Highly saturated – dominated by major apps",
            ],
        },
        # Choice – pick one of 3 options
        "primary_audience": {
            "type": "choice",
            "instructions": "Who is the primary target audience for this app?",
            "criteria": {
                "nightlife_enthusiasts": "People who regularly go out to bars and clubs",
                "casual_drinkers": "People who occasionally visit bars for social events",
                "tourists": "Travelers looking for local bar recommendations",
            },
        },
    },
}

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

# ── Send request ────────────────────────────────────────────────────────
print(f">> POST {ENDPOINT}")
print(f">> Model: {payload['model']}")
print(f">> State: {payload['state']!r}")
print(f">> Questions: {', '.join(payload['questions'])}")
print()

try:
    resp = httpx.post(ENDPOINT, json=payload, headers=headers, timeout=30)
except httpx.RequestError as exc:
    sys.exit(f"Connection error: {exc}")

# ── Print results ───────────────────────────────────────────────────────
print(f"HTTP status: {resp.status_code}")
print()

# Rate-limit headers
rl_headers = {
    k: v for k, v in resp.headers.items()
    if "rate" in k.lower() or "limit" in k.lower() or "retry" in k.lower()
}
if rl_headers:
    print("Rate-limit headers:")
    for k, v in rl_headers.items():
        print(f"  {k}: {v}")
    print()
else:
    print("(no rate-limit headers found)")
    print()

# Response body
try:
    body = resp.json()
    print("Response JSON:")
    print(json.dumps(body, indent=2))
except Exception:
    print("Response body (raw):")
    print(resp.text)

# ── Detect free-tier restriction ────────────────────────────────────────
body_text = resp.text.lower()
if (
    "free" in body_text
    and ("opencode" in body_text or "inside" in body_text)
) or resp.status_code in (401, 403):
    print()
    print("=" * 60)
    print("!!  The free tier (jev-1.13-free) only works inside the")
    print("    OpenCode environment. This key cannot be used externally.")
    print("=" * 60)
