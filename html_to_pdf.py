"""
Convert all HTML forms to PDF using LibreOffice (handles Word XML format too).
Run: hack\Scripts\python.exe html_to_pdf.py
"""

import subprocess
from pathlib import Path

HTML_STORAGE = Path(__file__).parent / "roc_forms_html_storage"
PDF_OUTPUT   = Path(__file__).parent / "pdf_forms"
PDF_OUTPUT.mkdir(exist_ok=True)

SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"
SKIP    = ["html"]

def convert_to_pdf(html_path: Path, out_dir: Path) -> bool:
    try:
        result = subprocess.run([
            SOFFICE,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(out_dir.resolve()),
            str(html_path.resolve())
        ], capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    except Exception as e:
        print(f"  ERR: {e}")
        return False

def main():
    total = converted = 0

    for btype_dir in sorted(HTML_STORAGE.iterdir()):
        if not btype_dir.is_dir():
            continue
        btype = btype_dir.name
        out_dir = PDF_OUTPUT / btype
        out_dir.mkdir(exist_ok=True)

        html_files = [f for f in sorted(btype_dir.glob("*.html"))
                      if f.stem and f.stem not in SKIP]
        print(f"\n[{btype}] {len(html_files)} files")

        for html_file in html_files:
            total += 1
            ok = convert_to_pdf(html_file, out_dir)
            print(f"  {'OK ' if ok else 'ERR'} {html_file.stem}.pdf")
            if ok:
                converted += 1

    print(f"\nDone! {converted}/{total} -> {PDF_OUTPUT}")

if __name__ == "__main__":
    main()
