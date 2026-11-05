"""Small text helpers: HTML to text, salary parsing, date parsing."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "tr", "section"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(s: str) -> str:
    """Convert (possibly entity-escaped) HTML to readable plain text."""
    if not s:
        return ""
    if "&lt;" in s and "<" not in s:
        s = html.unescape(s)
    p = _Text()
    p.feed(s)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


_MONEY = re.compile(r"£\s?(\d{2,3}(?:,\d{3})|\d{2,3}(?:\.\d)?\s?[kK])")


def _to_number(tok: str) -> float:
    tok = tok.replace(",", "").replace(" ", "")
    if tok.lower().endswith("k"):
        return float(tok[:-1]) * 1000
    return float(tok)


def parse_salary(text: str) -> tuple[float | None, float | None]:
    """Find an annual GBP salary range like '£60,000 - £70,000' or '£60k-70k' in free text."""
    if not text:
        return None, None
    m = re.search(r"£\s?(\d{2,3}(?:,\d{3}|\.\d)?\s?[kK]?)\s*(?:-|–|to)\s*£?\s?(\d{2,3}(?:,\d{3}|\.\d)?\s?[kK]?)", text)
    if m:
        a, b = m.group(1), m.group(2)
        if a.lower().endswith("k") and not b.lower().endswith("k") and "," not in b:
            b += "k"
        if b.lower().endswith("k") and not a.lower().endswith("k") and "," not in a:
            a += "k"
        lo, hi = _to_number(a), _to_number(b)
        if 15000 <= lo <= hi <= 1_000_000:
            return lo, hi
    vals = [_to_number(t) for t in _MONEY.findall(text)]
    vals = [v for v in vals if 15000 <= v <= 1_000_000]
    if vals:
        return min(vals), max(vals)
    return None, None


def parse_date(value) -> datetime | None:
    """Accept ISO strings, epoch milliseconds, or dd/mm/yyyy; return an aware UTC datetime."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
        s = str(value).strip()
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
            return datetime.strptime(s, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
