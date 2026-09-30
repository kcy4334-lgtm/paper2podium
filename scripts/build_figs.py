# -*- coding: utf-8 -*-
"""Draws figures from the tables in `slides.yaml` and writes `figs/chart_*.png` files plus a sidecar.

    python scripts/build_figs.py slides.yaml -o out/figs

Why this works
  The claim that figures are tied to raw data and so cannot be made is only
  half true. A breakdown of 12 figures from a real conference deck showed
  that half needed no raw logs at all: diagrams are drawn from constants,
  and value figures just parse numbers out of the paper. Those numbers are
  already in `slides.yaml`'s tables.

What comes for free
  `deckcheck` has already checked the table's values against the source of
  truth, so a figure drawn from that table inherits that guarantee. A
  hand-drawn figure needs a separate sidecar; here the drawn value is
  written to the sidecar as-is, with no manual copy step.

Spec
    right:
      chart:
        from: left          # which pane's table to use (left/right/self)
        kind: heat          # heat | bars
        title: "..."        # optional
        ylabel: "..."       # bars only
        note: "..."         # small print below the figure

  `heat` draws the table as a row-by-column grid and colors the cells
  marked with `<hit>`/`<safe>`. Use it when the shape of the grid carries
  the point: if the marked cells cluster in one row or one corner, that
  stands out. `bars` reads the first column as item names and the rest as
  series.

Font size
  Keep the drawing width within 2x the final display width. Drawing at 13
  inches and fitting into 5.6 inches turns 10pt into 4.3pt. The default
  figsize follows this rule.
"""
import argparse
import io
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckspec
from deckspec import load, strip_markup, MARKUP, _which  # noqa: E402
import sidecar  # noqa: E402

try:
    from PIL import Image
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    import matplotlib.patches  # noqa: F401 (legend swatch)
    from matplotlib.path import Path
except ImportError:  # pragma: no cover
    raise SystemExit("matplotlib is required:  pip install matplotlib")

# Colors, weights, margins, and corners are set by `design.py`. Writing them
#   separately here would diverge from the other generators; this file once
#   had 39 scattered colors and 12 scattered line weights before that change.
import design  # noqa: E402

# Figures also use the same font as the deck. If it doesn't match, the same
#   pt shows at a different size on screen, so "figure text is smaller than
#   body text" is only kept numerically, and a mismatched ruler makes the
#   comparison meaningless.
FONT_NOTE = []
matplotlib.rcParams["font.family"] = [design.font_family(FONT_NOTE),
                                      design.FALLBACK_FAMILY]

HIT = design.line_of("hit")
SAFE = design.line_of("safe")
INK = design.INK
MUTE = design.FIG_MUTE
GRID = design.NEUTRAL_LINE
# Within 2x the display width. Raise this and on-screen text shrinks by the
#   same factor.
# Size is set by `deckspec`. Setting it separately here would diverge from
#   the embedding side; it did diverge once, and on-screen text became 4.4pt.
BODY_PT = deckspec.BODY_PT          # 10pt. The baseline for figure text
FLOOR_PT = 8.0                      # \footnotesize. The size aimed for first when fitting
WARN_PT = round(BODY_PT * 0.7, 1)   # scriptsize. Warn below this, the same ruler as fitcheck
# (figure name, text) -> what shrank it 'w'(width) | 'h'(height). build reads this when attaching a fix to a bundled warning
BOUND = {}
FS = BODY_PT                        # default box label size
FIGSIZE = (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["chart"])


# ──────────────────────────────────────────────────────────────────────
# Diagrams: give slides something to look at when they have no table.
#
# This was the skill's biggest gap. `chart` draws from a table in the spec,
#   so it only helps slides that already have a table. Slides left with only
#   bullets (intro, related work, discussion, limitations, conclusion) are
#   exactly the slides with no table, and measurement showed that was 36% of
#   slides (10% for one sample deck).
#
#   The skill doc said, in §3, that a diagram is drawn from constants and so
#   there is no reason it cannot be made, but did not provide that tool.
#   Whoever received it filled those slides with bullets, and `refcheck`
#   correctly flagged that nothing was made to show, with no way to fix it.
#
# Three kinds cover most diagrams in a paper talk:
#   flow:  boxes and arrows, for comparing what leads to what.
#   stack: layers, what sits on top of what.
#   grid:  a combination of two axes, the "A is a choice of two things" kind.
DIAG_KINDS = ("flow", "stack", "grid", "strip", "pipeline", "graph")

# Role colors come from `design.ROLES`. One role spans two channels, fill and
# outline: filling an area with a saturated color spends the figure's whole
# contrast budget on that area, so the text inside and the arrows next to it
# end up fighting it. That's why heavy fills look cheap.
ROLE_COLOURS = tuple(design.ROLES[k][1] for k in design.ROLE_ORDER)


def role_map(names):
    """Role name -> fill for a small cell: a narrow spot like a strip's cell or a legend swatch.

    A wide area (a stage box) uses `design.fill_of`, which is lighter. Using
    the same color at both sizes makes one loud and the other invisible.
    """
    return {k: v[1] for k, v in design.role_map(names).items()}


def role_ink(names):
    """Role name -> outline/text color. Used for lines and small text."""
    return {k: v[2] for k, v in design.role_map(names).items()}


def _renderer(fig):
    # `plt.close` swaps a closed figure's canvas for a bare `FigureCanvasBase`, which
    #   cannot render. Give it an Agg canvas back instead of failing.
    if not hasattr(fig.canvas, "get_renderer"):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        FigureCanvasAgg(fig)
    fig.canvas.draw()
    return fig.canvas.get_renderer()


_MEASURE = [None]


def measurer():
    """One blank figure used only to measure text. It must be measured
    before sizes are decided, so it needs to exist on its own.

    `_width_in` divides by dpi to return inches, so the result is the same
    no matter which figure measures.
    """
    if _MEASURE[0] is None:
        # Not made through pyplot, so `plt.close("all")` elsewhere cannot take its
        #   canvas away. It did in CI: every later width measurement failed.
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        _MEASURE[0] = Figure(figsize=(4, 3))
        FigureCanvasAgg(_MEASURE[0])
    return _MEASURE[0]


def text_w(s, fs, weight="normal"):
    """Width (inches) of a single line of text at `fs`."""
    return _width_in(measurer(), str(s), weight) * fs


def wrapped_w(s, fs, lines=1, weight="normal"):
    """Width (inches) when wrapped to `lines` lines."""
    parts = _wrap(str(s).split(), lines)
    return max(text_w(p, fs, weight) for p in parts)


def _width_in(fig, s, weight="normal", ref=100.0):
    """Measures a single line of text's width in inches (measured at a reference size and converted proportionally).

    Never estimate instead of measuring. An estimate once produced a screen
    where column headers overlapped into "one pump per tankone per bedone per row".
    """
    key = (id(fig), s, weight)
    cache = _width_in.cache
    if key in cache:
        return cache[key]
    tx = fig.text(0, 0, s, fontsize=ref, fontweight=weight, alpha=0)
    bb = tx.get_window_extent(renderer=_renderer(fig))
    tx.remove()
    w = bb.width / float(fig.dpi) / ref          # width per 1pt
    cache[key] = w
    return w


_width_in.cache = {}


def _wrap(words, n):
    """Splits words into `n` lines as evenly as possible, minimizing the longest line's length.

    Cannot make more lines than there are words. Without this guard,
    `combinations` returned empty, `None` leaked out, and drawing broke
    outright: the figure never drew, yet the deck still built successfully
    with the old figure, with no signal that anything was wrong.
    """
    words = _keep_math(list(words))
    n = min(int(n), max(1, len(words)))
    if n <= 1 or len(words) <= 1:
        return [mathify(" ".join(words))]
    best, bestcost = None, None
    # Few words, so try every cut point exhaustively: at most 91 combinations for 15 words
    import itertools
    idx = range(1, len(words))
    for cuts in itertools.combinations(idx, n - 1):
        parts, prev = [], 0
        for c in list(cuts) + [len(words)]:
            parts.append(" ".join(words[prev:c]))
            prev = c
        cost = max(len(p) for p in parts)
        if bestcost is None or cost < bestcost:
            best, bestcost = parts, cost
    return [mathify(p) for p in best]


def _keep_math(words):
    """`$…$` is treated as one word. If a line break cuts through the
    middle of an equation, the `$` pairing breaks and the raw LaTeX
    (`\\max(\\beta_2`) gets printed straight into the figure."""
    out, cur = [], None
    for w in words:
        cur = w if cur is None else cur + " " + w
        if cur.count("$") % 2 == 0:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


_SUB_BACK = {v: k for k, v in deckspec._SUB.items()}
_SUP_BACK = {v: k for k, v in deckspec._SUP.items()}
_GREEK_BACK = {v: k for k, v in deckspec.GREEK.items()}
_MATHCH = {"∞": "infty", "→": "rightarrow", "≤": "leq", "≥": "geq", "≠": "neq",
           "∇": "nabla", "∂": "partial", "∈": "in", "≈": "approx", "×": "times",
           "±": "pm", "−": "minus", "·": "cdot", "∙": "cdot"}


def mathify(s):
    """In text containing `$`, moves Greek letters/subscripts that are
    outside math mode into math mode.

    If matplotlib sees even one `$`, it renders the entire string as
    mathtext, and there is no font fallback in that mode: the same label's
    unicode β₂ turned into tofu boxes (□).
    """
    s = deckspec.accents_to_tex(str(s))      # matplotlib strips combining accents
    if "$" not in s:
        return s
    parts = s.split("$")
    for i in range(0, len(parts), 2):            # even indices = outside math
        seg = parts[i]
        seg = re.sub("[%s]+" % "".join(_SUB_BACK),
                     lambda m: "$_{%s}$" % "".join(_SUB_BACK[c] for c in m.group(0)), seg)
        seg = re.sub("[%s]+" % "".join(_SUP_BACK),
                     lambda m: "$^{%s}$" % "".join(_SUP_BACK[c] for c in m.group(0)), seg)
        seg = re.sub("[%s]" % "".join(_GREEK_BACK),
                     lambda m: "$\\%s$" % _GREEK_BACK[m.group(0)], seg)
        seg = re.sub("[%s]" % "".join(_MATHCH),
                     lambda m: "$\\%s$" % _MATHCH[m.group(0)], seg)
        parts[i] = seg
    return "$".join(parts).replace("$$", "")


def sibling_pt(fig, items, fs, weight="normal", max_lines=1):
    """The largest pt at which all of a set of side-by-side texts
    (`[(text, width in inches, height in inches)]`) fit.

    Sibling text is drawn at one size. Calling `fit_text` on each one
    separately only shrinks the name in the narrow cell, so a group name and
    a count on the same row got printed at mismatched sizes; to an audience,
    a different size reads as a different weight."""
    def ok(t, w, h, size):
        words = str(t).split()
        for n in range(1, max_lines + 1):
            lines = _wrap(words, n)
            if len(lines) < n and n > 1:
                break
            if (max(_width_in(fig, ln, weight) for ln in lines) * size <= w
                    and len(lines) * 1.26 * size / 72.0 <= h):
                return True
        return False
    size = float(fs)
    live = [(t, w, h) for (t, w, h) in items if str(t).strip()]
    while size > FLOOR_PT - 1.5 and not all(ok(t, w, h, size) for (t, w, h) in live):
        size -= 0.5
    return size


def fit_text(fig, ax, cx, cy, box_w, box_h, s, fs, warn=None, seen=None,
             what="", max_lines=3, max_pt=None, outer_w=None, **kw):
    """Fits text inside a box: wraps it, shrinks it, and warns if it still
    does not fit.

    `box_w`/`box_h` are in inches. Returns the pt actually used.

    Passing `max_pt` starts from there and comes down, so it can grow if
    there is room to spare. Until now this function only ever shrank, so no
    matter what was drawn, every piece of text stayed at or below body size,
    and it was impossible to make a tile number three times body size.
    Emphasis that can only come from color and fill turns a slide into a
    colored-in table.
    """
    s = str(s)
    if not s.strip():
        return fs
    weight = kw.get("fontweight", "normal")
    words = s.split()
    size = float(max_pt or fs)
    while size >= FLOOR_PT - 1.5:
        for n in range(1, max_lines + 1):
            lines = _wrap(words, n)
            if len(lines) < n:                    # can't split any further
                if n > 1:
                    break
            w = max(_width_in(fig, ln, weight) for ln in lines) * size
            h = len(lines) * 1.26 * size / 72.0
            if w <= box_w and h <= box_h:
                ax.text(cx, cy, "\n".join(lines), fontsize=size,
                        linespacing=1.26, **kw)
                # If it shrank, record what decided it (width or height). "Cut a
                #   line" or "fine" only helps when height is the constraint; cutting
                #   fine in a width-bound box made the text shrink even further.
                if size < float(max_pt or fs) - 1e-6:
                    _up = (size + 0.5) / size
                    BOUND[(what, strip_markup(s)[:48])] = "w" if w * _up > box_w else "h"
                _note_size(size, s, warn, seen, what)
                return size
        size -= 0.5
    # It still doesn't fit: don't truncate. Draw at floor size and warn.
    size = max(FLOOR_PT - 1.5, 6.0)
    # If it has to overflow, use the fewest lines that fit the width.
    #   Drawing at the max line count once put two lines where there was room
    #   for one, and they stuck up and got clipped outside the figure.
    pick = _wrap(words, max_lines)
    for n in range(1, max_lines + 1):
        ls_ = _wrap(words, n)
        if max(_width_in(fig, ln, weight) for ln in ls_) * size <= box_w:
            pick = ls_
            break
    ax.text(cx, cy, "\n".join(pick), fontsize=size, linespacing=1.26, **kw)
    # Space is measured with a full line-spacing (1.26em) per line, but the
    #   ink of one line is only about 1em; the extra spacing only sits between
    #   lines. If text drawn at floor size actually fits inside the box, that
    #   is not "doesn't fit." A count and a stage name that rendered fine
    #   still got flagged this way in a 0.10-inch cell. Leave the layout as is
    #   and only change the verdict to use ink: changing the measuring formula
    #   would shake every figure's layout.
    _ink_h = ((len(pick) - 1) * 1.26 + 1.05) * size / 72.0
    _ink_w = max(_width_in(fig, ln, weight) for ln in pick) * size
    BOUND[(what, strip_markup(s)[:48])] = "w" if _ink_w > box_w else "h"
    if _ink_w <= box_w * 1.02 and _ink_h <= box_h * 1.02:
        _note_size(size, s, warn, seen, what)
        return size
    # The space (`box_w`) is usually the share left after the box's inner
    #   margin (72-92% of the box). If the text only fills up to that margin,
    #   it still looks like it fits in the render, so this says "tight," not
    #   "doesn't fit": the render was fine but build alone said "doesn't fit,"
    #   which left no way to tell which one to trust. The margin share comes
    #   from the box's inner-text share (`INNER_TEXT_SHARE`); up to
    #   1/0.82 ≈ 1.22x still counts as inside the box.
    _pad = 1.0 / INNER_TEXT_SHARE
    # This margin allowance only applies inside the outer cell (`outer_w`).
    #   Allowing the 1.22x in tiles packed against each other once let a
    #   verdict's text touch the neighboring cell's text: the two verdicts
    #   printed stuck together, and this still called it "tight."
    _lim_w = box_w * _pad if outer_w is None else min(box_w * _pad, outer_w)
    if warn is not None and _ink_w <= _lim_w and _ink_h <= box_h * _pad:
        line = ("%stext fills to the margin (%.1fpt, %d%% of the space's width): %r"
                % (what and what + ": ", size, round(100 * _ink_w / max(1e-6, box_w)), s[:48]))
        if line not in warn:
            warn.append(line)
        _note_size(size, s, warn, seen, what)
        return size
    if warn is not None:
        line = ("%stext doesn't fit the space (even shrunk to %.1fpt): %r"
                % (what and what + ": ", size, s[:48]))
        if line not in warn:
            warn.append(line)
    _note_size(size, s, warn, seen, what)
    return size


def _note_size(size, s, warn, seen, what):
    """Collects the sizes of drawn text, so `fitcheck` can see inside the PNG.

    The same warning for the same text fires only once. If the same name
    printed in four boxes, the same message would appear four times, and
    then the rest of the warnings go unread.
    """
    if seen is not None:
        seen.append((round(float(size), 2), strip_markup(str(s))))
    # Make the verdict and the display show the same number. Printing 7.95pt
    #   as "8.0pt (floor 8pt)" makes the reader think that is the same and
    #   stop reading warnings after that.
    # The warning threshold is the smallest text in the deck (scriptsize =
    #   0.7x body), the same ruler as fitcheck. Setting it to 8pt made build
    #   call the same text "small" while fitcheck called it "fine." When
    #   matching sizes, aim for 8pt first.
    if warn is not None and round(size, 1) < WARN_PT:
        line = ("%stext is %.1fpt on screen (floor %.0fpt): %r"
                % (what and what + ": ", size, WARN_PT, str(s)[:48]))
        if line not in warn:
            warn.append(line)


def _round(ax, x, y, w, h, face, xs=1.0, ys=1.0, zorder=2, alpha=1.0,
           hatch=None, edge="none", lw=0.0, r_in=None):
    """One rounded-corner fill: filled, with no outline.

    There is one radius, `design.RADIUS_IN`. Giving it as a ratio of box
    size makes a large box and a small box read as different visual
    languages, and past 1/4 of the short side it reads not as structure but
    as a button.

    The radius is set in inches. Leaving it to `FancyBboxPatch`'s
    `mutation_aspect` meant that the moment the axes' aspect ratio passed
    3:1, the vertical radius dropped below 3px and it became just a
    square-cornered box, confirmed by zooming in. Converting to each axis's
    own units, horizontal and vertical separately, looks the same at any
    ratio.
    """
    # The radius follows the shape's short side. Fixing it to one value
    #   turns a thin strip into a pill, and a pill reads as something you can
    #   press, but this is a structure diagram, not a control.
    if r_in is None:
        r_in = design.radius(min(w * xs, h * ys))
    rx = min(r_in / max(xs, 1e-6), w * 0.42)
    ry = min(r_in / max(ys, 1e-6), h * 0.42)
    v, c = [], []
    # Counterclockwise. Each corner as one cubic Bezier.
    k = 0.5523
    pts = [
        ((x + rx, y), (x + w - rx, y)),
        ((x + w, y + ry), (x + w, y + h - ry)),
        ((x + w - rx, y + h), (x + rx, y + h)),
        ((x, y + h - ry), (x, y + ry)),
    ]
    corners = [
        ((x + w - rx, y), (x + w - rx + rx * k, y), (x + w, y + ry - ry * k)),
        ((x + w, y + h - ry), (x + w, y + h - ry + ry * k),
         (x + w - rx + rx * k, y + h)),
        ((x + rx, y + h), (x + rx - rx * k, y + h), (x, y + h - ry + ry * k)),
        ((x, y + ry), (x, y + ry - ry * k), (x + rx - rx * k, y)),
    ]
    v.append(pts[0][0])
    c.append(Path.MOVETO)
    for i in range(4):
        v.append(pts[i][1])
        c.append(Path.LINETO)
        c1, c2, end = corners[i]
        v += [c1, c2, end]
        c += [Path.CURVE4] * 3
    v.append(pts[0][0])
    c.append(Path.CLOSEPOLY)
    ax.add_patch(PathPatch(Path(v, c), facecolor=face, edgecolor=edge,
                           linewidth=lw, alpha=alpha, hatch=hatch,
                           zorder=zorder))



def common_pt(labels, w_in, h_in, base, max_lines=3):
    """Gives several boxes one size: the largest pt at which every label fits.

    Fitting each box separately once left one long label at 6.5pt while the
    rest sat at 10pt. If sizes differ, size starts to carry meaning it
    should not, so layouts keep one size per grid.
    """
    pt = float(base)
    while pt > FLOOR_PT - 1.5:
        ok = True
        for s in labels:
            s = strip_markup(str(s or ""))
            if not s.strip():
                continue
            if not any(wrapped_w(s, pt, n) <= w_in and n * pt * 1.25 / 72.0 <= h_in
                       for n in range(1, max_lines + 1)):
                ok = False
                break
        if ok:
            return pt
        pt -= 0.5
    return FLOOR_PT - 1.5


def _box(ax, x, y, w, h, label, mark=None, fs=None, fig=None, xs=1.0, ys=1.0,
         warn=None, seen=None, what=""):
    """One box: a filled area, not an outline.

    `xs`/`ys` are inches per 1 axis unit. Without them, "fit to the box's
    width" does not work. This used to use matplotlib's `wrap=True`, but that
    fits to the figure's width, so it did nothing for a narrow box: the
    label ran outside the box.

    Appearance: this used to be a white area with a solid outline. Put four
    boxes side by side and it reads as a wireframe, and `_tile` in this same
    file was already a filled area, so the file's own visual language was
    split in two. Concept diagrams are all left as filled areas, with
    emphasis given by fill color, not outline weight.
    """
    # Give emphasis with an outline, not a fill. Filling a box with a
    #   saturated color spends the figure's whole contrast budget on that
    #   box, so the text inside it and the arrows next to it end up fighting
    #   it (`references/design.md` §2). Putting this only in `draw_pipeline`
    #   meant the emphasized box in the same deck came out as an outline on
    #   one slide and a green fill on another, and the viewer sees both
    #   slides on the same screen.
    ring = design.ROLE_TEXT.get(mark) if mark in design.ROLE_TEXT else None
    if ring:
        _round(ax, x, y, w, h, design.SURFACE, xs, ys, zorder=2,
               edge=ring, lw=design.BASE)
        txt = ring
    else:
        _round(ax, x, y, w, h, TILE_BG, xs, ys, zorder=2)
        txt = TILE_FG
    fit_text(fig, ax, x + w / 2.0, y + h / 2.0, (w - 2.2) * xs, (h - 1.4) * ys,
             strip_markup(str(label)), fs or FS, warn=warn, seen=seen,
             what=what, ha="center", va="center", zorder=3, color=txt,
             fontweight="bold" if mark else "normal")


INNER_BG = design.SURFACE
GLYPHS = ("grid", "funnel", "widen")
# A cell with no value: LaTeX's `--` (which scaffold passes through as-is)
#   also counts as blank. Missing this once counted a `--` cell as a value.
BLANK_CELLS = ("-", "--", "---", "\u2013", "\u2014", "n/a", "N/A")
# The share (in axis units) by which text sits inset inside a box. The
#   measuring side and the drawing side must read the same number. Writing
#   it in two places once let them drift apart five times.
BOX_TEXT_PAD = 1.6
CELL_TEXT_PAD = 1.3
# The saturated role colors used for outlines and text: a different set from
# the light fill colors. A light color drawn as an outline vanishes, and a
# saturated color used as a fill kills the text on top of it.
ROLE_INK = {k: v[2] for k, v in design.ROLES.items()}


def colour_of_inner(mark):
    """Background of a row inside a box. Without a mark it's white, so it stands out from the box."""
    return design.fill_of(mark) if mark else INNER_BG


def _glyph(ax, kind, x, y, w, h, xs, ys, colour="#9FB4C7"):
    """A pictogram inside a box. Shows what kind of step this is, through shape.

    Several gray boxes that differ only by name and look identical inside
    mean the figure cannot say where and how they differ, so the speaker
    has to fill that gap in out loud.

      grid     a grid: reads input by splitting it into pieces
      funnel   a trapezoid, narrower on the right: many become one
      widen    a trapezoid, wider on the right: one becomes many
    """
    if kind == "grid":
        nc, nr = 4, 3
        gw = w * 0.60
        cell = gw / (nc + (nc - 1) * 0.22)
        gap = cell * 0.22
        # Vertical is a different axis unit, so convert to inches, then convert back
        ch = cell * xs / ys
        gh = nr * ch + (nr - 1) * gap * xs / ys
        gh = min(gh, h * 0.92)
        ch = (gh - (nr - 1) * gap * xs / ys) / nr
        ox = x + (w - gw) / 2.0
        oy = y + (h - gh) / 2.0
        for ri in range(nr):
            # Lighter toward the bottom: "from here on, the same thing repeats"
            a = 0.95 - 0.28 * ri
            for ci in range(nc):
                _round(ax, ox + ci * (cell + gap),
                       oy + gh - (ri + 1) * ch - ri * gap * xs / ys,
                       cell, ch, colour, xs, ys, zorder=3, alpha=a,
                       r_in=design.RADIUS_THIN_IN)
        return
    if kind in ("funnel", "widen"):
        gw, gh = w * 0.52, h * 0.86
        ox, oy = x + (w - gw) / 2.0, y + (h - gh) / 2.0
        narrow = gh * 0.42
        if kind == "funnel":
            pts = [(ox, oy), (ox, oy + gh),
                   (ox + gw, oy + gh - (gh - narrow) / 2.0),
                   (ox + gw, oy + (gh - narrow) / 2.0)]
        else:
            pts = [(ox, oy + (gh - narrow) / 2.0),
                   (ox, oy + gh - (gh - narrow) / 2.0),
                   (ox + gw, oy + gh), (ox + gw, oy)]
        ax.add_patch(plt.Polygon(pts, closed=True, facecolor=colour,
                                 edgecolor="none", zorder=3, alpha=0.85))


# There are only three weights (`design.HAIR/BASE/EMPH`, each 2x the last).
#   Making a fourth value here produces raggedness, not hierarchy. The
#   wrapper is also thinner than what it wraps: auto-generated tools tend to
#   do the opposite, and a group box fighting its own content is a big part
#   of what makes something look auto-generated.
LW_DASH = design.HAIR       # dashed line between stages: the wrapper
DASH_ON, DASH_OFF = design.DASH
LW_RING = design.BASE       # outline of a marked stage: structure
LW_STRIP = design.HAIR      # a strip inside a box: thinner still
MODULE_BG = design.NEUTRAL_FILL


def _arrow_at(ax, p0, p1, weight="normal"):
    """An arrow in any direction. `_arrow` is horizontal only.

    A feedback loop and an input come in from above or below. With only
    horizontal arrows available, a structure diagram was always one row,
    left to right.
    """
    if weight == "faint":
        st, col, lw = ("-|>,head_width=0.10,head_length=0.20",
                       design.NEUTRAL_LINE, design.HAIR)
    else:
        st, col, lw = ("-|>,head_width=0.16,head_length=0.30",
                       design.INK3, design.BASE)
    ax.annotate("", xy=p1, xytext=p0, zorder=1,
                arrowprops=dict(arrowstyle=st, color=col, linewidth=lw,
                                shrinkA=0, shrinkB=0))


def _arrow(ax, x0, y, x1, weight="normal"):
    """An arrow between boxes.

    `faint` is the flow between stages. Measured on one sample deck it is
    only 2.5pt long and 3.8pt tall: the flow should read but not draw the
    eye. Drawn heavy, the arrow reads before the box does.
    """
    # The head follows the line weight (about 7x its length). Pairing one
    #   fixed head size with all three weights puts a big head on a thin line,
    #   and the arrow reads before the box does.
    if weight == "faint":
        ax.annotate("", xy=(x1, y), xytext=(x0, y), zorder=1,
                    arrowprops=dict(
                        arrowstyle="-|>,head_width=0.10,head_length=0.20",
                        color=design.NEUTRAL_LINE, linewidth=design.HAIR,
                        shrinkA=0, shrinkB=0))
        return
    ax.annotate("", xy=(x1, y), xytext=(x0, y), zorder=1,
                arrowprops=dict(arrowstyle="-|>,head_width=0.16,head_length=0.30",
                                color=design.INK3, linewidth=design.BASE,
                                shrinkA=0, shrinkB=0))


def _frame(slot):
    """Draws at `slot` (inches) exactly as-is.

    These are the two most important lines in this file. This used to
    always draw at a fixed 7.2-inch width, and the embedding side would
    then compress it to 5.0-5.4cm, a 0.337-0.495 shrink ratio: `fontsize=13`
    became 4.4pt on screen, and text inside a figure is not in the PDF's
    text layer, so no checker could see it. Drawing at the actual slot size
    means no shrinkage, so the pt declared here is the pt on screen.
    """
    w_in, h_in = slot
    fig = plt.figure(figsize=(w_in, h_in))
    ax = fig.add_axes([0, 0, 1, 1])          # no margin, full bleed: saved size = slot
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    # How many inches is one axis unit. Used when fitting text to a box.
    return fig, ax, w_in / 100.0, h_in / 100.0


