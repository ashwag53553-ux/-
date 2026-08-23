#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حارس النطاق — scope_check.py
============================
يمنع كل عمل خارج ما أُمر به. يقارن ما تغيّر فعلاً في المجلد (git) بقائمة
المسموح، فيرفض:
  ن١  تعديل ملف خارج نطاق المهمة المعلن
  ن٢  حذف أي ملف متتبَّع (الحذف ممنوع مطلقاً)
  ن٣  المساس بالحُرّاس أو الإعدادات (guards/ ، thesis.config.json ، CLAUDE.md)
  ن٤  إنشاء ملف وورد ثانٍ خارج المستند الأمّ

    python guards/scope_check.py --allow "chapters/chapter02/**" "state/**"
    python guards/scope_check.py --allow "chapters/**" --permit-config
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ("guards/", "thesis.config.json", "CLAUDE.md",
             "prompts/_SAFE_HEADER.md", ".claude/settings.json")
ALWAYS_OK = ("state/", "evidence_bank/", "source_registry/", ".gitignore")


def changed() -> list[tuple[str, str]]:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                         capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        code, path = line[:2].strip(), line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ")[-1]
        rows.append((code, path))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="حارس النطاق")
    ap.add_argument("--allow", nargs="*", default=[],
                    help="أنماط الملفات المسموح تغييرها في هذه المهمة")
    ap.add_argument("--permit-config", action="store_true",
                    help="اسمح بتعديل الإعدادات/الدستور (بإذن صريح فقط)")
    args = ap.parse_args(argv)

    allow = list(args.allow) + list(ALWAYS_OK)
    errors, ok = [], []
    for code, path in changed():
        if "D" in code:
            errors.append(f"ن٢ حذف ملف — ممنوع مطلقاً: {path}")
            continue
        if any(path.startswith(p) or path == p for p in PROTECTED):
            if args.permit_config:
                ok.append(f"(بإذن) {path}")
            else:
                errors.append(f"ن٣ مساس بملف محميّ: {path}")
            continue
        if path.endswith(".docx") and "الرسالة_الكاملة" not in path \
                and "_archive" not in path:
            errors.append(f"ن٤ ملف وورد ثانٍ: {path}")
            continue
        if allow and not any(fnmatch.fnmatch(path, pat) or path.startswith(pat.rstrip("*"))
                             for pat in allow):
            errors.append(f"ن١ خارج نطاق المهمة: {path}")
            continue
        ok.append(path)

    print("── حارس النطاق ─────────────────────────────")
    print(f"  داخل النطاق : {len(ok)}")
    for e in errors:
        print(f"   ✘ {e}")
    if errors:
        print("\n  ✘ رُفض: أعد الملفات الخارجة عن النطاق كما كانت "
              "(git checkout -- <الملف>) ثم استأذن قبل توسيع النطاق.")
        return 1
    print("  ✔ لم يخرج العمل عن نطاق المهمة")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
