#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حارس المستند المبنيّ — docx_verify.py
=====================================
لا يكفي أن ينجح أمر البناء: يُفتح الملف الناتج ويُفحص من داخله. هذا الحارس
يمنع عودة كل عطب سبق أن ظهر في المستند نفسه:

  و١  ربط الخط الفاصل في settings.xml (بغيره يرسم وورد فاصله المدمج يساراً)
  و٢  فقرة الفاصل وفاصل المتابعة: bidi + محاذاة يمين
  و٣  الافتراض الأصلي للمستند: docDefaults فيه bidi ومحاذاة يمين
  و٤  المقطع: bidi + rtlGutter + موضع الحواشي أسفل الصفحة
  و٥  إعادة ترقيم الحواشي في كل صفحة (numRestart=eachPage)
  و٦  علامات الحواشي: أرقام عربية شرقية في وضع العلامات المخصّصة
  و٧  صفر أرقام غربية في نصّ المتن والحواشي
  و٨  صفر رموز مخفية، وصفر آثار قوالب (customXml/thumbnail)
  و٩  بيانات وورد نظيفة (المؤلف/آخر تعديل فارغان)

    python guards/docx_verify.py outputs/docx/الرسالة_الكاملة.docx
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
HIDDEN_RE = re.compile("[​‌‍⁠﻿­‎‏؜"
                       "‪-‮⁦-⁩]")
LATIN_DIGIT_RE = re.compile(r"[0-9]")
AR_DIGIT_RE = re.compile(r"[٠-٩]")


def load_cfg() -> dict:
    import json
    c = ROOT / "thesis.config.json"
    return json.loads(c.read_text(encoding="utf-8-sig")) if c.exists() else {}


