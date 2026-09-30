# -*- coding: utf-8 -*-
"""Script/slide prose audit. Don't fix by feel, measure it.

    python prose_audit.py slides.yaml                    <- usually this
    python prose_audit.py slides.yaml TermOne TermTwo    <- also reports where each term first appears
    python prose_audit.py <script.json>                  <- also accepts a hand-made list

Takes `slides.yaml` directly. It used to take only a slide-list JSON, but nothing in the
pipeline ever produced that JSON, so using this tool meant writing your own converter
first, and nobody did.

Format when passing a hand-made list:
    [{"n":1, "title":"...", "say":["...","..."]}, ...]

It measures five things. Three are about sentences; two are about spots where the audience
trips.

The latter two (3 and 4) move what an audience panel used to catch onto a machine. A deck
that was clean on all six checks was shown to five people, and all five got stuck at the
same four spots, none of which any check had caught. The panel is still needed, but these
two are filtered out before a person ever has to look.

1. Title-first-sentence overlap rate: does the speaker's first line only repeat the title
   the audience just read?
   In this project, tightening the prose pushed nearly half the slides to 60%+ overlap
   (one in four hit 100%), and that surfaced as feedback that "the explanation is strangely
   unhelpful."
   When the mouth repeats what the screen already said, the real explanation gets pushed
   back.
   Re-measure this whenever a title changes.

2. First appearance of a term: the slide where a term first appears on screen versus the
   slide where it is first explained aloud.
   If the explanation comes later, the audience spends the whole gap looking at a word they
   don't know.
   In this project, a prior-work table let our model's name slip out early: a term the
   chair said "appears on slide 15 with no warning" had in fact been on screen since slide 6.

3. Something shown on screen but never said aloud: table column names like `b/c`,
   undefined abbreviations.
   Even if every number is right, if the audience gets stuck here, that table cannot be
   read.

4. Do a color's meaning, count, and name agree on screen: red used with no stated meaning,
   "five things" written but only four drawn, or the same word carrying two different
   values.

5. Register markers: sentence-initial discourse markers, first person, evaluative framing,
   titles that open with a conjunction.
   The feeling of "too casual" is usually a handful of specific constructions, not
   colloquial style in general.

Tightening #2 tends to make #1 worse. Measure the two together: measuring them separately
means you can fix one while breaking the other without noticing.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckspec  # noqa: E402
from deckspec import load, plain  # noqa: E402

STOP = set("a an the of in on to for and or is are was were be been it its this that "
           "we our us you they them with at by as from than then so but not no".split())


HEDGE = set("only about nearly almost roughly around just still under over "
            "within below above near least most loses drops costs gains".split())


def stem(w):
    """A rough stem: treats `irrigate` and `irrigating` as the same word."""
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def toks(s):
    return [stem(w) for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", s.lower())
            if w not in STOP]


def first_sentence(para):
    m = re.split(r"(?<=[.?!])\s", para.strip(), 1)
    return m[0] if m else para


def overlap(title, para):
    """Is the first sentence made up only of the title's words? (0-1).

    The denominator is the first sentence, not the title. Using the title as the
    denominator would let a long explanatory paragraph coincidentally cover every title
    word, producing false positives. What needs to be caught isn't "it covers the whole
    title" but "the first line adds no new information."
    """
    f = set(toks(first_sentence(para)))
    t = set(toks(title))
    return 0.0 if not f else len(t & f) / float(len(f))


CONJ_LABEL = "Titles that open with a conjunction"
REGISTER = [
    ("Sentence-initial discourse marker So/Now/And/But", r"(?:^|[.?!]\s+)(so|now|and|but)\s"),
    ("First-person singular I", r"\bI\b"),
    ("Evaluative framing", r"\bthe (honest|useful|interesting|fun) (part|bit)\b"),
    # A possessive (`pump's`) is not a contraction: 's only counts after a pronoun.
    ("Contraction", r"\b(?:it|that|there|here|what|he|she|let|who|where|how)['\u2019]s\b"
              r"|\b\w+['\u2019](?:re|ll|ve|d)\b|\b\w+n['\u2019]t\b"),
]


def big_text(v):
    """Turns a standout slide's `big` into text a person reads.

    If it's a list, joins the big number with the label beneath it. A plain `str()`
    would make the checker spit out the spec's data structure onto the screen, and word
    comparisons would count key names like `value`/`label` as words.
    """
    if not isinstance(v, list):
        return plain(v or "")
    out = []
    for b in v:
        if isinstance(b, dict):
            out += [plain(b.get(k) or "")
                    for k in ("value", "label", "note") if b.get(k)]
        else:
            out.append(plain(b))
    return " ".join(x for x in out if x)


def from_spec(path):
    """`slides.yaml` -> the slide list this tool sees.

    Separates the on-screen text (title) from the spoken words (`say`). If there's no
    `say`, uses `note` instead, so title/first-line overlap can still be measured even
    before a script has been written.
    """
    _, slides, _ = load(path)
    out = []
    for s in slides:
        say = list(s.get("say") or []) or list(s.get("note") or [])
        raw = screen_text(s)
        out.append({"n": s.get("n"),
                    "title": plain(s.get("title") or "") or big_text(
                        s.get("big")),
                    "own_title": bool(s.get("title")),
                    # Without `kind`/`backup`/`lead`, backup slides can't be told apart.
                    # `standout` is excluded from title judgment because `big` itself
                    # is the claim.
                    "kind": s.get("kind"),
                    "figure": s.get("figure"),
                    "diagram": s.get("diagram"),
                    "left": s.get("left"),
                    "right": s.get("right"),
                    "backup": bool(s.get("backup")),
                    "lead": plain(s.get("lead") or ""),
                    # The screen is not only the title. In this project, what leaked a
                    # term early was the prior-work table. Looking only at the title
                    # would miss that slide.
                    "screen": " ".join(plain(x) for x in raw),
                    "fig_words": " ".join(plain(x) for x in figure_words(s)),
                    # A version that keeps the markup, needed to check whether
                    # `<hit>`/`<safe>` are used
                    "raw_screen": " ".join(str(x) for x in raw),
                    # Does a chart write the meaning next to the color (`chart.verdict`)?
                    # That counts as disclosing the color key.
                    "verdict": any(((o or {}).get("chart") or {}).get("verdict")
                                   for o in (s, s.get("left"), s.get("right"))),
                    # On-screen text with tables removed. Concatenating table cells
                    # would attach some column's value next to a row name.
                    "prose_screen": " ".join(str(x) for x in screen_text(s, False)),
                    "counts": element_counts(s),
                    "tables": tables_of(s),
                    "has_figure": bool(
                        s.get("figure") or s.get("chart") or s.get("diagram")
                        or (s.get("left") or {}).get("figure")
                        or (s.get("left") or {}).get("chart")
                        or (s.get("left") or {}).get("diagram")
                        or (s.get("right") or {}).get("figure")
                        or (s.get("right") or {}).get("chart")
                        or (s.get("right") or {}).get("diagram")),
                    # `unspoken_terms` reads `note` and `ko`; without passing them through
                    # here, that path could never be reached, and a term explained in a
                    # stage note would be flagged as "never said aloud."
                    "note": [plain(x) for x in (s.get("note") or []
                                                if isinstance(s.get("note"), list)
                                                else [s.get("note") or ""])
                             if x],
                    "ko": [plain(x) for x in (s.get("ko") or [])],
                    "cue": s.get("cue") or "",
                    # The lower lines of a standout slide are on-screen text too, and
                    # must be read here too, or claim words in them get missed.
                    "lines": [plain(x if isinstance(x, str) else (x or {}).get("text", ""))
                              for x in (s.get("lines") or [])],
                    "say": [plain(x) for x in say]})
    return out


def panel_tables_of(s):
    """Tables held directly inside `chart.panels`. These are missed unless collected
    explicitly."""
    out = []
    for where in ("self", "left", "right"):
        owner = s if where == "self" else (s.get(where) or {})
        ch = owner.get("chart") or {}
        if isinstance(ch.get("table"), dict):
            out.append(ch["table"])           # a table placed inside the chart
        for p in (ch.get("panels") or []):
            if isinstance(p, dict) and p.get("table"):
                out.append(p["table"])
    return out


def tables_of(s):
    out = []
    for t in (s.get("table"), (s.get("left") or {}).get("table"),
              (s.get("right") or {}).get("table")):
        if t:
            out.append(t)
    return out + panel_tables_of(s)


def element_counts(s):
    """How many of something this slide draws on screen: (what, count).

    To cross-check against a number written in words ("four things"), we need the
    actual count.
    """
    out = []
    for where, f in (("self", s.get("figure")),
                     ("left", (s.get("left") or {}).get("figure")),
                     ("right", (s.get("right") or {}).get("figure"))):
        g = (f or {}).get("grid") or {}
        if g.get("images"):
            out.append(("grid columns", len(g["images"][0])))
            out.append(("grid rows", len(g["images"])))
        # Boxes inside a PNG can't be counted, so this asks to be told the count
        # instead: writing `figure: {path: x.png, shows: 4}` lets it be checked against
        # a "five things" in the body text.
        if (f or {}).get("shows"):
            out.append(("items in the figure", int(f["shows"])))
    # Table row/column counts are not put in here. Comparing the body text's "four"
    # against a table's 8 rows x 3 columns produces nothing but false positives, since
    # a number counted in prose and a table's dimensions count different things. Boxes
    # drawn inside a figure are a PNG and can't be counted. Only grids and bullets can
    # be counted.
    b = list(s.get("bullets") or [])
    if len(b) >= 3:
        out.append(("bullets", len(b)))
    return out


_FIG_TEXT_KEYS = ("title", "note", "takeaway", "caption", "label", "sub", "text",
                  "xlabel", "ylabel", "row_label", "col_label", "out", "col_notes",
                  "verdict", "legend", "edge_names", "axis")


def figure_words(s):
    """Words drawn inside the slide's charts and diagrams. `deckcheck` H reads them from
    the sidecar, so leaving them out here made the two checkers count the same word
    differently."""
    out = []

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key in _FIG_TEXT_KEYS:
            out.append(v)
    seen = []
    for o in [s, s.get("left") or {}, s.get("right") or {}] + [p for _, p in deckspec.panes(s)]:
        # A pane can come back from `panes` as well as from `left`/`right`.
        if any(o is x for x in seen):
            continue
        seen.append(o)
        for k in ("chart", "diagram"):
            if isinstance(o.get(k), dict):
                walk(o[k])
    return [str(x) for x in out if x]


def screen_text(s, with_tables=True):
    """Every piece of text that appears on screen for one slide: title, bullets, table,
    block, pane."""
    # `big` is resolved through the shared function. Feeding the list in raw would let
    # dictionary keys (`text`/`safe`) surface as "words the deck uses."
    out = [s.get("title") or ""] + deckspec.big_parts(s.get("big")) + [s.get("lead") or ""]
    for where in ("self", "left", "right"):
        _o = s if where == "self" else (s.get(where) or {})
        _c = _o.get("chart") or {}
        out += [_c.get("title") or "", _c.get("note") or ""]
        out += list(_c.get("col_notes") or [])
        out += [_c.get("row_label") or "", _c.get("col_label") or ""]
        for _p in (_c.get("panels") or []):
            if isinstance(_p, dict):
                out.append(_p.get("title") or "")
    out += (list(s.get("bullets") or []) + list(s.get("foot") or [])
            + list(s.get("fine") or []) + list(s.get("flow") or []))
    b = s.get("block") or {}
    out += [b.get("title") or "", b.get("text") or ""]
    tabs = [s.get("table")] + panel_tables_of(s)
    # Looks at `parts` flattened out. Without flattening, text inside a group doesn't
    # get counted, and the slide is wrongly scored as "no emphasis" / "too little text."
    for _side, p in deckspec.panes(s):
        out += [p.get("head") or ""]
        tv = p.get("text") or []
        out += [tv] if isinstance(tv, str) else list(tv)
        out += list(p.get("bullets") or [])
        pb = p.get("block") or {}
        out += [pb.get("title") or "", pb.get("text") or ""]
        tabs.append(p.get("table"))
    for t in tabs:
        if t and with_tables:
            out += list(t.get("header") or []) + [t.get("note") or ""]
            out += [c for r in t["rows"] for c in r]
        elif t:
            out += [t.get("note") or ""]
    return [str(x) for x in out if x]


# A dot between digits is part of the name, or "v2.5-1.3B" gets truncated to "v2" and
# reported as a nonexistent abbreviation.
JARGON = re.compile(r"[A-Za-z][A-Za-z0-9/+_-]*(?:(?<=\d)\.\d[A-Za-z0-9/+_-]*)*")


def looks_like_jargon(w):
    """Is this a word the audience might not know: abbreviation, symbol, model name.

    Plain English words are excluded. If digits are mixed in (`P4V2`, `HV2`), if it has
    two or more capital letters (`HVCX`, `RMSE`), or if it's a short slash-joined
    initialism (`w/l`), it needs an explanation.
    """
    if len(w) < 2 or w.lower() in STOP:
        return False
    # Notational conventions (n/a, w/o) are not terms
    if w.lower() in ("n/a", "w/o", "w/", "i.e", "e.g"):
        return False
    # Roman numerals (table/section numbers like "Table III") are not terms either
    if re.fullmatch(r"[IVX]{2,4}", w):
        return False
    # Size notation (`4x4`, `16x16`) and its fragments (`x4`) are not terms, or they
    # get flagged as "never said aloud" even when read aloud as numbers.
    if re.fullmatch(r"x?\d+(x\d+)*x?", w, re.I):
        return False
    # Formula fragments (`t-1`, `k+1`, `2p`, `n2`) are not abbreviations but formulas:
    # the script may read one aloud as "t minus one," which would otherwise flag it as
    # "never said aloud." A single letter with digits only.
    if re.fullmatch(r"[A-Za-z][-+]?\d{1,3}|\d{1,3}[-+]?[A-Za-z]", w):
        return False
    if any(c.isdigit() for c in w) and any(c.isalpha() for c in w):
        return True
    if sum(1 for c in w if c.isupper()) >= 2:
        return True
    return "/" in w and len(w) <= 6


_SPELLED = re.compile(r"(?<![A-Za-z])([A-Za-z](?:[-\s][A-Za-z]){1,7})(?![A-Za-z])")
# Digits too, so "T over 3" said aloud is recognized, and the on-screen T/3 is not
# flagged as "never said aloud."
_OVER = re.compile(r"\b([A-Za-z0-9]{1,4})\s+over\s+([A-Za-z0-9]{1,4})\b", re.I)
_SUBW = re.compile(r"\b([A-Za-z]{1,4})\s+sub\s+([A-Za-z0-9]{1,4})\b", re.I)


def spoken_forms(text):
    """Turns an abbreviation spelled out aloud back into its on-screen form.

        "E-x-M-y"   -> "ExMy"
        "b over c"  -> "b/c"
    """
    out = []
    for m in _SPELLED.finditer(text):
        out.append(re.sub(r"[-\s]", "", m.group(1)))
    for m in _OVER.finditer(text):
        out.append("%s/%s" % (m.group(1), m.group(2)))
    for m in _SUBW.finditer(text):
        out.append("%s_%s" % (m.group(1), m.group(2)))
    return out


def unspoken_terms(slides):
    """Words that appear on screen but are never said aloud, not even once.

    This was the most expensive gap in this pipeline. A deck that was clean on all six
    checks was shown to five audience members, and all five got stuck at the same spots,
    every one of this kind: table column names like `b/c`, `L`, setting names that exist
    only on screen and never in the script. Every number was correct; there was no
    explanation.

    `deckcheck` looks at whether the on-screen number is in the source of truth.
    Something put on screen and never spoken was checked by nothing.

    Returns: [(slide number, word)], by the slide where it first appears.
    """
    said = set()
    for s in slides:
        for x in (s.get("say") or []) + (s.get("ko") or []) + \
                ([s["note"]] if s.get("note") else []):
            said |= {w for w in JARGON.findall(str(x))}
            # Counts spelled-out forms too: "E-x-M-y" becomes ExMy, "b over c" becomes
            # b/c.
            said |= set(spoken_forms(str(x)))
            # Saying it spelled out counts as saying it too. Without this, saying "queue
            # manager" would still get the on-screen "QM" flagged, and saying
            # "round-trip time" would still get "RTT" flagged, forcing awkward sentences
            # like "X on the slide is Y." Takes the initials of 2 to 6 consecutive words
            # as an abbreviation.
            _ws = re.findall(r"[A-Za-z]+", str(x))
            for i in range(len(_ws)):
                for n in range(2, 7):
                    if i + n <= len(_ws):
                        said.add("".join(w[0] for w in _ws[i:i + n]))
    said_low = {w.lower() for w in said}
    # A word joined by a hyphen or slash counts as said even in parts, or saying
    # "RPC-based" would still get the on-screen "RPC" flagged, and saying "IC, OC"
    # would still get the on-screen "IC/OC" flagged.
    said_low |= {p for w in list(said_low) for p in re.split(r"[-/_+]", w) if p}
    # A symbolic expression (`R_T/T`) counts as said if each part was said aloud, or an
    # expression read aloud as "R T over T" would be flagged only because its subscript
    # is written as `_`. Takes single words (even single letters) from the script as
    # parts.
    _words = set()
    for s_ in slides:
        for x in (s_.get("say") or []) + (s_.get("ko") or []) + \
                ([s_["note"]] if s_.get("note") else []):
            _words |= set(w.lower() for w in re.findall(r"[A-Za-z]+|\d+", str(x)))

    def _said(w):
        lw = w.lower()
        # A plural counts as the same word, so the script saying "DWAs" still matches
        # the on-screen "DWA."
        if lw in said_low or lw + "s" in said_low or (lw.endswith("s") and lw[:-1] in said_low):
            return True
        parts = [p for p in re.split(r"[-/_+]", lw) if p]
        return len(parts) > 1 and all(p in said_low or p in _words for p in parts)

    seen, out = set(), []
    for s in slides:
        for w in JARGON.findall(s.get("screen") or s.get("title", "")):
            if not looks_like_jargon(w) or _said(w) or w in seen:
                continue
            seen.add(w)
            out.append((s.get("n"), w))
    # Greek letters and period-abbreviations also get stuck if they're on screen only:
    # an on-screen epsilon never once named in the script stalls the audience the same
    # way any other unexplained symbol would, and so does a table header like "Aug."
    # It's fine if the script has the name (epsilon) or the letter for epsilon, or a
    # word starting with that string for "Aug."
    spoken = " ".join(str(x) for s in slides for x in
                      (s.get("say") or []) + (s.get("ko") or []) +
                      ([s["note"]] if s.get("note") else []))
    sp_low = spoken.lower()
    sp_words = set(re.findall(r"[a-z]+", sp_low))
    # A single letter can have more than one name (epsilon = epsilon/varepsilon).
    # Inverting the map and keeping only one would flag a script that said "epsilon"
    # too.
    greek_name = {}
    for k, v in deckspec.GREEK.items():
        greek_name.setdefault(v, set()).add(k.lower())
    common_abbr = {"fig", "figs", "eq", "eqs", "tab", "no", "vs", "al", "eg", "ie", "dr",
                   "mr", "ms", "sec", "ref", "refs", "approx", "resp", "cf", "etc"}
    for s in slides:
        face = s.get("screen") or s.get("title", "")
        for ch in sorted(set(re.findall(u"[Ͱ-Ͽ]", face))):
            nms = greek_name.get(ch, set())
            # Delta (difference), mu (micro), Omega (ohm) are symbols everyone knows,
            # so their meaning doesn't need to be stated separately
            if ch in u"ΔμΩ" or ch in spoken or any(nm in sp_low for nm in nms) or ch in seen:
                continue
            seen.add(ch)
            out.append((s.get("n"), ch))
        # Abbreviations are only looked for in table headers and the first cell,
        # since a period in body text is usually a sentence end ("Luna.")
        _cells = " ".join(str(c) for t in s.get("tables", [])
                          for c in list(t.get("header") or []) +
                          [r[0] for r in (t.get("rows") or []) if r])
        for ab in re.findall(r"(?<![A-Za-z.])([A-Z][a-z]{1,4})\.(?![A-Za-z])", _cells):
            lo = ab.lower()
            if lo in common_abbr or ab in seen:
                continue
            if any(w.startswith(lo) and len(w) > len(lo) for w in sp_words) or lo in sp_words:
                continue
            seen.add(ab)
            out.append((s.get("n"), ab + "."))
    return out


# ──────────────────────────────────────────────────────────────────────
# The three below move what an audience panel used to catch onto a machine.
#
# A deck that was clean on all six checks was shown to five people, and all five got
# stuck at the same four spots, none of which any check had caught. The panel is the
# most valuable step in this pipeline, but it's also the only step with no machine, so
# it's the one that quietly gets skipped. Moving even the catchable part onto a machine
# frees the panel to work on the harder cases.
# ──────────────────────────────────────────────────────────────────────

NUMWORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
           "twelve": 12}
COLOUR_WORDS = re.compile(
    r"\b(red|green|빨강|초록|붉은|녹색)\b|유의|significan|not significant", re.I)
# The name of a color: a color key must be a word that names a color
COLOUR_NAME = re.compile(r"\b(red|green|orange|teal|빨강|빨간|초록|붉은|녹색|주황)\b", re.I)


def colour_key_missing(slides):
    """Does the deck communicate through color without ever stating what the color
    means?

    `<hit>`/`<safe>` are this deck's reading device. But that device only works if
    "red = worse" is stated somewhere, at least once. One panel reader asked whether
    green meant "good" or "not significant," because it wasn't stated anywhere in the
    deck.

    `refcheck` only pushes for more emphasis; it doesn't check whether the meaning was
    ever disclosed.
    """
    first = None
    for i, s in enumerate(slides):
        if re.search(r"<(hit|safe)>", s.get("raw_screen") or ""):
            first = i
            break
    if first is None:
        return None
    # The meaning must appear at or before the color's first use. Accepting a single
    # occurrence anywhere in the deck would let through a deck that only explained the
    # color on its last slide, and the word "significant" alone is not the name of a
    # color. A chart's verdict legend (`chart.verdict`) writes the meaning next to the
    # color, so that counts as disclosed.
    for s in slides[:first + 1]:
        hay = (s.get("raw_screen") or "") + " " + " ".join(s.get("say") or [])
        if COLOUR_NAME.search(hay) or s.get("verdict"):
            return None
    for s in slides[first + 1:]:
        hay = (s.get("raw_screen") or "") + " " + " ".join(s.get("say") or [])
        if COLOUR_NAME.search(hay) or s.get("verdict"):
            # Disclosing it late still counts, but only as info: many colors have a
            # guessable meaning anyway, like a red delay bar
            return ("(info) slide %s first uses color, but the meaning isn't stated "
                    "until later (slide %s). Saying it once on the slide that first "
                    "uses it keeps the audience from having to ask"
                    % (slides[first].get("n"), s.get("n")))
    return "color is used but its meaning is never stated anywhere"


# If a number word is followed by a unit noun, that's a value, not a count, or "eight
# hours" gets compared against a 4-column grid and false-positived: any deck that deals
# with units and has a figure grid would trigger this.
UNIT_NOUN = re.compile(
    r"^(bits?|bytes?|points?|percent|%|x|times|fold|"
    r"seconds?|minutes?|hours?|steps?|epochs?|layers?|trials?|"
    r"samples?|tokens?|frames?|runs?|seeds?|cells?|배|퍼센트|비트)\b", re.I)


def count_mismatch(slides):
    """Does the count written in words differ from the count actually drawn on screen?

    It said "the five cells we compared," but the figure only drew four. All five
    readers counted the boxes and got stuck right there. `deckcheck` passes this, since
    "five" is a word, and the figure is a PNG with no way to check what it shows.

    Returns: [(slide number, count as written, actual count, what)]
    """
    out = []
    for s in slides:
        txt = s.get("raw_screen") or ""
        # Counts only when a noun follows the number word, or counting every bare
        # "four" would also catch years and ordinal numbers.
        # And if that noun is a unit, it's a value, not a count: "eight hours" would
        # otherwise be compared against a 4-column grid and false-positived, and any
        # deck that deals with units would trigger this if it has a figure grid.
        def said(t):
            got_ = set()
            for m in re.finditer(r"\b(%s)\s+([a-z]{1,14})" % "|".join(NUMWORD),
                                 t, re.I):
                tail = m.group(2)
                if len(tail) < 3 or UNIT_NOUN.match(tail):
                    continue
                got_.add(NUMWORD[m.group(1).lower()])
            return got_
        words = said(txt)
        # A bullet count is only compared against the count promised by the title or
        # lead ("Six limits"). A "three retries per request" inside a bullet is a value
        # unrelated to the six bullets.
        head = said(" ".join([str(s.get("title") or ""), str(s.get("lead") or "")]))
        if not words:
            continue
        # A grid only needs to match one of rows, columns, or cells, or a 1-row,
        # 3-column grid with "three things" written would be flagged only because
        # "rows is 1." Only flag it when it differs from all three.
        _cs = dict(s.get("counts", []))
        _grid = {_cs.get(u"grid rows"), _cs.get(u"grid columns")}
        if None not in _grid:
            _grid.add(_cs[u"grid rows"] * _cs[u"grid columns"])
        for what, got in s.get("counts", []):
            for w in (head if what == u"bullets" else words):
                if what.startswith(u"grid") and w in _grid:
                    continue
                # 1-2 are often used like articles and cause many false positives.
                # Only look at three or more.
                if w >= 3 and w != got and abs(w - got) <= 4:
                    out.append((s.get("n"), w, got, what))
    return out


DASH = re.compile(r"^\s*[-–—]\s*$|^\s*(n/?a|tbd|\.\.\.)\s*$", re.I)
# If a colon or equals sign follows a dash character, that discloses what the dash
# means (as in "-- : the paper names no such choice"). Checking words alone would
# miss this pattern.
EXPLAINS_BLANK = re.compile(
    r"dash|빈\s*칸|not\s+(run|tested|measured|applicable)|안\s*(돌|잼|측정)|"
    r"미측정|해당\s*없|blank|empty|em\s*dash|"
    r"(^|[\s(])([\-\u2013\u2014]|n/?a)\s*[:=]", re.I)


def unexplained_blanks(slides):
    """Are blank cells left with no statement of what they mean?

    All five panel members got stuck at three blank cells in one grid; they couldn't
    tell whether it meant "not run" or "run, but not meaningful." One of those cells was
    the one that decided this talk's claim.

    What isn't there is invisible to a checker. A checker reads text that exists, so it
    has no way to know that being blank is itself information. So this counts it
    separately.

    Returns: [(slide number, blank count)], only when that slide never discloses the
    meaning.
    """
    # The meaning must be disclosed on that slide. A single occurrence of "dash"
    # anywhere in the deck would let every slide's blanks pass, but the audience asks
    # on the slide where they see the blank.
    out = []
    for s in slides:
        said = (s.get("raw_screen") or "") + " " + " ".join(s.get("say") or [])
        if EXPLAINS_BLANK.search(said):
            continue
        n = 0
        for t in s.get("tables", []):
            prev_first = ""
            for row in t.get("rows", []):
                # A row with only the first cell filled is a group label: it's
                # rendered spanning the row, and its blanks aren't visible.
                if len(row) > 1 and str(row[0]).strip() and \
                        not any(str(c).strip() for c in row[1:]):
                    prev_first = str(row[0]).strip()
                    continue
                cells = list(row)
                # When the first cell is blank but the row above's first cell was
                # filled, that means "same as above," a common table shape (writing a
                # group name only on the first row) that should not count as an
                # unexplained blank.
                if cells and not str(cells[0]).strip() and prev_first:
                    cells = cells[1:]
                elif cells and str(cells[0]).strip():
                    prev_first = str(cells[0]).strip()
                n += sum(1 for c in cells
                         if not str(c).strip() or DASH.match(str(c)))
        if n:
            out.append((s.get("n"), n))
    return out


def never_drawn(slides):
    """Something compared repeatedly across several tables but never drawn even once.

    This looks uncountable at first, but the signal can be counted:

      . If the names in a table's first column repeat across several slides, those are
        the cast of characters this talk compares.
      . If there is not one figure before those characters first appear, the audience
        rides out the whole talk on names alone.

    A deck can pass every other check and still draw complaints like "there's no figure
    showing what's being compared."

    Returns: (list of cast names, slide where first seen) or None.
    """
    where = {}
    for s in slides:
        for t in s.get("tables", []):
            for row in t.get("rows", []):
                if not row:
                    continue
                lab = plain(str(row[0])).strip()
                if len(lab) < 3 or DASH.match(lab):
                    continue
                where.setdefault(lab, set()).add(s.get("n"))
    cast = sorted((lab, sorted(ns)) for lab, ns in where.items() if len(ns) >= 2)
    if len(cast) < 3:
        return None
    first = min(ns[0] for _, ns in cast)
    if any(s.get("n") <= first for s in slides if s.get("has_figure")):
        return None
    # If the first table to appear is an explanatory table (cells are mostly text,
    # planning's §prior "dimension table"), that's the introduction: it introduces the
    # cast (what it reduces, whether it's accurate), and should not be flagged with
    # "no slide draws it."
    for s in slides:
        if s.get("n") != first:
            continue
        for t in s.get("tables", []):
            cells = [plain(str(c)).strip() for r in t.get("rows", []) for c in r[1:]
                     if str(c).strip()]
            numeric = sum(1 for c in cells if re.fullmatch(r"[-+−]?[\d.,]+\s*[%×x]?", c))
            if cells and numeric * 2 < len(cells):
                return None
    return [lab for lab, _ in cast], first


_UNSUP = {v: k for k, v in deckspec._SUP.items() if k in "0123456789.-"}
_NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")


def _nums(text):
    t = "".join(_UNSUP.get(c, c) for c in str(text or ""))
    return set(float(x) for x in _NUM.findall(t))


def spoken_only_values(slides):
    """Places where a decimal the script says is not on that slide's screen.
    [(slide, [values])].

    If a number the speaker says aloud is nowhere on screen, the audience has nowhere
    to look for it: they either scramble to write it down or miss it. It's fine if the
    number is on the immediately preceding slide's screen (that's a callback while
    pointing). Standout and backup slides are excluded."""
    out, prev = [], set()
    for s in slides:
        scr = _nums(" ".join([s.get("screen") or "", s.get("lead") or "", s.get("title") or ""]))
        if s.get("kind") in ("title", "section", "standout") or s.get("backup"):
            prev = scr
            continue
        spk = set(float(x) for x in re.findall(r"(?<![\d.])\d+\.\d+", " ".join(
            str(x) for x in (s.get("say") or []))))
        miss = sorted(v for v in spk - scr - prev)
        if miss:
            out.append((s.get("n"), miss, _pasted(s)))
        prev = scr
    return out


def _pasted(s):
    """A slide with a pasted-in figure (file `path`): numbers inside it are not
    caught as on-screen text."""
    for f in [s.get("figure")] + [(s.get(k) or {}).get("figure") for k in ("left", "right")
                                  if isinstance(s.get(k), dict)]:
        if isinstance(f, dict) and (f.get("path") or f.get("grid")):
            return True
    return False


def reciprocal_forms(slides):
    """Slides where the screen and the script state the same quantity as reciprocal
    forms of each other. [(slide, screen value, script value)].

    The screen can show one exponent while the script says its reciprocal, when a
    paper has written one quantity in two forms (x and 1/x) separately without linking
    them. Both values exist in the paper, so a plain numeric check passes, and the
    audience still stalls on that slide. It's resolved if the script states both
    together (with a linking phrase).
    """
    out = []
    for s in slides:
        if s.get("kind") in ("title", "section"):
            continue
        scr = _nums(" ".join([s.get("screen") or "", s.get("lead") or ""]))
        spk = _nums(" ".join(str(x) for x in (s.get("say") or [])))
        for b in sorted(spk - scr):
            for a in sorted(scr - spk):
                # Integers coincide too often (0.1 and 10, 0.2 and 5 give false
                # positives). Only look at two proper decimals.
                if a <= 0 or b <= 0 or a == int(a) or b == int(b):
                    continue
                if abs(a * b - 1.0) <= 0.03:
                    out.append((s.get("n"), a, b))
    return out


def contradicting_values(slides):
    """Is the same term attached to two different numbers?

    One slide wrote `baseline 88.4`, another wrote `baseline 81.9`. `deckcheck` §A
    passes both because they're both numbers that exist in the paper: the question "is
    the on-screen number in the source of truth" is answered "yes" either way. But to
    the audience, the same term has two values, and nothing on screen resolves it.

    This is not a verdict, it's a list to look at: the two values might really be two
    different things.
    """
    seen = {}
    for s in slides:
        # Table cells are not looked at. Running the regex over concatenated cell text
        # would attach the table's first-column value next to a row name, flagging
        # "Fine-tune" from two tables with different columns as a contradiction.
        # Pairing by row x column still catches same-shaped tables placed one per
        # model on separate slides against each other. A table's values are defined by
        # that table's header; what this check looks for is a written-in-prose
        # "baseline 88.4".
        txt = plain(s.get("prose_screen", s.get("raw_screen")) or "")
        for m in re.finditer(r"([A-Za-z][A-Za-z-]{3,})\s*[:=]?\s*"
                             # A decimal is read to its end, or "0.01" gets truncated
                             # to "0.0" and a nonexistent value gets flagged.
                             r"(\d{1,3}\.\d+)(?![\d.])", txt):
            lab = m.group(1).lower()
            # A word preceded by a number is a quantity ("18 layers", "VOC 07 test"):
            # it names something different per row, so two different values aren't a
            # contradiction.
            if re.search(r"\d\s*$", txt[:m.start()]):
                continue
            # A modifier is not a name: "only 0.7" and "only 1.1" are two different
            # values, not two values of the same term.
            if lab in STOP or lab in HEDGE:
                continue
            # A name attached in front is part of the term: "Model A baseline 8.15"
            # and "Model B baseline 6.95" are two different terms. Without splitting
            # the names out, they would be lumped into one "baseline" and flagged. A
            # name is recognized as a word containing a capital letter; if the verb in
            # "reaches baseline" were attached too, a real contradiction ("the
            # baseline 88.4" vs. "reaches baseline 81.9") would be split into two
            # terms and vanish.
            # A word that is capitalized only in its first letter ("First") is not
            # treated as a name, since text made by concatenating a title and a
            # bullet has the last word of the title right before the bullet's first
            # word. A name is recognized as a capital letter or digit after the
            # second character ("ResNet", "GPT-4") or a single capital letter
            # ("Model B").
            pre = re.search(r"([A-Za-z][\w-]*)\s+$", txt[:m.start()])
            if pre:
                w = pre.group(1)
                if ((re.fullmatch(r"[A-Z]", w) or re.search(r"[A-Z0-9]", w[1:]))
                        and w.lower() not in HEDGE):
                    lab = w.lower() + " " + lab
            seen.setdefault(lab, {}).setdefault(m.group(2), set()).add(s.get("n"))
    out = []
    for lab, vals in seen.items():
        # A contrast within a single slide is not a contradiction: a sentence like
        # "fast charge costs the dry cell 31.5, slow charge the dry cell 4.25" sets
        # two values against each other on purpose. What should be flagged is the
        # same term holding a different value on a different slide.
        slides_of = [frozenset(ns) for ns in vals.values()]
        if len(vals) > 1 and len(frozenset().union(*slides_of)) > 1:
            out.append((lab, sorted((v, sorted(ns)) for v, ns in vals.items())))
    return sorted(out)


# Verbs/auxiliaries common in talk titles. If even one is present, treat it as a
# sentence stating a claim.
# This is a list, not grammatical parsing. It's deliberately biased toward missing
# cases, since false positives burying the real problem has been a recurring failure
# in this skill.
# Base forms of verbs are listed and their inflections are attached automatically.
# Hand-typing each inflected form instead would miss forms like `removes`/`hurt`/`hit`
# and flag complete sentence titles as "labels."
_VERB_BASES = (
    "be do have can could will would may might should must shall "
    "add affect agree allow appear apply arrive ask avoid become begin "
    "behave believe belong break bring build buy call carry cause change "
    "check choose climb close come compare contain continue cost count "
    "cover create cross cut decide decline decrease degrade depend describe "
    "differ disappear divide double drive drop earn end enter erase explain "
    "fail fall feel fill find finish fit fix flip follow force forget gain "
    "get give go grow guide happen help hide hit hold hurt improve include "
    "increase indicate keep kill know land last lead learn leave let lift "
    "limit link live look lose lower make match matter mean measure meet "
    "miss move need offer open outperform own pass pay pick place plateau "
    "play point predict prefer prevent produce protect prove prune pull "
    "push put raise reach read recover reduce remain remove repeat replace "
    "report require reveal rise rule run save say scale see seem sell send "
    "separate set shift show shrink sit slip slow solve spend split spread "
    "stand start stay stop succeed suffer suggest support survive swap "
    "take talk tell tend think tie track transfer trigger triple try turn "
    "undo use vanish vary wait want warn win work worsen yield "
    "allocate answer bear beat order share span "
    "fade drift collapse spike flatten outlast outweigh overtake exceed "
    "converge diverge dominate saturate generalize generalise underperform"
).split()
_IRREG = ("is are was were been being am did does done has had "
          "broke broken brought built bought came chose cut drove fell felt "
          "found gave went gone grew held hid kept knew led left lost made "
          "meant met paid put ran rose said saw seen sold sent set shrank "
          "sat spent split spread stood took told thought won wore").split()


def _forms(b):
    out = {b, b + "s", b + "ed", b + "ing", b + "es"}
    if b.endswith("e"):
        out |= {b + "d", b[:-1] + "ing"}
    if b.endswith("y") and len(b) > 2 and b[-2] not in "aeiou":
        out |= {b[:-1] + "ies", b[:-1] + "ied"}
    if len(b) <= 4 and b[-1] in "tpgnm" and b[-2] in "aeiou":
        out |= {b + b[-1] + "ed", b + b[-1] + "ing"}       # stop -> stopped
    return out


_VERBS = set(_IRREG)
for _b in _VERB_BASES:
    _VERBS |= _forms(_b)
TITLE_VERB = re.compile(r"\b(" + "|".join(sorted(_VERBS, key=len, reverse=True))
                        + r")\b", re.I)
def is_claim(title):
    """Does the title have a predicate?

    If the verb is the last word only and the title is two words or fewer, it's a
    label ("Related work", "Future work"). From three words on, it's a spoken line
    ("The bench we used", "Three things we never tested", "Then the cheap cell wins").
    Treating a short verb-final title as a label would push a human-written spoken
    title toward being treated as a label, which in turn would push toward copying the
    paper's result sentence straight into a title instead. If it ends in a period,
    it's treated as a sentence.
    """
    s = str(title or "").strip()
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", s)
    if not words:
        return False
    # If a word follows a personal pronoun, it's a clause ("The two cells we
    # store"), a spoken line even with a verb not in the verb list. `this` is
    # excluded since it can be a determiner.
    if len(words) >= 3 and re.search(r"\b(we|you|they|I)\s+[A-Za-z]", s):
        return True
    hits = [i for i, w in enumerate(words) if TITLE_VERB.fullmatch(w)]
    if not hits:
        # A title over six words is a sentence using a verb outside the verb list,
        # such as "an RPC device pool feeds the optimizer its measurements." Labels
        # are short ("Results", "Related work", "per-valve readings").
        return len(words) >= 6
    if any(i < len(words) - 1 for i in hits):
        return True
    if len(words) >= 3:
        return True
    return s.endswith((".", "!"))


# "First: ..." / "Second: ..." are titles where the speaker states an order.
# planning's §factors permits this format, and it should not be flagged as a label.
SEQUENCE_MARK = re.compile(r"^\s*(first|second|third|fourth|next|then|finally|last)\s*[:,\u2014\-]",
                           re.I)
BACKUP_PREFIX = re.compile(r"^\s*(backup|appendix|extra)\s*[:\-\u2014]\s*", re.I)


def names_not_claims(slides):
    """Slides whose title only labels the content. (number, is backup, title).

    A question title (`?`) passes because it promises an answer. A slide that has
    the answer written in `lead` also passes; it only needs a claim somewhere on
    screen.
    """
    out = []
    for s in slides:
        # For a standout slide, `big` itself is the claim. Since that occupies the
        # title spot, judging it here would wrongly flag it as "made no claim."
        if s.get("kind") == "standout":
            continue
        title = str(s.get("title") or "").strip()
        if not title:
            continue
        bare = BACKUP_PREFIX.sub("", title)
        if "?" in bare or is_claim(bare) or SEQUENCE_MARK.match(bare):
            continue
        if str(s.get("lead") or "").strip():
            continue
        out.append((s.get("n"), bool(s.get("backup")), title))
    return out


TITLE_COPY_RUN = 5      # this many consecutive words matching the paper counts as copied
_FUNC = set("a an the as in of to for on at by with and or is are was were be been it its "
            "that this these those from than into each per not no we our".split())


def _wordrun(s):
    return re.findall(r"[a-z0-9]+", plain(str(s or "")).lower())


def titles_copied_from_paper(slides, paper):
    """Titles that copy a paper sentence verbatim. (number, consecutive matching word
    count, title).

    A title is what the speaker says to the audience. In one example deck, the main
    slides' titles matched the paper for at most 4 consecutive words. A title that
    runs 5-8 words with the paper usually means a results paragraph's first sentence
    was copied straight into the title, which turns the deck into a slide-by-slide
    listing of the paper.
    """
    pw = _wordrun(paper)
    k = TITLE_COPY_RUN
    grams = set(tuple(pw[i:i + k]) for i in range(len(pw) - k + 1))
    out = []
    for s in slides:
        # A standout slide's title can match the paper, since it is the claim itself.
        if s.get("backup") or s.get("kind") in ("title", "section", "standout"):
            continue
        tw = _wordrun(s.get("title") or "")
        if len(tw) < k:
            continue
        best = 0
        for i in range(len(tw) - k + 1):
            if tuple(tw[i:i + k]) not in grams:
                continue
            j = i + k
            while j < len(tw) and tuple(tw[i:j + 1][-k:]) in grams:
                j += 1
            # Copying is a run of content words. "as a power law in" is three
            # function words out of five, so counting raw word runs alone would flag
            # it for coincidentally overlapping with a caption in the appendix.
            if len([w for w in tw[i:j] if w not in _FUNC]) < 3:
                continue
            best = max(best, j - i)
        if best:
            out.append((s.get("n"), best, s.get("title") or ""))
    return out


def undirected_slides(slides):
    """Main-deck slide numbers with no delivery direction (`cue`/`note`).

    One example deck had a note on every slide: how many seconds, where to point,
    what to say and move on from. With only a script (`say`), the speaker only reads
    it.
    """
    return [s.get("n") for s in slides
            if not s.get("backup") and s.get("kind") not in ("title", "section")
            and not (str(s.get("cue") or "").strip()
                     or str(s.get("note") or "").strip())]


PAPER_DIR = re.compile(r"(^|[\\/])(paper|figs?|figures?|manuscript)[\\/]", re.I)


def pasted_paper_figures(slides, roots=()):
    """Figures pulled straight from the paper, unchanged. (number, path).

    "Abandon the practice of putting a paper's figure straight into a talk"
    (Rougier, Droettboom & Bourne 2014, PLoS Comput Biol 10(9):e1003833, Rule 3).
    "Don't copy a paper's table from a PDF and paste it onto a slide. Rebuild it to
    be readable" (Michael Ernst, UW). Projected, the lines get thin, the text gets
    small, and vertical text appears. Split a multi-panel figure into one panel per
    slide (Naegle 2021, Rule 6).

    The judgment criterion is the path. A figure the skill drew starts with
    `chart_`/`diagram_` and is excluded automatically. A hand-made talk-only figure
    (`talk_*`) is excluded too.
    """
    out = []
    for s in slides:
        # A backup slide is not part of the main deck. A paper figure carrying no
        # numeric data has no way to be redrawn, and if a question comes up, showing
        # that figure itself is the answer.
        if s.get("backup"):
            continue
        for where, f in _figures_of(s):
            p = str((f or {}).get("path") or "")
            if not p:
                continue
            # A figure with a marked point of focus (`highlight`) is the path taken
            # when a result only exists as a figure (planning §plots). There's no
            # number to redraw, so it's not something to warn about.
            if (f or {}).get("highlight"):
                continue
            # Something declared, with a reason, to not be a data figure (`picture`).
            # Without this, a map could be seen as a chart and flagged, forcing a
            # highlight onto a figure that had no point to look at.
            if str((f or {}).get("picture") or "").strip():
                continue
            base = os.path.basename(p)
            if base.startswith(("chart_", "diagram_", "talk")):
                continue
            # Photos are used as-is, because they can't be redrawn. Only charts and
            # diagrams are flagged.
            found = None
            for r in roots:
                for q in (os.path.join(r, p), os.path.join(r, base)):
                    if os.path.isfile(q):
                        found = q
                        break
                if found:
                    break
            if found and deckspec.is_photo(found):
                continue
            out.append((s.get("n"), p))
    return out


def _figures_of(s):
    got = []
    if s.get("figure"):
        got.append(("self", s["figure"]))
    # Looks at panes flattened out. Not looking inside `parts` for figures would let
    # a paper figure fall out of the list.
    for side, p in deckspec.panes(s):
        for leaf in deckspec.pane_leaves(p):
            if leaf.get("figure"):
                got.append((side, leaf["figure"]))
    return got


NUMERIC_CELL = re.compile(r"^\s*[+\u2212-]?\d+(\.\d+)?\s*%?\s*$")


def concept_before_results(slides):
    """How many figures come before the first results slide. (first results slide
    number, figure count before it).

    A concept figure comes before the first results slide. It states, with a figure
    first, what the subject is, what it's made of, and what's being varied, and only
    then gives the numbers.

    Going straight to results with no figure hands the audience numbers without them
    knowing what's being measured. All that's left then is reading a table, and that's
    a report, not a talk. `diagram: {kind: strip|pipeline|flow|stack|grid}` draws that
    spot.
    """
    first = None
    seen_fig = 0
    for i, s in enumerate(slides):
        if s.get("backup"):
            continue
        nums = 0
        for t in (s.get("tables") or []):
            # An explanatory table (cells are mostly text, planning's §prior
            # dimension table) is not a result, or a prior-work table's size column
            # would get "no figure before the first numeric slide" flagged even
            # though it follows the paper's order. Uses the same rule as the
            # cast-of-characters check (a results table needs at least half its cells
            # to be numeric).
            _cells = [c for r in (t.get("rows") or []) for c in r[1:] if str(c).strip()]
            _n = sum(1 for c in _cells if NUMERIC_CELL.match(str(c)))
            if _cells and _n * 2 >= len(_cells):
                nums += _n
        if first is None and nums >= 4:
            first = s.get("n") or (i + 1)
            break
        if s.get("has_figure"):
            seen_fig += 1
    return first, seen_fig


def _marks_in(d):
    """Does one diagram contain at least one emphasis mark?"""
    if not isinstance(d, dict):
        return False
    for b in (d.get("boxes") or []):
        if isinstance(b, dict) and b.get("mark"):
            return True
    for r in (d.get("rows") or []):
        if not isinstance(r, dict):
            continue
        if r.get("mark_at") is not None:
            return True
        for c in (r.get("cells") or []) + (r.get("stages") or []):
            if isinstance(c, dict) and c.get("mark"):
                return True
    for k in ("cells", "stages", "boxes"):
        for c in (d.get(k) or []):
            if isinstance(c, dict) and c.get("mark"):
                return True
    return bool(d.get("mark_at") is not None)


def _boxes_of(d):
    """Every named box inside a diagram. A list of (label,)."""
    out = []
    for b in (d.get("boxes") or []):
        out.append(str(b.get("label", "")) if isinstance(b, dict) else str(b))
    for r in (d.get("rows") or []):
        if not isinstance(r, dict):
            continue
        for c in (r.get("cells") or []) + (r.get("stages") or []):
            out.append(str(c.get("label", "")) if isinstance(c, dict) else str(c))
    for k in ("cells", "stages"):
        for c in (d.get(k) or []):
            out.append(str(c.get("label", "")) if isinstance(c, dict) else str(c))
    return [x for x in out if x.strip()]


def focus_candidate(s, d):
    """The box in this diagram that looks like it is where the argument hinges. None
    if there isn't one.

    Picked from what the slide is already saying: the title/lead/bullets are the
    claim, and the box whose words overlap that claim the most is the spot. It
    doesn't invent a new claim. It only picks, and it also gives the reason for the
    pick, so a wrong pick is immediately visible.
    """
    claim = " ".join([str(s.get("title") or ""), str(s.get("lead") or "")]
                     + [str(x) for x in (s.get("bullets") or [])])
    cw = {w for w in toks(claim)} - STOP
    if not cw:
        return None
    best, score = None, 0.0
    for lab in _boxes_of(d):
        lw = {w for w in toks(lab)} - STOP
        if not lw:
            continue
        hit = len(lw & cw) / float(len(lw))
        if hit > score:
            best, score = lab, hit
    return best if score >= 0.5 else None


def flat_diagrams(slides):
    """Diagrams with nothing telling you where to look. (total count,
    [(slide number, title)]).

    If every box is the same color, the screen doesn't say which one carries the
    argument. A concept figure usually has exactly one box in the emphasis color.
    `looking.md` §5 says only "use color sparingly" and leaves out "use it
    somewhere," but that's exactly a figure's job.

    A neutral taxonomy diagram may correctly have no emphasis. So this returns a
    list, not a verdict; the caller decides by looking at whether it's "most of
    them."
    """
    total, flat = 0, []
    for s in slides:
        for where in ("self", "left", "right"):
            owner = s if where == "self" else (s.get(where) or {})
            d = owner.get("diagram")
            if not d:
                continue
            total += 1
            if not _marks_in(d):
                flat.append((s.get("n"), str(s.get("title") or "")[:46],
                             focus_candidate(s, d)))
    return total, flat


_NAME_STOP = {"per", "of", "the", "a", "an", "and", "or", "in", "on", "by", "with", "for",
              "to", "no", "one", "all", "each"}


def _name_tokens(name):
    return [t for t in re.findall(r"[a-z0-9][a-z0-9.+-]*", plain(str(name)).lower())
            if len(t) > 1 and t not in _NAME_STOP]


def name_grids(slides):
    """`grid` diagrams whose cells only name the row-and-column combination. [(slide, title)].

    Two blind trials drew a design's two factors this way and nothing else: rows of one
    factor, columns of the other, each cell the name of the pair. The slide says which
    combinations exist and nothing about what either factor does (planning §factors).
    A cell counts as a name when it repeats a word of its row or column name; the grid is
    flagged when two thirds of its filled cells do. It may be fine as a map of the design
    after the factors are drawn, so this is advice, not a failure."""
    out = []
    for s in slides:
        if s.get("backup"):
            continue
        for where in ("self", "left", "right"):
            owner = s if where == "self" else (s.get(where) or {})
            d = owner.get("diagram")
            if not isinstance(d, dict) or d.get("kind") != "grid":
                continue
            rows, cols = list(d.get("rows") or []), list(d.get("cols") or [])
            boxes = list(d.get("boxes") or [])
            if len(rows) < 2 or len(cols) < 2:
                continue
            filled = named = 0
            for i, b in enumerate(boxes):
                b = b if isinstance(b, dict) else {"label": b}
                lab = plain(str(b.get("label") or "")).lower()
                if not lab.strip() or b.get("mark") == "blank":
                    continue
                r, c = divmod(i, len(cols))
                if r >= len(rows):
                    break
                filled += 1
                toks = _name_tokens(rows[r]) + _name_tokens(cols[c])
                if any(t in lab for t in toks):
                    named += 1
            if filled >= 3 and named * 3 >= filled * 2:
                out.append((s.get("n"), str(s.get("title") or "")[:46]))
    return out


def paper_text(meta, spec_path):
    """The text of the source of truth `meta.paper` points to. (None, reason) if
    missing or unreadable.

    The path is relative to the spec file. A checker whose result changes depending
    on where it's run from is worse than not running it at all.
    """
    raw = (meta or {}).get("paper")
    if not raw:
        return None, "meta.paper is missing"
    paths = raw if isinstance(raw, list) else [raw]
    base = os.path.dirname(os.path.abspath(str(spec_path)))
    got, miss = [], []
    for p in paths:
        fp = p if os.path.isabs(str(p)) else os.path.join(base, str(p))
        if os.path.isfile(fp):
            try:
                got.append(deckspec.read_paper(fp))
            except Exception:
                miss.append(str(p))
        else:
            miss.append(str(p))
    if not got:
        return None, "not found: %s" % ", ".join(miss)
    return "\n".join(got), ("not found: %s" % ", ".join(miss)) if miss else ""


def deck_words(slides):
    """All text that appears on screen: title, lead, bullets, table, names inside
    figures."""
    out = []
    for s in slides:
        if s.get("backup"):
            continue
        # `screen` already holds the title and the lead. Adding them again counted a
        #   title word twice.
        out += [s.get("screen") or "", s.get("fig_words") or ""]
    return " ".join(out)


def spec_meta(path):
    """The spec's `meta`. An empty mapping when the slide list was given as JSON."""
    try:
        with io.open(path, encoding="utf-8") as f:
            if f.read().lstrip().startswith("["):
                return {}
    except Exception:
        return {}
    try:
        return load(path)[0] or {}
    except Exception:
        return {}


