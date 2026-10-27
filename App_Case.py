import base64
import io
import json
import math
import os
import re
import time
import zlib
from datetime import datetime

import google.generativeai as genai
import pandas as pd
import requests
import streamlit as st
from geopy.geocoders import Nominatim
from geopy.point import Point

# Configurazione Pagina
st.set_page_config(page_title="Catalogo Case in Affitto", layout="wide")

FILE_CSV_LOCALE = "case_in_affitto.csv"
MODELLO_GEMINI_DEFAULT = "gemini-3.5-flash-lite"

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

COLONNE_TESTO = [c for c in COLONNE if c not in COLONNE_NUMERICHE and c != "Visita Effettuata"]
COLONNE_SI_NO = ["Ascensore", "Condizionatore", "Metro Vicina"]
DEFAULT_TESTO = {"Titolo Casa": "Nuova Casa", "Note": "", "Link": "-"}

# Aree di ricerca per Nominatim: (lat, lon) dei due angoli opposti.
# 1) area urbana (circa dentro il GRA)  2) intero comune di Roma
AREE_RICERCA = {
    "urbano": (Point(42.00, 12.33), Point(41.78, 12.63)),
    "comune": (Point(42.05, 12.22), Point(41.65, 12.86)),
}

_geolocator = Nominatim(user_agent="app_case_affitto_roma_v5")


# ---------------------------------------------------------------------------
# UTILITÀ
# ---------------------------------------------------------------------------
def get_secret(nome):
    """Legge un secret senza far crashare l'app se manca il file secrets."""
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass
    return None


def get_github_credentials():
    """Recupera le credenziali in modo sicuro senza far crashare l'app."""
    token = get_secret("GITHUB_TOKEN")
    repo = get_secret("GITHUB_REPO")
    if token and repo:
        return token, repo
    return None, None


def _e_vuoto(x):
    if x is None:
        return True
    try:
        return bool(pd.isna(x))
    except (TypeError, ValueError):
        return False


def _a_float(x, default=0.0):
    """Converte in float senza mai sollevare eccezioni."""
    if _e_vuoto(x):
        return default
    try:
        v = float(x)
    except (TypeError, ValueError):
        try:
            v = float(str(x).strip().replace(",", "."))
        except (TypeError, ValueError):
            return default
    return default if math.isnan(v) else v


def _a_bool(x):
    if isinstance(x, bool):
        return x
    if _e_vuoto(x):
        return False
    return str(x).strip().lower() in ["true", "1", "1.0", "sì", "si", "yes", "vero"]


def _pulisci_testo(x, col):
    """Uniforma i valori di testo: niente 'nan', 'N/d' -> 'N/D', 'Si'/'SI' -> 'Sì'."""
    default = DEFAULT_TESTO.get(col, "N/D")
    if _e_vuoto(x):
        return default
    s = str(x).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return default
    if s.upper() == "N/D":
        return "N/D"
    if col in COLONNE_SI_NO:
        if s.lower() in ("si", "sì"):
            return "Sì"
        if s.lower() == "no":
            return "No"
    return s


def _testo_utile(t):
    s = str(t).strip()
    return len(s) > 2 and s.upper() not in ["N/D", "SÌ", "SI", "NO", "NONE", "NAN"]


def calcola_prezzo_mq(df):
    """Ricalcola Prezzo Totale (= prezzo + spese) e Prezzo al m²."""
    if df.empty:
        return df
    prezzo = pd.to_numeric(df["Prezzo Immobile (€)"], errors="coerce").fillna(0.0)
    spese = pd.to_numeric(df["Spese (€)"], errors="coerce").fillna(0.0)
    tot_esistente = pd.to_numeric(df["Prezzo Totale (€)"], errors="coerce").fillna(0.0)
    calcolato = prezzo + spese
    # se prezzo e spese sono entrambi 0 si conserva il totale eventualmente inserito a mano
    df["Prezzo Totale (€)"] = calcolato.where(calcolato > 0, tot_esistente).round(2)

    mq = pd.to_numeric(df["Metri Quadri (m²)"], errors="coerce").fillna(0.0)
    df["Prezzo al m² (€/m²)"] = (df["Prezzo Totale (€)"] / mq).where(mq > 0, 0.0).round(2)
    return df


