# -*- coding: utf-8 -*-
"""deckcheck tests — the negative tests are the point.

Testing only inputs that pass proves nothing, because a checker can always
print "0 issues". In this project, **20 real defects once stayed alive while
the checker kept printing 0**.

So here we deliberately plant an error in the fixture and check that
exactly that one gets caught.

The fixture is on a subject completely unrelated to the project this skill
was extracted from (synthetic battery data). That is the only basis for the
claim that it is "general-purpose".

    python -m unittest discover skills/talk-deck/tests
"""
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import deckcheck  # noqa: E402

LATEX = os.path.join(HERE, "fixtures", "latex")
MARKDOWN = os.path.join(HERE, "fixtures", "markdown")


def run(cfg_dir, edits=None):
    """Copies the fixture into a temp folder, applies `edits`, and runs it.

    `edits` = {filename: [(string to find, string to replace with), ...]}
    Returns (exit code, output).
    """
    tmp = tempfile.mkdtemp(prefix="deckcheck-")
    try:
        for f in os.listdir(cfg_dir):
            src = os.path.join(cfg_dir, f)
            if os.path.isdir(src):              # subfolders like figs/ come along too
                shutil.copytree(src, os.path.join(tmp, f))
            else:
                shutil.copy(src, tmp)
        for name, subs in (edits or {}).items():
            p = os.path.join(tmp, name)
            with io.open(p, encoding="utf-8") as f:
                t = f.read()
            for old, new in subs:
                assert t.count(old) >= 1, "%r not found in fixture" % old
                t = t.replace(old, new, 1)
            with io.open(p, "w", encoding="utf-8") as f:
                f.write(t)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = deckcheck.main(os.path.join(tmp, "config.yaml"))
        return code, buf.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class CleanFixture(unittest.TestCase):
    """A clean input must pass first. Otherwise the negative tests are meaningless."""

    def test_latex_fixture_passes(self):
        code, out = run(LATEX)
        self.assertEqual(code, 0, out)
        self.assertIn("all 0 — passed", out)

    def test_markdown_fixture_passes(self):
        code, out = run(MARKDOWN)
        self.assertEqual(code, 0, out)

    def test_reverse_coverage_reports_unused(self):
        """Section E finds values that were left out. The fixture has two values
        that are only in the table, not in the deck."""
        _, out = run(LATEX)
        tail = out[out.index("E. Reverse direction"):]
        self.assertIn("2 value(s) never used", tail)
        self.assertIn("0.3", tail)
        self.assertIn("1.4", tail)


class InjectedErrors(unittest.TestCase):
    """The core of it. Every planted error must be caught, without exception."""

    def test_number_not_in_source(self):
        code, out = run(LATEX, {"deck.tex": [("92.4", "77.7")]})
        self.assertEqual(code, 1, out)
        self.assertIn("77.7", out)

    def test_banned_word_in_deck(self):
        code, out = run(LATEX, {
            "deck.tex": [("The anode loses", "This magical result proves the anode loses")]})
        self.assertEqual(code, 1, out)
        self.assertIn("magical", out)

    def test_banned_word_in_script(self):
        code, out = run(LATEX, {"script.md": [("The anode loses", "So the anode loses")]})
        self.assertEqual(code, 1, out)

    def test_claim_missing_from_source(self):
        """If the evidence disappears from the source, section B must catch it —
        even if it is still in the deck."""
        code, out = run(LATEX, {"paper.tex": [
            ("\\textminus45.6 percent and the cathode", "45.6 percent and the cathode"),
            ("\\textbf{\\textminus45.6}", "\\textbf{45.6}")]})
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"FAIL\s+anode pulse")

    def test_note_content_is_not_screen_text(self):
        """Speaker notes are not the screen. A number that only exists in a note must
        not be counted as "on the screen".

        Regression test for a defect where a non-greedy regex broke on nested
        braces (`$n{=}600$`).
        """
        code, out = run(LATEX, {"deck.tex": [("$n{=}600$ 이라고 말한다", "$n{=}600$ 과 99.9 를 말한다")]})
        self.assertEqual(code, 0, out)
        self.assertNotIn("99.9", out.split("B. Key claims")[0])


