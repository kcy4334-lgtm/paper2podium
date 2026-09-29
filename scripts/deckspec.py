# -*- coding: utf-8 -*-
"""`slides.yaml`: the single source that the deck, the PPTX and the script all read together.

Why do it this way: in the project this skill was extracted from, the
deck (`talk.tex`), the PPTX assembler, and the script generator each kept
their own separate copy of the content. That made "change one sentence,
fix all three in the same pass" an invariant rule, and it still drifted
apart in practice, forcing yet another checker to be built. Deriving all
three from one source instead makes that rule unnecessary.

Schema (use only what you need)

    meta:
      title:    talk title
      subtitle: subtitle              (optional)
      author:   presenter             (optional)
      venue:    conference · date     (optional)
      wpm:      135                   (optional, for timing)
      aspect:   "16:9"                (optional)

    slides:
      - kind: title | content | standout | figure | table
        title:   slide title
        bullets: [one line, another line]        # content
        big:     "big text in the middle of the screen"     # standout
        figure:  {path: figs/a.png, caption: ..., max_height: 5cm}
        table:   {header: [...], align: lrr, rows: [[...], ...], note: ...}
        note:    speaker note (not shown on screen)
        say:     ["what to say aloud", "..."]   # script
        ko:      ["translation", "..."]         # script translation (optional)
        cue:     ["gesture/tone direction"]     # script only
        pause:   4                              # seconds spent pointing in silence

If `kind` is omitted it is inferred from the content: `standout` if `big`
is present, `figure` if `figure` is present, `table` if `table` is
present, otherwise `content`.
"""
import io
import math
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    raise SystemExit("pyyaml is required:  pip install pyyaml")

KINDS = ("title", "content", "standout", "figure", "table", "columns")

# ──────────────────────────────────────────────────────────────────────
# On-screen geometry: this is the single source.
#
# Why it lives here: the side that draws figures (`build_figs`) and the
# side that places them (`build_deck`) were looking at two different
# sizes. The drawing side always drew at 7.2-inch width, while the
# placing side squeezed it down to 5.0-5.4cm. The measured shrink ratio
# was 0.337-0.495, so text stamped at `fontsize=13` came out 4.4pt on
# screen. Text inside a figure isn't in the PDF's text layer, so
# `fitcheck` can't see it either, and if the declared size isn't the real
# size, no checker can catch it. Draw the figure at the exact size of the
# slot it will occupy and the shrink ratio becomes 1.0, so the declared
# pt becomes the on-screen pt.
#
# Source of the numbers: in metropolis, aspectratio=169, `\the\textwidth` = 398.34pt
#            (TeX pt, /72.27 = 5.512 in), `\the\textheight` = 228.16pt.
TEXT_W_IN = 5.51            # \textwidth
TEXT_H_TOTAL_IN = 3.157     # \textheight (228.16pt / 72.27), used only when converting to a ratio
BODY_PT = 10.0              # metropolis default. Overridden by `meta.base_pt`
# The floor (pt) for text inside a figure. `build_figs` never draws smaller than this, and
# `fitcheck` only counts figure text as a failure below it. The two have to be written together,
# since a figure the skill itself drew can otherwise fail the skill's own check.
FIG_FLOOR_PT = 6.5
BASE_PT_OK = (8, 9, 10, 11, 12, 14, 17, 20)   # values beamer accepts


def acronyms(meta):
    """`meta.acronyms` -> {acronym: word count when spoken}.

    SKILL.md says to measure the acronym yourself, while `timing.TOKEN_WORDS`
    (inside the script) is the only place to put that value, and the same
    document says not to edit the script. Keeping the value on the side by
    hand instead once left a deck underestimated by 15 seconds, 30% of its
    remaining slack. Per this skill's own principle that the spec is the
    single source, it's taken from here instead.

        meta:
          acronyms: {NASA: 1, SoC: 3, NMC811: 6}
    """
    raw = (meta or {}).get("acronyms") or {}
    if not isinstance(raw, dict):
        raise ValueError("meta.acronyms is a {acronym: word count} mapping")
    out = {}
    for k, v in raw.items():
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise ValueError("meta.acronyms[%r] must be a word count (number)" % k)
        if n <= 0:
            raise ValueError("meta.acronyms[%r] must be greater than 0" % k)
        out[str(k)] = n
    return out


def set_base_pt(meta):
    """Changes the body text size via `meta.base_pt`. Figure text follows along too.

    10pt doesn't read in a deep hall: by ergonomic standards (16-22
    arcminutes), 22pt is the floor at a 6x viewing ratio. The only way to
    change the size used to be a `10pt` baked into the code, with no lever
    for the author to pull. Making it bigger shrinks the available room
    and pushes content around, and that trade-off belongs to the author,
    but the skill has to supply the lever before the author can decide it.

    Changed in one place. `build_figs` reads the same number, so the body
    text can't grow while the figures stay the same.
    """
    global BODY_PT
    v = (meta or {}).get("base_pt")
    if v is None:
        BODY_PT = 10.0
        return 10
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ValueError("meta.base_pt must be an integer — one of %s"
                         % ", ".join(str(x) for x in BASE_PT_OK))
    if v not in BASE_PT_OK:
        raise ValueError("meta.base_pt=%r is not accepted by beamer — one of %s"
                         % (v, ", ".join(str(x) for x in BASE_PT_OK)))
    BODY_PT = float(v)
    return v
PANE_GAP = 0.02             # the share `build_deck` subtracts per pane

# The height cap (inches) for the slot a figure occupies. `build_deck` uses this as-is.
# These caps used to be the 5.0/5.4cm that `build_deck` had hard-coded by hand. Since figures
# are now drawn at their content size, these are just caps; the real limit is
# `BODY_H_IN - fig_reserve`. Keeping them too low squeezes concept diagrams (strips,
# pipelines), pushing side labels off the bottom.
SLOT_H_IN = {
    "chart": 2.55,
    "diagram": 2.55,
    # If a pane holds nothing but a figure, it can use the full body
    # height. A fixed 5.2cm was an arbitrary value that squeezed a
    # four-row grid inside the pane. The real limit is
    # `BODY_H_IN - fig_reserve`.
    "pane": 2.55,           # one pane of a left/right two-column layout
    "figure": 2.44,         # 6.2cm — a hand-placed figure file
}


def cm_of(name):
    """The `max height` string `build_deck` writes into the LaTeX."""
    return "%.2fcm" % (SLOT_H_IN[name] * 2.54)


# Vertical space (inches) the body can use, minus the title and page number.
BODY_H_IN = 2.60
# Vertical space (inches) one line outside a figure takes up. A measured approximation.
LINE_H_IN = {"bullet": 0.20, "foot": 0.155, "lead": 0.19, "block": 0.165,
             "head": 0.17, "caption": 0.155, "text": 0.165, "fine": 0.14, "formula": 0.42}
# Roughly how many characters fit on one line. Used only to count line counts.
LINE_CHARS = {"bullet": 92, "foot": 118, "lead": 96, "block": 104,
              "head": 60, "caption": 110, "text": 62, "fine": 132, "formula": 70}


def _lines(text, what):
    """How many lines `text` will become. If it's a list, counts each item."""
    if not text:
        return 0
    items = text if isinstance(text, (list, tuple)) else [text]
    per = LINE_CHARS[what]
    n = 0
    for it in items:
        s = str(it)
        n += max(1, int(math.ceil(len(s) / float(per))))
    return n


# Feedback loop. Slide number -> extra inches to subtract from its figure slot.
# Empty means use the estimate only. Since the compile log already reports "this slide
# overflowed by N pt," that much is subtracted from the figure and it's drawn once more
# (`scripts/build.py`). Baking an estimate in as a constant instead lets the measuring
# side and the drawing side drift apart again.
EXTRA_RESERVE = {}
# If shrinking the figure doesn't reduce the overflow, the cause isn't the
# figure but the text: a left pane's bullets can overflow while the right
# pane's photo keeps shrinking into a thumbnail with the overflow
# unchanged. Record the previous overflow, and if it didn't shrink, roll
# back that slide's feedback and mark it as a "slide bound by its text,"
# so its figure is never shrunk again.
LAST_OVER = {}
TEXT_BOUND = set()

# The threshold (pt) for body overflow. Measured on one example deck: the
# content slides there never overflowed past 6pt, and that's invisible
# when actually shown. Decks that overflowed 9-18pt had their last line
# touching the page number.
OVERFULL_TOL_PT = 6.0


def log_overfull(pdf_or_log):
    """Pages where the body overflowed its slot, from the compile log. [(page, pt)], or None if there's no log.

    `Overfull \vbox` is printed while a frame is being typeset, and that
    page is shipped out afterward (`[n`), so the page is the last page
    shipped before the warning, plus 1.

    The title page is excluded: metropolis's title page overflows by
    13.8pt because of the theme itself, the same in every deck, and
    counting something the deck can't fix would only be noise.
    """
    stem = os.path.splitext(str(pdf_or_log))[0]
    log = stem + ".log"
    if not os.path.exists(log):
        return None
    with io.open(log, encoding="latin-1") as f:
        txt = f.read()
    ship = re.compile(r"(?:^|[\s\]])\[(\d+)(?=[\s\]<{]|$)", re.M)
    over = re.compile(r"Overfull \\vbox \((\d+(?:\.\d+)?)pt too high\)")
    ev = [(m.start(), 0, int(m.group(1))) for m in ship.finditer(txt)]
    ev += [(m.start(), 1, float(m.group(1))) for m in over.finditer(txt)]
    title_page = None
    tex = stem + ".tex"
    if os.path.exists(tex):
        with io.open(tex, encoding="utf-8", errors="replace") as f:
            if "\\maketitle" in f.read():
                title_page = 1
    out, last = [], 0
    for _pos, kind, v in sorted(ev):
        if kind == 0:
            last = max(last, v)
        elif v > OVERFULL_TOL_PT and (last + 1) != title_page:
            out.append((last + 1, v))
    return out


def fit_from_log(pdf_or_log, slides):
    """Feeds the log's overflow back into that slide's figure slot. {slide number: inches}.

    Page i is the spec's i-th slide (this skill renders one slide per
    page). A small margin is added on top of the overflow so it lands
    safely under the threshold. If a slide that's already been fed back
    still overflows, it stacks up, since some figures don't shrink enough
    in one pass.
    """
    got = log_overfull(pdf_or_log) or []
    for page, pt in got:
        if 1 <= page <= len(slides):
            n = slides[page - 1].get("n", page)
            if n in TEXT_BOUND:
                continue
            prev = LAST_OVER.get(n)
            # if it shrank less than half of what was subtracted (inches -> pt), the figure isn't the cause
            if prev is not None and prev - pt < 0.5 * EXTRA_RESERVE.get(n, 0.0) * 72.0:
                EXTRA_RESERVE.pop(n, None)
                TEXT_BOUND.add(n)
                continue
            LAST_OVER[n] = pt
            EXTRA_RESERVE[n] = round(EXTRA_RESERVE.get(n, 0.0)
                                     + pt / 72.0 + 0.05, 3)
    return dict(EXTRA_RESERVE)


# A numeric cell — sign, decimal point, percent, or a dash (no value) all count. Strip markup first.
_NUM_CELL = re.compile(r"^\s*(?:[+\u2212-]?\d+(?:[.,]\d+)*\s*[%x\u00d7]?|[\u2014\u2013-]{1,3})\s*$")


def column_align(rows):
    """Column alignment for one table: right for numeric columns, left for text columns.

    Hard-coding only the first column as l and the rest as r leaves text
    columns hugging the right edge, so each row's starting point comes
    out ragged. A dash (—) is a numeric cell with no value. Empty cells
    aren't counted. A column that is entirely empty is treated as text.
    """
    rows = [r for r in (rows or []) if isinstance(r, (list, tuple))]
    if not rows:
        return ""
    nc = max(len(r) for r in rows)
    out = []
    for ci in range(nc):
        cells = [strip_markup(str(r[ci])) for r in rows
                 if ci < len(r) and r[ci] is not None and str(r[ci]).strip()]
        num = sum(1 for c in cells if _NUM_CELL.match(math_to_text(c)))
        out.append("r" if cells and num * 2 > len(cells) else "l")
    return "".join(out)


def cell_indent(v):
    """Leading space in a table cell -> (indent level, remaining text). Two spaces is one level.

    An indented row ("  dry cell") means it belongs to the row above, but
    LaTeX strips leading space on its own, so that meaning would
    otherwise disappear.
    """
    s = "" if v is None else str(v)
    n = len(s) - len(s.lstrip(" "))
    return (n + 1) // 2, s.lstrip(" ")


def title_wraps(pdf, band=0.16, size=11.5):
    """Page numbers of slides whose title wrapped to two lines in the title band. (page, title text).

    In one example deck every title was a single line except three
    slides, whose titles wrapped to two lines, eating into the body
    height, which is why their tile numbers came out smaller (2-3). A
    wrapped title is usually long because it's carried over from a paper
    sentence. Measured from the PDF, since estimating by character count
    is wrong from font to font.
    """
    try:
        try:
            import pymupdf as fitz
        except ImportError:      # PyMuPDF before 1.24.3 has only the old import name
            import fitz
    except ImportError:                              # pragma: no cover
        return []
    out = []
    doc = fitz.open(pdf)
    # Count only the title font. A large character inside a pasted vector
    # figure (a paper's PDF figure), such as "Input-Input Layer5," can
    # land in the title band and read as "the title wrapped to two
    # lines." Uses the font used most in the title band across the whole deck.
    from collections import Counter
    pages = []
    fonts = Counter()
    for pg in doc:
        top = pg.rect.height * band
        got = []
        for b in pg.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                sp = [s for s in ln["spans"]
                      if s["size"] >= size and s["bbox"][1] < top and s["text"].strip()]
                if sp:
                    got.append((round(ln["bbox"][1]), sp))
                    fonts[sp[0].get("font")] += 1
        pages.append(got)
    tf = fonts.most_common(1)[0][0] if fonts else None
    for i, got in enumerate(pages, 1):
        ys, txt = set(), []
        for y, sp in got:
            sp = [s for s in sp if s.get("font") == tf]
            if sp:
                ys.add(y)
                txt += [s["text"] for s in sp]
        if len(ys) >= 2:
            out.append((i, " ".join(" ".join(txt).split())))
    doc.close()
    return out


TITLE_PAGE_CHARS = 70    # roughly how many characters of a title-page title fit on two lines (14.4pt bold)
GAP_MAX_IN = 1.3        # width cap (inches) for the words between two big numbers


def gap_place(gap, labelled):
    """Where to put the words between two big numbers: 'label' (name line, small + vs between the numbers) | 'number'.

    A distance (words containing a number) is secondary. Taking up the
    space between the two numbers pushes them apart. A connector (or, vs,
    versus) is a word that links the two numbers, so it stands between them.
    """
    if not gap:
        return "number"
    return "label" if (labelled and re.search(r"\d", str(gap))) else "number"


STANDOUT_SIZES = ("large", "normal", "small")


