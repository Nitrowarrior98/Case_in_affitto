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

# Elenco colonne strictly numeriche per evitare conflitti di tipo (str vs float)
COLONNE_NUMERICHE = [
    "Prezzo Immobile (€)",
    "Spese (€)",
    "Prezzo Totale (€)",
    "Metri Quadri (m²)",
    "Prezzo al m² (€/m²)",
    "Voto",
]


def calcola_prezzo_mq(df):
    """Calcola in modo vettoriale il prezzo al metro quadro per evitare problemi di tipo."""
    prezzo_tot = pd.to_numeric(df["Prezzo Totale (€)"], errors="coerce").fillna(0.0)
    mq = pd.to_numeric(df["Metri Quadri (m²)"], errors="coerce").fillna(0.0)

    # Evita divisioni per zero ed effettua il calcolo numerico pulito
    df["Prezzo al m² (€/m²)"] = (prezzo_tot / mq).where(mq > 0, 0.0).round(2)
    return df


def carica_dati():
    """Carica i dati e garantisce il tipo di dato corretto per ogni colonna."""
    df = None
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
                st.session_state["sha"] = content_json["sha"]
        except Exception:
            pass

    if df is None and os.path.exists(FILE_CSV_LOCALE):
        try:
            df = pd.read_csv(FILE_CSV_LOCALE)
        except Exception:
            pass

    if df is None:
        df = pd.DataFrame(columns=COLONNE)

    # Inizializzazione colonne mancanti con il giusto tipo
    for col in COLONNE:
        if col not in df.columns:
            if col == "Visita Effettuata":
                df[col] = False
            elif col in COLONNE_NUMERICHE:
                df[col] = 0.0
            elif col == "Note":
                df[col] = ""
            else:
                df[col] = "N/D"

    # Forzatura dei tipi numerici (converte eventuali 'N/D' presenti nei numeri in 0.0)
    for col in COLONNE_NUMERICHE:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Forzatura tipo booleano sicuro
    df["Visita Effettuata"] = df["Visita Effettuata"].apply(
        lambda x: True if str(x).lower() in ["true", "1", "sì", "si"] or x is True else False
    )

    # Pulisce le stringhe vuote o NaN
    df["Note"] = df["Note"].fillna("")

    # Ricalcola prezzo al metro quadro
    df = calcola_prezzo_mq(df)

    return df[COLONNE]


def salva_dati(df):
    """Salva il DataFrame garantendo la correttezza dei dati."""
    df = calcola_prezzo_mq(df)

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

    prezzo_match = re.search(r"(?:€|euro)\s*([\d\.]+)|([\d\.]+)\s*(?:€|euro)", testo_lower)
    prezzo = 0.0
    if prezzo_match:
        p_str = (prezzo_match.group(1) or prezzo_match.group(2)).replace(".", "")
        try:
            prezzo = float(p_str)
        except ValueError:
            prezzo = 0.0

    spese_match = re.search(r"(?:spese|condominio|spese condominiali|utenze)\b[^\d]*(\d+)", testo_lower)
    spese = float(spese_match.group(1)) if spese_match else 0.0
    prezzo_totale = prezzo + spese

    mq_match = re.search(r"(\d+)\s*(?:mq|m2|m²|metri quadri)", testo_lower)
    mq = float(mq_match.group(1)) if mq_match else 0.0

    piano_match = re.search(r"(\d+)°?\s*piano|piano\s*(\d+|terra|rialzato|attico)", testo_lower)
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

    vani_match = re.search(r"(\d+)\s*(?:locali|vani|camere)|monolocale|bilocale|trilocale|quadrilocale", testo_lower)
    vani = vani_match.group(0).capitalize() if vani_match else "N/D"

    classe_match = re.search(r"classe\s*energetica\s*:?\s*([a-g][1-3]?)", testo_lower)
    classe_energetica = classe_match.group(1).upper() if classe_match else "N/D"

    has_metro = "Sì" if any(k in testo_lower for k in ["metro", "metropolitana"]) else "No / Non specificato"

    linea_metro = "N/D"
    if re.search(r"\b(linea\s*a|metro\s*a)\b", testo_lower): linea_metro = "Linea A"
    elif re.search(r"\b(linea\s*b1|metro\s*b1)\b", testo_lower): linea_metro = "Linea B1"
    elif re.search(r"\b(linea\s*b|metro\s*b)\b", testo_lower): linea_metro = "Linea B"
    elif re.search(r"\b(linea\s*c|metro\s*c)\b", testo_lower): linea_metro = "Linea C"

    fermata_match = re.search(r"(?:metro|metropolitana)\s*(?:linea\s*[abc1]+)?\s*(?:fermata|stazione)?\s*([a-zàèéìòù\s'-]{3,20})", testo_lower)
    fermata_metro = fermata_match.group(1).strip().title() if fermata_match else "N/D"

    treno_match = re.search(r"(?:stazione|treno|fl\d|fm\d)\s*(?:di|fs)?\s*([a-zàèéìòù\s'-]{3,25})", testo_lower)
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
st.write("Incolla l'annuncio a sinistra o modifica direttamente le celle della tabella in basso.")