def thesis_of(meta, slides):
    """The one sentence the talk is trying to say, and where it came from.

    If it isn't written down, there's no way to check it. Falling back to the last
    standout slide is a second-best option: a closing slide usually carries the
    claim.
    """
    said = plain((meta or {}).get("thesis") or "").strip()
    if said:
        return said, "meta.thesis"
    outs = [s for s in slides
            if s.get("kind") == "standout" and not s.get("backup")]
    if outs:
        return (outs[-1].get("title") or "").strip(), "last standout slide"
    return "", ""


def _words(s):
    return set(toks(str(s or "")))


def _standout_words_text(s):
    """All text that appears on screen for a standout slide: title, lead, lines, big
    number, bullets, flow cells.

    Bullets need to be read too: layouts.md's standout/flow example puts the
    conclusion in `bullets:`, and skipping them would flag a deck that follows that
    example as low claim overlap.
    """
    parts = [s.get("title") or "", s.get("lead") or "", s.get("screen") or ""]
    parts += [str(x) for x in (s.get("lines") or [])]
    parts += deckspec.big_parts(s.get("big"))
    parts += [deckspec.bullet_of(b)[0] for b in (s.get("bullets") or [])]
    fl = s.get("flow")
    if isinstance(fl, list):
        parts += [str(x.get("text") if isinstance(x, dict) else x) for x in fl]
    return " ".join(parts)


