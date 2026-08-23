#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بطاقة المشروع — snapshot.py
===========================
يبني صفحةً واحدة مضغوطة تحوي «كل شيء» عن الرسالة: خريطة الفصول وعناوينها،
حالة كل ملف عند الحُرّاس، المدوّنة المرئية، المكتبة، البنوك، المستند الأمّ،
الصفحة الحمراء، القرارات المعتمدة، والخطوة التالية.

الغرض: أن تُقرأ بطاقةٌ واحدة صغيرة في أول كل جلسة بدل قراءة المشروع كله،
فيُعرَف الحال كاملاً بأقلّ التوكنز. تُبنى آلياً بلا أي استهلاك للنموذج.

    python tools/snapshot.py                 # يكتب state/SNAPSHOT.md
    python tools/snapshot.py --stdout        # يطبعها (لاستعمال خطّاف الجلسة)
    python tools/snapshot.py --full          # نسخة موسّعة بكل العناوين
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
SKIP = ("EXCEPTIONS", ".template.", "README", "SNAPSHOT")
SRT_LAST_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.]\d{3}\s*-->")


def n(x) -> str:
    return str(x).translate(AR)


def load_guard():
    spec = importlib.util.spec_from_file_location(
        "guard_check", ROOT / "guards" / "guard_check.py")
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def cfg() -> dict:
    p = ROOT / "thesis.config.json"
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}


def tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()}
                for r in csv.DictReader(fh, delimiter="\t")
                if any((v or "").strip() for v in r.values())]


def draft_files() -> list[Path]:
    seen, out = set(), []
    for base in ("chapters", "outputs/matalib", "drafts"):
        d = ROOT / base
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.md")):
            if p.name.startswith("_") or any(k in p.name for k in SKIP):
                continue
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def outline(text: str, max_items: int, deep: bool):
    items = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("#"):
            continue
        lvl = len(s) - len(s.lstrip("#"))
        if not deep and lvl > 3:
            continue
        items.append((lvl, s.lstrip("#").strip()))
    trimmed = items[:max_items]
    return trimmed, len(items) - len(trimmed)


def srt_duration(path: Path) -> str:
    try:
        stamps = SRT_LAST_RE.findall(path.read_text(encoding="utf-8-sig",
                                                    errors="replace"))
    except OSError:
        return "—"
    if not stamps:
        return "—"
    h, m, s = stamps[-1]
    total = int(h) * 60 + int(m)
    return f"{n(total)}د"


