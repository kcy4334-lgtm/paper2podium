# -*- coding: utf-8 -*-
"""Talk-time calculation. Do not estimate by eye.

    seconds = spoken word count / WPM * 60 + per-slide silence

Naive word counting undercounts a talk's length in two specific ways.

  A number is read as several words. `-12.3` is spoken "minus twelve point
  three," four words, not one token.
  An acronym is read as several words too. `NMC811` is spoken "en em cee
  eight one one," not one word. Missing this can put a talk's real length
  several minutes past its computed one.

`spoken_words()` converts numbers automatically. Acronyms are not automatic:
how they are read varies by field (`NASA` is read "nasa," `SoC` is read
"ess oh cee"). So acronyms are measured and written into the spec
(`meta.acronyms`).

Measuring an acronym's word value (carrier-sentence differencing):
  1. Synthesize a baseline sentence with TTS and time it.
     "We can see the result in the table today."
  2. Synthesize the same sentence again with the token inserted.
     "We can see the NMC811 result in the table today."
  3. Divide the length difference by the length of one baseline word.
     That's the word-count conversion value.
  The lead-in and trail-off cancel out, leaving only the token's own length.

  Without TTS, measure the same difference with the presenter's own voice
  and a stopwatch: read both sentences three times each and subtract the
  medians. Without even that, write the value as an estimate instead: an
  acronym read letter by letter is one word per letter, one read as a word
  (NASA) is one word. Mark it as an estimate in the spec. Writing an
  estimate down as an estimate isn't fabrication; treating an unmeasured
  value as measured is.

Do not fix this value by eyeballing it. To change it, measure it again the same way.

Korean, Chinese, and Japanese text need their own counting. Word counting is
built on `[A-Za-z0-9]`, so no Hangul character is counted as a word. A
10-minute talk built from a Korean report once came out as
`computed 1:25 · remaining 8:34`, when the true total was about 8:16, so the
`--limit` gate could not trigger on it. A silent zero here does not mean the
text is short; it means the tool could not read it.

CJK is counted by syllables, not words, at the rate `SYL_PER_SEC` below: the
midpoint of the measured range for spoken Korean, 4.5-5.5 syllables/sec.
Time your own script with a stopwatch once and adjust `timing.SYL_PER_SEC`.

Text it can't count, it reports. If there are characters but the conversion
comes out 0, `uncountable()` flags it, so a silent 0 is never mistaken for
"it's short."
"""
import re

WPM = 135          # native-speaker reading rate; non-native speakers reading numbers carefully run 115-125
# Midpoint of the measured range for spoken Korean, 4.5-5.5 syllables/sec. This is an estimate; verify with a stopwatch.
SYL_PER_SEC = 5.0
# Hangul, kana, kanji — characters with no word boundaries, or where spacing doesn't mark meaning.
CJK = re.compile(r"[가-힣぀-ヿ一-鿿]")

# Empty on purpose. An acronym's word value is field-specific, so it goes in
# the spec's `meta.acronyms` instead of being hard-coded here, which would
# tie the skill to one paper's field and break the rule that the script
# holds no project-specific values.
TOKEN_WORDS = {}
# Symbols read aloud -> word count (percent · about · times · plus or minus · at most · at least)
SYMBOL_WORDS = {u"%": 1, u"≈": 1, u"×": 1, u"±": 3, u"≤": 2,
                u"≥": 2, u"→": 1}


