# -*- coding: utf-8 -*-
"""Two-way checker for a derivative against its source of record (generic).

Checks that a **derivative** (a talk deck, a PPTX, a spoken script) made from a
finalized original (a paper, a report) does not diverge from that original. The
checker used to be tied to one project; paths, claims and banned phrases were
pulled out into config so it now runs on any manuscript.

    python deckcheck.py <config.yaml>
    python deckcheck.py <config.yaml> --selftest      # is the checker alive?

Sections it runs:
    A. Do the numbers shown on the derivative actually exist in the source?
    B. Are the key claims present on both sides: derivative and source?
    C. Banned phrasing (hype words + wording the project has retired)
    D. Numbers and banned phrasing in the spoken script (what goes out loud)
    E. Reverse direction: values the source has that the derivative never uses
    F. PPTX <-> deck two-way set difference + fonts (only when a pptx is given)
    G. PPTX structure (page numbers, slide count, aspect ratio)

Exits 1 if there is any failure.

Three design principles (all added after this project was actually burned by
their absence):
  1. Never hardcode a reference value. Things like slide count or the page-number
     denominator are read from the target being checked. Bake them in as constants
     and the check quietly passes the day the target changes.
  2. Numbers drawn inside a figure come in through a sidecar. A checker that
     reads source text cannot see a value printed inside a PNG. The generator that
     drew the figure leaves its own values in a TSV, and this reads them too.
  3. A checker must prove it can fail (`--selftest`).
     A checker can report a pass while it isn't actually watching anything: a
     banned-phrase pattern dead from a stray comment, `coverage_pattern` finding
     zero matches because a backslash had been stripped, or a wrong `syntax`
     setting silently dropping half the deck's text. Each of these can pass
     without any warning. So each section gets a deliberately wrong value
     planted into it, to see whether that section actually catches it. If it
     doesn't, the section is dead, and a dead section counts as a failure.
"""
import argparse
import io
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required:  pip install pyyaml")


