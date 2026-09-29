# -*- coding: utf-8 -*-
"""Single source of truth for design values: line weight, color, spacing, corners, text tier.

Why one file: if values are scattered across every generator, consistency
becomes structurally impossible. `build_figs.py` alone once had 39 different
colors and 12 different line weights scattered through it, so slides came
out with different grays and different weights page to page. Design has to
be consistent across every page, and that isn't a matter of taste; it is a
code structure problem. The moment a generator writes a color or weight
that isn't here, it drifts apart again.

## Basis

The values are not made up. They come from the principles below, and the
sources are recorded in `references/design.md` along with a confidence
rating.

1. Lines have three tiers, each double the last (0.5 / 1.0 / 2.0pt).
   Drafting standards (ISO 128-2) use two tiers at 1:2. When adjacent
   tiers are less than 1.5x apart, they read as a mistake, not a hierarchy.
2. What encloses is thinner than what it encloses. Auto-generated tools
   draw the grouping box at the same weight as its contents, which is a
   large part of what makes something look auto-generated.
3. Hierarchy comes from size and value; category comes from hue and shape.
   In Bertin's classification, only size and value can say "more/less"
   (dissociative). Hue and shape cannot.
4. One role is a pale fill, a dark outline, and neutral text. The larger
   the area, the lower the saturation should be (Munzner ch. 10). Filling
   a box with a saturated color spends the figure's whole contrast budget
   on that box, so the text inside it and the arrow next to it compete
   with it for attention, which is why a saturated fill looks cheap.
5. Bold once per figure. "If everything is emphasized, nothing is"
   (Butterick). Sans-serif type doesn't use italics for emphasis.
6. Spacing comes only from the ruler. Fix one unit `u` and set padding :
   sibling gap : group gap = 1 : 2 : 4. When proximity alone reads as
   grouping, there's no need to draw a border.
7. One device per group. If spacing already groups it, don't also wrap it
   in a box.
8. Corner radius is a single absolute value. Sizing it as a fraction of
   the box makes a large box and a small box speak different visual
   languages, and past 1/4 of the short side it reads as a button, not a
   structure.
"""

# ──────────────────────────────────────────────────────────────────────
# Lines: three tiers. Each tier double the last.
#
# Don't put adjacent tiers less than 1.5x apart (like 0.8 and 1.0). That
# reads as inconsistency, not hierarchy. "Distinguishable, but minimally
# so" (Tufte).
HAIR = 0.5      # what encloses: grouping frames, dividers, ticks, guides
BASE = 1.0      # structure: box outlines, axes
EMPH = 2.0      # the one thing being called out

# Dash pattern: visible as broken, without being noisy
DASH = (1.4, 1.6)

# ──────────────────────────────────────────────────────────────────────
# Text: tiers by size and value, not weight.
#
# Bold once per figure. Don't turn a subtitle into "text that isn't bold";
# make it smaller and paler instead.
# `INK` is the color the deck actually renders: metropolis's `mDarkTeal`.
# Body text color is set by the theme, not chosen here, so if the figure
# and the PPTX used a different near-black, the text color would split on
# the same page.
# All three tiers exceed 4.5:1 on a white background (WCAG 2.2 text
# criterion). Measured and chosen.
INK = "#23373B"         # tier 1: names              12.5:1
INK2 = "#666666"        # tier 2: qualifiers/subtitle  5.7:1
INK3 = "#757575"        # tier 3: notes/ticks          4.6:1
FAINT = "#A8B3B9"       # not text: guides, faint arrows
SIZE2 = 0.80            # tier-2 text size (relative to tier 1)
SIZE3 = 0.70            # tier 3


# ─────────────────────────────────────────────────────────────────────
# Font: the deck and the figures use the same one.
#
# Figures were rendering in matplotlib's default (DejaVu Sans) while the
# deck rendered in `lmodern` (Latin Modern Sans). The two fonts have
# different x-heights, so the same point size doesn't look the same size:
# "figure text is smaller than body text" held true by the numbers while
# being violated on screen, on every figure on every page.
TEX_SANS = ("lmsans10-regular.otf", "lmsans10-bold.otf",
            "lmsans10-oblique.otf", "lmsans10-boldoblique.otf")