def standouts_off_thesis(slides, thesis):
    """Per standout slide: (slide number, overlapping words, title). Ordered by
    least overlap first."""
    want = _words(thesis)
    out = []
    for s in slides:
        if s.get("kind") != "standout" or s.get("backup"):
            continue
        # Question slides are excluded. planning's §question says not to put the
        # conclusion's words on that slide, so judging claim overlap there would
        # collide with that guideline.
        if "?" in " ".join([str(s.get("lead") or ""), str(s.get("title") or "")]):
            continue
        got = _words(_standout_words_text(s))
        out.append((s.get("n"), sorted(want & got), (s.get("title") or "")))
    return sorted(out, key=lambda x: len(x[1]))


def thesis_coverage(slides, thesis):
    """How much of the claim the last standout slide echoes back (0-1, None if
    there isn't one)."""
    want = _words(thesis)
    outs = [s for s in slides
            if s.get("kind") == "standout" and not s.get("backup")]
    if not outs or not want:
        return None
    # Looks at everything that appears on screen. Reading only the title/lead would
    # undercount a claim sentence written verbatim into `lines`.
    o = outs[-1]
    got = _words(_standout_words_text(o))
    return len(want & got) / float(len(want))


def read_slides(path):
    """Decides by content, not extension: also accepts JSON saved with a `.txt` name."""
    with io.open(path, encoding="utf-8") as f:
        raw = f.read()
    if raw.lstrip().startswith("["):
        return json.loads(raw)
    return from_spec(path)


