# -*- coding: utf-8 -*-
"""Paper PDF to the manuscript this skill reads (`paper.md`) and figure PNGs.

    python scripts/pdf_paper.py paper/paper.pdf -o paper/

    produces
      paper/paper.md          body text with heading lines (#) restored from font size. scaffold
                              and the checkers read this
      paper/figs/fig_N.png    for each "Figure N" caption, that figure's region cropped out (200dpi)

Why this exists: a paper with no LaTeX manuscript is common. Some papers
on arXiv upload only the compiled PDF, where the manuscript is one line
of `\\includepdf`. This skill only reads LaTeX/Markdown, so a PDF-only
paper blocked it at the very first step.

Limits: tables come through as text only, since the cell structure can't
be recovered. A table's numbers do end up in the body text, so a checker
can cross-check them, but a slide table still has to be copied over by
hand, and deckcheck cross-checks those values against `paper.md`. Figures
come through exactly as cropped: if there's no data to redraw, point at
what to look at with `figure.highlight` (planning, section plots).
"""
import argparse
import io
import os
import re
import sys

try:
    try:
        import pymupdf as fitz
    except ImportError:      # PyMuPDF before 1.24.3 has only the old import name
        import fitz
except ImportError:  # pragma: no cover
    raise SystemExit("PyMuPDF is required:  pip install pymupdf")

# Known character swaps in the Advent Pi math font — applied only to spans in that font
_ADVP = {ord("þ"): "+", ord("¼"): "=", ord("ð"): "(", ord("Þ"): ")",
         ord("½"): "[", ord("Š"): "]", ord("À"): "−", ord("Ã"): "×"}
ADVP_SEEN = [False]
_LIGATURES = {ord("ﬀ"): "ff", ord("ﬁ"): "fi", ord("ﬂ"): "fl",
              ord("ﬃ"): "ffi", ord("ﬄ"): "ffl", ord("ﬅ"): "st",
              ord("ﬆ"): "st"}
CAPTION = re.compile(r"^\s*(Figure|Fig\.)\s*(\d+)\s*[:.]", re.I)
TABLE_CAPTION = re.compile(r"^\s*Table\s*(\d+)\s*[:.]", re.I)


BOLD_FONT = re.compile(r"Bold|Medi|Semibold|Demi|Heavy|Black|\.B$|-B$", re.I)


def _is_bold(s):
    return bool(BOLD_FONT.search(s["font"])) or bool(s["flags"] & 16)