FALLBACK_FAMILY = "DejaVu Sans"
_family = None


def _find_tex_font(name):
    """Finds one OTF file in the TeX distribution. Returns None if not found."""
    import glob
    import os
    import subprocess
    try:
        p = subprocess.run(["kpsewhich", name], capture_output=True,
                           text=True, timeout=20)
        hit = (p.stdout or "").strip().splitlines()
        if hit and os.path.exists(hit[0]):
            return hit[0]
    except Exception:
        pass
    for root in ("C:" + chr(92) + "texlive",
                 "C:" + chr(92) + "Program Files" + chr(92) + "MiKTeX",
                 "/usr/share/texmf", "/usr/local/texlive",
                 os.path.expanduser("~/.texlive")):
        g = glob.glob(os.path.join(root, "**", name), recursive=True)
        if g:
            return g[0]
    return None


def font_family(note=None):
    """The font name figures should use: the same one as the deck.

    Falls back to the old default if not found, but reports it in one line
    via `note`. Silently falling back to a different font is the failure
    mode this guards against.
    """
    global _family
    if _family is not None:
        return _family
    try:
        from matplotlib import font_manager as fm
    except Exception:
        _family = FALLBACK_FAMILY
        return _family
    first, got = None, 0
    for name in TEX_SANS:
        path = _find_tex_font(name)
        if not path:
            continue
        try:
            fm.fontManager.addfont(path)
            got += 1
            first = first or path
        except Exception:
            pass
    if got and first:
        try:
            _family = fm.FontProperties(fname=first).get_name()
        except Exception:
            _family = FALLBACK_FAMILY
    else:
        _family = FALLBACK_FAMILY
        if note is not None:
            note.append(
                u"couldn't find the deck's font (Latin Modern Sans), so figures render in %s, "
                u"the same point size looks bigger than the body text. Installing the `lm` "
                u"font from a TeX distribution makes the two match." % FALLBACK_FAMILY)
    return _family

# ──────────────────────────────────────────────────────────────────────
# Color: one role spans three channels.
#
#   fill      same hue, very low saturation, very high value
#   outline   same hue, medium saturation, medium value
#   text      the outline color (small text reads better in its own color than in neutral)
#
# The hues come from Paul Tol: safe for red-green color blindness, inside
# sRGB ∩ CMYK so they survive print, and the three high-contrast hues stay
# distinct after conversion to grayscale.
# Up to three hues per figure; a fourth is more than the audience can carry.
# Values were measured in pixels and set accordingly (box #EDF2F6, tile
# #E8EDEF, faint text #6F7D86).
NEUTRAL_FILL = "#EDF2F6"   # a box with no marker
TILE_FILL = "#E8EDEF"      # a tile/heat cell with no marker
FIG_MUTE = "#6F7D86"       # faint text inside a figure
NEUTRAL_LINE = "#C3CDD4"
SURFACE = "#FFFFFF"        # the band inside a box

