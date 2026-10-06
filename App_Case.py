import base64
import io
import os
import re
from datetime import datetime
import pandas as pd
import requests
import streamlit as st

# Configurazione Pagina
st.set_page_config(page_title="Catalogo Case in Affitto", layout="wide")

FILE_CSV_LOCALE = "case_in_affitto.csv"

COLONNE = [
    "Titolo Casa",
    "Data Inserimento",
    "Giorno/Ora Visita",
    "Visita Effettuata",
    "Contatto Telefonico",
    "Voto",
    "Prezzo Immobile (€)",
    "Spese (€)",
    "Prezzo Totale (€)",
    "Metri Quadri (m²)",
    "Prezzo al m² (€/m²)",
    "Piano",
    "Ascensore",
    "Riscaldamento",
    "Condizionatore",
    "Numero Vani",
    "Classe Energetica",
    "Stazione Treno",
    "Metro Vicina",
    "Linea Metro",
    "Fermata Metro",
    "Note",
    "Link",
]

COLONNE_NUMERICHE = [
    "Prezzo Immobile (€)",
    "Spese (€)",
    "Prezzo Totale (€)",
    "Metri Quadri (m²)",
    "Prezzo al m² (€/m²)",
    "Voto",
]

# PRE-COMPILAZIONE REGEX (per velocizzare l'estrazione dati)
RE_PREZZO = re.compile(r"(?:€|euro)\s*([\d\.]+)|([\d\.]+)\s*(?:€|euro)", re.IGNORECASE)
RE_SPESE = re.compile(r"(?:spese|condominio|spese condominiali|utenze)\b[^\d]*(\d+)", re.IGNORECASE)
RE_MQ = re.compile(r"(\d+)\s*(?:mq|m2|m²|metri quadri)", re.IGNORECASE)
RE_PIANO = re.compile(r"(\d+)°?\s*piano|piano\s*(\d+|terra|rialzato|attico)", re.IGNORECASE)
RE_VANI = re.compile(r"(\d+)\s*(?:locali|vani|camere)|monolocale|bilocale|trilocale|quadrilocale", re.IGNORECASE)
RE_CLASSE = re.compile(r"classe\s*energetica\s*:?\s*([a-g][1-3]?)", re.IGNORECASE)
RE_FERMATA = re.compile(r"(?:metro|metropolitana)\s*(?:linea\s*[abc1]+)?\s*(?:fermata|stazione)?\s*([a-zàèéìòù\s'-]{3,20})", re.IGNORECASE)
RE_TRENO = re.compile(r"(?:stazione|treno|fl\d|fm\d)\s*(?:di|fs)?\s*([a-zàèéìòù\s'-]{3,25})", re.IGNORECASE)
RE_TEL = re.compile(r"(\+?39[\s.-]?)?(3\d{2}[\s.-]?\d{3,4}[\s.-]?\d{3,4}|0\d{1,4}[\s.-]?\d{5,8})")


def calcola_prezzo_mq(df):
    """Calcola in modo vettoriale il prezzo al metro quadro."""
    prezzo_tot = pd.to_numeric(df["Prezzo Totale (€)"], errors="coerce").fillna(0.0)
    mq = pd.to_numeric(df["Metri Quadri (m²)"], errors="coerce").fillna(0.0)
    df["Prezzo al m² (€/m²)"] = (prezzo_tot / mq).where(mq > 0, 0.0).round(2)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def _scarica_dati_raw():
    """Scarica i dati e li mantiene in cache RAM per 5 minuti."""
    df = None
    sha = None
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            token = st.secrets["GITHUB_TOKEN"]
            repo = st.secrets["GITHUB_REPO"]
            url = f"https://api.github.com/repos/{repo}/contents/case_in_affitto.csv"
            headers = {"Authorization": f"token {token}"}
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                content_json = res.json()
                csv_text = base64.b64decode(content_json["content"]).decode("utf-8")
                df = pd.read_csv(io.StringIO(csv_text))
                sha = content_json["sha"]
        except Exception:
            pass

    if df is None and os.path.exists(FILE_CSV_LOCALE):
        try:
            df = pd.read_csv(FILE_CSV_LOCALE)
        except Exception:
            pass

    if df is None:
        df = pd.DataFrame(columns=COLONNE)

    # Inizializzazione e sanitizzazione rapida
    for col in COLONNE:
        if col not in df.columns:
