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

# Aggiunta la colonna "Note" prima di "Link"
COLONNE = [
    "Titolo Casa",
    "Data Inserimento",
    "Giorno/Ora Visita",
    "Visita Effettuata",
    "Voto",
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
    "Note",
    "Link",
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
                
                # Gestione nuove colonne per le case vecchie
                for col in COLONNE:
                    if col not in df.columns:
                        if col == "Visita Effettuata": df[col] = False
                        elif col == "Voto": df[col] = 0.0
                        elif col == "Note": df[col] = ""
                        else: df[col] = "N/D"
                # Forza i tipi corretti per la tabella
                df["Visita Effettuata"] = df["Visita Effettuata"].astype(bool)
                df["Voto"] = pd.to_numeric(df["Voto"], errors='coerce').fillna(0.0)
                df["Note"] = df["Note"].fillna("")
                
                return df[COLONNE]
        except Exception:
            pass

    # Fallback su file CSV locale
    if os.path.exists(FILE_CSV_LOCALE):
        df = pd.read_csv(FILE_CSV_LOCALE)
        
        # Gestione nuove colonne per le case vecchie
        for col in COLONNE:
            if col not in df.columns:
                if col == "Visita Effettuata": df[col] = False
                elif col == "Voto": df[col] = 0.0
                elif col == "Note": df[col] = ""
                else: df[col] = "N/D"
        # Forza i tipi corretti per la tabella
        df["Visita Effettuata"] = df["Visita Effettuata"].astype(bool)
        df["Voto"] = pd.to_numeric(df["Voto"], errors='coerce').fillna(0.0)
        df["Note"] = df["Note"].fillna("")
        
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
    testo_lower = testo.lower()

    # Prezzo Immobile
    prezzo_match = re.search(
        r"(?:€|euro)\s*([\d\.]+)|([\d\.]+)\s*(?:€|euro)", testo_lower
    )
    prezzo = 0.0
    if prezzo_match:
        p_str = (prezzo_match.group(1) or prezzo_match.group(2)).replace(".", "")
        try:
            prezzo = float(p_str)
        except ValueError:
            prezzo = 0.0

    # Spese condominiali / Utenze
    spese_match = re.search(
        r"(?:spese|condominio|spese condominiali|utenze)\b[^\d]*(\d+)", testo_lower
    )
    spese = float(spese_match.group(1)) if spese_match else 0.0

    # Prezzo Totale
    prezzo_totale = prezzo + spese

    # Metri Quadri
    mq_match = re.search(r"(\d+)\s*(?:mq|m2|m²|metri quadri)", testo_lower)
    mq = int(mq_match.group(1)) if mq_match else "N/D"

    # Piano
    piano_match = re.search(
        r"(\d+)°?\s*piano|piano\s*(\d+|terra|rialzato|attico)", testo_lower
    )
    piano = piano_match.group(0).capitalize() if piano_match else "N/D"

    # Ascensore
    if "ascensore" in testo_lower:
        ascensore = (
            "No"
            if re.search(r"(senza|no|privo di)\s+ascensore", testo_lower)
            else "Sì"
        )
    else:
        ascensore = "N/D"

    # Riscaldamento
    if "autonomo" in testo_lower:
        riscaldamento = "Autonomo"
    elif "centralizzato" in testo_lower:
        riscaldamento = "Centralizzato"
    else:
        riscaldamento = "N/D"

    # Condizionatore
    condizionatore = (
        "Sì"
        if any(
            k in testo_lower
            for k in ["aria condizionata", "climatizzat", "condizionator"]
        )
        else "No / Non specificato"
    )

    # Numero Vani
    vani_match = re.search(
        r"(\d+)\s*(?:locali|vani|camere)|monolocale|bilocale|trilocale|quadrilocale",
        testo_lower,
    )
    vani = vani_match.group(0).capitalize() if vani_match else "N/D"

    # Classe Energetica
    classe_match = re.search(
        r"classe\s*energetica\s*:?\s*([a-g][1-3]?)", testo_lower
    )
    classe_energetica = (
        classe_match.group(1).upper() if classe_match else "N/D"
    )

    # Metro Vicina
    has_metro = (
        "Sì"
        if any(k in testo_lower for k in ["metro", "metropolitana"])
        else "No / Non specificato"
    )

    # Linea Metro
    linea_metro = "N/D"
    if re.search(r"\b(linea\s*a|metro\s*a)\b", testo_lower):
        linea_metro = "Linea A"
    elif re.search(r"\b(linea\s*b1|metro\s*b1)\b", testo_lower):
        linea_metro = "Linea B1"
    elif re.search(r"\b(linea\s*b|metro\s*b)\b", testo_lower):
        linea_metro = "Linea B"
    elif re.search(r"\b(linea\s*c|metro\s*c)\b", testo_lower):
        linea_metro = "Linea C"

    # Fermata Metro
    fermata_match = re.search(
        r"(?:metro|metropolitana)\s*(?:linea\s*[abc1]+)?\s*(?:fermata|stazione)?\s*([a-zàèéìòù\s'-]{3,20})",
        testo_lower,
    )
    fermata_metro = (
        fermata_match.group(1).strip().title() if fermata_match else "N/D"
    )

    # Stazione Treno
    treno_match = re.search(
        r"(?:stazione|treno|fl\d|fm\d)\s*(?:di|fs)?\s*([a-zàèéìòù\s'-]{3,25})",
        testo_lower,
    )
    if treno_match:
        stazione_treno = treno_match.group(0).strip().title()
    elif any(k in testo_lower for k in ["stazione", "treno", "ferrovia", "fs"]):
        stazione_treno = "Sì (Vicina)"
    else:
        stazione_treno = "N/D"

    return {
        "Prezzo Immobile (€)": prezzo,
        "Spese (€)": spese,
        "Prezzo Totale (€)": prezzo_totale,
        "Metri Quadri (m²)": mq,
        "Piano": piano,
        "Ascensore": ascensore,
        "Riscaldamento": riscaldamento,
        "Condizionatore": condizionatore,
        "Numero Vani": vani,
        "Classe Energetica": classe_energetica,
        "Stazione Treno": stazione_treno,
        "Metro Vicina": has_metro,
        "Linea Metro": linea_metro,
        "Fermata Metro": fermata_metro,
    }


# Interfaccia Streamlit
st.title("🏠 Catalogo & Gestione Case in Affitto")
st.write(
    "Incolla l'annuncio a sinistra o modifica direttamente le celle della tabella in basso."
)

with st.sidebar:
    st.header("➕ Aggiungi Nuova Casa")
    
    titolo_casa = st.text_input("Titolo Casa", placeholder="Es. Trilocale Piazza Bologna")
    note_casa = st.text_area("Note / Impressioni", placeholder="Es. Molto luminosa, cucina piccola...")
    link = st.text_input("Link (opzionale)")
    visita_data = st.text_input(
        "Giorno e Ora Visita", placeholder="Es. Martedì 14/10 ore 18:00"
    )
    testo_annuncio = st.text_area("Incolla qui il testo dell'annuncio", height=220)

    if st.button("Analizza e Salva", type="primary"):
        if testo_annuncio.strip():
            dati = estrai_dati(testo_annuncio)
            
            dati["Titolo Casa"] = titolo_casa if titolo_casa else "Nuova Casa"
            dati["Data Inserimento"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            dati["Giorno/Ora Visita"] = visita_data if visita_data else "Da programmare"
            dati["Visita Effettuata"] = False
            dati["Voto"] = 0.0
            dati["Note"] = note_casa if note_casa else ""
            dati["Link"] = link if link else "-"

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
        column_config={
            "Visita Effettuata": st.column_config.CheckboxColumn(
                "Visita Effettuata",
                help="Spunta questa casella se hai già visto la casa",
                default=False,
            ),
            "Voto": st.column_config.NumberColumn(
                "Voto",
                help="Dai un voto da 0 a 10 (con scatti di 0.5)",
                min_value=0.0,
                max_value=10.0,
                step=0.5,
                format="%.1f",
            ),
            "Note": st.column_config.TextColumn(
                "Note",
                help="Note e impressioni personali",
                width="large",
            ),
            "Link": st.column_config.LinkColumn(
                "Link",
                help="Clicca per aprire l'annuncio",
            ),
        }
    )

    if st.button("💾 Salva Modifiche Tabella", type="primary"):
        if salva_dati(edited_df):
            st.success("Sincronizzato con il database!")
            st.rerun()
else:
    st.info("Nessuna casa ancora salvata.")
