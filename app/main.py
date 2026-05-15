import re
import os
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv
from assistant import ask_assistant
from pipeline import process_pdf, process_ics, get_or_create_study_program, erkennen_abschlussart, supabase as service_supabase

load_dotenv()

# ==============================================================================
# ### TEMP: HARDCODED USER_ID FÜR TESTS ###
# TODO: Diese ID später durch die Login-Logik / UI-Input ersetzen
TEMP_USER_ID = "61a487b6-af7f-459e-ae78-2fce48be88c6"
# ==============================================================================

# Env-Validierung beim Start
_supabase_url  = os.getenv("SUPABASE_URL")
_supabase_anon = os.getenv("SUPABASE_ANON_KEY")

if not _supabase_url or not _supabase_anon:
    st.error("Konfigurationsfehler: SUPABASE_URL oder SUPABASE_ANON_KEY fehlt in der .env Datei.")
    st.stop()

supabase = create_client(_supabase_url, _supabase_anon)

@st.cache_data(ttl=60)
def lade_studiengaenge() -> list[dict]:
    """Lädt alle Studiengänge aus der Datenbank via Service-Role-Key (umgeht RLS)."""
    return service_supabase.table("study_programs").select("id,code,name,degree_type").order("name").execute().data or []

# Initialisierung der Session States
if "user_id" not in st.session_state:
    st.session_state.user_id = TEMP_USER_ID

def validate_program_code(code: str) -> bool:
    return bool(re.match(r'^\d{3,6}$', code))

def validate_program_name(name: str) -> bool:
    return bool(name) and 3 <= len(name) <= 200 and re.match(r'^[\w\s\-äöüÄÖÜß,.()/]+$', name)

st.set_page_config(page_title="JKU Study Assistant", page_icon="🎓", layout="wide")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.info(f"👤 Test-Modus: Angemeldet als {st.session_state.user_id}")
    
    st.header("📁 Dokumente")
    program_code_raw = st.text_input("Studienkennzahl", placeholder="z.B. 526")
    program_code = program_code_raw.split("/")[-1].strip()
    program_name = st.text_input("Studiengang", placeholder="z.B. Wirtschaftsinformatik")

    uploaded_pdf = st.file_uploader("PDF hochladen", type=["pdf"])
    if uploaded_pdf and st.button("Verarbeiten", key="pdf_btn"):
        if not program_code or not program_name:
            st.warning("Bitte Studienkennzahl und Studiengang angeben.")
        elif not validate_program_code(program_code):
            st.warning("Ungültige Studienkennzahl.")
        elif not validate_program_name(program_name):
            st.warning("Ungültiger Studiengangsname.")
        else:
            with st.spinner("PDF wird verarbeitet..."):
                try:
                    pdf_bytes = uploaded_pdf.read()
                    # Abschlussart automatisch aus dem PDF-Inhalt erkennen
                    degree_type = erkennen_abschlussart(pdf_bytes)
                    program_id = get_or_create_study_program(program_code, program_name, degree_type)
                    n = process_pdf(pdf_bytes, uploaded_pdf.name, program_id, st.session_state.user_id)
                    # Cache leeren, damit der neue Studiengang sofort im Filter erscheint
                    lade_studiengaenge.clear()
                    label = f" ({degree_type})" if degree_type else ""
                    st.success(f"✅ {n} Chunks erstellt! Erkannter Abschluss: {degree_type or 'unbekannt'}")
                except Exception as e:
                    st.error(f"Fehler: {e}")

    st.divider()
    st.header("🔍 Suche einschränken")

    # Studiengänge aus dem Cache laden (wird automatisch nach 60 s aktualisiert)
    programs = lade_studiengaenge()
    program_options = {"Alle Studiengänge": None}
    for p in programs:
        # Abschlussart in Klammern anhängen, falls vorhanden (z.B. "526 – Wirtschaftsinformatik (Bachelor)")
        suffix = f" ({p['degree_type']})" if p.get("degree_type") else ""
        program_options[f"{p['code']} – {p['name']}{suffix}"] = p["id"]

    selected_label = st.selectbox("Studiengang filtern", options=list(program_options.keys()))
    st.session_state.study_program_id = program_options[selected_label]

    st.divider()
    st.header("📅 Stundenplan")
    # Import-Button nutzt ebenfalls den session_state.user_id
    uploaded_ics = st.file_uploader("KUSSS .ics hochladen", type=["ics"])
    if uploaded_ics and st.button("Importieren", key="ics_btn"):
        with st.spinner("Kalender wird importiert..."):
            try:
                process_ics(uploaded_ics.read(), uploaded_ics.name, st.session_state.user_id)
                st.success("✅ Kalender importiert!")
            except Exception as e:
                st.error(f"Fehler: {e}")

# ── Chat ──────────────────────────────────────────────────────────────────────
st.title("🎓 JKU Study Assistant")
st.markdown("Frag mich alles zum Curriculum oder deinem Stundenplan!")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Deine Frage..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Ich suche die Antwort..."):
            response = ask_assistant(
                prompt,
                user_id=st.session_state.user_id,
                study_program_id=st.session_state.get("study_program_id"),
            )
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})