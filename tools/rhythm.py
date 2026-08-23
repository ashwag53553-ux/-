#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خريطة الإيقاع — rhythm.py
=========================
يرسم أطوال فقرات المسودّة عموداً عموداً، ويؤشّر على مواضع الرتابة، ويقترح
أين تُدخَل فقرة قصيرة حاسمة وأين تُدمج فقرتان. الغرض: أن يُرى العيب بالعين
قبل أن يُقاس بالحارس.

    python tools/rhythm.py chapters/preliminary/الفصل_التمهيدي.md
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
SENT_SPLIT_RE = re.compile(r"[.؟!]")


def n(x):
    return str(x).translate(AR)


def paragraphs(text: str):
    out, buf = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if buf:
                out.append(" ".join(buf))
                buf = []
            continue
        if s.startswith(("#", ">", "|", "-", "*", "[^", "<!--")) or re.match(r"^\d+[.)]", s):
            if buf:
                out.append(" ".join(buf))
                buf = []
            continue
        buf.append(s)
    if buf:
        out.append(" ".join(buf))
    return [p for p in out if len(p.split()) >= 4]


def main(argv=None):
    ap = argparse.ArgumentParser(description="خريطة إيقاع الفقرات")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--width", type=int, default=46)
    args = ap.parse_args(argv)

    for f in args.files:
        p = Path(f)
        paras = paragraphs(p.read_text(encoding="utf-8-sig"))
        if not paras:
            print(f"  [!] لا فقرات في {p.name}")
            continue
        lens = [len(x.split()) for x in paras]
        med = statistics.median(lens)
        top = max(lens)
        print(f"\n══ {p.name} — {n(len(paras))} فقرة | الوسيط {n(int(med))} كلمة")
        print("   رقم | الطول | الجُمل | الإيقاع")
        for i, (para, L) in enumerate(zip(paras, lens), 1):
            sents = sum(1 for x in SENT_SPLIT_RE.split(para) if len(x.split()) >= 4)
            bar = "█" * max(1, round(L / top * args.width))
            tag = ""
            if L <= 0.60 * med:
                tag = "◄ قصيرة حاسمة"
            elif L >= 1.50 * med:
                tag = "◄ مطوّلة"
            print(f"   {n(i):>3} | {n(L):>5} | {n(sents):>4} | {bar} {tag}")

        short = sum(1 for L in lens if L <= 0.60 * med)
        long_ = sum(1 for L in lens if L >= 1.50 * med)
        print(f"\n   قصيرة: {n(short)} | مطوّلة: {n(long_)} | "
              f"المدى: {n(round(top / max(1, min(lens)), 1))}×")
        flat = []
        for i in range(len(lens) - 3):
            chunk = lens[i:i + 4]
            m = statistics.fmean(chunk)
            cv = statistics.pstdev(chunk) / m if m else 0
            if cv < 0.22:
                flat.append((i + 1, cv))
        if flat:
            print("   مواضع الرتابة (نافذة ٤ فقرات):")
            for i, cv in flat:
                print(f"     • الفقرات {n(i)}–{n(i + 3)} (تنوّع {cv:.2f}) — "
                      f"اقترح: اقطع إحداها إلى فقرتين، أو أدخل بعدها حكماً في سطرين")
        else:
            print("   ✔ لا رتابة محلية")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