def normalizza_df(df):
    """Porta qualsiasi DataFrame allo schema standard (colonne, tipi, valori coerenti)."""
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(columns=COLONNE)
    df = df.copy().reset_index(drop=True)

    for col in COLONNE:
        if col not in df.columns:
            if col == "Visita Effettuata":
                df[col] = False
            elif col in COLONNE_NUMERICHE:
                df[col] = 0.0
            else:
                df[col] = None
    df = df[COLONNE].copy()

    for col in COLONNE_NUMERICHE:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)

    df["Visita Effettuata"] = df["Visita Effettuata"].apply(_a_bool).astype(bool)

    for col in COLONNE_TESTO:
        df[col] = df[col].apply(lambda x, c=col: _pulisci_testo(x, c)).astype(object)

    return calcola_prezzo_mq(df)


def calcola_distanza_haversine(lat1, lon1, lat2, lon2):
    """Calcola la distanza in metri e stima i minuti a piedi tra due coordinate."""
    if lat1 == 0.0 or lon1 == 0.0 or lat2 == 0.0 or lon2 == 0.0:
        return None
    R = 6371000  # Raggio della Terra in metri
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    metri = int(R * c)
    minuti_a_piedi = max(1, round(metri / 80))  # Media di ~80 m/minuto a piedi
    return metri, minuti_a_piedi


# ---------------------------------------------------------------------------
# GEOCODING
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=500)
def _geocodifica(query, area):
    """Una singola chiamata a Nominatim, limitata a un'area di Roma.

    Restituisce (lat, lon) oppure None se l'indirizzo non esiste.
    In caso di errore di rete/timeout SOLLEVA l'eccezione: così il fallimento
    non finisce nella cache e al prossimo tentativo si riprova davvero.
    """
    time.sleep(1.0)  # Nominatim chiede al massimo 1 richiesta al secondo
    location = _geolocator.geocode(query, timeout=5, viewbox=list(AREE_RICERCA[area]), bounded=True)
    if location:
        return float(location.latitude), float(location.longitude)
    return None


def ottieni_coordinate(testo_posizione):
    """Converte un indirizzo, una fermata metro o una stazione in (lat, lon), cercando solo a Roma."""
    if not testo_posizione or str(testo_posizione).strip().upper() in ["N/D", "", "NONE", "NAN"]:
        return 0.0, 0.0
    query = str(testo_posizione).strip()
    if "roma" not in query.lower():
        query += ", Roma, Italia"
    for area in ("urbano", "comune"):
        try:
            risultato = _geocodifica(query, area)
        except Exception:
            return 0.0, 0.0  # errore temporaneo (non cachato)
        if risultato:
            return risultato
    return 0.0, 0.0


def trova_coordinate(indirizzo, fermata="N/D", stazione="N/D", solo_indirizzo=False):
    """Cascata: indirizzo -> fermata metro -> stazione treno."""
    lat, lon = ottieni_coordinate(indirizzo)
    if solo_indirizzo:
        return lat, lon
    if lat == 0.0 and lon == 0.0 and _testo_utile(fermata):
        lat, lon = ottieni_coordinate(f"Stazione Metro {fermata}")
    if lat == 0.0 and lon == 0.0 and _testo_utile(stazione):
        lat, lon = ottieni_coordinate(stazione)
    return lat, lon


def completa_coordinate(df, forza=False):
    """Calcola le coordinate mancanti (o tutte, se forza=True). Restituisce (df, n_aggiornate)."""
    df = df.copy()
    aggiornate = 0
    for idx in df.index:
        lat = _a_float(df.at[idx, "Latitudine"])
        lon = _a_float(df.at[idx, "Longitudine"])
        presenti = lat != 0.0 and lon != 0.0
        if presenti and not forza:
            continue
        n_lat, n_lon = trova_coordinate(
            df.at[idx, "Indirizzo"],
            df.at[idx, "Fermata Metro"],
            df.at[idx, "Stazione Treno"],
            solo_indirizzo=presenti,  # se ho già un punto, lo sostituisco solo con uno trovato dall'indirizzo
        )
        if (n_lat != 0.0 and n_lon != 0.0) and (n_lat, n_lon) != (lat, lon):
            df.at[idx, "Latitudine"] = n_lat
            df.at[idx, "Longitudine"] = n_lon
            aggiornate += 1
    return df, aggiornate