def band(fig, s, fs, avail_w_in, unit_h_in, max_lines=2, pad=1.4):
    """How many axis units a chunk of text takes up. This is where a band's height comes from.

    Fixing the band size means a two-line title has nowhere to go, so the
    text shrinks instead. That is how a title in a narrow cell ended up at
    6.5pt: there was width to spare but no height. Having decided to measure
    and draw to fit, fixing only the band contradicts that.
    """
    if not s:
        return 0.0
    words = str(s).split()
    n = 1
    while n < max_lines:
        w = max(_width_in(fig, ln, "bold") for ln in _wrap(words, n)) * fs
        if w <= avail_w_in:
            break
        n += 1
    return (n * 1.26 * fs / 72.0) / unit_h_in + pad


ROW_IN = 1.26 * BODY_PT / 72.0          # height of one line of text
PAD_IN = 0.16                           # inner/outer box margin



def bottom_band(fig, ax, xs, ys, cy, bh, note, take, note_pt, take_pt,
                warn=None, seen=None, tag=""):
    """The band at the very bottom of the figure: the cue faint on the left, the takeaway bold on the right.

    If there's only one, it's centered. Returns the drawn text, which must
    be written to the sidecar for `outcheck` to see it.

    `bh` is a height that has already had the margin subtracted. Shrinking
    it again here would cut a second time into the share the caller gave,
    pushing the text below the floor, which happened before this was fixed.
    """
    out = []
    two = bool(note and take)
    # With both, split proportional to text length (30-70% each). Pinning
    #   it to 46:50 once made a long takeaway not fit in its half and get
    #   clipped, and the warning only said "text doesn't fit the space," so
    #   it wasn't obvious the cause was adding `note`.
    n_w, t_w = 46.0, 50.0
    if two:
        _n = _width_in(fig, strip_markup(str(note))) * note_pt
        _t = _width_in(fig, strip_markup(str(take)), "bold") * take_pt
        t_w = max(30.0, min(70.0, 96.0 * _t / max(1e-6, _n + _t)))
        n_w = 96.0 - t_w - 2.0
    local = [] if (two and warn is not None) else warn
    if note:
        fit_text(fig, ax, 2.0 if two else 50, cy, (n_w if two else 96) * xs,
                 bh * ys, strip_markup(str(note)), note_pt, warn=local,
                 seen=seen, what=tag, max_lines=2,
                 ha="left" if two else "center", va="center", color=MUTE)
        out.append(strip_markup(str(note)))
    if take:
        fit_text(fig, ax, 98 if two else 50, cy, (t_w if two else 96) * xs,
                 bh * ys, strip_markup(str(take)), take_pt, warn=local,
                 seen=seen, what=tag, max_lines=2,
                 ha="right" if two else "center", va="center",
                 fontweight="bold", color=INK)
        out.append(strip_markup(str(take)))
    if two and warn is not None:
        if any(u"doesn't fit" in str(x) for x in local):
            warn.append(u"%s: `note` (cue) and `takeaway` (conclusion) share one line of the "
                        u"bottom band, and their combined length doesn't fit. Move the cue to the "
                        u"slide's `fine`/caption, or shorten it" % tag)
            warn.extend(x for x in local if u"doesn't fit" not in str(x))
        else:
            warn.extend(local)
    return out


def _rows_of(d):
    """Normalizes `rows:`. When there's only one row, it can be written directly without `rows`."""
    rows = d.get("rows")
    if rows:
        return [r if isinstance(r, dict) else {"label": r} for r in rows]
    keep = {k: v for k, v in d.items()
            if k in ("label", "sub", "cells", "bars", "groups",
                     "group_label", "mark_at", "stages", "out", "note",
                     "axis", "caption")}
    return [keep] if keep else []


# The share a box takes up in its row, and the share text takes up inside
#   an inner row. The measuring side and the drawing side must read the
#   same number; writing them separately once let them drift apart six times.
# Measuring a structure diagram from a sample deck: a box uses 72% of its
#   row, and text in an inner strip uses 82% of that strip. At 0.60 x 0.70,
#   one row eats 2.4x its own text height, so the same content demands
#   double the height.
# The share (in row units) of the input box below a stage. Height is this
# sum, and the space that divides its interior is also split from this
# number; multiplying by an eyeballed constant would hide what comes out of it.
FEED_LAB, FEED_SUB, FEED_PAD, FEED_ARROW = 1.00, 0.90, 0.35, 0.60


def feed_units(has_sub):
    """(box share, full band): in row units."""
    box = FEED_LAB + (FEED_SUB if has_sub else 0.0) + FEED_PAD
    return box, box + FEED_ARROW


OUT_ARROW_IN = 0.22     # width the exit arrow at the end eats up (inches)
BOX_SHARE = 0.72
INNER_TEXT_SHARE = 0.82

AXIS_MIN_IN = 1.75       # the axis line needs at least this much for ticks to be distinguishable
AXIS_MAX_CELL = 0.38     # cap on the cell's share. One sample deck's cell area was around 20%


def axis_ticks(spec):
    """Positions [0,1] where ticks are placed. Evenly spaced if a number; dense toward 0 if `log`.

    Why `log` is needed: a log scale is dense near 0 and sparse further out.
    Drawing it evenly makes it indistinguishable from a linear scale, and
    then whatever this figure was meant to say is gone entirely. To give
    positions directly, use a list (`ticks: [0, 0.1, …]`).
    """
    tk = spec.get("ticks", 17)
    if isinstance(tk, (list, tuple)):
        return [max(0.0, min(1.0, float(x))) for x in tk]
    if isinstance(tk, str):
        n = max(2, int(spec.get("n", 16)))
        if tk.lower() in ("log", "float", "exp"):
            return [(2.0 ** (4.0 * i / (n - 1.0)) - 1.0) / 15.0
                    for i in range(n)]
        return [i / float(n - 1) for i in range(n)]
    n = max(2, int(tk))
    return [i / float(n - 1) for i in range(n)]


def draw_strip(d, path, slot=None, warn=None):
    """A strip of named cells: the most general way to draw structure.

    Boxes and arrows can't draw this. "What parts is this made of" and "how
    do those parts group" need to come before the results in a talk, and
    without a way to draw them, whoever gets the slide either fills it with
    bullets or skips it entirely.

    Two modes:
      `cells:` named cells side by side. Seat columns, timetable slots, token columns.
      `bars:` + `groups:` a grouping bar over value bars. Weeks, windows, chunks.

    Stacks by splitting a row into bands: placing everything at once makes
    the label, subtitle, and caption overlap each other.
    """
    slot = slot or (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["diagram"])
    seen, tag = [], os.path.basename(path)
    rows = _rows_of(d)
    if not rows:
        return [], seen
    legend = d.get("legend") or {}
    marks = [c.get("mark") for r in rows for c in (r.get("cells") or [])
             if isinstance(c, dict)]
    colour = role_map(list(legend.keys()) + marks)
    # Gridlines and outlines are line colors. Drawing them with a fill color
    #   makes the line vanish: a light color is chosen to sit on a wide area,
    #   not to be used as a 1pt line.
    ink = role_ink(list(legend.keys()) + marks)
    any_note = any(r.get("note") for r in rows)
    any_group = any(r.get("groups") for r in rows)
    # A group on top of a group: something split into two levels (one value
    #   per bucket, and another value per group inside it). Only one layer
    #   could be drawn, so the outer layer was left as text only.
    any_outer = any(r.get("outer") for r in rows)
    # When the bars are identical across rows and only the grouping differs,
    #   each row needs a one-line `note` saying what that grouping changes.
    #   Without it, the viewer has to count the band's width and guess.
    if warn is not None and len(rows) > 1 and \
            all(r.get("bars") and r.get("groups") for r in rows) and \
            len(set(int(r["bars"]) for r in rows)) == 1 and \
            not any(r.get("note") for r in rows):
        warn.append(
            u"%s: the bars are identical across %d rows and only the grouping "
            u"differs. Give each row a one-line `note` saying what that grouping "
            u"changes (something like \"these seven cells are one week\"). Without "
            u"it, the viewer has to count the band's width to guess, and a talk "
            u"gives them no time for that." % (tag, len(rows)))
    any_sub = any(r.get("sub") for r in rows)
    any_axis = any(r.get("axis") for r in rows)
    # If a row has a vertical axis line drawn, those lines only mean
    #   something if they look different from each other. The axis line's
    #   job is to show where a value sits; if every row's ticks are placed
    #   evenly, the screen just repeats the same line, and only whoever drew
    #   it knows what it means.
    if warn is not None and sum(1 for r in rows if r.get("axis")) > 1:
        _sig = []
        for r in rows:
            a = r["axis"] if isinstance(r.get("axis"), dict) else {}
            ps = axis_ticks(a)
            if len(ps) < 2:
                _sig.append(("?", 0))
                continue
            _d = [ps[i + 1] - ps[i] for i in range(len(ps) - 1)]
            # Calibrate the threshold to the eye. Calling it "uneven" when
            #   only the last cell is double the rest makes the checker say
            #   "different" while a person says "the same." A log layout's
            #   spacing grows 10x at a time, so even 0.6 catches it.
            _even = (max(_d) - min(_d)) < 0.6 * (sum(_d) / len(_d))
            _sig.append(("even" if _even else "uneven", len(ps)))
        _kinds = set(k for k, _ in _sig)
        _ns = [n_ for _, n_ in _sig]
        # What distinguishes rows is the kind, not the count. Past fifteen,
        #   evenly-spaced ticks can't be counted and just read as texture, so
        #   evenly-spaced ticks that differ only slightly in count look the
        #   same on screen. They only become distinguishable when there are
        #   few enough to count, or the density differs by more than 2x.
        if len(_kinds) == 1 and "even" in _kinds and _ns and \
                min(_ns) >= 8 and max(_ns) < 2.5 * max(1, min(_ns)):
            warn.append(
                u"%s: a vertical axis line was drawn on every row, but "
                u"every row looks the same (%s ticks, all even). An axis "
                u"line's job is to show where a value sits, so only use it "
                u"when the layout differs visibly row to row (`ticks: log`, "
                u"or a list of positions). Otherwise cells (`cells`) and a "
                u"row description (`note`) are enough on their own, and the "
                u"figure shrinks to half height with larger text."
                % (tag, "/".join(str(x) for x in _ns)))

    def measure(fs, tight=False):
        """`tight` is the ruler for "does it fit at all": it only shrinks the margin share.

        Without this, even a 3-row, 8-cell figure got flagged "doesn't fit."
        It is the same defect already fixed in `draw_tiles` in this same
        file. A false positive removes a feature: a wrong warning once made
        an agent abandon a diagram entirely.
        """
        # Subtitles and captions also stop at the floor. Setting them to
        #   `fs - 2` makes them drop to an unreadable size as soon as body
        #   text shrinks even slightly.
        sec = max(FLOOR_PT - 1.5, fs - 2)
        line = 1.26 * fs / 72.0
        sline = 1.26 * sec / 72.0
        vk = 0.72 if tight else 1.0

        def bnd(unit, mult, floor_mult):
            return unit * max(floor_mult, mult * vk)

        rn_lines = 1
        if any_note:
            # A row's note sits below the axis line, so it wraps within that area's width
            navail = max(0.5, (AXIS_MIN_IN if any_axis else 3.0) * 0.94)
            rn_lines = min(2, max(1, int(math.ceil(
                max(text_w(strip_markup(str(r.get("note") or "")), sec)
                    for r in rows) / navail))))

        # Width comes first. The band's height depends on how many lines
        #   the subtitle wraps to, and the line count depends on the left
        #   column's width. Same spot, same shape as the fix in
        #   `draw_tiles`: fixing only one of them and it comes back.
        # Measure at the weight it is actually drawn at. Measuring at normal
        #   weight but drawing bold made the single word "step" get flagged
        #   "doesn't fit."
        lab = max([wrapped_w(strip_markup(str(r.get("label", ""))), fs, 1, "bold")
                   for r in rows] or [0.0])
        # Wraps the subtitle to up to two lines. Keeping it to one line lets
        #   a long subtitle widen the left column and eat up half the band:
        #   in a figure meant to show "how many things split one decision,"
        #   the bars themselves end up crammed into a corner. The fix is to
        #   raise the band by however much it wraps (`sub_lines`). The
        #   original problem was giving up width because there was no
        #   height to spare.
        sub1_ = max([wrapped_w(strip_markup(str(r.get("sub", ""))), sec, 1)
                     for r in rows] or [0.0])
        sub2_ = max([wrapped_w(strip_markup(str(r.get("sub", ""))), sec, 2)
                     for r in rows] or [0.0])
        # Wraps if the name column exceeds a third of the figure's width
        cap_ = slot[0] / 3.0
        sub_lines = 2 if (sub1_ > cap_ and sub2_ < sub1_ * 0.95) else 1
        sub = sub2_ if sub_lines == 2 else sub1_
        left = (max(lab, sub) + 0.16) if (lab or sub) else 0.0
        # If a cell name doesn't fit one line's width, wrap to two lines and
        #   raise the band. Allowing only one line once let a "to -1, damped"
        #   cell overrun its neighbor at floor size. Lines measured = lines drawn.
        _lc = [(strip_markup(str(c.get("label", "") if isinstance(c, dict) else c)),
                max(1, int((c.get("span", 1) if isinstance(c, dict) else 1) or 1)))
               for r in rows for c in (r.get("cells") or [])]
        _nc = max([sum(int(c.get("span", 1)) if isinstance(c, dict) else 1
                       for c in (r.get("cells") or [])) for r in rows] or [1])
        cell_lines = 1
        if _lc:
            _w1 = max((wrapped_w(x, fs, 1, "bold") + 0.16) / n for x, n in _lc)
            _w2 = max((wrapped_w(x, fs, 2, "bold") + 0.16) / n for x, n in _lc)
            if left + _nc * _w1 + 0.2 > slot[0] and _w2 < _w1 * 0.9:
                cell_lines = 2

        B = {
            "title": bnd(line, 1.55, 1.08) if d.get("title") else 0.0,
            # The name goes inside the grouping bar. At 1.25 a single line
            #   got trapped in a 0.75-line cell and dropped to 6.5pt.
            "group": bnd(sline, 1.85, 1.10) if any_group else 0.0,
            "outer": bnd(sline, 1.85, 1.10) if any_outer else 0.0,
            # With a subtitle, it stacks above or below the label, so the
            #   band must be that much taller. At 1.75, two lines got trapped
            #   in a 0.14-inch cell and dropped to 7.5pt.
            # If the subtitle wraps to two lines, the band must be that much taller too
            # Tightening the band to 1.55 produced a warning on a figure
            #   that used to fit. Margin should come from the row note's
            #   side and leave this alone: a false positive removes a feature.
            "strip": max(bnd(line, (2.35 + 0.70 * (sub_lines - 1)) if any_sub
                             else 1.75,
                             (2.15 + 0.70 * (sub_lines - 1)) if any_sub else 1.15),
                         # Two lines inside a cell: enough for two lines within the cell box's height (52% of the band)
                         line * 4.1 if cell_lines == 2 else 0.0),
            # The band for a row without a subtitle: cells/bars/ticks for
            #   every row are drawn at this height. Even when only one row
            #   has a subtitle, every row got the subtitle's height, so
            #   dropping the subtitle from three of four rows still left
            #   "0.23 inches short vertically" unchanged. Only rows with a
            #   subtitle get the extra two layers of left-name height.
            "strip0": max(bnd(line, 1.75, 1.15),
                          line * 4.1 if cell_lines == 2 else 0.0),
            # Told to draw two lines, but given a band sized for one and a
            #   half. Lines drawn and lines measured did not match, a
            #   recurring source of this kind of bug.
            # A row's note attaches to its own row. Because a trough sits
            #   below it, adding another margin separates the note from its
            #   row and blurs what it's explaining. Any margin removed here
            #   just goes into the trough: the total height is the same,
            #   only the grouping changes.
            "rnote": (bnd(sline, 0.55 + 1.10 * rn_lines, 1.04 * rn_lines)
                      if any_note else 0.0),
            # The trough between rows. Without it, the gap within a row
            #   becomes bigger than the gap between rows, so a grouping band
            #   reads as tied to the row above instead of its own bars, and
            #   then the figure breaks outright. Proximity is how grouping
            #   is communicated here, not decoration (`design.ladder`).
            "gap": (line * 0.75 if len(rows) > 1 else 0.0),
            "legend": bnd(sline, 1.95, 1.10) if legend else 0.0,
            # A conclusion sentence is better placed as slide text, not
            #   inside the figure: that way the checker can read it, and its
            #   size follows body text. Space is still reserved here for
            #   when someone wants to include it anyway.
            "note": bnd(line, 1.5, 1.05) if (d.get("note")
                                             or d.get("takeaway")) else 0.0,
        }
        B["strip0"] = min(B["strip0"], B["strip"])

        def _rh(r):
            return (B["group"] + (B["strip"] if r.get("sub") else B["strip0"])
                    + B["rnote"] + B["gap"])
        # No trough is needed below the last row. The outer band stands only on the row that has one.
        hh = (B["title"] + sum(_rh(r) for r in rows) - B["gap"]
              + B["outer"] * sum(1 for r in rows if r.get("outer"))
              + B["legend"] + B["note"] + 0.12)
        # Bars have no cell label. Applying the label floor value
        #   (0.16 inches) per bar flags "doesn't fit" past just seventeen
        #   bars: the example shipped in the doc failed its own checker.
        #   A false positive removes a feature.
        labelled = [(c.get("label", ""), max(1, int(c.get("span", 1) or 1)))
                    for r in rows for c in (r.get("cells") or [])]
        if labelled:
            # A label spanning several cells only needs to fit across all
            #   the cells it spans. Trying to fit it into one cell once
            #   flagged "4.45 inches short" for a nine-cell "at least 90
            #   true" label, even though the figure was fine. One cell's
            #   width = label width / max span count.
            cell = max((wrapped_w(strip_markup(str(x)), fs, cell_lines, "bold") + 0.16) / n
                       for x, n in labelled)
        else:
            cell = 0.055          # Width one bar eats up. No label.
        ncell = max([sum(int(c.get("span", 1)) for c in (r.get("cells") or []))
                     or int(r.get("bars", 0) or 0) for r in rows] or [1])
        # The legend eats up width too. Not counting it once dropped a
        #   four-line legend to 6.5pt: the figure's width is set by every
        #   line inside it.
        legw = (sum(wrapped_w(strip_markup(str(v)), sec, 1) + 0.17
                    for v in legend.values()) + 0.2) if legend else 0.0
        # With an axis line attached, cells only use the left part of the
        #   band. But don't split it by a fixed ratio: with as few as eight
        #   cells, the whole figure's width bloats and flags "doesn't fit,"
        #   since a cell holds one character and barely uses any space in
        #   practice. Give the cells only what they need and the line gets the rest.
        body = ncell * cell
        if any_axis:
            body += AXIS_MIN_IN
        ww = max(left + body + 0.2, legw)
        B["cell_lines"] = cell_lines
        return ww, hh, left, cell, ncell, B, line, sec

    need_w, need_h = measure(BODY_PT)[:2]
    # Don't stop at the floor (8pt): fit to the space instead. Stopping
    #   there and enlarging the canvas makes LaTeX shrink the whole figure,
    #   which leaves text the same size anyway while losing width too, so
    #   the figure sits small in the middle. Going below the floor is not
    #   hidden: `_note_size` warns for every line.
    fs = max(FLOOR_PT - 1.5,
             BODY_PT * min(1.0, slot[0] / need_w, slot[1] / need_h))
    # What decided the figure's overall text size: build reads this when picking a fix (`BOUND`)
    if min(slot[0] / need_w, slot[1] / need_h) < 1.0:
        BOUND[(os.path.basename(path), "*")] = "w" if slot[0] / need_w <= slot[1] / need_h else "h"
    need_w, need_h, left_in, cell_in, ncell, B, line, sec_pt = measure(fs)
    # The drawing side reads the same line count as the measuring side
    _s1 = max([wrapped_w(strip_markup(str(r.get("sub", ""))), sec_pt, 1)
               for r in rows] or [0.0])
    _s2 = max([wrapped_w(strip_markup(str(r.get("sub", ""))), sec_pt, 2)
               for r in rows] or [0.0])
    sub_lines_drawn = 2 if (_s1 > slot[0] / 3.0 and _s2 < _s1 * 0.95) else 1
    # A line is something that stretches: all spare width goes to it, and
    #   the longer the line, the more distinguishable the ticks are, which
    #   is the point of this figure. Drawing only "as much as needed" and
    #   leaving the rest blank leaves the figure small in the middle of its
    #   space with empty sides; bars once came out filling only 29% of it.
    need_w = max(need_w, slot[0])
    floor_w, floor_h = measure(FLOOR_PT, tight=True)[:2]
    # The width estimate is judged after actually drawing. The estimate
    #   assumes cells get their full width and the axis line gets its full
    #   1.75 inches, but the drawing side compresses cells to 38% and gives
    #   the line the rest, so a figure that rendered fine still kept
    #   flagging "0.30 inches short horizontally." Once that warning fired,
    #   `warn = None` turned off every warning during drawing. Now the
    #   drawing-time warnings are collected separately, and the width
    #   estimate is only issued when the figure has an actual problem (text
    #   doesn't fit, a line is too short). Height is still issued as is: if
    #   height falls short, the canvas grows and LaTeX shrinks the whole thing.
    _outer, _pend = warn, None
    if floor_w > slot[0] + 1e-6 or floor_h > slot[1] + 1e-6:
        if warn is not None:
            _pend = (floor_w - slot[0] if floor_w > slot[0] + 1e-6 else 0.0,
                     floor_h - slot[1] if floor_h > slot[1] + 1e-6 else 0.0)
            warn = []
    # If space falls short, grow the canvas. Cropping to fit the slot makes
    #   the last band vanish off-screen, and compressing further makes text
    #   overlap its neighbor. Drawing it tall lets LaTeX's `max height`
    #   shrink the whole thing proportionally: the shrunk text is what
    #   `fitcheck` catches.
    _zk = max(min(1.0, slot[1] / max(0.01, need_h)),
              (FLOOR_PT - 1.5) / max(1e-6, fs))
    fig, ax, xs, ys = _frame((min(slot[0], max(1.6, need_w)),
                              max(0.7, need_h * _zk)))
    # If space still falls short after text hits the floor (8pt), compress
    #   the bands. Without this, the last bands stream off-screen with no
    #   warning at all; a legend and a conclusion line vanished this way
    #   once. `draw_tiles` already does this. Only this function was missing it.
    zk = _zk

    def U(v):
        return v * zk / ys

    # A faint card used to sit under each row. Without drawing a line, it
    #   read as "these three go together" (shared area).
    # Use only one grouping device. Grouping with cards and with a trough at
    #   the same time weakens both: the cards merged into one sheet, which
    #   made the gap within a row bigger than the gap between rows, so a
    #   grouping band read as tied to the row above. No card is drawn now:
    #   the empty space between rows alone reads as "these three go
    #   together" (`design.py` §7).

    words, y = [], 99.0
    if d.get("title"):
        bh = U(B["title"])
        fit_text(fig, ax, 50, y - bh / 2, 96 * xs, bh * ys * 0.88,
                 strip_markup(str(d["title"])), fs + 1, warn=warn, seen=seen,
                 what=tag, max_lines=1, ha="center", va="center",
                 fontweight="bold", color=INK)
        words.append(strip_markup(str(d["title"])))
        y -= bh

    x0 = 2.0 + left_in / xs
    x1 = 98.0
    # Cell area / axis-line area: cells measure themselves to take only as much as they need
    if any_axis:
        cx1 = min(x0 + ncell * cell_in / xs,
                  x0 + (x1 - x0) * AXIS_MAX_CELL)
    else:
        cx1 = x1
    cw = (cx1 - x0) / max(1, ncell)
    for r in rows:
        gh, nh, gp = U(B["group"]), U(B["rnote"]), U(B["gap"])
        # Row height (sh) is only tall when there's a subtitle. Cells, bars,
        #   and ticks are all drawn at one shared ruler (sc) across every
        #   row: if cell height varied row to row, you couldn't compare the
        #   rows side by side. The ruler stays the subtitled band's size as
        #   before; shrinking it to the no-subtitle band once made names
        #   inside cells not fit their own cell. The cell box (60% of the
        #   ruler) fits within a no-subtitle row's height.
        sc = U(B["strip"])
        sh = sc if r.get("sub") else U(B["strip0"])
        oh = U(B["outer"]) if r.get("outer") else 0.0
        if r.get("outer"):
            _n = int(r.get("bars") or ncell)
            ax.add_patch(plt.Rectangle(
                (x0 + cw * 0.10, y - oh + oh * 0.12), cw * _n - cw * 0.20,
                oh * 0.78, facecolor=design.mark_of("e"),
                edgecolor=design.line_of("e"), linewidth=design.HAIR, zorder=2))
            fit_text(fig, ax, x0 + cw * _n / 2.0, y - oh * 0.49,
                     (cw * _n - cw * 0.3) * xs, oh * 0.78 * ys,
                     strip_markup(str(r["outer"])), sec_pt, warn=warn,
                     seen=seen, what=tag, max_lines=1, ha="center",
                     va="center", zorder=3, fontweight="bold",
                     color=design.text_of("e"))
            words.append(strip_markup(str(r["outer"])))
        # The outer band sits at the very top of the row: everything else stacks below it as usual
        y -= oh
        rh = gh + sh + nh + gp
        mid0 = y - gh - sh / 2          # vertical center of the band area
        # If there's a grouping band, the name sits at that band's own
        #   height. Starting it below the band makes an eye reading
        #   top-to-bottom see the band as the end of the row above: "per 8"
        #   got read as attached to the row above's bars instead of its own.
        #   Spacing is a scale, and order is the meaning.
        _top = gh > 0
        # Left-hand label: centered across the whole row
        if r.get("label"):
            ly = (y - gh * 0.52) if _top else (
                mid0 + (sh * 0.24 if r.get("sub") else 0))
            # The name sticks to the left. Right-aligning it makes the gap
            #   between the name and the content ragged, and different
            #   starting points row to row make the rows hard to compare.
            # Without a subtitle, the name stands alone: giving it only the
            #   two-layer share (0.46) meant one line didn't fit its own
            #   height, and a two-character name got flagged "doesn't fit
            #   even shrunk to 6.5pt."
            fit_text(fig, ax, 2.0, ly, left_in - 0.12,
                     (sh * 0.46 if r.get("sub") else max(sh * 0.80, gh * 0.9)) * ys,
                     strip_markup(str(r["label"])), fs,
                     warn=warn, seen=seen, what=tag, max_lines=1,
                     ha="left", va="center", fontweight="bold", color=INK)
            words.append(strip_markup(str(r["label"])))
        if r.get("sub"):
            fit_text(fig, ax, 2.0,
                     (y - gh - sh * 0.22) if _top else (mid0 - sh * 0.26),
                     left_in - 0.12, sh * 0.46 * ys,
                     strip_markup(str(r["sub"])), sec_pt, warn=warn,
                     seen=seen, what=tag, max_lines=sub_lines_drawn,
                     ha="left", va="center", color=MUTE)
            words.append(strip_markup(str(r["sub"])))

        sy = y - gh                       # top of the band area
        mid = sy - sh / 2
        if r.get("cells"):
            i = 0
            for c in r["cells"]:
                c = c if isinstance(c, dict) else {"label": c}
                span = max(1, int(c.get("span", 1)))
                _lab = strip_markup(str(c.get("label", "")))
                # If a name doesn't fit one cell, write it once across the
                #   whole span. Repeating it per cell once overlapped into
                #   "weekdayweekday…". A single character (like "I") is
                #   written per cell: that is what it means for one cell to
                #   be one slot.
                _once = span > 1 and (len(_lab) > 2
                                      or text_w(_lab, fs, "bold") > cw * 0.80 * xs)
                # `merge: true` turns several cells into one box, for a
                #   single chunk rather than separate units ("90 true").
                #   Cell borders used to cut across the label. Don't use it
                #   when each unit has meaning, like a seat.
                if c.get("merge") and span > 1:
                    _round(ax, x0 + cw * i + cw * 0.01, mid - sc * 0.30, cw * span - cw * 0.02,
                           sc * 0.60, colour.get(c.get("mark"), TILE_BG), xs, ys,
                           zorder=2, r_in=design.RADIUS_THIN_IN)
                    _once, _units = True, 0
                else:
                    _units = span
                for k in range(_units):
                    x = x0 + cw * (i + k)
                    # Cells touch each other. Separating them reads not as
                    #   "one word" but as several pills, and it loses the
                    #   sense that the cells form a contiguous layout.
                    _round(ax, x + cw * 0.01, mid - sc * 0.30, cw * 0.98,
                           sc * 0.60,
                           colour.get(c.get("mark"), TILE_BG), xs, ys,
                           zorder=2, r_in=design.RADIUS_THIN_IN)
                    if not _once:
                        # Wraps to up to two lines. Allowing only one line
                        #   once let "to -1, damped" overrun its neighbor at
                        #   floor size. If two lines don't fit the cell's
                        #   height, `fit_text` warns.
                        fit_text(fig, ax, x + cw / 2.0, mid, cw * 0.80 * xs,
                                 sc * 0.52 * ys, _lab, fs,
                                 warn=warn, seen=seen, what=tag,
                                 max_lines=B.get("cell_lines", 1),
                                 ha="center", va="center", zorder=3,
                                 fontweight="bold", color=INK)
                if _once:
                    fit_text(fig, ax, x0 + cw * (i + span / 2.0), mid,
                             cw * (span - 0.2) * xs, sc * 0.52 * ys, _lab, fs,
                             warn=warn, seen=seen, what=tag,
                             max_lines=B.get("cell_lines", 1),
                             ha="center", va="center", zorder=3,
                             fontweight="bold", color=INK)
                words.append(strip_markup(str(c.get("label", ""))))
                i += span
        elif r.get("bars"):
            n = int(r["bars"])
            hit = r.get("mark_at")
            base = mid - sc * 0.30
            for i in range(n):
                x = x0 + cw * i
                # Height is only a rough shape, not a value. Say so in the caption.
                # A marked bar must be visibly larger. In a figure whose
                #   whole point was "one is a clear outlier," making it only
                #   37% taller did not read as an outlier and led to the
                #   figure being abandoned before. Color alone is not enough.
                # A marked bar is only taller than its neighbors: it is
                #   still a bar. Filling the band edge to edge makes it
                #   punch through into the grouping band and read as a
                #   divider line.
                hgt = sc * (0.54 if i == hit
                            else 0.12 + 0.20 * ((i * 37 % 11) / 11.0))
                # A marked bar is still its own row's color. Painting it red
                #   made a tall red rectangle read as a divider line, which
                #   is how it looked. What makes it stand out is height and
                #   the triangle above it.
                ax.add_patch(plt.Rectangle(
                    (x + cw * 0.18, base), cw * 0.64, hgt,
                    # The other bars must also be visible. Too faint against
                    #   the card background, and the figure's whole point,
                    #   seeing the bars split into groups, disappears.
                    facecolor=design.line_of("a") if i == hit
                    else design.mark_of("a"),
                    edgecolor="none", zorder=2))
                if i == hit:
                    # One more channel besides color: still visible to red-green colorblind eyes
                    ax.plot([x + cw * 0.5], [base + hgt + sc * 0.12],
                            marker="v", markersize=4.0, color=HIT,
                            zorder=3, clip_on=False)
            at = 0
            for g in [int(g) for g in (r.get("groups") or [n])]:
                gx = x0 + cw * at
                # Lightly fills the group that holds the marked bar. When
                #   the bars are deliberately identical row to row, what
                #   carries the meaning is where the group's boundary falls.
                #   If only the grouping band's width differs and everything
                #   else is the same, the viewer has to count that width.
                if hit is not None and at <= hit < at + g:
                    _round(ax, gx + cw * 0.04, mid - sc * 0.34,
                           cw * g - cw * 0.08, sc * 0.66 + gh * 0.5,
                           design.fill_of("hit"), xs, ys, zorder=1,
                           r_in=design.RADIUS_IN)
                ax.add_patch(plt.Rectangle(
                    (gx + cw * 0.10, sy + gh * 0.10), cw * g - cw * 0.20,
                    gh * 0.78, facecolor=design.mark_of("c"),
                    edgecolor=design.line_of("c"),
                    linewidth=design.HAIR, zorder=2))
                # The name is written only when it fits. Writing it eight
                #   times across eight cells makes them overlap into
                #   nothing: "per 4" got printed eight times stacked on
                #   itself. If it doesn't fit, only the first cell gets it.
                _gw = (cw * g - cw * 0.3) * xs
                _fits = text_w(strip_markup(str(r.get("group_label") or "")),
                               max(FLOOR_PT, sec_pt)) <= _gw
                if r.get("group_label") and (_fits or at == 0):
                    fit_text(fig, ax, gx + cw * g / 2.0, sy + gh * 0.49,
                             max(_gw, 4.0 * xs), gh * 0.78 * ys,
                             strip_markup(str(r["group_label"])), sec_pt,
                             warn=warn, seen=seen, what=tag, max_lines=1,
                             ha="center", va="center", zorder=3,
                             fontweight="bold", color=design.text_of("c"))
                at += g
            if r.get("group_label"):
                words.append(strip_markup(str(r["group_label"])))
        if r.get("axis"):
            # Where the value sits: a cell only says "how many cells." An
            #   axis line next to the cells shows where each row's value
            #   falls, often the whole point in a concept diagram.
            a = r["axis"] if isinstance(r["axis"], dict) else {}
            ax0 = cx1 + (x1 - cx1) * 0.06
            ax1 = x1 - (x1 - cx1) * 0.02
            _cm = a.get("mark")
            if not _cm and r.get("cells"):
                _last = r["cells"][-1]
                _cm = _last.get("mark") if isinstance(_last, dict) else None
            col = ink.get(_cm, design.INK3)
            ay = mid + sc * 0.06
            ax.plot([ax0, ax1], [ay, ay], color=INK, lw=1.0, zorder=2,
                    solid_capstyle="butt")
            # Ticks cross the line. Standing them only above it makes the
            #   line read like a floor, as if the value sits on top of it,
            #   but a value is a position above the line, not something
            #   resting on it.
            for p in axis_ticks(a):
                tx = ax0 + (ax1 - ax0) * p
                ax.plot([tx, tx], [ay - sc * 0.15, ay + sc * 0.15],
                        color=col, lw=1.1, zorder=3, solid_capstyle="butt")
            for lab, tx, ha in ((a.get("left"), ax0, "left"),
                                (a.get("right"), ax1, "right")):
                if lab:
                    # Height is one line. Giving it as a ratio of band
                    # height drops the end tick labels first as soon as the
                    # band tightens, which is how "0" and "max" disappeared
                    # before.
                    # One line is one line of the drawn text (sec_pt).
                    #   Multiplying the body line height by the compression
                    #   factor also flagged a fine "0"/"max" as "doesn't fit
                    #   even shrunk to 6.5pt."
                    fit_text(fig, ax, tx, ay - sc * 0.30,
                             (ax1 - ax0) * 0.30 * xs,
                             max(line * zk * 0.94, 1.3 * sec_pt / 72.0),
                             strip_markup(str(lab)), sec_pt, warn=warn,
                             seen=seen, what=tag, max_lines=1, ha=ha,
                             va="center", color=MUTE)
                    words.append(strip_markup(str(lab)))
        if r.get("note"):
            # A note uses the figure's width, not the band's. Confining it
            #   to the band once dropped a 48-character line to 6.5pt.
            # With an axis line present, the note attaches right below that
            #   line. Centering it hides which row it's explaining, since
            #   each row's explanation sits directly under that row's line.
            _on_ax = bool(r.get("axis"))
            fit_text(fig, ax, (cx1 + (x1 - cx1) * 0.06) if _on_ax else 50.0,
                     # With an axis line, right below the line. Centered
                     # in the band it drifts more than a line away and stops attaching to what it explains.
                     sy - sh - (nh * 0.34 if _on_ax else nh / 2),
                     ((x1 - cx1) * 0.94 if _on_ax else 96) * xs,
                     nh * ys * 0.86,
                     strip_markup(str(r["note"])), sec_pt, warn=warn,
                     seen=seen, what=tag, max_lines=2,
                     ha="left" if _on_ax else "center",
                     va="center", color=MUTE)
            words.append(strip_markup(str(r["note"])))
        y -= rh

    if legend:
        bh = U(B["legend"])
        # A color swatch plus its meaning. The name is not printed twice
        #   (that once produced "open open").
        # Splitting cells evenly doesn't let a long item fit its own cell.
        #   It must be sized proportional to width, which is why "weekend
        #   hours" once dropped to 6.5pt.
        items = list(legend.items())
        need = [wrapped_w(strip_markup(str(v)), sec_pt, 1) for _, v in items]
        sw_u, gap_u = 0.10 / xs, 0.07 / xs      # inches
        tot = sum(n / xs for n in need) + len(items) * (sw_u + gap_u)
        sc = min(1.0, 96.0 / max(1.0, tot))
        lx = 2.0
        for (k, v), n in zip(items, need):
            ax.add_patch(plt.Rectangle((lx, y - bh * 0.62), sw_u * sc,
                                       bh * 0.28,
                                       facecolor=colour.get(k, "#FFFFFF"),
                                       edgecolor=INK, linewidth=0.6, zorder=2))
            tw = (n / xs) * sc
            fit_text(fig, ax, lx + sw_u * sc + gap_u * sc * 0.4,
                     y - bh * 0.48, tw * xs * 1.04, bh * 0.82 * ys,
                     strip_markup(str(v)), sec_pt, warn=warn, seen=seen,
                     what=tag, max_lines=1, ha="left", va="center", color=MUTE)
            words.append(strip_markup(str(v)))
            lx += (sw_u + gap_u) * sc + tw
        y -= bh
    # `note` used to be printed bold, in ink color. That makes "how to
    #   read this" and "the takeaway" the same weight, so neither stands
    #   out; the two are placed on the same line at different weights instead.
    if d.get("note") or d.get("takeaway"):
        bh = U(B["note"])
        words += bottom_band(fig, ax, xs, ys, y - bh / 2, bh * 0.86,
                             d.get("note"), d.get("takeaway"),
                             sec_pt, fs, warn, seen, tag)
    save_fig(fig, path, seen, warn, tag)
    if _pend is not None:
        # The length the line actually got: use the drawn value instead of the 1.75-inch estimate
        _ax_in = ((x1 - cx1) * 0.92 * xs) if any_axis else None
        _short_ax = _ax_in is not None and _ax_in < AXIS_MIN_IN * 0.7
        _trouble = _short_ax or any(u"doesn't fit" in str(x) or u"floor" in str(x) for x in warn)
        why = []
        # Say which dimension falls short. Naming the wrong one makes the recipient fix the wrong thing.
        if _pend[0] and _trouble:
            why.append("width falls short by %.2f inches: reduce the number of cells (now %d) or shorten the names%s"
                       % (_pend[0], ncell,
                          (" (the axis line only got %.2f inches)" % _ax_in) if _short_ax else ""))
        if _pend[1]:
            why.append("height falls short by %.2f inches: reduce the number of rows (now %d), or trim "
                       "the subtitle/row note/legend" % (_pend[1], len(rows)))
        _nofit = _short_ax or _pend[1] or any(u"doesn't fit" in str(x) for x in warn)
        # Floor uses the exact value the small-text warning wrote: writing it separately would make the two lines state different floors
        _fl = [float(m.group(1)) for m in (re.search(r"\(floor ([\d.]+)pt\)", str(x)) for x in warn) if m]
        _floor = _fl[0] if _fl else FLOOR_PT - 1.0
        _pts = [float(m.group(1)) for m in (re.search(r"is ([\d.]+)pt on screen", str(x)) for x in warn) if m]
        if why and _nofit:
            _outer.append("%s: a band of %d rows x %d cells doesn't fit "
                          "this space (%.1f x %.1f inches). %s"
                          % (tag, len(rows), ncell, slot[0], slot[1], "  and ".join(why)))
        elif why:
            # It does fit: only the text drops below the floor. Saying "doesn't fit" would contradict the render
            _outer.append("%s: a band of %d rows x %d cells fits this space (%.1f x %.1f inches), but text drops "
                          "below the floor of %gpt (minimum %.1fpt). This is because width falls short by %.2f "
                          "inches: reducing the number of cells (now %d) or shortening the names would make it larger"
                          % (tag, len(rows), ncell, slot[0], slot[1], _floor,
                             min(_pts) if _pts else _floor, _pend[0], ncell))
        else:
            _outer.extend(warn)
    return [w for w in words if w], seen