def standout_lines(s):
    """Impact slide `lines` -> [(text, LaTeX size name)]."""
    out = []
    for x in (s.get("lines") or []):
        if isinstance(x, dict):
            txt, size = str(x.get("text", "")), str(x.get("size") or "large")
        else:
            txt, size = str(x), "large"
        if size not in STANDOUT_SIZES:
            raise ValueError("slide %s: lines' size must be one of %s (got %r)"
                             % (s.get("n"), "/".join(STANDOUT_SIZES), size))
        out.append((txt, "normalsize" if size == "normal" else size))
    return out


# The height a photo under a diagram takes up: a share of the body
# height. The structure is the main point and the photo is its evidence.
STACK_PHOTO_SHARE = 0.24


def institute_lines(meta):
    """Institute(s) as a list of lines."""
    v = (meta or {}).get("institute")
    if not v:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def stacked(owner):
    """Does this slide have a diagram (or chart) with a photo below it?"""
    return bool(isinstance(owner, dict) and owner.get("figure")
                and (owner.get("diagram") or owner.get("chart"))
                and not (owner.get("left") or owner.get("right")))


def stacked_photo_in(owner):
    """Height (inches) of the photo placed below. Includes one caption line."""
    f = owner.get("figure") or {}
    h = BODY_H_IN * float(f.get("share") or STACK_PHOTO_SHARE)
    if f.get("caption"):
        h += LINE_H_IN["fine"] * max(1, _lines(f.get("caption"), "fine"))
    return round(h, 3)


def fig_reserve(owner, where="self", slide=None):
    """The vertical share (inches) taken up by everything outside the figure.

    Without subtracting this, the figure eats the whole slot and the
    footnote runs off the bottom of the screen, which is what happened in
    the first version, which drew the figure into a fixed-size slot.
    """
    r = 0.0
    # When `parts` is used, all the text lives inside chunks. Looking only
    # at the pane gives 0, and then the figure eats the whole pane,
    # pushing its sibling chunks off the screen.
    for p in (owner.get("parts") or []):
        r += fig_reserve(p) + 0.06          # 0.06 = gap between chunks
    for key, what in (("lead", "lead"), ("formula", "formula"), ("bullets", "bullet"),
                      ("foot", "foot"), ("head", "head"),
                      # `text` had never once been counted. Put a figure
                      # and text together in a pane and the text gets
                      # pushed down.
                      ("text", "text"), ("fine", "fine")):
        r += _lines(owner.get(key), what) * LINE_H_IN[what]
    blk = owner.get("block")
    if blk:
        # The spec's key is `text`. Looking it up as `body` instead would
        # leave the box text's height never counted, so on a slide with a
        # box the figure eats the whole slot and the box gets cut off the
        # screen. The title also takes up one line.
        if isinstance(blk, dict):
            r += _lines(blk.get("title"), "block") * LINE_H_IN["block"]
            body = blk.get("text")
        else:
            body = blk
        r += _lines(body, "block") * LINE_H_IN["block"] + 0.18
    if where in ("left", "right") and slide is not None:
        # in two columns, the whole slide's header and footer are also shared by both panes
        for key, what in (("lead", "lead"), ("formula", "formula"), ("foot", "foot"),
                          ("fine", "fine")):
            r += _lines(slide.get(key), what) * LINE_H_IN[what]
        if slide.get("figure"):
            r += 1.55                      # a full-width figure placed above the two columns
    elif where == "self" and (owner.get("left") or owner.get("right")):
        # The opposite direction: a full-width figure placed on a
        # two-column slide has to leave room for the height the two panes
        # below will use. Without this, the full-width figure takes up
        # the whole slot and the two lines of explanation run off the
        # screen. LaTeX stays quiet about it; only `outcheck` catches it,
        # since the text is present in the source.
        r += max(fig_reserve(owner.get(sd) or {}) for sd in ("left", "right"))
    # If there's a photo below a diagram, subtract its height, since
    # without it the diagram eats the whole slot.
    if where == "self" and stacked(owner):
        r += stacked_photo_in(owner) + 0.10
    # Feedback: however much the compiled result reported as overflow.
    # Chunks and panes have no slide number, so they aren't caught here;
    # this is added only once, per slide.
    _ref = slide if isinstance(slide, dict) else owner
    r += EXTRA_RESERVE.get(_ref.get("n"), 0.0) if isinstance(_ref, dict) else 0.0
    return round(r, 3)


def slot(what, where="self", pane_width=None, reserve=0.0):
    """Returns the slot a figure will occupy, in inches, -> (width, height).

    `what`    : "chart" | "diagram"
    `where`   : "self" for full width, "left"/"right" for one pane of a two-column layout
    `reserve` : vertical space (inches) taken up by everything outside the figure — counted by `fig_reserve()`
    """
    cap = SLOT_H_IN["pane" if where in ("left", "right") else what]
    h = min(cap, max(0.95, BODY_H_IN - float(reserve or 0.0)))
    if where in ("left", "right"):
        w = TEXT_W_IN * (float(pane_width or 0.5) - PANE_GAP)
    else:
        w = TEXT_W_IN
    return (round(w, 3), round(h, 3))


# Font size (pt) for an impact slide. Measured on one example deck, not a matter of taste.
#   number    40pt  (the big size is used only for numbers)
#   words     14pt  (sentences/questions use this size)
BIG_PT_NUMBER = 40.0
BIG_PT_WORDS = 14.0
# Numbers in a paired layout. Since three sit side by side, they're smaller than a single-line one.
BIG_PT_PAIRED = 34.0

# Longer than this, and it's words, not a value.
BIG_VALUE_CHARS = 12


def big_text(v, gap=None):
    """Turns `big` into one line a human reads. If it's a list, joins the values with `gap`.

    List layout was added to all three builders, but not to the reading
    set, so a Python dict was printed into the script's title, and
    `outcheck` produced four permanent false positives. Adding a feature
    to one builder and not the others in the same pass keeps causing this
    kind of drift, so this reading logic is kept in one place and every
    builder pulls from here.
    """
    if v is None:
        return ""
    if not isinstance(v, list):
        return str(v)
    out = []
    for b in v:
        b = b if isinstance(b, dict) else {"value": b}
        # A word item is written as `text` (`{text: "fast charge"}`). Skip
        # reading it and the script's title comes up empty.
        bit = str(b.get("value", b.get("text", "")))
        if b.get("label"):
            bit = "%s %s" % (b["label"], bit)
        if b.get("note"):
            bit = "%s (%s)" % (bit, b["note"])
        out.append(bit)
    # The word that joins a pair is the spec's `gap`. Without it, a slide
    # asking for "or" would come out as "vs" in the script instead.
    sep = str(gap).strip() if gap and len(out) == 2 else "vs"
    return ("  %s  " % sep).join(x for x in out if x)


def big_parts(v):
    """The text pieces `big` puts on screen. The checker matches them one by one."""
    if v is None:
        return []
    if not isinstance(v, list):
        return [str(v)]
    out = []
    for b in v:
        b = b if isinstance(b, dict) else {"value": b}
        for k in ("value", "text", "label", "note"):
            if b.get(k):
                out.append(str(b[k]))
    return out


def big_pt(text):
    """Decides the size (pt) of one chunk of an impact slide from its content.

    A fixed 40pt lets a thirty-seven-character phrase cover the whole
    screen, which reads as "way too big" once shown. The big size is
    used only for numbers; words are 14pt, and impact comes from the
    black screen and the whitespace.

    What splits them isn't "does it mix in letters" but "is it a short
    value." `39x`, `1.9x`, `53%` are values. Banning letters outright
    would classify `39x` as words and shrink it to 14pt.
    """
    s = strip_markup(str(text)).strip()
    # If it has the shape of an equation (only digits and operators),
    # it's a value even with spaces: "36 + 29" would otherwise be
    # classified as words for having two spaces, and its pair "62" would
    # shrink along with it.
    arith = bool(re.fullmatch(r"[\d\s.,+\-−×x/=≈<>≤≥%±()~]+", s))
    short = len(s) <= BIG_VALUE_CHARS and (s.count(" ") <= 1 or arith)
    return (BIG_PT_NUMBER if short and any(c.isdigit() for c in s)
            else BIG_PT_WORDS)


def slot_cm(what, where="self", pane_width=None, reserve=0.0):
    """The same slot as the `max height` string `build_deck` writes into the LaTeX."""
    return "%.2fcm" % (slot(what, where, pane_width, reserve)[1] * 2.54)

# What the spec can hold: this is the single source. Writing the same
# table by hand into the docs too lets it drift apart, which is what
# happened before. `python scripts/deckspec.py --keys` prints this same table.
SLIDE_KEYS = [
    ("kind", "Slide kind. If omitted, inferred from the content: " + "/".join(KINDS)),
    ("title", "Slide title. Top of the screen"),
    ("lead", "One line right below the title. What this slide is asking"),
    ("formula", "One definition (`$…$`) to show big, once, centered below `lead`. The target equation of a theory paper. Use this instead of an impact slide"),
    ("bullets", "Bullet list. Uses inline emphasis"),
    ("steps", "Numbered steps (algorithm/procedure), one step per line, equations as `$…$`. Rendered where bullets go, as \"1.\" \"2.\""),
    ("big", "Big number or one phrase for an impact slide (required for standout). Given as a list, set side by side: [{value, label, note, mark}, ...]"),
    ("gap", "The word to place between two big numbers set side by side. If it contains a number (\"3 days sooner\"), it goes small on the name line and \"vs\" goes between the numbers. A connector (\"or\") goes between the numbers"),
    ("lines", "Below an impact slide, line by line, separately: [\"sentence\", {text: \"...\", size: small}]. size = large | normal | small"),
    ("flow", "An impact slide's vertical flow: [\"first box\", \"next box\", \"last box\"]. An arrow goes between them and the last box gets bigger. `big` sets things side by side, but this runs top to bottom: what leads to what"),
    ("figure", "One figure: {path, width, height, lead, caption, shows} "
               "or an image grid via {grid: ...}"),
    ("chart", "Draws a figure from a table in the spec: {from, kind: tiles|heat|bars|dots|lines}. "
              "Use `panels: [{title, from}, ...]` to set the same grid side by side for "
              "two subjects, so the same cell of each can be compared by eye. "
              "`tiles` fills every cell so it reads as a field, not a table. "
              "`col_notes`/`row_label`/`col_label` name the axes"),
    ("diagram", "A diagram drawn without a table: {kind, ...}. A way to give a slide that would "
                "otherwise be bullets only (intro/interpretation/limitations/conclusion) something to look at.\n"
                "  flow  boxes and arrows\n"
                "  stack layers. What sits on top of what\n"
                "  grid  the combination of two axes\n"
                "  strip a strip of named cells: draws structure. "
                "each of `rows` is {label, sub, cells:[{label, span, mark}], note}, "
                "or {bars, groups, group_label, mark_at} for grouped bars. "
                "Give `outer` and one more outer group strip appears above it (two levels). "
                "`legend` names the roles. Layout, schedules, windows, token sequences\n"
                "  pipeline the flow of stages: each of `rows` is {label, sub, "
                "stages:[{label, group, count, mark}], out}. A group heading spans "
                "several stages, with a divider between groups. Processing pipelines, workflows"),
    ("table", "A table: {header, rows, align, size, note}"),
    ("block", "A bordered box: {title, text, kind: plain|alert|good}"),
    ("left", "Left pane of a two-column layout (columns)"),
    ("right", "Right pane of a two-column layout (columns)"),
    ("foot", "One or two lines of small text at the bottom of the slide. The conclusion or explanation goes here"),
    ("fine", "One step smaller than `foot`: a final group for notation, definitions, caveats. Stack this at a different weight than the conclusion sentence; at one weight, the reader can't tell what to read"),
    ("note", "Speaker note. Not shown on screen, only in the script and the PPTX notes"),
    ("say", "What to say aloud (original language). Not shown on screen"),
    ("ko", "What to say aloud (Korean). Not shown on screen"),
    ("cue", "Delivery direction: pointing by hand, advancing the slide. Not shown on screen"),
    ("pause", "Seconds of silence after this slide. Counted in the timing"),
    ("ask", "A question likely to come up on this slide, with its answer. Not shown on screen; collected at the end of the script"),
    ("backup", "true means a backup slide. Moves behind the main deck and is excluded from the page numbers and the timing"),
    ("n", "Set the slide number directly (not normally used)"),
]
def pane_leaves(pane):
    """Expands one pane into the chunks that are actually drawn.

    Once `parts` was added, "a pane's content" gained one more layer of
    depth. If each checker expands it its own way, sooner or later one
    falls behind, and the checker that falls behind can't see that
    content has disappeared. So there's only one place that expands it: here.
    """
    if not pane:
        return []
    ps = pane.get("parts")
    if not ps:
        return [pane]
    out = []
    for p in ps:
        out += pane_leaves(p)
    return out


def panes(slide):
    """All (side, chunk) pairs on this slide. Empty list unless it's `columns`."""
    out = []
    for side in ("left", "right"):
        for leaf in pane_leaves(slide.get(side)):
            out.append((side, leaf))
    return out


PANE_KEYS = [
    ("width", "Left pane's width ratio, 0.15-0.85 (`left` only)"),
    ("parts", "Several chunks, in order: [{...}, {...}]. Each chunk uses the rest of this table's keys (except `width`/`parts`). Using it means this pane's other keys aren't used, since an order set in two places would drift apart.\n  e.g.: table -> one-line explanation -> box. Or subheading+text -> bullets."),
    ("size", "Make one chunk one step smaller: `fine`. Used for an added caveat"),
    ("steps", "Numbered steps, same as the slide's `steps`. Use when one pane holds the steps and the other pane holds the reasoning for them"),
    ("head", "Pane heading. Not used together with `parts`; then the heading is the first chunk's `head`"),
    ("text", "Sentence(s) inside the pane. Prose, not bullets"),
    ("bullets", "Bullets inside the pane"),
    ("figure", "A figure inside the pane"),
    ("chart", "A figure drawn inside the pane"),
    ("diagram", "A diagram inside the pane"),
    ("table", "A table inside the pane"),
    ("block", "A box inside the pane"),
]
BLOCK_KINDS = ("plain", "alert", "good")

# Keys for the nested objects: this is the single source. `--keys`
# prints it and `load` filters by it. While it was missing, an agent had
# to hunt through the SKILL body for keys, and typos disappeared silently.
META_KEYS = [
    ("title", "Talk title (title page)"),
    ("subtitle", "Subtitle"),
    ("author", "Presenter"),
    ("institute", "Institute(s). A list for multiple lines: [\"research center\", \"institution\"]"),
    ("presenter", "Presenter's name, underlined within `author`"),
    ("venue", "Conference · date"),
    ("date", "Date, appended after `venue`"),
    ("thesis", "The one sentence the talk exists to deliver. `prose_audit` checks every impact slide against it"),
    ("paper", "Path to the paper file. The checkers read the paper's words and numbers from here"),
    ("lang", "Language of the script skeleton text: en | ko. If omitted, decided by `say`"),
    ("wpm", "Speaking rate (words per minute). Used for timing"),
    ("acronyms", "Word count for reading an acronym aloud: {GPU: 3, ...}. Used for timing"),
    ("coined_ok", "List of words allowed even though they aren't in the paper (deckcheck H · prose_audit 0a)"),
    ("aspect", '"16:9" | "4:3"'),
    ("figdir", "Figure folder (relative to the spec file)"),
    ("engine", "pdflatex | xelatex | lualatex"),
    ("pptx_font", "PPTX body font"),
    ("pptx_mono", "PPTX monospace font"),
    ("cjk_font", "CJK font (xelatex/lualatex)"),
    ("base_pt", "Body text size (pt). Not normally used"),
    ("colorblind", "true adds a second channel besides color: underline for a bad value, hatching for a cell. Default is color only"),
]
HIGHLIGHT_KEYS = {"x", "y", "w", "h", "label", "mark", "label_at"}


