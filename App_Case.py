import base64
import io
import json
import os
import re
from datetime import datetime
import google.generativeai as genai
import pandas as pd
import requests
import streamlit as st
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

# Configurazione Pagina
st.set_page_config(page_title="Catalogo Case in Affitto", layout="wide")

FILE_CSV_LOCALE = "case_in_affitto.csv"

COLONNE = [
    "Titolo Casa",
    "Data Inserimento",
    "Giorno/Ora Visita",
    "Visita Effettuata",
    "Contatto Telefonico",
    "Indirizzo",
    "Latitudine",
    "Longitudine",
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
    "Latitudine",
    "Longitudine",
]


def get_github_credentials():
    """Recupera le credenziali in modo sicuro senza far crashare l'app."""
    try:
        if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
            return st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"]
    except Exception:
        pass
    return None, None


def calcola_prezzo_mq(df):
    if df.empty:
        return df
    prezzo_tot = pd.to_numeric(df["Prezzo Totale (€)"], errors="coerce").fillna(0.0)
    mq = pd.to_numeric(df["Metri Quadri (m²)"], errors="coerce").fillna(0.0)
    df["Prezzo al m² (€/m²)"] = (prezzo_tot / mq).where(mq > 0, 0.0).round(2)
    return df


def ottieni_coordinate(testo_posizione):
    """Converte un indirizzo, una fermata metro o una stazione in latitudine e longitudine."""
    if not testo_posizione or str(testo_posizione).strip().upper() in ["N/D", "", "NONE", "NAN"]:
        return 0.0, 0.0
    try:
        geolocator = Nominatim(user_agent="app_case_affitto_roma_v3")
        query = str(testo_posizione).strip()
        if "roma" not in query.lower():
            query += ", Roma, Italia"
        location = geolocator.geocode(query, timeout=5)
        if location:
            return float(location.latitude), float(location.longitude)
    except (GeocoderTimedOut, Exception):
        pass
    return 0.0, 0.0


@st.cache_data(ttl=300, show_spinner=False)
def _scarica_dati_raw():
    df = None
    sha = None
    token, repo = get_github_credentials()

    if token and repo:
        try:
            url = f"https://api.github.com/repos/{repo}/contents/case_in_affitto.csv"
            headers = {"Authorization": f"token {token}"}
            res = requests.get(url, headers=headers, timeout=5)
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

    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(columns=COLONNE)

    for col in COLONNE:
        if col not in df.columns:
            if col == "Visita Effettuata":
                df[col] = False
            elif col in COLONNE_NUMERICHE:
                df[col] = 0.0
            elif col in ["Note", "Contatto Telefonico", "Indirizzo"]:
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
    df["Indirizzo"] = df["Indirizzo"].astype(str).fillna("N/D")

    # Tenta il recupero coordinate per righe vecchie senza coordinate
    for idx, row in df.iterrows():
        if float(row.get("Latitudine", 0.0)) == 0.0 or float(row.get("Longitudine", 0.0)) == 0.0:
            target = row.get("Indirizzo")
            if not target or str(target).strip().upper() in ["N/D", ""]:
                target = row.get("Fermata Metro")
            if not target or str(target).strip().upper() in ["N/D", ""]:
                target = row.get("Stazione Treno")

            if target and str(target).strip().upper() not in ["N/D", ""]:
                lat, lon = ottieni_coordinate(target)
                df.at[idx, "Latitudine"] = lat
                df.at[idx, "Longitudine"] = lon

    df = calcola_prezzo_mq(df)
    return df[COLONNE], sha


def carica_dati():
    df, sha = _scarica_dati_raw()
    if sha:
        st.session_state["sha"] = sha
    return df.copy()


def salva_dati(df):
    df = calcola_prezzo_mq(df)
    token, repo = get_github_credentials()

    salvato = False
    if token and repo:
        try:
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

            res = requests.put(url, headers=headers, json=payload, timeout=10)
            if res.status_code in [200, 201]:
                st.session_state["sha"] = res.json()["content"]["sha"]
                salvato = True
            else:
                st.error(f"Errore salvataggio GitHub (Codice {res.status_code})")
        except Exception as e:
            st.error(f"Errore connessione GitHub: {e}")
    else:
        try:
            df.to_csv(FILE_CSV_LOCALE, index=False)
            salvato = True
        except Exception as e:
            st.error(f"Errore salvataggio locale: {e}")

    if salvato:
        st.cache_data.clear()
    return salvato