def _lines(page):
    """(text, size, is_bold, rect), line by line.

    Pieces at the same height are joined into one line. Without this, the
    section number "4.3" and the heading "CELL AGING" can sit apart
    within the PDF, splitting into a number-only line and a heading-only line.
    """
    raw = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            sp = [s for s in ln["spans"] if s["text"].strip()]
            # Rotated text (the arXiv stamp "arXiv:...v1 [cs.CV]", a vertical axis label) is not body text
            if sp and abs(ln.get("dir", (1, 0))[1]) < 0.1:
                raw.append((fitz.Rect(ln["bbox"]), ln["spans"], sp))
    # Doesn't re-sort by y: sorting by y would interleave left- and
    # right-column lines one by one in a two-column paper. Keeps the
    # PDF's block order (reading order) instead, and joins two lines
    # only when one sits at the same height as the one right before it.
    rows = []
    for r, spans, sp in raw:
        last = rows[-1] if rows else None
        if (last and abs(last[0].y0 - r.y0) < 2.0 and abs(last[0].y1 - r.y1) < 3.0
                and 0 <= r.x0 - last[0].x1 < 40):
            last[0] |= r
            last[1].extend(spans)
            last[2].extend(sp)
        else:
            rows.append([fitz.Rect(r), list(spans), list(sp)])
    out = []
    for r, spans, sp in rows:
        # Gaps between pieces are inserted only when there's an actual
        # gap. Without this, a small-caps heading breaks into pieces at
        # every font-size change, turning into "A DAM : A M ETHOD."
        txt, prev = "", None
        # The line's dominant size and baseline: a piece smaller than this
        # and sitting above is a superscript, below is a subscript. The
        # PDF's own superscript flag can be set even on body-size spans,
        # so it can't be trusted on its own. Joining a superscript or
        # subscript plainly would turn "10^13" into "1013" and "10^-21"
        # into "10−21," corrupting the source-of-truth values.
        _big = max([s_["size"] for s_ in sp] or [0])
        _base = [s_["origin"][1] for s_ in sp if s_["size"] >= _big - 0.2]
        _base = sorted(_base)[len(_base) // 2] if _base else None
        _last_kind = None
        for s in sorted(spans, key=lambda s: s["bbox"][0]):
            if not s["text"]:
                continue
            piece = s["text"]
            # A publisher's math font (Advent Pi, named `AdvP...`) has a
            # broken ToUnicode mapping, so "+" comes out as "þ" and "="
            # as "¼." Unscrambled only for that font.
            if s.get("font", "").startswith("AdvP"):
                piece = piece.translate(_ADVP)
                ADVP_SEEN[0] = True
            # In the same publisher's italic math font (`AdvTT....I`),
            # "=" is actually "/": "2GM/c2" would otherwise come out as
            # "2GM=c2." The real equals sign comes from the AdvP font
            # above, as "¼."
            _f = s.get("font", "")
            if _f.startswith("AdvTT") and _f.endswith(".I"):
                piece = piece.replace("=", "/")
                ADVP_SEEN[0] = True
            _kind = None
            if (_base is not None and s["size"] < _big * 0.85 and piece.strip()
                    and txt and not txt.endswith(" ")):
                _dy = s["origin"][1] - _base
                _kind = "^" if _dy < -0.15 * _big else ("_" if _dy > 0.10 * _big else None)
                if _kind:
                    # If the same superscript/subscript continues across
                    # pieces, mark it only once; otherwise it becomes "10^−^21."
                    _gap = prev is not None and s["bbox"][0] - prev > 0.15 * s["size"]
                    piece = piece.strip() if (_kind == _last_kind and not _gap) else _kind + piece.strip()
            _last_kind = _kind
            # A word with letter-spacing ("P H Y S I C A L") is joined
            # solid, so a running page header with spaced-out letters
            # doesn't get mistaken for ordinary body prose.
            if re.fullmatch(r"\s*(?:\S ){2,}\S\s*", piece):
                piece = piece.replace(" ", "")
            if (prev is not None and s["bbox"][0] - prev > 0.15 * s["size"]
                    and not txt.endswith(" ") and not piece.startswith(" ")):
                txt += " "
            txt += piece
            prev = s["bbox"][2]
        # Expands ligatures (ﬁ, ﬂ). Left alone, "first" prints as a word
        # not in the paper, throwing off any claim that matches against it.
        txt = txt.translate(_LIGATURES)
        txt = re.sub(r"\s+", " ", txt.replace("\x00", "")).strip()
        size = max(s["size"] for s in sp)
        bold = all(_is_bold(s) for s in sp)
        out.append((txt, size, bold, r))
    return out


NUMBERED = re.compile(r"^(?:[A-Z]\.|[IVX]+\.|\d+(?:\.\d+)*\.?)\s+\S")
FRONT_END = re.compile(r"^(abstract|introduction)\b", re.I)


def _heading(txt, size, bold, body):
    """A short line that's bigger than body text, bold, or a numbered all-caps line. Not a
    sentence (one ending in a period, colon, comma, or semicolon)."""
    if len(txt) > 90 or txt.endswith((".", ":", ",", ";")) or CAPTION.match(txt) \
            or TABLE_CAPTION.match(txt):
        return False
    if not re.search(r"[A-Za-z]{3}", txt):
        return False
    if size > body + 1.2:
        return True
    numbered = bool(NUMBERED.match(txt))
    letters = re.sub(r"[^A-Za-z]", "", re.sub(r"^\S+\s+", "", txt) if numbered else txt)
    caps = len(letters) >= 4 and letters.isupper()
    if numbered and (bold or caps) and size >= body - 0.6:
        return True
    return bold and size >= body - 0.2 and caps


EDGE = 0.09          # only lines within this fraction of the top/bottom edge can be running headers/footers


def _key(t):
    return re.sub(r"\d+", "#", t)


def running_lines(doc):
    """Headers/footers that repeat on every page (a venue-name line, page number). Not body text."""
    from collections import Counter
    seen = Counter()
    for p in doc:
        h = p.rect.height
        for t, _, _, r in _lines(p):
            if r.y1 < h * EDGE or r.y0 > h * (1 - EDGE):
                seen[_key(t)] += 1
    n = len(doc)
    return {k for k, v in seen.items() if n >= 3 and v >= max(2, n // 2)}


def to_markdown(doc):
    """Renders the body as Markdown. A short line that's bigger or bolder than body text, or
    a numbered all-caps line, is treated as a heading.

    On the first page, whatever sits between the title and the abstract
    (authors, affiliations) is not a heading even if bold; it's left as a
    paragraph.
    """
    sizes = []
    for p in doc:
        for t, s, _, _ in _lines(p):
            sizes += [round(s, 1)] * len(t)
    if not sizes:
        return ""
    body = sorted(sizes)[len(sizes) // 2]
    out, para = [], []

    def flush():
        if para:
            t = " ".join(para)
            t = re.sub(r"(\w)- (\w)", r"\1\2", t)          # end-of-line hyphen
            out.append(t)
            out.append("")
            para[:] = []
    title_done = False
    _p0max = max([sz for _t, sz, _b, _r in _lines(doc[0])] or [0.0]) if len(doc) else 0.0
    front = True
    skip = running_lines(doc)
    # Text inside a figure (axis ticks, legend, diagram labels) is not
    # body text. Mixed in, it fills up "this section's numbers" and
    # diffcheck with ticks like 0.2-3.0 that don't belong there.
    try:
        figs = figure_regions(doc)
    except Exception:                       # still reads the body even if figure regions can't be found
        figs = {}
    for pi, p in enumerate(doc):
        h = p.rect.height
        last = None
        for txt, size, bold, _r in _lines(p):
            _c = fitz.Point((_r.x0 + _r.x1) / 2.0, (_r.y0 + _r.y1) / 2.0)
            if any(g.contains(_c) for g in figs.get(pi, [])):
                continue
            # Discards headers that repeat on every page, but keeps the
            # one on the first page: the venue and year are commonly
            # found only there ("Published as a conference paper at ICLR 2015").
            if _key(txt) in skip and (_r.y1 < h * EDGE or _r.y0 > h * (1 - EDGE)):
                if pi == 0 and not re.fullmatch(r"[\d\s#]+", txt) and _r.y1 < h * EDGE:
                    out.append(txt)
                    out.append("")
                continue
            # Paragraph boundary = a gap between lines of more than half a line. Without one, a
            # whole section becomes a single block
            if last is not None and 0.5 * size < _r.y0 - last.y1 < 4 * size:
                flush()
            last = _r
            # The title is the largest line on the first page. Looking
            # only for "more than 3pt above body size" can miss a 12.5pt
            # title over 9.5pt body text, leaving the scaffold's title
            # page unfilled.
            if not title_done and pi == 0 and size >= body + 1.8 and size >= _p0max - 0.05:
                flush()
                out += ["# " + txt, ""]
                title_done = True
                continue
            if front and FRONT_END.match(re.sub(r"^\S+\s+", "", txt) if NUMBERED.match(txt)
                                         else txt):
                front = False
            if front and pi == 0:
                para.append(txt)
                continue
            if _heading(txt, size, bold, body):
                flush()
                num = re.match(r"^(\d+(?:\.\d+)+)\.?\s", txt)
                lvl = 3 if num else 2
                out += ["#" * lvl + " " + re.sub(r"^\S+\s+", "", txt) if NUMBERED.match(txt)
                        else "#" * lvl + " " + txt, ""]
            else:
                para.append(txt)
        flush()
    return back_matter("\n".join(out))


_REF_START = re.compile(r"^\[1\]\s")
_REF_ITEM = re.compile(r"(?<!\S)(?=\[\d{1,3}\]\s)")
# One entry in an author list: "B. P. Abbott,^1" — a name followed by an affiliation number as a superscript
_AUTHOR = re.compile(r"[A-Z][\w.\-’' ]{1,40},\^[\d,]+")


def back_matter(md):
    """Puts a "## References" heading in front of the numbered reference list and splits
    it into one entry per line. Drops the author/affiliation list that follows it.

    A journal PDF's references can have no titles: "[1] A. Einstein, ..."
    runs on like a concluding paragraph, so the volume/year/page numbers
    become source-of-truth values, and a citation like "[108,109]"
    surfaces as an unused value. Left unhandled, a long author and
    affiliation list after the references reads as body text. When
    there's a title, scaffold/diffcheck/deckcheck cut the manuscript off there instead."""
    lines = md.split("\n")
    at = next((i for i, ln in enumerate(lines)
               if _REF_START.match(ln) and any(l_.startswith("#") for l_ in lines[:i])), None)
    if at is None:
        return md
    body, refs = lines[:at], []
    for ln in lines[at:]:
        if not ln.strip() or ln.startswith("#"):
            continue
        # Cuts off at the author list (several affiliation-numbered names) that follows the references
        _au = list(_AUTHOR.finditer(ln))
        if len(_au) >= 3:
            ln = ln[:_au[0].start()]
            refs += [x.strip() for x in _REF_ITEM.split(ln) if x.strip()]
            break
        if not re.match(r"^\[\d{1,3}\]\s", ln) and refs:
            # an affiliation/collaboration line after the references have ended
            if not re.search(r"\[\d{1,3}\]\s", ln):
                break
        refs += [x.strip() for x in _REF_ITEM.split(ln) if x.strip()]
    return "\n".join(body + ["## References", ""] + refs) + "\n"


MONO_FONT =re.compile(r"Mono|Courier|Typewriter|CMTT|Inconsolata|Consol|SFTT|Menlo", re.I)


def body_size(doc):
    sizes = []
    for p in doc:
        for t, s, _, _ in _lines(p):
            sizes += [round(s, 1)] * len(t)
    return sorted(sizes)[len(sizes) // 2] if sizes else 10.0


def _mono_rects(page):
    got = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            sp = [s for s in ln["spans"] if s["text"].strip()]
            if sp and all(MONO_FONT.search(s["font"]) for s in sp):
                got.append(fitz.Rect(ln["bbox"]))
    return got


def two_columns(lines, W):
    """A page is two-column if body lines often start in the right half."""
    right = [r for t, _, _, r in lines if r.x0 > W / 2 - 10 and r.width > 0.3 * W]
    return len(right) >= 5


def _column(page, crect, two=True):
    """On a two-column page, if the caption is one column wide, use just that column; otherwise
    the full page width. Without this, the neighboring column's figure bled in.

    A short caption in a single-column paper can otherwise be mistaken
    for column-width, missing a figure that spans the middle entirely.
    """
    W = page.rect.width
    if two and crect.width < 0.6 * W:
        mid = W / 2
        return (page.rect.x0, mid + 6) if crect.x1 <= mid + 20 else (mid - 6, page.rect.x1)
    return (page.rect.x0, page.rect.x1)


def _rotated_rects(page):
    """Rectangles of rotated text (a vertical axis label, a row name) — excluded from the body
    text but included in figures."""
    got = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            if abs(ln.get("dir", (1, 0))[1]) >= 0.1 and any(
                    s["text"].strip() for s in ln["spans"]):
                got.append(fitz.Rect(ln["bbox"]))
    return got


def figure_regions(doc):
    """{page number: [figure rects]} — just the regions, without cropping."""
    reg = {}
    figure_crops(doc, None, regions=reg)
    return reg


def figure_crops(doc, outdir, dpi=200, regions=None):
    """For each "Figure N" caption, crops the figure region above it (or below, if there's none) to PNG.

    Returns: (cropped [(N, path, caption)], missed [(N, page, caption)]).
    Also returns what couldn't be cropped. A figure made of text, like a
    code listing, has no line or shape fragments and can otherwise drop
    silently. A block of fixed-width text lines is also treated as a
    figure, and if there's still nothing, the page number is reported.
    """
    got, missed = [], []
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    body = body_size(doc)
    for page in doc:
        lines = _lines(page)
        # A caption is the first line of its block. Without this, a body
        # sentence starting a line with "Fig. 4. First, ..." can be
        # caught as a caption, turning the wrong fragment into "figure 4."
        starts = [fitz.Rect(b["lines"][0]["bbox"]) for b in page.get_text("dict")["blocks"]
                  if b.get("lines")]

        def first(r):
            return any(abs(s.y0 - r.y0) < 1.5 and abs(s.x0 - r.x0) < 2 for s in starts)
        caps = [(int(CAPTION.match(t).group(2)), r, t) for t, _, _, r in lines
                if CAPTION.match(t) and first(r)]
        if not caps:
            continue
        stops = []
        for b in page.get_text("dict")["blocks"]:
            ls = b.get("lines") or []
            if ls:
                t0 = "".join(s["text"] for s in ls[0]["spans"]).strip()
                if CAPTION.match(t0) or TABLE_CAPTION.match(t0):
                    stops.append(fitz.Rect(b["bbox"]))
        stops += [r for t, _, _, r in lines if (CAPTION.match(t) or TABLE_CAPTION.match(t))
                  and first(r) and not any(s.contains(r.tl + (1, 1)) for s in stops)]
        area = page.rect.width * page.rect.height
        shapes = [fitz.Rect(d["rect"]) for d in page.get_drawings()
                  if d.get("rect") is not None]
        for img in page.get_images(full=True):
            try:
                shapes += list(page.get_image_rects(img[0]))
            except Exception:
                pass
        H_ = page.rect.height
        # A thin line in a header/footer band (a running rule at the top
        # of the page) is not a figure. Treated as a figure fragment, it
        # would make the crop start at the top of the page and swallow
        # the body text in between, dropping that text from paper.md.
        shapes = [s for s in shapes if (s.width > 2 or s.height > 2)
                  and s.width * s.height < 0.9 * area
                  and not (min(s.height, s.width) < 3
                           and (s.y1 < H_ * EDGE or s.y0 > H_ * (1 - EDGE)))]
        mono = _mono_rects(page)
        # Body lines: body-sized and long. A figure never extends above or below these lines.
        bodyl = [r for t_, sz_, _, r in lines
                 if sz_ >= body - 0.6 and len(t_) >= 30 and not CAPTION.match(t_)
                 and not TABLE_CAPTION.match(t_)
                 and not any(r.intersects(m_) for m_ in mono)]
        rot = _rotated_rects(page)
        two = two_columns(lines, page.rect.width)
        for num, crect, ctext in caps:
            x0, x1 = _column(page, crect, two)

            def inside(s):
                return s.x1 > x0 and s.x0 < x1 and s.x0 >= x0 - 8 and s.x1 <= x1 + 8

            def over(s):                  # even a horizontal overlap counts — a page-wide caption is a boundary too
                return s.x1 > x0 + 4 and s.x0 < x1 - 4
            # Top boundary = the nearest other caption's entire block
            # (figure or table) above this caption, in this column. Using
            # only the first line as the boundary can let a table
            # caption's second line attach to the figure below it, and
            # looking for a page-wide caption only within the column can
            # mix two adjacent figures into one crop.
            top = max([s.y1 for s in stops if s.y1 <= crect.y0 - 1 and over(s)] + [page.rect.y0])
            # The top boundary also includes this column's last body
            # line, since a figure starts below the body text.
            top = max([top] + [r.y1 for r in bodyl if inside(r) and r.y1 <= crect.y0 - 2])
            above = [s for s in shapes + mono if inside(s) and s.y1 <= crect.y0 + 3 and s.y0 >= top - 1]
            region = None
            for s in above:
                region = s if region is None else region | s
            cblock = next((s for s in stops if s.contains(crect.tl + (1, 1))), crect)
            below = region is None
            if below:
                nxt = min([s.y0 for s in stops if s.y0 >= cblock.y1 + 1 and over(s)]
                          + [r.y0 for r in bodyl if inside(r) and r.y0 >= cblock.y1 + 2]
                          + [page.rect.y1])
                for s in shapes + mono:
                    if inside(s) and s.y0 >= cblock.y1 - 3 and s.y1 <= nxt:
                        region = s if region is None else region | s
            if region is None or region.width < 20 or region.height < 12:
                missed.append((num, page.number + 1, ctext))
                continue
            # Text like an axis label or legend also belongs to the
            # figure: adds small lines that touch the region.
            for t, sz, _, r in lines:
                if r.y1 < H_ * EDGE or r.y0 > H_ * (1 - EDGE):
                    continue            # a header/footer line is not part of the figure
                # doesn't add body-sized lines, since a table caption's last line or a body line could otherwise attach to the figure above it
                if (r.intersects(region + (-12, -12, 12, 12)) and inside(r)
                        and not CAPTION.match(t) and not TABLE_CAPTION.match(t)
                        and sz < body - 0.3 and r.height < 3 * body
                        and not r.intersects(cblock) and r.y0 >= top - 1):
                    region |= r
            # A short name attached to the side (a row label like
            # "beta_1=0") and a rotated axis label also belong to the
            # figure. Excluding them for being body-sized cuts the row
            # labels off and requires a manual re-crop.
            for t, sz, _, r in lines:
                if r.y1 < H_ * EDGE or r.y0 > H_ * (1 - EDGE):
                    continue            # a header/footer line is not part of the figure
                cy = (r.y0 + r.y1) / 2.0
                if (len(t) <= 16 and sz <= body + 0.5 and region.y0 <= cy <= region.y1
                        and r.intersects(region + (-24, 0, 24, 0)) and inside(r)
                        and not CAPTION.match(t)):
                    region |= r
            for r in rot:
                if r.intersects(region + (-14, -4, 14, 4)) and inside(r):
                    region |= r
            region = (region + (-4, -4, 4, 4)) & page.rect
            # Doesn't cross into the caption block (a 4pt margin used to bite halfway into the caption's top line)
            if below:
                region.y0 = max(region.y0, cblock.y1 + 1)
            else:
                region.y1 = min(region.y1, cblock.y0 - 1)
                region.y0 = max(region.y0, top + 1)
            if regions is not None:
                regions.setdefault(page.number, []).append(fitz.Rect(region))
            if not outdir:
                got.append((num, None, ctext))
                continue
            path = os.path.join(outdir, "fig_%d.png" % num)
            if path in [g[1] for g in got]:
                path = os.path.join(outdir, "fig_%d_p%d.png" % (num, page.number + 1))
            page.get_pixmap(dpi=dpi, clip=region).save(path)
            got.append((num, path, ctext))
    # If a number was already cropped, a figure-less "Fig. 1. ..." is a body mention — not reported as missed
    done = {g[0] for g in got}
    missed = [m for m in missed if m[0] not in done]
    return got, missed


def convert(pdf_path, outdir):
    doc = fitz.open(pdf_path)
    try:
        md = to_markdown(doc)
        os.makedirs(outdir, exist_ok=True)
        mdp = os.path.join(outdir, os.path.splitext(os.path.basename(pdf_path))[0] + ".md")
        with io.open(mdp, "w", encoding="utf-8") as f:
            f.write(md)
        figs, missed = figure_crops(doc, os.path.join(outdir, "figs"))
    finally:
        doc.close()
    return mdp, figs, missed


def main(argv=None):
    ap = argparse.ArgumentParser(description="paper PDF -> paper.md + figure PNGs")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default=None, help="output folder (default: next to the PDF)")
    a = ap.parse_args(argv)
    out = a.out or os.path.dirname(os.path.abspath(a.pdf))
    mdp, figs, missed = convert(a.pdf, out)
    with io.open(mdp, encoding="utf-8") as f:
        n_head = sum(1 for ln in f if ln.startswith("#"))
    print("=> %s  (%d heading line(s))" % (mdp, n_head))
    for num, path, cap in sorted(figs):
        print("   figure %-3d %s  \"%s\"" % (num, os.path.basename(path), cap[:50]))
    for num, pg, cap in missed:
        print("   figure %d (p.%d) couldn't be cropped. Look at the page directly and crop it "
              "by hand if needed.  \"%s\""
              % (num, pg, cap[:40]))
    if ADVP_SEEN[0]:
        print("   swapped the broken symbols from a publisher's math font (AdvP...) "
              "(þ->+, ¼->= etc). Cross-check the +, =, and parentheses in formulas against the "
              "PDF once.")
    print("   open each cropped figure one by one. Neighboring text may have bled in, or a "
          "piece may be cut off.")
    print("   tables came through as text only. Copy the cell structure by hand; deckcheck "
          "cross-checks the values against paper.md.")
    print("   skim through paper.md once to check the heading lines are right. They were "
          "inferred from font size.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
