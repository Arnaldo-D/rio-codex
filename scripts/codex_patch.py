import subprocess, pathlib, os, openai, tempfile, textwrap, json, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

def sh(cmd): return subprocess.run(cmd, shell=True, text=True,
                                   capture_output=True, check=True).stdout

def read(p): return (ROOT/p).read_text()

def build_prompt():
    failures = read("test_failures.txt")[:1500]
    src      = read("scripts/rio_pipeline_retry.py")[:4000]
    tests    = read("tests/test_kpi.py")[:1500]

    return textwrap.dedent(f"""
    You are Codex acting as an automated CI fixer.

    Project RIO KPI (must all pass):
      • ROI_preciso ≥ 15
      • rischio == "Basso"
      • pass_ratio ≥ 0.90

    Current failing tests:
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

    Provide **only** a valid unified git diff that fixes the failures without
    breaking existing logic. No commentary, no markdown fences.
    """).strip()

def call_codex(prompt):
    r = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.1,
    )
    return r.choices[0].message.content

def apply_patch(patch):
    with tempfile.NamedTemporaryFile('w+', delete=False) as tf:
        tf.write(patch)
    subprocess.run(f"git apply {tf.name}", shell=True, check=True)
    os.unlink(tf.name)

if __name__ == "__main__":
    prompt = build_prompt()
    patch  = call_codex(prompt)
    apply_patch(patch)
    try:
        sh("pytest -q")
    except subprocess.CalledProcessError:
        print("Patch failed or tests still red")
        sys.exit(1)