# ---------------------------------------------------------------------------
# LETTURA / SCRITTURA DATI
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def _scarica_github(token, repo):
    """Scarica il CSV da GitHub. Solleva eccezione se GitHub non risponde (così non viene cachato)."""
    url = f"https://api.github.com/repos/{repo}/contents/case_in_affitto.csv"
    headers = {"Authorization": f"token {token}"}
    res = requests.get(url, headers=headers, timeout=8)
    if res.status_code == 200:
        content_json = res.json()
        csv_text = base64.b64decode(content_json["content"]).decode("utf-8")
        return csv_text, content_json["sha"]
    if res.status_code == 404:
        return None, None  # il file non esiste ancora: verrà creato al primo salvataggio
    raise RuntimeError(f"GitHub ha risposto con codice {res.status_code}")


def carica_dati():
    token, repo = get_github_credentials()
    df = None
    st.session_state["remoto_ko"] = False

    if token and repo:
        try:
            csv_text, sha = _scarica_github(token, repo)
            st.session_state["sha"] = sha
            if csv_text is not None:
                df = pd.read_csv(io.StringIO(csv_text), dtype=str)
        except Exception:
            st.session_state["remoto_ko"] = True

    if df is None and os.path.exists(FILE_CSV_LOCALE):
        try:
            df = pd.read_csv(FILE_CSV_LOCALE, dtype=str)
        except Exception:
            pass

    return normalizza_df(df)


def _put_github(url, headers, payload):
    res = requests.put(url, headers=headers, json=payload, timeout=15)
    if res.status_code in (409, 422):
        # sha non aggiornato: lo rileggo e riprovo una volta
        r2 = requests.get(url, headers=headers, timeout=10)
        if r2.status_code == 200:
            payload = dict(payload, sha=r2.json()["sha"])
            res = requests.put(url, headers=headers, json=payload, timeout=15)
    return res


def salva_dati(df):
    df = normalizza_df(df)
    token, repo = get_github_credentials()

    salvato = False
    if token and repo:
        if st.session_state.get("remoto_ko"):
            st.error(
                "GitHub non era raggiungibile quando ho caricato i dati: non salvo, "
                "per non sovrascrivere il catalogo online con dati vecchi. Ricarica la pagina e riprova."
            )
            return False
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
            if st.session_state.get("sha"):
                payload["sha"] = st.session_state["sha"]

            res = _put_github(url, headers, payload)
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
        # Svuoto solo la cache del CSV: quella delle coordinate resta (evita richieste inutili a Nominatim)
        _scarica_github.clear()
    return salvato


# ---------------------------------------------------------------------------
# ESTRAZIONE CON GEMINI
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=50)
def _chiama_gemini(testo):
    """Chiamata a Gemini. Solleva eccezione in caso di errore (così l'errore non viene cachato)."""
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY non trovata nei Secrets di Streamlit.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(get_secret("GEMINI_MODEL") or MODELLO_GEMINI_DEFAULT)

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
    if isinstance(dati, list) and dati:
        dati = dati[0]
    if not isinstance(dati, dict):
        raise ValueError("Risposta di Gemini non valida")
    return dati


def estrai_dati(testo):
    """Analizza l'annuncio usando Gemini API ed estrae un dizionario pulito."""
    if not get_secret("GEMINI_API_KEY"):
        st.error("⚠️ GEMINI_API_KEY non trovata nei Secrets di Streamlit.")
        return None

    try:
        dati = _chiama_gemini(testo)

        prezzo = _a_float(dati.get("Prezzo"))
        spese = _a_float(dati.get("Spese"))
        indirizzo_estratto = str(dati.get("Indirizzo", "N/D"))
        fermata_metro = str(dati.get("FermataMetro", "N/D"))
        stazione_treno = str(dati.get("Treno", "N/D"))

        lat, lon = trova_coordinate(indirizzo_estratto, fermata_metro, stazione_treno)

        return {
            "Prezzo Immobile (€)": prezzo,
            "Spese (€)": spese,
            "Prezzo Totale (€)": prezzo + spese,
            "Metri Quadri (m²)": _a_float(dati.get("MQ")),
            "Indirizzo": indirizzo_estratto,
            "Latitudine": lat,
            "Longitudine": lon,
            "Piano": str(dati.get("Piano", "N/D")).capitalize(),
            "Ascensore": str(dati.get("Ascensore", "N/D")),
            "Riscaldamento": str(dati.get("Riscaldamento", "N/D")),
            "Condizionatore": str(dati.get("Condizionatore", "N/D")),
            "Numero Vani": str(dati.get("Vani", "N/D")).capitalize(),
            "Classe Energetica": str(dati.get("Classe", "N/D")).upper(),
            "Stazione Treno": stazione_treno.title(),
            "Metro Vicina": str(dati.get("MetroVicina", "N/D")),
            "Linea Metro": str(dati.get("LineaMetro", "N/D")),
            "Fermata Metro": fermata_metro.title(),
            "Contatto Telefonico": str(dati.get("Telefono", "N/D")),
        }

    except Exception as e:
        st.error(f"❌ Errore durante l'estrazione con Gemini: {e}")
        return None


