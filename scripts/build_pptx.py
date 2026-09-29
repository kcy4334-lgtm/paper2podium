# -*- coding: utf-8 -*-
"""`slides.yaml` -> `talk.pptx` (the PowerPoint edition).

    python scripts/build_pptx.py slides.yaml -o out/talk.pptx

Does not use PDF-to-PPTX conversion. Converting turns every page into a
  single flat image, so not even one typo can be fixed at the venue. Here the
  title, body, and tables are all real text.

Fonts: PPTX cannot embed fonts. It only uses what is installed on the venue
  PC (default Segoe UI). Keeping the deck's Fira Sans as-is breaks on site,
  replaced by a substitute font.

Tables: PowerPoint never reports the rendered row height. When a cell wraps,
  its row grows taller, but there is no way to find that out, so it cannot
  be corrected afterward. So this estimates the text width and warns in advance.

There is no vertical-centering, so the bottom ends up hollow -> body blocks
  are filled from the top, and table row heights are grown instead.
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckspec
# Used to measure the figure's aspect ratio. Without this line, `place_picture`
#   swallowed a NameError and stretched every figure to 4:3.
from PIL import Image  # noqa: E402
import design
from deckspec import (load, MARKUP, strip_markup, math_to_text,  # noqa: E402
                      _which)

try:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.util import Inches, Pt, Emu
except ImportError:  # pragma: no cover
    raise SystemExit("python-pptx is required:  pip install python-pptx")

# There is no guarantee the venue PC runs Windows. This artifact exists
#   precisely to hedge against "the venue's computer," so a Windows-only
#   default would defeat its own purpose. `Segoe UI` does not exist on
#   macOS, and neither does `Consolas`; both get silently substituted, and
#   the moment that happens every column-width calculation for tables goes
#   wrong (the warning here is keyed off `FONT`).
#
#   The default is set to something present on Windows, macOS, and Office
#   everywhere. Arial ships with every Office install, and so does Courier
#   New. If the venue is definitely Windows, set `meta.pptx_font: Segoe UI`
#   to switch back.
FONT = "Arial"
MONO = "Courier New"
# Only list what is known; warn if given a name that is not here.
SAFE_FONTS = {"Arial", "Helvetica", "Times New Roman", "Courier New",
              "Verdana", "Georgia", "Trebuchet MS", "Tahoma"}


def _rgb(h):
    """`design.py`'s `#RRGGBB` into a python-pptx color."""
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# Color comes from a single place, `design.py`. Writing it separately here
#   would drift from the deck and the figures, and nobody would notice while
#   the values happen to still match; in fact, only the figure side was
#   changed once and it drifted from the body's red.
DARK = _rgb(design.INK)                # title band
BRAND = RGBColor(0xEB, 0x81, 0x1B)     # progress bar: metropolis's accent color
INK = _rgb(design.INK)
MUTE = _rgb(design.INK2)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

MARGIN, TOP = 0.55, 1.02
# Same ratio as the deck. Deck slide height 255pt, PPTX 540pt: multiply the
#   deck's pt by this ratio. Setting them separately once made body text
#   come out at 80% of the deck's size and footnotes at 70%.
PX = 540.0 / 255.0
T_TITLE = round(12 * PX)      # \large: metropolis title band
T_BODY = round(10 * PX)       # body
T_SMALL = round(8 * PX)       # \footnotesize: footnotes/captions
T_LEAD = round(9 * PX)        # \small: a slide's lead
T_FINE = round(7 * PX)        # \scriptsize: fine print
T_BIG = round(deckspec.BIG_PT_NUMBER * PX)


def deck_pt(pt):
    """Deck pt -> PPTX pt."""
    return pt * PX


# Values lowered so both are above WCAG AA (4.5:1) on both a white background
# and the block background. The progress bar (BRAND) is not text, so it keeps
# its original orange.
HI = _rgb(design.HI_TEXT)
# Semantic colors: red for the bad side (a judged regression), green for the
# good side (an effect/recommendation).
HIT = _rgb(design.text_of("hit"))
SAFE = _rgb(design.text_of("safe"))
# Bright variants for a dark background (impact slides): same values as the deck
HIT_LT = _rgb(design.text_of("hit", dark_bg=True))
SAFE_LT = _rgb(design.text_of("safe", dark_bg=True))


_MINUS = re.compile(r"(?<![\w.\-])-(?=\d)")


def block_colours(kind):
    """(background, title color) of a highlight box. Matches the deck's
    `block`/`alertblock`/`exampleblock`.

    PPTX once used a gray box with a black title regardless of kind, and the
      deck's red "alert" title and green "good" title had disappeared.
    """
    return (_rgb(design.NEUTRAL_FILL),
            {"alert": HIT, "good": SAFE}.get(str(kind or "plain"), INK))


def add_runs(p, text, size, color, bold=False, font=None):
    """Split `**bold**` and `<hi>highlight</hi>` into runs, one run per span.

    One example deck used bold text on almost every slide (90%) to point out
      "look here." Without splitting into runs, the asterisks would print
      literally on screen.
    """
    # Using `font=FONT` as a default argument binds it at definition time:
    #   even if the spec changes the font later, this alone would keep the
    #   old value. It has to be resolved inside the function body.
    font = font or FONT
    # PowerPoint does not know LaTeX. Passing `$p<10^{-4}$` through as-is
    #   prints the dollar signs and braces on screen too, so without this
    #   the two artifacts silently diverge.
    text = math_runs(text)
    # A hyphen before a digit becomes a minus sign. PowerPoint breaks the
    #   line right after a hyphen, splitting "cost -" / "0.4" across two
    #   lines. The deck was fine because it uses `\textminus`. There is no
    #   line break right after U+2212.
    text = re.sub(r"(?<![\w\-])-(?=\d)", u"−", str(text))
    _emit(p, str(text), size, font, color, bold, False, False)
    _end_mark(p, size)


# Placeholder markers to print a math-derived subscript/superscript as a
# real baseline-shifted run; they never reach the screen
SUB_ON, SUB_OFF, SUP_ON, SUP_OFF = u"\ue030", u"\ue031", u"\ue032", u"\ue033"


def _script_char(ch):
    """A character that is already a Unicode super/subscript (², ᵐ, ₙ), which
    was getting mixed into a run because `isalnum()` is true for it."""
    import unicodedata
    n = unicodedata.name(ch, "")
    return "SUPERSCRIPT" in n or "SUBSCRIPT" in n or n.startswith("MODIFIER LETTER")


def _mark_scripts(t):
    """Turn a math-converted `_(...)` / `_x` / `^(...)` / `^x` into a
    placeholder marker; parentheses are matched by depth."""
    out, i = [], 0
    while i < len(t):
        c = t[i]
        if c in "_^" and i + 1 < len(t) and (i == 0 or not t[i - 1].isspace()):
            on, off = (SUB_ON, SUB_OFF) if c == "_" else (SUP_ON, SUP_OFF)
            if t[i + 1] == "(":
                d, j = 0, i + 1
                while j < len(t):
                    d += {"(": 1, ")": -1}.get(t[j], 0)
                    if d == 0:
                        break
                    j += 1
                if j < len(t):
                    out.append(on + _mark_scripts(t[i + 2:j]) + off)     # a script inside a script too
                    i = j + 1
                    continue
            elif not t[i + 1].isspace():
                k = i + 1
                # Now that the braces are gone, `_model` / `_drop` / `_ff` are
                #   subscript as a whole chunk. Lowering only one letter would
                #   otherwise print "dₘodel" / "P_d rop." Lower it as long as
                #   alphanumerics keep running.
                # But stop at a character that is already a script character
                #   (the ² in `d_model²`), or "model2" gets lowered whole.
                if t[i + 1].isalnum():
                    while (k + 1 < len(t) and t[k + 1].isalnum()
                           and not _script_char(t[k + 1])):
                        k += 1
                # A combining accent is lowered together with its base letter (ψ̄)
                while k + 1 < len(t) and u"\u0300" <= t[k + 1] <= u"\u036f":
                    k += 1
                out.append(on + t[i + 1:k + 1] + off)
                i = k + 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def math_runs(text):
    """Math glyphs for PPTX: on top of `math_to_text`, turn scripts into
    baseline-shifted runs.

    A character with no Unicode subscript form (ψ, θ, T) would otherwise
      print as plain text, "V_ψ" / "Q_θ1." In the deck these are real
      scripts. PowerPoint can look the same with a baseline-shifted run.
      The underscore outside math (`max_len`) is left untouched.
    """
    held = deckspec.hold_currency(str(text or ""))
    held = re.sub(r"\$([^$]*)\$", lambda m: _mark_scripts(math_to_text("$" + m.group(1) + "$")), held)
    return math_to_text(held.replace(deckspec.CUR, "\\$"))


def _end_mark(p, size):
    """Write the font size onto the end-of-paragraph mark (`endParaRPr`).

    Without it, PowerPoint treats the end-of-paragraph mark as the default
      18pt and sizes the line to that height. A 15pt table's row rendered at
      0.40 inches instead of 0.35, so the note placed under the table
      printed over the last row, and since the file's row height was still
      0.35, fitcheck could not see it either. With it set, the row renders
      at the height written in the file.
    """
    from pptx.oxml.ns import qn
    for e in p._p.findall(qn("a:endParaRPr")):
        p._p.remove(e)
    e = p._p.makeelement(qn("a:endParaRPr"), {})
    e.set("sz", str(int(round(size * 100))))
    p._p.append(e)