df_case = carica_dati()

# --- BARRA LATERALE (AGGIUNTA E FILTRI) ---
with st.sidebar:
    st.header("➕ Aggiungi Nuova Casa")
    titolo_casa = st.text_input("Titolo Casa", placeholder="Es. Trilocale Piazza Bologna")
    note_casa = st.text_area("Note / Impressioni", placeholder="Es. Molto luminosa, cucina piccola...")
    link = st.text_input("Link (opzionale)")
    visita_data = st.text_input("Giorno e Ora Visita", placeholder="Es. Martedì 14/10 ore 18:00")
    testo_annuncio = st.text_area("Incolla qui il testo dell'annuncio", height=180)

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

            df_nuovo = pd.concat([pd.DataFrame([dati]), df_case], ignore_index=True)[COLONNE]

            if salva_dati(df_nuovo):
                st.success("Immobile salvato nel catalogo condiviso!")
                st.rerun()
        else:
            st.error("Inserisci il testo prima di salvare.")

    st.divider()

    st.header("🔍 Filtri Rapidi")
    ricerca_testo = st.text_input("Cerca nel titolo o note", "")

    if not df_case.empty:
        max_p = df_case["Prezzo Totale (€)"].max()
        max_prezzo_possibile = int(max_p) + 500 if pd.notna(max_p) and max_p > 0 else 2500
    else:
        max_prezzo_possibile = 2500

    max_prezzo_possibile = max(max_prezzo_possibile, 1500)

    filtro_prezzo_max = st.slider("Prezzo Totale Max (€)", 500, max_prezzo_possibile, max_prezzo_possibile, step=50)
    filtro_solo_da_visitare = st.checkbox("Mostra solo case da visitare")
    filtro_voto_min = st.slider("Voto Minimo", 0.0, 10.0, 0.0, step=0.5)


# --- DASHBOARD KPI ---
if not df_case.empty:
    st.markdown("### 📊 Panoramica Rapida")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    totale_case = len(df_case)
    prezzi_validi = df_case[df_case["Prezzo Totale (€)"] > 0]["Prezzo Totale (€)"]
    prezzo_medio = prezzi_validi.mean() if not prezzi_validi.empty else 0.0

    visite_fatte = int(df_case["Visita Effettuata"].sum())

    voti_validi = df_case[df_case["Voto"] > 0]["Voto"]
    voto_medio = voti_validi.mean() if not voti_validi.empty else 0.0

    kpi1.metric("Case in Catalogo", f"{totale_case}")
    kpi2.metric("Prezzo Totale Medio", f"€ {prezzo_medio:.0f}" if prezzo_medio > 0 else "N/D")
    kpi3.metric("Visite Effettuate", f"{visite_fatte} / {totale_case}")
    kpi4.metric("Voto Medio", f"{voto_medio:.1f} ⭐" if voto_medio > 0 else "N/D")

    st.divider()


# --- FILTRAGGIO E TABELLA ---
df_filtrato = df_case.copy()

if ricerca_testo:
    df_filtrato = df_filtrato[
        df_filtrato["Titolo Casa"].str.contains(ricerca_testo, case=False, na=False)
        | df_filtrato["Note"].str.contains(ricerca_testo, case=False, na=False)
    ]

df_filtrato = df_filtrato[df_filtrato["Prezzo Totale (€)"] <= filtro_prezzo_max]

if filtro_solo_da_visitare:
    df_filtrato = df_filtrato[df_filtrato["Visita Effettuata"] == False]

if filtro_voto_min > 0:
    df_filtrato = df_filtrato[df_filtrato["Voto"] >= filtro_voto_min]


st.subheader(f"📋 Case in Catalogo ({len(df_filtrato)} filtrate su {len(df_case)} totali)")

if not df_case.empty:
    edited_df = st.data_editor(
        df_filtrato,
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
            "Prezzo al m² (€/m²)": st.column_config.NumberColumn(
                "Prezzo al m² (€/m²)",
                help="Calcolato automaticamente",
                format="€ %.2f",
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
        },
    )

    if st.button("💾 Salva Modifiche Tabella", type="primary"):
        df_completo = df_case.copy()
        for idx, row in edited_df.iterrows():
            if idx in df_completo.index:
                df_completo.loc[idx] = row

        if salva_dati(df_completo):
            st.success("Sincronizzato con il database!")
            st.rerun()
else:
    st.info("Nessuna casa ancora salvata. Incolla il primo annuncio dalla barra laterale!")