def _paper(path):
    """Manuscript text: expands `\\input` and macros (see `deckspec.read_paper`)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import deckspec
    return deckspec.read_paper(path)


def strip_tex_comments(s):
    """Delete everything after a `%` to end of line. Keeps `\\%` (a literal percent)."""
    return re.sub(r"(?<!\\)%.*", "", s or "")


def slurp(path):
    """Read a whole file as UTF-8. Always closes the handle."""
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def spit(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ── LaTeX/text cleanup ───────────────────────────────────────────────
def strip_braced(s, cmd):
    """Remove `\\cmd{...}` using brace balancing.

    A non-greedy regex (`\\note\\{.*?\\}`) must not be used, or if the note
      itself contains braces such as `$x{=}2$`, it cuts at the first `}` and
      the rest is counted as body text. That would let a value that exists
      only in the note wrongly pass as "on screen".
    """
    out, i, tag = [], 0, "\\" + cmd + "{"
    while True:
        j = s.find(tag, i)
        if j < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:j])
        k, d = j + len(tag), 1
        while k < len(s) and d:
            d += 1 if s[k] == "{" else -1 if s[k] == "}" else 0
            k += 1
        i = k


# A unit letter (cm, in, em, ...) is a dimension only when it is attached
#   to a number with no letter right after. Allowing `\s*` would let "81.5 in dry
#   cells" get its `81.5 in` erased as a dimension, so section A would silently
#   miss that number. A length command (`0.9\linewidth`) is
#   still a dimension even with a space before it.
DIM = re.compile(r"\d*\.?\d+(?:(?:cm|mm|pt|em|ex|in)(?![A-Za-z])"
                 # `\textheight` is a length too, or the 0.46 in
                 #   `max height=0.46\textheight` would be flagged as an "unsourced
                 #   number" that `skip_numbers` couldn't fix either
                 r"|\s*\\(?:textwidth|textheight|paperwidth|paperheight|columnwidth"
                 r"|height|width|linewidth|baselineskip))")
# A table's column spec (`{llrr}`) is not text, or it would be flagged as "wording
#   not in the source"
COLSPEC = re.compile(r"\\begin\{(?:tabular\*?|tabularx|array)\}(?:\{[^{}]*\})?"
                     r"\{(?:[^{}]|\{[^{}]*\})*\}")

# A typesetting command's argument is not on-screen text. It can
#   contain a bare unitless number, so `DIM` does not catch it. This actually
#   leaked through twice and made the checker fail a perfectly fine deck: the
#   38 in `\fontsize{34}{38}`, the 14 in `\fontsize{14}{16}`. Each time it was
#   patched by adding it to `skip_numbers`, but that's a workaround. The real
#   fix is to not read it as text in the first place.
TYPESET = (
    "fontsize", "scalebox", "resizebox", "rule", "raisebox", "kern",
    "hspace", "vspace", "setlength", "addtolength", "arraystretch",
    "setbeamersize", "hskip", "vskip", "extrarowheight", "tabcolsep",
    "columnsep", "baselineskip", "parskip", "abovecaptionskip",
)
# Strips `\cmd{..}{..}` and `\cmd*[..]{..}` together with their arguments
# An argument is short. Without a length bound, `\vspace{0.35em}`
#   followed by `{\footnotesize ...a whole footnote...}` would get swallowed as an
#   argument too, and on-screen text would disappear. That footnote's number
#   would then be flagged as "only in the PPTX", since the checker had closed its eyes.
#   A typesetting argument is at most about twenty characters and never more
#   than two of them.
TYPESET_RE = re.compile(
    r"\\(?:" + "|".join(TYPESET) + r")\b\*?"
    r"(?:\s*\[[^\]]{0,24}\])?(?:\s*\{[^{}]{0,24}\}){0,2}")
# Vertical spacing after a line break, `\\[0.25em]`: also typesetting, not content
OPTLEN = re.compile(r"\\\\\s*\[[^\]]{0,24}\]")


def strip_drawing(s):
    """Strips drawing code and font declarations that are not on-screen text. Keeps label `{…}` content.

    The TikZ coordinates (0.125) drawn by `figure.highlight` could otherwise be counted
      as numbers, `rectangle`/`line width` counted as words, and the
      `\\setsansfont{Malgun Gothic}` in an xelatex preamble would also become a word,
      the skill's own feature failing the skill's own check.
    """
    s = re.sub(r"\\(?:set\w*font|setCJK\w*|newfontfamily)\b[^\n]*",
               " ", s)
    s = re.sub(r"\\draw\[[^\]]*\][^;]*;", " ", s)
    s = re.sub(r"\\node\[[^\]]*\](?:\s*\(\w+\))?(?:\s*at\s*\([^)]*\))?", " ", s)
    # The `\csname f@size\endcsname` the builder emits is typesetting too, or
    #   section H would count "size" as a deck word. It was
    #   first added only to `screen_text`, and it resurfaced in `term_text`,
    #   which section H also uses. Placed here where both call it.
    s = re.sub(r"\\csname\s+[^\\]*?\\endcsname", " ", s)
    return re.sub(r"\\begin\{scope\}\[[^\]]*\]", " ", s)


def screen_text(src, drop_cmds=(), syntax="latex"):
    """Keeps only the text from the deck source that is actually visible on screen.

    Getting `syntax` wrong weakens the check silently. Applying LaTeX
      rules to Markdown treats `%` as a comment start and deletes the rest of
      that line: in a synthetic fixture, "Retention is 92.4% and we ran 600
      cycles in total." was cut down to "Retention is 92.4", and the checker
      reported a pass. It had not looked at the rest of the deck at all.
    """
    if syntax != "latex":
        # Plain text/Markdown: percent signs and dimensions are both content. Only HTML comments are stripped.
        return re.sub(r"<!--.*?-->", " ", src, flags=re.S)

    s = re.sub(r"(?<!\\)%.*", "", src)                 # comments
    for c in drop_cmds:
        s = strip_braced(s, c)                          # speaker notes, etc.
    s = re.sub(r"\\(newcommand|renewcommand|definecolor|usepackage|documentclass)\b.*",
               " ", s)
    s = strip_drawing(s)
    # Typesetting is stripped first. Left after `DIM`, an argument
    #   with no unit like `\fontsize{14}{16}` would survive and get counted as
    #   a content number.
    s = COLSPEC.sub(" ", s)
    s = TYPESET_RE.sub(" ", s)
    s = OPTLEN.sub(" ", s)
    s = DIM.sub(" ", s)                                 # dimensions
    s = re.sub(r"\b[0-9A-Fa-f]{6}\b", " ", s)           # HTML colors
    s = re.sub(r"aspectratio\s*=\s*\d+", " ", s)
    # Numbers can't be found unless this is resolved first. It eats
    #   the trailing space too: the builder writes `\textminus 27.1`, and
    #   if the space were left, it would become "- 27.1", making a negative
    #   claim fail in section B while section E missed the deck's negative
    #   number.
    s = re.sub(r"\\textminus(?:\{\})?\s*", "-", s)
    return s


# Looks at any number of decimal places, not just one. Back when it
#   only looked at one place (`\.\d(?!\d)`), 12.29, 45.61 and 0.999 were
#   outside what section A checks, which is not a pass, it's not looking.
#   Section A was effectively off for papers whose results are all two decimal
#   places and for papers where hyperparameters are the point, and the
#   selftest canary was also one decimal place so it couldn't catch this
#   either.
NUM = re.compile(r"(?<![\w.])(\d{1,4}\.\d+)(?![\d])")


def decimals(s):
    return set(NUM.findall(s))


def flat_thousands(s):
    """Strips thousands separators (19,559 / 203 000 / 203\\,000) down to a joined number."""
    s = str(s or "")
    for _ in range(3):
        s = re.sub(r"(\d)(?:,| | |\\,)(\d{3})(?!\d)", r"\1\2", s)
    # Thousands separated by an ordinary space too: "203 000" pulled
    #   from a journal PDF splits into two numbers otherwise, so the deck's "203,000" would be
    #   flagged as not in the source while "203 000" stayed effectively outside
    #   the check. To reduce false positives, the leading
    #   group is 2-3 digits ("Table 2 150" is not joined), and the trailing
    #   groups are joined only when they are exactly 3 digits each.
    s = re.sub(r"(?<![\d.,])(\d{2,3})((?: \d{3})+)(?![\d.,])",
               lambda m: m.group(1) + m.group(2).replace(" ", ""), s)
    return s


def has(hay, val):
    return bool(re.search(r"(?<![\d.])" + re.escape(val) + r"(?![\d])", hay))


# ── config ──────────────────────────────────────────────────────────────
def load(path):
    _raw = slurp(path)
    # A control character in the config is almost always a broken
    #   backslash: a shell heredoc can turn the `\t` in `\textbf` into an actual
    #   tab, which silently narrows coverage_pattern (351 kinds -> 313 kinds)
    #   while selftest still says OK. Section E can't catch
    #   this with a canary, so it is rejected right here.
    _bad = sorted({"\\x%02x" % ord(c) for c in _raw if ord(c) < 32 and c not in "\n\r"})
    if _bad:
        _ln = next(i for i, l in enumerate(_raw.splitlines(), 1)
                   if any(ord(c) < 32 for c in l))
        raise SystemExit("%s: has control character(s) %s (line %d) — a backslash got mangled while "
                         "writing it from a shell "
                         "(`\\t` -> tab, `\\b` -> backspace). Rewrite it with a file-writing tool."
                         % (path, " ".join(_bad), _ln))
    cfg = yaml.safe_load(_raw) or {}
    base = os.path.dirname(os.path.abspath(path))
    root = os.path.abspath(os.path.join(base, cfg.get("root", ".")))

    def P(p):
        return None if not p else os.path.join(root, p)

    def read(p):
        p = P(p)
        return slurp(p) if p and os.path.isfile(p) else ""

    cfg["_root"], cfg["_P"], cfg["_read"] = root, P, read
    return cfg


META = re.compile(r"[\\(){}\[\]|^$+*?]")

# The name `build_pptx` attaches to the page-number box. Writing it in
#   two places is bound to make them diverge, so it is read from there when
#   available, and the value written here is used only as a fallback.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from build_pptx import PAGENUM_TAG
except Exception:                                  # must still work without python-pptx
    PAGENUM_TAG = "p2t-pagenum"


def ban_patterns(cfg, warn=None):
    """A banned phrase has one file as its single source of truth. Keeping it in two places will always let them drift apart.

    **You can just write the plain word.** There is a reason regex must
      not be required: a whole class of banned-phrase patterns can go dead at once.
      Someone had once written `\\bproves?\\b  # dropped in section 44` and the reason text
      stuck to the regex, so it matched nothing at all. Section C kept
      reporting `0 hits, passed` the whole time.

      Stripping the trailing comment is not enough by itself. A regex that is
      syntactically valid but means the wrong thing (`\\bzzproves?\\b`)
      cannot be caught by any automated check, since it matches its own example.
      So the default path avoids regex entirely:

        state-of-the-art        <- a word. Matched with word boundaries, case-insensitive
        significantly better    <- several words too, just write them as-is
        re:\\bprove(s|n|d)?\\b    <- prefix with `re:` only when you really need a regex

      A line that has metacharacters but no `re:` prefix is treated as an
      old-style file, so it is still read as a regex, but `--selftest` counts
      it as "could not verify individually."
    A pattern that fails to compile is not silently dropped either: it is reported.
    """
    txt = cfg["_read"](cfg.get("ban_file"))
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"\s+(?<!\\)#.*$", "", s).strip()   # trailing comment
        if not s:
            continue
        if s.startswith("re:"):
            s = s[3:].strip()
        elif not META.search(s):
            # It's a plain word. Turn it into a form that cannot go dead.
            # Inflected forms of a word too, or writing "matters as much"
            #   would fail to catch the script's "matter as much". Right before it,
            #   negation (not/never/n't) means it isn't hype: "always
            #   better" would otherwise match inside "not always better".
            #   Hyphenated words are left as-is.
            def _inf(w):
                if "-" in w or len(w) <= 3:
                    return re.escape(w)
                # The stem rule is "strip ing/ed/s -> then strip a trailing
                #   e". Stripping "es" whole turns "proves" into "prov", missing
                #   the base forms "prove"/"proven". The suffix
                #   side also keeps e/en/n (proven, shown).
                base = w
                if not re.search(r"(?:ss|us|is)$", w, re.I):
                    base = re.sub(r"(?<=[^s])(?:ing|ed|s)$", "", w, flags=re.I)
                    if len(base) > 3:
                        base = re.sub(r"e$", "", base, flags=re.I)
                # The stripped suffix goes first in the list of alternatives, so selftest's example rebuilds the exact word it was given
                cut = w[len(base):].lower()
                alts = [a for a in (cut, "e", "es", "s", "ed", "d", "ing", "en", "n") if a]
                alts = [a for i, a in enumerate(alts) if a not in alts[:i]]
                if not cut:
                    alts = [""] + alts
                return re.escape(base) + "(?:%s)?" % "|".join(alts)
            s = (r"(?<!\bnot\s)(?<!\bnever\s)(?<!n't\s)\b"
                 + r"\s+".join(_inf(w) for w in s.split()) + r"\b")
        try:
            re.compile(s)
        except re.error as e:
            if warn is not None:
                warn.append("banned-phrase pattern does not parse as a regex: %r (%s)" % (s, e))
            continue
        out.append(s)
    return out + list(cfg.get("ban_extra") or [])


def ban_kinds(cfg):
    """Counts banned-phrase lines as `plain word / regex marked with re: / unmarked regex`.

    The third kind is the dangerous one — it can be syntactically valid but mean the wrong thing, and no one would know.
    """
    word, marked, bare = 0, 0, []
    for ln in cfg["_read"](cfg.get("ban_file")).splitlines():
        s = re.sub(r"\s+(?<!\\)#.*$", "", ln.strip()).strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("re:"):
            marked += 1
        elif META.search(s):
            bare.append(s)
        else:
            word += 1
    return word, marked, bare


def scan_ban(text, pats, paras=()):
    out = []
    for p in pats:
        for m in re.finditer(p, text, re.I):
            a = max(0, m.start() - 55)
            out.append(re.sub(r"\s+", " ", text[a:m.end() + 35]).strip())
    # A pattern meant only for the start of a paragraph is written with `^`. Matching it against a run (a formatting fragment) gives a false positive.
    for p in [x for x in pats if x.startswith("^")]:
        for q in paras:
            if re.match(p, q.strip(), re.I):
                out.append(re.sub(r"\s+", " ", q.strip()[:90]).strip())
    return out


# ── reading the material ─────────────────────────────────────────────────────────
def _unescape(t):
    r"""Undoes LaTeX's escaped characters — `\&` -> `&`."""
    return re.sub(r"\\([&%_$#{}])", r"\1", t or "")


