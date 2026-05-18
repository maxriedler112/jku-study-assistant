"""
admin_ingest_pdf.py – Admin-Tool zum Einspielen von Curriculum-PDFs.
=====================================================================
Nutzt process_pdf_curriculum() aus pipeline.py – erzeugt web-chunk-
kompatible Metadaten (ects, module_name, lva_name, lva_code, ...).

USAGE:
    python admin_ingest_pdf.py

PDFs kommen aus data/admin_pdfs/. PDF_MANIFEST anpassen für neue Dateien.
"""

import os
from dotenv import load_dotenv
from pipeline import (
    get_or_create_study_program,
    erkennen_abschlussart,
    process_pdf_curriculum,   # ← neue Funktion statt process_pdf
    supabase,
)

load_dotenv()

PDF_DIR       = "../data/admin_pdfs"
ADMIN_USER_ID = "61a487b6-af7f-459e-ae78-2fce48be88c6"

PDF_MANIFEST = [
    {
        "filename":      "1193_17_BS_Wirtschaftsinformatik.pdf",
        "code":          "033/526",
        "name":          "Wirtschaftsinformatik",
        "study_program": "Wirtschaftsinformatik",
    },
    {
        "filename":      "1199_19_MS_Wirtschaftsinformatik.pdf",
        "code":          "066/926",
        "name":          "Wirtschaftsinformatik",
        "study_program": "Wirtschaftsinformatik",
    },
]


def run_admin_ingest():
    os.makedirs(PDF_DIR, exist_ok=True)

    available  = set(os.listdir(PDF_DIR))
    to_process = [e for e in PDF_MANIFEST if e["filename"] in available]
    skipped    = [e for e in PDF_MANIFEST if e["filename"] not in available]

    if skipped:
        print(f"⚠️  {len(skipped)} PDF(s) nicht im Ordner:")
        for e in skipped:
            print(f"   - {e['filename']}")

    if not to_process:
        print(f"\n❌ Keine PDFs zum Verarbeiten in: {os.path.abspath(PDF_DIR)}/")
        return

    print(f"\n🚀 Starte PDF-Ingest für {len(to_process)} Datei(en)...\n")
    success = errors = 0

    for entry in to_process:
        pdf_path = os.path.join(PDF_DIR, entry["filename"])
        print(f"📄 {entry['filename']}")

        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            degree_type = erkennen_abschlussart(pdf_bytes)
            print(f"   Erkannter Abschluss: {degree_type or 'unbekannt'}")

            program_id = get_or_create_study_program(
                entry["code"], entry["name"], degree_type
            )

            n = process_pdf_curriculum(
                pdf_bytes,
                filename=entry["filename"],
                program_id=program_id,
                user_id=ADMIN_USER_ID,
                degree=degree_type or "Bachelor",
                study_program=entry["study_program"],
            )
            print(f"   ✅ {n} Chunks erstellt und gespeichert.\n")
            success += 1

        except ValueError as e:
            print(f"   ⏭️  Übersprungen: {e}\n")
        except Exception as e:
            print(f"   ❌ Fehler: {e}\n")
            import traceback
            traceback.print_exc()
            errors += 1

    print("=" * 50)
    print(f"🏁 Fertig! {success} erfolgreich, {errors} Fehler.")


if __name__ == "__main__":
    run_admin_ingest()