def build(full: bool) -> str:
    c = cfg()
    guard = load_guard()
    L: list[str] = []
    add = L.append

    add("# بطاقة المشروع — كل شيء في صفحة واحدة")
    add("")
    add(f"> بُنيت آلياً: {datetime.now().strftime('%Y-%m-%d %H:%M').translate(AR)}"
        " — لا تُحرَّر يدوياً، تُعاد بناؤها بـ `python tools/snapshot.py`.")
    add("")
    add(f"**الرسالة:** {c.get('thesis_title', '—')}")
    add("")

    # ── ١) خريطة المسودّات ────────────────────────────────
    drafts = draft_files()
    total_words = 0
    add("## ١) خريطة المسودّات")
    add("")
    if not drafts:
        add("- لا مسودّات بعد.")
    for p in drafts:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        words = len(text.split())
        total_words += words
        notes = len(re.findall(r"^\[\^[^\]]+\]:", text, re.M))
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:7]
        status = "—"
        if guard:
            try:
                rep = guard.check_file(p, c)
                cv = rep.stats.get("length_cv", "—")
                status = ("اجتاز ✔" if rep.ok
                          else f"مرفوض ✘ ({n(len(rep.errors))}): {rep.errors[0][:60]}")
                status += f" | تنوّع {cv}"
            except Exception as exc:
                status = f"تعذّر الفحص ({exc.__class__.__name__})"
        add(f"### {p.relative_to(ROOT)}")
        add(f"- {n(words)} كلمة | {n(notes)} هامشاً | بصمة `{digest}` | الحُرّاس: {status}")
        items, rest = outline(text, 40 if full else 14, full)
        for lvl, title in items:
            add(f"{'  ' * (lvl - 1)}- {title}")
        if rest > 0:
            add(f"  - … و{n(rest)} عنواناً آخر (شغّل --full)")
        add("")
    add(f"**مجموع الكلمات في المسودّات: {n(total_words)}**")
    add("")

    # ── ٢) المدوّنة المرئية ───────────────────────────────
    srts = sorted(ROOT.rglob("*.srt"))
    txts = [p for p in sorted((ROOT / "chapters").rglob("*.txt"))] \
        if (ROOT / "chapters").exists() else []
    add("## ٢) المدوّنة المرئية (التفريغات)")
    add("")
    add(f"- ملفات SRT: {n(len(srts))} | ملفات نصّية: {n(len(txts))}")
    show = srts if full else srts[:25]
    for p in show:
        add(f"  - {p.relative_to(ROOT)} — {srt_duration(p)}")
    if len(srts) > len(show):
        add(f"  - … و{n(len(srts) - len(show))} ملفاً آخر")
    add("")

    # ── ٣) المكتبة وسجل المصادر ──────────────────────────
    reg = tsv(ROOT / "source_registry" / "registry.tsv")
    states = Counter(r.get("حالة_النص", "—") for r in reg)
    sides = Counter(r.get("التصنيف", "—") for r in reg)
    complete = [r for r in reg if all(r.get(k) for k in
                                      ("العنوان", "المؤلف", "الدار", "السنة",
                                       "عدد_الصفحات"))]
    queue = ROOT / "source_registry" / "ocr_queue.txt"
    add("## ٣) المكتبة وسجل المصادر")
    add("")
    add(f"- قيود السجل: {n(len(reg))} | مكتملة البيانات: {n(len(complete))}")
    add(f"- حالة النص: " + " | ".join(f"{k}: {n(v)}" for k, v in states.items()))
    add(f"- التصنيف: " + " | ".join(f"{k}: {n(v)}" for k, v in sides.items()))
    if queue.exists():
        pending = len([l for l in queue.read_text(encoding="utf-8").splitlines() if l.strip()])
        add(f"- طابور OCR: {n(pending)} ملفاً")
    for r in (reg if full else reg[:15]):
        add(f"  - `{r.get('id')}` {r.get('العنوان')} — {r.get('المؤلف')} "
            f"({r.get('حالة_النص') or '—'}/{r.get('التصنيف') or '—'})")
    if not full and len(reg) > 15:
        add(f"  - … و{n(len(reg) - 15)} قيداً آخر")
    add("")

    # ── ٤) البنوك ────────────────────────────────────────
    quotes = tsv(ROOT / "evidence_bank" / "quotes.tsv")
    clips = tsv(ROOT / "evidence_bank" / "clips.tsv")
    add("## ٤) بنك الشواهد وبنك المقاطع")
    add("")
    add(f"- شواهد الكتب: {n(len(quotes))} "
        f"({' | '.join(f'{k}: {n(v)}' for k, v in Counter(q.get('التصنيف', '—') for q in quotes).items()) or '—'})")
    add(f"- دعاوى المقاطع: {n(len(clips))} "
        f"({' | '.join(f'{k}: {n(v)}' for k, v in Counter(cl.get('حالة_التحقق', '—') for cl in clips).items()) or '—'})")
    used = Counter(q.get("المطلب", "—") for q in quotes if q.get("المطلب"))
    if used:
        add("- توزّع الشواهد على المطالب: "
            + " | ".join(f"{k}: {n(v)}" for k, v in used.items()))
    add("")

    # ── ٥) المستند الأمّ ─────────────────────────────────
    master = ROOT / c.get("master_docx", "outputs/docx/الرسالة_الكاملة.docx")
    add("## ٥) المستند الأمّ")
    add("")
    if master.exists():
        st = master.stat()
        add(f"- {master.relative_to(ROOT)} — {n(round(st.st_size / 1024))} ك.ب — "
            f"آخر بناء {datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M').translate(AR)}")
    else:
        add("- لم يُبنَ بعد.")
    rep_path = ROOT / "state" / "last_build_report.json"
    if rep_path.exists():
        try:
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            add(f"- آخر بناء ضمّ {n(len(rep.get('chapters', [])))} ملفاً "
                f"و{n(rep.get('footnotes_total', 0))} هامشاً")
        except json.JSONDecodeError:
            pass
    add("")

    # ── ٦) الصفحة الحمراء ───────────────────────────────
    red = ROOT / "state" / "red_page.md"
    add("## ٦) الصفحة الحمراء (ما لم يثبت بعد)")
    add("")
    if red.exists():
        items = [l for l in red.read_text(encoding="utf-8").splitlines()
                 if l.startswith("- [[تحقق]]")]
        add(f"- بنود معلَّقة: {n(len(items))}")
        for it in (items if full else items[:12]):
            add(f"  {it}")
        if not full and len(items) > 12:
            add(f"  - … و{n(len(items) - 12)} بنداً آخر")
    else:
        add("- لم تُبنَ بعد (شغّل `python tools/thesis.py court <files>`).")
    add("")

    # ── ٧) القرارات والخطوة التالية ─────────────────────
    ledger = ROOT / "state" / "ledger.md"
    add("## ٧) القرارات المعتمدة والخطوة التالية")
    add("")
    if ledger.exists():
        txt = ledger.read_text(encoding="utf-8")
        for header in ("## قرارات معتمدة", "## الخطوة التالية"):
            if header in txt:
                chunk = txt.split(header, 1)[1].split("\n## ", 1)[0].strip()
                add(f"**{header.lstrip('# ')}**")
                for line in chunk.splitlines()[:12]:
                    add(line)
                add("")
    else:
        add("- لا لوحة حالة بعد.")

    # ── ٨) الاستثناءات السارية ──────────────────────────
    exc = [p for p in ROOT.rglob("EXCEPTIONS.md")]
    if exc:
        add("## ٨) استثناءات سارية على فصول بعينها")
        add("")
        for p in exc:
            add(f"- {p.relative_to(ROOT)}")
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith("|") and "---" not in line:
                    add(f"  {line}")
        add("")

    add("---")
    add("_انتهت البطاقة. ما ليس فيها يُقرأ من ملفه عند الحاجة فقط._")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="بناء بطاقة المشروع")
    ap.add_argument("--full", action="store_true", help="نسخة موسّعة")
    ap.add_argument("--stdout", action="store_true", help="اطبع بدل الكتابة")
    ap.add_argument("--out", default=str(ROOT / "state" / "SNAPSHOT.md"))
    args = ap.parse_args(argv)

    text = build(args.full)
    if args.stdout:
        sys.stdout.write(text)
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    print(f"  بطاقة المشروع : {out}  ({n(round(size / 1024, 1))} ك.ب، "
          f"~{n(size // 3)} توكنز تقديراً)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
