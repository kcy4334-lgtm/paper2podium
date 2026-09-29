# -*- coding: utf-8 -*-
"""Measures a deck's design density, and compares it against a reference deck if one
is given.

    python scripts/refcheck.py slides.yaml
    python scripts/refcheck.py slides.yaml --ref other/talk.tex

Why this is needed: `deckcheck` checks whether the numbers are right. But even when
every number is right, if the result is a bullet deck, nobody watches it. That happened
in this project: every checker printed 0, and only after a person looked at it did the
feedback "the whole composition is just too different" come out.

What the person did by hand at that point was something countable: how many slides used
bold text in the example deck, how many slides used two columns, how many had a figure.
So this check does the same thing, before a person has to point it out.

Measures (all as a ratio against slide count)
  . figures . tables . two-column layout . standout slides
  . slides that use emphasis (bold/semantic color)
  . slides with only bullets: if this is high, that alone means "shabby"
  . bullets per slide, words per bullet line

Run with no reference and it compares against a baseline. The baseline is a value taken
from one human-made conference deck.
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckspec
from deckspec import load, slurp, strip_markup, plain  # noqa: E402

# This is not a rule. It is only a value measured from one hand-made conference deck,
# and that deck is an experimental-paper talk full of tables and figures. A concept talk
# or a demo talk will naturally look different. Do not read this as a rule like "figures
# must be 50%."
#
# Exactly one part of it is actually useful: the ratio of slides with only bullets. If
# that's high, it means "nothing was made to show" in any field. Treat the rest as a
# reference only.
#
# Override it with `--baseline figure=0.2,table=0.4` if you have your own standard.
#
# Every value here must be one actually measured from that deck. Bullets-per-slide and
# bullet length used to be typed in by hand (2.6 / 11 words), but the measured values
# were 1.0 / 18.8 words. Tuned to that wrong value, SKILL.md instructed "move a bullet
# down to `say` once it passes twelve words," and decks built that way turned into two
# or three short tags per slide. The reference deck instead has one line per slide that
# carries its claim and its evidence together. That is the difference between a list and
# an argument, and it is visible at a glance.
BASELINE = {
    "figure": 0.50, "table": 0.30, "columns": 0.35, "standout": 0.20,
    "emphasis": 0.90, "bullets_only": 0.10, "question": 0.15,
}
# Values measured together from the same deck (bullets per slide, words per bullet)
BASELINE_BULLETS = (1.0, 18.8)
# Items counted as a failure when run with no reference. The rest only show numbers.
# The emphasis ratio is not counted as a failure: forcing bold text into footnotes only
# to hit one example deck's 90% has happened before. A low emphasis ratio only flags
# which slide fails to say where to look.
STRICT = ("bullets_only",)
LABEL = {
    "figure": "slides with a figure", "table": "slides with a table",
    "columns": "two-column slides", "standout": "standout slides",
    "emphasis": "slides that use emphasis (bold/semantic color)",
    "bullets_only": "slides with only bullets",
    "question": "slides whose title is a question",
}


def shown_table(s):
    """Does this slide's slide-level `table` actually appear on screen?

    For a slide that is `kind: figure` + `chart`, the `table` is data the chart reads
    from, not the screen. Counting it as on-screen breaks two things at once: it
    false-positives "table and figure show the same value twice," and it inflates the
    table ratio.
    """
    return bool(s.get("table")) and not _eaten(s)


def _eaten(owner):
    """Does the chart in this same spot consume this spot's `table`?

    This is the same rule the deck builder uses: regardless of kind, if the chart is
    `from: self`, the table is data. Applying that only when `kind: figure` would count
    a consumed table on a two-column slide as on-screen, and flag it as "same value
    shown twice."
    """
    ch = owner.get("chart")
    return bool(ch) and ch.get("from", "self") == "self" and not ch.get("table")


def tables_in(s):
    """Every table on a slide that actually appears on screen, as (where, table)."""
    out = []
    if shown_table(s):
        out.append(("self", s["table"]))
    for side in ("left", "right"):
        p = s.get(side) or {}
        if p.get("table") and not _eaten(p):
            out.append((side, p["table"]))
    return out


def _panel_tables(s):
    """Tables inside `chart.panels`. These are missed unless collected explicitly."""
    out = []
    for where in ("self", "left", "right"):
        owner = s if where == "self" else (s.get(where) or {})
        ch = owner.get("chart") or {}
        for p in (ch.get("panels") or []):
            if isinstance(p, dict) and p.get("table"):
                out.append((where, p["table"]))
    return out


def charts_in(s):
    out = []
    if s.get("chart"):
        out.append(("self", s["chart"]))
    for side in ("left", "right"):
        p = s.get(side) or {}
        if p.get("chart"):
            out.append((side, p["chart"]))
    return out


def same_data_twice(s):
    """Does a table and a figure show the same value twice?

    `chart: {from: left}` draws a figure from that pane's table. But if that table is
    also put on screen, the same numbers appear in two sets on one slide. It looks like
    a two-column layout, but it's duplication, not a comparison: a useful two-column
    layout has left and right showing two different things (two subjects, or a table
    and its evidence).

    This can happen on several slides at once, and the design-density ratio alone would
    read it as a healthy use of two-column layout.
    """
    have = {w for w, _ in tables_in(s)}
    for where, ch in charts_in(s):
        src = ch.get("from", "self")
        if src in have:
            return True
    return False


SPLIT = re.compile(r"\s*[,/·]\s*| — | - ")


def merged_column(t):
    """Are two attributes crammed into one cell?

    Writing something like `Front end, dry cell` turns six rows into a flat list.
    Splitting it into two columns (or two panels) makes which side drives what visible
    from the layout alone.

    If the front part of the first cell repeats across several rows, that's actually one
    column in disguise.
    """
    firsts = [strip_markup(str(r[0])) for r in t["rows"] if r and str(r[0]).strip()]
    if len(firsts) < 4:
        return None
    heads = {}
    for f in firsts:
        parts = SPLIT.split(f, 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            heads.setdefault(parts[0].strip(), 0)
            heads[parts[0].strip()] += 1
    rep = {k: v for k, v in heads.items() if v >= 2}
    # It's considered crammed if two or more repeated prefixes cover at least half the table
    if len(rep) >= 2 and sum(rep.values()) >= len(firsts) * 0.6:
        return sorted(rep)
    return None


def texts_of(s):
    """Every piece of text on a slide that appears on screen."""
    out = [s.get("title") or "", s.get("lead") or "", s.get("formula") or ""]
    # If `big` is a list, each piece is on-screen text. Passing it whole hides the
    # emphasis markup and the slide gets counted as "no emphasis."
    out += deckspec.big_parts(s.get("big"))
    out += (list(s.get("bullets") or []) + list(s.get("foot") or [])
            + list(s.get("fine") or []) + list(s.get("flow") or []))
    b = s.get("block") or {}
    out += [b.get("title") or "", b.get("text") or ""]
    for f in ([s.get("figure")]
              + [p.get("figure") for _s, p in deckspec.panes(s)]):
        g = (f or {}).get("grid") or {}
        out += list(g.get("cols") or []) + list(g.get("caption") or [])
    # Looks at `parts` flattened out. Without flattening, text inside a group isn't
    # counted, and the slide gets wrongly scored as "no emphasis" / "too little text."
    for _side, p in deckspec.panes(s):
        out += [p.get("head") or ""]
        tv = p.get("text") or []
        out += [tv] if isinstance(tv, str) else list(tv)
        out += list(p.get("bullets") or [])
        t = p.get("table")
        if t:
            out += list(t.get("header") or [])
            out += [c for r in t["rows"] for c in r]
    # A slide's table and a chart's table are counted outside the pane loop too.
    # Counting only inside the pane loop would hide `<hit>` on a table slide with no
    # panes, or on a panel chart.
    tables = [s.get("table")]
    for owner in [s] + [p for _s, p in deckspec.panes(s)]:
        ch = owner.get("chart") or {}
        tables.append(ch.get("table"))
        tables += [(pn or {}).get("table") for pn in (ch.get("panels") or [])
                   if isinstance(pn, dict)]
    for t in tables:
        if t:
            out += list(t.get("header") or [])
            out += [c for r in t.get("rows") or [] for c in r]
    t = s.get("table")
    if t:
        out += [t.get("note") or ""]
    out += [x if isinstance(x, str) else (x or {}).get("text", "")
            for x in (s.get("lines") or [])]
    return [str(x) for x in out if x]


def has_marks(s):
    """Does it point to where to look through shape rather than text markup: a `big`
    piece's `mark`, a diagram's `mark`/`mark_at`, a chart's `callout`.

    Counting only `**bold**`/`<hit>` would score a minimal-pair slide, or a diagram that
    already has an emphasis box, as "no emphasis," and force bold text onto an
    otherwise fine slide.
    """
    def walk(o):
        if isinstance(o, dict):
            if o.get("mark") or o.get("mark_at") is not None or o.get("callout"):
                return True
            # A strip cell's `mark` is a role color (legend), not a point to look at
            return any(walk(v) for k, v in o.items() if k not in ("cells", "legend"))
        if isinstance(o, list):
            return any(walk(v) for v in o)
        return False
    owners = [s] + [p for _s, p in deckspec.panes(s)]
    return (walk(s.get("big") if isinstance(s.get("big"), list) else None)
            or any(walk(o.get("diagram")) or walk(o.get("chart")) for o in owners))


def is_question(s):
    """Does the title ask the audience something?

    Why measure this: in one example deck, 15% of slide titles ended in a question
    mark. Slides like "Isn't the sample too small?" or "How much does this cost?" raise,
    before anyone asks, the objection the audience is silently thinking. Building a deck
    by pulling only the skeleton out of a paper drives this to 0, because the paper has
    no sentences like that. A deck with not one question in it becomes a report that
    gets read, not a talk that gets heard.
    """
    # Strips markup before checking, so a title like "... **Where do LLMs land?**" is
    # still counted as a question even with markup around it.
    return bool(plain(str(s)).rstrip().endswith("?"))


def bullets_only_slides(path):
    """Which slides have only bullets. A ratio alone gives no place to fix.

    A number with no location invites guessing instead of fixing: someone reading only
    "bullets-only 20%" has to guess what it is counting, and can guess wrong.
    """
    _, slides, _ = load(path)
    out = []
    for s in slides:
        # Looks at `parts` flattened out. `profile` below flattens it too; without
        # this, a bullets-only slide inside `parts` would be missing from this list.
        panes = [leaf for side in (s.get("left"), s.get("right"))
                 for leaf in (deckspec.pane_leaves(side) if side else [])] or [{}]
        # A defining formula (`formula:`) shown big also counts as a visual. Counting
        # it as bullets-only would put a formula slide required by planning's §shapes
        # at a disadvantage in the density score.
        has_fig = bool(s.get("figure") or s.get("chart")
                       or s.get("diagram") or s.get("formula")) or \
            any(p.get("figure") or p.get("chart") or p.get("diagram")
                for p in panes)
        has_tab = shown_table(s) or any(p.get("table") for p in panes)
        bullets = list(s.get("bullets") or [])
        for p in panes:
            bullets += list(p.get("bullets") or [])
        if bullets and not has_fig and not has_tab \
                and s["kind"] not in ("standout", "title"):
            out.append((s["n"], plain(s.get("title") or "")[:40]))
    return out


def col_chars(t):
    """How many characters wide a table is: the sum of each column's longest cell.

    Measuring by column count gets this wrong. Even with only three columns,
    twenty-nine characters per cell gets crushed in a narrow pane, so switching such a
    table to two columns can make it worse rather than better.
    """
    rows = list(t.get("rows") or [])
    head = t.get("header") or []
    if head:
        rows = [head] + rows
    if not rows:
        return 0
    n = max(len(r) for r in rows)
    total = 0
    for c in range(n):
        total += max((len(strip_markup(str(r[c]))) for r in rows
                      if c < len(r)), default=0)
    return total


# Characters that fit in a narrow pane (a bit over half the slide width,
# `\footnotesize`). Measured and hard-coded.
PANE_CHARS = 55


def one_visual(s):
    """Does this slide have one thing to look at? If so, (kind, is it wide).

    Width is what decides this. Something wide is right at full width; something narrow
    and tall is better off with text placed beside it.
    """
    if s.get("kind") == "columns" or s.get("left") or s.get("right"):
        return None
    if s.get("diagram"):
        d = s["diagram"]
        kind = d.get("kind", "flow")
        # flow runs horizontally so it's wide. stack is vertical. grid is judged by
        # column count.
        wide = kind == "flow" or (kind == "grid"
                                  and len(d.get("cols") or []) >= 3)
        return ("diagram", wide)
    if s.get("chart"):
        t = s.get("table") or {}
        cols = len(t.get("header") or []) - 1
        return ("grid", cols >= 3 or col_chars(t) > PANE_CHARS)
    if s.get("figure") and not (s["figure"].get("grid")):
        return ("figure", True)      # a file figure's aspect ratio is unknown, so it is assumed wide
    if shown_table(s):
        t = s["table"]
        cols = len(t.get("header") or t["rows"][0]) - 1
        return ("table", cols >= 4 or col_chars(t) > PANE_CHARS)
    return None


def column_candidates(path):
    """Slides to consider re-laying-out into two columns. (slide number, what, why).

    A ratio alone changes nothing. This names the actual spot to change.
    """
    _, slides, _ = load(path)
    out = []
    for s in slides:
        if s.get("backup"):
            continue
        got = one_visual(s)
        if not got:
            continue
        what, wide = got
        says = (len(s.get("bullets") or []) + (1 if s.get("block") else 0)
                + (1 if s.get("foot") else 0))
        if says < 2 or wide:
            continue
        out.append((s["n"], what,
                    "one %s and %d line(s) of text about it, stacked vertically"
                    % (what, says)))
    return out


def shape_notes(path):
    """Two things that numbers don't catch but are obvious once you look. Returned
    with slide numbers."""
    _, slides, _ = load(path)
    dup, merged = [], []
    for s in slides:
        if same_data_twice(s):
            dup.append(s["n"])
        for where, t in tables_in(s):
            got = merged_column(t)
            if got:
                merged.append((s["n"], where, got[:3]))
                break
    return dup, merged


def profile_spec(path):
    meta, slides, _ = load(path)
    # A backup slide is not part of the talk. Counting it would force bold text onto
    # a lookup table. The ratio is measured only over slides the audience sees.
    slides = [s for s in slides if not s.get("backup")]
    n = len(slides)
    c = dict.fromkeys(BASELINE, 0)
    nb, nbw = 0, 0
    skip_emph = 0
    for s in slides:
        # Looks at panes flattened into groups. Not counting bullets/figures inside
        # `parts` would mean that the more a deck used the `parts` structure SKILL
        # recommends, the more "bullets per slide" dropped toward 0.0.
        panes = [leaf for side in (s.get("left"), s.get("right"))
                 for leaf in (deckspec.pane_leaves(side) if side else [])] or [{}]
        # `chart` is a figure too: the builder draws a PNG into it. Not counting it
        # would flag a deck that already drew figures as "no figures," and trusting
        # that message would lead to drawing yet another one.
        # A defining formula (`formula:`) shown big also counts as a visual. Counting
        # it as bullets-only would put a formula slide required by planning's §shapes
        # at a disadvantage in the density score.
        has_fig = bool(s.get("figure") or s.get("chart")
                       or s.get("diagram") or s.get("formula")) or \
            any(p.get("figure") or p.get("chart") or p.get("diagram")
                for p in panes)
        has_tab = shown_table(s) or any(p.get("table") for p in panes)
        bullets = list(s.get("bullets") or [])
        for p in panes:
            bullets += list(p.get("bullets") or [])
        c["figure"] += has_fig
        c["table"] += has_tab
        c["columns"] += s["kind"] == "columns"
        c["standout"] += s["kind"] == "standout"
        # The cover and question slides are excluded from the emphasis ratio's
        # denominator. planning's §question says not to mark up a question slide, and
        # including it in the denominator would penalize a deck for following that
        # guideline.
        if s["kind"] == "title" or (s["kind"] == "standout"
                                    and "?" in str(s.get("lead") or "")):
            skip_emph += 1
        else:
            c["emphasis"] += (any(deckspec.emphasis(x) for x in texts_of(s))
                              or has_marks(s))
        c["bullets_only"] += bool(bullets) and not has_fig and not has_tab \
            and s["kind"] not in ("standout", "title")
        # A standout slide's question lives in `lead` (planning §question/§objection).
        # Looking only at the title would miss it.
        c["question"] += is_question(s.get("title")
                                     or (s.get("lead") if s["kind"] == "standout" else "")
                                     or deckspec.big_text(s.get("big")) or "")
        nb += len(bullets)
        nbw += sum(len(strip_markup(b).split()) for b in bullets)
    ratios = {k: v / float(n) for k, v in c.items()}
    ratios["emphasis"] = c["emphasis"] / float(max(1, n - skip_emph))
    return n, ratios, \
        (nb / float(n), nbw / float(max(1, nb)))


def profile_tex(path):
    """Pulls the same values from a reference Beamer source. Notes are stripped since
    they aren't on screen."""
    src = slurp(path)
    out, i, tag = [], 0, "\\note{"
    while True:
        j = src.find(tag, i)
        if j < 0:
            out.append(src[i:])
            break
        out.append(src[i:j])
        k, d = j + len(tag), 1
        while k < len(src) and d:
            d += 1 if src[k] == "{" else -1 if src[k] == "}" else 0
            k += 1
        i = k
    src = "".join(out)
    frames = re.split(r"\\begin\{frame\}", src)[1:]
    n = len(frames)
    c = dict.fromkeys(BASELINE, 0)
    nb, nbw = 0, 0
    for f in frames:
        b = f.split("\\end{frame}")[0]
        fig, tab = "includegraphics" in b, "tabular" in b
        stand = b.lstrip().startswith("[standout]")
        items = re.findall(r"\\item\s+(.+)", b)
        c["figure"] += fig
        c["table"] += tab
        c["columns"] += "begin{columns}" in b
        c["standout"] += stand
        c["emphasis"] += bool(re.search(r"\\(textbf|hit|safe|textcolor)", b))
        c["bullets_only"] += bool(items) and not fig and not tab and not stand
        # The title is in `\begin{frame}{...}` or on the line after `[standout]`
        m = re.match(r"\s*(?:\[[^\]]*\])?\s*\{(.+?)\}\s*$", b.split("\n")[0]) \
            or re.match(r"\s*(.+?)\s*$", b.split("\n")[1] if stand and
                        len(b.split("\n")) > 1 else "")
        c["question"] += is_question(re.sub(r"\\[a-zA-Z]+|[{}$]", "", m.group(1))
                                     if m else "")
        nb += len(items)
        nbw += sum(len(re.sub(r"\\[a-zA-Z]+|[{}$]", " ", x).split()) for x in items)
    return n, {k: v / float(n) for k, v in c.items()}, \
        (nb / float(n), nbw / float(max(1, nb)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measures a deck's design density and compares it against a reference")
    ap.add_argument("spec")
    ap.add_argument("--ref", default=None, metavar="TALK_TEX",
                    help="Reference Beamer source. Compares against the baseline if omitted")
    ap.add_argument("--baseline", default=None, metavar="k=v,k=v",
                    help="Overrides the baseline (e.g. figure=0.2,table=0.4)")
    ap.add_argument("--tolerance", type=float, default=0.15,
                    help="Flags a difference larger than this (default 0.15)")
    a = ap.parse_args(argv)

    n, got, (bpp, wpb) = profile_spec(a.spec)
    if a.ref:
        rn, want, (rbpp, rwpb) = profile_tex(a.ref)
        src = "reference %s (%d slides)" % (os.path.basename(a.ref), rn)
        strict = tuple(BASELINE)          # look at everything if a reference is given
    else:
        # There usually is no reference deck. That's normal. In that case, use the
        # baseline measured from one deck only as a reference, and count as a failure
        # only the items that don't depend on the field.
        rn, want, (rbpp, rwpb) = 20, dict(BASELINE), BASELINE_BULLETS
        src = "baseline (a value measured from one deck, not a rule)"
        strict = STRICT
    for kv in (a.baseline or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            if k.strip() in want:
                want[k.strip()] = float(v)

    print("=" * 72)
    print("Design density: %s / %s (%d slides)" % (os.path.basename(a.spec), src, n))
    print("=" * 72)
    bad = 0
    for k in ("figure", "table", "columns", "standout", "emphasis",
              "question", "bullets_only"):
        d = got[k] - want[k]
        # Bullets-only is a problem when high; everything else is a problem when low
        off = (d > a.tolerance) if k == "bullets_only" else (d < -a.tolerance)
        off = off and k in strict
        bad += off
        print("   %s %-*s %3.0f%%  (ref %3.0f%%)  %s"
              % ("! " if off else "  ", max(len(v) for v in LABEL.values()), LABEL[k], got[k] * 100, want[k] * 100,
                 "%+.0f%%p" % (d * 100)))
    # Having not one question-mark title is field-independent. A paper has no sentence
    # that voices an objection first, so building straight from the paper always drives
    # this to 0.
    if not got["question"] and n >= 8:
        print()
        print("   Not one slide's title is a question. One example deck had 15% of its slides this way.")
        print("     Slides like \"Isn't the sample too small?\" raise, before anyone asks,")
        print("     the objection the audience is silently thinking. A paper has no")
        print("     sentences like that, so pulling straight from it always gives 0, and")
        print("     a deck at 0 becomes a report that gets read, not a talk that gets heard.")
        bad += 1

    print()
    print("   %s bullets/slide %.1f (ref %.1f)   words/bullet %.0f (ref %.0f)"
          % ("! " if bpp > rbpp + 1.0 else "  ", bpp, rbpp, wpb, rwpb))
    # The baseline deck is one line per slide that carries a claim and its evidence
    # together (1.0 / 18.8 words). Placing several short tags is a list, not an
    # argument. Count, more than length, is the signal: going by length alone and
    # saying "cut it once it passes twelve words" went the opposite direction from
    # the reference.
    if bpp > rbpp + 1.0:
        print("     Many bullets on one slide. The reference has one line per")
        print("       slide, but that line carries the claim and the evidence")
        print("       together. Laying out several tags turns it into a list.")
        bad += 1
    if wpb > rwpb + 10:
        print("     A bullet line is even longer than the reference. Past this point, move it down to `say`.")
        bad += 1

    # ── Shape, not numbers ───────────────────────────────────────────────────
    # There are cases where the ratios all check out but it looks different anyway.
    # The two below actually happen.
    dup, merged = shape_notes(a.spec)
    if dup:
        print()
        print("   %d slide(s) show the same value twice, as a table and a figure: %s"
              % (len(dup), ", ".join(str(x) for x in dup)))
        print("     It counts as two columns, but it's duplication, not a comparison.")
        print("     A useful two-column layout has left and right showing two")
        print("     different things: two subjects, or a table and its evidence.")
        print("     Delete one side or replace it with something else.")
        bad += 1
    if merged:
        print()
        print("   %d table(s) cram two attributes into one cell:" % len(merged))
        for n_, where, heads in merged:
            print("       slide %2d %-5s first column splits into \"%s\""
                  % (n_, where, " / ".join(heads)))
        print("     Splitting it into two columns or two panels makes which side")
        print("     drives what visible only from the layout. Left crammed")
        print("     together, it becomes a flat list that the reader has to")
        print("     reconstruct.")
        # If a table is grouped by subject (planning §part-whole), don't repeat the
        # lead word in every cell; use a group row instead, so a table that follows
        # §part-whole isn't flagged here with no way to fix it.
        print("     If this is a table grouped by subject: don't repeat the lead")
        print("       word in every cell. Use a group row with only the first cell")
        print("       filled (`[\"Dry cell, 300 trials\", \"\", \"\"]`) and write only the")
        print("       trailing word in the rows below it.")
        bad += 1

    # This prints a path forward when the gap is large even if it isn't counted as a
    # failure. An item outside `STRICT` can have the biggest gap of all and still leave
    # `bad` at 0, so without this the advice below would never print. A number with no
    # instruction changes nothing.
    print()
    if got["figure"] < want["figure"] - a.tolerance:
        print("     Few slides have a figure. But there is no basis for \"just draw")
        print("     more figures\": Tufte says a table usually beats a figure when")
        print("     reporting twenty numbers or fewer, and Meyer 1999's empirical")
        print("     comparison found tables winning or tying more often than not.")
        print("     The question isn't figure vs. table, it's what this slide")
        print("     claims:")
        print("       . a value must be looked up or read exactly      -> table is right")
        print("       . shape itself is the claim (trend/outlier/cluster) -> figure is right")
        print("       . both are needed                                    -> put both (Few)")
        print("     And in the room, a table steals the ear: the audience can't")
        print("     hear you while they're reading it (Knaflic). A dense table is")
        print("     better off as a handout.")
    # A ratio alone changes nothing without a location: knowing only "columns 13/35"
    # gives no single slide to change.
    if got["columns"] < want["columns"] - a.tolerance:
        cand = column_candidates(a.spec)
        print("     Few two-column slides. The common two-column shape is this:")
        print("     one pane shows it, the other tells you how to read it.")
        if cand:
            print("     Below are slides that currently stack that vertically:")
            for n_, what, why in cand:
                print("       slide %2d  %s" % (n_, why))
            print("     Even inside a pane, `chart: {from: self}` can stand in for its")
            print("     own table: a grid on the left, how to read it on the right.")
            print("     A wide grid (3+ columns) belongs at full width, so it isn't")
            print("     listed here.")
        else:
            print("     But no slide needs the change: what there is to show is")
            print("     either all wide, or there's only one line to say about it.")
            print("     Don't force a split only to match the ratio.")

    if bad:
        print("   %d item(s) differ sharply from the reference." % bad)
        if got["bullets_only"] > want["bullets_only"] + a.tolerance:
            print("     Many slides with only bullets means nothing was made to")
            print("     show. Put a table beside it (columns), draw a figure, or use")
            print("     emphasis to mark where to look.")
            print("     But a table is evidence too. What Alley's")
            print("       assertion-evidence approach forbids is a bullet list, not a table")
            print("       (2005, Table 1 names a table as evidence).")
            for n_, ttl in bullets_only_slides(a.spec):
                print("       slide %2d  %s" % (n_, ttl))
        if got["emphasis"] < want["emphasis"] - a.tolerance:
            print("     Little emphasis. Use `**bold**` and `<hit>`/`<safe>` to mark")
            print("     where to look.")
            print("     Emphasis is what lets the point be read without reading the")
            print("     whole table.")
    else:
        print("   Comparable to the reference.")
    if not a.ref:
        print("   No reference deck, so among the ratios only slides with only")
        print("     bullets counted as a failure (emphasis is for reference only).")
        print("     The checks below the ratios (question titles, bullet count and")
        print("     length, duplicated or crammed tables) still count.")
        print("     The rest of the ratios depend on the field: a concept talk")
        print("     having fewer figures is normal.")
    print("   (These numbers are not a verdict, they are a list of places to look. Render it and look for yourself.)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    sys.exit(main())