def _emit(p, text, size, font, color, bold, italic, underline):
    """Split markup into runs, but recurse into nested markup too.

    Unwrapping only the outer layer left the asterisks of
      `<safe>... *whether* ...</safe>` printed literally on the PowerPoint
      screen. The inner span inherits the outer span's color and weight.
    """
    pos = 0

    def run(s, c, b, it, u, f=None):
        if not s:
            return
        # A hyphen before a digit becomes a minus sign. An ASCII `-` is a
        #   spot where PowerPoint can break the line, so "−" and "10.0" have
        #   ended up split across two lines. The deck already uses
        #   `\textminus`; this makes both artifacts print the same character.
        for seg, shift in _scripts_split(_MINUS.sub(u"\u2212", s)):
            r = p.add_run()
            r.text = seg
            r.font.size, r.font.name = Pt(size), f or font
            r.font.bold, r.font.italic = b, it
            r.font.color.rgb = c
            if shift:
                r.font._rPr.set("baseline", shift)
            if u:
                r.font.underline = True

    for m in MARKUP.finditer(text):
        run(text[pos:m.start()], color, bold, italic, underline)
        kind, inner = _which(m)
        if kind == "c":
            # Code is one fixed-width run: an asterisk inside it might be a
            #   multiplication sign or a pointer, so it is not unpacked
            run(inner, color, bold, italic, underline, MONO)
            pos = m.end()
            continue
        c = {"b": color, "i": color,
             "hit": HIT, "safe": SAFE, "hi": HI}[kind]
        # Meaning is never carried by color alone. Red and green become the
        #   same mustard shade to a red-green colorblind eye, so for the
        #   same reason as the deck, the loss side also gets an extra underline.
        _emit(p, inner, size, font, c,
              bold or kind != "i", italic or kind == "i",
              underline or (kind == "hit" and deckspec.SECOND_CHANNEL))
        pos = m.end()
    tail = text[pos:]
    if tail or pos == 0:
        for seg, shift in (_scripts_split(tail) if tail else [("", None)]):
            r = p.add_run()
            r.text = seg
            r.font.size, r.font.name = Pt(size), font
            r.font.bold, r.font.italic = bold, italic
            r.font.color.rgb = color
            if shift:
                r.font._rPr.set("baseline", shift)
            if underline:
                r.font.underline = True


# A Unicode super/subscript (β₁, 10⁻⁸) gets replaced by a mangled glyph when
#   the font lacks it: Arial has no ₁, so the table's "β₁" printed as a tofu
#   box. Uses PowerPoint's real superscript/subscript (a baseline-shifted
#   character) instead. Looks the same in any font.
_SUB_ASCII = {v: k for k, v in deckspec._SUB.items()}
_SUP_ASCII = {v: k for k, v in deckspec._SUP.items()}


def _scripts_split(s):
    """[(text, baseline shift)]. shift is None (normal), '-25000' (down), or
    '30000' (up)."""
    out, cur, mode = [], "", None
    stack = []                         # math-script placeholder markers (math_runs): can nest
    for ch in s:
        if ch in (SUB_ON, SUP_ON):
            stack.append("-25000" if ch == SUB_ON else "30000")
            continue
        if ch in (SUB_OFF, SUP_OFF):
            if stack:
                stack.pop()
            continue
        force = stack[0] if stack else None
        m = force or ("-25000" if ch in _SUB_ASCII else "30000" if ch in _SUP_ASCII else None)
        c = _SUB_ASCII.get(ch) or _SUP_ASCII.get(ch) or ch
        if m != mode and cur:
            out.append((cur, mode))
            cur = ""
        mode = m
        cur += c
    if cur or not out:
        out.append((cur, mode))
    return out


def textbox(slide, x, y, w, h, lines, size, color, align=PP_ALIGN.LEFT,
            anchor=MSO_ANCHOR.TOP, bold=False, spacing=1.15, font=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        # A bullet line gets a hanging indent. The second line would
        #   otherwise start under the bullet mark, unlike the deck (which
        #   aligns to the text). Indent by the width of the "• " mark and
        #   pull only the first line back out by that much.
        if isinstance(ln, str) and ln.startswith(u"• "):
            _m = int(size * 0.62 * 12700)
            _pp = p._p.get_or_add_pPr()
            _pp.set("marL", str(_m))
            _pp.set("indent", str(-_m))
        add_runs(p, ln, size, color, bold, font)
    return tb


def find_img(p, base, figdir):
    """Where the figure actually is. None if it is not there.

    Same rule as the deck side: check where the artifact will be placed
      first, and also check the spec folder. Using `-o out/talk.pptx` and
      `-o out/figs` exactly as the docs say used to check only the spec
      folder, so it dropped the figure entirely and only printed a warning.
    """
    if os.path.isabs(p):
        return raster(p) if os.path.isfile(p) else None
    roots = [base] if isinstance(base, str) else list(base or [])
    for r in roots:
        if r and os.path.isfile(os.path.join(r, figdir, os.path.basename(p))):
            return raster(os.path.join(r, figdir, os.path.basename(p)))
    return None


def raster(path):
    """PowerPoint cannot embed a PDF/EPS figure, so this makes a PNG next to
    it and uses that instead.

    A LaTeX paper's figures are usually PDF (sometimes EPS). `add_picture`
      either died trying to take it as-is, or a person had to make the PNG
      by hand, as with a paper with only EPS figures. EPS gets converted to
      PDF by `build.py` first (`epstopdf`).
    """
    stem, ext = os.path.splitext(path)
    if ext.lower() not in (".pdf", ".eps"):
        return path
    png = stem + ".png"
    if os.path.isfile(png) and os.path.getmtime(png) >= os.path.getmtime(path):
        return png
    pdf = stem + ".pdf"
    if not os.path.isfile(pdf):
        return path
    try:
        try:
            import pymupdf as fitz
        except ImportError:      # PyMuPDF before 1.24.3 has only the old import name
            import fitz
        doc = fitz.open(pdf)
        try:
            doc[0].get_pixmap(dpi=200, alpha=False).save(png)
        finally:
            doc.close()
        return png
    except Exception as e:          # fitz is missing, or the PDF is broken: report it and fall back to the original
        print("   Could not convert figure to PNG: %s (%s)" % (pdf, e))
        return path


def _img_path(p, base, figdir):
    """Expected path to use in a warning: the first candidate."""
    if os.path.isabs(p):
        return p
    roots = [base] if isinstance(base, str) else list(base or [])
    return os.path.join(roots[0] if roots else "", figdir, os.path.basename(p))


# Name of the page-number box. The checker finds it by name, not by shape.
PAGENUM_TAG = "p2t-pagenum"


def band(slide, prs, s, npage):
    """metropolis-style title band + progress bar + page number."""
    W = prs.slide_width / 914400.0
    bar = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.86))
    bar.fill.solid()
    bar.fill.fore_color.rgb = DARK
    bar.line.fill.background()
    bar.shadow.inherit = False
    tf = bar.text_frame
    tf.margin_left, tf.margin_top = Inches(MARGIN), Inches(0.12)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT      # A shape defaults to centered. metropolis is left-aligned.
    add_runs(p, s.get("title") or "", T_TITLE, WHITE, bold=True)
    if s.get("page"):
        frac = s["page"] / float(npage)
        pb = slide.shapes.add_shape(1, 0, Inches(0.86), int(prs.slide_width * frac),
                                    Inches(0.045))
        pb.fill.solid()
        pb.fill.fore_color.rgb = BRAND
        pb.line.fill.background()
        pb.shadow.inherit = False
        tb = textbox(slide, W - 1.15, prs.slide_height / 914400.0 - 0.45, 0.8, 0.3,
                     ["%d/%d" % (s["page"], npage)], T_SMALL, MUTE, PP_ALIGN.RIGHT)
        # Tag the shape with a name. Finding the page number by its shape
        #   catches body text too: a footnote's `ratio 27/14` was read as
        #   "page 27 of a 14-page deck" and section G threw 17 failures. The
        #   deck was fine and the checker was wrong. If the writer leaves a
        #   marker, the reader never has to guess.
        tb.name = PAGENUM_TAG


A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _border(pr, side, width_pt=None):
    """Remove one side's border (width_pt=None), or add it as a solid line."""
    from lxml import etree
    tag = A_NS + side
    for old in pr.findall(tag):
        pr.remove(old)
    # The order is fixed (lnL, lnR, lnT, lnB). Insert it anywhere else and
    #   PowerPoint ignores it.
    order = ["lnL", "lnR", "lnT", "lnB"]
    ln = etree.Element(tag)
    if width_pt is None:
        ln.set("w", "0")
        etree.SubElement(ln, A_NS + "noFill")
    else:
        ln.set("w", str(int(width_pt * 12700)))
        ln.set("cap", "flat")
        fill = etree.SubElement(ln, A_NS + "solidFill")
        clr = etree.SubElement(fill, A_NS + "srgbClr")
        clr.set("val", "23373B")
    after = [pr.find(A_NS + s) for s in order[:order.index(side)]]
    after = [x for x in after if x is not None]
    if after:
        after[-1].addnext(ln)
    else:
        pr.insert(0, ln)


def booktabs(tbl, has_header):
    """Remove the vertical lines and keep only the three horizontal rules,
    the same look as the deck's booktabs.

    Do not draw the lines as shapes. Because PowerPoint never reports the
      rendered row height, the moment a header wraps to two lines, a line
      drawn at a fixed position cuts straight through the row. It has to go
      in as a cell border so it moves with the row.
    """
    nr = len(tbl.rows)
    last_head = 0 if has_header else -1
    for ri, r in enumerate(tbl.rows):
        for c in r.cells:
            pr = c._tc.get_or_add_tcPr()
            _border(pr, "lnL")
            _border(pr, "lnR")
            _border(pr, "lnT", 1.25 if ri == 0 else None)
            _border(pr, "lnB",
                    1.25 if ri == nr - 1 else (0.75 if ri == last_head else None))


def table_height(shape):
    """The height (in inches) the table actually occupies: the sum of row
    heights, counting wrapped lines too."""
    return sum(r.height for r in shape.table.rows) / 914400.0


