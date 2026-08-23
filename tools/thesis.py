#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مصنع الرسالة — أمرٌ واحد يقود خطّ الإنتاج كلّه
=============================================
    python tools/thesis.py check  <files>    فحص الحُرّاس فقط
    python tools/thesis.py court  <files>    محكمة الإحالات + بناء الصفحة الحمراء
    python tools/thesis.py build  [--open]   بناء المستند الأمّ من ترتيب الفصول
    python tools/thesis.py ship   <files>    حُرّاس ← محكمة ← بناء ← تقرير ← فتح
    python tools/thesis.py status            لوحة حالة الفصول والمكتبة والبنك
    python tools/thesis.py snapshot          بطاقة المشروع الكاملة في صفحة واحدة
"""
from __future__ import annotations

import csv
import glob
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
CFG = ROOT / "thesis.config.json"


def run(args) -> int:
    return subprocess.run([PY, *[str(a) for a in args]], cwd=str(ROOT)).returncode


def cfg() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8-sig")) if CFG.exists() else {}


def expand(patterns):
    out = []
    for p in patterns:
        hits = sorted(glob.glob(p, recursive=True)) or sorted(
            glob.glob(str(ROOT / p), recursive=True))
        out.extend(h for h in hits if h.endswith(".md"))
    return out or [str(p) for p in sorted((ROOT / "chapters").rglob("*.md"))]


def count_tsv(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return sum(1 for r in csv.DictReader(fh, delimiter="\t")
                   if any((v or "").strip() for v in r.values()))


def cmd_status():
    c = cfg()
    print("══ لوحة حالة الرسالة ══════════════════════")
    skip = ("EXCEPTIONS", ".template.", "README")
    chapters = [p for p in sorted((ROOT / "chapters").rglob("*.md"))
                if not p.name.startswith("_") and not any(k in p.name for k in skip)]
    for p in chapters:
        words = len(p.read_text(encoding="utf-8-sig").split())
        print(f"  • {p.relative_to(ROOT)}  —  {words} كلمة")
    if not chapters:
        print("  (لا مسودّات بعد)")
    print(f"\n  سجل المصادر  : {count_tsv(ROOT / 'source_registry/registry.tsv')} قيداً")
    print(f"  بنك الشواهد  : {count_tsv(ROOT / 'evidence_bank/quotes.tsv')} شاهداً")
    print(f"  بنك المقاطع  : {count_tsv(ROOT / 'evidence_bank/clips.tsv')} دعوى")
    srts = list((ROOT / "chapters").rglob("*.srt"))
    print(f"  التفريغات    : {len(srts)} ملف SRT")
    master = ROOT / c.get("master_docx", "outputs/docx/الرسالة_الكاملة.docx")
    if master.exists():
        stamp = datetime.fromtimestamp(master.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  المستند الأمّ : موجود — آخر بناء {stamp}")
    else:
        print("  المستند الأمّ : لم يُبنَ بعد")
    red = ROOT / "state/red_page.md"
    if red.exists():
        items = sum(1 for l in red.read_text(encoding="utf-8").splitlines()
                    if l.startswith("- [[تحقق]]"))
        print(f"  الصفحة الحمراء: {items} بنداً مُعلَّقاً")
    return 0


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]

    if cmd == "check":
        return run([ROOT / "guards/guard_check.py", *expand(rest)])
    if cmd == "court":
        return run([ROOT / "guards/citation_court.py", *expand(rest)])
    if cmd == "build":
        return run([ROOT / "tools/build_rtl_clean_docx.py", *rest])
    if cmd == "status":
        return cmd_status()
    if cmd == "snapshot":
        return run([ROOT / "tools/snapshot.py", *rest])
    if cmd == "ship":
        files = expand([a for a in rest if not a.startswith("--")])
        print("\n[١/٤] الحُرّاس …")
        if run([ROOT / "guards/guard_check.py", *files]) != 0:
            print("\n✘ رُفض النص عند الحُرّاس — أصلح ثم أعد. لم يُمسّ المستند الأمّ.")
            return 1
        print("\n[٢/٤] محكمة الإحالات …")
        run([ROOT / "guards/citation_court.py", *files])
        print("\n[٣/٤] البناء في المستند الأمّ …")
        rc = run([ROOT / "tools/build_rtl_clean_docx.py",
                  *(["--open"] if "--open" in rest else [])])
        if rc != 0:
            return rc
        print("\n[٤/٤] تقرير التحقّق …")
        run([ROOT / "tools/snapshot.py"])
        return cmd_status()

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
