import os
import re
import pandas as pd
import streamlit as st
from datetime import datetime

# Configurazione Pagina
st.set_page_config(page_title="Catalogo Case in Affitto", layout="wide")

DB_FILE = "case_in_affitto.csv"

# Inizializzazione Database CSV locale se non esiste
if not os.path.exists(DB_FILE):
    df_init = pd.DataFrame(
        columns=[
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
            "Link/Note",
        ]
    )
    df_init.to_csv(DB_FILE, index=False)


def estrai_dati(testo):
    """Funzione di analisi del testo per estrarre i parametri immobiliari."""
    testo_lower = testo.lower()

    # Prezzo
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

    # Spese condominiali
    spese_match = re.search(
        r"(?:spese|condominio|spese condominiali)\b[^\d]*(\d+)", testo_lower
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
    if piano_match:
        piano = piano_match.group(0).capitalize()
    else:
        piano = "N/D"

    # Ascensore
    if "ascensore" in testo_lower:
        ascensore = (
            "No"
            if re.search(
                r"(senza|no|privo di)\s+ascensore", testo_lower
            )
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

    # Condizionatore / Aria condizionata
    if any(
        k in testo_lower
        for k in ["aria condizionata", "climatizzat", "condizionator"]
    ):
        condizionatore = "Sì"
    else:
        condizionatore = "No / Non specificato"

    # Numero Vani
    vani_match = re.search(
        r"(\d+)\s*(?:locali|vani|camere)|monolocale|bilocale|trilocale|quadrilocale",
        testo_lower,
    )
    if vani_match:
        vani = vani_match.group(0).capitalize()
    else:
        vani = "N/D"

    # Classe Energetica
    classe_match = re.search(
        r"classe\s*energetica\s*:?\s*([a-g][1-3]?)", testo_lower
    )
    classe_energetica = (
        classe_match.group(1).upper() if classe_match else "N/D"
    )

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
    }


# Interfaccia Utente
st.title("🏠 Catalogo & Gestione Case in Affitto")
st.write(
    "Incolla il testo dell'annuncio e inserisci i dettagli della visita per salvandoli nel tuo archivio locale."
)

with st.sidebar:
    st.header("➕ Aggiungi Nuova Casa")
    link_nota = st.text_input("Link o Titolo Riferimento (opzionale)")
    visita_data = st.text_input(
        "Giorno e Ora Visita", placeholder="Es. Martedì 14/10 ore 18:00"
    )
    testo_annuncio = st.text_area(
        "Incolla qui tutto il testo dell'annuncio", height=250
    )

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

            # Carica CSV esistente e aggiungi nuova riga
            df = pd.read_csv(DB_FILE)
            df = pd.concat([pd.DataFrame([dati]), df], ignore_index=True)
            df.to_csv(DB_FILE, index=False)
            st.success("Immobile salvato con successo nel catalogo!")
            st.rerun()
        else:
            st.error("Inserisci il testo dell'annuncio prima di salvare.")

# Visualizzazione Tabelle e Catalogo
df_case = pd.read_csv(DB_FILE)

st.subheader(f"📋 Case in Catalogo ({len(df_case)})")

if not df_case.empty:
    st.dataframe(df_case, use_container_width=True)

    # Download backup CSV
    st.download_button(
        label="📥 Esporta Catalogo in Excel/CSV",
        data=df_case.to_csv(index=False).encode("utf-8"),
        file_name="catalogo_case_affitto.csv",
        mime="text/csv",
    )
else:
    st.info("Nessuna casa ancora salvata. Usa il menu a sinistra per aggiungere la prima!")
