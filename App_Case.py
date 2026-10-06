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
            if col == "Visita Effettuata":
                df[col] = False
            elif col in COLONNE_NUMERICHE:
                df[col] = 0.0
            elif col in ["Note", "Contatto Telefonico"]:
                df[col] = ""
            else:
                df[col] = "N/D"

    for col in COLONNE_NUMERICHE:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["Visita Effettuata"] = df["Visita Effettuata"].apply(
        lambda x: True if str(x).lower() in ["true", "1", "sì", "si"] or x is True else False
    )

    df["Note"] = df["Note"].fillna("")
    df["Contatto Telefonico"] = df["Contatto Telefonico"].astype(str).fillna("N/D")

    df = calcola_prezzo_mq(df)
    return df[COLONNE], sha


def carica_dati():
    """Interfaccia pulita per caricare i dati gestendo la cache e lo SHA di GitHub."""
    df, sha = _scarica_dati_raw()
    if sha:
        st.session_state["sha"] = sha
    return df.copy()


def salva_dati(df):
    """Salva il DataFrame e svuota la cache per aggiornare la memoria dell'app."""
    df = calcola_prezzo_mq(df)

    salvato = False
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            token = st.secrets["GITHUB_TOKEN"]
            repo = st.secrets["GITHUB_REPO"]
            url = f"https://api.github.com/repos/{repo}/contents/case_in_affitto.csv"
            headers = {"Authorization": f"token {token}"}

            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            content_b64 = base64.b64encode(csv_buffer.getvalue().encode("utf-8")).decode("utf-8")

            payload = {
                "message": f"Aggiornamento catalogo {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "content": content_b64,
            }
            if "sha" in st.session_state and st.session_state["sha"]:
                payload["sha"] = st.session_state["sha"]

            res = requests.put(url, headers=headers, json=payload)
            if res.status_code in [200, 201]:
                st.session_state["sha"] = res.json()["content"]["sha"]
                salvato = True
            else:
                st.error(f"Errore salvataggio GitHub: {res.status_code}")
        except Exception as e:
            st.error(f"Errore connessione GitHub: {e}")
    else:
        df.to_csv(FILE_CSV_LOCALE, index=False)
        salvato = True

    if salvato:
        st.cache_data.clear()
    return salvato


def estrai_dati(testo):
    testo_lower = testo.lower()

    prezzo_match = RE_PREZZO.search(testo_lower)
    prezzo = 0.0
    if prezzo_match:
        p_str = (prezzo_match.group(1) or prezzo_match.group(2)).replace(".", "")
        try:
            prezzo = float(p_str)
        except ValueError:
            prezzo = 0.0

    spese_match = RE_SPESE.search(testo_lower)
    spese = float(spese_match.group(1)) if spese_match else 0.0
    prezzo_totale = prezzo + spese

    mq_match = RE_MQ.search(testo_lower)
    mq = float(mq_match.group(1)) if mq_match else 0.0

    piano_match = RE_PIANO.search(testo_lower)
    piano = piano_match.group(0).capitalize() if piano_match else "N/D"

    ascensore = "N/D"
    if "ascensore" in testo_lower:
        ascensore = "No" if re.search(r"(senza|no|privo di)\s+ascensore", testo_lower) else "Sì"

    riscaldamento = "N/D"
    if "autonomo" in testo_lower:
        riscaldamento = "Autonomo"
    elif "centralizzato" in testo_lower:
        riscaldamento = "Centralizzato"

    condizionatore = "Sì" if any(k in testo_lower for k in ["aria condizionata", "climatizzat", "condizionator"]) else "No / Non specificato"

    vani_match = RE_VANI.search(testo_lower)
    vani = vani_match.group(0).capitalize() if vani_match else "N/D"

    classe_match = RE_CLASSE.search(testo_lower)
    classe_energetica = classe_match.group(1).upper() if classe_match else "N/D"

    has_metro = "Sì" if any(k in testo_lower for k in ["metro", "metropolitana"]) else "No / Non specificato"

    linea_metro = "N/D"
    if re.search(r"\b(linea\s*a|metro\s*a)\b", testo_lower): linea_metro = "Linea A"
    elif re.search(r"\b(linea\s*b1|metro\s*b1)\b", testo_lower): linea_metro = "Linea B1"
    elif re.search(r"\b(linea\s*b|metro\s*b)\b", testo_lower): linea_metro = "Linea B"
    elif re.search(r"\b(linea\s*c|metro\s*c)\b", testo_lower): linea_metro = "Linea C"

    fermata_match = RE_FERMATA.search(testo_lower)
    fermata_metro = fermata_match.group(1).strip().title() if fermata_match else "N/D"

    treno_match = RE_TRENO.search(testo_lower)
    if treno_match:
        stazione_treno = treno_