# ---------------------------------------------------------------------------
# MODIFICHE DALLA TABELLA
# ---------------------------------------------------------------------------
def _riga_vuota(riga):
    """True se una riga aggiunta dalla tabella non contiene nessun dato utile."""
    for col in ["Titolo Casa", "Indirizzo", "Note", "Link", "Contatto Telefonico", "Giorno/Ora Visita"]:
        v = riga.get(col)
        if not _e_vuoto(v) and str(v).strip() not in ("", "N/D", "-"):
            return False
    for col in ["Prezzo Immobile (€)", "Spese (€)", "Metri Quadri (m²)", "Voto"]:
        if _a_float(riga.get(col)) > 0:
            return False
    return True


def applica_modifiche_tabella(df_case, df_filtrato, edited_df):
    """Fonde nel catalogo completo le modifiche fatte sulla tabella filtrata.

    - le righe nascoste dai filtri non vengono mai toccate;
    - le righe eliminate vengono rimosse;
    - le righe nuove vengono sempre aggiunte (mai sovrascrivono righe esistenti);
    - se cambia l'indirizzo, le coordinate vengono azzerate per essere ricalcolate.
    """
    visibili = df_filtrato.index
    eliminati = visibili.difference(edited_df.index)
    df_out = df_case.drop(index=eliminati).astype(object)
    ed = edited_df.astype(object)

    mask_esistenti = ed.index.isin(visibili)

    for idx in ed.index[mask_esistenti]:
        vecchio = _pulisci_testo(df_case.at[idx, "Indirizzo"], "Indirizzo")
        for col in COLONNE:
            if col in ed.columns:
                df_out.at[idx, col] = ed.at[idx, col]
        nuovo = _pulisci_testo(df_out.at[idx, "Indirizzo"], "Indirizzo")
        if nuovo != vecchio:
            df_out.at[idx, "Latitudine"] = 0.0
            df_out.at[idx, "Longitudine"] = 0.0

    righe_nuove = []
    for _, r in ed.loc[~mask_esistenti].iterrows():
        riga = {c: r.get(c) for c in COLONNE}
        if _riga_vuota(riga):
            continue
        if _e_vuoto(riga["Data Inserimento"]) or str(riga["Data Inserimento"]).strip() in ("", "N/D"):
            riga["Data Inserimento"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        righe_nuove.append(riga)

    if righe_nuove:
        df_nuove = pd.DataFrame(righe_nuove, columns=COLONNE).astype(object)
        df_out = pd.concat([df_out, df_nuove], ignore_index=True)

    return df_out


# ---------------------------------------------------------------------------
# INTERFACCIA STREAMLIT
# ---------------------------------------------------------------------------
st.title("🏠 Catalogo & Gestione Case in Affitto")
st.write("Incolla l'annuncio a sinistra o modifica direttamente le celle della tabella in basso.")

# Pulizia campi della sidebar dopo un salvataggio riuscito (va fatta PRIMA di creare i widget)
CHIAVI_FORM = ["in_titolo", "in_testo", "in_tel", "in_note", "in_link", "in_visita"]
if st.session_state.pop("reset_form", False):
    for _k in CHIAVI_FORM:
        st.session_state[_k] = ""

if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"))

df_case = carica_dati()

if st.session_state.get("remoto_ko"):
    st.warning(
        "⚠️ Non riesco a leggere il catalogo da GitHub: sto mostrando i dati locali (se presenti) "
        "e il salvataggio è disattivato. Ricarica la pagina tra qualche istante."
    )

# --- BARRA LATERALE ---
with st.sidebar:
    st.header("➕ Aggiungi Nuova Casa")
    titolo_casa = st.text_input("Titolo Casa", placeholder="Es. Trilocale Piazza Bologna", key="in_titolo")
    testo_annuncio = st.text_area("Incolla qui il testo dell'annuncio", height=180, key="in_testo")
    contatto_tel = st.text_input("Contatto Telefonico", placeholder="Es. 333 1234567 (opzionale)", key="in_tel")
    note_casa = st.text_area("Note / Impressioni", placeholder="Es. Molto luminosa, cucina piccola...", key="in_note")
    link = st.text_input("Link (opzionale)", key="in_link")
    visita_data = st.text_input("Giorno e Ora Visita", placeholder="Es. Martedì 14/10 ore 18:00", key="in_visita")

    if st.button("Analizza e Salva", type="primary"):
        if testo_annuncio.strip():
            with st.spinner("Intelligenza Artificiale in azione..."):
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

                nuova_riga = pd.DataFrame([dati])
                df_nuovo = nuova_riga if df_case.empty else pd.concat([nuova_riga, df_case], ignore_index=True)
                df_nuovo = normalizza_df(df_nuovo)

                if salva_dati(df_nuovo):
                    st.session_state["reset_form"] = True
                    st.session_state["toast"] = "✅ Immobile salvato nel catalogo!"
                    st.rerun()
        else:
            st.error("Inserisci il testo prima di salvare.")

    st.divider()

    st.header("🔍 Filtri Rapidi")
    ricerca_testo = st.text_input("Cerca nel titolo, note, indirizzo o telefono", "")

    max_p = df_case["Prezzo Totale (€)"].max() if not df_case.empty else 2500
    max_prezzo_possibile = int(math.ceil((max_p + 500) / 50.0) * 50) if pd.notna(max_p) and max_p > 0 else 2500
    max_prezzo_possibile = max(max_prezzo_possibile, 1500)

    filtro_prezzo_max = st.slider("Prezzo Totale Max (€)", 500, max_prezzo_possibile, max_prezzo_possibile, step=50)
    filtro_solo_da_visitare = st.checkbox("Mostra solo case da visitare")
    filtro_voto_min = st.slider("Voto Minimo", 0.0, 10.0, 0.0, step=0.5)

    st.divider()

    st.header("📍 Coordinate")
    st.caption("Calcola la posizione delle case che non ce l'hanno (es. indirizzo non riconosciuto).")
    forza_coordinate = st.checkbox("Ricalcola anche quelle già presenti", help="Utile se una casa appare nel posto sbagliato sulla mappa.")
    if st.button("Aggiorna coordinate"):
        if df_case.empty:
            st.info("Il catalogo è vuoto.")
        else:
            with st.spinner("Cerco le coordinate (può richiedere un po')..."):
                df_agg, n_agg = completa_coordinate(df_case, forza=forza_coordinate)
            if n_agg == 0:
                st.info("Nessuna coordinata nuova trovata.")
            elif salva_dati(df_agg):
                st.session_state["toast"] = f"📍 Coordinate aggiornate: {n_agg}"
                st.rerun()


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

if ricerca_testo.strip() and not df_filtrato.empty:
    termine = ricerca_testo.strip()
    maschera = pd.Series(False, index=df_filtrato.index)
    for _col in ["Titolo Casa", "Note", "Contatto Telefonico", "Indirizzo"]:
        # regex=False: così "+39" o "(" nella ricerca non fanno crashare l'app
        maschera |= df_filtrato[_col].astype(str).str.contains(termine, case=False, na=False, regex=False)
    df_filtrato = df_filtrato[maschera]

if not df_filtrato.empty:
    df_filtrato = df_filtrato[df_filtrato["Prezzo Totale (€)"] <= filtro_prezzo_max]

if filtro_solo_da_visitare and not df_filtrato.empty:
    df_filtrato = df_filtrato[df_filtrato["Visita Effettuata"] == False]  # noqa: E712

if filtro_voto_min > 0 and not df_filtrato.empty:
    df_filtrato = df_filtrato[df_filtrato["Voto"] >= filtro_voto_min]


# --- SEZIONE MAPPA (CASE + METRO DOPPIO PUNTO) ---
st.subheader("🗺️ Mappa Immobili & Fermate Metro")
if not df_filtrato.empty:
    punti_mappa = []
    info_distanze = []

    with st.spinner("Preparo la mappa..."):
        for idx, row in df_filtrato.iterrows():
            c_lat = _a_float(row.get("Latitudine"))
            c_lon = _a_float(row.get("Longitudine"))
            titolo = str(row.get("Titolo Casa", "Casa"))
            fermata = str(row.get("Fermata Metro", "N/D")).strip()

            if c_lat != 0.0 and c_lon != 0.0:
                # 🔴 Punto Casa (Rosso)
                punti_mappa.append({
                    "Latitudine": c_lat,
                    "Longitudine": c_lon,
                    "color": "#E63946",
                })

                # 🔵 Punto Metro (Blu) + Calcolo Distanza Istantaneo
                if fermata and fermata.upper() not in ["N/D", "NONE", ""]:
                    m_lat, m_lon = ottieni_coordinate(f"Stazione Metro {fermata}")
                    if m_lat != 0.0 and m_lon != 0.0:
                        dist_info = calcola_distanza_haversine(c_lat, c_lon, m_lat, m_lon)
                        if dist_info:
                            metri, min_piedi = dist_info
                            info_distanze.append(f"• **{titolo}** ➔ Metro **{fermata}**: ~{metri} metri (**{min_piedi} min a piedi**)")

                        punti_mappa.append({
                            "Latitudine": m_lat,
                            "Longitudine": m_lon,
                            "color": "#1D3557",
                        })

    if punti_mappa:
        df_mappa = pd.DataFrame(punti_mappa)
        st.map(df_mappa, latitude="Latitudine", longitude="Longitudine", color="color", use_container_width=True)

        if info_distanze:
            with st.expander("🚶‍♂️ Dettaglio distanze a piedi dalle fermate Metro", expanded=True):
                for info in info_distanze:
                    st.markdown(info)
    else:
        st.info("ℹ️ Nessuna coordinata geografica valida trovata per le case attualmente filtrate.")
else:
    st.info("ℹ️ Nessun immobile salvato o filtrato.")

st.divider()


# --- TABELLA DATI ---
st.subheader(f"📋 Case in Catalogo ({len(df_filtrato)} filtrate su {len(df_case)} totali)")

if not df_case.empty:
    st.caption("💡 Prezzo Totale e Prezzo al m² si calcolano da soli. Salva le modifiche prima di cambiare i filtri: quelle non salvate vengono scartate.")

    # La chiave cambia quando cambiano filtri o dati: l'editor riparte pulito e le modifiche
    # non salvate non possono finire per sbaglio su righe diverse.
    _firma = repr((ricerca_testo, filtro_prezzo_max, filtro_solo_da_visitare, filtro_voto_min)) + df_filtrato.to_csv(index=True)
    chiave_editor = f"data_editor_{zlib.crc32(_firma.encode('utf-8'))}"

    edited_df = st.data_editor(
        df_filtrato,
        num_rows="dynamic",
        use_container_width=True,
        key=chiave_editor,
        disabled=["Prezzo Totale (€)", "Prezzo al m² (€/m²)"],
        column_config={
            "Latitudine": None,
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
            "Prezzo Totale (€)": st.column_config.NumberColumn(
                "Prezzo Totale (€)",
                help="Calcolato automaticamente: prezzo + spese",
                format="%.2f",
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
        with st.spinner("Salvataggio in corso..."):
            df_completo = applica_modifiche_tabella(df_case, df_filtrato, edited_df)
            df_completo = normalizza_df(df_completo)
            df_completo, _ = completa_coordinate(df_completo)  # solo righe senza coordinate (nuove o con indirizzo cambiato)
            salvato_ok = salva_dati(df_completo)

        if salvato_ok:
            st.session_state["toast"] = "✅ Sincronizzato con il database!"
            st.rerun()
else:
    st.info("Nessuna casa ancora salvata. Incolla il primo annuncio dalla barra laterale!")