def _int_words(s):
    n = int(s)
    if n < 100:
        return 1                    # seventeen · ninety-seven (hyphenated, so one word)
    if n < 1000:
        return 3                    # five hundred and five
    # A four-digit number read as a year is two words (nineteen sixteen).
    # Otherwise it's read broken into thousands/millions: 203000 is spoken
    # "two hundred three thousand," which the recursive split below handles.
    if 1000 <= n <= 2099 and n % 100 != 0:
        return 2
    if 1000 <= n < 10000 and n % 100 == 0 and n % 1000 != 0:
        return 2                    # fifteen hundred
    for unit in (10 ** 9, 10 ** 6, 10 ** 3):
        if n >= unit:
            rest = n % unit
            return _int_words(str(n // unit)) + 1 + (_int_words(str(rest)) if rest else 0)
    return 2


def spoken_words(tok):
    """Word count for one numeric token, as spoken aloud."""
    if "." in tok:                  # 12.3 -> twelve / point / three
        a, b = tok.split(".", 1)
        return _int_words(a) + 1 + len(b)
    return _int_words(tok)


def words(s, table=None):
    """Spoken word count. Converts numbers and acronyms to the word count as read aloud.

    `table` layers on top of the default table instead of overwriting it.
    Overwriting would wipe out the whole default table the moment the spec
    adds one acronym, losing every other acronym silently to gain the one.
    """
    t = TOKEN_WORDS if not table else dict(TOKEN_WORDS, **table)
    n = 0.0
    # A sign before a number is spoken as "minus," one word. The token regex
    # below doesn't catch the sign on its own, so it's counted here instead.
    n += len(re.findall(r"(?<![\w.])[-−](?=\d)", s))
    # Symbols that are read aloud count too: Δ in "ΔT" is spoken "delta," and
    # the percent sign in "92%" is spoken "percent." A Greek letter counts as
    # one word for its name; a symbol counts by however many words its
    # reading takes.
    n += len(re.findall(u"[Α-Ωα-ω]", s))
    n += sum(k * len(re.findall(re.escape(c), s)) for c, k in SYMBOL_WORDS.items())
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*", s):
        core = w.strip(".")
        # A hyphenated term is read segment by segment: "ISO-8601" is two
        # words, not one. If the whole term is in the table, that value wins.
        if "-" in core and core not in t and not re.fullmatch(r"-?\d+(\.\d+)?", core):
            n += sum(words(x, table) for x in core.split("-") if x)
            continue
        _nu = re.fullmatch(r"(\d+(?:\.\d+)?)([A-Za-z]{1,3})", core)
        if re.fullmatch(r"\d+(\.\d+)?", core):
            n += spoken_words(core)
        elif _nu and core not in t:
            # A number with a unit attached (8.65M · 350GB · 175B) is read as
            # number plus unit, not as a single word. If the unit itself is
            # in the table, that value wins.
            _ord = _nu.group(2).lower() in ("st", "nd", "rd", "th")     # 1st = "first"
            n += spoken_words(_nu.group(1)) + (0 if _ord else t.get(_nu.group(2), 1))
        elif core in t:
            n += t[core]
        else:
            n += 1
    return n


def syllables(s):
    """CJK syllable count. Counts Hangul, kana, and kanji."""
    return len(CJK.findall(s))


def uncountable(lines):
    """Reports any text it can't count.

    If there are clearly characters but both the word count and the
    syllable count come out 0, that does not mean the text is short. It
    means the text is written in characters this tool can't read. Returns
    the list of such lines.
    """
    out = []
    for s in lines:
        body = re.sub(r"\s+", "", str(s))
        if body and not words(s) and not syllables(s):
            out.append(str(s)[:60])
    return out


def seconds(lines, pause=0.0, wpm=WPM, table=None, syl_rate=SYL_PER_SEC):
    """Sentence list + that slide's silence -> seconds.

    Words (Latin) and syllables (CJK) are counted separately and added.
    Even when both appear in one sentence, each is computed at its own
    rate, since English acronyms embedded in a Korean talk are common.
    """
    w = sum(words(s, table) for s in lines)
    syl = sum(syllables(s) for s in lines)
    return w / float(wpm) * 60.0 + syl / float(syl_rate) + pause


def total(slides, wpm=WPM, table=None):
    """`slides` = [{"say": [...], "pause": seconds}, ...] -> (total seconds, per-slide seconds)"""
    per = [seconds(s.get("say", []), s.get("pause", 0), wpm, table) for s in slides]
    return sum(per), per


def hhmm(sec):
    return "%d:%02d" % (int(sec) // 60, int(sec) % 60)


if __name__ == "__main__":
    demo = "The NMC811 cell reaches 41.5 after 900 cycles, up 29.2 points."
    print("word count %.1f  (naive token count %d)"
          % (words(demo), len(demo.split())))
    print("=> %s" % hhmm(seconds([demo])))