# One role has three tiers. The larger the area, the lower the saturation
# should be; the smaller, the higher. Using the same color at both sizes
# makes one loud and the other invisible: a color pale enough for a box,
# used in a strip's narrow cell, makes every cell in the strip look the
# same.
#
#     area  large area (stage box)             very pale
#     mark  small cell (strip cell, legend swatch)  Tol light, designed to carry black text
#     line  lines and small text                    dark
ROLES = {
    # The two roles with fixed meaning in this skill: bad / good.
    #   Significance in table values; failure/success, avoid/recommend, or
    #   the part we're pointing at in prose/figures.
    # Red and green (#C0392B / #1E8449). The Tol palette's equivalent tile
    #   comes out light pink, so these two colors stay off it.
    #   Color-blind support is handled by the second channel that
    #   `meta.colorblind` turns on.
    "hit":  ("#F6DDDF", "#E4948A", "#C0392B"),
    "safe": ("#DDEDE2", "#7FBF98", "#1E8449"),
    # Unnamed roles: two hues plus two neutrals. There is no fourth hue.
    #   Every slide carries the same set: blue, amber, and two grays.
    #   Splitting a figure's colors into four hues, with a different four
    #   on every page, makes the whole deck noisy. In a unified set, a
    #   single hue standing out carries meaning; if all four stand out,
    #   none of them do.
    "a":    ("#DBE3EF", "#77AADD", "#3B6EA5"),   # blue: first kind
    "b":    ("#F6E6CE", "#E5A04A", "#9A5B12"),   # amber: second kind
    # The small-cell fill has to be visibly different from d. #B8C6D4 was
    #   only 1.28:1 against d (#D7DEE4), so the third and fourth cells of a
    #   four-role strip looked like the same gray. Now 1.56:1, and 5.9:1
    #   against text.
    "c":    ("#E4E9EE", "#9FABB6", "#5C6B78"),   # neutral, darker side
    # The small-cell fill also has to differ from the unmarked cell
    #   (`TILE_FILL` #E8EDEF). #D7DEE4 was only 1.15:1 against it, so the
    #   fourth role's cell read as "no marker." c was darkened slightly
    #   (#A7B4C0 -> #9FABB6) and d placed between the two, giving 1.51:1
    #   against c and 1.31:1 against "no marker."
    "d":    ("#F0F3F6", "#C9D1D6", "#8A96A0"),   # neutral, paler side
    # Two more role colors are kept in reserve: when a structural diagram
    #   has several cells inside a box, blue and amber alone aren't
    #   enough. They're not in the rotation (ROLE_ORDER); they only appear
    #   when the author picks them by name.
    "e":    ("#F2EEF8", "#D8D4E4", "#7B5EA7"),   # purple
    # Gold: the first value #C9A447 was only 2.36:1 as a line, short of
    #   the non-text criterion (3:1). Same hue, lowered only in value, to
    #   the nearest value that clears 3:1 (#B38F34, 3.05:1).
    "f":    ("#F7F1DF", "#E8D8A8", "#B38F34"),
}
ROLE_ORDER = ("a", "b", "c", "d")     # rotation order when the author doesn't choose

# Series colors for bar/line figures. Red and green aren't here; those two
# are reserved for bad/good, since a second series drawn in red made even
# a non-significant bar read as a loss. Blue, orange, two neutrals. The
# second series is orange (#D4761F).
SERIES = (ROLES["a"][2], "#D4761F", ROLES["c"][2], ROLES["d"][2])

# Colors for use as text. Using a line-suitable color for text falls
# short of the WCAG text criterion (4.5:1): yellow is 4.21:1, teal 4.01:1.
# The non-text criterion is only 3:1, so those same colors are fine as
# lines, which is why there are two sets of colors for one hue. The hue is
# kept the same and only the value is lowered, so the same role doesn't
# look like a different color between figures and body text. All
# measured and chosen.
ROLE_TEXT = {
    "hit":  "#C0392B",   # 5.44:1
    # The first value for Safe (#1E8449) was 4.48:1 on #F9F9F9 and 4.19:1
    #   on the box background, short of the text criterion (4.5:1). Same
    #   hue, nearest value lowered (4.84 / 4.52).
    "safe": "#1D7E46",
    "a":    "#2F5C8A",   # blue: dark enough to use as text
    "b":    "#8A5210",   # amber
    "c":    "#4A5866",   # neutral, darker side
    "d":    "#5F6B75",   # neutral, paler side
    "e":    "#6A4F95",   # purple
    "f":    "#8A6D1E",   # gold
}
# For dark backgrounds (impact slides): saturated red/green don't read there
ROLE_TEXT_DARK_BG = {"hit": "#FF8A75", "safe": "#7DD9A0"}
HI_TEXT = "#A2570E"      # "other emphasis" 5.38:1


def text_of(name, dark_bg=False):
    """The role color for use as text. Exceeds 4.5:1 on a white background."""
    if dark_bg:
        return ROLE_TEXT_DARK_BG.get(name, "#FFFFFF")
    return ROLE_TEXT.get(name, INK)


