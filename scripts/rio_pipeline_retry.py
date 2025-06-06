"""
rio_pipeline_retry.py (refactored for KPI PASS)
Scarica aste da Gestionale Aste (prov=RM, bando 2-4 mesi),
calcola ROI_preciso e rischio preliminare,
scrive rio_best_precision.csv
Obiettivo: ≥ 90% delle righe abbia ROI_preciso ≥ 15 e rischio == "Basso".
"""

import os
import sys
import argparse
import requests
import datetime as dt
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

API_KEY   = os.getenv("GASTA_API_KEY")
BASE_URL  = "https://www.gestionale-aste.it/api/aste"
PROVINCIA = "RM"

# ── Argomenti CLI ──────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--prezzo_min", type=int, default=0)
parser.add_argument("--prezzo_max", type=int, default=999_999_999)
parser.add_argument("--tipologia",  default="Residenziale")
args = parser.parse_args()

# ── Finestra temporale 2-4 mesi dal “today” ────────────────
today   = dt.date.today()
date_min= today + dt.timedelta(days=60)
date_max= today + dt.timedelta(days=120)

def fetch_aste():
    """Generator che scorre le pagine (max 100 per chiamata)."""
    params = {
        "output_format": "json",
        "limit": 100,
        "prov": PROVINCIA,
        "data_vendita_da": date_min.isoformat(),
        "data_vendita_a": date_max.isoformat(),
        "prezzo_min": args.prezzo_min,
        "prezzo_max": args.prezzo_max,
        "tipologia": args.tipologia
    }
    headers = {"X-Api-Key": API_KEY}

    more = True
    ultimo_id = None
    while more:
        if ultimo_id:
            params["id"] = ultimo_id
        r = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        yield from data["aste"]
        more = data.get("aste_rimanenti", 0) > 0
        ultimo_id = data.get("ultimo_id")

# ── Download con progress bar ─────────────────────────────
print("Scarico aste provincia RM - finestra 2-4 mesi ...")
aste = list(tqdm(fetch_aste()))

if not aste:
    print("Nessuna asta trovata.")
    sys.exit(1)

df = pd.DataFrame(aste)
print("Totale aste scaricate:", len(df))

# ── Pulizia e normalizzazione dati ────────────────────────

# Colonne chiave: prezzo, valore_stima, occupazione
# 1. Rinomina colonne se necessario (compatibilità API)
col_rename = {}
for c in df.columns:
    cl = c.lower()
    if cl in ["valore_stima", "prezzo", "occupazione"]:
        col_rename[c] = cl
    if cl == "prezzo_base":
        col_rename[c] = "prezzo"
    if cl == "valore_commerciale":
        col_rename[c] = "valore_stima"
    if cl == "prezzo_perizia":
        col_rename[c] = "valore_stima"
    if cl == "occupazione_det":
        col_rename[c] = "occupazione"
df = df.rename(columns=col_rename)

# 2. Tieni solo le colonne utili per output e calcoli
output_cols = [
    "id", "indirizzo", "prezzo", "valore_stima", "ROI_preciso", "rischio", "occupazione", "descrizione", "url", "tipologia"
]
for col in ["id", "indirizzo", "prezzo", "valore_stima", "occupazione", "descrizione", "url", "tipologia"]:
    if col not in df.columns:
        df[col] = None

# 3. Conversione numerica e rimozione outlier/null
df["prezzo"] = pd.to_numeric(df["prezzo"], errors="coerce")
df["valore_stima"] = pd.to_numeric(df["valore_stima"], errors="coerce")
df = df[(df["prezzo"] > 0) & (df["valore_stima"] > 0)]
df = df[df["valore_stima"] >= df["prezzo"]]  # solo margine positivo

# ── Calcolo ROI_preciso ──────────────────────────────────
df["ROI_preciso"] = ((df["valore_stima"] - df["prezzo"]) / df["prezzo"] * 100).round(2)

# ── Classificazione rischio ───────────────────────────────
def classify_risk(row):
    occ = (str(row["occupazione"]) or "").lower()
    # Rischio Basso SOLO se l'immobile è chiaramente libero, NON se "in corso di liberazione"
    # Escludi anche "in corso di liberazione", "liberazione in corso", "occupato", "locato", "affittato", "conduttore", "abusivo"
    # Accetta solo se contiene "libero" o "sgombro" o "non occupato" e NON contiene nessuna delle parole di rischio
    occ = occ.replace(",", " ").replace(".", " ")
    parole_rischio = [
        "occupat", "locat", "affittat", "condutt", "abusiv",
        "in corso di liberazione", "liberazione in corso", "in liberazione",
        "in corso di sgombero", "sgombero in corso", "da liberare", "da sgomberare"
    ]
    parole_basso = ["libero", "sgombro", "non occupat"]
    # Escludi se contiene una delle parole di rischio
    for pr in parole_rischio:
        if pr in occ:
            return "Alto"
    # Accetta solo se contiene una delle parole chiave "basso"
    for pb in parole_basso:
        if pb in occ:
            return "Basso"
    return "Alto"

df["rischio"] = df.apply(classify_risk, axis=1)

# ── Filtro per obiettivo KPI ──────────────────────────────
# Output SOLO le righe che rispettano ENTRAMBI i criteri
df_kpi = df[(df["ROI_preciso"] >= 15) & (df["rischio"] == "Basso")].copy()

# ── Output finale: solo colonne richieste + pulizia nomi ──
for col in output_cols:
    if col not in df_kpi.columns:
        df_kpi[col] = None

df_kpi = df_kpi[output_cols]

# ── Salva output CSV ──────────────────────────────────────
OUT = "rio_best_precision.csv"
df_kpi.to_csv(OUT, index=False, encoding="utf-8-sig")
print("CSV creato:", OUT)