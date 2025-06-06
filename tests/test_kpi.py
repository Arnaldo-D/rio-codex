import pandas as pd, os

ROI_MIN     = 15
PASS_RATIO  = 0.90      # 90 %
RISK_REQ    = "Basso"   # valore richiesto nella colonna “rischio”

def test_kpi():
    csv = "rio_best_precision.csv"
    assert os.path.exists(csv), f"{csv} non generato"

    df = pd.read_csv(csv)

    passed = df[(df["ROI_preciso"] >= ROI_MIN) &
                (df["rischio"] == RISK_REQ)]

    ratio = len(passed) / len(df) if len(df) else 0
    assert ratio >= PASS_RATIO, (
        f"KPI FAIL  –  {ratio:.1%} record soddisfano ROI≥{ROI_MIN} "
        f"e rischio=={RISK_REQ}"
    )