def add_table(slide, t, x, y, w, warn, size=None, rh=0.34, where=""):
    """Place a table and return the shape. Height is `table_height(shape)`.

    Row height is set by counting the wrapped lines. PowerPoint only grows
      a wrapped row on screen and leaves the file's height unchanged. So
      text placed under the table would print on top of the table instead,
      and fitcheck could not see it either, since it reads the file's height.
    """
    header = t.get("header")
    rows = t["rows"]
    nr, nc = len(rows) + (1 if header else 0), len(rows[0])
    size = size or (T_BODY - 2)
    shape = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w),
                                   Inches(rh * nr))
    tbl = shape.table
    # The default style draws a full grid. Removing tableStyleId alone is
    #   not enough, since PowerPoint puts its default borders back. Every
    #   cell's border has to be cleared explicitly to match the deck's
    #   booktabs look (three horizontal rules), or the two artifacts diverge.
    tbl._tbl.tblPr.set("firstRow", "1")
    for el in tbl._tbl.tblPr.findall(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId"):
        tbl._tbl.tblPr.remove(el)
    booktabs(tbl, bool(t.get("header")))

    # Column width is fit to the content. Splitting evenly ignores the
    #   content, and since the deck side (`tabular`) fits to content, the
    #   two artifacts diverge: the same table is fine in the PDF and wraps
    #   in PowerPoint. PowerPoint does not report row height, so it cannot
    #   even be fixed after the fact.
    data_all = ([header] if header else []) + rows
    _em = size * 0.55 / 72.0
    need, floor_ = [], []
    for c in range(nc):
        cells = [strip_markup(str(r[c])) for r in data_all if c < len(r)
                 and not (len(r) > 1 and str(r[0] or "").strip()
                          and not any(str(x or "").strip() for x in r[1:]))]
        # Width is measured with the actual font. The 0.55em-per-character
        #   estimate reads a bold header as narrower, so "Heads" was wider
        #   than its column and split into "Head/s." A header prints bold,
        #   so it is measured bold.
        def _w(x, b):
            return deckspec.text_width_in(math_to_text(x), size, b, FONT)
        _hb = [bool(header) and ri == 0 for ri in range(len(cells))]
        longest = max((_w(x, b) for x, b in zip(cells, _hb)), default=_em)
        word = max((_w(wd, b) for x, b in zip(cells, _hb) for wd in x.split()), default=_em)
        need.append(max(0.45, longest + 0.24))
        # Keep the single longest word from wrapping: a number is one chunk
        floor_.append(min(need[-1], max(0.40, word + 0.24)))
    tot = sum(need) or 1.0
    if tot > w:
        # Shrinking proportionally split short numeric columns character by
        #   character ("0 . 0 1"). Give every column at least its longest
        #   word, and split the remaining width in proportion to how much
        #   more each one needs.
        fl = sum(floor_)
        if fl >= w:
            need = [v * w / fl for v in floor_]
        else:
            extra = [need[c] - floor_[c] for c in range(nc)]
            ex = sum(extra) or 1.0
            need = [floor_[c] + (w - fl) * extra[c] / ex for c in range(nc)]
        tot = w
    slack = (w - tot) / nc
    colr = [need[c] + slack for c in range(nc)]   # actual column width: the warning reads this too
    for c in range(nc):
        tbl.columns[c].width = Emu(int(Inches(colr[c])))
    data = data_all
    # Same rule as the deck: decide from the body rows, excluding the header row
    _al = t.get("align") or deckspec.column_align(t.get("rows") or [])
    wrapped = []
    for ri, row in enumerate(data):
        # Number of wrapped lines, counted with the same estimate (0.55em)
        # used to measure column width
        _span = (len(row) > 1 and str(row[0] or "").strip()
                 and not any(str(c or "").strip() for c in row[1:]))
        _lines = 1
        for ci, val in enumerate(row):
            if _span and ci > 0:
                break
            _w = (w if _span else colr[ci]) - 0.20
            _lv, _rest = deckspec.cell_indent(val)
            _txt = strip_markup(str(_rest if val is not None else ""))
            # The wrap estimate is 0.50em. Reusing the 0.55 used for column
            #   width counted rows that do not actually wrap as two lines,
            #   stretching the table into the footnote. Width stays
            #   generous; the line count needs to be exact.
            # Measured with the actual font: an average-width estimate
            #   missed the header "FDR (%)" wrapping.
            _n = deckspec.wrap_count(deckspec.math_to_text(_txt),
                                     max(0.2, _w - _lv * size / 72.0), size,
                                     # Measured bold if it has a bold span,
                                     #   since it is wider. Measuring it as
                                     #   regular weight counted "**charge
                                     #   rate** per pack of cells" as one
                                     #   line, but it wrapped, and the text
                                     #   under the table printed onto the
                                     #   last row
                                     bold=(bool(header) and ri == 0) or bool(
                                         re.search(r"\*\*|<(?:hit|safe|hi)>", str(_rest))),
                                     font=FONT)
            if _n > 1:
                wrapped.append((ri + 1, ci + 1, _txt[:24]))
            _lines = max(_lines, _n)
        tbl.rows[ri].height = Emu(int(Inches(
            max(rh, _lines * size * 1.18 / 72.0 + 0.10))))
        # A row where only the first cell is filled is a group heading
        #   (`\multicolumn` on the deck side). Without merging the cells, it
        #   sticks to the left cell and reads like a list item, and the shape
        #   diverges from the deck. Merge it and italicize it to match.
        span = (len(row) > 1 and str(row[0] or "").strip()
                and not any(str(c or "").strip() for c in row[1:]))
        if span:
            cell = tbl.cell(ri, 0)
            cell.merge(tbl.cell(ri, nc - 1))
            cell.margin_left = Inches(0.10)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT
            add_runs(p, row[0], size, INK)
            for r in p.runs:
                r.font.italic = True
            continue
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.10)  # 0.06 makes numbers touch
            # Leading whitespace is indentation: 1em per level, same as the deck
            _lv, _rest = deckspec.cell_indent(val)
            if _lv:
                cell.margin_left = Inches(0.10 + _lv * size / 72.0)
                val = _rest
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            # Uses the same rule as the deck: a numeric column is
            #   right-aligned, a text column is left-aligned.
            p.alignment = (PP_ALIGN.RIGHT if ci < len(_al) and _al[ci] == "r"
                           else PP_ALIGN.LEFT)
            plain = "" if val is None else strip_markup(val)
            add_runs(p, "" if val is None else val, size,
                     INK, bool(header and ri == 0))
    # Frame height also set from the sum of row heights: this is the value fitcheck reads
    shape.height = Emu(int(Inches(table_height(shape))))
    if wrapped:
        # One line per table, with the slide number attached. Emitting one
        #   line per cell turns the warnings into a pile nobody reads. Space
        #   is now reserved for however much it wraps, so nothing overlaps.
        warn.append(u"%s%d table cell(s) wrap in PPTX (e.g. row %d, col %d \"%s\"); "
                    u"space was reserved for the wrap. Shorten the cell text if you don't want it to wrap"
                    % (((where + " ") if where else "", len(wrapped)) + wrapped[0]))
    return shape


def text_h(lines, w_in, pt, spacing=1.25, bold=False):
    """The height (in inches) this text occupies at width `w_in`. Counts
    wrapped lines.

    Counting one bullet as one 0.34-inch line put the next block on top of a
      bullet that wrapped to three lines in a narrow column. Character width
      is estimated at an average 0.52em: erring wide leaves a gap, erring
      narrow overlaps text. So it errs wide.
    """
    # Since wrapping happens word by word, the characters that fit on a line
    #   run a bit under the average width (5%). Measuring exactly flush made
    #   the end of a wrapped bullet touch the next block.
    # Subtract the text box's inner margin (0.1in each side), and wrap word by
    # word, measured with the actual font
    n = 0
    for ln in lines:
        s = deckspec.plain(str(ln or ""))
        # Bold text is wider: measuring it at regular weight counted a bold
        # name as one line, but it wrapped
        n += deckspec.wrap_count(s, max(0.3, w_in - 0.22), pt, bold=bold or '**' in str(ln),
                                 font=FONT)
    # One PowerPoint line = font size x 1.2 x line spacing (value measured
    #   from the render). Missing the 1.2 undercounted the height by 17%,
    #   and the block under a seven-line bullet touched the last line.
    return n * pt * 1.2 * spacing / 72.0 + 0.06 * len(lines)


def foot_top(s, H, CW):
    """Position (in inches) where a slide's footnote (`foot`) starts. The
    footnote, fine print, and box stack up from the bottom.

    The footnote's position and the limit on the content above it read the
      same function.
    """
    if s.get("kind") in ("title", "standout"):
        return H - 0.62
    h = 0.0
    if s.get("foot"):
        h += text_h(s["foot"], CW, T_SMALL, 1.25) + 0.08
    if s.get("fine"):
        h += text_h(s["fine"], CW, T_SMALL - 1, 1.15)
    if s.get("block"):
        # A box is drawn at its own text's height. Pinned to a fixed 1.30
        #   instead, a tall box climbed above the footnote. Measured with
        #   the same function as the one that draws it.
        h += max(1.30, block_height(s["block"], CW)[2] + 0.12)
    return H - 0.62 - h


def block_height(b, CW):
    """A highlight box's (title height, text height, total height), in inches.
    Used together by the code that draws it and the code that places it."""
    _tt = text_h([b.get("title") or ""], CW - 0.32, T_BODY - 1)
    _bt = text_h([b.get("text") or ""], CW - 0.32, T_SMALL + 1)
    return _tt, _bt, 0.08 + _tt + 0.04 + _bt + 0.10


GRID_COL_MIN_IN = 1.35  # minimum grid column width (inches), so the header/result text fits in two lines