def bib_entries(paths):
    """The bibliography next to the manuscript — [(author part, years)]. For `.bbl`, it's
    everything before the first `\newblock`; for `.bib`, it's the `author` field. Looks only in the manuscript's folder and its parent."""
    import glob as _g
    dirs = []
    for p_ in paths:
        d_ = os.path.dirname(os.path.abspath(p_))
        for x in (d_, os.path.dirname(d_)):
            if x not in dirs:
                dirs.append(x)
    out_ = []
    for d_ in dirs[:2]:
        for f_ in sorted(_g.glob(os.path.join(d_, "*.bbl"))):
            with io.open(f_, encoding="utf-8", errors="replace") as _fh:
                t = _fh.read()
            for e in re.split(r"\\bibitem", t)[1:]:
                e = re.sub(r"^\s*(\[[^\]]*\])?\s*\{[^}]*\}", "", e)
                auth = re.split(r"\\newblock", e)[0]
                out_.append((auth, set(re.findall(r"(?<!\d)((?:19|20)\d{2})[a-z]?(?!\d)", e))))
        for f_ in sorted(_g.glob(os.path.join(d_, "*.bib"))):
            with io.open(f_, encoding="utf-8", errors="replace") as _fh:
                t = _fh.read()
            for e in re.split(r"\n\s*@", t)[1:]:
                a = re.search(r"\bauthor\s*=\s*[{\"](.*?)[}\"]\s*,?\s*\n", e, re.S | re.I)
                y = re.search(r"\byear\s*=\s*[{\"]?\s*((?:19|20)\d{2})", e, re.I)
                if a and y:
                    out_.append((a.group(1), {y.group(1)}))
    return out_


_CITE = re.compile(r"\b([A-Z][a-z][A-Za-z'\-]+)(?:\s+(?:and|&)\s+[A-Z][A-Za-z'\-]+|\s+et\s+al\.?)?"
                   r",?\s*\(?((?:19|20)\d{2})\)?(?!\d)")


def cite_years(text, bib):
    """On-screen "Name ..., year" cites where that name's bibliography entry does not have that year: [(name, year, entry's years)].

    If the name is not in any entry's author list, it isn't a citation (something like "ICLR 2018"), so it's skipped.
    """
    bad = []
    for m in _CITE.finditer(text or ""):
        nm, yr = m.group(1), m.group(2)
        hit = [ys for a, ys in bib if re.search(r"\b%s\b" % re.escape(nm), a)]
        if not hit:
            continue
        if not any(yr in ys for ys in hit):
            want = sorted(set().union(*hit))
            if (nm, yr) not in [(b[0], b[1]) for b in bad]:
                bad.append((nm, yr, want))
    return bad


class Stuff(object):
    """All the text that goes into the check. `--selftest` shakes this up to test it."""

    def __init__(self, cfg):
        read = cfg["_read"]
        D = cfg.get("derivative") or {}
        self.cfg, self.D = cfg, D
        # A LaTeX comment is not part of the source of record. A value
        #   that exists only in a comment would then count as "sourced", and a
        #   claim regex matching a comment line would let it pass.
        #   A check that treats a missing basis as present is
        #   not a check.
        # A Markdown manuscript is cut at the bibliography heading, or
        #   volume and page numbers would otherwise become source-of-record numbers,
        #   letting unrelated deck numbers pass (as with a manuscript
        #   converted from a PDF). Cut per manuscript; a numeric table that
        #   follows is kept.
        _refcut = re.compile(r"(?mi)^#{1,3}\s*(?:references|bibliography)\s*$")
        self.source = "\n".join(_paper(cfg["_P"](p)) if str(p).lower().endswith((".tex", ".pdf"))
                                and cfg["_P"](p) and os.path.isfile(cfg["_P"](p))
                                else _refcut.split(read(p) or "")[0]
                                for p in (cfg.get("source") or []))
        # Also keeps the manuscript before macros are expanded, or writing a
        #   key claim's `source:` regex the way the paper spells it out
        #   (`\gopher 5-shot`) would fail to find it in the expanded manuscript
        #   (`\textit{Gopher}`)
        try:
            import deckspec as _dsp
            self.source_raw = "\n".join(
                _dsp.read_tex(cfg["_P"](p)) if str(p).lower().endswith(".tex")
                and cfg["_P"](p) and os.path.isfile(cfg["_P"](p)) else ""
                for p in (cfg.get("source") or []))
        except Exception:                              # if it can't be read, only the expanded manuscript is used
            self.source_raw = ""
        self.syntax = cfg.get("syntax", "latex")
        self.deck_raw = read(D.get("deck"))
        self.spoken = read(D.get("spoken"))
        self.side = read(cfg.get("sidecar"))
        self.skip = {str(x) for x in (cfg.get("skip_numbers") or [])}
        # A number in the title slide's venue, date, or institute is
        #   not content, or the paper's year kept only in `\def\year{2018}`,
        #   which gets stripped, would leave the title slide's "AAAI 2018" flagged
        #   as a number not in the source. Excluded from the spec's meta.
        try:
            _sp = cfg["_P"](cfg.get("spec")) if cfg.get("spec") else None
            if _sp and os.path.isfile(_sp):
                import yaml
                _m = (yaml.safe_load(slurp(_sp)) or {}).get("meta") or {}
                for k in ("venue", "date", "institute"):
                    v = _m.get(k)
                    for x in (v if isinstance(v, list) else [v]):
                        self.skip |= set(re.findall(r"\d{2,}", str(x or "")))
        except Exception:
            pass
        self.pat_warn = []
        self.pats = ban_patterns(cfg, self.pat_warn)

    @property
    def deck(self):
        return screen_text(self.deck_raw, self.cfg.get("drop_commands") or [],
                           self.syntax)

    def copy(self):
        import copy as _c
        n = _c.copy(self)
        n.pats = list(self.pats)
        n.pat_warn = list(self.pat_warn)
        return n


# ── main body ──────────────────────────────────────────────────────────────
# Words that don't carry meaning — count these and the list turns into an English dictionary.
TERM_STOP = set((
    "a an the of in on at to for and or but not no is are was were be been "
    "this that these those it its as by from with without than then so very "
    "we our us you your they them their he she his her "
    "each per one two three four five both all any some more most less least "
    "same other another such only just also even still yet much many few "
    "what which who whom when where how why if because while into onto over "
    "under after before between during through about above below across "
    "figure table slide page section appendix backup next previous here there "
    "does do did done can may might will would should must shall "
    "have has had get gets got make makes made take takes took "
    "use uses used using show shows shown see seen look looks looked "
    "say says said ask asks asked give gives given know knows knew "
    "first second third last left right top bottom different "
    "every either neither none out up down off "
    "work works worked need needs needed want wants wanted "
    "thing things way ways part parts case cases point points "
    "time times number numbers value values result results "
    "example examples note notes question questions answer answers "
    # Words for how to read a table or figure. Words the skill itself
    #   instructs to use ("read the row", "blank cells") would otherwise be flagged as
    #   "wording not in the source".
    "read reads reading row rows column columns cell cells blank blanks "
    "dash dashes grid grids panel panels tile tiles line lines "
    "shaded coloured colored bold marked mark marks red green grey gray "
    # Words from the caption "From the paper (Fig. 3)" that planning §plots instructs to use would otherwise be flagged as a coined word
    "paper papers figure figures fig table tables appendix "
    # Ordinary English is not that deck's working vocabulary, or
    #   flagging "cannot"/"never"/"enough"/"nothing" as "wording not in the
    #   source" would force common words into
    #   `coined_ok` over and over. What this check looks for is
    #   terminology. Words that just connect a sentence are excluded.
    "cannot never always often sometimes usually enough nothing something anything "
    "everything nobody someone anyone everyone itself themselves himself herself "
    "yourself ourselves myself exist exists existed again already almost quite rather "
    "really simply clearly actually probably perhaps maybe instead however therefore "
    "thus hence although though unless until since whether whole half twice once "
    "keep keeps kept let lets put puts call calls called come comes came go goes went "
    "gone find finds found tell tells told think thinks thought mean means meant "
    "try tries tried turn turns turned move moves moved begin begins began start "
    "starts started stop stops stopped end ends ended hold holds held bring brings "
    "brought run runs ran leave leaves left change changes changed enter enters "
    "entered happen happens happened follow follows followed seem seems seemed "
    "big small large long short high low new old good bad better worse best worst "
    "real true false easy hard heavy light fast slow early late later earlier full "
    "empty open close near far enough able own sure clear whole main key plain "
    "against along around away back behind beside beyond toward towards within "
    "today tomorrow now ever yes okay dollar dollars people year years day days"
).split())

