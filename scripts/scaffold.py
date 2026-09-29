# -*- coding: utf-8 -*-
"""Paper source -> `slides.yaml` skeleton.

    python scripts/scaffold.py paper/paper.tex -o slides.yaml

This does not write the talk for you. It only builds the skeleton.
  What it extracts: title/authors, the section structure (this becomes the slide
  order), tables, each section's key numbers.
  What it leaves blank: a slide title's phrasing, `say` (what to speak), where the
  impact slides go.
  `TODO:` goes in that spot instead. While `TODO:` still appears, it is a draft.

Using the section order as the slide order as-is is deliberate: reordering it in the
  talk leaves someone who read the paper lost, and gains nothing for someone who
  didn't.

A Markdown manuscript treats `#`/`##` as sections (`--syntax plain`).
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deckspec import math_to_text, slurp, spit  # noqa: E402
import deckspec  # noqa: E402


def dq(s):
    """A YAML double-quoted string."""
    return '"%s"' % str(s).replace("\\", "\\\\").replace('"', '\\"')


def clip_caption(cap, n):
    """Clips a caption to within `n` characters, at a sentence end if there is one,
    otherwise between words. Clipping strictly by character count can cut mid-word,
    like "The task is to p...", and that would go straight onto the slide as-is."""
    cap = str(cap)
    if len(cap) <= n:
        return cap
    head = cap[:n]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", head)]
    if ends and ends[-1] >= n * 0.4:
        return head[:ends[-1]]
    cut = head.rsplit(" ", 1)[0].rstrip(",;:") if " " in head else head
    return cut + "..."


def braced(s, i):
    """When `s[i]` is `{`, gives the position of the matching `}`. -1 if there is none.

    A non-greedy regex will not do: when braces nest, as in `\\textbf{\\textminus31.5}`,
    it cuts at the first `}`, leaving a fragment behind that goes straight into the
    LaTeX as-is and kills the compile.
    """
    if i >= len(s) or s[i] != "{":
        return -1
    d = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            d += 1
        elif s[j] == "}":
            d -= 1
            if d == 0:
                return j
    return -1


def drop_cmd(s, names, keep_arg):
    """Removes `\\name{...}`. If `keep_arg`, keeps only the argument's contents (nesting-safe)."""
    out, i = [], 0
    # Without `(?![a-zA-Z])`, `text` eats the front part of `\textminus`, leaving
    #   `minus` behind as literal text. In a real paper, `-31.7` came out as `minus31.7`.
    pat = re.compile(r"\\(" + "|".join(names) + r")(?![a-zA-Z])\*?\s*")
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:m.start()])
        j = m.end()
        if j < len(s) and s[j] == "[":            # an optional argument
            k = s.find("]", j)
            j = k + 1 if k >= 0 else j
        e = braced(s, j)
        if e < 0:
            i = m.end()
            continue
        if keep_arg:
            out.append(drop_cmd(s[j + 1:e], names, keep_arg))
        i = e + 1


# Only what is commonly used in math is turned into characters. This much is enough
# for a talk skeleton.
# As Unicode: flattening to `Delta`/`^` erases the distinction a paper's own marks
#   carry († vs ‡). The builder (`build_deck.SYMBOL`) converts these characters back
#   to LaTeX.
# `\pm` matches only at a word boundary: without it, `\pmb{\alpha}` became "±bα".
MATH = [(r"\\Delta", "Δ"), (r"\\times", "×"), (r"\\pm(?![a-zA-Z])", "±"),
        (r"\\textminus", "-"), (r"\\leq", "≤"), (r"\\geq", "≥"),
        (r"\\ll", "≪"), (r"\\gg", "≫"), (r"\\approx", "≈"),
        (r"\\textdagger", "†"), (r"\\textdaggerdbl", "‡"),
        (r"\\dagger", "†"), (r"\\ddagger", "‡"),
        (r"\\%", "%"), (r"\\&", "&"), (r"\\\$", "$"), (r"\\_", "_")]


