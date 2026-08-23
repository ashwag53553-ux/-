#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محرّك البناء الوحيد للرسالة  |  build_rtl_clean_docx.py
=======================================================
مهمّته: تحويل مسودّات Markdown إلى المستند الأمّ الواحد (docx) بمواصفات:
  ١) RTL كامل: المقطع، الفقرة، الجدول، الهامش، الخط الفاصل، والتشغيلات (runs).
  ٢) أرقام عربية شرقية ٠-٩ في كل السياق العربي، ومنها أرقام الحواشي.
     (طبقة مستقلة عن الاتجاه: الأرقام تُحوَّل نصياً + علامات الحواشي مخصّصة
      customMark لا تلقائية، لأن ترقيم Word التلقائي يتبع إعداد الجهاز لا المستند.)
  ٣) صفر رموز مخفية / علامات مائية / آثار قوالب، وتنظيف بيانات الوورد.
  ٤) مستند أمّ واحد لا نسخ متعدّدة.

الاستعمال:
    python tools/build_rtl_clean_docx.py --config thesis.config.json
    python tools/build_rtl_clean_docx.py --only chapters/chapter02/*.md --open
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
except ImportError:  # pragma: no cover
    sys.exit("[!] ينقص python-docx.  ثبّته:  pip install python-docx")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

# ----------------------------------------------------------------------------
# طبقة الأرقام والتنظيف
# ----------------------------------------------------------------------------
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_LATIN_TO_AR = str.maketrans("0123456789", AR_DIGITS)
_AR_TO_LATIN = str.maketrans(AR_DIGITS, "0123456789")

# رموز مخفية/علامات مائية محتملة: تُمحى محواً تاماً
HIDDEN_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069\u034f\u2028\u2029\ufe00-\ufe0f\U000e0000-\U000e007f]")
EMOJI_RE = re.compile("[\\U0001f300-\\U0001faff\\u2190-\\u21ff\\u2600-\\u27bf\\u2b00-\\u2bff\\u2022\\u25aa\\u25cf]")
URL_RE = re.compile(r"(https?://\S+|www\.\S+)")


def scrub(text: str) -> str:
    """يمحو الرموز المخفية والإيموجي ويوحّد المسافات دون المساس بالمعنى."""
    text = HIDDEN_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    text = text.replace(" ", " ").replace("\t", " ")
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def arabize_digits(text: str) -> str:
    """يحوّل الأرقام إلى عربية شرقية، ويستثني الروابط ورموز الملفات."""
    parts = URL_RE.split(text)
    return "".join(p if URL_RE.fullmatch(p or "") else (p or "").translate(_LATIN_TO_AR)
                   for p in parts)


def latinize_digits(text: str) -> str:
    return text.translate(_AR_TO_LATIN)


# ----------------------------------------------------------------------------
# محلّل Markdown (مجموعة فرعية مضبوطة لخدمة الرسالة)
# ----------------------------------------------------------------------------
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\]")
INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|\[\^[^\]]+\])")
PAGEBREAK_TOKENS = ("<<<pagebreak>>>", "\\pagebreak", "---pagebreak---")
RED_SECTION_HINTS = ("للتحقّق قبل التسليم", "للتحقق قبل التسليم")


@dataclass
class Block:
    kind: str                      # h1..h4 | p | quote | li | table | pagebreak
    text: str = ""
    rows: list = field(default_factory=list)
    red: bool = False


@dataclass
class Chapter:
    path: Path
    blocks: list = field(default_factory=list)
    footnotes: dict = field(default_factory=dict)   # key -> نص الهامش
    order: list = field(default_factory=list)       # ترتيب ظهور المفاتيح


def parse_markdown(path: Path) -> Chapter:
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    ch = Chapter(path=path)
    buf: list[str] = []
    red = False
    i = 0

    def flush(kind="p"):
        nonlocal buf
        if buf:
            ch.blocks.append(Block(kind, " ".join(buf).strip(), red=red))
            buf = []

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        # تعريفات الحواشي (قد تمتد على أسطر تالية بمسافة بادئة)
        m = FOOTNOTE_DEF_RE.match(stripped)
        if m:
            flush()
            key, body = m.group(1).strip(), m.group(2).strip()
            i += 1
            while i < len(lines) and lines[i].startswith(("    ", "\t")) and lines[i].strip():
                body += " " + lines[i].strip()
                i += 1
            ch.footnotes[key] = body
            continue

        if not stripped:
            flush()
            i += 1
            continue

        if stripped in PAGEBREAK_TOKENS:
            flush()
            ch.blocks.append(Block("pagebreak"))
            i += 1
            continue

        if stripped.startswith("<!--"):          # تعليقات المسودة لا تُبنى
            flush()
            i += 1
            continue

        if stripped.startswith("#"):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            red = any(h in title for h in RED_SECTION_HINTS) or (red and level > 1)
            if any(h in title for h in RED_SECTION_HINTS):
                red = True
            ch.blocks.append(Block(f"h{min(level, 4)}", title, red=red))
            i += 1
            continue

        if stripped.startswith(">"):
            flush()
            quote = [stripped.lstrip("> ").strip()]
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip("> ").strip())
                i += 1
            ch.blocks.append(Block("quote", " ".join(quote).strip(), red=red))
            continue

        if re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+[.)]\s+", stripped):
            flush()
            item = re.sub(r"^([-*+]|\d+[.)])\s+", "", stripped)
            ch.blocks.append(Block("li", item, red=red))
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            ch.blocks.append(Block("table", rows=rows, red=red))
            continue

        buf.append(stripped)
        i += 1

    flush()

    # ترتيب ظهور الحواشي في المتن
    for b in ch.blocks:
        for key in FOOTNOTE_REF_RE.findall(b.text or ""):
            if key not in ch.order:
                ch.order.append(key)
    return ch


# ----------------------------------------------------------------------------
# طبقة OOXML: RTL + الحواشي المخصّصة
# ----------------------------------------------------------------------------
FOOTNOTES_CT = ("application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.footnotes+xml")
FOOTNOTES_RT = ("http://schemas.openxmlformats.org/officeDocument"
                "/2006/relationships/footnotes")
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

FOOTNOTES_SKELETON = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="{W_NS}">
  <w:footnote w:type="separator" w:id="-1">
    <w:p><w:pPr><w:bidi/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
      <w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:rtl/></w:rPr><w:separator/></w:r></w:p>
  </w:footnote>
  <w:footnote w:type="continuationSeparator" w:id="0">
    <w:p><w:pPr><w:bidi/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
      <w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:rtl/></w:rPr>
      <w:continuationSeparator/></w:r></w:p>
  </w:footnote>
</w:footnotes>"""


def el(tag: str, **attrs) -> "OxmlElement":
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k.replace("__", ":")), v)
    return e


def set_rtl_paragraph(par, jc="both"):
    pPr = par._p.get_or_add_pPr()
    for child in ("w:bidi",):
        if pPr.find(qn(child)) is None:
            pPr.append(OxmlElement(child))
    jc_el = pPr.find(qn("w:jc"))
    if jc_el is None:
        jc_el = OxmlElement("w:jc")
        pPr.append(jc_el)
    jc_el.set(qn("w:val"), jc)
    return par


def set_rtl_run(run, cfg, size=None, color=None, bold=None):
    rPr = run._r.get_or_add_rPr()
    if rPr.find(qn("w:rtl")) is None:
        rPr.append(OxmlElement("w:rtl"))
    fonts = rPr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rPr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), cfg["font"]["arabic"])
    pts = size or cfg["font"]["size_pt"]
    run.font.size = Pt(pts)
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(int(pts * 2)))
    rPr.append(szcs)
    if bold is not None:
        run.bold = bold
        if bold:
            rPr.append(OxmlElement("w:bCs"))
    if color is not None:
        run.font.color.rgb = color
    return run


class FootnoteEngine:
    """حواشٍ بعلامات مخصّصة: الرقم نصّ عربي شرقي مضمون الشكل في كل جهاز."""

    def __init__(self, document, cfg):
        self.doc = document
        self.cfg = cfg
        self.counter = 0
        self.items: list[tuple[int, str]] = []

    def mark(self, n: int) -> str:
        tpl = self.cfg.get("footnote_mark_format", "({n})")
        return tpl.replace("{n}", arabize_digits(str(n)))

    def add(self, paragraph, text: str) -> int:
        self.counter += 1
        n = self.counter
        run = paragraph.add_run()
        set_rtl_run(run, self.cfg, size=self.cfg["font"]["size_pt"] - 4)
        rPr = run._r.get_or_add_rPr()
        va = OxmlElement("w:vertAlign")
        va.set(qn("w:val"), "superscript")
        rPr.append(va)
        ref = OxmlElement("w:footnoteReference")
        ref.set(qn("w:customMarkFollows"), "1")
        ref.set(qn("w:id"), str(n))
        run._r.append(ref)
        t = OxmlElement("w:t")
        t.text = self.mark(n)
        run._r.append(t)
        self.items.append((n, text))
        return n

    def _run_xml(self, text: str, size: int, italic=False, bold=False) -> str:
        from xml.sax.saxutils import escape
        f = self.cfg["font"]["arabic"]
        props = (f'<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}"/>'
                 f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
        if bold:
            props += "<w:b/><w:bCs/>"
        if italic:
            props += "<w:i/><w:iCs/>"
        props += "<w:rtl/>"
        return (f"<w:r><w:rPr>{props}</w:rPr>"
                f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')

    def _footnote_xml(self, n: int, text: str) -> str:
        size = int((self.cfg["font"]["size_pt"] - 4) * 2)
        runs = [self._run_xml(self.mark(n) + " ", size)]
        for token in INLINE_RE.split(text):
            if not token:
                continue
            strong = token.startswith("**") or token.startswith("__")
            em = (token.startswith("*") and not strong) or \
                 (token.startswith("_") and not strong)
            runs.append(self._run_xml(token.strip("*_"), size,
                                      italic=em, bold=strong))
        return (
            f'<w:footnote w:id="{n}">'
            f'<w:p><w:pPr><w:bidi/><w:jc w:val="both"/>'
            f'<w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
            + "".join(runs) + "</w:p></w:footnote>"
        )

    def commit(self):
        xml = FOOTNOTES_SKELETON.strip()
        payload = "".join(self._footnote_xml(n, t) for n, t in self.items)
        xml = xml.replace("</w:footnotes>", payload + "</w:footnotes>")
        part = Part(PackURI("/word/footnotes.xml"), FOOTNOTES_CT,
                    xml.encode("utf-8"), self.doc.part.package)
        self.doc.part.relate_to(part, FOOTNOTES_RT)


# ----------------------------------------------------------------------------
# بناء المستند
# ----------------------------------------------------------------------------
def configure_document(doc, cfg):
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    m = cfg.get("margins_cm", {"top": 2.5, "bottom": 2.5, "left": 2.5, "right": 3.0})
    sec.top_margin, sec.bottom_margin = Cm(m["top"]), Cm(m["bottom"])
    sec.left_margin, sec.right_margin = Cm(m["left"]), Cm(m["right"])
    sectPr = sec._sectPr
    if sectPr.find(qn("w:bidi")) is None:
        sectPr.append(OxmlElement("w:bidi"))
    if sectPr.find(qn("w:rtlGutter")) is None:
        sectPr.append(OxmlElement("w:rtlGutter"))

    normal = doc.styles["Normal"]
    normal.font.name = cfg["font"]["arabic"]
    normal.font.size = Pt(cfg["font"]["size_pt"])
    pf = normal.paragraph_format
    pf.line_spacing = cfg.get("line_spacing", 1.5)
    pf.space_after = Pt(6)
    rpr = normal.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(attr), cfg["font"]["arabic"])
    if rpr.find(qn("w:rtl")) is None:
        rpr.append(OxmlElement("w:rtl"))

    # إعدادات المستند: لغة ثنائية الاتجاه
    settings = doc.settings.element
    tfl = settings.find(qn("w:themeFontLang"))
    if tfl is None:
        tfl = OxmlElement("w:themeFontLang")
        settings.append(tfl)
    tfl.set(qn("w:bidi"), "ar-SA")
    tfl.set(qn("w:val"), "ar-SA")


HEADING_SIZES = {"h1": 8, "h2": 5, "h3": 3, "h4": 2}   # زيادة على حجم المتن


def add_rich_text(par, text, cfg, red=False, size=None, bold=None, footnotes=None,
                  fn_map=None):
    """يفكّ التوكيد والحواشي داخل الفقرة ويبني تشغيلات RTL."""
    color = RGBColor(0xC0, 0x00, 0x00) if red else None
    for token in INLINE_RE.split(text):
        if not token:
            continue
        m = FOOTNOTE_REF_RE.fullmatch(token)
        if m and footnotes is not None:
            key = m.group(1)
            body = footnotes.get(key)
            if body is None:
                body = f"[هامش غير معرَّف: {key}]"
            n = fn_map.add(par, arabize_digits(scrub(body)))
            continue
        strong = token.startswith("**") or token.startswith("__")
        em = (token.startswith("*") and not strong) or (token.startswith("_") and not strong)
        clean = token.strip("*_")
        run = par.add_run(arabize_digits(scrub(clean)))
        set_rtl_run(run, cfg, size=size, color=color,
                    bold=True if (bold or strong) else None)
        if em:
            run.italic = True


def build(cfg, sources, out_path: Path, report: dict):
    doc = Document()
    configure_document(doc, cfg)
    fn = FootnoteEngine(doc, cfg)
    body_size = cfg["font"]["size_pt"]

    first = True
    for src in sources:
        ch = parse_markdown(Path(src))
        report["chapters"].append({"file": str(src), "blocks": len(ch.blocks),
                                   "footnotes": len(ch.footnotes)})
        if not first:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        first = False

        for b in ch.blocks:
            if b.kind == "pagebreak":
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
                continue

            if b.kind == "table":
                if not b.rows:
                    continue
                tbl = doc.add_table(rows=len(b.rows), cols=max(len(r) for r in b.rows))
                tbl.style = "Table Grid"
                tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                tblPr = tbl._tbl.tblPr
                if tblPr.find(qn("w:bidiVisual")) is None:
                    tblPr.append(OxmlElement("w:bidiVisual"))
                for ri, row in enumerate(b.rows):
                    for ci, cell in enumerate(row):
                        par = tbl.rows[ri].cells[ci].paragraphs[0]
                        set_rtl_paragraph(par, jc="center" if ri == 0 else "right")
                        add_rich_text(par, cell, cfg, red=b.red, size=body_size - 2,
                                      bold=(ri == 0), footnotes=ch.footnotes, fn_map=fn)
                doc.add_paragraph()
                continue

            if b.kind.startswith("h"):
                par = doc.add_paragraph()
                set_rtl_paragraph(par, jc="center" if b.kind in ("h1", "h2") else "right")
                par.paragraph_format.space_before = Pt(18 if b.kind == "h1" else 12)
                par.paragraph_format.space_after = Pt(10)
                par.paragraph_format.keep_with_next = True
                add_rich_text(par, b.text, cfg, red=b.red,
                              size=body_size + HEADING_SIZES.get(b.kind, 2), bold=True,
                              footnotes=ch.footnotes, fn_map=fn)
                continue

            par = doc.add_paragraph()
            set_rtl_paragraph(par, jc="both")
            pf = par.paragraph_format
            if b.kind == "quote":
                pf.left_indent = Cm(1.5)
                pf.right_indent = Cm(1.5)
                pf.first_line_indent = Cm(0)
                add_rich_text(par, b.text, cfg, red=b.red, size=body_size - 2,
                              footnotes=ch.footnotes, fn_map=fn)
            elif b.kind == "li":
                pf.right_indent = Cm(1.0)
                pf.first_line_indent = Cm(0)
                add_rich_text(par, "- " + b.text, cfg, red=b.red,
                              footnotes=ch.footnotes, fn_map=fn)
            else:
                pf.first_line_indent = Cm(cfg.get("first_line_indent_cm", 1.25))
                add_rich_text(par, b.text, cfg, red=b.red,
                              footnotes=ch.footnotes, fn_map=fn)

    fn.commit()
    report["footnotes_total"] = fn.counter
    clean_package(doc, cfg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return report


def clean_package(doc, cfg):
    """يمحو آثار القوالب وبيانات الوورد الكاشفة."""
    pkg = doc.part.package
    doc_part = doc.part
    drop_rt = ("thumbnail", "customXml", "customXmlProps")
    for rel_id, rel in list(pkg.rels.items()):
        if any(k.lower() in rel.reltype.lower() for k in drop_rt):
            del pkg.rels[rel_id]
    for rel_id, rel in list(doc_part.rels.items()):
        if any(k.lower() in rel.reltype.lower() for k in drop_rt):
            del doc_part.rels[rel_id]

    cp = doc.core_properties
    meta = cfg.get("metadata", {})
    cp.author = meta.get("author", "")
    cp.last_modified_by = meta.get("author", "")
    cp.title = meta.get("title", "")
    cp.subject = meta.get("subject", "")
    cp.comments = ""
    cp.category = ""
    cp.keywords = ""
    cp.content_status = ""
    cp.identifier = ""
    cp.language = "ar-SA"
    cp.revision = 1

    # إزالة معرّفات المراجعة (rsid) التي تكشف تسلسل التحرير
    root = doc.element
    for e in root.iter():
        for attr in list(e.attrib):
            if "rsid" in attr.lower():
                del e.attrib[attr]
    settings = doc.settings.element
    for tag in ("w:proofState", "w:rsids"):
        node = settings.find(qn(tag))
        if node is not None:
            settings.remove(node)


# ----------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cfg.setdefault("font", {}).setdefault("arabic", "Traditional Arabic")
    cfg["font"].setdefault("size_pt", 16)
    return cfg


SKIP_RE = re.compile(r"(^_|EXCEPTIONS|\.template\.|README|LEDGER)")


def _keep(path: str) -> bool:
    return not SKIP_RE.search(Path(path).name)


def resolve_sources(cfg, only) -> list[str]:
    if only:
        out = []
        for pattern in only:
            out.extend(sorted(glob.glob(pattern)))
        return out
    ordered = []
    for pattern in cfg.get("chapter_order", []):
        hits = sorted(glob.glob(str(ROOT / pattern))) or sorted(glob.glob(pattern))
        ordered.extend(hits)
    if not ordered:
        ordered = sorted(glob.glob(str(ROOT / cfg.get("chapters_glob", "chapters/**/*.md")),
                                   recursive=True))
    seen, uniq = set(), []
    for p in (p for p in ordered if _keep(p)):
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def main(argv=None):
    ap = argparse.ArgumentParser(description="محرّك بناء المستند الأمّ (RTL/أرقام عربية/نظيف)")
    ap.add_argument("--config", default=str(ROOT / "thesis.config.json"))
    ap.add_argument("--only", nargs="*", help="ملفات md محدّدة بدل ترتيب الفصول")
    ap.add_argument("--out", help="مسار الإخراج (افتراضياً المستند الأمّ من الإعدادات)")
    ap.add_argument("--open", action="store_true", help="فتح المستند بعد البناء")
    ap.add_argument("--report", default=str(ROOT / "state" / "last_build_report.json"))
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config))
    sources = resolve_sources(cfg, args.only)
    if not sources:
        sys.exit("[!] لا توجد مسودّات .md للبناء. أضف فصلاً في chapters/ أو حدّد --only")

    out_path = Path(args.out or (ROOT / cfg.get("master_docx",
                                                "outputs/docx/الرسالة_الكاملة.docx")))
    if out_path.exists():                      # نسخة أمان واحدة لا نسخ متكاثرة
        backup = out_path.with_suffix(".bak.docx")
        shutil.copy2(out_path, backup)

    report = {"built_at": datetime.now().isoformat(timespec="seconds"),
              "output": str(out_path), "chapters": [], "footnotes_total": 0}
    build(cfg, sources, out_path, report)

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    print("── تقرير البناء ─────────────────────────────")
    print(f"  المستند الأمّ : {out_path}")
    print(f"  الفصول       : {len(report['chapters'])}")
    print(f"  الحواشي      : {report['footnotes_total']}")
    print(f"  RTL          : مقطع/فقرة/تشغيل/جدول/هامش/فاصل ✔")
    print(f"  الأرقام      : عربية شرقية ٠-٩ + علامات حواشٍ مخصّصة ✔")
    print(f"  التنظيف      : رموز مخفية ٠ | آثار قوالب محذوفة | بيانات وورد منظّفة ✔")

    if args.open:
        try:
            if os.name == "nt":
                os.startfile(str(out_path))           # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(out_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(out_path)], check=False)
        except Exception as exc:                       # pragma: no cover
            print(f"  [i] تعذّر فتح الملف تلقائياً: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