LABEL_BAND = 0.07      # the share of the figure's height one label line takes (estimate): the height of the band whose ink is measured
LABEL_INK = 0.015      # if that band is darker than this, it's read as having text
LABEL_COVERED = []     # a label placed over the figure because there was no clean spot; build_deck reports it
_INK_CACHE = {}


def _ink(img, x0, y0, x1, y1):
    """The fraction of dark pixels in the ratio region [x0,x1]x[y0,y1] of figure `img` (path). None if it can't be opened."""
    try:
        g = _INK_CACHE.get(img)
        if g is None:
            g = _open_figure(img).convert("L")
            g.thumbnail((800, 800))
            _INK_CACHE[img] = g
        W, H = g.size
        box = (max(0, int(x0 * W)), max(0, int(y0 * H)), min(W, int(x1 * W + 0.5)), min(H, int(y1 * H + 0.5)))
        if box[2] <= box[0] or box[3] <= box[1]:
            return 0.0
        hist = g.crop(box).histogram()
        n = float(sum(hist)) or 1.0
        return sum(hist[:160]) / n
    except Exception:
        return None


def label_place(h, img=None):
    """Where on the box to put the label: whatever `label_at` says, otherwise the side that doesn't cover text inside the figure.

    Sticking it above by default meant that for a box at the top of a
    figure, the label landed on top of the panel title. With no key to
    move it, the label had to be deleted and explained via `lead`
    instead. No room above falls back to below; no room below either
    falls back to inside.

    Given `img` (the visible figure file), it measures the band the
    label would sit in. A box just 0.12 from the top can still read as
    "there's room above" and have the label cover a paper figure's panel
    title, and moving the threshold only gets it wrong on a different
    figure instead. If the band has text (ink), it moves to the next spot.
    """
    at = str(h.get("label_at") or "").lower()
    if at in ("above", "below", "inside"):
        return at
    y, hh = float(h.get("y", 0)), float(h.get("h", 0))
    x, w = float(h.get("x", 0)), float(h.get("w", 0))
    room_above, room_below = y >= 0.08, y + hh <= 0.90
    if img:
        above = _ink(img, x, max(0.0, y - LABEL_BAND), x + w, y) if room_above else None
        below = _ink(img, x, y + hh, x + w, min(1.0, y + hh + LABEL_BAND)) if room_below else None
        if above is not None or below is not None:
            if above is not None and above <= LABEL_INK:
                return "above"
            if below is not None and below <= LABEL_INK:
                return "below"
            # if there's no clean spot, pick the side that covers least;
            # inside might still be over a bar (above can cover a panel
            # title, below a tick label, inside a bar)
            inside = _ink(img, x, y, x + w, min(1.0, y + LABEL_BAND))
            cands = [(v, k) for v, k in ((above, "above"), (below, "below"), (inside, "inside"))
                     if v is not None]
            if not cands:
                return "inside"
            best = min(cands)
            # If all three spots cover the figure's text or lines, pick
            # the one that covers least, but report it, since a covered
            # tick label inside the figure is otherwise invisible to any
            # check.
            if best[0] > LABEL_INK and str(h.get("label") or "").strip():
                LABEL_COVERED.append((str(h.get("label")), best[1], best[0]))
            return best[1]
    if img and not room_above and not room_below:
        # If the box covers the figure's full height, there's no room
        # above or below, so measure inside too rather than placing it
        # there without measuring, and report it if it covers something.
        inside = _ink(img, x, y, x + w, min(1.0, y + LABEL_BAND))
        if inside is not None and inside > LABEL_INK and str(h.get("label") or "").strip():
            LABEL_COVERED.append((str(h.get("label")), "inside", inside))
        return "inside"
    if room_above:
        return "above"
    return "below" if room_below else "inside"
# `figure.highlight` is deliberately placed on top of the figure.
# `fitcheck` used to count that as "overlap on a figure," so the skill's
# own feature failed the skill's own check. The builder leaves a
# name/list, and `fitcheck` excludes only that from figure overlap;
# overlap between labels, or with other text, is still checked as before.
HIGHLIGHT_TAG = "p2t-highlight"
HIGHLIGHT_LIST = "highlights.txt"
BACKUP_LIST = "backup_pages.txt"     # PDF page numbers of backup slides, read by `fitcheck`
HLFIG_LIST = "hlfig_pages.txt"       # pages where a pasted paper figure has a highlighted spot, read by `fitcheck`


def pasted_with_highlight(node):
    """Is there a pasted figure (`path`) with a `highlight` on it? Looks inside panes and chunks too."""
    if isinstance(node, dict):
        if node.get("path") and node.get("highlight"):
            return True
        # A slide that lays out several paper panels at a glance (`grid`)
        # counts too: it's a spot for showing "every case" as a shape.
        # Reading the tick labels isn't the point; pointing out which of
        # them is the next slide's job.
        if node.get("grid") and any(isinstance(r, list) and r for r in (node["grid"].get("images") or [])):
            return True
        return any(pasted_with_highlight(v) for v in node.values())
    if isinstance(node, list):
        return any(pasted_with_highlight(v) for v in node)
    return False


def highlight_labels(node):
    """The label text of every `highlight`, wherever it is in the spec."""
    out = []
    if isinstance(node, dict):
        hs = node.get("highlight")
        if hs is not None:
            for h in ([hs] if isinstance(hs, dict) else list(hs or [])):
                if isinstance(h, dict) and h.get("label"):
                    out.append(plain(str(h["label"])))
        for k, v in node.items():
            if k != "highlight":
                out += highlight_labels(v)
    elif isinstance(node, list):
        for v in node:
            out += highlight_labels(v)
    return out
FIGURE_KEYS = [("path", "Figure file"), ("lead", "One line above the figure"),
               ("picture", "Declares that this is not a data figure (a map, a photo of the setup), so there's nothing to redraw; write the reason. Excluded from `prose_audit`'s \"just pasted it in\" check. A data figure with coordinates not in the paper (e.g. a scatter plot) uses `highlight`, not this"),
               ("crop", "Only one panel of a figure: {x, y, w, h}, as a ratio 0-1 measured from the figure's top-left. The deck and the PPTX share the same cropped PNG. `highlight` is relative to the cropped figure"),
               ("highlight", "A box marking what to look at, on a pasted figure: {x, y, w, h, label, mark} (a list also works). Ratio 0-1 measured from the figure's top-left. For when the result exists only in the figure"),
               ("share", "Share of the body height when placed below a diagram (default 0.24)"),
               ("caption", "One line below the figure"), ("max_height", "Height cap (e.g. '0.5\\textheight')"),
               ("width", "Width"), ("height", "Height"),
               ("shows", "The count the figure holds, checked against a phrase like \"three sites\" in the body text"),
               ("grid", "An image grid: see the grid table below")]
GRID_DOC = [("images", "List of image paths, per row"), ("cols", "Column names"),
            ("rows", "Row names"), ("mark", "ok | fail per column: border"),
            ("caption", "One line below each column"), ("max_height", "Grid height cap"),
            ("gap", "Gap between cells")]
TABLE_KEYS = [("header", "Header row"), ("rows", "Rows"), ("align", "Column alignment: 'lrr'. If omitted, numeric columns are right-aligned"),
              ("size", "One step smaller text: small | fine"), ("note", "One line below the table")]
BIG_ITEM_KEYS = [("value", "Big number"), ("label", "Name above the number"), ("note", "Condition below the number"),
                 ("mark", "hit | safe: bad / good (the paper's verdict)"), ("text", "Words instead of a number"), ("kind", "Not normally used")]
CHART_KEYS = [
    ("from", "Which table: self (the table of this slide/pane)"),
    ("kind", "tiles | heat | bars | dots | lines. dots is a dot plot: since the axis is the data's own range, "
             "differences between closely clustered values show up. lines is a line plot: each row is a point [series, x, y]"),
    ("log", "Make dots/lines' x-axis log-scaled (true), for when values span more than tenfold. lines also supports y and both. Not used with bars"),
    ("xlabel", "x-axis name for dots/lines"),
    ("title", "Title inside the figure"), ("note", "One line below, inside the figure"),
    ("takeaway", "The conclusion, written bold inside the figure"),
    ("verdict", "What the colors mean: {hit: 'over budget', plain: 'within budget'}. Written below the grid. `plain` is the unmarked cell (a cell the paper didn't rule on is unmarked), `safe` is a green cell"),
    ("share_rows", "If panel row names match, show them on the left only once (true). Default is per panel"),
    ("panels", "The same grid for two subjects: [{title, from, table}, ...]"),
    ("table", "A table used only by this chart (instead of the slide's table)"),
    ("col_notes", "One line below each column header"), ("row_label", "Row axis name"),
    ("col_label", "Column axis name"), ("ylabel", "y-axis name for bars"),
    ("callout", "A short phrase above the bars: {at, text, series, mark}. `at` = a row name or 0-based row number; "
                "`series` = 0-based series index (default 0). Color follows the pointed bar's <hit>/<safe>, or the ink color if none, "
                "or set directly with `mark: hit|safe`. lines uses {series, at: x value, text} to point at one point"), ("values", "Print the values above the bars (true)"),
    ("caption", "One line below the figure (deck)"), ("max_height", "Height cap"),
]
CHART_PANEL_KEYS = {"title", "from", "table"}
# Only the keys each kind actually draws. Otherwise a key can be accepted
# but never drawn: heat's `col_notes` used to pass validation and
# disappear silently, yet get written into the sidecar, so even
# `outcheck` counted it as "delivered."
_CHART_COMMON = {"from", "kind", "table", "caption", "max_height", "takeaway"}
CHART_KIND_KEYS = {
    "tiles": _CHART_COMMON | {"title", "note", "verdict", "share_rows", "panels",
                              "col_notes", "row_label", "col_label"},
    "heat": _CHART_COMMON | {"title", "note"},
    "bars": _CHART_COMMON | {"title", "ylabel", "note", "callout", "values", "log"},
    "dots": _CHART_COMMON | {"xlabel", "ylabel", "log"},
    "lines": _CHART_COMMON | {"xlabel", "ylabel", "log", "callout"},
}
DIAGRAM_KEYS = [
    ("kind", "flow | stack | grid | strip | pipeline | graph. graph is nodes with crossing edges"),
    ("nodes", "graph's nodes: [{id, label, col, row, mark, shape: box|oval}]. col/row are grid positions starting at 0"),
    ("edges", "graph's edges: [{from, to, kind: data|control|state|plain, label, bend, mark}]"),
    ("edge_names", "Legend names per edge kind, for graph: {data: '…', control: '…'}"),
    ("boxes", "Boxes for flow/stack/grid: [{label, mark}, ...]"),
    ("rows", "Rows for strip/pipeline / row names for grid"),
    ("cols", "Column names for grid"),
    ("title", "Title inside the figure"), ("note", "One line below, inside the figure"),
    ("takeaway", "Conclusion inside the figure"), ("legend", "Role names: {a: '...', b: '...'}. Drawn only for strip; other diagrams use a `note` line instead"),
    ("axis", "strip's axis"), ("separate", "pipeline: box each stage in a dashed border (\"stage\", true means the same). If unused, a divider is drawn only where the group changes"),
    ("gap", "strip: gap between cells"), ("caption", "One line below the figure (deck)"),
    ("max_height", "Height cap"),
]
PIPE_ROW_KEYS = [("label", "Row name (the system)"), ("sub", "Below the name (one-line description)"),
                 ("stages", "The stages"), ("out", "What exits at the end"),
                 ("caption", "A fact attached to the whole row"), ("loop", "A loop back: from `out` to the start"),
                 ("skip", "A skip: {from, to, label, mark} (a list also works). Exits before the `from` stage, passes over the boxes, and enters at the `to` stage. Residual connections, bypasses. from/to are stage numbers (0-based, -1 = last) or names"),
                 ("frame", "Groups stages into one frame: {label, note, mark}. \"these stages are one system\"")]
PIPE_FRAME_KEYS = {"label", "note", "mark"}
PIPE_STAGE_KEYS = [("label", "Stage name"), ("inner", "Lines inside the box: ['Step 1', '...', 'Step N']"),
                   ("glyph", "Pictogram inside the box: grid · funnel · widen"), ("sub", "Italicized name inside the box"),
                   ("group", "Group name: stages with the same value share one header"),
                   ("count", "Count below the box"), ("mark", "Role a | b | c | d (hit | safe for bad/good)"),
                   ("feed", "What feeds into this stage: one per input, on the stage that receives it"),
                   ("width", "Width ratio")]
# Keys that were accepted but never drawn: they passed validation and
# disappeared silently from the screen, with nothing pointing to where
# they should go instead.
PIPE_MOVED = {
    ("row", "feed"): "A row's `feed` isn't drawn. Write the input on the stage that receives it "
                     "(`stages: [{label: filter, feed: {label: sensor, sub: ...}}, ...]`). "
                     "One per stage if there are several inputs",
    ("row", "note"): "A pipeline row's `note` isn't drawn. A fact attached to the whole row is `caption`, "
                     "an explanation inside a frame is `frame.note`, one line below the figure is `diagram.note`",
    ("stage", "loop"): "A stage's `loop` isn't drawn. A loop-back goes on the row instead, one per row (`rows[].loop`)",
    ("stage", "out"): "A stage's `out` isn't drawn. What exits at the end goes on the row instead, one per row (`rows[].out`)",
}
STRIP_ROW_KEYS = {"label", "sub", "cells", "note", "bars", "groups", "group_label", "outer", "axis",
                  "mark_at", "rnote", "left", "right", "gap", "legend", "span", "mark"}


# Is it a photo (a figure that can't be redrawn)? Decided by
# measurement. Across 37 paper figures, photos had a top-32-color share
# <=0.41 and >=13k colors; diagrams/charts had >=0.49 and <=6.5k. The
# threshold sits between the two.
PHOTO_TOP32_MAX = 0.45
PHOTO_COLOURS_MIN = 8000


def is_photo(path):
    """True if it's a photo or experiment frame. None if it can't be opened."""
    try:
        from PIL import Image
        from collections import Counter
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((400, 400))
            px = list(im.getdata()) if not hasattr(im, "get_flattened_data") \
                else list(im.get_flattened_data())
    except Exception:
        return None
    c = Counter(px)
    top = sum(v for _, v in c.most_common(32)) / float(max(1, len(px)))
    return top <= PHOTO_TOP32_MAX and len(c) >= PHOTO_COLOURS_MIN


# Second channel besides color (underline/hatching). Set by `load()` from `meta.colorblind`.
SECOND_CHANNEL = False


def _check_keys(obj, known, where, what):
    """An unknown key is an error. Says which object and which key, and points to `--keys`."""
    if not isinstance(obj, dict):
        return
    ks = {k for k, _ in known} if known and isinstance(next(iter(known)), tuple) else set(known)
    bad = sorted(set(obj) - ks)
    if bad:
        raise ValueError("%s: %s has unknown key(s) %s. If it's a typo, it disappears from the screen "
                         "silently. Keys you can use: %s  (`deckspec.py --keys`)"
                         % (where, what, ", ".join(bad), ", ".join(sorted(ks))))



