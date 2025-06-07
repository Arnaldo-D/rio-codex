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

    Return ONLY a unified git diff.
          **All paths must be relative to the repository root.
           The file to patch is scripts/rio_pipeline_retry.py (not in root).**
 """).strip()

# ----------------------------------------------------------------------
def diff_from_codex(prompt: str) -> str:
    """Invia il prompt a GPT-4o-mini e restituisce il diff."""
    print("⇢ Calling OpenAI…", flush=True)
    rsp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    print("✓ Received diff", flush=True)
    return rsp.choices[0].message.content

# ----------------------------------------------------------------------
def apply_patch(patch: str):
    """Prova il diff in modalità --check prima di applicarlo.
       Se fallisce, stampa il patch per debug e solleva l'errore."""
    with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
        tf.write(patch)
    try:
        # dry-run: se non si applica, git restituisce exit code ≠ 0
        sh(f"git apply --check {tf.name}")
        # ok, lo applichiamo davvero
        sh(f"git apply {tf.name}")
    except subprocess.CalledProcessError:
        print("✗ Patch non applicabile — diff prodotto da Codex:\n")
        print(patch)
        raise
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