def _inner_rows(v):
    """Normalizes `inner` into a list of lines. Several items on one line are placed side by side with an arrow between them.

        inner: ["Step 1", "...", "Step N"]        one per line
        inner: [["Mix", "Proof"], "oven"]       first line has two, side by side
    """
    out = []
    for row in (v or []):
        if isinstance(row, (list, tuple)):
            out.append([c if isinstance(c, dict) else {"label": c}
                        for c in row])
        else:
            out.append([row if isinstance(row, dict) else {"label": row}])
    return out


def is_ditto(cell):
    """"From here on, the same thing repeats": drawn as three vertical dots."""
    s = strip_markup(str(cell.get("label", ""))).strip()
    return s in ("...", "\u2026", "\u22ee", ":")


def _settle(outer, pend, drawn):
    """Judges a figure the floor-size estimate said "doesn't fit" after actually drawing it.

    The estimate (`measure(FLOOR_PT)`) doesn't know the drawing side's room
    to compress and split. So a figure that rendered fine still kept
    flagging "width falls short by 0.36 inches," and once that warning
    fired, `warn = None` turned off even the warnings during drawing. Now
    the drawing-time warnings (`drawn`) are collected, and: if text still
    doesn't fit or height fell short, the estimate is issued as is; if only
    the text dropped below the floor, that's what's said; if there's no
    problem, the estimate is discarded.
    `pend` = (estimate warning, whether height fell short, figure name).
    """
    if outer is None or pend is None:
        return
    msg, tall, tag = pend
    # The height estimate is also judged from the drawn result. A height
    #   shortfall is resolved by growing the canvas and compressing, and the
    #   drawing side reports that separately as "shrinks to N%." "Doesn't
    #   fit" and "shrinks to 98%" once printed side by side on the same
    #   figure and contradicted each other. The estimate is only issued once
    #   text still doesn't fit.
    if any(u"doesn't fit" in str(x) for x in drawn):
        outer.append(msg)
        return
    _fl = [float(m.group(1)) for m in (re.search(r"\(floor ([\d.]+)pt\)", str(x)) for x in drawn) if m]
    _pts = [float(m.group(1)) for m in (re.search(r"is ([\d.]+)pt on screen", str(x)) for x in drawn) if m]
    if _pts:
        outer.append(u"%s: this fits the space, but text drops below the floor of %gpt (minimum %.1fpt): %s"
                     % (tag, _fl[0] if _fl else FLOOR_PT - 1.0, min(_pts),
                        msg.split(u"doesn't fit. ", 1)[-1]))
    # Drop only the small-text lines folded into the line above: match their exact shape. A bare
    #   "on screen" also matched the clipped-text warning ("… doesn't appear on screen") and
    #   silently dropped it after the translation
    outer.extend(x for x in drawn if not re.search(r"is [\d.]+pt on screen \(floor", str(x)))