# Which slide kind actually draws which key.
#
# While this didn't exist, the schema accepted any key, and a builder
# that didn't use a key silently dropped it. A full sweep found thirteen
# such combinations, such as `table` attached to `kind: content`, `foot`
# attached to `kind: standout`, `figure` attached to `kind: table`: all
# passed validation, zero build warnings, and vanished from the screen.
# `outcheck` does catch it after rendering, but by then it's already
# been built and typeset.
#
# The right move is to reject a key the moment it's given, if that slide
# kind won't use it. Rejecting typos while accepting "a spot that can't
# be drawn" is inconsistent.
COMMON_KEYS = {"kind", "n", "note", "say", "ko", "cue", "pause", "backup", "ask"}
RENDERS = {
    # The title page pulls its text from `meta`. Accepted because many people also write
    # `title:` out of habit and the value matches anyway; it isn't content that disappears.
    "title":    {"title"},
    "content":  {"title", "bullets", "foot", "fine", "block", "lead", "formula"},
    "standout": {"big", "gap", "flow", "bullets", "table", "lead", "lines"},
    "figure":   {"title", "figure", "chart", "diagram", "bullets", "foot",
                 "fine", "block", "lead", "formula"},
    "table":    {"title", "table", "bullets", "foot", "fine", "block", "lead", "formula"},
    # `columns`' `figure`/`chart` is a full-width figure straddling the
    # two columns. This was once rejected as "a combination that splits
    # the two outputs," which was the wrong call: a figure on top with
    # the two panes below explaining its two sides is a useful layout.
    # What was actually split wasn't the layout but the fact that the
    # PPTX didn't draw it, and the fix was to bring the two into line,
    # not to block the feature.
    "columns":  {"title", "left", "right", "foot", "fine", "block", "lead", "formula",
                 "figure", "chart", "diagram"},
}
# Also says where to move a key that doesn't belong there. Reject it
# with no alternative and whoever's writing it just deletes the key
# instead; the content disappears either way.
MOVE_HINT = {
    ("content", "table"): "switch to kind: table, or put it in one pane of columns",
    ("content", "figure"): "switch to kind: figure",
    ("content", "big"): "kind: standout uses big; if what should show big is an equation, use `formula:`",
    ("standout", "formula"): "an impact slide's big text is `big`; for a defining equation, use `formula:` on a regular slide",
    ("standout", "foot"): "an impact slide has no footnote; move it into bullets, or onto the next slide",
    ("standout", "fine"): "don't put fine print on an impact slide, it's unreadable projected",
    ("content", "flow"): "a vertical flow is only for kind: standout, it's a device for a turning point",
    ("figure", "flow"): "a vertical flow is only for kind: standout",
    ("table", "flow"): "a vertical flow is only for kind: standout",
    ("columns", "flow"): "a vertical flow is only for kind: standout",
    ("standout", "block"): "an impact slide has no box, use bullets",
    ("standout", "figure"): "a figure belongs on a kind: figure slide",
    ("figure", "table"): "a table belongs on a kind: table slide, or in a pane of columns",
    ("figure", "big"): "a big number belongs on kind: standout",
    ("table", "figure"): "switch to columns to put the table and figure side by side",
    ("table", "big"): "a big number belongs on kind: standout",
    ("columns", "table"): "put the table inside one of the left/right panes",
    ("columns", "figure"): "put the figure inside one of the left/right panes",
    ("columns", "big"): "a big number belongs on kind: standout",
}

# An image grid: names for rows and columns, a result border per column. `mark` is a meaning, not a color.
GRID_KEYS = {"cols", "rows", "images", "mark", "caption", "max_height", "gap"}
GRID_MARKS = ("ok", "fail")

# Inline emphasis. Reading through one example deck showed this is the
# reading device itself: a reader can skim just the red and green
# without reading the whole table and still catch the point. With only
# one means of emphasis, that whole device disappears, and no matter
# what fills the slides, it becomes a bullet deck.
#
#     **bold**            where to look
#     <hit>-12.3</hit>    a value the paper judged bad — a significant drop, a missed target, etc. (red)
#     <safe>value</safe>  an effect/recommendation the paper showed (green). An unjudged value is unmarked
#     <hi>value</hi>      other emphasis (use sparingly)
#
#   Dark red/green don't read on a dark background (standout), so the
#   output side switches to a light variant; two sets of colors are kept.
# `**bold**` has to come before `*italic*`. Reverse the order and `**x**`
# splits into two italics.
MARKUP = re.compile(
    # `**… *down***`: the closing `***` closes the italic, then the bold.
    # Closing at the first `**` instead breaks the italic and prints the
    # asterisk on screen.
    # An asterisk right after a number is a significance marker
    # (`0.128**`), so reading it as markup would print "0.128 and 0.214*"
    # bold in a regression table. An opening asterisk can't come right
    # after a digit.
    # An asterisk right after a letter, `_`, or `^` is also notation
    # (`B_*`, `C^*`, `L*`). With two such markers on one line, the gap
    # between them can be swallowed as italic, producing `B_\emph{…}` and
    # crashing pdflatex.
    r"(?<![\w*^])\*\*(?P<b>.+?)\*\*(?!\*)"
    r"|(?<![\w*^])\*(?P<i>[^*\n]+?)\*"
    r"|<hit>(?P<hit>.+?)</hit>"
    r"|<safe>(?P<safe>.+?)</safe>"
    r"|<hi>(?P<hi>.+?)</hi>"
    # `` `code` ``: a paper's function/command name. With no markup for
    # it, the deck would print the backticks as-is and the PPTX couldn't
    # use a monospace font. Double backticks (``…'') are LaTeX quotes, so
    # they're excluded.
    r"|(?<!`)`(?!`)(?P<c>[^`\n]+?)(?<!`)`(?!`)", re.S)

MARK_KINDS = ("b", "i", "hit", "safe", "hi", "c")
CODE = re.compile(r"(?<!`)`(?!`)([^`\n]+?)(?<!`)`(?!`)")


def emphasis(s):
    """Does it have emphasis markup? Code doesn't count as emphasis. Used to decide "marks what to look at" / "the last cell is green"."""
    return any(_which(m)[0] != "c" for m in MARKUP.finditer(str(s or "")))


def _which(m):
    for k in MARK_KINDS:
        if m.group(k) is not None:
            return k, m.group(k)
    return "b", m.group(0)


# Turns a hand-typed arrow into the character. Telling whoever writes the
# spec to type → directly is unreasonable, since it isn't a key on the
# keyboard, and printing `->` as-is reads on screen as clutter, not a symbol.
_ARROW = ((re.compile(r"(?<![-<>=])-{1,2}>"), "\u2192"),
          (re.compile(r"<-{1,2}(?![-<>=])"), "\u2190"))


def arrows(s):
    """`->` `-->` -> →,  `<-` `<--` -> ←. Leaves other symbols untouched."""
    s = str(s or "")
    for pat, ch in _ARROW:
        s = pat.sub(ch, s)
    return s


# A `> ` before a bullet is an indented line with no bullet mark: a caveat line at the end of a list.
NO_BULLET = re.compile(r"^>\s+")


def head_is_caption(leaf):
    """Is a pane's heading a caption for what to look at (centered, small), or a subheading for the text (left, bold)?"""
    return bool(leaf.get("figure") or leaf.get("chart") or leaf.get("diagram")
                or leaf.get("table"))


def bullet_of(b):
    """One bullet -> (text, whether it has a bullet mark)."""
    s = str(b)
    m = NO_BULLET.match(s)
    return (s[m.end():], False) if m else (s, True)


def strip_markup(s):
    """For the script and checks. Strips only the markup, keeps the text.

    Strips nested markup too. Unwrapping only one layer would leave the
    asterisks in `<safe>… *whether* …</safe>` as-is, printed into the
    figure and the script.
    """
    s = NO_BULLET.sub("", arrows(s))
    out = MARKUP.sub(lambda m: _which(m)[1], s)
    return out if out == s else strip_markup(out)


# Equations only work in the deck; the PPTX prints the raw source as-is.
# Without conversion, `$p<10^{-4}$` shows up on the PowerPoint screen with
# the dollar signs and braces intact, and since the digits still match,
# no checker catches it either, which is where the two outputs silently
# drift apart. So outputs that can't use LaTeX (PPTX, script) get it
# converted to plain characters instead.
_SUP = {"-": "⁻", "+": "⁺", "0": "⁰", "1": "¹", "2": "²",
        "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷",
        "8": "⁸", "9": "⁹", "n": "ⁿ"}
_SUB = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
        "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉"}
# Letter subscripts/superscripts too: without this, `\\beta_1^t` comes
# out as "β₁^t," `m_t` as "mt." Doesn't depend on the font even when the
# glyph is missing, since the PPTX falls back to a baseline-shifted run
# and the deck prints it back as `$^{t}$`.
_SUP.update({"=": "⁼", "(": "⁽", ")": "⁾", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ",
             "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "i": "ⁱ", "j": "ʲ", "k": "ᵏ",
             "l": "ˡ", "m": "ᵐ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ",
             "u": "ᵘ", "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ", "T": "ᵀ"})
# Uppercase superscripts too: without them, `\Sigma^{(L+1)}` prints in
# the PPTX as "Σ^((L+1))." Layer numbers/dimensions (L, N, K) are common
# superscripts in theory papers. Uppercase letters missing from Unicode
# (C, F, Q, S, X, Y, Z) stay as `^(…)`.
_SUP.update({"A": "ᴬ", "B": "ᴮ", "D": "ᴰ", "E": "ᴱ", "G": "ᴳ", "H": "ᴴ", "I": "ᴵ",
             "J": "ᴶ", "K": "ᴷ", "L": "ᴸ", "M": "ᴹ", "N": "ᴺ", "O": "ᴼ", "P": "ᴾ",
             "R": "ᴿ", "U": "ᵁ", "V": "ⱽ", "W": "ᵂ"})
_SUB.update({"-": "₋", "+": "₊", "=": "₌", "(": "₍", ")": "₎", "a": "ₐ", "e": "ₑ",
             "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ",
             "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ",
             "x": "ₓ"})
# Greek letters and common math symbols share one table, used by the
# deck (carried into pdflatex) and the PPTX/script (carried into plain
# characters). Without it, `\\beta` prints raw in the PPTX for
# math/stats/optimization papers, and pdflatex chokes on β/Σ in the body text.
GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
MATH_SYM = {
    "infty": "∞", "nabla": "∇", "partial": "∂", "sum": "∑", "prod": "∏",
    "in": "∈", "notin": "∉", "neq": "≠", "ne": "≠", "sim": "∼", "propto": "∝",
    "cdot": "·", "cdots": "⋯", "ldots": "…", "dots": "…", "forall": "∀",
    "exists": "∃", "emptyset": "∅", "subset": "⊂", "subseteq": "⊆", "cup": "∪",
    "cap": "∩", "to": "→", "rightarrow": "→", "leftarrow": "←", "mapsto": "↦",
    "le": "≤", "ge": "≥", "mid": "|", "lVert": "‖", "rVert": "‖", "|": "‖",
    "langle": "⟨", "rangle": "⟩", "top": "⊤", "circ": "∘", "sqrt": "√",
    "lessapprox": "≲", "lesssim": "≲", "gtrapprox": "≳", "gtrsim": "≳", "equiv": "≡",
    "perp": "⊥", "times": "×", "leftrightarrow": "↔", "Rightarrow": "⇒",
    "ell": "ℓ", "hbar": "ℏ", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "wedge": "∧", "vee": "∨",
    "checkmark": "✓", "cmark": "✓", "xmark": "✗", "times": "×",
    # Operators from theory papers: without `\otimes`, pdflatex chokes
    #   in the deck and the command is left as-is in the PPTX (as with
    #   the NTK's Θ ⊗ Id). The deck (amssymb) and the PPTX/script share
    #   the same table.
    "otimes": "⊗", "oplus": "⊕", "odot": "⊙", "bigotimes": "⨂", "bigoplus": "⨁",
    "setminus": "∖", "supset": "⊃", "supseteq": "⊇", "iff": "⟺", "Leftrightarrow": "⇔",
    "implies": "⇒", "longrightarrow": "⟶", "longmapsto": "⟼", "uparrow": "↑",
    "downarrow": "↓", "ast": "∗", "bullet": "•", "triangleq": "≜", "int": "∫",
    "cong": "≅", "simeq": "≃", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    # Order/negation symbols: without this, `\succeq 0` and `\nrightarrow
    #   0` are left as commands in the PPTX (positive-semidefiniteness,
    #   non-convergence).
    "succeq": "⪰", "preceq": "⪯", "succ": "≻", "prec": "≺", "nrightarrow": "↛",
    "nleftarrow": "↚", "neg": "¬", "lnot": "¬", "nleq": "≰", "ngeq": "≱",
}
_SYM = [(r"\\dagger", "†"), (r"\\ddagger", "‡"), (r"\\star", "★"),
        (r"\\Delta", "Δ"), (r"\\times", "×"), (r"\\pm(?![a-zA-Z])", "±"),
        (r"\\leq", "≤"), (r"\\geq", "≥"), (r"\\approx", "≈"),
        (r"\\ll", "≪"), (r"\\gg", "≫"), (r"\\textminus", "−"),
        (r"\\%", "%"), (r"\\&", "&"), (r"\\,", " "), (r"\\;", " ")]


def _sub_script(m):
    """A subscript. If Unicode subscript characters exist for every character, use those;
    if it's one character, keep it as is; if it's several characters and only some have a
    Unicode form, fall back to plain text with a `_`, since mixing the two would produce
    something half-lowered like "dₘₒdₑₗ" (from `d_{model}`)."""
    body = (m.group(1) or m.group(2) or "")
    if body and all(c in _SUB for c in body):
        return "".join(_SUB[c] for c in body)
    # A letter with no Unicode subscript form keeps the `_`, since
    # dropping it would glue `$R_T$` into "RT" and read as an unrelated
    # symbol. A symbol subscript (`_*`) is kept as-is.
    if len(body) == 1 and body.isalpha():
        return "_" + body
    if len(body) <= 1:
        return body
    return "_" + body


def _sup_body(body):
    """One braced superscript — Unicode if every character converts, otherwise `^(…)` (held as placeholder \\x01, turned into `^` later)."""
    if body and all(c in _SUP for c in body):
        return "".join(_SUP[c] for c in body)
    if len(body) == 1 and not body.isalnum():
        return body
    if len(body) <= 1:
        return "\x01" + body
    return "\x01" + (body if body.isalnum() else "(" + body + ")")


def _sub_body(body):
    """One braced subscript — same rule as `_sub_script`, multi-character expressions get parentheses."""
    if body and all(c in _SUB for c in body):
        return "".join(_SUB[c] for c in body)
    if len(body) <= 1:
        return body
    return "\x02" + (body if body.replace("_", "").isalnum() else "(" + body + ")")


def _script(m, table):
    body = (m.group(1) or m.group(2) or "")
    if body and all(c in table for c in body):
        return "".join(table[c] for c in body)
    # A symbol that already looks like a superscript, like †/★, only gets messier with a `^` added
    if len(body) == 1 and not body.isalnum():
        return body
    return "^" + body


