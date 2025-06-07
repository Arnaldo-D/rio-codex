#!/usr/bin/env python3
"""
Codex Auto-Fix helper
--------------------

• Scarica il log `test_failures/pytest.log` (se presente)
• Costruisce un prompt con il codice e il log
• Chiede a GPT-4o-mini un diff che sistemi i test
• Applica il diff:
      1. git apply --check  (rigoroso)
      2. patch -p1 --fuzz=3 (fallback tollerante)
• Rilancia `pytest -q`; se fallisce, il job esce rosso.
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

client = OpenAI()          # legge OPENAI_API_KEY dal runner
client.timeout = 120       # fail-fast 120 s


# --------------------------------------------------#
# Helpers
# --------------------------------------------------#
def sh(cmd: str) -> str:
    """Esegue shell, ritorna stdout, solleva se exit-code ≠ 0."""
    return subprocess.run(cmd, shell=True, text=True,
                          capture_output=True, check=True).stdout


def load_failures(max_chars: int = 1500) -> str:
    """Restituisce il log dei test falliti (o placeholder)."""
    for p in [
        ROOT / "test_failures" / "pytest.log",
        ROOT / "pytest.log",
        ROOT / "test_failures.txt",
    ]:
        if p.exists():
            return p.read_text()[:max_chars]
    return "Failure log not found."


# --------------------------------------------------#
# Prompt
# --------------------------------------------------#
def build_prompt() -> str:
    failures = load_failures()
    src = (ROOT / PATCH_TARGET).read_text()[:4000]
    tests = (ROOT / "tests" / "test_kpi.py").read_text()[:1500]

    prompt = f"""
    You are Codex acting as an automated CI fixer for project RIO.

    KPI to satisfy:
      • ROI_preciso ≥ 15
      • rischio == "Basso"
      • pass_ratio ≥ 0.90

    ### Failing tests (trimmed)
    ```text
    {failures}
    ```

    ### Code context
    #### {PATCH_TARGET}
    ```python
    {src}
    ```
    #### tests/test_kpi.py
    ```python
    {tests}
    ```

    Return **ONLY** a valid unified git diff.
    The file to patch is `{PATCH_TARGET}` (path relative to repo root).
    IMPORTANT: generate the diff against the current HEAD so it applies
    cleanly with `git apply --check`, without any offsets.
    """
    return textwrap.dedent(prompt).strip()


# --------------------------------------------------#
# OpenAI call
# --------------------------------------------------#
def diff_from_codex(prompt: str) -> str:
    print("⇢ Calling OpenAI…", flush=True)
    rsp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    print("✓ Received diff", flush=True)
    return rsp.choices[0].message.content


# --------------------------------------------------#
# Apply patch (strict → fuzzy)
# --------------------------------------------------#
def apply_patch(patch: str):
    with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
        tf.write(patch)
        tmp = tf.name

    try:
        sh(f"git apply --check {tmp}")
        sh(f"git apply {tmp}")
        print("✓ Patch applied with git apply", flush=True)
    except subprocess.CalledProcessError:
        print("⚠️  git apply failed, retrying with patch --fuzz=3…", flush=True)
        try:
            sh(f"patch -p1 --fuzz=3 --batch < {tmp}")
            print("✓ Patch applied with patch --fuzz", flush=True)
        except subprocess.CalledProcessError as err:
            print("✗ Patch still not applicable — diff below:\n")
            print(patch)
            raise err
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


# --------------------------------------------------#
# Main
# --------------------------------------------------#
def main():
    diff = diff_from_codex(build_prompt())
    apply_patch(diff)

    try:
        sh("pytest -q")
    except subprocess.CalledProcessError as e:
        sys.stderr.write("Tests still failing after patch\n")
        sys.exit(e.returncode)


if __name__ == "__main__":
    main()