def draw_pipeline(d, path, slot=None, warn=None):
    """A flow of stages: a process or system diagram.

    How this differs from `flow`: a group header spans several stages, each
    stage carries a count, a divider goes between groups, and stacking
    several rows lets two things be compared. A handful of boxes cannot
    substitute for this.
    """
    slot = slot or (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["diagram"])
    seen, tag = [], os.path.basename(path)
    rows = _rows_of(d)
    rows = [r for r in rows if r.get("stages")]
    if not rows:
        return [], seen
    ns = max(len(r["stages"]) for r in rows)
    has_group = any(s.get("group") for r in rows for s in r["stages"])
    has_count = any(s.get("count") for r in rows for s in r["stages"])
    # Lines that go inside a box: the substance of a structure diagram
    max_inner = max([len(_inner_rows(s.get("inner"))) for r in rows
                     for s in r["stages"] if isinstance(s, dict)] or [0])
    any_glyph = any(s.get("glyph") for r in rows for s in r["stages"]
                    if isinstance(s, dict))
    any_ssub = any(s.get("sub") for r in rows for s in r["stages"]
                   if isinstance(s, dict))
    any_cap = any(r.get("caption") for r in rows)
    # Whether to draw the dashed line around every stage, or only where
    #   groups change. "module" is kept as an old name (same as "stage").
    sep_all = str(d.get("separate") or "group").lower() in ("all", "stage",
                                                            "module", "true")
    # A pictogram also takes up space. The inside of a box must be drawn even without lines.
    body_rows = max(max_inner, 2 if any_glyph else 0)
    has_out = any(r.get("out") for r in rows)
    # An input hanging below a stage, and a feedback loop returning from
    #   `out`. These two let a structure diagram say "this is a closed
    #   loop" rather than just "these are the parts." Without them, no space is used at all.
    _feeds = [s.get("feed") for r in rows for s in r["stages"]
              if isinstance(s, dict)]
    any_feed = any(_feeds)
    any_fsub = any(isinstance(f, dict) and f.get("sub") for f in _feeds)
    any_loop = any(r.get("loop") for r in rows)
    # Skip: a path that skips several stages into a later one, a residual
    #   connection, a bypass. Without it, a key figure in that kind of paper
    #   cannot be drawn (the x arrow of a residual block). A band above the
    #   boxes appears only when a row actually uses it.
    any_skip = any(r.get("skip") for r in rows)
    # A frame wrapping a row: one more header band sits above the map, and a bit more margin below.
    any_frame = any(isinstance(r.get("frame"), dict) and
                    (r["frame"].get("label") or r["frame"].get("note"))
                    or r.get("frame") is True for r in rows)

    def _extra(line):
        """Height (inches) of the things that hang below a row.

        The measuring side and the drawing side must read the same
        formula. Writing the two numbers separately is a recurring source
        of mismatches in this file.
        """
        return ((line * feed_units(any_fsub)[1]) if any_feed else 0.0,
                (line * 1.55) if any_loop else 0.0)

    def _row_gap(line):
        """The gap between rows that have an input hanging off them (inches). When the gap
        between an input box and its own row equals the gap to the next row,
        the row above's input read as belonging to the row below: whichever is closer reads as one unit."""
        return (line * 0.9) if (any_feed and len(rows) > 1) else 0.0
    # A hollow box (an endpoint like an input/output) is not warned about;
    #   it's just drawn low, see `hollow` below. Warning about it once made
    #   an agent invent content that wasn't there.

    def measure(fs):
        line = 1.26 * fs / 72.0
        lab = max([wrapped_w(strip_markup(str(r.get("label", ""))), fs, 1)
                   for r in rows] or [0.0])
        sec = max(FLOOR_PT - 1.5, fs - 2)
        sub = max([wrapped_w(strip_markup(str(r.get("sub", ""))), sec, 1)
                   for r in rows] or [0.0])
        # The dashed line also stands before the first stage, so its share
        #   is left on the left side. Without it, the first dash cuts across the row's name.
        left = max(lab, sub) + 0.30 if (lab or sub) else 0.0
        stage = max([wrapped_w(strip_markup(str(s.get("label", ""))), fs, 2)
                     for r in rows for s in r["stages"]] or [0.5]) + 0.22
        # Count the arrow's share separately. Measuring it as one chunk and
        #   then multiplying by 0.55 when drawing left the name with only
        #   half its own space, another spot where the measured number and
        #   the drawn number differed.
        outw = ((max([wrapped_w(strip_markup(str(r.get("out", ""))), fs, 1)
                      for r in rows] or [0.0]) + OUT_ARROW_IN + 0.10)
                if has_out else 0.0)
        ww = left + ns * (stage + 0.10) + outw + 0.2
        # The count line needs enough room for one 8pt line. At 2.9 it got
        #   trapped in a 0.09-inch cell and dropped to 6.5pt.
        # If a box has an inner line, the box must be that much taller.
        #   Without it, the inner line either punches through the box or gets squeezed to 6.5pt.
        # Row height is solved backward from the text height it needs.
        #   Since the drawing side's formula is
        #
        #     text height = rh x BOX_SHARE / (line count + 1.45 + subtitle) x TEXT_SHARE
        #
        #   working out what rh must be for one secondary-text line to fit
        #   at `sec` size is just division. Tweaking the constants by eye
        #   makes the three multiplied terms hide each other, so no value
        #   plugged in gives a predictable result; in practice `inner` text
        #   never reached the floor (8pt) at any length.
        # The drawing side adds 0.85 to the denominator when a name wraps
        #   to two lines. If the measuring side doesn't count that, the
        #   height given to the inner text shrinks by 26% and drops below
        #   the floor. If even one name can wrap, assume the worst case:
        #   being generously wrong leaves spare margin, being short wrong
        #   loses the text.
        # Not every name wraps just because it has two words; it only wraps
        #   when it doesn't fit one line at its own share of the width.
        #   Assuming the worst case unconditionally once left 0.85 lines
        #   empty on every row, and that margin pushed the figure past its
        #   space, so LaTeX shrank it to 75% and text was lost trying to
        #   save margin.
        _avail1 = max(0.30,
                      (slot[0] - left - outw - 0.20) / max(1, ns) - 0.22)
        _wrap2 = any(
            wrapped_w(strip_markup(str(
                s.get("label", "") if isinstance(s, dict) else s)),
                fs, 1) > _avail1
            for r in rows for s in r["stages"])
        denom = (body_rows + 1.45 + (0.80 if any_ssub else 0.0)
                 + (0.85 if _wrap2 else 0.0))
        # Measure by text height, not line spacing. Since the drawing side
        #   fits text into `hrow x 0.82`, that 0.82 and 0.72 already create
        #   the margin. Multiplying in line spacing (1.26em) here too counts
        #   the same margin twice, and the box ends up 26% taller, pushing
        #   the figure past its space.
        # A box's height is the sum of its own contents. Tying it to a row
        # also stretches boxes with less content, which was the cause of
        # the "big empty rectangle."
        # The comment above is wrong: the drawing side (`fit_text`)
        #   measures one line as 1.26em when fitting it in. Setting it to
        #   1.0em here means a box's inner line never fits its own size and
        #   always shrinks (sample deck: 7.5pt with empty space below). The
        #   measuring side and the drawing side must read the same formula.
        #   If space falls short, fs comes down; at the floor, it warns.
        box_h = (((1.26 * sec / 72.0) * denom / INNER_TEXT_SHARE) if body_rows
                 else line * 1.55)
        # Things that stand outside the box: count, row caption
        outside = line * ((1.0 if has_count else 0.0)
                          + (1.25 if any_cap else 0.0) + 0.5)
        pad_row = line * 0.22
        # Compose by adding, not by ratio. Composing by ratio would mean
        #   each extra outside line inflates the whole row by
        #   1/(1-0.72) = 3.6x, leaving the box that much emptier.
        rh = max(line * 2.0, box_h + outside + pad_row
                 + (line * (FRAME_BAND + FRAME_PAD) if any_frame else 0.0)
                 + (line * SKIP_BAND if any_skip else 0.0))
        hh = (len(rows) * (rh + sum(_extra(line))) + (len(rows) - 1) * _row_gap(line)
              + (line * 1.35 if has_group else 0)
              + (line * 1.5 if d.get("title") else 0)
              + (line * 1.5 if (d.get("note")
                                or d.get("takeaway")) else 0) + 0.12)
        return ww, hh, left, stage, outw, rh, line, sec, box_h, outside

    need_w, need_h = measure(BODY_PT)[:2]
    # Don't stop at the floor (8pt): fit to the space instead. Stopping
    #   there and enlarging the canvas makes LaTeX shrink the whole figure,
    #   which leaves text the same size anyway while losing width too, so
    #   the figure sits small in the middle. Going below the floor is not
    #   hidden: `_note_size` warns for every line.
    fs = max(FLOOR_PT - 1.5,
             BODY_PT * min(1.0, slot[0] / need_w, slot[1] / need_h))
    # What decided the figure's overall text size: build reads this when picking a fix (`BOUND`)
    if min(slot[0] / need_w, slot[1] / need_h) < 1.0:
        BOUND[(os.path.basename(path), "*")] = "w" if slot[0] / need_w <= slot[1] / need_h else "h"
    (need_w, need_h, left_in, stage_in, out_in, rh_in, line, sec_pt,
     box_in, outside_in) = measure(fs)
    floor_w, floor_h = measure(FLOOR_PT)[:2]
    _outer, _pend = warn, None
    if floor_w > slot[0] + 1e-6 or floor_h > slot[1] + 1e-6:
        if warn is not None:
            why = []
            if floor_w > slot[0] + 1e-6:
                # If width falls short, the name is the culprit: a stage's width is set by its name
                why.append("width falls short by %.2f inches: shorten the stage names or "
                           "merge some of the %d stages" % (floor_w - slot[0], ns))
            if floor_h > slot[1] + 1e-6:
                drop = [n for n, k in (("pictogram (glyph)", any_glyph),
                                       ("inner box line (inner)", max_inner),
                                       ("inner box subtitle (sub)", any_ssub),
                                       ("count", has_count)) if k]
                why.append("height falls short by %.2f inches: reduce the number of rows (now %d), or %s"
                           % (floor_h - slot[1], len(rows),
                              ("drop " + "/".join(drop))
                              if drop else "split into slides"))
            _pend = ("%s: a diagram of %d rows x %d stages in this space "
                     "(%.1f x %.1f inches) doesn't fit. %s"
                     % (tag, len(rows), ns, slot[0], slot[1],
                        "  and ".join(why)), floor_h > slot[1] + 1e-6, tag)
            warn = []
    # If space falls short, grow the canvas: cropping to fit makes things vanish, compressing further makes them overlap.
    _zk = max(min(1.0, slot[1] / max(0.01, need_h)),
              (FLOOR_PT - 1.5) / max(1e-6, fs))
    # Use the full width. Drawing only as much as needed leaves the
    #   structure diagram small in the middle of its space with empty sides;
    #   this was added to `draw_strip` but left out here.
    need_w = max(need_w, slot[0])
    fig, ax, xs, ys = _frame((min(slot[0], max(1.8, need_w)),
                              max(0.7, need_h * _zk)))
    # If space still falls short after text hits the floor, compress and
    #   draw it anyway. Without compressing, the bands below stream
    #   off-screen with no warning at all. Same defect just fixed in `draw_strip`.
    # Compression stops at the text's own floor. Compressing further makes
    #   the band smaller than the text and text overlaps its neighbor:
    #   overlapping text cannot be read at all, while small text is merely
    #   hard to read. Stopping here makes the figure taller than its space,
    #   and LaTeX shrinks the whole thing proportionally. That shrinkage is
    #   what `fitcheck` catches.
    zk = _zk
    rh_in *= zk
    line *= zk
    box_in *= zk
    outside_in *= zk

    words, y = [], 99.0
    if d.get("title"):
        bh = line * 1.5 / ys
        fit_text(fig, ax, 50, y - bh / 2, 96 * xs, bh * ys * 0.9,
                 strip_markup(str(d["title"])), fs + 1, warn=warn, seen=seen,
                 what=tag, max_lines=1, ha="center", va="center",
                 fontweight="bold", color=INK)
        words.append(strip_markup(str(d["title"])))
        y -= bh

    x0 = 2.0 + left_in / xs
    x1 = 98.0 - out_in / xs
    # Splits by what each stage needs. Splitting evenly leaves spare space
    #   for a stage with just a short name, and overlapping text for a stage
    #   with two things side by side inside it. Even a hand-drawn structure
    #   diagram doesn't give every stage the same width.
    def _stage_need(i):
        n = 0.30                       # floor value (inches)
        for r in rows:
            st = r["stages"][i] if i < len(r["stages"]) else None
            if not isinstance(st, dict):
                st = {"label": st} if st else {}
            # Counts margin twice over: the box's margin within its slot,
            #   and the text's margin within the box. Counting only one
            #   layer makes the name touch both ends of the box and the inner text cross the border.
            n = max(n, _width_in(fig, strip_markup(str(st.get("label", ""))),
                                 "bold") * fs + 0.34)
            if st.get("sub"):
                n = max(n, _width_in(fig, strip_markup(str(st["sub"])))
                        * max(FLOOR_PT - 1.0, BODY_PT - 3) + 0.34)
            for cells in _inner_rows(st.get("inner")):
                # Text can shrink down to floor size. Measuring at that size
                # keeps the space from falling short and text crossing the border.
                w_ = sum(_width_in(fig, strip_markup(str(c.get("label", ""))))
                         * max(FLOOR_PT - 1.0, BODY_PT - 3) + 0.30
                         for c in cells)
                n = max(n, w_ + (0.26 * (len(cells) - 1)) + 0.40)
            if st.get("glyph"):
                n = max(n, 0.52)
            # A count below the box, and a single-stage group name, are
            #   also held by this cell. Not counting them once shrank only
            #   the long count and group name to a different size from their
            #   siblings.
            if st.get("count"):
                n = max(n, _width_in(fig, strip_markup(str(st["count"]))) * sec_pt * 1.05
                        + 1.5 * xs)
            fd = st.get("feed")
            if fd:
                fd = fd if isinstance(fd, dict) else {"label": fd}
                for k, wt in (("label", "bold"), ("sub", None)):
                    if fd.get(k):
                        n = max(n, _width_in(fig, strip_markup(str(fd[k])),
                                             wt) * max(FLOOR_PT, fs - 1)
                                + 0.30)
        _st = [s if isinstance(s, dict) else {} for s in rows[0]["stages"]] if rows else []
        _g = _st[i].get("group") if i < len(_st) else None
        if _g and all((j == i) or (j >= len(_st)) or _st[j].get("group") != _g
                      for j in (i - 1, i + 1) if j >= 0):
            n = max(n, _width_in(fig, strip_markup(str(_g))) * sec_pt * 1.08 + 1.1 * xs)
        return n

    # Knowing the width a gutter eats up ahead of time requires knowing the
    # gutter, and the gutter comes from the space. To break that cycle,
    # base it only on what's needed and subtract the gutter afterward.

    _needs = [_stage_need(i) for i in range(ns)]
    _tot = sum(_needs) or 1.0
    # The gutter between columns. The flow arrow and the group boundary
    #   dash stand here. Doubling it as the box's inner margin leaves
    #   nothing outside the box, so both end up flush against the border.
    gut = max(3.0, (x1 - x0) * 0.028)
    _avail = max(4.0, (x1 - x0) - gut * (ns - 1))
    _wid = [_avail * v / _tot for v in _needs]
    _off, _at = [], 0.0
    for v in _wid:
        _off.append(_at)
        _at += v + gut
    sw = _avail / max(1, ns)            # baseline (average) for a group header
    rh = rh_in / ys
    # A stage name's size is decided all at once. Fitting each box
    #   separately would only enlarge the short names, and then size starts
    #   to mean something: it would read as "filter matters more," when no
    #   one ever said that. The baseline is the tightest stage.
    _labs_at = []
    for i in range(ns):
        _room = max(0.02, (_wid[i] - BOX_TEXT_PAD) * xs)
        for r in rows:
            st = r["stages"][i] if i < len(r["stages"]) else None
            st = st if isinstance(st, dict) else ({"label": st} if st else {})
            lab = strip_markup(str(st.get("label", "")))
            if lab:
                _labs_at.append((lab, _room))

    def _pt_for(nl):
        return min([fs] + [room / max(0.004, wrapped_w(lab, 1.0, nl, "bold"))
                           for lab, room in _labs_at])

    # If it doesn't fit one line, wrap it. Shrinking further makes it
    #   unreadable, and overflow invades the next cell: "middle stage" once ran outside its box.
    stage_pt, lab_lines = _pt_for(1), 1
    if stage_pt < FLOOR_PT and len(_labs_at) > 0:
        two = _pt_for(2)
        if two > stage_pt + 0.2:
            stage_pt, lab_lines = two, 2
    stage_pt = max(FLOOR_PT - 1.5, stage_pt)

    if has_group:
        bh = line * 1.35 / ys
        groups, at = [], 0
        for s in rows[0]["stages"]:
            g = s.get("group")
            if groups and groups[-1][0] == g:
                groups[-1][2] += 1
            else:
                groups.append([g, at, 1])
            at += 1
        # The name extends into part of the gutter (0.3 on each side): nothing occupies that height in the gutter
        _gpt = sibling_pt(fig, [(strip_markup(str(g)), (sum(_wid[a:a + n]) + gut * 0.6 - 1.0) * xs,
                                 bh * ys * 0.85) for g, a, n in groups if g], sec_pt)
        # Rather than dragging every group below the floor, shrink and warn about just the one outlier
        _gpt = _gpt if round(_gpt, 1) >= WARN_PT else sec_pt
        for g, a, n in groups:
            if not g:
                continue
            _ga = x0 + _off[a]
            _gw = sum(_wid[a:a + n])
            fit_text(fig, ax, _ga + _gw / 2.0, y - bh / 2,
                     (_gw + gut * 0.6 - 1.0) * xs, bh * ys * 0.85, strip_markup(str(g)),
                     _gpt, warn=warn, seen=seen, what=tag, max_lines=1,
                     ha="center", va="center", style="italic", color=MUTE)
            words.append(strip_markup(str(g)))
        y -= bh

    cap_h = (line * 1.25 / ys) if any_cap else 0.0
    cnt_h = (line * 1.0 / ys) if has_count else 0.0
    bh_row = box_in / ys                 # box height: derived from its contents
    pad_u = line * 0.22 / ys
    _fd_in, _lp_in = _extra(line)
    fd_u, lp_u = _fd_in / ys, _lp_in / ys
    fr_u = (line * FRAME_BAND / ys) if any_frame else 0.0
    # A count is a sibling too: "536" and "2+ per question" once stood at different sizes
    _cpt = sibling_pt(fig, [(strip_markup(str(s["count"])), (_wid[i] + gut * 0.6 - 1.4) * xs,
                             cnt_h * 0.88 * ys)
                            for r in rows for i, s in enumerate(r["stages"])
                            if isinstance(s, dict) and s.get("count") and i < len(_wid)],
                      sec_pt)
    _cpt = _cpt if round(_cpt, 1) >= WARN_PT else sec_pt
    # Chip text inside a box is a sibling too: only the chips of a narrower
    #   box once shrank. Its spot is pre-measured with the same formula as
    #   the drawing below to find one shared size.
    _chips = []
    if body_rows:
        for r in rows:
            for i, s in enumerate(r["stages"]):
                s = s if isinstance(s, dict) else {"label": s}
                if i >= len(_wid):
                    continue
                _hr = bh_row / (body_rows + 1.45 + (0.80 if s.get("sub") else 0.0)
                                + 0.85 * (lab_lines - 1))
                for cells in _inner_rows(s.get("inner")):
                    _nc = len(cells)
                    _span = (_wid[i] - 1.6) / _nc
                    for iv in cells:
                        if is_ditto(iv):
                            continue
                        _fr = max(0.2, min(1.0, float(iv.get("width") or 1.0)))
                        _cw = max(1.2, _span * _fr - (1.9 if _nc > 1 else 0.0))
                        _chips.append((strip_markup(str(iv.get("label", ""))),
                                       (_cw - CELL_TEXT_PAD) * xs, _hr * INNER_TEXT_SHARE * ys))
    _ipt = sibling_pt(fig, _chips, sec_pt)
    _ipt = _ipt if round(_ipt, 1) >= WARN_PT else sec_pt
    for r in rows:
        top = y
        # Stacks a row "from the top": margin -> box -> count -> caption -> input -> feedback loop
        # With a frame, a frame header band stands above the box
        sk_u = (line * SKIP_BAND / ys) if any_skip else 0.0
        by = top - pad_u - fr_u - sk_u - bh_row
        cy = by + bh_row / 2.0
        frp_u = (line * FRAME_PAD / ys) if any_frame else 0.0
        # The frame wraps the skip band too: if the skip band poked through the frame, it would read as "outside" it
        _frame_row(fig, ax, r, x0, _off, _wid, gut, by, bh_row + sk_u, fr_u,
                   frp_u + cnt_h, xs, ys, fs, sec_pt, warn, seen, tag,
                   words)
        # The name and the count must sit next to each other to read as one
        #   unit. Placing them at 0.12 and -0.20 of row height each let them
        #   drift apart by a whole box height and look unrelated. Both also
        #   stand at the top of the row: the name has to say where the row
        #   starts (same rule as `draw_strip`).
        _bt = by + bh_row
        # The name aligns to the top edge of the box right next to it.
        #   Aligning it to the tallest box in the row leaves the name
        #   floating in mid-air when the first box in a low row is a hollow input box.
        _s0 = r["stages"][0] if r.get("stages") else {}
        _s0 = _s0 if isinstance(_s0, dict) else {"label": _s0}
        if body_rows and _is_hollow(_s0):
            _bt = by + (bh_row + _hollow_h(bh_row, lab_lines, body_rows)) / 2.0
        _lh = line / ys
        # The dashed line wrapping every stage also stands before the first
        #   stage. Attaching the name at `x0 - 1.0` made that dash cut
        #   across the row's name: a line must never pass over text. It
        #   backs off by half the gutter more.
        _lx = x0 - max(1.0, gut * 0.5 + 0.6)
        _lw = max(0.2, left_in - 0.08 - (x0 - 1.0 - _lx) * xs)
        if r.get("label"):
            fit_text(fig, ax, _lx, _bt - _lh * 0.52,
                     _lw, _lh * 0.94 * ys,
                     strip_markup(str(r["label"])), fs, warn=warn, seen=seen,
                     what=tag, max_lines=1, ha="right", va="center",
                     fontweight="bold", color=INK)
            words.append(strip_markup(str(r["label"])))
        if r.get("sub"):
            fit_text(fig, ax, _lx, _bt - _lh * 1.46, _lw,
                     _lh * 0.88 * ys, strip_markup(str(r["sub"])), sec_pt,
                     warn=warn, seen=seen, what=tag, max_lines=1,
                     ha="right", va="center", color=MUTE)
            words.append(strip_markup(str(r["sub"])))
        prev = None
        for i, s in enumerate(r["stages"]):
            s = s if isinstance(s, dict) else {"label": s}
            x = x0 + _off[i]
            sw = _wid[i]
            pad_x = 0.0                  # the gutter is separate, so the box uses the full column
            bw_plain = sw
            inner = _inner_rows(s.get("inner"))
            if body_rows:
                # Draws the box's interior: four boxes that differ only by
                #   name and are otherwise identically empty cannot say
                #   what is different here.
                # Height is the same for every box. Scaling it to the inner
                #   line count once made a tall box merge visually with the
                #   row below it, and covered the count label so the count
                #   printed inside the box. Leaving a less-full box less
                #   full is what tells the viewer "this stage is simpler."
                bw, bh = sw - 2 * pad_x, bh_row
                nsub = 0.80 if s.get("sub") else 0.0
                nlab = 0.85 * (lab_lines - 1)
                hrow = bh / (body_rows + 1.45 + nsub + nlab)
                # A box with no contents is a short box holding only its
                #   name. Stretching it to the same height makes a big
                #   empty rectangle. It sits at the row's vertical center (arrow height).
                hollow = _is_hollow(s)
                by_s = by
                if hollow:
                    bh = _hollow_h(bh_row, lab_lines, body_rows)
                    by_s = by + (bh_row - bh) / 2.0
                mk = s.get("mark")
                # Give emphasis with an outline, not a fill. A solid green
                #   fill reads as a blob on screen and its contents become
                #   unreadable. An outline says "look here" while leaving
                #   the inside empty.
                ring = ROLE_INK.get(mk)
                if ring:
                    _round(ax, x + pad_x, by_s, bw, bh, "#FFFFFF", xs, ys,
                           zorder=2, edge=ring, lw=LW_RING)
                    tcol = ring
                else:
                    _round(ax, x + pad_x, by_s, bw, bh, MODULE_BG, xs, ys,
                           zorder=2)
                    tcol = INK
                fit_text(fig, ax, x + pad_x + bw / 2.0,
                         (by_s + bh / 2.0) if hollow
                         else by + bh - hrow * (0.80 + nlab / 2.0),
                         (bw - BOX_TEXT_PAD) * xs,
                         hrow * (1.00 + nlab) * ys,
                         strip_markup(str(s.get("label", ""))), stage_pt,
                         warn=warn, seen=seen, what=tag, max_lines=lab_lines,
                         ha="center", va="center", zorder=3,
                         # Weight is the emphasis channel, but if
                         #   everything is bold, emphasis disappears. Only the marked stage is bold.
                         fontweight="bold" if ring else "normal", color=tcol)
                gk = s.get("glyph")
                if gk and gk not in GLYPHS and warn is not None:
                    warn.append("%s: glyph=%r can only be %s"
                                % (tag, gk, "/".join(GLYPHS)))
                    gk = None
                if gk:
                    gy = by + hrow * (0.20 + nsub)
                    _glyph(ax, gk, x + pad_x + 0.8, gy, bw - 1.6,
                           by + bh - hrow * (1.30 + nlab) - gy, xs, ys)
                for k, cells in enumerate(inner):
                    iy = by + bh - hrow * (1.65 + nlab + k)
                    nc = len(cells)
                    # Several items on one line go side by side with an arrow between
                    # When placing them side by side, leave just enough room for the arrow.
                    gapc = (1.9 if nc > 1 else 0.0)
                    span = (bw - 1.6) / nc
                    for ci, iv in enumerate(cells):
                        frac = max(0.2, min(1.0, float(iv.get("width") or 1.0)))
                        cwid = max(1.2, span * frac - gapc)
                        cx0 = x + pad_x + 0.8 + span * ci
                        if is_ditto(iv):
                            # Three vertical dots: "from here on it repeats"
                            ax.text(cx0 + cwid / 2.0, iy, "\u22ee",
                                    ha="center", va="center", zorder=4,
                                    fontsize=max(FLOOR_PT - 1.0, sec_pt),
                                    color=MUTE)
                            continue
                        ec = ROLE_INK.get(iv.get("mark"))
                        # Applying a large radius to a thin strip turns it
                        #   into a pill. A pill reads as "something you can press," but this is a structure diagram, not a control.
                        _round(ax, cx0, iy - hrow * 0.38, cwid, hrow * 0.76,
                               INNER_BG, xs, ys, zorder=3,
                               edge=ec or design.NEUTRAL_LINE, lw=LW_STRIP,
                               r_in=design.RADIUS_THIN_IN)
                        # Don't shave the starting size in advance.
                        #   Starting from `sec_pt - 0.5` meant even a
                        #   four-character label never reached the floor
                        #   (8pt), and because of `warn=None` not a single
                        #   line reported it: a silent shrink is a silent failure.
                        fit_text(fig, ax, cx0 + cwid / 2.0, iy,
                                 (cwid - CELL_TEXT_PAD) * xs,
                                 hrow * INNER_TEXT_SHARE * ys,
                                 strip_markup(str(iv.get("label", ""))),
                                 _ipt, warn=warn,
                                 seen=seen, what=tag, max_lines=1, ha="center",
                                 va="center", zorder=4, color=ec or INK)
                        words.append(strip_markup(str(iv.get("label", ""))))
                        if ci < nc - 1:
                            _arrow(ax, cx0 + cwid + 0.18, iy,
                                   x + pad_x + 0.8 + span * (ci + 1) - 0.18)
                if s.get("sub"):
                    # An italic name inside the box: "what does this slot hold"
                    fit_text(fig, ax, x + pad_x + bw / 2.0, by + hrow * 0.44,
                             (bw - 1.6) * xs, hrow * 0.72 * ys,
                             strip_markup(str(s["sub"])),
                             sec_pt, warn=warn,
                             seen=seen, what=tag, max_lines=1, ha="center",
                             va="center", zorder=4, style="italic", color=MUTE)
                    words.append(strip_markup(str(s["sub"])))
            else:
                _box(ax, x + pad_x, by, bw_plain, bh_row,
                     s.get("label", ""), s.get("mark"), fs=stage_pt, fig=fig,
                     xs=xs, ys=ys, warn=warn, seen=seen, what=tag)
            words.append(strip_markup(str(s.get("label", ""))))
            if s.get("count"):
                fit_text(fig, ax, x + sw / 2.0, by - cnt_h * 0.55,
                         (sw + gut * 0.6 - 1.4) * xs, cnt_h * 0.88 * ys,
                         strip_markup(str(s["count"])), _cpt, warn=warn,
                         seen=seen, what=tag, max_lines=1, ha="center",
                         va="center", color=MUTE)
                words.append(strip_markup(str(s["count"])))
            g = s.get("group")
            if has_group and not sep_all and prev is not None and g != prev:
                # A divider between groups. Says by placement where one unit ends.
                # The divider is this figure's claim about where one unit
                #   ends. A 0.9pt dotted line is not visible on screen.
                # The line stands at the gutter's center (same spot as
                #   `sep_all`). Drawing it at the next box's left edge once
                #   got it hidden behind boxes that have an outline. The
                #   arrow stops just before it (0.44 of the gutter).
                _dx = x - gut * 0.5
                ax.plot([_dx, _dx],
                        [by - pad_u * 0.6, by + bh_row + pad_u * 0.6],
                        color=HIT, linewidth=LW_DASH,
                        linestyle=(0, (DASH_ON, DASH_OFF)),
                        zorder=4, solid_capstyle="butt")
            prev = g
            # It flows: an arrow between every pair of stages. Without it,
            #   this is a table, not a pipeline; it was named `pipeline` but
            #   wasn't flowing.
            if i < len(r["stages"]) - 1:
                # Uses most of the gutter's left side. The dash stands at
                # the gutter's center, so the arrow stops just before it.
                a0 = x + sw
                _arrow(ax, a0 + gut * 0.10, cy, a0 + gut * 0.44,
                       weight="faint")
        if sep_all:
            # A dashed line wraps the front and back of every stage. The
            #   line says the stages are separate from each other.
            edges = ([x0 + _off[i2] - gut * 0.5 for i2 in range(ns)]
                     + [x0 + _off[ns - 1] + _wid[ns - 1] + gut * 0.5])
            for ex in edges:
                ax.plot([ex, ex],
                        [by - pad_u * 0.6, by + bh_row + pad_u * 0.6],
                        color=HIT, linewidth=LW_DASH,
                        linestyle=(0, (DASH_ON, DASH_OFF)),
                        zorder=4, solid_capstyle="butt")
        if r.get("caption"):
            # A fact that belongs to the whole row, not a property of any one stage
            fit_text(fig, ax, 2.0, by - cnt_h - cap_h * 0.55,
                     94 * xs, cap_h * 0.86 * ys,
                     strip_markup(str(r["caption"])),
                     max(FLOOR_PT, sec_pt), warn=warn, seen=seen, what=tag,
                     max_lines=1, ha="left", va="center", color=MUTE)
            words.append(strip_markup(str(r["caption"])))
        # An input hanging below a stage. The arrow points up into it;
        #   placing "this goes in there" beside the stage would read as yet another stage.
        # With a frame, the input hangs below the frame. The frame's margin
        #   once ate up the arrow's space and the input box touched the frame, making the arrow invisible.
        fy1 = by - cnt_h - cap_h - frp_u
        fy0 = fy1 - fd_u
        _first_fx = None
        if fd_u:
            for i, s in enumerate(r["stages"]):
                s = s if isinstance(s, dict) else {"label": s}
                fd = s.get("feed")
                if not fd:
                    continue
                fd = fd if isinstance(fd, dict) else {"label": fd}
                fx, fw = x0 + _off[i], _wid[i]
                # A feedback loop returns into the first stage. Catching
                #   "the first input that appears" once fed into the second
                #   stage's input box when the first stage had none.
                if i == 0:
                    _first_fx = fx + fw / 2.0
                _bx, _tot = feed_units(any_fsub)
                bh_f = fd_u * (_bx / _tot)
                _round(ax, fx, fy0, fw, bh_f, design.SURFACE, xs, ys,
                       zorder=2, edge=design.line_of("a"), lw=design.HAIR)
                # The arrow climbs through the count line. Down the middle it ran
                #   straight through the count text ("12 sensors"), so when the stage
                #   has a count the arrow moves into the clear strip beside it.
                _ax_x = fx + fw / 2.0
                if s.get("count"):
                    _cw = text_w(strip_markup(str(s["count"])), _cpt) / xs
                    _side = (fw - _cw) / 2.0
                    if _side > 0.12 / xs:
                        _ax_x = fx + _side / 2.0
                _arrow_at(ax, (_ax_x, fy0 + bh_f),
                          (_ax_x, by), weight="faint")
                # The name sits (margin/2 + name/2) down from the top of the box.
                # An input with no subtitle is centered: box height is the same across rows.
                _ly = (fy0 + bh_f * (1.0 - (FEED_PAD / 2 + FEED_LAB / 2) / _bx)
                       if fd.get("sub") else fy0 + bh_f / 2.0)
                fit_text(fig, ax, fx + fw / 2.0, _ly,
                         (fw - BOX_TEXT_PAD) * xs,
                         bh_f * (FEED_LAB / _bx) * ys,
                         strip_markup(str(fd.get("label", ""))),
                         max(FLOOR_PT - 1.5, sec_pt), warn=warn, seen=seen,
                         what=tag, max_lines=1, ha="center", va="center",
                         zorder=3, fontweight="bold",
                         color=design.text_of("a"))
                words.append(strip_markup(str(fd.get("label", ""))))
                if fd.get("sub"):
                    fit_text(fig, ax, fx + fw / 2.0,
                             fy0 + bh_f * ((FEED_PAD / 2 + FEED_SUB / 2)
                                           / _bx),
                             (fw - BOX_TEXT_PAD) * xs,
                             bh_f * (FEED_SUB / _bx) * ys,
                             strip_markup(str(fd["sub"])),
                             max(FLOOR_PT - 1.5, sec_pt - 0.5), warn=warn,
                             seen=seen, what=tag, max_lines=1, ha="center",
                             va="center", zorder=3, color=MUTE)
                    words.append(strip_markup(str(fd["sub"])))
        if r.get("out"):
            _a1 = x1 + OUT_ARROW_IN / xs
            _arrow(ax, x1 + 0.4, cy, _a1)
            _tw = max(0.15, out_in - OUT_ARROW_IN - 0.10)
            # Height is one line. Giving it as a ratio of row height makes
            # it shrink with the row, and the outside text is the first to go.
            fit_text(fig, ax, _a1 + (_tw + 0.10) / xs / 2.0, cy,
                     _tw, line * 0.98,
                     strip_markup(str(r["out"])), fs, warn=warn, seen=seen,
                     what=tag, max_lines=1, ha="center", va="center",
                     fontweight="bold", color=INK)
            words.append(strip_markup(str(r["out"])))
        # Feedback loop: what comes out at the end goes back in at the
        #   front. This one line turns the figure from "four stages" into a "closed loop."
        if sk_u and r.get("skip"):
            _labs = [strip_markup(str((st if isinstance(st, dict) else {"label": st})
                                      .get("label", ""))) for st in r["stages"]]

            def _ix(v, _labs=_labs):
                if isinstance(v, int):
                    return v + len(_labs) if v < 0 else v
                v = strip_markup(str(v))
                return _labs.index(v) if v in _labs else None
            for sk in (r["skip"] if isinstance(r["skip"], list) else [r["skip"]]):
                a_, b_ = _ix(sk.get("from", 0)), _ix(sk.get("to", -1))
                if a_ is None or b_ is None or not (0 <= a_ < b_ < len(_labs)):
                    if warn is not None:
                        warn.append(u"%s: skip %r: from/to must be a stage number (0-based) or a stage "
                                    u"name, and from must come before to (stages: %s)" % (tag, sk, ", ".join(_labs)))
                    continue
                sx = x0 + _off[a_] - (gut * 0.5 if a_ > 0 else 0.0)
                sy0 = cy if a_ > 0 else by + bh_row
                ex = x0 + _off[b_] + _wid[b_] / 2.0
                ay = by + bh_row + sk_u * 0.42
                col = {"hit": HIT, "safe": SAFE}.get(sk.get("mark"), design.INK3)
                ax.plot([sx, sx, ex], [sy0, ay, ay], color=col, lw=design.BASE,
                        zorder=3, solid_capstyle="butt", solid_joinstyle="miter")
                ax.annotate("", xy=(ex, by + bh_row), xytext=(ex, ay), zorder=3,
                            arrowprops=dict(arrowstyle="-|>,head_width=0.16,head_length=0.30",
                                            color=col, linewidth=design.BASE,
                                            shrinkA=0, shrinkB=0))
                if sk.get("label"):
                    fit_text(fig, ax, (sx + ex) / 2.0, ay + sk_u * 0.30,
                             max(0.3, (ex - sx) * 0.9 * xs), sk_u * 0.52 * ys,
                             strip_markup(str(sk["label"])), fs, warn=warn,
                             seen=seen, what=tag, max_lines=1, ha="center",
                             va="center", zorder=4, fontweight="bold",
                             color=col if sk.get("mark") else INK)
                    words.append(strip_markup(str(sk["label"])))
        if lp_u and r.get("loop"):
            ly = fy0 - lp_u * 0.55
            sx = x1 + out_in / xs * 0.72 if r.get("out") else x1
            # If the first stage has no input, the arrow enters at the
            #   box's left edge. Raising it to the center would punch
            #   through the count text (`count`) at the box's bottom center.
            ex = (_first_fx if _first_fx is not None
                  else x0 + min(_wid[0] * 0.14, 0.22 / xs))
            ty = (fy0 if _first_fx is not None else by)
            txt = strip_markup(str(r["loop"]))
            tw = min((x1 - x0) * 0.7,
                     text_w(txt, max(FLOOR_PT - 1.5, sec_pt)) / xs + 1.2)
            mx = (sx + ex) / 2.0
            lc = design.NEUTRAL_LINE
            ax.plot([sx, sx], [by, ly], color=lc,
                    lw=design.HAIR, zorder=1, solid_capstyle="butt")
            ax.plot([sx, mx + tw / 2.0], [ly, ly], color=lc,
                    lw=design.HAIR, zorder=1, solid_capstyle="butt")
            ax.plot([mx - tw / 2.0, ex], [ly, ly], color=lc,
                    lw=design.HAIR, zorder=1, solid_capstyle="butt")
            _arrow_at(ax, (ex, ly), (ex, ty), weight="faint")
            fit_text(fig, ax, mx, ly, tw * xs, lp_u * 0.80 * ys, txt,
                     max(FLOOR_PT - 1.5, sec_pt), warn=warn, seen=seen,
                     what=tag, max_lines=1, ha="center", va="center",
                     color=MUTE)
            words.append(txt)
        y -= rh + fd_u + lp_u + (_row_gap(line) / ys if r is not rows[-1] else 0.0)

    if d.get("note") or d.get("takeaway"):
        bh = line * 1.5 / ys
        words += bottom_band(fig, ax, xs, ys, y - bh / 2, bh * 0.9,
                             d.get("note"), d.get("takeaway"),
                             sec_pt, fs, warn, seen, tag)
    save_fig(fig, path, seen, warn, tag)
    _settle(_outer, _pend, warn)
    return [w for w in words if w], seen