_ACCENT = {"hat": "\u0302", "widehat": "\u0302", "tilde": "\u0303",
           "widetilde": "\u0303", "bar": "\u0304", "overline": "\u0304",
           "dot": "\u0307", "vec": "\u20D7", "check": "\u030C", "ddot": "\u0308",
           "breve": "\u0306"}
_ACCENT_TEX = {"\u0302": "hat", "\u0303": "tilde", "\u0304": "bar", "\u0307": "dot",
               "\u030C": "check", "\u0308": "ddot", "\u0306": "breve"}
_GREEK_NAME = {}


def accents_to_tex(s):
    """A letter with a combining accent (m̂, θ̃) -> `$\\hat{m}$`, `$\\tilde{\\theta}$`.

    pdflatex chokes on a combining accent, and matplotlib silently drops
    the accent while the sidecar still has the original text, so a
    checker that only reads the sidecar would pass it anyway. The deck
    and the figures convert it with the same function.
    """
    if not _GREEK_NAME:
        _GREEK_NAME.update({v: k for k, v in GREEK.items()})

    def one(m):
        base, acc = m.group(1), m.group(2)
        name = _GREEK_NAME.get(base)
        inner = ("\\" + name) if name else base
        return "$\\%s{%s}$" % (_ACCENT_TEX[acc], inner)
    return re.sub(u"([A-Za-z\u0370-\u03ff])([%s])" % "".join(_ACCENT_TEX), one, str(s))


_ATOM = re.compile(r"^√?(?:\\?[A-Za-z]+|[\u0370-\u03ff√])[\u0300-\u036f]*\s*(?:[_^]\s*(?:\{[^{}]*\}|\S)\s*){0,2}$")


def _group(x, i):
    """From `x[i]`, skip whitespace and take one braced group: (contents, position after the end). (None, i) if there's none."""
    while i < len(x) and x[i] == " ":
        i += 1
    if i >= len(x) or x[i] != "{":
        return None, i
    d = 0
    for j in range(i, len(x)):
        d += {"{": 1, "}": -1}.get(x[j], 0)
        if d == 0:
            return x[i + 1:j], j + 1
    return None, i


def _paren(g):
    g = g.strip()
    # "√(1-ᾱ)" is already one chunk wrapped in parentheses, so don't wrap it a second time
    if re.fullmatch(r"√\([^()]*\)", g):
        return g
    return g if len(g) <= 1 or _ATOM.match(g) else "(%s)" % g


def _frac_sqrt(x):
    """`\\frac{a}{b}` -> a/b, `\\sqrt{a}` -> √a. Works from the inside out, tracking brace balance."""
    out, i = [], 0
    pat = re.compile(r"\\(?:[dt]?frac|sqrt)(?![A-Za-z])")
    while True:
        m = pat.search(x, i)
        if not m:
            out.append(x[i:])
            return "".join(out)
        out.append(x[i:m.start()])
        if "frac" in m.group(0):
            a, j = _group(x, m.end())
            b, k = _group(x, j) if a is not None else (None, j)
            if a is None or b is None:
                out.append(m.group(0))
                i = m.end()
                continue
            out.append("%s/%s" % (_paren(_frac_sqrt(a)), _paren(_frac_sqrt(b))))
            i = k
        else:
            a, j = _group(x, m.end())
            if a is None:
                out.append("√")
                i = m.end()
                while i < len(x) and x[i] == " ":
                    i += 1
                continue
            out.append("√" + _paren(_frac_sqrt(a)))
            i = j


def math_words(x):
    """Turns math commands into visible characters: Greek letters, accents (x̂, X̃), fractions, square roots, font commands."""
    # font/text commands: keep only the contents
    x = re.sub(r"\\(?:mathbf|mathrm|mathit|mathsf|mathcal|mathbb|boldsymbol|bm|pmb|text|"
               r"textrm|textbf|textit|operatorname)\s*\{([^{}]*)\}", r"\1", x)
    # Greek letters are converted before accents, since otherwise
    # `\\bar\\theta` is left as "\\barθ."
    x = re.sub(r"\\(%s)(?![A-Za-z])" % "|".join(sorted(GREEK, key=len, reverse=True)),
               lambda m: GREEK[m.group(1)], x)
    x = re.sub(r"\\(%s)\s*\{([^{}]*)\}" % "|".join(_ACCENT),
               lambda m: m.group(2) + _ACCENT[m.group(1)], x)
    x = re.sub(r"\\(%s)(?![A-Za-z])\s*([A-Za-z\u0370-\u03ff])" % "|".join(_ACCENT),
               lambda m: m.group(2) + _ACCENT[m.group(1)], x)
    # Fractions and roots are read by brace balance. A regex that stops
    # at the inner brace of `\frac{D^2\sqrt{T}}{\alpha(1-\beta_1)}` would
    # drop the division and read it as the product "D²√Tα(1-β₁)" with no
    # warning.
    x = _frac_sqrt(x)
    x = re.sub(r"\\not\s*(\\to|\\rightarrow|\\in|=|\\subset|\\equiv)",
               lambda m: {"\\to": "↛", "\\rightarrow": "↛", "\\in": "∉", "=": "≠",
                          "\\subset": "⊄", "\\equiv": "≢"}[m.group(1)], x)
    x = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)(?![A-Za-z])", "", x)
    x = re.sub(r"\\(?:rm|bf|it|sf|tt)(?![A-Za-z])\s*", "", x)
    # A function name becomes text, with a space inserted if a letter
    # follows, since otherwise `\cos\gamma` prints in the PPTX as "\cosγ."
    # If a letter precedes it too (`\cdot\min`), a space goes there as
    # well, since otherwise it becomes the nonexistent command "\cdotmin"
    # and prints raw in the PPTX.
    x = re.sub(r"(?<=[A-Za-z])(?=\\(?:log|ln|exp|max|min|sup|inf|lim|liminf|limsup|arg|det|tr|sign|Pr|sin|cos|tan|cot|sec|csc|sinh|cosh|tanh|arcsin|arccos|arctan|dim|ker|deg|gcd|lg|hom)(?![A-Za-z]))", " ", x)
    x = re.sub(r"\\(log|ln|exp|max|min|sup|inf|lim|liminf|limsup|arg|det|tr|sign|Pr|E|"
               r"sin|cos|tan|cot|sec|csc|sinh|cosh|tanh|arcsin|arccos|arctan|dim|ker|deg|gcd|"
               r"lg|hom)(?![A-Za-z])\s*(?=(.?))",
               lambda m: m.group(1) + (" " if m.group(2) and (m.group(2).isalnum()
                                                              or m.group(2) == "\\") else ""), x)
    x = re.sub(r"\\([A-Za-z]+|\|)",
               lambda m: GREEK.get(m.group(1)) or MATH_SYM.get(m.group(1)) or m.group(0), x)
    x = x.replace("\\qquad", "  ").replace("\\quad", " ").replace("\\ ", " ")
    # drop invisible placeholders, since otherwise `\phantom{0}99` becomes "099"
    x = re.sub(r"\\[hv]?phantom\s*\{[^{}]*\}", "", x)
    # pifont symbols: without this, `\\ding{55}` leaves just the
    # argument, printing "55" in a table cell meant to hold an X mark.
    x = re.sub(r"\\ding\s*\{\s*(\d+)\s*\}",
               lambda m: {"51": "✓", "52": "✓", "55": "✗", "56": "✗"}.get(m.group(1), ""), x)
    # An unknown command's argument is text. Stripping the whole command
    # would drop its argument too, so a paper macro like `\bolds{q=20\%}`
    # would lose the "q" along with the command name. Keeps only the argument.
    x = re.sub(r"\\[A-Za-z]+\s*\{([^{}]*)\}", r"\1", x)
    return re.sub(r"\\[!:,;>]", " ", x)


# A currency symbol is not math. Without this, the two `$` in "from
# $30,230 to $81,980" are read as math and pdflatex chokes, and escaping
# with `\$` instead prints "\30,230" in the PPTX. A number with
# thousands-separator commas, or a number followed by a word or end of
# sentence, is a dollar sign. `$5 \times 10$`, `$0.5$` are still read as math.
CURRENCY = re.compile(r"(?<![\\$\w])\$(?=\d{1,3}(?:,\d{3})+(?![\d^_{])"
                      r"|\d+(?:\.\d+)?(?:\s+[A-Za-z]{1,12}\b|[KMB]\b|\s*$|[,.;:)](?:\s|$)))")
CUR = u"\ue011"


def hold_currency(s):
    """Replaces a currency `$` and an already-escaped `\\$` with a placeholder, so math processing doesn't touch them."""
    return CURRENCY.sub(CUR, str(s)).replace("\\$", CUR)


def math_to_text(s):
    """Turns `$...$` into plain text. Used by outputs that can't use LaTeX."""
    return _math_to_text(hold_currency(s or "")).replace(CUR, "$")


def _math_to_text(s):
    s = str(s or "")
    # An unmatched `$` is a literal dollar sign. Reading "(in $)" as math
    # would turn all the following text into math too. Only resolved as
    # math when the `$` are paired.
    if len(re.findall(r"(?<!\\)\$", s)) % 2:
        return s.replace("\\$", "$")

    def one(m):
        x = m.group(1)
        # An old-style font switch like `{\rm crit}` is also one chunk.
        # Knowing only `\mathrm` would leave "\rm" printed as-is in the
        # PPTX for a paper that uses this notation throughout.
        x = re.sub(r"\{\s*\\(?:rm|bf|it|sf|tt|cal)(?![A-Za-z])\s*([^{}]*)\}", r"{\1}", x)
        # A text command (`\text{large}`) is one chunk. Stripping it
        # first would turn `_\text{large}` into `_large`, sending only
        # the first letter to subscript ("RoBₗarge"). Keeping the braces
        # protects the chunk.
        x = re.sub(r"\\(?:text|textbf|textit|textrm|textsf|mathrm|mathbf|mathit|mathsf|"
                   r"operatorname)\s*\{([^{}]*)\}", r"{\1}", x)
        while re.search(r"\{\{[^{}]*\}\}", x):
            x = re.sub(r"\{\{([^{}]*)\}\}", r"{\1}", x)
        for a, b in _SYM:
            x = re.sub(a, b, x)
        x = math_words(x)
        x = x.replace("{=}", "=").replace("{<}", "<").replace("{>}", ">")
        # A chunk inside a sub/superscript (`{x}`, what's left from
        # `\mathbf{x}`) gets its braces stripped. Without this, the
        # double braces in `\mathbb{E}_{t,\mathbf{x}_0,\epsilon}` glue it
        # into "Et,x₀,ε" instead. A chunk right after a
        # subscript/superscript marker (`_{…}`) is its boundary, so it's
        # kept.
        for _ in range(3):
            x = re.sub(r"(?<![_^{])\{([^{}_^]*)\}(?=[^{}]*\})", r"\1", x)
        # Resolved from the inside out, over several passes. Resolving
        # only once would leave the outer superscript of
        # `e^{m(x^{(1)})-m(x)}` unmatched because of the inner braces,
        # mangling it into "em(x(1))-m(x)." A multi-character expression
        # that can't be converted is left as `^(…)`, since without the
        # parentheses there's no way to tell where the
        # subscript/superscript ends.
        for _ in range(6):
            y = re.sub(r"\^\{([^{}]*)\}", lambda k: _sup_body(k.group(1)), x)
            # A multi-character subscript left without parentheses
            # (`_layer`) gets a space inserted if a letter follows it,
            # since otherwise a factor of a product glues on, reading as
            # "n_layerd_model" in a table cell.
            y = re.sub(r"_\{([^{}]*)\}(?=(.?))",
                       lambda k: _sub_body(k.group(1)) + (
                           " " if (k.group(2).isalnum() and _sub_body(k.group(1)).startswith("\x02")
                                   and not _sub_body(k.group(1)).endswith(")")) else ""), y)
            if y == x:
                break
            x = y
        x = re.sub(r"\^(\S)", lambda k: _script(k, _SUP), x)
        x = re.sub(r"_(\S)", _sub_script, x)
        return re.sub(r"[{}]", "", x).replace("\x01", "^").replace("\x02", "_")

    s = re.sub(r"\$([^$]*)\$", one, s)
    # Commands left outside `$` are converted with the same table too (a bare `\dagger` used without math mode)
    for a, b in _SYM:
        s = re.sub(a, b, s)
    return re.sub(r"\\(%s)(?![A-Za-z])" % "|".join(GREEK), lambda m: GREEK[m.group(1)], s)


_ONES = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split())
         if w != "_"}
_NUMWORD = re.compile(r"\b(?:(%s)(?:[-\s]+(%s))?|(%s))(?:\s+hundred(?:\s+(?:and\s+)?(%s)(?:[-\s]+(%s))?"
                      r"|\s+(?:and\s+)?(%s))?)?\b" % ("|".join(_TENS), "|".join(list(_ONES)[1:10]), "|".join(_ONES),
                                           "|".join(_TENS), "|".join(list(_ONES)[1:10]),
                                           "|".join(_ONES)), re.I)


def number_words(text):
    """Numbers written as words -> digits: "forty-nine" -> 49, "three hundred and twelve" -> 312. 0-999.

    A script writes numbers as words. Counting only digits would leave a
    value marked as "not used" just because the script wrote it as
    "forty-nine." Used only on a copy for comparison; it doesn't change
    the on-screen text.
    """
    def one(m):
        tens, unit, single, h_tens, h_unit, h_single = m.groups()
        v = (_TENS[tens.lower()] + (_ONES[unit.lower()] if unit else 0)) if tens else _ONES[single.lower()]
        if re.search(r"hundred", m.group(0), re.I):
            v = v * 100 + ((_TENS[h_tens.lower()] + (_ONES[h_unit.lower()] if h_unit else 0))
                           if h_tens else (_ONES[h_single.lower()] if h_single else 0))
        return str(v)
    out = _NUMWORD.sub(one, text or "")
    # "80 percent" is 80% — the numeric comparison looks for the percent sign
    return re.sub(r"(\d)\s*(?:percent|per\s+cent)\b", r"\1%", out, flags=re.I)


def plain(s):
    """The final form used when an output can't use LaTeX. Strips both markup and math."""
    return math_to_text(strip_markup(s))


def render_markup(s, handlers):
    """Takes `{"b": fn, "hit": fn, "safe": fn, "hi": fn}` and converts per output.

    Goes all the way inside. Converting only the outer layer would leave
    the inner asterisks of `<safe>… *whether* …</safe>` printed as-is on
    screen, which happened once, on page 13 of a deck. The inner text is
    always shorter, so the recursion terminates.
    """
    def sub(m):
        k, text = _which(m)
        return handlers[k](render_markup(text, handlers))
    return MARKUP.sub(sub, str(s or ""))


def slurp(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


_INPUT = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
# The body's braces are matched up to three levels deep. Matching only
# one level would leave `\newcommand{\bmu}{{\boldsymbol{\mu}}}`
# unexpanded, and a table's "$\tilde\bmu$ prediction" left as just "prediction."
_B1 = r"\{[^{}]*\}"
_B2 = r"\{(?:[^{}]|%s)*\}" % _B1
_B3 = r"\{(?:[^{}]|%s)*\}" % _B2
_MACRO_DEF = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\\([A-Za-z]+)\}?\s*(?:\[0\])?\s*"
    r"\{((?:[^{}]|%s)*)\}"
    r"|\\def\\([A-Za-z]+)\s*\{((?:[^{}]|%s)*)\}" % (_B3, _B3))


