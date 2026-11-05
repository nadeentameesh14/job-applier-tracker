"""Read a Word CV, apply tailoring edits in place (keeping its design), and fit it to N pages.

The CV is split into blocks with stable ids:
  S1      the summary paragraph
  B<n>    bullets under the experience section (editable, reorderable within their role, removable)
  K<n>    "Label: values" lines in the skills section (values editable)
  X<n>    anything else that can be dropped to save space (other bullets, awards, publications...)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.document import Document as DocxDocument
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

BULLET_RE = re.compile(r"^\s*[•\-–▪●◦]\s*")
SUMMARY_HEADINGS = ("SUMMARY", "PROFILE", "ABOUT")
EXPERIENCE_HEADINGS = ("EXPERIENCE", "EMPLOYMENT", "WORK HISTORY")
SKILLS_HEADINGS = ("SKILLS",)
KEEP_HEADINGS = ("EDUCATION",)  # whole section is never dropped (its bullets can be)


@dataclass
class Block:
    id: str
    kind: str  # summary | bullet | skills | item
    text: str
    section: str
    role: str = ""  # job heading the bullet belongs to
    para: Paragraph | None = field(default=None, repr=False)
    prefix: str = ""  # bullet marker as written, e.g. "•  "
    cont: list[Paragraph] = field(default_factory=list, repr=False)  # wrapped continuation lines


def _is_heading(p: Paragraph) -> bool:
    t = p.text.strip()
    return bool(t) and len(t) <= 40 and t.upper() == t and any(c.isalpha() for c in t) and not BULLET_RE.match(t)


def _has_numbering(p: Paragraph) -> bool:
    ppr = p._p.pPr
    return ppr is not None and ppr.numPr is not None


class CV:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.doc: DocxDocument = docx.Document(str(path))
        self.blocks: list[Block] = []
        self._parse()

    # ---------- parsing ----------
    def _parse(self) -> None:
        body = self.doc.element.body
        section, role = "", ""
        counters = {"B": 0, "K": 0, "X": 0}
        para_by_el = {p._p: p for p in self.doc.paragraphs}
        for el in body.iterchildren():
            tag = el.tag.split("}")[-1]
            if tag == "tbl":
                # tables in CVs are usually "Job title | Company ... Dates" rows
                text = " ".join(t.text or "" for t in el.iter() if t.tag.endswith("}t")).strip()
                if text:
                    role = re.sub(r"\s+", " ", text)
                continue
            if tag != "p" or el not in para_by_el:
                continue
            p = para_by_el[el]
            text = p.text.strip()
            if not text:
                continue
            if _is_heading(p):
                section, role = text, ""
                continue
            up = section.upper()
            bullet = bool(BULLET_RE.match(p.text)) or _has_numbering(p)
            if any(h in up for h in SUMMARY_HEADINGS) and not any(b.kind == "summary" for b in self.blocks):
                self.blocks.append(Block("S1", "summary", text, section, para=p))
            elif any(h in up for h in EXPERIENCE_HEADINGS) and bullet:
                counters["B"] += 1
                m = BULLET_RE.match(p.text)
                self.blocks.append(Block(f"B{counters['B']}", "bullet", BULLET_RE.sub("", text), section,
                                         role=role, para=p, prefix=m.group(0) if m else ""))
            elif any(h in up for h in SKILLS_HEADINGS) and ":" in text[:40]:
                counters["K"] += 1
                self.blocks.append(Block(f"K{counters['K']}", "skills", text, section, para=p))
            elif any(h in up for h in SKILLS_HEADINGS) and self.blocks and self.blocks[-1].kind == "skills":
                last = self.blocks[-1]  # a skills line that wrapped onto its own paragraph
                last.cont.append(p)
                last.text = f"{last.text} {text}"
            elif not section or (any(h in up for h in KEEP_HEADINGS) and not bullet):
                continue  # name, contact details, degree lines: never touched
            elif not any(h in up for h in SUMMARY_HEADINGS + EXPERIENCE_HEADINGS + SKILLS_HEADINGS):
                if not bullet and len(text) <= 30 and len(text.split()) <= 3:
                    continue  # sub-heading such as "Awards"; removed automatically when empty
                counters["X"] += 1
                self.blocks.append(Block(f"X{counters['X']}", "item", text, section, role=role, para=p))

    # ---------- views ----------
    def full_text(self) -> str:
        parts = []
        for el in self.doc.element.body.iter():
            if el.tag.endswith("}t") and el.text:
                parts.append(el.text)
            elif el.tag.endswith("}p"):
                parts.append("\n")
        return re.sub(r"\n+", "\n", "".join(parts)).strip()

    def block(self, bid: str) -> Block | None:
        return next((b for b in self.blocks if b.id == bid), None)

    def outline(self) -> str:
        """Text given to the model: every block with its id, grouped by section and role."""
        lines, last = [], None
        for b in self.blocks:
            head = f"## {b.section}" + (f" / {b.role}" if b.role and b.kind == "bullet" else "")
            if head != last:
                lines.append(head)
                last = head
            lines.append(f"[{b.id}] {b.text}")
        return "\n".join(lines)

    # ---------- edits ----------
    @staticmethod
    def _set_text(p: Paragraph, text: str, keep_first_run: bool = False) -> None:
        runs = p.runs
        if not runs:
            p.add_run(text)
            return
        if keep_first_run and len(runs) > 1:
            runs[1].text = text
            for r in runs[2:]:
                r._r.getparent().remove(r._r)
        else:
            runs[0].text = text
            for r in runs[1:]:
                r._r.getparent().remove(r._r)

    def set_block_text(self, bid: str, text: str) -> None:
        b = self.block(bid)
        if b is None or b.para is None:
            raise KeyError(bid)
        text = text.strip()
        if b.kind == "bullet":
            self._set_text(b.para, (b.prefix or "") + BULLET_RE.sub("", text))
        elif b.kind == "skills":
            for c in b.cont:
                c._p.getparent().remove(c._p)
            b.cont = []
            label = b.para.runs[0].text if b.para.runs else ""
            if label.strip().endswith(":") and len(b.para.runs) > 1:
                value = text.split(":", 1)[1] if text.lower().startswith(label.strip().lower()) else text
                self._set_text(b.para, " " + value.strip(), keep_first_run=True)
            else:
                self._set_text(b.para, text)
        else:
            self._set_text(b.para, text)
        b.text = BULLET_RE.sub("", text) if b.kind == "bullet" else text

    def reorder_bullets(self, order: list[str]) -> None:
        """Reorder experience bullets inside each role to follow `order` (ids not listed keep their place last)."""
        by_role: dict[str, list[Block]] = {}
        for b in self.blocks:
            if b.kind == "bullet" and b.para is not None:
                by_role.setdefault(b.role, []).append(b)
        rank = {bid: i for i, bid in enumerate(order)}
        for role, bullets in by_role.items():
            wanted = sorted(bullets, key=lambda b: rank.get(b.id, 10_000 + bullets.index(b)))
            if [b.id for b in wanted] == [b.id for b in bullets]:
                continue
            anchors = [b.para._p for b in bullets]
            slots = [(a.getparent(), a.getparent().index(a)) for a in anchors]
            for a in anchors:
                a.getparent().remove(a)
            # re-insert in slot order, smallest index first, so indexes stay valid
            for (parent, idx), b in sorted(zip(slots, wanted), key=lambda t: t[0][1]):
                parent.insert(idx, b.para._p)

    def remove_block(self, bid: str) -> bool:
        b = self.block(bid)
        if b is None or b.para is None:
            return False
        if b.kind in {"summary", "skills"}:
            return False
        if b.kind == "bullet":
            same_role = [x for x in self.blocks if x.kind == "bullet" and x.role == b.role and x.para is not None]
            if len(same_role) <= 2:
                return False  # always keep at least two bullets per job
        el = b.para._p
        el.getparent().remove(el)
        b.para = None
        self._drop_orphan_headings()
        return True

    def _drop_orphan_headings(self) -> None:
        """Remove a heading (or sub-heading like 'Awards') when nothing is left under it."""
        body = self.doc.element.body
        para_by_el = {p._p: p for p in self.doc.paragraphs}

        def level(el) -> int | None:
            """1 = section heading, 2 = sub-heading, 0 = content, None = empty paragraph."""
            if el.tag.endswith("}tbl"):
                return 0
            p = para_by_el.get(el)
            if p is None or not p.text.strip():
                return None
            if _is_heading(p):
                return 1
            t = p.text.strip()
            if len(t) <= 30 and len(t.split()) <= 3 and ":" not in t and not BULLET_RE.match(t) and t[:1].isupper():
                return 2
            return 0

        protected = EXPERIENCE_HEADINGS + SKILLS_HEADINGS + SUMMARY_HEADINGS + KEEP_HEADINGS
        changed = True
        while changed:
            changed = False
            children = list(body.iterchildren())
            levels = [level(el) for el in children]
            for i, (el, lv) in enumerate(zip(children, levels)):
                if not lv:
                    continue
                p = para_by_el.get(el)
                if p is not None and any(h in p.text.upper() for h in protected):
                    continue
                nxt = next((l for l in levels[i + 1:] if l is not None), None)
                if nxt is None or (nxt > 0 and nxt <= lv):
                    el.getparent().remove(el)
                    changed = True
                    break

    def default_drop_order(self) -> list[str]:
        """Fallback trimming order: last non-experience items first, then oldest-role bullets."""
        items = [b.id for b in self.blocks if b.kind == "item"][::-1]
        bullets = [b.id for b in self.blocks if b.kind == "bullet"][::-1]
        return items + bullets

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(path))
        return path


def soffice_bin() -> str:
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in ("/Applications/LibreOffice.app/Contents/MacOS/soffice", r"C:\Program Files\LibreOffice\program\soffice.exe"):
        if Path(p).exists():
            return p
    raise RuntimeError("LibreOffice is needed to make PDFs and count pages (install it: see docs/SETUP.md)")


def to_pdf(docx_path: str | Path, out_dir: str | Path | None = None) -> Path:
    docx_path = Path(docx_path)
    out_dir = Path(out_dir or docx_path.parent)
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [soffice_bin(), f"-env:UserInstallation=file://{profile}", "--headless",
             "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
            check=True, capture_output=True, timeout=180,
        )
    return out_dir / (docx_path.stem + ".pdf")


def page_count(pdf_path: str | Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def fit_to_pages(cv: CV, out_docx: Path, max_pages: int, drop_order: list[str]) -> tuple[Path, int, list[str]]:
    """Save, render, and drop blocks in drop_order until the PDF is within max_pages."""
    dropped: list[str] = []
    order = [b for b in drop_order if cv.block(b)] + [b for b in cv.default_drop_order() if b not in drop_order]
    cv.save(out_docx)
    pdf = to_pdf(out_docx)
    pages = page_count(pdf)
    for bid in order:
        if pages <= max_pages:
            break
        if cv.remove_block(bid):
            dropped.append(bid)
            cv.save(out_docx)
            pdf = to_pdf(out_docx)
            pages = page_count(pdf)
    return pdf, pages, dropped


def clone(cv: CV) -> CV:
    """Fresh copy of the CV loaded from the same file (edits are applied to the copy)."""
    return CV(cv.path)


