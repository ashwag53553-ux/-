#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
فهرسة المكتبة — index_library.py
================================
يمسح مجلد «مراجع الرسالة» ويبني/يحدّث source_registry/registry.tsv:
  • اسم المجلد ← المؤلف، اسم الملف ← العنوان المبدئي
  • عدد الصفحات الحقيقي، وهل الكتاب نصّي أم ممسوح (يحتاج OCR)
  • لا يمسّ أي حقل ملأتَه يدوياً (الدار/الطبعة/السنة/التصنيف) — يضيف فقط
ويُخرج طابور OCR في source_registry/ocr_queue.txt

    python tools/index_library.py                       # يقرأ library_root من الإعدادات
    python tools/index_library.py --root "D:/مراجع الرسالة" --write
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "source_registry" / "registry.tsv"
OCR_QUEUE = ROOT / "source_registry" / "ocr_queue.txt"
FIELDS = ["id", "النوع", "العنوان", "المؤلف", "المحقق", "الطبعة", "الدار", "المدينة",
          "السنة", "عدد_الأجزاء", "عدد_الصفحات", "الملف", "حالة_النص", "التصنيف",
          "ملاحظات"]
AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def probe(pdf: Path, sample=6):
    """(عدد الصفحات، هل فيه نص مستخرَج) — يحتاج pypdf، وإلا يرجع (None, None)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader          # type: ignore
        except ImportError:
            return None, None
    try:
        reader = PdfReader(str(pdf))
        pages = len(reader.pages)
        chars = 0
        for p in reader.pages[:sample]:
            chars += len((p.extract_text() or "").strip())
        return pages, chars > 200
    except Exception:
        return None, None


def load_existing() -> dict:
    if not REGISTRY.exists():
        return {}
    with REGISTRY.open(encoding="utf-8-sig", newline="") as fh:
        return {(r.get("الملف") or "").strip(): r
                for r in csv.DictReader(fh, delimiter="\t") if r.get("الملف")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="فهرسة مكتبة المراجع")
    ap.add_argument("--root")
    ap.add_argument("--write", action="store_true", help="اكتب في السجل فعلياً")
    args = ap.parse_args(argv)

    cfg = json.loads((ROOT / "thesis.config.json").read_text(encoding="utf-8-sig"))
    root = Path(args.root or cfg.get("library_root", ""))
    if not root.exists():
        sys.exit(f"[!] مجلد المكتبة غير موجود: {root}\n"
                 f"    شغّل السكربت على الجهاز الذي فيه المكتبة، أو مرّر --root")

    existing = load_existing()
    rows, queue, new, scanned = [], [], 0, 0
    pdfs = sorted(root.rglob("*.pdf"))
    for i, pdf in enumerate(pdfs, 1):
        rel = str(pdf.relative_to(root)).replace("\\", "/")
        pages, has_text = probe(pdf)
        row = existing.get(rel) or existing.get(str(pdf)) or {}
        if not row:
            new += 1
            row = {f: "" for f in FIELDS}
            row["id"] = f"SRC{i:03d}"
            row["النوع"] = "كتاب"
            row["العنوان"] = pdf.stem
            row["المؤلف"] = pdf.parent.name if pdf.parent != root else ""
            row["الملف"] = rel
            row["ملاحظات"] = "مفهرس آلياً — أكمل الطبعة/الدار/السنة يدوياً"
        if pages:
            row["عدد_الصفحات"] = str(pages).translate(AR)
        if has_text is not None:
            row["حالة_النص"] = "نصي" if has_text else "ممسوح"
            if not has_text:
                scanned += 1
                queue.append(str(pdf))
        rows.append({f: row.get(f, "") for f in FIELDS})

    print(f"  ملفات PDF        : {len(pdfs)}")
    print(f"  قيود جديدة       : {new}")
    print(f"  ممسوح (يحتاج OCR): {scanned}")
    if not any(probe(p)[0] for p in pdfs[:1]):
        print("  [i] لقياس الصفحات وكشف الممسوح ثبّت:  pip install pypdf")

    if args.write:
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        with REGISTRY.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        OCR_QUEUE.write_text("\n".join(queue), encoding="utf-8")
        print(f"  كُتب السجل       : {REGISTRY}")
        print(f"  طابور OCR        : {OCR_QUEUE}")
    else:
        print("  (تجربة فقط — أضف --write للكتابة)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
