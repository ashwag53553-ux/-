#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مُطبِّع النصّ المصدر — normalize_text.py
=======================================
يُصلح بصمات الآلة في **مسودّة الماركداون نفسها**، لا في المستند المبنيّ:
  • الشرطة الطويلة (—/–) → علامة عربية مناسبة للسياق
      - شرطتان في فقرة واحدة والمحصور بينهما قصير → قوسان (…)
      - شرطة مفردة بين جملتين → فاصلة عربية «، »
      - شرطة قبل نهاية الفقرة → نقطة
  • الأرقام الغربية → عربية شرقية (خارج الروابط)
  • الإيموجي والرموز المخفية → حذف
لا يمسّ كلمةً واحدة من المعنى: العلامات والأرقام فقط.

    python tools/normalize_text.py <ملف.md>              # عرض فقط (٣ عيّنات)
    python tools/normalize_text.py <ملف.md> --apply      # تطبيق فعليّ
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
HIDDEN_RE = re.compile("[​‌‍⁠﻿­᠎‎‏؜"
                       "‪-‮⁦-⁩͏  ︀-️"
                       "\U000e0000-\U000e007f]")
EMOJI_RE = re.compile("[\U0001f300-\U0001faff←-⇿☀-➿⬀-⯿"
                      "•▪●]")
URL_RE = re.compile(r"(https?://\S+|www\.\S+)")
DASH = "[—–]"


def arabize(text: str) -> str:
    return "".join(p if URL_RE.fullmatch(p or "") else (p or "").translate(AR)
                   for p in URL_RE.split(text))


def fix_dashes(par: str) -> str:
    # زوج شرطتين حول عبارة قصيرة ← قوسان
    def pair(m):
        inner = m.group(1).strip()
        return f" ({inner}) " if len(inner.split()) <= 8 else f"، {inner}، "
    prev = None
    while prev != par:
        prev = par
        par = re.sub(rf"\s{DASH}\s(.+?)\s{DASH}\s", pair, par, count=1)
    # شرطة قبل نهاية الفقرة ← نقطة
    par = re.sub(rf"\s{DASH}\s([^—–]{{1,80}})$", r"، \1", par)
    # شرطة مفردة بين جملتين ← فاصلة عربية
    par = re.sub(rf"\s*{DASH}\s*", "، ", par)
    par = re.sub(r"،\s*،", "،", par)
    par = re.sub(r"،\s*\.", ".", par)
    par = re.sub(r"\s+،", "،", par)
    par = re.sub(r"\s+([.،؛:؟!])", r"\1", par)
    par = re.sub(r"\(\s+", "(", par)
    par = re.sub(r"\s+\)", ")", par)
    par = re.sub(r" {2,}", " ", par)
    return par


def normalize(text: str) -> str:
    out = []
    for line in text.splitlines():
        s = HIDDEN_RE.sub("", line)
        s = EMOJI_RE.sub("", s)
        s = arabize(s)
        s = re.sub(r" {2,}", " ", s)
        if not s.lstrip().startswith(("|", "```")):
            s = fix_dashes(s)
        out.append(s.rstrip())
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="تطبيع مسودّة الماركداون")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--apply", action="store_true", help="اكتب التغيير فعلياً")
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args(argv)

    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"  [!] غير موجود: {p}")
            continue
        before = p.read_text(encoding="utf-8-sig")
        after = normalize(before)
        b_lines, a_lines = before.splitlines(), after.splitlines()
        diffs = [(i + 1, b, a) for i, (b, a) in enumerate(zip(b_lines, a_lines)) if b != a]

        print(f"\n── {p.name}")
        print(f"   أسطر متغيّرة: {len(diffs)} | شرطات قبل: {before.count('—') + before.count('–')}"
              f" → بعد: {after.count('—') + after.count('–')}")
        print(f"   إيموجي: {len(EMOJI_RE.findall(before))} → {len(EMOJI_RE.findall(after))}"
              f" | رموز مخفية: {len(HIDDEN_RE.findall(before))} → {len(HIDDEN_RE.findall(after))}")
        for ln, b, a in diffs[:args.samples]:
            print(f"\n   [سطر {ln}]")
            print(f"   قبل : {b[:160]}")
            print(f"   بعد : {a[:160]}")
        if args.apply:
            p.write_text(after, encoding="utf-8")
            print(f"\n   ✔ طُبّق على {p}")
        else:
            print(f"\n   (عرض فقط — أضف --apply للتطبيق)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
