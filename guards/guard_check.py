#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
الحُرّاس — guard_check.py
========================
فاحص آليّ يرفض أي نص يخالف قواعد CLAUDE.md الستّ قبل أن يدخل المستند الأمّ.
لا يُبنى فصلٌ لم يجتَز الحُرّاس.

  ح١  رموز مخفية / علامات مائية / إيموجي            → صفر إلزاماً
  ح٢  أرقام غربية في سياق عربي                       → صفر إلزاماً
  ح٣  عبارات آلية نمطية (بصمة الآلة)                 → صفر إلزاماً
  ح٤  تساوي أطوال الفقرات (رتابة إيقاعية)            → معامل اختلاف ≥ الحد
  ح٥  هوامش فيها إحالات إلى الحلقات/المقاطع          → صفر إلزاماً
  ح٦  اكتمال بيانات الإحالة (ص/طبعة/دار/سنة)         → تحذير مُحصى
  ح٧  المشكوك فيه خارج الصفحة الحمراء                → خطأ

الاستعمال:
    python guards/guard_check.py chapters/chapter02/*.md
    python guards/guard_check.py --json --config thesis.config.json <files>
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HIDDEN_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069\u034f\u2028\u2029\ufe00-\ufe0f\U000e0000-\U000e007f]")
EMOJI_RE = re.compile("[\\U0001f300-\\U0001faff\\u2190-\\u21ff\\u2600-\\u27bf\\u2b00-\\u2bff\\u2022\\u25aa\\u25cf]")
URL_RE = re.compile(r"(https?://\S+|www\.\S+)")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\]")
ARABIC_RE = re.compile(r"[؀-ۿ]")
LATIN_DIGIT_RE = re.compile(r"[0-9]")
RED_HEADING_RE = re.compile(r"^#{1,4}\s*.*للتحقّ?ق قبل التسليم")
UNVERIFIED_MARK_RE = re.compile(r"\[\[(?:تحقق|تحقّق|verify)\]\]")

# ح٣: بصمات الآلة — عبارات مقولبة لا يكتبها باحث في رسالة علمية
MACHINE_PHRASES = [
    "من الجدير بالذكر", "تجدر الإشارة إلى أنه", "من المهم أن نلاحظ",
    "في الختام يمكن القول", "في عالم اليوم", "لا يخفى على أحد",
    "مما لا شك فيه أن", "بشكل عام يمكن القول", "دعنا نستعرض",
    "في هذا المقال", "كما ذكرنا سابقًا", "كما ذكرنا سابقاً",
    "يفتح الباب أمام آفاق", "نقطة تحول محورية", "في نهاية المطاف يمكن",
    "الخلاصة النهائية", "بناءً على ما سبق يمكن استنتاج",
    "يمثل هذا نقلة نوعية", "بصفتي", "كنموذج لغوي", "لا يسعنا إلا أن",
    "من خلال هذا التحليل الشامل", "إليك", "بالتأكيد!", "بالطبع!",
]

# ح٥: كل ما يدلّ على مقطع/حلقة — ممنوع داخل الهوامش
CLIP_MARKERS = [
    "الحلقة", "حلقة", "المقطع", "مقطع", "يوتيوب", "youtube", "youtu.be",
    "قناة", "بودكاست", "الدقيقة", "د:", "ت:",
]
TIMESTAMP_RE = re.compile(r"\d{1,2}:\d{2}(:\d{2})?|[٠-٩]{1,2}:[٠-٩]{2}")

# ح٦: بيانات الإحالة المكتملة
PAGE_RE = re.compile(r"\bص\s*[٠-٩0-9]|\bص\.?\s*[٠-٩0-9]|ج\s*[٠-٩0-9]")
YEAR_RE = re.compile(r"[٠-٩0-9]{3,4}\s*(هـ|م)\b|[٠-٩0-9]{4}")


class Report:
    def __init__(self, path: Path):
        self.path = path
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.stats: dict = {}

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    @property
    def ok(self):
        return not self.errors


def split_body_and_footnotes(lines):
    body, notes, red_zone = [], {}, False
    red_lines = []
    for line in lines:
        if RED_HEADING_RE.match(line.strip()):
            red_zone = True
        m = FOOTNOTE_DEF_RE.match(line.strip())
        if m:
            notes[m.group(1)] = m.group(2)
        elif red_zone:
            red_lines.append(line)
        else:
            body.append(line)
    return body, notes, red_lines


def paragraphs_of(body_lines):
    paras, buf = [], []
    for line in body_lines:
        s = line.strip()
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        if s.startswith(("#", ">", "|", "-", "*", "<!--")) or re.match(r"^\d+[.)]", s):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(s)
    if buf:
        paras.append(" ".join(buf))
    return paras


def check_file(path: Path, cfg: dict) -> Report:
    rep = Report(path)
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    body, notes, red_lines = split_body_and_footnotes(lines)
    gcfg = cfg.get("guards", {})

    # ── ح١ رموز مخفية وإيموجي ───────────────────────────────
    hidden = HIDDEN_RE.findall(text)
    emoji = EMOJI_RE.findall(text)
    rep.stats["hidden_chars"] = len(hidden)
    rep.stats["emoji"] = len(emoji)
    if hidden:
        codes = sorted({hex(ord(c)) for c in hidden})
        rep.err(f"ح١ رموز مخفية ({len(hidden)}): {', '.join(codes)}")
    if emoji:
        rep.err(f"ح١ إيموجي/رموز زخرفية ({len(emoji)}): {''.join(sorted(set(emoji)))[:20]}")

    # ── ح٢ أرقام غربية في سياق عربي ─────────────────────────
    latin_hits = []
    for i, line in enumerate(lines, 1):
        probe = URL_RE.sub("", line)
        probe = FOOTNOTE_REF_RE.sub("", probe)          # [^1] مفاتيح داخلية
        probe = re.sub(r"^\[\^[^\]]+\]:", "", probe.strip())
        if ARABIC_RE.search(probe) and LATIN_DIGIT_RE.search(probe):
            latin_hits.append((i, LATIN_DIGIT_RE.findall(probe), line.strip()[:70]))
    rep.stats["latin_digits_lines"] = len(latin_hits)
    for ln, digits, preview in latin_hits[:12]:
        rep.err(f"ح٢ أرقام غربية (سطر {ln}): {''.join(digits)} — «{preview}»")
    if len(latin_hits) > 12:
        rep.err(f"ح٢ ... و{len(latin_hits) - 12} سطراً آخر فيه أرقام غربية")

    # ── ح٣ بصمات الآلة ──────────────────────────────────────
    found = [(p, text.count(p)) for p in MACHINE_PHRASES if p in text]
    rep.stats["machine_phrases"] = sum(c for _, c in found)
    for phrase, count in found:
        rep.err(f"ح٣ عبارة آلية نمطية ×{count}: «{phrase}»")
    dashes = text.count("—")
    if dashes > max(6, len(paragraphs_of(body)) // 2):
        rep.warn(f"ح٣ إفراط في الشرطة الطويلة (—) ×{dashes} — أسلوب آلي محتمل")

    # ── ح٤ رتابة أطوال الفقرات ──────────────────────────────
    paras = paragraphs_of(body)
    lengths = [len(p.split()) for p in paras if len(p.split()) >= 12]
    rep.stats["paragraphs"] = len(paras)
    rep.stats["para_words"] = lengths
    if len(lengths) >= 4:
        mean = statistics.fmean(lengths)
        cv = statistics.pstdev(lengths) / mean if mean else 0
        rep.stats["length_cv"] = round(cv, 3)
        floor = gcfg.get("min_paragraph_length_cv", 0.30)
        if cv < floor:
            rep.err(f"ح٤ أطوال الفقرات متساوية (معامل الاختلاف {cv:.2f} < {floor}) "
                    f"— نوّع: فقرة قصيرة حاسمة بعد فقرتين مطوّلتين")
        tol = gcfg.get("similar_tolerance", 0.12)
        run, worst = 1, 1
        for a, b in zip(lengths, lengths[1:]):
            if abs(a - b) <= tol * max(a, b):
                run += 1
                worst = max(worst, run)
            else:
                run = 1
        rep.stats["max_similar_run"] = worst
        limit = gcfg.get("max_similar_consecutive_paragraphs", 2)
        if worst > limit:
            rep.err(f"ح٤ {worst} فقرات متتالية متقاربة الطول (الحد {limit})")

    # ── ح٥ الهوامش للكتب فقط ────────────────────────────────
    rep.stats["footnotes"] = len(notes)
    for key, body_text in notes.items():
        low = body_text.lower()
        hit = [m for m in CLIP_MARKERS if m in low or m in body_text]
        if hit or TIMESTAMP_RE.search(body_text):
            rep.err(f"ح٥ الهامش [{key}] يحيل إلى مقطع/حلقة "
                    f"({', '.join(hit) or 'توقيت زمني'}) — انقله إلى المتن مختصراً")

    # ── ح٦ اكتمال بيانات الإحالة ────────────────────────────
    incomplete = [k for k, v in notes.items()
                  if not PAGE_RE.search(v) or not YEAR_RE.search(v) or v.count("،") < 3]
    rep.stats["incomplete_citations"] = len(incomplete)
    if incomplete:
        rep.warn("ح٦ هوامش ناقصة البيانات (مؤلف/كتاب/طبعة/دار/سنة/صفحة): "
                 + "، ".join(f"[{k}]" for k in incomplete[:10]))

    # ── ح٧ المشكوك فيه خارج الصفحة الحمراء ──────────────────
    red_text = "\n".join(red_lines)
    marks_all = UNVERIFIED_MARK_RE.findall(text)
    marks_red = UNVERIFIED_MARK_RE.findall(red_text)
    rep.stats["unverified_marks"] = len(marks_all)
    if len(marks_all) > len(marks_red):
        rep.err(f"ح٧ {len(marks_all) - len(marks_red)} موضعاً مشكوكاً فيه [[تحقق]] "
                f"خارج «صفحة التحقّق الحمراء» — انقله إليها أو احذفه")
    rep.stats["has_red_page"] = bool(red_lines)

    # ── إحصاء مساند: الحواشي المعرّفة مقابل المستدعاة ───────
    refs = set(FOOTNOTE_REF_RE.findall("\n".join(body)))
    defined = set(notes)
    if refs - defined:
        rep.err("هوامش مستدعاة بلا تعريف: " + "، ".join(sorted(refs - defined)))
    if defined - refs:
        rep.warn("هوامش معرّفة بلا استدعاء في المتن: "
                 + "، ".join(sorted(defined - refs)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="الحُرّاس: فحص المسودّات قبل البناء")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--config", default=str(ROOT / "thesis.config.json"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn-only", action="store_true", help="لا تُفشل البناء")
    args = ap.parse_args(argv)

    cfg = {}
    cfgp = Path(args.config)
    if cfgp.exists():
        cfg = json.loads(cfgp.read_text(encoding="utf-8-sig"))

    paths = []
    for pattern in args.files:
        hits = sorted(glob.glob(pattern, recursive=True))
        paths.extend(Path(h) for h in hits if h.endswith(".md"))
    if not paths:
        sys.exit("[!] لا ملفات md مطابقة")

    reports = [check_file(p, cfg) for p in paths]

    if args.json:
        print(json.dumps([{"file": str(r.path), "ok": r.ok, "errors": r.errors,
                           "warnings": r.warnings, "stats": r.stats}
                          for r in reports], ensure_ascii=False, indent=2))
    else:
        for r in reports:
            state = "اجتاز ✔" if r.ok else "مرفوض ✘"
            print(f"\n── {r.path.name} — {state}")
            print(f"   فقرات: {r.stats.get('paragraphs', 0)} | "
                  f"حواشٍ: {r.stats.get('footnotes', 0)} | "
                  f"تنوّع الأطوال: {r.stats.get('length_cv', '—')} | "
                  f"رموز مخفية: {r.stats.get('hidden_chars', 0)}")
            for e in r.errors:
                print(f"   ✘ {e}")
            for w in r.warnings:
                print(f"   ⚠ {w}")
        failed = [r for r in reports if not r.ok]
        print(f"\n══ النتيجة: {len(reports) - len(failed)}/{len(reports)} اجتاز الحُرّاس")

    if any(not r.ok for r in reports) and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