def read_tex(path, base=None, seen=None):
    """Reads the manuscript as one chunk. Follows `\\input`/`\\include`. Strips comments.

    For a paper split across several files (common with USENIX/ACM),
    without this `scaffold` produces only "section 1 -> slide 1" and
    `diffcheck` ends up as an empty check.

    Paths are resolved relative to the main file's folder, as LaTeX does.
    A commented-out `\\input` is not followed.
    """
    top = seen is None
    seen = set() if seen is None else seen
    ap = os.path.abspath(path)
    if ap in seen or not os.path.isfile(ap):
        return ""
    if top:
        # only on the top-level call: toggles live in the main file and are used in the `\input`-ed files
        return tex_accents(resolve_toggles(read_tex(path, base, seen)))
    seen.add(ap)
    src = slurp(ap)
    if not ap.lower().endswith(".tex"):
        return src
    base = base or os.path.dirname(ap)
    src = re.sub(r"(?<!\\)%.*", "", src)
    # What's inside `\iffalse … \fi` is deleted text. Without this, a
    # discarded abstract ("quadrupling!") is read as part of the
    # manuscript and enters the A/H comparison.
    src = re.sub(r"\\iffalse\b.*?\\fi\b", "", src, flags=re.S)

    def inline(m):
        cand = os.path.join(base, m.group(1).strip())
        if not os.path.isfile(cand) and os.path.isfile(cand + ".tex"):
            cand += ".tex"
        if not os.path.isfile(cand):
            return m.group(0)
        return "\n" + read_tex(cand, base, seen) + "\n"
    return _INPUT.sub(inline, src)


def _braced_arg(s, i):
    """From `s[i:]`, one `{…}` after whitespace — (contents, position after the end), or None."""
    while i < len(s) and s[i] in " \t\n":
        i += 1
    if i >= len(s) or s[i] != "{":
        return None
    d = 0
    for j in range(i, len(s)):
        if s[j] == "{" and (j == 0 or s[j - 1] != "\\"):
            d += 1
        elif s[j] == "}" and (j == 0 or s[j - 1] != "\\"):
            d -= 1
            if d == 0:
                return s[i + 1:j], j + 1
    return None


def resolve_toggles(src, state=None):
    """Keeps only one branch of `\\iftoggle{x}{true}{false}`, according to that manuscript's toggle state.

    Reading both branches would produce the author list twice and a
    section title in two versions. The state lives in the manuscript
    itself: `\\newtoggle{x}` is false, and `\\toggletrue{x}`/`\\togglefalse{x}` change it.
    """
    state = dict(state or {})         # an inner branch is also resolved using the outer state
    for m in re.finditer(r"\\(newtoggle|toggletrue|togglefalse)\s*\{([^{}]+)\}", src):
        state[m.group(2).strip()] = (m.group(1) == "toggletrue")
    if not state and "\\iftoggle" not in src:
        return src
    out, i = [], 0
    pat = re.compile(r"\\(?:iftoggle|iftoggleverb)\s*\{([^{}]+)\}")
    while True:
        m = pat.search(src, i)
        if not m:
            out.append(src[i:])
            return "".join(out)
        a = _braced_arg(src, m.end())
        b = _braced_arg(src, a[1]) if a else None
        if not a or not b:
            out.append(src[i:m.end()])
            i = m.end()
            continue
        out.append(src[i:m.start()])
        keep = a[0] if state.get(m.group(1).strip(), False) else b[0]
        out.append(resolve_toggles(keep, state) if "\\iftoggle" in keep else keep)
        i = b[1]


_ACC = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303",
        "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b",
        "c": "\u0327", "k": "\u0328", "r": "\u030a"}
_ACC_LET = {"i": "\u0131", "o": "\u00f8", "O": "\u00d8", "ss": "\u00df", "ae": "\u00e6",
            "AE": "\u00c6", "oe": "\u0153", "OE": "\u0152", "aa": "\u00e5", "AA": "\u00c5",
            "l": "\u0142", "L": "\u0141"}


def tex_accents(src):
    """Letter accents (`R{\\'e}`, `R\\'{e}`, `\\"o`, `\\c{c}`) to Unicode.

    Left unconverted, "R'e" breaks the author's name, and the deck's "Ré"
    becomes a word not in the source of truth.
    """
    import unicodedata

    def one(m):
        return unicodedata.normalize("NFC", m.group(2) + _ACC[m.group(1)])
    # Inner braces matched only in pairs. Matching `\{?…\}?\}` more
    # loosely would swallow the outer closing brace of `{R{\'e}}` too,
    # leaving `\author{… R{\'e}}` unclosed and the last author gone.
    s = re.sub(r"\{\\(['`^\"~=.])\s*([A-Za-z])\}", one, src)
    s = re.sub(r"\{\\(['`^\"~=.])\s*\{([A-Za-z])\}\}", one, s)
    s = re.sub(r"\\(['`^\"~=.])\s*\{([A-Za-z])\}", one, s)
    s = re.sub(r"\\(['`\"~=])([A-Za-z])", one, s)
    s = re.sub(r"\{?\\([uvHckr])\s*\{([A-Za-z])\}\}?", one, s)
    s = re.sub(r"\{\\(ss|ae|AE|oe|OE|aa|AA|i|o|O|l|L)\}|\\(ss|ae|AE|oe|OE|aa|AA)(?![A-Za-z])",
               lambda m: _ACC_LET[m.group(1) or m.group(2)], s)
    return s


def expand_macros(src):
    """Expands a no-argument `\\newcommand{\\X}{text}`/`\\def\\X{text}` inline in the body. Leaves ones with arguments alone.

    Without expanding it, `\\System{}` disappears, leaving a table's row
    name "Ray" blank, while the deck's "Ray" becomes a word not in the
    source of truth.
    """
    macros = {}
    for m in _MACRO_DEF.finditer(src or ""):
        name = m.group(1) or m.group(3)
        body = m.group(2) if m.group(1) else m.group(4)
        if name and body is not None and "#" not in body:
            macros[name] = re.sub(r"\\xspace(?![A-Za-z])", "", body).strip()
    if not macros:
        return src
    src = _MACRO_DEF.sub(" ", src)
    for _ in range(2):
        for name, body in macros.items():
            src = re.sub(r"\\%s(?![A-Za-z])(\{\})?" % re.escape(name),
                         lambda _m, b=body: b, src)
    return src


_RESULT_NUM = re.compile(
    # If another number follows a multiplication mark (×, \times, x),
    # it's a size (`16$\times$16`, `4x4`)
    r"(?<![\w.])(\d{1,4}(?:\.\d+)?)"
    # If a single-letter variable follows the multiplication mark, it's a
    # coefficient in an equation (`4 × d_model`, `2 × L`), and counting it
    # as a result would make it "a value not in the deck." "3× faster" is
    # counted as-is since it's a word.
    r"(?=\s*(?:(?:\$?\s*\\times|×|x)(?![A-Za-z])(?!\s*\$?\s*\{?\d)"
    r"(?!\s*\$?\s*[A-Za-z](?![A-Za-z\d]))|\\%|%))"
    r"|(?<![\w.])(\d{1,4}\.\d+)(?![\d])"
    # Counts and rankings are results too: software/community papers say
    # things like "14th," "2000+," "400,000," and skipping any of the
    # three would leave the reverse check empty. Thousands-separator
    # numbers, `N+`, ordinals.
    r"|(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d{2,}(?=\+)|\d{1,4}(?=(?:st|nd|rd|th)\b))(?![\d]|,\d{3})")
# A section/theorem/figure number is not a result. Without this, "Lemma
# 10.2" and "section 11.7" get counted as manuscript values, and every
# one of `diffcheck`'s "value not in the deck" turns out to be a number
# like this. Split by the word right before it.
_REF_BEFORE = re.compile(
    r"(?:section|sections|sec\.|§|lemma|theorem|thm\.|eq\.|eqs\.|equation|figure|fig\.|"
    r"figs\.|table|tab\.|appendix|app\.|algorithm|alg\.|corollary|proposition|prop\.|"
    r"definition|def\.|remark|example|assumption|condition|chapter|step|line|\\ref\{)"
    r"\s*[~(]?\s*$", re.I)


def result_numbers(text):
    """Result values in the body: decimals, plus integers with a multiplier or percent sign attached (`40×`, `70%`).

    Counting only decimals would drop a systems paper's key values
    ("40×", "3.3-7.1×", "70%") entirely from `scaffold`, `diffcheck`, and
    `deckcheck` E, since the manuscript's values come in only five kinds.
    A size like `4x4` isn't a multiplier (a number follows it).
    """
    out = []
    text = text or ""
    for m in _RESULT_NUM.finditer(text):
        v = m.group(1) or m.group(2) or m.group(3)
        if _REF_BEFORE.search(text[max(0, m.start() - 16):m.start()]):
            continue
        # A dimension is not a result. Without this, `width=0.4\\textwidth`
        # and `\\vskip 0.2in` are counted as manuscript values.
        if re.match(r"\s*(?:pt|cm|mm|em|ex|in|bp|pc)\b|\s*\\(?:text|line|column|paper)(?:width|height)",
                    text[m.end():m.end() + 14]):
            continue
        # An arXiv id or DOI is not a value (`arXiv:1502.01589`, `10.1103/PhysRevLett`)
        if (re.search(r"(?:arxiv|doi|hep-\w+|astro-ph)[:/ ]?\s*$", text[max(0, m.start() - 10):m.start()], re.I)
                or text[m.end():m.end() + 1] == "/" or re.fullmatch(r"\d{4}\.\d{4,5}", v)):
            continue
        if v not in out:
            out.append(v)
    return out


def read_paper(path):
    """The manuscript as read by the checkers/skeleton builder. For `.tex`, expands `\\input`, strips comments, and expands macros."""
    if str(path).lower().endswith(".tex"):
        return expand_macros(read_tex(path))
    if str(path).lower().endswith(".pdf"):
        # A paper that exists only as a PDF: extract the text and read
        # it as Markdown (`pdf_paper.py`). Without this, opening it as
        # utf-8 breaks, and the checkers can't read a PDF manuscript at all.
        key = (os.path.abspath(path), os.path.getmtime(path))
        if key not in _PDF_CACHE:
            import pdf_paper
            _doc = pdf_paper.fitz.open(path)
            try:
                _PDF_CACHE[key] = pdf_paper.to_markdown(_doc)
            finally:
                _doc.close()
        return _PDF_CACHE[key]
    return slurp(path)


_PDF_CACHE = {}


def crop_image(src, crop, dpi=200):
    """`figure.crop`: crops one part of a figure into a PNG, placed next to the original, and returns its path.

    planning §plots calls for "just one panel," but with no way to crop
    in the spec, agents building a deck kept writing their own one-off
    script to crop panels every time. The deck and the PPTX use the same file.
    """
    x, y, w, h = (float(crop[k]) for k in ("x", "y", "w", "h"))
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(os.path.dirname(src), "%s__crop_%03d_%03d_%03d_%03d.png"
                       % (stem, round(x * 1000), round(y * 1000), round(w * 1000),
                          round(h * 1000)))
    if not (os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src)):
        im = _open_figure(src, dpi)
        W, H = im.size
        box = (int(round(x * W)), int(round(y * H)),
               int(round(min(1.0, x + w) * W)), int(round(min(1.0, y + h) * H)))
        im.crop(box).save(dst)
    try:
        _record_crop_text(src, (x, y, w, h), dst)
    except Exception:                  # recording the text is only for checking — cropping still works without it
        pass
    return dst


CROPTEXT = "croptext.tsv"


def _record_crop_text(src, box, dst):
    """Records the size of the text inside the cropped figure, known exactly from the text layer if the original is a PDF.

    Cropping turns it into a PNG, and `fitcheck` can't see the text
    inside. An uncropped original gets flagged at "5.0pt," but a
    cropped-and-pasted 5.5pt tick label passes right through, so cropping
    can become a way to dodge the check. Recording the original size and
    native width here lets `fitcheck` compute the scale from the width
    it's actually placed at on the page.
    One line: fingerprint, native width (pt), text size (pt), text, file
    """
    if not src.lower().endswith((".pdf", ".eps")):
        return
    try:
        import pymupdf as fitz
    except ImportError:      # PyMuPDF before 1.24.3 has only the old import name
        import fitz
    from PIL import Image
    x, y, w, h = box
    _doc = fitz.open(src[:-4] + ".pdf")
    try:
        pg = _doc[0]
        R = pg.rect
        clip = fitz.Rect(R.x0 + x * R.width, R.y0 + y * R.height,
                         R.x0 + min(1.0, x + w) * R.width, R.y0 + min(1.0, y + h) * R.height)
        rows = []
        for b in pg.get_text("dict", clip=clip)["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln.get("spans", []):
                    t = sp.get("text", "").strip()
                    c = fitz.Rect(sp["bbox"])
                    if t and clip.contains(fitz.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2)):
                        rows.append((sp["size"], t))
    finally:
        _doc.close()
    with Image.open(dst) as im:
        g = im.convert("L").resize((8, 8))
        fp = "".join("%x" % (p >> 4) for p in g.tobytes())
    path = os.path.join(os.path.dirname(dst), CROPTEXT)
    keep = []
    if os.path.isfile(path):
        with io.open(path, encoding="utf-8") as _fh:
            keep = [ln for ln in _fh.read().splitlines()
                    if ln and not ln.startswith("#") and ln.split("\t")[0] != fp]
    keep += ["%s\t%.2f\t%.2f\t%s\t%s" % (fp, clip.width, s, t.replace("\t", " "),
                                          os.path.basename(dst)) for s, t in rows]
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# fingerprint\tnative_width_pt\tsize_pt\ttext\tfile  (text inside a cropped figure, at its native size)\n")
        f.write("\n".join(keep) + ("\n" if keep else ""))


def _open_figure(src, dpi=200):
    from PIL import Image
    if src.lower().endswith((".pdf", ".eps")):
        try:
            import pymupdf as fitz
        except ImportError:      # PyMuPDF before 1.24.3 has only the old import name
            import fitz
        _doc = fitz.open(src[:-4] + ".pdf")
        try:
            pix = _doc[0].get_pixmap(dpi=dpi, alpha=False)
        finally:
            _doc.close()
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    with Image.open(src) as im:
        im.load()
        return im


