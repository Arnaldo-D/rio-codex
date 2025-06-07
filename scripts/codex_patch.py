import subprocess, pathlib, os, tempfile, textwrap, sys
from openai import OpenAI   # nuova API (>=1.0)

ROOT   = pathlib.Path(__file__).resolve().parents[1]
client = OpenAI()           # legge OPENAI_API_KEY da variabile d’ambiente
client.timeout = 120        # fail fast se l’API impiega >120 s

# ----------------------------------------------------------------------
def sh(cmd: str) -> str:
    """Esegue comando shell e ritorna stdout."""
    return subprocess.run(cmd, shell=True, text=True,
                          capture_output=True, check=True).stdout

# ----------------------------------------------------------------------
def load_failures(max_chars: int = 1500) -> str:
    """Legge il log dei test falliti da vari percorsi possibili."""
    for p in [
        ROOT / "test_failures" / "pytest.log",
        ROOT / "pytest.log",
        ROOT / "test_failures.txt",
    ]:
        if p.exists():
            return p.read_text()[:max_chars]
    return "Failure log not found."

# ----------------------------------------------------------------------
def build_prompt() -> str:
    failures = load_failures()
    src   = (ROOT / "scripts" / "rio_pipeline_retry.py").read_text()[:4000]
    tests = (ROOT / "tests" / "test_kpi.py").read_text()[:1500]

    return textwrap.dedent(f"""
    You are Codex acting as an automated CI fixer for project RIO.

    KPI to satisfy:
      • ROI_preciso ≥ 15
      • rischio == "Basso"
      • pass_ratio ≥ 0.90

    Failing tests log:
    ```text
    {failures}
    ```

    Code context:
    ### rio_pipeline_retry.py
    ```python
    {src}
    ```
    ### test_kpi.py
    ```python
    {tests}
    ```

    Return ONLY a valid unified git diff that fixes the failure.
    Do not add explanations or markdown fences.
    """).strip()

# ----------------------------------------------------------------------
def diff_from_codex(prompt: str) -> str:
    """Invia il prompt a GPT-4o-mini e restituisce il diff."""
    print("⇢ Calling OpenAI…", flush=True)
    rsp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        request_timeout=120,       # timeout per questa singola request
    )
    print("✓ Received diff", flush=True)
    return rsp.choices[0].message.content

# ----------------------------------------------------------------------
def apply_patch(patch: str):
    """Applica il diff git ricevuto da Codex."""
    with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
        tf.write(patch)
    try:
        sh(f"git apply {tf.name}")
    finally:
        os.unlink(tf.name)

# ----------------------------------------------------------------------
if __name__ == "__main__":
    patch = diff_from_codex(build_prompt())
    apply_patch(patch)

    # riesegui i test; se falliscono, il job Actions terminerà failure
    try:
        sh("pytest -q")
    except subprocess.CalledProcessError as e:
        sys.stderr.write("Tests still failing after patch\n")
        sys.exit(e.returncode)
