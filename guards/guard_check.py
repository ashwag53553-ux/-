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
  ح٣ب إفراط الشرطة الطويلة (بصمة أسلوب آلي)          → رفض
  ح٦  اكتمال بيانات الإحالة (ص/طبعة/دار/سنة)         → تحذير مُحصى
  ح٧  المشكوك فيه خارج الصفحة الحمراء                → خطأ
  ح٨  تشكيل زائد عن حدّ رفع اللبس                    → رفض
  ح٩  رتابة مطالع الفقرات (تكرار كلمة الافتتاح)       → رفض
  ح١٠ تساوي أطوال الجُمل داخل الفقرات                 → رفض
  ح١١ إفراط الروابط المنطقية المقولبة                 → رفض
  ح١٢ رتابة الإيقاع محلياً (نافذة أربع فقرات)          → رفض
  ح١٣ غياب الفقرة القصيرة الحاسمة أو المطوّلة          → رفض
  ح١٤ تساوي بنية الفقرات (عدد الجُمل نفسه توالياً)      → رفض

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
from collections import Counter
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
    "قناة", "بودكاست", "الدقيقة",
]
TIMESTAMP_RE = re.compile(r"\d{1,2}:\d{2}(:\d{2})?|[٠-٩]{1,2}:[٠-٩]{2}")

# ح٦: بيانات الإحالة المكتملة
PAGE_RE = re.compile(r"\bص\s*[٠-٩0-9]|\bص\.?\s*[٠-٩0-9]|ج\s*[٠-٩0-9]")
YEAR_RE = re.compile(r"[٠-٩0-9]{3,4}\s*(هـ|م)\b|[٠-٩0-9]{4}")
# إحالات لا تُطلب فيها بيانات النشر: الآيات وتخريج الحديث
QURAN_RE = re.compile(r"سورة|الآية|الآيات|\[[^\]]*:\s*[٠-٩0-9]+\s*\]")
HADITH_RE = re.compile(r"أخرجه|رواه|صحيح البخاري|صحيح مسلم|سنن |مسند |المستدرك|"
                       r"رقم الحديث|حديث رقم|برقم")


# ح٨: التشكيل — تُحصى الحركات عدا الشدّة (فالشدّة كثيراً ما ترفع اللبس)
TASHKEEL_RE = re.compile(r"[\u064b-\u0650\u0652\u0670\u0640]")
QURAN_BRACKETS_RE = re.compile(r"﴿[^﴾]*﴾")
# ح١١: روابط مقولبة يُفرط فيها التوليد الآلي
STOCK_CONNECTORS = ["وبالتالي", "ومن ثمّ", "ومن ثم", "وعليه فإن", "إضافة إلى ذلك",
                    "علاوة على ذلك", "وفي هذا السياق", "وفي الوقت نفسه",
                    "من ناحية أخرى", "وختاماً", "وفي المقابل"]