def crop_cuts(src, crop, dpi=200):
    """Edges where the crop line cuts across the figure. [(edge, number of severed chunks, painted fraction)].

    If both sides right at the cut line are painted, something continues
    across that line. Cutting through text leaves several short chunks
    (cutting through the middle of a classification map once left
    "Lea…"/"Pa…," 17-28 chunks per edge), while cutting through a color
    band paints most of the line (cutting through a colorbar's tick
    numbers once made the color's meaning unreadable). Cutting through
    the whitespace between panels gives 0-3 chunks.
    """
    import numpy as np
    x, y, w, h = (float(crop[k]) for k in ("x", "y", "w", "h"))
    a = np.asarray(_open_figure(src, dpi).convert("RGB")).astype(int)
    H, W = a.shape[:2]
    ink = (a.min(axis=2) < 150) | (a.max(axis=2) - a.min(axis=2) > 60)
    x0, y0 = int(round(x * W)), int(round(y * H))
    x1, y1 = int(round(min(1.0, x + w) * W)), int(round(min(1.0, y + h) * H))
    out = []
    for edge, c, vert in (("left", x0, True), ("right", x1 - 1, True),
                          ("top", y0, False), ("bottom", y1 - 1, False)):
        lim = W if vert else H
        if c <= 1 or c >= lim - 2:          # the figure's own edge — not a cut
            continue
        both = (ink[y0:y1, c - 1] & ink[y0:y1, c + 1]) if vert else \
               (ink[c - 1, x0:x1] & ink[c + 1, x0:x1])
        if not len(both):
            continue
        runs = int(both[0]) + int(np.count_nonzero(both[1:] & ~both[:-1]))
        frac = float(both.mean())
        if runs >= 6 or frac >= 0.30:
            out.append((edge, runs, frac))
    return out


# ── PPTX text width: measured from the real font ─────────────────────────────────
# While this used an average width estimate (0.50em, 0.52em), PowerPoint
# always wrapped one or two more lines than expected. A table header
# "FDR (%)" wrapped to two lines, pushing the row down and printing the
# note below the table over the last row, and a pane's long text covered
# the next chunk. The builder and `fitcheck` used the same estimate, so
# neither caught it; only reading the output by eye did. Now both
# measure word by word from the font file and wrap at word boundaries.
_FONTS = {}


def _font(name, bold):
    key = (name, bool(bold))
    if key not in _FONTS:
        f = None
        try:
            from PIL import ImageFont
            from matplotlib import font_manager
            path = font_manager.findfont(font_manager.FontProperties(
                family=name, weight="bold" if bold else "normal"), fallback_to_default=True)
            f = ImageFont.truetype(path, 100)
        except Exception:
            f = None
        _FONTS[key] = f
    return _FONTS[key]


def text_width_in(s, pt, bold=False, font="Arial"):
    """Width (inches) of one line of text. If the font can't be found, estimated generously at 0.55em."""
    # A hyphen before a digit is measured at the width of a minus sign.
    # The deck prints `\textminus` and the PPTX prints U+2212, but
    # measuring it as a narrow hyphen instead would make a table with
    # many negative cells wider than estimated, covering the text below
    # it in the PPTX.
    s = re.sub(r"(?<![\w\-])-(?=\d)", u"−", str(s))
    f = _font(font, bold)
    if f is None:
        return len(s) * pt * (0.60 if bold else 0.55) / 72.0
    return f.getlength(s) / 100.0 * pt / 72.0


def wrap_count(s, w_in, pt, bold=False, font="Arial"):
    """How many lines it wraps to at width `w_in`, wrapping at word boundaries. Newline characters count too."""
    n = 0
    sp = text_width_in(" ", pt, bold, font)
    # Breaks between words exactly at the limit. Giving it slack once
    # counted a question sentence that nearly filled the pane's width as
    # one line, but PowerPoint wrapped it anyway. Slack is given only
    # when one whole word overflows: a 3.41in number can print as one
    # line in a 3.40in cell (0.3% over). Setting the slack to 5% instead
    # once counted a header "Heads" overflowing by 3.7% as one line, but
    # PowerPoint wrapped it as "Head/s" and the note below the table
    # covered that row.
    long_ok = w_in * 1.015
    for para in str(s or "").split("\n"):
        words = para.split()
        if not words:
            n += 1
            continue
        lines, cur = 1, 0.0
        for wd in words:
            ww = text_width_in(wd, pt, bold, font)
            if cur and cur + sp + ww > w_in:
                lines += 1
                cur = ww
            else:
                cur = cur + (sp if cur else 0.0) + ww
            while cur > (long_ok if cur == ww else w_in) and w_in > 0:   # a long word wraps character by character
                lines += 1
                cur -= w_in
        n += lines
    return n