def diagram_size(d, slot):
    """This diagram's actually needed size (inches). The slot is only a limit.

    Filling the slot as-is once let three short phrases eat 60% of the
    page, and the user called it needlessly big. Figures in one sample
    deck ranged 40-77% of width, varying with content: narrow content
    should draw narrow.
    """
    max_w, max_h = slot
    kind = d.get("kind", "flow")
    boxes = [b if isinstance(b, dict) else {"label": b} for b in d["boxes"]]
    labs = [strip_markup(str(b.get("label", ""))) for b in boxes
            if str(b.get("label", "")).strip()]
    fs = BODY_PT
    bands = 0.0
    if d.get("title"):
        bands += ROW_IN * 1.3
    if d.get("note"):
        bands += ROW_IN * 1.1

    if kind == "stack":
        n = len(boxes)
        w = max(wrapped_w(s, fs, 2) for s in labs) + 2 * PAD_IN if labs else 1.6
        w = min(max_w, max(1.7, w + 0.5))
        # Sets row height by counting how many lines a label wraps to.
        #   Assuming one line once trapped a two-line label in a 0.34-inch
        #   cell and dropped it to 7.5pt, the same mistake already made in
        #   the grid header.
        inner = max(0.4, w - 2 * PAD_IN - 0.24)
        ll = min(3, max(int(math.ceil(text_w(s, fs) / inner)) for s in labs)
                 if labs else 1)
        h = n * (ROW_IN * (0.55 + 0.95 * ll) + PAD_IN) + bands + 0.1
    elif kind == "grid":
        cols = list(d.get("cols") or [])
        rows = list(d.get("rows") or [])
        nc = max(1, len(cols))
        nr = max(1, int(round(len(boxes) / float(nc))))
        cw = max([wrapped_w(s, fs - 1, 2) for s in labs + cols] or [0.9])
        lw = max([wrapped_w(s, fs - 1, 2) for s in rows] or [0.0])
        w = min(max_w, lw + nc * (cw + 2 * PAD_IN) + 0.3)
        # Sets the band by counting how many lines the header wraps to.
        #   Assuming one line once compressed a two-line header down to
        #   6.5pt, a mistake already made in the grid.
        hl = min(2, max([int(math.ceil(text_w(c, fs - 1) / max(0.4, cw)))
                         for c in cols] or [1])) if cols else 0
        # `_box` subtracts its own margin again inside the box, so row
        #   height is set generously enough to cover it. Leaving it at 1.6
        #   once dropped the label to just below the floor (7.9pt).
        h = (nr * (ROW_IN * 2.0 + PAD_IN)
             + hl * ROW_IN * 1.45 + bands)
    else:                                    # flow
        n = len(boxes)
        bw = max(wrapped_w(s, fs, 2) for s in labs) + 2 * PAD_IN if labs else 1.2
        w = min(max_w, n * bw + (n - 1) * 0.42 + 0.2)
        # Box height only needs two lines of text. Stretching it to fill
        #   the slot turns a one-line tag into something the size of a palm.
        h = ROW_IN * 2 + 2 * PAD_IN + bands + 0.22
    return (round(min(max_w, max(1.4, w)), 3),
            round(min(max_h, max(0.75, h)), 3))


def draw_diagram(d, path, slot=None, warn=None):
    """Draws one diagram. Returns the list of text printed on screen (for the sidecar)."""
    kind = d.get("kind", "flow")
    # These two concept-drawing paths have very different geometry, so they
    #   are kept separate. Cramming them into one function makes the
    #   branches trip over each other, which this file has already been through.
    if kind == "strip":
        return draw_strip(d, path, slot, warn)
    if kind == "pipeline":
        return draw_pipeline(d, path, slot, warn)
    if kind == "graph":
        # Crossing edges: task graphs, dependency relations (see `figs_extra`)
        import figs_extra
        return figs_extra.draw_graph(
            d, path, slot or (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["diagram"]),
            warn, sys.modules[__name__])
    boxes = [b if isinstance(b, dict) else {"label": b} for b in d["boxes"]]
    words = [strip_markup(str(b.get("label", ""))) for b in boxes]
    slot = slot or (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["diagram"])
    seen = []
    tag = os.path.basename(path)

    # The slot is a limit. The actual size is drawn out of the content.
    want = diagram_size(d, slot)
    # Shrinking each cell separately makes text sizes ragged within one
    #   diagram. If space falls short, shrink the whole diagram at once.
    base = BODY_PT
    raw_h = diagram_size(d, (slot[0], 99.0))[1]
    if raw_h > want[1] + 1e-6:
        # A box label is printed at `base - 1`, so this is set so that is
        #   what touches the floor.
        base = max(FLOOR_PT + 1.0, BODY_PT * want[1] / raw_h)
        if base <= FLOOR_PT + 1.0 and warn is not None:
            warn.append("%s: this diagram doesn't fit the space: shrink the boxes or "
                        "split into slides" % tag)
    fig, ax, xs, ys = _frame(want)
    t_h = band(fig, d.get("title"), BODY_PT + 1.5, 96 * xs, ys)
    # When a cue and a takeaway come together, one line is split in half,
    #   which halves the width each one wraps within. Measuring at full
    #   width would make the text overlap.
    _two = bool(d.get("note") and d.get("takeaway"))
    n_h = max(band(fig, d.get("note"), BODY_PT - 2,
                   (46 if _two else 96) * xs, ys),
              band(fig, d.get("takeaway"), BODY_PT - 1,
                   (50 if _two else 96) * xs, ys))
    # Breathing room between the band and the content. Placing them flush
    #   once let a caption touch a box's bottom edge, and the box covered the text (a box has higher zorder).
    gap_u = 0.055 / ys
    top = 97 - t_h - (gap_u if t_h else 0)
    bot = 3 + n_h + (gap_u if n_h else 0)

    if kind == "grid":
        cols = list(d.get("cols") or [])
        rows = list(d.get("rows") or [])
        nc = max(1, len(cols))
        nr = max(1, int(round(len(boxes) / float(nc))))
        # Sets the band in inches and converts to axis units. A fixed axis
        #   unit would shrink the band along with the figure and make text
        #   not fit, a mismatch that showed up once sizing started following content.
        lab_w = ((max(wrapped_w(strip_markup(str(x)), base - 1, 2)
                      for x in rows) + 0.16) / xs + 2.0) if rows else 2.0
        lab_w = min(46.0, lab_w)
        gx0, gx1 = lab_w, 98.0
        bw = (gx1 - gx0) / nc
        # The space a header fits into is the box's width, not the column
        #   pitch. Dividing by pitch once counted a two-line header as one
        #   line, so the band fell short and text shrank to 6.5pt. So `bw`
        #   is worked out first, then measured.
        hbox = max(0.2, (bw - 1.0) * xs)
        hl = min(2, max(int(math.ceil(
            text_w(strip_markup(str(c)), base - 1) / hbox))
            for c in cols)) if cols else 0
        head_h = (hl * 1.26 * base / 72.0 * 1.45 / ys) if cols else 0.0
        gy1, gy0 = top - head_h, bot
        bh = (gy1 - gy0) / nr
        for ci, c in enumerate(cols):
            fit_text(fig, ax, gx0 + bw * (ci + 0.5), gy1 + head_h * 0.45,
                     (bw - 1.0) * xs, head_h * 0.9 * ys, strip_markup(str(c)),
                     base - 1, warn=warn, seen=seen, what=tag,
                     ha="center", va="center", fontweight="bold", color=INK)
        for i, b in enumerate(boxes):
            r, c = divmod(i, nc)
            # An empty cell doesn't even get a box drawn: in a "two independent choices" grid, a missing combination should look empty.
            # But with a `mark`, a box with no text is drawn. `mark: blank`
            #   is a light neutral box: a matrix split into blocks
            #   (tiles/masks) needs its empty blocks shown too for the
            #   shape to read, otherwise a 2D block grid reduces to 1D.
            _mk = b.get("mark")
            if not str(b.get("label", "")).strip() and not _mk:
                continue
            _box(ax, gx0 + bw * c + 1.0, gy1 - bh * (r + 1) + 1.0,
                 bw - 2.0, bh - 2.0, b.get("label", ""), None if _mk == "blank" else _mk,
                 fs=base - 1, fig=fig, xs=xs, ys=ys, warn=warn, seen=seen,
                 what=tag)
        for ri, rlab in enumerate(rows):
            fit_text(fig, ax, lab_w - 2.5, gy1 - bh * (ri + 0.5),
                     (lab_w - 4.0) * xs, (bh - 1.0) * ys,
                     strip_markup(str(rlab)), base - 1, warn=warn,
                     seen=seen, what=tag, ha="right", va="center", color=MUTE)
        words += [strip_markup(str(x)) for x in cols + rows]
    elif kind == "stack":
        n = len(boxes)
        bh = (top - bot) / float(n)
        _pt = common_pt([b.get("label", "") for b in boxes], (80 - 2.2) * xs,
                        (bh - 3.0 - 1.4) * ys, base)
        for i, b in enumerate(boxes):
            _box(ax, 10, top - bh * (i + 1) + 1.5, 80, bh - 3.0,
                 b.get("label", ""), b.get("mark"), fig=fig, xs=xs, ys=ys,
                 fs=_pt, warn=warn, seen=seen, what=tag)
    else:                                    # flow
        n = len(boxes)
        gap = 5.0
        bw = (96.0 - gap * (n - 1)) / n
        # Stretching a box to the slot's full height leaves a one-line
        #   label floating in mid-air. A box in a horizontal flow is sized
        #   to its text and centered vertically.
        bh = min(top - bot, 0.62 * bw * (xs / ys))
        y0 = (top + bot) / 2.0 - bh / 2.0
        _pt = common_pt([b.get("label", "") for b in boxes], (bw - 2.2) * xs,
                        (bh - 1.4) * ys, base)
        for i, b in enumerate(boxes):
            x = 2 + (bw + gap) * i
            _box(ax, x, y0, bw, bh, b.get("label", ""), b.get("mark"),
                 fig=fig, xs=xs, ys=ys, fs=_pt, warn=warn, seen=seen,
                 what=tag)
            if i:
                _arrow(ax, x - gap - 0.5, y0 + bh / 2.0, x - 0.5)

    if d.get("title"):
        fit_text(fig, ax, 50, 97 - t_h / 2.0, 96 * xs, t_h * ys,
                 strip_markup(str(d["title"])), BODY_PT + 1.5, warn=warn,
                 seen=seen, what=tag, max_lines=2, ha="center", va="center",
                 fontweight="bold", color=INK)
        words.append(strip_markup(str(d["title"])))
    if d.get("note") or d.get("takeaway"):
        words += bottom_band(fig, ax, xs, ys, 3 + n_h / 2.0, n_h,
                             d.get("note"), d.get("takeaway"),
                             BODY_PT - 2, BODY_PT - 1, warn, seen, tag)
    save_fig(fig, path, seen, warn, tag)
    return [w for w in words if w], seen


def cell_kind(v):
    """Reads a cell's mark: ('hit'|'safe'|'b'|None, plain text)."""
    s = str(v)
    ks = [_which(m)[0] for m in MARKUP.finditer(s)]
    if not ks:
        return None, s
    ks = [k for k in ks if k != "c"]          # code isn't a verdict mark
    if not ks:
        return None, strip_markup(s)
    return ks[0], strip_markup(s)


_SCALE = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "B": 1e9, "T": 1e12,
          "thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}


def num(s):
    """A cell's numeric value. Applies the suffix in `2.16M`/`208K` to the
    value: without this, 208K reads as 208 and a bar is silently wrong.

    Exponential notation (`1.92e+19`) and unit words (`1.5 Trillion`/`300
    Billion`) too, otherwise the first reads as 1.92 and the second as
    1.5/300, silently, which made a line chart copied straight from a
    paper's table unusable. The manuscript's text is left as-is; only the
    value is read correctly.
    """
    t = str(s).replace("−", "-").replace("×", "x")
    e = re.search(r"(?<![\d.])([-+]?\d+(?:\.\d+)?)\s*(?:[eE]\s*([-+]?\d+)|"
                  r"x\s*10\s*\^?\s*\{?\s*([-+]?\d+)\}?)", t)
    if e:
        return float(e.group(1)) * 10.0 ** int(e.group(2) or e.group(3))
    w = re.search(r"(?<![\d.])([-+]?\d+(?:\.\d+)?)\s*(thousand|million|billion|trillion)\b", t, re.I)
    if w:
        return float(w.group(1)) * _SCALE[w.group(2).lower()]
    m = re.search(r"(?<![\d.])([-+]?\d+(?:\.\d+)?)(?![\d.])\s*([kKMGBT](?![A-Za-z]))?", t)
    if not m:
        m = re.search(r"[-+−]?\d+(?:\.\d+)?", str(s).replace("−", "-"))
        return float(m.group(0)) if m else None
    return float(m.group(1)) * _SCALE.get(m.group(2) or "", 1.0)


HEAT_GROW_MAX = 1.6     # cap on growing a heat grid when there's spare space


SKIP_BAND = 2.00       # skip band (row-height multiple): one name line + a line
FRAME_BAND = 1.40      # frame header band (row-height multiple): one name line
FRAME_PAD = 0.35       # extra body the frame extends below the box (row-height multiple)


def _frame_row(fig, ax, r, x0, off, wid, gut, by, bh_row, fr_u, pad_u, xs, ys,
               fs, sec_pt, warn, seen, tag, words):
    """Wraps a row's stages in one frame. The name sits at the frame's top-left inside edge, the note at top-right.

    A single frame lets the figure say "these stages are one system" up front.
    """
    fr = r.get("frame")
    if not fr:
        return
    fr = fr if isinstance(fr, dict) else {}
    n = len(r["stages"])
    ring = ROLE_INK.get(fr.get("mark")) or INK
    fx0 = x0 + off[0] - gut * 0.30
    fx1 = x0 + off[n - 1] + wid[n - 1] + gut * 0.30
    fy0 = by - pad_u
    fy1 = by + bh_row + fr_u
    _round(ax, fx0, fy0, fx1 - fx0, fy1 - fy0, "none", xs, ys, zorder=1.4,
           edge=ring, lw=LW_RING)
    hy = by + bh_row + fr_u * 0.52
    half = (fx1 - fx0) * 0.5 - 1.0
    if fr.get("label"):
        fit_text(fig, ax, fx0 + 1.0, hy, half * xs, fr_u * 0.86 * ys,
                 strip_markup(str(fr["label"])), fs, warn=warn, seen=seen,
                 what=tag, max_lines=1, ha="left", va="center",
                 fontweight="bold", color=ring)
        words.append(strip_markup(str(fr["label"])))
    if fr.get("note"):
        fit_text(fig, ax, fx1 - 1.0, hy, half * xs, fr_u * 0.80 * ys,
                 strip_markup(str(fr["note"])), sec_pt, warn=warn, seen=seen,
                 what=tag, max_lines=1, ha="right", va="center",
                 style="italic", color=MUTE)
        words.append(strip_markup(str(fr["note"])))


def _is_hollow(s):
    """A hollow stage: only has a name (an endpoint like an input/output)."""
    return not (_inner_rows(s.get("inner")) or s.get("glyph") or s.get("sub"))


def _hollow_h(bh_row, lab_lines, body_rows):
    """A hollow box's height. The drawing side and the name-matching side must read the same formula."""
    nlab = 0.85 * (lab_lines - 1)
    hrow = bh_row / (body_rows + 1.45 + nlab)
    return min(bh_row, hrow * (2.3 + 2.0 * nlab))


def draw_heat(t, path, title=None, note=None, slot=None, warn=None,
              takeaway=None):
    # An `hi` mark goes out here too as an outline: see `_cellbox`.
    """Draws a table as a grid. For cases where the shape is the message."""
    header = t.get("header") or []
    rows = t["rows"]
    cols = [strip_markup(h) for h in header[1:]] or \
        ["c%d" % i for i in range(len(rows[0]) - 1)]
    labels = [strip_markup(r[0]) for r in rows]
    nr, nc = len(rows), len(cols)
    slot = slot or (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["chart"])
    seen = []
    tag = os.path.basename(path)

    # The grid also follows its content. A two-column grid has no reason to eat the full body width.
    lab_need = max(wrapped_w(s, BODY_PT - 1, 2) for s in labels)
    cell_need = max([wrapped_w(s, BODY_PT, 1) for s in cols]
                    + [wrapped_w(strip_markup(str(v)), BODY_PT, 1)
                       for r in rows for v in r[1:]] or [0.6])
    # A cell only spends 84% of its width on text (`bw * 0.84`). That share
    #   must be added back in when sizing, otherwise text doesn't fit the
    #   set width and shrinks to 6.5pt.
    need_w = lab_need + nc * (cell_need / 0.84 + 0.22) + 0.3
    need_w = min(slot[0], max(2.0, need_w))
    # Must count the title/caption bands too. Without it, a two-line title
    #   compresses the grid and cell text shrinks to 6.5pt.
    t_lines = (math.ceil(text_w(strip_markup(title), BODY_PT + 1, "bold")
                         / max(0.5, need_w - 0.1)) if title else 0)
    n_lines = max(
        math.ceil(text_w(strip_markup(note), BODY_PT - 2)
                  / max(0.5, need_w - 0.1)) if note else 0,
        math.ceil(text_w(strip_markup(takeaway), BODY_PT - 1, "bold")
                  / max(0.5, need_w - 0.1)) if takeaway else 0)
    need_h = (nr * (ROW_IN * 1.7) + ROW_IN * 1.5
              + min(2, t_lines) * ROW_IN * 1.45
              + min(2, n_lines) * ROW_IN * 1.25 + 0.1)
    # If space falls short, shrink the whole grid at once. Shrinking each
    #   cell separately makes text sizes ragged within one table, and the
    #   fact that it hit the floor gets reported as "this one cell is
    #   small," so the cause, the row count, never shows up.
    avail_h = max(1.0, slot[1])
    fs = BODY_PT
    cell_warn = warn          # once the cause is stated, cells are drawn quietly
    if need_h > avail_h:
        # A label/header is printed at `fs - 1`, so this is set so that is
        #   what touches the floor. Otherwise the grid passes while only
        #   the label falls below the floor, and warnings pile up one after another.
        fs = max(FLOOR_PT + 1.0, BODY_PT * avail_h / need_h)
        if fs <= FLOOR_PT + 1.0 and warn is not None:
            warn.append("%s: %d rows x %d columns doesn't fit this space: reduce the rows, "
                        "split into slides, or show only a few cells with `kind: tiles`"
                        % (os.path.basename(path), nr, nc))
            # Once the cause is stated, don't repeat the symptom. This used
            #   to be followed by 24 lines per cell, burying the actual cause line.
            cell_warn = None
        need_h = avail_h
    else:
        # If there's spare space, grow the whole grid by one ratio. A
        #   3-row 2-column table once used only a third of the body width
        #   and sat at 10pt: the goal is to make the numbers big. Both
        #   width and height stay within bounds, up to 1.6x.
        grow = min(HEAT_GROW_MAX, avail_h / need_h, slot[0] / need_w)
        if grow > 1.05:
            fs = BODY_PT * grow
            need_w, need_h = need_w * grow, need_h * grow
    slot = (need_w, min(avail_h, max(1.0, need_h)))

    fig, ax, xs, ys = _frame(slot)
    # Gives the band height as exactly what the title/caption actually
    #   use. A fixed value once shrank the title to 6.5pt in a narrow cell.
    t_h = band(fig, title, BODY_PT + 1, 96 * xs, ys)
    _two = bool(note and takeaway)
    n_h = max(band(fig, note, BODY_PT - 2, (46 if _two else 96) * xs, ys),
              band(fig, takeaway, BODY_PT - 1, (50 if _two else 96) * xs, ys))
    top = 98 - t_h
    bot = 3 + n_h
    # Sets the row-label width by measuring it. A fixed value lets a long
    #   label spill over the grid or forces abbreviations like `Q1`/`Avg`.
    need = max(_width_in(fig, s) for s in labels) * (fs - 1) / xs
    lab_w = min(36.0, max(12.0, need + 4.0))   # subtracts another 3 for the box's own margin
    # The column-header band is also set by measuring. Fixing it to 9 once
    #   shrank a two-line header to 7.0pt in a narrow cell, the same mistake as the title band.
    head_h = max(band(fig, c, fs - 1, (98.0 - lab_w) / nc * xs, ys,
                      pad=1.0) for c in cols) if cols else 0.0
    head_h = max(7.0, head_h)
    gx0, gx1 = lab_w, 98.0
    gy1, gy0 = top - head_h, bot
    bw, bh = (gx1 - gx0) / nc, (gy1 - gy0) / nr

    for ci, c in enumerate(cols):
        fit_text(fig, ax, gx0 + bw * (ci + 0.5), gy1 + head_h * 0.5,
                 (bw - 1.0) * xs, head_h * 0.9 * ys, c, fs - 1,
                 warn=cell_warn, seen=seen, what=tag, max_lines=2, ha="center",
                 va="center", fontweight="bold", color=INK)
    for ri, lab in enumerate(labels):
        fit_text(fig, ax, lab_w - 2.0, gy1 - bh * (ri + 0.5),
                 (lab_w - 3.0) * xs, (bh - 1.0) * ys, lab, fs - 1,
                 warn=cell_warn, seen=seen, what=tag, max_lines=2, ha="right",
                 va="center", color=INK)

    for ri, row in enumerate(rows):
        for ci, val in enumerate(row[1:]):
            kind, plain = cell_kind(val)
            face = {"hit": HIT, "safe": SAFE}.get(kind)
            cx = gx0 + bw * (ci + 0.5)
            cy = gy1 - bh * (ri + 0.5)
            if kind == "hi":
                # `hi` is marked with an outline, not a color. Red and
                #   green already carry the meaning "significant/not
                #   significant," and reusing that color would make a
                #   statistical claim nobody intended. The doc defines `hi`
                #   as "emphasis for anything else," and the drawing side
                #   was dropping it: a spec accepted and then ignored.
                ax.add_patch(plt.Rectangle(
                    (cx - bw * 0.44, cy - bh * 0.36), bw * 0.88, bh * 0.72,
                    facecolor="none", edgecolor=design.INK,
                    linewidth=design.BASE, zorder=1))
            if face:
                # Gives one more channel besides color. To red-green
                #   colorblind eyes, red and green become the same mustard
                #   color (distance 181 -> 41). A caption that says "red =
                #   significant drop" would then point to a color that isn't on screen.
                ax.add_patch(plt.Rectangle(
                    (cx - bw * 0.44, cy - bh * 0.36), bw * 0.88, bh * 0.72,
                    facecolor=face, edgecolor="none", zorder=1))
                if kind == "hit" and deckspec.SECOND_CHANNEL:
                    ax.add_patch(plt.Rectangle(
                        (cx - bw * 0.44, cy - bh * 0.36), bw * 0.88, bh * 0.72,
                        facecolor="none", edgecolor="white", linewidth=0.0,
                        hatch="////", zorder=1.5, alpha=0.45))
            used = fit_text(fig, ax, cx, cy, bw * 0.84 * xs, bh * 0.66 * ys, plain,
                            fs + (1.0 if face else 0.0), warn=cell_warn, seen=seen,
                            what=tag, max_lines=1, ha="center", va="center", zorder=2,
                            fontweight="bold" if face else "normal",
                            color="white" if face else INK)
            if kind == "hit" and used and deckspec.SECOND_CHANNEL:
                # Hatching goes on the cell, and a same-color plate goes
                #   behind the number. Hatching crossing a white number made
                #   it unreadable. The plate's size comes from measuring the text's width.
                pw = min(bw * 0.88, (_width_in(fig, plain, "bold") * used + 0.10) / xs)
                ph = min(bh * 0.72, (used * 1.25 / 72.0 + 0.04) / ys)
                ax.add_patch(plt.Rectangle(
                    (cx - pw / 2.0, cy - ph / 2.0), pw, ph,
                    facecolor=face, edgecolor="none", zorder=1.7))
    if title:
        fit_text(fig, ax, 50, 98 - t_h / 2.0, 96 * xs, t_h * ys,
                 strip_markup(title), BODY_PT + 1, warn=warn, seen=seen,
                 what=tag, max_lines=2, ha="center", va="center",
                 fontweight="bold", color=INK)
    if note or takeaway:
        bottom_band(fig, ax, xs, ys, 3 + n_h / 2.0, n_h, note, takeaway,
                    BODY_PT - 2, BODY_PT - 1, warn, seen, tag)
    save_fig(fig, path, seen, warn, tag)
    return seen


