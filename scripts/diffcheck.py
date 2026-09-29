# -*- coding: utf-8 -*-
"""Finds what the deck left out of the manuscript.

    python scripts/diffcheck.py out/talk.pdf --source paper/paper.tex   <- usually this
    python scripts/diffcheck.py out/talk.pdf --ref old/talk.pdf         <- only when there's a previous deck

`deckcheck` looks at "is a number the deck uses in the manuscript." This tool
  is the opposite: it finds what's in the manuscript that the deck never
  uses. A derivative doesn't go wrong loudly; it goes wrong by quietly
  dropping something. What's there is visible and what's missing isn't, so reading it over can't find this.

**The manuscript is the answer key.** There is usually no previous deck: of
  course there isn't for someone building the first one, and that's normal. So
  the default mode is `--source`. `--ref` is used only when reworking a deck that already exists.

What `--source` checks
  · manuscript values that never appear in the deck, not even once
  · manuscript sentences carrying a number that the deck never touches at all (a whole paragraph dropped)
  · places where the deck states something more strongly than the
    manuscript - a hedge like "up to", "comparable", "may", "on these
    datasets" in the manuscript, missing from the deck's flat claim (checked against the abstract and captions too)

What `--ref` checks
  · a page with no match · numbers missing per page · content words missing per page
  A slide whose title differs (an impact slide) can't be matched. That's a
    limit of the tool, not a defect - both lists are printed side by side so a person can confirm it in one line.
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

WORD = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")
NUM = re.compile(r"(?<![\w.])(\d{1,4}\.\d)(?![\d])")


def pages(path):
    d = fitz.open(path)
    out = []
    for p in d:
        t = p.get_text()
        lines = [x.strip() for x in t.splitlines() if x.strip()]
        out.append((lines[0] if lines else "", t))
    d.close()
    return out


def words(t):
    return set(w.lower() for w in WORD.findall(t))


def nums(t):
    """Decimals and multiplier/percent integers (`deckspec.result_numbers`)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import deckspec
    return set(deckspec.result_numbers(t))


def match(pa, pb, floor=0.5):
    """Pairs each page with whichever other page shares the most title words."""
    pairs, used = [], set()
    for i, (ta, _) in enumerate(pa, 1):
        key, best, score = words(ta), None, 0.0
        for j, (tb, _) in enumerate(pb, 1):
            if j in used:
                continue
            k = words(tb)
            s = len(key & k) / float(len(key | k)) if (key | k) else 0.0
            if s > score:
                best, score = j, s
        if best and score >= floor:
            used.add(best)
            pairs.append((i, best))
        else:
            pairs.append((i, None))
    return pairs, [j for j in range(1, len(pb) + 1) if j not in used]