def main(path):
    slides = read_slides(path)

    print("=" * 72)
    print("0. Does the title state a claim?")
    print("=" * 72)
    named = names_not_claims(slides)
    nb = [x for x in named if x[1]]
    if named:
        for n_, bk, ttl in named:
            print("   %3s %s %s" % (n_, "backup" if bk else "main", ttl[:56]))
        print("   %d slide(s) whose title only labels the content (%d backup)"
              % (len(named), len(nb)))
        print("     A title has to say what that slide answers. A table is evidence, not an answer.")
        if nb:
            print("     This goes double for backup slides: during the ~15 seconds a")
            print("       backup slide sits on screen after a question, all the audience")
            print("       reads is the title, and no explanation follows.")
            print("     (Basis: this is a derivation. \"a backup slide's title should")
            print("      state the answer\" doesn't exist as such in the academic")
            print("      literature. It follows from general rules: Doumont asks whether the")
            print("      title conveys the message, and whether it is a complete sentence with a")
            print("      subject and a verb; Alley & Neeley 2005 say \"on every slide")
            print("      except the cover\"; Naegle 2021 Rule 8 says to let someone who tuned")
            print("      out still walk away with the point.")
            print("      There is an opposing convention too: Munter says to keep a")
            print("      backup slide's title the same as the table of contents")
            print("      (easy to find under pressure). The two are compatible: solve the")
            print("      finding problem with a section header, and use the title line")
            print("      for the answer.)")
            print("       (Measured: one example deck's main slides were 88% sentence or")
            print("        question, the generated deck's main slides 100%, but its")
            print("        backup slides only 29%. The gap showed up only here.)")
        print("     Two ways to fix it: turn the title into a sentence or a question,")
        print("     or write the answer in one line with `lead:`.")
    else:
        print("   Every title states a claim or asks a question.")

    # A standout slide is the talk's peak moment. If it asks about something other
    # than what the paper is trying to say at that point, the audience's focus gets
    # spent elsewhere.
    meta = spec_meta(path) if isinstance(path, str) else {}

    # Which paper did this come from. If that isn't stated, no checker can
    # cross-check anything, and the deck goes out without ever having been checked
    # against the paper.
    print()
    print("0a. Which paper this deck comes from")
    _paper, _why = paper_text(meta, path) if isinstance(path, str) else (None, "")
    if _paper is None:
        print("   points to no source of truth: %s." % _why)
        print("     Then no checker can cross-check whether the deck's words match")
        print("     the paper's words. The first place a talk drifts from the paper is")
        print("     the words, not the numbers.")
        print("     Write it like `meta: {paper: ../paper/paper.tex}` (a list works too).")
    else:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import deckcheck
            _ok = set(str(x).lower() for x in (meta.get("coined_ok") or []))
            # A deliberately simplified term is disclosed in `meta.coined_ok`, the
            # same spot deckcheck uses.
            coined = [c for c in deckcheck.coined_terms(deck_words(slides), _paper, 3)
                      if c[0] not in _ok]
            copied = titles_copied_from_paper(slides, _paper)
        except Exception as e:                      # pragma: no cover
            copied = []
            coined, e = [], e
            print("   (could not cross-check: %s)" % e)
        if _why:
            print("   %s" % _why)
        print("   source of truth: %d chars · terms the deck uses 3+ times that aren't "
              "in the paper: %d kinds"
              % (len(_paper), len(coined)))
        for w, n in coined[:12]:
            print("   %-26s deck %d times · paper 0 times" % (w, n))
        if len(coined) > 12:
            print("   ... and %d more kinds" % (len(coined) - 12))
        if copied:
            print("   %d title(s) copy a paper sentence verbatim" % len(copied))
            for n_, run_, ttl in copied:
                print("     %3s  matches the paper for %d consecutive words: %s" % (n_, run_, ttl[:52]))
            print("     A title is what the speaker says to the audience. Send the")
            print("     paper's result sentence to `lead`/`say`, and write in the title")
            print("     the one line you will say aloud on that slide")
            print("     (references/planning.md §voice \"The voice\").")
        if coined:
            print("     If the word the audience hears differs from the paper's, they'll")
            print("     end up calling the same thing by two names during Q&A. Switch to")
            print("     the paper's word.")

    thesis, src = thesis_of(meta, slides)
    outs = [s for s in slides
            if s.get("kind") == "standout" and not s.get("backup")]
    if outs:
        print()
        print("0b. Do the standout slides serve the paper's claim?")
        if not thesis:
            print("   The claim is unknown. Write, in `meta.thesis:`, the one")
            print("     sentence stating why this talk exists. Without it, nobody,")
            print("     including the person who wrote it, can see whether the")
            print("     standout slides serve that claim.")
        else:
            print("   claim (%s): %s" % (src, thesis[:66]))
            off = [x for x in standouts_off_thesis(slides, thesis)
                   if len(x[1]) < 2]
            for n_, sh, ttl in off:
                print("   slide %3s: %d word(s) overlap the claim%s: %s"
                      % (n_, len(sh),
                         (" (" + ", ".join(sh) + ")") if sh else "", ttl[:44]))
            if off:
                print("     A standout slide is the talk's peak. Asking something")
                print("     other than what the paper is trying to say right there means")
                print("     every slide after it answers that question instead of the")
                print("     real thesis. Rewrite it with the claim's own words.")
            cov = thesis_coverage(slides, thesis)
            if cov is not None and cov < 0.5 and src == "meta.thesis":
                print("   The last standout slide covers only %d%% of the claim."
                      % round(cov * 100))
                print("     A talk should end on that one sentence, and that is also all")
                print("     the audience takes away: let the last slide be the claim")
                print("     itself.")
            if not off and (cov is None or cov >= 0.5):
                print("   All %d standout slides serve the claim." % len(outs))

    bare = undirected_slides(slides)
    _main = [s for s in slides if not s.get("backup")
             and s.get("kind") not in ("title", "section")]
    if _main and len(bare) * 2 > len(_main):
        print()
        print("   Of %d main slides, %d have no delivery direction (`cue`/`note`): %s"
              % (len(_main), len(bare), ", ".join(str(x) for x in bare[:12])))
        print("     With only a script, the speaker only reads it. Write it on every")
        print("     slide: what to point to first, whether to pose a question and")
        print("     wait, how many seconds.")

    first_res, pre_fig = concept_before_results(slides)
    if first_res is not None and pre_fig == 0:
        print()
        print("   Not one figure comes before the first numeric slide (slide %s)." % first_res)
        print("     The audience gets numbers without knowing what's being measured:")
        print("     all that's left then is reading a table, and that's a report, not a")
        print("     talk.")
        print("     A concept figure comes before the first results slide: it states")
        print("     what's being measured with a figure first.")
        print("     Draw it with `diagram:`:")
        print("       strip     a strip of named boxes. What something is made of")
        print("                 (give `bars`/`groups` for grouped bars: weeks, windows,")
        print("                 chunks)")
        print("       pipeline  a flow of stages. Structure, data flow, where it was")
        print("                 touched")
        print("       flow/stack/grid  other diagram shapes")

    n_dia, flat = flat_diagrams(slides)
    if n_dia and len(flat) * 2 >= n_dia:
        print()
        print("   Of %d diagrams, %d have no emphasis at all." % (n_dia, len(flat)))
        for n_, ttl, pick in flat[:6]:
            print("       %3s  %s" % (n_, ttl))
            if pick:
                print("            box overlapping what this slide says: \"%s\"" % pick)
        if len(flat) > 6:
            print("       ... and %d more" % (len(flat) - 6))
        print("     If every box is the same color, the screen doesn't say where to")
        print("     look. That's exactly a figure's job. A concept figure usually has")
        print("     one box in the emphasis color: put `mark` on the one that carries")
        print("     the argument.")
        print("     (Green `safe` for the box that carries the argument, role colors a-f")
        print("     for a plain distinction.)")
        # Only prints this note when at least one of the listed diagrams has a pick,
        # or the note would describe something that isn't there.
        if any(pick for _n, _t, pick in flat[:6]):
            print("     (This points to the box whose words overlap the")
            print("      title/lead/bullets. It's only a pick, not a new claim: pick")
            print("      a different box yourself if this one is wrong.)")
        print("     (`looking.md` §5 only says \"use color sparingly.\" Using it")
        print("      sparingly and not using it at all are different things.)")

    for n_, ttl in name_grids(slides):
        print()
        print("   ! slide %s: a grid whose cells name each row-and-column pair (%s)." % (n_, ttl))
        print("     It shows which combinations exist, not what either factor changes.")
        print("     Draw each factor first (planning §factors): the thing it changes, in its")
        print("     settings, from the paper's definition. Keep this grid after them as a")
        print("     map of the design, or drop it.")

    _sd = os.path.dirname(os.path.abspath(path))
    _fd = str((spec_meta(path) or {}).get("figdir") or "figs")
    pasted = pasted_paper_figures(slides, (_sd, os.path.join(_sd, _fd),
                                           os.path.join(_sd, "out", "figs")))
    if pasted:
        print()
        print("   %d slide(s) paste the paper's chart/diagram unchanged (photos excluded):" % len(pasted))
        for n_, p in pasted:
            print("       %3s  %s" % (n_, p))
        print("     \"Abandon the practice of putting a paper's figure straight into a talk\"")
        print("       (Rougier, Droettboom & Bourne 2014, PLoS Comput Biol, Rule 3).")
        print("     Projected, the lines get thin and the text gets small. Thicken the")
        print("     lines, enlarge the text, remove vertical text, and split a")
        print("     multi-panel figure into one panel per slide.")
        print("     (Excludes the skill's own `chart_*`/`diagram_*` figures and talk-only `talk*` figures.)")
        # The path for a data figure with no coordinates left to redraw. Without
        # this, the warning could be silenced with `picture:` (a photo/map
        # declaration) even for a numeric-image figure like a scatter plot.
        print("     A data figure whose values aren't in the manuscript can mark where to look with")
        print("     `highlight`, which drops it from this list. `picture:` declares a non-data figure")
        print("     (photo, map, device); don't use it here.")

    print()
    print("=" * 72)
    print("1. Title-first-sentence overlap rate")
    print("=" * 72)
    bad = []
    for s in slides:
        say = s.get("say") or []
        # A conclusion (standout) slide is where the claim is deliberately restated.
        # SKILL says to do exactly that, so it should not be flagged as repetition.
        if not say or not s.get("title") or s.get("kind") == "standout":
            continue
        r = overlap(s["title"], say[0])
        if r >= 0.6:
            bad.append((s.get("n"), r, s["title"]))
            print("   %3s  %3.0f%%  %s" % (s.get("n"), r * 100, s["title"][:52]))
    print("   60%% or more overlap: %d / %d slides" % (len(bad), len(slides)))

    print()
    print("=" * 72)
    print("2. First appearance of a term: screen (title/bullets/table) vs. voice (script)")
    print("=" * 72)
    terms = sys.argv[2:] or []
    if not terms:
        print("   (pass terms as arguments to measure this:  prose_audit.py script.json Term1 Term2)")
    for t in terms:
        scr = spk = None
        for s in slides:
            n = s.get("n")
            face = s.get("screen") or s.get("title", "")
            if scr is None and re.search(re.escape(t), face, re.I):
                scr = n
            if spk is None and any(re.search(re.escape(t), x, re.I) for x in s.get("say") or []):
                spk = n
        flag = "! " if (scr is not None and spk is not None and spk > scr) else "  "
        print("   %s %-18s screen %s · voice %s" % (flag, t, scr, spk))

    print()
    print("=" * 72)
    print("3. Put on screen but never said aloud")
    print("=" * 72)
    mute = unspoken_terms(slides)
    if not mute:
        print("   none: every abbreviation/symbol on screen appears at least once in the script.")
    else:
        # Prints all of them. Cutting off at a fixed count and leaving only "and 23
        # more" would force anyone who wanted the full list to write their own script.
        # Groups them one line per slide to keep it from running long.
        # The first column of a table with four or more row names (prior work,
        # method list) is grouped separately. Following this section's advice to
        # name each one aloud would mean reading seven names in one breath, which the
        # audience panel called a "name bomb." A list's names only need to say what
        # the table compares, plus one or two rows pointed out.
        _rowlab = {}
        for s in slides:
            for t in s.get("tables", []):
                rows_ = [r for r in (t.get("rows") or []) if r]
                if len(rows_) >= 4:
                    for r in rows_:
                        _rowlab.setdefault(s.get("n"), set()).update(JARGON.findall(str(r[0])))
        by, lists = {}, {}
        for n, w in mute:
            (lists if w in _rowlab.get(n, ()) else by).setdefault(n, []).append(w)
        for n in sorted(by, key=lambda x: (x is None, x)):
            print("   slide %3s  %s" % (n, ", ".join(by[n])))
        if by:
            print("   The audience can only read this; they never hear it explained. If a")
            print("     table column name or setting name gets flagged here, treat that")
            print("     table as unreadable.")
            print("     Add a line to `say`. Only drop it from the screen when it's")
            print("     decorative: if it's a setting or name the paper reports, say")
            print("     it instead of dropping it (dropping it makes diffcheck report")
            print("     it as \"only on a backup slide\").")
        for n in sorted(lists, key=lambda x: (x is None, x)):
            print("   (info) slide %3s  %d row name(s) from a list table (%s): don't read"
                  % (n, len(lists[n]), ", ".join(lists[n][:4]) + (" ..." if len(lists[n]) > 4 else "")))
            print("           them one by one. Say what the table compares and point out only")
            print("           one or two rows. Calling out every name makes it a name bomb.")

    print()
    print("=" * 72)
    print("4. Spots where the audience trips (what the panel used to catch)")
    print("=" * 72)
    stuck = 0
    key = colour_key_missing(slides)
    if key and key.startswith("(info)"):
        print("   %s" % key)
        key = None
    if key:
        stuck += 1
        print("   %s" % key)
        print("     Color is used through `<hit>`/`<safe>`, but what red means is")
        print("     never stated. A reader can't tell whether green means \"good\" or")
        print("     \"not significant.\"")
    for n, said_n, got, what in count_mismatch(slides):
        stuck += 1
        print("   slide %3s  the text says %d but there are %d %s" % (n, said_n, got, what))
    bad_vals = contradicting_values(slides)
    for lab, vals in bad_vals[:6]:
        stuck += 1
        print("   \"%s\" has more than one value: %s"
              % (lab, " · ".join("%s (slide %s)" % (v, ",".join(str(x) for x in ns))
                                 for v, ns in vals)))
    if bad_vals:
        print("     If the same term carries two values, the audience can't tell which")
        print("     one is right.")
        print("     If they really are two different things, give them different")
        print("     names: this isn't a verdict, it's a place to look.")
    for n, vals, pasted in spoken_only_values(slides):
        if pasted:
            print("   (info) slide %3s  the script says %s but it's not on screen: fine if it's inside a pasted-in figure"
                  % (n, ", ".join("%g" % v for v in vals)))
            continue
        stuck += 1
        print("   slide %3s  the script says %s but it's not on screen" % (n, ", ".join("%g" % v for v in vals)))
        print("     If the audience has nowhere to look for a number they heard, they")
        print("     miss it. Put one line (even in `fine`) on that slide instead of")
        print("     dropping it.")
    for n, a, b in reciprocal_forms(slides):
        stuck += 1
        print("   slide %3s  screen says %g, script says %g: reciprocals of each other (%g x %g ≈ 1)" % (n, a, b, a, b))
        print("     Stating the same quantity in two forms makes the audience hear it as")
        print("     two different things. Pick one form, or say both together in the")
        print("     script (\"2.5, that is one over 0.4\", stating both values).")
    blanks = unexplained_blanks(slides)
    if blanks:
        stuck += 1
        print("   %d blank cell(s) (slide(s) %s): meaning never stated"
              % (sum(n for _, n in blanks),
                 ",".join(str(x) for x, _ in blanks)))
        print("     The audience can't tell \"not run\" from \"run, but not meaningful.\"")
        print("     One line under the table is enough: what isn't there is invisible")
        print("     to a checker too.")
    cast = never_drawn(slides)
    if cast:
        stuck += 1
        names, first = cast
        print("   %d thing(s) are compared across several tables, but no slide draws them"
              % len(names))
        print("     %s%s" % (" · ".join(names[:5]),
                             " ..." if len(names) > 5 else ""))
        print("     They first appear on slide %d with no figure before it. The audience" % first)
        print("     rides out the rest of the talk on names alone: draw one slide")
        print("     showing what's being compared.")
    if not stuck:
        print("   none: color meaning, count, name, and blanks all agree on screen.")

    print()
    print("=" * 72)
    print("5. Register markers")
    print("=" * 72)
    body = "\n".join(x for s in slides for x in (s.get("say") or []))
    # `re.I` matters here: the pattern is written lowercase, but a sentence's first
    # letter is capitalized, so without it, no matter how many lines started with
    # "So"/"And" this would always print `0`, exactly the case this check exists to
    # catch. "0 hits" would not mean it was clean.
    _lw = max([len(l) for l, _ in REGISTER] + [len(CONJ_LABEL)])
    for lab, pat in REGISTER:
        hits = re.findall(pat, body, re.I | re.M)
        print("   %-*s %d %s" % (_lw, lab, len(hits),
                                  ("e.g. " + ", ".join(sorted(set(
                                      h if isinstance(h, str) else h[0]
                                      for h in hits))[:6])) if hits else ""))
    # A title beginning with a question word is not a conjunction. This skill
    # recommends question titles (§2), so flagging one as a penalty here would
    # contradict that: `Which format should you pick?` should not be flagged.
    # Only titles the author wrote: a standout slide fills the title slot with
    # large text (including note), and a note like "but too small" should not be
    # flagged as "a title that opens with a conjunction."
    titles = [s.get("title", "") for s in slides if s.get("own_title", True)]
    conj = [t for t in titles
            if re.match(r"^(and|but|so|because)\b", t, re.I)
            or (re.match(r"^which\b", t, re.I) and not t.rstrip().endswith("?"))]
    print("   %-*s %d %s" % (_lw, CONJ_LABEL, len(conj),
                              ("e.g. " + " / ".join(t[:28] for t in conj[:3]))
                              if conj else ""))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    # Without `--help`, it would try to read that as a file name and throw a traceback.
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) > 1 else 2)
    sys.exit(main(sys.argv[1]))
