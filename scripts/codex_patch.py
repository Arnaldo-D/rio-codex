#!/usr/bin/env python3
"""
Codex Auto-Fix helper
--------------------

• Riceve il log dei test falliti (pytest.log) dall’artifact `test_failures`
• Costruisce un prompt per GPT-4o-mini con il contesto del codice
• Ottiene un diff unificato e lo applica:
    1. prova `git apply --check` (rigoroso)
    2. se fallisce, tenta `patch -p1 --fuzz=3` (applica con contesto fuzzy)
• Rilancia `pytest -q` – se i test restano rossi il workflow termina failure
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import pathlib

from openai import OpenAI

# -----------------------------------------------------------
# 0 · Config
# -----------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[1]

client = OpenAI()        # legge OPENAI_API_KEY dall'ambiente GitHub
client.timeout = 120     # fail-fast se l'API impiega > 120 s

MODEL = "gpt-4o-mini"
PATCH_TARGET = "scripts/rio_pipeline_retry.py"


# -----------------------------------------------------------
# utilità shell
# -----------------------------------------------------------
def sh(cmd: str) -> str:
    """Esegue un comando shell e restituisce stdout, solleva se exit≠0."""
    return subprocess.run(
        cmd, shell=True, text=True, capture_output=True, check=True
    ).stdout


# -----------------------------------------------------------
# 1 · Legge il log dei test falliti (artifact)
# -----------------------------------------------------------
def load_failures(max_chars: int = 1500) -> str:
    for path in [
        ROOT / "test_failures" / "pytest.log",
        ROOT / "pytest.log",
        ROOT / "test_failures.txt",
    ]:
        if path.exists():
            return path.read_text()[:max_chars]
    return "Failure log not found."


# -----------------------------------------------------------
# 2 · Prompt builder
# -----------------------------------------------------------
def build_prompt() -> str:
    failures = load_failures()
    src = (ROOT / PATCH_TARGET).read_text()[:4000]
    tests = (ROOT / "tests" / "test_kpi.py").read_text()[:1500]

    prompt = f"""
You are Codex acting as an automated CI fixer for project RIO.

### KPI that *must* be satisfied
• ROI_preciso ≥ 15
• rischio == "Basso"
• pass_ratio ≥ 0.90

### Failing tests (trimmed):
```text
{failures}