def _paper(path):
    """Manuscript text: expands `\\input` and macros (see `deckspec.read_paper`)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import deckspec
    return deckspec.read_paper(path)


CAVEAT = re.compile(r"\b(?:should|must|can|could)\s*not\s+be\s+compared|\bcannot\s+be\s+compared|"
                    r"\bnot\s+(?:directly\s+)?comparable|\bincomparable\b|\bdo\s+not\s+compare\b", re.I)


def captions(raw):
    """Text of the manuscript's `\\caption{…}` — by brace balancing."""
    out = []
    for m in re.finditer(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", raw or ""):
        i, d = m.end(), 1
        j = i
        while j < len(raw) and d:
            d += {"{": 1, "}": -1}.get(raw[j], 0)
            j += 1
        out.append(raw[i:j - 1])
    return out


def deckspec_backup_list():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import deckspec
    return deckspec.BACKUP_LIST


def deckspec_number_words(t):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import deckspec
    return deckspec.number_words(t)


def clean_tex(s):
    """Keeps only sentences from a LaTeX manuscript. Doesn't need to be perfect — it's for a rough pass."""
    s = re.sub(r"(?<!\\)%.*", "", s)
    # Multiplier/percent signs are turned into characters before the
    #   commands are stripped, otherwise `40$\times$` becomes `40` and it isn't recognized as a result value.
    s = s.replace("\\times", "×").replace("\\%", "%")
    # A layout command's argument is not content: the 1.2 in
    #   `\\arraystretch` and `6.5pt` would otherwise come in as "a value the deck didn't use".
    #   Each command strips only its own argument, since casting too wide a net eats the body text of a following `\textbf{…}` too.
    s = re.sub(r"\\(renewcommand|def|setlength|addtolength)\s*\{?\\[a-zA-Z]+\}?\s*\{[^{}]*\}",
               " ", s)
    s = re.sub(r"\\(vspace|hspace)\*?\s*\{[^{}]*\}", " ", s)
    # A figure's style definition is not a sentence: `\tikzstyle{mybox} =
    #   [draw=black, …]` would otherwise be flagged as an "explanatory sentence".
    #   Stripped whole line by line. A tikzpicture body is the same.
    s = re.sub(r"\\(?:tikzstyle|tikzset|pgfplotsset)\b[^\n]*", " ", s)
    s = re.sub(r"\\begin\{tikzpicture\}(\[[^\]]*\])?|\\end\{tikzpicture\}|\\node\s*\[[^\]]*\]\s*(\([^)]*\))?",
               " ", s)
    s = re.sub(r"\\resizebox\*?\s*\{[^{}]*\}\s*\{[^{}]*\}", " ", s)
    s = re.sub(r"\\scalebox\s*\{[^{}]*\}", " ", s)
    s = re.sub(r"\\includegraphics\*?(\[[^\]]*\])?\{[^{}]*\}", " ", s)
    s = re.sub(r"\\newcolumntype\{[^{}]*\}(\[[^\]]*\])?\{([^{}]|\{[^{}]*\})*\}", " ", s)
    s = re.sub(r"(?<![\w.])\d+(\.\d+)?(pt|em|ex|cm|mm)\b", " ", s)
    # A multiple of a length is typesetting too: the 0.29 and 0.85 in
    #   `{0.29\textwidth}` and `\parbox{0.85\linewidth}` would otherwise come up as "a value
    #   the deck doesn't use". deckcheck already strips this with `DIM`.
    s = re.sub(r"(?<![\w.])\d*\.?\d+\s*\\(?:textwidth|textheight|paperwidth|paperheight|"
               r"columnwidth|linewidth|hsize|vsize|baselineskip)(?![A-Za-z])", " ", s)
    # A math environment is not an explanatory sentence: `align*` could otherwise be
    #   read as "A _ ij = cases ..." and flagged as an explanation.
    #   `\vskip`/`\bibliography` are not sentences either.
    s = re.sub(r"\\\[.*?\\\]|\$\$.*?\$\$", " ", s, flags=re.S)
    s = re.sub(r"\\(vskip|hskip|bibliography|bibliographystyle)\b\s*(\{[^{}]*\}|[-\d.]+\s*\w*)?", " ", s)
    for env in ("figure", "table", "tabular", "thebibliography", "abstract", "equation",
                "align", "gather", "multline", "eqnarray", "displaymath", "split"):
        s = re.sub(r"\\begin\{%s\*?\}.*?\\end\{%s\*?\}" % (env, env), " ", s,
                   flags=re.S)
    s = re.sub(r"\\(cite|citep|citet|ref|label)\{[^}]*\}", " ", s)
    s = re.sub(r"\\textminus", "-", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", s)
    return re.sub(r"[{}$~\\]", " ", s)


# An abbreviation's period is not a sentence end: "(i.e. across decoding
#   positions) must be causal" would otherwise split into two sentences, leaving
#   the manuscript's flat claim unfound.
_ABBR = re.compile(r"\b(i\.e|e\.g|et\s+al|etc|vs|cf|resp|approx|fig|figs|eq|eqs|sec|no|U\.S|U\.K|"
                   r"Fig|Figs|Eq|Eqs|Sec|Tab|Dr|Mr|Ms)\.", re.I)


def sentences(s):
    s = _ABBR.sub(lambda m: m.group(0).replace(".", "\x00"), s)
    return [re.sub(r"\s+", " ", x).strip().replace("\x00", ".")
            for x in re.split(r"(?<=[.!?])\s+", s) if x.strip()]


# Markers of a sentence where the paper says why. Not "we measured X" but
#   a place saying "what causes what" or "what this is". If the deck leaves
#   this out whole, the audience hears the name but not the meaning.
WHY = re.compile(
    r"\b(because|since\s+\w+\s+(is|are|was|were|has|have)|so\s+that|"
    r"therefore|thus|hence|otherwise|in\s+order\s+to|the\s+reason|"
    r"which\s+(widen|narrow|vary|varies|mean|prevent|allow|give|make|let|"
    r"keep|leave|cause|explain|remove|add)\w*|"
    r"without\b[^.]{0,80}\b(would|overflow|fall|clip|lose|break|fail)\w*|"
    r"this\s+is\s+why|that\s+is\s+why|follows\s+from|"
    r"\bdenotes?\b|\brefers?\s+to\b|is\s+defined\s+as|we\s+call\b|"
    r"we\s+describe\b|\bmeans?\s+that\b)", re.I)


# A common word can't tell topics apart. Only the rare ones count.
TOPIC_STOP = set("""result results value values model models test tests case
cases number numbers point points setting settings change changes report
reports show shows give gives make makes take takes apply applies use uses
used using each every other same both more most only just also than then
where when what which this that these those with from into over under about
across between within while after before""".split())


def topic_words(s, words_fn):
    """What this sentence is about: content words with common ones excluded."""
    return {w for w in words_fn(s) if w not in TOPIC_STOP and len(w) > 4}


def topic_hits(s, dw, words_fn):
    """This sentence's topic words that the deck actually mentions.

    A long word is also checked for containment: `non-significant` would otherwise
      not match the deck's `significant`, so the most important hedge ("not
      significant doesn't mean the same") would fall into "a topic the deck doesn't cover".
    """
    long_deck = [w for w in dw if len(w) >= 7]
    out = set()
    for w in topic_words(s, words_fn):
        if w in dw:
            out.add(w)
        elif len(w) >= 7 and any(w in d or d in w for d in long_deck):
            out.add(w)
    return out


_NOTATION = re.compile(r"^\s*(?:we\s+(?:denote|write|use)\b|let\b|here\b[^.]{0,20}\bdenotes?\b)", re.I)


def notation_only(s):
    """Is this a sentence that just sets up notation, like "We denote by d… a dual element such that ∂C = ⟨d,·⟩".

    Setting up notation is not an explanation. A talk can simply not use the
      symbol, so there's nothing to carry over, yet `denote` is a marker of
      explanation, so without this it would always stay as "an explanation the
      deck didn't cover" and cause exit 1. Excluded only when it opens
      by setting up notation and more than half its words are symbols:
      an actual gloss like "X denotes the share of …" still counts.
    """
    # "abuse of notation" is itself a notation setup
    if re.search(r"\babuse\s+of\s+notation\b", s, re.I):
        return True
    if not _NOTATION.search(s):
        return False
    toks = s.split()
    sym = [t for t in toks if re.search(r"[_^|=\\{}()<>]|^[A-Za-z]$|^\W+$", t)]
    return len(sym) >= 0.4 * max(1, len(toks))


def reasoning_left(body, dw, limit, sentences_fn, words_fn):
    """Sentences the paper explains that the deck never touches. [(sentence, already covers it or not)].

    `diffcheck` counts numbers the deck doesn't use. But a sentence where
      the paper works through a concept usually has no number: things like
      "the insulation reduces heat loss" or "without that valve the large tank
      overflows". So the deck could say only the name of the concept and pass every check.

    The second value matters. If the deck already covers that topic and
      still dropped this sentence, that's not a choice but a dropped
      hedge: it puts the claim on screen without stating the condition
      attached to it. That's different from dropping a topic it never covers
      at all. Failing to separate the two lumps everything into "up to the author."

    Uses the same yardstick as counting numbers: how much of this sentence's content words are in the deck.
    """
    out = []
    for s in sentences_fn(body):
        if not WHY.search(s):
            continue
        w = words_fn(s)
        if len(w) < 5:
            continue
        if notation_only(s):
            continue
        if len(w & dw) / float(len(w)) >= 0.34:
            continue
        # The question isn't "did the deck carry this sentence over" but
        #   "does the deck mention this subject at all." If it does, then
        #   not stating the condition attached here isn't a choice. Requiring
        #   half of the whole sentence made this the same yardstick as the
        #   full-overlap check right above, and every sentence became "not covered".
        out.append((s, len(topic_hits(s, dw, words_fn)) >= 2))
    return out



# The shape of the paper naming something or spelling out its meaning.
#   The two are different in kind. A name (`called X`) is short: if it's
#   long or opens with an adverb, it isn't a name ("we call it the same way
#   throughout" would otherwise catch "same way throughout" as a term). The Y in a meaning
#   (`X denotes Y`) can be long.
#   Must not be picked by frequency, since that mixes in common words like `data`/`compared`.
NAMED = [
    re.compile(r"\bcalled\s+(?:the\s+|a\s+)?([a-z][a-z \-]{2,28}?)\s*[.,;]", re.I),
    re.compile(r"\bwe\s+call\s+(?:it\s+|this\s+|these\s+)?"
               r"(?:the\s+)?([a-z][a-z \-]{2,28}?)\s*[.,;]", re.I),
    re.compile(r"\b(?:known|referred\s+to)\s+as\s+(?:the\s+)?"
               r"([a-z][a-z \-]{2,28}?)\s*[.,;]", re.I),
]
DEFINES = [
    re.compile(r"\bdenotes?\s+(?:the\s+)?([a-z][a-z \-]{2,44}?)\s*[.,;]", re.I),
    re.compile(r"\bis\s+defined\s+as\s+(?:the\s+)?"
               r"([a-z][a-z \-]{2,44}?)\s*[.,;]", re.I),
]
NAMED_STOP = set("it this that these those them us one".split())
# Spots that catch an adverbial phrase rather than a name
NAMED_BAD_HEAD = set("same such more most very only just again here there "
                     "other another every each both all any one two".split())


def named_terms_missing(body, deck_text, sentences_fn):
    """Something the paper names or spells out the meaning of that the deck doesn't use. [(term, sentence)].

    If the paper assigns a name like "… called the control group" and the
      deck never uses that word, an audience that has read the paper cannot
      connect the two. And the speaker doesn't realize they've switched to
      their own wording: in practice, "cohort" had turned into "group".
    """
    low = deck_text.lower()
    out, seen = [], set()
    for s in sentences_fn(body):
        for pats, short in ((NAMED, True), (DEFINES, False)):
            for pat in pats:
                for m in pat.finditer(s):
                    name = " ".join(m.group(1).split())
                    key = name.lower()
                    if not key or key in NAMED_STOP or key in seen:
                        continue
                    if short and (key.split()[0] in NAMED_BAD_HEAD
                                  or len(key.split()) > 4):
                        continue
                    seen.add(key)
                    parts = re.findall(r"[a-z\-]{3,}", key)
                    if parts and not all(p in low for p in parts):
                        out.append((name, s))
    return out


# Places where the deck states things more strongly than the paper.
#   Numbers get checked, but the wording matters too: if the paper's
#   "up to 3x"/"comparable"/"may" become the deck's "3x"/"better"/"always", the
#   number check passes completely. The strong-claim and hedge words are a
#   list, not a grammatical parse: they just point at a spot to look at by eye.
STRONG = re.compile(
    r"\b(always|never|every|entirely|completely|fully|guarantee[sd]?|prove[sd]?|proof|"
    r"eliminat\w+|best|outperform\w*|beats?|superior|significantly|dramatically|"
    r"universally|cannot|impossible|must|solves?|no\s+(?:loss|drop|cost|penalty|effect|"
    r"degradation|difference))\b", re.I)
HEDGE = re.compile(
    r"\b(may|might|could|often|usually|typically|generally|largely|mostly|some|up\s+to|"
    # "postulate"/"conjecture"/"hypothesize" are hedges too: the deck's "we
    #   postulate …" would otherwise be flagged as a flat claim stripped of the manuscript's
    #   "It seems natural to postulate …" hedge.
    r"roughly|approximately|comparable|on[\s-]par|similar(?:ly)?|suggest\w*|appears?|"
    r"postulat\w*|conjectur\w*|hypothesi[sz]\w*|speculat\w*|"
    # A plan or intention is a hedge too, or the manuscript's "we plan to investigate" turned by the deck into "… need" would be missed.
    r"plan(?:s|ned)?\s+to|intends?\s+to|hopes?\s+to|aims?\s+to|"
    # A mathematical limit is not a hedge: "tend (in law) to iid Gaussian
    #   processes", "almost surely". In an NTK paper, the deck's "prove" would otherwise be
    #   paired with the theorem's "tend to" and flagged as hype.
    #   Only "tend to + verb" (a tendency) counts as a hedge: excluded
    #   when it's followed by a limit's target (an article, a number, a symbol, iid, zero, infinity).
    # "potentially"/"possibly"/"perhaps"/"exhibit traits" are hedges too, or a deck that turned "higher-income jobs
    #   potentially facing greater exposure" into "always face" would go uncaught.
    r"seems?|likely|potentially|possibly|perhaps|exhibits?\s+(?:the\s+)?traits|"
    r"tends?(?!\s*(?:\([^)]*\)\s*)?(?:to|towards)\s+(?:a|an|the|zero|infinity|iid|i\.i\.d|some|its|their"
    r"|[\d$\\∞]))|in\s+many\s+cases|partially|partly|slightly|marginal\w*|"
    r"at\s+least\s+as|competitive|nearly|almost(?!\s+(?:surely|everywhere))|matches|close\s+to|"
    # Scope-narrowing wording is a hedge too: if "a rank as small as one
    #   suffices … on these datasets" becomes "always enough" in the deck, the scope disappears
    r"on\s+these\s+\w+|in\s+our\s+(?:experiments?|settings?|study|setup)|for\s+these\s+\w+|"
    r"in\s+this\s+(?:setting|setup|work|study)|we\s+observe|in\s+practice|"
    # Wording narrowed to the range actually tested ("… in all the rooms
    #   we tested") is a hedge too, even where the deck had disclosed the range but "all" still read as hype.
    r"we\s+(?:tried|tested|studied|ran)|in\s+our\s+(?:tests?|runs?)|so\s+far)\b", re.I)
_SAME = {"every": ["all", "each"], "always": ["in\\s+all\\s+cases", "consistently", "every"],
         "never": ["not\\s+\\w+\\s+any", "no\\s+\\w+\\s+ever"], "cannot": ["can\\s*not", "unable"],
         "must": ["need\\s+to", "needs\\s+to", "has\\s+to", "have\\s+to", "require\\w*"],
         "entirely": ["completely", "fully"], "completely": ["entirely", "fully"],
         "fully": ["entirely", "completely"], "best": ["highest", "strongest", "outperform\\w*"],
         "outperform": ["better", "exceed\\w*", "surpass\\w*"], "no": ["without", "zero"],
         # In math, "the best point" is an optimum, and a guarantee is a
         #   proof, or "the best point" would otherwise be paired with the introduction's
         #   "typically", and a theorem-backed "guarantee" with the abstract's "suggests".
         "guarantee": ["prove\\w*", "guarantee\\w*", "ensure\\w*"],
         "guarantees": ["prove\\w*", "guarantee\\w*", "ensure\\w*"],
         "guaranteed": ["prove\\w*", "guarantee\\w*", "ensure\\w*"],
         "prove": ["guarantee\\w*", "prove\\w*"], "proves": ["guarantee\\w*", "prove\\w*"],
         "proved": ["guarantee\\w*", "prove\\w*"]}
_SAME["best"] = _SAME["best"] + ["optimal", "optimum", "minimum", "minimal"]
_UPTO = re.compile(r"\bup\s+to\s+\$?(\d[\d.,]*)\s*\$?\s*(\\times|×|x\b|%|\\%|times|fold)", re.I)


# Dropping this hedge changes the modality of the claim (possible ->
# factual). Scope hedges (some/mostly) are excluded — a deck routinely
# understates scope, and flagging that too lets false positives bury the real ones.
# Lowercase only, or reading the title block's month name "May 2018" as a
#   hedge would flag the title/author line. "suggest + -ing" (a recommendation:
#   "suggest choosing …") is not a hedge, or a deck that turned a recommendation into an imperative would get flagged.
MODAL = re.compile(r"(?:^|(?<=[\s(]))(?:[Cc]ould|[Mm]ay(?!\s+\d)|[Mm]ight|potentially|[Pp]ossibly|[Pp]erhaps|"
                   r"likely|suggests?(?!\s+\w+ing\b)|suggested(?!\s+\w+ing\b)|"
                   r"plan(?:s|ned)?\s+to|intends?\s+to|hopes?\s+to|"
                   # Even an adjective with no "to", like "appears
                   #   limited" or "seems unlikely", is a hedge, or looking only
                   #   for "appears to" would miss a deck that turned "appears
                   #   stable under …" into "Stable under …".
                   #   Wording that names a place or time ("appears in Table
                   #   2", "appears when …", "appear last") is not a hedge:
                   #   excluded after checking how real manuscripts actually use it.
                   r"(?:appears?|seems?)\s+(?!(?:in|on|at|as|when|where|while|if|below|above|last|first|"
                   r"only|once|twice|after|before|here|there|again|with|alongside|throughout|under|"
                   r"between|near|next|both|together|and|or|for|from|of)\b)[a-z]+|"
                   r"exhibits?\s+(?:the\s+)?traits)\b")
_CLAUSE = re.compile(r"[,;:()]|\s(?:and|but|while|whereas|which|who|that)\s")


ANNOUNCE = re.compile(
    # "the two limits" refers back to something already counted earlier, so it isn't an announcement
    r"\b(?:(?<![Tt]he\s)(?:two|three|four|five|several|\d)\s+(?:\w+\s+)?(?:reasons|causes|mechanisms|explanations|"
    r"limits|limitations|factors|effects|things|ways|lessons|failure\s+modes)"
    r"|for\s+(?:different|distinct|separate)\s+reasons|(?:a|one)\s+different\s+(?:limit|cause|reason|mechanism))\b",
    re.I)


def announced_counts(body, sentences_fn):
    """Manuscript sentences that announce a count, like "Queues grow for two reasons." / "… fail for different reasons.".

    An announcement is checked only in the body: "two ways" in a reference or caption is not an announcement."""
    out = []
    for s in sentences_fn(body):
        s = re.sub(r"\s+", " ", s).strip()
        if ANNOUNCE.search(s) and len(s) < 400 and s not in out:
            out.append(s)
    return out


def _dropped_modal(u, paper, words_fn, fold):
    """If a hedge-free deck sentence `u` almost verbatim carries over a manuscript sentence that carries a modal hedge (manuscript sentence, hedge).

    A match is a manuscript sentence with four or more content words, more
    than 60% overlapping the deck side's topic words. If another sentence
    in the manuscript says the same thing with no hedge, the deck has carried over that sentence, so it is not flagged.
    """
    # Only something ending like a sentence: a table header row or a title is not a claim. A question isn't a flat claim either
    if not re.search(r"[.!][\"'”’)]*\s*$", u.strip()):
        return None
    # A negated sentence hasn't strengthened a claim, or "Exposure means …,
    #   not that the job can be fully automated" would be paired with the
    #   manuscript's "suggest" as if it had.
    if re.search(r"\b(not|no|nor|neither|never)\b|n't\b", u, re.I):
        return None
    tw = fold({w for w in topic_words(u, words_fn) if not MODAL.fullmatch(w)})
    if len(tw) < 4:
        return None
    cand = [(len(tw & sw), s) for s, sw in paper]
    cand = [(k, s) for k, s in cand if k >= 4 and k >= 0.6 * len(tw)]
    if not cand:
        return None
    k0, best = max(cand)
    h = MODAL.search(best)
    if not h:
        return None
    # The hedge must sit in a clause that has overlapping words. In
    #   "AMSGrad neither increases nor decreases …, which can potentially lead
    #   to …", the "potentially" is not a hedge on the earlier clause the deck
    #   carried over.
    #   The hedge's clause and the clauses on both sides of it are viewed
    #   as one window, since looking at only one clause would miss the flat claim
    #   carried over from "LLMs … exhibit traits of general-purpose technologies, indicating that they could have …"
    parts = [pt or "" for pt in _CLAUSE.split(best)]

    def _win(i):
        return " ".join(parts[max(0, i - 1):i + 2])
    # Looking at the window alone also matches a hedge that sits only in the
    #   adjacent clause: in "The cell may seem steady; its capacity drops
    #   …", the "may" would get attached to a deck that carried over the later
    #   clause (the flat claim). The hedge's own clause must also have at least two overlapping words
    if not any(len(tw & fold(words_fn(_win(i)))) >= max(3, 0.35 * len(tw))
               and len(tw & fold(words_fn(pt))) >= 2
               for i, pt in enumerate(parts) if pt and MODAL.search(pt)):
        return None
    if any(not MODAL.search(s) for k, s in cand if k >= 0.8 * k0):
        return None
    return best, h.group(0).strip()


def overclaims(body, units, sentences_fn, words_fn, raw=""):
    """Places where the deck's (screen/script) flat claim was hedged wording in the manuscript. [(deck, manuscript, strong word, hedge word)].

    A match is found by content-word overlap: a manuscript sentence
      sharing more than half of one deck unit's topic words, at least three of
      them. Flagged if that sentence uses a hedge word and the deck's version doesn't.
    """
    def _fold(ws):                      # folds plurals — "token" and "tokens" are the same word
        return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in ws}
    paper = [(s, _fold(words_fn(s))) for s in sentences_fn(body)]
    out, seen = [], set()
    # If one unit has several sentences, check sentence by sentence: a hedge or negation only means something within its own sentence
    units = [x for u in units for x in sentences_fn(u)]
    for u in units:
        # "the best point"/"best fixed point" is the name for an optimum, not a performance claim
        u = re.sub(r"\bbest\s+(?=(?:fixed\s+)?(?:point|solution|value|response|action|arm)s?\b)",
                   "", u, flags=re.I)
        m = STRONG.search(u)
        if not HEDGE.search(u):
            # A sentence with only the hedge dropped: if the deck turns
            #   the manuscript's "could have at least 10% of their tasks
            #   affected" into "will have …", there's no strong-claim word, so
            #   this check would otherwise pass right through it.
            # Checked first even when there is a strong-claim word, or turning
            #   "appears limited … must cover" into "is limited … must cover"
            #   would pass because "must" is in the manuscript.
            d_ = _dropped_modal(u, paper, words_fn, _fold)
            if d_:
                key = (u[:60], d_[0][:60])
                if key not in seen:
                    seen.add(key)
                    out.append((u, d_[0], u"(no hedge)", d_[1]))
                continue
        if not m:
            continue
        # A deck sentence that also has a hedge or is negated hasn't
        #   stated things more strongly, or the "every" in "may not work
        #   for every task"/"We do not expect … for every task" would get flagged.
        if HEDGE.search(u) or re.search(r"\b(not|no|nor|neither)\b|n't\b", u[:m.start()]):
            continue
        # If the strong-claim word appears in the manuscript as the same
        #   two words ("fully exposed"), the deck carried over the
        #   manuscript's own wording. Otherwise a manuscript table's term
        #   would get flagged as hype, with no way even for `--omit` to turn it off.
        _nx = re.match(r"\s*([A-Za-z][\w-]*)", u[m.end():])
        # A term inside a table isn't in the sentence list, so it is searched for in the whole manuscript text instead
        if _nx and re.search(r"\b%s\s+%s\b" % (re.escape(m.group(1)), re.escape(_nx.group(1))),
                             body + "\n" + (raw or ""), re.I):
            continue
        # The strong-claim/hedge word itself is not the topic, or lowering the match overlap would fail to find the manuscript sentence
        tw = _fold({w for w in topic_words(u, words_fn)
                    if not STRONG.fullmatch(w) and not HEDGE.fullmatch(w)
                    and not re.match(r"(always|never|outperform|significant|dramatic)", w)})
        if len(tw) < 3:
            continue
        best, bw = None, 0
        for s, sw in paper:
            k = len(tw & sw)
            if k > bw:
                best, bw = s, k
        if not best or bw < 3 or bw < 0.5 * len(tw):
            continue
        # If another manuscript sentence makes the same flat claim, the
        #   deck carried over the manuscript. Looking only at the single
        #   most-overlapping sentence would otherwise flag "must be causal" even though it appears verbatim elsewhere in the manuscript.
        # The same claim made in different words counts too, or a
        #   deck that turned the manuscript's "all the parameters" into "every parameter" would get flagged.
        _w = m.group(1).lower().split()[0]
        _eq = [re.escape(m.group(1))] + _SAME.get(_w, [])
        _sw = re.compile(r"\b(?:%s)\b" % "|".join(_eq), re.I)
        if any(_sw.search(s) for s, sw in paper
               if len(tw & sw) >= max(3, 0.4 * len(tw))):
            continue
        h = HEDGE.search(best)
        if h and not _sw.search(best):
            key = (u[:60], best[:60])
            if key not in seen:
                seen.add(key)
                out.append((u, best, m.group(1), h.group(1)))
    return out


def dropped_upto(body, deck_all):
    """A place where the manuscript's "up to Nx" survives in the deck as only "Nx". [(value, manuscript sentence)]."""
    out = []
    _qual = r"(up\s+to|as\s+much\s+as|at\s+most|maximum|max\.?|roughly|about|around|nearly|~|≈)\s*$"
    for m in _UPTO.finditer(body):
        v = m.group(1).rstrip(".,")
        _pat = r"(?<![\w.])\$?%s\s*\$?\s*(\\times|×|x\b|%%|\\%%|times|fold)" % re.escape(v)
        # If the manuscript states the same value elsewhere with no hedge,
        #   the deck's flat claim is the manuscript's own wording, rather than
        #   the body's "up to 10,000x" getting flagged while the abstract already had "by 10,000 times".
        if any(not re.search(_qual, body[max(0, x.start() - 16):x.start()], re.I)
               for x in re.finditer(_pat, body)):
            continue
        uses = list(re.finditer(_pat, deck_all))
        if uses and not any(re.search(_qual, deck_all[max(0, u.start() - 16):u.start()], re.I)
                            for u in uses):
            s = next((x for x in sentences(body) if m.group(0) in x), m.group(0))
            out.append((v, s))
    return out


APPENDIX_AT = re.compile(
    r"\\appendix\b|\\begin\{appendix\}|\\section\*?\{\s*(?:appendix|supplement)"
    r"|^#{1,3}\s*(?:appendix|supplementary)", re.I | re.M)


def against_source(deck_text, source_path, limit, spoken="", omit=(), units=None, main_deck=None):
    """Finds numbers and sentences that are in the manuscript but not in the deck. The manuscript is always the answer key."""
    # Giving the wrong path is common. Dumping a raw Python traceback makes
    #   the person on the other end think the tool itself is broken, so tell them what to fix instead.
    if not os.path.isfile(source_path):
        raise SystemExit("could not find the manuscript: %s\n"
                         "  give `--source` the paper's file path "
                         "(the same thing as `source:` in deckcheck.yaml)."
                         % os.path.abspath(source_path))
    raw = _paper(source_path)
    # The preamble (before `\begin{document}`) is not the manuscript, or
    #   `\setstretch{0.985}` and the package list would come up as "unused values/sentences".
    _bd = re.search(r"\\begin\{document\}", raw)
    if _bd:
        raw = raw[_bd.end():]
    # The appendix is not part of the talk, or sentences from the proof and
    #   notation sections would flood in as "dropped hedges". Checked only up to the appendix.
    _ap = APPENDIX_AT.search(raw)
    if _ap and _ap.start() > len(raw) * 0.3:
        raw = raw[:_ap.start()]
    # The bibliography too, or arXiv IDs and DOIs would flood in as "unused values"
    # The backslashes must be doubled: in a regex `\b` is a word boundary, so `\bibliography\{`
    #   would otherwise not match a LaTeX `\bibliography{`, and the cut would only ever work for Markdown headings
    _rf = re.search(r"\\bibliography\{|\\begin\{thebibliography\}|^#{1,3}\s*(?:references|bibliography)\s*$",
                    raw, re.I | re.M)
    if _rf and _rf.start() > len(raw) * 0.3:
        raw = raw[:_rf.start()]
    body = clean_tex(raw)
    # Numbered citations in text read out of a PDF ("[108,109]", "[8–10]") are not values,
    #   or "108,109" would come up as a number the deck never used (a physics paper read from its PDF)
    body = re.sub(r"\[\d{1,3}(?:\s*[,–-]\s*\d{1,3})*\]", " ", body)
    sn = nums(body)
    # The deck writes the same number in a different form than the
    #   manuscript: the manuscript's "48th layer" is counted as an ordinal,
    #   while the deck's "layer 48." is a bare integer, so without this a
    #   value that was actually in the deck would come up "missing".
    #   If the manuscript's value shows up as a number anywhere in the deck, it's present.
    dn = nums(deck_text) | {x for x in re.findall(r"(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\d])",
                                                  deck_text or "") if x in sn}
    # An explanation given out loud in the script also counts as covered,
    #   since the skill says "the why goes through say". Recognizing only the
    #   screen would leave it as "a topic the deck doesn't
    #   cover". Numbers are handled separately (below).
    dw = words(deck_text + "\n" + (spoken or ""))

    print("=" * 78)
    print("checked against %s" % os.path.basename(source_path))
    print("=" * 78)
    # A value spoken in the script hasn't been dropped, it's just not on
    #   screen. Shown separately and not counted as a failure, rather than exiting
    #    1 for something the script covers out loud.
    # A number the script writes as words ("forty-nine") counts as spoken too.
    said = set(nums(spoken)) | set(nums(deckspec_number_words(spoken))) if spoken else set()
    # A bare number in the script counts as spoken too, or the 21 and 250 in
    #   "10 to the 21"/"over 250 times" would stay as "values not in the deck"
    #   if this were only patched for the deck.
    said |= {x for x in re.findall(r"(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\d])", spoken or "")
             if x in sn}
    # A deliberately excluded value is not counted once disclosed. With
    #   no way to disclose it, a single value would cause a permanent exit 1.
    #   A disclosed one is shown separately (not hidden).
    omitted = sorted((sn - dn - said) & set(omit))
    missing_n = sorted(sn - dn - said - set(omit))
    said_only = sorted((sn - dn) & said)
    print("   %d manuscript value(s) · %d value(s) in the deck · %d manuscript value(s) not in the deck"
          % (len(sn), len(dn), len(missing_n)))
    if missing_n:
        print("   " + " ".join(missing_n))
    if said_only:
        print("   %d value(s) not on screen but spoken only in the script: %s"
              % (len(said_only), " ".join(said_only)))
    if omitted:
        print("   %d deliberately excluded value(s) (`--omit`): %s" % (len(omitted), " ".join(omitted)))
    print("   (not everything needs to be used — this is a prompt to check by eye whether something was dropped)")
    # A result that exists only on a backup slide: a value on a backup
    #   table would otherwise be counted as "the deck used it", so a whole paragraph's
    #   finding in the results section could go missing from the main deck
    #   without tripping any check. Shows manuscript sentences whose result
    #   numbers all exist only on a backup slide, not on the main deck's screen or in its script (informational).
    if main_deck is not None:
        mn = nums(main_deck) | {x for x in re.findall(r"(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\d])",
                                                       main_deck or "") if x in sn}
        # The script too: only its main-deck share. A backup slide's
        #   wording and an anticipated question's answer are wording that
        #   needs the question to be asked first. Counting a finding that
        #   existed only in a backup slide's `say` as "already said" would miss it.
        #   The header belongs to the script generator
        _main_sp = spoken or ""
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import build_script
            _heads = [v[k] for v in build_script.LABELS.values() for k in ("spare_head", "asks") if k in v]
            _cut = [i for i in (_main_sp.find(h) for h in _heads) if i >= 0]
            if _cut:
                _main_sp = _main_sp[:min(_cut)]
        except Exception:
            pass
        _msaid = (set(nums(_main_sp)) | set(nums(deckspec_number_words(_main_sp)))
                  | {x for x in re.findall(r"(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\d])", _main_sp) if x in sn})
        _bk_only = (dn - mn - _msaid) & sn
        _hit = []
        for s_ in sentences(body):
            _v = nums(s_) & sn
            if _v and _v <= _bk_only:
                _hit.append(s_)
        if _hit:
            print()
            print("   (info) %d manuscript sentence(s) whose result number is only on a backup slide, never appearing in the main deck:"
                  % len(_hit))
            for s_ in _hit[:4]:
                print("   · %s" % s_[:150])
            print("     if it's a finding from one paragraph of the results section, say it once in the main deck (one `say` line, or one row of a main-deck table).")

    # A comparison caveat - "should not be compared to …"/"not comparable" -
    #   is usually in a table caption, so the check above (body text with
    #   table/figure environments stripped) would otherwise miss it: a deck could compare that
    #   value in the main deck while leaving the caveat only in a backup
    #   table's caption. Shows
    #   sentences where the hedge's target appears in the main deck but
    #   less than half of the hedge's remaining wording does (informational).
    _main_txt = ((main_deck if main_deck is not None else deck_text) + chr(10)
                 + (_main_sp if main_deck is not None else (spoken or "")))
    _mw = words(_main_txt)
    _cav = []
    for s_ in sentences(body) + [x for c in captions(raw) for x in sentences(clean_tex(c))]:
        s_ = re.sub(r"\s+", " ", s_).strip()
        if not CAVEAT.search(s_):
            continue
        tw = topic_words(s_, words)
        hit = {w for w in tw if w in _mw}
        if hit and len(hit) < 0.5 * len(tw) and s_ not in _cav:
            _cav.append(s_)
    if _cav:
        print()
        print("   (info) %d of the manuscript's comparison caveats are missing from the main deck's screen/script - the target appears in the main deck:" % len(_cav))
        for s_ in _cav[:4]:
            print("   · %s" % s_[:160])
        print("     if that value is compared in the main deck, say the caveat once on the same slide (one `say` line, or a `fine` line).")

    # Sentences carrying a number whose content words are almost entirely absent from the deck
    print()
    print("   Manuscript sentences carrying a number that the deck never touches at all")
    shown = 0
    for s in sentences(body):
        if not NUM.search(s):
            continue
        w = words(s)
        if not w:
            continue
        # If all of that sentence's result numbers are in the deck
        #   (screen/script), it has been touched. Measuring words alone would otherwise leave a
        #   sentence the deck restated in its own words ("a peak even at
        #   ε=0.1") as "never touched at all".
        _sn = nums(s)
        if _sn and _sn <= (dn | said):
            continue
        overlap = len(w & dw) / float(len(w))
        if overlap < 0.34:
            shown += 1
            if shown <= limit:
                print("   · %s" % s[:110])
    if not shown:
        print("   none")
    else:
        print("   -> %d sentence(s) (showing %d)" % (shown, min(shown, limit)))

    # ── explanations left behind ────────────────────────────────────────────
    #   This is the spot that had long been empty in this skill. Numbers were
    #     counted, but not what the paper explained. So a deck
    #     could just say a concept's name and move on, and still pass every other check.
    left = reasoning_left(body, dw, limit, sentences, words)
    # Giving `--omit` a sentence fragment counts that sentence as
    #   deliberately dropped. Otherwise, since it took only values, a single
    #   explanatory sentence with an obvious reason to drop it would cause a permanent exit 1.
    # A sentence fragment = wording of five or more characters (three or more
    #   letters in a row, to separate it from a value). At eight characters
    #   this would silently ignore something like "mybox".
    _frag = [x.lower() for x in omit if re.search(r"[A-Za-z]{3}", x) and len(x) >= 5]
    _skip = [s_ for s_, _on in left if any(f in s_.lower() for f in _frag)]
    left = [(s_, on) for s_, on in left if s_ not in _skip]
    hot = [s for s, on in left if on]
    cold = [s for s, on in left if not on]
    print()
    print("   Sentences the manuscript explains that the deck doesn't touch")
    if _skip:
        print("   %d deliberately dropped sentence(s) (`--omit`) - not counted. plan.md must have a reason" % len(_skip))
    if not left:
        print("   none - wherever the paper says why, the deck says it too.")
    if hot:
        # The deck already talks about this while dropping the hedge.
        #   That's not a choice - the deck puts the claim on screen without stating the condition attached to it.
        print("   the deck already talks about this and dropped the hedge - not a choice")
        for s in hot[:limit]:
            print("   · %s" % s[:110])
        if len(hot) > limit:
            print("     -> %d sentence(s) (showing %d)" % (len(hot), limit))
        print("     these claims are put on screen with the condition attached to them left unsaid.")
        print("     the audience hears an unconditional claim, which isn't what the paper wrote.")
    if cold:
        print("   explanation of a topic the deck doesn't cover at all - up to you whether to drop it")
        for s in cold[:limit]:
            print("   · %s" % s[:110])
        if len(cold) > limit:
            print("     -> %d sentence(s) (showing %d)" % (len(cold), limit))
    if left:
        print("     getting the numbers right and being understood are different things.")
    # ── places where the manuscript announces a count ─────────────────────────────────
    #   Two reasons can follow "… for different reasons", but the deck draw only
    #     one. The words all existed elsewhere in the deck, so
    #     the explanation check above counted it as "touched". Whether the
    #     announced count is fully present in the deck is for a person to check.
    ann = announced_counts(body, sentences)
    if ann:
        print()
        print("   (info) %d manuscript sentence(s) that announce a count - is everything that follows all present in the deck:" % len(ann))
        for s_ in ann[:limit]:
            print("   · %s" % s_[:150])
        print("     if there are two reasons or two limitations, give both - drawing only one tells the audience that's all there is (planning §closing).")
    # ── does the deck use what the paper names ──────────────────────
    named = named_terms_missing(body, deck_text, sentences)
    print()
    print("   Terms the manuscript names that the deck doesn't use")
    if not named:
        print("   none - the deck uses the names the manuscript assigns.")
    else:
        for n_, s in named[:limit]:
            print("   · %s" % n_)
            print("       %s" % s[:104])
        if len(named) > limit:
            print("   -> %d term(s) (showing %d)" % (len(named), limit))
        print("   switching to your own wording means an audience who has read the paper cannot connect the two.")
        print("     use the manuscript's word, or if there's a reason to rename it, connect")
        print("     them once on screen - like \"the baseline model (v1)\".")
    # ── places where the deck states things more strongly than the paper ─────────────────────────────────
    _units = list(units) if units else sentences(deck_text)
    _units += sentences(spoken or "")
    # A claim's original wording is most common in the abstract and
    #   captions, so the check above, which reads without them, would otherwise miss a
    #   sentence that turned the abstract's "on-par or better" into "always outperforms" (confirmed by testing)
    # A theorem/proposition/lemma body is a proven claim, or the deck's "We
    #   prove it when the data lie on the sphere" would be paired with the hedge of
    #   the sentence right before the proposition. Read by prefixing the environment's opening with "We prove:".
    _thm = {"theorem", "thm", "proposition", "prop", "lemma", "lem", "corollary", "cor"}
    for _m in re.finditer(r"\\newtheorem\*?\s*\{([^}]+)\}\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", raw):
        if re.match(r"\s*(theorem|proposition|lemma|corollary)", _m.group(2), re.I):
            _thm.add(_m.group(1).strip())
    _raw = re.sub(r"\\begin\{(%s)\}(\s*\[[^\]]*\])?" % "|".join(re.escape(x) for x in sorted(_thm)),
                  " We prove: ", raw)
    _claims = clean_tex(re.sub(r"\\begin\{abstract\}|\\end\{abstract\}", " ", _raw))
    _caps = []
    for _m in re.finditer(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", raw):
        _i, _dep = _m.end(), 1
        _j = _i
        while _j < len(raw) and _dep:
            _dep += {"{": 1, "}": -1}.get(raw[_j], 0)
            _j += 1
        _caps.append(clean_tex(raw[_i:_j - 1]).strip().rstrip(".") + ".")
    _claims += "\n" + "\n".join(_caps)
    strong = overclaims(_claims, _units, sentences, words, raw)
    upto = dropped_upto(_claims, deck_text + "\n" + (spoken or ""))
    print()
    print("   Places where the deck states things more strongly than the manuscript (the manuscript has a hedge)")
    if not strong and not upto:
        print("   none — the deck doesn't state as flat claims things the manuscript hedges.")
    for v, s in upto:
        print("   · manuscript says \"up to %s\", deck just says \"%s\" - states the max as if it were the typical value" % (v, v))
        print("       manuscript: %s" % s[:104])
    for u, s, w, h in strong[:limit]:
        if w == u"(no hedge)":
            print("   · deck <<%s>> drops the hedge - manuscript says \"%s\"" % (u[:70], h))
        else:
            print("   · deck <<%s>> says \"%s\" - manuscript says \"%s\"" % (u[:70], w, h))
        print("       manuscript: %s" % s[:104])
    if len(strong) > limit:
        print("   -> %d spot(s) (showing %d)" % (len(strong), limit))
    if strong or upto:
        print("   even with the right number, dropping the hedge makes it a different claim. Carry over the manuscript's hedge, or")
        print("     if the deck is right (another spot in the manuscript states it flatly), write that sentence down in plan.md.")
    _n = len(missing_n) + len(left) + len(named) + len(strong) + len(upto)
    if _n:
        # Breaks down what was counted, since "4 kinds only in the manuscript"
        #   printed right under "0 values not in the deck" would read as a contradiction.
        print()
        print("   %d thing(s) to fix - values not used %d · explanations not covered %d · terms not used %d · places stated too strongly %d · "
              "dropped \"up to\" %d" % (_n, len(missing_n), len(left), len(named), len(strong), len(upto)))
    return _n



def split_omit(txt):
    """Splits the `--omit` list. If there's a `;`, split on `;` only (no ambiguity).

    A comma overlaps between a thousands separator ("14,562") and a list
      separator. Treating a three-digit trailing group as a thousands
      separator would otherwise turn "0.99,108,109" into one lump, so nothing would actually be
      excluded. A comma right after a decimal point can never be a thousands separator, so it's split there. If still ambiguous, write it with `;`."""
    txt = txt or ""
    if ";" in txt:
        return [x.strip() for x in txt.split(";") if x.strip()]
    out, cur = [], ""
    for part in txt.split(","):
        if cur and re.fullmatch(r"\d{3}", part.strip()) and re.fullmatch(r"\d{1,3}(?:,\d{3})*", cur.strip()):
            cur += "," + part
        else:
            if cur.strip():
                out.append(cur.strip())
            cur = part
    if cur.strip():
        out.append(cur.strip())
    return out

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Finds what the deck left out of the manuscript")
    ap.add_argument("deck", help="the built deck PDF")
    ap.add_argument("--source", default=None,
                    help="the manuscript (usually this - the manuscript is always the answer key)")
    ap.add_argument("--ref", default=None,
                    help="a previous deck PDF. Used only when reworking a deck that already exists")
    ap.add_argument("--max-words", type=int, default=8,
                    help="in the page-by-page check, flag when more than this many words disappear (default 8)")
    ap.add_argument("--max-sentences", type=int, default=10)
    ap.add_argument("--sidecar", default=None, metavar="TSV",
                    help="the figs/values.txt that `build_figs` leaves behind. A "
                         "value drawn inside a figure is not in the PDF's "
                         "text layer, so without this, everything is counted as \"unused\"")
    ap.add_argument("--omit", default="", metavar="V1,V2",
                    help="manuscript values deliberately left out of the deck "
                         "(comma-separated; use `;` if it's confusable with a thousands comma). Shown separately, not counted; "
                         "write the reason in plan.md. Giving a sentence fragment of five or more characters (three or more letters in a row) "
                         "also counts an explanatory sentence containing that fragment as deliberately dropped")
    ap.add_argument("--script", default=None, metavar="MD",
                    help="the spoken script (out/script.md). A value spoken there is excluded from \"values not used\" and shown separately")
    a = ap.parse_args(argv)
    if not a.source and not a.ref:
        ap.error("one of --source or --ref must be given "
                 "(if there's no previous deck, use --source - that's the usual case)")

    deck_text = "\n".join(t for _, t in pages(a.deck))
    # A value drawn inside a figure is not in the PDF's text layer.
    #   Without reading the sidecar, everything gets counted as "not used".
    #   `outcheck` takes a sidecar for exactly this reason: a checker's false
    #   positive hides the real problem.
    _side = ""
    if a.sidecar and os.path.exists(a.sidecar):
        with io.open(a.sidecar, encoding="utf-8") as f_:
            _side = f_.read()
        deck_text += "\n" + _side
    # Text for the main deck only: excludes backup slides (from the builder's `figs/backup_pages.txt`) and that section's figure values
    _bkp = os.path.join(os.path.dirname(os.path.abspath(a.deck)), "figs", deckspec_backup_list())
    main_deck = None
    if os.path.exists(_bkp):
        with io.open(_bkp, encoding="utf-8") as f_:
            _bk = {int(x) for x in f_.read().split() if x.strip().isdigit()}
        _pg = pages(a.deck)
        main_deck = "\n".join(t for i, (_, t) in enumerate(_pg, 1) if i not in _bk)
        main_deck += "\n" + "\n".join(
            ln for ln in _side.splitlines()
            if not (re.match(r"(?:chart|diagram)_?(\d+)", ln)
                    and int(re.match(r"(?:chart|diagram)_?(\d+)", ln).group(1)) in _bk))
    bad = 0
    if a.source:
        _sp = ""
        if a.script and os.path.exists(a.script):
            with io.open(a.script, encoding="utf-8") as f_:
                _sp = f_.read()
        # The deck's text is split into text blocks, since a title has no
        #   period, so splitting by sentence would merge a title and a bullet
        #   into one unit, and then it can't be matched against a manuscript sentence
        _units = []
        _d = fitz.open(a.deck)
        for _p in _d:
            for _b in _p.get_text("blocks"):
                _t = re.sub(r"\s+", " ", _b[4]).strip()
                if len(_t.split()) >= 4:
                    _units.append(_t)
        _d.close()
        bad += against_source(deck_text, a.source, a.max_sentences, _sp,
                              # A thousands comma ("14,562") is not split, or splitting it would make it impossible to exclude
                              split_omit(a.omit), _units, main_deck)
    if not a.ref:
        print()
        print("   %s" % ("everything in the manuscript was touched." if not bad
                         else "%d issue(s) - see the items above. If it's deliberately dropped, put it in `--omit` (value or sentence fragment) and "
                              "write the reason in plan.md." % bad))
        return 1 if bad else 0

    pa, pb = pages(a.ref), pages(a.deck)
    pairs, extra = match(pa, pb)

    print()
    print("=" * 78)
    print("checked page by page against the previous deck: %d pages · %d pages" % (len(pa), len(pb)))
    print("=" * 78)
    for i, j in pairs:
        ta, fa = pa[i - 1]
        if j is None:
            print("! %2d -> ??  %-44s no match" % (i, ta[:44]))
            bad += 1
            continue
        fb = pb[j - 1][1]
        lw = sorted(words(fa) - words(fb))
        ln = sorted(nums(fa) - nums(fb))
        off = ln or len(lw) > a.max_words
        bad += bool(off)
        print("%s %2d -> %2d  %-44s words -%-3d values -%d %s"
              % ("! " if off else "  ", i, j, ta[:44], len(lw), len(ln),
                 " ".join(ln[:8])))
        if off and lw:
            print("        words that disappeared: %s" % " ".join(lw[:14]))

    if extra:
        print()
        print("pages that exist only in the built deck: %s"
              % ", ".join("%d(%s)" % (j, pb[j - 1][0][:34]) for j in extra))
        print("   (a slide with a different title, like an impact slide, can't be matched - confirm it by eye in one line)")

    na = set()
    nb = set()
    for _, t in pa:
        na |= nums(t)
    for _, t in pb:
        nb |= nums(t)
    print()
    print("%d distinct on-screen values in the original · %d in the built deck · %d value(s) missing"
          % (len(na), len(nb), len(na - nb)))
    if na - nb:
        print("   " + " ".join(sorted(na - nb)))
        bad += 1
    print()
    print("   %s" % ("matches the original." if not bad
                     else "%d spot(s) differ from the original. Start with the words that disappeared." % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    sys.exit(main())