def estrai_dati(testo):
    """Analizza l'annuncio usando Gemini API ed estrae un dizionario pulito."""
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        st.error("⚠️ GEMINI_API_KEY non trovata nei Secrets di Streamlit.")
        return None

    try:
        genai.configure(api_key=api_key)

        model = genai.GenerativeModel("gemini-3.5-flash-lite")

        prompt = f"""
        Sei un assistente immobiliare esperto. Analizza il seguente annuncio di affitto ed estrai le informazioni.
        Rispondi SOLO ed ESCLUSIVAMENTE con un oggetto JSON valido, usando esattamente le seguenti chiavi:
        - "Prezzo": numero (solo il costo dell'affitto, usa 0.0 se non trovato)
        - "Spese": numero (spese condominiali/utenze se esplicitate, usa 0.0 se non trovato)
        - "MQ": numero (metri quadri, usa 0.0 se non trovato)
        - "Indirizzo": stringa (la via, piazza o quartiere esatto se presente, es. "Via Lorenzo il Magnifico". Usa "N/D" se non trovato)
        - "Piano": stringa (es. "Terra", "1°", "Attico". Usa "N/D" se non trovato)
        - "Ascensore": stringa ("Sì", "No", o "N/D")
        - "Riscaldamento": stringa ("Autonomo", "Centralizzato", o "N/D")
        - "Condizionatore": stringa ("Sì", "No", o "N/D")
        - "Vani": stringa (es. "Monolocale", "Bilocale", "3". Usa "N/D" se non trovato)
        - "Classe": stringa (es. "A", "G". Usa "N/D" se non trovata)
        - "Treno": stringa (nome della stazione vicina o "Sì", altrimenti "N/D")
        - "MetroVicina": stringa ("Sì", "No / Non specificato")
        - "LineaMetro": stringa (es. "Linea A", "Linea B". Usa "N/D" se non trovata)
        - "FermataMetro": stringa (nome della fermata. Usa "N/D" se non trovata)
        - "Telefono": stringa (numero di contatto. Usa "N/D" se non trovato)

        Testo dell'annuncio:
        '''
        {testo}
        '''
        """

        with st.spinner("Intelligenza Artificiale in azione..."):
            response = model.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                },
            )

            res_text = response.text.strip()
            if res_text.startswith("```"):
                res_text = re.sub(r"^```(?:json)?\n?", "", res_text)
                res_text = re.sub(r"\n?```$", "", res_text)

            dati = json.loads(res_text)

            prezzo = float(dati.get("Prezzo", 0.0))
            spese = float(dati.get("Spese", 0.0))
            indirizzo_estratto = str(dati.get("Indirizzo", "N/D"))
            fermata_metro = str(dati.get("FermataMetro", "N/D"))
            stazione_treno = str(dati.get("Treno", "N/D"))

            # Strategia a cascata per trovare le coordinate
            lat, lon = ottieni_coordinate(indirizzo_estratto)
            if lat == 0.0 and lon == 0.0:
                lat, lon = ottieni_coordinate(fermata_metro)
            if lat == 0.0 and lon == 0.0:
                lat, lon = ottieni_coordinate(stazione_treno)

            return {
                "Prezzo Immobile (€)": prezzo,
                "Spese (€)": spese,
                "Prezzo Totale (€)": prezzo + spese,
                "Metri Quadri (m²)": float(dati.get("MQ", 0.0)),
                "Indirizzo": indirizzo_estratto,
                "Latitudine": lat,
                "Longitudine": lon,
                "Piano": str(dati.get("Piano", "N/D")).capitalize(),
                "Ascensore": str(dati.get("Ascensore", "N/D")),
                "Riscaldamento": str(dati.get("Riscaldamento", "N/D")),
                "Condizionatore": str(dati.get("Condizionatore", "N/D")),
                "Numero Vani": str(dati.get("Vani", "N/D")).capitalize(),
                "Classe Energetica": str(dati.get("Classe", "N/D")).upper(),
                "Stazione Treno": str(dati.get("Treno", "N/D")).title(),
                "Metro Vicina": str(dati.get("MetroVicina", "N/D")),
                "Linea Metro": str(dati.get("LineaMetro", "N/D")),
                "Fermata Metro": str(dati.get("FermataMetro", "N/D")).title(),
                "Contatto Telefonico": str(dati.get("Telefono", "N/D")),
            }

    except Exception as e:
        st.error(f"❌ Errore durante l'estrazione con Gemini: {e}")
        return None


# --- INTERFACCIA STREAMLIT ---
st.title("🏠 Catalogo & Gestione Case in Affitto")
st.write("Incolla l'annuncio a sinistra o modifica direttamente le celle della tabella in basso.")

df_case = carica_dati()