def verify(path: Path) -> list[str]:
    cfg = load_cfg()
    want_restart = cfg.get("footnote_restart", "continuous")
    want_custom = cfg.get("footnote_numbering", "custom") == "custom"
    errs: list[str] = []
    z = zipfile.ZipFile(path)
    names = z.namelist()

    def read(n):
        return z.read(n).decode("utf-8") if n in names else ""

    settings = read("word/settings.xml")
    styles = read("word/styles.xml")
    document = read("word/document.xml")
    footnotes = read("word/footnotes.xml")
    core = read("docProps/core.xml")

    # و١ ربط الفاصل
    fp = re.search(r"<w:footnotePr>.*?</w:footnotePr>", settings, re.S)
    if not fp:
        errs.append("و١ لا يوجد <w:footnotePr> في settings.xml — وورد سيرسم فاصله "
                    "المدمج (يبدأ من اليسار)")
    else:
        block = fp.group(0)
        if 'w:id="-1"' not in block or 'w:id="0"' not in block:
            errs.append("و١ الفاصل غير مربوط: ينقص <w:footnote w:id=\"-1\"/> "
                        "أو <w:footnote w:id=\"0\"/> — الفاصل سيظهر يساراً")
        # و٥ إعادة الترقيم
        m = re.search(r'<w:numRestart w:val="([^"]+)"', block)
        if not m:
            errs.append("و٥ لا إعداد لترقيم الحواشي — أضف numRestart")
        elif m.group(1) != want_restart:
            errs.append(f"و٥ ترقيم الحواشي في المستند «{m.group(1)}» "
                        f"ولا يطابق الإعدادات «{want_restart}»")

    # و٢ فقرتا الفاصل
    if not footnotes:
        errs.append("و٢ لا ملف حواشٍ في المستند")
    else:
        for kind in ("separator", "continuationSeparator"):
            m = re.search(rf'<w:footnote w:type="{kind}"[^>]*>(.*?)</w:footnote>',
                          footnotes, re.S)
            if not m:
                errs.append(f"و٢ فقرة «{kind}» غير معرَّفة")
                continue
            body = m.group(1)
            if "<w:separator/>" in body or "<w:continuationSeparator/>" in body:
                errs.append(f"و٢ فقرة «{kind}» تستعمل محرف الفاصل المدمج — "
                            f"رسمٌ ثابت يقع يسار الصفحة مهما ضُبط الاتجاه. "
                            f"استبدله بحدّ سفليّ مع إزاحة طرف")
            if "<w:pBdr>" not in body or "w:bottom" not in body:
                errs.append(f"و٢ فقرة «{kind}» بلا حدّ سفليّ — لا خطّ فاصل")
            if not re.search(r'<w:ind[^>]*w:(end|right)="[1-9]', body):
                errs.append(f"و٢ فقرة «{kind}» بلا إزاحة طرف — "
                            f"الخطّ سيمتدّ من اليسار")
            if "<w:bidi/>" not in body:
                errs.append(f"و٢ فقرة «{kind}» بلا bidi")
            if 'w:jc w:val="right"' not in body:
                errs.append(f"و٢ فقرة «{kind}» بلا محاذاة يمين")

    # و٣ الافتراض الأصلي
    dd = re.search(r"<w:pPrDefault>.*?</w:pPrDefault>", styles, re.S)
    if not dd or "<w:bidi/>" not in dd.group(0):
        errs.append("و٣ docDefaults/pPrDefault بلا bidi — فقرات وورد الداخلية LTR")
    elif 'w:jc w:val="right"' not in dd.group(0):
        errs.append("و٣ docDefaults/pPrDefault بلا محاذاة يمين")

    # و٤ المقطع
    sect = re.search(r"<w:sectPr[^>]*>.*?</w:sectPr>", document, re.S)
    if not sect:
        errs.append("و٤ لا إعدادات مقطع")
    else:
        block = sect.group(0)
        for tag, msg in (("<w:bidi/>", "bidi"), ("<w:rtlGutter/>", "rtlGutter")):
            if tag not in block:
                errs.append(f"و٤ المقطع بلا {msg}")
        if 'w:pos w:val="pageBottom"' not in block:
            errs.append("و٤ موضع الحواشي غير مثبت أسفل الصفحة")

    # و٦ علامات الحواشي
    refs = re.findall(r"<w:footnoteReference[^>]*/>", document)
    custom = [r for r in refs if "customMarkFollows" in r]
    if refs and custom and len(custom) != len(refs):
        errs.append(f"و٦ خلط في نمط الترقيم: {len(custom)} مخصّصة من {len(refs)}")

    # و٦ب تناقض: علامات مخصّصة مع طلب إعادة الترقيم كل صفحة
    if want_custom and 'w:numRestart w:val="eachPage"' in settings:
        errs.append("و٦ب تناقض: العلامات مخصّصة (يرقّمها المحرّك تسلسلياً) "
                    "بينما الإعداد يطلب إعادة الترقيم كل صفحة — "
                    "إمّا نمط تلقائي، وإمّا ترقيم متصل")

    # و٧ أرقام غربية في النصّ
    for label, xml in (("المتن", document), ("الحواشي", footnotes)):
        bad = [t for t in TEXT_RE.findall(xml)
               if LATIN_DIGIT_RE.search(t) and re.search(r"[؀-ۿ]", t)]
        if bad:
            errs.append(f"و٧ أرقام غربية في {label} ({len(bad)}): "
                        f"«{bad[0][:60]}»")

    # و٨ رموز مخفية وآثار قوالب
    for label, xml in (("المتن", document), ("الحواشي", footnotes)):
        hidden = [c for t in TEXT_RE.findall(xml) for c in HIDDEN_RE.findall(t)]
        if hidden:
            errs.append(f"و٨ رموز مخفية في {label}: {len(hidden)}")
    leftovers = [n for n in names if "customXml" in n or "thumbnail" in n]
    if leftovers:
        errs.append(f"و٨ آثار قوالب باقية: {', '.join(leftovers[:3])}")

    # و٩ بيانات وورد
    for tag, label in (("creator", "المؤلف"), ("lastModifiedBy", "آخر تعديل")):
        m = re.search(rf"<[^>]*{tag}[^>]*>([^<]+)<", core)
        if m and m.group(1).strip():
            errs.append(f"و٩ بيانات كاشفة: {label} = «{m.group(1).strip()}»")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description="فحص المستند المبنيّ من داخله")
    ap.add_argument("docx", nargs="?",
                    default=str(ROOT / "outputs/docx/الرسالة_الكاملة.docx"))
    args = ap.parse_args(argv)
    path = Path(args.docx)
    if not path.exists():
        print(f"[!] لا يوجد ملف: {path}")
        return 1
    errs = verify(path)
    print("── حارس المستند المبنيّ ─────────────────────")
    print(f"  الملف : {path.name}")
    if not errs:
        cfg = load_cfg()
        mode = ("علامات مخصّصة بترقيم متصل"
                if cfg.get("footnote_numbering", "custom") == "custom"
                else f"ترقيم تلقائي ({cfg.get('footnote_restart')})")
        print(f"  ✔ اجتاز: الفاصل مربوط ويمينيّ | {mode} | "
              f"أرقام عربية | لا رموز مخفية ولا آثار قوالب")
        return 0
    for e in errs:
        print(f"   ✘ {e}")
    print(f"\n  ✘ رُفض المستند: {len(errs)} مخالفة — أصلح الباني ثم أعد البناء")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
