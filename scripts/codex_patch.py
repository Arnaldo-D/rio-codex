import subprocess, pathlib, os, tempfile, textwrap, sys, openai

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------
# utility shell
def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, text=True,
                          capture_output=True, check=True).stdout

# ---------------------------------------------------------------------
# trova il log dei test falliti in qualsiasi layout di artifact
def load_failures() -> str:
    """Restituisce il contenuto del log dei test falliti (max 1 500 caratteri).
    Cerca in varie posizioni compatibili con GitHub Actions:
    1.   test_failures/pytest.log   ← struttura di download-artifact
    2.   pytest.log                 ← fallback
    3.   test_failures.txt          ← vecchio nome
    Ritorna stringa vuota se non trova nulla.
    """
    candidates = [
        ROOT / "test_failures" / "pytest.log",
        ROOT / "pytest.log",
        ROOT / "test_failures.txt",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text()[:1500]
    return "Failure log not found."

# ---------------------------------------------------------------------
# costruiamo il prompt
def build_prompt() -> str:
    failures = load_failures()
    src  = (ROOT / "scripts" / "rio_pipeline_retry.py").read_text()[:4000]
    tests = (ROOT / "tests" / "test_kpi.py").read_text()[:1500]

    return textwrap.dedent(f"""
    You are Codex acting as an automated CI fixer for project RIO.

    KPI to satisfy:
      • ROI_preciso >= 15
      • rischio == "Basso"
      • pass_ratio >= 0.90

    Failing tests log (trimmed):
    ```text
    {failures}
    ```

    Current code (trimmed):
    ### rio_pipeline_retry.py
    ```python
    {src}
    ```
    ### test_kpi.py
    ```python
    {tests}
    ```

    Respond with **ONLY** a valid unified git diff that fixes the failure.
    Do not add explanations or markdown fences.
    """).strip()

# ---------------------------------------------------------------------
# chiama OpenAI e ottiene il diff
def call_codex(prompt: str) -> str:
    return openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    ).choices[0].message.content

# ---------------------------------------------------------------------
# applica il diff al repo
def apply_patch(patch: str):
    with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
        tf.write(patch)
    try:
        sh(f"git apply {tf.name}")
    finally:
        os.unlink(tf.name)

# ---------------------------------------------------------------------
if __name__ == "__main__":
    prompt = build_prompt()
    patch  = call_codex(prompt)
    apply_patch(patch)

    # riesegui i test – se falliscono, esce con code 1 e la job segnala failure
    try:
        sh("pytest -q")
    except subprocess.CalledProcessError as e:
        sys.stderr.write("Tests still failing after patch\n")
        sys.exit(e.returncode)