def spit(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def infer_kind(s):
    if s.get("kind"):
        return s["kind"]
    if s.get("big") or s.get("flow"):
        return "standout"
    # A figure plus left/right panes means a two-column slide. A
    # full-width figure on top with the two panes below explaining its
    # two different sides is a valid layout. `RENDERS["columns"]`
    # already allows it, but sending it to `figure` here instead would
    # make the next check reject it as "figure doesn't draw
    # left/right," rejecting a layout the docs themselves recommend and
    # leaving whoever wrote it exactly as the docs say to just give up
    # on that layout.
    if s.get("left") or s.get("right"):
        return "columns"
    if s.get("figure") or s.get("chart") or s.get("diagram"):
        return "figure"
    if s.get("table"):
        return "table"
    return "content"


# Double-quoted YAML turns `\t`, `\f`, `\b`, `\v`, `\a`, `\r` into control
# characters, and there's no reason for these to appear in slide text.
# `\n` can be a legitimate line break, so it's only flagged when a LaTeX
# command name follows it.
_CTRL = {"\t": "t", "\f": "f", "\b": "b", "\v": "v", "\a": "a", "\r": "r"}
_NL_CMD = re.compile(r"\n(u|abla|eq|ot|ewline|ormalsize|oindent|leq|geq|i)\b")


def yaml_escapes(node, path, where="", found=None):
    """Finds LaTeX swallowed by double quotes. Finds all of them and reports which keys at once, then stops.

    Stopping at the first one found would mean fixing and re-running
    discovers them one at a time, as happened once when `\\r` was used in two places."""
    top = found is None
    found = [] if top else found
    if isinstance(node, dict):
        for k, v in node.items():
            yaml_escapes(v, path, "%s.%s" % (where, k) if where else str(k), found)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yaml_escapes(v, path, "%s[%d]" % (where, i), found)
    elif isinstance(node, str):
        bad = [c for c in node if c in _CTRL]
        m = _NL_CMD.search(node)
        if bad or m:
            c = bad[0] if bad else "\n"
            found.append("%s: `\\%s` (%r)" % (where, _CTRL.get(c, "n"), node[:40]))
    if top and found:
        raise ValueError(
            "%s: a backslash inside double quotes was swallowed as a control character, %d spot(s): %s. "
            "Use single quotes for a value with LaTeX: '0.19\\textheight'. "
            "If double quotes are required, double the backslash (`\\\\`)."
            % (path, len(found), " · ".join(found)))


def load(path):
    """Reads slides.yaml and validates it.

    Doesn't let anything slide silently. If a typo in a key ships a
    slide out empty, that gets discovered at the podium.
    """
    try:
        spec = yaml.safe_load(slurp(path)) or {}
    except yaml.YAMLError as e:
        # A YAML error is reported in one line, with the line number and
        # the likely cause, rather than buried at the end of a
        # thirty-line Python traceback.
        mk = getattr(e, "problem_mark", None)
        where = (" line %d col %d" % (mk.line + 1, mk.column + 1)) if mk else ""
        try:
            _ln = slurp(path).splitlines()[mk.line] if mk else ""
        except Exception:
            _ln = ""
        # the hint is added only when it fits that line, since attaching
        # the backslash hint to a bracket error sends the fix to the wrong place
        _hint = (". This line has a backslash inside double quotes: for a value with LaTeX, use single quotes: '$\\alpha$'"
                 if re.search(r'"[^"]*\\[^"]*"', _ln) else "")
        raise ValueError("%s%s: can't read the YAML: %s%s%s"
                         % (path, where, getattr(e, "problem", None) or str(e).splitlines()[0],
                            (" \"%s\"" % _ln.strip()[:60]) if _ln else "", _hint))
    yaml_escapes(spec, path)
    meta = spec.get("meta") or {}
    slides = spec.get("slides") or []
    if not slides:
        raise ValueError("%s: slides is empty" % path)
    _check_keys(meta, META_KEYS, path, "meta")
    # Accepts author/title even if written as a list. Left as-is, it
    # would print `['Ann', 'Bo']` on the title page. `institute` is
    # meant to take a list (one entry per line).
    for _k in ("author", "title", "subtitle", "venue", "presenter"):
        if isinstance(meta.get(_k), list):
            meta[_k] = ", ".join(str(x) for x in meta[_k] if x)
    global SECOND_CHANNEL
    SECOND_CHANNEL = bool(meta.get("colorblind"))
    # No builder read `date`, so it silently disappeared from the title
    # page. Appending it onto `venue` here means the deck, PPTX, and
    # script all see the same text.
    if meta.get("date"):
        meta["venue"] = " · ".join(str(x) for x in (meta.get("venue"), meta["date"]) if x)

    known = {k for k, _ in SLIDE_KEYS}
    pane_known = {k for k, _ in PANE_KEYS}
    block_kinds = BLOCK_KINDS

    def check_table(t, where):
        _check_keys(t, TABLE_KEYS, where, "table")
        if not t.get("rows"):
            raise ValueError("%s: table.rows is missing" % where)
        w = len(t.get("header") or t["rows"][0])
        for r, row in enumerate(t["rows"], 1):
            if len(row) != w:
                raise ValueError("%s table row %d: %d cell(s), header has %d"
                                 % (where, r, len(row), w))
        # Column alignment only accepts l, c, r. Without this check,
        # `pppp` would pass validation and hang pdflatex.
        _al = str(t.get("align") or "")
        if _al and re.search(r"[^lcr]", _al):
            raise ValueError("%s: table.align=%r, each column is one of l, c, r (write l instead of p{…} or X)"
                             % (where, _al))

    def check_figure(f, where):
        """One figure, or an image grid.

        Why the grid exists: when a paper has photos of the same subject
        shot under several conditions, placing those photos side by side
        can be the strongest evidence available. With only `path` in the
        spec, that slide couldn't be built at all, and the same claim
        would collapse into one line of big text. This isn't tied to any
        dataset; the images already belong to whoever's writing the
        deck, and all that's needed is layout, so it can live in the skill.
        """
        if f.get("shows") is not None:
            try:
                if int(f["shows"]) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("%s: figure.shows is the count the figure holds (an "
                                 "integer >= 1), checked against a phrase like \"three sites\" in the body text" % where)
        _check_keys(f, FIGURE_KEYS, where, "figure")
        if f.get("picture") is not None and not str(f.get("picture")).strip():
            raise ValueError("%s: figure.picture needs a reason written in it (e.g. \"map of the two "
                             "sites\"); an empty declaration isn't accepted" % where)
        _cr = f.get("crop")
        if _cr is not None:
            if not isinstance(_cr, dict) or set(_cr) - {"x", "y", "w", "h"} \
                    or not all(isinstance(_cr.get(k), (int, float)) for k in "xywh"):
                raise ValueError("%s: figure.crop is {x, y, w, h}, a ratio (0-1) measured "
                                 "from the figure's top-left" % where)
            if not (0 <= _cr["x"] < 1 and 0 <= _cr["y"] < 1 and 0 < _cr["w"] <= 1
                    and 0 < _cr["h"] <= 1 and _cr["x"] + _cr["w"] <= 1.001
                    and _cr["y"] + _cr["h"] <= 1.001):
                raise ValueError("%s: figure.crop=%r goes outside the figure" % (where, _cr))
        _hl = f.get("highlight")
        for hi, h in enumerate([_hl] if isinstance(_hl, dict) else list(_hl or []), 1):
            if not isinstance(h, dict):
                raise ValueError("%s: figure.highlight[%d] must be a {x, y, w, h} mapping" % (where, hi))
            _check_keys(h, HIGHLIGHT_KEYS, where, "figure.highlight[%d]" % hi)
            for k in ("x", "y", "w", "h"):
                v = h.get(k)
                if not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
                    raise ValueError("%s: figure.highlight[%d].%s=%r is a ratio (0-1) "
                                     "measured from the figure's top-left" % (where, hi, k, v))
            if h.get("label_at") not in (None, "above", "below", "inside"):
                raise ValueError("%s: figure.highlight[%d].label_at=%r: above · below · inside"
                                 % (where, hi, h.get("label_at")))
            if h.get("mark") not in (None, "plain", "hit", "safe"):
                raise ValueError("%s: figure.highlight[%d].mark=%r: hit (the paper judged it "
                                 "bad) · safe (judged it good) · leave empty for unjudged emphasis"
                                 % (where, hi, h.get("mark")))
        g = f.get("grid")
        if not g:
            if not f.get("path"):
                raise ValueError("%s: figure.path is missing (use figure.grid for a grid)" % where)
            return
        gbad = set(g) - GRID_KEYS
        if gbad:
            raise ValueError("%s grid: unknown key(s) %s" % (where, ", ".join(sorted(gbad))))
        imgs = g.get("images")
        if not imgs or not imgs[0]:
            raise ValueError("%s grid: images is missing" % where)
        nc = len(imgs[0])
        for r, row in enumerate(imgs, 1):
            if len(row) != nc:
                raise ValueError("%s grid row %d: %d image(s), first row has %d"
                                 % (where, r, len(row), nc))
        for key, want, what in (("cols", nc, "column"), ("rows", len(imgs), "row"),
                                ("mark", nc, "column"), ("caption", nc, "column")):
            v = g.get(key)
            if v and len(v) != want:
                raise ValueError("%s grid: %s has %d, but there are %d %s(s)"
                                 % (where, key, len(v), want, what))
        for m in (g.get("mark") or []):
            if m and m not in GRID_MARKS:
                raise ValueError("%s grid: mark must be one of %s (got %r)"
                                 % (where, "/".join(GRID_MARKS), m))

    # What each diagram kind must have. Without this, the figure
    # generator dies with a traceback, telling nobody which slide or
    # what was wrong.
    DIAG_NEEDS = {
        "flow": ("boxes", "list of boxes: boxes: [{label: ...}, ...]"),
        "stack": ("boxes", "layers stacked bottom to top: boxes: [{label: ...}, ...]"),
        "grid": ("boxes", "cells written as one flat list: boxes: [...], "
                          "plus cols:/rows: for the axis names"),
        "strip": ("rows", "rows of the strip: rows: [{label, cells or bars}, ...]"),
        "pipeline": ("rows", "rows: rows: [{label, stages: [...]}, ...]"),
        "graph": ("nodes", "nodes: nodes: [{id, label, col, row}, ...], edges: [{from, to, kind}]"),
    }

    def check_chart(c, where):
        if not isinstance(c, dict):
            raise ValueError("%s: chart must be a mapping" % where)
        _check_keys(c, CHART_KEYS, where, "chart")
        _kind = c.get("panels") and "tiles" or c.get("kind", "heat")
        if c.get("panels") and c.get("kind", "tiles") != "tiles":
            raise ValueError("%s: chart.panels only draws as tiles, kind: %s is ignored. "
                             "Remove kind or set it to tiles" % (where, c.get("kind")))
        _dead = sorted(set(c) - CHART_KIND_KEYS.get(_kind, set(c)))
        if _dead:
            _who = [k for k, v in sorted(CHART_KIND_KEYS.items()) if set(_dead) <= v]
            raise ValueError("%s: chart kind=%s doesn't draw %s, it won't appear on "
                             "screen, but the check counts it as delivered. %s"
                             % (where, _kind, ", ".join(_dead),
                                ("Kind(s) that draw this key: " + ", ".join(_who)) if _who else
                                "Remove it, or move it to the slide's caption/lead"))
        for pi, p in enumerate(c.get("panels") or [], 1):
            _check_keys(p, CHART_PANEL_KEYS, where, "chart panels[%d]" % pi)
            if isinstance(p, dict) and p.get("table"):
                check_table(p["table"], where)
        if c.get("table"):
            check_table(c["table"], where)

    def check_diagram(d, where):
        if not isinstance(d, dict):
            raise ValueError("%s: diagram must be a mapping" % where)
        _check_keys(d, DIAGRAM_KEYS, where, "diagram")
        # Only `strip` draws a legend. Other diagrams used to accept it
        # and silently drop it instead, so this is blocked here in one
        # place, regardless of kind.
        if d.get("legend") and d.get("kind", "flow") not in ("strip", "pipeline"):
            raise ValueError("%s: a %s diagram doesn't draw `legend`, write what the mark "
                             "means as one `diagram.note` line instead (a `graph`'s edge meanings are `edge_names`)"
                             % (where, d.get("kind", "flow")))
        if d.get("kind") == "pipeline":
            if d.get("legend"):
                # pipeline doesn't draw a legend either; it used to be
                # accepted and silently dropped.
                raise ValueError("%s: pipeline doesn't draw `legend`, write what the mark "
                                 "means as a `diagram.note` line (\"red border = check this first\")" % where)
            for ri, r in enumerate(d.get("rows") or [], 1):
                for (lv, k), msg in PIPE_MOVED.items():
                    if lv == "row" and isinstance(r, dict) and k in r:
                        raise ValueError("%s: pipeline rows[%d]: %s" % (where, ri, msg))
                    if lv == "stage":
                        for si, st in enumerate((r or {}).get("stages") or [], 1):
                            if isinstance(st, dict) and k in st:
                                raise ValueError("%s: pipeline rows[%d].stages[%d]: %s"
                                                 % (where, ri, si, msg))
                _check_keys(r, PIPE_ROW_KEYS, where, "pipeline rows[%d]" % ri)
                if isinstance((r or {}).get("frame"), dict):
                    _check_keys(r["frame"], PIPE_FRAME_KEYS, where,
                                "pipeline rows[%d].frame" % ri)
                for si, st in enumerate((r or {}).get("stages") or [], 1):
                    _check_keys(st, PIPE_STAGE_KEYS, where,
                                "pipeline rows[%d].stages[%d]" % (ri, si))
        if d.get("kind") == "strip":
            for ri, r in enumerate(d.get("rows") or [], 1):
                _check_keys(r, STRIP_ROW_KEYS, where, "strip rows[%d]" % ri)
        kind = d.get("kind", "flow")
        if kind not in DIAG_NEEDS:
            raise ValueError("%s: diagram.kind=%r must be one of %s"
                             % (where, kind, "/".join(sorted(DIAG_NEEDS))))
        key, why = DIAG_NEEDS[kind]
        if not d.get(key):
            raise ValueError("%s: diagram.kind=%s must have %s, %s"
                             % (where, kind, key, why))
        # `grid` needs the axis name count to match the cell count
        if kind == "grid" and d.get("cols"):
            nc = len(d["cols"])
            if nc and len(d["boxes"]) % nc:
                raise ValueError(
                    "%s: grid has %d cell(s) but %d column(s); the cell count must be a "
                    "multiple of the column count" % (where, len(d["boxes"]), nc))

    def check_pane(pane, i, side, part=0):
        """One pane, or one chunk inside that pane.

        Adding `parts` made it possible to set the same thing in two
        places: if a pane has both `text` and `parts`, the spec alone
        can't say which comes first. So mixing them is blocked here. The
        order is decided in exactly one place.
        """
        where = "slide %d %s" % (i, side)
        if part:
            where += " chunk %d" % part
        # `steps` inside a pane too: accepting it only as a slide key
        # would make it impossible to put "the steps on the left, the
        # reasoning on the right."
        if isinstance(pane, dict) and pane.get("steps") is not None:
            st_ = pane.pop("steps")
            if not isinstance(st_, list) or not st_:
                raise ValueError("%s: steps must be a list of steps" % where)
            pane["bullets"] = list(pane.get("bullets") or []) + [
                "> %d. %s" % (j, str(x)) for j, x in enumerate(st_, 1)]
        allowed = pane_known - ({"width", "parts"} if part else set())
        pbad = set(pane) - allowed
        if pbad:
            raise ValueError("%s: unknown key(s) %s%s"
                             % (where, ", ".join(sorted(pbad)),
                                "\n  -> width/parts can't be used inside a chunk"
                                if part and pbad & {"width", "parts"} else ""))
        if pane.get("size") not in (None, "fine"):
            raise ValueError("%s: size only accepts fine (got %r)"
                             % (where, pane["size"]))
        if pane.get("table"):
            check_table(pane["table"], where)
        if pane.get("figure"):
            check_figure(pane["figure"], where)
        if pane.get("diagram"):
            check_diagram(pane["diagram"], where)
        if pane.get("chart"):
            check_chart(pane["chart"], where)
        ps = pane.get("parts")
        if ps is None:
            return
        if part:
            raise ValueError("%s: parts can't be nested inside a chunk" % where)
        mixed = sorted(set(pane) - {"width", "parts"})
        if mixed:
            raise ValueError(
                "%s: parts was used together with %s, the spec alone can't say which "
                "comes first.\n  -> move %s into a chunk under parts too"
                % (where, ", ".join(mixed), ", ".join(mixed)))
        if not isinstance(ps, list) or len(ps) < 2:
            raise ValueError("%s: parts must be a list of two or more chunks; "
                             "with only one, just use that key directly" % where)
        for j, p in enumerate(ps, 1):
            if not isinstance(p, dict):
                raise ValueError("%s chunk %d is not a mapping" % (where, j))
            if not p:
                raise ValueError("%s chunk %d is empty" % (where, j))
            check_pane(p, i, side, j)

    out = []
    for i, s in enumerate(slides, 1):
        if not isinstance(s, dict):
            raise ValueError("slide %d is not a mapping" % i)
        # A shape for algorithms/procedures. With nowhere to draw
        # pseudocode, a training/sampling algorithm would otherwise end
        # up moved into the script only. Converted into numbered bullets
        # (bullet-less `> 1. …`) instead: all three outputs and every
        # checker already understand bullets.
        if s.get("steps") is not None:
            st_ = s.pop("steps")
            if not isinstance(st_, list) or not st_:
                raise ValueError("slide %d: steps must be a list of steps" % i)
            s["bullets"] = list(s.get("bullets") or []) + [
                "> %d. %s" % (j, str(x)) for j, x in enumerate(st_, 1)]
        bad = set(s) - known
        if bad:
            raise ValueError("slide %d: unknown key(s) %s, a typo?"
                             % (i, ", ".join(sorted(bad))))
        k = infer_kind(s)
        if k not in KINDS:
            raise ValueError("slide %d: kind=%r is not a known kind" % (i, k))
        # A key that kind doesn't draw is not accepted. Accept it and it disappears silently.
        allowed = set(RENDERS[k])
        # The `table` a `chart` reads from is data, not something drawn
        # on screen. A heat chart turns a table into a picture, so the
        # source table has to be in the spec, but forbidding tables there
        # would make it impossible to build a slide that turns a table
        # into a picture. This isn't a property of the `figure` kind
        # alone but of having a `chart`, so it's judged by whether there's
        # a chart, not by kind: the same table would otherwise be
        # rejected on a full-width chart placed on top of `columns`, a
        # layout the docs themselves recommend.
        if s.get("chart"):
            allowed.add("table")
        ignored = sorted(set(s) - COMMON_KEYS - allowed)
        if ignored:
            hint = MOVE_HINT.get((k, ignored[0]))
            raise ValueError(
                "slide %d: kind=%s doesn't draw %s, anything left in disappears "
                "silently from the screen.%s"
                % (i, k, ", ".join(ignored), ("\n  -> " + hint) if hint else ""))
        if k == "standout" and not (s.get("big") or s.get("flow")):
            raise ValueError("slide %d: standout but has neither big nor flow" % i)
        if s.get("flow") is not None:
            fl = s["flow"]
            if not isinstance(fl, list) or len(fl) < 2:
                raise ValueError("slide %d: flow is two or more boxes; "
                                 "with one it's not a flow but a single phrase, which belongs in big" % i)
            if any(not str(x).strip() for x in fl):
                raise ValueError("slide %d: flow has an empty box" % i)
        if k == "figure" and not (s.get("chart") or s.get("diagram")):
            f = s.get("figure") or {}
            if not (f.get("path") or f.get("grid")):
                raise ValueError("slide %d: figure has neither path nor grid, and "
                                 "there's no chart or diagram either" % i)
            check_figure(f, "slide %d" % i)
        if s.get("diagram"):
            check_diagram(s["diagram"], "slide %d" % i)
        if s.get("chart"):
            check_chart(s["chart"], "slide %d" % i)
        # A one-item list has no partner to sit beside. Sent down the
        # paired-layout path anyway, a long sentence comes out as one
        # tiny line. With no name, note, or mark, it's just converted to
        # plain text instead.
        _b = s.get("big")
        if isinstance(_b, list) and len(_b) == 1 and isinstance(_b[0], dict) \
                and not (set(_b[0]) - {"text", "value"}):
            s["big"] = str(_b[0].get("text", _b[0].get("value", "")))
        if isinstance(s.get("big"), list):
            for bi, b in enumerate(s["big"], 1):
                _check_keys(b, BIG_ITEM_KEYS, "slide %d" % i, "big[%d]" % bi)
        if k == "table":
            check_table(s.get("table") or {}, "slide %d" % i)
        if k == "columns":
            for side in ("left", "right"):
                pane = s.get(side)
                if not pane:
                    raise ValueError("slide %d: columns but %s is missing" % (i, side))
                check_pane(pane, i, side)
            lw = float(s["left"].get("width") or 0.5)
            if not 0.15 <= lw <= 0.85:
                raise ValueError("slide %d: left.width %.2f is out of range" % (i, lw))
        if s.get("block"):
            b = s["block"]
            if not b.get("title"):
                # In metropolis's `block=fill`, a block with no title renders as an empty gray bar
                raise ValueError("slide %d: block has no title "
                                 "(with no title it renders as an empty gray bar)" % i)
            if b.get("kind", "plain") not in block_kinds:
                raise ValueError("slide %d: block.kind must be one of %s"
                                 % (i, "/".join(block_kinds)))
        d = dict(s)
        # `big: {text: …}` (a single mapping) is a one-item list. Left
        # as-is, it would pass validation and print the Python repr
        # (`{'text': …}`) into the deck.
        if isinstance(d.get("big"), dict):
            d["big"] = [d["big"]]
        d["kind"] = k
        d["n"] = i
        for key in ("bullets", "say", "ko", "cue", "foot", "fine", "ask"):
            v = d.get(key) or []
            d[key] = [v] if isinstance(v, str) else list(v)
            # Spoken lines are text lines. A nested list would otherwise
            # pass validation and the build would die with a traceback.
            # Rejected here with a clear message instead.
            if key in ("say", "ko", "cue", "foot", "fine"):
                for j, x in enumerate(d[key], 1):
                    if not isinstance(x, (str, int, float)):
                        raise ValueError(
                            "slide %d: item %d of %s is not a text line but a %s, "
                            "write one sentence per line (flatten any nested list)"
                            % (i, j, key, type(x).__name__))
        d["pause"] = float(d.get("pause") or 0)
        d["backup"] = bool(d.get("backup"))
        out.append(d)

    # Backup slides move to the back. A talk ends with questions, and
    # until now the spec had no notion of "after the main deck." Putting
    # a backup slide in the middle of the main deck means it gets passed
    # over during the talk, and just leaving it at the end mixes it into
    # the page numbers and the timing, throwing off the calculation.
    # Splitting it out here, in one place, means all three outputs see
    # the same meaning.
    if any(s["backup"] for s in out):
        main_ = [s for s in out if not s["backup"]]
        out = main_ + [s for s in out if s["backup"]]
        for j, s in enumerate(out, 1):
            s["n"] = j

    # Page numbers apply only to slides other than the title page,
    # standout slides, and backup slides. Done once, here.
    page = 0
    for s in out:
        if s["kind"] in ("title", "standout") or s["backup"]:
            s["page"] = None
        else:
            page += 1
            s["page"] = page
    meta.setdefault("wpm", 135)
    meta.setdefault("aspect", "16:9")
    # Body text size is decided once, here. Figures read the same number.
    meta["base_pt"] = set_base_pt(meta)
    return meta, out, page


def numbered(slides):
    return [s for s in slides if s.get("page")]


def key_reference():
    """All usable keys, as a table. Run this instead of copying it into the docs."""
    L = ["Slide kinds:  " + "  ".join(KINDS),
         "Block kinds: " + "  ".join(BLOCK_KINDS),
         "",
         "Slide keys",
         "-" * 72]
    for k, d in SLIDE_KEYS:
        L.append("  %-10s %s" % (k, d))
    L += ["", "Pane (left/right) keys", "-" * 72]
    for k, d in PANE_KEYS:
        L.append("  %-10s %s" % (k, d))
    def sect(name, rows):
        L.extend(["", name, "-" * 72])
        for k, d in rows:
            L.append("  %-12s %s" % (k, d))
    sect("meta keys", META_KEYS)
    sect("figure keys", FIGURE_KEYS)
    sect("figure.grid keys", GRID_DOC)
    sect("table keys", TABLE_KEYS)
    sect("one item of a big list", BIG_ITEM_KEYS)
    sect("chart keys", CHART_KEYS)
    sect("diagram keys", DIAGRAM_KEYS)
    sect("pipeline's rows (rows[])", PIPE_ROW_KEYS)
    sect("pipeline's stages (rows[].stages[])", PIPE_STAGE_KEYS)
    L += ["", "Marks", "-" * 72,
          "  hit / safe   bad / good: only what the paper judged. hit is what the paper found bad (e.g. a significant",
          "               loss, a missed target), safe is an effect/recovery/recommendation the paper showed. Unjudged values are unmarked",
          "               In text/figures: failure / success, avoid / recommend, the part we're looking at (safe)",
          "  a b c d e f  a diagram's role colors: blue, amber, two grays, purple, gold. For distinctions unrelated to bad/good"]
    L += ["", "Inline emphasis", "-" * 72,
          "  **bold**            where to look",
          "  *italic*            soft emphasis",
          "  <hit>-12.3</hit>    a value the paper judged bad (red): a significant drop, a missed target, etc.",
          "  <safe>value</safe>  an effect/recommendation the paper showed (green); an unjudged value is unmarked",
          "  <hi>value</hi>      other emphasis (use sparingly)"]
    return "\n".join(L)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    USAGE = ("Usage:\n"
             "  deckspec.py slides.yaml   validates the spec (an unknown key is an error)\n"
             "  deckspec.py --keys        prints every usable key")
    if "--keys" in sys.argv[1:]:
        print(key_reference())
        sys.exit(0)
    # Without handling `--help`, it tries to read it as a file name and
    # throws a traceback, and `--help` is the first thing a first-time
    # user types.
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0 if len(sys.argv) > 1 else 2)
    m, sl, np_ = load(sys.argv[1])
    print("OK: %d slide(s) · %d numbered page(s)" % (len(sl), np_))
