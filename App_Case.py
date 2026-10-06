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
    "Data Inserimento",
    "Giorno/Ora Visita",
    "Prezzo Immobile (€)",
    "Spese (€)",
    "Prezzo Totale (€)",
    "Metri Quadri (m²)",
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
    "Link/Note",
]


def carica_dati():
    """Carica i dati dal repository GitHub se disponibili i Secrets, altrimenti dal file locale."""
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            token = st.secrets["GITHUB_TOKEN"]
            repo = st.secrets["GITHUB_REPO"]
            url = f"https://api.github.com/repos/{repo}/contents/case_in_affitto.csv"
            headers = {"Authorization": f"token {token}"}
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                content_json = res.json()
                csv_text = base64.b64decode(content_json["content"]).decode(
                    "utf-8"
                )
                df = pd.read_csv(io.StringIO(csv_text))
                st.session_state["sha"] = content_json["sha"]
                for col in COLONNE:
                    if col not in df.columns:
                        df[col] = "N/D"
                return df[COLONNE]
        except Exception:
            pass

    # Fallback su file CSV locale
    if os.path.exists(FILE_CSV_LOCALE):
        df = pd.read_csv(FILE_CSV_LOCALE)
        for col in COLONNE:
            if col not in df.columns:
                df[col] = "N/D"
        return df[COLONNE]

    return pd.DataFrame(columns=COLONNE)


def salva_dati(df):
    """Salva i dati su GitHub se configurato, altrimenti sul file CSV locale."""
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            token = st.secrets["GITHUB_TOKEN"]
            repo = st.secrets["GITHUB_REPO"]
            url = f"https://api.github.com/repos/{repo}/contents/case_in_affitto.csv"
            headers = {"Authorization": f"token {token}"}

            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            content_b64 = base64.b64encode(
                csv_buffer.getvalue().encode("utf-8")
            ).decode("utf-8")

            payload = {
                "message": f"Aggiornamento catalogo {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "content": content_b64,
            }
            if "sha" in st.session_state and st.session_state["sha"]:
                payload["sha"] = st.session_state["sha"]

            res = requests.put(url, headers=headers, json=payload)
            if res.status_code in [200, 201]:
                st.session_state["sha"] = res.json()["content"]["sha"]
                return True
            else:
                st.error(f"Errore salvataggio GitHub: {res.status_code}")
                return False
        except Exception as e:
            st.error(f"Errore connessione GitHub: {e}")
            return False
    else:
        df.to_csv(FILE_CSV_LOCALE, index=False)
        return True


def estrai_dati(testo):
    """Estrae le informazioni dall'annuncio usando l'API di Gemini."""
    raw_key = st.secrets.get("GEMINI_API_KEY", "")

    # Pulisce la chiave da eventuali virgolette o spazi accidentali
    api_key = str(raw_key).strip().strip("'").strip('"')

    if not api_key:
        st.error("Chiave API di Gemini mancante o non valida nei Secrets!")
        return {}

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    prompt = f"""
    Sei un assistente esperto in immobili a Roma. Analizza il seguente annuncio di affitto ed estrai le informazioni.
    Rispondi TASSATIVAMENTE ed ESCLUSIVAMENTE con un oggetto JSON valido (senza blocchi markdown ```json).

    Formato JSON richiesto:
    {{
      "Prezzo Immobile (€)": float (solo numero dell'affitto base, es: 850.0),
      "Spese (€)": float (spese condominiali/utenze se menzionate, altrimenti 0.0),
      "Metri Quadri (m²)": int o stringa ("N/D" se assente),
      "Piano": stringa (es: "3° piano", "Piano terra", "Attico", o "N/D"),
      "Ascensore": stringa ("Sì", "No", o "N/D"),
      "Riscaldamento": stringa ("Autonomo", "Centralizzato", o "N/D"),
      "Condizionatore": stringa ("Sì", "No", o "N/D"),
      "Numero Vani": stringa (es: "Bilocale", "3 locali", "N/D"),
      "Classe Energetica": stringa (es: "A1", "G", "N/D"),
      "Stazione Treno": stringa (es: "Stazione Tiburtina", "Sì", "N/D"),
      "Metro Vicina": stringa ("Sì", "No", o "N/D"),
      "Linea Metro": stringa ("Linea A", "Linea B", "Linea B1", "Linea C", o "N/D"),
      "Fermata Metro": stringa (nome della fermata più vicina trovata o dedotta, es: "Bologna", "N/D")
    }}

    Regole:
    - Tollerare errori di battitura (es. "spesy condominialz", "ascnsore").
    - Se l'annuncio cita luoghi noti o piazze vicine (es. "vicino Piazza Bologna"), deduci la metro/fermata corretta se evidente.

    Testo annuncio:
    \"\"\"{testo}\"\"\"
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        response = requests.post(
            url, headers=headers, json=payload, timeout=15
        )

        if response.status_code != 200:
            st.error(
                f"Errore API Gemini ({response.status_code}): {response.text}"
            )
            return {}

        data = response.json()
        testo_risposta = data["candidates"][0]["content"]["parts"][0][
            "text"
        ].strip()

        # Rimuove eventuali marcatori ```json ... ```
        if testo_risposta.startswith("```"):
            testo_risposta = (
                testo_risposta.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            )

        dati_estratti = json.loads(testo_risposta)

        # Calcolo prezzo totale
        prezzo = float(dati_estratti.get("Prezzo Immobile (€)", 0.0))
        spese = float(dati_estratti.get("Spese (€)", 0.0))
        dati_estratti["Prezzo Totale (€)"] = prezzo + spese

        return dati_estratti

    except Exception as e:
        st.error(f"Errore durante l'estrazione con LLM: {e}")
        return {}


# Interfaccia Streamlit
st.title("🏠 Catalogo & Gestione Case in Affitto")
st.write(
    "Incolla l'annuncio a sinistra o modifica direttamente le celle della tabella in basso."
)

with st.sidebar:
    st.header("➕ Aggiungi Nuova Casa")
    link_nota = st.text_input("Link o Titolo Riferimento (opzionale)")
    visita_data = st.text_input(
        "Giorno e Ora Visita", placeholder="Es. Martedì 14/10 ore 18:00"
    )
    testo_annuncio = st.text_area("Incolla qui il testo dell'annuncio", height=220)

    if st.button("Analizza e Salva", type="primary"):
        if testo_annuncio.strip():
            dati = estrai_dati(testo_annuncio)
            dati["Data Inserimento"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
            dati["Giorno/Ora Visita"] = (
                visita_data if visita_data else "Da programmare"
            )
            dati["Link/Note"] = link_nota if link_nota else "-"

            df_attuale = carica_dati()
            df_nuovo = pd.concat(
                [pd.DataFrame([dati]), df_attuale], ignore_index=True
            )[COLONNE]
            if salva_dati(df_nuovo):
                st.success("Immobile salvato nel catalogo condiviso!")
                st.rerun()
        else:
            st.error("Inserisci il testo prima di salvare.")

df_case = carica_dati()
st.subheader(f"📋 Case in Catalogo ({len(df_case)})")

if not df_case.empty:
    edited_df = st.data_editor(
        df_case,
        num_rows="dynamic",
        use_container_width=True,
        key="data_editor",
    )

    if st.button("💾 Salva Modifiche Tabella", type="primary"):
        if salva_dati(edited_df):
            st.success("Sincronizzato con il database!")
            st.rerun()
else:
    st.info("Nessuna casa ancora salvata.")