# Does not start right after a digit, or it would pick up
#   `e-08` from `1.78e-08` as a word.
TERM_RE = re.compile(
    r"(?<![\w.])[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*")

# Commands that are themselves machine language — stripped whole, including their arguments (color names, file names).
MACHINE_CMD = re.compile(
    r"\\(?:textcolor|fcolorbox|colorbox|definecolor|color|graphicspath|usetheme|metroset"
    r"|usepackage|documentclass|adjincludegraphics|includegraphics|adjustbox|resizebox|scalebox"
    r"|label|ref|pageref|hspace|vspace|rule|setlength|input|include"
    r"|setbeamer[A-Za-z]*|newcommand|renewcommand|def)\s*"
    r"(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})?(?:\{[^{}]*\})?")


def term_text(s, syntax="latex"):
    """Strips machine language before extracting terms.

    A command name, environment name, color name, or figure file name is
      not something the audience hears. If the checker's first line of output
      is garbage, nobody reads the second line.
    """
    if syntax != "latex":
        return s or ""
    # A comment is not on screen. Counting it would mean the checker is reading its own source code.
    s = re.sub(r"(?<!\\)%[^\n]*", " ", s or "")
    s = strip_drawing(s)
    s = COLSPEC.sub(" ", s)
    # An environment's typesetting argument (`\\begin{adjustbox}{max width=…}`, column width) is not text either
    s = re.sub(r"\\begin\{(?:adjustbox|minipage|column|columns|block)\}"
               r"(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?", " ", s)
    s = MACHINE_CMD.sub(" ", s)
    s = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", " ", s)
    s = re.sub(r"\\[A-Za-z@]+\*?", " ", s)
    s = re.sub(r"\[[^\[\]\n]{0,90}\]", " ", s)
    return re.sub(r"[{}$&~^_%\\]", " ", s)


SIDECAR_FIELDS = {"label", "panel", "note", "ylabel", "title", "takeaway",
                  "verdict", "callout", "legend", "caption", "lead", "corner",
                  "row_label", "col_label", "col_notes"}