SENT_SPLIT_RE = re.compile(r"[.؟!]|(?<=[^\d]):")


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
    words_total = max(1, len(text.split()))
    dashes = text.count("—") + text.count("–")
    rate = dashes / words_total * 1000
    rep.stats["dashes"] = dashes
    rep.stats["dash_rate_per_1000"] = round(rate, 2)
    limit = gcfg.get("max_dashes_per_1000_words", 3.0)
    if dashes > 5 and rate > limit:
        rep.err(f"ح٣ب إفراط في الشرطة الطويلة: {dashes} شرطة "
                f"({rate:.1f} لكل ألف كلمة، الحد {limit}) — بصمة آلة. "
                f"بدّلها بعلامة عربية مناسبة للسياق.")

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
        if QURAN_RE.search(body_text) or HADITH_RE.search(body_text):
            continue                      # آية أو تخريج حديث: ليست إحالة مقطع
        low = body_text.lower()
        hit = [m for m in CLIP_MARKERS if m in low or m in body_text]
        if hit or TIMESTAMP_RE.search(body_text):
            rep.err(f"ح٥ الهامش [{key}] يحيل إلى مقطع/حلقة "
                    f"({', '.join(hit) or 'توقيت زمني'}) — انقله إلى المتن مختصراً")

    # ── ح٦ اكتمال بيانات الإحالة ────────────────────────────
    def exempt(v: str) -> bool:
        return bool(QURAN_RE.search(v) or HADITH_RE.search(v))

    incomplete = [k for k, v in notes.items() if not exempt(v) and
                  (not PAGE_RE.search(v) or not YEAR_RE.search(v) or v.count("،") < 3)]
    rep.stats["exempt_citations"] = sum(1 for v in notes.values() if exempt(v))
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

    # ── ح١٢–ح١٤ إيقاع الفقرات (يُقاس محلياً لا على المتوسط) ──
    plens = [len(p.split()) for p in paras if len(p.split()) >= 4]
    if len(plens) >= 6:
        med = statistics.median(plens)
        short = [n for n in plens if n <= 0.60 * med]
        long_ = [n for n in plens if n >= 1.50 * med]
        rep.stats["median_paragraph"] = med
        rep.stats["short_paragraphs"] = len(short)
        rep.stats["long_paragraphs"] = len(long_)
        rep.stats["length_span"] = round(max(plens) / max(1, min(plens)), 2)

        # ح١٢: نافذة متحركة من أربع فقرات
        win = gcfg.get("rhythm_window", 4)
        floor_local = gcfg.get("min_local_cv", 0.22)
        flat = []
        for i in range(len(plens) - win + 1):
            chunk = plens[i:i + win]
            m = statistics.fmean(chunk)
            cv_local = statistics.pstdev(chunk) / m if m else 0
            if cv_local < floor_local:
                flat.append((i + 1, cv_local, chunk))
        if flat:
            spots = "، ".join(f"الفقرات {i}-{i + win - 1} ({c:.2f})"
                              for i, c, _ in flat[:4])
            rep.err(f"ح١٢ إيقاع رتيب في {len(flat)} موضعاً: {spots} — "
                    f"أدخل فقرة قصيرة حاسمة أو ادمج فقرتين")

        # ح١٣: لا بدّ من قصيرة حاسمة ومطوّلة
        need = max(1, int(len(plens) * gcfg.get("min_short_ratio", 0.15)))
        if len(short) < need:
            rep.err(f"ح١٣ الفقرات القصيرة {len(short)} والمطلوب {need} على الأقل "
                    f"(أقصر من {int(0.6 * med)} كلمة) — النصّ يمشي بنفَس واحد")
        if len(long_) < need:
            rep.err(f"ح١٣ الفقرات المطوّلة {len(long_)} والمطلوب {need} على الأقل "
                    f"(أطول من {int(1.5 * med)} كلمة) — لا تفاوت في التنفّس")
        span_floor = gcfg.get("min_length_span", 2.2)
        if rep.stats["length_span"] < span_floor:
            rep.err(f"ح١٣ المدى بين أطول فقرة وأقصرها {rep.stats['length_span']} "
                    f"والمطلوب {span_floor} فأكثر")

        # ح١٤: بنية الفقرة — عدد الجُمل لا يتكرر ثلاثاً متوالية
        counts = []
        for p_text in paras:
            if len(p_text.split()) >= 4:
                counts.append(sum(1 for x in SENT_SPLIT_RE.split(p_text)
                                  if len(x.split()) >= 4))
        run, worst_i = 1, None
        for i in range(1, len(counts)):
            if counts[i] == counts[i - 1] and counts[i] >= 2:
                run += 1
                if run >= 3:
                    worst_i = i - run + 2
            else:
                run = 1
        if worst_i:
            rep.err(f"ح١٤ ثلاث فقرات متتالية أو أكثر بعدد الجُمل نفسه "
                    f"(ابتداءً من الفقرة {worst_i}) — نوّع بنية الفقرة لا طولها فقط")

    # ── ح٨ تشكيل زائد ───────────────────────────────────────
    plain = QURAN_BRACKETS_RE.sub("", "\n".join(
        l for l in body if not l.strip().startswith(">")))
    letters = max(1, len(re.findall(r"[\u0621-\u064a]", plain)))
    marks = len(TASHKEEL_RE.findall(plain))
    rate_t = marks / letters * 1000
    rep.stats["tashkeel_per_1000"] = round(rate_t, 1)
    t_limit = gcfg.get("max_tashkeel_per_1000_letters", 15)
    if marks > 20 and rate_t > t_limit:
        rep.err(f"ح٨ تشكيل زائد: {marks} حركة ({rate_t:.0f} لكل ألف حرف، "
                f"الحد {t_limit}) — اكتفِ بما لولاه لتغيّرت الكلمة. "
                f"(الآيات بين ﴿﴾ والاقتباسات مستثناة)")

    # ── ح٩ رتابة مطالع الفقرات ─────────────────────────────
    openers = [p.split()[0].strip("،.") for p in paras if p.split()]
    rep.stats["paragraph_openers"] = len(set(openers))
    for word, count in Counter(openers).items():
        if count >= 3 and len(word) > 2:
            rep.err(f"ح٩ {count} فقرات تفتتح بـ«{word}» — نوّع المطالع، "
                    f"فتكرار الافتتاح بصمة آلة")

    # ── ح١٠ تساوي أطوال الجُمل ──────────────────────────────
    sent_lens = []
    for p_text in paras:
        for sent in SENT_SPLIT_RE.split(p_text):
            n_w = len(sent.split())
            if n_w >= 4:
                sent_lens.append(n_w)
    if len(sent_lens) >= 8:
        mean_s = statistics.fmean(sent_lens)
        cv_s = statistics.pstdev(sent_lens) / mean_s if mean_s else 0
        rep.stats["sentence_cv"] = round(cv_s, 3)
        s_floor = gcfg.get("min_sentence_length_cv", 0.35)
        if cv_s < s_floor:
            rep.err(f"ح١٠ الجُمل متساوية الطول (معامل {cv_s:.2f} < {s_floor}) — "
                    f"اكسر الإيقاع: جملة قصيرة حاسمة بين المطوّلات")

    # ── ح١١ إفراط الروابط المقولبة ─────────────────────────
    conn = [(c, text.count(c)) for c in STOCK_CONNECTORS if text.count(c)]
    total_conn = sum(c for _, c in conn)
    rep.stats["stock_connectors"] = total_conn
    conn_limit = gcfg.get("max_stock_connectors_per_1000_words", 4)
    if total_conn > 3 and total_conn / words_total * 1000 > conn_limit:
        top = "، ".join(f"«{c}»×{n}" for c, n in sorted(conn, key=lambda x: -x[1])[:4])
        rep.err(f"ح١١ إفراط في الروابط المقولبة ({total_conn}): {top} — "
                f"اربط بالمعنى لا بالحشو")

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
    ap.add_argument("--all", action="store_true",
                    help="افحص كل ملفات md بما فيها السجلات والخرائط")
    args = ap.parse_args(argv)

    cfg = {}
    cfgp = Path(args.config)
    if cfgp.exists():
        cfg = json.loads(cfgp.read_text(encoding="utf-8-sig"))

    SKIP_DIRS = ("state", "project_brief", "prompts", "examples", ".claude",
                 "source_registry", "evidence_bank", "outputs/docx")
    SKIP_NAMES = ("README", "SNAPSHOT", "ledger", "defects", "EXCEPTIONS",
                  ".template.", "_map", "map_", "log")

    def is_draft(path: Path) -> bool:
        rel = str(path).replace("\\", "/")
        if any(f"/{d}/" in f"/{rel}" for d in SKIP_DIRS):
            return False
        if path.name.startswith("_") or any(k in path.name for k in SKIP_NAMES):
            return False
        return True

    paths, skipped = [], []
    for pattern in args.files:
        hits = sorted(glob.glob(pattern, recursive=True))
        for h in hits:
            if not h.endswith(".md"):
                continue
            (paths if (args.all or is_draft(Path(h))) else skipped).append(Path(h))
    if skipped:
        print(f"  [i] تُخُطّي {len(skipped)} ملفاً ليس من مسودّات الرسالة "
              f"(سجلات/خرائط/أمثلة). لفحصها أضف --all")
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
