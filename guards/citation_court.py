#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محكمة الإحالات — citation_court.py
==================================
لا هامشَ بلا قيدٍ حقيقي، ولا دعوى مقطعٍ بلا لحظةٍ حقيقية في ملف التفريغ.

تفحص المحكمة ثلاث دعاوى:
  د١  كل هامش في المسودّة ← قيد مطابق في source_registry/registry.tsv
      (وتتحقّق أن رقم الصفحة داخل حدود صفحات الكتاب المسجَّلة)
  د٢  كل شاهد في evidence_bank/quotes.tsv ← مصدر مسجَّل + صفحة
  د٣  كل دعوى مقطع في evidence_bank/clips.tsv ← ملف SRT موجود + توقيت
      موجود فعلاً في الملف + تطابق لفظي مع نص التفريغ عند ذلك التوقيت

الحكم: ما لم يثبت ← يُساق إلى «صفحة التحقّق الحمراء» ولا يدخل النسخة النهائية.

    python guards/citation_court.py chapters/chapter02/*.md
    python guards/citation_court.py --red-page state/red_page.md <files>
"""
from __future__ import annotations

import argparse
import csv
import glob
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "source_registry" / "registry.tsv"
QUOTES = ROOT / "evidence_bank" / "quotes.tsv"
CLIPS = ROOT / "evidence_bank" / "clips.tsv"

FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
PAGE_RE = re.compile(r"ص\.?\s*([٠-٩0-9]+)")
DIACRITICS = re.compile(r"[ً-ْٰـ]")
AR2LAT = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
SRT_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
                         r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def norm(text: str) -> str:
    """تطبيع عربي: حذف التشكيل، توحيد الهمزات والتاء، حذف أل، ضغط المسافات."""
    t = DIACRITICS.sub("", text or "")
    t = (t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
           .replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي"))
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\bال(?=\w)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def to_int(num: str) -> int | None:
    try:
        return int(str(num).translate(AR2LAT))
    except (TypeError, ValueError):
        return None


def load_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh, delimiter="\t")
                if any((v or "").strip() for v in r.values())]
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def srt_timestamps(path: Path) -> list[tuple[int, str]]:
    """يعيد [(ثانية_البداية، النص)] من ملف SRT."""
    out = []
    if not path.exists():
        return out
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig", errors="replace"))
    for block in blocks:
        m = SRT_TIME_RE.search(block)
        if not m:
            continue
        start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        text = " ".join(line for line in block.splitlines()
                        if not SRT_TIME_RE.search(line) and not line.strip().isdigit())
        out.append((start, text.strip()))
    return out


def parse_hhmmss(stamp: str) -> int | None:
    stamp = stamp.translate(AR2LAT).strip()
    parts = stamp.split(":")
    if not all(p.isdigit() for p in parts) or not 2 <= len(parts) <= 3:
        return None
    parts = [int(p) for p in parts]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else \
        parts[0] * 3600 + parts[1] * 60 + parts[2]


class Verdict:
    def __init__(self):
        self.proved: list[str] = []
        self.rejected: list[str] = []          # يُساق إلى الصفحة الحمراء
        self.notes: list[str] = []

    @property
    def ok(self):
        return not self.rejected


def try_footnotes(files, registry, v: Verdict):
    index = [(norm(r.get("العنوان", "")), r) for r in registry if r.get("العنوان")]
    for path in files:
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            m = FOOTNOTE_DEF_RE.match(line.strip())
            if not m:
                continue
            key, body = m.group(1), m.group(2)
            nbody = norm(body)
            hit = next((r for title, r in index if title and title in nbody), None)
            loc = f"{Path(path).name}[^{key}]"
            if not hit:
                v.rejected.append(f"د١ هامش بلا قيد في السجل: {loc} — «{body[:70]}»")
                continue
            page = PAGE_RE.search(body)
            if not page:
                v.rejected.append(f"د١ هامش بلا رقم صفحة: {loc} — «{body[:70]}»")
                continue
            pnum, maxp = to_int(page.group(1)), to_int(hit.get("عدد_الصفحات", ""))
            if maxp and pnum and pnum > maxp:
                v.rejected.append(
                    f"د١ صفحة خارج حدود الكتاب: {loc} ص{pnum} > {maxp} "
                    f"({hit.get('العنوان')})")
                continue
            if hit.get("حالة_النص") == "ممسوح":
                v.notes.append(f"د١ {loc} من كتاب ممسوح بلا OCR — الصفحة تحتاج تأكيداً بصرياً")
            v.proved.append(f"د١ {loc} ← {hit.get('العنوان')} ص{pnum}")


def try_quotes(registry, v: Verdict):
    ids = {r.get("id") for r in registry}
    for q in load_tsv(QUOTES):
        qid = q.get("quote_id", "?")
        if q.get("source_id") not in ids:
            v.rejected.append(f"د٢ شاهد بمصدر غير مسجَّل: {qid} ← {q.get('source_id')}")
        elif not to_int(q.get("الصفحة", "")):
            v.rejected.append(f"د٢ شاهد بلا رقم صفحة: {qid}")
        elif len(q.get("النص", "")) < 15:
            v.rejected.append(f"د٢ شاهد بنصٍّ ناقص أو فارغ: {qid}")
        else:
            v.proved.append(f"د٢ {qid} ← {q.get('source_id')} ص{q.get('الصفحة')}")


def try_clips(v: Verdict, tolerance=45):
    for c in load_tsv(CLIPS):
        cid = c.get("clip_id", "?")
        srt = c.get("ملف_التفريغ", "")
        path = Path(srt) if Path(srt).is_absolute() else ROOT / srt
        if not srt or not path.exists():
            v.rejected.append(f"د٣ دعوى بلا ملف تفريغ موجود: {cid} ← {srt or '—'}")
            continue
        target = parse_hhmmss(c.get("التوقيت", ""))
        if target is None:
            v.rejected.append(f"د٣ توقيت غير صالح: {cid} ← «{c.get('التوقيت')}»")
            continue
        cues = srt_timestamps(path)
        if not cues:
            v.rejected.append(f"د٣ ملف تفريغ لا يُقرأ: {cid} ← {srt}")
            continue
        window = [t for s, t in cues if abs(s - target) <= tolerance]
        if not window:
            last = max(s for s, _ in cues)
            v.rejected.append(f"د٣ التوقيت خارج مدة المقطع: {cid} "
                              f"({c.get('التوقيت')} > {last // 60}:{last % 60:02d})")
            continue
        claim = norm(c.get("نص_الدعوى", ""))
        haystack = norm(" ".join(window))
        words = [w for w in claim.split() if len(w) > 3]
        overlap = sum(1 for w in words if w in haystack) / len(words) if words else 0
        if overlap < 0.5:
            v.rejected.append(f"د٣ نص الدعوى لا يطابق التفريغ عند {c.get('التوقيت')}: "
                              f"{cid} (تطابق {overlap:.0%})")
        else:
            v.proved.append(f"د٣ {cid} ← {Path(srt).name} @{c.get('التوقيت')} "
                            f"(تطابق {overlap:.0%})")


def write_red_page(path: Path, v: Verdict):
    lines = ["## للتحقّق قبل التسليم — تُحذف من النسخة النهائية", "",
             "> هذه الصفحة تحوي كل ما لم تثبته محكمة الإحالات. "
             "لا يُسلَّم البحث وفيها بند واحد.", ""]
    for item in v.rejected:
        lines.append(f"- [[تحقق]] {item}")
    if v.notes:
        lines += ["", "### تنبيهات (لا ترفض البناء)", ""]
        lines += [f"- {n}" for n in v.notes]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="محكمة الإحالات")
    ap.add_argument("files", nargs="*", help="مسودّات md لفحص هوامشها")
    ap.add_argument("--red-page", default=str(ROOT / "state" / "red_page.md"))
    ap.add_argument("--strict", action="store_true", help="أفشِل عند أي بند مرفوض")
    args = ap.parse_args(argv)

    paths = []
    for pattern in args.files:
        paths.extend(p for p in sorted(glob.glob(pattern, recursive=True))
                     if p.endswith(".md"))

    registry = load_tsv(REGISTRY)
    v = Verdict()
    if not registry:
        v.notes.append("سجل المصادر فارغ — املأ source_registry/registry.tsv أولاً")
    try_footnotes(paths, registry, v)
    try_quotes(registry, v)
    try_clips(v)

    print("── حكم محكمة الإحالات ──────────────────────")
    print(f"  قيود السجل      : {len(registry)}")
    print(f"  ثبت             : {len(v.proved)}")
    print(f"  رُدَّ (الصفحة الحمراء): {len(v.rejected)}")
    for item in v.rejected[:25]:
        print(f"   ✘ {item}")
    if len(v.rejected) > 25:
        print(f"   ... و{len(v.rejected) - 25} بنداً آخر (انظر الصفحة الحمراء)")
    for n in v.notes[:10]:
        print(f"   ⚠ {n}")

    write_red_page(Path(args.red_page), v)
    print(f"  الصفحة الحمراء  : {args.red_page}")
    return 1 if (v.rejected and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