def sidecar_text(s):
    """The sidecar: the first column is a figure name, so it's not text."""
    out = []
    for line in (s or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        cells = line.split('\t')
        # If the second column is a field name (label, ylabel,
        #   title, ...) and the third is empty, that name is not text.
        #   Otherwise counting it would catch "ylabel" as a deck word.
        if len(cells) >= 3 and cells[2] == "" and cells[1] in SIDECAR_FIELDS:
            cells = cells[3:]
        else:
            cells = cells[1:]
        out.append('\t'.join(cells))
    # A math command in figure text (`$\\beta_2$`) is not something the audience hears, it reads as a symbol
    return re.sub(r"\\[A-Za-z]+", " ", '\n'.join(out))


IRREGULAR = {
    "kept": "keep", "held": "hold", "led": "lead", "left": "leave", "lost": "lose",
    "made": "make", "meant": "mean", "ran": "run", "rose": "rise", "risen": "rise",
    "shown": "show", "seen": "see", "saw": "see", "taken": "take", "took": "take",
    "gave": "give", "given": "give", "found": "find", "fell": "fall", "fallen": "fall",
    "grew": "grow", "grown": "grow", "knew": "know", "known": "know", "went": "go",
    "gone": "go", "brought": "bring", "built": "build", "chose": "choose",
    "chosen": "choose", "drove": "drive", "driven": "drive", "spent": "spend",
    "split": "split", "stood": "stand", "told": "tell", "thought": "think",
    "won": "win", "wrote": "write", "written": "write", "broke": "break",
    "broken": "break", "began": "begin", "begun": "begin", "sent": "send",
}


def fold(w):
    """For comparison: lowercase, strip hyphen/slash, a very rough stem.

    `per-bed` and `per bed`, `irrigate` and `irrigated` are treated as
      the same word. Otherwise the list fills up with mere spelling
      differences, and then nobody reads it.
    """
    w = re.sub(r"[-/]", "", w.lower())
    # Irregular inflections are folded to their base form, or "kept" would be counted as a different word from the paper's "keep".
    w = IRREGULAR.get(w, w)
    # -ies -> -y ("families" vs. the paper's "family")
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    # "comparably" is "comparable"; stripping only "-ly" would split it into "comparab"
    if len(w) > 6 and w.endswith(("ably", "ibly")):
        w = w[:-1] + "e"
    # Derivational suffixes are stripped too, or "existence" in the
    #   paper next to the deck's "exist" would get flagged as wording not in the source.
    #   It's fine for this to be rough, since it's only a stem for comparison.
    for suf in ("ences", "ence", "ances", "ance", "ments", "ment", "ness", "ities", "ity",
                "ations", "ation", "ally", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[:-len(suf)]
            break
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[:-len(suf)]
            break
    # A leftover trailing `e` is also trimmed, or `irrigated ->
    #   irrigat` while `irrigate -> irrigate`, and the two would count as different words.
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def _uncontract(s):
    """Expands English contractions — can't, won't, doesn't, I'm, it's, ..."""
    s = re.sub(r"\b([Cc])an['’]t\b", r"\1an not", s)
    s = re.sub(r"\b([Ww])on['’]t\b", r"\1ill not", s)
    s = re.sub(r"\b(\w+)n['’]t\b", r"\1 not", s)
    return re.sub(r"\b(\w+)['’](s|re|ve|ll|d|m)\b", r"\1", s)


def coined_terms(deck_text, source_text, floor=3):
    """Wording the deck uses often but the source never has. [(word, count in the deck)].

    Using something once or twice may just be connective wording. Using
      it three or more times (`coined_floor`) makes it that deck's working vocabulary,
      and if the paper doesn't have it, the talk has drifted from the paper.
    """
    # A subscript number is read joined to its letter, or the paper's
    #   `$F_1$` and the deck's "F1" would be treated as different words, giving
    #   "0 hits in the source". Unicode subscripts (F₁) are handled the same way.
    _st = re.sub(r"([A-Za-z])\s*[_^]\s*\{?\s*(\d+)\s*\}?", r"\1\2", source_text or "")
    _st = _st.translate({ord(c): ord("0") + i for i, c in enumerate(u"₀₁₂₃₄₅₆₇₈₉")})
    _st = _st.translate({ord(c): ord("0") + i for i, c in enumerate(u"⁰¹²³⁴⁵⁶⁷⁸⁹")})
    # Contractions are expanded before reading, or the title's "doesn't" would split into "doesn", giving "0 hits in the paper".
    _st = _uncontract(_st)
    # A symbol is read as the word for it: the paper only writes
    #   `\%`, while the deck and script say "percent", which would otherwise get flagged as
    #   wording not in the source. Only symbols that are read aloud are converted.
    _st = re.sub(r"\\?%", " percent ", _st)
    deck_text = _uncontract(deck_text or "")
    _sw = TERM_RE.findall(_st)
    src = set(fold(w) for w in _sw)
    # It's common for the paper to space something out that the deck
    #   joins (or the reverse). Counting those as different words fills the
    #   list with mere spelling differences, and real coined terms get buried underneath.
    src |= set(fold(a + b) for a, b in zip(_sw, _sw[1:]))
    # Parts of a hyphenated word are also the paper's wording: the
    #   paper has "vendor-specific" five times, yet the deck's "vendor" would otherwise be
    #   flagged as wording not in the paper.
    # Parts of a slash-joined word ("orientation/tracking") too: fold strips the slash and joins it into one word.
    src |= set(fold(x) for w in _sw if "-" in w or "/" in w
               for x in re.split(r"[-/]", w) if len(x) >= 3)
    cnt = {}
    for w in TERM_RE.findall(deck_text or ""):
        if len(w) < 4 and not re.search(r"[-/0-9]", w):
            continue
        lw = w.lower()
        if lw in TERM_STOP:
            continue
        cnt[lw] = cnt.get(lw, 0) + 1
    got = [(w, n) for w, n in cnt.items()
           if n >= floor and fold(w) not in src]
    return sorted(got, key=lambda x: (-x[1], x[0]))


def run(S, out=None):
    """Runs sections A through G and returns `(fail dict, seen dict)`.

    The seen dict is the material for judging whether a section is alive:
    if it found zero of something, that section saw nothing, even if it also reports zero failures.
    """
    out = out or (lambda *a: None)
    cfg, D = S.cfg, S.D
    P = cfg["_P"]
    deck, source, spoken, side = S.deck, S.source, S.spoken, S.side
    pats, skip = S.pats, S.skip
    fail, seen = {}, {}
    bar = "=" * 72

    def head(t):
        out("\n" + bar + "\n" + t + "\n" + bar)

    # A ────────────────────────────────────────────────────────────────
    head("A. Are the numbers shown on the derivative in the source?")
    # A wrong `syntax` setting silently disables the checker (a pass
    #   is reported even if half the deck's text is gone). Only warning about
    #   it without adding it to the total would be the same kind of failure,
    #   so it counts as a failure. A LaTeX deck cannot have zero backslashes.
    kept = 100.0 * len(deck.strip()) / max(1, len(S.deck_raw.strip()))
    out("   syntax=%s · %.0f%% of the deck's raw text survives as on-screen text" % (S.syntax, kept))
    if S.syntax == "latex" and S.deck_raw and "\\" not in S.deck_raw:
        out("   the deck has not a single backslash - this doesn't look "
            "like LaTeX, yet syntax=latex. Everything after `%` gets cut whole. Check syntax")
        fail["syntax misconfigured"] = 1
    miss = sorted(v for v in decimals(deck) if not has(source, v))
    # Integers are checked at any number of digits, including thousands
    #   commas (19,559) and thin spaces (203 000). Checking only up to four
    #   digits would leave a five-digit value in a dollar table (11764 vs.
    #   11794) outside the check. The comparison strips commas from both sides.
    _flat = flat_thousands(source)
    # A trailing period is blocked only when it's a decimal point, or an integer at the end of a sentence ("...then 11794.") would fall outside the check
    ints = sorted({v for v in (flat_thousands(m) for m in re.findall(
        # The deck side is also joined first, or joining only the source
        #   would split the deck's "203 000" into two numbers and miss it in the joined source
        r"(?<![\w.,])(\d{1,3}(?:(?:,| | |\\,)\d{3})+|\d{2,})(?!\d|\.\d|,\d{3})", flat_thousands(deck)))
        if v not in skip and not has(_flat, v)})
    out("   %d decimals · %d values not in the source %s"
        % (len(decimals(deck)), len(miss), miss or ""))
    if ints:
        # A number that isn't content, like
        #   a year or a page number, must be explicitly excluded via `skip_numbers` -
        #   a warning without adding it to the total is exactly a silent pass.
        out("   integers not in the source: %s" % " ".join(ints))
        out("     (if it isn't content, put it in skip_numbers - a warning alone doesn't let it slide)")
    fail["unsourced numbers"] = len(miss) + len(ints)
    seen["A decimals read from the deck"] = len(decimals(deck))
    # Figure/table numbers. Since an integer is only checked against "is
    #   the same number somewhere in the manuscript", a hand-written wrong "Fig.
    #   16" could otherwise pass thanks to an unrelated 16. At minimum, a number
    #   beyond the manuscript's count of
    #   figures or tables is wrong. If unsure, leave the number out.
    if S.syntax == "latex" or "\\begin{figure" in source:
        nfig = len(re.findall(r"\\begin\{figure\*?\}", source))
        ntab = len(re.findall(r"\\begin\{table\*?\}", source))
        badref = []
        for kind, num in re.findall(r"\b(Fig(?:ure)?s?\.?|Tab(?:le)?s?\.?)\s*(\d{1,3})\b", deck):
            lim = nfig if kind.lower().startswith("fig") else ntab
            if lim and int(num) > lim:
                badref.append("%s %s (the manuscript has %d %s)" % (kind, num, lim,
                              ("figure" if lim == 1 else "figures") if kind.lower().startswith("fig")
                              else ("table" if lim == 1 else "tables")))
        for b in sorted(set(badref)):
            out("   nonexistent number: %s" % b)
        fail["figure/table numbers"] = len(set(badref))
    # Citation years. A year exists almost anywhere in the manuscript, so
    #   a wrong one could still pass: the deck's "Kingma and Ba, 2014" (the
    #   bibliography says 2015) could pass thanks to another entry's 2014.
    #   An on-screen "Name ..., year" is checked against that
    #   author's bibliography entry. Skipped if there's no bibliography (.bbl/.bib) next to the manuscript.
    _bib = bib_entries([cfg["_P"](p_) for p_ in (cfg.get("source") or []) if cfg["_P"](p_)])
    if _bib:
        _bad = cite_years(deck, _bib)
        out("   citation years: checked against %d bibliography entries · %d wrong year(s)" % (len(_bib), len(_bad)))
        for nm, yr, want in _bad:
            out("   %s %s - the bibliography entry for %s says %s" % (nm, yr, nm, ", ".join(want)))
        fail["citation years"] = len(_bad)

    # B ────────────────────────────────────────────────────────────────
    head("B. Key claims - on both the derivative and the source")
    bad = 0
    claims = cfg.get("claims") or []
    for c in claims:
        v, lab = str(c["value"]), c["label"]
        in_d = has(deck + side, v) or has(spoken, v)
        if c.get("source"):
            # LaTeX's escaped characters (`\&`, `\%`, `\_`) are also
            #   looked for in the unescaped version, or a pattern that copied
            #   the manuscript's "Kale \& Kumar" verbatim would match in neither version.
            _raw_s = getattr(S, "source_raw", "") or ""
            in_s, note = bool(any(re.search(c["source"], t_) for t_ in
                                  (source, _raw_s, _unescape(source), _unescape(_raw_s)))), ""
        else:
            # Searching for a bare number with no `source` hits the wrong
            #   spot. If that value appears more than once in the source,
            #   there's no way to know which one it matched, so it can't be
            #   marked correct - pinning the context is required instead.
            n = len(re.findall(r"(?<![\d.])" + re.escape(v) + r"(?![\d])", source))
            in_s = n == 1
            note = ("" if n == 1 else
                    "  <- appears in the source %d times. Pin the context with `source:`" % n)
        ok = in_d and in_s
        bad += 0 if ok else 1
        out("   %s %-26s %-7s derivative %s · source %s%s"
            % ("OK  " if ok else "FAIL", lab, v,
               "present" if in_d else "absent", "present" if in_s else "absent", note))
    fail["key-claim check"] = bad
    seen["B number of claims"] = len(claims)

    # C ────────────────────────────────────────────────────────────────
    head("C. Banned phrasing - hype words + retired wording, %d kinds" % len(pats))
    for w in S.pat_warn:
        out("   %s" % w)
    fail["banned-phrase patterns"] = len(S.pat_warn)
    hits = scan_ban(deck, pats)
    for h in hits:
        out("   %s" % h)
    out("   -> %d hit(s)" % len(hits))
    fail["banned phrasing (deck)"] = len(hits)
    seen["C number of banned phrases"] = len(pats)

    # D ────────────────────────────────────────────────────────────────
    if D.get("spoken"):
        head("D. The script that goes out loud")
        if not spoken:
            out("   no script file - run the generator first")
            fail["script"] = 1
        else:
            sm = sorted(v for v in decimals(spoken) if not has(source, v))
            sh = scan_ban(spoken, pats, spoken.splitlines())
            for h in sh:
                out("   %s" % h)
            out("   %d decimals · %d values not in the source %s · %d banned phrase hit(s)"
                % (len(decimals(spoken)), len(sm), sm or "", len(sh)))
            fail["script"] = len(sm) + len(sh)
        seen["D script character count"] = len(spoken)

    # E ────────────────────────────────────────────────────────────────
    head("E. Reverse direction - values the source has that the derivative never uses")
    custom = bool(cfg.get("coverage_pattern"))
    pat = cfg.get("coverage_pattern")
    # The appendix is not part of the talk, or the appendix's training-config
    #   table would inflate "values never used" with unrelated kinds. Cut
    #   at the same point diffcheck does. To include the appendix too, set `coverage_appendix: true`.
    # A typesetting value in the preamble (before `\begin{document}`), like `\setstretch{0.985}`, is not manuscript content either
    _bdoc = re.search(r"\\begin\{document\}", source or "")
    _s0 = _bdoc.end() if _bdoc else 0
    import diffcheck as _dc
    _ap = _dc.APPENDIX_AT.search(source or "", _s0)
    _cut_appx = bool(_ap and _ap.start() > len(source) * 0.3 and not cfg.get("coverage_appendix"))
    _src_e = source[_s0:_ap.start()] if _cut_appx else source[_s0:]
    # A typesetting dimension is not a value, or a figure width like
    #   `0.285\textwidth` or `width=1.05\textwidth` would come up as an "unused
    #   value" (this happened when the decimal pattern was widened for a theory paper with no tables)
    _src_e = re.sub(r"(?<![\w.])\d*\.?\d+\s*\\(?:text|line|column|paper)(?:width|height)", " ", _src_e)
    _src_e = re.sub(r"\b(?:width|height|scale|angle|trim|clip)\s*=\s*[-\d.]+", " ", _src_e)
    _src_e = re.sub(r"\\(?:[vh]space\*?|scalebox|resizebox|rotatebox|put|begin\{picture\})"
                    r"\s*(?:\{[^{}]*\}|\([^()]*\))", " ", _src_e)
    if pat:
        pool = sorted(set(re.findall(pat, _src_e)))
    else:
        # The default is decimals and multiplier/percent integers, or
        #   counting only decimals would drop a systems paper's key figures (`40x`, `70%`) from this section
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import deckspec as _ds
        pool = sorted(set(_ds.result_numbers(_src_e)))
    unused = [v for v in pool if not (has(deck + side, v) or has(spoken, v))]
    out("   %d value(s) in the source · %d value(s) never used anywhere in the derivative%s"
        % (len(pool), len(unused),
           " (appendix excluded - set coverage_appendix: true to include it)" if _cut_appx else ""))
    if unused:
        out("   " + " ".join(unused))
    # If a custom pattern finds nothing at all in the source, the
    #   pattern is broken. Silently reporting zero would hide that section E
    #   is completely disabled. This actually happened once, in a config file where
    #   `\\textbf` was reduced to `\textbf` and the regex ended up reading a literal tab.
    if custom and not pool:
        out("   coverage_pattern found nothing at all in the source - the pattern is broken.")
        out("     Common cause: a backslash got stripped off (`\\\\textbf` became `\\textbf`).")
        fail["coverage_pattern"] = 1
    out("   (not every value needs to be used - this is a prompt to check by eye whether something was left out)")
    seen["E values found in the source"] = len(pool)

    # F ────────────────────────────────────────────────────────────────
    if D.get("pptx") and os.path.isfile(P(D["pptx"])):
        head("F. PPTX <-> deck")
        from pptx import Presentation
        prs = Presentation(P(D["pptx"]))
        runs, paras, fonts, npic = [], [], {}, 0
        for sl in prs.slides:
            for sh in sl.shapes:
                if sh.shape_type == 13 or sh.__class__.__name__ == "Picture":
                    npic += 1
                tfs = [sh.text_frame] if sh.has_text_frame else []
                if getattr(sh, "has_table", False) and sh.has_table:
                    tfs += [c.text_frame for r in sh.table.rows for c in r.cells]
                for tf in tfs:
                    for p in tf.paragraphs:
                        for r in p.runs:
                            if r.text.strip():
                                runs.append(r.text)
                                fonts.setdefault(r.font.name, []).append(r.text[:28])
                        t = "".join(r.text for r in p.runs)
                        if t.strip():
                            paras.append(t)
        # A page number is not content. The denominator is read from the deck and stripped out (never hardcoded).
        full = " ".join(runs)
        den = cfg.get("page_denominator") or page_denominator(runs, len(prs.slides._sldIdLst))
        if den:
            full = re.sub(r"(?<!\d)\d{1,2}/%d(?!\d)" % int(den), " ", full)
        a, b = decimals(full), decimals(deck)
        only_p, only_d = sorted(a - b), sorted(b - a)
        out("   only in PPTX: %s" % (" ".join(only_p) or "none"))
        out("   only in deck: %s" % (" ".join(only_d) or "none"))
        ph = scan_ban(full, pats, paras)
        for h in ph:
            out("   %s" % h)
        ok_fonts = set(cfg.get("ok_fonts") or [])
        badf = [n for n in fonts if ok_fonts and n not in ok_fonts]
        for n in badf:
            out("   font outside the allowed list: %s (%d occurrence(s))" % (n, len(fonts[n])))
        out("   %d picture(s) · fonts %s" % (npic, ", ".join(str(x) for x in fonts)))
        fail["PPTX set difference"] = len(only_p) + len(only_d)
        fail["banned phrasing (PPTX)"] = len(ph)
        fail["fonts"] = sum(len(fonts[n]) for n in badf)
        seen["F fragments read from PPTX"] = len(runs)

        # ── G. structure ────────────────────────────────────────────────────
        # The denominator is read from the deck. Hardcoding it would let
        #   it warn without adding to the total from the day the slide count changes, and silently pass.
        head("G. PPTX structure")
        n_slide = len(prs.slides._sldIdLst)
        # Page numbers are read from shapes with a name. Looking for
        #   "text shaped like n/m" catches body text too: a footnote's `ratio
        #   27/14` could otherwise be read as a page number and section G would report false
        #   failures even though the deck was fine. For a PPTX
        #   with no named shape (made by another tool), it falls back to the old way, but says so.
        tagged, marked = [], 0
        for sl in prs.slides:
            txt = [sh.text_frame.text for sh in sl.shapes
                   if sh.has_text_frame and sh.name == PAGENUM_TAG]
            marked += bool(txt)
            tagged.append(" ".join(txt))
        if marked:
            hay = tagged
        else:
            print("   the page-number box has no name - falling back to matching by shape of text. "
                  "Something in the body like `27/14` may get mixed in")
            hay = [" ".join(sh.text_frame.text for sh in sl.shapes
                            if sh.has_text_frame) for sl in prs.slides]
        pairs = re.findall(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", " ".join(hay))
        denoms = sorted({int(b) for _, b in pairs})
        dn = denoms[-1] if denoms else 0
        s_seen = {int(a) for a, b in pairs if int(b) == dn}
        gap = [i for i in range(1, dn + 1) if i not in s_seen]
        # Slides with no number = title slide + impact slides
        plain = sum(1 for t in hay
                    if not re.search(r"(?<!\d)\d{1,2}/%d(?!\d)" % dn, t))
        bad_s = (0 if len(denoms) == 1 else 1) + (0 if n_slide == dn + plain else 1)
        out("   %d slides = %d numbered + %d unnumbered   %s"
            % (n_slide, dn, plain, "OK" if not bad_s else "FAIL"))
        out("   page numbers 1..%d %s   %s"
            % (dn, "all present" if not gap else gap, "OK" if not gap else "FAIL"))
        w, h = prs.slide_width, prs.slide_height
        want = cfg.get("aspect")
        if want:
            a, b = (float(x) for x in str(want).split(":"))
            ok_a = abs(w / float(h) - a / b) < 0.01
        else:
            ok_a = True
        out("   aspect ratio %.3f x %.3f in   %s"
            % (w / 914400.0, h / 914400.0,
               ("%s = %s" % (want, "OK" if ok_a else "FAIL")) if want else ""))
        fail["structure"] = bad_s + len(gap) + (0 if ok_a else 1)
        seen["G page-number denominator"] = dn

    # H ────────────────────────────────────────────────
    head("H. Is the wording the deck uses the source's wording?")
    _floor = int(cfg.get("coined_floor", 3))
    _ok = set(str(x).lower() for x in (cfg.get("coined_ok") or []))
    # The spec's `meta.coined_ok` is read too, or writing the same list in two places would let them drift apart.
    _sp = cfg["_P"](cfg.get("spec")) if cfg.get("spec") else None
    if _sp and os.path.isfile(_sp):
        try:
            _meta = (yaml.safe_load(slurp(_sp)) or {}).get("meta") or {}
            _ok |= set(str(x).lower() for x in (_meta.get("coined_ok") or []))
        except Exception as e:
            out("   could not read the spec (%s): %s" % (_sp, e))
    coined = [x for x in coined_terms(
        term_text(S.deck_raw, S.syntax) + " " + sidecar_text(side),
        source, _floor) if x[0] not in _ok]
    out("   %d kind(s) of wording not in the source, out of the deck's working vocabulary (%d+ uses)"
        % (len(coined), _floor))
    for w, n in coined[:20]:
        out("   %-26s deck %d time(s) · source 0 times" % (w, n))
    if len(coined) > 20:
        out("   ... and %d more" % (len(coined) - 20))
    if coined:
        out("     The first place a talk drifts from the paper isn't a number, it's wording.")
        out("     Even if every number is right, if the words the audience hears differ from the paper,")
        out("     the same thing ends up with two names during Q&A. Switch to the source's wording, or")
        out("     if it's a plain-language rewording, disclose it in `coined_ok:`.")
    fail["wording not in the source"] = len(coined)
    seen["H wording not in the source"] = len(coined)

    # I ────────────────────────────────────────────────────────────────
    # Is a quotation exactly as the manuscript has it? Section A checks
    #   numbers, but not what's inside quotation marks:
    #   in a deck that copies out a participant's words or a paper's sentence
    #   (qualitative research, quoting a definition), a reworded or invented
    #   quotation could otherwise pass every check. Only quotes of five words or more are checked (a short quote is emphasis).
    head("I. Is what's inside quotation marks exactly in the manuscript?")
    # Only the screen is checked, since a quotation mark in the script is a
    #   line for the speaker to say, or an anticipated question ("I pause here
    #   for a moment", something like that), not a quotation. Checking the
    #   script too turned every hit into a false positive in one sample deck.
    bad_q = quotes_missing(deck + "\n" + side, source)
    got_q = len(quoted(deck + "\n" + side))
    for where_, q in bad_q:
        out("   %s <<%s>> - not in the manuscript as-is" % (where_, q[:70]))
    if bad_q:
        out("     Copy a quotation exactly as the manuscript has it. If you shortened it, show where with \"...\".")
        out("     If you reworded it, drop the quotation marks - quotation marks are a promise that \"this person said exactly this\".")
    out("   %d quote(s) · %d not in the manuscript" % (got_q, len(bad_q)))
    fail["quotes"] = len(bad_q)
    seen["I quotes"] = got_q

    return fail, seen


_QUOTE = re.compile(u"[\u201c\"]([^\u201d\"]{8,400})[\u201d\"]")


def quoted(text):
    """Text inside quotation marks: only quotes of five words or more.

    A deck is written in LaTeX, and the builder turns "..." into ``...'',
      and an ellipsis into `\\ldots{}`. Not reading this form would give "0 quotes" in
      a deck that actually had eight, with selftest passing regardless because
      its canary inserted "..." directly. A command (`\\textbf{…}`) is stripped, and an ellipsis is kept as "...".
    """
    t = (text or "").replace("``", u"\u201c").replace("''", u"\u201d")
    t = re.sub(r"\\(?:ldots|dots|textellipsis)\s*(?:\{\})?", u"\u2026", t)
    out_ = []
    for m in _QUOTE.finditer(t):
        q = re.sub(r"\\[a-zA-Z]+\*?", " ", m.group(1))
        q = re.sub(r"[{}]", "", re.sub(r"\s+", " ", q)).strip()
        if len(re.findall(r"[A-Za-z0-9\u00c0-\u024f\uac00-\ud7a3]+", q)) >= 5:
            out_.append(q)
    return out_


def _norm_q(s):
    s = (s or "").lower().replace(u"’", "'").replace(u"‘", "'")
    s = re.sub(r"[^a-z0-9À-ɏ가-힣']+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quotes_missing(text, source):
    """Text inside quotation marks that is not in the manuscript as-is: [(location, quote)]."""
    qs = quoted(text)
    if not qs:
        return []
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import diffcheck as _dc
        src = _norm_q(_dc.clean_tex(source or "").replace("``", '"').replace("''", '"'))
    except Exception:
        src = _norm_q(source)
    out_ = []
    for q in qs:
        # A quotation cut with an ellipsis must have its pieces, in order
        parts = [_norm_q(p) for p in re.split(u"\\.\\.\\.|…|\\[\\.\\.\\.\\]", q)]
        parts = [p for p in parts if len(p.split()) >= 2]
        pos, ok = 0, bool(parts)
        for p in parts:
            k = src.find(p, pos)
            if k < 0:
                ok = False
                break
            pos = k + len(p)
        if not ok:
            out_.append(("screen", q))
    return out_


def page_denominator(runs, n_slides):
    """Reads the PPTX's page-number denominator from the deck.

    Having it written by hand in config would run head-on into traps.md's
      "never hardcode a reference value". Among lone `n/m`
      fragments, if the same m appears in at least half the slides, that's
      the denominator. If not, None: nothing gets stripped.
    """
    seen = {}
    for r in runs:
        m = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*", str(r))
        if m and int(m.group(1)) <= int(m.group(2)):
            seen[int(m.group(2))] = seen.get(int(m.group(2)), 0) + 1
    if not seen:
        return None
    m, c = max(seen.items(), key=lambda kv: kv[1])
    return m if c * 2 >= max(1, n_slides - 2) else None


def main(cfg_path):
    cfg = load(cfg_path)
    S = Stuff(cfg)
    if not S.source.strip():
        sys.exit("the source is empty - check the path")
    fail, _ = run(S, print)
    bar = "=" * 72
    print("\n" + bar + "\ntotal\n" + bar)
    print("   " + " · ".join("%s %d" % (k, v) for k, v in fail.items()))
    tot = sum(fail.values())
    print("   %s" % ("all 0 — passed" if tot == 0 else "%d failure(s)" % tot))
    return 1 if tot else 0


# ── self-check ─────────────────────────────────────────────────────────
#
# A pass has two meanings: "it's clean" or "it wasn't looked at." There
#   is only one way to tell them apart: plant something deliberately wrong and see whether it gets caught.
#
# Each entry is (section name, a function that corrupts the material, the fail key that must go up).
# If the fail key doesn't go up, that section is dead.
CANARY_WORD = "zzqxcanary"


def _canaries(S):
    c = []

    def deck_plus(txt):
        def f(n):
            n.deck_raw = n.deck_raw + "\n" + txt + "\n"
        return f
    # A: plants a decimal in the deck that could not possibly be in the source
    c.append(("A unsourced numbers", deck_plus("canary 731.9 value"), "unsourced numbers"))
    # A two-decimal-place canary too, separately, since a hole where two-decimal-place values
    #   went unseen would not be caught by a one-place canary alone.
    c.append(("A second decimal place", deck_plus("canary 0.9173 and 73.18 value"), "unsourced numbers"))
    # A five-digit integer too, for a hole where only up to four digits were checked
    c.append(("A five-digit integer", deck_plus("canary 73,918 value"), "unsourced numbers"))
    # I: plants a made-up quotation not in the manuscript, on screen
    # Planted in the form the builder emits (``...'' and `\ldots{}`), since
    #   planting "..." directly would let a regex that never actually reads
    #   anything in a real deck pass selftest anyway.
    c.append(("I quotes", deck_plus("\\textbf{``a canary sentence \\ldots{} that no paper would "
                                  "ever print here''}"), "quotes"))
    # B: if the claims list is empty, section B sees nothing at all
    if S.cfg.get("claims"):
        def break_claim(n):
            v = str(n.cfg["claims"][0]["value"])
            n.deck_raw = n.deck_raw.replace(v, "")
            n.spoken = n.spoken.replace(v, "")
            n.side = n.side.replace(v, "")
        c.append(("B key claim", break_claim, "key-claim check"))
    # C: builds an actual example from the banned-phrase list and plants it in the deck
    ex = [x for x in (example_for(p) for p in S.pats) if x]
    if ex:
        c.append(("C banned phrasing", deck_plus("We " + " and ".join(ex[:6]) + " here."),
                  "banned phrasing (deck)"))
    # D: the same, for the script
    if S.D.get("spoken") and S.spoken:
        def spoken_plus(n):
            n.spoken = n.spoken + "\nAnd the value was 731.9 percent.\n"
        c.append(("D script", spoken_plus, "script"))
    # F: making a value exist only in the deck should widen the set difference
    if S.D.get("pptx") and os.path.isfile(S.cfg["_P"](S.D["pptx"])):
        c.append(("F PPTX set difference", deck_plus("only-in-deck 612.4"), "PPTX set difference"))
    return c


def example_for(pat):
    """Builds one string that must actually get caught from a banned-phrase regex.

    Not every pattern can be built this way. Only what can be built is built,
    and the rest is None. The goal is to see whether this pattern actually
    catches something, not to reimplement a regex engine. Handling
    `\\bproves?\\b` -> `proves` and `(a|b)` -> `a` covers most of a real banned-phrase file.
    """
    s = pat
    if s.startswith("^"):
        s = s[1:]
    if s.endswith("$"):
        s = s[:-1]
    # A lookaround (`(?<!\bnot\s)`) consumes no characters, so it's stripped
    #   out. Without stripping it, the negation exception attached to word
    #   bans would make every single word-ban line get counted as "couldn't
    #   build an example".
    s = re.sub(r"\(\?<?[!=](?:[^()\\]|\\.)*\)", "", s)
    s = s.replace("\\b", "").replace("\\s+", " ").replace("\\s*", " ")
    s = re.sub(r"\((?:\?:)?([^()|]*)(?:\|[^()|]*)*\)", r"\1", s)   # (a|b) -> a
    s = re.sub(r"(?<!\\)\[([^\]]*)\]", lambda m: m.group(1)[:1], s)  # [abc] -> a
    s = re.sub(r"(.)\?", r"\1", s)                                  # x? -> x
    s = re.sub(r"(.)[+*]", r"\1", s)                                # x+ -> x
    # Undoes the backslashes `re.escape` added — a single word-ban line becomes
    # `\bstate\-of\-the\-art\b`, so without undoing this, even a plain word would be counted as "couldn't build an example".
    s = re.sub(r"\\([^bdswWSDAZnrtfv])", r"\1", s)
    if re.search(r"[\\(){}\[\]|^$+*?]", s) or not s.strip():
        return None                                     # metacharacters left over = give up
    try:
        if not re.search(pat, s, re.I):
            return None                                 # the example we built doesn't actually match
    except re.error:
        return None
    return s.strip()


def selftest(cfg_path):
    """Whether the checker has the ability to fail. Plants a canary in each section and sees whether it's caught."""
    cfg = load(cfg_path)
    S = Stuff(cfg)
    if not S.source.strip():
        sys.exit("the source is empty - check the path")
    quiet = lambda *a: None                                  # noqa: E731
    base, seen = run(S, quiet)

    bar = "=" * 72
    print(bar)
    print("Checker self-check - plants something deliberately wrong and sees whether it gets caught")
    print(bar)

    dead = 0
    tested = set()
    for name, mangle, key in _canaries(S):
        tested.add(str(name).strip()[:1])
        n = S.copy()
        mangle(n)
        got, _ = run(n, quiet)
        rose = got.get(key, 0) > base.get(key, 0)
        dead += 0 if rose else 1
        # Distinguishes the cause. If the reason the canary didn't rise is
        #   "that section is already failing", the section is alive and
        #   the config or deck is wrong. Lumping the two together as the
        #   same kind of "dead" causes a misdiagnosis (as when a claim
        #   with its backslash stripped was already failing in the baseline run).
        why = "caught" if rose else (
            "not caught - already %d failure(s) in the baseline run. Fix that failure first "
            "(run `deckcheck` without --selftest)" % base.get(key, 0)
            if base.get(key, 0) else "not caught - this section is dead")
        print("   %s %-18s canary -> %s" % ("OK  " if rose else "FAIL", name, why))

    # A section for which no canary can be built is not "passed" but "has
    #   nothing to check." Hiding that fact makes an empty config
    #   indistinguishable from a clean one.
    print()
    todo = []
    if not cfg.get("claims"):
        todo.append("B: claims is empty - write down two or three key figures, or section B is an empty section")
    if not S.pats:
        todo.append("C: 0 kinds of banned phrase - check the ban_file path")
    # Section C must be checked pattern by pattern. Even if only one of
    #   twenty kinds is alive, the canary above still reports "caught". That's
    #   how section C can report "0 hits, passed" while most of its patterns are dead.
    if S.pats:
        no_ex = [p for p in S.pats if example_for(p) is None]
        word, marked, bare = ban_kinds(cfg)
        print("   · Of %d kinds of banned phrase, %d were verified by building an example that actually gets caught."
              % (len(S.pats), len(S.pats) - len(no_ex)))
        print("     plain-word lines %d · `re:` regexes %d · unmarked regexes %d"
              % (word, marked, len(bare)))
        if bare:
            # This is the genuinely dangerous cell. `\bzzproves?\b` is
            #   syntactically valid and matches its own example, so no
            #   automated check can catch it. Switching to a plain word makes it disappear.
            plain = [p for p in bare
                     if re.match(r"^\\b[\w '/.\-]+\\b$", p)]
            print("     %d unmarked regex line(s) - even if the syntax is valid, if the meaning is wrong, nobody catches it."
                  % len(bare))
            if plain:
                print("       these %d line(s) are just a single word. Drop the `\\b` and write the "
                      "word plainly, then a typo can't kill it:" % len(plain))
                for p in plain[:6]:
                    print("         %-30s ->  %s" % (p, p[2:-2]))
            rest = [p for p in bare if p not in plain]
            if rest:
                print("       the remaining %d line(s) are genuine regexes. Prefix them with `re:` to declare intent:"
                      % len(rest))
                for p in rest[:6]:
                    print("         %-30s     (example it catches: %s)"
                          % (p, example_for(p) or "could not build one"))
        if no_ex:
            print("     %d kind(s) with no example built could not be verified individually:" % len(no_ex))
            for p in no_ex[:8]:
                print("       %s" % p)
    if not S.D.get("spoken"):
        todo.append("D: no script in the config - numbers going out loud are not being watched")
    if not seen.get("E values found in the source"):
        todo.append("E: found 0 kinds of value in the source - coverage_pattern is broken")
    if not (S.D.get("pptx") and os.path.isfile(cfg["_P"](S.D["pptx"]))):
        todo.append("F/G: no PPTX - the distributed file was not checked")

    for t in todo:
        print("   %s" % t)
    dead += len(todo)

    print()
    for k in sorted(seen):
        print("   %-22s %d" % (k, seen[k]))
    print()
    if dead:
        print("   %d section(s) are watching nothing at all. The \"pass\" reported here "
              "does not mean clean." % dead)
    else:
        # Says by name what was tested. Saying "every section" while E,
        #   G, H had no canary would be misleading.
        _t = "·".join(sorted(tested))
        _u = "·".join(sorted(set("ABCDEFGHI") - tested))
        print("   Every section a canary was planted in (%s) caught it - they're alive in this config." % _t)
        if _u:
            print("   Section(s) %s have no canary - only checked that the input wasn't empty." % _u)
    return 1 if dead else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    ap = argparse.ArgumentParser(description="Two-way checker for a derivative against its source of record")
    ap.add_argument("config")
    ap.add_argument("--selftest", action="store_true",
                    help="checks whether the checker has the ability to fail (canaries)")
    a = ap.parse_args()
    sys.exit(selftest(a.config) if a.selftest else main(a.config))