def add_grid(slide, f, x, y, w, H, base, figdir, warn):
    """Image grid: rows are viewpoints, columns are conditions, a result
    outline on the last row.

    Counterpart to the deck's `grid_body`. PowerPoint has no clean way to
      put images inside a table, so this lays them out by raw coordinates.
      That makes the two sides easy to drift apart, and there have been six
      such bugs; `outcheck` exists to catch them.
    A border does not use color alone. Failure is a thick solid line, success
      a thin one (same as the deck).
    """
    g = f["grid"]
    imgs = g["images"]
    nr, nc = len(imgs), len(imgs[0])
    cols = list(g.get("cols") or [""] * nc)
    rows = list(g.get("rows") or [""] * nr)
    mark = list(g.get("mark") or [None] * nc)
    cap = list(g.get("caption") or [""] * nc)

    lab_w = 0.75 if any(rows) else 0.0
    head_h = 0.28 if any(cols) else 0.0
    cap_h = 0.26 if any(cap) else 0.0
    if f.get("lead"):
        textbox(slide, x, y, w, 0.4, [f["lead"]], T_SMALL, INK, PP_ALIGN.CENTER)
        y += 0.45
    avail_w = w - lab_w
    avail_h = H - y - 0.55 - head_h - cap_h
    gap = 0.04
    cw = (avail_w - gap * (nc - 1)) / nc
    # A cell's aspect ratio follows the photo's own ratio. Pinning it to
    #   0.75 and forcing both width and height stretched a square frame into
    #   2.84x1.59.
    ar = 4.0 / 3.0
    for row in imgs:
        for src in row:
            p0 = find_img(src, base, figdir)
            if p0:
                try:
                    with Image.open(p0) as im:
                        ar = float(im.width) / max(1, im.height)
                except (OSError, ValueError):
                    pass
                break
        else:
            continue
        break
    ch = min(cw / ar, (avail_h - gap * (nr - 1)) / nr)
    iw = min(cw, ch * ar)                # photo width: centered in the cell
    # When the figure is narrower than the cell, fit the column width to
    #   the figure and center the grid, same as the deck. Otherwise the row
    #   label sits one cell away from the first image.
    # The width a label needs to fit on one line is the floor: a wrapped
    # line steals space from the figure (same as the deck).
    lab_in = max([len(strip_markup(str(t_))) for t_ in cols + cap] or [0]) \
        * 0.52 * (T_SMALL - 3) / 72.0 + 0.12
    cw_fit = max(GRID_COL_MIN_IN, iw + 0.10, lab_in)
    if cw_fit < cw:
        cw = cw_fit
        x += (w - (lab_w + nc * cw + gap * (nc - 1))) / 2.0

    if any(cols):
        for ci in range(nc):
            textbox(slide, x + lab_w + ci * (cw + gap), y, cw, head_h,
                    [cols[ci]], T_SMALL - 3, INK, PP_ALIGN.CENTER)
        y += head_h
    for ri in range(nr):
        yy = y + ri * (ch + gap)
        if lab_w:
            textbox(slide, x, yy + ch / 2 - 0.12, lab_w - 0.06, 0.24,
                    [rows[ri]], T_SMALL - 3, MUTE, PP_ALIGN.RIGHT)
        for ci in range(nc):
            xx = x + lab_w + ci * (cw + gap)
            src = imgs[ri][ci]
            p = find_img(src, base, figdir)
            px = xx + (cw - iw) / 2.0
            if p:
                slide.shapes.add_picture(p, Inches(px), Inches(yy),
                                         width=Inches(iw), height=Inches(ch))
            else:
                warn.append("Grid figure not found: %s" % _img_path(src, base, figdir))
                textbox(slide, xx, yy + ch / 2 - 0.12, cw, 0.24, ["[missing]"],
                        T_SMALL - 2, MUTE, PP_ALIGN.CENTER, font=MONO)
            m = mark[ci] if ri == nr - 1 else None
            if m:
                box = slide.shapes.add_shape(1, Inches(px), Inches(yy),
                                             Inches(iw), Inches(ch))
                box.fill.background()
                box.shadow.inherit = False
                box.line.color.rgb = HIT if m == "fail" else SAFE
                box.line.width = Pt(2.5 if m == "fail" else 1.0)
                # Failure gets a thick solid line, same as the deck (this used to be the one dashed line)
    y += nr * ch + (nr - 1) * gap
    if any(cap):
        for ci in range(nc):
            textbox(slide, x + lab_w + ci * (cw + gap), y + 0.04, cw, cap_h,
                    [cap[ci]], T_SMALL - 3, MUTE, PP_ALIGN.CENTER)
    if any(cap):
        y += cap_h + 0.04
    # A figure's caption goes right under the grid. Printing it at a fixed
    #   position at the bottom of the slide (H - 0.95) would put it in the
    #   same spot as the slide's footnote.
    if f.get("caption"):
        ch_ = text_h([f["caption"]], w, T_SMALL)
        textbox(slide, x, y + 0.04, w, ch_, [f["caption"]], T_SMALL, MUTE,
                PP_ALIGN.CENTER)
        y += ch_ + 0.06
    return y


def place_picture(sl, path, x, y, w_max, h_max, f=None, warn=None):
    """Place a figure with both axes bound and return its actual bottom.

    Giving only `add_picture(..., width=...)` lets the height come out as
      anything. Then the following bullet prints at a fixed position and
      runs right over the figure: rendering the PPTX has measured 0.54-2.58
      inches of overlap across four slides this way. `traps.md`'s note that
      "binding only one axis does not bind the box" had only been fixed on
      the deck side.
    """
    if f and f.get("crop") and path and os.path.isfile(path):
        path = deckspec.crop_image(path, f["crop"])      # same cropped figure as the deck
    # The only thing caught here is a file that cannot be opened.
    #   `except Exception` was also swallowing a NameError from a missing
    #   import, and every figure was silently turned into 4:3.
    try:
        with Image.open(path) as im:
            iw, ih = im.width, im.height
    except (OSError, ValueError):
        iw, ih = 4, 3
    ar = float(iw) / max(1, ih)
    w = min(w_max, h_max * ar)
    h = w / ar
    px = x + (w_max - w) / 2.0
    sl.shapes.add_picture(path, Inches(px), Inches(y),
                          width=Inches(w), height=Inches(h))
    # Same outline as the deck (`figure.highlight`): putting it on only one side splits the two artifacts apart
    import build_deck as _bd
    for hx, hy, hw, hh, lab, mk, at in _bd.highlights(f, path):
        col = {"hit": HIT, "safe": SAFE}.get(mk, HI)      # no mark = an accent color with no judgment attached
        box = sl.shapes.add_shape(1, Inches(px + hx * w), Inches(y + hy * h),
                                  Inches(hw * w), Inches(hh * h))
        box.fill.background()
        box.line.color.rgb = col
        box.line.width = Pt(2.0)
        box.shadow.inherit = False
        box.name = deckspec.HIGHLIGHT_TAG
        if lab:
            # Width comes from the text: fitting it to the box width wraps even a short label to two lines
            # Measured with the actual font, and never wrapped. A
            #   character-count estimate has wrapped eight characters like
            #   "GW150914" to two lines. A label is one line on principle.
            _lw = deckspec.text_width_in(deckspec.plain(lab), T_FINE, True, FONT) + 0.3
            _ly = {"above": y + hy * h - 0.30, "below": y + (hy + hh) * h + 0.02,
                   "inside": y + hy * h + 0.02}[at]
            # A label is kept within the figure's width. Stretching from
            #   the box's left edge to the right has covered the table
            #   header of the neighboring column outside the figure. Pull
            #   it left if it overflows, and align it to the figure's left
            #   edge if it is wider than the figure.
            _bw = max(_lw, hw * w)
            # Same rule as the deck: a box on the right half aligns its label to the box's right edge
            _right = hx + hw / 2.0 > 0.5
            _lx = (px + (hx + hw) * w - _bw) if _right else px + hx * w
            _lx = min(_lx, px + w - _bw)
            _lx = max(_lx, px)
            if _bw > w + 0.05 and warn is not None:
                warn.append(u"Label %r on the figure is wider than the figure. Shorten it" % deckspec.plain(lab)[:30])
            # The text inside the box goes the same way. When the box was as
            #   wide as the highlight itself, aligning the box right still
            #   left the text stuck to the left, sitting on top of the code
            #   text instead of matching the deck (right-aligned).
            tb = textbox(sl, _lx, _ly, _bw, 0.28,
                         [lab], T_FINE, col, PP_ALIGN.RIGHT if _right else PP_ALIGN.LEFT,
                         bold=True)
            tb.text_frame.word_wrap = False
            tb.name = deckspec.HIGHLIGHT_TAG
    return y + h


def _part_text_h(q, w0, fine=False):
    """A block's text height (in inches), actually measured at this
    column's width. Excludes the figure/table body."""
    small = fine or q.get("size") == "fine"
    ts = T_SMALL - 1 if small else T_SMALL
    tb = T_BODY - 2 if small else T_BODY - 1
    h = 0.0
    if q.get("head"):
        h += text_h([q["head"]], w0, T_SMALL) + 0.06
    if q.get("bullets"):
        h += text_h([bullet_line(b) for b in q["bullets"]], w0, tb) + 0.1
    if q.get("text"):
        t_ = q["text"]
        h += text_h([t_] if isinstance(t_, str) else list(t_), w0, ts) + 0.1
    cap = (q.get("figure") or {}).get("caption")
    if cap:
        h += text_h([cap], w0, ts) + 0.08
    return h


