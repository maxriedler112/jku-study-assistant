"""
main.py – Streamlit-Frontend des JKU Study Assistants.
=======================================================

BENUTZER-ROLLEN:
  Admin  → kann über handbook_scraper.py Curriculum-Daten vorladen
  User   → kann ausschließlich persönliche KUSSS-Dateien hochladen:
              1. KUSSS-Kalender (.ics)    → Stundenplan & Termine
              2. KUSSS-Studienerfolg      → Noten & ECTS (PDF oder CSV)

HINWEIS: Das Hochladen allgemeiner Curricula-PDFs ist im Frontend
         bewusst NICHT verfügbar. Studiengangsdaten werden ausschließlich
         vom Admin über handbook_scraper.py vorgeladen.
"""

import re
import os
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv
from assistant import ask_assistant
from pipeline import (
    process_ics,
    process_studienerfolg,
    get_or_create_study_program,
    supabase as service_supabase,
)

load_dotenv()

# ==============================================================================
# ### TEMP: HARDCODED USER_ID FÜR TESTS ###
# TODO: Diese ID später durch echte Login-Logik ersetzen
TEMP_USER_ID = "61a487b6-af7f-459e-ae78-2fce48be88c6"
# ==============================================================================

_supabase_url  = os.getenv("SUPABASE_URL")
_supabase_anon = os.getenv("SUPABASE_ANON_KEY")

if not _supabase_url or not _supabase_anon:
    st.error("Konfigurationsfehler: SUPABASE_URL oder SUPABASE_ANON_KEY fehlt in der .env Datei.")
    st.stop()

supabase = create_client(_supabase_url, _supabase_anon)


# ═══════════════════════════════════════════════════════════════════════════════
# DATEN-LADEN
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=60)
def lade_studiengaenge() -> list[dict]:
    """Lädt alle Studiengänge aus der Datenbank (via Service-Role-Key, umgeht RLS)."""
    return (
        service_supabase.table("study_programs")
        .select("id,code,name,degree_type")
        .order("name")
        .execute()
        .data or []
    )


@st.cache_data(ttl=30)
def lade_noten_zusammenfassung(user_id: str) -> dict | None:
    """
    Lädt eine kompakte Noten-Zusammenfassung für den aktuellen User.
    Gibt None zurück wenn noch keine Noten vorhanden sind.
    """
    result = (
    service_supabase.table("completed_courses")   # ← geändert
    .select("grade,ects,passed")
    .eq("user_id", user_id)
    .execute()
    )
    if not result.data:
        return None

    grades        = result.data
    passed        = [g for g in grades if g["passed"]]
    ects_gesamt   = sum(g["ects"] for g in passed)
    schnitt_noten = [g["grade"] for g in grades if g["grade"] and g["grade"] <= 4]
    schnitt       = round(sum(schnitt_noten) / len(schnitt_noten), 2) if schnitt_noten else None

    return {
        "total":      len(grades),
        "passed":     len(passed),
        "failed":     len(grades) - len(passed),
        "ects_total": round(ects_gesamt, 1),
        "schnitt":    schnitt,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION-STATE INITIALISIERUNG
# ═══════════════════════════════════════════════════════════════════════════════

if "user_id" not in st.session_state:
    st.session_state.user_id = TEMP_USER_ID

if "messages" not in st.session_state:
    st.session_state.messages = []

if "study_program_id" not in st.session_state:
    st.session_state.study_program_id = None


# ═══════════════════════════════════════════════════════════════════════════════
# SEITEN-KONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="JKU Study Assistant",
    page_icon="🎓",
    layout="wide",
)


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.info(f"👤 Test-Modus\n`{st.session_state.user_id[:8]}…`")

    # ── Studiengang-Filter ─────────────────────────────────────────────────────
    st.header("🔍 Studiengang")

    programs = lade_studiengaenge()
    program_options: dict[str, str | None] = {"Alle Studiengänge": None}

    for p in programs:
        suffix = f" ({p['degree_type']})" if p.get("degree_type") else ""
        label  = f"{p['code']} – {p['name']}{suffix}"
        program_options[label] = p["id"]

    selected_label = st.selectbox(
        "Für welchen Studiengang möchtest du Fragen stellen?",
        options=list(program_options.keys()),
        help="Schränkt die Suche auf Inhalte dieses Studiengangs ein.",
    )
    st.session_state.study_program_id = program_options[selected_label]

    st.divider()

    # ── Kalender-Import ────────────────────────────────────────────────────────
    st.header("📅 Stundenplan")
    st.caption("Exportiere deinen Kalender aus KUSSS und lade die .ics-Datei hoch.")

    uploaded_ics = st.file_uploader(
        "KUSSS-Kalender hochladen",
        type=["ics"],
        key="ics_uploader",
        help="Zu finden in KUSSS unter: Mein Stundenplan → Export → iCalendar",
    )

    if uploaded_ics and st.button("📥 Kalender importieren", key="ics_btn"):
        with st.spinner("Kalender wird importiert..."):
            try:
                count = process_ics(
                    uploaded_ics.read(),
                    uploaded_ics.name,
                    st.session_state.user_id,
                )
                st.success(f"✅ Kalender importiert! ({count} Events gesamt)")
            except Exception as e:
                st.error(f"Fehler beim Importieren: {e}")

    st.divider()

    # ── Studienerfolg-Import ───────────────────────────────────────────────────
    st.header("🏆 Studienerfolg")
    st.caption(
        "Lade deinen persönlichen Notennachweis aus KUSSS hoch. "
        "Unterstützte Formate: PDF, CSV."
    )

    uploaded_erfolg = st.file_uploader(
        "KUSSS-Studienerfolg hochladen",
        type=["pdf", "csv"],
        key="erfolg_uploader",
        help="Zu finden in KUSSS unter: Mein Studium → Studienerfolg → Export",
    )

    if uploaded_erfolg and st.button("📥 Noten importieren", key="erfolg_btn"):
        with st.spinner("Noten werden eingelesen..."):
            try:
                summary = process_studienerfolg(
                    uploaded_erfolg.read(),
                    uploaded_erfolg.name,
                    st.session_state.user_id,
                )
                # Cache leeren damit die Noten-Zusammenfassung aktualisiert wird
                lade_noten_zusammenfassung.clear()

                st.success(
                    f"✅ {summary['saved']} Einträge gespeichert! "
                    f"Bestanden: {summary['passed']} | "
                    f"Nicht bestanden: {summary['failed']} | "
                    f"ECTS gesamt: {summary['ects_total']}"
                )
            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"Fehler beim Einlesen: {e}")

    # ── Noten-Zusammenfassung ──────────────────────────────────────────────────
    noten_info = lade_noten_zusammenfassung(st.session_state.user_id)
    if noten_info:
        st.divider()
        st.subheader("📊 Dein Studienfortschritt")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("ECTS (bestanden)", noten_info["ects_total"])
            st.metric("Prüfungen gesamt", noten_info["total"])
        with col2:
            if noten_info["schnitt"]:
                st.metric("Notendurchschnitt", noten_info["schnitt"])
            st.metric("Nicht bestanden", noten_info["failed"])


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT-INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

st.title("🎓 JKU Study Assistant")
st.markdown(
    "Frag mich alles zu deinem Studienplan, Lehrveranstaltungen, "
    "Prüfungsterminen oder deinem persönlichen Studienerfolg!"
)

# Verlauf anzeigen
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Neue Nachricht verarbeiten
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