def clean(s):
    """A LaTeX fragment -> plain text. If a leftover fragment goes out as-is, the
    compile dies."""
    # The line break `\\` is turned into a space first, before anything else.
    #   Otherwise, in `cases\\Within`, the command-stripping regex sees `\Within`
    #   starting from the second backslash as a command and deletes the whole word.
    #   In a real paper's title, this erased the first two words of a line, the
    #   biggest text on screen.
    s = re.sub(r"\\\\\s*", " ", s)
    # In `\multicolumn{3}{l}{Cooling axis}`, only the third argument is text. Without
    #   stripping the first two arguments, `3lCooling axis` gets written into the
    #   skeleton.
    s = re.sub(r"\\multicolumn\s*\{[^}]*\}\s*\{[^}]*\}\s*", " ", s)
    s = re.sub(r"\\multirow\s*\{[^}]*\}\s*(\[[^\]]*\])?\s*\{[^}]*\}\s*", " ", s)
    # The width argument of `\parbox[l]{.27\linewidth}{...}`/`\makebox[..]{...}` is
    #   not text: a table header once came out as ".27 Method Category." Only the
    #   content is kept.
    s = re.sub(r"\\(parbox|minipage)\s*(\[[^\]]*\])*\s*\{[^{}]*\}", " ", s)
    s = re.sub(r"\\(makebox|framebox)\s*(\[[^\]]*\])+", " ", s)
    # A placement command is removed argument and all: `\vspace{-.2em}`'s argument
    #   otherwise leaks into the author line. A color name is not text either:
    #   `\textcolor{myred1}{+2.2\%}`'s "myred1" would be left in the cell.
    s = re.sub(r"\\(?:textcolor|colorbox)\s*(\[[^\]]*\])?\s*\{[^{}]*\}|\\color\s*\{[^{}]*\}",
               " ", s)
    # A row/cell color (`\rowcolor{gray!10}`) is removed argument and all, or "gray!10
    # 18310" is left in a cell.
    s = re.sub(r"\\(?:rowcolor|cellcolor|columncolor)\s*(\[[^\]]*\])?\s*\{[^{}]*\}", " ", s)
    # Rule/spacing commands too, argument and all: the dimensions of
    #   `\rule{0pt}{2.0ex}`/`\specialrule{1pt}{-1pt}{0pt}` would otherwise stick to a
    #   cell as "0pt2.0exSelf-Attention".
    s = re.sub(r"\\rule\s*(\[[^\]]*\])?\s*\{[^{}]*\}\s*\{[^{}]*\}", " ", s)
    s = re.sub(r"\\specialrule\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{[^{}]*\}", " ", s)
    s = re.sub(r"\\cmidrule\s*(\([^)]*\))?\s*\{[^{}]*\}", " ", s)
    s = re.sub(r"\\addlinespace\s*(\[[^\]]*\])?|\\strut\b", " ", s)
    s = drop_cmd(s, ["cite", "citep", "citet", "ref", "eqref", "autoref", "cref", "Cref",
                     "label", "footnote",
                     "vspace", "hspace", "thanks", "phantom", "hphantom", "vphantom"], False)
    # Only a reference word with its number stripped would be left in the parentheses,
    #   turning a caption into "(Sec. )". Parentheses containing only a reference
    #   word, and empty parentheses, are removed.
    s = re.sub(r"\s*\(\s*(?:see\s+)?(?:Secs?|Sections?|Figs?|Figures?|Tabs?|Tables?|Eqs?|"
               r"Equations?|Apps?|Appendix|Algs?|Algorithm)\.?\s*[~,;]?\s*(?:and\s*)?\)", "", s)
    s = re.sub(r"\s*\(\s*\)", "", s)
    # A math fragment is turned into text with the same function the PPTX and script
    #   use: `$^\dagger$` becomes †, `$10^{-4}$` becomes 10⁻⁴. This runs before
    #   stripping text commands, since doing that first erases the subscript chunk of
    #   `$\text{RoB}_\text{base}$`, giving "RoBbase".
    s = re.sub(r"\$[^$]*\$", lambda m: math_to_text(m.group(0)), s)
    s = drop_cmd(s, ["textbf", "textit", "emph", "texttt", "textrm", "mathrm",
                     "text", "mbox", "pmb", "boldsymbol", "bm"], True)
    s = re.sub(r"\\ding\s*\{\s*(\d+)\s*\}",
               lambda m: {"51": "✓", "52": "✓", "55": "✗", "56": "✗"}.get(m.group(1), ""), s)
    s = re.sub(r"\\(?:checkmark|cmark)(?![A-Za-z])", "✓", s)
    s = re.sub(r"\\xmark(?![A-Za-z])", "✗", s)
    for a, b in MATH:
        s = re.sub(a, b, s)
    s = s.replace("~", " ")
    s = re.sub(r"\^\{?([^}\s$]*)\}?", r"^\1", s)      # 10^{-4} -> 10^-4
    s = re.sub(r"_\{?([^}\s$]*)\}?", r"_\1", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", s)
    s = re.sub(r"[{}$\\]", "", s)
    # A significance asterisk is attached to the number: `\sym{***}` would otherwise
    # fall apart into "0.00113 ***".
    s = re.sub(r"(\d)\s+(\*{1,3})(?=\s|$)", r"\1\2", s)
    return re.sub(r"\s+", " ", s).strip()


APPENDIX_SKIPPED = []
APPENDIX_CUT = [None]     # where the appendix starts (manuscript character offset). None if there is none

FRONT_RE = re.compile(r"\A\s*---\s*\n(.*?)\n---\s*\n", re.S)


def front_matter(src):
    """The YAML front matter at the top of a Markdown manuscript -> dict. {} if there is
    none or it cannot be read."""
    m = FRONT_RE.match(src or "")
    if not m:
        return {}
    try:
        import yaml
        d = yaml.safe_load(m.group(1))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def front_people(front):
    """(author line, affiliation line). Supports both the JOSS form (`authors:
    [{name, affiliation}]`, `affiliations: [{name, index}]`) and a plain string
    list."""
    names, used = [], []
    for a in front.get("authors") or front.get("author") or []:
        if isinstance(a, dict):
            if a.get("name"):
                names.append(str(a["name"]))
            for i in str(a.get("affiliation") or "").replace(" ", "").split(","):
                if i and i not in used:
                    used.append(i)
        elif a:
            names.append(str(a))
    affs = {}
    for f in front.get("affiliations") or []:
        if isinstance(f, dict) and f.get("name"):
            affs[str(f.get("index", len(affs) + 1))] = str(f["name"])
    inst = [affs[i] for i in used if i in affs] or list(affs.values())
    return ", ".join(names), "; ".join(inst)


def figures_in(body, syntax):
    """The figures in a section's body: [(path, caption)]. Markdown `![caption](path)`,
    a LaTeX figure environment."""
    out = []
    if syntax != "latex":
        for m in re.finditer(r"!\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)[^)]*\)", body):
            cap = re.sub(r"\\label\{[^}]*\}", "", m.group(1))
            out.append((m.group(2), clean(cap)))
        return out
    # `wrapfigure` (a figure wedged next to body text) and `SCfigure` are also
    #   figures. Looking only for `figure` dropped the method diagram, the paper's
    #   Figure 1, from the skeleton. An algorithm box standing outside a figure (a
    #   lone `\begin{algorithm}`) is caught here too, not only ones inside figures.
    _outside = re.sub(r"\\begin\{(figure\*?|wrapfigure|SCfigure\*?)\}.*?\\end\{\1\}", " ", body, flags=re.S)
    for m in re.finditer(r"\\begin\{algorithm\*?\}(.*?)\\end\{algorithm\*?\}", _outside, re.S):
        out.append(("<algorithm>", _caption(m.group(1))))
    for m in re.finditer(r"\\begin\{(figure\*?|wrapfigure|SCfigure\*?)\}(.*?)\\end\{\1\}",
                         body, re.S):
        blk = m.group(2)
        # A sub-figure with its own caption (subfigure/minipage) is a figure in its
        #   own right. Taking only the first figure would drop three of Figure 1,
        #   2, 3a-c held in one environment from the skeleton. Several panels with
        #   no caption are left as one figure.
        subs = []
        for sm in re.finditer(r"\\begin\{(subfigure|minipage)\}(.*?)\\end\{\1\}", blk, re.S):
            sp = [_gpath(p) for p in
                  re.findall(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", sm.group(2))]
            sc = _caption(sm.group(2))
            if sp and sc:
                subs.append((sp[0], sc))
        rest = re.sub(r"\\begin\{(subfigure|minipage)\}.*?\\end\{\1\}", "", blk, flags=re.S)
        cap = _caption(rest)
        if len(subs) >= 2:
            out += [(p, ("%s — %s" % (cap, c)) if cap else c) for p, c in subs]
            continue
        _raw_paths = re.findall(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", blk)
        paths = [_gpath(p) for p in _raw_paths]
        cap = cap or _caption(blk)
        # A figure with no image file: a graph drawn with pgfplots/TikZ, or an
        #   algorithm box. Missing from the list, there would be no way to know it
        #   needed redrawing or spelling out in words. The kind is noted instead of
        #   a file name.
        if not paths:
            if re.search(r"\\begin\{algorithm", blk):
                out.append(("<algorithm>", cap or _caption(blk)))
            elif re.search(r"\\begin\{(tikzpicture|axis|semilogxaxis|loglogaxis)\}|\\addplot", blk):
                out.append(("<plot>", cap))
            continue
        if paths:
            out.append((paths[0], cap))
            FIG_LABELS[paths[0]] = re.findall(r"\\label\{([^}]+)\}", blk)
            # Several panels under one caption: the rest of the panel names are left
            # in the skeleton, since dropping them silently means they can't be
            # found later.
            FIG_PANELS[paths[0]] = paths[1:]
            # A figure the paper itself cropped (`trim=l b r t, clip`) needs the same
            #   crop here, or the cropped-off header comes back in the deck.
            _op = re.search(r"\\includegraphics\s*\[([^\]]*)\]\s*\{" + re.escape(_raw_paths[0]) + r"\}", blk)
            if _op and re.search(r"\bclip\b", _op.group(1)):
                _tm = re.search(r"trim\s*=\s*\{?\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", _op.group(1))
                if _tm:
                    FIG_TRIM[paths[0]] = tuple(float(x) for x in _tm.groups())
    return out


def _gpath(p):
    """Strips the quotes from `\\includegraphics{"images/A,_B_"}`, a grffile-style
    wrap around a file name containing spaces or commas. Carried over as-is, it would
    leave a stray quote at the end of the path and lose the extension."""
    p = str(p).strip()
    if len(p) >= 2 and p[0] == p[-1] == '"':
        p = p[1:-1].strip()
    return p


FIG_PANELS = {}      # first panel's path -> the same figure's remaining panel paths
FIG_LABELS = {}      # path -> that figure's \label(s), used to find which section points at it
FIG_TRIM = {}        # path -> (left, bottom, right, top) bp, the paper's own `trim=..., clip`
FIG_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".eps")


def find_figure(path, base):
    """The figure path the paper wrote -> the actual file. LaTeX often writes it
    without an extension (`Figures/ModalNet-21`); carried over as-is, the build would
    say "Figure not found" while ModalNet-21.png sat right there."""
    cands = [path] if os.path.splitext(path)[1] else [path + e for e in FIG_EXT]
    for c in cands:
        f = os.path.join(base or ".", c)
        if os.path.isfile(f):
            return f
    return None


def trim_to_crop(src, trim):
    """`trim=l b r t` (bp) -> `figure.crop` fractions {x, y, w, h}. None if the figure's
    native size cannot be read."""
    try:
        if src.lower().endswith((".pdf", ".eps")):
            try:
                import pymupdf as fitz
            except ImportError:      # PyMuPDF before 1.24.3 has only the old import name
                import fitz
            _doc = fitz.open(src[:-4] + ".pdf" if src.lower().endswith(".eps") else src)
            try:
                r = _doc[0].rect
            finally:
                _doc.close()
            W, H = r.width, r.height
        else:
            from PIL import Image
            with Image.open(src) as im:
                dpi = (im.info.get("dpi") or (72, 72))[0] or 72
                W, H = im.width * 72.0 / dpi, im.height * 72.0 / dpi
        l, b, r_, t = trim
        w, h = (W - l - r_) / W, (H - b - t) / H
        if not (0 < w <= 1 and 0 < h <= 1):
            return None
        return {"x": round(l / W, 3), "y": round(t / H, 3), "w": round(w, 3), "h": round(h, 3)}
    except Exception:
        return None


def _caption(blk):
    """A block's first `\\caption{...}` text, or empty text if there is none."""
    cm = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", blk)
    if not cm:
        return ""
    e = braced(blk, cm.end() - 1)
    return clean(blk[cm.end():e]) if e > 0 else ""


def sections(src, syntax):
    """A list of (level, title, body). Level 1 = section."""
    if syntax == "latex":
        # A title is read by brace balance, not `[^}]*`, which cuts at the `}`
        #   inside `\ref{...}` and would leak "Proof of Lemma lem: neyman" into a
        #   title.
        heads = []
        for m in re.finditer(r"\\(section|subsection)\*?\s*(?:\[[^\]]*\])?\s*\{", src):
            e = braced(src, m.end() - 1)
            if e > 0:
                heads.append((m.group(1), src[m.end():e], m.start(), e + 1))
        # The appendix (after `\appendix`, or starting from a section beginning with
        #   "Appendix") is not a slide, or twelve proof sections would become
        #   slides. Only their names are kept, as a comment.
        cut = len(src) + 1
        ma = re.search(r"\\appendix\b|\\begin\{appendix\}", src)
        if ma:
            cut = ma.start()
        for kind, title, st, _ in heads:
            if kind == "section" and re.match(r"\s*(appendix|supplement)", clean(title), re.I):
                cut = min(cut, st)
                break
        APPENDIX_SKIPPED[:] = [clean(t) for k, t, st, _ in heads if st >= cut and k == "section"]
        APPENDIX_CUT[0] = cut if cut <= len(src) else None
        heads = [h for h in heads if h[2] < cut]
        lvl = {"section": 1, "subsection": 2}
        out = []
        for i, (kind, title, st, en) in enumerate(heads):
            end = heads[i + 1][2] if i + 1 < len(heads) else min(len(src), cut)
            out.append((lvl[kind], clean(title), src[en:end], st))
        # A figure before the first section (a header figure before `\maketitle`) is
        #   also a figure. Being outside every section, it would otherwise be
        #   dropped entirely, including the paper's Figure 1. Only figure
        #   environments are attached before the first section; numbers in the
        #   abstract are not.
        if out:
            _bd = re.search(r"\\begin\{document\}", src)
            pre = src[_bd.end() if _bd else 0:heads[0][2]]
            _pf = "".join(m.group(0) for m in re.finditer(
                r"\\begin\{(figure\*?|wrapfigure)\}.*?\\end\{\1\}", pre, re.S))
            if _pf:
                l0, t0, b0, s0 = out[0]
                out[0] = (l0, t0, _pf + "\n" + b0, s0)
        return out
    else:
        pat = re.compile(r"^(#{1,3})\s+(.+)$", re.M)
        lvl = None
    ms = list(pat.finditer(src))
    shift = 0
    if (not lvl and len(ms) > 1 and len(ms[0].group(1)) == 1
            and all(len(m.group(1)) > 1 for m in ms[1:])):
        # If there is only one `#` at the very front, that is the paper's title, not
        #   a section. Treating it as one would turn the title into a slide of its
        #   own, with every remaining `##` bundled under it as a subsection, as in a
        #   PDF-converted manuscript.
        ms, shift = ms[1:], 1
    out = []
    for i, m in enumerate(ms):
        L = lvl[m.group(1)] if lvl else len(m.group(1)) - shift
        end = ms[i + 1].start() if i + 1 < len(ms) else len(src)
        out.append((L, clean(m.group(2)), src[m.end():end], m.start()))
    return out


def colspec(src, i):
    """Reads the column spec after `\\begin{tabular}` by brace balance.

    Reading it as `[^}]*` cuts `llrc@{\\hskip 5pt}rr` at `llrc@{\\hskip 5pt`. That
      counts 5 columns while the row actually has 6 cells, and LaTeX dies with
      "Extra alignment tab has been changed to \\cr." On top of that, the leftover
      `r}` leaks into the table body.
    """
    e = braced(src, i)
    if e < 0:
        return None, i
    spec = src[i + 1:e]
    # dcolumn `D{.}{.}{-1}` is one column (decimal-aligned). Because of its argument
    #   braces, `*{8}{D{.}{.}{-1}}` would otherwise fail to expand, collapsing an
    #   eight-column regression table into one column. It is swapped for `r` before
    #   expanding.
    spec = re.sub(r"D\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{[^{}]*\}", "r", spec)
    # `*{3}{c}` is three columns: expand it.
    for _ in range(4):
        spec = re.sub(r"\*\{(\d+)\}\{([^{}]*)\}",
                      lambda m: m.group(2) * int(m.group(1)), spec)
    # The inside of `@{...}` is not a column, it is filler between cells, so it is
    #   not counted. It is walked by brace balance, since when it nests, as in
    #   `@{\extracolsep{\fill}}`, the inner word's l/c/r would otherwise be counted
    #   as columns, turning a two-column table into six.
    bare, k = "", 0
    while k < len(spec):
        if spec[k] in "@!<>" and k + 1 < len(spec) and spec[k + 1] == "{":
            e2 = braced(spec, k + 1)
            if e2 > 0:
                k = e2 + 1
                continue
        bare += spec[k]
        k += 1
    # The argument of `p{3cm}`/`x{42}` is not a column. Without stripping it, the c/m
    #   in `3cm` gets counted as columns.
    bare = re.sub(r"\{[^{}]*\}", "", bare)
    # A column letter defined by `\newcolumntype{x}` is also a column. Not knowing
    #   this drops that column entirely, and a results column has vanished from
    #   another paper's key table this way.
    custom = set(re.findall(r"\\newcolumntype\{(\w)\}", CUSTOM_SRC[0] or ""))
    out = []
    for ch in bare:
        if ch in "lrc":
            out.append(ch)
        elif ch in "pmbX":
            out.append("p" if ch == "p" else "l")
        elif ch == "S":
            out.append("r")
        elif ch in custom:
            out.append("c")
    return "".join(out), e + 1


# so `colspec` can see the whole manuscript's `\newcolumntype`, filled in by `build`
CUSTOM_SRC = [""]


def _fig_spans(src):
    """The (start, end) of figure environments in the manuscript."""
    return [(m.start(), m.end()) for m in re.finditer(
        r"\\begin\{(figure\*?|wrapfigure|SCfigure\*?)\}.*?\\end\{\1\}", src, re.S)]


_STACK_TAB = re.compile(r"\\begin\{tabular\}\s*(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}"
                        r"((?:(?!\\begin\{tabular|\\end\{tabular|&).)*?)\\end\{tabular\}", re.S)
_STACK_CMD = re.compile(r"\\(?:shortstack|makecell|Centerstack|stackanchor)\s*(?:\[[^\]]*\])?\s*\{")


def flatten_stacks(src):
    """A structure that only stacks lines inside a cell -> a one-line text. The
    length stays the same (padded with spaces), so `pos` does not drift.

    Reading `\\shortstack{a\\\\b}`'s `\\\\` as a row end would split four tables into
      several rows, and a header's
      `\\begin{tabular}[c]{@{}l@{}}Our Results\\\\ (rllab)\\end{tabular}` would come
      out as "tabular[c]@l@Our Results," failing to read the column spec. An inner
      tabular with no `&` is not a table, it is a line stack."""
    def _pad(m, body):
        t = re.sub(r"\\\\(?:\[[^\]]*\])?", " ", body)
        t = re.sub(r"\s+", " ", t).strip()
        return t + " " * max(0, len(m) - len(t))
    for _ in range(4):
        new = _STACK_TAB.sub(lambda m: _pad(m.group(0), m.group(1)), src)
        if new == src:
            break
        src = new
    out, i = [], 0
    for m in _STACK_CMD.finditer(src):
        if m.start() < i:
            continue
        e = braced(src, m.end() - 1)
        if e < 0:
            continue
        out.append(src[i:m.start()])
        out.append(_pad(src[m.start():e + 1], src[m.end():e]))
        i = e + 1
    out.append(src[i:])
    return "".join(out)


def tables(src, pos=None):
    """A LaTeX tabular -> (col spec, header, rows). If it cannot be read, skips it
    and says so.

    Given a list for `pos`, puts each table read's position in the manuscript into
    it, so a table lands in its own section.
    """
    # `\tabularnewline` is also a row end (every table LyX exports uses it). Looking
    #   only for `\\` would discard four tables as "fewer than 2 rows." It is
    #   swapped for something the same length so `pos` does not drift.
    src = re.sub(r"\\tabularnewline(?![A-Za-z])",
                 lambda m: "\\\\" + " " * (len(m.group(0)) - 2), src)
    src = flatten_stacks(src)
    got, skipped = [], []
    # `tabular*`/`tabularx` are also tables, with one extra width argument
    #   `{\textwidth}` attached. Looking only for `tabular` would drop four of a
    #   journal paper's tables entirely, including its main results table.
    for m in re.finditer(r"\\begin\{(tabular\*?|tabularx)\}", src):
        env = m.group(1)
        j = m.end()
        while j < len(src) and src[j] in " \n\t":
            j += 1
        if env != "tabular" and j < len(src) and src[j] == "{":
            e0 = braced(src, j)                    # width argument
            j = e0 + 1 if e0 > 0 else j
            while j < len(src) and src[j] in " \n\t":
                j += 1
        align, body_start = colspec(src, j)
        if not align:
            # names which table, since the same line printed 65 times would give no
            # way to tell which one to look at
            skipped.append("could not read the column spec (manuscript line %d)" % (src.count("\n", 0, m.start()) + 1))
            continue
        end = src.find("\\end{%s}" % env, body_start)
        if end < 0:
            skipped.append("no end{%s}" % env)
            continue
        # A tabular used to lay out figures side by side is not a table: a "Table 1"
        #   whose header was a figure file name (`1337f06a.eps`) would otherwise
        #   come out as one.
        if "\\includegraphics" in src[body_start:end]:
            skipped.append("a figure-layout tabular")
            continue
        # A tabular inside a figure is part of the figure (an example passage, an
        #   editing-cost diagram), not a table slide of its own. Read as one, it can
        #   produce a row like "tabularc c c c c Wittenberg." A table's caption lives
        #   in a table environment.
        if any(a <= m.start() < b for a, b in _fig_spans(src)):
            skipped.append("a tabular inside a figure")
            continue
        ncol = len(align)
        rows, ragged = [], 0
        # If there are several rows above the first rule (`\hline`/`\midrule`), all
        #   of them are header. A journal table can stack its header three rows deep
        #   ("FDR (%)" / "(nominal level" / "q=20%)"); treating only the first row
        #   as header would turn the rest into body rows. They are joined together
        #   cell by cell.
        _body = src[body_start:end]
        _top = re.match(r"\s*\\(?:toprule|hline)\b", _body)
        _b0 = _top.end() if _top else 0
        _rule = re.search(r"\\(?:midrule|hline)\b", _body[_b0:])
        head_n = 0
        if _rule:
            _hp = _body[_b0:_b0 + _rule.start()]
            head_n = len([x for x in re.split(r"\\\\", _hp) if "&" in x])
        for line in re.split(r"\\\\", src[body_start:end]):
            # A row-spacing `\\ [0.08cm]` right after a line break is not the next
            #   row's text, or "[0.08cm]" leaks into a row's name.
            line = re.sub(r"^\s*\[[^\]]{0,20}\]", "", line)
            line = re.sub(r"\\(toprule|midrule|bottomrule|hline|cmidrule|cline)\b"
                          r"(\([^)]*\))?(\{[^}]*\})?", "", line)
            # A cell is split only on an unescaped `&`, since "Model \& Method"
            #   would otherwise become two cells, shifting every column after it by
            #   one.
            parts = re.split(r"(?<!\\)&", line)
            if len(parts) > 1 and not "".join(clean(c) for c in parts).strip():
                continue          # every cell is empty (the trailing `\\`), not a row
            if len(parts) == 1:
                # A divider row spanning a single cell, like
                #   `\multicolumn{5}{l}{\textit{Cooling axis}}`. Discarding it for
                #   having no `&` erases the table's group name entirely, and whoever
                #   receives the skeleton doesn't even know such a row existed. It is
                #   put in the first cell, with the rest left empty.
                lab = clean(line)
                if lab:
                    rows.append([lab] + [""] * (ncol - 1))
                continue
            # `\multicolumn{9}{c}{...}` is nine cells. Counting it as one cell throws
            #   off the columns the moment it joins a two-row header, as in
            #   "# Trainable MNLI." The content goes in the first cell, the rest
            #   left empty.
            cells = []
            for c in parts:
                mc = re.match(r"\s*\\multicolumn\s*\{\s*(\d+)\s*\}", c)
                # A citation inside a cell leaves a placeholder, or removing it
                #   produces "described in ."
                cc = clean(re.sub(r"\\cite[tp]?\*?\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", r"[\1]", c))
                cells.append(cc)
                # A value spanning several cells is the value for every cell it
                #   spans. Putting a cost shared by two columns
                #   (`\multicolumn{2}{c}{3.3*10^18}`) only in the first cell would
                #   make the second cell read as "not reported." A name (a header
                #   group) goes in the first cell only.
                _val = bool(re.fullmatch(r"[-+−]?[\d.,]+\s*(?:[·×x]\s*10\S*)?\s*[%]?", cc.strip())) if cc.strip() else False
                # A header row's (the first `head_n` rows) group name is attached to
                # every column it spans; if "BLEU EN-DE" is next to a plain "EN-FR,"
                # there is no way to tell if that's BLEU or cost.
                _span = _val or (head_n > 1 and len(rows) < head_n)
                cells += [cc if _span else ""] * ((int(mc.group(1)) - 1) if mc else 0)
            if len(cells) != ncol:
                # Sending out a row with the wrong cell count as-is kills the
                #   compile. It is a row merged by multicolumn or similar, so it is
                #   fit by trimming or padding.
                ragged += 1
                cells = (cells + [""] * ncol)[:ncol]
            rows.append(cells)
        # If the rows in the header's spot are name plus number, it is not a header
        #   but a condition row: three rows of "Batch Size & 32 & 16 & 1" joined
        #   cell by cell would become "32 512 0.5M." It is left as a row instead.
        _num = re.compile(r"[-+−]?\d[\d.,]*\s*[%KMBGkx×]?$")
        _cond = head_n > 1 and all(
            r[0] and sum(bool(_num.match(c)) for c in r[1:] if c) * 2 >= max(1, len([c for c in r[1:] if c]))
            for r in rows[:head_n])
        header = None
        if _cond:
            pass
        elif head_n > 1 and len(rows) > head_n:
            header = [" ".join(x for x in col if x).strip() for col in zip(*rows[:head_n])]
            rows = rows[head_n:]
        elif rows:
            header, rows = rows[0], rows[1:]
        if header is not None and len(rows) >= 1 or header is None and len(rows) >= 2:
            got.append((align, header, rows, ragged))
            if pos is not None:
                pos.append(m.start())
        else:
            skipped.append("fewer than 2 rows")
    return got, skipped


def numbers(body, limit=None):
    # A multiplier or a whole-number percentage is also a number (`40x`, `70%`).
    # A placement command's argument or dimension is not a number: without this,
    #   `\vspace*{1.5pt}`'s 1.5 gets written down as that section's number.
    body = re.sub(r"\\(?:v|h)(?:space|skip)\*?\s*\{[^{}]*\}|\\(?:setlength|addtolength|rule|"
                  r"raisebox|kern|resizebox|scalebox|includegraphics)\*?\s*(?:\[[^\]]*\])?"
                  r"(?:\s*\{[^{}]*\})*", " ", body)
    body = re.sub(r"-?\d*\.?\d+\s*(?:pt|cm|mm|em|ex|in|bp)(?![A-Za-z])", " ", body)
    vals = deckspec.result_numbers(re.sub(r"\\textminus", "", body))
    seen = []
    for v in vals:
        if v not in seen:
            seen.append(v)
    return seen[:limit] if limit else seen


def sniff(path, src):
    """What format the manuscript is, figured out from the extension and its content.

    The default used to be `latex`, decided without asking. Running it on a `.md`
      file exactly as documented printed "0 sections -> 0 slides, 0 tables" and
      exited 0 as "success." `--syntax plain` only existed in this file's docstring,
      not in SKILL.md. A default should not depend on a flag the person using it
      doesn't know about.
    """
    # a PDF is read by `deckspec.read_paper` as Markdown with title lines (#) restored
    if re.search(r"\.(md|markdown|txt|rst|pdf)$", path, re.I):
        return "plain"
    if re.search(r"\.tex$", path, re.I):
        return "latex"
    return "latex" if "\\begin{document}" in src or "\\section{" in src else "plain"


def md_tables(src, pos=None):
    """A Markdown pipe table -> (col spec, header, rows, ragged row count).

    `tables()` only looks for `\\begin{tabular}`, so a Markdown manuscript always had
      0 tables. But section 1 promises that the tables are already carried over. If
      that promise is false, whoever receives it has to copy the whole table over by
      hand, exactly the work this skill exists to remove.
    """
    out, rows, header = [], [], None
    off, start = 0, 0
    for ln in src.splitlines() + [""]:
        here, off = off, off + len(ln) + 1
        s = ln.strip()
        is_row = s.startswith("|") and s.count("|") >= 2
        if is_row:
            cells = [clean(c) for c in s.strip("|").split("|")]
            if re.fullmatch(r"[\s:|-]+", s):        # a |---|---| divider line
                continue
            if header is None:
                header = cells
                start = here
            else:
                rows.append(cells)
            continue
        if header is not None:
            if rows:
                w = len(header)
                ragged = sum(1 for r in rows if len(r) != w)
                fixed = [(r + [""] * w)[:w] for r in rows]
                out.append(("l" + "r" * (w - 1), header, fixed, ragged))
                if pos is not None:
                    pos.append(start)
            header, rows = None, []
    return out, []


# A section that gets no slide in the talk. "Acknowledgment" once showed up as a
#   slide in the skeleton.
BACK_MATTER = re.compile(r"^\s*(acknowledge?ments?|funding|references|bibliography|"
                         r"appendix|appendices|supplementary)\b", re.I)


def build(paper, out_path, syntax="latex", max_slides=None):
    # Follows `\input` and expands argument-free macros. Without this, a multi-file
    #   paper comes out as only "Section 1," and `\System{}` comes out blank.
    src = deckspec.read_paper(paper)
    if syntax == "latex":
        # A comment is not manuscript text. Leaving it in lets a comment line like
        #   `% SPP-net` into a table, and an entirely commented-out table can become
        #   a slide.
        src = re.sub(r"(?<!\\)%.*", "", src)
        # A bibliography environment is not a section. A `thebibliography` with no
        #   section title, tacked onto the end of the conclusion, can get merged
        #   into the conclusion section, producing "numbers in this section: 21 44
        #   51" (conference edition numbers). It doesn't get caught by
        #   `BACK_MATTER`, which filters by title, so the whole environment is
        #   stripped instead.
        src = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", " ", src, flags=re.S)
    CUSTOM_SRC[0] = src
    title = ""
    # Title/author are read by brace balance. `(.+?)\}` cuts at the first `}`,
    #   stopping inside `\vspace{-.2em}` and leaking `-.2em` into the author line.
    def _arg(cmd):
        m_ = re.search(r"\\%s\s*(\[[^\]]*\])?\s*\{" % cmd, src)
        if not m_:
            return None
        e_ = braced(src, m_.end() - 1)
        return src[m_.end():e_] if e_ > 0 else None
    t_ = _arg("title") if syntax == "latex" else None
    # A Markdown manuscript's YAML front matter (JOSS/pandoc) is where the title,
    #   author, and affiliation live. Not reading it makes the title come out as the
    #   first section's name, "Summary," and leaves the author as TODO.
    front = front_matter(src) if syntax != "latex" else {}
    if front:
        src = FRONT_RE.sub("", src, count=1)
        CUSTOM_SRC[0] = src
    if t_ is not None:
        title = clean(t_)
    elif front.get("title"):
        title = clean(str(front["title"]))
    else:
        m = re.search(r"^#\s+(.+)$", src, re.M)
        if m:
            title = clean(m.group(1))
    author, institute = "", ""
    if front:
        author, institute = front_people(front)
    a_ = _arg("author") if syntax == "latex" else None
    if a_ is not None:
        # Some formats (journal classes) have several `\author{}` calls. Reading only
        #   the first one can leave 3 of 7 authors out. All of them are collected and
        #   joined by newline.
        _all = []
        for m_ in re.finditer(r"\\author\s*(\[[^\]]*\])?\s*\{", src):
            e_ = braced(src, m_.end() - 1)
            if e_ > 0:
                _all.append(src[m_.end():e_])
        if len(_all) > 1:
            a_ = "\\\\".join(_all)
    if a_ is not None:
        # A footnote (`\thanks{...}`) and its marker are not part of the author
        # line, so they are stripped first.
        a_ = re.sub(r"\\footnotemark\s*(\[[^\]]*\])?", " ", drop_cmd(a_, ["thanks"], False))
        # An email can be written in `\texttt{...}` spanning several lines. A line
        #   like `{edwardhu, yeshe,` has no `@`, so it would read as a name, and a
        #   version line like `(Version 2)` would also read as a name.
        a_ = drop_cmd(a_, ["texttt", "url", "email", "href"], False)
        a_ = re.sub(r"(^|\\\\)\s*\([^()]*\)\s*(?=\\\\|$)", r"\1", a_.strip())
    if a_ is not None and re.search(r"\\(And|AND)\b", a_):
        # The ICLR/NeurIPS format: each author's "name \\ affiliation" block is
        #   split by `\And`. Reading it line by line would mix the name and
        #   affiliation on one line.
        names_, insts = [], []
        for blk in re.split(r"\\(?:And|AND)\b", a_):
            bits = [clean(x).strip(" ,") for x in re.split(r"\\\\", blk)]
            bits = [b for b in bits if b and "@" not in b]
            if not bits:
                continue
            names_.append(bits[0])
            for b in bits[1:2]:
                if b not in insts:
                    insts.append(b)
        author, institute = ", ".join(names_), "; ".join(insts)
    elif a_ is not None and "IEEEauthorblockN" in a_:
        # The IEEE format: the name is `\IEEEauthorblockN{...}`, the affiliation is
        #   the first lines of `\IEEEauthorblockA{...}`. Splitting line by line
        #   would attach the first affiliation line to the author.
        def _blocks(tag):
            out_, i_ = [], 0
            while True:
                k_ = a_.find("\\" + tag, i_)
                if k_ < 0:
                    return out_
                j_ = a_.find("{", k_)
                e_ = braced(a_, j_) if j_ >= 0 else -1
                if e_ < 0:
                    return out_
                out_.append(a_[j_ + 1:e_])
                i_ = e_ + 1
        names = ", ".join(clean(re.sub(r"\\(and|qquad|quad)(?![a-zA-Z])", ",", b))
                          for b in _blocks("IEEEauthorblockN"))
        author = re.sub(r"\s*,\s*(,\s*)*", ", ", names).strip(" ,")
        insts = []
        for b in _blocks("IEEEauthorblockA"):
            for ln in [clean(x) for x in re.split(r"\\\\", b)][:2]:
                if ln and "@" not in ln and ln not in insts:
                    insts.append(ln)
        institute = "; ".join(insts)
    elif a_ is not None:
        # Splits whether each line is a name or an affiliation. Treating "first line
        #   = name" would mix the second-line author into the affiliation for a
        #   paper whose names spanned two lines, and leave an affiliation number
        #   (`$^{1,2}$`) as "^1, 2." An affiliation line starts with a number or
        #   contains an institution word.
        _mark = r"\$\s*\^\s*\{?[^${}]*\}?\s*\$|\\textsuperscript\s*\{[^{}]*\}"
        _inst = re.compile(r"\b(Universit|Institut|School|College|Laborator|Lab\b|Research|"
                           r"Department|Dept|Center|Centre|Inc\b|Corp|Company|Academy|"
                           r"Faculty|Hospital|Google|Microsoft|Meta|AWS|Amazon|NVIDIA|IBM)",
                           re.I)
        pieces = [x for x in re.split(r"\\\\|\n\s*\n", a_) if clean(x).strip()]
        names_, insts = [], []
        for x in pieces:
            bare = clean(re.sub(_mark, " ", x))
            if not bare or "@" in bare:
                continue
            # An address line is neither a name nor an institution: "New York, NY
            #   10011, USA" would otherwise end up in the author field. A name has
            #   no zip code (a number of 3+ digits) and no country name.
            if re.search(r"\d{3,}", bare) or re.search(
                    r"\b(USA|U\.S\.A\.|UK|United\s+(States|Kingdom)|China|Canada|Germany|France|"
                    r"Japan|Korea|Switzerland|Israel|India|Italy|Spain|Netherlands|Australia|"
                    r"Singapore|Sweden|Austria|Belgium|Denmark|Finland|Norway|Brazil)\b\s*[.,]?\s*$",
                    bare):
                continue
            starts_marked = re.match(r"\s*(\\[a-z]+\s*\{)?\s*(" + _mark + ")", x)
            if starts_marked or (_inst.search(bare) and not re.search(_mark, x)):
                # one institution per number: `$^2$ AWS, $^3$ Shanghai ...`
                for part in re.split(_mark, x):
                    c = clean(part).strip(" ,;")
                    # Several institutions joined by commas ("Carnegie Mellon
                    #   University , Stanford University") are split when each piece
                    #   contains an institution word, or they stick together in one
                    #   cell as "A , B."
                    _bits = [b_.strip() for b_ in c.split(",")]
                    _top = re.compile(r"\b(Universit|Institut|College|Academy|Hospital|Inc\b|Corp|Company|"
                                      r"Google|Microsoft|Meta|AWS|Amazon|NVIDIA|IBM)", re.I)
                    # something like "Cell Lab, North University", joining a lab and a
                    # university, is one affiliation
                    for c in (_bits if len(_bits) > 1 and all(_top.search(b_) for b_ in _bits) else [c]):
                        if c and "@" not in c and c not in insts:
                            insts.append(c)
            else:
                # `\&`/`&` also separates names: "Lipton \enskip \& Steinhardt"
                #   would otherwise stay as "Lipton, & Steinhardt."
                names_.append(re.sub(r"\\(qquad|quad|and|AND)(?![a-zA-Z])|\\&|(?<!\\)&", ",",
                                     re.sub(_mark, " ", x)))
        author = re.sub(r"\s*,\s*(,\s*)*", ", ", clean(", ".join(names_))).strip(" ,")
        institute = "; ".join(insts)

    # The authblk format: affiliation lives separately in `\affil[...]{...}`. Not
    #   reading it leaves the affiliation empty.
    if syntax == "latex" and not institute:
        _aff = []
        for m_ in re.finditer(r"\\affil\s*(\[[^\]]*\])?\s*\{", src):
            e_ = braced(src, m_.end() - 1)
            if e_ > 0:
                c_ = clean(drop_cmd(src[m_.end():e_], ["texttt", "url", "email", "href"], False))
                c_ = c_.strip(" ,;")
                if c_ and "@" not in c_ and c_ not in _aff:
                    _aff.append(c_)
        institute = "; ".join(_aff)
    # The ICML format: `\icmlauthor{name}{key}`/`\icmlaffiliation{key}{affiliation}`.
    #   With no `\author`, both author and affiliation would come out empty.
    if syntax == "latex" and not author and "\\icmlauthor" in src:
        _names, _keys = [], []
        for m_ in re.finditer(r"\\icmlauthor\s*\{([^{}]*)\}\s*\{([^{}]*)\}", src):
            if clean(m_.group(1)) not in _names:
                _names.append(clean(m_.group(1)))
            for k_ in m_.group(2).split(","):
                if k_.strip() and k_.strip() not in _keys:
                    _keys.append(k_.strip())
        _affs = {}
        for m_ in re.finditer(r"\\icmlaffiliation\s*\{([^{}]*)\}\s*\{", src):
            e_ = braced(src, m_.end() - 1)
            if e_ > 0:
                _affs[m_.group(1).strip()] = clean(src[m_.end():e_]).strip(" ,;")
        author = ", ".join(_names)
        if not institute:
            institute = "; ".join(_affs[k_] for k_ in _keys if _affs.get(k_))
    # Sections/tables come only from the body. A preamble
    #   `\newcommand\Section[2]{\section{#2}}` can otherwise become a slide titled
    #   "#2," and a `\definecolor` value can come out as that section's number. It is
    #   padded with spaces of the same length so positions stay correct.
    _bd = re.search(r"\\begin\{document\}", src) if syntax == "latex" else None
    body_src = (" " * _bd.end() + src[_bd.end():]) if _bd else src
    secs = sections(body_src, syntax)
    tpos = []
    tabs, skipped = (tables(body_src, tpos) if syntax == "latex"
                     else md_tables(src, tpos))

    # TODO text is written in ASCII. Someone will always try building the skeleton
    #   as-is, and pdflatex cannot handle non-Latin characters. Korean TODO text has
    #   set off over 100 Unicode errors this way on a real paper.
    L = ["# Single source read by build_deck.py, build_pptx.py and build_script.py.",
         "# Generated by scaffold.py: this is a SKELETON.",
         "# While `TODO:` appears anywhere, it is still a draft.",
         "",
         "meta:",
         "  title: %s" % dq(title or "TODO: talk title"),
         "  subtitle: %s" % dq("TODO: subtitle (delete if unused)"),
         "  author: %s" % dq(author or "TODO: speaker"),
         ("  institute: [%s]" % ", ".join(dq(x) for x in institute.split("; "))
          if institute and "; " in institute
          else "  institute: %s" % dq(institute or "TODO: affiliation (delete if unused)")),
         "  venue: %s" % dq("TODO: venue and date"),
         "  # The one sentence the talk exists to say. prose_audit checks the",
         "  # impact slides against it.",
         "  thesis: %s" % dq("TODO: the one claim, in the paper's own words"),
         "  # The paper itself. The checkers read its words and numbers from here.",
         "  paper: %s" % dq(os.path.relpath(paper, os.path.dirname(os.path.abspath(out_path)))
                            .replace(os.sep, "/")),
         "  wpm: 135",
         '  aspect: "16:9"',
         "  figdir: figs",
         "",
         "slides:",
         "  - kind: title",
         ""]

    # A table goes right after the section it appeared in. Collecting them all at
    #   the end contradicts "keep the section order," and whoever receives it has to
    #   move each table back into place by hand.
    starts = [s[3] for s in secs] + [len(src) + 1]
    own = {}
    _cut0 = APPENDIX_CUT[0] if syntax == "latex" else None
    for k, p in enumerate(tpos):
        if _cut0 is not None and p >= _cut0:
            continue                    # an appendix table goes out as a backup slide at the very end
        si = max([q for q in range(len(secs)) if starts[q] <= p] or [-1])
        own.setdefault(si, []).append(k)

    emitted = set()

    def emit_table(i, backup=False):
        emitted.add(i)
        align, header, rows, ragged = tabs[i]
        # A column empty in every row is dropped. The manuscript's column spec can
        #   declare more columns than were used (six columns in a `*{8}`), leaving
        #   two empty columns in the skeleton. The first column (row names) is kept
        #   even if empty.
        _w = max([len(header or [])] + [len(r) for r in rows] or [0])
        _keep = [j for j in range(_w)
                 if j == 0 or any(str(r[j]).strip() for r in ([header] if header else []) + rows
                                  if j < len(r))]
        if len(_keep) < _w:
            header = [header[j] for j in _keep if j < len(header)] if header else header
            rows = [[r[j] for j in _keep if j < len(r)] for r in rows]
            align = "".join(align[j] for j in _keep if j < len(align)) if align else align
            # If the mismatched cell count was only because of declaring more
            # columns than used (for example 3 columns in an lllll), there's
            # nothing to warn about.
            ragged = 0
        L.append("  - kind: table")
        L.append("    title: %s" % dq("TODO(the point of table %d)" % (i + 1)))
        if backup:
            # An appendix table is a backup slide. Skipping the section but still
            #   emitting the table as a main-deck slide would turn eleven appendix
            #   tables, including a training-setup table, into main-deck table
            #   slides. Keep only what's needed and delete the rest.
            L.append("    backup: true    # from the appendix: keep only if asked, else delete")
        if ragged:
            L.append("    # %d row(s) had a different cell count (multicolumn?) and were "
                     "padded or trimmed, so check them" % ragged)
        L.append("    table:")
        _w = len(header) if header else len(rows[0])
        # A deck's column spec is only l/c/r. `p{2cm}` drops its width, leaving only
        #   `p`, and pdflatex would stop with "Missing number." A paragraph column
        #   (p/m/b/X) is carried over as left-aligned.
        align = re.sub(r"[pmbX]", "l", align or "")
        align = re.sub(r"[^lcr]", "", align)
        L.append("      align: %s" % dq(align or "l" + "r" * (_w - 1)))
        if header:
            L.append("      header: [%s]" % ", ".join(dq(h) for h in header))
        L.append("      rows:")
        for r in rows:
            L.append("        - [%s]" % ", ".join(dq(c) for c in r))
        L.append("    note: %s" % dq("TODO: do not read the table, point at one pair"))
        L.append("    say:")
        L.append("      - %s" % dq("TODO: name the cells they should look at"))
        L.append("    pause: 4")
        L.append("")

    for k in own.get(-1, []):          # a table that appeared before the first section
        emit_table(k)
    n = 0
    parent = ""
    for si, (lvl, head, body, _start) in enumerate(secs):
        if max_slides and n >= max_slides:
            break
        # Acknowledgments/references/appendix get no slide in the talk.
        if BACK_MATTER.search(head):
            continue
        prose = re.sub(r"\\(begin|end)\{[^}]*\}|\\label\{[^}]*\}|%[^\n]*", "", body)
        if lvl == 1:
            parent = ""
        # A parent section with no body text of its own, going straight into a
        #   subsection, is not a slide. Only its name is prefixed onto the
        #   subsection's title.
        nxt = secs[si + 1][0] if si + 1 < len(secs) else 0
        if not clean(prose) and nxt > lvl and si not in own:
            parent = head
            continue
        n += 1
        nums = numbers(body)
        L.append("  - kind: content")
        L.append("    title: %s" % dq("TODO(say it, don't label it): "
                                      # not prefixed when a subsection has the same
                                      #   title as its parent, as in "Analysis ... /
                                      #   Analysis ..."
                                      + (parent + " / " if parent and lvl > 1 and parent != head
                                         else "")
                                      + head))
        L.append("    bullets:")
        L.append("      - %s" % dq("TODO: the one line to leave on screen"))
        for c in range(0, len(nums), 10):
            L.append("    # numbers in this section: %s" % " ".join(nums[c:c + 10]))
        # A deeper section (`\subsubsection`/`###`) does not get its own slide. A
        #   survey paper can put twenty methods inside one, so their names are noted
        #   here and a person does the choosing instead of everything getting
        #   crushed onto one slide.
        _subs = ([clean(x) for x in re.findall(r"\\subsubsection\*?\s*\{([^{}]*)\}", body)]
                 if syntax == "latex" else re.findall(r"^####+\s+(.+)$", body, re.M))
        if _subs:
            L.append("    # parts in this section (%d): %s" % (len(_subs), "; ".join(_subs[:30])))
        L.append("    note: %s" % dq("TODO: stage and tone note (never on screen)"))
        L.append("    say:")
        L.append("      - %s" % dq("TODO: what you will say. Do not repeat the title: "
                                   "say where to look, why it happens, what follows."))
        L.append("    pause: 2")
        L.append("")
        for k in own.get(si, []):
            emit_table(k)
        # A section's figures also become a slide skeleton. Ignoring figures would
        #   mean a paper whose results were all figures gets not a single figure
        #   slide. Only directions are written here, leaving the decision of what to
        #   do to a person.
        for path, cap in figures_in(body, syntax):
            if path in ("<algorithm>", "<plot>"):
                # no file, so it is left only as a comment, with directions on what to do
                L.append("  # %s in the paper: %s" % (
                    "Algorithm box" if path == "<algorithm>" else "Plot drawn with pgfplots/TikZ",
                    (cap or "(no caption)")[:100]))
                if path == "<algorithm>":
                    L.append("  #   No image to paste. Put its steps in `steps:` (numbered, one line each) and the")
                    L.append("  #   loss or update it applies in `formula:` on the same slide.")
                else:
                    L.append("  #   No image file. Redraw it as a `chart` from its numbers: look for `\\addplot table`,")
                    L.append("  #   a `.csv` next to the paper, or the table in the appendix that the plot is drawn from.")
                L.append("")
                continue
            # A figure's code sits wherever is convenient for typesetting. Slotting
            #   its slide there can put it ahead of the section that explains it,
            #   and a method section pointing ahead at a results figure is common.
            #   It is not moved automatically; the section that cites it is noted
            #   instead, so it can be moved to where it's explained.
            _cites = [h_ for (_l, h_, b_, _s) in secs if any(
                re.search(r"\\(?:ref|cref|Cref|autoref)\{[^}]*" + re.escape(lab) + r"[^}]*\}", b_)
                for lab in FIG_LABELS.get(path, []))]
            if _cites and _cites != [head]:
                L.append("  # cited in: %s, move this slide to where the figure is explained"
                         % " / ".join(_cites))
            L.append("  - kind: figure")
            L.append("    title: %s" % dq("TODO(the point of this figure)"))
            L.append("    figure:")
            _found = find_figure(path, os.path.dirname(os.path.abspath(paper)))
            L.append("      path: %s    # copy it into figdir"
                     % dq(os.path.basename(_found or path)))
            _crop = trim_to_crop(_found, FIG_TRIM[path]) if (_found and path in FIG_TRIM) else None
            if _crop:
                L.append("      crop: {x: %s, y: %s, w: %s, h: %s}    # the paper's own trim/clip"
                         % (_crop["x"], _crop["y"], _crop["w"], _crop["h"]))
            if cap:
                L.append("      caption: %s" % dq(clip_caption(cap, 110)))
            _more = FIG_PANELS.get(path) or []
            if _more:
                L.append("    # This figure has %d more panel(s) under the same caption: %s"
                         % (len(_more), ", ".join(os.path.basename(x) for x in _more)))
                L.append("    #   One panel per slide, or side by side (left/right) if they compare.")
            L.append("    # The paper's figure. Numbers printed in the text? Redraw it (chart).")
            L.append("    # Only in the plot? One panel (figure.crop) + figure.highlight on where to look.")
            L.append("    say:")
            L.append("      - %s" % dq("TODO: where to look first, and what it shows"))
            L.append("")
    # a table that got cut off (--max-slides) or sat further back is not lost either
    _cut = APPENDIX_CUT[0] if syntax == "latex" else None
    for k in range(len(tabs)):
        if k not in emitted:
            emit_table(k, backup=_cut is not None and k < len(tpos) and tpos[k] >= _cut)

    L += ["  # Add an impact slide at each turning point. Three or four in a whole talk.",
          "  # - kind: standout",
          "  #   big:                     # a list sets two values against each other",
          '  #     - {value: "-12.3", label: "anode", note: "under CC-CV", mark: hit}',
          '  #     - {value: "-45.6", label: "cathode", note: "under pulse", mark: hit}',
          '  #   gap: "same part"         # the claim, between them',
          '  #   bullets: ["Same conditions. Opposite result."]',
          '  #   say: ["Put the number up, wait three seconds, then speak."]',
          "  #   pause: 3",
          ""]
    spit(out_path, "\n".join(L))
    return len(secs), len(tabs), n, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description="paper source -> slides.yaml skeleton")
    ap.add_argument("paper")
    ap.add_argument("-o", "--out", default="slides.yaml")
    ap.add_argument("--syntax", choices=["latex", "plain"], default=None,
                    help="if not given, figured out from the extension and content. "
                         "Hard-coding the default to latex meant a .md manuscript "
                         "silently produced an empty skeleton")
    ap.add_argument("--max-slides", type=int, default=None)
    a = ap.parse_args(argv)
    syn = a.syntax or sniff(a.paper, deckspec.read_paper(a.paper))
    nsec, ntab, n, skipped = build(a.paper, a.out, syn, a.max_slides)
    print("=> %s  (%d section(s) -> %d slide(s), %d table(s), syntax=%s%s)"
          % (a.out, nsec, n, ntab, syn, "" if a.syntax else " (inferred)"))
    for s in skipped:
        print("   skipped table: %s" % s)
    if APPENDIX_SKIPPED:
        print("   %d appendix section(s) were not made into slides (add them as backup slides if "
              "needed): %s"
              % (len(APPENDIX_SKIPPED), "; ".join(APPENDIX_SKIPPED[:6])
                 + (" ..." if len(APPENDIX_SKIPPED) > 6 else "")))

    # Does not call it "success" when nothing could be extracted. It used to print
    #   "0 sections -> 0 slides, 0 tables" and exit 0 saying "this is a skeleton."
    #   `deckcheck` already refuses the same kind of mistake (misconfigured syntax);
    #   only one side was guarded.
    if not nsec and not ntab:
        print()
        print("   Nothing could be extracted from the manuscript. This is not a "
              "skeleton, it is an empty file.")
        print("     - is the syntax right? It was read as %s" % syn)
        print("     - LaTeX needs \\section{...}, Markdown needs `#`/`##`")
        print("     - a report written only in nested bullets has no sections. In that "
              "case, give up on the skeleton and")
        print("       write `slides.yaml` by hand instead, using `deckspec.py --keys` as "
              "a reference.")
        return 1
    if not ntab:
        print("   Not a single table could be read. If the manuscript has tables, "
              "check the syntax.")
    print("   This is a skeleton. Fill in every `TODO:`, then run "
          "build_deck/build_pptx/build_script.")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    sys.exit(main())