def draw_pane(sl, pane, x0, yy, w0, s, side, base, figdir, warn, H,
              fine=False):
    """One column of a two-column layout, or one block within that column.
    Returns the new bottom (inches).

    Counterpart to the deck side's `pane_body`: the order must match. This
      file has already gotten that spot wrong four times (a chart inside a
      column, a full-width figure, a table's note, a figure's bottom),
      every time by adding it to the deck and not here.
    """
    if pane.get("parts"):
        for j, p in enumerate(pane["parts"]):
            # Reserve, ahead of time, the vertical space the later blocks will
            # need. Without reserving it, an earlier block's figure eats the
            # whole column and the rest runs off screen.
            # A later block's text is subtracted measured at this column's
            #   width. Estimating character count from the slide's full
            #   width failed to count the second and third lines in a
            #   narrow column, and the text ran 0.23 inches off the slide.
            after = sum(max(deckspec.fig_reserve(q), _part_text_h(q, w0, fine)) + 0.06
                        for q in pane["parts"][j + 1:])
            yy = draw_pane(sl, p, x0, yy, w0, s, side, base, figdir, warn,
                           H - after, fine) + 0.10
        return yy
    small = fine or pane.get("size") == "fine"
    ts = T_SMALL - 1 if small else T_SMALL
    tb = T_BODY - 2 if small else T_BODY - 1
    if pane.get("head"):
        # Same rule as the deck: a small centered caption over something to look at, a bold left-aligned subheading over text
        cap = deckspec.head_is_caption(pane)
        hp = T_SMALL if cap else round(deck_pt(9))
        hh = text_h([pane["head"]], w0, hp)
        textbox(sl, x0, yy, w0, hh, [pane["head"]], hp, INK,
                PP_ALIGN.CENTER if cap else PP_ALIGN.LEFT, bold=not cap)
        yy += hh + 0.06
    # Same rule as the deck. Fixing it on only one side splits the two artifacts apart.
    ate = (pane.get("chart") is not None
           and pane["chart"].get("from", "self") == "self")
    if pane.get("table") and not ate:
        tt = pane["table"]
        _tb = add_table(sl, tt, x0, yy, w0, warn, size=ts, rh=0.30,
                        where=u"Slide %s %s column:" % (s.get("n"), side))
        yy += table_height(_tb)
        # A footnote stacks up from the bottom. If the table runs past that
        #   spot, the footnote covers the table's last row.
        _cw = sl.part.package.presentation_part.presentation.slide_width / 914400.0 - 2 * MARGIN
        if yy > foot_top(s, H, _cw) + 0.02:
            warn.append(u"Slide %s %s column: table bottom (%.2fin) in PPTX runs past "
                        u"the footnote position (%.2fin). Shorten rows/cell text, or move the table to a backup slide"
                        % (s.get("n"), side, yy, foot_top(s, H, _cw)))
        if tt.get("note"):
            textbox(sl, x0, yy + 0.08, w0, 0.4, [tt["note"]], ts - 1, MUTE)
            yy += 0.45
    # If there is no `figure`, use the image `chart` produced. This was
    #   missing, so four chart slides vanished entirely in PPTX with no
    #   warning at all.
    pf = pane.get("figure") or (
        {"path": "chart_%02d_%s.png" % (s["n"], side)}
        if pane.get("chart")
        else {"path": "diagram_%02d_%s.png" % (s["n"], side)}
        if pane.get("diagram") else None)
    # A grid inside a column. It only knew about a single file (`path`) and
    #   died with a `KeyError`; the deck draws the same spec fine.
    if pf and pf.get("grid"):
        room = H - yy - 0.75
        if pane.get("bullets"):
            room -= text_h([bullet_line(b) for b in pane["bullets"]], w0, tb) + 0.1
        if pane.get("text"):
            tv = pane["text"]
            room -= text_h([tv] if isinstance(tv, str) else list(tv), w0, tb) + 0.1
        yy = add_grid(sl, pf, x0, yy, w0, yy + max(0.8, room) + 0.55,
                      base, figdir, warn) + 0.08
        pf = None
    if pf:
        p = find_img(pf["path"], base, figdir)
        if p:
            # Both axes are bound inside a column too. Giving only the
            #   width would let a tall figure grow right off the slide;
            #   measured 1.83 inches over.
            room = H - yy - 0.75
            if pane.get("bullets"):
                room -= text_h([bullet_line(b) for b in pane["bullets"]], w0, tb) + 0.1
            if pane.get("text"):
                tv = pane["text"]
                room -= text_h([tv] if isinstance(tv, str) else list(tv),
                               w0, tb) + 0.1
            _cap = pf.get("caption")
            if _cap:
                room -= text_h([_cap], w0, T_SMALL) + 0.06
            yy = place_picture(sl, p, x0, yy, w0, max(0.7, room), pf) + 0.12
            # A figure's caption inside a column: printed in the deck but missing from PPTX
            if _cap:
                _ch = text_h([_cap], w0, T_SMALL)
                textbox(sl, x0, yy - 0.06, w0, _ch, [_cap], T_SMALL, MUTE,
                        PP_ALIGN.CENTER)
                yy += _ch
        else:
            warn.append("Figure not found: %s" % _img_path(pf["path"], base, figdir))
    if pane.get("bullets"):
        _bl = [bullet_line(b) for b in pane["bullets"]]
        _bh = text_h(_bl, w0, tb, 1.35)
        textbox(sl, x0, yy, w0, _bh, _bl, tb, INK, spacing=1.35)
        yy += _bh + 0.06
    # The order is the same as the deck: bullets -> box -> column text
    #   (`text` is the column's footnote). Only PPTX has printed the text before the box.
    pb = pane.get("block")
    if pb:
        # A box's height is measured from its own text. Pinned to a fixed
        #   0.95 inches instead, text that wraps to three lines can spill
        #   outside the box and overlap the next block.
        _tt = text_h([pb.get("title") or ""], w0 - 0.24, ts + 1)
        _bt = text_h([pb.get("text") or ""], w0 - 0.24, ts)
        _hh = 0.12 + _tt + 0.04 + _bt + 0.10
        box = sl.shapes.add_shape(1, Inches(x0), Inches(yy + 0.1),
                                  Inches(w0), Inches(_hh))
        _bg, _tc = block_colours(pb.get("kind"))
        box.fill.solid()
        box.fill.fore_color.rgb = _bg
        box.line.fill.background()
        box.shadow.inherit = False
        textbox(sl, x0 + 0.12, yy + 0.16, w0 - 0.24, _tt,
                [pb["title"]], ts + 1, _tc, bold=True)
        textbox(sl, x0 + 0.12, yy + 0.16 + _tt + 0.04, w0 - 0.24, _bt,
                [pb.get("text") or ""], ts, INK)
        yy += 0.1 + _hh + 0.08
    if pane.get("text"):
        tv = pane["text"]
        # Putting a list-valued `text` in as-is prints it as a literal
        #   Python list, `['line1', 'line2']`. This actually happened.
        lines = [tv] if isinstance(tv, str) else list(tv)
        _th = text_h(lines, w0, ts, 1.2)
        textbox(sl, x0, yy + 0.1, w0, _th, lines, ts, MUTE, spacing=1.2)
        yy += _th + 0.12
    return yy


def bullet_line(b):
    """One bullet line. `> ` indents with no bullet mark (same as the deck)."""
    txt, dot = deckspec.bullet_of(b)
    return (u"\u2022 " + txt) if dot else (u"    " + txt)


def title_pptx(sl, meta, H, CW):
    """Title slide, same layers, same proportions as the deck
    (metropolis): title / subtitle / rule / author / venue / affiliation.

    Stacked by measuring the height. A fixed 40pt title box would otherwise
      cover the author line whenever the title wrapped to two lines.
    """
    x, w = MARGIN + 0.25, CW - 0.5
    y = H * 0.24
    layers = [(meta.get("title"), round(deck_pt(14.4)), INK, True),
              (meta.get("subtitle"), round(deck_pt(10)), INK, False)]
    for txt, pt, col, bold in layers:
        if not txt:
            continue
        h = text_h([txt], w, pt, 1.15)
        textbox(sl, x, y, w, h, [txt], pt, col, PP_ALIGN.LEFT, bold=bold)
        y += h + 0.10
    y += 0.12
    ln = sl.shapes.add_connector(1, Inches(x), Inches(y), Inches(x + w), Inches(y))
    ln.line.color.rgb = BRAND
    ln.line.width = Pt(0.8)
    y += 0.25
    if meta.get("author"):
        pt = round(deck_pt(8))
        # The author line's height counts wrapped lines. Pinning it to one
        #   line has made the second line overlap the affiliation line for
        #   a paper with eleven authors.
        _ah = max(_lh(pt), text_h([str(meta["author"])], w, pt, 1.25))
        box = textbox(sl, x, y, w, _ah, [""], pt, INK, PP_ALIGN.LEFT)
        par = box.text_frame.paragraphs[0]
        a, p_ = str(meta["author"]), meta.get("presenter")
        cut = a.find(p_) if p_ else -1
        parts = ([(a[:cut], False), (p_, True), (a[cut + len(p_):], False)]
                 if cut >= 0 else [(a, False)])
        for txt, und in parts:
            if not txt:
                continue
            r = par.add_run()
            r.text = txt
            r.font.size = Pt(pt)
            r.font.name = FONT
            r.font.color.rgb = INK
            r.font.underline = und
        # The end-of-paragraph mark must be the last child. More runs were
        # appended, so it is re-attached
        _end_mark(par, pt)
        y += _ah + 0.04
    if meta.get("venue"):
        pt = round(deck_pt(8))
        textbox(sl, x, y, w, _lh(pt), [meta["venue"]], pt, INK, PP_ALIGN.LEFT)
        y += _lh(pt) + 0.10
    inst = deckspec.institute_lines(meta)
    if inst:
        pt = round(deck_pt(6))
        textbox(sl, x, y, w, _lh(pt, len(inst)), inst, pt, INK, PP_ALIGN.LEFT)


def _lh(pt, lines=1, gap=1.25):
    """Height (inches) that n lines take up at font size pt."""
    return lines * pt * gap / 72.0


