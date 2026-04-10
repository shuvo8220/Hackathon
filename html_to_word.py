"""
Convert HTML forms to Word (.docx) using LibreOffice.
Run: hack\Scripts\python.exe html_to_word.py
"""

import subprocess
from pathlib import Path
from docx.oxml import OxmlElement

HTML_STORAGE  = Path(__file__).parent / "roc_forms_html_storage"
WORD_OUTPUT   = Path(__file__).parent / "word_forms"
WORD_OUTPUT.mkdir(exist_ok=True)

SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"
SKIP    = ["html"]

def fix_spacing(docx_path: Path):
    """Remove extra paragraph spacing from all paragraphs"""
    from docx import Document
    from docx.shared import Pt
    from docx.oxml.ns import qn
    from lxml import etree

    doc = Document(str(docx_path))
    for para in doc.paragraphs:
        fmt = para.paragraph_format
        fmt.space_before = Pt(0)
        fmt.space_after  = Pt(0)
        fmt.line_spacing = Pt(12)

        # Also remove spacing via XML directly
        pPr = para._p.get_or_add_pPr()
        spacing = pPr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            pPr.append(spacing)
        spacing.set(qn("w:before"), "0")
        spacing.set(qn("w:after"),  "0")
        spacing.set(qn("w:line"),   "240")
        spacing.set(qn("w:lineRule"), "auto")

    doc.save(str(docx_path))
def convert_html_to_docx(html_path: Path, out_dir: Path) -> bool:
    try:
        # Inject CSS to reduce spacing before conversion
        raw = html_path.read_text(encoding="utf-8", errors="ignore")
        css = """<style>
        * { margin: 0 !important; padding: 0 !important; }
        body { font-family: Verdana, sans-serif; font-size: 10pt; line-height: 1.2; }
        table { border-collapse: collapse; width: 100%; }
        td, tr { margin: 0 !important; padding: 2px 0 !important; line-height: 1.3; }
        p { margin: 0 !important; padding: 0 !important; }
        </style>"""
        if "<head>" in raw:
            patched = raw.replace("<head>", f"<head>{css}", 1)
        else:
            patched = css + raw

        # Write patched HTML to temp file
        tmp = html_path.parent / f"_tmp_{html_path.name}"
        tmp.write_text(patched, encoding="utf-8")

        result = subprocess.run([
            SOFFICE,
            "--headless",
            "--convert-to", "docx:MS Word 2007 XML",
            "--outdir", str(out_dir.resolve()),
            str(tmp.resolve())
        ], capture_output=True, text=True, timeout=60)

        tmp.unlink(missing_ok=True)

        # Rename _tmp_xxx.docx -> xxx.docx
        tmp_out = out_dir / f"_tmp_{html_path.stem}.docx"
        final_out = out_dir / f"{html_path.stem}.docx"
        if tmp_out.exists():
            tmp_out.rename(final_out)

        # Fix spacing with python-docx
        if final_out.exists():
            fix_spacing(final_out)

        if result.returncode != 0:
            print(f"  ERR detail: {result.stderr.strip() or result.stdout.strip()}")
        return result.returncode == 0
    except Exception as e:
        print(f"  ERR detail: {e}")
        return False

def main():
    total = converted = 0

    for btype_dir in sorted(HTML_STORAGE.iterdir()):
        if not btype_dir.is_dir():
            continue
        btype = btype_dir.name
        out_dir = WORD_OUTPUT / btype
        out_dir.mkdir(exist_ok=True)

        html_files = [f for f in sorted(btype_dir.glob("*.html"))
                      if f.stem and f.stem not in SKIP]
        print(f"\n[{btype}] {len(html_files)} files")

        for html_file in html_files:
            total += 1
            ok = convert_html_to_docx(html_file, out_dir)
            status = "OK " if ok else "ERR"
            print(f"  {status} {html_file.stem}.docx")
            if ok:
                converted += 1

    print(f"\nDone! {converted}/{total} -> {WORD_OUTPUT}")

if __name__ == "__main__":
    main()