# --- BARRA LATERALE ---
with st.sidebar:
    st.header("➕ Aggiungi Nuova Casa")
    titolo_casa = st.text_input("Titolo Casa", placeholder="Es. Trilocale Piazza Bologna")
    testo_annuncio = st.text_area("Incolla qui il testo dell'annuncio", height=180)
    contatto_tel = st.text_input("Contatto Telefonico", placeholder="Es. 333 1234567 (opzionale)")
    note_casa = st.text_area("Note / Impressioni", placeholder="Es. Molto luminosa, cucina piccola...")
    link = st.text_input("Link (opzionale)")
    visita_data = st.text_input("Giorno e Ora Visita", placeholder="Es. Martedì 14/10 ore 18:00")

    if st.button("Analizza e Salva", type="primary"):
        if testo_annuncio.strip():
            dati = estrai_dati(testo_annuncio)

            if dati is not None:
                dati["Titolo Casa"] = titolo_casa if titolo_casa else "Nuova Casa"
                if contatto_tel.strip():
                    dati["Contatto Telefonico"] = contatto_tel.strip()

                dati["Data Inserimento"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                dati["Giorno/Ora Visita"] = visita_data if visita_data else "Da programmare"
                dati["Visita Effettuata"] = False
                dati["Voto"] = 0.0
                dati["Note"] = note_casa if note_casa else ""
                dati["Link"] = link if link else "-"

                df_nuovo = pd.concat([pd.DataFrame([dati]), df_case], ignore_index=True)[COLONNE]

                if salva_dati(df_nuovo):
                    st.success("Immobile salvato nel catalogo!")
                    st.rerun()
        else:
            st.error("Inserisci il testo prima di salvare.")

    st.divider()

    st.header("🔍 Filtri Rapidi")
    ricerca_testo = st.text_input("Cerca nel titolo, note o telefono", "")

    max_p = df_case["Prezzo Totale (€)"].max() if not df_case.empty else 2500
    max_prezzo_possibile = int(max_p) + 500 if pd.notna(max_p) and max_p > 0 else 2500
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


# --- FILTRAGGIO ---
df_filtrato = df_case.copy()

if ricerca_testo and not df_filtrato.empty:
    df_filtrato = df_filtrato[
        df_filtrato["Titolo Casa"].str.contains(ricerca_testo, case=False, na=False)
        | df_filtrato["Note"].str.contains(ricerca_testo, case=False, na=False)
        | df_filtrato["Contatto Telefonico"].str.contains(ricerca_testo, case=False, na=False)
        | df_filtrato["Indirizzo"].str.contains(ricerca_testo, case=False, na=False)
    ]

if not df_filtrato.empty:
    df_filtrato = df_filtrato[df_filtrato["Prezzo Totale (€)"] <= filtro_prezzo_max]

if filtro_solo_da_visitare and not df_filtrato.empty:
    df_filtrato = df_filtrato[df_filtrato["Visita Effettuata"] == False]

if filtro_voto_min > 0 and not df_filtrato.empty:
    df_filtrato = df_filtrato[df_filtrato["Voto"] >= filtro_voto_min]


# --- SEZIONE MAPPA ---
st.subheader("🗺️ Mappa Immobili")
if not df_filtrato.empty:
    df_mappa = df_filtrato[(df_filtrato["Latitudine"] != 0.0) & (df_filtrato["Longitudine"] != 0.0)]
    if not df_mappa.empty:
        st.map(df_mappa, latitude="Latitudine", longitude="Longitudine", use_container_width=True)
    else:
        st.info("ℹ️ Nessuna coordinata geografica valida trovata per le case attualmente filtrate.")
else:
    st.info("ℹ️ Nessun immobile salvato o filtrato.")
st.divider()


# --- TABELLA DATI ---
st.subheader(f"📋 Case in Catalogo ({len(df_filtrato)} filtrate su {len(df_case)} totali)")

if not df_case.empty:
    edited_df = st.data_editor(
        df_filtrato,
        num_rows="dynamic",
        use_container_width=True,
        key="data_editor",
        column_config={
            "Latitudine": None,  # Nascoste per non ingombrare la vista
            "Longitudine": None,
            "Visita Effettuata": st.column_config.CheckboxColumn(
                "Visita Effettuata",
                help="Spunta questa casella se hai già visto la casa",
                default=False,
            ),
            "Contatto Telefonico": st.column_config.TextColumn(
                "Contatto Telefonico",
                help="Numero di telefono del proprietario o agenzia",
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
        indici_eliminati = df_filtrato.index.difference(edited_df.index)
        df_completo = df_case.drop(index=indici_eliminati)

        for idx, row in edited_df.iterrows():
            df_completo.loc[idx] = row

        if salva_dati(df_completo):
            st.success("Sincronizzato con il database!")
            st.rerun()
else:
    st.info("Nessuna casa ancora salvata. Incolla il primo annuncio dalla barra laterale!")
