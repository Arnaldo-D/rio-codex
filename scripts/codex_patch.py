#!/usr/bin/env python3
"""
Codex Auto-Fix helper
--------------------

• Scarica il log `test_failures/pytest.log` (se presente)
• Costruisce un prompt per GPT-4o-mini con codice + log
• Riceve un diff (unified, --context=0) che sistema i test
• Applica il diff:
      1. git apply --check   – rigore assoluto
      2. patch -p1 --fuzz=3  – fallback tollerante
• Rilancia `pytest -q`; se i test falliscono, il job esce rosso
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import textwrap

from openai import OpenAI

# --------------------------------------------------#
# Config
# --------------------------------------------------#
ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH_TARGET = "scripts/rio_pipeline_retry.py"
MODEL = "gpt-4o-mini"

client = OpenAI()          # legge OPENAI_API_KEY
client.timeout = 120       # fail-fast 120 s


# --------------------------------------------------#
# Shell helper
# --------------------------------------------------#
def sh(cmd: str) -> str:
    """Esegue shell, ritorna stdout, solleva se exit-code ≠ 0."""
    return subprocess.run(
        cmd, shell=True, text=True, capture_output=True, check=True
    ).stdout


# --------------------------------------------------#
# Failure log loader
# --------------------------------------------------#
def load_failures(max_chars: int = 1500) -> str:
    for p in [
        ROOT / "test_failures" / "pytest.log",
        ROOT / "pytest.log",
        ROOT / "test_failures.txt",
    ]:
        if p.exists():
            return p.read_text()[:max_chars]
    return "Failure log not found."


# --------------------------------------------------#
# Prompt builder
# --------------------------------------------------#
def build_prompt() -> str:
    failures = load_failures()
    src   = (ROOT / PATCH_TARGET).read_text()[:4000]
    tests = (ROOT / "tests" / "test_kpi.py").read_text()[:1500]

    prompt = f"""
You are Codex acting as an automated CI fixer for project RIO.

### KPI to satisfy
• ROI_preciso ≥ 15
• rischio == "Basso"
• pass_ratio ≥ 0.90

### Failing tests (trimmed)
```text
{failures}
