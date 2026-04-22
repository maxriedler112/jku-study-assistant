import re
import os
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv
from assistant import ask_assistant
from pipeline import process_pdf, process_ics, get_or_create_study_program

load_dotenv()

# Env-Validierung beim Start
_supabase_url  = os.getenv("SUPABASE_URL")
_supabase_anon = os.getenv("SUPABASE_ANON_KEY")

if not _supabase_url or not _supabase_anon:
    st.error("Konfigurationsfehler: SUPABASE_URL oder SUPABASE_ANON_KEY fehlt in der .env Datei.")
    st.stop()

# Nur Anon-Key im Frontend — Service Role Key bleibt in pipeline.py / assistant.py
supabase = create_client(_supabase_url, _supabase_anon)


def validate_program_code(code: str) -> bool:
    """Studienkennzahl: 3–6 Ziffern, z.B. 526 oder 926."""
    return bool(re.match(r'^\d{3,6}$', code))


def validate_program_name(name: str) -> bool:
    """Studiengangsname: 3–200 Zeichen, nur normale Buchstaben/Zahlen/Leerzeichen."""
    return bool(name) and 3 <= len(name) <= 200 and re.match(r'^[\w\s\-äöüÄÖÜß,.()/]+$', name)


def validate_user_id(user_id: str) -> bool:
    """JKU Matrikelnummer: 'k' + 8 Ziffern oder nur 8 Ziffern."""
    return bool(re.match(r'^k?\d{7,8}$', user_id.strip()))


st.set_page_config(page_title="JKU Study Assistant", page_icon="🎓", layout="wide")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📁 Dokumente")

    program_code_raw = st.text_input("Studienkennzahl", placeholder="z.B. 526")
    program_code = program_code_raw.split("/")[-1].strip()
    program_name = st.text_input("Studiengang", placeholder="z.B. Wirtschaftsinformatik")

    uploaded_pdf = st.file_uploader("PDF hochladen", type=["pdf"])
    if uploaded_pdf and st.button("Verarbeiten", key="pdf_btn"):
        if not program_code or not program_name:
            st.warning("Bitte Studienkennzahl und Studiengang angeben.")
        elif not validate_program_code(program_code):
            st.warning("Ungültige Studienkennzahl — bitte nur die Zahl eingeben (z.B. 526).")
        elif not validate_program_name(program_name):
            st.warning("Ungültiger Studiengangsname — bitte nur normale Zeichen verwenden.")
        else:
            with st.spinner("PDF wird verarbeitet..."):
                try:
                    program_id = get_or_create_study_program(program_code, program_name)
                    n = process_pdf(uploaded_pdf.read(), uploaded_pdf.name, program_id)
                    st.success(f"✅ {n} Chunks erstellt und gespeichert!")
                except ValueError as e:
                    st.warning(str(e))
                except Exception as e:
                    st.error(f"Fehler: {e}")

    st.divider()

    st.header("🔍 Suche einschränken")
    programs = supabase.table("study_programs").select("id,code,name").execute().data or []
    program_options = {"Alle Studiengänge": None}
    program_options.update({f"{p['code']} – {p['name']}": p["id"] for p in programs})

    selected_label = st.selectbox("Studiengang filtern", options=list(program_options.keys()))
    st.session_state.study_program_id = program_options[selected_label]

    st.divider()
    st.header("📅 Stundenplan")

    user_id = st.text_input("Matrikelnummer", placeholder="z.B. k12345678")
    if user_id:
        if validate_user_id(user_id):
            st.session_state.user_id = user_id.strip()
        else:
            st.warning("Ungültige Matrikelnummer — Format: k12345678 oder 12345678.")

    uploaded_ics = st.file_uploader("KUSSS .ics hochladen", type=["ics"])
    if uploaded_ics and st.button("Importieren", key="ics_btn"):
        if not st.session_state.get("user_id"):
            st.warning("Bitte zuerst eine gültige Matrikelnummer eingeben.")
        else:
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
                user_id=st.session_state.get("user_id"),
                study_program_id=st.session_state.get("study_program_id"),
            )
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