class SyntaxGuard(unittest.TestCase):
    """A misconfigured `syntax` silently disables the checker. Check that it
    is counted as a failure."""

    def test_latex_rules_on_markdown_is_caught(self):
        code, out = run(MARKDOWN, {"config.yaml": [("syntax: plain", "syntax: latex")]})
        self.assertEqual(code, 1, out)
        self.assertIn("the deck has not a single backslash", out)

    def test_percent_is_content_in_plain_mode(self):
        """The part after `92.4% and we ran 600 cycles` must survive."""
        with io.open(os.path.join(MARKDOWN, "deck.md"), encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("600", deckcheck.screen_text(raw, syntax="plain"))
        self.assertNotIn("600", deckcheck.screen_text(raw, syntax="latex"))


class AmbiguousClaim(unittest.TestCase):
    """A claim with no `source:` can only be trusted if **that value appears
    exactly once in the source**.

    If it appears more than once, there is no way to tell which occurrence it
    matched — the checker will print "present" even if it matched the same
    number in a completely different sentence. That is why it requires the
    context to be pinned down.
    """

    BARE = ("{label: anode CC-CV,   value: \"12.3\", source: 'textminus12\\.3'}",
            "{label: anode CC-CV,   value: \"12.3\"}")

    def test_bare_value_with_several_matches_is_not_accepted(self):
        code, out = run(LATEX, {"config.yaml": [self.BARE]})
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"appears in the source \d+ times")
        self.assertIn("Pin the context with `source:`", out)

    def test_pinning_the_context_makes_it_pass(self):
        """Even the same claim passes once `source:` pins down the context —
        this is the fixture's default."""
        code, out = run(LATEX)
        self.assertEqual(code, 0, out)
        self.assertIn("anode CC-CV", out)


class BanFileFormat(unittest.TestCase):
    """A banned term must be expressible as a plain word.

    Forcing a regex kills it. In a blind trial, 12 of 20 kinds ended up as
    regexes that matched nothing at all because of a trailing end-of-line
    comment, and section C had been printing "0 issues, passed" the whole time.
    """

    def test_plain_word_line_is_matched_with_boundaries(self):
        code, out = run(LATEX, {
            "banned.txt": [("magical", "wondrous")],
            "deck.tex": [("The anode loses", "A wondrous anode loses")]})
        self.assertEqual(code, 1, out)
        self.assertIn("wondrous", out)

    def test_plain_word_does_not_match_inside_another_word(self):
        """Word boundaries are attached — it is unusable if `art` matches inside
        `artifact`."""
        code, out = run(LATEX, {
            "banned.txt": [("magical", "art")],
            "deck.tex": [("The anode loses", "An artifact appeared and the anode loses")]})
        self.assertEqual(code, 0, out)

    def test_regex_needs_the_re_prefix_to_stay_a_regex(self):
        pats = deckcheck.ban_patterns({"_read": lambda p: "a.b\nre:a.b\n",
                                       "ban_file": "x"})
        # word: the dot is a literal character (still true even with the
        # inflection/negation guard attached)
        self.assertTrue(re.search(pats[0], "x a.b y"))
        self.assertFalse(re.search(pats[0], "x aXb y"))
        self.assertEqual(pats[1], "a.b")            # re: prefix makes it a regex

    def test_a_plain_banned_phrase_takes_inflections_and_spares_negation(self):
        """trial 38 — "always better" matched "not always better", and "matters as
        much" failed to catch "matter as much"."""
        pats = deckcheck.ban_patterns({"_read": lambda p: chr(10).join(["always better", "matters as much", ""]),
                                       "ban_file": "x"})
        self.assertTrue(re.search(pats[0], "it is always better", re.I))
        self.assertFalse(re.search(pats[0], "it is not always better", re.I))
        self.assertTrue(re.search(pats[1], "this matter as much as that", re.I))

    def test_trailing_comment_does_not_kill_the_pattern(self):
        code, out = run(LATEX, {
            "banned.txt": [("magical", "magical    # rejected in §44")]})
        self.assertEqual(code, 0, out)
        code, out = run(LATEX, {
            "banned.txt": [("magical", "magical    # rejected in §44")],
            "deck.tex": [("The anode loses", "This magical anode loses")]})
        self.assertEqual(code, 1, out)