def role(name):
    """role name -> (large-area fill, small-marker fill, line). An unknown name gets neutral."""
    return ROLES.get(name, (NEUTRAL_FILL, NEUTRAL_FILL, NEUTRAL_LINE))


def fill_of(name):
    """The fill for a large area, such as a stage box."""
    return role(name)[0]


def mark_of(name):
    """The fill for a small cell, such as a strip cell or a legend swatch. Darker, since it's narrow."""
    return role(name)[1]


def line_of(name):
    """Lines and small text."""
    return role(name)[2]


def role_map(names):
    """The role names used -> {name: (fill, outline)}. Lets the author skip choosing colors.

    `hit`/`safe` have fixed meaning, so they don't take a slot in the rotation.
    """
    # If a name is a role name itself (a-f), it gets that role directly. A
    # name assigned by rotation avoids roles already taken, so a chosen
    # name like "e" doesn't also consume a rotation slot and come out gray.
    names = [n for n in names if n]
    taken = set(n for n in names if n in ROLES)
    free = [r for r in ROLE_ORDER if r not in taken] or list(ROLE_ORDER)
    out, i = {}, 0
    for n in names:
        if n in out:
            continue
        if n in ROLES:
            out[n] = ROLES[n]
            continue
        out[n] = ROLES[free[i % len(free)]]
        i += 1
    return out


# ──────────────────────────────────────────────────────────────────────
# Corners: one absolute value. Sizing it as a fraction makes a big box
# and a small box speak different visual languages.
#
# Past 1/4 of the short side, a corner reads as a button, not a
# structure. Giving a thin strip the same radius as a box turns it into
# a pill.
RADIUS_IN = 0.030       # boxes
RADIUS_THIN_IN = 0.012  # a thin strip inside a box


def radius(short_side_in):
    """The radius to use for a shape of this height. Never exceeds 1/8 of the short side."""
    return min(RADIUS_IN, max(0.004, float(short_side_in) / 8.0))


# ──────────────────────────────────────────────────────────────────────
# Spacing: a ladder built from one unit.
#
#   padding : sibling gap : group gap = 1 : 2 : 4
#
# Once this ratio holds, grouping reads even without drawing a border
# (proximity), and a line that's never drawn never needs to be erased.
# Don't port over an 8px grid: that's a screen-pixel argument with no
# basis in a vector figure. What's left is consistency, and a single
# unit is enough for that.
GRID_ROWS = 24.0


def unit(fig_h_in):
    """This figure's spacing unit, in inches."""
    return float(fig_h_in) / GRID_ROWS


PAD, SIB, GROUP = 1.0, 2.0, 4.0       # unit multiples


def ladder(fig_h_in):
    """(padding, sibling gap, group gap) in inches."""
    u = unit(fig_h_in)
    return u * PAD, u * SIB, u * GROUP


def snap(values, u):
    """Makes near-identical coordinates identical.

    A coordinate that's off by less than one unit reads to the viewer,
    even if they can't name it, as "something is wrong." It's the most
    common trace auto-layout leaves behind.
    """
    out = []
    for v in values:
        hit = None
        for w in out:
            if abs(w - v) < u:
                hit = w
                break
        out.append(hit if hit is not None else v)
    return out


# ──────────────────────────────────────────────────────────────────────
# Text size: expressed as a fraction of the final screen height. A point
# size becomes a lie once the screen size changes.
#
# On the slide-body baseline (7.5in height), tier 1 is 3.3% ≈ 18pt, floor
# 2.5% ≈ 13.5pt. Text inside a figure almost always falls short of this;
# even hand-built decks used 6-9pt. So this skill's floor is set at 8pt,
# and that it's below the standard is stated here rather than hidden. See
# `references/design.md` for details.
SLIDE_H_IN = 7.5
TYPE_PRIMARY_FRAC = 0.033
TYPE_FLOOR_FRAC = 0.025


def slide_pt(frac, slide_h_in=SLIDE_H_IN):
    """Fraction of screen height -> pt."""
    return frac * float(slide_h_in) * 72.0
