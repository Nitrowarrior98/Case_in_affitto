with st.sidebar:
    st.header("➕ Aggiungi Nuova Casa")

    titolo_casa = st.text_input(
        "Titolo Casa",
        placeholder="Es. Trilocale Piazza Bologna"
    )

    testo_annuncio = st.text_area(
        "Incolla qui il testo dell'annuncio",
        height=180
    )

    contatto_tel = st.text_input(
        "Contatto Telefonico",
        placeholder="Es. 333 1234567 (opzionale)"
    )

    note_casa = st.text_area(
        "Note / Impressioni",
        placeholder="Es. Molto luminosa, cucina piccola..."
    )

    link = st.text_input("Link (opzionale)")
    visita_data = st.text_input(
        "Giorno e Ora Visita",
        placeholder="Es. Martedì 14/10 ore 18:00"
    )
