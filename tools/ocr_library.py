#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خطّ OCR للمراجع الممسوحة — ocr_library.py
=========================================
يمرّر كل ملف في source_registry/ocr_queue.txt على ocrmypdf بلغة عربية،
ويكتب نسخة قابلة للبحث بجانب الأصل (لا يمسّ الأصل)، ثم يحدّث حالة_النص.

المتطلبات على الجهاز (مرة واحدة):
    pip install ocrmypdf pypdf
    Tesseract + حزمة اللغة العربية:  tesseract-ocr-ara
    (ويندوز: نزّل مثبّت Tesseract ثم أضف مجلده إلى PATH)

    python tools/ocr_library.py --limit 5      # جرّب على خمسة أولاً
    python tools/ocr_library.py --all
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "source_registry" / "ocr_queue.txt"
LOG = ROOT / "state" / "ocr_log.txt"


def main(argv=None):
    ap = argparse.ArgumentParser(description="OCR للمراجع الممسوحة")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--suffix", default="_OCR")
    ap.add_argument("--lang", default="ara+eng")
    args = ap.parse_args(argv)

    if shutil.which("ocrmypdf") is None:
        sys.exit("[!] ocrmypdf غير مثبّت.  pip install ocrmypdf  + ثبّت Tesseract "
                 "مع حزمة اللغة العربية tesseract-ocr-ara")
    if not QUEUE.exists():
        sys.exit(f"[!] لا يوجد طابور OCR. شغّل أولاً: python tools/index_library.py --write")

    files = [Path(l.strip()) for l in QUEUE.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    if args.limit and not args.all:
        files = files[:args.limit]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    done = fail = 0
    with LOG.open("a", encoding="utf-8") as log:
        for i, src in enumerate(files, 1):
            out = src.with_name(src.stem + args.suffix + ".pdf")
            if out.exists():
                print(f"  [{i}/{len(files)}] موجود سلفاً: {out.name}")
                continue
            print(f"  [{i}/{len(files)}] OCR: {src.name}")
            rc = subprocess.run(
                ["ocrmypdf", "-l", args.lang, "--skip-text", "--optimize", "1",
                 "--quiet", str(src), str(out)]).returncode
            if rc == 0:
                done += 1
                log.write(f"OK\t{src}\t{out}\n")
            else:
                fail += 1
                log.write(f"FAIL({rc})\t{src}\n")
    print(f"\n  تمّ: {done} | فشل: {fail} | السجل: {LOG}")
    print("  ثم أعد الفهرسة:  python tools/index_library.py --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