def standout_pptx(sl, s, H, CW):
    """An impact slide. Measures the height of each layer and centers the
    total on the slide, same order as the deck.

    Every size is the deck's pt x PX. A different formula from the deck
      would shrink only one side.
    """
    T_LARGE = round(deck_pt(12))
    T_LARGE2 = round(deck_pt(14.4))            # \\Large
    blocks = []                                # (height, drawing function)

    def add(h, fn, gap=0.12):
        blocks.append((h, fn, gap))

    if s.get("lead"):
        h = text_h([s["lead"]], CW, T_LARGE)
        add(h, lambda y: textbox(sl, MARGIN, y, CW, h, [s["lead"]], T_LARGE,
                                 WHITE, PP_ALIGN.CENTER), 0.25)
    big = s.get("big")
    if isinstance(big, list) and big:
        bigs = [b if isinstance(b, dict) else {"value": b} for b in big]
        n_ = len(bigs)
        mid_w = 1.6 if n_ == 2 else 0.4
        # If the middle word (`gap`) gets narrower than a single word, it
        #   breaks mid-word: "improve / ment" has printed across three
        #   lines this way, though the deck was fine. Gives it at least
        #   enough room for the longest word.
        if n_ == 2 and s.get("gap"):
            _longest = max(str(s["gap"]).split() or [""], key=len)
            mid_w = max(mid_w, deckspec.text_width_in(_longest, T_LARGE, font=FONT) + 0.35)
        colw = min(3.6, (CW - mid_w * (n_ - 1)) / n_)
        x0 = MARGIN + (CW - (colw * n_ + mid_w * (n_ - 1))) / 2.0
        vals = [str(b.get("value", b.get("text", ""))) for b in bigs]
        pts = []
        for v in vals:
            bp = deckspec.big_pt(v)
            pts.append(deckspec.BIG_PT_PAIRED if bp >= deckspec.BIG_PT_NUMBER else bp)
        vpt = round(deck_pt(min(pts)))           # values placed side by side share one size
        # A value with no space in it ("93,817.45M") is one chunk. If it is
        #   wider than the column, PowerPoint has broken the line in the
        #   middle of the number ("93,81 / 7.45M"). Shrink it until the
        #   chunk fits the column.
        for v in vals:
            # A short value (`41.7 ms`) is also one whole line. Leaving it
            #   out only because it has a space would split the number and
            #   its unit across two lines. If it is within the value length
            #   limit (`BIG_VALUE_CHARS`), shrink it to fit one line.
            if v.strip() and (" " not in v.strip()
                              or len(v.strip()) <= deckspec.BIG_VALUE_CHARS):
                while vpt > T_LARGE and deckspec.text_width_in(v, vpt, True, FONT) > colw - 0.25:
                    vpt -= 1
        has_lab = any(b.get("label") for b in bigs)
        has_note = any(b.get("note") for b in bigs)
        # A label, subtitle, or middle word is measured by its wrapped line
        #   count. Pinning it to one line has let a long label overlap the
        #   value next to it.
        h_lab = max([text_h([b["label"]], colw, T_LARGE, bold=True) for b in bigs
                     if b.get("label")] or [0.0])
        # The big number also counts wrapped lines. Pinning it to one line
        #   has let a word choice ("run it unoptimized") wrap to two lines
        #   and overlap the line below.
        h_val = max([_lh(vpt, gap=1.15)] + [text_h([v], colw, vpt, 1.15, bold=True)
                                           for v in vals])
        h_note = max([text_h([b["note"]], colw, T_SMALL) for b in bigs
                      if b.get("note")] or [0.0])
        _gw = s.get("gap") or "vs"
        _gplace = deckspec.gap_place(s.get("gap"), has_lab) if n_ == 2 else None
        h_gap = (text_h([_gw], mid_w, T_LARGE) if _gplace == "number" else 0.0)
        h = h_lab + max(h_val, h_gap) + h_note

        def draw_pair(y):
            for i, b in enumerate(bigs):
                x = x0 + (colw + mid_w) * i
                col = {"hit": HIT_LT, "safe": SAFE_LT}.get(b.get("mark"), WHITE)
                if b.get("label"):
                    textbox(sl, x, y, colw, h_lab, [b["label"]], T_LARGE, col,
                            PP_ALIGN.CENTER, bold=True)
                textbox(sl, x, y + h_lab, colw, h_val, [vals[i]], vpt, col,
                        PP_ALIGN.CENTER, bold=True)
                if b.get("note"):
                    textbox(sl, x, y + h_lab + h_val, colw, h_note, [b["note"]],
                            T_SMALL, col, PP_ALIGN.CENTER)
            if n_ == 2:
                # Same rule as the deck (`deckspec.gap_place`)
                mx = x0 + colw
                place = deckspec.gap_place(s.get("gap"), has_lab)
                if place == "label":
                    # If the middle word wraps, put "vs" below it, or it prints on top of it
                    _gh = max(h_lab, text_h([s["gap"]], mid_w, T_SMALL))
                    textbox(sl, mx, y, mid_w, _gh, [s["gap"]], T_SMALL, WHITE,
                            PP_ALIGN.CENTER)
                    textbox(sl, mx, max(y + h_lab + h_val / 2 - _lh(T_BODY) / 2, y + _gh + 0.04),
                            mid_w, _lh(T_BODY), ["vs"], T_BODY, WHITE, PP_ALIGN.CENTER)
                else:
                    textbox(sl, mx, y + h_lab + max(0.0, (h_val - h_gap) / 2), mid_w,
                            h_gap, [_gw], T_LARGE, WHITE, PP_ALIGN.CENTER)
        add(h, draw_pair, 0.3)
    elif big:
        bpt = round(deck_pt(deckspec.big_pt(big)))
        _toks = ([str(big).strip()] if len(str(big).strip()) <= deckspec.BIG_VALUE_CHARS
                 else str(big).split())          # a short value stays whole (same reason as above)
        for tok in _toks:                        # keep any one chunk from overflowing the slide width
            while bpt > T_LARGE and deckspec.text_width_in(tok, bpt, True, FONT) > CW - 0.25:
                bpt -= 1
        h = text_h([str(big)], CW, bpt)
        add(h, lambda y: textbox(sl, MARGIN, y, CW, h, [str(big)], bpt, WHITE,
                                 PP_ALIGN.CENTER, bold=True), 0.3)
    # A vertical flow, narrowing from top to bottom. The last step is large (same as the deck).
    fl = list(s.get("flow") or [])
    for j, step in enumerate(fl):
        last = (j == len(fl) - 1)
        if j:
            add(_lh(T_LARGE2), lambda y: textbox(sl, MARGIN, y, CW, _lh(T_LARGE2),
                                                 [u"\u21d3"], T_LARGE2, WHITE,
                                                 PP_ALIGN.CENTER), 0.06)
        pt = T_LARGE2 if last else T_SMALL
        # The last step prints bold. Measuring it at regular weight has let
        #   a step that wraps to two lines overlap the text after it
        h = text_h([step], CW, pt, bold=last)
        _col = SAFE_LT if (last and not deckspec.emphasis(step)) else WHITE
        add(h, (lambda st, p_, h_, c_: lambda y: textbox(
            sl, MARGIN, y, CW, h_, [st], p_, c_, PP_ALIGN.CENTER,
            bold=last))(step, pt, h, _col), 0.06)
    if s.get("table"):
        for row in s["table"]["rows"]:
            cells = [c for c in row if str(c).strip()]
            if cells:
                txt = "   ".join(cells)
                add(_lh(T_BODY), (lambda tx: lambda y: textbox(
                    sl, MARGIN, y, CW, _lh(T_BODY), [tx], T_BODY, WHITE,
                    PP_ALIGN.CENTER))(txt), 0.04)
    if s.get("bullets"):
        txt = " ".join(s["bullets"])
        h = text_h([txt], CW, T_LARGE)
        add(h, lambda y: textbox(sl, MARGIN, y, CW, h, [txt], T_LARGE, WHITE,
                                 PP_ALIGN.CENTER), 0.15)
    _PT = {"large": T_LARGE, "normalsize": T_BODY, "small": T_SMALL}
    for txt, size in deckspec.standout_lines(s):
        pt = _PT[size]
        h = text_h([txt], CW, pt)
        add(h, (lambda tx, p_, h_: lambda y: textbox(
            sl, MARGIN, y, CW, h_, [tx], p_, WHITE, PP_ALIGN.CENTER))(txt, pt, h),
            0.08)
    total = sum(h for h, _, _ in blocks) + sum(g for _, _, g in blocks[:-1])
    y = max(0.3, (H - total) / 2.0)
    for h, fn, g in blocks:
        fn(y)
        y += h + g


