"""A tiny, safe Markdown renderer (no dependencies).

Supports: headings, paragraphs, **bold**, *italic*, ~~strike~~, `code`,
fenced code blocks, links, images, ordered/unordered lists, blockquotes,
horizontal rules and simple pipe tables. All raw HTML is escaped.
"""
from __future__ import annotations

import html
import re
import textwrap

_SAFE_URL = re.compile(r"^(https?:|mailto:|/|#|\.|data:image/)", re.I)


def _url(u: str) -> str:
    u = u.strip()
    return html.escape(u, quote=True) if _SAFE_URL.match(u) else "#"


def inline(text: str) -> str:
    codes: list[str] = []

    def keep_code(m: re.Match) -> str:
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep_code, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: f'<img alt="{m.group(1)}" src="{_url(m.group(2))}">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: f'<a href="{_url(m.group(2))}" target="_blank" rel="noopener">{m.group(1)}</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def render(src: str) -> str:
    lines = textwrap.dedent(str(src)).strip("\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(s.strip() for s in para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            lang = html.escape(s[3:].strip())
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            out.append(f'<pre data-lang="{lang}"><code>{html.escape(chr(10).join(buf))}</code></pre>')
        elif not s:
            flush()
        elif m := re.match(r"^(#{1,6})\s+(.*)$", s):
            flush()
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush()
            out.append("<hr>")
        elif s.startswith(">"):
            flush()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + render("\n".join(buf)) + "</blockquote>")
            continue
        elif re.match(r"^([-*+]|\d+[.)])\s+", s):
            flush()
            ordered = bool(re.match(r"^\d", s))
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                item = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", lines[i])
                if item.startswith("[ ] ") or item.startswith("[x] "):
                    box = "☑" if item[1] == "x" else "☐"
                    item = f"{box} {item[4:]}"
                items.append(f"<li>{inline(item)}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        elif s.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush()
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            head = cells(s)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            tb = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table>")
            continue
        else:
            para.append(line)
        i += 1
    flush()
    return "\n".join(out)
