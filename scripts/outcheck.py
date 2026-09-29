# -*- coding: utf-8 -*-
"""Did what the spec wrote actually arrive in the output.

    python scripts/outcheck.py slides.yaml --deck out/talk.pdf --pptx out/talk.pptx --script out/script.md

Why this check exists: it was not built to fix a single bug. Several known defects
  turned out to be the same accident:

    (1) `lead` is in the `.tex` but not in the PDF (beamer eats it as the frame subtitle)
    (2) `chart`/`foot`/a pane's `block`/list `text` are missing from the PPTX
    (3) a table's divider row is in the paper but not in the skeleton

  Each of these is text silently disappearing between stages, and each one compiled
  with zero LaTeX errors and a passing checker. `deckcheck` reads the `.tex`, so it
  cannot catch case (1). Section F only compares a set of decimal values, so it
  cannot catch case (2).

  So this reads the text back out of the output and cross-checks it against the
  spec. It is the only check that looks at text after rendering, so any future
  accident of the same kind is caught here too.

Limit: it only looks at text. A broken layout is not caught; that has to be checked
  by eye.
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckspec
from deckspec import load, slurp, plain  # noqa: E402

# For each output, must this text arrive there. What must not go there is noted here.
#   note  : speaker notes — never on screen, only in the script/PPTX notes
#   say/ko: spoken words — only in the script
WHERE = {
    "title": ("deck", "pptx"), "lead": ("deck", "pptx"), "formula": ("deck", "pptx"),
    "big": ("deck", "pptx"), "bullets": ("deck", "pptx"),
    "foot": ("deck", "pptx"), "fine": ("deck", "pptx"),
    "flow": ("deck", "pptx"), "table": ("deck", "pptx"),
    "chart": ("deck", "pptx"), "block": ("deck", "pptx"),
    "head": ("deck", "pptx"), "text": ("deck", "pptx"),
    "grid": ("deck", "pptx"), "figure": ("deck", "pptx"),
    "note": ("script",), "say": ("script",), "ko": ("script",),
    "ask": ("script",),
}


def frags(slide):
    """(which key it came from, the text) — every fragment that must reach the screen or script."""
    out = []

    def add(key, v):
        if not v:
            return
        if isinstance(v, str):
            out.append((key, v))
        else:
            for x in v:
                if x:
                    out.append((key, x))

    add("title", slide.get("title"))
    add("lead", slide.get("lead"))
    add("formula", slide.get("formula"))
    # If `big` is a list, each piece is on-screen text. Passing it whole makes
    #   the check look for a Python dict inside the PDF and produces permanent
    #   false positives that have to be explained away every time. A false
    #   positive hides a real omission.
    for _p in deckspec.big_parts(slide.get("big")):
        out.append(("big", _p))
    add("bullets", slide.get("bullets"))
    add("foot", slide.get("foot"))
    add("fine", slide.get("fine"))
    add("flow", slide.get("flow"))
    add("note", slide.get("note"))
    add("say", slide.get("say"))
    add("ko", slide.get("ko"))
    # `ask: [{q, a}]` is two fragments: the question and the answer. Passing the
    #   mapping whole makes it look for a Python repr in the script, and every
    #   question comes out "missing".
    for _a in (slide.get("ask") or []):
        if isinstance(_a, dict):
            add("ask", [_a.get("q"), _a.get("a")])
        else:
            add("ask", _a)
    b = slide.get("block") or {}
    add("block", [b.get("title"), b.get("text")])
    def _hdr(t, owner):
        # For a table drawn as a figure, only `tiles` draws the first header cell
        #   (the name of the row-label column) in the corner. A line chart's "dataset"
        #   cell, which is never drawn, would otherwise be counted as "did not arrive".
        h = list(t.get("header") or [])
        ch = (owner or {}).get("chart") or {}
        if ch and ch.get("from", "self") == "self" and not ch.get("table") \
                and ch.get("kind", "heat") != "tiles" and not ch.get("panels"):
            h = h[1:]
        return h
    for t in (slide.get("table"),):
        if t:
            add("table", [c for r in t["rows"] for c in r] +
                _hdr(t, slide) + [t.get("note")])
    # Looks at `parts` expanded. If it is not expanded, the text inside the block
    #   drops out of the check entirely, and if it then disappears from the
    #   screen, nobody notices.
    for _side, p in deckspec.panes(slide):
        add("head", p.get("head"))
        add("text", p.get("text"))
        add("bullets", p.get("bullets"))
        pb = p.get("block") or {}
        add("block", [pb.get("title"), pb.get("text")])
        if p.get("table"):
            t = p["table"]
            add("table", [c for r in t["rows"] for c in r] +
                _hdr(t, p) + [t.get("note")])
        if p.get("chart"):
            add("chart", [p["chart"].get("caption"), p["chart"].get("title")])
        add("grid", _grid_text(p.get("figure")))
        # A figure's caption inside a pane is also on-screen text. Not collecting it
        #   would let a caption missing from the PPTX go unnoticed.
        add("figure", [(p.get("figure") or {}).get("caption")])
    add("grid", _grid_text(slide.get("figure")))
    add("figure", [(slide.get("figure") or {}).get("caption")])
    return out


def _grid_text(f):
    """What an image grid prints on screen as text: column/row names and cell captions.

    An image file name is not text, but a grid's column names are printed on screen,
      so if one goes missing it has disappeared. Because this is text, not a
      picture, it can be read back from the output without a sidecar.
    """
    g = (f or {}).get("grid") or {}
    return [x for x in (list(g.get("cols") or []) + list(g.get("rows") or [])
                        + list(g.get("caption") or [])) if x]


# Superscripts and subscripts are folded back to plain digits. Otherwise `p<10⁻⁴`
#   shrinks to `p 10` on the spec side but to `p 10 4` on the typeset PDF side, and
#   a perfectly fine fragment gets flagged as "vanished". A checker's false
#   positive hides a real omission.
# Scripts are unfolded to plain characters. The table is the single one in
#   deckspec, so if more super/subscripts are added, this follows along.
import deckspec as _ds  # noqa: E402
_FLAT = {ord(v): k for k, v in list(_ds._SUP.items()) + list(_ds._SUB.items())}


CJK = re.compile(r"[가-힣぀-ヿ一-鿿]")


def norm(s):
    """Normalization for comparison: strips markup, math and case, and collapses whitespace.

    **Hangul spacing.** XeLaTeX (kotex) typesets the spacing between Hangul
      syllables as a glyph-less glue, so it looks properly spaced on screen even
      though the PDF's text layer comes out run together (a Hangul phrase like "what
      did we build" comes out as "whatdidwebuild"), so `arrived` compares a
      whitespace-stripped copy of both sides (`despace`). Comparing without knowing
      this makes perfectly fine fragments get flagged as "did not arrive" in bulk: in a
      Korean deck, 22 of 44 were this false positive, and they hid the 2 real ones
      underneath.
    """
    s = plain(s).translate(_FLAT)
    s = re.sub(r"[^0-9A-Za-z가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def despace(s):
    """A version with whitespace stripped entirely. It only makes sense if applied
    identically to both sides: stripping only one side creates a new false
    positive where an ASCII fragment does not match the Korean body."""
    return re.sub(r"\s+", "", s)


def read_pdf(path):
    try:
        try:
            import pymupdf as fitz
        except ImportError:      # PyMuPDF before 1.24.3 has only the old import name
            import fitz
    except ImportError:
        return None
    d = fitz.open(path)
    t = "\n".join(p.get_text() for p in d)
    d.close()
    return t


def read_pptx(path):
    try:
        from pptx import Presentation
    except ImportError:
        return None
    out = []
    for sl in Presentation(path).slides:
        for sh in sl.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                for r in sh.table.rows:
                    for c in r.cells:
                        out.append(c.text)
        # Speaker notes are not read here. Since the script (`say`) goes into
        #   the notes, text missing from the screen could be marked "arrived" just
        #   because it is in the notes. `note` is checked against the script instead.
    # PPTX uses the minus sign (U+2212) before numbers; treat it as the same
    #   character as the spec's `-`
    return "\n".join(out).replace(u"\u2212", "-")


_MATHISH = re.compile(u"[̀-ͯͰ-Ͽ√∑∏∫$\\\\^_%s]"
                      % "".join(sorted(set(_ds._SUP.values()) | set(_ds._SUB.values()))))


def arrived(frag, body, flat=None):
    """Did the fragment arrive. For long text, checking only the first half is
    enough, because of line wraps and folding.

    `flat` is the body with whitespace stripped. XeLaTeX (kotex) typesets the
      spacing between Hangul syllables as glyph-less glue, so the screen looks fine
      while the PDF's text layer comes out run together. So it is checked once
      more with whitespace stripped identically from both sides. Stripping only
      one side creates a new false positive.
    """
    n = norm(frag)
    if not n:
        return True
    if n in body:
        return True
    if flat is not None and despace(n) and despace(n) in flat:
        return True
    # A fragment containing math comes out reordered in the PDF's text layer: a
    #   parenthesis after a radical, or a stacked subscript (β₁²), lands somewhere
    #   else, and text that printed just fine would get flagged "did not arrive".
    #   Such a fragment is checked by whether every word longer than
    #   three letters is present. A pure formula with no words is not checked at all.
    if _MATHISH.search(frag or ""):
        words = [x for x in n.split() if len(x) >= 3 and x.isalpha()]
        return all(x in body for x in words)
    w = n.split()
    if len(w) >= 6:                      # long sentences are checked by their first 6 words
        head = " ".join(w[:6])
        if head in body:
            return True
        return flat is not None and despace(head) in flat
    return False


# Text that must never appear in the output: this skill's own markup.
# One chunk counts as one hit. Counting the opening and closing marks
#   separately turns a single `**shape**` into four hits, and once the list gets
#   long nobody reads it (a false positive of that kind once hid two real ones
#   among 22). An unmatched mark must not be missed either, so the single-mark
#   patterns come last.
LEAKS = (
    # An asterisk after a number (`0.128**`) is a significance mark, not leaked
    # markup, so it must not be counted as one.
    (re.compile(r"(?<![\d*])\*\*[^\n]*?\*\*|(?<![\d*])\*\*"), u"**\u2026** (bold)"),
    (re.compile(r"(?<![\w*])\*[^*\n]{1,60}\*(?![\w*])"),
     u"*\u2026* (italic)"),
    (re.compile(r"<(hit|safe|hi)>.*?</\1>|</?(?:hit|safe|hi)>"),
     u"<hit>/<safe>/<hi>"),
)


def markup_leaks(bodies):
    """Finds the markup itself left behind in the output.

    This is the opposite of "the text disappeared": it arrived unconverted.
      Both happen at the render stage, and both compile with zero LaTeX errors.
    """
    out = []
    for name in sorted(bodies):
        # The script is Markdown. There, `**bold**` is formatting, not leaked
        #   markup: the only thing that counts as a leak is this skill's own
        #   angle-bracket markup.
        pats = LEAKS[2:] if name == "script" else LEAKS
        for pat, what in pats:
            for m in pat.finditer(bodies[name]):
                lo = max(0, m.start() - 30)
                out.append((name, what,
                            bodies[name][lo:m.end() + 30].replace("\n", " ")))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Did what the spec wrote actually arrive in the output")
    ap.add_argument("spec")
    ap.add_argument("--deck", default=None, help="the rendered deck PDF (not .tex)")
    ap.add_argument("--pptx", default=None)
    ap.add_argument("--script", default=None)
    ap.add_argument("--sidecar", default=None,
                    help="TSV listing the text printed inside figures. Without it, "
                         "every title/number inside a PNG is flagged \"did not "
                         "arrive\": a text-reading checker cannot see inside a picture")
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args(argv)
    if not (a.deck or a.pptx or a.script):
        ap.error("one of --deck / --pptx / --script is required")

    meta, slides, _ = load(a.spec)
    bodies, raws = {}, {}
    # Text inside a figure is pixels. What the generator wrote to the sidecar is
    #   checked together with the on-screen text - the same PNG goes into both
    #   the deck and the PPTX, so it is added to both.
    side = norm(slurp(a.sidecar)) if a.sidecar and os.path.isfile(a.sidecar) else ""
    if a.deck:
        t = read_pdf(a.deck)
        if t is None:
            print("   No PyMuPDF, so the deck cannot be read - pip install pymupdf")
        else:
            bodies["deck"] = norm(t) + " " + side
            raws["deck"] = t
    if a.pptx:
        t = read_pptx(a.pptx)
        if t is None:
            print("   No python-pptx, so the PPTX cannot be read")
        else:
            bodies["pptx"] = norm(t) + " " + side
            raws["pptx"] = t
    if a.script:
        _sc = slurp(a.script)
        bodies["script"] = norm(_sc)
        raws["script"] = _sc

    print("=" * 78)
    print("spec -> output arrival check  (%s)" % ", ".join(sorted(bodies)))
    print("=" * 78)
    # Build the whitespace-stripped version up front - rebuilding it per fragment is slow
    flats = {k: despace(v) for k, v in bodies.items()}
    lost = {k: [] for k in bodies}
    total = 0
    for s in slides:
        for key, v in frags(s):
            for out in WHERE.get(key, ()):
                if out not in bodies:
                    continue
                total += 1
                if not arrived(v, bodies[out], flats[out]):
                    lost[out].append((s["n"], key, plain(v)[:70]))

    bad = 0
    for out in sorted(bodies):
        miss = lost[out]
        bad += len(miss)
        print("   %s %-7s missing fragments: %d"
              % ("! " if miss else "  ", out, len(miss)))
        for n, key, v in miss[:a.show]:
            print("        slide %2d %-8s %s" % (n, key, v))
        if len(miss) > a.show:
            print("        ... and %d more" % (len(miss) - a.show))

    # Also checks what must not arrive: this skill's own markup.
    # Looks at the text before normalization. `norm` goes through
    #   `strip_markup`, which removes the very markup being searched for,
    #   so searching there would always give zero.
    leaks = markup_leaks(raws)
    if leaks:
        print()
        print("   markup printed as literal text %d time(s): asterisks/angle "
              "brackets are visible on screen"
              % len(leaks))
        for name, what, ctx in leaks[:a.show]:
            print(u"        %-6s %-16s …%s…" % (name, what, ctx.strip()))
        if len(leaks) > a.show:
            print("        ... and %d more" % (len(leaks) - a.show))
        print("     if even one path that unwraps markup is missing, it shows up here: "
              "markup spanning two pieces and a branch that bypasses `fmt` were the culprits before.")
    print()
    print("   checked %d fragment(s) - missing %d - markup leaked %d time(s)"
          % (total, bad, len(leaks)))
    if bad:
        print("   Text disappeared during rendering. Find which stage ate it.")
        print("     This is not a LaTeX error, and deckcheck cannot see it either, "
              "because it is present in the source.")
        if not a.sidecar and any(k == "chart" for m in lost.values() for _, k, _ in m):
            print("     A `chart` fragment was flagged but `--sidecar` was not given. "
                  "Text inside a figure is pixels and cannot be read:")
            print("       give the TSV the generator left behind via `--sidecar`.")
    elif not leaks:
        print("   No markup leaked, and everything written in the spec arrived.")
    return 1 if (bad or leaks) else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    sys.exit(main())