class SelfTest(unittest.TestCase):
    """Does the checker itself prove that it is capable of failing?"""

    def _selftest(self, edits=None):
        tmp = tempfile.mkdtemp(prefix="selftest-")
        try:
            for f in os.listdir(LATEX):
                src = os.path.join(LATEX, f)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(tmp, f))
                else:
                    shutil.copy(src, tmp)
            for name, subs in (edits or {}).items():
                p = os.path.join(tmp, name)
                with io.open(p, encoding="utf-8") as f:
                    t = f.read()
                for old, new in subs:
                    t = t.replace(old, new)
                with io.open(p, "w", encoding="utf-8") as f:
                    f.write(t)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = deckcheck.selftest(os.path.join(tmp, "config.yaml"))
            return code, buf.getvalue()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_every_section_catches_its_canary(self):
        _, out = self._selftest()
        for sec in ("A unsourced numbers", "B key claim", "C banned phrasing", "D script"):
            self.assertRegex(out, r"OK\s+%s\s+canary -> caught" % re.escape(sec))

    def test_empty_claims_is_reported_not_passed(self):
        """If `claims:` is left empty, section B is an empty section. It must
        not read as a pass."""
        code, out = self._selftest({"config.yaml": [("claims:", "claims: []\n_old_claims:")]})
        self.assertEqual(code, 1, out)
        self.assertIn("claims is empty", out)

    def test_dead_ban_file_is_reported(self):
        code, out = self._selftest({"config.yaml": [("ban_file: banned.txt",
                                                     "ban_file: nope.txt")]})
        self.assertEqual(code, 1, out)
        self.assertIn("0 kinds of banned phrase", out)

    def test_broken_coverage_pattern_is_reported(self):
        """If one layer of backslash is stripped, section E finds 0 kinds and
        passes silently."""
        code, out = self._selftest({
            "config.yaml": [("coverage_pattern:", "coverage_pattern: 'zzz(\\d+\\.\\d)'\n_old:")]})
        self.assertEqual(code, 1, out)
        self.assertIn("coverage_pattern is broken", out)


class Helpers(unittest.TestCase):
    def test_example_for_builds_a_string_the_pattern_catches(self):
        for pat, want in ((r"\bproves?\b", "proves"),
                          (r"\b(clearly|obviously)\b", "clearly"),
                          (r"\bstate[- ]of[- ]the[- ]art\b", "state-of-the-art"),
                          (r"\bstate\-of\-the\-art\b", "state-of-the-art")):
            self.assertEqual(deckcheck.example_for(pat), want)
        self.assertIsNone(deckcheck.example_for(r"\bvery\s+\w+\b"))

    def test_strip_braced_handles_nesting(self):
        s = "a \\note{x $x{=}2$ y} b"
        self.assertEqual(deckcheck.strip_braced(s, "note").strip(), "a  b")

    def test_sidecar_merges_by_tag(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
        import sidecar
        tmp = tempfile.mkdtemp(prefix="sidecar-")
        try:
            p = os.path.join(tmp, "v.txt")
            sidecar.write(p, {"a"}, ["a\t1", "a\t2"])
            sidecar.write(p, {"b"}, ["b\t3"])
            sidecar.write(p, {"a"}, ["a\t9"])          # replaces only "a"
            d = sidecar.read(p)
            self.assertEqual(d["a"], ["a\t9"])
            self.assertEqual(d["b"], ["b\t3"])          # "b" must still be there
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_timing_counts_acronyms_as_multiple_words(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
        import timing
        # acronyms come from the spec — the script has no values of its own
        self.assertEqual(timing.TOKEN_WORDS, {})
        self.assertGreater(timing.words("NMC811", {"NMC811": 6}), 3.0)
        self.assertEqual(timing.words("NMC811"), 1.0)
        self.assertEqual(timing.words("the"), 1.0)
        self.assertEqual(timing.spoken_words("12.3"), 3)  # twelve point three

    def test_prose_audit_reads_the_spec_directly(self):
        """If a tool demands an input format that is not in the pipeline, nobody
        uses it.

        It used to accept only a slide-list JSON, and there was no step that
        produced that JSON. And on the screen side it only looked at the title —
        it was the table that leaked the term first.
        """
        sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
        import prose_audit as pa
        tmp = tempfile.mkdtemp(prefix="prose-")
        try:
            p = os.path.join(tmp, "slides.yaml")
            with io.open(p, "w", encoding="utf-8") as f:
                f.write('meta: {title: T, author: A, venue: V, date: D}\n'
                        'slides:\n'
                        '  - title: "Prior work"\n'
                        '    table: {header: [Method, Score], '
                        'rows: [["HVCX", "1.0"]]}\n'
                        '    say: ["Others have looked at this."]\n'
                        '  - title: "Ours"\n'
                        '    bullets: ["x"]\n'
                        '    say: ["HVCX groups valves that share one line."]\n')
            got = pa.from_spec(p)
            self.assertEqual(len(got), 2)
            self.assertIn("HVCX", got[0]["screen"])      # words in the table are part of the screen too
            self.assertNotIn("HVCX", got[0]["say"][0])   # spoken aloud, it first appears in slide 2
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_overlap_denominator_is_the_first_sentence(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
        import prose_audit as pa
        repeat = pa.overlap("Each oven burns the loaves at the edge",
                            "Each oven burns the loaves at the edge. Look left.")
        explain = pa.overlap("Second: which door the parcels leave by",
                             "The second choice is the one people skip.")
        self.assertGreater(repeat, 0.9)
        self.assertLess(explain, 0.6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