def build(spec_path, out_path, figdir=None):
    meta, slides, npage = load(spec_path)
    prs = Presentation()
    a, b = (float(x) for x in str(meta.get("aspect", "16:9")).split(":"))
    prs.slide_height = Inches(7.5)
    prs.slide_width = Inches(7.5 * a / b)
    W = prs.slide_width / 914400.0
    H = prs.slide_height / 914400.0
    CW = W - 2 * MARGIN
    blank = prs.slide_layouts[6]
    warn = []
    figdir = figdir or meta.get("figdir") or "figs"
    # A figure checks where the artifact will be placed first. Following
    #   the docs' command literally puts it in `out/figs/`, but this used to
    #   check only the spec folder and dropped it entirely.
    base = (os.path.dirname(os.path.abspath(out_path)),
            os.path.dirname(os.path.abspath(spec_path)))

    # The font can be changed from the spec, but an unknown name gets
    #   flagged. Since PPTX cannot embed fonts, a name missing at the venue
    #   gets silently substituted, and at that point every table's estimated
    #   column width goes wrong.
    global FONT, MONO
    FONT = meta.get("pptx_font") or FONT
    MONO = meta.get("pptx_mono") or MONO
    for f in (FONT, MONO):
        if f not in SAFE_FONTS:
            warn.append("Confirm that font \"%s\" is on the venue PC. PPTX cannot "
                        "embed fonts, and a missing one is silently substituted" % f)

    for s in slides:
        sl = prs.slides.add_slide(blank)
        k = s["kind"]

        if k == "title":
            title_pptx(sl, meta, H, CW)
        elif k == "standout":
            bg = sl.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
            bg.fill.solid()
            bg.fill.fore_color.rgb = DARK
            bg.line.fill.background()
            bg.shadow.inherit = False
            standout_pptx(sl, s, H, CW)
        elif k == "columns":
            # Must be the same layout as the deck. Diverging here means fixing the two artifacts separately.
            band(sl, prs, s, npage)
            y = TOP
            if s.get("lead"):
                # Measured height: if it wraps to two lines, it covers the figure below. The deck's \small.
                _lh_ = text_h([s["lead"]], CW, T_LEAD)
                textbox(sl, MARGIN, y, CW, _lh_, [s["lead"]], T_LEAD, INK)
                y += _lh_ + 0.08
            if s.get("formula"):
                # Same spot as the deck's formula_body: centered under the lead, \Large
                _fp = round(deck_pt(14.4))
                _fh = text_h([s["formula"]], CW, _fp)
                textbox(sl, MARGIN, y + 0.04, CW, _fh, [s["formula"]], _fp, INK,
                        PP_ALIGN.CENTER)
                y += _fh + 0.14
            # A full-width figure spanning the two columns. The deck drew
            #   this and PPTX did not, so that slide's figure was entirely
            #   missing only in the PowerPoint edition.
            #   Figure on top, the two columns' text below: the layout the spec accepts.
            top = s.get("figure") or (
                {"path": "chart_%02d_self.png" % s["n"]} if s.get("chart")
                else {"path": "diagram_%02d_self.png" % s["n"]}
                if s.get("diagram") else None)
            if top:
                if top.get("grid"):
                    add_grid(sl, top, MARGIN, y, CW, H * 0.62, base, figdir, warn)
                    y = H * 0.55
                else:
                    p = find_img(top["path"], base, figdir)
                    if p:
                        # Binds the height and derives the width from the
                        #   actual aspect ratio, then centers it. Estimating
                        #   the width let the figure drift to one side (this
                        #   actually happened).
                        try:
                            with Image.open(p) as _im:
                                iw, ih = _im.size
                            ratio = iw / float(ih)
                        except (OSError, ValueError):
                            ratio = 2.0
                        h = min(2.3, CW / ratio)
                        w = h * ratio
                        # One unreadable figure must not stop the whole
                        #   deck from being built. The deck side already
                        #   only reserves the space and warns; only this side died.
                        try:
                            sl.shapes.add_picture(
                                p, Inches(MARGIN + (CW - w) / 2), Inches(y),
                                height=Inches(h))
                        except Exception as e:
                            warn.append("Cannot read figure: %s (%s)"
                                        % (p, type(e).__name__))
                        y += h + 0.18
                    else:
                        # This `else` is `if p`'s partner. It used to hang
                        #   off the caption branch, so every figure with no
                        #   caption triggered "figure not found," even
                        #   though the file was perfectly fine. A false
                        #   positive erases the feature, and buries the real
                        #   warnings in noise.
                        warn.append("Figure not found: %s"
                                    % _img_path(top["path"], base, figdir))
                    if top.get("caption"):
                        textbox(sl, MARGIN, y, CW, 0.32, [top["caption"]],
                                T_SMALL, MUTE, PP_ALIGN.CENTER)
                        y += 0.36
            lw = float(s["left"].get("width") or 0.5)
            gap = 0.22
            for side, x0, w0 in (("left", MARGIN, CW * lw - gap / 2),
                                 ("right", MARGIN + CW * lw + gap / 2,
                                  CW * (1 - lw) - gap / 2)):
                # A column's bottom is where the slide's footnote starts.
                #   Past the slide's height, the column's figure covers the
                #   footnote, as surfaced when the deck's proportional font
                #   made the footnote grow.
                draw_pane(sl, s[side], x0, y, w0, s, side,
                          base, figdir, warn, foot_top(s, H, CW) + 0.65)
        else:
            band(sl, prs, s, npage)
            _n_pre = len(sl.shapes)          # shape count through the band/page number: excluded from centering
            y = TOP
            # A figure's bottom. Whatever follows tracks this.
            fig_bot = None
            # Height taken up by the footnote/fine print, measured once so
            #   the footnote position and the figure/grid limit see the
            #   same number. The grid did not subtract this, so the footnote
            #   printed on top of the caption.
            fy0 = foot_top(s, H, CW)
            if s.get("lead"):
                # Measured height: if it wraps to two lines, it covers the figure below. The deck's \small.
                _lh_ = text_h([s["lead"]], CW, T_LEAD)
                textbox(sl, MARGIN, y, CW, _lh_, [s["lead"]], T_LEAD, INK)
                y += _lh_ + 0.08
            if s.get("formula"):
                # Same spot as the deck's formula_body: centered under the lead, \Large
                _fp = round(deck_pt(14.4))
                _fh = text_h([s["formula"]], CW, _fp)
                textbox(sl, MARGIN, y + 0.04, CW, _fh, [s["formula"]], _fp, INK,
                        PP_ALIGN.CENTER)
                y += _fh + 0.14
            if k == "figure" and (s.get("figure") or {}).get("grid"):
                # A grid must be the same shape as the deck. Adding it to
                #   only one side splits the two artifacts apart, and only
                #   `outcheck` catches that.
                fig_bot = add_grid(sl, s["figure"], MARGIN, y, CW,
                                   fy0 - 0.12 + 0.55, base, figdir, warn)
            elif k == "figure":
                _stk = deckspec.stacked(s)
                _chart = ({"path": "chart_%02d_self.png" % s["n"]}
                          if s.get("chart")
                          else {"path": "diagram_%02d_self.png" % s["n"]})
                f = _chart if _stk else (s.get("figure") or _chart)
                if _stk:
                    # Reserves the body of the figure that goes below, first: same proportion as the deck.
                    _ph_in = (fy0 - y) * deckspec.STACK_PHOTO_SHARE
                    fy0_saved, fy0 = fy0, fy0 - _ph_in - 0.12
                p = find_img(f["path"], base, figdir)
                if f.get("lead"):
                    # Reserves 0.8 inches even for a one-line lead. A wide
                    #   figure bound to that height has come out far smaller
                    #   than in the PDF (57% of the slide width). The text
                    #   height is measured.
                    _flh = text_h([f["lead"]], CW, T_SMALL)
                    textbox(sl, MARGIN, y, CW, _flh, [f["lead"]], T_SMALL, INK,
                            PP_ALIGN.CENTER)
                    y += _flh + 0.1
                if p:
                    # Reserves room for whatever comes after. A fixed `y +
                    #   3.2` has printed the bullets on top of a tall figure.
                    room = fy0 - 0.12 - y
                    if s["bullets"]:
                        room -= text_h([bullet_line(b) for b in s["bullets"]], CW,
                                       T_BODY, 1.45) + 0.2
                    if f.get("caption"):
                        room -= text_h([f["caption"]], CW, T_SMALL) + 0.12
                    fig_bot = place_picture(sl, p, MARGIN, y, CW,
                                            max(0.9, room), f)
                else:
                    warn.append("Figure not found: %s"
                                % _img_path(f["path"], base, figdir))
                    textbox(sl, MARGIN, y, CW, 0.5, ["[missing: %s]" % f["path"]],
                            T_SMALL, MUTE, PP_ALIGN.CENTER, font=MONO)
                if _stk:
                    fy0 = fy0_saved
                    _ph = s["figure"]
                    _y2 = (fig_bot if fig_bot is not None else y) + 0.10
                    if _ph.get("grid"):
                        fig_bot = add_grid(sl, _ph, MARGIN, _y2, CW,
                                           fy0 - 0.12 + 0.55, base, figdir, warn)
                    else:
                        _p2 = find_img(_ph["path"], base, figdir)
                        if _p2:
                            # Uses only its own body's height: eating all the leftover space puts the caption on the footnote.
                            _cap = (text_h([_ph["caption"]], CW, T_SMALL) + 0.06
                                    if _ph.get("caption") else 0.0)
                            # The figure config (`_ph`) has to be passed
                            #   through for `crop`/`highlight` to take
                            #   effect; this was missing, same as on the deck side.
                            fig_bot = place_picture(
                                sl, _p2, MARGIN, _y2, CW,
                                max(0.5, min(_ph_in, fy0 - 0.12 - _y2 - _cap)), _ph)
                        else:
                            warn.append("Figure not found: %s"
                                        % _img_path(_ph["path"], base, figdir))
                    if _ph.get("caption"):
                        textbox(sl, MARGIN, (fig_bot or _y2) + 0.04, CW,
                                0.4, [_ph["caption"]], T_SMALL, MUTE,
                                PP_ALIGN.CENTER)
                        fig_bot = (fig_bot or _y2) + 0.4
                if f.get("caption"):
                    # Pinning it to a fixed `H - 0.95` covers a tall figure. Placed below its bottom instead.
                    cy = (fig_bot + 0.10) if fig_bot is not None else H - 0.95
                    textbox(sl, MARGIN, min(cy, H - 0.62), CW, 0.5,
                            [f["caption"]], T_SMALL, MUTE, PP_ALIGN.CENTER)
                    fig_bot = cy + 0.45
            elif k == "table":
                # Follows the slide-level `table.size` (the deck already
                #   does). If it runs past the footnote position, shrink it
                #   one step at a time and lay it out again, the same thing
                #   the deck's adjustbox does.
                _sz0 = {"small": round(T_BODY * 0.8), "fine": round(T_BODY * 0.7)}.get(
                    str(s["table"].get("size") or ""), T_BODY - 2)
                _w0 = []
                # Also reserves room for the bullets under the table.
                #   Filling the table up to the footnote line has made the
                #   bullets overlap the footnote/fine print. Measures the
                #   bullets' height and raises the table's bottom by that much.
                _bl = ([bullet_line(b) for b in s["bullets"]] if s["bullets"] else [])
                _bh = (text_h(_bl, CW, T_BODY, 1.45) + 0.18) if _bl else 0.0
                _lim = foot_top(s, H, CW) - _bh - (0.06 + text_h([s["table"]["note"]], CW, T_SMALL)
                                                   if s["table"].get("note") else 0.0)
                for _sz in (_sz0, _sz0 - 2, _sz0 - 4):
                    _w0 = []
                    _tb = add_table(sl, s["table"], MARGIN, y + 0.1, CW, _w0,
                                    size=_sz, where=u"Slide %s:" % s.get("n"))
                    if y + 0.1 + table_height(_tb) <= _lim + 0.02 \
                            or _sz <= _sz0 - 4:
                        break
                    _tb._element.getparent().remove(_tb._element)
                warn.extend(_w0)
                # What goes under the table follows the table's actual
                #   bottom. A fixed value (a position measured from the
                #   slide bottom, an estimate of the table's height) collides
                #   with the same spot when the table is long or wraps.
                fig_bot = y + 0.1 + table_height(_tb)
                if fig_bot > foot_top(s, H, CW) + 0.02:
                    warn.append(u"Slide %s: table bottom (%.2fin) in PPTX runs past the footnote position (%.2fin). "
                                u"Shorten rows/cell text, or split the table"
                                % (s.get("n"), fig_bot, foot_top(s, H, CW)))
                if s["table"].get("note"):
                    textbox(sl, MARGIN, fig_bot + 0.06, CW, 0.5, [s["table"]["note"]],
                            T_SMALL, MUTE)
                    fig_bot += 0.06 + text_h([s["table"]["note"]], CW, T_SMALL)
            if s["bullets"]:
                # Follows the figure's actual bottom. A fixed value overlaps it.
                yy = (fig_bot + 0.18 if fig_bot is not None
                      else y + (3.2 if k in ("figure", "table") else 0.1))
                _bl = [bullet_line(b) for b in s["bullets"]]
                # A slide with only bullets is vertically centered: beamer
                #   centers it, but PPTX alone sticks it to the top, giving
                #   the two artifacts a different center of gravity.
                if fig_bot is None and k == "content":
                    _room = foot_top(s, H, CW) - y
                    yy = y + max(0.1, (_room - text_h(_bl, CW, T_BODY, 1.45)) / 2.0)
                textbox(sl, MARGIN, yy, CW, max(0.3, min(H - yy - 0.7, text_h(_bl, CW, T_BODY, 1.45))),
                        _bl, T_BODY, INK, spacing=1.45)
                if yy + text_h(_bl, CW, T_BODY, 1.45) > foot_top(s, H, CW) + 0.02:
                    warn.append(u"Slide %s: bullets in PPTX reach down to the footnote position. "
                                u"Shorten the bullets or move them to foot" % s.get("n"))

        # `foot`: full-width fine print under the body. Without it, PPTX
        #   has come out 35 items short of the deck. This is where the two
        #   artifacts drift apart, and section F only compares decimal sets
        #   so it could not catch it. `outcheck` is what caught it.
        if (s.get("foot") or s.get("fine")) and k not in ("title", "standout"):
            # `fine` goes under `foot`, one size smaller. A concluding
            #   sentence and a pile of notation are stacked at different
            #   weights; at one weight, neither gets read.
            fy = foot_top(s, H, CW)
            # A slide with only a table or figure has the deck center the
            #   content and footnote as one block. PPTX alone sticks the
            #   footnote to the bottom of the slide, leaving a hollow gap
            #   between the table and the footnote. Pull it up to right
            #   under the content.
            if k in ("table", "figure") and not s["bullets"] and fig_bot is not None:
                fy = min(fy, fig_bot + 0.15)
            if s.get("foot"):
                _fh = text_h(s["foot"], CW, T_SMALL, 1.25)
                textbox(sl, MARGIN, fy, CW, _fh, s["foot"],
                        T_SMALL, MUTE, spacing=1.25)
                fy += _fh + 0.08
            if s.get("fine"):
                textbox(sl, MARGIN, fy, CW, text_h(s["fine"], CW, T_SMALL - 1, 1.15),
                        s["fine"], T_SMALL - 1, MUTE, spacing=1.15)

        # A slide with only a table or figure is vertically centered: the
        #   deck centers it with `\vfill` above and below, but PPTX alone
        #   sticks to the top, leaving the bottom half empty (traps.md:
        #   "Table- or figure-only frames ... Centre them"). Moves all the
        #   content, minus the band and page number, as one block.
        if k in ("table", "figure") and not s["bullets"] and not s.get("block") \
                and s.get("kind") != "columns":
            _mine = list(sl.shapes)[_n_pre:]
            if _mine:
                def _bot(x):
                    if getattr(x, "has_table", False) and x.has_table:
                        return Emu(x.top).inches + table_height(x)
                    return Emu(x.top + x.height).inches
                _t0 = min(Emu(x.top).inches for x in _mine)
                _b0 = max(_bot(x) for x in _mine)
                _dy = ((TOP + H - 0.55) - (_t0 + _b0)) / 2.0
                if _dy > 0.08:
                    for x in _mine:
                        x.top = Emu(int(x.top + Inches(_dy)))

        # A highlight box. Made to resemble metropolis's gray block; the spec requires a title.
        b = s.get("block")
        if b and k not in ("title", "standout"):
            # Height is measured from its own text. Pinning it to 1.05
            #   inches has let the text spill outside the box and over the
            #   page number. The bottom is fixed above the page number and
            #   it grows upward.
            _tt, _bt, _hh = block_height(b, CW)
            by = H - 0.50 - _hh
            _bg, _tc = block_colours(b.get("kind"))
            box = sl.shapes.add_shape(1, Inches(MARGIN), Inches(by),
                                      Inches(CW), Inches(_hh))
            box.fill.solid()
            box.fill.fore_color.rgb = _bg
            box.line.fill.background()
            box.shadow.inherit = False
            textbox(sl, MARGIN + 0.16, by + 0.08, CW - 0.32, _tt,
                    [b["title"]], T_BODY - 1, _tc, bold=True)
            textbox(sl, MARGIN + 0.16, by + 0.08 + _tt + 0.04, CW - 0.32, _bt,
                    [b.get("text") or ""], T_SMALL + 1, INK)

        # Speaker notes also get what to say (`say`) and what to do (`cue`).
        #   Moving only `note` has left the venue PC's presenter view with
        #   not a single sentence to say. The SKILL's "notes transplanted."
        _notes = []
        _cue = s.get("cue") or []
        _cue = [_cue] if isinstance(_cue, str) else list(_cue)
        if _cue:
            _notes.append("[cue] " + " ".join(deckspec.plain(str(x)) for x in _cue))
        if s.get("note"):
            _notes.append(deckspec.plain(str(s["note"])))
        if s.get("say"):
            _notes.append("\n".join(deckspec.plain(str(x)) for x in s["say"]))
        if _notes:
            sl.notes_slide.notes_text_frame.text = "\n\n".join(_notes)

    # Watches for a LaTeX leak. Math gets converted to plain characters
    #   above, but if some other command leaks through, a backslash prints
    #   literally on the PowerPoint screen. The deck is fine, so there is no
    #   way to know without looking, so this counts it here.
    for sl in prs.slides:
        for sh in sl.shapes:
            # Table cells are checked too: a `\hat` that leaked into a cell has gone unseen, with outcheck flagging it backwards
            if getattr(sh, "has_table", False) and sh.has_table:
                txt = " ".join(c.text_frame.text for r_ in sh.table.rows for c in r_.cells)
            elif sh.has_text_frame:
                txt = sh.text_frame.text
            else:
                continue
            # A currency `$` ("$31,900") is not LaTeX
            for bad in re.findall(r"\\[a-zA-Z]+|\$", deckspec.CURRENCY.sub("", txt)):
                warn.append("Raw LaTeX left over in PPTX: %r (%s)"
                            % (bad, re.sub(r"\s+", " ", txt)[:48]))
                break

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    prs.save(out_path)
    # "reaches down to the footnote position" is an estimate (an estimated
    #   table/text height against the footnote area's top edge). Measure the
    #   saved file with the same function as `fitcheck --pptx`, and if that
    #   slide has no actual overlap or overflow, drop the estimated warning.
    #   The build has kept saying "table bottom runs past the footnote" to
    #   the end while fitcheck said "zero geometry," with the PowerPoint
    #   render looking fine too, so an agent could not tell which one to
    #   trust. The footnote area is space left empty, so its bottom is blank
    #   when the text is short.
    try:
        import fitcheck as _fc
        warn = settle_foot(warn, _fc.check_pptx(out_path))
    except Exception:                  # if the measuring side cannot run, keep the estimate as-is
        pass
    return len(slides), npage, warn


_FOOT_EST = re.compile(u"[Ss]lide (\\d+).*footnote position")


def settle_foot(warn, measured):
    """Of the estimated footnote-position warnings, drop the ones for
    slides where the measured result (`fitcheck.check_pptx`) shows no
    overlap or overflow."""
    # `kind` is fitcheck.py's own label for the finding; the two names must match there
    hit = {n_ for n_, kind, _ in measured if kind in (u"overlap", u"off the page")}
    return [w for w in warn
            if not (_FOOT_EST.match(w) and int(_FOOT_EST.match(w).group(1)) not in hit)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="slides.yaml -> talk.pptx")
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", default="talk.pptx")
    ap.add_argument("--figdir", default=None)
    a = ap.parse_args(argv)
    n, npage, warn = build(a.spec, a.out, a.figdir)
    print("=> %s  (%d slides, %d numbered, %s)" % (a.out, n, npage, FONT))
    for w in warn:
        print("   %s" % w)
    print("   The venue runs PowerPoint. Open it for real and check it by eye, not LibreOffice.")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    sys.exit(main())
