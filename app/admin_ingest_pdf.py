"""
admin_ingest_pdf.py – Admin-Tool zum Einspielen von Curriculum-PDFs.
=====================================================================

Nutzt die bestehende process_pdf()-Pipeline aus pipeline.py direkt,
ohne den User-Upload in main.py zu öffnen.

USAGE:
    python admin_ingest_pdf.py

Die PDFs werden aus dem Ordner data/admin_pdfs/ geladen.
Lege deine Curriculum-PDFs dort ab bevor du das Skript startest.

ORDNERSTRUKTUR:
    data/
    └── admin_pdfs/
        ├── 1193_17_BS_Wirtschaftsinformatik.pdf
        ├── 1199_17_MS_Wirtschaftsinformatik.pdf
        └── ...
"""

import os
from dotenv import load_dotenv
from pipeline import process_pdf, get_or_create_study_program, erkennen_abschlussart, supabase

load_dotenv()

PDF_DIR      = "../data/admin_pdfs"
ADMIN_USER_ID = "61a487b6-af7f-459e-ae78-2fce48be88c6"

# ── Mapping: PDF-Dateiname → Studiengang-Metadaten ───────────────────────────
# Füge hier für jedes PDF den passenden Eintrag hinzu.
# "code" muss mit dem code in study_programs übereinstimmen (get_or_create).
PDF_MANIFEST = [
    {
        "filename": "1193_17_BS_Wirtschaftsinformatik.pdf",
        "code":     "033/526",
        "name":     "Wirtschaftsinformatik",
    },
    {
        "filename": "1199_19_MS_Wirtschaftsinformatik.pdf",
        "code":     "066/926",
        "name":     "Wirtschaftsinformatik",
    },
    
]


def run_admin_ingest():
    os.makedirs(PDF_DIR, exist_ok=True)

    # Welche PDFs liegen tatsächlich im Ordner?
    available = set(os.listdir(PDF_DIR))
    to_process = [e for e in PDF_MANIFEST if e["filename"] in available]
    skipped    = [e for e in PDF_MANIFEST if e["filename"] not in available]

    if skipped:
        print(f"⚠️  {len(skipped)} PDF(s) nicht gefunden (im Manifest aber nicht in {PDF_DIR}):")
        for e in skipped:
            print(f"   - {e['filename']}")

    if not to_process:
        print(f"\n❌ Keine PDFs zum Verarbeiten gefunden.")
        print(f"   Lege deine PDFs in: {os.path.abspath(PDF_DIR)}/")
        return

    print(f"\n🚀 Starte PDF-Ingest für {len(to_process)} Datei(en)...\n")

    success = 0
    errors  = 0

    for entry in to_process:
        pdf_path = os.path.join(PDF_DIR, entry["filename"])
        print(f"📄 {entry['filename']}")

        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            # Abschlussart automatisch aus PDF erkennen
            degree_type = erkennen_abschlussart(pdf_bytes)
            print(f"   Erkannter Abschluss: {degree_type or 'unbekannt'}")

            # Studiengang anlegen / finden
            program_id = get_or_create_study_program(
                entry["code"], entry["name"], degree_type
            )

            # PDF durch die volle Pipeline jagen
            n = process_pdf(pdf_bytes, entry["filename"], program_id, ADMIN_USER_ID)
            print(f"   ✅ {n} Chunks erstellt und gespeichert.\n")
            success += 1

        except ValueError as e:
            # Duplikat – bereits hochgeladen
            print(f"   ⏭️  Übersprungen: {e}\n")
        except Exception as e:
            print(f"   ❌ Fehler: {e}\n")
            import traceback
            traceback.print_exc()

    print("=" * 50)
    print(f"🏁 Fertig! {success} erfolgreich, {errors} Fehler.")


if __name__ == "__main__":
    run_admin_ingest()