def draw_bars(t, path, title=None, ylabel=None, note=None, slot=None,
              warn=None, callout=None, takeaway=None, values=True):
    header = t.get("header") or []
    rows = t["rows"]
    series = [strip_markup(h) for h in header[1:]]
    labels = [strip_markup(r[0]) for r in rows]
    slot = slot or (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["chart"])
    seen = []
    tag = os.path.basename(path)
    fs = BODY_PT - 1

    fig = plt.figure(figsize=slot)
    # Bars need an axis. The left margin is set by measuring it: a fixed
    #   ratio leaves spare room in a wide figure and falls short in a
    #   narrow one, clipping tick labels and pushing the axis name
    #   completely outside the figure.
    # If the legend sits below the axis, that space is reserved for it in advance
    _bot = (0.20 if (note or takeaway) else 0.14) + (
        0.12 if [s for s in series if str(s).strip()] else 0.0)
    ax = fig.add_axes([0.13, _bot, 0.85, 0.66 if title else 0.76])
    ns = len(series)
    bar_xy = {}
    w = 0.8 / max(1, ns)
    # Series colors come from design. The second one used to be
    #   "significant drop" red (#C0392B).
    palette = list(design.SERIES)
    # A mark (`<hit>`/`<safe>`) does not change a bar's color. Changing it
    #   would make the legend swatch pick up the first bar's color, so a
    #   series name turns red, and a red bar in a different series becomes
    #   impossible to identify. The series color stays as is; only the
    #   outline and the value text are colored.
    _mark = {}
    # A cell with no value (—, n/a, blank) is not a bar. Filling it with 0
    #   used to draw a "+0.0" bar: a missing measurement looked like a
    #   measurement of 0. Now the space is reserved with no bar drawn, and
    #   the table's own text is written faint.
    _missing = set()
    for si in range(ns):
        vals, edges, lws = [], [], []
        for bi, r in enumerate(rows):
            kind, plain = cell_kind(r[si + 1])
            if num(plain) is None:
                _missing.add((si, bi))
            vals.append(num(plain) or 0.0)
            if kind in ("hit", "safe"):
                _mark[(si, bi)] = kind
            edges.append({"hit": HIT, "safe": SAFE}.get(kind, "none"))
            lws.append(2.0 if kind in ("hit", "safe") else 0.0)
        xsv = [i - 0.4 + w / 2 + si * w for i in range(len(rows))]
        ax.bar(xsv, vals, w * 0.92, color=palette[si % len(palette)],
               edgecolor=edges, linewidth=lws,
               label=series[si] if series else None)
        bar_xy[si] = list(zip(xsv, vals))
    ax.set_xticks(range(len(rows)))
    # Every other generator in this file measures its own text and warns
    #   when it doesn't fit. Only `draw_bars` never measured: three
    #   sixteen-character labels once ran into each other with no warning at
    #   all, and since it's inside a PNG, `fitcheck` couldn't catch it either.
    per = (slot[0] * 0.85) / max(1, len(rows))
    lab_fs = fs
    while lab_fs > FLOOR_PT and max(
            wrapped_w(s, lab_fs, 2) for s in labels) > per:
        lab_fs -= 0.5
    if max(wrapped_w(s, lab_fs, 2) for s in labels) > per and warn is not None:
        warn.append("%s: item names overlap each other: shorten the names or "
                    "switch to `kind: dots`, where each row's name then stands on its own line "
                    "on the left (%d items at %.2f inches each)"
                    % (tag, len(rows), per))
    labels = ["\n".join(_wrap(s.split(), 2)) if wrapped_w(s, lab_fs, 1) > per
              else s for s in labels]
    # Item names are bold: the eye reads "which scenario" first, then looks at the bar.
    ax.set_xticklabels(labels, fontsize=lab_fs, fontweight="bold")
    ax.tick_params(labelsize=lab_fs)
    for s in labels:
        seen.append((round(float(lab_fs), 2), s.replace("\n", " ")))
    # Measures the width tick labels and the axis name actually use, and pushes the axis over by that much.
    fig.canvas.draw()
    _tw = max([tk.get_window_extent(renderer=fig.canvas.get_renderer()).width
               for tk in ax.get_yticklabels()] or [0.0]) / fig.dpi
    _need = 0.05 + _tw + (1.5 * fs / 72.0 if ylabel else 0.0)
    _left = min(0.45, max(0.13, _need / max(0.5, slot[0])))
    # Measure height so it stays inside the canvas. The bottom edge
    #   (`_bot`) rises when an x-axis name wraps to two lines, but height
    #   used to be a constant, and adding the two together made 1.02, so the
    #   plot spilled above the canvas and the top tick labels ran off screen.
    # Measures the bottom margin in inches. The x-axis name, legend, and
    #   caption all have their height set in pt, so leaving this as a ratio
    #   would shrink only the margin when the canvas gets shorter, and everything overlaps.
    _xth = max([tk.get_window_extent(renderer=fig.canvas.get_renderer()).height
                for tk in ax.get_xticklabels() if tk.get_text().strip()]
               or [0.0]) / fig.dpi
    _named = bool([s for s in series if str(s).strip()])
    _need_b = (0.06 + _xth
               + ((fs - 1) * 1.45 / 72.0 + 0.04 if _named else 0.0)
               + ((BODY_PT - 1) * 1.45 / 72.0 + 0.03 if (note or takeaway)
                  else 0.0))
    _bot = min(0.55, max(_bot if not _named and not (note or takeaway)
                         else 0.0, _need_b / max(0.5, slot[1])))
    _h = min(0.66 if title else 0.76, 0.98 - _bot)
    ax.set_position([_left, _bot, 0.98 - _left, _h])
    # Item-name spacing is measured after the layout is settled. The
    #   estimate above treated 85% of the canvas as the axis width, but if
    #   the y-axis text eats more on the left, the actual axis is narrower,
    #   and two neighboring names ended up touching. If the gap between
    #   neighboring names is narrower than one character (0.9em), shrink by one step.
    # If the gap is close to word spacing (about 0.25em), two names read as
    #   one phrase: two names still looked stuck together even past 0.06 inches.
    def _gap_need():
        return max(0.06, 0.9 * lab_fs / 72.0)

    def _tick_gap():
        fig.canvas.draw()
        _r = fig.canvas.get_renderer()
        _bb = sorted((tk.get_window_extent(renderer=_r) for tk in ax.get_xticklabels()
                      if tk.get_text().strip()), key=lambda b: b.x0)
        return min([(b.x0 - a.x1) / fig.dpi for a, b in zip(_bb, _bb[1:])] or [1.0])
    _names = set(s.replace("\n", " ") for s in labels)
    while _tick_gap() < _gap_need() and lab_fs > FLOOR_PT:
        lab_fs -= 0.5
        for tk in ax.get_xticklabels():
            tk.set_fontsize(lab_fs)
        seen[:] = [(round(float(lab_fs), 2), t) if t in _names else (p, t)
                   for (p, t) in seen]
    if _tick_gap() < _gap_need() and warn is not None:
        warn.append("%s: item names touch each other (even shrunk to %.1fpt): shorten the names or "
                    "switch to `kind: dots`, where each row's name then stands on its own line on the left" % (tag, lab_fs))
    ax.axhline(0, color=INK, lw=design.BASE)
    ax.yaxis.grid(True, color=GRID, lw=0.9)
    ax.set_axisbelow(True)
    for s in [str(x) for x in ax.get_yticks()]:
        seen.append((round(float(fs), 2), s))
    if ylabel:
        # Text set vertically is confined to the axis's height. A long name
        #   pokes out top and bottom and gets clipped on both ends. Every
        #   other piece of text in this file shrinks to fit its space, but
        #   the axis name alone wasn't doing that.
        _lab = strip_markup(ylabel)
        _axh = ax.get_position().height * slot[1]
        _ypt = fs
        while _ypt > FLOOR_PT - 1.5 and text_w(_lab, _ypt) > _axh * 0.96:
            _ypt -= 0.5
        if text_w(_lab, _ypt) > _axh * 0.96 and warn is not None:
            warn.append("%s: the y-axis name is longer than the axis (%.1f inches of space "
                        "for %.1f inches): shorten it or leave only the unit"
                        % (tag, _axh, text_w(_lab, _ypt)))
        ax.set_ylabel(_lab, fontsize=_ypt)
        seen.append((round(float(_ypt), 2), _lab))
    # Only puts series with an actual name in the legend. Calling
    #   `legend()` with an empty header makes matplotlib warn "nothing to
    #   attach," and once an unfixable warning mixes in, the recipient stops
    #   reading warnings entirely.
    named = [s for s in series if str(s).strip()]
    # With only one series and a y-axis name present, the legend just says
    #   the same thing again. With no way to turn it off, an "ATE" legend
    #   once sat right under the bars. It's kept only when there's no y-axis name.
    if len(series) == 1 and ylabel:
        named = []
    if named:
        # Places the legend below the axis, outside it. `best` picks
        #   "wherever there are no bars," but a callout arrow picks the same
        #   spot, and the two collide. Placing it below the axis means they don't compete for space.
        # Height is measured from the tick labels' actual bottom. Using a
        #   ratio of axis height (-0.14) instead once made the legend climb
        #   above `Clean` when the figure got shorter.
        fig.canvas.draw()
        _r = fig.canvas.get_renderer()
        _bot = [tk.get_window_extent(renderer=_r).y0
                for tk in ax.get_xticklabels() if tk.get_text().strip()]
        _ly = -0.14
        if _bot:
            _ly = ax.transAxes.inverted().transform((0, min(_bot)))[1]
            _ly -= (0.03 / max(0.3, ax.get_position().height * slot[1]))
        # The swatch is built directly from the series color. An automatic
        #   swatch copies the first bar, so if that bar has a mark outline,
        #   the series name ends up wrapped in a red border.
        _hs = [matplotlib.patches.Patch(facecolor=palette[i % len(palette)],
                                        edgecolor="none", label=s)
               for i, s in enumerate(series) if str(s).strip()]
        # The legend's width is measured to keep it inside the figure.
        #   Kept to one row it once clipped the end of something like
        #   "FlashAttent." If it overflows, columns are reduced and it wraps to two rows.
        # A legend must read horizontally, in bar order. matplotlib fills
        #   it column-first, so four series once read as "DDPG TRPO PPO /
        #   ACKTR" against bars ordered DDPG ACKTR TRPO PPO. Entries are
        #   reordered column-major, and four wraps as 2+2 rather than 3+1.
        _n = len(_hs)
        _cands = [4, 2, 1] if _n == 4 else list(range(min(3, max(1, _n)), 0, -1))

        def _rowmajor(hs, c):
            r = -(-len(hs) // c)
            return [hs[j + k * c] for j in range(c) for k in range(r) if j + k * c < len(hs)]
        for _nc in _cands:
            _lg = ax.legend(handles=_rowmajor(_hs, _nc), fontsize=fs - 1, frameon=False, ncol=_nc,
                            loc="upper center", bbox_to_anchor=(0.5, _ly),
                            handlelength=1.3, columnspacing=1.4, borderpad=0.0)
            fig.canvas.draw()
            _lb = _lg.get_window_extent(fig.canvas.get_renderer())
            if _nc <= 1 or (_lb.x0 >= 1 and _lb.x1 <= fig.bbox.width - 1):
                break
        for s in named:
            seen.append((round(float(fs - 1), 2), s))
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    lo, hi = ax.get_ylim()
    span = max(1e-6, hi - lo)
    # Counts which way the bars extend to decide the empty side. Value
    #   labels and callouts both go there. Without widening the axis, a
    #   label near 0 gets clipped outside it.
    allv = [v for pts in bar_xy.values() for _, v in pts]
    # If bars are all positive (an absolute value like error rate or
    #   score), a callout goes on top. This used to only check "more
    #   negative bars than positive," and otherwise made room below and
    #   lowered the axis into negative territory, producing a negative tick
    #   in an absolute-value figure that has no negatives.
    top_free = (all(v >= 0 for v in allv)
                or sum(1 for v in allv if v < 0) >= sum(1 for v in allv if v > 0))

    def _vstr(si, bi, bv):
        """The value text is exactly as written in the table. Rewriting it
        as `%+.1f` adds a `+` to an absolute value (`+28.5`) and rounds the
        paper's own number, which assumed a bar was always a delta."""
        try:
            raw = strip_markup(str(rows[bi][si + 1])).strip()
        except Exception:
            raw = ""
        if (si, bi) in _missing:
            return raw or u"—"
        # A negative sign uses the same minus as the ticks (U+2212): ticks
        #   read "−5" while values read "-12.6," mixing two different signs
        #   in one figure. The side that reads values (`num`/the sidecar)
        #   reads both as a minus.
        if re.search(r"\d", raw) and len(raw) <= 12:
            return re.sub(r"(?<![\w.])-(?=\d|\.\d)", u"−", raw.replace(u"−", "-"))
        return (("%+.1f" % bv) if abs(bv) < 1000 else "%g" % bv).replace("-", u"−")
    # Value text shrinks only if it actually overlaps. A negative sign is
    #   one character wider, so in a narrow cell with three bars side by
    #   side, "-8.45" and "-9.15" once covered each other (the same figure
    #   with positive values was fine). It shrinks only when drawing shows
    #   an overlap: shrinking based on width alone would also shrink
    #   figures that don't overlap just because their height differs. If it
    #   still overlaps at floor size, the overlap warning reports it.
    vfs = fs - 1
    # Counts the label's own height. Sizing it only as a ratio of the axis
    #   range lets the label poke above the axis when the axis gets
    #   shorter: "+0.0" got clipped outside the figure.
    _axh_in = max(0.2, ax.get_position().height * slot[1])
    _lab_h = (1.5 * vfs / 72.0) / _axh_in * span if values else 0.0
    pad_t = max(span * ((0.26 if callout else 0.08) if top_free else 0.08),
                _lab_h)
    pad_b = max(span * (0.08 if top_free else (0.26 if callout else 0.08)),
                _lab_h)
    ax.set_ylim(lo - pad_b, hi + pad_t)
    lo, hi = ax.get_ylim()
    span = max(1e-6, hi - lo)

    # Writes the value on the bar. With only ticks, the audience has to
    #   trace it with their eyes, and a talk gives them no time for that.
    _vtext = {}                      # (series, bar) -> value text: a callout avoids these
    if values:
        for si, pts in bar_xy.items():
            for _bi, (bx, bv) in enumerate(pts):
                up = bv >= 0
                _vtext[(si, _bi)] = ax.text(
                        bx, bv + (0.018 if up else -0.018) * span,
                        _vstr(si, _bi, bv),
                        ha="center", va="bottom" if up else "top",
                        fontsize=vfs, fontweight="bold",
                        color=MUTE if (si, _bi) in _missing else
                        {"hit": HIT, "safe": design.text_of("safe")}.get(
                            _mark.get((si, _bi)), INK),
                        zorder=4)
                # Recorded with the same hyphen as tick labels (`get_text`): the later cross-check reads a hyphen
                seen.append((round(float(vfs), 2), _vstr(si, _bi, bv).replace(u"−", "-")))

    # Calls out one bar. When there are several bars and the point is
    #   about one of them, a short phrase above that bar carries the slide's point.
    if callout:
        cs = int(callout.get("series", 0))
        at = callout.get("at", 0)
        bi = None
        if isinstance(at, int):
            bi = at if 0 <= at < len(rows) else None
        else:
            want = strip_markup(str(at)).strip().lower()
            for i2, lb in enumerate(labels):
                if strip_markup(lb).replace("\n", " ").strip().lower() == want:
                    bi = i2
                    break
        pts = bar_xy.get(cs)
        if bi is None or not pts:
            if warn is not None:
                warn.append("%s: no bar matches chart.callout.at=%r: "
                            "the row name must be one of %s or a 0-based number"
                            % (tag, at, ", ".join(repr(l) for l in labels)))
        else:
            bx, bv = pts[bi]
            # Color follows the called-out bar's mark: red for `<hit>`,
            #   green for `<safe>`, ink color otherwise. Always red once
            #   attached a red arrow even to an unmarked "+0.0"; `hit`
            #   should only apply to what the paper itself marked. Can also
            #   be given directly with `mark: hit|safe`.
            _k = callout.get("mark") or _mark.get((cs, bi))
            col = {"safe": SAFE, "hit": HIT}.get(_k, INK)
            txt = strip_markup(str(callout.get("text") or ""))
            # The text's width is measured and confined horizontally. Estimating it would run it off-screen.
            xu = len(rows) / max(0.1, slot[0] * 0.85)      # x units / inch
            tw = text_w(txt, fs - 1, "bold") * xu
            x0, x1 = ax.get_xlim()
            # Offsets to the side of the called-out bar so the arrow comes
            #   in at an angle. Placing it directly above would hide the
            #   arrow crossing that bar's own value label.
            side = 1.0 if bx < (x0 + x1) / 2.0 else -1.0
            tx = min(max(bx + side * 0.52, x0 + tw / 2 + 0.05),
                     x1 - tw / 2 - 0.05)
            # Centered in the open band. No bar reaches here.
            ty = (hi - pad_t * 0.55) if top_free else (lo + pad_b * 0.55)
            # The arrow's tip lands beside the value text. The value text
            #   is printed exactly at the bar's tip, so ending there would
            #   draw a red line through "+0.0", which happened before this
            #   was fixed. The arrow comes in from the text's side, so it's
            #   offset by half that width in that direction.
            _vl = _vstr(cs, bi, bv) if values else ""
            # A callout that only repeats the printed value adds a second copy of the same number.
            _norm = lambda t: re.sub(u"[−–]", "-", re.sub(r"\s", "", strip_markup(str(t))))
            if warn is not None and _vl and _norm(txt) == _norm(_vl):
                warn.append("%s: `callout.text` %r repeats the value already printed on that bar. "
                            "Say what the value means instead (\"the gap closes\"), or drop the callout."
                            % (tag, txt))
            _half = (text_w(_vl, vfs, "bold") * xu / 2.0 + 0.05) if _vl else 0.0
            # Half the text's height: ending it at the floor would let an arrow coming from below cut across the corner
            _axh = max(0.2, ax.get_position().height * slot[1])
            _lh = ((vfs) / 72.0) / _axh * span * 0.55 if _vl else 0.0
            _ty = bv + (_lh if bv >= 0 else -_lh)
            _tx = bx + side * _half
            # If the called-out bar extends toward the opposite side from
            #   the open band, an arrow pointing at its tip runs down across
            #   a neighboring bar and its value text. In that case the bar
            #   instead points at the spot where it starts from the
            #   baseline: calling out one bar still means the same thing,
            #   just a shorter arrow.
            _flip = (top_free and bv < 0) or (not top_free and bv > 0)
            if _flip:
                _ty = (0.03 if top_free else -0.03) * span
                _tx = bx
            # The text must sit at least two lines away from the called-out
            #   spot for the arrow to be visible. If the bar's tip touches
            #   the open band (near 0), the text sat at the same height as
            #   the value text and the arrow's length became 0. If there
            #   isn't enough room, the axis grows.
            _line = ((fs - 1) / 72.0) / _axh * span
            _rad = 0.12
            # A bar pointing away from the open band is called out at its base.
            #   Coming in at an angle, that arrow ran across the neighbouring
            #   bar's value label ("+0.0" next to a long negative bar), so it drops
            #   straight down too.
            if top_free and (bv >= 0 or _flip):
                # Placed directly above the called-out bar. Placing it in
                #   the topmost band once, when calling out a short bar,
                #   covered a neighboring tall bar's value (21.0) and the
                #   arrow crossed another bar and its value. Height is set
                #   above the value text of whichever bars fall under the
                #   text's width, and the arrow drops straight down.
                tx = min(max(bx, x0 + tw / 2 + 0.05), x1 - tw / 2 - 0.05)
                _half_bar = w * 0.46
                _tops = [v + _lab_h for pts_ in bar_xy.values() for (x_, v) in pts_
                         if x_ + _half_bar >= tx - tw / 2 and x_ - _half_bar <= tx + tw / 2]
                if _flip:
                    _tops.append(_ty)
                else:
                    _tops.append(bv + _lab_h)
                    _tx, _ty = bx, bv + _lab_h * 0.95
                # Floats just enough for the arrow to be visible: calling out the tallest bar once put the text right against its value
                ty = max(max(_tops) + 1.3 * _line, _ty + 2.75 * _line)
                _rad = 0.0
                if ty + 0.8 * _line > hi:
                    hi = ty + 0.8 * _line
                    ax.set_ylim(lo, hi)
            elif top_free and ty < _ty + 2.4 * _line:
                ty = _ty + 2.4 * _line
                if ty + _line > hi:
                    hi = ty + _line
                    ax.set_ylim(lo, hi)
            elif not top_free and ty > _ty - 2.4 * _line:
                ty = _ty - 2.4 * _line
                if ty - _line < lo:
                    lo = ty - _line
                    ax.set_ylim(lo, hi)
            _an = ax.annotate(txt, xy=(_tx, _ty), xytext=(tx, ty),
                        ha="center", va="center", fontsize=fs - 1,
                        fontweight="bold", color=col, zorder=5,
                        # Gives the text a background-color box. Without
                        #   it, the arrow started from the exact center of
                        #   the text and cut across it. With the box, it
                        #   starts from the box's edge, and the box also
                        #   hides the zero line behind it.
                        bbox=dict(boxstyle="square,pad=0.15", fc=fig.get_facecolor(),
                                  ec="none"),
                        arrowprops=dict(arrowstyle="->", color=col, lw=1.4,
                                        shrinkA=2, shrinkB=3,
                                        connectionstyle="arc3,rad=%s" % _rad))
            # It's drawn, then offset by measuring it. The estimated text
            #   height was smaller than the real one, so it was judged "no
            #   overlap" while the screen actually had a 4px overlap.
            # Checked against every value text. A long callout can cover
            #   even a neighboring bar's value (`+3.8`). If the offset spot
            #   still overlaps, it offsets once more.
            if _vtext:
                for _try in range(4):
                    fig.canvas.draw()
                    _r = fig.canvas.get_renderer()
                    cb = matplotlib.text.Text.get_window_extent(_an, _r)   # text only: excludes the arrow
                    bad = [lb for lb in (v.get_window_extent(_r)
                                         for v in _vtext.values())
                           if min(lb.x1, cb.x1) - max(lb.x0, cb.x0) > 0
                           and min(lb.y1, cb.y1) - max(lb.y0, cb.y0) > 0]
                    if not bad:
                        break
                    if top_free:
                        dy = max(lb.y1 for lb in bad) - cb.y0 + 4.0
                    else:
                        dy = -(cb.y1 - min(lb.y0 for lb in bad) + 4.0)
                    ax_, ay_ = _an.xyann
                    px = ax.transData.transform((ax_, ay_))
                    ny = ax.transData.inverted().transform(
                        (px[0], px[1] + dy))[1]
                    _an.xyann = (ax_, ny)
                # On each pass, only the text moves. Growing the axis at
                #   the same time shrinks pixels-per-unit, which makes the
                #   same text bigger in data terms, which grows it again:
                #   over four passes it inflated to -100. Once everything has
                #   moved, if the text is still outside the axis, it grows the axis once by however many pixels stick out.
                fig.canvas.draw()
                _r = fig.canvas.get_renderer()
                cb = matplotlib.text.Text.get_window_extent(_an, _r)
                abx = ax.get_window_extent(_r)
                lo_, hi_ = ax.get_ylim()
                _upp = (hi_ - lo_) / max(1.0, abx.height)     # data / pixel
                if cb.y0 < abx.y0 + 2:
                    ax.set_ylim(lo_ - (abx.y0 + 4 - cb.y0) * _upp, hi_)
                elif cb.y1 > abx.y1 - 2:
                    ax.set_ylim(lo_, hi_ + (cb.y1 - abx.y1 + 4) * _upp)
                # The loop above moves only the text. The arrow can still cross a
                #   value label, and nothing downstream sees inside the PNG.
                if warn is not None and _an.arrow_patch is not None:
                    fig.canvas.draw()
                    _r = fig.canvas.get_renderer()
                    ab = _an.arrow_patch.get_window_extent(_r)
                    _own = _vtext.get((cs, bi))
                    _hit = [v.get_text() for v in _vtext.values() if v is not _own
                            for lb in [v.get_window_extent(_r)]
                            if min(lb.x1, ab.x1) - max(lb.x0, ab.x0) > 1
                            and min(lb.y1, ab.y1) - max(lb.y0, ab.y0) > 1]
                    if _hit:
                        warn.append("%s: the callout arrow crosses the value label %s. "
                                    "Point at another series, or shorten `callout.text`."
                                    % (tag, " / ".join(repr(h) for h in _hit)))
            seen.append((round(float(fs - 1), 2), txt))

    if title:
        # The title also wraps to fit its width: when a figure in a cell
        #   got narrower through feedback, a one-line title's ends got
        #   clipped outside the figure, and a warning fired but there was no way to fix it.
        _tt = strip_markup(title)
        _tn = max(1, min(2, int(math.ceil(text_w(_tt, BODY_PT + 1, "bold") / max(0.3, slot[0] * 0.94)))))
        ax.set_title("\n".join(_wrap(_tt.split(), _tn)) if _tn > 1 else _tt, fontsize=BODY_PT + 1,
                     fontweight="bold", color=INK)
        seen.append((round(float(BODY_PT + 1), 2), _tt))
    two = bool(note and takeaway)

    def _fold(s, pt, weight):
        """Wraps to fit its width. Printed as one line, its ends got clipped in a narrow cell."""
        room = slot[0] * (0.46 if two else 0.94)
        need = text_w(s, pt, weight)
        n = max(1, min(3, int(math.ceil(need / max(0.3, room)))))
        return "\n".join(_wrap(s.split(), n)) if n > 1 else s
    _band = []
    if note:
        _band.append(fig.text(0.02 if two else 0.5, 0.02,
                              _fold(strip_markup(note), BODY_PT - 2, "normal"),
                              ha="left" if two else "center", va="bottom",
                              fontsize=BODY_PT - 2, color=MUTE))
        seen.append((round(float(BODY_PT - 2), 2), strip_markup(note)))
    if takeaway:
        _band.append(fig.text(0.98 if two else 0.5, 0.02,
                              _fold(strip_markup(takeaway), BODY_PT - 1, "bold"),
                              ha="right" if two else "center", va="bottom",
                              fontsize=BODY_PT - 1, fontweight="bold", color=INK))
        seen.append((round(float(BODY_PT - 1), 2), strip_markup(takeaway)))
    # It's drawn, then pushed by measuring it. If the axis name is outside
    #   on the left, the axis moves right; if the legend/tick labels touch
    #   the band below (caption/takeaway), the axis moves up. The estimated
    #   margin fell short in narrow cells before, clipping figures with no warning.
    fig.canvas.draw()
    _r = fig.canvas.get_renderer()
    _W, _H = fig.get_size_inches() * fig.dpi
    _pos = ax.get_position()
    _dx = _dy = 0.0
    _yl = ax.yaxis.label
    if _yl.get_text().strip():
        _b = _yl.get_window_extent(_r)
        if _b.x0 < 3:
            _dx = (3 - _b.x0) / _W
    _floor = max([b.get_window_extent(_r).y1 for b in _band] or [0.0]) + 4
    _low = [tk.get_window_extent(_r).y0 for tk in ax.get_xticklabels()
            if tk.get_text().strip()]
    _lg = ax.get_legend()
    if _lg is not None:
        _low.append(_lg.get_window_extent(_r).y0)
    if _low and min(_low) < _floor:
        _dy = (_floor - min(_low)) / _H
    if _dx or _dy:
        ax.set_position([_pos.x0 + _dx, _pos.y0 + _dy,
                         max(0.2, _pos.width - _dx),
                         max(0.2, _pos.height - _dy)])
        # A shorter axis can get different ticks with wider labels, which pushes the y label
        #   back past the left edge; measure it again after the move.
        if _yl.get_text().strip():
            fig.canvas.draw()
            _b = _yl.get_window_extent(fig.canvas.get_renderer())
            if _b.x0 < 3:
                _p2 = ax.get_position()
                _d2 = (3 - _b.x0) / _W
                ax.set_position([_p2.x0 + _d2, _p2.y0, max(0.2, _p2.width - _d2), _p2.height])
    # Value-text overlap is measured only after the axis is fully settled:
    #   a callout and the margin push both change the axis, which moves the text.
    _vt = list(_vtext.values())
    while vfs > FLOOR_PT - 1.0 + 1e-6:
        fig.canvas.draw()
        _r = fig.canvas.get_renderer()
        _bb = [v.get_window_extent(_r) for v in _vt]
        # The overlap check is the same as `save_fig`'s warning, and
        #   horizontally, being within 1.5px counts as overlapping: two
        #   touching "0.06"s once read as a single "0.060.06"
        if not any(min(a.x1, b.x1) - max(a.x0, b.x0) > -1.5
                   and min(a.y1, b.y1) - max(a.y0, b.y0)
                   > max(1.0, 0.15 * max(1.0, min(a.height, b.height)))
                   for i_, a in enumerate(_bb) for b in _bb[i_ + 1:]):
            break
        vfs = max(FLOOR_PT - 1.0, vfs - 0.5)
        for v in _vt:
            v.set_fontsize(vfs)
    if vfs != fs - 1:
        _vs = set(v.get_text() for v in _vt)
        seen = [((round(float(vfs), 2), t_) if (z_ == round(float(fs - 1), 2) and t_ in _vs) else (z_, t_))
                for z_, t_ in seen]
    # If it still overlaps at floor size, stagger them upward: when two
    #   neighboring bars share the same value (0.06 / 0.06), shrinking still
    #   leaves them stuck together as "0.060.06." Scanning left to right, a
    #   text that overlaps the one before it is pushed above it (below, for negatives).
    if _vt:
        fig.canvas.draw()
        _r = fig.canvas.get_renderer()
        _placed = []
        for v in sorted(_vt, key=lambda t_: t_.get_position()[0]):
            bb = v.get_window_extent(_r)
            _up = v.get_va() != "top"
            for pb in _placed:
                if min(bb.x1, pb.x1) - max(bb.x0, pb.x0) > -1.5 and \
                        min(bb.y1, pb.y1) - max(bb.y0, pb.y0) > 1:
                    dy = (pb.y1 - bb.y0 + 2.0) if _up else -(bb.y1 - pb.y0 + 2.0)
                    x_, y_ = v.get_position()
                    px = ax.transData.transform((x_, y_))
                    v.set_position((x_, ax.transData.inverted().transform((px[0], px[1] + dy))[1]))
                    bb = v.get_window_extent(_r)
            _placed.append(bb)
        # If a raised text ends up outside the axis, grow the axis by that much
        fig.canvas.draw()
        _r = fig.canvas.get_renderer()
        abx = ax.get_window_extent(_r)
        lo_, hi_ = ax.get_ylim()
        _upp = (hi_ - lo_) / max(1.0, abx.height)
        _top = max(v.get_window_extent(_r).y1 for v in _vt)
        _bot = min(v.get_window_extent(_r).y0 for v in _vt)
        if _top > abx.y1 - 2:
            ax.set_ylim(lo_, hi_ + (_top - abx.y1 + 4) * _upp)
        if _bot < abx.y0 + 2:
            lo_, hi_ = ax.get_ylim()
            ax.set_ylim(lo_ - (abx.y0 + 4 - _bot) * _upp, hi_)
    for size, s in seen:
        _note_size(size, s, warn, None, tag)
    save_fig(fig, path, seen, warn, tag)
    return seen



# ──────────────────────────────────────────────────────────────────────
# Tile grid: read as a field, not a table.
#
# The decisive difference from `heat` is that even non-significant cells
#   are filled. Numbers on a white background just end up as a pretty
#   table. Filling every cell lets the eye read the arrangement of color
#   first, and the numbers second.
# A wrong record used to sit right here. It said a sample deck's tile
#   numbers are 9-10pt on screen, matching body text, but measuring that
#   PNG showed the stroke height was 25pt on screen (about 36pt as a
#   character size), three times the 12pt body text on the same page.
#   Drawing to that wrong record made the generated tiles look like a
#   colored-in table. Fill says where to look; size says how much it
#   matters. Neither can substitute for the other.
TILE_BG = design.TILE_FILL      # a cell with no mark (#E8EDEF)
TILE_FG = design.INK


def _tile(ax, x, y, w, h, text, mark, fig, xs, ys, fs, warn, seen, what,
          verdict=None, sec_pt=None, v_in=0.0):
    """One cell. If `verdict` is given, writes a verdict below the value.

    Writes a verdict below a big number ("over budget" / "within budget,"
    for instance). Hatching and color are channels for colorblind viewers
    but do not state the meaning: without that stated on screen, the
    audience can only guess that red is bad.
    """
    face = {"hit": HIT, "safe": SAFE}.get(mark, TILE_BG)
    fg = "#FFFFFF" if mark in ("hit", "safe") else TILE_FG
    # `hi` is marked with an outline, not a color. Red and green already
    #   carry the meaning "significant/not significant," so reusing that
    #   color would make a statistical claim nobody intended. The doc
    #   defines `hi` as "emphasis for anything else," and the drawing side
    #   was dropping it: a spec accepted and then ignored.
    if mark == "hi":
        _round(ax, x, y, w, h, face, xs, ys, zorder=1,
               edge=design.INK, lw=design.BASE)
    else:
        _round(ax, x, y, w, h, face, xs, ys, zorder=1)
    if mark == "hit" and not verdict and deckspec.SECOND_CHANNEL:
        # One more channel besides color. To red-green colorblind eyes, red
        #   and green are the same mustard color.
        # But skip this when a verdict sentence is already attached: the
        #   meaning is already stated in words, and hatching only makes
        #   that text harder to read there.
        _round(ax, x, y, w, h, "none", xs, ys, zorder=1.5, alpha=0.40,
               hatch="////", edge="white")
    if verdict:
        vh = max(0.02, min(v_in, h * ys * 0.55)) / ys      # axis units
        pad = h * 0.06
        fit_text(fig, ax, x + w / 2.0, y + vh + (h - vh - pad) / 2.0,
                 (w - 1.0) * xs, (h - vh - pad * 2) * ys, text, fs,
                 warn=warn, seen=seen, what=what, max_lines=1, ha="center",
                 va="center", zorder=2, fontweight="bold", color=fg, outer_w=w * xs)
        fit_text(fig, ax, x + w / 2.0, y + pad + vh / 2.0, (w - 1.0) * xs,
                 vh * ys, verdict, max(FLOOR_PT, (sec_pt or fs)),
                 warn=warn, seen=seen, what=what, max_lines=2, ha="center",
                 va="center", zorder=2, color=fg, outer_w=w * xs)
        return
    used = fit_text(fig, ax, x + w / 2.0, y + h / 2.0, (w - 1.0) * xs,
                    (h - 1.0) * ys, text, fs, warn=warn, seen=seen, what=what,
                    max_lines=1, ha="center", va="center", zorder=2,
                    fontweight="bold", color=fg, outer_w=w * xs)
    if mark == "hit" and used and deckspec.SECOND_CHANNEL:
        # Hatching goes on the cell, and a same-color plate goes behind
        #   the number, same as `heat`. Hatching crossing a white number
        #   made it unreadable. The plate's size comes from measuring the text's width.
        pw = min(w * 0.96, (_width_in(fig, strip_markup(str(text)), "bold") * used
                            + 0.10) / xs)
        ph = min(h * 0.9, (used * 1.25 / 72.0 + 0.04) / ys)
        ax.add_patch(plt.Rectangle((x + (w - pw) / 2.0, y + (h - ph) / 2.0), pw, ph,
                                   facecolor=face, edgecolor="none", zorder=1.7))


def panel_tables(slide, ch):
    """`chart.panels` -> [(panel title, table), ...]. Falls back to its own single table.

    Placing the same grid side by side for two subjects lets the eye go
    back and forth between the same cell to compare. This was missing
    before, and had been written off as something that couldn't be expressed.
    """
    ps = ch.get("panels")
    if not ps:
        return None
    out = []
    for p in ps:
        p = p if isinstance(p, dict) else {"from": p}
        # A table can be placed directly inside a panel. The data sits right next to what draws it.
        tb = p.get("table") or find_table(slide, p.get("from", "self"), "self")
        out.append((p.get("title"), tb))
    return out


# The same test `prose_audit` uses for "does this slide say what a blank cell means".
EXPLAINS_BLANK = re.compile(
    r"dash|not\s+(run|tested|measured|applicable)|blank|empty|"
    u"(^|[\\s(])([\\-–—]|n/?a)\\s*[:=]", re.I)


def blanks_said(s):
    """Does the slide say, anywhere on screen, what a blank cell means?"""
    txt = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            txt.append(v)
    for k in ("title", "fine", "foot", "note", "bullets", "chart", "table", "left", "right", "parts"):
        walk(s.get(k))
    return bool(EXPLAINS_BLANK.search(strip_markup(" ".join(txt))))


def draw_tiles(panels, path, title=None, note=None, slot=None, warn=None,
               col_notes=None, row_label=None, col_label=None,
               verdict=None, takeaway=None, share_rows=False, blanks_said=False):
    """One tile grid, or several placed side by side. `panels` = [(title, table), ...].

    `blanks_said`: the slide says what a blank cell means ("-: not tested"). Then a
    mostly blank row is a design fact, not clutter, and is not flagged.

    Bands (title, panel name, axis name, header, subtitle, caption) are all
    measured in inches first, then stacked top to bottom. Building it by
    subtracting margins on the fly let the axis name overlap the header and
    let a caption cover the grid. Stacked, they cannot overlap.

    Size is measured twice. Measuring only once creates a contradiction: if
    space falls short and text stops at the floor, the band shrinks but the
    text doesn't, and they overlap. It's measured first at body size, then
    the bands are re-measured at the size actually used.
    """
    slot = slot or (deckspec.TEXT_W_IN, deckspec.SLOT_H_IN["chart"])
    seen = []
    tag = os.path.basename(path)
    np_ = len(panels)

    heads = [[strip_markup(h) for h in (tb.get("header") or [])[1:]]
             for _, tb in panels]
    nr = max(len(tb["rows"]) for _, tb in panels)
    # Tiling every cell. If only a few cells are marked but more than six
    #   cells are tiled, the audience has to hunt for those few. Planning
    #   §table wrote down this as a common failure, but guidance alone
    #   wasn't enough, so build now flags it.
    if warn is not None and np_ == 1:
        _vals = [strip_markup(str(c)).strip() for _, _tb in panels
                 for _r in _tb["rows"] for c in _r[1:]]
        _real = [v for v in _vals if v and v not in BLANK_CELLS]
        _mk = sum(1 for _, _tb in panels for _r in _tb["rows"] for c in _r[1:]
                  # `<hi>` counts as a mark too: a paper with no good/bad axis uses only that
                  if cell_kind(c)[0] in ("hit", "safe", "hi"))
        if len(_real) >= 6 and _mk * 3 <= len(_real):
            warn.append(
                u"%s: all %d cells were drawn as tiles, but only %d are marked: the "
                u"audience has to hunt for those %d. Mark within the full table, and "
                u"only blow up the standout part as tiles when the table itself is too big "
                u"to read (planning §table)."
                % (tag, len(_real), _mk, _mk))
    # A row that's mostly dashes shrinks every tile. Giving up space for
    #   blank cells shrank the numbers in the cells that carry the argument.
    if warn is not None and nr > 2 and not blanks_said:
        for _pt, _tb in panels:
            for _r in _tb["rows"]:
                _cells = [strip_markup(str(c)).strip() for c in _r[1:]]
                _dash = sum(1 for c in _cells
                            if not c or c in BLANK_CELLS)
                if len(_cells) >= 2 and _dash * 2 > len(_cells):
                    warn.append(
                        u"%s: tile row \"%s\" has %d of %d cells blank, and every tile shrinks "
                        u"to make room for them. If the argument does not compare this row, send "
                        u"it to `fine` or a backup table. If the blanks are part of the design "
                        u"(combinations that were not run), keep the row and say so on the slide "
                        u"(\"-: not tested\"), which also silences this."
                        % (tag, strip_markup(str(_r[0])), _dash, len(_cells)))
    nc = max([len(x) for x in heads] or [1]) or 1
    has_ptitle = any(ttl for ttl, _ in panels)
    # If row names are the same across panels, write it once on the left.
    #   Writing it twice isn't information, and that width once shrank cell
    #   text below the floor.
    _names = [tuple(strip_markup(str(r[0])) for r in tb["rows"]) for _, tb in panels]
    # By default, row names appear per panel. If width falls short, use `share_rows: true`.
    shared = bool(share_rows) and np_ > 1 and len(set(_names)) == 1

    def measure(fs, tight=False):
        """The (width, height, band, label width, cell width, axis width, subtitle pt) needed at this text size.

        `tight` is used to check whether the text fits at all. Requiring
        even generous margin as mandatory flags "doesn't fit" on figures
        that render fine, and a false positive hides the real problem.
        """
        pad = 0.10 if tight else 0.26
        gut = 0.06 if tight else 0.18
        # A tile grid has plenty of room: secondary text also stops at
        #   the floor. Bands and structure diagrams sometimes fall below
        #   the floor because their space is constrained, but not here.
        sec = max(FLOOR_PT, fs - 2)
        line = 1.26 * fs / 72.0
        sline = 1.26 * sec / 72.0
        # Width comes first. Row height depends on how many lines the
        #   verdict sentence wraps to, and that line count depends on the
        #   cell's width. Computing height first would use a number that doesn't exist yet.
        lab = max(wrapped_w(strip_markup(r[0]), fs, 1)
                  for _, tb in panels for r in tb["rows"]) + gut
        cell = max([wrapped_w(s, fs, 1) for x in heads for s in x]
                   + [wrapped_w(strip_markup(str(v)), fs, 1)
                      for _, tb in panels for r in tb["rows"] for v in r[1:]]
                   + [0.34]) + pad
        if col_notes:
            # The drawing side wraps to two lines (`max_lines=2`).
            #   Measuring at one line here once let the subtitle widen the
            #   whole cell, and that width flagged "doesn't fit," even at
            #   2 rows x 2 columns. Lines measured and lines drawn must match.
            cell = max(cell, max(wrapped_w(s, sec, 2)
                                 for s in col_notes) + 0.12)
        # The subtitle's line count is also measured. Always assuming two
        #   lines once wasted a vertical line for a subtitle that fit one,
        #   shrinking the value by that much.
        cn_lines = 0
        if col_notes:
            cn_lines = 1 if (max(text_w(strip_markup(str(s)), sec)
                                 for s in col_notes) + 0.12 <= cell) else 2
        v_in = 0.0
        if verdict:
            # Measures the line count first. If it fits one line, that's
            #   one line, and there's no reason to raise the cell. Always
            #   assuming two lines shrinks the value by that much.
            vt = [strip_markup(str(v)) for v in verdict.values()]
            if max(text_w(v, sec) for v in vt) + 0.16 <= cell:
                vlines = 1
            else:
                vlines = 2
                cell = max(cell, max(wrapped_w(v, sec, 2) for v in vt) + 0.16)
            v_in = vlines * 1.26 * sec / 72.0 * 1.10
        aw = (wrapped_w(row_label, sec, 2) + 0.12) if row_label else 0.0
        if shared:
            ww = (aw + lab) + np_ * (nc * cell + gut) + (np_ - 1) * (pad - 0.04)
        else:
            ww = np_ * (aw + lab + nc * cell + gut) + (np_ - 1) * (pad - 0.04)
        tk_lines = 0
        if takeaway:
            # A takeaway shares the bottom band with a cue: it must be measured that much narrower
            avail = max(0.6, (0.50 if note else 0.96) * min(ww, slot[0]))
            tk_lines = min(2, max(1, int(math.ceil(
                text_w(strip_markup(str(takeaway)), fs, "bold") / avail))))

        # `tight` is the ruler for whether the text fits at all. But it
        #   only shrank the horizontal margin while leaving the vertical one
        #   as is, so figures that render fine still flagged "height falls
        #   short." The ruler differed between the two directions. Only the
        #   margin share shrinks; the height text actually needs is left untouched.
        vk = 0.72 if tight else 1.0

        def bnd(unit, mult, floor_mult):
            return unit * max(floor_mult, mult * vk)

        band = {
            "title": bnd(line, 1.55, 1.08) if title else 0.0,
            "ptitle": bnd(line, 1.45, 1.08) if has_ptitle else 0.0,
            "axis": bnd(sline, 1.25, 1.05) if col_label else 0.0,
            # If the corner text (header[0]) wraps to two lines, the header
            #   band must be two lines tall too. Putting two lines into a
            #   one-line band once made it stick up and get clipped outside the figure.
            "head": max(bnd(line, 1.30, 1.08),
                        (bnd(sline, 1.25 + 1.05, 1.05 * 2) if _corner_lines(sec, lab + aw) > 1
                         else 0.0)),
            "cnote": (bnd(sline, 1.25 + 1.05 * (cn_lines - 1), 1.05 * cn_lines)
                      if col_notes else 0.0),
            # Adds the measured verdict height to one value line. Splitting
            #   it by ratio instead makes text run outside the cell when
            #   space changes, and the value shrinks to pay for it: shrinking
            #   the value to make room for a verdict is backward.
            "row": bnd(line, 1.95, 1.18) + v_in * max(1.02, 1.55 * vk),
            "note": bnd(sline, 1.55, 1.05) if note else 0.0,
            # A takeaway that wraps to two lines but was fixed to one and a
            #   half printed smaller than the cue. If a takeaway is smaller
            #   than a cue, the reading order flips.
            "take": (bnd(line, 1.20 + 0.92 * tk_lines, 1.02 * tk_lines)
                     if takeaway else 0.0),
        }
        hh = (band["title"] + band["ptitle"] + band["axis"] + band["head"]
              + band["cnote"] + nr * band["row"] + band["note"]
              + band["take"] + 0.10)
        return ww, hh, band, lab, cell, aw, sec, v_in

    def _corner_lines(sec_, avail_in):
        cs = [strip_markup(str((tb.get("header") or [""])[0] or "")) for _, tb in panels]
        cs = [c for c in cs if c.strip()]
        if not cs or avail_in <= 0:
            return 1
        return 2 if max(text_w(c, sec_) for c in cs) > avail_in - 0.06 else 1

    need_w, need_h = measure(BODY_PT)[:2]
    # Don't stop at the floor (8pt): fit to the space instead. Stopping
    #   there and enlarging the canvas makes LaTeX shrink the whole figure,
    #   which leaves text the same size anyway while losing width too, so
    #   the figure sits small in the middle. Going below the floor is not
    #   hidden: `_note_size` warns for every line.
    fs = max(FLOOR_PT - 1.5,
             BODY_PT * min(1.0, slot[0] / need_w, slot[1] / need_h))
    # What decided the figure's overall text size: build reads this when picking a fix (`BOUND`)
    if min(slot[0] / need_w, slot[1] / need_h) < 1.0:
        BOUND[(os.path.basename(path), "*")] = "w" if slot[0] / need_w <= slot[1] / need_h else "h"
    need_w, need_h, B, lab_w, cell_w, axis_w, sec_pt, v_in = measure(fs)
    # Does it still not fit at floor size: this is what "unreadable" means here
    floor_w, floor_h = measure(FLOOR_PT, tight=True)[:2]

    # Warn only when it's actually unreadable. If it fits at floor size, it
    #   fits. Saying "doesn't fit" for "10pt isn't enough" is a false
    #   positive, and a false positive hides the real problem.
    wide = floor_w > slot[0] + 1e-6
    tall = floor_h > slot[1] + 1e-6
    _outer, _pend = warn, None
    if wide or tall:
        if warn is not None:
            # Count how many fit, and say only which dimension falls
            #   short. Saying only "doesn't fit" leaves the recipient not
            #   knowing what to cut, and naming the wrong dimension makes them fix the wrong thing.
            bits = []
            if wide:
                # Counted at the floor size. Counting with the shrunk cells said
                #   "up to 1 column fits" while all three were drawn, below the floor.
                _fl = measure(FLOOR_PT, tight=True)
                per = (slot[0] / np_ - _fl[5] - _fl[3] - 0.06)
                fits = min(nc, max(0, int(per / max(0.2, _fl[4]))))
                bits.append("width falls short by %.2f inches: at %gpt, the size aimed for, only %d of %d "
                            "column(s)%s fit, so all of them are drawn smaller. "
                            "Flipping rows and columns usually fixes it, but if the "
                            "reading direction (read by row, or by column) is itself the "
                            "argument, don't flip it; shorten the names or split into panels instead"
                            % (floor_w - slot[0], FLOOR_PT, fits, nc,
                               " per panel" if np_ > 1 else ""))
            if tall:
                # Says to shrink the band before the row count: there's
                # something droppable before giving up the data itself.
                # A verdict is moved, not dropped. SKILL says to state what
                #   the color means, but the old advice instead said to try
                #   dropping it. Writing it once on a `foot` line instead of
                #   per cell keeps the meaning and frees up one cell per row.
                drop = [n for n, k in (("takeaway", takeaway),
                                       ("column subtitle (col_notes)", col_notes),
                                       ("title", title),
                                       ("note", note)) if k]
                move = (" Drop the verdict written per cell and move its meaning to one "
                        "foot line for the slide (\"red = significant drop\"): the "
                        "meaning of the color is kept."
                        if verdict else "")
                bits.append("height falls short by %.2f inches: %d rows don't "
                            "fit this space.%s%s"
                            % (floor_h - slot[1], nr, move,
                               (" Before dropping rows, try trimming " + "/".join(drop)
                                + " first.") if drop else ""))
            _pend = ("%s: %d rows x %d columns%s in this space "
                     "(%.1f x %.1f inches) doesn't fit. %s"
                     % (tag, nr, nc,
                        (" (%d panels)" % np_) if np_ > 1 else "",
                        slot[0], slot[1], "  and ".join(bits)), tall, tag)
            # Once the cause is stated, don't repeat it per row (24 lines
            #   once buried the cause line). Drawing-time warnings are
            #   collected separately and judged by `_settle`
            warn = []

    # Gives spare space back to the rows. Until now, only what was needed
    #   was drawn and the rest was left blank, so even a grid with just four
    #   cells carried body-size numbers, leaving white space below it on the
    #   slide. Filling the grid's full space makes the numbers look three
    #   times body size. The header/caption bands are left alone: they have
    #   no reason to grow.
    if need_h < slot[1] - 0.02 and nr:
        spare = slot[1] - need_h
        # Past 2.3x its own height, a row stops being a cell and becomes a wall
        grow = min(spare / nr, B["row"] * 1.3)
        B["row"] += grow
        need_h += grow * nr
    w, h = min(slot[0], need_w), min(slot[1], need_h)
    fig, ax, xs, ys = _frame((max(1.6, w), max(0.8, h)))
    sh = min(1.0, slot[1] / need_h)        # only compresses when height falls short

    def U(inches):
        return inches * sh / ys

    y = 99.0
    if title:
        bh = U(B["title"])
        fit_text(fig, ax, 50, y - bh / 2.0, 96 * xs, bh * ys * 0.90,
                 strip_markup(title), fs + 1, warn=warn, seen=seen, what=tag,
                 max_lines=2, ha="center", va="center", fontweight="bold",
                 color=INK)
        y -= bh

    # A value's size is set once, across the whole grid. Fitting each cell
    #   separately would print `+0.0` and `-23.9` at different sizes and
    #   make the grid ragged. If space is left over, it grows: a tile
    #   number can go up to three times body size.
    # How much of a row a cell fills. Adding a verdict raises the row, but
    #   if the cell keeps using a flat 68%, only the gap between cells
    #   widens, and the value would then shrink and the grid would look ragged.
    TH = 0.86 if verdict else 0.68
    _aw = (axis_w / xs) if row_label else 0.0
    # When shared, the row-name band appears once on the left; panels only get cells
    lead_u = (_aw + lab_w / xs) if shared else 0.0
    pw = (98.0 - 2.0 - lead_u) / np_
    _bw = (pw - 1.2 - (0.0 if shared else _aw + lab_w / xs)) / max(1, nc)
    _vals = [cell_kind(v)[1] for _, tb in panels for r in tb["rows"]
             for v in r[1:]
             if strip_markup(str(v)).strip() not in ("", "-", "\u2013")]
    _w1 = max([_width_in(fig, s, "bold") for s in _vals] or [0.02])
    val_pt = fs
    if _vals:
        box_w = max(0.05, (_bw * 0.92 - 1.0) * xs)
        th_in = U(B["row"]) * TH * ys                # cell height (inches)
        box_h = max(0.05, th_in - v_in - 0.04 if verdict else th_in - 0.03)
        val_pt = max(fs, min(fs * 3.6, box_w / _w1, box_h * 72.0 / 1.26))
    for pi, (ptitle, tb) in enumerate(panels):
        px0 = 2.0 + lead_u + pw * pi
        yy = y
        if has_ptitle:
            bh = U(B["ptitle"])
            if ptitle:
                fit_text(fig, ax, px0 + pw / 2.0, yy - bh / 2.0,
                         (pw - 2) * xs, bh * ys * 0.90,
                         strip_markup(str(ptitle)), fs + 1, warn=warn,
                         seen=seen, what=tag, max_lines=1, ha="center",
                         va="center", fontweight="bold", color=INK)
            yy -= bh

        cols = heads[pi] or ["" for _ in range(nc)]
        rows = tb["rows"]
        aw = (axis_w / xs) if row_label else 0.0
        lw = lab_w / xs
        # When shared, the name appears only at the left of the first panel: other panels start right at their cells
        name_x0 = 2.0 if shared else px0
        draw_names = (not shared) or pi == 0
        gx0 = px0 if shared else px0 + aw + lw
        gx1 = px0 + pw - 1.2
        bw = (gx1 - gx0) / max(1, len(cols))

        if col_label:
            bh = U(B["axis"])
            fit_text(fig, ax, (gx0 + gx1) / 2.0, yy - bh / 2.0,
                     (gx1 - gx0) * xs, bh * ys * 0.88, strip_markup(col_label),
                     sec_pt, warn=warn, seen=seen, what=tag, max_lines=1,
                     ha="center", va="center", style="italic", color=MUTE)
            yy -= bh
        bh = U(B["head"])
        for ci, c in enumerate(cols):
            fit_text(fig, ax, gx0 + bw * (ci + 0.5), yy - bh / 2.0,
                     (bw - 0.8) * xs, bh * ys * 0.88, c, fs, warn=warn,
                     seen=seen, what=tag, max_lines=1, ha="center",
                     va="center", fontweight="bold", color=INK)
        # The table's corner text (header[0]): what was measured. Small, above the row-name column.
        corner = strip_markup(str((tb.get("header") or [""])[0] or ""))
        if corner and draw_names:
            fit_text(fig, ax, (name_x0 + aw + lw) - 0.9, yy - bh / 2.0,
                     max(0.2, lab_w + (axis_w if row_label else 0.0) - 0.06),
                     bh * ys * 0.88, corner, sec_pt, warn=warn, seen=seen,
                     what=tag, max_lines=2, ha="right", va="center", color=MUTE)
        yy -= bh
        if col_notes:
            bh = U(B["cnote"])
            for ci in range(len(cols)):
                if ci < len(col_notes):
                    fit_text(fig, ax, gx0 + bw * (ci + 0.5), yy - bh / 2.0,
                             (bw - 0.6) * xs, bh * ys * 0.88,
                             strip_markup(str(col_notes[ci])), sec_pt,
                             warn=warn, seen=seen, what=tag, max_lines=2,
                             ha="center", va="center", color=MUTE)
            yy -= bh

        rh = U(B["row"])
        top_rows = yy
        if row_label and draw_names:
            fit_text(fig, ax, name_x0 + aw / 2.0, top_rows - rh * len(rows) / 2.0,
                     max(0.2, (aw - 0.6) * xs), rh * len(rows) * 0.55 * ys,
                     strip_markup(row_label), sec_pt, warn=warn, seen=seen,
                     what=tag, max_lines=2, ha="center", va="center",
                     style="italic", color=MUTE)
        for ri, r in enumerate(rows):
            cy = top_rows - rh * (ri + 0.5)
            if draw_names:
                fit_text(fig, ax, (name_x0 + aw + lw) - 0.9, cy, lab_w - 0.06,
                         rh * 0.78 * ys, strip_markup(r[0]), fs, warn=warn,
                         seen=seen, what=tag, max_lines=1, ha="right",
                         va="center", fontweight="bold", color=INK)
            for ci, v in enumerate(r[1:]):
                kind, plain_v = cell_kind(v)
                cx = gx0 + bw * (ci + 0.5)
                # An em dash also counts as "not run." This used to check
                #   only `-`/`–`, so a `—` cell got a "plain" verdict printed
                #   under it: a setting that wasn't run looked "fine."
                if not plain_v.strip() or plain_v.strip() in BLANK_CELLS:
                    ax.text(cx, cy, "\u2013", ha="center", va="center",
                            fontsize=sec_pt, color=GRID, zorder=2)
                    continue
                # A cell with no number ("not run", "skipped") gets no
                #   verdict printed. A verdict is supposed to interpret a
                #   value, but a "plain" verdict once printed under "not
                #   run," making a setting that wasn't run look "fine."
                #   Only the text itself is written, faint.
                if not re.search(r"\d", plain_v):
                    fit_text(fig, ax, cx, cy, bw * 0.92 * xs, rh * TH * ys,
                             plain_v, sec_pt, warn=warn, seen=seen, what=tag,
                             max_lines=2, ha="center", va="center",
                             style="italic", color=MUTE)
                    continue
                _tile(ax, cx - bw * 0.46, cy - rh * TH / 2.0, bw * 0.92,
                      rh * TH, plain_v, kind, fig, xs, ys, val_pt, warn,
                      seen, tag,
                      verdict=(verdict or {}).get(kind or "plain"),
                      sec_pt=sec_pt, v_in=v_in)

    # A figure's takeaway sits inside the figure. A caption is outside it,
    #   so it's read only after the eye leaves the figure, and "what did I
    #   just see" arrives late. One bold line sits inside the figure, bottom right.
    ty = 1.0
    if note:
        bh = U(B["note"])
        two = bool(takeaway)
        fit_text(fig, ax, 2.0 if two else 50, ty + bh / 2.0,
                 (46 if two else 96) * xs, bh * ys * 0.90,
                 strip_markup(note), sec_pt, warn=warn, seen=seen, what=tag,
                 max_lines=2, ha="left" if two else "center", va="center",
                 color=MUTE)
        if not takeaway:
            ty += bh
    if takeaway:
        bh = U(B["take"])
        fit_text(fig, ax, 98 if note else 50, ty + bh / 2.0,
                 (50 if note else 96) * xs, bh * ys * 0.90,
                 strip_markup(takeaway), fs, warn=warn, seen=seen, what=tag,
                 max_lines=2, ha="right" if note else "center", va="center",
                 fontweight="bold", color=INK)
    save_fig(fig, path, seen, warn, tag)
    _settle(_outer, _pend, warn)
    return seen



def _table_in(pane):
    """The table inside a pane, found by unfolding into its parts.

    If `parts` is used, the table lives at `pane["parts"][k]["table"]`.
    Looking only at the pane means "no table," and the chart meant to read
    and draw from that pane disappears entirely.
    """
    for leaf in deckspec.pane_leaves(pane):
        if leaf.get("table"):
            return leaf["table"]
    return None


def find_table(slide, ref, where="self"):
    """The table that `chart.from` points to.

    `self` means whatever the chart is attached to. For a chart inside a
    pane, that's the pane. This used to always look at the slide's own
    table, so a `chart` inside a pane never once got drawn: the only
    warning was "no table," so the cause was never visible. "One pane
    shows the figure, the other explains how to read it" is a common
    two-pane layout, and this bug blocked the only way to build it.
    """
    # If a pane is written as `parts:`, the table lives inside those
    #   parts. Looking only at the pane means "no table," and the chart
    #   meant to read and draw from that table disappears entirely.
    if ref == "self":
        if where == "self":
            return slide.get("table")
        return _table_in(slide.get(where))
    if ref in ("left", "right"):
        return _table_in(slide.get(ref))
    return (slide.get(ref) or {}).get("table")


def _in_panes(slide, key):
    """Finds `key` inside a pane, unfolding all the way into its parts.

    A diagram placed inside a part once never got drawn: no file was
    built, and the deck built that spot as an empty box along with one
    line, "figure missing." Adding `parts` missed a few places on the
    reading side.
    """
    got = []
    for side in ("left", "right"):
        for leaf in deckspec.pane_leaves(slide.get(side)):
            if leaf.get(key):
                got.append((side, leaf[key]))
                break          # only one per pane: the filename is decided by the pane
    return got


def charts_in(slide):
    """List of (where it's attached, chart spec)."""
    got = []
    if slide.get("chart"):
        got.append(("self", slide["chart"]))
    return got + _in_panes(slide, "chart")


def diagrams_in(slide):
    got = []
    if slide.get("diagram"):
        got.append(("self", slide["diagram"]))
    return got + _in_panes(slide, "diagram")


def chart_path(out_dir, n, where):
    return os.path.join(out_dir, "chart_%02d_%s.png" % (n, where))


def diagram_path(out_dir, n, where):
    return os.path.join(out_dir, "diagram_%02d_%s.png" % (n, where))


TEXTSIZE = "textsize.tsv"


LAST_CUT = set()      # text (even partially) clipped in the last save_fig


def save_fig(fig, path, seen=None, warn=None, tag=""):
    """Saves the figure, stripping out clipped text before it does.

    The sidecar exists to fill the gap that text inside a PNG is pixels, so
    a checker cannot see it. But if text that was thought to be drawn but
    actually got clipped ends up in the sidecar, the sidecar testifies to
    text that never arrived. `outcheck` then prints "0 missing," and a
    person believes it, which is worse than having no checker at all.

    It happened with `ylabel`. The spot that got fixed was `draw_bars`, but
    the hole was open in every generator, so it's blocked in the one place
    that saves.
    """
    fig.canvas.draw()
    W, H = fig.get_size_inches() * fig.dpi
    # A tick outside the view range is only held by matplotlib as a text
    #   object and never drawn. Its position is computed in data coordinates
    #   that fall outside the figure, so it looks "clipped," but it was
    #   never drawn in the first place. This isn't something to warn about;
    #   it's something to drop from the sidecar.
    off_view, lost, clipped = set(), [], []
    for _ax in fig.axes:
        # A diagram with the axis turned off (`ax.axis("off")`) has no tick
        #   text on screen even if the label objects remain. It's skipped
        #   entirely, otherwise 0/20/40... would show up as "clipped" every
        #   time, and that noise would bury the real warnings.
        if not getattr(_ax, "axison", True):
            for _l in list(_ax.get_yticklabels()) + list(_ax.get_xticklabels()):
                off_view.add(id(_l))
            continue
        for get_t, get_l, get_lim in ((_ax.get_yticks, _ax.get_yticklabels,
                                       _ax.get_ylim),
                                      (_ax.get_xticks, _ax.get_xticklabels,
                                       _ax.get_xlim)):
            lo, hi = sorted(get_lim())
            # Minor ticks too: a log axis within one order of magnitude
            #   puts labels on minor ticks, and ones outside the view range
            #   got counted as "clipped."
            for minor in (False, True):
                for val, lab in zip(get_t(minor=minor), get_l(minor=minor)):
                    if not (lo - 1e-9 <= val <= hi + 1e-9):
                        off_view.add(id(lab))
                        lost.append((lab.get_text() or "").strip())
    # Detached text isn't drawn. A tick label from a removed axis remains
    #   as an object and still gets caught by `findobj`, holding onto
    #   whatever position was last computed for it; if that position is
    #   outside the canvas, it counts as "clipped." That text was never on
    #   screen to begin with, so it isn't something to warn about.
    #   Changing the font is what surfaced this.
    _live = set(id(x) for x in fig.texts)
    for _ax in fig.axes:
        for x in _ax.findobj(match=lambda o: hasattr(o, "get_text")):
            _live.add(id(x))
    for tx in fig.findobj(match=lambda o: hasattr(o, "get_text")):
        s = (tx.get_text() or "").strip()
        if not s or not tx.get_visible() or id(tx) in off_view:
            continue
        if id(tx) not in _live:
            continue
        try:
            bb = tx.get_window_extent(renderer=fig.canvas.get_renderer())
        except Exception:
            continue
        # If more than half is outside, treat it as not on screen
        if (bb.x1 < W * 0.02 or bb.x0 > W * 0.98
                or bb.y1 < H * 0.02 or bb.y0 > H * 0.98):
            clipped.append(s)
    # Overlap inside the figure. Text against text, and a callout arrow
    #   against text. It's inside a PNG, so `fitcheck` can't see it, but
    #   right now matplotlib knows every position.
    if warn is not None:
        _rend = fig.canvas.get_renderer()
        _boxes = []
        for tx in fig.findobj(match=lambda o: hasattr(o, "get_text")):
            s = (tx.get_text() or "").strip()
            if (not s or not tx.get_visible() or id(tx) in off_view
                    or id(tx) not in _live):
                continue
            # Counts only text objects. A legend's `TextArea` is a box
            #   wrapping the text, so it got caught a second time at the
            #   same spot, producing `'one' / 'one'`.
            if not isinstance(tx, matplotlib.text.Text):
                continue
            if any(tx is b_[1] for b_ in _boxes):
                continue                 # don't count the same object twice
            try:
                _boxes.append((s, tx, matplotlib.text.Text.get_window_extent(tx, _rend)))
            except Exception:
                continue
        _hit = set()
        for i1 in range(len(_boxes)):
            s1, t1, b1 = _boxes[i1]
            for i2 in range(i1 + 1, len(_boxes)):
                s2, t2, b2 = _boxes[i2]
                ix = min(b1.x1, b2.x1) - max(b1.x0, b2.x0)
                iy = min(b1.y1, b2.y1) - max(b1.y0, b2.y0)
                # Text is read as a line: overlapping more than 30%
                #   vertically and even a little horizontally reads to the
                #   eye as touching. Measured by area, that's under 20%.
                if ix <= 2 or iy <= 1:
                    continue
                if iy > 0.15 * max(1.0, min(b1.height, b2.height)):
                    _hit.add(tuple(sorted((s1[:24], s2[:24]))))
        for s, tx, bb in _boxes:
            ap = getattr(tx, "arrow_patch", None)
            if ap is None:
                continue
            # Flattens the curve and samples it densely. A control point
            #   doesn't sit on the curve itself, so a curve passing straight
            #   through the middle of some text had no sample points land there.
            try:
                pts = []
                for poly in ap.get_path().to_polygons(closed_only=False):
                    for (xa, ya), (xb, yb) in zip(poly[:-1], poly[1:]):
                        for k in range(12):
                            f_ = k / 12.0
                            pts.append((xa + (xb - xa) * f_, ya + (yb - ya) * f_))
            except Exception:
                continue
            for s2, t2, b2 in _boxes:
                if t2 is tx:
                    continue
                inner = (b2.x0 + 1, b2.y0 + 1, b2.x1 - 1, b2.y1 - 1)
                if any(inner[0] < x < inner[2] and inner[1] < y < inner[3]
                       for x, y in pts):
                    _hit.add((u"\u2192 " + s[:20], s2[:24]))
        for a_, b_ in sorted(_hit):
            warn.append(u"%stext overlaps inside the figure: %r / %r: "
                        u"one covers the other"
                        % (tag and tag + ": ", a_, b_))
    # Reports it if even slightly outside the edge. Checking only for
    #   more-than-half-outside once let both ends of a y-axis
    #   name/legend/takeaway get clipped with no warning at all.
    if warn is not None:
        _edge = []
        for tx in fig.findobj(match=lambda o: isinstance(o, matplotlib.text.Text)):
            s = (tx.get_text() or "").strip()
            if (not s or not tx.get_visible() or id(tx) in off_view
                    or id(tx) not in _live or s in clipped):
                continue
            try:
                bb = matplotlib.text.Text.get_window_extent(
                    tx, fig.canvas.get_renderer())
            except Exception:                           # noqa: BLE001
                continue
            if bb.x0 < -1 or bb.y0 < -1 or bb.x1 > W + 1 or bb.y1 > H + 1:
                _edge.append(s)
        for s in sorted(set(_edge)):
            warn.append("%stext is clipped at the figure's edge: %r"
                        % (tag and tag + ": ", s[:48]))
    if clipped and warn is not None:
        for s in sorted(set(clipped)):
            warn.append("%stext was clipped outside the figure and does not appear on screen: %r"
                        % (tag and tag + ": ", s[:48]))
    # Both clipped text and undrawn ticks are dropped from the sidecar.
    # The sidecar testifies that "this text is on screen." Writing down
    # what isn't there would make the checker report something false.
    # Even partially clipped text is not fully on screen either. "37.71"
    #   had its last digit clipped and showed as "37.7," but the sidecar had
    #   37.71 written down, and deckcheck/outcheck/fitcheck all passed it.
    #   It's dropped from the testimony, and a chart sidecar that writes
    #   table values directly also checks this (`LAST_CUT`).
    _cut_now = set(clipped) | set(_edge if warn is not None else [])
    LAST_CUT.clear()
    LAST_CUT.update(strip_markup(x) for x in _cut_now)
    if (_cut_now or lost) and seen is not None:
        gone = set(strip_markup(x) for x in _cut_now) | set(x for x in lost if x)
        seen[:] = [(pt, s) for pt, s in seen if strip_markup(s) not in gone]
    # Background is transparent. Otherwise a white card reads as a border
    #   sitting on the pale gray slide, and the figure ends up looking
    #   placed on top of the slide rather than resting on it.
    fig.savefig(path, dpi=200, transparent=True)
    plt.close(fig)


def fingerprint(im):
    """A fingerprint for one figure: an 8x8 grayscale reduced to 16 levels. A 64-digit hex string.

    Size alone can't match it. A diagram and a grid drawn into the same
    slot have identical pixel dimensions, so one's small text once got
    attributed to the other's number, and a checker that points at the
    wrong spot is worse than none.
    """
    g = im.convert("L").resize((8, 8))
    return "".join("%x" % (p >> 4) for p in g.tobytes())


# On a figure slide, the figure must use at least this much of body height.
# Measuring a sample deck's figure slides gave 0.52-0.72. Below half, the figure becomes a supporting player.
FIG_SHARE_MIN = 0.45


def crowding(slide, where, h_in, warn):
    """How much smaller the figure got on its own slide. If small, says what pushed it down.

    "The figure is too small with text above and below, so the composition
    is off" is obvious just by looking, but that can't be left to a person
    re-measuring every time. `deckspec` already computes the layout, so
    that number is used for the verdict.
    """
    if warn is None or where != "self":
        return
    # If there's a photo below a diagram, they're measured combined: a figure slide has two figures.
    if deckspec.stacked(slide):
        h_in += deckspec.stacked_photo_in(slide)
    share = h_in / deckspec.BODY_H_IN
    if share >= FIG_SHARE_MIN:
        return
    crowd = []
    for key, name in (("lead", "lead sentence (lead)"), ("foot", "footnote (foot)"),
                      ("fine", "fine print (fine)"), ("bullets", "bullets (bullets)"),
                      ("block", "box (block)")):
        v = slide.get(key)
        if v:
            n = 1 if isinstance(v, (str, dict)) else len(v)
            crowd.append("%s %d" % (name, n))
    warn.append(
        "slide %d: the figure gets only %d%% of body height (minimum %d%%). "
        "This is a figure slide, but the figure is a supporting player: trim %s "
        "or move it to `say`. The problem isn't having text above and below at all, it's the share it takes."
        % (slide["n"], round(share * 100), round(FIG_SHARE_MIN * 100),
           " / ".join(crowd) if crowd else "the content"))


def display_scale(png, slot):
    """The shrink ratio when this figure is placed in that slot. 1.0 means no shrinkage.

    A deck gives both `max width` and `max height`, so aspect ratio is
    preserved and it shrinks to whichever is tighter.
    """
    try:
        from PIL import Image as _I
        with _I.open(png) as _im:
            w, h = _im.size
    except Exception:
        return 1.0
    # Drawn at dpi=200, so inches = pixels/200
    return min(1.0, slot[0] / max(1e-6, w / 200.0),
               slot[1] / max(1e-6, h / 200.0))


# There is one baseline, `FIG_SHARE_MIN`. Measuring one verdict, "below
#   half of body height, it's a supporting player," separately in two
#   places creates two thresholds, and whichever is looser becomes a false
#   negative. Only the diagnosis differs: is the space too tight
#   (`crowding`), or is the figure drawn too thin (`underfill`).


# Paths to offer a thin figure: naming only what that kind can actually do.
UNDERFILL_WAY = {
    "flow": u"draw the inputs/feedback loop/count/group names (`kind: pipeline`), ",
    "stack": u"write in what changes at each layer, ",
    "grid": u"add row/column names or enlarge the cells, ",
    "pipeline": (u"add one more row (`rows`) to compare two things, or draw an "
                 u"input (`feed`)/feedback loop (`loop`)/inner box line (`inner`), "),
    "strip": u"add more rows, or add a vertical axis line (`axis`)/description (`note`) per row, ",
}


def underfill(png, slot, tag, warn, kind="flow", extra_in=0.0, text_in=0.0):
    """Speaks up when a figure fails to fill its own space.

    `crowding` catches the case where space is too tight. The opposite,
    where space is plenty but the figure itself is drawn thin and leaves
    the top and bottom empty, nobody was watching for. Drawing only five
    boxes and leaving the other half blank turns a figure slide into a
    text slide with a figure-sized blank area.
    """
    if warn is None:
        return
    try:
        from PIL import Image as _I
        with _I.open(png) as _im:
            h_in = _im.size[1] / 200.0
    except Exception:
        return
    # The baseline is body height, not the slot. On a slide where text
    #   above and below narrowed the slot to 1.5 inches, this became "72% of
    #   the slot" and said nothing, while the figure was actually 41% of
    #   body height, exactly the slide the user called "the figure is too small."
    share = (h_in + extra_in) / max(1e-6, deckspec.BODY_H_IN)
    # A thin flow that followed the advice and propped itself up with
    #   `foot` still counts that text: the warning persisted even after
    #   propping it up, so the advice wasn't a real fix (a summary's
    #   one-line "premise => conclusion" flow). Only counted when the
    #   figure fails to fill its own space; a figure that filled its space
    #   but reads small because text crowds it (the slide the user called
    #   "too small") is measured on the figure alone.
    if text_in and h_in < 0.85 * slot[1]:
        share += text_in / max(1e-6, deckspec.BODY_H_IN)
    if share >= FIG_SHARE_MIN:
        return
    # A horizontally flowing `flow` belongs at full width (layouts).
    #   "Push it to one side, split into two panes" collided with that
    #   rule. For `flow`, the only advice given is to prop it up with text below.
    tail = (u"prop up the figure with one or two lines (`foot`) below it saying why that step turns out that way."
            if kind == "flow" else u"push the figure to one side and split into two panes (`left`/`right`).")
    _way = UNDERFILL_WAY.get(kind, u"")
    # The ways end in "or"; with no kind-specific way the ending starts the sentence itself
    _rest = (_way + u"or " + tail) if _way else (tail[:1].upper() + tail[1:])
    warn.append(
        u"%s: this figure uses only %d%% of body height (minimum %d%%): "
        u"the rest stays blank. This is a figure slide, meaning there's little to show: "
        u"%s Add only what's in the paper: leaving this warning in place is better than inventing what isn't there."
        % (tag, round(share * 100), round(FIG_SHARE_MIN * 100), _rest))


def shrink_note(png, slot, sizes, tag, warn):
    """When shrunk, warns and fixes the sidecar's sizes.

    The sidecar testifies that "this text is on screen at this size." If
    the drawn size is recorded but it shrinks on screen, that testimony
    becomes false, and `fitcheck` reports it as fine. That exact failure is
    what led this skill to create the sidecar in the first place.
    """
    k = display_scale(png, slot)
    if k > 0.995:
        return sizes
    if warn is not None:
        warn.append(
            "%s: placed in this space, it shrinks to %d%%: the text "
            "shrinks by the same amount and the sides go blank. Trim the figure's content or split into slides."
            % (tag, round(k * 100)))
    return [(f, round(pt * k, 2), s) for f, pt, s in sizes]


def chart_field_lines(tag, ch):
    """Fields printed as text inside a chart: sidecar lines. Lets a checker see them.

    An axis name/column subtitle/verdict weren't here before, so a checker couldn't see them.
    """
    out = []
    for lab in ("title", "ylabel", "note", "takeaway", "row_label", "col_label"):
        if ch.get(lab):
            out.append("%s\t%s\t\t%s" % (tag, lab, strip_markup(str(ch[lab]))))
    for v in (ch.get("col_notes") or []):
        out.append("%s\tcol_notes\t\t%s" % (tag, strip_markup(str(v))))
    for v in (ch.get("verdict") or {}).values():
        out.append("%s\tverdict\t\t%s" % (tag, strip_markup(str(v))))
    return out


def _slot_for(slide, where, what):
    """The slot this figure will be placed in: uses exactly the numbers `deckspec` decides.

    The slot isn't fixed. If the same slide has bullets/a footnote/a
    highlight box, it gets that much space. Otherwise the figure eats the
    whole slot and the footnote runs off screen.
    """
    pane_w = None
    owner = slide
    if where in ("left", "right"):
        lw = float((slide.get("left") or {}).get("width") or 0.5)
        pane_w = lw if where == "left" else 1.0 - lw
        owner = slide.get(where) or {}
    res = deckspec.fig_reserve(owner, where, slide)
    return deckspec.slot(what, where, pane_w, res)


def build(spec_path, out_dir, sidecar_path=None):
    meta, slides, _ = load(spec_path)
    os.makedirs(out_dir, exist_ok=True)
    made, lines, warn = [], [], []
    sizes = []                       # (file, pt, text): fitcheck reads this
    for s in slides:
        # Diagrams come first: the only way to give a slide with no table something to look at.
        for where, d in diagrams_in(s):
            if d.get("kind", "flow") not in DIAG_KINDS:
                warn.append("slide %d: diagram.kind=%r can only be %s"
                            % (s["n"], d.get("kind"), "/".join(DIAG_KINDS)))
                continue
            # `mark` is a name: writing "red" still becomes blue, then
            #   orange, in sequence. Even the doc's own example wrote
            #   `mark: red` in cell R and it drew blue. This reports it.
            _marks = set()
            for _it in (list(d.get("boxes") or []) + list(d.get("nodes") or [])
                        + [c for r in (d.get("rows") or []) if isinstance(r, dict)
                           for c in (r.get("cells") or []) + (r.get("stages") or [])]):
                if isinstance(_it, dict) and _it.get("mark"):
                    _marks.add(str(_it["mark"]).lower())
            _col = sorted(_marks & {"red", "green", "blue", "orange", "yellow", "purple",
                                    "grey", "gray", "light", "dark", "pale"})
            if _col:
                warn.append(u"slide %d: a diagram's mark %s is a name, not a color: each new "
                            u"name becomes blue, orange, gray in sequence. For bad/good use "
                            u"hit/safe (red/green); for neutral, drop mark" % (s["n"], ", ".join(_col)))
            p = diagram_path(out_dir, s["n"], where)
            _sl = _slot_for(s, where, "diagram")
            crowding(s, where, _sl[1], warn)
            words, seen = draw_diagram(d, p, _sl, warn)
            made.append(p)
            if where == "self":
                underfill(p, _sl, os.path.basename(p), warn,
                          d.get("kind", "flow"),
                          deckspec.stacked_photo_in(s) if deckspec.stacked(s) else 0.0,
                          max(0.0, deckspec.BODY_H_IN - _sl[1])
                          if d.get("kind", "flow") == "flow" and (s.get("foot") or s.get("fine"))
                          else 0.0)
            # Records the size it displays at, not the size it was drawn at
            sizes += shrink_note(p, _sl,
                                 [(os.path.basename(p), pt, txt)
                                  for pt, txt in seen],
                                 os.path.basename(p), warn)
            # Writes the text inside the figure to the sidecar. Without
            #   this, `outcheck` marks all of it "didn't arrive," because it
            #   can't read inside a PNG.
            if d.get("takeaway"):
                words.append(strip_markup(str(d["takeaway"])))
            tag = "diagram%02d" % s["n"]
            for w in words:
                lines.append("%s\tlabel\t\t%s" % (tag, w))
        for where, ch in charts_in(s):
            # `panels` reads several tables: a layout that places the
            #   same grid side by side for two subjects.
            pans = panel_tables(s, ch)
            if pans is not None:
                miss = [p.get("from", "self") if isinstance(p, dict) else p
                        for p, (_, tb) in zip(ch["panels"], pans) if not tb]
                if miss:
                    warn.append("slide %d: no table for %r in chart.panels"
                                % (s["n"], miss))
                    continue
                p = chart_path(out_dir, s["n"], where)
                seen = draw_tiles(pans, p, ch.get("title"), ch.get("note"),
                                  _slot_for(s, where, "chart"), warn,
                                  ch.get("col_notes"), ch.get("row_label"),
                                  ch.get("col_label"), ch.get("verdict"),
                                  ch.get("takeaway"), ch.get("share_rows"),
                                  blanks_said=blanks_said(s))
                made.append(p)
                sizes += [(os.path.basename(p), pt, txt) for pt, txt in seen]
                tag = "chart%02d" % s["n"]
                lines += chart_field_lines(tag, ch)
                for ptitle, tb in pans:
                    if ptitle:
                        lines.append("%s\tpanel\t\t%s"
                                     % (tag, strip_markup(str(ptitle))))
                    if (tb.get("header") or [""])[0]:
                        lines.append("%s\tcorner\t\t%s"
                                     % (tag, strip_markup(str(tb["header"][0]))))
                    for r in tb["rows"]:
                        head = strip_markup(r[0])
                        hdr = tb.get("header") or []
                        for ci, v in enumerate(r[1:], 1):
                            col = strip_markup(hdr[ci]) if ci < len(hdr) else ""
                            if strip_markup(v).strip() in LAST_CUT:
                                continue      # a clipped value hasn't arrived
                            lines.append("%s\t%s\t%s\t%s"
                                         % (tag, head, col, strip_markup(v)))
                continue
            # A table placed inside the chart comes first. `panels[].table`
            #   was being read, but this wasn't: it was silently ignored
            #   and a missing box was inserted instead.
            t = ch.get("table") or find_table(s, ch.get("from", "self"), where)
            if not t:
                warn.append("slide %d %s: no table for chart.from=%r: "
                            "`self` means wherever this chart is attached"
                            % (s["n"], where, ch.get("from", "self")))
                continue
            p = chart_path(out_dir, s["n"], where)
            kind = ch.get("kind", "heat")
            slot = _slot_for(s, where, "chart")
            crowding(s, where, slot[1], warn)
            if kind == "tiles":
                seen = draw_tiles([(None, t)], p, ch.get("title"),
                                  ch.get("note"), slot, warn,
                                  ch.get("col_notes"), ch.get("row_label"),
                                  ch.get("col_label"), ch.get("verdict"),
                                  ch.get("takeaway"), blanks_said=blanks_said(s))
            elif kind == "heat":
                seen = draw_heat(t, p, ch.get("title"), ch.get("note"),
                                 slot, warn, ch.get("takeaway"))
            elif kind == "dots":
                # A dot chart: for when values cluster in a narrow range and bars can't show the difference
                import figs_extra
                seen = figs_extra.draw_dots(t, p, slot, warn, sys.modules[__name__],
                                            ch.get("xlabel") or ch.get("ylabel"),
                                            bool(ch.get("log")), ch.get("takeaway"))
            elif kind == "lines":
                # A line chart: each row is one point [series, x, y]. A performance-vs-scale curve
                import figs_extra
                seen = figs_extra.draw_lines(t, p, slot, warn, sys.modules[__name__],
                                             ch.get("xlabel"), ch.get("ylabel"),
                                             ch.get("log") or False, ch.get("takeaway"),
                                             ch.get("callout"))
            elif kind == "bars":
                if ch.get("log"):
                    # A bar's value is its length from 0. A log axis has no
                    #   0, so length means nothing on one, so the warning
                    #   points the user to a dot chart, which states a value by position.
                    warn.append(u"slide %d: bars doesn't take a log axis: a bar's length is measured "
                                u"from 0, and a log axis has no 0. Use `kind: dots, log: true`" % s["n"])
                seen = draw_bars(t, p, ch.get("title"), ch.get("ylabel"),
                                 ch.get("note"), slot, warn,
                                 ch.get("callout"), ch.get("takeaway"),
                                 ch.get("values", True))
            else:
                warn.append("slide %d: chart.kind=%r can only be tiles/heat/bars/dots/lines"
                            % (s["n"], kind))
                continue
            made.append(p)
            sizes += [(os.path.basename(p), pt, txt) for pt, txt in seen]
            # Writes the drawn value straight to the sidecar: there's no manual-copy step.
            tag = "chart%02d" % s["n"]
            # Also writes down everything printed as text inside the
            #   figure. A title/axis name/caption ends up inside the PNG,
            #   so to a checker that reads text, it's the same as not
            #   existing. Writing only the values and skipping the title
            #   once made `outcheck` report "the title didn't arrive": that
            #   wasn't a false positive, the sidecar was incomplete.
            lines += chart_field_lines(tag, ch)
            if kind == "tiles" and (t.get("header") or [""])[0]:
                lines.append("%s\tcorner\t\t%s"
                             % (tag, strip_markup(str(t["header"][0]))))
            _cut = set(LAST_CUT)           # a value clipped at the figure's edge hasn't arrived
            for r in t["rows"]:
                head = strip_markup(r[0])
                for ci, v in enumerate(r[1:], 1):
                    col = strip_markup((t.get("header") or ["", ""])[ci]
                                       if ci < len(t.get("header") or []) else "")
                    if strip_markup(v).strip() in _cut:
                        continue
                    lines.append("%s\t%s\t%s\t%s" % (tag, head, col,
                                                     strip_markup(v)))
    if sidecar_path and lines:
        tags = {l.split("\t", 1)[0] for l in lines}
        sidecar.write(sidecar_path, tags, lines)
    # Leaves behind the size of text inside the figure. `fitcheck
    #   --figtext` reads this and counts text inside a PNG by its on-screen
    #   size too. Without this, that gap never closes.
    if sizes:
        # Also records pixel dimensions. On the PDF side, a figure cannot
        #   be found by name: what `page.get_images()` gives is a PDF
        #   resource name (`Im10`), not a filename. Pixel dimensions match
        #   exactly on both sides, so that's used instead.
        dims = {}
        for p in made:
            try:
                with Image.open(p) as im:
                    dims[os.path.basename(p)] = (im.width, im.height,
                                                 fingerprint(im))
            except Exception:                              # noqa: BLE001
                pass
        with io.open(os.path.join(out_dir, TEXTSIZE), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write("# png\tw\th\tfingerprint\tpt\ttext"
                    "  (text inside the figure. This is the size it renders at on screen)\n")
            for png, pt, txt in sizes:
                w, h, fp = dims.get(png, (0, 0, ""))
                f.write("%s\t%d\t%d\t%s\t%.2f\t%s\n"
                        % (png, w, h, fp, pt, txt.replace("\t", " ")))
    return made, lines, warn


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draws figures from the tables in slides.yaml")
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", default="figs")
    ap.add_argument("--sidecar", default=None,
                    help="TSV to write the drawn values to (a checker reads this)")
    a = ap.parse_args(argv)
    made, lines, warn = build(a.spec, a.out, a.sidecar)
    for p in made:
        print("=> %s" % p)
    for w in warn:
        print("   %s" % w)
    if a.sidecar and lines:
        print("   sidecar: %d lines -> %s" % (len(lines), a.sidecar))
    if not made:
        print("   (no slide uses chart)")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    sys.exit(main())
