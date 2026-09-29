# -*- coding: utf-8 -*-
"""Generation-side tests -- from one `slides.yaml`, three outputs come out; do the three agree with each other.

    python -m unittest discover tests

The end-to-end test (`EndToEnd`) that runs all the way through is the core of this file. Even if each piece passes on its own,
  a mismatch once they are stitched together only surfaces at the podium.
"""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)

# The newline used when concatenating YAML. Writing the backslash directly
# in the string gets stripped one layer at a time by each patch script pass, silently going wrong.
NL = chr(10)

import deckcheck      # noqa: E402
import deckspec       # noqa: E402
import build_deck     # noqa: E402
import build_script   # noqa: E402
import scaffold       # noqa: E402

LATEX = os.path.join(HERE, "fixtures", "latex")
SPEC = os.path.join(LATEX, "slides.yaml")


def tex_body(src):
    """Strip comments from the generated `.tex`.

    This test broke three times over `%` lines that the typesetter never even reads. Assertions on
      the generated output should only concern what actually appears on screen.
    """
    return "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("%"))



def _but_thin(warn):
    """The remaining warnings after filtering out the thin-figure notice.

    It fires because the sample is small, not because it's wrong -- a diagram
      with just two boxes filling an entire figure slide leaves 2/3 of it blank.
    """
    return [w for w in warn if "this figure uses only" not in w]

class Spec(unittest.TestCase):
    """`slides.yaml` must not pass silently -- an empty slide would go to the podium."""

    def _load(self, text):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, text)
            return deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_key_reference_covers_every_accepted_key(self):
        """The single source of truth for the keys that can be used. Writing them again by hand in the docs would let the two drift apart.

        If the table `--keys` prints and the keys the validator actually accepts fall out of sync, whoever reads it hits
        either "it's in the docs but doesn't work" or "it works but nobody knows."
        """
        ref = deckspec.key_reference()
        for k, _ in deckspec.SLIDE_KEYS:
            self.assertIn(k, ref)
        for k, _ in deckspec.PANE_KEYS:
            self.assertIn(k, ref)
        # does this match the keys the validator actually accepts -- missing even one makes the spec unusable
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - title: "T"\n    bullets: ["x"]\n    zzz: 1\n')
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            with io.open(p, "w", encoding="utf-8") as f:
                f.write(spec)
            with self.assertRaises(ValueError) as e:
                deckspec.load(p)
            self.assertIn("zzz", str(e.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError) as e:
            self._load("slides:\n  - title: x\n    bulets: [typo]\n")
        self.assertIn("bulets", str(e.exception))

    def test_ragged_table_is_rejected(self):
        with self.assertRaises(ValueError) as e:
            self._load("slides:\n  - table:\n      header: [a, b]\n"
                       "      rows:\n        - [1, 2]\n        - [3]\n")
        self.assertIn("table", str(e.exception))

    def test_standout_needs_big(self):
        with self.assertRaises(ValueError):
            self._load("slides:\n  - kind: standout\n    title: x\n")

    def test_page_numbers_skip_title_and_standout(self):
        meta, slides, npage = deckspec.load(SPEC)
        kinds = [s["kind"] for s in slides]
        self.assertIn("standout", kinds)
        self.assertEqual(npage, sum(1 for s in slides
                                    if s["kind"] not in ("title", "standout")))
        for s in slides:
            if s["kind"] in ("title", "standout"):
                self.assertIsNone(s["page"])


class Deck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tex = os.path.join(self.tmp, "talk.tex")
        build_deck.build(SPEC, self.tex)
        self.src = deckspec.slurp(self.tex)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_standout_has_the_frametitle_guard(self):
        """If the line after `[standout]` starts with `{`, Beamer swallows it as the frametitle."""
        i = self.src.index("[standout")
        after = self.src[i:i + 200].splitlines()
        self.assertIn("\\vspace{0pt}", after[1])

    def test_standout_frames_are_plain(self):
        """Without `plain`, metropolis prints the page number in dark text on a dark

        background. It's invisible to the eye but still present in the text layer, and the value is the stale
        number from one slide back, which the checker reads as the page number.
        """
        self.assertIn("[standout,plain]", self.src)

    def test_big_minus_is_drawn_not_typeset(self):
        """At 40pt, a minus sign gets stretched into an em dash by font substitution."""
        self.assertIn("\\bigminus", self.src)

    def test_notes_are_emitted_outside_the_frame(self):
        self.assertIn("\\note{", self.src)
        self.assertLess(self.src.index("\\end{frame}"), self.src.index("\\note{"))

    def test_lmodern_is_loaded(self):
        self.assertIn("lmodern", self.src)

    def test_sparse_frames_are_vertically_centred(self):
        """A slide with only a table or figure, top-aligned, leaves the bottom empty."""
        i = self.src.index("Three electrodes, two chargers")
        frame = self.src[i:self.src.index("\\end{frame}", i)]
        self.assertEqual(frame.count("\\vfill"), 2)

    def test_present_figure_is_included(self):
        self.assertIn("adjincludegraphics", self.src)
        self.assertIn("fade.png", self.src)


class Layout(unittest.TestCase):
    """Counting one example deck: bold text appeared on almost every slide, and two-column layout on about one in three.

    If the schema can't express this, whatever content you pour into it becomes a bullet deck.
    The schema was failing to capture the goal, not a matter of how skillfully it was filled in.
    """

    def _build(self, yaml_text):
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, yaml_text)
            out = os.path.join(tmp, "talk.tex")
            build_deck.build(spec, out)
            return deckspec.slurp(out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_inline_bold_and_highlight(self):
        src = self._build('slides:\n  - title: "T"\n'
                          '    bullets: ["a **b** c", "d <hi>e</hi> f"]\n')
        self.assertIn(r"\textbf{b}", src)
        self.assertIn(r"\textcolor{mHi}{\textbf{e}}", src)
        # Comments are excluded before checking. pdflatex never reads `%` lines, yet
        #   this test broke every time a preamble comment carried Korean emphasis markup (`**denominator**`) -- twice.
        #   What the test is checking is "does markup leak onto the screen," not the comments.
        body = "\n".join(l for l in src.splitlines()
                         if not l.lstrip().startswith("%"))
        self.assertNotIn("**", body)
        self.assertNotIn("<hi>", body)

    def test_semantic_colours(self):
        """A reading aid -- red marks values the paper treats as bad, green marks values that are fine.

        With only one way to add emphasis, "skim the colors instead of reading the table" would be impossible.
        """
        src = self._build('slides:\n  - title: "T"\n'
                          '    bullets: ["<hit>-12.3</hit> and <safe>+0.2</safe>"]\n')
        self.assertIn(r"\textcolor{mHit}", src)
        self.assertIn(r"\textcolor{mSafe}", src)

    def test_standout_uses_the_light_palette(self):
        """Deep red/green are unreadable on a dark background, so two color sets are kept."""
        src = self._build('slides:\n  - kind: standout\n    big: "X"\n'
                          '    bullets: ["<hit>-31.8</hit>"]\n')
        self.assertIn(r"\textcolor{mHitLt}", src)
        self.assertNotIn(r"\textcolor{mHit}{", src)

    # ── pane-internal ordering, text weight, vertical flow ─────────────────────────
    #   Without all three of these, there were slides that could not be drawn.

    def test_a_pane_stacks_its_chunks_in_the_written_order(self):
        """The chunks inside one pane stack in the order they were written.

        With one occurrence per key and a fixed order, text could not be placed above the bullets -- `text` was
          always last, so the lead line could never come above the bullets. As a result, all the content
          inside one pane collapsed into a single "bullet."
        """
        src = self._build(
            'slides:' + NL +
            '  - title: "T"' + NL +
            '    left:' + NL +
            '      width: 0.44' + NL +
            '      parts:' + NL +
            '        - text: "OVEN TWO RUNS HOT."' + NL +
            '        - bullets: ["<hit>rye</hit> burns at the edge",' + NL +
            '                    "<safe>white</safe> bakes evenly"]' + NL +
            '        - size: fine' + NL +
            '          text: "OVEN TEMPERATURES ARE IN CELSIUS."' + NL +
            '    right:' + NL +
            '      text: "r"' + NL)
        i_lead = src.index("OVEN TWO")
        i_bull = src.index("rye")
        i_fine = src.index("OVEN TEMPERATURES")
        self.assertLess(i_lead, i_bull, "the lead line comes after the bullets")
        self.assertLess(i_bull, i_fine, "the fine print is not at the bottom")
        # the last chunk is one step smaller
        self.assertIn(r"\scriptsize", src[i_bull:i_fine])

    def test_a_pane_cannot_say_the_same_order_twice(self):
        """Using `parts` together with another key means order gets decided in two places.

        If this were allowed, looking at the spec alone couldn't tell you which comes first, and the three
        builders would each pick their own -- a divergence this skill has already hit four times.
        """
        with self.assertRaises(ValueError) as e:
            self._build('slides:' + NL + '  - title: "T"' + NL +
                        '    left:' + NL +
                        '      text: "a"' + NL +
                        '      parts: [{text: "b"}, {text: "c"}]' + NL +
                        '    right: {text: "r"}' + NL)
        self.assertIn("parts", str(e.exception))

    def test_a_single_chunk_is_not_a_list(self):
        with self.assertRaises(ValueError):
            self._build('slides:' + NL + '  - title: "T"' + NL +
                        '    left: {parts: [{text: "only one"}]}' + NL +
                        '    right: {text: "r"}' + NL)

    def test_fine_print_sits_one_step_below_the_footnote(self):
        """The conclusion sentence and the pile of fine print are stacked at different weights.

        If they were the same weight, "the sentence to read first" and "the thing to look up only if needed"
          would look identical, and the audience would end up reading neither.
        """
        src = self._build(
            'slides:' + NL + '  - title: "T"' + NL +
            '    bullets: ["x"]' + NL +
            '    foot: ["THE NIGHT ROUTE RUNS LATE MOST OFTEN."]' + NL +
            '    fine: ["DELAYS ARE IN MINUTES AFTER THE TIMETABLE."]' + NL)
        i_foot = src.index("THE NIGHT ROUTE")
        i_fine = src.index("DELAYS ARE")
        self.assertLess(i_foot, i_fine)
        self.assertIn(r"\footnotesize", src[:i_foot])
        self.assertIn(r"\scriptsize", src[i_foot:i_fine])

    def test_fine_print_is_refused_on_an_impact_slide(self):
        """Projected, it would be unreadable. An impact slide is a place to leave just one line."""
        with self.assertRaises(ValueError) as e:
            self._build('slides:' + NL + '  - kind: standout' + NL +
                        '    big: "42"' + NL + '    fine: ["tiny"]' + NL)
        self.assertIn("fine", str(e.exception))

    def test_an_impact_slide_can_flow_from_top_to_bottom(self):
        """Vertical flow (`flow`) -- pane down-arrow pane down-arrow last pane.

        `big` places two panes side by side. It cannot produce a top-to-bottom
          progression, and forcing it to reads as a contrast instead.
        """
        src = self._build(
            'slides:' + NL + '  - kind: standout' + NL +
            '    lead: "Every loaf passes three stations."' + NL +
            '    flow: ["DOUGH", "PROOFING SHELF", "OVEN"]' + NL +
            '    bullets: ["Where does the morning batch wait longest?"]' + NL)
        i_from = src.index("DOUGH")
        i_to = src.index("OVEN}")
        self.assertLess(i_from, i_to)
        # there is an arrow in between, and the destination grows bigger
        self.assertIn(r"\Downarrow", src[i_from:i_to])
        self.assertIn(r"\Large", src[i_from:i_to])
        self.assertIn(r"\textbf{OVEN}", src)

    def test_a_flow_of_one_is_not_a_flow(self):
        with self.assertRaises(ValueError) as e:
            self._build('slides:' + NL + '  - kind: standout' + NL +
                        '    flow: ["only one"]' + NL)
        self.assertIn("flow", str(e.exception))

    def test_foot_is_full_width_small_type(self):
        src = self._build('slides:\n  - title: "T"\n    bullets: ["x"]\n'
                          '    foot: ["legend one", "legend two"]\n')
        self.assertIn(r"\footnotesize", src)
        self.assertIn("legend one", src)
        self.assertIn("legend two", src)

    def test_block_kinds(self):
        for kind, env in (("plain", "block"), ("alert", "alertblock"),
                          ("good", "exampleblock")):
            src = self._build('slides:\n  - title: "T"\n'
                              '    block: {kind: %s, title: "B", text: "x"}\n' % kind)
            self.assertIn(r"\begin{%s}{B}" % env, src)

    def test_pane_heading(self):
        src = self._build(
            'slides:\n  - kind: columns\n    title: "T"\n'
            '    left:  {head: "Model A", bullets: ["x"]}\n'
            '    right: {head: "Model B", bullets: ["y"]}\n')
        self.assertIn("Model A", src)
        self.assertIn("Model B", src)

    def test_markup_survives_escaping_order(self):
        """esc must not see the backslash of `\\textbf` and skip the whole thing."""
        src = self._build('slides:\n  - title: "T"\n'
                          '    bullets: ["100% **and** 50%"]\n')
        self.assertIn(r"100\%", src)
        self.assertIn(r"\textbf{and}", src)

    def test_group_label_row_spans_the_table(self):
        """A row where only the first cell is filled is a `\\multicolumn` group label from the paper's table.

        Left as-is in the left cell, it reads as a regular item. This pairs with the defect where the skeleton (⑤)
        dropped this row entirely -- if it's kept, it must be drawn in its proper shape.
        """
        src = self._build(
            'slides:\n  - title: "T"\n'
            '    table:\n      header: [Cell, CC-CV, Pulse]\n'
            '      rows:\n        - ["Cathode variants", "", ""]\n'
            '        - ["NMC 811", "-12.3", "0.0"]\n')
        self.assertIn(r"\multicolumn{3}{l}{\itshape Cathode variants}", src)

    def test_user_math_is_left_alone(self):
        """The builder must not rewrite the inside of a human-written `$...$`.

        Substituting `\\textminus` for the `-` in `$p<10^{-4}$` turns it into
        `$p<10^{\\textminus 4}$` -- it still compiles, only the exponent is wrong.
        This was defect ③ from the blind trial.
        """
        src = self._build('slides:\n  - title: "T"\n'
                          '    bullets: ["$p<10^{-4}$ and a drop of -3.0 hours"]\n')
        self.assertIn("$p<10^{-4}$", src)                 # the formula is unchanged
        self.assertIn(r"\textminus 3.0", src)             # outside the formula it is substituted

    def test_columns_render_two_panes(self):
        src = self._build(
            'slides:\n  - kind: columns\n    title: "T"\n'
            '    left:  {width: 0.6, table: {header: [a, b], rows: [["1", "2"]]}}\n'
            '    right: {bullets: ["x"]}\n')
        self.assertIn(r"\begin{columns}", src)
        self.assertEqual(src.count(r"\begin{column}"), 2)
        # A table inside a column must be constrained to its width, or it overlaps the text in the next pane.
        self.assertIn(r"max width=\linewidth", src)

    def test_columns_requires_both_sides(self):
        with self.assertRaises(ValueError):
            self._build('slides:\n  - kind: columns\n    left: {bullets: ["x"]}\n')

    def test_block_without_title_is_rejected(self):
        """In metropolis's block=fill, a block without a title becomes an empty gray band."""
        with self.assertRaises(ValueError):
            self._build('slides:\n  - title: "T"\n    block: {text: "x"}\n')

    def test_block_renders(self):
        src = self._build('slides:\n  - title: "T"\n'
                          '    block: {title: "B", text: "x"}\n')
        self.assertIn(r"\begin{block}{B}", src)


class MissingFigure(unittest.TestCase):
    """Including a nonexistent figure as-is crashes pdflatex, and the whole deck fails to build."""

    def test_missing_figure_warns_and_does_not_emit_includegraphics(self):
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, "\n".join([
                'meta: {title: "T", figdir: figs}',
                "slides:",
                "  - kind: figure",
                '    title: "F"',
                "    figure: {path: nope.png}",
            ]))
            out = os.path.join(tmp, "talk.tex")
            npage, n, warn = build_deck.build(spec, out)
            src = deckspec.slurp(out)
            self.assertTrue(any("nope.png" in w for w in warn), warn)
            self.assertNotIn("adjincludegraphics", src)
            self.assertIn("missing:", src)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Script(unittest.TestCase):
    def test_timing_is_reported_and_nonzero(self):
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "script.md")
            total, n, th = build_script.build(SPEC, out)
            self.assertGreater(total, 0)
            md = deckspec.slurp(out)
            self.assertIn("**Total ", md)          # an English deck gets the English skeleton
            self.assertIn("Start at the anode row", md)   # did `say` make it in
            self.assertIn("표를 읽지 마시고", md)          # did `ko` make it in
            self.assertIn("손으로 짚는다", md)             # did note/cue make it in
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Scaffold(unittest.TestCase):
    def test_skeleton_is_valid_yaml_and_marks_what_is_missing(self):
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "slides.yaml")
            nsec, ntab, n, skipped = scaffold.build(
                os.path.join(LATEX, "paper.tex"), out)
            self.assertEqual(skipped, [], "a table was skipped")
            self.assertGreaterEqual(ntab, 1)
            meta, slides, _ = deckspec.load(out)      # the skeleton must follow the schema too
            text = deckspec.slurp(out)
            self.assertIn("TODO:", text)
            self.assertTrue(any(s["kind"] == "table" for s in slides))
            # did the table's numbers carry over from the paper as-is (not typed by hand)
            t = [s for s in slides if s["kind"] == "table"][0]["table"]
            flat = " ".join(" ".join(r) for r in t["rows"])
            self.assertIn("-12.3", flat)
            self.assertIn("-45.6", flat)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_multicolumn_separator_row_survives(self):
        """`\\multicolumn{3}{l}{Cathode variants}` has no `&`.

        If it were coded as "skip when there's no `&`," the table's group label would vanish entirely,
        and whoever receives the skeleton would not even know that row had existed. Blind-trial defect ⑤.
        """
        src = ("\\begin{tabular}{lrr}\n\\toprule\n"
               "Cell & CC-CV & Pulse " + chr(92) * 2 + "\n\\midrule\n"
               "\\multicolumn{3}{l}{\\textit{Cathode variants}} " + chr(92) * 2 + "\n"
               "NMC 811 & \\textminus12.3 & 0.0 " + chr(92) * 2 + "\n"
               "\\bottomrule\n\\end{tabular}")
        got, skipped = scaffold.tables(src)
        self.assertEqual(skipped, [])
        align, head, rows, ragged = got[0]
        self.assertEqual(rows[0], ["Cathode variants", "", ""])
        self.assertEqual(rows[1][0], "NMC 811")


class HardPaper(unittest.TestCase):
    """Patterns from a real paper that broke compilation. The synthetic fixtures never caught these.

    The first time a real paper was fed in, pdflatex threw 449 errors. Four causes:
      - the column spec `llrc@{\\hskip 5pt}rr` was read via `[^}]*` and counted as 5 columns
      - a fragment survived from the nested braces in `\\textbf{\\textminus18.9}`
      - `text` ate the leading part of `\\textminus`, producing `minus18.9`
      - a TODO note was in Korean, which pdflatex could not typeset
    """

    HARD = os.path.join(HERE, "fixtures", "hard", "paper.tex")

    def _skeleton(self, tmp):
        out = os.path.join(tmp, "slides.yaml")
        nsec, ntab, n, skipped = scaffold.build(self.HARD, out)
        self.assertEqual(skipped, [], "a table was skipped")
        self.assertEqual(ntab, 1)
        return deckspec.load(out)

    def test_colspec_with_braces_is_counted_correctly(self):
        tmp = tempfile.mkdtemp()
        try:
            meta, slides, _ = self._skeleton(tmp)
            t = [s for s in slides if s["kind"] == "table"][0]["table"]
            self.assertEqual(len(t["header"]), 6, t["header"])
            for r in t["rows"]:
                self.assertEqual(len(r), 6, r)
            self.assertNotIn("r}", " ".join(t["header"]))   # the column spec must not leak into the body
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nested_braces_and_command_boundaries(self):
        tmp = tempfile.mkdtemp()
        try:
            meta, slides, _ = self._skeleton(tmp)
            flat = " ".join(" ".join(r) for s in slides if s["kind"] == "table"
                            for r in s["table"]["rows"])
            self.assertIn("-18.9", flat)         # \textbf{\textminus18.9}
            self.assertNotIn("minus", flat)       # `text` must not consume `\textminus`
            self.assertNotIn("{", flat)
            self.assertNotIn("$", flat)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_citations_and_refs_are_dropped_with_their_arguments(self):
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "slides.yaml")
            scaffold.build(self.HARD, out)
            text = deckspec.slurp(out)
            for leak in ("someref", "tab:main", "dropped entirely"):
                self.assertNotIn(leak, text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_linebreak_does_not_eat_the_following_word(self):
        r"""In the title `cases\\Within`, `Within` disappeared entirely.

        The command-stripping regex read `\Within`, starting from the second backslash, as a command.
        The largest text on the screen came out wrong, yet compilation produced zero errors --
        proof that "it doesn't crash" does not mean "it's correct." Only a visual check catches this.
        """
        tmp = tempfile.mkdtemp()
        try:
            meta, slides, _ = self._skeleton(tmp)
            for w in ("Within", "one small file"):
                self.assertIn(w, meta["title"], meta["title"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skeleton_uses_only_characters_the_builder_can_typeset(self):
        """Someone will always try building the skeleton as-is. pdflatex cannot typeset non-Latin script.

        Restricting output to ASCII only turned both `†` and `‡` into `^`, so the paper's two distinct
          settings stopped being distinguished (blind trial 8). The bar is not "is it ASCII" but "can the builder carry it over."
        """
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "slides.yaml")
            scaffold.build(self.HARD, out)
            text = deckspec.slurp(out)
            known = (set(build_deck.SYMBOL) | set(deckspec._SUP.values())
                     | set(deckspec._SUB.values()))
            bad = sorted({c for c in text if ord(c) > 127 and c not in known})
            self.assertEqual(bad, [], "non-ASCII characters: %r" % bad)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_generated_tex_has_no_math_only_characters_in_text_mode(self):
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "slides.yaml")
            scaffold.build(self.HARD, out)
            tex = os.path.join(tmp, "talk.tex")
            build_deck.build(out, tex)
            src = deckspec.slurp(tex)
            body = "\n".join(l for l in src.splitlines()
                             if not l.lstrip().startswith(("%", "\\usepackage",
                                                           "\\documentclass")))
            # ^ and _ are math-only. Left bare, they trigger "Missing $ inserted".
            body = re.sub(r"\$[^$]*\$", "", body)       # inside math stays untouched
            for m in re.finditer(r"(?<!\\textasciicircum)\^", body):
                self.fail("a bare ^ remained: %r" % body[max(0, m.start() - 40):m.start() + 10])
            for m in re.finditer(r"(?<!\\)_", body):
                self.fail("a bare _ remained: %r" % body[max(0, m.start() - 40):m.start() + 10])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class EndToEnd(unittest.TestCase):
    """The core test -- from one spec, produce all three and cross-check against the paper."""

    def test_one_spec_three_outputs_all_consistent(self):
        try:
            import pptx  # noqa: F401
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx

        tmp = tempfile.mkdtemp()
        try:
            for f in ("paper.tex", "numbers.md", "banned.txt", "figvalues.txt",
                      "generated.yaml"):
                shutil.copy(os.path.join(LATEX, f), tmp)
            build_deck.build(SPEC, os.path.join(tmp, "talk.tex"))
            build_pptx.build(SPEC, os.path.join(tmp, "talk.pptx"))
            build_script.build(SPEC, os.path.join(tmp, "script.md"))

            buf = io.StringIO()
            with redirect_stdout(buf):
                code = deckcheck.main(os.path.join(tmp, "generated.yaml"))
            out = buf.getvalue()
            self.assertEqual(code, 0, out)
            # since both come from the same source, the PPTX and the deck cannot diverge -- that's the point
            self.assertIn("only in PPTX: none", out)
            self.assertIn("only in deck: none", out)
            # the section-E pattern must still be alive (zero matches means the pattern is broken)
            self.assertNotIn("found nothing at all", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_broken_coverage_pattern_is_caught(self):
        """A pattern with one layer of backslash stripped away silently matches zero. This must be caught."""
        tmp = tempfile.mkdtemp()
        try:
            for f in ("paper.tex", "numbers.md", "banned.txt"):
                shutil.copy(os.path.join(LATEX, f), tmp)
            build_deck.build(SPEC, os.path.join(tmp, "talk.tex"))
            deckspec.spit(os.path.join(tmp, "c.yaml"), "\n".join([
                "root: .",
                "source: [paper.tex, numbers.md]",
                "derivative: {deck: talk.tex}",
                "syntax: latex",
                "drop_commands: [note]",
                "skip_numbers: [16, 10, 40, 46, 2026]",
                "ban_file: banned.txt",
                # one layer of backslash -- the regex reads it as \t (tab)
                r"coverage_pattern: '&\s*(?:\textbf\{)?(\d{1,2}\.\d)'",
            ]))
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = deckcheck.main(os.path.join(tmp, "c.yaml"))
            self.assertEqual(code, 1, buf.getvalue())
            self.assertIn("found nothing at all", buf.getvalue())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unsourced_integer_counts_as_failure(self):
        """It used to just print without adding it to the total -- that was a silent pass."""
        tmp = tempfile.mkdtemp()
        try:
            for f in ("paper.tex", "numbers.md", "banned.txt"):
                shutil.copy(os.path.join(LATEX, f), tmp)
            build_deck.build(SPEC, os.path.join(tmp, "talk.tex"))
            deckspec.spit(os.path.join(tmp, "c.yaml"), "\n".join([
                "root: .",
                "source: [paper.tex, numbers.md]",
                "derivative: {deck: talk.tex}",
                "syntax: latex",
                "drop_commands: [note]",
                "skip_numbers: [16, 10, 40, 46]",   # 2026 was deliberately left out
                "ban_file: banned.txt",
            ]))
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = deckcheck.main(os.path.join(tmp, "c.yaml"))
            self.assertEqual(code, 1, buf.getvalue())
            self.assertIn("2026", buf.getvalue())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RefCheck(unittest.TestCase):
    """Have the machine say "something feels off" before a person has to point it out."""

    def _profile(self, yaml_text):
        import refcheck
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, yaml_text)
            return refcheck.profile_spec(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bullets_only_deck_is_flagged(self):
        n, got, _ = self._profile(
            "slides:\n" + "".join(
                '  - title: "T%d"\n    bullets: ["a", "b"]\n' % i for i in range(5)))
        self.assertEqual(got["bullets_only"], 1.0)
        self.assertEqual(got["emphasis"], 0.0)

    def test_rich_deck_is_not_flagged(self):
        n, got, _ = self._profile(
            'slides:\n'
            '  - kind: columns\n    title: "**T**"\n'
            '    left:  {table: {header: [a], rows: [["<hit>1</hit>"]]}}\n'
            '    right: {bullets: ["x"]}\n')
        self.assertEqual(got["bullets_only"], 0.0)
        self.assertEqual(got["columns"], 1.0)
        self.assertEqual(got["emphasis"], 1.0)

    def test_reference_profile_reads_a_beamer_source(self):
        import refcheck
        tmp = tempfile.mkdtemp()
        try:
            tex = os.path.join(tmp, "ref.tex")
            deckspec.spit(tex, "\n".join([
                r"\begin{frame}{A}",
                r"\begin{columns}",
                r"\begin{tabular}{l}\textbf{x}\end{tabular}",
                r"\end{columns}",
                r"\end{frame}",
                r"\begin{frame}{B}",
                r"\begin{itemize}\item y\end{itemize}",
                r"\end{frame}",
            ]) + "\n")
            n, got, _ = refcheck.profile_tex(tex)
            self.assertEqual(n, 2)
            self.assertEqual(got["columns"], 0.5)
            self.assertEqual(got["table"], 0.5)
            self.assertEqual(got["bullets_only"], 0.5)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_notes_do_not_count_as_screen_content(self):
        """Notes are not the screen. Counting them would inflate the reference profile."""
        import refcheck
        tmp = tempfile.mkdtemp()
        try:
            tex = os.path.join(tmp, "ref.tex")
            deckspec.spit(tex, "\n".join([
                r"\begin{frame}{A}",
                r"\begin{itemize}\item y\end{itemize}",
                r"\end{frame}",
                r"\note{\textbf{bold in a note}}",
            ]) + "\n")
            n, got, _ = refcheck.profile_tex(tex)
            self.assertEqual(got["emphasis"], 0.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Charts(unittest.TestCase):
    """"Figures can't be made without being tied to raw data" was only half right.

    Of the 12 figures in a real deck, half needed no raw log at all, and the remaining values were
    already sitting in the spec's tables. Drawing from a table brings the sidecar along for free --
    there is no hand-copying step at all.
    """

    SPEC = ("meta: {title: T}\n"
            "slides:\n"
            "  - kind: columns\n"
            '    title: "T"\n'
            "    left:\n"
            "      table:\n"
            '        header: ["m", "A", "B"]\n'
            "        rows:\n"
            '          - ["one", "<hit>-12.3</hit>", "+0.0"]\n'
            '          - ["two", "+0.3", "<hit>-45.6</hit>"]\n'
            "    right:\n"
            "      chart: {from: left, kind: heat}\n")

    def test_chart_is_drawn_and_sidecar_written(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        import build_figs
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, self.SPEC)
            side = os.path.join(tmp, "values.txt")
            made, lines, warn = build_figs.build(spec, os.path.join(tmp, "figs"), side)
            self.assertEqual(warn, [])
            self.assertEqual(len(made), 1)
            self.assertTrue(os.path.isfile(made[0]))
            # the plotted values must be present in the sidecar as-is -- the checker reads them from there
            body = deckspec.slurp(side)
            self.assertIn("-12.3", body)
            self.assertIn("-45.6", body)
            self.assertNotIn("<hit>", body)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_deck_includes_the_chart_once_it_has_been_drawn(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        import build_figs
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, self.SPEC)
            build_figs.build(spec, os.path.join(tmp, "figs"))
            out = os.path.join(tmp, "talk.tex")
            npage, n, warn = build_deck.build(spec, out)
            src = deckspec.slurp(out)
            self.assertIn("adjincludegraphics", src)
            self.assertIn("chart_01_right.png", src)
            self.assertEqual(warn, [], warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_deck_warns_when_the_chart_has_not_been_drawn(self):
        """Building the deck without drawing the figure must not fail silently."""
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, self.SPEC)
            out = os.path.join(tmp, "talk.tex")
            npage, n, warn = build_deck.build(spec, out)
            self.assertTrue(any("chart_01_right" in w for w in warn), warn)
            self.assertIn("missing", deckspec.slurp(out))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_chart_pointing_at_a_missing_table_warns(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        import build_figs
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec,
                          "meta: {title: T}\nslides:\n"
                          '  - kind: columns\n    title: "T"\n'
                          "    left:  {bullets: [x]}\n"
                          "    right: {chart: {from: left, kind: heat}}\n")
            made, lines, warn = build_figs.build(spec, os.path.join(tmp, "figs"))
            self.assertEqual(made, [])
            self.assertTrue(any("no table" in w for w in warn), warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class MathAcrossOutputs(unittest.TestCase):
    """Formulas rendered only in the deck; in the PPTX the raw source text was printed verbatim.

    `$p<10^{-4}$` showed up on the PowerPoint slide, dollar signs, braces and all, and since the numbers
    matched, even the checker missed it. A spot where the two outputs silently diverge, so it is pinned down with a test.
    """

    def test_math_becomes_text_for_outputs_without_latex(self):
        from deckspec import math_to_text as M
        self.assertEqual(M("$n{=}900$"), "n=900")
        self.assertEqual(M("$p<10^{-4}$"), "p<10⁻⁴")
        self.assertEqual(M(r"weights$^{\dagger}$"), "weights†")
        self.assertEqual(M(r"$\Delta$T"), "ΔT")
        self.assertEqual(M("no math here"), "no math here")

    def test_pptx_has_no_latex_left(self):
        try:
            import pptx  # noqa: F401
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec,
                          'meta: {title: T}\nslides:\n'
                          '  - title: "T"\n'
                          "    bullets:\n"
                          "      - 'Across $n{=}900$ riders, $p<10^{-4}$.'\n")
            out = os.path.join(tmp, "t.pptx")
            n, npage, warn = build_pptx.build(spec, out)
            self.assertEqual([w for w in warn if "LaTeX" in w], [], warn)
            from pptx import Presentation
            body = " ".join(sh.text_frame.text for sl in Presentation(out).slides
                            for sh in sl.shapes if sh.has_text_frame)
            self.assertNotIn("$", body)
            self.assertIn("n=900", body)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_latex_leak_into_pptx_is_reported(self):
        """If any command other than a formula leaks through, a backslash prints on screen. This counts and reports it."""
        try:
            import pptx  # noqa: F401
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec,
                          'meta: {title: T}\nslides:\n'
                          '  - title: "T"\n'
                          "    bullets: ['a \\hfill b']\n")
            n, npage, warn = build_pptx.build(spec, os.path.join(tmp, "t.pptx"))
            self.assertTrue(any("LaTeX" in w for w in warn), warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Italic(unittest.TestCase):
    """Without `*italic*`, the asterisks print as-is on screen. This actually happened."""

    def _tex(self, y):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml"); deckspec.spit(p, y)
            o = os.path.join(tmp, "t.tex"); build_deck.build(p, o)
            return deckspec.slurp(o)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_italic_renders(self):
        src = self._tex('slides:\n  - title: "T"\n    bullets: ["on *every* route"]\n')
        self.assertIn(r"\emph{every}", src)
        self.assertNotIn("*every*", src)

    def test_bold_wins_over_italic(self):
        """`**x**` must not split into two italics -- regex ordering is everything here."""
        src = self._tex('slides:\n  - title: "T"\n    bullets: ["a **b** c *d* e"]\n')
        self.assertIn(r"\textbf{b}", src)
        self.assertIn(r"\emph{d}", src)
        self.assertNotIn(r"\emph{}", src)

    def test_no_stray_asterisks_anywhere(self):
        src = self._tex('slides:\n  - title: "*T*"\n'
                        '    bullets: ["**b** and *i*"]\n'
                        '    foot: ["see *this*"]\n')
        body = "\n".join(l for l in src.splitlines()
                         if not l.lstrip().startswith("%"))
        self.assertNotIn("*", body)


class NoGroundTruth(unittest.TestCase):
    """Someone the deck was shared with has no original deck. That is the normal case.

    If the tool required a reference deck, that person could not use it at all.
    The one thing that's always available is the manuscript.
    """

    def test_refcheck_runs_without_a_reference(self):
        import refcheck
        n, got, _ = refcheck.profile_spec(SPEC)
        self.assertGreater(n, 0)
        self.assertIn("bullets_only", got)

    def test_refcheck_only_fails_on_field_independent_items(self):
        """Few figures may just be a matter of the field -- without a reference, this must not be counted as a failure."""
        import refcheck
        self.assertEqual(set(refcheck.STRICT), {"bullets_only"})
        for k in ("figure", "table", "columns", "standout", "emphasis"):
            self.assertNotIn(k, refcheck.STRICT)

    def test_diffcheck_needs_source_or_ref_not_ref_only(self):
        import diffcheck
        # argparse dumps its rejection reason to stderr. This is swallowed so a
        # successful run doesn't look like a failure -- what the test checks is the exit status.
        with self.assertRaises(SystemExit), \
                redirect_stderr(io.StringIO()):
            diffcheck.main(["nope.pdf"])          # rejected when neither is given
        # must run with --source alone: the argument definition must not mark it required
        import inspect
        src = inspect.getsource(diffcheck.main)
        self.assertNotIn('"--ref", required=True', src)
        self.assertIn('"--source"', src)

    def test_diffcheck_finds_source_values_missing_from_the_deck(self):
        import diffcheck
        tmp = tempfile.mkdtemp()
        try:
            tex = os.path.join(tmp, "paper.tex")
            deckspec.spit(tex, "The anode loses 12.3 percent and the cathode 45.6.")
            buf = io.StringIO()
            with redirect_stdout(buf):
                n = diffcheck.against_source("only 12.3 here", tex, 5)
            self.assertEqual(n, 1)               # 45.6 was dropped
            self.assertIn("45.6", buf.getvalue())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class QuestionSlides(unittest.TestCase):
    """A paper never contains a sentence that raises the audience's objection first.

    So extracting straight from the paper alone yields exactly 0 question-mark titles -- that's
    what happened in the blind trial (one example deck had them on about one slide in seven). A deck with no
    questions is not a talk that gets heard, it's a report that gets read. Have the machine say so before a person has to.
    """

    def _run(self, yaml_text):
        import refcheck
        tmp = tempfile.mkdtemp(prefix="q-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, yaml_text)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = refcheck.main([p])
            return code, buf.getvalue()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _deck(self, titles):
        out = ['meta: {title: T, author: A, venue: V, date: D}', 'slides:']
        for t in titles:
            out += ['  - title: "%s"' % t,
                    '    table: {header: [a, b], rows: [["1", "2"]]}',
                    '    bullets: ["**one** claim carrying its own evidence '
                    'right here in the line"]']
        return "\n".join(out) + "\n"

    def test_no_question_titles_is_a_failure(self):
        code, out = self._run(self._deck(["Result %d" % i for i in range(10)]))
        self.assertEqual(code, 1, out)
        self.assertIn("Not one slide's title is a question.", out)

    def test_one_question_title_clears_it(self):
        t = ["Result %d" % i for i in range(9)] + ["What happens below freezing?"]
        code, out = self._run(self._deck(t))
        self.assertNotIn("Not one slide's title is a question", out)

    def test_short_decks_are_not_nagged(self):
        """Demanding a question mark even for a five-slide lightning talk would be nagging."""
        code, out = self._run(self._deck(["Result %d" % i for i in range(5)]))
        self.assertNotIn("Not one slide's title is a question", out)

    def test_baseline_bullets_match_the_measured_example(self):
        """Baseline figures must never be made up.

        Bullets-per-slide and bullet length were once typed in by hand, which drifted from the measured
        values (1.0 / 18.8), and that fabricated figure spread into SKILL.md's instructions, producing a deck
        that was the opposite of the reference.
        """
        import refcheck
        self.assertEqual(refcheck.BASELINE_BULLETS, (1.0, 18.8))
        self.assertIn("question", refcheck.BASELINE)


class ImageGrid(unittest.TestCase):
    """A figure grid -- rows and columns get names, and each column gets a bordered outcome.

    With only a single `path` in the spec, a slide like this could not be made, and the same claim
    would collapse into one line of big text. That is exactly what happened in the blind trial.
    """

    GRID = ('slides:\n  - title: "T"\n'
            '    figure:\n      grid:\n'
            '        cols: [North gate, South gate]\n'
            '        rows: [Front, Side]\n'
            '        images: [[a.png, b.png], [c.png, d.png]]\n'
            '        mark: [ok, fail]\n'
            '        caption: ["t=3", "t=9"]\n')

    def _build(self, text, images=()):
        tmp = tempfile.mkdtemp(prefix="grid-")
        try:
            if images:
                # when the file is missing, it is replaced with a placeholder -- that is expected behavior,
                #   and the height limit applies only to real figures. This test used to confuse the two.
                os.makedirs(os.path.join(tmp, "figs"))
                for f in images:
                    io.open(os.path.join(tmp, "figs", f), "w").close()
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, text)
            out = os.path.join(tmp, "talk.tex")
            build_deck.build(spec, out)
            return deckspec.slurp(out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_grid_renders_rows_columns_and_marks(self):
        src = self._build(self.GRID)
        for w in ("North gate", "South gate", "Front", "Side", "t=3", "t=9"):
            self.assertIn(w, src)
        self.assertIn("fcolorbox{mSafe}", src)     # ok
        self.assertIn("fcolorbox{mHit}", src)      # fail

    def test_grid_cells_are_height_bounded(self):
        """Given only a width, rows stack up and the last line overflows off the slide.

        pdflatex doesn't error, it just goes invisible -- `outcheck` is what caught it.
        """
        src = self._build(self.GRID, ["a.png", "b.png", "c.png", "d.png"])
        self.assertIn("max height=", src)
        self.assertIn("textheight", src)
        self.assertNotIn("missing", src)

    def test_a_missing_grid_image_warns_instead_of_killing_the_document(self):
        tmp = tempfile.mkdtemp(prefix="grid-")
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, self.GRID)
            _, _, warn = build_deck.build(spec, os.path.join(tmp, "talk.tex"))
            self.assertEqual(len(warn), 4, warn)
            self.assertIn("Grid figure not found", warn[0])
            self.assertNotIn("adjincludegraphics",
                             deckspec.slurp(os.path.join(tmp, "talk.tex")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ragged_grid_is_rejected(self):
        with self.assertRaises(ValueError) as e:
            self._build('slides:\n  - title: "T"\n'
                        '    figure:\n      grid:\n'
                        '        images: [[a.png, b.png], [c.png]]\n')
        self.assertIn("image(s)", str(e.exception))

    def test_label_count_must_match(self):
        with self.assertRaises(ValueError) as e:
            self._build('slides:\n  - title: "T"\n'
                        '    figure:\n      grid:\n'
                        '        cols: [only one]\n'
                        '        images: [[a.png, b.png]]\n')
        self.assertIn("cols", str(e.exception))

    def test_unknown_mark_is_rejected(self):
        with self.assertRaises(ValueError) as e:
            self._build('slides:\n  - title: "T"\n'
                        '    figure:\n      grid:\n'
                        '        images: [[a.png]]\n'
                        '        mark: [maybe]\n')
        self.assertIn("mark", str(e.exception))


class BackupAndQuestions(unittest.TestCase):
    """A talk ends on a question. Until now, the spec had no notion of "after the main body"."""

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n'
            '  - title: "Main one"\n    bullets: ["x"]\n'
            '    say: ["A sentence that takes some seconds to read aloud here."]\n'
            '    ask: ["Would a colder room change this?"]\n'
            '  - backup: true\n    title: "Control"\n    bullets: ["y"]\n'
            '    say: ["Another sentence of roughly the same length as above."]\n'
            '  - title: "Main two"\n    bullets: ["z"]\n'
            '    say: ["A third sentence, also several seconds long when read."]\n')

    def _load(self):
        tmp = tempfile.mkdtemp(prefix="backup-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, self.SPEC)
        return tmp, p

    def test_backup_slides_move_to_the_end_and_lose_page_numbers(self):
        tmp, p = self._load()
        try:
            _, slides, npage = deckspec.load(p)
            self.assertEqual([s.get("title") for s in slides],
                             ["Main one", "Main two", "Control"])
            self.assertIsNone(slides[-1]["page"])
            self.assertEqual(npage, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_backup_slides_are_not_counted_in_the_talk_time(self):
        """Including a slide that only unfolds if a question comes up would throw off the total time entirely."""
        tmp, p = self._load()
        try:
            out = os.path.join(tmp, "script.md")
            total, n, _ = build_script.build(p, out)
            _, slides, _ = deckspec.load(p)
            import timing
            # rounds to whole seconds per slide and sums (trial 46 -- so the per-slide seconds and running total agree)
            main_only = sum(int(round(timing.seconds(s["say"], s["pause"], 135)))
                            for s in slides if not s["backup"])
            self.assertAlmostEqual(total, main_only, places=6)
            md = deckspec.slurp(out)
            self.assertIn(build_script.LABELS["en"]["spare_head"], md)   # English deck
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_questions_are_collected_in_one_place(self):
        tmp, p = self._load()
        try:
            out = os.path.join(tmp, "script.md")
            build_script.build(p, out)
            md = deckspec.slurp(out)
            self.assertIn(build_script.LABELS["en"]["asks"], md)
            self.assertIn("Would a colder room change this?", md)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ask_never_reaches_the_screen(self):
        """`ask` is script-only. If it reached the screen, the audience would see the anticipated question."""
        tmp, p = self._load()
        try:
            tex = os.path.join(tmp, "talk.tex")
            build_deck.build(p, tex)
            src = deckspec.slurp(tex)
            self.assertNotIn("colder room", src)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ColourIsNotTheOnlyChannel(unittest.TestCase):
    """`<hit>`/`<safe>` are this deck's reading aid, and it was only red versus green.

    To red-green colorblind eyes, both become the same mustard color (distance 181 -> 41.5, 23%).
    A caption that says "red = bad" would be pointing at a color that isn't on the screen.
    """

    def test_deck_underlines_the_loss_as_a_second_channel(self):
        tmp = tempfile.mkdtemp(prefix="cvd-")
        try:
            spec = os.path.join(tmp, "s.yaml")
            # The second channel is a colorblind option -- by default, no underline is drawn.
            deckspec.spit(spec, 'meta: {colorblind: true}\nslides:\n  - title: "T"\n'
                                '    bullets: ["<hit>-12.3</hit> vs <safe>+0.2</safe>"]\n')
            out = os.path.join(tmp, "talk.tex")
            build_deck.build(spec, out)
            src = deckspec.slurp(out)
            self.assertIn(r"\textcolor{mHit}{\textbf{\underline{", src)
            # `safe` does not get underlined -- that's what distinguishes the two
            self.assertIn(r"\textcolor{mSafe}{\textbf{", src)
            self.assertNotIn(r"\textcolor{mSafe}{\textbf{\underline{", src)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pptx_uses_the_same_second_channel(self):
        """If the two outputs don't use the same rule, that's another place they can diverge."""
        try:
            from pptx import Presentation
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx
        tmp = tempfile.mkdtemp(prefix="cvd-")
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, 'meta: {title: T, author: A, venue: V, date: D, colorblind: true}\n'
                                'slides:\n  - title: "T"\n'
                                '    bullets: ["<hit>-12.3</hit> vs <safe>+0.2</safe>"]\n')
            out = os.path.join(tmp, "t.pptx")
            build_pptx.build(spec, out)
            runs = [r for sl in Presentation(out).slides for sh in sl.shapes
                    if sh.has_text_frame for p in sh.text_frame.paragraphs
                    for r in p.runs]
            hit = [r for r in runs if "12.3" in r.text]
            safe = [r for r in runs if "0.2" in r.text]
            self.assertTrue(hit and safe)
            self.assertTrue(all(r.font.underline for r in hit))
            self.assertFalse(any(r.font.underline for r in safe))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DeckShape(unittest.TestCase):
    """Two cases where every ratio checks out but they look different. A test added after actually looking."""

    def _spec(self, tmp, text):
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, "meta: {title: T, author: A, venue: V, date: D}\n" + text)
        return p

    def test_table_and_chart_of_the_same_data_is_flagged(self):
        """With `chart: {from: left}`, showing that same table on screen too means the same values appear twice.

        It gets counted as two columns and prints as praise -- "two-column layout, 65%" -- but a two-column layout
        that's actually useful is one where the left and right sides differ.
        """
        import refcheck
        tmp = tempfile.mkdtemp(prefix="shape-")
        try:
            p = self._spec(tmp,
                           'slides:\n  - kind: columns\n    title: "T"\n'
                           '    left:  {table: {header: [a, b], '
                           'rows: [["x", "1"], ["y", "2"]]}}\n'
                           '    right: {chart: {from: left, kind: heat}}\n')
            dup, merged = refcheck.shape_notes(p)
            self.assertEqual(dup, [1])
            self.assertEqual(merged, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_chart_beside_a_different_table_is_not_flagged(self):
        import refcheck
        tmp = tempfile.mkdtemp(prefix="shape-")
        try:
            p = self._spec(tmp,
                           'slides:\n  - kind: columns\n    title: "T"\n'
                           '    left:  {table: {header: [a, b], '
                           'rows: [["x", "1"], ["y", "2"]]}}\n'
                           '    right: {figure: {path: f.png}}\n')
            dup, merged = refcheck.shape_notes(p)
            self.assertEqual(dup, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_two_attributes_crammed_into_one_cell_is_flagged(self):
        """A rule the user gave -- attributes crammed into one cell must be split into columns to be distinguishable.

        Written as `Cathode, CC-CV`, six rows become a flat list, and which side determines
        what has to be read and reconstructed by hand.
        """
        import refcheck
        tmp = tempfile.mkdtemp(prefix="shape-")
        try:
            p = self._spec(tmp,
                           'slides:\n  - title: "T"\n'
                           '    table:\n      header: [Cell, A, B]\n'
                           '      rows:\n'
                           '        - ["Cathode, CC-CV", "1", "2"]\n'
                           '        - ["Cathode, Pulse", "3", "4"]\n'
                           '        - ["Anode, CC-CV", "5", "6"]\n'
                           '        - ["Anode, Pulse", "7", "8"]\n')
            dup, merged = refcheck.shape_notes(p)
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0][0], 1)
            self.assertEqual(merged[0][2], ["Anode", "Cathode"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_plain_first_column_is_not_flagged(self):
        import refcheck
        tmp = tempfile.mkdtemp(prefix="shape-")
        try:
            p = self._spec(tmp,
                           'slides:\n  - title: "T"\n'
                           '    table:\n      header: [Cell, A, B]\n'
                           '      rows:\n'
                           '        - ["Cathode", "1", "2"]\n'
                           '        - ["Anode", "3", "4"]\n'
                           '        - ["Separator", "5", "6"]\n'
                           '        - ["Electrolyte", "7", "8"]\n')
            dup, merged = refcheck.shape_notes(p)
            self.assertEqual(merged, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PageNumbers(unittest.TestCase):
    """The page number is read from a named box. Finding it by shape catches body text instead.

    This actually happened: a footnote reading `ratio 27/14` was read as "page 27 of a 14-page deck,"
    and section G spat out 17 failures. The deck was fine; the checker was wrong.
    If the producing side leaves a marker, the reading side never has to guess.
    """

    def test_footer_text_is_not_mistaken_for_a_page_number(self):
        try:
            from pptx import Presentation
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx
        tmp = tempfile.mkdtemp(prefix="pagenum-")
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, (
                'meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n'
                '  - kind: title\n    title: "T"\n'
                '  - title: "One"\n    bullets: ["x"]\n'
                '    foot: ["ratio 19/13, and 27/14 for the second"]\n'
                '  - title: "Two"\n    bullets: ["y"]\n'))
            out = os.path.join(tmp, "t.pptx")
            build_pptx.build(spec, out)
            prs = Presentation(out)
            tagged = [sh.text_frame.text for sl in prs.slides for sh in sl.shapes
                      if sh.has_text_frame and sh.name == build_pptx.PAGENUM_TAG]
            self.assertEqual(tagged, ["1/2", "2/2"])
            # did the footnote make it through -- text must not be dropped just to eliminate a false positive
            allt = " ".join(sh.text_frame.text for sl in prs.slides
                            for sh in sl.shapes if sh.has_text_frame)
            self.assertIn("27/14", allt)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class OutCheck(unittest.TestCase):
    """The only check that looks at text after it has been rendered.

    Every other check reads the source. So a fragment the renderer swallows is invisible to
    all of them -- three of eleven defects in the blind trial were exactly that, every one of them
    zero LaTeX errors and a passing checker.
    """

    def _lost(self, spec_text, deck_text, sidecar=None):
        import outcheck
        tmp = tempfile.mkdtemp(prefix="outcheck-")
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec, spec_text)
            md = os.path.join(tmp, "out.md")
            deckspec.spit(md, deck_text)
            argv = [spec, "--script", md]
            if sidecar:
                sp = os.path.join(tmp, "values.txt")
                deckspec.spit(sp, sidecar)
                argv += ["--sidecar", sp]
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = outcheck.main(argv)
            return code, buf.getvalue()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - title: "T"\n    bullets: ["x"]\n'
            '    note: ["the anode loses twelve percent"]\n')

    def test_a_fragment_that_never_arrived_is_reported(self):
        code, out = self._lost(self.SPEC, "nothing useful here\n")
        self.assertEqual(code, 1, out)
        self.assertIn("missing", out)
        self.assertIn("anode", out)

    def test_a_fragment_that_arrived_is_not_reported(self):
        code, out = self._lost(self.SPEC, "the anode loses twelve percent\n")
        self.assertEqual(code, 0, out)
        self.assertIn("everything written in the spec arrived", out)

    def test_superscripts_are_normalised_before_comparing(self):
        """`p<10⁻⁴` normalized differently on each side and got flagged as "a perfectly fine fragment went missing."

        A false positive from the checker hides the real omissions -- once the list gets long, nobody reads it.
        """
        import outcheck
        self.assertEqual(outcheck.norm("$p<10^{-4}$"), outcheck.norm("p<10⁻⁴"))


class KeysThatWouldVanish(unittest.TestCase):
    """There were thirteen combinations that the schema accepted but the builder silently dropped.

    `table` attached to `kind: content`, `foot` attached to `kind: standout`,
    `figure` attached to `kind: table` ... all of them pass validation, build with zero warnings, and
    vanish from the screen. Rejecting typos while accepting "a spot that can't be drawn" doesn't add up.
    """

    HEAD = "meta: {title: T, author: A, venue: V, date: D}\nslides:\n"

    def _load(self, body):
        tmp = tempfile.mkdtemp(prefix="keys-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + body)
            return deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_key_the_kind_cannot_draw_is_rejected(self):
        for kind, skel, key, frag in (
                ("content", '    title: "T"\n    bullets: ["b"]\n', "table",
                 '    table: {header: [A, B], rows: [["1", "2"]]}\n'),
                ("standout", '    big: "42"\n', "foot", '    foot: ["f"]\n'),
                ("table", '    title: "T"\n'
                          '    table: {header: [A], rows: [["1"]]}\n',
                 "figure", '    figure: {path: x.png}\n'),
                ("columns", '    title: "T"\n    left: {bullets: ["L"]}\n'
                            '    right: {bullets: ["R"]}\n',
                 "big", '    big: "42"\n')):
            with self.assertRaises(ValueError) as e:
                self._load("  - kind: %s\n%s%s" % (kind, skel, frag))
            msg = str(e.exception)
            self.assertIn(key, msg)
            self.assertIn("disappears silently", msg)

    def test_the_message_says_where_to_put_it_instead(self):
        """Rejecting without offering an alternative just gets the key deleted by whoever's using it -- the same loss either way."""
        with self.assertRaises(ValueError) as e:
            self._load('  - kind: content\n    title: "T"\n    bullets: ["b"]\n'
                       '    table: {header: [A], rows: [["1"]]}\n')
        self.assertIn("kind: table", str(e.exception))

    def test_legitimate_combinations_still_load(self):
        """Rejecting too broadly must not block a perfectly valid spec."""
        for body in (
                '  - kind: standout\n    big: "42"\n    bullets: ["b"]\n'
                '    table: {header: [A], rows: [["1"]]}\n',
                '  - kind: figure\n    title: "T"\n    figure: {path: x.png}\n'
                '    bullets: ["b"]\n    foot: ["f"]\n',
                '  - kind: table\n    title: "T"\n'
                '    table: {header: [A], rows: [["1"]]}\n    block: {title: B, text: t}\n',
                '  - kind: title\n    title: "T"\n'):
            self._load(body)          # failure means an exception was raised

    def test_every_kind_has_a_declared_key_set(self):
        """Adding a new kind without updating the table crashes with a KeyError -- this catches it in advance."""
        for k in deckspec.KINDS:
            self.assertIn(k, deckspec.RENDERS)


class BackupNumbering(unittest.TestCase):
    """Three different places disagreed about the page number of a backup slide.

    The spec said "no number," the PPTX followed that, and beamer counted its own way, numbering the backup
    slide too and including it in the denominator. Deck `1/4`, PPTX `1/2`.
    `deckcheck` §G looks only at the PPTX, so it printed `OK`.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n'
            '  - title: "One"\n    bullets: ["a"]\n'
            '  - title: "Two"\n    bullets: ["b"]\n'
            '  - backup: true\n    title: "Spare"\n    bullets: ["c"]\n')

    def test_appendix_is_emitted_before_the_first_backup(self):
        tmp = tempfile.mkdtemp(prefix="bk-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.SPEC)
            tex = os.path.join(tmp, "talk.tex")
            build_deck.build(p, tex)
            src = tex_body(deckspec.slurp(tex))
            self.assertEqual(src.count("\\appendix"), 1)
            self.assertLess(src.index("\\appendix"), src.index("Spare"))
            self.assertGreater(src.index("\\appendix"), src.index("Two"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_denominator_counts_only_the_main_deck(self):
        """`\\inserttotalframenumber` counts backup slides too. The one that counts only the main body must be used instead."""
        tmp = tempfile.mkdtemp(prefix="bk-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.SPEC)
            tex = os.path.join(tmp, "talk.tex")
            build_deck.build(p, tex)
            src = tex_body(deckspec.slurp(tex))
            self.assertIn("insertmainframenumber", src)
            self.assertNotIn("inserttotalframenumber", src)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ProseAuditFlags(unittest.TestCase):
    """Both defects passed by printing 0. Zero didn't mean clean."""

    def test_discourse_markers_are_matched_case_insensitively(self):
        """The pattern is lowercase, but sentences start capitalized -- it always came out 0."""
        import prose_audit as pa
        body = "The gap is real.\nSo we split the axis.\nAnd the ordering held."
        pat = pa.REGISTER[0][1]
        self.assertEqual(len(re.findall(pat, body)), 0)          # the old behavior
        self.assertEqual(len(re.findall(pat, body, re.I | re.M)), 2)

    def test_a_question_title_is_not_counted_as_a_conjunction(self):
        """This skill recommends question titles. Counting one as a penalty would be a contradiction."""
        import prose_audit as pa
        tmp = tempfile.mkdtemp(prefix="pa-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, 'meta: {title: T, author: A, venue: V, date: D}\n'
                             'slides:\n'
                             '  - title: "Which route should you take?"\n'
                             '    bullets: ["x"]\n    say: ["A line."]\n'
                             '  - title: "Which we could not test"\n'
                             '    bullets: ["y"]\n    say: ["Another."]\n')
            buf = io.StringIO()
            with redirect_stdout(buf):
                pa.main(p)
            out = buf.getvalue()
            m = re.search(r"Titles that open with a conjunction\s+(\d+)", out)
            self.assertTrue(m, out)
            self.assertEqual(int(m.group(1)), 1, out)   # excluding the question title, only one
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ShownButNeverSaid(unittest.TestCase):
    """In a deck where all six checkers came back green, all five audience members got stuck at the same spot.

    Every sticking point was the same kind -- an abbreviation or column name that was on screen but never
    spoken in the script. All the numbers were correct. `deckcheck` checks "does the number on screen
    match the source," but something shown yet never said was something no check looked at.
    """

    def _terms(self, body):
        import prose_audit as pa
        tmp = tempfile.mkdtemp(prefix="say-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, "meta: {title: T, author: A, venue: V, date: D}\n"
                             "slides:\n" + body)
            return pa.unspoken_terms(pa.from_spec(p))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_table_header_never_spoken_is_flagged(self):
        got = self._terms(
            '  - kind: table\n    title: "Results"\n'
            '    table: {header: [Cell, P4V2, "w/l"],\n'
            '            rows: [["NMC", "1.0", "2"]]}\n'
            '    say: ["The first column is the chemistry."]\n')
        words = [w for _, w in got]
        self.assertIn("P4V2", words)
        self.assertIn("w/l", words)

    def test_a_term_that_is_spoken_is_not_flagged(self):
        got = self._terms(
            '  - kind: table\n    title: "Results"\n'
            '    table: {header: [Cell, P4V2], rows: [["NMC", "1.0"]]}\n'
            '    say: ["P4V2 means four pumps and two valves."]\n')
        words = [w for _, w in got]
        self.assertNotIn("P4V2", words)
        # `NMC` is on screen only, not in the script -- it is correct for this to be flagged. When this test was
        # first written it said "nothing should be flagged here," and the tool was right and the test was wrong.
        self.assertIn("NMC", words)

    def test_ordinary_words_are_not_flagged(self):
        """Flagging even ordinary English words would make the list long enough that nobody reads it."""
        got = self._terms(
            '  - title: "The cathode degrades"\n'
            '    bullets: ["Charging protocol matters here"]\n'
            '    say: ["A sentence."]\n')
        self.assertEqual([w for _, w in got], [])

    def test_it_reports_the_slide_where_the_term_first_appears(self):
        got = self._terms(
            '  - title: "Setup"\n    bullets: ["nothing special"]\n'
            '    say: ["A plain sentence."]\n'
            '  - title: "Now ZX40B"\n    bullets: ["x"]\n'
            '    say: ["Another plain sentence."]\n')
        self.assertEqual(got, [(2, "ZX40B")])


class Diagrams(unittest.TestCase):
    """The only way to give a slide something to look at when it has no table.

    `chart` draws from a table in the spec, so it only helps slides that already have one. But the
    slides left with nothing but bullets are exactly the ones with no table -- introduction,
    related work, interpretation, limitations, conclusion -- and measured, that came to 36% (10% in one
    example deck). §③ of the docs says "a diagram is drawn as a fixed asset" but **never provided the
    tool for it.** Pointing this out without providing a way to do it is just nagging.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n'
            '  - kind: figure\n    title: "The parts"\n'
            '    diagram:\n      kind: flow\n'
            '      boxes:\n'
            '        - {label: "Intake"}\n'
            '        - {label: "Pump", mark: hit}\n'
            '      note: "Red is where the loss lands."\n'
            '    say: ["Two parts."]\n')

    def _figs(self, spec_text=None):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="dg-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text or self.SPEC)
        made, lines, warn = build_figs.build(p, os.path.join(tmp, "figs"))
        return tmp, p, made, lines, warn

    def test_a_diagram_is_drawn_and_named_like_a_chart(self):
        tmp, p, made, lines, warn = self._figs()
        try:
            self.assertEqual(_but_thin(warn), [])
            self.assertEqual(len(made), 1)
            self.assertTrue(os.path.basename(made[0])
                            .startswith("diagram_01_self"))
            self.assertTrue(os.path.getsize(made[0]) > 3000)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_its_labels_reach_the_sidecar(self):
        """Text inside a figure is pixels. Without recording it in the sidecar, `outcheck`
        marks all of it as "did not arrive" -- a false positive hides the real omissions."""
        tmp, p, made, lines, warn = self._figs()
        try:
            flat = " ".join(lines)
            for w in ("Intake", "Pump",
                      "Red is where the loss lands."):
                self.assertIn(w, flat)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_all_three_kinds_draw(self):
        for kind, extra in (("flow", ""), ("stack", ""),
                            ("grid", "      cols: [A, B]\n")):
            spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                    'slides:\n  - kind: figure\n    title: "T"\n'
                    '    diagram:\n      kind: %s\n%s'
                    '      boxes: [{label: "one"}, {label: "two"}]\n' % (kind, extra))
            tmp, p, made, lines, warn = self._figs(spec)
            try:
                self.assertEqual(_but_thin(warn), [], kind)
                self.assertEqual(len(made), 1, kind)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def _spec_file(self, text):
        tmp = tempfile.mkdtemp(prefix="dsp-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, text)
        return p

    def test_an_unknown_diagram_kind_is_refused_by_name(self):
        """A typo'd diagram kind is rejected the moment the spec is read.

        It used to be that the figure generator would warn and skip, and the deck would build with that spot
        left blank. Rejecting is stronger than warning, and matches this skill's own principle that
        "an unknown key is rejected the moment it is received."
        """
        with self.assertRaises(ValueError) as e:
            deckspec.load(self._spec_file(
                'meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: figure\n    title: "T"\n'
                '    diagram:\n      kind: spiral\n'
                '      boxes: [{label: "one"}]\n'))
        self.assertIn("spiral", str(e.exception))

    def test_a_diagram_missing_its_required_key_says_which_and_why(self):
        """It used to die with a `KeyError: 'boxes'` traceback -- it never said which slide, which key
        was wrong, so whoever received it had to go hunting."""
        with self.assertRaises(ValueError) as e:
            deckspec.load(self._spec_file(
                'meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: figure\n    title: "T"\n'
                '    diagram:\n      kind: grid\n'
                '      cols: ["a", "b"]\n'))
        msg = str(e.exception)
        self.assertIn("boxes", msg)
        self.assertIn("grid", msg)
        self.assertIn("1", msg)          # which slide

    def test_a_diagram_slide_counts_as_a_figure_not_as_bullets_only(self):
        """If `refcheck` doesn't count a diagram as a figure, it gets flagged as "there is no figure,"
        and trusting that message leads to drawing another one that wasn't needed."""
        import refcheck
        tmp = tempfile.mkdtemp(prefix="dg-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.SPEC)
            n, got, _ = refcheck.profile_spec(p)
            self.assertEqual(got["figure"], 1.0)
            self.assertEqual(got["bullets_only"], 0.0)
            self.assertEqual(refcheck.bullets_only_slides(p), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_it_satisfies_never_drawn(self):
        """This is exactly the answer to "a comparison was never once drawn"."""
        import prose_audit as pa
        rows = ('            rows: [["Intake", "1"], ["Pump", "2"],\n'
                '                   ["Outlet", "3"], ["Filter", "4"]]}\n')
        tmp = tempfile.mkdtemp(prefix="dg-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p,
                          'meta: {title: T, author: A, venue: V, date: D}\n'
                          'slides:\n'
                          '  - kind: figure\n    title: "What it is made of"\n'
                          '    diagram:\n      kind: flow\n'
                          '      boxes: [{label: "Intake"}, {label: "Outlet"}]\n'
                          '    say: ["Parts."]\n'
                          '  - kind: table\n    title: "Loss"\n'
                          '    table: {header: [Stage, A],\n' + rows +
                          '    say: ["One."]\n'
                          '  - kind: table\n    title: "Loss again"\n'
                          '    table: {header: [Stage, B],\n' + rows +
                          '    say: ["Two."]\n')
            self.assertIsNone(pa.never_drawn(pa.from_spec(p)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FiguresThatCarryTheirOwnPoint(unittest.TestCase):
    """A figure can carry its own conclusion inside it.

    Measuring the PNG of one example deck, the stroke height of the tile numbers came out to 25pt on
    screen (about 36pt font size) -- three times the same slide's 12pt body text. Yet this skill's own
    comments claimed it "matched the body text," and drawing from that wrong record made the generated
    tiles look like a colored-in table. Only a side-by-side look revealed it.
    """

    T = {"header": ["delay", "north", "south"],
         "rows": [["Monday", "<hit>27.1</hit>", "<hit>24.1</hit>"],
                  ["Friday", "3.3", "3.1"]]}

    def _tiles(self, **kw):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="tl-")
        try:
            p = os.path.join(tmp, "t.png")
            warn = []
            seen = build_figs.draw_tiles(
                [(None, self.T)], p, kw.get("title"), kw.get("note"),
                (3.05, 2.44), warn, None, None, None,
                kw.get("verdict"), kw.get("takeaway"))
            return seen, warn
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_tile_value_grows_to_fill_its_tile(self):
        """Until now, `fit_text` could only shrink text. So no matter what was drawn, every
        character stayed at or below body size, and emphasis had to rely on color and fill alone."""
        seen, warn = self._tiles()
        import deckspec
        vals = [pt for pt, txt in seen if txt in ("27.1", "24.1",
                                                  "3.3", "3.1")]
        self.assertTrue(vals, "tile values are not in the sidecar")
        self.assertGreater(min(vals), deckspec.BODY_PT * 1.4,
                           "tile values did not exceed body size: %r" % vals)
        # Within a grid, sizes must match. Fitting each cell individually makes it ragged.
        self.assertEqual(len(set(vals)), 1, "value size differs cell to cell: %r" % vals)

    def test_a_tile_says_what_the_colour_means(self):
        """Hatching and color are a channel for colorblindness but do not say what they mean.
        Without that stated on screen, the audience can only guess that red is bad."""
        seen, warn = self._tiles(verdict={"hit": "missed the target",
                                          "plain": "on target"})
        said = [txt for _pt, txt in seen]
        self.assertIn("missed the target", said)
        self.assertIn("on target", said)

    def test_a_figure_can_carry_its_conclusion_inside(self):
        """A caption sits outside the figure, so it is read only after the eye has left the figure."""
        seen, warn = self._tiles(note="Invented values.",
                                 takeaway="THE DRY BED LEADS.")
        said = [txt for _pt, txt in seen]
        self.assertIn("THE DRY BED LEADS.", said)
        self.assertIn("Invented values.", said)
        # the conclusion is bolder and bigger than the note -- at the same weight, neither gets read
        take = [pt for pt, txt in seen if txt == "THE DRY BED LEADS."][0]
        note = [pt for pt, txt in seen if txt == "Invented values."][0]
        self.assertGreaterEqual(take, note)

    def test_a_short_grid_does_not_claim_it_cannot_fit(self):
        """A false positive erases a feature -- blind trial 6 saw a wrong warning and abandoned the
        diagram entirely. A 2-row, 2-column grid could not possibly fail to fit in 3 inches."""
        seen, warn = self._tiles()
        self.assertEqual([w for w in warn if "doesn't fit" in w], [])

    def test_a_strip_can_show_where_values_land(self):
        """A cell only says "how many cells." "So where does the value actually fall" is said by
        the axis line beside the cell.

        Without being able to draw this, a concept slide ended up as nothing but "colored-in cells."
        """
        import build_figs
        tmp = tempfile.mkdtemp(prefix="ax-")
        try:
            warn = []
            words, seen = build_figs.draw_strip(
                {"kind": "strip",
                 "rows": [{"label": "tape A",
                           "cells": [{"label": "whole"}, {"label": "tenths", "span": 3}],
                           "axis": {"ticks": 11, "left": "0", "right": "max"},
                           "note": "A MARK EVERY METRE"}],
                 "takeaway": "FEWER MARKS, LONGER GUESSES."},
                os.path.join(tmp, "s.png"), (5.51, 2.55), warn)
            said = [txt for _pt, txt in seen]
            self.assertIn("0", said)
            self.assertIn("max", said)
            self.assertIn("A MARK EVERY METRE", said)
            self.assertIn("FEWER MARKS, LONGER GUESSES.", said)
            # the endpoint labels and the conclusion must also go out through the sidecar -- text inside a PNG
            # has no PDF text layer, so `outcheck` cannot see it
            self.assertIn("max", words)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_float_axis_is_dense_near_zero(self):
        """A log axis is dense near zero and sparse further out. Drawn evenly, it would be
        indistinguishable from an even axis, and whatever this figure was meant to say would
        disappear entirely."""
        import build_figs
        even = build_figs.axis_ticks({"ticks": 9})
        logg = build_figs.axis_ticks({"ticks": "log", "n": 9})
        self.assertAlmostEqual(even[0], 0.0)
        self.assertAlmostEqual(even[-1], 1.0)
        self.assertAlmostEqual(logg[0], 0.0)
        self.assertAlmostEqual(logg[-1], 1.0)
        # the first half is packed into a much narrower span
        self.assertLess(logg[len(logg) // 2], even[len(even) // 2] * 0.55)

    def test_nothing_falls_off_the_bottom_when_the_slot_is_short(self):
        """Even after the font size hit its floor, if there still wasn't enough room, the strip
        overflowed off screen -- the legend and conclusion actually vanished this way, with no warning.
        Disappearing silently is the worst outcome."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="ax2-")
        try:
            warn = []
            words, seen = build_figs.draw_strip(
                {"kind": "strip",
                 "legend": {"a": "ALPHA", "b": "BETA"},
                 "rows": [{"label": "row %d" % i, "sub": "sub %d" % i,
                           "cells": [{"label": "A", "mark": "a"},
                                     {"label": "B", "span": 4, "mark": "b"}],
                           "axis": {"ticks": 12, "left": "0", "right": "max"},
                           "note": "A NOTE LONG ENOUGH TO NEED TWO LINES "
                                   "WHEN IT IS FOLDED %d" % i}
                          for i in range(3)],
                 "takeaway": "THE LAST LINE MUST SURVIVE."},
                os.path.join(tmp, "s.png"), (5.51, 1.9), warn)
            said = [txt for _pt, txt in seen]
            self.assertIn("THE LAST LINE MUST SURVIVE.", said)
            self.assertIn("ALPHA", said)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_stage_box_can_show_what_is_inside_it(self):
        """A structure diagram must be able to draw what is inside a stage box.
        Four empty gray boxes differing only in name look identical inside, so they cannot say
        "what differs and how" -- the speaker had to fill that gap by talking."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="pp-")
        try:
            warn = []
            words, seen = build_figs.draw_pipeline(
                {"kind": "pipeline", "rows": [{"label": "Depot", "stages": [{"label": "receive", "group": "dock", "count": "12", "inner": ["SCAN", "WEIGH"]},{"label": "sort", "group": "floor", "count": "25", "inner": ["AISLE A"]},{"label": "load", "group": "yard", "count": "7", "mark": "safe", "inner": ["VAN", "TRUCK"]}], "out": "trucks"}]},
                os.path.join(tmp, "p.png"), (5.51, 2.55), warn)
            said = [txt for _pt, txt in seen]
            for v in ("SCAN", "WEIGH", "AISLE A", "VAN", "TRUCK"):
                self.assertIn(v, said)
            # this must also go out through the sidecar for `outcheck` to see it
            self.assertIn("TRUCK", words)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_stage_names_are_all_the_same_size(self):
        """Fitting each box individually only makes the short names bigger, and then **font size
        starts to carry meaning** -- it reads as "sort matters more," even though nobody ever
        said that."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="pp2-")
        try:
            warn = []
            words, seen = build_figs.draw_pipeline(
                {"kind": "pipeline", "rows": [{"label": "Depot", "stages": [{"label": "receive", "group": "dock", "count": "12", "inner": ["SCAN", "WEIGH"]},{"label": "sort", "group": "floor", "count": "25", "inner": ["AISLE A"]},{"label": "load", "group": "yard", "count": "7", "mark": "safe", "inner": ["VAN", "TRUCK"]}], "out": "trucks"}]},
                os.path.join(tmp, "p.png"), (5.51, 2.55), warn)
            pts = [pt for pt, txt in seen if txt in ("receive", "sort", "load")]
            self.assertEqual(len(pts), 3)
            self.assertEqual(len(set(pts)), 1,
                             "stage name sizes are all different: %r" % pts)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_same_complaint_is_not_repeated_for_every_box(self):
        """When the same name appears on four boxes, the same warning used to print four times.
        When six of ten lines say the same thing, the remaining four go unread."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="pp3-")
        try:
            warn = []
            build_figs.draw_pipeline(
                {"kind": "pipeline", "rows": [
                    {"label": "M%d" % i, "stages": [
                        {"label": "a considerably long stage name",
                         "count": "1"} for _ in range(4)]}
                    for i in range(2)]},
                os.path.join(tmp, "p.png"), (3.0, 1.6), warn)
            self.assertEqual(len(warn), len(set(warn)),
                             "the same warning repeats: %r" % warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    ARCH = {"kind": "pipeline", "rows": [
        {"label": "Depot", "stages": [
            {"label": "unload", "group": "dock", "count": "7",
             "inner": ["AISLE A", "...", "AISLE K"]},
            {"label": "check", "group": "floor", "count": "25",
             "sub": "MAIN HALL", "mark": "safe",
             "inner": [{"label": "WEIGH", "mark": "a"},
                       [{"label": "TAPE", "mark": "a"},
                        {"label": "LABEL", "mark": "b"}]]},
            {"label": "store", "group": "floor", "count": "3",
             "glyph": "funnel"},
            {"label": "dispatch", "group": "yard", "count": "9",
             "glyph": "grid"}],
         "out": "trucks"}]}

    def _arch(self, spec=None, slot=(5.51, 2.55)):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="ar-")
        try:
            warn = []
            words, seen = build_figs.draw_pipeline(
                spec or self.ARCH, os.path.join(tmp, "a.png"), slot, warn)
            return words, seen, warn
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_stage_can_look_like_what_it_does(self):
        """Four identical gray boxes differing only in name look the same inside. Then the figure
        cannot say where and how the two structures differ, and the speaker has to fill the gap
        by talking. Shapes like a grid (read in pieces) or a funnel (many becoming one) say
        what that stage actually does."""
        import build_figs
        self.assertIn("grid", build_figs.GLYPHS)
        self.assertIn("funnel", build_figs.GLYPHS)
        words, seen, warn = self._arch()
        self.assertEqual([w for w in warn if "glyph" in w and "can only be" in w], [])

    def test_an_unknown_glyph_says_which_ones_exist(self):
        spec = {"kind": "pipeline", "rows": [{"label": "M", "stages": [
            {"label": "a", "glyph": "sparkle"}]}]}
        words, seen, warn = self._arch(spec)
        self.assertTrue(any("sparkle" in w and "grid" in w for w in warn),
                        "does not say what can be used instead: %r" % warn)

    def test_the_watched_stage_is_outlined_not_filled(self):
        """Filling it solid green makes it read as one solid block on screen, and **what's inside
        becomes unreadable.** An outline says "this is what we're watching" while leaving the inside empty."""
        import build_figs
        import matplotlib
        matplotlib.use("Agg")
        calls = []
        real = build_figs._round

        def spy(ax, x, y, w, h, face, *a, **kw):
            calls.append((face, kw.get("edge"), kw.get("lw", 0.0)))
            return real(ax, x, y, w, h, face, *a, **kw)

        build_figs._round = spy
        try:
            self._arch()
        finally:
            build_figs._round = real
        ring = build_figs.ROLE_INK["safe"]
        outlined = [c for c in calls
                    if c[0] == "#FFFFFF" and c[1] == ring and c[2] > 0.0]
        self.assertTrue(outlined, "the marked stage was not drawn with an outline")
        self.assertEqual([c for c in calls if c[0] == ring], [],
                         "the marked stage was **filled** with color -- only an outline keeps the inside readable")

    def test_a_repeated_part_is_drawn_once_with_an_ellipsis(self):
        """The ellipsis in "Aisle A ... Aisle K" means don't count how many there are.
        Drawing every one of them would let that box take over the whole figure."""
        import build_figs
        self.assertTrue(build_figs.is_ditto({"label": "..."}))
        self.assertTrue(build_figs.is_ditto({"label": "\u22ee"}))
        self.assertFalse(build_figs.is_ditto({"label": "AISLE K"}))
        words, seen, warn = self._arch()
        said = [txt for _pt, txt in seen]
        self.assertIn("AISLE A", said)
        self.assertIn("AISLE K", said)
        self.assertNotIn("...", said)

    def test_two_parts_on_one_row_both_get_drawn(self):
        words, seen, warn = self._arch()
        said = [txt for _pt, txt in seen]
        for v in ("TAPE", "LABEL", "WEIGH", "MAIN HALL"):
            self.assertIn(v, said)
            self.assertIn(v, words)      # through the sidecar too

    def test_a_crowded_stage_gets_more_width_than_a_bare_one(self):
        """Splitting stages evenly isn't fair, it's ignoring the content.
        A stage crowded inside must be wider than an empty one."""
        import build_figs
        import matplotlib
        matplotlib.use("Agg")
        seen_boxes = []
        real = build_figs._round

        def spy(ax, x, y, w, h, face, *a, **kw):
            if face == build_figs.MODULE_BG and w > 4:
                seen_boxes.append(round(w, 2))
            return real(ax, x, y, w, h, face, *a, **kw)

        build_figs._round = spy
        try:
            self._arch()
        finally:
            build_figs._round = real
        self.assertGreaterEqual(len(seen_boxes), 3)
        self.assertGreater(max(seen_boxes), min(seen_boxes) * 1.15,
                           "stage widths are all the same: %r" % seen_boxes)

    def _bars(self, **kw):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="br-")
        try:
            p = os.path.join(tmp, "b.png")
            warn = []
            seen = build_figs.draw_bars(
                {"header": ["", "one", "two"],
                 "rows": [["North", "-2.85", "-12.4"],
                          ["East", "-8.7", "-6.35"],
                          ["South", "+0.0", "-15.9"],
                          ["West", "-11.05", "-7.45"]]},
                p, None, "dT", kw.get("note"), (5.51, 2.44), warn,
                kw.get("callout"), kw.get("takeaway"))
            return seen, warn
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bars_say_their_values(self):
        """With only axis ticks and no values, the audience has to trace the ticks by eye,
        and a talk gives them no time for that."""
        seen, warn = self._bars()
        said = [txt for _pt, txt in seen]
        for v in ("-2.85", "+0.0", "-15.9"):
            self.assertIn(v, said)

    def test_one_bar_can_be_pointed_at(self):
        seen, warn = self._bars(
            callout={"at": "South", "text": "THE GAP CLOSES RIGHT HERE"})
        self.assertEqual(warn, [])
        self.assertIn("THE GAP CLOSES RIGHT HERE", [txt for _pt, txt in seen])

    def test_pointing_at_a_bar_that_is_not_there_says_which_ones_are(self):
        """Saying only "not found" leaves whoever receives it not knowing what to fix."""
        seen, warn = self._bars(callout={"at": "Scene Z", "text": "x"})
        self.assertEqual(len(warn), 1)
        self.assertIn("North", warn[0])
        self.assertIn("South", warn[0])


class SeventhBlindTrial(unittest.TestCase):
    """What blind trial 7 found. Every one of them failed silently.

    Handing a fresh agent only the paper and the skill and letting it run the whole way through
    turned up eleven of them, and several were happening while the checkers were printing "all pass."
    """

    def test_a_percent_survives_a_symbol_in_the_same_string(self):
        """`esc()` saw the `$` it had just inserted itself and stopped escaping.

        After substituting `±` with `$\\pm$`, it judged "there's a `$`, so this must be author LaTeX,"
        let a `%` through raw, and turned everything after it into a comment, which
        crashed the build. Whenever a substituted symbol and a character needing escape landed in the
        same string, this broke every time.
        """
        import build_deck
        got = build_deck.esc("the gauge reads 95% full, give or take \u00b13 litres")
        self.assertIn(r"95\%", got)
        self.assertIn(r"$\pm$", got)

    def test_a_raw_percent_is_escaped_even_in_author_latex(self):
        """In LaTeX, `%` always turns the rest of that line into a comment.
        There is no such thing as "I wanted the percent sign on screen but meant for it to become a comment"."""
        import build_deck
        got = build_deck.esc("$p<10^{-4}$ and 5%")
        self.assertIn(r"5\%", got)
        self.assertIn("$p<10^{-4}$", got)
        # something already escaped is not escaped a second time
        self.assertEqual(build_deck.esc(r"already \% escaped"),
                         r"already \% escaped")

    def test_the_sidecar_never_claims_text_that_was_not_drawn(self):
        """The sidecar is testimony that "this text is inside the PNG." Recording text that was
        actually cropped off means the checker lies -- `outcheck` prints "0 missing," and a person
        believes it. That is worse than having no checker at all."""
        import build_figs
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(2.0, 1.0))
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.text(-3.0, 0.5, "OFF THE LEFT EDGE", fontsize=9)
        ax.text(0.5, 0.5, "INSIDE", fontsize=9, ha="center")
        seen = [(9.0, "OFF THE LEFT EDGE"), (9.0, "INSIDE")]
        warn = []
        tmp = tempfile.mkdtemp(prefix="sc-")
        try:
            build_figs.save_fig(fig, os.path.join(tmp, "x.png"), seen, warn, "x")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        said = [s for _pt, s in seen]
        self.assertIn("INSIDE", said)
        self.assertNotIn("OFF THE LEFT EDGE", said, "text that was never drawn remained")
        self.assertTrue(any("clipped outside the figure" in w for w in warn), warn)

    def test_a_diagram_with_its_axis_off_is_not_reported_as_clipped(self):
        """A false positive erases a feature. A diagram is drawn with its axis turned off, so even if
        tick labels remain, they are not on screen -- counting that as "clipped" would drag six lines
        along with it every time, burying the real warnings."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="ax-")
        try:
            warn = []
            build_figs.draw_diagram(
                {"kind": "flow", "boxes": [{"label": "one"}, {"label": "two"}]},
                os.path.join(tmp, "d.png"), (5.51, 2.44), warn)
            self.assertEqual([w for w in warn if "clipped outside the figure" in w], [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_other_emphasis_is_drawn_without_claiming_significance(self):
        """`&lt;hi&gt;` was in the docs, was accepted, and did nothing at all.
        Red and green already carry the fixed meaning "bad/good," so `hi` marks with an outline instead
        of a color -- using color for it would render a verdict the source material never made."""
        import build_figs
        import matplotlib
        matplotlib.use("Agg")
        calls = []
        real = build_figs.plt.Rectangle

        def spy(xy, w, h, **kw):
            calls.append((kw.get("facecolor"), kw.get("edgecolor"),
                          kw.get("linewidth", 0.0)))
            return real(xy, w, h, **kw)

        build_figs.plt.Rectangle = spy
        tmp = tempfile.mkdtemp(prefix="hi-")
        try:
            build_figs.draw_heat(
                {"header": ["", "one", "two"],
                 "rows": [["row", "<hi>-71.9</hi>", "+0.1"]]},
                os.path.join(tmp, "h.png"), None, None, (5.51, 2.44), [])
        finally:
            build_figs.plt.Rectangle = real
            shutil.rmtree(tmp, ignore_errors=True)
        ringed = [c for c in calls
                  if c[0] == "none" and c[1] not in (None, "none")
                  and c[2] > 0.0]
        self.assertTrue(ringed, "the hi cell received no marking at all")

    def test_the_spec_can_supply_acronym_word_counts(self):
        """The docs said "measure the acronym yourself," yet the only place to put that was inside
        the script, and the same docs said "do not edit the script." The blind trial computed it by
        hand separately, and that deck alone was underestimated by 15 seconds."""
        import deckspec
        import timing
        table = deckspec.acronyms({"acronyms": {"ZZTOP": 5}})
        self.assertEqual(table["ZZTOP"], 5.0)
        plain = timing.words("ZZTOP runs")
        with_t = timing.words("ZZTOP runs", table)
        self.assertGreater(with_t, plain)
        # It does not overwrite the base table. Adding one entry must not lose the rest.
        self.assertEqual(timing.words("12.5", table), timing.words("12.5"))

    def test_a_bad_acronym_table_is_refused_with_a_reason(self):
        import deckspec
        for bad in ({"acronyms": ["ECU"]}, {"acronyms": {"ECU": "many"}},
                    {"acronyms": {"ECU": 0}}):
            with self.assertRaises(ValueError):
                deckspec.acronyms(bad)


class OneDesignAcrossAllThree(unittest.TestCase):
    """Design must be one consistent set across the whole deck, not decided slide by slide.

    This repository was failing at that -- `build_figs.py` alone had 39 different colors and 12
    different line widths, and the deck and the PPTX each kept their own set again. It passes as long
    as the values happen to match, but that is luck, not something being enforced.
    The moment only one side gets fixed, they diverge, and no checker sees it.
    """

    def test_all_three_builders_read_the_same_file(self):
        import build_deck, build_figs, build_pptx   # noqa: E401
        for mod in (build_deck, build_figs, build_pptx):
            self.assertTrue(hasattr(mod, "design"),
                            "%s does not read design.py" % mod.__name__)

    def test_the_semantic_colours_are_identical_everywhere(self):
        """Red must be one red -- in the figures, in the body, and in the PPTX."""
        import build_deck, build_pptx, design       # noqa: E401
        src = build_deck.PREAMBLE
        # The deck stamps these into the preamble. Any hardcoded leftover gets caught here.
        for token in ("%(c_hit)s", "%(c_safe)s", "%(c_hit_lt)s",
                      "%(c_safe_lt)s", "%(c_hi)s"):
            self.assertIn(token, src, "the deck is writing the color directly: %s" % token)

        def hexof(rgb):
            return "#%02X%02X%02X" % (rgb[0], rgb[1], rgb[2])

        self.assertEqual(hexof(build_pptx.HIT), design.text_of("hit"))
        self.assertEqual(hexof(build_pptx.SAFE), design.text_of("safe"))
        self.assertEqual(hexof(build_pptx.HIT_LT),
                         design.text_of("hit", dark_bg=True))
        self.assertEqual(hexof(build_pptx.INK), design.INK)

    def test_every_colour_meant_for_text_clears_the_contrast_bar(self):
        """WCAG 2.2 -- 4.5:1 for text, 3:1 for non-text (lines, markers).

        Since the standards differ, there are two color sets. Using a line-appropriate color for text
        falls short: yellow comes in at 4.21:1, teal at 4.01:1. The temptation to merge the two sets is
        always there, so this is where it gets blocked.
        """
        import design

        def lin(c):
            c = c / 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        def ratio(h):
            h = h.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
            return 1.05 / (L + 0.05)

        for name in design.ROLE_TEXT:
            self.assertGreaterEqual(
                ratio(design.text_of(name)), 4.5,
                "%s's text color falls short of 4.5:1 on a white background" % name)
        for tone in (design.INK, design.INK2, design.INK3, design.HI_TEXT):
            self.assertGreaterEqual(ratio(tone), 4.5,
                                    "%s is too light to use as text" % tone)
        # for lines/markers, only 3:1 is required -- the text standard is not applied
        for name in design.ROLES:
            self.assertGreaterEqual(ratio(design.line_of(name)), 3.0,
                                    "%s's line color falls short of 3:1" % name)


class ReproducingAnExampleDeck(unittest.TestCase):
    """Defects that turned up while rewriting one example deck's layout as a spec.

    A spot that has to be patched by hand is exactly the skill's own gap. Ten of them turned up, and
    every one of them was failing silently -- while the checkers were printing pass.
    """

    def _spec(self, text):
        tmp = tempfile.mkdtemp(prefix="rp-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, text)
        return p, tmp

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_a_figure_with_two_columns_is_a_two_column_slide(self):
        """A full-width figure with two panes of explanation underneath. `kind` inference saw `chart`
        and routed it to `figure`, so the next check rejected it with "figure doesn't draw
        left/right." Writing the layout the docs recommend exactly as the docs say, only to get
        rejected, means whoever hits this just gives up on that layout."""
        p, _ = self._spec(self.HEAD +
                          '  - title: "T"\n'
                          '    chart: {kind: heat, from: self}\n'
                          '    table:\n      header: ["", "a"]\n'
                          '      rows: [["r", "+0.1"]]\n'
                          '    left: {text: "what it shows"}\n'
                          '    right: {text: "what follows"}\n')
        meta, slides, _n = deckspec.load(p)
        self.assertEqual(slides[0]["kind"], "columns")

    def test_a_chart_may_read_a_table_on_any_kind_of_slide(self):
        """The table `chart` reads from is data, not something shown on screen. This exception was
        wired to `kind == figure` only, so the same table got rejected on a full-width chart sitting
        above a two-column slide. The exception was pinned to one spot instead of being a rule."""
        p, _ = self._spec(self.HEAD +
                          '  - kind: columns\n    title: "T"\n'
                          '    chart: {kind: heat, from: self}\n'
                          '    table:\n      header: ["", "a"]\n'
                          '      rows: [["r", "+0.1"]]\n'
                          '    left: {text: "l"}\n    right: {text: "r"}\n')
        deckspec.load(p)            # is not rejected

    def test_a_full_width_chart_on_a_two_column_slide_reaches_the_deck(self):
        """`RENDERS["columns"]` allows `chart` and the PPTX draws it, but the deck only ever looked at
        `s["figure"]` -- the same layout existed in PowerPoint and was missing from the PDF.
        The fifth spot where the two outputs diverge."""
        p, tmp = self._spec(self.HEAD +
                            '  - kind: columns\n    title: "T"\n'
                            '    chart: {kind: heat, from: self}\n'
                            '    table:\n      header: ["", "a"]\n'
                            '      rows: [["r", "+0.1"]]\n'
                            '    left: {text: "l"}\n    right: {text: "r"}\n')
        out = os.path.join(tmp, "talk.tex")
        build_deck.build(p, out)
        src = deckspec.slurp(out)
        # the figure file is not produced here -- this only checks whether the deck recognized the spot
        self.assertIn("chart", src.replace("\\_", "_"))
        self.assertIn("01_self.png", src.replace("\\_", "_"))

    def test_a_pane_head_does_not_centre_the_rest_of_its_column(self):
        """`\\centering` stays in effect until the group ends -- this file already notes that twice,
        and it was still leaking from the pane head. Knowing about a bug and having fixed it are not the same thing."""
        p, tmp = self._spec(self.HEAD +
                            '  - kind: columns\n    title: "T"\n'
                            '    left: {head: "H", text: "body text"}\n'
                            '    right: {text: "r"}\n')
        out = os.path.join(tmp, "talk.tex")
        build_deck.build(p, out)
        src = deckspec.slurp(out)
        i = src.index("body text")
        # `\centering` from the pane head must be closed off
        self.assertNotIn("centering", src[src.index("{H}") if "{H}" in src
                                          else 0:i].split("\\par}")[-1])

    def test_a_full_width_figure_leaves_room_for_the_columns_below_it(self):
        """`fig_reserve` only knew "a figure inside a pane avoids the full-width figure above it," and
        did not know the reverse direction. So the full-width figure ate all the space, and the
        explanation below it ran off screen -- LaTeX stayed silent about it."""
        bare = {"left": {"text": "x"}, "right": {"text": "y"}}
        full = {"left": {"parts": [{"head": "H"},
                                   {"text": "a fairly long sentence here"},
                                   {"text": "and another one below it"}]},
                "right": {"text": "y"}}
        self.assertGreater(deckspec.fig_reserve(full, "self", full),
                           deckspec.fig_reserve(bare, "self", bare) + 0.2)

    def test_a_block_reserves_the_height_its_text_actually_needs(self):
        """The space calculation was looking for the box's text under a key called `body`, which
        doesn't exist. The schema calls it `text` -- within the same file, the schema and the calculation
        were looking at two different names. The box got cropped off screen."""
        short = {"block": {"title": "T", "text": "one line"}}
        long_ = {"block": {"title": "T", "text": "x" * 400}}
        self.assertGreater(deckspec.fig_reserve(long_),
                           deckspec.fig_reserve(short) + 0.3)

    def test_a_diagram_inside_a_pane_part_is_actually_drawn(self):
        """Adding `parts` missed the reading side in three places --
        `find_table`, `charts_in`, `diagrams_in`. A diagram placed inside a chunk never even got a
        file made for it, and the deck built that spot as an empty box."""
        import build_figs
        slide = {"n": 1, "left": {"parts": [
            {"text": "t"},
            {"diagram": {"kind": "flow", "boxes": [{"label": "one"}]}}]}}
        self.assertEqual(build_figs.diagrams_in(slide),
                         [("left", slide["left"]["parts"][1]["diagram"])])

    def test_a_table_inside_a_pane_part_can_feed_a_chart(self):
        import build_figs
        slide = {"n": 1, "left": {"parts": [
            {"head": "h"},
            {"table": {"header": ["", "a"], "rows": [["r", "+0.1"]]}}]}}
        self.assertIsNotNone(build_figs.find_table(slide, "left", "right"))

    def test_a_figure_taller_than_its_slot_is_scaled_not_clipped(self):
        """When there isn't enough room, there are three options: squeeze the strips further and text
        overlaps its neighbor; crop it and the last strip disappears; or grow the canvas and let
        LaTeX scale it down proportionally. The first two were hit in turn before arriving at the third."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="tall-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        words, seen = build_figs.draw_strip(
            {"kind": "strip", "legend": {"a": "ALPHA"},
             "rows": [{"label": "row %d" % i, "sub": "sub %d" % i,
                       "cells": [{"label": "A", "mark": "a"},
                                 {"label": "B", "span": 4}],
                       "note": "A NOTE LONG ENOUGH TO FOLD ONTO TWO LINES %d" % i}
                      for i in range(3)],
             "takeaway": "THE LAST LINE MUST SURVIVE."},
            os.path.join(tmp, "s.png"), (5.51, 1.2), warn)
        said = [t for _p, t in seen]
        self.assertIn("THE LAST LINE MUST SURVIVE.", said)
        self.assertIn("ALPHA", said)

    def test_a_missing_caption_is_not_reported_as_a_missing_figure(self):
        """The `else` was attached to the caption branch, so every figure without a caption
        produced "figure not found." A false positive erases the feature and buries the real warning."""
        src = deckspec.slurp(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "build_pptx.py"))
        i = src.index('Figure not found: %s"\n                                    % _img_path(top["path"]')
        head = src[:i]
        # the `else:` right before this warning must be paired with `if p:`
        self.assertIn("This `else` is `if p`'s partner", head[-600:])


class ComposedImpact(unittest.TestCase):
    """An impact slide can be a composition, not just one "big thing."

    Two values, a word between them, a condition under each value. One generated version placed
    one big sentence in that same spot, and `refcheck` counted both as "1 impact slide" and
    reported them as "equivalent." Counting alone cannot tell them apart.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: standout\n'
            '    big:\n'
            '      - {value: "-27.1", label: "paper forms", note: "replies lost", mark: hit}\n'
            '      - {value: "-3.1", label: "web forms", note: "replies lost", mark: safe}\n'
            '    gap: "24 more returned"\n'
            '    bullets: ["Web forms skip the post room."]\n')

    def _tex(self, text):
        tmp = tempfile.mkdtemp(prefix="imp-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, text)
            out = os.path.join(tmp, "talk.tex")
            build_deck.build(p, out)
            return tex_body(deckspec.slurp(out))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_two_numbers_are_set_side_by_side(self):
        src = self._tex(self.SPEC)
        flat = src.replace("\\bigminus ", "-")
        self.assertIn("-27.1", flat)
        self.assertIn("-3.1", flat)
        self.assertIn("24 more returned", src)
        self.assertIn("paper forms", src)
        self.assertIn("replies lost", src)
        self.assertIn("mHitLt", src)
        self.assertIn("mSafeLt", src)

    def test_each_column_stacks_rather_than_running_inline(self):
        """Inside a tabular cell, `\\par` does not start a new line -- three of them lined up
        side by side and the rightmost ran off screen. They must be stacked with a nested tabular."""
        src = self._tex(self.SPEC)
        self.assertGreaterEqual(src.count("\\begin{tabular}{@{}c@{}}"), 2)

    def test_the_paragraph_is_closed_so_bullets_fall_below(self):
        """Without `\\par`, the bullets that follow sit next to the table and overflow off screen."""
        self.assertIn("\\end{tabular}}\\par", self._tex(self.SPEC))  # closes the paragraph after the box that confines it to a fixed width

    def test_a_plain_string_big_still_works(self):
        src = self._tex('meta: {title: T, author: A, venue: V, date: D}\n'
                        'slides:\n  - kind: standout\n    big: "31x"\n')
        self.assertIn("31x", src)
        self.assertIn("fontsize{40}", src)


class ChartReplacesTheTable(unittest.TestCase):
    """A heat chart is a table turned into a figure. The original table has to be present in the
    spec, yet tables were banned, so a slide that turns a table into a figure could not be made.
    A rule I had set myself was blocking the exact layout I was aiming for."""

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: figure\n    title: "Visits by season"\n'
            '    chart: {from: self, kind: heat}\n'
            '    table:\n      header: ["", "spring", "autumn"]\n'
            '      rows:\n'
            '        - ["main hall", "+3.3", "+1.9"]\n'
            '        - ["annex", "-", "<hit>-18.9</hit>"]\n'
            '    say: ["The annex was shut for a season."]\n')

    def _spec(self):
        tmp = tempfile.mkdtemp(prefix="heat-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, self.SPEC)
        return tmp, p

    def test_a_table_feeding_a_chart_is_accepted_on_a_figure_slide(self):
        tmp, p = self._spec()
        try:
            deckspec.load(p)          # failure means an exception was raised
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_table_is_not_also_drawn(self):
        import build_figs
        tmp, p = self._spec()
        try:
            # the chart must actually be drawn first, or the builder inserts a placeholder instead of the figure
            build_figs.build(p, os.path.join(tmp, "figs"))
            out = os.path.join(tmp, "talk.tex")
            build_deck.build(p, out)
            src = tex_body(deckspec.slurp(out))
            self.assertIn("adjincludegraphics", src)
            self.assertIn("chart_01_self.png", src)
            self.assertNotIn("spring", src)        # the table itself does not go on screen
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_it_is_not_reported_as_duplication(self):
        """This is not showing the same value twice -- the table is only data."""
        import refcheck
        tmp, p = self._spec()
        try:
            self.assertEqual(refcheck.shape_notes(p)[0], [])
            n, got, _ = refcheck.profile_spec(p)
            self.assertEqual(got["figure"], 1.0)
            self.assertEqual(got["table"], 0.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_displayed_table_beside_its_own_chart_is_still_flagged(self):
        """The broadened rule must not let actual duplication through too."""
        import refcheck
        tmp = tempfile.mkdtemp(prefix="heat-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, 'meta: {title: T, author: A, venue: V, date: D}\n'
                             'slides:\n  - kind: columns\n    title: "T"\n'
                             '    left:  {table: {header: [a, b],\n'
                             '                    rows: [["x", "1"], ["y", "2"]]}}\n'
                             '    right: {chart: {from: left, kind: heat}}\n')
            self.assertEqual(refcheck.shape_notes(p)[0], [1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PanelFindingsMechanised(unittest.TestCase):
    """Whatever the panel used to catch that could be moved to a machine has been moved.

    The panel is the most valuable step in this pipeline and also the **only step with no machine
    behind it,** so it's the one that quietly gets skipped. Filtering out what can be caught first
    frees up people for the harder cases.
    """

    def _spec(self, body):
        import prose_audit as pa
        tmp = tempfile.mkdtemp(prefix="pf-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, "meta: {title: T, author: A, venue: V, date: D}\n"
                             "slides:\n" + body)
            return pa, pa.from_spec(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_colour_used_but_never_explained_is_flagged(self):
        pa, sl = self._spec(
            '  - title: "Results"\n'
            '    bullets: ["<hit>-12.3</hit> and <safe>+0.2</safe>"]\n'
            '    say: ["Look at the left column."]\n')
        self.assertIsNotNone(pa.colour_key_missing(sl))

    def test_explaining_the_colour_clears_it(self):
        pa, sl = self._spec(
            '  - title: "Results"\n'
            '    bullets: ["<hit>-12.3</hit> and <safe>+0.2</safe>"]\n'
            '    foot: ["Red: the cell failed; green: it held."]\n'
            '    say: ["Look at the left column."]\n')
        self.assertIsNone(pa.colour_key_missing(sl))

    def test_the_word_significant_is_not_a_colour_key(self):
        pa, sl = self._spec(
            '  - title: "Results"\n'
            '    bullets: ["<hit>-12.3</hit> is a significant drop"]\n'
            '    say: ["Look at the left column."]\n')
        self.assertIsNotNone(pa.colour_key_missing(sl))

    def test_a_key_given_only_later_is_a_note_not_a_failure(self):
        pa, sl = self._spec(
            '  - title: "Results"\n'
            '    bullets: ["<hit>-12.3</hit> and <safe>+0.2</safe>"]\n'
            '    say: ["Look at the left column."]\n'
            '  - title: "More"\n'
            '    bullets: ["x"]\n'
            '    foot: ["Red: the cell failed; green: it held."]\n'
            '    say: ["Another sentence."]\n')
        self.assertTrue(pa.colour_key_missing(sl).startswith(u"(info)"))

    def test_a_deck_with_no_colour_is_not_nagged(self):
        pa, sl = self._spec('  - title: "Plain"\n    bullets: ["x"]\n'
                            '    say: ["A sentence."]\n')
        self.assertIsNone(pa.colour_key_missing(sl))

    def test_one_label_with_two_values_is_flagged(self):
        """If both values are in the source, `deckcheck` §A passes -- the audience cannot tell which one to believe."""
        pa, sl = self._spec(
            '  - title: "First"\n    bullets: ["baseline 88.4 on this route"]\n'
            '    say: ["One."]\n'
            '  - title: "Second"\n    bullets: ["baseline 81.9 after redoing it"]\n'
            '    say: ["Two."]\n')
        got = dict(pa.contradicting_values(sl))
        self.assertIn("baseline", got)
        self.assertEqual([v for v, _ in got["baseline"]], ["81.9", "88.4"])

    def test_one_label_with_one_value_is_not_flagged(self):
        pa, sl = self._spec(
            '  - title: "First"\n    bullets: ["baseline 88.4 here"]\n'
            '    say: ["One."]\n'
            '  - title: "Second"\n    bullets: ["baseline 88.4 again"]\n'
            '    say: ["Two."]\n')
        self.assertEqual(pa.contradicting_values(sl), [])

    def test_a_number_word_that_disagrees_with_the_grid_is_flagged(self):
        pa, sl = self._spec(
            '  - kind: figure\n    title: "The five stations we compare"\n'
            '    figure:\n      grid:\n'
            '        images: [[a.png, b.png, c.png, d.png]]\n'
            '    say: ["Four columns."]\n')
        got = pa.count_mismatch(sl)
        self.assertTrue(any(said == 5 and real == 4 for _, said, real, _ in got),
                        got)

    def test_a_bare_number_word_is_not_counted(self):
        """Counting even a number word with no noun attached floods it with false positives -- ten actually occurred."""
        pa, sl = self._spec(
            '  - kind: figure\n    title: "Round two"\n'
            '    figure:\n      grid:\n'
            '        images: [[a.png, b.png, c.png, d.png]]\n'
            '    say: ["Nothing to see."]\n')
        self.assertEqual(pa.count_mismatch(sl), [])

    def test_a_declared_figure_count_is_checked(self):
        """"Can't count what's inside a PNG" was not the end of the story -- **just ask for the count
        to be declared.**

        Writing `figure: {path: x.png, shows: 4}` lets it be checked against "five things" in the body text.
        This is the exact spot that stopped all five panelists.
        """
        pa, sl = self._spec(
            '  - kind: figure\n    title: "The five stations we compare"\n'
            '    figure: {path: f.png, shows: 4}\n    say: ["Here."]\n')
        got = pa.count_mismatch(sl)
        self.assertTrue(any(said == 5 and real == 4 for _, said, real, _ in got),
                        got)

    def test_a_declared_count_that_agrees_is_silent(self):
        pa, sl = self._spec(
            '  - kind: figure\n    title: "The four soils we compare"\n'
            '    figure: {path: f.png, shows: 4}\n    say: ["Here."]\n')
        self.assertEqual(pa.count_mismatch(sl), [])

    def test_shows_must_be_a_positive_integer(self):
        tmp = tempfile.mkdtemp(prefix="pf-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, "meta: {title: T, author: A, venue: V, date: D}\n"
                             "slides:\n  - kind: figure\n    title: \"T\"\n"
                             "    figure: {path: f.png, shows: many}\n")
            with self.assertRaises(ValueError) as e:
                deckspec.load(p)
            self.assertIn("shows", str(e.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unexplained_blank_cells_are_flagged(self):
        """What isn't there is invisible to a checker. All five people got stuck on a blank cell."""
        pa, sl = self._spec(
            '  - kind: table\n    title: "Grid"\n'
            '    table: {header: [Cell, A, B],\n'
            '            rows: [["x", "1.0", "-"], ["y", "-", "2.0"]]}\n'
            '    say: ["Compare the two rows."]\n')
        self.assertTrue(pa.unexplained_blanks(sl))

    def test_explaining_the_blank_clears_it(self):
        pa, sl = self._spec(
            '  - kind: table\n    title: "Grid"\n'
            '    table: {header: [Cell, A, B],\n'
            '            rows: [["x", "1.0", "-"], ["y", "-", "2.0"]],\n'
            '            note: "A dash means the setting was not run."}\n'
            '    say: ["Compare the two rows."]\n')
        self.assertEqual(pa.unexplained_blanks(sl), [])

    def test_a_cast_compared_across_tables_but_never_drawn_is_flagged(self):
        """This was first written down as "cannot be expressed as a rule." Wrong -- the signal can be counted.

        The first-cell name that recurs across several tables is this talk's cast of characters, and if not
        a single figure appears before their first mention, the audience has been holding on by name alone.
        """
        rows = ('            rows: [["Intake", "1"], ["Pump", "2"],\n'
                '                   ["Outlet", "3"], ["Filter", "4"]]}\n')
        pa, sl = self._spec(
            '  - kind: table\n    title: "Delay by stage"\n'
            '    table: {header: [Stage, A],\n' + rows +
            '    say: ["One."]\n'
            '  - kind: table\n    title: "And on the night shift"\n'
            '    table: {header: [Stage, B],\n' + rows +
            '    say: ["Two."]\n')
        got = pa.never_drawn(sl)
        self.assertIsNotNone(got)
        names, first = got
        self.assertIn("Outlet", names)
        self.assertEqual(first, 1)

    def test_drawing_them_first_clears_it(self):
        rows = ('            rows: [["Intake", "1"], ["Pump", "2"],\n'
                '                   ["Outlet", "3"], ["Filter", "4"]]}\n')
        pa, sl = self._spec(
            '  - kind: figure\n    title: "What the line is made of"\n'
            '    figure: {path: line.png}\n    say: ["Four parts."]\n'
            '  - kind: table\n    title: "Delay by stage"\n'
            '    table: {header: [Stage, A],\n' + rows +
            '    say: ["One."]\n'
            '  - kind: table\n    title: "And on the night shift"\n'
            '    table: {header: [Stage, B],\n' + rows +
            '    say: ["Two."]\n')
        self.assertIsNone(pa.never_drawn(sl))

    def test_a_single_table_is_not_a_cast(self):
        """A name appearing in only one table is not a cast member -- this guards against a false positive."""
        pa, sl = self._spec(
            '  - kind: table\n    title: "Only once"\n'
            '    table: {header: [Stage, A],\n'
            '            rows: [["Intake", "1"], ["Pump", "2"],\n'
            '                   ["Outlet", "3"]]}\n'
            '    say: ["One."]\n')
        self.assertIsNone(pa.never_drawn(sl))

    def test_table_dimensions_are_not_compared_against_prose(self):
        """A table's rows and columns count something different from what the prose counts. Comparing them directly was wrong all ten times it was tried."""
        pa, sl = self._spec(
            '  - kind: table\n    title: "The three protocols we ran"\n'
            '    table: {header: [A, B, C],\n'
            '            rows: [["1","2","3"], ["4","5","6"],\n'
            '                   ["7","8","9"], ["10","11","12"]]}\n'
            '    say: ["A sentence."]\n')
        self.assertEqual(pa.count_mismatch(sl), [])


class ActionableOutput(unittest.TestCase):
    """A failure with no indication of where to fix it gets ignored. That's what happened in the blind trial."""

    def test_bullets_only_failure_names_the_slides(self):
        import refcheck
        tmp = tempfile.mkdtemp(prefix="ao-")
        try:
            p = os.path.join(tmp, "s.yaml")
            rows = "".join('  - title: "Slide %d"\n    bullets: ["only bullets here"]\n'
                           % i for i in range(1, 11))
            deckspec.spit(p, 'meta: {title: T, author: A, venue: V, date: D}\n'
                             'slides:\n' + rows)
            got = refcheck.bullets_only_slides(p)
            self.assertEqual(len(got), 10)
            self.assertEqual(got[0][0], 1)
            self.assertIn("Slide 1", got[0][1])
            buf = io.StringIO()
            with redirect_stdout(buf):
                refcheck.main([p])
            self.assertIn("slide  1", buf.getvalue())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_literal_double_percent_reaches_the_screen(self):
        """`%%` collapses to one `%` only inside a format string. Printed as a plain string, it prints as-is.

        This looks at a syntax tree instead of scanning text by eye. Scanning line by line would
          misfire on a format string spanning several lines, and would even count a `%%` sitting inside a
          comment -- this test got that wrong twice in one day.
        """
        import ast
        bad = []
        for name in sorted(os.listdir(SCRIPTS)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(deckspec.slurp(os.path.join(SCRIPTS, name)))
            for node in ast.walk(tree):
                # only looks at cases passed to `print()` as a bare string. A preamble kept aside and
                #   filled in later with `%`, or a `help=` string where argparse resolves `%%` its own way,
                #   are both fine -- casting the net too wide flagged both of these as false positives.
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "print"):
                    continue
                for arg in node.args:
                    if (isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)
                            and "%%" in arg.value):
                        bad.append("%s:%d %r"
                                   % (name, arg.lineno, arg.value[:48]))
        self.assertEqual(bad, [])


class DocumentedLayout(unittest.TestCase):
    """The command written in the docs had never actually been run.

    Tests always built from a single folder, while SKILL.md instructs sending output to `out/`.
    Under that layout, the builder only looked for figures in the spec's own folder, while the
    figure sat in `out/figs/` -- so anyone who followed the docs got a "missing" empty box where the
    chart should be, even though the figure would have typeset just fine.

    The blind trial caught this. Two lines within the docs contradicted each other, and
    no test had ever run that combination.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n'
            '  - kind: columns\n    title: "Late arrivals by region"\n'
            '    left:  {table: {header: [Region, A, B],\n'
            '                    rows: [["Harbour", "+3.3", "+1.9"],\n'
            '                           ["Hills", "-13.7", "+3.1"]]}}\n'
            '    right: {chart: {from: left, kind: heat, title: "Minutes"}}\n')

    def _run(self, outdir):
        """Builds as documented with output split into `out/`, and returns the warnings."""
        import build_figs
        import build_pptx
        tmp = tempfile.mkdtemp(prefix="layout-")
        try:
            spec = os.path.join(tmp, "slides.yaml")
            deckspec.spit(spec, self.SPEC)
            figs = os.path.join(tmp, outdir, "figs") if outdir else \
                os.path.join(tmp, "figs")
            build_figs.build(spec, figs)
            tex = os.path.join(tmp, outdir, "talk.tex") if outdir else \
                os.path.join(tmp, "talk.tex")
            _, _, warn = build_deck.build(spec, tex)
            src = deckspec.slurp(tex)
            pwarn = []
            try:
                px = tex.replace(".tex", ".pptx")
                pwarn = build_pptx.build(spec, px)[-1]
            except ImportError:
                pass
            return warn, pwarn, src
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_outputs_in_a_subdirectory_still_find_the_figures(self):
        warn, pwarn, src = self._run("out")
        self.assertEqual([w for w in warn if "not found" in w], [], warn)
        self.assertEqual([w for w in pwarn if "not found" in w], [], pwarn)
        self.assertIn("adjincludegraphics", src)
        self.assertNotIn("missing", src)

    def test_outputs_beside_the_spec_still_work(self):
        """The old layout must keep working too -- fixing one side must not break the other."""
        warn, pwarn, src = self._run("")
        self.assertEqual([w for w in warn if "not found" in w], [], warn)
        self.assertIn("adjincludegraphics", src)

    def test_a_genuinely_missing_figure_still_warns(self):
        """Making it look in two places must not let something genuinely missing slip through."""
        tmp = tempfile.mkdtemp(prefix="layout-")
        try:
            spec = os.path.join(tmp, "slides.yaml")
            deckspec.spit(spec, 'slides:\n  - title: "T"\n'
                                '    figure: {path: nope.png}\n')
            _, _, warn = build_deck.build(spec, os.path.join(tmp, "out", "talk.tex"))
            self.assertTrue(any("nope.png" in w for w in warn), warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FitCheck(unittest.TestCase):
    """There are things visible only once you look at the raster.

    Every workable presentation-generation system surveyed follows the same chain --
    read -> plan -> intermediate representation -> code -> render -> look and fix.
    The reason for the last two steps is always the same: the most common failure, overflow or
    overlap, is invisible in the source and visible only on the rendered screen.

    That step was missing from our chain. `deckcheck` reads the `.tex`, and
    `outcheck` only checks whether text arrived -- if text arrives and then sits on top of the
    next pane, both of them print pass.
    """

    BROKEN = r"""\documentclass[aspectratio=169,10pt]{beamer}
\usetheme[block=fill,numbering=fraction]{metropolis}
\usepackage{lmodern}
\usepackage[T1]{fontenc}
\begin{document}
\begin{frame}{Overflowing table}
  \begin{tabular}{lrrrrrrrrrrrrrrrr}
    A condition with a long name & 12.3 & 45.6 & 78.9 & 11.2 & 33.4 & 55.6 & 77.8 & 99.1 & 22.3 & 44.5 & 66.7 & 88.9 & 10.1 & 20.2 & 30.3 & 40.4 \\
  \end{tabular}
\end{frame}
\begin{frame}{Overlapping text}
  \raisebox{0pt}[0pt][0pt]{\makebox[0pt][l]{\hspace{3cm}\Large Left hand label}}%
  \raisebox{0pt}[0pt][0pt]{\makebox[0pt][l]{\hspace{3.4cm}\Large Right hand label}}
  \vspace{2cm}
\end{frame}
\begin{frame}{Tiny text}
  \begin{tiny}\begin{tiny}A whole sentence set far too small to read.\end{tiny}\end{tiny}
\end{frame}
\end{document}
"""

    @classmethod
    def setUpClass(cls):
        try:
            import fitz  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("PyMuPDF not installed")
        if not shutil.which("pdflatex"):
            raise unittest.SkipTest("pdflatex not installed")
        cls.tmp = tempfile.mkdtemp(prefix="fitcheck-")
        deckspec.spit(os.path.join(cls.tmp, "b.tex"), cls.BROKEN)
        for _ in range(2):
            subprocess.run(["pdflatex", "-interaction=nonstopmode", "b.tex"],
                           cwd=cls.tmp, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        cls.pdf = os.path.join(cls.tmp, "b.pdf")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", None) or ".", ignore_errors=True)

    def _kinds(self, pdf, argv=()):
        import fitcheck
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = fitcheck.main([pdf] + list(argv))
        return code, buf.getvalue()

    def test_pdflatex_itself_barely_notices(self):
        """A silent typesetter is exactly why this check exists."""
        log = deckspec.slurp(os.path.join(self.tmp, "b.log"))
        self.assertEqual(log.count("\n! "), 0, "pdflatex produced an error")

    def test_all_three_faults_are_caught(self):
        code, out = self._kinds(self.pdf, ["--margin", "0"])
        self.assertEqual(code, 1, out)
        for kind in ("off the page", "overlap", "small text"):
            m = re.search(r"!\s+%s\s+(\d+) page\(s\)" % kind, out)
            self.assertTrue(m and int(m.group(1)) > 0, "failed to catch %s\n%s"
                            % (kind, out))

    def test_footnote_markers_are_not_called_small(self):
        """A footnote marker is supposed to be small. A false positive hides the real problem."""
        import fitcheck
        self.assertTrue(fitcheck.MARKER.fullmatch("†"))
        self.assertTrue(fitcheck.MARKER.fullmatch("⋆"))
        self.assertFalse(fitcheck.MARKER.fullmatch("sentence"))

    def test_a_clean_deck_has_no_overflow_or_overlap(self):
        """A clean deck must pass first -- otherwise a negative-case check is meaningless.

        It only looks at overflow and overlap. Font size and margins depend on "which room this
          will be shown in," so the deck alone cannot decide right or wrong. Counting it as a failure without
          knowing the room turns a check into nagging.
        """
        tmp = tempfile.mkdtemp(prefix="fitclean-")
        try:
            tex = os.path.join(tmp, "talk.tex")
            build_deck.build(SPEC, tex)
            for _ in range(2):
                subprocess.run(["pdflatex", "-interaction=nonstopmode",
                                "talk.tex"], cwd=tmp,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            code, out = self._kinds(os.path.join(tmp, "talk.pdf"),
                                    ["--margin", "0", "--min-height", "0"])
            self.assertEqual(code, 0, out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



class FigureTextIsReallyThatSize(unittest.TestCase):
    """Text inside a figure is not in the PDF's text layer. So it went unseen.

    The deck blind trial 5 produced passed all seven checkers, yet the diagram's text came out at
    4.4pt on screen and the grid's column headers overlapped each other. Two causes:

      - the drawing side always drew at 7.2 inches wide, while the placing side squeezed it down to
        5.0-5.4cm. The measured shrink ratio was 0.337-0.495 -- **the declared pt was not the pt
        that ended up on screen.**
      - `matplotlib`'s `wrap=True` fits to the figure's width, not the box's width, so long
        labels ran outside the box.

    This slipped through while all 176 tests passed. What isn't watched isn't kept.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n'
            '  - kind: figure\n    title: "Where the gauge sits"\n'
            '    diagram:\n      kind: stack\n'
            '      boxes:\n'
            '        - {label: "the rain gauge sits under the eaves"}\n'
            '        - {label: "slanted rain misses it", mark: hit}\n'
            '    say: ["Two."]\n')

    def _build(self, spec_text=None):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="fs-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text or self.SPEC)
        out = os.path.join(tmp, "figs")
        made, lines, warn = build_figs.build(p, out)
        return tmp, out, made, warn

    def test_a_figure_never_exceeds_its_slot(self):
        """If it's bigger than its slot, the placing side squeezes it down, and the moment that happens
        the declared pt becomes a lie.

        Being small is correct. Stretching it to fill the slot would let a three-short-phrase
          flow diagram eat 60% of the slide -- it actually did, and drew the complaint "needlessly big."
          The figures in one example deck ranged 40-77% of width, following their content.
        """
        from PIL import Image
        tmp, out, made, warn = self._build()
        try:
            want = deckspec.slot("diagram", "self")
            with Image.open(made[0]) as im:
                dpi = im.info.get("dpi") or (72, 72)
                got = (im.width / dpi[0], im.height / dpi[1])
            self.assertLessEqual(got[0], want[0] + 0.01, "width exceeds the slot")
            self.assertLessEqual(got[1], want[1] + 0.01, "height exceeds the slot")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_short_diagram_does_not_fill_the_slot(self):
        """A flow diagram on page 4 ate 60% of the slide -- and it was only three short phrases."""
        from PIL import Image
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n'
                '  - kind: figure\n    title: "Three steps"\n'
                '    diagram:\n      kind: flow\n'
                '      boxes: [{label: "pick"}, {label: "add"}, '
                '{label: "report"}]\n'
                '    say: ["s"]\n')
        tmp, out, made, warn = self._build(spec)
        try:
            cap = deckspec.slot("diagram", "self")[1]
            with Image.open(made[0]) as im:
                h = im.height / (im.info.get("dpi") or (72, 72))[1]
            self.assertLess(h, cap * 0.62,
                            "three one-line boxes eat %.0f%% of the slot"
                            % (100 * h / cap))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_both_builders_get_the_height_from_the_same_function(self):
        """If the two sides see different numbers, the shrinking problem comes right back -- that was exactly this defect."""
        for what in ("chart", "diagram"):
            for where, pw in (("self", None), ("left", 0.46)):
                h_in = deckspec.slot(what, where, pw, 0.4)[1]
                cm = deckspec.slot_cm(what, where, pw, 0.4)
                self.assertAlmostEqual(float(cm[:-2]), h_in * 2.54, places=1)
        # does the placing side actually write out that number
        with io.open(os.path.join(SCRIPTS, "build_deck.py"), encoding="utf-8") as f_:
            src = f_.read()
        self.assertNotIn('"5.0cm"', src, "the height was hardcoded by hand again")
        self.assertNotIn('"5.4cm"', src)
        self.assertNotIn('"5.2cm"', src)
        self.assertIn("deckspec.slot_cm", src)

    def test_the_slot_shrinks_when_the_slide_carries_more(self):
        """With a fixed slot, the footnote runs off screen. It actually did."""
        bare = deckspec.slot("diagram", "self")[1]
        loaded = deckspec.slot(
            "diagram", "self",
            reserve=deckspec.fig_reserve(
                {"bullets": ["x" * 180], "foot": "y" * 200}))
        self.assertLess(loaded[1], bare)

    def test_a_label_never_leaves_its_box(self):
        """`wrap=True` fits to the figure's width. This measures whether it actually fits the box's width."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import build_figs
        fig, ax, xs, ys = build_figs._frame((2.4, 2.0))
        box_w, box_h = 30.0 * xs, 20.0 * ys       # inches
        pt = build_figs.fit_text(fig, ax, 50, 50, box_w, box_h,
                                 "the rain gauge sits under the eaves",
                                 build_figs.BODY_PT, ha="center", va="center")
        txt = [c for c in ax.texts][-1]
        bb = txt.get_window_extent(renderer=build_figs._renderer(fig))
        plt.close(fig)
        self.assertLessEqual(bb.width / 200.0, box_w + 0.02,
                             "label is wider than the box")
        self.assertLessEqual(bb.height / 200.0, box_h + 0.02,
                             "label is taller than the box")
        self.assertLessEqual(pt, build_figs.BODY_PT)

    def test_every_drawn_string_lands_in_textsize_tsv(self):
        """Only the drawing side knows that size. If it isn't recorded, the checker can never see it."""
        import build_figs
        tmp, out, made, warn = self._build()
        try:
            p = os.path.join(out, build_figs.TEXTSIZE)
            self.assertTrue(os.path.exists(p), "textsize.tsv does not exist")
            with io.open(p, encoding="utf-8") as f_:
                rows = [l.rstrip("\n").split("\t")
                        for l in f_
                        if l.strip() and not l.startswith("#")]
            self.assertTrue(rows)
            for r in rows:
                self.assertEqual(len(r), 6, "column count differs: %r" % (r,))
                float(r[4])                      # is pt a number
                self.assertEqual(len(r[3]), 64, "fingerprint length differs")
            drawn = {r[5] for r in rows}
            self.assertIn("slanted rain misses it", drawn)
            self.assertIn("the rain gauge sits under the eaves", drawn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_text_below_the_floor_is_reported_when_drawn(self):
        """The drawing side says so first -- before it even reaches the checker."""
        import build_figs
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n'
                '  - kind: columns\n    title: "T"\n'
                '    left:\n      width: 0.4\n'
                '      diagram:\n        kind: stack\n'
                '        boxes: [{label: "a"}, {label: "b"}]\n'
                '        note: "%s"\n'
                '    right:\n      bullets: ["x"]\n'
                '    say: ["s"]\n' % ("a very long note " * 9))
        tmp, out, made, warn = self._build(spec)
        try:
            self.assertTrue(any("pt" in w for w in warn),
                            "it got too small and nothing was said: %r" % warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FitcheckSeesInsideFigures(unittest.TestCase):
    """A canary -- does `fitcheck` catch figure text that was deliberately drawn too small.

    The most dangerous failure mode is something that used to be caught quietly no longer being
    caught. This defect was exactly that: text inside a PNG had never once, from the start,
    been counted.
    """

    def test_it_is_blind_without_the_sidecar_and_sees_with_it(self):
        import fitcheck
        tmp = tempfile.mkdtemp(prefix="fc-")
        try:
            tsv = os.path.join(tmp, "textsize.tsv")
            with io.open(tsv, "w", encoding="utf-8", newline="\n") as f_:
                f_.write(
                    "# png\tw\th\tfingerprint\tpt\ttext\n"
                    "d.png\t100\t50\t%s\t4.40\tunreadable\n" % ("0" * 64))
            got = fitcheck.fig_text(tsv)
            self.assertIn("0" * 64, got)
            self.assertEqual(got["0" * 64][0][0], 4.40)
            # without it, nothing can be seen at all -- that was the original state
            self.assertEqual(fitcheck.fig_text(None), {})
            self.assertEqual(fitcheck.fig_text(os.path.join(tmp, "nope")), {})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_figure_is_matched_by_fingerprint_not_by_size(self):
        """Matching by size meant a note from the page-6 diagram also showed up on pages 8 and 12.

        A diagram and a grid drawn in the same spot come out at the exact same pixel size.
        A checker that points at the wrong spot is worse than no checker at all.
        """
        from PIL import Image
        import fitcheck
        a = Image.new("RGB", (60, 40), (255, 255, 255))
        b = Image.new("RGB", (60, 40), (10, 10, 10))
        self.assertEqual(a.size, b.size)
        self.assertNotEqual(fitcheck.fingerprint(a), fitcheck.fingerprint(b))
        self.assertEqual(len(fitcheck.fingerprint(a)), 64)

    def test_the_two_sides_fingerprint_the_same_way(self):
        """Both sides must produce it the same way. Two different implementations would never once match."""
        from PIL import Image
        import build_figs
        import fitcheck
        im = Image.new("RGB", (37, 23), (200, 30, 30))
        for x in range(37):
            im.putpixel((x, x % 23), (0, 0, 0))
        self.assertEqual(build_figs.fingerprint(im), fitcheck.fingerprint(im))


class ChartInsideAPane(unittest.TestCase):
    """`chart.from: self` had never once been drawn inside a pane.

    `find_table(slide, "self")` looked for the slide's table, but the table was inside the pane.
    Blind trial 5 wrote this down as "not in the docs," but it wasn't a documentation gap, it was
    a bug. Because of it, the common two-column shape --
    "one pane shows it, the other pane says what to look at" -- could not be made.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n'
            '  - kind: columns\n    title: "Two branches"\n'
            '    left:\n      width: 0.55\n'
            '        \n'.replace("        \n", "")
            + '      chart: {from: self, kind: heat}\n'
            '      table:\n'
            '        header: ["Branch", "spring", "autumn, weekends"]\n'
            '        rows:\n'
            '          - ["Harbour", "+3.3", "+1.9"]\n'
            '          - ["Hill", "+3.1", "<hit>-14.3</hit>"]\n'
            '    right:\n      head: "What to look at"\n'
            '      bullets: ["The hill branch in **autumn**."]\n'
            '    say: ["s"]\n')

    def _figs(self):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="pc-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, self.SPEC)
        made, lines, warn = build_figs.build(p, os.path.join(tmp, "figs"))
        return tmp, p, made, warn

    def test_self_means_the_pane_the_chart_sits_in(self):
        import build_figs
        slide = {"table": {"rows": [["장"]]},
                 "left": {"table": {"rows": [["칸"]]}}}
        self.assertEqual(build_figs.find_table(slide, "self", "left"),
                         slide["left"]["table"])
        self.assertEqual(build_figs.find_table(slide, "self", "self"),
                         slide["table"])

    def test_a_pane_chart_is_actually_drawn(self):
        tmp, p, made, warn = self._figs()
        try:
            self.assertEqual(warn, [], "the pane chart produced a warning")
            self.assertEqual(len(made), 1)
            self.assertTrue(os.path.basename(made[0])
                            .startswith("chart_01_left"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_pane_chart_replaces_the_pane_table_in_both_outputs(self):
        """Printing both means the same data twice in one pane -- `refcheck` flags it."""
        tmp, p, made, warn = self._figs()
        try:
            out = os.path.join(tmp, "t.tex")
            build_deck.build(p, out, figdir="figs")
            with io.open(out, encoding="utf-8") as f_:
                tex = tex_body(f_.read())
            self.assertIn("chart_01_left.png", tex)
            self.assertNotIn("Harbour", tex, "the table was printed again next to the chart")
            with io.open(os.path.join(SCRIPTS, "build_pptx.py"), encoding="utf-8") as f_:
                src = f_.read()
            self.assertIn('if pane.get("table") and not ate:', src,
                          "the PPTX uses a different rule than the deck")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TwoColumnCandidates(unittest.TestCase):
    """Printing a ratio alone changes nothing.

    Blind trial 5 was handed "two-column layout 13/35" and still didn't change a single slide.
    That item wasn't in `STRICT`, `bad` came out 0, and all the advice lived inside `if bad:`, so
    not one line printed -- even though it was the biggest gap in the table.

    And "is it wide" is measured by character width, not column count. Measuring by column
      count once told a three-column table to become two columns, and doing so made it worse.
    """

    def _cand(self, spec_text):
        import refcheck
        tmp = tempfile.mkdtemp(prefix="cc-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return refcheck.column_candidates(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    NARROW = ('meta: {title: T, author: A, venue: V, date: D}\n'
              'slides:\n'
              '  - kind: figure\n    title: "Two temperatures"\n'
              '    chart: {from: self, kind: heat}\n'
              '    table:\n'
              '      header: ["Part", "40 C"]\n'
              '      rows:\n'
              '        - ["Anode", "+3.3"]\n'
              '        - ["Cathode", "-7.2"]\n'
              '    bullets: ["Only the cathode fades at **40 C**."]\n'
              '    foot: "Red means the cell failed."\n'
              '    say: ["s"]\n')

    WIDE = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n'
            '  - kind: table\n    title: "Route timings"\n'
            '    table:\n'
            '      header: ["", "the morning timetable", "the evening one"]\n'
            '      rows:\n'
            '        - ["Route 4, through the old town", "late by 12.6 min",'
            ' "late by 3.3 min"]\n'
            '        - ["Route 9, along the ring road", "early by 1.9 min",'
            ' "late by 18.9 min"]\n'
            '    bullets: ["Evening traffic slows the ring road'
            ' most of all."]\n'
            '    foot: "Minutes are medians over one month."\n'
            '    say: ["s"]\n')

    def test_a_narrow_visual_with_commentary_is_a_candidate(self):
        got = self._cand(self.NARROW)
        self.assertEqual([n for n, _, _ in got], [1])

    def test_a_wide_table_is_not(self):
        """65 characters wide. This test was added after actually converting it to two columns and finding it worse."""
        self.assertEqual(self._cand(self.WIDE), [])

    def test_width_is_measured_in_characters_not_columns(self):
        import refcheck
        narrow = {"header": ["Part", "20 C", "40 C, dry"],
                  "rows": [["Anode", "+3.3", "+1.9"]]}
        wide = {"header": ["", "the morning timetable", "the evening one"],
                "rows": [["Route 4, through the old town",
                          "late by 12.6 min", "late by 3.3 min"]]}
        self.assertEqual(len(narrow["header"]), len(wide["header"]))
        self.assertLess(refcheck.col_chars(narrow), refcheck.PANE_CHARS)
        self.assertGreater(refcheck.col_chars(wide), refcheck.PANE_CHARS)

    def test_a_slide_already_in_two_columns_is_not_a_candidate(self):
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n'
                '  - kind: columns\n    title: "T"\n'
                '    left:\n      width: 0.5\n'
                '      table:\n        header: ["a", "b"]\n'
                '        rows: [["x", "1"]]\n'
                '    right:\n      bullets: ["one", "two"]\n'
                '    say: ["s"]\n')
        self.assertEqual(self._cand(spec), [])

    def test_the_advice_prints_even_when_nothing_failed(self):
        """This is the crux of it. Even when it isn't a failure, a large gap should still be shown a path forward."""
        import refcheck
        tmp = tempfile.mkdtemp(prefix="cp-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, self.NARROW)
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = refcheck.main([p])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        out = buf.getvalue()
        self.assertIn("Few two-column slides", out)
        self.assertIn("one pane shows it", out)
        self.assertIn("slide  1", out, "did not point to which slide")


class SizeFollowsContent(unittest.TestCase):
    """This skill's sizing must come from the content, not from a constant.

    The user raised four complaints at once, and all four traced to the same cause:
      - "page 4's figure is needlessly big" -- the figure was drawn at the full slot size
      - "page 16's text is also too big" -- impact text was fixed at 40pt
      - "the charts aren't used effectively" -- the grid was always full body width
      - "17-21 are nothing but a list of tables" -- the title just named the content instead of stating a claim

    Measuring one example deck set the standard. This is measurement, not taste:
      figure  height 31~59%% . width 40~77%%   (the generated version was always 87%% width)
      impact text  digits 40pt . words 14pt  (the generated version set words at 40pt too)
    """

    def test_big_is_large_only_when_it_is_a_value(self):
        """In one example deck, 40pt was reserved for big numbers only, and words were all 14pt --
        even the long conclusion sentence. Impact comes from the black screen, not from the letters."""
        for s in ("-27.1", "+0.0", "31x", "3.3x", "92%"):
            self.assertEqual(deckspec.big_pt(s), deckspec.BIG_PT_NUMBER, s)
        for s in ("a bakery on the corner",
                  "north gate or south gate",
                  "the late shift on Fridays"):
            self.assertEqual(deckspec.big_pt(s), deckspec.BIG_PT_WORDS, s)

    def test_a_worded_big_is_not_typeset_at_forty_points(self):
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: standout\n'
                '    big: "a bakery on the corner"\n'
                '    say: ["s"]\n')
        tmp = tempfile.mkdtemp(prefix="bg-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, spec)
            out = os.path.join(tmp, "t.tex")
            build_deck.build(p, out)
            src = tex_body(deckspec.slurp(out))
            self.assertIn("fontsize{14}", src)
            self.assertNotIn("fontsize{40}", src)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_typesetting_numbers_are_not_counted_as_content(self):
        """Third time this happened. The 38 in `fontsize{34}{38}` and the 14 in `{14}{16}` got counted
        as content numbers, failing a perfectly fine deck. Each time it happened, it was patched by adding
        it to `skip_numbers`, but that is a workaround. A typesetting argument is not screen text."""
        src = (r"{\fontsize{14}{16}\selectfont 31x\par}"
               r"\\[0.25em] \vspace{0.7em} \raisebox{0.27em}{x}"
               r" 92.4 hours")
        got = deckcheck.screen_text(src)
        for n in ("14", "16", "0.25", "0.7", "0.27"):
            self.assertNotIn(n, got, "typesetting number %s remained" % n)
        self.assertIn("31x", got)
        self.assertIn("92.4", got)


class TitlesStateTheClaim(unittest.TestCase):
    """A title must say what the slide answers. A table is evidence, not the answer.

    Measured it: one example deck's main body was 88%% sentence-or-question titles, the generated
    version's main body was 100%% -- the skill was already doing well there. But the generated
    version's backup slides were only 29%%. The gap sat there and nowhere else, and the user
    pointed at exactly those five slides.

    Why backup slides matter more: while it's up for about 15 seconds after a question comes in, all
    the audience reads is the title, and there is no follow-up explanation.
    """

    def _audit(self, spec_text):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="ti-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return prose_audit.names_not_claims(prose_audit.read_slides(p))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'
    TABLE = ('    table:\n      header: ["a", "b"]\n'
             '      rows: [["x", "1"]]\n    say: ["s"]\n')

    def test_a_named_backup_table_is_flagged(self):
        got = self._audit(self.HEAD + '  - kind: table\n    backup: true\n'
                          '    title: "Backup: per-valve readings"\n'
                          + self.TABLE)
        self.assertEqual([(n, b) for n, b, _ in got], [(1, True)])

    def test_a_sentence_title_passes(self):
        got = self._audit(self.HEAD + '  - kind: table\n    backup: true\n'
                          '    title: "No single month drives the result"\n'
                          + self.TABLE)
        self.assertEqual(got, [])

    def test_a_question_title_passes(self):
        got = self._audit(self.HEAD + '  - kind: table\n    backup: true\n'
                          '    title: "Backup: is one month driving it?"\n'
                          + self.TABLE)
        self.assertEqual(got, [])

    def test_a_lead_carrying_the_answer_passes(self):
        """If there's a reason the title can't be changed, the answer can be written in `lead` instead."""
        got = self._audit(self.HEAD + '  - kind: table\n    backup: true\n'
                          '    title: "Backup: per-valve readings"\n'
                          '    lead: "No single month drives the result."\n'
                          + self.TABLE)
        self.assertEqual(got, [])

    def test_an_impact_slide_is_not_judged_on_its_title(self):
        """On an impact slide, `big` itself is the claim. Since it takes the title's place,
        judging it by the title rule would wrongly flag it as "made no claim" -- and it actually did."""
        got = self._audit(self.HEAD + '  - kind: standout\n'
                          '    big: "a bakery on the corner"\n'
                          '    say: ["s"]\n')
        self.assertEqual(got, [])


class PaperFiguresAreNotSlideFigures(unittest.TestCase):
    """Do not put a paper's figure into a talk as-is.

    "Abandon the practice of dropping a paper's figure straight into a talk" -- Rougier, Droettboom &
    Bourne 2014, *PLoS Comput Biol* 10(9):e1003833, Rule 3.
    "Don't copy-paste a paper's table out of the PDF. Rebuild it to be readable" -- Ernst (UW).
    Projected, the lines are thin and the text is small. A multi-panel figure should become one panel
    per slide (Naegle, Rule 6).

    Our own generated deck was doing exactly this twice, and no checker caught it.
    """

    def _flag(self, spec_text):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="pf-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return prose_audit.pasted_paper_figures(prose_audit.read_slides(p))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_a_paper_figure_is_flagged(self):
        got = self._flag(self.HEAD + '  - kind: figure\n    title: "The garden beds"\n'
                         '    figure: {path: "fig_a.png"}\n'
                         '    say: ["s"]\n')
        self.assertEqual([n for n, _ in got], [1])

    def test_what_the_skill_drew_is_not_flagged(self):
        """`chart_*`/`diagram_*` are things the skill itself drew at slot size."""
        for name in ("chart_01_self.png", "diagram_04_self.png",
                     "talk_x.png"):
            got = self._flag(self.HEAD + '  - kind: figure\n    title: "T"\n'
                             '    figure: {path: "%s"}\n    say: ["s"]\n' % name)
            self.assertEqual(got, [], name)

    def test_a_figure_inside_a_pane_is_seen_too(self):
        got = self._flag(self.HEAD + '  - kind: columns\n    title: "T"\n'
                         '    left:\n      width: 0.5\n'
                         '      figure: {path: "fig_b.png"}\n'
                         '    right:\n      bullets: ["x"]\n    say: ["s"]\n')
        self.assertEqual([n for n, _ in got], [1])


class TilesAndPanels(unittest.TestCase):
    """A tile grid with two panels set side by side -- blind trial 5 wrote this shape down as
    "cannot be expressed." It really wasn't there.

    The decisive difference from my own `heat` is that this **fills in cells that aren't significant
      too.** Numbers on a white background alone just end up as a pretty table.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: figure\n    title: "Two branches"\n'
            '    chart:\n      kind: tiles\n'
            '      panels:\n'
            '        - title: "Harbour"\n'
            '          table:\n            header: ["", "spring", "autumn"]\n'
            '            rows:\n'
            '              - ["mornings", "+3.3", "+1.9"]\n'
            '              - ["noon", "-", "+3.1"]\n'
            '              - ["evenings", "<hit>-14.3</hit>", "<hit>-11.7</hit>"]\n'
            '        - title: "Hill"\n'
            '          table:\n            header: ["", "spring", "autumn"]\n'
            '            rows:\n'
            '              - ["mornings", "+0.0", "+3.9"]\n'
            '              - ["noon", "+1.9", "-"]\n'
            '              - ["evenings", "<hit>-12.6</hit>", "<hit>-18.9</hit>"]\n'
            '      row_label: "time of day"\n'
            '      col_label: "season"\n'
            '    say: ["s"]\n')

    def _build(self, spec_text=None):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="tl-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text or self.SPEC)
        out = os.path.join(tmp, "figs")
        made, lines, warn = build_figs.build(p, out, os.path.join(out, "v.txt"))
        return tmp, out, made, lines, warn

    def test_two_panels_are_drawn_as_one_figure(self):
        tmp, out, made, lines, warn = self._build()
        try:
            self.assertEqual(warn, [], "warning: %r" % warn)
            self.assertEqual(len(made), 1)
            self.assertTrue(os.path.basename(made[0]).startswith("chart_01"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_every_value_reaches_the_sidecar(self):
        """Text inside a figure is pixels. Without recording it, `outcheck` reports everything as "did not arrive"."""
        tmp, out, made, lines, warn = self._build()
        try:
            flat = " ".join(lines)
            for v in ("-14.3", "-12.6", "-18.9", "+3.9",
                      "Harbour", "Hill"):
                self.assertIn(v, flat, v)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_panel_tables_are_visible_to_the_checkers(self):
        """If the checker can't see it, that number reaches the screen with no check at all."""
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="tv-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, self.SPEC)
        try:
            sl = prose_audit.read_slides(p)[0]
            self.assertIn("-14.3", sl["screen"])
            self.assertIn("Harbour", sl["screen"])
            self.assertEqual(len(prose_audit.tables_of(
                deckspec.load(p)[1][0])), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_it_says_how_many_columns_fit_when_it_cannot(self):
        """Saying only "it doesn't fit" leaves no idea what to cut. This is a repeated failure pattern
        in this skill -- pointing out a problem without offering a way forward is just nagging."""
        wide = self.SPEC.replace(
            '["", "spring", "autumn"]',
            '["", "spring, weekdays", "summer holidays", "autumn, weekends"]'
        ).replace('"+3.3", "+1.9"', '"+3.3", "+3.1", "+1.9"'
                  ).replace('"-", "+3.1"', '"-", "+1.9", "+3.1"'
                            ).replace('"<hit>-14.3</hit>", "<hit>-11.7</hit>"',
                                      '"<hit>-14.3</hit>", "+3.3", "<hit>-11.7</hit>"'
                                      ).replace('"+0.0", "+3.9"', '"+0.0", "+3.3", "+3.9"'
                                                ).replace('"+1.9", "-"', '"+1.9", "-", "+3.3"'
                                                          ).replace('"<hit>-12.6</hit>", "<hit>-18.9</hit>"',
                                                                    '"<hit>-12.6</hit>", "+3.1", "<hit>-18.9</hit>"')
        tmp, out, made, lines, warn = self._build(wide)
        try:
            self.assertTrue(warn, "it doesn't fit and nothing was said")
            msg = " ".join(warn)
            self.assertIn("columns", msg)
            self.assertIn("Flipping", msg, "no suggestion to transpose")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TypesetStrippingDoesNotEatContent(unittest.TestCase):
    """Guards against a regression I introduced myself.

    Making the typesetting command strip its argument along with it, without bounding the argument's
    length, ended up deleting the entire footnote following `\\vspace{0.35em}`. That footnote's
    number then gets reported as "exists only in the PPTX" -- it actually was reported that way.
    A checker that silently deletes screen text is the worst kind of bug.
    """

    def test_a_following_group_is_not_eaten(self):
        nl, bs = chr(10), chr(92)
        src = (bs + "vspace{0.35em}" + nl + "  {" + bs + "footnotesize" + nl
               + "  Rain adds 3.9 minutes to the round.}")
        got = deckcheck.screen_text(src)
        self.assertIn("3.9", got, "the footnote was swallowed whole")
        self.assertIn("Rain adds", got)
        self.assertNotIn("0.35", got)

    def test_the_arguments_themselves_still_go(self):
        bs = chr(92)
        got = deckcheck.screen_text(
            "{" + bs + "fontsize{14}{16}" + bs + "selectfont 31x" + bs + "par}")
        for n in ("14", "16"):
            self.assertNotIn(n, got)
        self.assertIn("31x", got)


class ConceptFigures(unittest.TestCase):
    """A device for drawing a paper's foundational concept.

    A concept figure comes before the first results slide -- what the key terms are, what parts
    the subject is made of.

    My `diagram` was only boxes and arrows, so it could draw none of the three, and the generated
    deck ended up either writing concept slides as bullets or skipping them entirely and jumping
    straight to numbers -- the complaint "it's nothing but numbers" is exactly that.
    """

    STRIP = ('meta: {title: T, author: A, venue: V, date: D}\n'
             'slides:\n  - kind: figure\n    title: "What each ticket covers"\n'
             '    diagram:\n      kind: strip\n'
             '      rows:\n'
             '        - label: "single"\n          sub: "one ride"\n'
             '          cells:\n'
             '            - {label: "R", mark: ride}\n'
             '          note: "one ride"\n'
             '        - label: "day pass"\n          sub: "until midnight"\n'
             '          cells:\n'
             '            - {label: "R", mark: ride}\n'
             '            - {label: "T", span: 4, mark: transfer}\n'
             '          note: "unlimited rides"\n'
             '        - label: "week pass"\n          sub: "seven days"\n'
             '          cells:\n'
             '            - {label: "R", mark: ride}\n'
             '            - {label: "T", span: 4, mark: transfer}\n'
             '            - {label: "N", span: 2, mark: night}\n'
             '          note: "night buses too"\n'
             '      legend: {ride: "one ride", transfer: "transfer",'
             ' night: "night bus"}\n'
             '    say: ["s"]\n')

    PIPE = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: figure\n    title: "The three stations"\n'
            '    diagram:\n      kind: pipeline\n'
            '      rows:\n'
            '        - label: "Depot"\n          sub: "night shift"\n'
            '          stages:\n'
            '            - {label: "receive", group: "dock", count: "12"}\n'
            '            - {label: "sort", group: "floor", count: "25"}\n'
            '            - {label: "load", group: "yard", count: "7",'
            ' mark: hit}\n'
            '          out: "trucks"\n'
            '    say: ["s"]\n')

    def _build(self, spec_text):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="cf-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        out = os.path.join(tmp, "figs")
        made, lines, warn = build_figs.build(p, out, os.path.join(out, "v.txt"))
        return tmp, made, lines, warn

    def test_a_strip_is_drawn(self):
        tmp, made, lines, warn = self._build(self.STRIP)
        try:
            self.assertEqual(warn, [], "warning: %r" % warn)
            self.assertEqual(len(made), 1)
            self.assertTrue(os.path.getsize(made[0]) > 3000)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_pipeline_is_drawn(self):
        tmp, made, lines, warn = self._build(self.PIPE)
        try:
            self.assertEqual(_but_thin(warn), [], "warning: %r" % warn)
            self.assertEqual(len(made), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_their_words_reach_the_sidecar(self):
        """Text inside a figure is pixels. Without recording it, `outcheck` reports everything as "did not arrive"."""
        for spec, wants in ((self.STRIP, ("day pass", "unlimited rides", "transfer")),
                            (self.PIPE, ("receive", "12", "trucks",
                                         "dock"))):
            tmp, made, lines, warn = self._build(spec)
            try:
                flat = " ".join(lines)
                for w in wants:
                    self.assertIn(w, flat, w)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_a_role_is_a_pale_fill_and_a_strong_line(self):
        """One role spans three channels -- a pale fill, a strong outline, and text in that color.

        Filling a large area with a saturated color spends the whole figure's contrast budget on that
        area, and the text inside it and the arrows next to it end up fighting it for attention. That is
        why a saturated fill reads as cheap (the larger the area, the lower the saturation should go,
        Munzner ch.10).
        """
        import build_figs
        import design
        names = ["a", "b", "hit", "safe", "a"]
        fill = {k: design.fill_of(k) for k in ("a", "b", "hit", "safe")}
        mark = build_figs.role_map(names)
        ink = build_figs.role_ink(names)
        self.assertEqual(ink["hit"], build_figs.HIT)
        self.assertEqual(ink["safe"], build_figs.SAFE)
        self.assertNotEqual(mark["a"], mark["b"])

        def _lum(h):
            r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        # the larger the area, the lower the saturation: large area > small cell > line
        for k in ("a", "b", "hit", "safe"):
            self.assertGreater(_lum(fill[k]), _lum(mark[k]) + 0.10,
                               "%s: the large area is as saturated as the small cell" % k)
            self.assertGreater(_lum(mark[k]), _lum(ink[k]) + 0.10,
                               "%s: the small cell is as saturated as the line" % k)

        def lum(h):
            r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for k in ("a", "b", "hit", "safe"):
            self.assertGreater(lum(fill[k]), lum(ink[k]) + 0.35,
                               "%s's fill is as dark as its outline" % k)
            self.assertGreater(lum(fill[k]), 0.80,
                               "%s's fill is unreadable under black text" % k)

    def test_there_are_only_three_stroke_weights(self):
        """If adjacent weights differ by less than 1.5x, they read as inconsistent, not as a hierarchy.
        Technical drafting standards (ISO 128-2) use a 1:2 ratio between two levels."""
        import design
        w = [design.HAIR, design.BASE, design.EMPH]
        self.assertEqual(sorted(w), w)
        for a, b in zip(w, w[1:]):
            self.assertGreaterEqual(b / a, 1.5, "the weight steps are too close together: %r" % w)

    def test_the_radius_never_turns_a_thin_strip_into_a_pill(self):
        """Beyond a quarter of the short side, it reads as a button, not a structural shape."""
        import design
        for short in (0.04, 0.08, 0.2, 1.0):
            self.assertLessEqual(design.radius(short), short / 4.0)


class ConceptComesBeforeNumbers(unittest.TestCase):
    """How to count "it's nothing but numbers."

    A good deck states the concept through a figure first, then gives the numbers. Without a
    figure, going straight to results hands the audience numbers before they know what's being
    measured, and all that's left for them to do is read the table -- that's a report, not a talk.
    """

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'
    TABLE = ('  - kind: table\n    title: "The numbers"\n'
             '    table:\n      header: ["m", "a", "b"]\n'
             '      rows:\n'
             '        - ["x", "1.0", "2.0"]\n'
             '        - ["y", "3.0", "4.0"]\n'
             '    say: ["s"]\n')
    FIG = ('  - kind: figure\n    title: "What we cut"\n'
           '    diagram:\n      kind: flow\n'
           '      boxes: [{label: "one"}, {label: "two"}]\n'
           '    say: ["s"]\n')

    def _check(self, spec_text):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="cb-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return prose_audit.concept_before_results(
                prose_audit.read_slides(p))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_straight_to_numbers_is_caught(self):
        first, pre = self._check(self.HEAD + self.TABLE)
        self.assertEqual(first, 1)
        self.assertEqual(pre, 0)

    def test_a_figure_first_passes(self):
        first, pre = self._check(self.HEAD + self.FIG + self.TABLE)
        self.assertEqual(first, 2)
        self.assertEqual(pre, 1)

    def test_a_deck_with_no_numbers_is_not_judged(self):
        first, pre = self._check(self.HEAD + self.FIG)
        self.assertIsNone(first)


class CenteringDoesNotSwallowTheTable(unittest.TestCase):
    """A regression I introduced myself. Wrapping the figure/table in `{\\centering ... \\par}`
    to fix footnote alignment made the table inside `adjustbox` disappear entirely. Typesetting
    still passed, and the log said nothing -- it surfaced only because `outcheck`'s
    "fragments that never arrived" count jumped from 10 to 27.

    So instead, the footnote side resets it back with `\\raggedright`. What was meant to be
      fixed still gets fixed, and the table survives.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: table\n    title: "The numbers"\n'
            '    table:\n      header: ["m", "a", "b"]\n'
            '      rows:\n'
            '        - ["anode", "1.0", "2.0"]\n'
            '        - ["cathode", "3.0", "4.0"]\n'
            '    foot: "A footnote long enough to run past one line so that any '
            'centring left over from the table above it shows up as a ragged '
            'right edge instead of a flush one."\n'
            '    say: ["s"]\n')

    def _tex(self):
        tmp = tempfile.mkdtemp(prefix="ct-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.SPEC)
            out = os.path.join(tmp, "t.tex")
            build_deck.build(p, out)
            return tex_body(deckspec.slurp(out))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_table_is_not_wrapped_in_a_centering_group(self):
        src = self._tex()
        self.assertIn("\\centering", src)
        self.assertNotIn("{\\centering", src,
                         "wrapping in `{\\centering ...}` makes the table inside adjustbox disappear")

    def test_the_foot_resets_the_alignment_itself(self):
        """Instead of wrapping, the footnote resets it -- that's the way to fix alignment while keeping the table alive."""
        src = self._tex()
        self.assertIn("\\raggedright", src)

    def test_the_table_survives_the_round_trip(self):
        """A case where typesetting passes but the text vanishes. This checks it actually survives."""
        if not shutil.which("pdflatex"):
            self.skipTest("pdflatex not installed")
        tmp = tempfile.mkdtemp(prefix="cr-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.SPEC)
            out = os.path.join(tmp, "t.tex")
            build_deck.build(p, out)
            r = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                 "t.tex"], cwd=tmp, capture_output=True, text=True,
                errors="replace")
            pdf = os.path.join(tmp, "t.pdf")
            if r.returncode or not os.path.exists(pdf):
                self.skipTest("pdflatex not installed")
            import fitz
            doc = fitz.open(pdf)
            got = " ".join(p_.get_text() for p_ in doc)
            doc.close()
            for w in ("anode", "cathode", "1.0", "4.0"):
                self.assertIn(w, got, "%s did not appear on screen" % w)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class AGroupFirstEatsTheBody(unittest.TestCase):
    """If a frame's body starts with `{`, its content disappears entirely.

    Blind trial 6's opening evidence slide came out as a blank screen -- zero figures, zero LaTeX
    errors, not one line in the log. The conditions are narrow (a figure grid + bullets + no `lead`),
    which makes it easy to miss: with `lead` present, text comes first; without bullets, `\\vfill`
    comes first.

    This skill already knew about this -- the `standout` code path notes "without one, the next
      `{..}` gets swallowed as the frametitle." The problem was that the defense existed on only that
      one path. So `guard_group` now blocks it at every return point.
    """

    def _spec(self, extra):
        return ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: figure\n    title: "The grid"\n'
                '    figure:\n      grid:\n'
                '        cols: ["one", "two"]\n'
                '        rows: ["top", "bottom"]\n'
                '        images: [["a.png", "b.png"], ["c.png", "d.png"]]\n'
                + extra + '    say: ["s"]\n')

    def test_the_guard_is_inserted_when_the_body_starts_with_a_group(self):
        tmp = tempfile.mkdtemp(prefix="gg-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self._spec('    bullets: ["a line"]\n'))
            out = os.path.join(tmp, "t.tex")
            build_deck.build(p, out)
            src = tex_body(deckspec.slurp(out))
            body = src[src.index("\\begin{frame}{The grid}"):]
            first = [l.strip() for l in body.splitlines()[1:] if l.strip()][0]
            self.assertFalse(first.startswith("{"),
                             "the body starts with `{` -- the content disappears")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_images_actually_reach_the_page(self):
        """A case where the source looks fine but the screen is blank. This compiles and counts."""
        if not shutil.which("pdflatex"):
            self.skipTest("pdflatex not installed")
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="gp-")
        try:
            figs = os.path.join(tmp, "figs")
            os.makedirs(figs)
            for n in ("a", "b", "c", "d"):
                Image.new("RGB", (120, 90), (180, 190, 200)).save(
                    os.path.join(figs, "%s.png" % n))
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self._spec('    bullets: ["a line"]\n'))
            out = os.path.join(tmp, "t.tex")
            build_deck.build(p, out, figdir="figs")
            r = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                 "t.tex"], cwd=tmp, capture_output=True, text=True,
                errors="replace")
            pdf = os.path.join(tmp, "t.pdf")
            if r.returncode or not os.path.exists(pdf):
                self.skipTest("pdflatex not installed")
            import fitz
            doc = fitz.open(pdf)
            n_img = len(doc[1].get_image_info())
            doc.close()
            self.assertEqual(n_img, 4, "the grid came out as a blank screen")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ComposedImpactIsReadable(unittest.TestCase):
    """A `big` list made it into all three builders but not into the three that read it back.

    A Python dict printed straight into the script's heading, `outcheck` produced four permanent
    false positives, and `refcheck` counted that slide as "no emphasis." This skill fell into a trap
    it had written down itself -- "when a feature goes into one builder, add it to the others in the
    same pass."
    """

    BIG = [{"value": "-27.1", "label": "paper forms", "note": "by post",
            "mark": "hit"},
           {"value": "-3.1", "label": "web forms", "note": "online"}]

    def test_it_reads_as_a_sentence_not_a_dict(self):
        s = deckspec.big_text(self.BIG)
        self.assertNotIn("{", s)
        self.assertNotIn("'value'", s)
        self.assertIn("-27.1", s)
        self.assertIn("paper forms", s)
        self.assertIn("vs", s)

    def test_every_piece_is_offered_to_the_checkers(self):
        parts = deckspec.big_parts(self.BIG)
        for w in ("-27.1", "-3.1", "paper forms", "web forms", "by post"):
            self.assertIn(w, parts, w)

    def test_a_plain_string_still_works(self):
        self.assertEqual(deckspec.big_text("31x"), "31x")
        self.assertEqual(deckspec.big_parts("31x"), ["31x"])

    def test_the_script_heading_is_the_sentence(self):
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: standout\n'
                '    big:\n'
                '      - {value: "-27.1", label: "paper forms", note: "by post"}\n'
                '      - {value: "-3.1", label: "web forms", note: "online"}\n'
                '    say: ["Two numbers."]\n')
        tmp = tempfile.mkdtemp(prefix="bs-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, spec)
            out = os.path.join(tmp, "script.md")
            build_script.build(p, out)
            with io.open(out, encoding="utf-8") as f_:
                heads = [l for l in f_
                         if l.startswith("## ")]
            self.assertTrue(heads)
            self.assertNotIn("'value'", " ".join(heads))
            self.assertIn("-27.1", " ".join(heads))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ThePowerPointGeometryIsChecked(unittest.TestCase):
    """The podium machine is PowerPoint. Yet **there was no check that looked at the PPTX's
    geometry** -- `deckcheck` F counts the character set, G counts the slide count. While both
    passed, text ran across a figure on four slides, and blind trial 6 found it by eye.

    The cause is exactly the rule `traps.md` had already written down --
      "constraining only one axis does not constrain the box." The deck constrains both axes, while
      the PPTX was only constraining width.
    """

    SPEC = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: figure\n    title: "A tall figure"\n'
            '    figure: {path: "tall.png"}\n'
            '    bullets: ["a line about it", "and another line"]\n'
            '    foot: "a footnote"\n    say: ["s"]\n')

    def test_text_does_not_cross_the_picture(self):
        from PIL import Image
        import fitcheck
        import build_pptx
        tmp = tempfile.mkdtemp(prefix="pg-")
        try:
            figs = os.path.join(tmp, "figs")
            os.makedirs(figs)
            # a tall figure -- constrained by width only, it would grow downward
            Image.new("RGB", (400, 700), (170, 180, 195)).save(
                os.path.join(figs, "tall.png"))
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.SPEC)
            out = os.path.join(tmp, "t.pptx")
            build_pptx.build(p, out, figdir=figs)
            bad = fitcheck.check_pptx(out)
            self.assertEqual(bad, [], "text overlaps the figure or runs off screen")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CheckerFalseAlarms(unittest.TestCase):
    """A false positive erases a feature. Blind trial 6 saw a wrong warning from `draw_strip`
    and abandoned the figure entirely -- because the example given in the docs failed its own
    checker.
    """

    def test_a_bar_strip_that_fits_does_not_warn(self):
        import build_figs
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: figure\n    title: "Budget"\n'
                '    diagram:\n      kind: strip\n'
                '      rows:\n'
                '        - {label: "company", bars: 30, groups: [30],'
                ' group_label: "one budget", mark_at: 11, note: "all 30 draw on it"}\n'
                '        - {label: "teams", bars: 30, groups: [13, 9, 8],'
                ' group_label: "per team", mark_at: 11, note: "10 share each"}\n'
                '    say: ["s"]\n')
        tmp = tempfile.mkdtemp(prefix="bw-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, spec)
            made, lines, warn = build_figs.build(p, os.path.join(tmp, "figs"))
            self.assertEqual(warn, [], "a figure that fits produced a warning")
            from PIL import Image
            with Image.open(made[0]) as im:
                dpi = im.info.get("dpi") or (72, 72)
                self.assertLessEqual(im.width / dpi[0],
                                     deckspec.slot("diagram", "self")[0] + 0.01)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_unit_value_is_not_counted_as_a_count(self):
        """"eight hours" was compared against a 4-column grid and flagged as a false positive. Any
        deck dealing with units would always trip this as long as it had a figure grid."""
        import prose_audit
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: figure\n'
                '    title: "Patients on the ward slept eight hours on average"\n'
                '    figure:\n      grid:\n'
                '        cols: ["a", "b", "c", "d"]\n'
                '        rows: ["one"]\n'
                '        images: [["p.png", "q.png", "r.png", "s.png"]]\n'
                '    say: ["s"]\n')
        tmp = tempfile.mkdtemp(prefix="cm-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, spec)
            got = prose_audit.count_mismatch(prose_audit.read_slides(p))
            self.assertEqual(got, [], "a unit value was counted as a count: %r" % (got,))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_diffcheck_can_see_inside_figures(self):
        """A value drawn inside a figure is not in the PDF's text layer. Without reading the sidecar,
        all of it gets counted as "never used" -- five out of ten cases in blind trial 6 were exactly that."""
        with io.open(os.path.join(SCRIPTS, "diffcheck.py"), encoding="utf-8") as f_:
            src = f_.read()
        self.assertIn("--sidecar", src)
        self.assertIn("a.sidecar", src)


class SpokenSetSeesTheNotes(unittest.TestCase):
    """`unspoken_terms` reads `note` and `ko`, but `from_spec` never passed them through --
    a dead path that could never see them. A term explained in the note still got flagged as
    "never spoken"."""

    def test_note_and_ko_reach_the_slide_dict(self):
        import prose_audit
        spec = ('meta: {title: T, author: A, venue: V, date: D}\n'
                'slides:\n  - kind: content\n    title: "T"\n'
                '    bullets: ["one"]\n'
                '    note: "the stage direction"\n'
                '    ko: ["한국어 한 줄"]\n'
                '    say: ["spoken"]\n')
        tmp = tempfile.mkdtemp(prefix="nk-")
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, spec)
            sl = prose_audit.read_slides(p)[0]
            self.assertIn("note", sl)
            self.assertIn("ko", sl)
            self.assertTrue(any("stage direction" in x for x in sl["note"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ReasoningLeftBehind(unittest.TestCase):
    """What this skill watched for was numbers and shapes, and nothing else.

    `deckcheck` checks whether a number on screen is in the manuscript, `diffcheck` finds
    numbers from the manuscript that went unused, `refcheck` looks at the proportion of
    figures/tables/bullets, and `prose_audit` looks at speech patterns. None of them checked
    whether the deck carried over what the paper explained. So a deck could name a concept
    without explaining it and still pass all seven checks.

    A sentence a paper spends on a concept usually has no number in it -- something like
      "without a thermostat, the heater runs all night." `diffcheck` had the machinery, but its door
      only opened for numbers.
    """

    def _left(self, body, deck):
        import diffcheck
        return diffcheck.reasoning_left(body, diffcheck.words(deck), 9,
                                        diffcheck.sentences, diffcheck.words)

    def test_a_mechanism_sentence_the_deck_never_touched_is_named(self):
        body = ("We measure how long each greenhouse stays warm. "
                "Without the thermostat, the heater would run all night "
                "and the seedlings would scorch by morning. "
                "The table lists every greenhouse.")
        deck = "We measure how long each greenhouse stays warm, for every greenhouse."
        got = self._left(body, deck)
        self.assertEqual(len(got), 1)
        self.assertIn("scorch", got[0][0])

    def test_a_mechanism_the_deck_does_carry_is_not_named(self):
        body = ("Without the thermostat, the heater would run all night "
                "and the seedlings would scorch by morning.")
        deck = ("Without the thermostat the heater would run all night, "
                "and the seedlings would scorch by morning.")
        self.assertEqual(self._left(body, deck), [])

    def test_a_plain_measurement_sentence_is_not_named(self):
        """"What was measured" is not an explanation. Counting that too would bury the list."""
        body = ("We keep four greenhouses of twelve beds each. "
                "Each bed is watered at dawn.")
        self.assertEqual(self._left(body, "nothing at all here"), [])

    def test_a_definition_counts_as_reasoning(self):
        body = ("A star rating denotes the number of inspections that each "
                "kitchen has passed.")
        got = self._left(body, "we rate several kitchens")
        self.assertEqual(len(got), 1)

    def test_it_is_wired_into_the_report(self):
        with io.open(os.path.join(SCRIPTS, "diffcheck.py"), encoding="utf-8") as f_:
            src = f_.read()
        self.assertIn("reasoning_left(body", src)
        self.assertIn("explains", src)

    def test_it_says_whether_the_deck_already_covers_the_topic(self):
        """If the deck already talks about the topic but drops the mechanism, that isn't a choice.
        It must be told apart from dropping a topic the deck never touches at all -- otherwise both
        get lumped together as "up to the author to decide"."""
        body = ("Without the storm shutter, falling leaves would clog the gauge "
                "within the second week of autumn.")
        # the deck puts "storm shutter" on screen -> the mechanism was dropped
        hot = self._left(body, "the storm shutter column and the totals")
        self.assertEqual(len(hot), 1)
        self.assertTrue(hot[0][1], "the deck does cover the topic but this said it doesn't")
        # the deck doesn't touch the topic at all -> a choice
        cold = self._left(body, "a talk about something else entirely")
        self.assertEqual(len(cold), 1)
        self.assertFalse(cold[0][1], "the deck doesn't cover the topic but this said it does")



class TheDeckUsesThePapersWords(unittest.TestCase):
    """If the deck renames a term the paper explicitly named into its own words, an audience
    that has read the paper cannot connect the two. And the speaker has no idea they're renaming it.

    One blind trial turned up two such spots -- a term defined with denotes and a term named with
    called the ... were each called something different in the deck.

    Selecting by frequency is wrong -- generic words like `data`, `compared`, `close` would get
      mixed in. Looking only at spots where a name was explicitly assigned keeps it noise-free.
    """

    def _miss(self, body, deck):
        import diffcheck
        return diffcheck.named_terms_missing(body, deck, diffcheck.sentences)

    def test_a_name_the_deck_never_uses_is_reported(self):
        body = ("Each route is timed against the printed timetable, "
                "called the schedule. We then report the minutes late.")
        got = self._miss(body, "Everything is measured against the printed times.")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], "schedule")

    def test_a_name_the_deck_does_use_is_not_reported(self):
        body = ("Each route is timed against the printed timetable, "
                "called the schedule.")
        self.assertEqual(
            self._miss(body, "Minutes late against the schedule, per route."), [])

    def test_a_definition_by_denotes_is_caught(self):
        body = "Here a star rating denotes the number of inspections passed."
        got = self._miss(body, "the inspection results of each kitchen")
        self.assertEqual(len(got), 1)
        self.assertIn("inspections", got[0][0])

    def test_pronouns_are_not_treated_as_names(self):
        body = "We call it the same way throughout. We call this that."
        self.assertEqual(self._miss(body, ""), [])

    def test_frequency_alone_does_not_trigger_it(self):
        """A generic word is not a name, no matter how often the paper uses it."""
        body = ("We compared the data across every case. The data were "
                "compared again. Comparison of the data followed.")
        self.assertEqual(self._miss(body, "nothing in common"), [])

    def test_it_is_wired_into_the_report(self):
        with io.open(os.path.join(SCRIPTS, "diffcheck.py"), encoding="utf-8") as f_:
            src = f_.read()
        self.assertIn("named_terms_missing(body", src)
        self.assertIn("manuscript names", src)

class SuiteReachable(unittest.TestCase):
    """A test that never ran is not a test that passed.

    `if __name__ == "__main__": unittest.main()` was sitting in the middle of this file. The five
    test classes defined after it (`RefCheck`, `Charts`, `MathAcrossOutputs`, `Italic`,
    `NoGroundTruth`) had never once run -- yet the output said `OK`, and the docs listed three
    different test counts in three different places.

    This is the same failure mode as a checker "passing without looking at anything," so it gets
    blocked the same way, by a machine: the runner block must come after the last class.
    """

    def test_runner_block_comes_after_every_test_class(self):
        for name in ("test_build.py", "test_deckcheck.py"):
            src = deckspec.slurp(os.path.join(HERE, name))
            last_class = max((m.start() for m in
                              re.finditer(r"^class \w+\(unittest\.TestCase\)",
                                          src, re.M)), default=-1)
            runner = [m.start() for m in
                      re.finditer(r'^if __name__ == "__main__":', src, re.M)]
            self.assertEqual(len(runner), 1, "%s: there are %d runner blocks" % (name, len(runner)))
            self.assertGreater(runner[0], last_class,
                               "%s: test classes defined after the runner block never run" % name)


class EighthRoundComposition(unittest.TestCase):
    """Composition -- what turned up from placing one example deck alongside it and comparing
    page by page.

    These weren't found by counting, they were found by looking, and what was seen got turned
    into a rule. Without turning it into a rule, it quietly disappears on the next round of edits --
    this repository has already had that happen twice.
    """

    def _diagram(self, d, slot=(5.51, 2.44)):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="er-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "d.png")
        warn = []
        build_figs.draw_diagram(d, p, slot, warn)
        return p, warn

    # ── an empty box with nothing inside ─────────────────────────────────

    def test_a_box_left_empty_beside_full_ones_is_drawn_low_not_nagged(self):
        """When neighboring boxes show what's inside and only one is empty, it becomes **one big blank
        rectangle.**

        This is the spot where the user asked what that empty space was meant to be used for.
        Warning about it made an agent invent contents that weren't there (blind trial 8) -- now a
          shorter box holding only the label is drawn centered in the row, and nothing is said about it.
        """
        import build_figs
        seen = []
        real = build_figs._round

        def spy(ax, x, y, w, h, *a, **k):
            if k.get("zorder") == 2:
                seen.append((y, h))
            return real(ax, x, y, w, h, *a, **k)
        with mock.patch.object(build_figs, "_round", spy):
            _p, warn = self._diagram({
                "kind": "pipeline",
                "rows": [{"stages": [
                    {"label": "sorter", "inner": ["Bin 1", "Bin N"]},
                    {"label": "packer"}]}]})
        self.assertEqual([w for w in warn if "\ube48 \uc0c1\uc790" in w], [])
        (y0, h0), (y1, h1) = seen[:2]
        self.assertLess(h1, h0 * 0.8)                     # shorter
        self.assertAlmostEqual(y1 + h1 / 2, y0 + h0 / 2, places=3)   # centered

    def test_boxes_that_are_all_empty_are_not_nagged(self):
        """If everything is empty, that's just a plain stage diagram. A false positive erases a feature."""
        _p, warn = self._diagram({
            "kind": "pipeline",
            "rows": [{"stages": [{"label": "sorter"}, {"label": "packer"}]}]})
        self.assertEqual([w for w in warn if "\ube48 \uc0c1\uc790" in w], [])

    # ── a thin figure ─────────────────────────────────────

    def test_a_thin_figure_is_told_a_way_out_its_own_kind_can_take(self):
        """Telling a figure that is already `pipeline` to "draw it as `kind: pipeline`" is just nagging.

        Pointing out a problem without giving a way forward is nagging -- a failure this repository has
        repeated four times.
        """
        import build_figs
        tmp = tempfile.mkdtemp(prefix="uf-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "d.png")
        build_figs.draw_diagram(
            {"kind": "pipeline", "rows": [{"stages": [{"label": "a"}]}]},
            p, (5.51, 2.44), [])
        warn = []
        build_figs.underfill(p, (5.51, 2.44), "d.png", warn, "pipeline")
        self.assertEqual(len(warn), 1, warn)
        self.assertIn("feed", warn[0])
        self.assertNotIn("kind: pipeline", warn[0])

    def test_a_figure_that_fills_its_page_is_left_alone(self):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="uf2-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "d.png")
        rows = [{"label": "M%d" % i, "cells": [{"label": "W", "span": 8}],
                 "sub": "a row", "note": "a note about the row"}
                for i in range(4)]
        build_figs.draw_diagram({"kind": "strip", "rows": rows}, p,
                                (5.51, 2.44), [])
        warn = []
        build_figs.underfill(p, (5.51, 2.44), "d.png", warn, "strip")
        self.assertEqual(warn, [])

    # ── the gap between rows ─────────────────────────────────

    def test_strip_rows_are_separated_by_empty_bands(self):
        """The gap between rows must stay empty for them to read as separate rows.

        It used to lay a background card behind each row and butt those cards up against each other.
        That made the gap inside a row (group band -> bar) bigger than the gap between rows, so the
        "per 5" band read as grouped with the bar of the row above it, not its own -- this is
        exactly what the user meant by "the figure is completely broken." There is only one
        mechanism for grouping (`design.py` §7).
        """
        from PIL import Image
        p, _w = self._diagram({"kind": "strip", "rows": [
            {"label": "one", "bars": 15, "groups": [5, 5, 5],
             "group_label": "per 5"},
            {"label": "two", "bars": 12, "groups": [12],
             "group_label": "all"},
            {"label": "three", "bars": 9, "groups": [3, 3, 3],
             "group_label": "per 3"}]})
        with Image.open(p) as im:
            a = im.convert("RGBA")
            w, h = a.size
            px = a.load()
            blank = [y for y in range(h)
                     if all(px[x, y][3] == 0 for x in range(0, w, 3))]
        # with three rows, there must be at least two empty bands between them.
        # (the margins above and below merge into one run each, so runs are counted, not raw pixels.)
        runs, prev = 0, -9
        for y in blank:
            if y != prev + 1:
                runs += 1
            prev = y
        self.assertGreaterEqual(runs, 3, "%d empty-band runs" % runs)

    # ── composing row height by addition ────────────────────────────

    def test_a_row_caption_costs_a_caption_not_a_row(self):
        """Row height used to be `things standing outside the box / (1 - 0.72)`.

        Adding one line of caption (0.22 inches) made the row grow by 0.78 inches, leaving the box
        that much emptier. Now a row is box + things standing outside it + margin.
        """
        from PIL import Image

        def tall(cap):
            row = {"label": "M", "stages": [
                {"label": "a", "count": "1", "inner": ["x", "y"]},
                {"label": "b", "count": "2", "inner": ["x", "y"]}]}
            if cap:
                row["caption"] = "a caption line for the row"
            p, _w = self._diagram({"kind": "pipeline", "rows": [row]})
            with Image.open(p) as im:
                return im.size[1] / 200.0

        self.assertLess(tall(True) - tall(False), 0.35)

    # ── typeface ────────────────────────────────────────

    def test_figures_use_the_same_typeface_as_the_deck(self):
        """If the same pt renders at a different apparent size, "figure text is smaller than body text"
        only holds on paper as a number. The deck used `lmodern`, the figures used DejaVu --
        not on one page, but in every figure on every page.
        """
        import build_figs
        import matplotlib
        fam = matplotlib.rcParams["font.family"]
        self.assertIsInstance(fam, list)
        self.assertEqual(fam[0], build_figs.design.font_family())
        # if it can't be found, this reports it in one line -- it does not silently fall back to another font.
        if fam[0] == build_figs.design.FALLBACK_FAMILY:
            self.assertTrue(build_figs.FONT_NOTE)


class NinthRoundMeaning(unittest.TestCase):
    """An asterisk printed on screen, a figure that couldn't carry its meaning, and an impact
    slide asking a different question. All three, while ten checkers all printed pass.
    """

    # ── markup printing as literal characters ──────────────────────────

    def test_markup_inside_markup_is_resolved(self):
        """The inner asterisks in `<safe>... *still* ...</safe>` printed as literal characters on screen.

        Resolving only the outer layer of markup has been the case for a long time, and it never
        surfaced because nobody had ever nested one kind of markup inside another.
        """
        import build_deck
        import deckspec
        got = build_deck.fmt("<safe>the gauge *still* reads</safe>")
        self.assertNotIn("*", got)
        self.assertIn("emph{still}", got)
        self.assertNotIn("*", deckspec.plain("<hit>a **b** c</hit>"))

    def test_a_one_line_impact_slide_resolves_its_markup(self):
        """Only when `big` was a single line of text did it skip `fmt`, letting `**shape**` print as-is."""
        import build_deck
        got = "\n".join(build_deck.big_body(
            {"big": "Board the **first** bus that comes."}))
        self.assertNotIn("**", got)
        self.assertIn("textbf{first}", got)

    def test_outcheck_reports_markup_that_reached_the_screen(self):
        """The checkers looked only at the spec and never at the text in the actual output, so this
        was missed.

        And searching against the normalized version would always return zero -- because `norm` runs
        through `strip_markup`, which strips out the exact markup being searched for.
        """
        import outcheck
        got = outcheck.markup_leaks({"deck": "a **b** c and *d* and <hit>e</hit>"})
        self.assertEqual(len(got), 3, got)
        self.assertEqual(outcheck.markup_leaks({"deck": "2*3 = 6, a*b"}), [])

    # ── arrows ───────────────────────────────────────────

    def test_typed_arrows_become_real_arrows(self):
        """Telling whoever writes the spec to "just type → directly" is nagging -- it isn't on a keyboard."""
        import deckspec
        self.assertEqual(deckspec.arrows("a -> b"), "a \u2192 b")
        self.assertEqual(deckspec.arrows("a --> b"), "a \u2192 b")
        self.assertEqual(deckspec.arrows("a <- b"), "a \u2190 b")
        # subtraction and inequality signs are left untouched
        self.assertEqual(deckspec.arrows("3 - 2 > 0"), "3 - 2 > 0")

    # ── does the figure carry its meaning ──────────────────────────────

    def test_rows_that_differ_only_in_grouping_must_say_what_changed(self):
        """If the bars are identical row to row and only the grouping differs, the meaning lives only
        in the band's width.

        The viewer has to count that width, and a talk gives them no time to.
        """
        import build_figs
        tmp = tempfile.mkdtemp(prefix="nr-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = [{"label": "a", "bars": 12, "groups": [6, 6], "mark_at": 5},
                {"label": "b", "bars": 12, "groups": [2, 2, 2, 2, 2, 2],
                 "mark_at": 5}]
        warn = []
        build_figs.draw_diagram({"kind": "strip", "rows": rows},
                                os.path.join(tmp, "a.png"), (5.51, 2.44), warn)
        self.assertTrue([w for w in warn if "only the grouping" in w], warn)
        # writing one line of note per row quiets it
        for i, r in enumerate(rows):
            r["note"] = "row %d pairs up" % i
        warn = []
        build_figs.draw_diagram({"kind": "strip", "rows": rows},
                                os.path.join(tmp, "b.png"), (5.51, 2.44), warn)
        self.assertEqual([w for w in warn if "only the grouping" in w], [])

    # ── does the impact slide serve the thesis ───────────────────────

    def test_an_impact_slide_that_asks_a_different_question_is_named(self):
        """An impact slide is the talk's climax. If it asks something other than what the paper is
        trying to say, every slide after it ends up answering that different question instead, and the
        thesis gets sidestepped. This is exactly what the user pointed at.
        """
        import prose_audit as pa
        slides = [
            {"n": 3, "kind": "standout", "title": "morning or evening",
             "lead": "", "screen": ""},
            {"n": 9, "kind": "standout", "title": "bus lanes and signal timing",
             "lead": "", "screen": ""},
        ]
        thesis = "Shorten the trip with bus lanes and signal timing"
        off = [x for x in pa.standouts_off_thesis(slides, thesis)
               if len(x[1]) < 2]
        self.assertEqual([x[0] for x in off], [3], off)

    def test_the_thesis_falls_back_to_the_closing_impact_slide(self):
        """Not writing `meta.thesis` doesn't mean giving up the check -- the thesis often lands on the
        final impact slide."""
        import prose_audit as pa
        slides = [{"n": 3, "kind": "standout", "title": "first"},
                  {"n": 9, "kind": "standout", "title": "the real claim"}]
        got, src = pa.thesis_of({}, slides)
        self.assertEqual(got, "the real claim")
        self.assertIn("standout", src)
        got, src = pa.thesis_of({"thesis": "written down"}, slides)
        self.assertEqual((got, src), ("written down", "meta.thesis"))

    def test_big_is_read_as_text_not_as_a_data_structure(self):
        """If a checker dumps the spec's raw data structure onto the screen, whoever reads it can't tell
        what the actual problem is. And `value`/`label` end up counted as ordinary words."""
        import prose_audit as pa
        got = pa.big_text([{"value": "the route", "label": "where a bus can go"},
                           {"value": "the timetable"}])
        self.assertNotIn("{", got)
        self.assertIn("the route", got)
        self.assertIn("the timetable", got)


class TenthRoundItsPaperWords(unittest.TestCase):
    """Numbers were checked against the manuscript, but wording was never checked, not once.

    The first place a talk drifts from its paper isn't a number, it's a name that got reworded for
    the talk. This project's own paper side already had the same rule -- "no coinages: replace
    any word absent from all 8 papers in `ref/` with the field's own term." Only the deck was missing it.
    """

    def test_a_word_the_deck_leans_on_but_the_paper_never_uses(self):
        import deckcheck
        deck = ("pruning the rows is pruning the model, and pruning again "
                "keeps the entries aligned")
        paper = "we remove rows by structured sparsity; the entries stay aligned"
        got = dict(deckcheck.coined_terms(deck, paper, 3))
        self.assertIn("pruning", got)
        self.assertEqual(got["pruning"], 3)
        self.assertNotIn("entries", got)      # it's in the manuscript
        self.assertNotIn("rows", got)

    def test_one_or_two_uses_are_not_the_decks_working_vocabulary(self):
        """Once or twice could just be a connecting word. A false positive erases a feature."""
        import deckcheck
        got = dict(deckcheck.coined_terms("a gadget here and a gadget there",
                                          "nothing like it", 3))
        self.assertEqual(got, {})

    def test_the_word_and_its_inflections_count_as_one(self):
        """`per-bed` and `per bed`, `water` and `watered` are the same word. Otherwise the list fills
        up with mere spelling differences, and then nobody reads it."""
        import deckcheck
        self.assertEqual(deckcheck.fold("per-bed"), deckcheck.fold("perbed"))
        self.assertEqual(deckcheck.fold("irrigated"), deckcheck.fold("irrigate"))
        got = dict(deckcheck.coined_terms(
            "per-bed here, per-bed there, per-bed everywhere",
            "we use per bed watering", 3))
        self.assertEqual(got, {})

    def test_machine_words_are_not_counted_as_the_decks_vocabulary(self):
        """Command names, environment names, color names, comments -- none of these are words the
        audience hears.

        Running it without filtering them out, 14 of 19 flagged terms were `frame`, `itemize`,
        `textcolor`. If a checker's first line of output is garbage, nobody reads the second line.
        """
        import deckcheck
        src = ("%% frametitle in a comment" + chr(10)
               + chr(92) + "begin{frame}{Real words here}" + chr(10)
               + chr(92) + "textcolor{mSafe}{Real words here} Real words here"
               + chr(10) + chr(92) + "end{frame}")
        got = deckcheck.term_text(src, "latex")
        for machine in ("frame", "frametitle", "textcolor", "mSafe", "begin"):
            self.assertNotIn(machine, got, machine)
        self.assertIn("Real words here", got)

    def test_the_sidecar_figure_id_is_not_a_word(self):
        import deckcheck
        got = deckcheck.sidecar_text(
            "# a comment" + chr(10) + "fig_x" + chr(9) + "Intake"
            + chr(9) + "-38.6")
        self.assertNotIn("fig_x", got)
        self.assertIn("Intake", got)

    def test_a_spec_that_names_no_paper_is_told_so(self):
        """A deck that points at no manuscript is a deck that has never been cross-checked.

        The user was left with no choice but to ask "which paper am I even looking at right now?" and
        that wasn't the speaker's fault, it was a gap in the skill.
        """
        import prose_audit as pa
        got, why = pa.paper_text({}, "x.yaml")
        self.assertIsNone(got)
        self.assertIn("meta.paper", why)

    def test_a_named_paper_is_read_relative_to_the_spec(self):
        """The path is resolved relative to the spec file -- a checker whose result changes
        depending on where you run it from is worse than not running it at all."""
        import prose_audit as pa
        tmp = tempfile.mkdtemp(prefix="pw-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "paper"))
        with io.open(os.path.join(tmp, "paper", "p.tex"), "w",
                     encoding="utf-8") as f:
            f.write("structured sparsity and entries")
        got, why = pa.paper_text({"paper": "paper/p.tex"},
                                 os.path.join(tmp, "slides.yaml"))
        self.assertIn("structured", got)
        self.assertEqual(why, "")


class EleventhRoundMeasureThenFix(unittest.TestCase):
    """LaTeX had already written "this slide overflowed by 18pt" into the log. Nobody read it.

    The last line of four overflowing slides got pushed down as far as the page-number line, and ten
    checkers all printed pass. `fitcheck` measures only the page boundary, not where the body
    text actually sits.
    """

    def _log(self, body, tex=""):
        tmp = tempfile.mkdtemp(prefix="ov-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with io.open(os.path.join(tmp, "talk.log"), "w", encoding="latin-1") as f:
            f.write(body)
        if tex:
            with io.open(os.path.join(tmp, "talk.tex"), "w", encoding="utf-8") as f:
                f.write(tex)
        return os.path.join(tmp, "talk.pdf")

    def test_overflow_is_read_from_the_log_and_pinned_to_its_page(self):
        import deckspec
        pdf = self._log(
            "Overfull " + chr(92) + "vbox (13.8pt too high) detected at line 47"
            + chr(10) + "[1{x.map}]" + chr(10) + "[2]" + chr(10) + "[3 <./figs/a.png>]" + chr(10)
            + "Overfull " + chr(92) + "vbox (18.3pt too high) detected at line 90" + chr(10) + "[4]",
            tex=chr(92) + "maketitle")
        # the title page (1) overflows because of the theme itself -- excluded. The wide one is page 4.
        self.assertEqual(deckspec.log_overfull(pdf), [(4, 18.3)])

    def test_small_overflow_like_a_finished_decks_is_not_reported(self):
        """A content slide's overflow in one example deck came to only a few pt and was invisible once
        projected. Nobody trusts a check that flags a well-made deck."""
        import deckspec
        pdf = self._log("[1]" + chr(10) + "Overfull " + chr(92) + "vbox (5.7pt too high) detected")
        self.assertEqual(deckspec.log_overfull(pdf), [])

    def test_no_log_means_not_measured_not_fine(self):
        """No log means None -- that's "couldn't be measured," not "didn't overflow"."""
        import deckspec
        self.assertIsNone(deckspec.log_overfull(
            os.path.join(tempfile.gettempdir(), "no-such-deck.pdf")))

    def test_the_overflow_is_fed_back_into_that_slides_figure(self):
        """Fixed by measuring, not by hammering in another guessed constant. A figure is the one
        thing on a slide that can grow or shrink, so the overflow amount just gets subtracted from that
        slide's figure."""
        import deckspec
        pdf = self._log("[1]" + chr(10) + "[2]" + chr(10)
                        + "Overfull " + chr(92) + "vbox (14.4pt too high) detected" + chr(10) + "[3]")
        slides = [{"n": 1}, {"n": 2}, {"n": 3}]
        deckspec.EXTRA_RESERVE.clear()
        self.addCleanup(deckspec.EXTRA_RESERVE.clear)
        before = deckspec.fig_reserve({"n": 3, "foot": ["x"]}, "self")
        got = deckspec.fit_from_log(pdf, slides)
        self.assertIn(3, got)
        self.assertGreater(got[3], 14.4 / 72.0)
        after = deckspec.fig_reserve({"n": 3, "foot": ["x"]}, "self")
        self.assertAlmostEqual(after - before, got[3], places=3)
        # other slides are left untouched
        self.assertEqual(deckspec.fig_reserve({"n": 2}, "self"), 0.0)

    def test_a_windows_figure_path_does_not_become_a_latex_command(self):
        """`out` + backslash + `figs` turned into an undefined command: a backslash right before `figs`."""
        import build_deck
        tmp = tempfile.mkdtemp(prefix="gp-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        spec = os.path.join(tmp, "s.yaml")
        deckspec_mod = __import__("deckspec")
        deckspec_mod.spit(spec, "meta: {title: T, author: A, venue: V, date: D}" + chr(10)
                          + "slides:" + chr(10) + "  - title: X" + chr(10) + "    bullets: [a]" + chr(10))
        out = os.path.join(tmp, "talk.tex")
        build_deck.build(spec, out, "out" + chr(92) + "figs")
        with io.open(out, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("graphicspath{{out/figs/}}", src)
        self.assertNotIn("out" + chr(92) + "figs", src)

    def test_pptx_resolves_markup_inside_markup(self):
        """The same defect that was fixed in the deck was still sitting in the PPTX.
        "When a feature goes into one builder, add it to the others in the same pass" -- a rule this
        skill wrote down itself."""
        try:
            from pptx import Presentation
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx
        prs = Presentation()
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        tb = sl.shapes.add_textbox(0, 0, 100, 100)
        p = tb.text_frame.paragraphs[0]
        build_pptx.add_runs(p, "<safe>the gauge *still* reads</safe>",
                            12, build_pptx.SAFE)
        text = "".join(r.text for r in p.runs)
        self.assertNotIn("*", text)
        italic = [r for r in p.runs if r.text == "still"]
        self.assertEqual(len(italic), 1)
        self.assertTrue(italic[0].font.italic)
        self.assertEqual(italic[0].font.color.rgb, build_pptx.SAFE)


class TwelfthRoundInsideTheFigure(unittest.TestCase):
    """`fitcheck` cannot see overlap inside a PNG. Right before saving, matplotlib still knows
    every piece of text's position, so that's where this looks."""

    ROWS = {"header": ["", "one", "two"],
            "rows": [["North", "-2.85", "-12.4"], ["East", "-8.7", "-6.35"],
                     ["South", "+0.0", "-15.9"], ["West", "-11.05", "-7.45"]]}

    def _bars(self, slot=(5.51, 2.44), **kw):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="tw-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        build_figs.draw_bars(self.ROWS, os.path.join(tmp, "b.png"), None, "dT",
                             kw.get("note"), slot, warn, kw.get("callout"), None)
        return warn

    def test_a_callout_moves_off_the_value_it_would_cover(self):
        """A callout label was covering `+0.0`, and this used to pass with "0 warnings." Dodging it by
        guesswork failed; only dodging it by measurement made the overlap disappear."""
        warn = self._bars(callout={"at": "South",
                                   "text": "THE GAP CLOSES RIGHT HERE"})
        self.assertEqual([w for w in warn if "overlap" in w], [], warn)

    def test_a_short_figure_keeps_legend_and_note_apart(self):
        """Because the bottom margin was a fraction of the canvas, the legend sank onto the note in
        a short figure. Anything whose height is fixed in pt gets measured in inches instead."""
        for h in (2.44, 1.8, 1.5):
            warn = self._bars(slot=(5.51, h), note="Model A. A note under it.")
            self.assertEqual([w for w in warn if "overlap" in w], [],
                             "%s in: %r" % (h, warn))

    def test_overlap_inside_a_figure_is_reported(self):
        """Is the check itself alive -- deliberately overlapping two pieces of text must get
        caught. A check that can't catch this is a dead check (the same reason `deckcheck --selftest`
        exists)."""
        import build_figs
        import matplotlib.pyplot as plt
        tmp = tempfile.mkdtemp(prefix="ol-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        fig = plt.figure(figsize=(3, 1))
        fig.text(0.1, 0.5, "first words here", fontsize=10)
        fig.text(0.12, 0.52, "second words", fontsize=10)
        warn = []
        build_figs.save_fig(fig, os.path.join(tmp, "o.png"), [], warn, "o.png")
        self.assertTrue([w for w in warn if "overlap" in w], warn)

    def test_text_columns_align_left_and_numbers_right(self):
        """Hardcoding only the first column as l and the rest as r pushed a text column flush right, so
        each row's starting point became ragged. A dash marks a numeric cell with no value."""
        import deckspec
        rows = [["Shop A", "bakery", "+3.3", "\u2014"],
                ["Shop B", "florist", "<hit>-23.9</hit>", "3.1"],
                ["Shop C", "grocer", "$-1.9$", "12%"]]
        self.assertEqual(deckspec.column_align(rows), "llrr")

    def test_build_prints_what_the_builders_found(self):
        """Consolidating everything into one command and calling `build()` meant not one figure
        warning printed. Building a check and then discarding its output is worse than having no check."""
        import build
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            got = build._say("figures", ["a.png: something is off"])
        self.assertEqual(got, ["a.png: something is off"])
        self.assertIn("something is off", buf.getvalue())


class EighthBlindTrialWrongOutputs(unittest.TestCase):
    """Wrong output found by blind trial 8. All of it was on screen while the checkers printed pass."""

    def _png(self, tmp, name, w, h):
        from PIL import Image
        p = os.path.join(tmp, name)
        Image.new("RGB", (w, h), (120, 120, 120)).save(p)
        return p

    def _deck(self, spec_text):
        import build_deck
        tmp = tempfile.mkdtemp(prefix="a8-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for n in ("a.png", "b.png"):
            self._png(tmp, n, 400, 400)
        sp = os.path.join(tmp, "s.yaml")
        __import__("deckspec").spit(sp, spec_text)
        out = os.path.join(tmp, "talk.tex")
        build_deck.build(sp, out, tmp)
        with io.open(out, encoding="utf-8") as f:
            return f.read(), tmp, sp

    GRID = ('meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: figure\n    title: "Grid"\n'
            '    lead: "A lead sentence that takes one line on the slide."\n'
            '    foot: ["A foot line under the grid."]\n'
            '    figure:\n      grid:\n'
            '        cols: ["one", "two"]\n        rows: ["start", "end"]\n'
            '        images:\n          - [a.png, b.png]\n          - [a.png, b.png]\n'
            '        mark: [ok, fail]\n'
            '        caption: ["fine", "a much longer caption for this column"]\n'
            '    say: ["s"]\n')

    def test_grid_rows_are_sized_in_inches_not_fraction_minus_inches(self):
        """Subtracting inches from a fraction (0.86) turned the grid on a slide with `lead`/`foot` into a thumbnail."""
        src, _, _ = self._deck(self.GRID)
        m = re.search(r"max height=([0-9.]+)" + chr(92) * 2 + "textheight", src)
        self.assertIsNotNone(m, src[:400])
        self.assertGreater(float(m.group(1)), 0.2)     # two rows -- one row is nearly half the body

    def test_grid_columns_are_fixed_and_images_fill_their_cell(self):
        """The longest caption set the column width, and giving an image `cw` inside `m{}` makes it a
        part of the cell -- inside a cell, the entire cell width is used."""
        src, _, _ = self._deck(self.GRID)
        self.assertIn(chr(92) + "centering" + chr(92) + "arraybackslash}m{", src)
        self.assertIn("max width=" + chr(92) + "linewidth,max height=", src)
        self.assertIn(chr(92) + "usepackage{array}", src)

    def test_pptx_draws_a_grid_inside_a_pane_and_keeps_the_aspect(self):
        """A grid inside a pane crashed with `KeyError: 'path'`, and without importing PIL, **every
        figure** got stretched to 4:3 (because `except Exception` was swallowing the `NameError`)."""
        try:
            from pptx import Presentation
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx
        _, tmp, sp = self._deck(
            'meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - title: "Pane grid"\n'
            '    left: {text: "Left side words."}\n'
            '    right:\n      figure:\n        grid:\n'
            '          images:\n            - [a.png, b.png]\n'
            '          mark: [ok, fail]\n    say: ["s"]\n')
        out = os.path.join(tmp, "talk.pptx")
        build_pptx.build(sp, out, tmp)
        pics = [s for s in Presentation(out).slides[0].shapes
                if s.shape_type == 13]
        self.assertEqual(len(pics), 2)
        for s in pics:
            self.assertAlmostEqual(s.width / float(s.height), 1.0, places=2)

    def test_pptx_text_height_counts_wrapped_lines(self):
        """Counting one bullet as a single 0.34in line meant the next chunk printed on top of the wrapped bullet."""
        import build_pptx
        long = ["word " * 40]
        self.assertGreater(build_pptx.text_h(long, 2.5, 16),
                           2.5 * build_pptx.text_h(["word"], 2.5, 16))
        self.assertGreater(build_pptx.text_h(long, 2.0, 16),
                           build_pptx.text_h(long, 6.0, 16))

    def test_bar_series_never_use_the_verdict_colours(self):
        """The second series was "bad" red -- even the fine bars read as bad."""
        import design
        banned = {c.lower() for c in design.ROLES["hit"] + design.ROLES["safe"]}
        banned |= {design.text_of("hit").lower(), design.text_of("safe").lower(),
                   "#c0392b"}
        for c in design.SERIES:
            self.assertNotIn(c.lower(), banned, c)

    def test_bars_in_a_narrow_pane_are_not_clipped(self):
        """In a narrow pane, the vertical axis label, legend, and conclusion used to get clipped with no warning."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="nb-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        build_figs.draw_bars(
            {"header": ["", "front bed", "back bed"],
             "rows": [["no shade", "-13.3", "-15.3"],
                      ["late water", "-5.9", "-8.2"],
                      ["no mulch", "-31.9", "-32.4"]]},
            os.path.join(tmp, "b.png"), None, "loss (percent)", None,
            (3.0, 2.2), warn, None,
            "Beds without mulch dry out first, front or back.")
        bad = [w for w in warn if "clipped at the figure's edge" in w or "clipped outside the figure" in w]
        self.assertEqual(bad, [], warn)

    def test_partly_clipped_text_is_reported(self):
        """Is the check alive -- back when it only looked for more than half sticking out, this went uncaught."""
        import build_figs
        import matplotlib.pyplot as plt
        tmp = tempfile.mkdtemp(prefix="pc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        fig = plt.figure(figsize=(3, 1))
        fig.text(0.9, 0.5, "this sentence runs off the right edge", fontsize=10)
        warn = []
        build_figs.save_fig(fig, os.path.join(tmp, "o.png"), [], warn, "o.png")
        self.assertTrue([w for w in warn if "clipped at the figure's edge" in w], warn)


class EighthBlindTrialMore(unittest.TestCase):

    def test_a_table_inside_the_chart_is_drawn(self):
        """`panels[].table` was read while `chart.table` was silently ignored, inserting a missing box --
        even though the spec clearly stated where the table was."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="ct-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        sp = os.path.join(tmp, "s.yaml")
        __import__("deckspec").spit(sp, (
            'meta: {title: T, author: A, venue: V, date: D}\n'
            'slides:\n  - kind: figure\n    title: "Inline"\n'
            '    chart:\n      kind: tiles\n      table:\n'
            '        header: ["", "hot", "cool"]\n'
            '        rows:\n          - ["dry", "-27.5", "-1.2"]\n'
            '          - ["wet", "-9.3", "-0.4"]\n    say: ["s"]\n'))
        made, lines, warn = build_figs.build(sp, os.path.join(tmp, "figs"))
        self.assertEqual(len(made), 1, warn)
        self.assertFalse([w for w in warn if "no table" in w], warn)

    def test_paired_impact_values_share_one_size_and_stay_inside(self):
        """Sizing each value separately made "range" small and "4 pumps" large, and when the word in
        the middle was long, the right-hand value got cropped off the page."""
        import build_deck
        got = "\n".join(build_deck.big_body({
            "big": [{"value": "range"}, {"value": "4 pumps"}],
            "gap": "a rather long sentence that sits between the two values"}))
        sizes = set(re.findall(r"fontsize\{(\d+)\}", got))
        self.assertEqual(len(sizes), 1, sizes)
        self.assertIn("adjustbox{max width=" + chr(92) + "textwidth}", got)




class EighthBlindTrialPptxText(unittest.TestCase):
    """Blind trial 8, item 30 -- no check had caught text overlapping text in the PPTX."""

    def _deck(self, boxes):
        from pptx import Presentation
        from pptx.util import Inches, Pt
        tmp = tempfile.mkdtemp(prefix="px-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        for (x, y, w, h, text, pt) in boxes:
            tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
            tb.text_frame.word_wrap = True
            for i, line in enumerate(text if isinstance(text, list) else [text]):
                p = tb.text_frame.paragraphs[0] if i == 0 else tb.text_frame.add_paragraph()
                r = p.add_run()
                r.text = line
                r.font.size = Pt(pt)
        p = os.path.join(tmp, "t.pptx")
        prs.save(p)
        return p

    def _hits(self, p):
        sys.path.insert(0, SCRIPTS)
        import fitcheck
        return [b for b in fitcheck.check_pptx(p) if u"overlap by" in b[2]]

    def test_bullets_that_wrap_into_the_box_below_are_caught(self):
        """The bullet frame is sized for one line, but the text wraps to three and covers the text box below it."""
        long = "a claim that runs well past the width of a narrow column " * 2
        p = self._deck([(0.6, 1.6, 4.0, 0.34, [long, long], 18),
                        (0.6, 2.0, 4.0, 0.6, "the text box under the bullets", 18)])
        self.assertEqual(len(self._hits(p)), 1)

    def test_generous_frames_around_short_text_are_not_overlaps(self):
        """If the frames overlap but the text itself never touches, this stays quiet -- a false positive erases a feature."""
        p = self._deck([(0.6, 1.6, 6.0, 2.0, "short", 18),
                        (0.6, 2.6, 6.0, 2.0, "also short", 18)])
        self.assertEqual(self._hits(p), [])

    def test_text_that_spills_off_the_slide_is_caught_even_in_a_frame_that_fits(self):
        """PowerPoint does not clip overflowing text. A footnote has actually run off the bottom of the slide before."""
        sys.path.insert(0, SCRIPTS)
        import fitcheck
        long = "footnote text that keeps going " * 30
        p = self._deck([(0.6, 6.6, 12.0, 0.8, long, 18)])
        self.assertTrue([b for b in fitcheck.check_pptx(p)
                         if b[1] == u"off the page"])


class EighthBlindTrialFitNoise(unittest.TestCase):
    """Blind trial 8, item 28 -- `fitcheck`'s defaults flagged 42 pages on the theme alone."""

    def _pdf(self):
        import fitz
        tmp = tempfile.mkdtemp(prefix="fn-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        d = fitz.open()
        for k in range(3):
            pg = d.new_page(width=454, height=255)
            # text sitting at the edge, like a theme's title band
            pg.insert_text((6, 14), "Title band text", fontsize=14)
            for i in range(8):
                pg.insert_text((40, 60 + 18 * i), "body line %d of the slide" % i,
                               fontsize=10)
            if k == 1:
                pg.insert_text((40, 235), "fine print far smaller", fontsize=5)
        p = os.path.join(tmp, "t.pdf")
        d.save(p)
        return p

    def test_defaults_flag_only_text_clearly_smaller_than_the_body(self):
        sys.path.insert(0, SCRIPTS)
        import fitcheck
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fitcheck.main([self._pdf(), "--contrast", "0"])
        out = buf.getvalue()
        self.assertRegex(out, r"margin\s+0 page\(s\)")
        self.assertRegex(out, r"small text\s+1 page\(s\)")


class EighthBlindTrialSymbols(unittest.TestCase):
    """Blind trial 8, item 9 -- scaffold mangled the paper's symbols, and esc escaped its own braces."""

    def test_dagger_and_double_dagger_stay_distinct(self):
        """Both † and ‡ became `^`, erasing the distinct meaning of the two marks."""
        sys.path.insert(0, SCRIPTS)
        import scaffold
        D, B = "$", "\\"
        got = scaffold.clean("per-day" + D + "^" + B + "dagger" + D
                             + " and weekly" + D + "^" + B + "ddagger" + D)
        self.assertIn(u"\u2020", got)
        self.assertIn(u"\u2021", got)
        self.assertNotIn("^", got)
        self.assertEqual(scaffold.clean(D + B + "Delta" + D + "T"), u"\u0394T")

    def test_the_symbols_scaffold_writes_come_out_as_latex(self):
        sys.path.insert(0, SCRIPTS)
        import build_deck
        self.assertIn(r"\textdagger{}", build_deck.esc(u"x\u2020"))
        self.assertIn(r"$^{-4}$", build_deck.esc(u"p < 10\u207b\u2074"))

    def test_an_ellipsis_does_not_print_its_own_braces(self):
        """Substituting the symbol before escaping produced `\\ldots\\{\\}` -- "...{}" on screen."""
        sys.path.insert(0, SCRIPTS)
        import build_deck
        self.assertEqual(build_deck.esc(u"wait\u2026 then"), r"wait\ldots{} then")


class EighthBlindTrialYamlEscape(unittest.TestCase):
    """Blind trial 8, item 10 -- the `\\t` in `"0.19\\textheight"` silently became a tab."""

    def _load(self, text):
        sys.path.insert(0, SCRIPTS)
        import deckspec
        tmp = tempfile.mkdtemp(prefix="ye-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "slides.yaml")
        with io.open(p, "w", encoding="utf-8") as f_:
            f_.write(text)
        return deckspec.load(p)

    def test_a_tab_eaten_from_textheight_names_the_key(self):
        bs = chr(92)
        with self.assertRaises(ValueError) as cm:
            self._load('slides:\n- title: A\n  figure: {path: a.png, max_height: "0.19'
                       + bs + 'textheight"}\n')
        self.assertIn("max_height", str(cm.exception))

    def test_single_quotes_keep_the_backslash(self):
        bs = chr(92)
        self._load("slides:\n- title: A\n  bullets: ['0.19" + bs + "textheight', '"
                   + bs + "nu is fine']\n")

    def test_a_newline_in_a_block_is_not_an_escape(self):
        self._load("slides:\n- title: A\n  note: |\n    one line\n    next line\n")

    def test_every_eaten_escape_is_named_at_once(self):
        """Trial 40 -- `\\r` used in two places used to be reported one at a time instead of all at once."""
        bs = chr(92)
        with self.assertRaises(ValueError) as cm:
            self._load('slides:\n- title: A\n  lead: "x ' + bs + 'rm y"\n'
                       '  bullets: ["a ' + bs + 'tau b"]\n')
        msg = str(cm.exception)
        self.assertIn("2", msg)
        self.assertIn("lead", msg)
        self.assertIn("bullets[0]", msg)


class EighthBlindTrialScriptLanguage(unittest.TestCase):
    """Blind trial 8, item 12 -- an English talk's script had "backup slide" and "anticipated question" hardcoded in it."""

    def test_language_follows_meta_then_the_speech(self):
        sys.path.insert(0, SCRIPTS)
        import build_script
        en = [{"say": ["We watered every bed at every hour."]}]
        ko = [{"say": [u"모든 화단에 매시간 물을 줬다."]}]
        self.assertEqual(build_script.script_lang({}, en), "en")
        self.assertEqual(build_script.script_lang({}, ko), "ko")
        self.assertEqual(build_script.script_lang({"lang": "ko"}, en), "ko")
        self.assertEqual(set(build_script.LABELS["en"]), set(build_script.LABELS["ko"]))


class ExampleDeckHeat(unittest.TestCase):
    """Rendering the example deck after fixing it to match the guidelines turned up two places where
    the heat grid was wrong."""

    def _heat(self, rows, slot=(5.5, 2.6)):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="ht-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return build_figs, build_figs.draw_heat(
            {"header": ["", "A", "B"], "rows": rows},
            os.path.join(tmp, "h.png"), slot=slot, warn=[])

    def test_a_small_grid_grows_into_spare_room(self):
        """A 3-row, 2-column grid used only a third of the body and sat there at 10pt."""
        bf, seen = self._heat([["x", "<hit>-1.0</hit>", "2"], ["y", "3", "4"]])
        self.assertGreater(max(pt for pt, _ in seen), bf.BODY_PT * 1.3)

    def test_a_crowded_grid_does_not_grow(self):
        bf, seen = self._heat([["x", "1", "2"]] * 9)
        self.assertLessEqual(max(pt for pt, _ in seen), bf.BODY_PT + 1.0)

    def test_the_hatch_does_not_cross_the_number(self):
        """The hatching used to cross straight through the white digits -- a matching-color plate is now laid behind the number."""
        import build_figs
        from matplotlib import pyplot as plt
        made = []
        real = plt.Rectangle

        def spy(*a, **k):
            r = real(*a, **k)
            made.append(k)
            return r
        with mock.patch.object(build_figs.plt, "Rectangle", spy), \
                mock.patch.object(deckspec, "SECOND_CHANNEL", True):
            self._heat([["x", "<hit>-1.0</hit>", "2"]])
        plates = [k for k in made if k.get("zorder") == 1.7]
        self.assertEqual(len(plates), 1)


class ExampleDeckPipeline(unittest.TestCase):
    """The example deck's pipeline slide -- there was empty space below, yet the text inside the box sat at 7.5pt."""

    SPEC = {"kind": "pipeline", "rows": [
        {"label": "A", "stages": [{"label": "cells"}, {"label": "charge"},
                                  {"label": "fades?", "inner": ["anode", "cathode", "separator"]}]},
        {"label": "B", "stages": [{"label": "cells"}, {"label": "pulse"},
                                  {"label": "fades?", "inner": ["anode", "cathode", "separator"]}]}]}

    def test_inner_rows_keep_their_size_when_there_is_room(self):
        """The measuring side counted one line as 1.0em, while the drawing side (`fit_text`) counted it as 1.26em."""
        import build_figs
        tmp = tempfile.mkdtemp(prefix="pi-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        seen = build_figs.draw_diagram(self.SPEC, os.path.join(tmp, "d.png"),
                                       (5.51, 2.6), warn)
        self.assertEqual([w for w in warn if "anode" in w], [])


class EighthBlindTrialScaffoldOrder(unittest.TestCase):
    """Blind trial 8, item 15 -- the table got appended at the end, and empty parent sections and the acknowledgments were also turned into slides."""

    def _run(self):
        bs = chr(92)
        src = NL.join([
            bs + "documentclass{article}", bs + "begin{document}",
            bs + "section{Introduction}", "Cells fade at 3.1 3.3 3.9 4.1 4.3 5.2 9.7.",
            bs + "section{Setup}", bs + "subsection{Cells}", "We used cells.",
            bs + "begin{tabular}{lr}", "Cell & Fade " + bs * 2, "A & 1.1 " + bs * 2,
            bs + "end{tabular}",
            bs + "section{Results}", "Things faded.",
            bs + "section*{Acknowledgment}", "Thanks.", bs + "end{document}"])
        tmp = tempfile.mkdtemp(prefix="so-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "paper.tex")
        with io.open(p, "w", encoding="utf-8") as f_:
            f_.write(src)
        out = os.path.join(tmp, "slides.yaml")
        scaffold.build(p, out)
        return deckspec.slurp(out)

    def test_a_table_follows_its_own_section(self):
        y = self._run()
        self.assertLess(y.index("Setup / Cells"), y.index("kind: table"))
        self.assertLess(y.index("kind: table"), y.index("Results"))

    def test_empty_parents_and_back_matter_get_no_slide(self):
        y = self._run()
        self.assertNotIn("Acknowledgment", y)
        self.assertNotIn('label it): Setup"', y)

    def test_meta_keys_the_skill_asks_for_are_there(self):
        y = self._run()
        for k in ("thesis:", "paper:", "institute:"):
            self.assertIn(k, y)

    def test_section_numbers_are_not_cut_at_six(self):
        self.assertIn("9.7", self._run())


class EighthBlindTrialKeys(unittest.TestCase):
    """Blind trial 8, item 16 -- `--keys` didn't show key core keys, and a typo in a nested key passed silently."""

    def _load(self, text):
        tmp = tempfile.mkdtemp(prefix="ky-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "slides.yaml")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return deckspec.load(p)

    def test_the_reference_lists_the_keys_agents_had_to_dig_for(self):
        ref = deckspec.key_reference()
        for k in ("thesis", "paper", "acronyms", "verdict", "takeaway", "col_notes",
                  "inner", "feed", "loop", "max_height", "size"):
            self.assertIn(k, ref)

    def test_a_typo_inside_a_chart_is_an_error(self):
        with self.assertRaises(ValueError) as cm:
            self._load(NL.join([
                "slides:", "- kind: figure", "  title: A b c",
                "  chart: {from: self, kind: heat, takeway: x}",
                "  table: {header: [a, b], rows: [[x, '1']]}", ""]))
        self.assertIn("takeway", str(cm.exception))

    def test_a_typo_inside_a_pipeline_stage_is_an_error(self):
        with self.assertRaises(ValueError) as cm:
            self._load(NL.join([
                "slides:", "- kind: figure", "  title: A b c",
                "  diagram: {kind: pipeline, rows: [{label: m, stages: [{label: s, iner: [a]}]}]}",
                ""]))
        self.assertIn("iner", str(cm.exception))

    def test_a_date_reaches_the_title_page(self):
        meta, _, _ = self._load(NL.join([
            "meta: {venue: Conf, date: May 2026}", "slides:", "- kind: title", ""]))
        self.assertEqual(meta["venue"], u"Conf · May 2026")


class EighthBlindTrialBuildPaths(unittest.TestCase):
    """Blind trial 8, item 17 -- build.py ignored `meta.figdir` and printed `out/out/figs` in a warning."""

    def test_user_figures_beside_the_spec_are_brought_into_the_output(self):
        sys.path.insert(0, SCRIPTS)
        import build
        tmp = tempfile.mkdtemp(prefix="bp-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        spec_dir = os.path.join(tmp, "talk")
        os.makedirs(os.path.join(spec_dir, "pics", "sub"))
        for p in (os.path.join(spec_dir, "pics", "a.png"),
                  os.path.join(spec_dir, "pics", "sub", "b.png")):
            with open(p, "wb") as f:
                f.write(b"x")
        spec = os.path.join(spec_dir, "slides.yaml")
        out = os.path.join(tmp, "elsewhere", "figs")
        os.makedirs(out)
        got = build.bring_user_figures(spec, {"figdir": "pics"}, out)
        self.assertEqual(sorted(got), ["a.png", "b.png"])
        self.assertTrue(os.path.isfile(os.path.join(out, "b.png")))

    def test_the_deck_is_given_figs_relative_to_its_own_folder(self):
        """Passing `out/figs` made the builder append it to the output folder again, producing `out/out/figs`."""
        src = deckspec.slurp(os.path.join(SCRIPTS, "build.py"))
        self.assertIn('build_deck.build(spec, tex, "figs")', src)
        self.assertIn('"figs")[2])', src)
        self.assertIn("cwd=outdir", src)


class EighthBlindTrialGridPitch(unittest.TestCase):
    """Blind trial 8, item 21 -- when a figure was narrower than its cell, the row label sat one cell away from the first figure."""

    def _body(self, cap):
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="gp-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "figs"))
        Image.new("RGB", (100, 100)).save(os.path.join(tmp, "figs", "a.png"))
        f = {"grid": {"images": [["a.png"] * 4] * 3, "rows": ["r1", "r2", "r3"],
                      "cols": ["c1", "c2", "c3", "c4"], "caption": [cap] * 4}}
        out = build_deck.grid_body(f, (tmp,), "figs", [], reserve=1.0)
        m = re.findall(r"m\{([0-9.]+)" + chr(92) * 2 + "linewidth", "".join(out))
        return [float(x) for x in m]

    def test_short_labels_let_the_columns_close_up(self):
        full = (1.0 - 0.11 - 0.012 * 4) / 4
        cols = self._body("ok")[1:]
        self.assertLess(max(cols), full * 0.9)

    def test_a_long_caption_keeps_its_line(self):
        cols = self._body("failure, ran past noon")[1:]
        need = len("failure, ran past noon") * 0.52 * 7 / 72 / deckspec.TEXT_W_IN
        self.assertGreaterEqual(min(cols) + 1e-6, min(need, (1.0 - 0.11 - 0.048) / 4))


class PipelineFrame(unittest.TestCase):
    """User feedback -- a frame enclosing several stages as one group could not be drawn."""

    SPEC = {"kind": "pipeline", "rows": [{
        "frame": {"label": "one depot", "note": "three halls", "mark": "a"},
        "stages": [{"label": "front", "feed": {"label": "input", "sub": "raw"}},
                   {"label": "middle"}, {"label": "back"}],
        "out": "result"}]}

    def _draw(self, spec):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="pf-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        made = []
        real = build_figs._round

        def spy(ax, x, y, w, h, face, *a, **k):
            made.append((x, y, w, h, face, k.get("zorder"), k.get("edge")))
            return real(ax, x, y, w, h, face, *a, **k)
        warn = []
        with mock.patch.object(build_figs, "_round", spy):
            words, seen = build_figs.draw_diagram(
                spec, os.path.join(tmp, "d.png"), (5.51, 2.4), warn)
        return build_figs, made, words, warn

    def test_one_outline_encloses_every_stage_and_names_it(self):
        bf, made, words, _ = self._draw(self.SPEC)
        frames = [m for m in made if m[5] == 1.4]
        self.assertEqual(len(frames), 1)
        fx, fy, fw, fh = frames[0][:4]
        boxes = [m for m in made if m[5] == 2 and m[4] != "none"
                 and m[6] is None]
        for b in boxes:
            self.assertGreaterEqual(b[0], fx)
            self.assertLessEqual(b[0] + b[2], fx + fw + 1e-6)
        self.assertEqual(frames[0][6], bf.ROLE_INK["a"])
        self.assertIn("one depot", words)
        self.assertIn("three halls", words)

    def test_inputs_hang_below_the_frame(self):
        bf, made, _, _ = self._draw(self.SPEC)
        fy = [m for m in made if m[5] == 1.4][0][1]
        feed = [m for m in made if m[4] == bf.design.SURFACE][0]
        self.assertLess(feed[1] + feed[3], fy)

    def test_the_stages_under_study_may_be_framed_in_green(self):
        """The stages under study can be enclosed in a green frame. This used to be rejected."""
        tmp = tempfile.mkdtemp(prefix="pf-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "slides.yaml")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(NL.join(["slides:", "- kind: figure", "  title: A b c",
                             "  diagram: {kind: pipeline, rows: [{frame: {label: m, mark: safe},"
                             " stages: [{label: s}]}]}", ""]))
        deckspec.load(p)

    def _old_verdict_colours_are_refused_on_a_frame(self):
        tmp = tempfile.mkdtemp(prefix="pf-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "slides.yaml")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(NL.join(["slides:", "- kind: figure", "  title: A b c",
                             "  diagram: {kind: pipeline, rows: [{frame: {label: m, mark: hit},"
                             " stages: [{label: s}]}]}", ""]))
        with self.assertRaises(ValueError) as cm:
            deckspec.load(p)
        self.assertIn("frame.mark", str(cm.exception))


class FixedPalette(unittest.TestCase):
    """Red/green are fixed as one set, the second channel is optional -- by default there is no underline or hatching."""

    def test_hit_and_safe_keep_their_fixed_values(self):
        import design
        self.assertEqual(design.line_of("hit"), "#C0392B")
        self.assertEqual(design.line_of("safe"), "#1E8449")
        self.assertEqual(design.text_of("safe"), "#1D7E46")   # text stays above 4.5:1

    def test_no_underline_by_default(self):
        tmp = tempfile.mkdtemp(prefix="op-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        spec = os.path.join(tmp, "s.yaml")
        deckspec.spit(spec, 'slides:\n  - title: "T"\n    bullets: ["<hit>-12.3</hit>"]\n')
        out = os.path.join(tmp, "talk.tex")
        build_deck.build(spec, out)
        self.assertNotIn(r"\underline", deckspec.slurp(out))

    def test_no_hatch_by_default(self):
        import build_figs
        from matplotlib import pyplot as plt
        tmp = tempfile.mkdtemp(prefix="op-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        made = []
        real = plt.Rectangle

        def spy(*a, **k):
            made.append(k.get("hatch"))
            return real(*a, **k)
        with mock.patch.object(build_figs.plt, "Rectangle", spy):
            build_figs.draw_heat({"header": ["", "A"], "rows": [["x", "<hit>-1.0</hit>"]]},
                                 os.path.join(tmp, "h.png"), slot=(3, 1.5), warn=[])
        self.assertEqual([h for h in made if h], [])


class PhotographsAreKept(unittest.TestCase):
    """A photograph or an experimental frame cannot be redrawn -- it's excluded from the pasted-paper-figure warning."""

    def _run(self, img):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="ph-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        img.save(os.path.join(tmp, "fig1.png"))
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, NL.join(['slides:', '  - kind: figure', '    title: "The garden beds"',
                                  '    figure: {path: "fig1.png"}', '    say: ["s"]', '']))
        return prose_audit.pasted_paper_figures(prose_audit.read_slides(p), (tmp,))

    def test_a_photograph_is_not_flagged(self):
        import random
        from PIL import Image
        random.seed(3)
        im = Image.new("RGB", (300, 200))
        im.putdata([(random.randrange(256), random.randrange(256), random.randrange(256))
                    for _ in range(300 * 200)])
        self.assertEqual(self._run(im), [])

    def test_a_chart_is_still_flagged(self):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (300, 200), "white")
        d = ImageDraw.Draw(im)
        for k in range(5):
            d.rectangle([20 + 50 * k, 180 - 30 * k, 50 + 50 * k, 180], fill="#3B6EA5")
        self.assertEqual([n for n, _ in self._run(im)], [1])


class PlanningFeatures(unittest.TestCase):
    """General features that `planning.md` points to -- the deck and the PPTX follow the same rule."""

    def _deck(self, spec_lines, figs=()):
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="pl-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "figs"))
        for name in figs:
            Image.new("RGB", (400, 120), (120, 110, 90)).save(os.path.join(tmp, "figs", name))
        spec = os.path.join(tmp, "slides.yaml")
        deckspec.spit(spec, NL.join(spec_lines + [""]))
        out = os.path.join(tmp, "talk.tex")
        build_deck.build(spec, out)
        return tmp, spec, deckspec.slurp(out)

    def test_a_diagram_and_a_photo_stack_on_one_slide(self):
        """Given both, only the figure got drawn, and the diagram was silently dropped."""
        tmp, spec, src = self._deck([
            "slides:", "- kind: figure", "  title: The pack we opened",
            "  diagram: {kind: flow, boxes: [{label: a}, {label: b}]}",
            "  figure: {path: rig.png, caption: The rig.}"], figs=("rig.png",))
        # since the figure was never generated, the diagram's spot comes out as a missing box (underscore escaped)
        self.assertIn("diagram", src)
        self.assertIn("rig.png", src)
        self.assertLess(src.index("diagram"), src.index("rig.png"))
        _, slides, _ = deckspec.load(spec)
        self.assertGreater(deckspec.fig_reserve(slides[0]), deckspec.stacked_photo_in(slides[0]))

    def test_a_tall_photo_under_a_diagram_is_called_a_thumbnail(self):
        """Trial 36 -- placing a whole frame grid (a tall figure) under a diagram shrank it to a thumbnail,
        and an agent dropped the photo because of it. Now the width is measured and reported, and a
        one-line crop suggestion is given. A wide band draws no comment."""
        from PIL import Image
        def warns(size):
            tmp = tempfile.mkdtemp(prefix="pl-")
            self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
            os.makedirs(os.path.join(tmp, "figs"))
            Image.new("RGB", size, (120, 110, 90)).save(os.path.join(tmp, "figs", "rig.png"))
            spec = os.path.join(tmp, "slides.yaml")
            deckspec.spit(spec, NL.join([
                "slides:", "- kind: figure", "  title: The pack we opened",
                "  diagram: {kind: flow, boxes: [{label: a}, {label: b}]}",
                "  figure: {path: rig.png}", ""]))
            return [w for w in build_deck.build(spec, os.path.join(tmp, "talk.tex"))[2] if "thumbnail" in w]
        self.assertTrue(warns((400, 330)))
        self.assertIn("crop", warns((400, 330))[0])
        self.assertEqual(warns((1200, 200)), [])

    def test_gap_with_a_number_sits_on_the_label_row(self):
        self.assertEqual(deckspec.gap_place("3 days sooner", True), "label")
        self.assertEqual(deckspec.gap_place("or", True), "number")
        self.assertEqual(deckspec.gap_place("3 days sooner", False), "number")
        _, _, src = self._deck([
            "slides:", "- kind: standout",
            "  big: [{value: '31.8', label: old bridge}, {value: '28.8', label: new bridge}]",
            "  gap: 3 days sooner", "  lines: [Buses cross twice an hour., {text: counted in May, size: small}]"])
        self.assertIn("{\\normalsize vs}", src)
        self.assertIn("{\\small counted in May", src)
        self.assertIn("{\\large Buses cross twice an hour.", src)

    def test_big_text_items_are_drawn(self):
        """The key table has `text`, but the drawing side only ever read `value`."""
        _, _, src = self._deck([
            "slides:", "- kind: standout", "  lead: Where should the new stop go?",
            "  big: [{text: by the school}, {text: by the market}]", "  gap: or"])
        self.assertIn("by the school", src)
        self.assertIn("by the market", src)

    def test_a_caveat_line_has_no_bullet(self):
        _, _, src = self._deck([
            "slides:", "- title: Rules to take away", "  bullets:",
            "  - Keep the pack cool", "  - '> Measured in summer only'"])
        self.assertIn("\\item[] \\hspace{1em}Measured in summer", src)
        self.assertEqual(deckspec.strip_markup("> Measured"), "Measured")

    def test_a_head_over_text_is_a_bold_subhead(self):
        _, _, src = self._deck([
            "slides:", "- kind: columns", "  title: The second site, row by row",
            "  left: {head: site two, table: {header: [a, b], rows: [[x, '1']]}}",
            "  right: {head: Where it differs, bullets: [one]}"])
        self.assertIn("{\\centering\\footnotesize site two", src)
        self.assertIn("{\\small\\bfseries Where it differs", src)

    def test_the_presenter_is_underlined(self):
        _, _, src = self._deck([
            "meta: {title: T, author: 'A. One, B. Two', presenter: A. One,",
            "       institute: [Lab, Institute]}", "slides:", "- kind: title"])
        self.assertIn("\\underline{A. One}", src)
        self.assertIn("Lab\\\\Institute", src)

    def test_pptx_text_is_the_deck_size_times_the_page_ratio(self):
        """PPTX body text is 80% of the deck's size, and footnotes are 70%."""
        import build_pptx
        self.assertAlmostEqual(build_pptx.T_BODY / 540.0, 10 / 255.0, places=3)
        self.assertAlmostEqual(build_pptx.T_SMALL / 540.0, 8 / 255.0, places=3)

    def test_tile_rows_are_named_in_each_panel_by_default(self):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="pl-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tb = {"header": ["", "p", "q"], "rows": [["row", "1", "2"], ["2:4", "3", "4"]]}
        seen = build_figs.draw_tiles([("A", tb), ("B", tb)], os.path.join(tmp, "t.png"),
                                     slot=(5.5, 2.0), warn=[])
        self.assertEqual(sum(1 for _, s in seen if s == "row"), 2)
        seen = build_figs.draw_tiles([("A", tb), ("B", tb)], os.path.join(tmp, "u.png"),
                                     slot=(5.5, 2.0), warn=[], share_rows=True)
        self.assertEqual(sum(1 for _, s in seen if s == "row"), 1)


class NinthBlindTrialSmall(unittest.TestCase):
    """Blind trial 9, D8/D9/D12."""

    def _script(self, lines):
        tmp = tempfile.mkdtemp(prefix="n9-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, NL.join(lines + [""]))
        out = os.path.join(tmp, "script.md")
        build_script.build(p, out)
        return deckspec.slurp(out)

    def test_an_ask_with_q_and_a_is_not_a_python_repr(self):
        md = self._script(["slides:", "- title: One claim here", "  say: [s]",
                           "  ask: [{q: 'Why this cell?', a: 'Because it is hottest.'}]"])
        self.assertNotIn("{'q'", md)
        self.assertIn("Why this cell?", md)
        self.assertIn("Because it is hottest.", md)

    def test_an_untitled_flow_slide_gets_a_heading(self):
        md = self._script(["slides:", "- kind: standout", "  flow: [dough, oven]",
                           "  say: [s]"])
        self.assertIn("## 1. dough", md)

    def test_a_middle_dot_is_typeset(self):
        self.assertIn(chr(92) + "textperiodcentered{}", build_deck.esc(u"a \u00b7 b"))


class TenthBlindTrialVoice(unittest.TestCase):
    """A talk is speech -- not a paper copied over slide by slide.

    In blind trial 10, about one title in three had lifted a results sentence straight from the paper
    (5-8 consecutive words matching the paper). In one example deck, titles matched the paper by at
    most four consecutive words. Delivery direction (`cue`) also appeared on only about one slide in six.
    """

    PAPER = ("Cells stored above forty degrees with the dry electrolyte lose a third "
             "of their capacity within seven days, while the wet cell keeps it.")

    def _slides(self, spec_text):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="vo-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return prose_audit.read_slides(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_spoken_titles_are_not_labels(self):
        """A false positive (D8) that mistook a spoken title for a label."""
        import prose_audit
        for t in ("The route we timed", "Why the ovens run hot",
                  "Every loaf rises slower in winter"):
            self.assertTrue(prose_audit.is_claim(t), t)

    def test_bare_labels_still_fail(self):
        import prose_audit
        for t in ("Results", "Related work", "Method", "Experimental setup",
                  "Future work"):
            self.assertFalse(prose_audit.is_claim(t), t)

    def test_a_title_copied_from_the_paper_is_listed(self):
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - title: "Cells stored above forty degrees with the dry electrolyte lose capacity"\n'
                          '    bullets: ["x"]\n'
                          '  - title: "Heat is the problem, for one of the two cells"\n'
                          '    bullets: ["x"]\n')
        got = prose_audit.titles_copied_from_paper(sl, self.PAPER)
        self.assertEqual([n for n, _, _ in got], [1])
        self.assertGreaterEqual(got[0][1], prose_audit.TITLE_COPY_RUN)

    def test_an_impact_slide_may_quote_the_paper(self):
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - kind: standout\n'
                          '    big: "the dry electrolyte lose a third of their capacity"\n')
        self.assertEqual(prose_audit.titles_copied_from_paper(sl, self.PAPER), [])

    def test_slides_without_a_cue_are_listed(self):
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - title: "Look at the bottom row"\n    bullets: ["x"]\n'
                          '    cue: "point at the dry cell first"\n'
                          '  - title: "Does it hold in the cold?"\n    bullets: ["x"]\n')
        self.assertEqual(prose_audit.undirected_slides(sl), [2])

    def test_a_number_inside_a_bullet_is_not_a_bullet_count(self):
        """A false positive (D9) that compared "three retries per request" against a count of six bullets."""
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - title: "Things we never tested"\n'
                          '    bullets: ["One pump moves eight litres per stroke", "b", "c", "d", "e", "f"]\n')
        self.assertEqual(prose_audit.count_mismatch(sl), [])
        sl = self._slides(self.HEAD +
                          '  - title: "Five things we never tested"\n'
                          '    bullets: ["a", "b", "c", "d", "e", "f"]\n')
        self.assertEqual([(n, w, g) for n, w, g, _ in prose_audit.count_mismatch(sl)],
                         [(1, 5, 6)])

    def test_a_hedge_word_is_not_a_name(self):
        """"only 3.3" and "only 1.9" are not two values of the same term (D9)."""
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - title: "A"\n    bullets: ["the north route loses only 3.3"]\n'
                          '  - title: "B"\n    bullets: ["the south route loses only 1.9"]\n')
        self.assertEqual([x for x in prose_audit.contradicting_values(sl)
                          if x[0] == "only"], [])


class TenthBlindTrialFeatures(unittest.TestCase):
    """Blind trial 10, items 2-2 / 2-3 / 2-5 / D6."""

    def test_cell_indent(self):
        """D6 -- leading whitespace in a table cell (a sub-item) used to disappear."""
        self.assertEqual(deckspec.cell_indent("  dry cell"), (1, "dry cell"))
        self.assertEqual(deckspec.cell_indent("x"), (0, "x"))
        src = build_deck.render_table({"header": ["a", "b"],
                                       "rows": [["Heat", "1"], ["  dry", "2"]]})
        self.assertIn("\\hspace*{1em}dry", src)

    def test_outer_band_is_drawn_and_counted(self):
        """2-2 -- a group above a group. The outer band's label must be captured in the figure's text."""
        import build_figs
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, 'slides:\n  - kind: figure\n    title: "T"\n'
                             '    diagram:\n      kind: strip\n      rows:\n'
                             '        - {label: "Company", bars: 12, groups: [4, 4, 4], '
                             'group_label: "team", outer: "one department"}\n')
            with redirect_stdout(io.StringIO()):
                build_figs.build(p, tmp, os.path.join(tmp, "values.txt"))
            got = deckspec.slurp(os.path.join(tmp, "values.txt"))
            self.assertIn("one department", got)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_outer_is_a_known_row_key(self):
        self.assertIn("outer", deckspec.STRIP_ROW_KEYS)

    def test_title_wrap_is_measured_from_the_pdf(self):
        """2-3 -- a title wrapped onto two lines is found by measuring the PDF."""
        try:
            import fitz
        except ImportError:                          # pragma: no cover
            self.skipTest("PyMuPDF not installed")
        tmp = tempfile.mkdtemp()
        try:
            pdf = os.path.join(tmp, "t.pdf")
            doc = fitz.open()
            pg = doc.new_page(width=453.5, height=255.1)
            pg.insert_text((10, 18), "First line of a long title", fontsize=12)
            pg.insert_text((10, 33), "second line", fontsize=12)
            pg = doc.new_page(width=453.5, height=255.1)
            pg.insert_text((10, 18), "One line", fontsize=12)
            pg.insert_text((10, 120), "body text", fontsize=12)
            doc.save(pdf)
            self.assertEqual([n for n, _ in deckspec.title_wraps(pdf)], [1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TenthBlindTrialBugs(unittest.TestCase):
    """Build defects D1/D2/D5/D7 reported by blind trial 10, plus defaults 2-4/2-7."""

    def _tex(self, y):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml"); deckspec.spit(p, y)
            o = os.path.join(tmp, "t.tex")
            _, _, warn = build_deck.build(p, o)
            return deckspec.slurp(o), "\n".join(warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_table_size_names_become_latex_sizes(self):
        """D1 -- `size: fine` came out as `{\\fine`, which stopped compilation."""
        src, _ = self._tex('slides:\n  - title: "T"\n    table:\n'
                           '      header: ["a", "b"]\n      rows: [["x", "1"]]\n'
                           '      size: fine\n')
        self.assertIn("\\scriptsize", src)
        self.assertNotIn("{\\fine", src)

    def test_en_dash_range_is_not_a_minus(self):
        """D2 -- "3-5" printed as "3-−5"."""
        src, _ = self._tex('slides:\n  - title: "T"\n    bullets: ["from 3–5 cells, and -7 at worst"]\n')
        self.assertNotIn("-\\textminus", src)
        self.assertIn("\\textminus 7", src)

    def test_italic_inside_bold(self):
        """D5 -- in `**... *slowly***`, the asterisks printed on screen."""
        src, _ = self._tex('slides:\n  - title: "T"\n    bullets: ["**the queue grows *slowly***"]\n')
        self.assertIn("\\emph{slowly}", src)
        self.assertNotIn("*", src.split("\\begin{document}")[-1].replace("\\frametitle", ""))

    def test_nested_say_is_refused_at_validation(self):
        """D7 -- a nested list passed validation and then crashed the build with a traceback."""
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, 'slides:\n  - title: "T"\n    say: ["a", ["b", "c"]]\n')
            with self.assertRaises(ValueError) as cm:
                deckspec.load(p)
            self.assertIn("say", str(cm.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_flow_last_step_is_green(self):
        """2-4 -- the last box a flow arrives at is colored green."""
        src, _ = self._tex('slides:\n  - kind: standout\n'
                           '    flow: ["dough", "proof", "oven"]\n')
        self.assertIn("\\textcolor{mSafeLt}", src)

    def test_long_title_page_title_warns(self):
        """2-7 -- a title-page title spanning three lines is flagged with a suggestion to move a qualifying clause into the subtitle."""
        long_t = ("Seasonal Variation in Queue Length at Rural Clinics Staffed "
                  "by Rotating Nurses Across Three Provinces During Two Consecutive "
                  "Winters and One Long Summer")
        _, err = self._tex('meta: {title: "%s", author: A, venue: V, date: D}\n'
                           'slides:\n  - kind: title\n  - title: "T"\n    bullets: ["x"]\n'
                           % long_t)
        self.assertIn("subtitle", err)
        # a title that fits on two lines must stay quiet -- a title of this length was two lines in an
        #   actual deck, yet character count said "exceeds two lines" (surfaced by blind trial 29)
        two = ("Seasonal Variation in Queue Length at Rural Clinics Staffed "
               "by Rotating Nurses Across Three Provinces")
        _, err = self._tex('meta: {title: "%s", author: A, venue: V, date: D}\n'
                           'slides:\n  - kind: title\n  - title: "T"\n    bullets: ["x"]\n'
                           % two)
        self.assertNotIn("subtitle", err)


class EleventhBlindTrial(unittest.TestCase):
    """What blind trial 11 found -- three checker false positives, a key that never got drawn, and figure/PPTX defects."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _slides(self, spec_text):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="e11-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return prose_audit.read_slides(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _load(self, spec_text):
        tmp = tempfile.mkdtemp(prefix="e11-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_sequence_title_is_spoken(self):
        """Defect 10 -- a "First: ..." title, which `planning` §factors explicitly allows, was flagged as a mere label."""
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - title: "First: the dial"\n    bullets: ["x"]\n'
                          '  - title: "Results"\n    bullets: ["x"]\n')
        self.assertEqual([n for n, _, _ in prose_audit.names_not_claims(sl)], [2])

    def test_blanks_are_explained_on_their_own_slide(self):
        """Defect 12 -- one "dash" explanation on a different slide let every blank cell through."""
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - title: "A"\n    table:\n      header: [a, b]\n'
                          '      rows: [["x", "-"]]\n      note: "A dash: not measured."\n'
                          '  - title: "B"\n    table:\n      header: [a, b]\n'
                          '      rows: [["y", "-"]]\n')
        self.assertEqual([n for n, _ in prose_audit.unexplained_blanks(sl)], [2])

    def test_row_feed_is_refused_with_where_to_put_it(self):
        """A row's `feed` passed validation and was never drawn -- the input box silently disappeared."""
        with self.assertRaises(ValueError) as cm:
            self._load(self.HEAD + '  - kind: figure\n    title: "T"\n'
                       '    diagram:\n      kind: pipeline\n      rows:\n'
                       '        - label: "Plant"\n          feed: {label: "sensor"}\n'
                       '          stages: [{label: "filter"}, {label: "mixer"}]\n')
        self.assertIn("stages", str(cm.exception))

    def test_stage_feed_is_still_accepted(self):
        self._load(self.HEAD + '  - kind: figure\n    title: "T"\n'
                   '    diagram:\n      kind: pipeline\n      rows:\n'
                   '        - label: "Plant"\n'
                   '          stages: [{label: "filter", feed: {label: "sensor"}}, {label: "mixer"}]\n')

    def test_a_marked_bar_keeps_its_series_colour(self):
        """Defect 1 -- `<hit>` painted the bar red, and the legend swatch turned red along with it."""
        import build_figs
        import matplotlib.pyplot as plt
        made = []
        real = plt.Axes.bar

        def spy(ax, *a, **k):
            made.append(k.get("color"))
            return real(ax, *a, **k)
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(plt.Axes, "bar", spy):
                build_figs.draw_bars(
                    {"header": ["Part", "Dry", "Wet"],
                     "rows": [["Cathode", "<hit>-12.1</hit>", "<hit>-8.2</hit>"],
                              ["Anode", "-1.9", "-3.1"]]},
                    os.path.join(tmp, "b.png"), None, "change", None,
                    (4.0, 2.4), [], None, None)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(len(made), 2)
        for c in made:
            self.assertIsInstance(c, str, "each series must be a single color")

    def test_tile_row_of_dashes_is_named(self):
        """2-4 -- a mostly-empty row was shrinking every tile."""
        import build_figs
        warn = []
        tb = {"header": ["", "a", "b", "c"],
              "rows": [["one", "+3.3", "+0.2", "+0.1"],
                       ["two", "-0.4", "-", "-"],
                       ["three", "<hit>-1.0</hit>", "<hit>-2.0</hit>", "+0.0"]]}
        tmp = tempfile.mkdtemp()
        try:
            build_figs.draw_tiles([("P", tb)], os.path.join(tmp, "t.png"), warn=warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(any("two" in w and "fine" in w for w in warn), warn)

    def test_pptx_minus_and_block_colours(self):
        """Defects 6/7 -- an emphasis box's title color, and the minus sign in front of a number."""
        import build_pptx
        self.assertEqual(build_pptx._MINUS.sub("−", "a -10.0 and 8-15"),
                         "a −10.0 and 8-15")
        _, tc = build_pptx.block_colours("alert")
        self.assertEqual(tc, build_pptx.HIT)
        _, tc = build_pptx.block_colours("good")
        self.assertEqual(tc, build_pptx.SAFE)
        _, tc = build_pptx.block_colours(None)
        self.assertEqual(tc, build_pptx.INK)


class TwelfthBlindTrial(unittest.TestCase):
    """What blind trial 12 found -- a PPTX table wrapping, three checker false positives, strip label/color, and verdict color."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _slides(self, spec_text):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="e12-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return prose_audit.read_slides(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pptx_table_height_counts_wrapped_rows(self):
        """Defect 1 -- a wrapped row was counted as a single line, so the text under the table printed on top of it."""
        import build_pptx
        from pptx import Presentation
        from pptx.util import Inches
        prs = Presentation()
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        warn = []
        t = {"header": ["Part", "fast charge at room temperature", "p"],
             "rows": [["Cathode, first layer of the coating", "-15.3", "0.01"],
                      ["Anode", "+1.4", "0.02"]]}
        sh = build_pptx.add_table(sl, t, 0.5, 1.0, 3, warn, size=14, rh=0.30,
                                  where="Slide 1:")
        self.assertGreater(build_pptx.table_height(sh), 0.30 * 3 + 0.2)
        self.assertAlmostEqual(sh.height / 914400.0, build_pptx.table_height(sh), 2)
        self.assertTrue(any("Slide 1" in w for w in warn), warn)
        # a numeric column is one solid block -- it gets the width of its longest word
        p_col = sh.table.columns[2].width / 914400.0
        self.assertGreater(p_col, len("0.01") * 14 * 0.55 / 72.0)

    def test_group_header_row_is_not_a_blank(self):
        """Defect 2 -- a group-header row with only its first cell filled was counted as blank."""
        import prose_audit
        sl = self._slides(self.HEAD + '  - title: "A"\n    table:\n'
                          '      header: [a, b, c]\n'
                          '      rows: [["Dry cell", "", ""], ["x", "1", "2"]]\n')
        self.assertEqual(prose_audit.unexplained_blanks(sl), [])

    def test_reading_words_are_not_coined(self):
        """Defect 3 -- "read" and "blank cells" were flagged as words absent from the manuscript."""
        got = deckcheck.coined_terms("read read read cells cells cells blank blank blank",
                                     "the paper says nothing about it", 3)
        self.assertEqual(got, [])

    def test_marks_count_as_emphasis(self):
        """Defect 4 -- `mark` on `big` and `mark` on a diagram were not counted as emphasis."""
        import refcheck
        self.assertTrue(refcheck.has_marks(
            {"big": [{"value": "-15.3", "mark": "hit"}, {"value": "+0.4"}]}))
        self.assertTrue(refcheck.has_marks(
            {"diagram": {"kind": "pipeline", "rows": [{"stages": [{"label": "x", "mark": "a"}]}]}}))
        self.assertFalse(refcheck.has_marks(
            {"diagram": {"kind": "strip", "rows": [{"cells": [{"label": "R", "mark": "ride"}]}]}}))

    def test_a_long_span_label_is_drawn_once(self):
        """Defect 5 -- `{label: weekdays, span: 4}` used to repeat in every cell and overlap itself."""
        import build_figs
        tmp = tempfile.mkdtemp()
        try:
            _, seen = build_figs.draw_strip(
                {"kind": "strip", "rows": [
                    {"label": "week", "cells": [{"label": "Sun"},
                                                {"label": "weekdays", "span": 4}]},
                    {"label": "shifts", "cells": [{"label": "N", "span": 3}]}]},
                os.path.join(tmp, "s.png"), warn=[])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        labs = [t for _, t in seen]
        self.assertEqual(labs.count("weekdays"), 1)
        self.assertEqual(labs.count("N"), 3)

    def test_role_names_get_distinct_colours(self):
        """Defect 6 -- the fourth role was the same gray as the third, and a role named "e" also received its assigned turn."""
        import design
        m = design.role_map(["p", "q", "e", "r"])
        self.assertEqual(m["e"], design.ROLES["e"])
        fills = [v[1] for v in m.values()]
        self.assertEqual(len(set(fills)), 4)

        def lum(h):
            h = h.lstrip("#")
            r, g, b = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
            f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
        a, b = lum(design.ROLES["c"][1]), lum(design.ROLES["d"][1])
        self.assertGreater((max(a, b) + 0.05) / (min(a, b) + 0.05), 1.5)

    def test_verdict_for_unmarked_cells_is_plain(self):
        """2-1 -- an example attached the words for "an unmarked cell" to `safe:`, which turned unmarked
        cells green. A verdict example must put the words for an unmarked cell under `plain:` (never under `safe:`)."""
        with io.open(os.path.join(os.path.dirname(SCRIPTS), "references", "layouts.md"), encoding="utf-8") as f:
            doc = f.read()
        examples = re.findall(r"verdict:\s*\{([^}]*)\}", doc)
        self.assertTrue(examples, "layouts.md has no verdict examples")
        for ex in examples:
            self.assertIn("plain:", ex)
            self.assertNotIn("safe:", ex)


class ThirteenthBlindTrial(unittest.TestCase):
    """What blind trial 13 found -- dash-cell verdicts, tiling every cell, rules colliding with each other, and script page numbers."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _slides(self, spec_text):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="e13-")
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, spec_text)
        try:
            return prose_audit.read_slides(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _tiles(self, rows, verdict=None):
        import build_figs
        warn = []
        tmp = tempfile.mkdtemp()
        try:
            seen = build_figs.draw_tiles(
                [("", {"header": ["", "dry", "wet"], "rows": rows})],
                os.path.join(tmp, "t.png"), warn=warn, verdict=verdict)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return warn, [t for _, t in seen]

    def test_an_em_dash_cell_gets_no_verdict(self):
        """Defect 1 -- a "held" verdict was printed on a "—" (not run) cell."""
        _, said = self._tiles([["Cathode", "<hit>-12.1</hit>", "—"],
                               ["Anode", "—", "+0.2"]],
                              verdict={"hit": "failed", "plain": "held"})
        self.assertEqual(said.count("held"), 1)

    def test_a_worded_cell_gets_no_verdict(self):
        """Trial 36, defect 1 -- a "held" verdict printed under a "not run" cell, making a setting that
        was never run look fine. The text stays; only the verdict is dropped."""
        _, said = self._tiles([["Cathode", "<hit>-12.1</hit>", "not run"],
                               ["Anode", "skipped", "+0.2"]],
                              verdict={"hit": "failed", "plain": "held"})
        self.assertEqual(said.count("held"), 1)
        self.assertIn("not run", said)
        self.assertIn("skipped", said)

    def test_tiles_of_every_cell_are_named(self):
        """2-1 -- all eight cells were drawn as tiles while only two were actually flagged."""
        warn, _ = self._tiles([["a", "<hit>-12.1</hit>", "+0.2"], ["b", "+0.1", "+0.3"],
                               ["c", "-0.4", "<hit>-8.2</hit>"], ["d", "+1.1", "-0.2"]])
        self.assertTrue(any("planning §table" in w for w in warn), warn)
        warn, _ = self._tiles([["a", "<hit>-12.1</hit>", "+0.2"],
                               ["c", "-0.4", "<hit>-8.2</hit>"]])
        self.assertFalse(any("planning §table" in w for w in warn), warn)

    def test_keys_no_longer_call_safe_not_significant(self):
        """Defect 2 -- `--keys` still said "<safe> = not significant"."""
        txt = deckspec.keys_help() if hasattr(deckspec, "keys_help") else ""
        if not txt:
            with io.open(os.path.join(SCRIPTS, "deckspec.py"), encoding="utf-8") as f:
                txt = f.read()
        self.assertNotIn("<safe>+0.2</safe>   not significant", txt)

    def test_the_question_standout_need_not_carry_the_thesis(self):
        """Defect 3 -- `planning` §question ("don't put the conclusion in it") collided with 0b ("carry the thesis's own wording")."""
        import prose_audit
        sl = self._slides(self.HEAD +
                          '  - kind: standout\n    lead: "Which stop would you move?"\n'
                          '    big: [{text: "by the school"}, {text: "by the market"}]\n    gap: "or"\n'
                          '  - kind: standout\n    big: "Move the stop first; the timetable follows."\n')
        got = prose_audit.standouts_off_thesis(sl, "Move the stop first; the timetable follows.")
        self.assertEqual([n for n, _, _ in got], [2])

    def test_dash_legend_explains_blanks(self):
        """Defect 5 -- "-- : the paper names no such choice" was not recognized as an explanation."""
        import prose_audit
        self.assertTrue(prose_audit.EXPLAINS_BLANK.search("— : the paper names no such choice"))
        self.assertTrue(prose_audit.EXPLAINS_BLANK.search("Empty cell = same part as above"))
        self.assertFalse(prose_audit.EXPLAINS_BLANK.search("from 3 to 5 cycles"))

    def test_irregular_forms_are_the_same_word(self):
        """Defect 4 -- the paper has "keep," yet the deck's "kept" was flagged as a coinage."""
        self.assertEqual(deckcheck.coined_terms("kept kept kept", "we keep it", 3), [])

    def test_a_pipeline_legend_is_refused(self):
        """Defect 7 -- pipeline's `legend` was accepted but never drawn."""
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - kind: figure\n    title: "T"\n'
                             '    diagram:\n      kind: pipeline\n      legend: {hit: "avoid"}\n'
                             '      rows:\n        - label: "Plant"\n'
                             '          stages: [{label: "filter"}, {label: "mixer", mark: hit}]\n')
            with self.assertRaises(ValueError) as cm:
                deckspec.load(p)
            self.assertIn("note", str(cm.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_backup_slide_may_show_the_paper_figure(self):
        """Defect 10 -- a paper figure carrying no numbers has no way to be redrawn. This is allowed on a backup slide."""
        import prose_audit
        sl = [{"n": 5, "backup": True, "figure": {"path": "fig_c.png"}}]
        self.assertEqual(prose_audit.pasted_paper_figures(sl, ()), [])

    def test_script_heads_carry_the_screen_page_and_old_thumbs_go(self):
        """Defect 9 -- the script's numbering and the on-screen page number disagreed, and stale thumbnails were left behind."""
        import build_script
        self.assertIn("page", build_script.LABELS["ko"])
        self.assertIn("page", build_script.LABELS["en"])
        try:
            import fitz
        except ImportError:                          # pragma: no cover
            self.skipTest("PyMuPDF not installed")
        tmp = tempfile.mkdtemp()
        try:
            pdf = os.path.join(tmp, "t.pdf")
            doc = fitz.open()
            doc.new_page(width=200, height=120)
            doc.save(pdf)
            out = os.path.join(tmp, "thumbs")
            os.makedirs(out)
            with io.open(os.path.join(out, "s28.png"), "wb") as _f:
                _f.write(b"x")
            got = build_script.thumbs(pdf, out, dpi=20)
            self.assertEqual(sorted(os.listdir(out)), ["s01.png"])
            self.assertEqual(list(got), [1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repeated_build_warnings_print_once(self):
        import build
        with redirect_stdout(io.StringIO()) as f:
            got = build._say("x", ["a", "b", "a"])
        self.assertEqual(got, ["a", "b"])
        self.assertEqual(f.getvalue().count("a"), 1)


class FourteenthBlindTrialOtherPaper(unittest.TestCase):
    """Blind trial 14 -- spots that assumed one particular kind of paper, surfaced by running against a different paper."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_deckcheck_ignores_latex_comments_in_the_source(self):
        """A number that existed only in a comment was counted as "has a source" -- claiming evidence that wasn't there."""
        self.assertEqual(deckcheck.strip_tex_comments("a 71 % 99 hidden\nb 50\\% c"),
                         "a 71 \nb 50\\% c")

    def test_diffcheck_drops_layout_values(self):
        import diffcheck
        body = diffcheck.clean_tex("\\renewcommand{\\arraystretch}{1.2}\\vspace{-.2em}"
                                   " The loss is 8.6 hours. \\textbf{Kept} 6.5pt")
        self.assertIn("8.6", body)
        self.assertIn("Kept", body)
        self.assertNotIn("1.2", body)
        self.assertNotIn("6.5", body)

    def test_scaffold_counts_custom_and_repeated_columns(self):
        """Not recognizing a `\\newcolumntype{x}` column made the key table's results column vanish entirely."""
        import scaffold
        scaffold.CUSTOM_SRC[0] = "\\newcolumntype{x}[1]{>{\\centering}p{#1pt}}"
        try:
            self.assertEqual(scaffold.colspec("{l|x{42}|c}", 0)[0], "lcc")
            self.assertEqual(scaffold.colspec("{l*{3}{r}}", 0)[0], "lrrr")
            self.assertEqual(scaffold.colspec("{p{3cm}c}", 0)[0], "pc")
        finally:
            scaffold.CUSTOM_SRC[0] = ""

    def test_scaffold_reads_authors_and_drops_comment_rows(self):
        import scaffold
        tmp = tempfile.mkdtemp()
        try:
            src = ("\\documentclass{article}\\title{Cells}\n"
                   "\\author{Ann Lee \\qquad Bo Kim \\\\\n\\large Cell Lab \\vspace{-.2em}\\\\\n"
                   "\\{ann\\}@lab.org}\n\\begin{document}\\section{Results}\n"
                   "\\begin{tabular}{lc}\nPart & Loss \\\\\n% Old part & 9.9 \\\\\n"
                   "Anode & 8.6 \\\\\nCathode & 1.3 \\\\\n\\end{tabular}\n\\end{document}\n")
            p = os.path.join(tmp, "p.tex")
            deckspec.spit(p, src)
            o = os.path.join(tmp, "s.yaml")
            with redirect_stdout(io.StringIO()):
                scaffold.build(p, o)
            got = deckspec.slurp(o)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn('author: "Ann Lee, Bo Kim"', got)
        self.assertIn('institute: "Cell Lab"', got)
        self.assertNotIn("Old part", got)
        self.assertNotIn("-.2em", got)

    def test_pipeline_skip_is_drawn_and_validated(self):
        """A skip connection -- residual blocks and bypass routes could not be drawn."""
        import build_figs
        d = {"kind": "pipeline", "rows": [{"label": "unit", "stages": [
            {"label": "layer"}, {"label": "relu"}, {"label": "layer"}, {"label": "add"}],
            "skip": {"from": 0, "to": "add", "label": "identity"}}]}
        warn = []
        tmp = tempfile.mkdtemp()
        try:
            words, _ = build_figs.draw_pipeline(d, os.path.join(tmp, "p.png"), warn=warn)
            bad = dict(d, rows=[dict(d["rows"][0], skip={"from": 3, "to": 1})])
            build_figs.draw_pipeline(bad, os.path.join(tmp, "q.png"), warn=warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("identity", words)
        self.assertTrue(any("skip" in w for w in warn), warn)
        self.assertIn("skip", [k for k, _ in deckspec.PIPE_ROW_KEYS])

    def test_bar_values_are_written_as_the_table_has_them(self):
        """An absolute-value bar printed as `+28.5` (from a `%+.1f` format that assumed a change value)."""
        import build_figs
        tmp = tempfile.mkdtemp()
        try:
            got = build_figs.draw_bars(
                {"header": ["depth", "error"],
                 "rows": [["34", "24.52"], ["152", "21.43"]]},
                os.path.join(tmp, "b.png"), ylabel="error (%)", slot=(4.0, 2.4),
                warn=[], callout={"at": "152", "series": 0, "text": "lowest"})
            seen = got[-1] if isinstance(got, tuple) else got
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        said = [t for _, t in seen]
        self.assertIn("24.52", said)
        self.assertNotIn("+24.5", said)

    def test_a_single_big_mapping_becomes_a_list(self):
        """Defect 4 -- `big: {text: ...}` printed as a Python repr in the deck."""
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - kind: standout\n    big: {text: "one sentence"}\n')
            _, sl, _ = deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(deckspec.big_text(sl[0]["big"]).strip(), "one sentence")

    def test_a_number_before_a_word_is_a_quantity_not_a_name(self):
        """Defect 11 -- "18 layers 27.94" and "34 layers 28.54" were treated as two values of the same term."""
        import prose_audit
        sl = [{"n": 1, "raw_screen": "18 layers 27.94 and 34 layers 28.54"}]
        self.assertEqual(prose_audit.contradicting_values(sl), [])

    def test_backup_slides_do_not_count_in_the_profile(self):
        """Defect 14 -- counting backup slides too forced bold text to be added to a lookup table."""
        import refcheck
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - title: "A"\n    bullets: ["**x**"]\n'
                             '  - title: "B"\n    backup: true\n    table:\n'
                             '      header: [a, b]\n      rows: [["x", "1"]]\n')
            prof = refcheck.profile_spec(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        n, got = prof[0], prof[1]
        self.assertEqual(n, 1)
        self.assertEqual(got.get("emphasis"), 1.0, got)


class FifteenthSixteenthBlindTrials(unittest.TestCase):
    """Blind trial 15 (regression) / 16 (systems paper) -- multi-file manuscripts, macros, suffixes, gaps in the checks."""

    def test_read_paper_follows_inputs_and_expands_macros(self):
        """A/B -- not following `\\input` reduced a multi-file paper to "one section," and `\\System{}` turned into a blank."""
        tmp = tempfile.mkdtemp()
        try:
            deckspec.spit(os.path.join(tmp, "main.tex"),
                          "\\newcommand{\\Sys}[0]{{Relay}}\n\\section{Intro}\n\\input{body}\n"
                          "% \\input{ghost}\n")
            deckspec.spit(os.path.join(tmp, "body.tex"),
                          "\\section{Design}\n\\Sys{} runs 71 cells.\n")
            got = deckspec.read_paper(os.path.join(tmp, "main.tex"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("\\section{Design}", got)
        self.assertIn("Relay", got)
        self.assertNotIn("\\Sys", got)
        self.assertNotIn("ghost", got)

    def test_deckcheck_keeps_numbers_before_words_like_in(self):
        """G -- "81.5 in dry cells" had its `81.5 in` stripped out as a dimension, so section A never saw the number."""
        got = deckcheck.screen_text("Yield 81.5 in dry cells, 6.9 examples, 1.5in wide")
        self.assertIn("81.5", got)
        self.assertIn("6.9", got)
        self.assertFalse(deckcheck.has(got, "1.5"), got)

    def test_deckcheck_drops_column_specs(self):
        """K -- a table's column spec `llrr` printed as a word absent from the manuscript."""
        got = deckcheck.screen_text("\\begin{tabular}{llrr} a & b \\end{tabular}")
        self.assertNotIn("llrr", got)

    def test_bar_numbers_read_suffixes(self):
        """D -- `208K` was read as 208, silently making the bar wrong."""
        import build_figs
        self.assertEqual(build_figs.num("208K"), 208000.0)
        self.assertAlmostEqual(build_figs.num("2.16M"), 2160000.0)
        self.assertEqual(build_figs.num("10ms"), 10.0)
        self.assertEqual(build_figs.num("-11.7"), -11.7)

    def test_outcheck_reads_question_and_answer(self):
        """E -- `ask: [{q, a}]` was searched for as a dict repr, so it always came out "missing"."""
        import outcheck
        got = outcheck.frags({"ask": [{"q": "Why dry?", "a": "It lasts."}, "Plain?"]})
        self.assertIn(("ask", "Why dry?"), got)
        self.assertIn(("ask", "It lasts."), got)
        self.assertIn(("ask", "Plain?"), got)

    def test_timing_counts_the_minus(self):
        """H -- `-12.3` was counted as 3 words (spoken aloud, "minus" makes it 4)."""
        import timing
        self.assertEqual(timing.words("-7.4"), timing.words("7.4") + 1)

    def test_blank_legend_with_n_a(self):
        """L -- "n/a: not run" was not recognized as an explanation."""
        import prose_audit
        self.assertTrue(prose_audit.EXPLAINS_BLANK.search("n/a: the cell was not built"))

    def test_scaffold_reads_ieee_author_blocks(self):
        """M -- the first affiliation line of an IEEE author block got attached to the author name."""
        import scaffold
        tmp = tempfile.mkdtemp()
        try:
            src = ("\\documentclass{IEEEtran}\\title{Cells}\n"
                   "\\author{\\IEEEauthorblockN{Ann Lee, Bo Kim}\n"
                   "\\IEEEauthorblockA{Cell Lab\\\\ North Institute\\\\ ann@lab.org}}\n"
                   "\\begin{document}\\section{Results}Text.\\end{document}\n")
            p = os.path.join(tmp, "p.tex")
            deckspec.spit(p, src)
            o = os.path.join(tmp, "s.yaml")
            with redirect_stdout(io.StringIO()):
                scaffold.build(p, o)
            got = deckspec.slurp(o)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn('author: "Ann Lee, Bo Kim"', got)
        self.assertIn('institute: ["Cell Lab", "North Institute"]', got)


class GraphAndDots(unittest.TestCase):
    """Two figure kinds that a different kind of paper demanded -- crossing edges (graph), and a narrow range with an order-of-magnitude gap (dots)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_graph_draws_nodes_edges_and_a_legend(self):
        import build_figs
        d = {"kind": "graph",
             "nodes": [{"id": "p", "label": "plan", "col": 1, "row": 0, "shape": "oval"},
                       {"id": "a", "label": "cell one", "col": 0, "row": 1},
                       {"id": "b", "label": "cell two", "col": 2, "row": 1}],
             "edges": [{"from": "p", "to": "a", "kind": "control"},
                       {"from": "a", "to": "b", "kind": "state", "label": "rack"},
                       {"from": "p", "to": "zz"}]}
        warn = []
        tmp = tempfile.mkdtemp()
        try:
            words, _ = build_figs.draw_diagram(d, os.path.join(tmp, "g.png"), warn=warn)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "g.png")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        for w in ("plan", "cell one", "rack", "control", "state"):
            self.assertIn(w, words)
        self.assertTrue(any("zz" in w for w in warn), warn)

    def test_graph_needs_nodes(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - kind: figure\n    title: "T"\n'
                             '    diagram: {kind: graph, edges: []}\n')
            with self.assertRaises(ValueError):
                deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _dots(self, rows, log=False):
        import build_figs
        import figs_extra
        import matplotlib.pyplot as plt
        got = {}
        real = plt.Axes.set_xlim

        def spy(ax, *a, **k):
            if len(a) == 2:
                got["xlim"] = a
            return real(ax, *a, **k)
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(plt.Axes, "set_xlim", spy):
                seen = figs_extra.draw_dots({"header": ["", "dry", "wet"], "rows": rows},
                                            os.path.join(tmp, "d.png"), (4.0, 2.5), [],
                                            build_figs, "hours", log)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return got["xlim"], [t for _, t in seen]

    def test_dots_axis_follows_the_data(self):
        """A bar must start at 0, which made the difference within 21-25 invisible (trial 14)."""
        (lo, hi), said = self._dots([["A", "24.5", "25.0"], ["B", "21.4", "22.9"]])
        self.assertGreater(lo, 15)
        self.assertIn("21.4", said)

    def test_dots_log_axis_for_orders_of_magnitude(self):
        (lo, hi), said = self._dots([["batch", "22.6K", "2.16M"]], log=True)
        self.assertLess(lo, 22600)
        self.assertGreater(hi, 2160000)
        self.assertIn("2.16M", said)

    def test_bars_refuse_log(self):
        import build_figs
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - kind: figure\n    title: "T"\n'
                             '    chart: {from: self, kind: bars, log: true}\n'
                             '    table:\n      header: [a, b]\n      rows: [["x", "8"], ["y", "9"]]\n')
            with redirect_stdout(io.StringIO()):
                _, _, warn = build_figs.build(p, tmp, os.path.join(tmp, "v.txt"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(any("dots" in w for w in warn), warn)


class SeventeenthBlindTrial(unittest.TestCase):
    """Blind trial 17 (compiler paper) -- a paper whose results live only in figures, multiplier/percentage figures, and checker noise."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _load(self, text):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + text)
            return deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_highlight_draws_a_box_over_the_image(self):
        """A pasted-in figure gave no indication of where to look -- the audience had to read all twenty bars."""
        tex = build_deck.image_tex("max width=4cm", "p.png",
                                   {"highlight": {"x": 0.8, "y": 0.1, "w": 0.1, "h": 0.5,
                                                  "label": "here"}})
        self.assertIn("tikzpicture", tex)
        self.assertIn("rectangle", tex)
        self.assertIn("here", tex)
        # stays within the grayscale color space -- so metropolis's RGB text color doesn't shift the PDF figure's colors (trial 34)
        self.assertEqual(build_deck.image_tex("max width=4cm", "p.png", {}),
                         "{\\color{black}\\adjincludegraphics[max width=4cm]{p.png}}")

    def test_highlight_is_validated(self):
        self._load('  - kind: figure\n    title: "T"\n    figure:\n      path: p.png\n'
                   '      highlight: {x: 0.1, y: 0.2, w: 0.3, h: 0.4}\n')
        with self.assertRaises(ValueError):
            self._load('  - kind: figure\n    title: "T"\n    figure:\n      path: p.png\n'
                       '      highlight: {x: 12, y: 0.2, w: 0.3, h: 0.4}\n')
        with self.assertRaises(ValueError):
            self._load('  - kind: figure\n    title: "T"\n    figure:\n      path: p.png\n'
                       '      highlight: {x: 0.1, y: 0.2, w: 0.3, h: 0.4, colour: red}\n')

    def test_result_numbers_count_multipliers_and_percentages(self):
        """Counting decimals only left `40×`/`70%` out of the manuscript's numbers. Dimensions (`16×16`) are excluded."""
        got = deckspec.result_numbers(
            "up to 40$\\times$ faster, 1.6--3.8$\\times$, 70\\% to 88\\%, "
            "a 16$\\times$16 tile, a 4x4 kernel, 12.3 hours")
        self.assertEqual(got, ["40", "1.6", "3.8", "70", "88", "12.3"])

    def test_legend_is_refused_where_it_is_not_drawn(self):
        """`grid` accepted `legend` and then dropped it (the second such case, after pipeline)."""
        with self.assertRaises(ValueError):
            self._load('  - kind: figure\n    title: "T"\n    diagram:\n      kind: grid\n'
                       '      cols: [a, b]\n      boxes: [x, y]\n      legend: {a: "one"}\n')

    def test_a_long_title_without_a_listed_verb_is_a_sentence(self):
        import prose_audit
        self.assertTrue(prose_audit.is_claim("an RPC device pool feeds the optimizer its measurements"))
        self.assertFalse(prose_audit.is_claim("per-valve readings"))

    def test_sizes_and_split_terms_are_not_unspoken_jargon(self):
        import prose_audit
        self.assertFalse(prose_audit.looks_like_jargon("4x4"))
        self.assertFalse(prose_audit.looks_like_jargon("x4"))
        sl = [{"n": 1, "say": ["We use an RPC-based pool; IC, OC are channels."],
               "screen": "RPC IC/OC 4x4"}]
        self.assertEqual(prose_audit.unspoken_terms(sl), [])

    def test_small_type_warnings_group_per_figure(self):
        import build
        with redirect_stdout(io.StringIO()):
            got = build._say("x", ["a.png: text is 7.4pt on screen (floor 8pt): 'one'",
                                   "a.png: text is 6.5pt on screen (floor 8pt): 'two'",
                                   "other"])
        self.assertEqual(len(got), 2)
        self.assertTrue(any("2" in w and "a.png" in w for w in got), got)

    def test_overflow_feedback_reaches_pasted_figures(self):
        """Feedback only applied to generated figures, so a slide with a pasted-in figure overflowed by the same amount no matter how many times it was fed back."""
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - kind: figure\n    title: "T"\n'
                             '    figure: {path: p.png}\n')
            from PIL import Image
            os.makedirs(os.path.join(tmp, "figs"))
            for d_ in (tmp, os.path.join(tmp, "figs")):
                Image.new("RGB", (40, 30), (200, 200, 200)).save(os.path.join(d_, "p.png"))
            o = os.path.join(tmp, "t.tex")
            deckspec.EXTRA_RESERVE.clear()
            build_deck.build(p, o)
            before = deckspec.slurp(o)
            deckspec.EXTRA_RESERVE[1] = 0.5
            build_deck.build(p, o)
            after = deckspec.slurp(o)
        finally:
            deckspec.EXTRA_RESERVE.clear()
            shutil.rmtree(tmp, ignore_errors=True)
        h = lambda s: float(re.search(r"max height=([\d.]+)cm\]\{p\.png\}", s).group(1))
        self.assertAlmostEqual(h(before) - h(after), 0.5 * 2.54, 2)


class OpenDefectsFromEarlierTrials(unittest.TestCase):
    """Defects noted and deferred from blind trials 11-17 -- closed off all at once."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_figure_warning_floor_matches_fitcheck(self):
        """For the same text, `build` said "too small" while `fitcheck` said "fine" (happened five times)."""
        import build_figs
        self.assertAlmostEqual(build_figs.WARN_PT, round(build_figs.BODY_PT * 0.7, 1))
        warn = []
        build_figs._note_size(7.2, "x", warn, [], "f.png")
        self.assertEqual(warn, [])
        build_figs._note_size(6.5, "y", warn, [], "f.png")
        self.assertEqual(len(warn), 1)

    def test_flow_boxes_share_one_size(self):
        """One long label alone shrank to 6.5pt while the rest stayed at 10pt -- one grid, one size."""
        import build_figs
        pt = build_figs.common_pt(["plan", "measure the cells under a long protocol name"],
                                  1.2, 0.5, 10.0)
        self.assertLessEqual(pt, 10.0)
        self.assertEqual(build_figs.common_pt(["a", "b"], 1.2, 0.5, 10.0), 10.0)

    def test_scaffold_splits_author_lines_from_affiliations(self):
        """With two lines of authors and numbered affiliations (`$ ^1$`), the second author line got mixed into the affiliations (trial 17)."""
        import scaffold
        tmp = tempfile.mkdtemp()
        try:
            src = ("\\documentclass{article}\\title{Cells}\n\\author{\n\\small{\n"
                   "Ann Lee$ ^1$, \\ \\ Bo Kim$ ^{1, 2}$\\\\\nCy Park$ ^2$}\n\n"
                   "\\small{$ ^1$Cell Lab, North University}\\\\\n"
                   "\\small{$ ^2$ South Institute}\n}\n"
                   "\\begin{document}\\section{Results}"
                   "\\begin{tabular}{ll}\\parbox[l]{.27\\linewidth}{Method} & Cost \\\\\n"
                   "a & b \\\\\nc & d \\\\\n\\end{tabular}\\end{document}\n")
            p = os.path.join(tmp, "p.tex")
            deckspec.spit(p, src)
            o = os.path.join(tmp, "s.yaml")
            with redirect_stdout(io.StringIO()):
                scaffold.build(p, o)
            got = deckspec.slurp(o)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn('author: "Ann Lee, Bo Kim, Cy Park"', got)
        self.assertIn('institute: ["Cell Lab, North University", "South Institute"]', got)
        self.assertIn('"Method"', got)
        self.assertNotIn(".27", got)

    def test_hyphenated_paper_words_count_by_part(self):
        self.assertEqual(deckcheck.coined_terms("vendor vendor vendor",
                                                "uses vendor-specific code", 3), [])

    def test_figure_numbers_beyond_the_paper_fail(self):
        """A manually mistyped "Fig. 16" passed only because an unrelated 16 happened to be present (trial 17)."""
        tmp = tempfile.mkdtemp()
        try:
            deckspec.spit(os.path.join(tmp, "paper.tex"),
                          "\\begin{figure}x\\end{figure}\\begin{figure}y\\end{figure} 16 cells")
            deckspec.spit(os.path.join(tmp, "talk.tex"),
                          "\\begin{frame}From the paper, Fig. 16 and Fig. 2\\end{frame}")
            deckspec.spit(os.path.join(tmp, "c.yaml"),
                          "source: [paper.tex]\nderivative: {deck: talk.tex}\n")
            with redirect_stdout(io.StringIO()):
                fail, _ = deckcheck.run(deckcheck.Stuff(deckcheck.load(os.path.join(tmp, "c.yaml"))))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(fail.get("figure/table numbers"), 1)

    def test_timing_reads_hyphenated_tokens_part_by_part(self):
        import timing
        self.assertEqual(timing.words("dry-wet"), 2)
        self.assertGreaterEqual(timing.words("state-of-the-art"), 4)

    def test_question_slide_is_not_in_the_emphasis_denominator(self):
        import refcheck
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD +
                          '  - kind: standout\n    lead: "Which one?"\n'
                          '    big: [{text: "dry"}, {text: "wet"}]\n    gap: "or"\n'
                          '  - title: "A"\n    bullets: ["**x**"]\n')
            n, got, _ = refcheck.profile_spec(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(got["emphasis"], 1.0)

    def test_diffcheck_separates_values_said_in_the_script(self):
        """A value spoken in the script was counted as "an unused value," exiting with 1 (trials 11/16/17)."""
        import diffcheck
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "p.tex")
            deckspec.spit(src, "The cell holds 81.5 hours and 63.8 cycles.")
            with redirect_stdout(io.StringIO()) as f:
                bad = diffcheck.against_source("81.5 hours", src, 5,
                                               "It lasts 63.8 cycles.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(bad, 0, f.getvalue())
        self.assertIn("63.8", f.getvalue())

    def test_pptx_check_sees_tables_and_line_spacing(self):
        """Text printed over a table, and a bullet overflowing because of line spacing, both went uncaught by `fitcheck`."""
        import fitcheck
        from pptx import Presentation
        from pptx.util import Inches, Pt
        prs = Presentation()
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        tb = sl.shapes.add_table(3, 2, Inches(1), Inches(1), Inches(4), Inches(1.5))
        box = sl.shapes.add_textbox(Inches(1), Inches(2.0), Inches(4), Inches(0.4))
        box.text_frame.text = "a note that sits on the table"
        box.text_frame.paragraphs[0].runs[0].font.size = Pt(14)
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "t.pptx")
            prs.save(path)
            bad = fitcheck.check_pptx(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(any(k == "overlap" for _, k, _ in bad), bad)


class PdfOnlyPaper(unittest.TestCase):
    """A PDF-only paper (an arXiv manuscript that's just one line of `\\includepdf`) could not even be read at the first step (prep for trial 18)."""

    @staticmethod
    def make_pdf(path):
        import fitz
        doc = fitz.open()
        body = ("The cells were charged at a fixed rate and held at rest for one hour "
                "before each reading was taken from the gauge.")
        for k in range(3):
            pg = doc.new_page(width=612, height=792)
            pg.insert_text((72, 30), "Workshop on Cell Chemistry", fontsize=8)
            pg.insert_text((300, 770), str(k + 1), fontsize=8)
            y = 90
            if k == 0:
                pg.insert_text((72, y), "Slow Charging Keeps Cells Cool", fontsize=18)
                y += 30
                pg.insert_text((72, y), "Ann Lee  North University", fontsize=10)
                y += 30
                pg.insert_text((72, y), "ABSTRACT", fontsize=12)
                y += 20
            pg.insert_text((72, y), "%d  RESULTS PART %d" % (k + 1, k + 1),
                           fontsize=10, fontname="hebo")
            y += 20
            pg.insert_text((72, y), body, fontsize=10)
            y += 14
            pg.insert_text((72, y), body, fontsize=10)
            if k == 1:
                pg.draw_rect(fitz.Rect(100, 300, 400, 450), color=(0, 0, 1))
                pg.insert_text((120, 440), "charge rate", fontsize=7)
                pg.insert_text((72, 475), "Figure 1: Temperature rises with charge rate.",
                               fontsize=9)
                pg.insert_text((72, 520), "Fig. 1. is referred to here in the body text.",
                               fontsize=10)
        doc.save(path)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pdf = os.path.join(self.tmp, "paper.pdf")
        self.make_pdf(self.pdf)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_headings_title_and_running_lines(self):
        import pdf_paper
        md = pdf_paper.to_markdown(pdf_paper.fitz.open(self.pdf))
        heads = [ln for ln in md.splitlines() if ln.startswith("#")]
        self.assertEqual(heads[0], "# Slow Charging Keeps Cells Cool")
        self.assertIn("## ABSTRACT", heads)
        self.assertIn("## RESULTS PART 2", heads)
        self.assertNotIn("## Ann Lee  North University", heads)   # the author line is not a heading
        # a header repeated on every page keeps only the first page's copy (the venue and year live there)
        self.assertEqual(md.count("Workshop on Cell Chemistry"), 1)

    def test_figure_is_cut_at_its_caption_and_body_mentions_are_not_captions(self):
        import pdf_paper
        got, missed = pdf_paper.figure_crops(pdf_paper.fitz.open(self.pdf),
                                             os.path.join(self.tmp, "figs"))
        self.assertEqual([g[0] for g in got], [1])
        self.assertEqual(missed, [])
        from PIL import Image
        with Image.open(got[0][1]) as im:
            w, h = im.size
        # the rectangle (300x150pt) plus margin -- the caption line (475) is not included
        self.assertLess(h / w, 0.62)

    def test_checkers_and_scaffold_read_the_pdf(self):
        import scaffold
        text = deckspec.read_paper(self.pdf)
        self.assertIn("charged at a fixed rate", text)
        self.assertEqual(scaffold.sniff(self.pdf, text), "plain")
        secs = scaffold.sections(text, "plain")
        self.assertEqual(secs[0][:2], (1, "ABSTRACT"))        # the paper's title is not a section
        self.assertTrue(all(s[0] == 1 for s in secs))

    def test_single_hash_title_in_markdown_is_not_a_section(self):
        import scaffold
        secs = scaffold.sections("# Cells\n\n## Method\nx\n\n## Results\ny\n", "plain")
        self.assertEqual([(s[0], s[1]) for s in secs], [(1, "Method"), (1, "Results")])



class VectorFigureFormats(unittest.TestCase):
    """PowerPoint cannot embed a PDF or EPS figure. A LaTeX paper's figures are usually PDF (prep for trial 19)."""

    EPS = ("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 50\n"
           "newpath 10 10 moveto 90 40 lineto 2 setlinewidth stroke showpage\n%%EOF\n")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pptx_uses_a_png_made_from_a_pdf_figure(self):
        import fitz
        import build_pptx
        pdf = os.path.join(self.tmp, "cells.pdf")
        d = fitz.open()
        pg = d.new_page(width=200, height=100)
        pg.draw_rect(fitz.Rect(20, 20, 180, 80), color=(1, 0, 0))
        d.save(pdf)
        got = build_pptx.raster(pdf)
        self.assertTrue(got.endswith("cells.png"), got)
        self.assertTrue(os.path.isfile(got))
        self.assertEqual(build_pptx.raster(os.path.join(self.tmp, "a.png")),
                         os.path.join(self.tmp, "a.png"))

    def test_deck_names_the_pdf_for_an_eps_figure(self):
        import build_deck
        self.assertEqual(build_deck.tex_img("figs/gauge.eps"), "figs/gauge.pdf")
        self.assertEqual(build_deck.tex_img("gauge.png"), "gauge.png")

    @unittest.skipUnless(shutil.which("epstopdf"), "epstopdf not installed")
    def test_eps_is_converted_once_for_both_outputs(self):
        import build
        import build_pptx
        eps = os.path.join(self.tmp, "gauge.eps")
        deckspec.spit(eps, self.EPS)
        with redirect_stdout(io.StringIO()):
            pdf = build.eps_to_pdf(eps)
        self.assertTrue(pdf and os.path.isfile(pdf))
        self.assertTrue(build_pptx.raster(eps).endswith("gauge.png"))



class EighteenthNineteenthBlindTrials(unittest.TestCase):
    """Blind trial 18 (PDF-only manuscript) / 19 (EPS/formulas) -- starting with a defect both trials found independently."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_numbers_with_two_or_more_decimals_are_checked(self):
        """12.29 and 0.999 were outside the reach of section A's check -- not a pass, just never looked at."""
        self.assertEqual(deckcheck.decimals("12.29 and 0.999 and 6.25"),
                         {"12.29", "0.999", "6.25"})

    def test_selftest_plants_a_two_decimal_canary(self):
        names = [c[0] for c in deckcheck._canaries(mock.Mock(cfg={}, pats=[], D={}, spoken=""))]
        self.assertTrue(any("second decimal place" in n for n in names), names)

    def test_highlight_drawing_code_is_not_screen_text(self):
        """TikZ coordinates were counted as numbers, and `rectangle`/`width` as words, so the skill flagged its own output."""
        tex = (r"\begin{tikzpicture}\node[anchor=south west,inner sep=0] (im) "
               r"{\adjincludegraphics[max width=\linewidth]{a.png}};"
               r"\begin{scope}[x={(im.south east)},y={(im.north west)}]"
               r"\draw[mHi,line width=1.4pt] (0.125,0.250) rectangle (0.375,0.500);"
               r"\node[mHi,anchor=south west] at (0.125,0.500) {dry cells};"
               r"\end{scope}\end{tikzpicture}"
               "\n\\setsansfont{Some Font}\n\\begin{adjustbox}{max width=\\textwidth}x\\end{adjustbox}")
        self.assertEqual(deckcheck.decimals(deckcheck.screen_text(tex)), set())
        words = deckcheck.term_text(tex)
        for w in ("rectangle", "width", "Some", "Font"):
            self.assertNotIn(w, words)
        self.assertIn("dry cells", words)

    def test_highlight_without_mark_is_neutral_not_red(self):
        import build_deck
        tex = build_deck.image_tex("max width=1cm", "a.png",
                                   {"highlight": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}})
        self.assertIn("mHi", tex)
        self.assertNotIn("mHit", tex)

    def test_highlight_mark_is_validated(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - title: "A"\n    figure: {path: a.png, highlight: '
                             '{x: 0.1, y: 0.1, w: 0.2, h: 0.2, mark: red}}\n')
            with self.assertRaises(ValueError):
                deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_build_uses_the_engine_the_spec_names(self):
        import build
        with mock.patch("shutil.which", return_value=None) as w, \
                redirect_stdout(io.StringIO()):
            self.assertFalse(build._latex("t.tex", ".", "xelatex"))
        w.assert_called_with("xelatex")

    def test_greek_and_math_reach_the_pptx_as_symbols(self):
        m = deckspec.math_to_text
        self.assertEqual(m(r"$\beta_1$"), "β₁")
        self.assertEqual(m(r"$\lambda \to \infty$"), "λ → ∞")
        self.assertEqual(m(r"$\frac{1}{2}$"), "1/2")
        self.assertEqual(m(r"$\tilde{X}$"), "X̃")
        self.assertEqual(m(r"$\bolds{q=20\%}$"), "q=20%")      # an unknown macro's argument is treated as plain text
        self.assertEqual(m(r"$\phantom{0}99$"), "99")

    def test_pdflatex_gets_greek_as_math_and_latin_accents_pass(self):
        import build_deck
        self.assertIn(r"$\beta$", build_deck.esc("β"))
        self.assertIn(r"$\Sigma$", build_deck.esc("Σ"))
        warn = []
        build_deck.symbols("Candès, β", warn, "x")
        self.assertEqual(warn, [])

    def test_figure_labels_keep_math_whole_and_avoid_tofu(self):
        import build_figs
        parts = build_figs._wrap(r"max of $\beta_2 u_{t-1}$ and more words here".split(), 2)
        self.assertTrue(all(p.count("$") % 2 == 0 for p in parts), parts)
        self.assertEqual(build_figs.mathify(r"E[$v$] (1 − β₂)"),
                         r"E[$v$] (1 $\minus$ $\beta_{2}$)")
        self.assertEqual(build_figs.mathify("no math β₂"), "no math β₂")

    def test_pptx_wrap_is_measured_with_the_font(self):
        """An average-width estimate came out one or two lines short of PowerPoint's actual wrap -- the builder and `fitcheck` shared the same error."""
        s = "Your gradients are sparse, and your objective keeps moving. Which optimizer?"
        w = deckspec.text_width_in(s, 25)
        self.assertEqual(deckspec.wrap_count(s, w * 0.99, 25), 2)   # tight between words
        big = deckspec.text_width_in("12.29%", 72, True)
        self.assertEqual(deckspec.wrap_count("12.29%", big * 0.99, 72, True), 1)  # a single word gets slack

    def test_pptx_scripts_become_baseline_runs(self):
        import build_pptx
        self.assertEqual(build_pptx._scripts_split("β₁ = 10⁻⁸"),
                         [("β", None), ("1", "-25000"), (" = 10", None), ("-8", "30000")])

    def test_fitcheck_sees_text_touching_text_and_skips_highlight_labels(self):
        import fitcheck
        from pptx import Presentation
        from pptx.util import Inches, Pt
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        sl = prs.slides.add_slide(prs.slide_layouts[6])

        def box(x, y, w, h, text, pt, ls=1.35):
            tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
            tb.text_frame.word_wrap = True
            p = tb.text_frame.paragraphs[0]
            p.line_spacing = ls
            r = p.add_run()
            r.text = text
            r.font.size, r.font.name = Pt(pt), "Arial"
            return tb
        long = ("The cells were charged at a fixed rate and then held at rest "
                "before each reading was taken from the gauge at the bench")
        box(0.5, 1.0, 4.3, 1.2, long, 20)                 # the frame's height fits two lines, but the actual text runs longer
        box(0.5, 2.45, 4.3, 0.6, "A note below the bullets", 17)
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "t.pptx")
            prs.save(path)
            bad = fitcheck.check_pptx(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(any(k == "overlap" for _, k, _ in bad), bad)

    def test_scaffold_reads_starred_tables_and_stacked_headers(self):
        import scaffold
        src = (r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}lcc@{}}\hline"
               "\n& \\textbf{Charge} & \\textbf{Heat}\\\\\n& (per hour) & (degrees)\\\\\\hline\n"
               "Dry cell & 12.25 & 6.25\\\\\nWet cell & 14.75 & \\phantom{0}4.0\\\\\n\\hline"
               "\\end{tabular*}\\vspace*{1.5pt}\n"
               r"\begin{tabular}{cc}\includegraphics{a.eps}&\includegraphics{b.eps}\\"
               r"x&y\\\end{tabular}")
        got, skipped = scaffold.tables(src)
        self.assertEqual(len(got), 1)
        align, head, rows, _ = got[0]
        self.assertEqual(align, "lcc")
        self.assertEqual(head, ["", "Charge (per hour)", "Heat (degrees)"])
        self.assertEqual(rows[1][2], "4.0")
        self.assertIn("a figure-layout tabular", skipped)
        self.assertNotIn("1.5", scaffold.numbers(r"\vspace*{1.5pt} we ran 12.25 cycles"))

    def test_prose_audit_reads_the_whole_closing_slide(self):
        import prose_audit
        slides = [{"kind": "standout", "title": "", "lead": "",
                   "lines": ["Slow charging keeps the cells cool"], "big": None}]
        self.assertEqual(prose_audit.thesis_coverage(slides, "Slow charging keeps cells cool"), 1.0)
        self.assertFalse(prose_audit.looks_like_jargon("t-1"))
        self.assertTrue(prose_audit.looks_like_jargon("HV2"))



class NineteenthTrialFigureFit(unittest.TestCase):
    """Blind trial 19 -- two figure-fitting cases."""

    def test_spanned_strip_label_needs_only_its_span(self):
        """Trying to fit a nine-cell-wide label into one cell produced a false positive: "falls short by 4.45 inches"."""
        import build_figs
        d = {"kind": "strip", "rows": [{"label": "cells", "cells": [
            {"label": "at least ninety charged", "span": 9, "mark": "a"},
            {"label": "flat", "span": 1, "mark": "c"}]}]}
        warn = []
        tmp = tempfile.mkdtemp()
        try:
            build_figs.draw_strip(d, os.path.join(tmp, "s.png"), (5.5, 1.9), warn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertFalse([w for w in warn if "falls short by" in w], warn)

    def test_overflowing_text_uses_the_fewest_lines_that_fit_the_width(self):
        """Drawn as two lines in a one-line slot, the text spilled upward and got clipped (a table corner label)."""
        import build_figs
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        try:
            build_figs.fit_text(fig, ax, 50, 50, 2.5, 0.05, "charged cells only", 8.0,
                                max_lines=2)
            txt = [t.get_text() for t in ax.texts]
        finally:
            plt.close(fig)
        self.assertEqual(txt, ["charged cells only"])



class TwentiethToTwentySecondTrials(unittest.TestCase):
    """Blind trial 20 (LIGO, two-column PDF) / 21 (Adam retest) / 22 (DML, econometrics LaTeX)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_reference_numbers_and_identifiers_are_not_results(self):
        got = deckspec.result_numbers(
            "rate 0.001 and 0.999; see Lemma 10.2, section 11.7, Table~9.7, "
            "arXiv:1502.01589, doi 10.1103/PhysRevLett, then 7.25 cells")
        self.assertEqual(got, ["0.001", "0.999", "7.25"])

    def test_long_integers_and_thousands_are_checked(self):
        """Only checking up to four digits left a five-digit dollar figure in a table outside the check (trial 22)."""
        tmp = tempfile.mkdtemp()
        try:
            deckspec.spit(os.path.join(tmp, "paper.md"), "The bonus was 19,559 dollars.")
            deckspec.spit(os.path.join(tmp, "talk.md"), "It was 19559 and then 11794.")
            deckspec.spit(os.path.join(tmp, "c.yaml"),
                          "source: [paper.md]\nsyntax: plain\nderivative: {deck: talk.md}\n")
            with redirect_stdout(io.StringIO()):
                fail, _ = deckcheck.run(deckcheck.Stuff(deckcheck.load(os.path.join(tmp, "c.yaml"))))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(fail.get("unsourced numbers"), 1)          # only 11794

    def test_pdf_crop_does_not_swallow_body_text(self):
        """Cropping used to start right at the page-header rule, making an entire section vanish from paper.md (trial 20)."""
        import fitz
        import pdf_paper
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "p.pdf")
            doc = fitz.open()
            for k in range(3):
                pg = doc.new_page(width=612, height=792)
                pg.insert_text((72, 30), "Cell Letters", fontsize=8)
                pg.draw_line(fitz.Point(72, 36), fitz.Point(540, 36), width=0.5)
                y = 80
                for i in range(6):
                    pg.insert_text((72, y), "The dry cells were charged slowly and held at rest "
                                   "before reading %d." % i, fontsize=10)
                    y += 14
                if k == 1:
                    pg.draw_rect(fitz.Rect(100, 200, 400, 380), color=(0, 0, 1))
                    pg.insert_text((72, 400), "Figure 1: Temperature against charge rate.",
                                   fontsize=9)
            doc.save(path)
            d = fitz.open(path)
            md = pdf_paper.to_markdown(d)
            reg = pdf_paper.figure_regions(d)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(md.count("before reading 5."), 3)
        self.assertGreater(reg[1][0].y0, 150)

    def test_pdf_text_repairs(self):
        import pdf_paper
        self.assertEqual("\ufb01rst".translate(pdf_paper._LIGATURES), "first")
        self.assertEqual("36\u00fe5".translate(pdf_paper._ADVP), "36+5")

    def test_math_edge_cases(self):
        m = deckspec.math_to_text
        self.assertEqual(m(r"$\hat\mu$"), "\u03bc\u0302")
        self.assertEqual(m(r"$\ell_1$"), "\u2113\u2081")
        self.assertEqual(m(r"$g_0,\ m_0$"), "g\u2080, m\u2080")
        self.assertEqual(m(r"$\beta_1^t$"), "\u03b2\u2081\u1d57")
        self.assertEqual(m("gains (in $)"), "gains (in $)")      # an unpaired $ is treated as plain text

    def test_deck_escapes_stray_dollars_and_combining_accents(self):
        import build_deck
        self.assertIn(r"\$", build_deck.esc("gains (in $)"))
        self.assertIn(r"$\hat{m}$", build_deck.esc("m\u0302 fits"))
        self.assertIn(r"$\tilde{\theta}$", build_deck.esc("\u03b8\u0303 here"))

    def test_arithmetic_big_values_stay_big(self):
        self.assertEqual(deckspec.big_pt("36 + 29"), deckspec.big_pt("62"))

    def test_crop_is_validated_and_cut(self):
        from PIL import Image
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "a.png")
            Image.new("RGB", (400, 200), "white").save(src)
            dst = deckspec.crop_image(src, {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0})
            with Image.open(dst) as im:
                self.assertEqual(im.size, (200, 200))
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - title: "A"\n    figure: {path: a.png, crop: '
                             '{x: 0.8, y: 0, w: 0.5, h: 1}}\n')
            with self.assertRaises(ValueError):
                deckspec.load(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_declared_pictures_are_not_pasted_charts(self):
        import prose_audit
        slides = [{"n": 3, "figure": {"path": "sites.png", "picture": "map of the two sites"}}]
        self.assertEqual(prose_audit.pasted_paper_figures(slides), [])

    def test_diffcheck_omits_declared_values_and_the_appendix(self):
        import diffcheck
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "p.md")
            deckspec.spit(src, "# T\n\n## Results\n\nThe cells held 81.25 hours and 63.75 cycles."
                               + " filler words" * 400 + "\n\n## Appendix\n\nProof uses 12.125.\n")
            with redirect_stdout(io.StringIO()) as f:
                bad = diffcheck.against_source("81.25 hours", src, 5, "", ["63.75"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertNotIn("12.125", f.getvalue())
        self.assertIn("63.75", f.getvalue())
        self.assertEqual(bad, 0, f.getvalue())

    def test_scaffold_reads_every_author_and_stops_at_the_appendix(self):
        import scaffold
        tmp = tempfile.mkdtemp()
        try:
            src = ("\\documentclass{article}\\title{Cells}\n\\author{Ann Lee, Bo Kim}\n"
                   "\\author{Cy Park}\n\\begin{document}\n\\section{Results \\ref{sec:x}}\nA\n"
                   "\\begin{tabular}{lc}\\hline Cell & Hours\\\\ \\hline Dry & 81.25\\\\ [0.08cm]\n"
                   "Wet & 63.75\\\\\n & \\\\ \\hline\\end{tabular}\n"
                   "\\section*{Appendix: Proofs}\nB\n\\section{Proof of Lemma 1}\nC\n"
                   "\\end{document}\n")
            p = os.path.join(tmp, "p.tex")
            deckspec.spit(p, src)
            o = os.path.join(tmp, "s.yaml")
            with redirect_stdout(io.StringIO()) as f:
                scaffold.build(p, o)
            got = deckspec.slurp(o)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn('author: "Ann Lee, Bo Kim, Cy Park"', got)
        self.assertNotIn("Proof of Lemma", got)
        self.assertNotIn("sec:x", got)
        self.assertNotIn("0.08cm", got)
        self.assertIn('["Wet", "63.75"]', got)
        self.assertNotIn('["", ""]', got)

    def test_fine_size_reaches_pane_text(self):
        import build_deck
        out = build_deck.pane_body({"size": "fine", "text": "a small note"}, None, "figs", [],
                                   {"n": 1}, "left")
        self.assertIn("\\scriptsize a small note", "".join(out))
        self.assertNotIn("footnotesize", "".join(out))

    def test_outcheck_reads_math_fragments_by_their_words(self):
        import outcheck
        body = outcheck.norm("the step is alpha times m over root v and it shrinks")
        self.assertTrue(outcheck.arrived("the step √(v̂ₜ) shrinks", body))



class TwentyThirdTrial(unittest.TestCase):
    """Blind trial 23 -- a regression test against the user's own paper."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_label_goes_where_it_covers_nothing(self):
        self.assertEqual(deckspec.label_place({"y": 0.30, "h": 0.2}), "above")
        self.assertEqual(deckspec.label_place({"y": 0.02, "h": 0.4}), "below")
        self.assertEqual(deckspec.label_place({"y": 0.0, "h": 0.98}), "inside")
        self.assertEqual(deckspec.label_place({"y": 0.5, "h": 0.2, "label_at": "inside"}), "inside")

    def test_a_contrast_on_one_slide_is_not_a_clash(self):
        import prose_audit
        one = [{"n": 4, "raw_screen": "fast charge costs capacity 31.5, slow charge capacity 4.25"}]
        self.assertEqual(prose_audit.contradicting_values(one), [])
        two = [{"n": 4, "raw_screen": "baseline 31.5"}, {"n": 7, "raw_screen": "baseline 29.5"}]
        self.assertEqual(len(prose_audit.contradicting_values(two)), 1)

    def test_an_empty_first_cell_under_a_name_means_same_as_above(self):
        import prose_audit
        slides = [{"n": 2, "tables": [{"rows": [["Dry cell", "fast", "31.5"],
                                                ["", "slow", "4.25"]]}]}]
        self.assertEqual(prose_audit.unexplained_blanks(slides), [])

    def test_pptx_table_leaves_room_for_its_bullets(self):
        """The table filled all the way down to the footnote line, so the bullets overlapped the footnote/fine print."""
        import build_pptx
        import fitcheck
        rows = "".join('        - ["cell %d", "%d.25", "yes"]\n' % (i, i) for i in range(9))
        spec = (self.HEAD + '  - kind: table\n    title: "All cells"\n    table:\n'
                '      header: ["Cell", "Hours", "Kept"]\n      size: small\n      rows:\n' + rows +
                '    bullets: ["Every cell kept its charge for the whole run of the test bench."]\n'
                '    fine: ["Hours are the median over three runs at the bench.",\n'
                '           "Kept means the cell stayed above the cut-off voltage."]\n')
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, spec)
            out = os.path.join(tmp, "t.pptx")
            with redirect_stdout(io.StringIO()):
                build_pptx.build(p, out)
            bad = fitcheck.check_pptx(out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertFalse([b for b in bad if b[1] == "overlap"], bad)



class TwentyFourthTwentyFifthTrials(unittest.TestCase):
    """Blind trial 24 (Markdown manuscript, JOSS) / 25 (survey paper)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def test_markdown_front_matter_and_figures_reach_the_skeleton(self):
        import scaffold
        src = ("---\ntitle: 'Charger kit: a status report'\nauthors:\n  - name: Ann Lee\n"
               "    affiliation: 1\n  - name: Bo Kim\n    affiliation: 2\naffiliations:\n"
               " - name: North Lab\n   index: 1\n - name: South Works\n   index: 2\n---\n\n"
               "# Summary\n\nThe kit charges cells.\n\n# Growth\n\nMore users.\n\n"
               "![Users per year (left) and sites (right).\\label{fig:u}](users.pdf)\n")
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "paper.md")
            deckspec.spit(p, src)
            o = os.path.join(tmp, "s.yaml")
            with redirect_stdout(io.StringIO()):
                scaffold.build(p, o, "plain")
            got = deckspec.slurp(o)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn('title: "Charger kit: a status report"', got)
        self.assertIn('author: "Ann Lee, Bo Kim"', got)
        self.assertIn('institute: ["North Lab", "South Works"]', got)
        self.assertIn('path: "users.pdf"', got)
        self.assertIn("Users per year (left)", got)
        self.assertNotIn("TODO(say it, don't label it): Summary\"\n    bullets", got.split("slides:")[0])

    def test_counts_and_ranks_are_results_but_lengths_are_not(self):
        got = deckspec.result_numbers("ranked 14th with 2000+ users and 400,000 downloads; "
                                      "width=0.45\\textwidth and \\vskip 0.25in")
        self.assertEqual(got, ["14", "2000", "400,000"])

    def test_check_marks_survive(self):
        import scaffold
        self.assertEqual(scaffold.clean(r"\ding{55} and $\checkmark$ and \ding{51}"), "✗ and ✓ and ✓")

    def test_pptx_notes_carry_what_to_say(self):
        import build_pptx
        from pptx import Presentation
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - title: "Cells"\n    bullets: ["dry"]\n'
                             '    cue: "Point at the dry cell."\n'
                             '    say: ["The dry cell kept its charge."]\n')
            out = os.path.join(tmp, "t.pptx")
            with redirect_stdout(io.StringIO()):
                build_pptx.build(p, out)
            notes = [sl.notes_slide.notes_text_frame.text for sl in Presentation(out).slides
                     if sl.has_notes_slide]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(any("kept its charge" in x and "Point at" in x for x in notes), notes)

    def test_script_heading_uses_the_gap_word(self):
        self.assertEqual(deckspec.big_text([{"text": "fast"}, {"text": "slow"}], "or"),
                         "fast  or  slow")

    def test_refcheck_counts_bullets_inside_parts(self):
        import refcheck
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.yaml")
            deckspec.spit(p, self.HEAD + '  - kind: columns\n    title: "Two sides"\n'
                             '    left: {parts: [{bullets: ["dry cells hold", "wet cells fade"]},'
                             ' {text: "compare the rows"}]}\n'
                             '    right: {text: "compare the columns"}\n')
            n, got, per = refcheck.profile_spec(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(per[0], 2.0)            # two bullets per slide -- counted even inside `parts`

    def test_grid_count_matches_rows_or_columns(self):
        import prose_audit
        s = {"n": 3, "raw_screen": "Three fixed patterns", "lead": "Three fixed patterns",
             "counts": [(u"grid columns", 3), (u"grid rows", 1)]}
        self.assertEqual(prose_audit.count_mismatch([s]), [])

    def test_table_note_is_left_aligned(self):
        import build_deck
        tex = build_deck.render_table({"header": ["a", "b"], "rows": [["1", "2"]],
                                       "note": "a note"}, [], "t")
        self.assertIn("\\raggedright", tex)

    def test_plural_ies_folds_to_y(self):
        self.assertEqual(deckcheck.fold("families"), deckcheck.fold("family"))



class TwentySixthTrial(unittest.TestCase):
    """Blind trial 26 (ICLR format, tables/Greek letters/chunks that aren't cells)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_iffalse_block_is_not_read(self):
        d = self._tmp()
        p = os.path.join(d, "p.tex")
        deckspec.spit(p, "Kept text.\n\\iffalse\nDropped 17.5 text.\n\\fi\nAfter.\n")
        src = deckspec.read_tex(p)
        self.assertIn("Kept text.", src)
        self.assertIn("After.", src)
        self.assertNotIn("17.5", src)

    def test_iclr_and_authors_split_into_names_and_places(self):
        d = self._tmp()
        p = os.path.join(d, "p.tex")
        deckspec.spit(p, "\\documentclass{article}\n\\title{Dry cells}\n"
                         "\\author{Ann Lee\\thanks{Equal.} " + chr(92) * 2 + " North Lab " +
                         chr(92) * 2 + " \\texttt{ann@x.org} \\And Bo Kim " + chr(92) * 2 +
                         " South Works}\n\\begin{document}\n\\maketitle\n"
                         "\\section{Intro}\nDry cells hold.\n\\end{document}\n")
        out = os.path.join(d, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(p, out)
        meta, _, _ = deckspec.load(out)
        self.assertEqual(meta["author"], "Ann Lee, Bo Kim")
        self.assertEqual(meta.get("institute"), ["North Lab", "South Works"])

    def test_meta_author_list_is_joined(self):
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, 'meta: {title: T, author: [Ann Lee, Bo Kim], venue: V, date: D}\n'
                         'slides:\n  - title: "Cells"\n    bullets: ["dry"]\n')
        meta, _, _ = deckspec.load(p)
        self.assertEqual(meta["author"], "Ann Lee, Bo Kim")

    def test_single_item_big_list_becomes_text(self):
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: standout\n    big: [{text: "Dry wins"}]\n')
        _, slides, _ = deckspec.load(p)
        self.assertEqual(slides[0]["big"], "Dry wins")

    def test_greek_letter_and_header_abbreviation_must_be_spoken(self):
        import prose_audit
        tab = {"header": ["Cell", "Temp."], "rows": [["dry", "hot"]]}
        mute = [{"n": 1, "title": "Cells", "screen": u"Cells at ε = 4.75",
                 "say": ["Dry cells hold."], "tables": [tab]}]
        got = [w for _n, w in prose_audit.unspoken_terms(mute)]
        self.assertIn(u"ε", got)
        self.assertIn("Temp.", got)
        said = [dict(mute[0], say=["At epsilon 4.75 the temperature column stays hot."])]
        got = [w for _n, w in prose_audit.unspoken_terms(said)]
        self.assertNotIn(u"ε", got)
        self.assertNotIn("Temp.", got)

    def test_merged_strip_cell_is_one_box(self):
        import build_figs
        d = self._tmp()
        spec = {"kind": "strip",
                "rows": [{"label": "row", "cells": [{"label": "A"},
                                                     {"label": "ninety", "span": 5, "merge": True}]}]}
        with mock.patch.object(build_figs, "_round", wraps=build_figs._round) as r:
            build_figs.draw_strip(spec, os.path.join(d, "a.png"), (5.51, 2.55), [])
            merged = r.call_count
        spec["rows"][0]["cells"][1].pop("merge")
        with mock.patch.object(build_figs, "_round", wraps=build_figs._round) as r:
            build_figs.draw_strip(spec, os.path.join(d, "b.png"), (5.51, 2.55), [])
            units = r.call_count
        self.assertEqual(units - merged, 4)          # five cells -> one box

    def test_middle_dot_becomes_math(self):
        import build_figs
        # this only applies to labels already mixed with math -- if a `$` is present, matplotlib draws the whole string as mathtext
        self.assertIn("\\cdot", build_figs.mathify(u"a·b at $x$"))

    def test_pptx_paragraphs_carry_their_end_mark_size(self):
        """Without a paragraph end mark on an empty cell, PowerPoint grows the row to 18pt (defect 7)."""
        import build_pptx
        import fitcheck
        from pptx import Presentation
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: table\n    title: "Cells"\n'
                         '    table:\n      header: ["Kind", "Temp"]\n'
                         '      rows: [["dry", "hot"], ["", "cold"]]\n'
                         '      note: "Temp is the case temperature."\n')
        out = os.path.join(d, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(p, out)
        tbl = [sh for sl in Presentation(out).slides for sh in sl.shapes
               if sh.has_table][0].table
        size = tbl.cell(1, 1).text_frame.paragraphs[0].runs[0].font.size.pt
        empty = tbl.cell(2, 0).text_frame.paragraphs[0]
        self.assertEqual(fitcheck.empty_para_pt(empty, size), size)
        # a file with no mark (an old build) is measured at 18pt -- this is what `fitcheck` uses to see the overlap
        from pptx.oxml.ns import qn
        for e in empty._p.findall(qn("a:endParaRPr")):
            empty._p.remove(e)
        self.assertEqual(fitcheck.empty_para_pt(empty, size), 18.0)

    def test_sentence_whose_numbers_are_all_on_screen_is_touched(self):
        import diffcheck
        d = self._tmp()
        src = os.path.join(d, "p.tex")
        deckspec.spit(src, "\\section{A}\nWe heuristically pick the knob at 3.85 for every run.\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source("Peak stays at knob 3.85", src, 5)
        part = buf.getvalue().split(u"the deck never touches at all")[1].split(u"**explains**")[0]
        self.assertIn(u"none", part)
        self.assertNotIn("heuristically", part)

    def test_crop_that_slices_labels_or_a_colour_band_is_reported(self):
        """Reports when a crop line cuts through text (trial 25) or crosses a color band (trial 26). Margins stay quiet."""
        from PIL import Image, ImageDraw
        d = self._tmp()
        im = Image.new("RGB", (400, 200), "white")
        g = ImageDraw.Draw(im)
        g.rectangle([10, 20, 180, 180], outline="black")           # left panel
        g.rectangle([220, 20, 390, 180], outline="black")          # right panel
        for k in range(12):                                         # a line of text -- crosses x=300
            g.rectangle([290, 30 + 12 * k, 310, 36 + 12 * k], fill="black")
        g.rectangle([360, 25, 375, 175], fill=(60, 60, 200))        # color band
        src = os.path.join(d, "f.png")
        im.save(src)
        self.assertEqual(deckspec.crop_cuts(src, {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0}), [])
        cut = deckspec.crop_cuts(src, {"x": 0.5, "y": 0.0, "w": 0.25, "h": 1.0})
        self.assertIn("right", [e for e, _r, _f in cut])            # cut through twelve lines of text
        band = deckspec.crop_cuts(src, {"x": 0.5, "y": 0.0, "w": 0.42, "h": 1.0})
        self.assertTrue(any(e == "right" and f >= 0.30 for e, _r, f in band), band)



class TwentySeventhTrial(unittest.TestCase):
    """Blind trial 27 (a methods paper -- a large comparison table, math notation, an appendix longer than the body)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def _scaffold(self, body):
        d = self._tmp()
        p = os.path.join(d, "p.tex")
        deckspec.spit(p, body)
        out = os.path.join(d, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(p, out)
        return out

    def test_author_block_drops_emails_and_version_note(self):
        NL = chr(92) * 2
        out = self._scaffold(
            "\\documentclass{article}\n\\title{Dry cells}\n"
            "\\author{Ann Lee \\qquad Bo Kim " + NL + " North Lab " + NL +
            " \\texttt{\\{ann, bo,} " + NL + " \\texttt{cho\\}@x.org} " + NL + " (Version 2)}\n"
            "\\begin{document}\n\\maketitle\n\\section{Intro}\nDry cells hold.\n\\end{document}\n")
        meta, _, _ = deckspec.load(out)
        self.assertEqual(meta["author"], "Ann Lee, Bo Kim")
        self.assertEqual(meta.get("institute"), "North Lab")

    def test_appendix_tables_become_backup_and_wrapfigure_is_a_figure(self):
        NL = chr(92) * 2
        tab = ("\\begin{tabular}{lr}\n\\toprule\nCell & Ah " + NL + "\n\\midrule\n"
               "dry & %s " + NL + "\nwet & %s " + NL + "\n\\bottomrule\n\\end{tabular}\n")
        out = self._scaffold(
            "\\documentclass{article}\n\\begin{document}\n\\section{Intro}\nDry cells hold.\n"
            "\\begin{wrapfigure}{r}{0.3\\textwidth}\\includegraphics{kit.pdf}"
            "\\caption{The kit.}\\end{wrapfigure}\n" + tab % ("7.25", "5.75") +
            "\\appendix\n\\section{Settings}\n" + tab % ("9.35", "4.35") + "\\end{document}\n")
        _, slides, _ = deckspec.load(out)
        tabs = [s for s in slides if s["kind"] == "table"]
        self.assertEqual(len(tabs), 2)
        self.assertFalse(tabs[0].get("backup"))
        self.assertTrue(tabs[1].get("backup"))                   # the appendix's table
        self.assertIn("kit.pdf", deckspec.slurp(out))             # wrapfigure

    def test_escaped_ampersand_multicolumn_and_condition_rows(self):
        NL = chr(92) * 2
        src = ("\\begin{tabular}{llrr}\n\\toprule\n"
               "Kind \\& Lot & Cells & \\multicolumn{2}{c}{Capacity} " + NL + "\n"
               " & count & dry & wet " + NL + "\n\\midrule\n"
               "A & 12 & 8.15 & \\textcolor{myred}{6.95} " + NL + "\n\\bottomrule\n\\end{tabular}")
        got, _ = scaffold.tables(src)
        align, head, rows, ragged = got[0]
        self.assertEqual(head, ["Kind & Lot", "Cells count", "Capacity dry", "Capacity wet"])
        self.assertEqual(rows[0], ["A", "12", "8.15", "6.95"])      # the color name is not left behind
        cond = ("\\begin{tabular}{lrr}\n\\toprule\nBatch & 32 & 16 " + NL + "\n"
                "Length & 512 & 256 " + NL + "\n\\midrule\n"
                "dry & 2.64 & 1.35 " + NL + "\n\\bottomrule\n\\end{tabular}")
        got, _ = scaffold.tables(cond)
        align, head, rows, ragged = got[0]
        self.assertIsNone(head)                                     # a condition row is not a header
        self.assertEqual(rows[0], ["Batch", "32", "16"])

    def test_text_subscript_stays_one_group(self):
        self.assertEqual(deckspec.math_to_text(r"$\text{Cell}_\text{large}$"), "Cell_large")
        self.assertEqual(deckspec.math_to_text(r"$x_1$"), "x₁")

    def test_chart_keys_the_kind_does_not_draw_are_refused(self):
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: figure\n    title: x\n'
                         '    table: {header: [a, b], rows: [[c, "8.15"]]}\n'
                         '    chart: {kind: heat, col_notes: ["dry"]}\n')
        with self.assertRaises(ValueError) as e:
            deckspec.load(p)
        self.assertIn("col_notes", str(e.exception))

    def test_dots_widen_the_axis_for_the_largest_value_label(self):
        import build_figs
        import figs_extra
        d = self._tmp()
        t = {"header": ["", "dry", "wet"],
             "rows": [["a cell kept in the cold room overnight", "2.64", "31.87"],
                      ["b", "0.35", "8.15"]]}
        warn = []
        with redirect_stdout(io.StringIO()):
            seen = figs_extra.draw_dots(t, os.path.join(d, "d.png"), (5.5, 2.4), warn,
                                        build_figs, "Ah", True, None)
        self.assertEqual(build_figs.LAST_CUT, set(), warn)
        self.assertIn("31.87", [s for _p, s in seen])

    def test_lines_chart_draws_one_line_per_series(self):
        import build_figs
        import figs_extra
        d = self._tmp()
        t = {"header": ["cell", "cycles", "Ah"],
             "rows": [["<safe>dry</safe>", "100", "7.25"], ["<safe>dry</safe>", "400", "6.95"],
                      ["wet", "100", "5.75"], ["wet", "400", "<hit>4.35</hit>"]]}
        warn = []
        seen = figs_extra.draw_lines(t, os.path.join(d, "l.png"), (6.0, 3.0), warn,
                                     build_figs, None, None, True, "Wet fades.")
        said = [s for _p, s in seen]
        self.assertIn("dry", said)
        self.assertIn("wet", said)
        self.assertIn("cycles", said)
        self.assertEqual(build_figs.LAST_CUT, set(), warn)

    def test_big_value_shrinks_to_its_column_and_split_tokens_are_found(self):
        import build_pptx
        import fitcheck
        from pptx import Presentation
        from pptx.util import Emu
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: standout\n    big:\n'
                         '      - {value: "93,817.45M", label: "dry"}\n'
                         '      - {value: "8.65M", label: "wet"}\n')
        out = os.path.join(d, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(p, out)
        boxes = [sh for sl in Presentation(out).slides for sh in sl.shapes
                 if sh.has_text_frame and "93,817.45M" in sh.text_frame.text]
        sh = boxes[0]
        r = (Emu(sh.left).inches, Emu(sh.top).inches,
             Emu(sh.left + sh.width).inches, Emu(sh.top + sh.height).inches)
        self.assertEqual(fitcheck.split_tokens(sh, r), [])
        narrow = (r[0], r[1], r[0] + 0.6, r[3])                   # a narrow box gets split
        self.assertIn("93,817.45M", fitcheck.split_tokens(sh, narrow))

    def test_numbers_with_units_are_read_as_several_words(self):
        import timing
        self.assertEqual(timing.words("8.65M"), 5)      # eight point six five million
        self.assertEqual(timing.words("2x"), 2)
        self.assertEqual(timing.words("1st"), 1)

    def test_diffcheck_ignores_layout_widths_and_credits_bare_numbers(self):
        import diffcheck
        d = self._tmp()
        src = os.path.join(d, "p.tex")
        deckspec.spit(src, "\\section{A}\n\\begin{wrapfigure}{r}{0.29\\textwidth}x\\end{wrapfigure}\n"
                           "We look only at the 48th cell. The width is $d_{ffn} = 4 \\times d$.\n"
                           "It reached 8.15 overall.\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source("cell 48. It reached 8.15", src, 5)
        line = buf.getvalue().split(u" manuscript value(s) not in the deck")[0].split("\n")[-1]
        self.assertTrue(line.endswith(u"0"), line)

    def test_formula_coefficient_is_not_a_result(self):
        self.assertEqual(deckspec.result_numbers("d_ffn = 4 × d_ model"), [])
        self.assertEqual(deckspec.result_numbers("3× faster on 2× A100 cards"), ["3", "2"])

    def test_same_row_name_in_two_tables_is_not_a_contradiction(self):
        import prose_audit
        mk = lambda n, v: {"n": n, "raw_screen": "Tune %s" % v, "prose_screen": "",
                           "tables": [{"header": ["", "x"], "rows": [["Tune", v]]}]}
        self.assertEqual(prose_audit.contradicting_values([mk(1, "8.15"), mk(2, "6.95")]), [])
        prose = [{"n": 1, "prose_screen": "baseline 8.15"}, {"n": 2, "prose_screen": "baseline 6.95"}]
        self.assertTrue(prose_audit.contradicting_values(prose))

    def test_a_named_baseline_is_its_own_label(self):
        """Trial 36 -- in a deck where each model normally has its own baseline, "Pump A baseline" and
        "Pump B baseline" were still flagged as a single "baseline"."""
        import prose_audit
        named = [{"n": 1, "prose_screen": "Pump A baseline 8.15"},
                 {"n": 2, "prose_screen": "HydraNet baseline 6.95"}]
        self.assertEqual(prose_audit.contradicting_values(named), [])
        # words that aren't a name (articles, verbs) are not attached -- a genuine contradiction still gets flagged
        plain = [{"n": 1, "prose_screen": "The baseline 8.15"},
                 {"n": 2, "prose_screen": "it reaches baseline 6.95"}]
        self.assertTrue(prose_audit.contradicting_values(plain))

    def test_config_with_a_broken_backslash_is_refused(self):
        d = self._tmp()
        p = os.path.join(d, "deckcheck.yaml")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write("coverage_pattern: '(?:\textbf)'\n")      # the shape of `\t` broken into a tab
        with self.assertRaises(SystemExit) as e:
            deckcheck.load(p)
        self.assertIn("x09", str(e.exception))


class Overclaims(unittest.TestCase):
    """Spots where the deck states things more strongly than the manuscript -- the number is right, but a qualifier is missing."""

    def _run(self, paper, deck_units, spoken=""):
        import diffcheck
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        src = os.path.join(d, "p.tex")
        deckspec.spit(src, paper)
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source(" ".join(deck_units), src, 10, spoken, (), deck_units)
        out = buf.getvalue()
        return out[out.index(u"more strongly than the manuscript"):]

    PAPER = ("\\begin{abstract}The dry cell performs on par with the wet cell in charge capacity "
             "on bench tests.\\end{abstract}\n\\section{Results}\n"
             "Charging the dry cell is up to 6.25x faster than charging the wet cell on the bench.\n"
             "\\begin{table}\\caption{A single charger suffices for every dry cell kit on these "
             "benches.}\\end{table}\n")

    def test_dropped_hedge_from_the_abstract_is_reported(self):
        out = self._run(self.PAPER, ["The dry cell always beats the wet cell in charge capacity "
                                     "on bench tests."])
        self.assertIn(u'says "always"', out)
        self.assertIn("on par", out)

    def test_dropped_up_to_is_reported(self):
        out = self._run(self.PAPER, ["Charging the dry cell is 6.25x faster on the bench."])
        self.assertIn("up to 6.25", out)
        out = self._run(self.PAPER, ["Charging the dry cell is up to 6.25x faster on the bench."])
        self.assertIn(u"none — the deck doesn't state as flat claims", out)

    def test_hedged_or_negated_deck_sentences_are_not_overclaims(self):
        out = self._run(self.PAPER, ["The dry cell may not always beat the wet cell in charge "
                                     "capacity on bench tests.",
                                     "We do not expect the dry cell to beat the wet cell in "
                                     "every charge capacity bench test."])
        self.assertIn(u"none — the deck doesn't state as flat claims", out)

    def test_the_same_claim_elsewhere_in_the_paper_clears_it(self):
        paper = self.PAPER + "The dry cell always holds its charge capacity on bench tests.\n"
        out = self._run(paper, ["The dry cell always holds its charge capacity on bench tests."])
        self.assertIn(u"none — the deck doesn't state as flat claims", out)

    def test_abbreviation_does_not_end_a_sentence(self):
        import diffcheck
        self.assertEqual(len(diffcheck.sentences("The cell (i.e. the dry one) must be cold. It is.")), 2)


class TwentyEighthTrial(unittest.TestCase):
    """Blind trial 28 (a scaling-curve paper -- values shaped like "1.5 Trillion" / "1.92e+19", the paper's own figure cropped and pasted in)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_numbers_in_words_and_scientific_notation(self):
        import build_figs
        self.assertEqual(build_figs.num("8.75 Billion"), 8.75e9)
        self.assertEqual(build_figs.num("3.35 Trillion"), 3.35e12)
        self.assertAlmostEqual(build_figs.num("6.15e+19"), 6.15e19)
        self.assertEqual(build_figs.num("11.25M"), 11.25e6)
        self.assertEqual(build_figs.num("<hit>2.25</hit>"), 2.25)

    def test_lines_log_both_with_single_point_series(self):
        import build_figs
        import figs_extra
        d = self._tmp()
        t = {"header": ["kit", "cells", "hours"],
             "rows": [["<safe>fitted</safe>", "1 Billion", "8.75 Billion"],
                      ["<safe>fitted</safe>", "1 Trillion", "3.35 Trillion"],
                      ["dry", "11.25 Billion", "<hit>2.25 Billion</hit>"],
                      ["wet", "20 Billion", "<hit>2.25 Billion</hit>"]]}
        warn = []
        seen = figs_extra.draw_lines(t, os.path.join(d, "l.png"), (6.0, 3.0), warn,
                                     build_figs, None, None, "both", None)
        said = [s for _p, s in seen]
        for name in ("fitted", "dry", "wet"):
            self.assertIn(name, said)
        self.assertEqual(build_figs.LAST_CUT, set(), warn)
        self.assertFalse([w for w in warn if u"no free spot" in w], warn)

    def test_dots_flip_a_tied_value_label_to_the_left(self):
        import build_figs
        import figs_extra
        d = self._tmp()
        t = {"header": ["", "dry", "wet"],
             "rows": [["kit %d" % i, "4.45", "4.45"] for i in range(7)]}
        warn = []
        figs_extra.draw_dots(t, os.path.join(d, "d.png"), (5.5, 2.0), warn, build_figs,
                             None, False, None)
        self.assertFalse([w for w in warn if u"overlap" in w], warn)

    def test_a_word_slightly_wider_than_its_cell_wraps(self):
        w = deckspec.text_width_in("Heads", 19, True, "Arial")
        self.assertEqual(deckspec.wrap_count("Heads", w / 1.037, 19, True, "Arial"), 2)
        self.assertEqual(deckspec.wrap_count("Heads", w / 1.003, 19, True, "Arial"), 1)

    def test_seven_column_header_does_not_split_a_word(self):
        import build_pptx
        from pptx import Presentation
        from pptx.util import Emu
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: table\n    title: "Two kits"\n    table:\n'
                         '      header: ["Kit", "Layers", "Heads", "Key/value size", "d_model", '
                         '"Max learning rate", "Batch size"]\n'
                         '      rows: [["Dry kit 11B", "80", "128", "128", "16,384", "4 × 10⁻⁵", '
                         '"3M → 6M"]]\n      note: "A note under the table."\n')
        out = os.path.join(d, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(p, out)
        tbl = [sh for sl in Presentation(out).slides for sh in sl.shapes if sh.has_table][0]
        for ci, c in enumerate(tbl.table.rows[0].cells):
            r = c.text_frame.paragraphs[0].runs[0]
            w = Emu(tbl.table.columns[ci].width).inches - 0.2
            self.assertEqual(deckspec.wrap_count(c.text_frame.text, w, r.font.size.pt, True,
                                                 r.font.name or "Arial"), 1, c.text_frame.text)

    def test_highlight_label_on_the_right_stays_inside_the_figure(self):
        import build_deck
        tex = build_deck.image_tex("width=1cm", "f.png",
                                   {"path": "f.png", "highlight": {
                                       "x": 0.75, "y": 0.1, "w": 0.2, "h": 0.2,
                                       "label": "a long label here", "label_at": "above"}})
        self.assertIn("anchor=south east", tex)
        self.assertIn("at (0.950,", tex)

    def test_crop_of_a_pdf_figure_records_its_text_sizes(self):
        import fitz
        d = self._tmp()
        src = os.path.join(d, "f.pdf")
        doc = fitz.open()
        pg = doc.new_page(width=400, height=200)
        pg.insert_text((20, 50), "tiny tick 7", fontsize=5)
        pg.insert_text((250, 50), "right side", fontsize=9)
        doc.save(src)
        dst = deckspec.crop_image(src, {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0})
        with io.open(os.path.join(d, deckspec.CROPTEXT), encoding="utf-8") as f_:
            rows = f_.read()
        self.assertIn("tiny tick 7", rows)
        self.assertNotIn("right side", rows)                   # text outside the crop is not recorded
        self.assertIn("\t200.00\t5.00\t", rows)                 # original width 200pt, text 5pt
        import fitcheck
        got = fitcheck.crop_text([os.path.join(d, deckspec.CROPTEXT)])
        self.assertEqual(list(got.values())[0][0][:2], (200.0, 5.0))
        self.assertTrue(os.path.isfile(dst))

    def test_bare_numbers_said_in_the_script_count(self):
        import diffcheck
        d = self._tmp()
        src = os.path.join(d, "p.tex")
        deckspec.spit(src, "\\section{A}\nThe kit ran $10^{21}$ cycles, over 250$\\times$ more.\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source("nothing here", src, 5, "ten to the 21, over 250 times")
        line = buf.getvalue().split(u" manuscript value(s) not in the deck")[0].split("\n")[-1]
        self.assertTrue(line.endswith(u"0"), line)

    def test_paper_is_not_a_coined_word(self):
        got = deckcheck.coined_terms("From the paper. From the paper. From the paper.",
                                     "cells and kits", 3)
        self.assertNotIn("paper", [w for w, _n in got])


class TwentyNinthTrial(unittest.TestCase):
    """Blind trial 29 (a systems paper -- sequence-length curves, `authblk` authors, toggles, stacked figures)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_toggles_keep_one_branch_and_accents_become_letters(self):
        B = chr(92)
        src = (B + "newtoggle{long}" + B + "toggletrue{long}" + B + "newtoggle{draft}\n"
               + B + "iftoggle{long}{Kept " + B + "iftoggle{draft}{no}{yes}}{Dropped}\n"
               + "Ann R{" + B + "'e} and Bo G" + B + '"odel\n')
        d = self._tmp()
        p = os.path.join(d, "p.tex")
        deckspec.spit(p, src)
        got = deckspec.read_tex(p)
        self.assertIn("Kept yes", got)
        self.assertNotIn("Dropped", got)
        self.assertIn(u"Ann Ré", got)
        self.assertIn(u"Gödel", got)

    def test_accent_does_not_eat_the_closing_brace(self):
        B = chr(92)
        self.assertEqual(deckspec.tex_accents(B + "author{Ann R{" + B + "'e}}"),
                         B + u"author{Ann Ré}")

    def test_authblk_affiliations_and_repeated_section_titles(self):
        B, NL = chr(92), chr(92) * 2
        out = os.path.join(self._tmp(), "s.yaml")
        p = out.replace("s.yaml", "p.tex")
        deckspec.spit(p, B + "documentclass{article}\n" + B + "author[1]{Ann Lee}\n"
                      + B + "author[2]{Bo Kim}\n" + B + "affil[1]{North Lab}\n"
                      + B + "affil[2]{South Works}\n" + B + "begin{document}\n"
                      + B + "section{Kits}\nA.\n" + B + "subsection{Kits}\nB.\n"
                      + B + "end{document}\n")
        with redirect_stdout(io.StringIO()):
            scaffold.build(p, out)
        meta, slides, _ = deckspec.load(out)
        self.assertEqual(meta["author"], "Ann Lee, Bo Kim")
        self.assertEqual(meta.get("institute"), ["North Lab", "South Works"])
        self.assertNotIn("Kits / Kits", deckspec.slurp(out))

    def test_nested_superscripts_survive_in_plain_text(self):
        self.assertEqual(deckspec.math_to_text(r"$e^{m(x^{(1)})-m(x)}$"), u"e^(m(x⁽¹⁾)-m(x))")
        self.assertEqual(deckspec.math_to_text(r"$10^{-4}$"), u"10⁻⁴")

    def test_short_value_with_a_unit_stays_on_one_line(self):
        import build_pptx
        import fitcheck
        from pptx import Presentation
        from pptx.util import Emu
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: standout\n    big:\n'
                         '      - {value: "12.35 ms", label: "a long label on the left side"}\n'
                         '      - {value: "3.65 ms", label: "right"}\n')
        out = os.path.join(d, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(p, out)
        for sl in Presentation(out).slides:
            for sh in sl.shapes:
                if sh.has_text_frame and "ms" in sh.text_frame.text:
                    r = (Emu(sh.left).inches, Emu(sh.top).inches,
                         Emu(sh.left + sh.width).inches, Emu(sh.top + sh.height).inches)
                    self.assertEqual(fitcheck.split_tokens(sh, r), [], sh.text_frame.text)

    def test_lines_callout_and_wrapped_takeaway(self):
        import build_figs
        import figs_extra
        d = self._tmp()
        t = {"header": ["kit", "cycles", "hours"],
             "rows": [["dry", "128", "1.85"], ["dry", "1024", "2.95"], ["dry", "4096", "8.45"],
                      ["wet", "128", "5.45"], ["wet", "1024", "3.65"], ["wet", "4096", "9.15"]]}
        warn = []
        seen = figs_extra.draw_lines(
            t, os.path.join(d, "l.png"), (2.65, 2.4), warn, build_figs, None, None, "x",
            "The wet kit catches up with the dry kit only past a thousand cycles.",
            {"series": "wet", "at": "1024", "text": "crosses"})
        said = [s for _p, s in seen]
        self.assertIn("crosses", said)
        self.assertEqual(build_figs.LAST_CUT, set(), warn)     # the conclusion wraps without getting clipped

    def test_bars_legend_wraps_inside_a_narrow_figure(self):
        import design
        if design.font_family() == design.FALLBACK_FAMILY:
            self.skipTest("deck font (Latin Modern Sans) not installed; the sizes depend on its metrics")
        import build_figs
        d = self._tmp()
        t = {"header": ["", "a long first series", "a longer second series", "third one"],
             "rows": [["x", "1.85", "2.95", "3.65"], ["y", "5.45", "8.45", "9.15"]]}
        warn = []
        build_figs.draw_bars(t, os.path.join(d, "b.png"), None, "h", None, (2.85, 2.4), warn)
        self.assertEqual(build_figs.LAST_CUT, set(), warn)

    def test_first_header_of_a_charted_table_is_not_expected_on_screen(self):
        import outcheck
        s = {"kind": "figure", "title": "t", "chart": {"kind": "lines"},
             "table": {"header": ["kit", "cycles", "hours"], "rows": [["dry", "1", "2"]]}}
        got = [txt for _w, txt in outcheck.frags(s)]
        self.assertNotIn("kit", got)
        self.assertIn("cycles", got)

    def test_omit_keeps_thousands_together(self):
        import re as _re
        self.assertEqual([x for x in _re.split(r",(?!\d{3}(?:\D|$))", "14,562,0.985") if x],
                         ["14,562", "0.985"])

    def test_subscript_digits_are_one_word(self):
        got = deckcheck.coined_terms("micro F1 F1 F1", "we report micro $F_1$ here", 3)
        self.assertEqual(got, [])

    def test_script_heading_of_a_pair_is_its_lead(self):
        import build_script
        s = {"kind": "standout", "lead": "Two kits, one cell.",
             "big": [{"value": "12.35", "label": "dry", "note": "cold room"},
                     {"value": "3.65", "label": "wet", "note": "warm room"}], "gap": "vs"}
        self.assertEqual(build_script.heading(s), "Two kits, one cell.")
        s.pop("lead")
        self.assertEqual(build_script.heading(s), "dry 12.35  vs  wet 3.65")

    def test_bars_callout_on_a_short_bar_clears_the_tall_neighbour(self):
        import build_figs
        d = self._tmp()
        t = {"header": ["", "one", "two", "three"],
             "rows": [["x", "5.45", "3.65", "1.85"], ["y", "12.35", "8.45", "9.15"]]}
        for at, ser in (("x", 2), ("y", 0)):
            warn = []
            build_figs.draw_bars(t, os.path.join(d, "b.png"), None, "h", None, (3.3, 2.5), warn,
                                 {"at": at, "series": ser, "text": "look here"})
            self.assertFalse([w for w in warn if u"overlap" in w], warn)

    def test_grid_blank_blocks_are_drawn(self):
        import build_figs
        from unittest import mock
        d = self._tmp()
        spec = {"kind": "grid", "cols": ["a", "b"], "rows": ["x", "y"],
                "boxes": [{"label": "now", "mark": "hit"}, {"label": "", "mark": "blank"},
                          {"label": ""}, {"label": "skip"}]}
        with mock.patch.object(build_figs, "_box", wraps=build_figs._box) as bx:
            build_figs.draw_diagram(spec, os.path.join(d, "g.png"), (3.0, 2.0), [])
        self.assertEqual(bx.call_count, 3)          # only a cell with an empty label and no mark is skipped

    def test_quotes_on_screen_must_be_verbatim(self):
        src = ("We saw it. As P3 put it, ``I just wanted the charger to stop blinking at me.'' "
               "Then we moved on.")
        ok = deckcheck.quotes_missing(u"“I just wanted the charger to stop blinking at me”", src)
        self.assertEqual(ok, [])
        cut = deckcheck.quotes_missing(u"“I just wanted … to stop blinking at me”", src)
        self.assertEqual(cut, [])                             # an ellipsis is checked fragment by fragment, in order
        bad = deckcheck.quotes_missing(u"“I only wanted the charger to stop blinking”", src)
        self.assertEqual(len(bad), 1)                         # a reworded quote
        self.assertEqual(deckcheck.quotes_missing(u"“fast charge”", src), [])  # a short one is emphasis

    def test_colour_named_mark_warns(self):
        import build_figs
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: figure\n    title: x\n    diagram:\n'
                         '      kind: flow\n      boxes: [{label: "a", mark: red}, {label: "b"}]\n')
        with redirect_stdout(io.StringIO()):
            got = build_figs.build(p, os.path.join(d, "figs"))
        warn = got[-1] if isinstance(got, tuple) else got
        self.assertTrue(any(u"a name, not a color" in str(w) for w in (warn or [])), warn)


class ThirtiethTrial(unittest.TestCase):
    """Blind trial 30 (an observational study -- the quote check had been dead in real decks, contractions, column specs, PPTX layout)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_quotes_are_read_in_the_builders_form(self):
        """The builder writes quotes as ``...'' with `\\ldots` -- reading only straight quotes meant the check never once caught anything."""
        B = chr(92)
        deck = B + "textbf{``I just wanted the charger " + B + "ldots{} to stop blinking at me''}"
        got = deckcheck.quoted(deck)
        self.assertEqual(len(got), 1, got)
        self.assertNotIn("textbf", got[0])
        self.assertIn(u"…", got[0])
        src = "As P3 put it, I just wanted the charger to stop blinking at me. Then we moved on."
        self.assertEqual(deckcheck.quotes_missing(deck, src), [])
        bad = B + "textbf{``I only wanted the charger to stop blinking at all''}"
        self.assertEqual(len(deckcheck.quotes_missing(bad, src)), 1)   # a reworded quote gets flagged

    def test_contractions_are_not_coined_words(self):
        """"doesn't" split into "doesn," coming out as "0 occurrences in the paper"."""
        self.assertEqual(deckcheck._uncontract("it doesn't; we can't; they won't; it's"),
                         "it does not; we can not; they will not; it")
        deck = " ".join(["The pump doesn't stall."] * 4)
        src = "In every run the pump does not stall at low flow."
        self.assertFalse([w for w, _ in deckcheck.coined_terms(deck, src) if "doesn" in w])

    def test_table_align_takes_only_lcr(self):
        """`pppp` passed validation and then pdflatex stopped with "Missing number"."""
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: table\n    title: x\n    table:\n'
                         '      align: "pr"\n      header: [a, b]\n      rows: [["u", "1.25"]]\n')
        with self.assertRaises(ValueError) as e:
            deckspec.load(p)
        self.assertIn("align", str(e.exception))

    def test_scaffold_turns_paragraph_columns_into_l(self):
        B = chr(92)
        src = (B + "documentclass{article}" + B + "begin{document}" + B + "section{Intro}\nText.\n"
               + B + "begin{table}" + B + "begin{tabular}{p{2cm}rX}\nName & Hours & Note " + B + B
               + "\npump & 3.25 & ok " + B + B + "\n" + B + "end{tabular}"
               + B + "caption{Runs.}" + B + "end{table}\n" + B + "end{document}\n")
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        out = os.path.join(d, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(tex, out)
        with open(out, encoding="utf-8") as f_:
            body = f_.read()
        self.assertIn('align: "lrl"', body)

    def test_bullets_in_parts_count_as_bullets_only(self):
        """A slide with nothing but bullets inside `parts` was missing from "bullets-only slides"."""
        import refcheck
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: columns\n    title: "Two sides"\n'
                         '    left: {parts: [{bullets: ["one side"]}, {bullets: ["and more"]}]}\n'
                         '    right: {bullets: ["other side"]}\n')
        got = refcheck.bullets_only_slides(p)
        self.assertEqual([n for n, _ in got], [1], got)

    def _png(self, d):
        from PIL import Image
        os.makedirs(os.path.join(d, "figs"), exist_ok=True)
        f = os.path.join(d, "figs", "p.png")
        Image.new("RGB", (800, 400), "white").save(f)
        return f

    def test_pptx_label_on_the_right_is_right_aligned(self):
        import build_pptx
        from pptx import Presentation
        from pptx.enum.text import PP_ALIGN
        d = self._tmp()
        self._png(d)
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: figure\n    title: x\n    figure:\n'
                         '      path: p.png\n      highlight: [{x: 0.1, y: 0.2, w: 0.2, h: 0.3, '
                         'label: "left"}, {x: 0.6, y: 0.2, w: 0.35, h: 0.3, label: "right"}]\n')
        out = os.path.join(d, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(p, out)
        al = {}
        for sh in Presentation(out).slides[0].shapes:
            if sh.has_text_frame and sh.name == deckspec.HIGHLIGHT_TAG and sh.text_frame.text:
                al[sh.text_frame.text] = sh.text_frame.paragraphs[0].alignment
        self.assertEqual(al.get("right"), PP_ALIGN.RIGHT, al)
        self.assertNotEqual(al.get("left"), PP_ALIGN.RIGHT, al)

    def test_pptx_table_only_slide_is_centred(self):
        """The deck centers with `\\vfill` above and below, but the PPTX alone stuck to the top, leaving the bottom half empty."""
        import build_pptx
        from pptx import Presentation
        from pptx.util import Emu
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - kind: table\n    title: x\n    table:\n'
                         '      header: [a, b]\n      rows: [["u", "1.25"], ["v", "2.75"]]\n')
        out = os.path.join(d, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(p, out)
        prs = Presentation(out)
        H = prs.slide_height / 914400.0
        tbl = [s for s in prs.slides[0].shapes if s.has_table][0]
        top = Emu(tbl.top).inches
        bot = top + build_pptx.table_height(tbl)
        room_above = top - build_pptx.TOP
        room_below = (H - 0.55) - bot
        self.assertGreater(room_above, 0.5)
        self.assertLess(abs(room_above - room_below), 0.3)

    def test_inline_code_is_typeset_as_code(self):
        """Backticks printed literally in the deck, and the PPTX couldn't use a fixed-width font."""
        B = chr(92)
        self.assertEqual(build_deck.fmt("call `set_rate(x_1, 50%)` now"),
                         "call " + B + "texttt{set" + B + "_rate(x" + B + "_1, 50" + B + "%)} now")
        self.assertIn(B + "textbf{use " + B + "texttt{a*b}}", build_deck.fmt("**use `a*b`** here"))
        # double backticks and curly quotes are quotation marks -- not read as code
        self.assertNotIn("texttt", build_deck.fmt(u"‘a’ and ‘b’"))
        self.assertNotIn("texttt", build_deck.fmt("``a'' and ``b''"))
        self.assertEqual(deckspec.strip_markup("run `make all` first"), "run make all first")
        self.assertFalse(deckspec.emphasis("run `make all` first"))    # code is not emphasis
        self.assertTrue(deckspec.emphasis("run `make` **first**"))

    def test_pptx_code_run_uses_the_mono_font(self):
        import build_pptx
        from pptx import Presentation
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + '  - title: x\n    bullets: ["run `make all` first"]\n')
        out = os.path.join(d, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(p, out)
        runs = [r for sh in Presentation(out).slides[0].shapes if sh.has_text_frame
                for para in sh.text_frame.paragraphs for r in para.runs]
        code = [r for r in runs if r.text == "make all"]
        self.assertEqual(len(code), 1, [r.text for r in runs])
        self.assertEqual(code[0].font.name, build_pptx.MONO)
        self.assertFalse([r for r in runs if "`" in r.text])

    def test_negative_bar_values_shrink_instead_of_covering_each_other(self):
        """A negative number is one character wider for its sign, so in a narrow pane with three side-by-side bars, the value labels overlapped each other."""
        import design
        if design.font_family() == design.FALLBACK_FAMILY:
            self.skipTest("deck font (Latin Modern Sans) not installed; the sizes depend on its metrics")
        import build_figs
        d = self._tmp()
        neg = {"header": ["", "one", "two", "three"],
               "rows": [["x", "-5.45", "-3.65", "-1.85"], ["y", "-12.35", "-8.45", "-9.15"],
                        ["z", "-2.15", "-6.35", "-4.05"]]}
        pos = {"header": neg["header"],
               "rows": [[r[0]] + [v.lstrip("-") for v in r[1:]] for r in neg["rows"]]}
        co = {"at": "y", "series": 0, "text": "look here"}
        warn = []
        seen = build_figs.draw_bars(neg, os.path.join(d, "n.png"), None, "h", None,
                                    (3.3, 2.5), warn, co)
        self.assertFalse([w for w in warn if u"overlap" in w], warn)
        self.assertGreaterEqual(min(z for z, s in seen if s == "-8.45"), build_figs.FLOOR_PT - 1.0)
        seen = build_figs.draw_bars(pos, os.path.join(d, "p.png"), None, "h", None,
                                    (3.3, 2.5), [], co)
        self.assertEqual([z for z, s in seen if s == "8.45"], [build_figs.BODY_PT - 2])  # stays as-is when there's no overlap


class ThirtyFirstTrial(unittest.TestCase):
    """Blind trial 31 (a theory paper -- theorems as results, formulas, subfigures, no tables)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_scaffold_takes_every_captioned_subfigure(self):
        """Only the first figure in an environment was taken -- of two minipages and three subfigures, three went missing."""
        B = chr(92)
        src = (B + "begin{figure*}" + B + "begin{minipage}{0.47" + B + "textwidth}"
               + B + "includegraphics{left.pdf}" + B + "caption{The left panel.}" + B + "end{minipage}"
               + B + "begin{minipage}{0.47" + B + "textwidth}" + B + "includegraphics{right.pdf}"
               + B + "caption{The right panel.}" + B + "end{minipage}" + B + "end{figure*}\n"
               + B + "begin{figure}" + B + "includegraphics{a.pdf}" + B + "includegraphics{b.pdf}"
               + B + "caption{Two images, one caption.}" + B + "end{figure}\n")
        got = scaffold.figures_in(src, "latex")
        self.assertEqual([p for p, _ in got], ["left.pdf", "right.pdf", "a.pdf"])
        self.assertEqual(got[1][1], "The right panel.")

    def test_theory_symbols_and_function_names_become_text(self):
        """`\\otimes` stopped pdflatex, the raw command leaked into the PPTX, and `\\cos\\gamma` was left as "\\cosγ"."""
        B = chr(92)
        self.assertEqual(deckspec.math_to_text("$" + B + "Theta " + B + "otimes I$"), u"Θ ⊗ I")
        self.assertEqual(deckspec.math_to_text("$(" + B + "cos" + B + "gamma, " + B + "sin t)$"),
                         u"(cos γ, sin t)")
        self.assertEqual(deckspec.math_to_text("$" + B + "cos(x)$"), "cos(x)")
        # a capital-letter superscript -- a layer index (L+1) used to print as "^((L+1))"
        self.assertEqual(deckspec.math_to_text("$" + B + "Sigma^{(L+1)}$"), u"Σ⁽ᴸ⁺¹⁾")
        self.assertIn(B + "otimes", build_deck.fmt(u"a ⊗ b"))

    def test_prose_audit_reads_the_whole_decimal(self):
        import prose_audit
        got = prose_audit.contradicting_values(
            [{"n": 1, "raw_screen": "the step rate 0.015 here"},
             {"n": 2, "raw_screen": "the step rate 1.25 there"}])
        self.assertEqual(got, [("rate", [("0.015", [1]), ("1.25", [2])])])

    def test_limits_are_not_hedges(self):
        """"tend (in law) to iid Gaussian processes" was read as a hedge, which then flagged the deck's "prove" as an overclaim."""
        import diffcheck
        for t in ("the outputs tend (in law) to iid Gaussian processes", "f tends to zero",
                  "it converges almost surely"):
            self.assertIsNone(diffcheck.HEDGE.search(t), t)
        for t in ("participants tend to explore", "the kernel tends to inflate", "almost always"):
            self.assertIsNotNone(diffcheck.HEDGE.search(t), t)

    def test_theorem_body_counts_as_proven(self):
        B = chr(92)
        src = (B + "newtheorem{prp}{Proposition}\n" + B + "begin{document}\n"
               "Roughly speaking, in our setup the pump may keep its pressure on the ring.\n"
               + B + "begin{prp}The pump keeps its pressure on the unit ring for every valve.\n"
               + B + "end{prp}\n" + B + "end{document}\n")
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        import diffcheck
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source("We prove the pump keeps its pressure on the unit ring.", tex, 5)
        self.assertNotIn(u"「prove」", buf.getvalue())

    def test_notation_sentences_are_not_explanations_and_omit_takes_fragments(self):
        import diffcheck
        self.assertTrue(diffcheck.notation_only(
            "We denote by d |_ f_0 F , a corresponding dual element, such that C = d , _ p ."))
        self.assertFalse(diffcheck.notation_only(
            "Here q denotes the share of pumps that keep their pressure because the valve holds."))
        B = chr(92)
        src = (B + "begin{document}\nThe valve holds the ring shut because the spring is stiff "
               "enough to resist the pump pressure.\n" + B + "end{document}\n")
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        with redirect_stdout(io.StringIO()):
            bad = diffcheck.against_source("unrelated words only", tex, 5)
            ok = diffcheck.against_source("unrelated words only", tex, 5, "",
                                          ["the spring is stiff"])
        self.assertGreater(bad, ok)

    def test_flow_with_foot_counts_its_text(self):
        """Even after propping it with `foot` per the recommendation, a "body height 34%" warning remained."""
        import build_figs
        d = self._tmp()
        p = os.path.join(d, "d.png")
        build_figs.draw_diagram({"kind": "flow", "boxes": [{"label": "a"}, {"label": "b"}]},
                                p, (5.51, 2.44), [])
        warn = []
        build_figs.underfill(p, (5.51, 2.44), "d.png", warn, "flow")
        self.assertEqual(len(warn), 1)
        warn = []
        build_figs.underfill(p, (5.51, 2.44), "d.png", warn, "flow", 0.0, 1.2)
        self.assertEqual(warn, [])

    def test_highlighted_paste_pages_are_written(self):
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD
                      + '  - kind: figure\n    title: a\n    figure: {path: p.png}\n'
                      + '  - kind: figure\n    title: b\n    figure: {path: p.png, '
                        'highlight: {x: 0.1, y: 0.1, w: 0.2, h: 0.2, label: here}}\n')
        with redirect_stdout(io.StringIO()):
            build_deck.build(p, os.path.join(d, "talk.tex"))
        with io.open(os.path.join(d, "figs", deckspec.HLFIG_LIST), encoding="utf-8") as f_:
            got = f_.read().split()
        self.assertEqual(got, ["2"])

    def test_scaffold_names_the_other_panels_of_one_caption(self):
        """One caption, three panels -- only the first panel stayed in the skeleton, and the rest vanished silently."""
        B = chr(92)
        src = (B + "begin{figure}" + B + "begin{minipage}{.3" + B + "textwidth}"
               + B + "includegraphics{p1}" + B + "end{minipage}" + B + "begin{minipage}{.3"
               + B + "textwidth}" + B + "includegraphics{p2}" + B + "end{minipage}"
               + B + "caption{Three panels.}" + B + "end{figure}\n")
        got = scaffold.figures_in(src, "latex")
        self.assertEqual([p for p, _ in got], ["p1"])
        self.assertEqual(scaffold.FIG_PANELS.get("p1"), ["p2"])


class ThirtySecondTrial(unittest.TestCase):
    """Blind trial 32 (a theory paper whose results are counterexamples -- fractions, ordering symbols, citation years, one-line definitions)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_fractions_keep_their_bar_and_symbols_their_meaning(self):
        """Stopping at the inner braces made it read as the product "D²√Tα(1-β₁)" (with no warning)."""
        B = chr(92)
        f = deckspec.math_to_text
        self.assertEqual(f("$" + B + "frac{D^2" + B + "sqrt{T}}{" + B + "alpha(1-" + B + "beta_1)}$"),
                         u"(D²√T)/(α(1-β₁))")
        self.assertEqual(f("$" + B + "frac{" + B + "sqrt{V_{t+1}}}{" + B + "alpha_{t+1}}$"),
                         u"√Vₜ₊₁/αₜ₊₁")
        self.assertEqual(f("$R_T$"), "R_T")              # does not merge into "RT"
        self.assertEqual(f("$x_i$"), u"xᵢ")
        self.assertEqual(f("$" + B + "Gamma_t " + B + "succeq 0$"), u"Γₜ ⪰ 0")
        self.assertEqual(f("$a " + B + "not" + B + "to 0$"), u"a ↛ 0")
        self.assertEqual(f("$" + B + "sqrt x$"), u"√x")

    def test_strip_cells_wrap_to_two_lines_before_overlapping(self):
        import build_figs
        d = self._tmp()
        spec = {"kind": "strip", "rows": [{"label": "step",
                                           "cells": [{"label": "to -1, damped"}] * 6}]}
        warn = []
        build_figs.draw_diagram(spec, os.path.join(d, "s.png"), (4.35, 2.0), warn)
        self.assertEqual(warn, [])

    def test_citation_year_is_checked_against_that_author(self):
        """The deck's "Kingma and Ba, 2014" (the reference is actually 2015) passed only because a different entry happened to be 2014."""
        d = self._tmp()
        B = chr(92)
        deckspec.spit(os.path.join(d, "p.bbl"),
                      B + "bibitem{k}\nAnn Kettle and Bo Ray.\n" + B + "newblock Pumps.\n"
                      + B + "newblock In {" + B + "em ICLR}, 2015.\n"
                      + B + "bibitem{s}\nCy Stone.\n" + B + "newblock Valves, 2014.\n")
        bib = deckcheck.bib_entries([os.path.join(d, "p.tex")])
        self.assertEqual(len(bib), 2)
        bad = deckcheck.cite_years("Kettle and Ray, 2014 said. ICLR 2018. Stone 2014.", bib)
        self.assertEqual(bad, [("Kettle", "2014", ["2015"])])

    def test_scaffold_drops_the_postal_address_from_authors(self):
        B = chr(92)
        src = (B + "title{T}" + B + "author{Ann Kettle, Bo Ray " + B + B + "\nPump Lab North" + B + B
               + "\nNorth City, NC 10471, USA " + B + B + "\n" + B + "texttt{ann@x.org}}\n"
               + B + "begin{document}" + B + "maketitle\n" + B + "section{Intro}\nText.\n"
               + B + "end{document}\n")
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        out = os.path.join(d, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(tex, out)
        with io.open(out, encoding="utf-8") as f_:
            body = f_.read()
        self.assertIn('author: "Ann Kettle, Bo Ray"', body)
        self.assertNotIn("10471", body)

    def test_formula_is_one_large_line_on_an_ordinary_slide(self):
        """`planning` §shapes calls for "big," but the only large text available was `standout`'s `big`, so five slides ended up forced into becoming impact slides."""
        import build_pptx
        from pptx import Presentation
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + "  - title: x\n    formula: '$a = b + c$'\n"
                                     "    bullets: ['a is the sum']\n")
        _m, slides, _ = deckspec.load(p)
        self.assertEqual(slides[0]["formula"], "$a = b + c$")
        tex = build_deck.slide_tex(slides[0], d, "figs", []) if hasattr(build_deck, "slide_tex") \
            else None
        with redirect_stdout(io.StringIO()):
            build_deck.build(p, os.path.join(d, "talk.tex"))
            build_pptx.build(p, os.path.join(d, "t.pptx"))
        with io.open(os.path.join(d, "talk.tex"), encoding="utf-8") as f_:
            self.assertIn("Large $a = b + c$", f_.read())
        txt = [sh.text_frame.text for sl in Presentation(os.path.join(d, "t.pptx")).slides
               for sh in sl.shapes if sh.has_text_frame]
        self.assertIn("a = b + c", txt)
        # not accepted on an impact slide, and the message says where it should go instead
        deckspec.spit(p, self.HEAD + "  - kind: standout\n    big: x\n    formula: '$a$'\n")
        with self.assertRaises(ValueError) as e:
            deckspec.load(p)
        self.assertIn("formula", str(e.exception))

    def test_yaml_errors_are_one_line_with_the_right_hint(self):
        import build
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, "meta: {title: T\nslides:\n  - title: x\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = build.main([p, "-o", os.path.join(d, "out")])
        self.assertEqual(code, 2)
        self.assertIn(u"can't read the YAML", buf.getvalue())
        self.assertNotIn(u"single quotes", buf.getvalue())       # a backslash hint for a bracket error would be beside the point
        self.assertNotIn("Traceback", buf.getvalue())

    def test_proof_words_and_optimum_names_are_not_overclaims(self):
        import diffcheck
        self.assertIn("prove\\w*", diffcheck._SAME["guarantee"])
        self.assertIn("optimal", diffcheck._SAME["best"])
        self.assertTrue(diffcheck.notation_only(
            "With slight abuse of notation, for a vector a and a matrix M we use a/M for it."))
        B = chr(92)
        src = (B + "begin{document}\nIt has been typically observed that the pump moves to the "
               "wrong end of the ring.\n" + B + "end{document}\n")
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source("The pump moves to the wrong end of the ring, the best point "
                                     "is the other end.", tex, 5)
        self.assertNotIn(u"「best」", buf.getvalue())

    def test_symbols_read_aloud_by_their_parts_count_as_said(self):
        import prose_audit
        slides = [{"n": 1, "screen": "average regret R_T/T and T/3",
                   "say": ["If R T over T goes to zero it converges; after T over 3 steps it is bad."]}]
        self.assertEqual(prose_audit.unspoken_terms(slides), [])

    def test_claim_pattern_copied_from_latex_matches(self):
        """A claim pattern copied verbatim from the manuscript's "Kale \\& Kumar" failed to match in either version."""
        B = chr(92)
        NL = chr(10)
        d = self._tmp()
        deckspec.spit(os.path.join(d, "paper.tex"),
                      B + "begin{document}" + NL + "Ann " + B + "& Bo reach 12.75 metres." + NL
                      + B + "end{document}" + NL)
        deckspec.spit(os.path.join(d, "talk.tex"),
                      B + "begin{frame}Ann and Bo: 12.75" + B + "end{frame}" + NL)
        deckspec.spit(os.path.join(d, "c.yaml"),
                      "source: [paper.tex]" + NL + "derivative: {deck: talk.tex}" + NL + "claims:" + NL
                      + "  - {label: pts, value: '12.75', source: 'Ann " + B + "& Bo reach 12"
                      + B + ".75'}" + NL)
        with redirect_stdout(io.StringIO()):
            fail, _ = deckcheck.run(deckcheck.Stuff(deckcheck.load(os.path.join(d, "c.yaml"))))
        self.assertEqual(fail.get("key-claim check"), 0)


class ThirtyThirdTrial(unittest.TestCase):
    """Blind trial 33 (labor economics -- currency symbols, significance asterisks, regression tables, a heavily hedged manuscript)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_currency_is_not_math(self):
        """The two `$` in "from $30,230 to $81,980" were read as math delimiters, which stopped pdflatex."""
        B = chr(92)
        self.assertEqual(build_deck.fmt("from $30,230 to $81,980"),
                         "from " + B + "$30,230 to " + B + "$81,980")
        self.assertEqual(deckspec.math_to_text("from $30,230 to $81,980"), "from $30,230 to $81,980")
        # even escaped with `\$`, no backslash is left behind in the PPTX
        self.assertEqual(deckspec.math_to_text("costs " + B + "$4,150 each"), "costs $4,150 each")
        self.assertEqual(deckspec.math_to_text("$2 and $3 each"), "$2 and $3 each")
        # actual math stays as math
        self.assertEqual(deckspec.math_to_text("$5 " + B + "times 10$"), u"5 × 10")
        self.assertEqual(deckspec.math_to_text("$0.5$"), "0.5")

    def test_significance_stars_are_not_markup(self):
        """"0.128** and 0.214***" was read as bold markup, and `outcheck` produced 86 false hits."""
        import outcheck
        self.assertEqual(deckspec.strip_markup("0.425** and 0.375***"), "0.425** and 0.375***")
        self.assertNotIn("textbf", build_deck.fmt("0.425** and 0.375***"))
        self.assertEqual(deckspec.strip_markup("**bold** and *it*"), "bold and it")
        self.assertEqual(outcheck.markup_leaks({"deck": "Writing 0.425** 0.375*** (0.041)"}), [])
        self.assertTrue(outcheck.markup_leaks({"deck": "a **bold** leak"}))

    def test_scaffold_reads_regression_tables(self):
        """A `dcolumn` table collapsed into one column, `\\pmb{\\alpha}` came out as "±bα," and `\\rowcolor` was left inside the cell."""
        B = chr(92)
        NL = chr(10)
        src = (B + "begin{document}" + B + "section{Results}" + NL + "Text." + NL
               + B + "begin{table}" + B + "begin{tabular}{l*{4}{D{.}{.}{-1}}}" + NL
               + " & (1) & (2) " + B + B + NL
               + B + "rowcolor{gray!10} Pump $" + B + "pmb{" + B + "alpha}$ & 0.425" + B + "sym{**} & 0.375 "
               + B + B + NL + " & (0.041) & (0.037) " + B + B + NL
               + B + "end{tabular}" + B + "caption{Runs.}" + B + "end{table}" + NL + B + "end{document}" + NL)
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        out = os.path.join(d, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(tex, out)
        with io.open(out, encoding="utf-8") as f_:
            body = f_.read()
        self.assertIn('align: "lrr"', body)                # the two empty columns are dropped
        self.assertIn(u'"Pump α", "0.425**", "0.375"', body)
        self.assertNotIn("gray", body)
        self.assertNotIn(u"±", body)

    def test_hi_marks_count_on_tiles(self):
        import build_figs
        d = self._tmp()
        t = {"header": ["", "a", "b", "c"],
             "rows": [["x", "<hi>0.625</hi>", "<hi>0.575</hi>", "0.125"],
                      ["y", "<hi>0.325</hi>", "0.225", "<hi>0.425</hi>"]]}
        warn = []
        build_figs.draw_tiles([("", t)], os.path.join(d, "t.png"), None, None, (4.0, 2.0), warn)
        self.assertFalse([w for w in warn if u"cells were drawn as tiles, but only" in w], warn)

    def test_integer_categories_get_every_tick(self):
        import build_figs
        import figs_extra
        from unittest import mock
        d = self._tmp()
        t = {"header": ["", "Zone", "share"],
             "rows": [["h", str(i), str(v)] for i, v in zip(range(1, 6), [0.05, 0.15, 0.25, 0.45, 0.4])]}
        import matplotlib.ticker as mt
        with mock.patch.object(mt, "FixedLocator", wraps=mt.FixedLocator) as fl:
            figs_extra.draw_lines(t, os.path.join(d, "l.png"), (3.3, 2.4), [], build_figs)
        self.assertIn([1.0, 2.0, 3.0, 4.0, 5.0], [list(map(float, c.args[0])) for c in fl.call_args_list])

    def test_equal_neighbour_values_do_not_run_together(self):
        """When two bars had the same value, shrinking them still ran them together into "0.060.06"."""
        import build_figs
        d = self._tmp()
        t = {"header": ["", "human", "model"],
             "rows": [["Zone %d" % i, a, b] for i, (a, b) in enumerate(
                 [("0.00", "0.00"), ("0.06", "0.06"), ("0.13", "0.16"), ("0.35", "0.40"),
                  ("0.29", "0.33")], 1)]}
        warn = []
        build_figs.draw_bars(t, os.path.join(d, "g.png"), None, "share", None, (3.0, 2.2), warn, None)
        self.assertFalse([w for w in warn if u"overlap" in w], warn)

    def test_quoted_paper_phrase_and_tikz_styles(self):
        """"fully exposed" from the manuscript's table was flagged as an overclaim, and a `\\tikzstyle` line was flagged as an explanatory sentence."""
        import diffcheck
        B = chr(92)
        NL = chr(10)
        src = (B + "begin{document}" + NL + B + "tikzstyle{mybox} = [draw=black, fill=black!2, very thick, "
               "rectangle, rounded corners, which makes it thick]" + NL
               + "Our results suggest that valves may leak at high flow." + NL
               + B + "begin{table}" + B + "begin{tabular}{l}The pump labeled 15 valves as fully sealed. "
               + B + B + B + "end{tabular}" + B + "end{table}" + NL + B + "end{document}" + NL)
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source("The pump calls 15 valves fully sealed; valves may leak at high flow.",
                                     tex, 5)
        self.assertNotIn(u"「fully」", buf.getvalue())
        self.assertNotIn("mybox", buf.getvalue())

    def test_number_words_count_as_said(self):
        self.assertEqual(deckspec.number_words("forty-nine jobs, three hundred and twelve tasks, "
                                               "eighty percent"), "49 jobs, 312 tasks, 80%")

    def test_bold_question_is_a_question(self):
        import refcheck
        self.assertTrue(refcheck.is_question("Where does it land? **Where do pumps land?**"))

    def test_plural_counts_as_said(self):
        import prose_audit
        slides = [{"n": 1, "screen": "Each DWA is scored", "say": ["We score the DWAs one by one."]}]
        self.assertEqual(prose_audit.unspoken_terms(slides), [])

    def test_scripts_compile_without_syntax_warnings(self):
        """A `\\&` inside a docstring produced a SyntaxWarning on every run."""
        import warnings
        for f in sorted(os.listdir(os.path.join(HERE, "..", "scripts"))):
            if not f.endswith(".py"):
                continue
            p = os.path.join(HERE, "..", "scripts", f)
            with warnings.catch_warnings():
                warnings.simplefilter("error", SyntaxWarning)
                with io.open(p, encoding="utf-8") as f_:
                    compile(f_.read(), p, "exec")

    def test_dropped_hedge_is_caught_without_a_strong_word(self):
        """When the deck rewords the manuscript's "could have" as "will have," there's no strong word left to catch it, so the whole thing slipped through."""
        import diffcheck
        B = chr(92)
        NL = chr(10)
        src = (B + "begin{document}" + NL
               + "Around 70" + B + "% of pumps could have at least 20" + B + "% of their valve seals worn by the new fluid. "
               + "Larger pumps potentially face greater wear from the new fluid and its additives. "
               + "The fluid exhibits traits of a general coolant, indicating that it could have broad industrial uses."
               + NL + "A surprising observation is that small pumps appear to wear faster than large ones."
               + NL + "Our tests suggest replacing the seals every spring." + NL
               + B + "end{document}" + NL)
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)

        def flags(deck):
            buf = io.StringIO()
            with redirect_stdout(buf):
                diffcheck.against_source(deck, tex, 5, "", [], [deck])
            out = buf.getvalue()
            return out[out.index(u"more strongly than the manuscript"):]
        self.assertIn(u"drops the hedge", flags(
            "Around 70% of pumps will have at least 20% of their valve seals worn by the new fluid."))
        self.assertIn(u"potentially", flags("Larger pumps always face greater wear from the new fluid and its additives."))
        self.assertIn(u"exhibit", flags("The fluid is a general coolant with broad industrial uses."))
        # a sentence that keeps its hedge, a question, or a recommendation is not flagged
        self.assertNotIn(u"drops the hedge", flags(
            "Around 70% of pumps could have at least 20% of their valve seals worn by the new fluid."))
        self.assertNotIn(u"drops the hedge", flags("So why do small pumps wear faster than large ones?"))
        self.assertNotIn(u"drops the hedge", flags("Replace the seals every spring."))

    def test_appears_without_to_is_a_hedge(self):
        """Trial 36 -- the manuscript's "appears stable under ..." was reworded by the deck as "Stable
        under ...," yet counting only "appears to" as a hedge found nothing. "Appears in Table 2" is not a hedge."""
        import diffcheck
        B = chr(92)
        NL = chr(10)
        src = (B + "begin{document}" + NL
               + "The older compressor appears sluggish mainly during winter nights at northern stations."
               + NL + "The rear pump reading appears in the second table with the other gauges." + NL
               + B + "end{document}" + NL)
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)

        def flags(deck):
            buf = io.StringIO()
            with redirect_stdout(buf):
                diffcheck.against_source(deck, tex, 5, "", [], [deck])
            out = buf.getvalue()
            return out[out.index(u"more strongly than the manuscript"):]
        self.assertIn(u"appears sluggish", flags(
            "The older compressor is sluggish mainly during winter nights at northern stations."))
        self.assertNotIn(u"drops the hedge", flags(
            "The rear pump reading is in the second table with the other gauges."))
        self.assertTrue(diffcheck.MODAL.search("it seems unlikely"))
        self.assertFalse(diffcheck.MODAL.search("it appears when the valve opens"))


class ThirtySixthTrial(unittest.TestCase):
    """Blind trial 36 (where a label lands on a pasted-in figure)."""

    def test_a_label_does_not_land_on_the_figure_text_above_the_box(self):
        """A box sitting 0.12 down from the top looked like "there's room above," and the label ended
        up covering the paper figure's panel title. The band where the label would sit is now
        measured, and if text is there, the label moves below instead."""
        from PIL import Image, ImageDraw
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "fig.png")
        im = Image.new("RGB", (400, 300), "white")
        dr = ImageDraw.Draw(im)
        for x in range(60, 340, 12):                  # the panel-title line (0.04-0.10 from the top)
            dr.rectangle([x, 14, x + 7, 28], fill="black")
        im.save(p)
        h = {"x": 0.1, "y": 0.12, "w": 0.8, "h": 0.4, "label": "look"}
        self.assertEqual(deckspec.label_place(h), "above")         # without knowledge of the figure, the old rule applies
        self.assertEqual(deckspec.label_place(h, p), "below")      # measuring it dodges the text
        blank = os.path.join(d, "blank.png")
        Image.new("RGB", (400, 300), "white").save(blank)
        self.assertEqual(deckspec.label_place(h, blank), "above")  # an empty band stays above as before
        self.assertEqual(deckspec.label_place(dict(h, label_at="above"), p), "above")


class ThirtySixthTrialStrip(unittest.TestCase):
    def _h(self, nsub):
        import build_figs
        from PIL import Image
        rows = []
        for i in range(4):
            r = {"label": "row %d" % i, "cells": [{"label": "a", "span": 2}, {"label": "b", "span": 3}]}
            if i < nsub:
                r["sub"] = "a short note"
            rows.append(r)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "s.png")
        build_figs.draw_strip({"kind": "strip", "rows": rows}, p, slot=(8.0, 6.0), warn=[])
        with Image.open(p) as im:
            return im.height

    def test_sub_space_is_paid_per_row(self):
        """Trial 36, defect 4 -- even with a subtitle on just one row, every row was given the
        subtitle's height, so removing it from three of four rows left the figure's height unchanged.
        Only rows that actually carry a subtitle grow taller."""
        h0, h1, h4 = self._h(0), self._h(1), self._h(4)
        self.assertLess(h0, h1)
        self.assertLess(h1, h4)


class ThirtySixthTrialPptx(unittest.TestCase):
    def test_a_foot_estimate_is_dropped_when_the_file_measures_clean(self):
        """Trial 36, defect 2 -- `build` said "the table's bottom runs past the footnote spot," while `fitcheck` measured zero geometry. The measured side wins."""
        import build_pptx
        warn = [u"Slide 10 left column: table bottom (5.18in) in PPTX runs past the footnote position (4.58in) -- …",
                u"Slide 14: bullets in PPTX reach down to the footnote position -- …",
                u"Slide 3: another warning"]
        got = build_pptx.settle_foot(warn, [(14, u"overlap", u"«a» and «b» overlap by 0.20 in²")])
        self.assertEqual(got, warn[1:])


class ThirtySixthTrialSettle(unittest.TestCase):
    def test_a_floor_estimate_is_judged_after_drawing(self):
        """Trial 36, defect 3 -- when the estimate said "doesn't fit," it suppressed every warning from the drawing pass, even though the render turned out fine."""
        import build_figs
        pend = (u"f.png: 2 rows x 2 columns in this space doesn't fit. width falls short by 0.36 inches", False, "f.png")
        out = []
        build_figs._settle(out, pend, [])
        self.assertEqual(out, [])                                   # drawing it revealed no problem
        out = []
        build_figs._settle(out, pend, [u"f.png: text is 6.5pt on screen (floor 7pt): 'x'"])
        self.assertTrue(out and u"this fits the space, but" in out[0] and u"6.5" in out[0])
        out = []
        build_figs._settle(out, pend, [u"f.png: text doesn't fit the space (even shrunk to 6.5pt): 'x'"])
        self.assertEqual(out, [pend[0]])                            # if it genuinely doesn't fit, the estimate is reported


class TextBoundOverflow(unittest.TestCase):
    def test_a_figure_is_restored_when_shrinking_it_does_not_help(self):
        """Trial 37, defect 1 -- the left pane's text overflowed, yet the right-hand photo got shrunk twice while the overflow stayed unchanged."""
        slides = [{"n": 1}, {"n": 2}]
        seq = iter([[(1, 49.5), (2, 21.5)], [(1, 49.0), (2, 2.0)]])
        old = deckspec.log_overfull
        deckspec.log_overfull = lambda _p: next(seq)
        try:
            deckspec.EXTRA_RESERVE.clear(); deckspec.LAST_OVER.clear(); deckspec.TEXT_BOUND.clear()
            deckspec.fit_from_log("x.pdf", slides)
            self.assertIn(1, deckspec.EXTRA_RESERVE)
            deckspec.fit_from_log("x.pdf", slides)
            self.assertNotIn(1, deckspec.EXTRA_RESERVE)       # the figure was restored
            self.assertIn(1, deckspec.TEXT_BOUND)
            self.assertNotIn(2, deckspec.TEXT_BOUND)          # a slide fixed by shrinking stays shrunk
            self.assertIn(2, deckspec.EXTRA_RESERVE)
        finally:
            deckspec.log_overfull = old
            deckspec.EXTRA_RESERVE.clear(); deckspec.LAST_OVER.clear(); deckspec.TEXT_BOUND.clear()


class SmallTextAdvice(unittest.TestCase):
    def test_the_advice_follows_what_shrank_the_text(self):
        """Trial 37, defect 2 -- following "trim the fine print" on a box constrained by width only made the text smaller."""
        import build, build_figs
        build_figs.BOUND.clear()
        build_figs.BOUND[("a.png", "Long stage name")] = "w"
        build_figs.BOUND[("b.png", "*")] = "h"
        try:
            self.assertIn("width decides it", build._why_small("a.png", ["Long stage name"]))
            self.assertIn("height decides it", build._why_small("b.png", ["x", "y"]))
            self.assertEqual(build._why_small("c.png", ["x"]), "")
        finally:
            build_figs.BOUND.clear()

    def test_figure_text_at_the_builder_floor_is_not_a_failure(self):
        """The builder's drawing floor and `fitcheck`'s failure threshold are the same constant."""
        import build_figs
        self.assertEqual(build_figs.FLOOR_PT - 1.5, deckspec.FIG_FLOOR_PT)


class RoleFillsVsUnmarked(unittest.TestCase):
    def test_every_role_fill_stands_apart_from_an_unmarked_cell(self):
        """Trial 37, defect 3 -- the fourth role's cell was only 1.15:1 against an unmarked cell, so it read as "no mark"."""
        import design

        def lum(h):
            h = h.lstrip("#")
            v = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
            v = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in v]
            return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]

        def cr(a, b):
            x, y = sorted([lum(a), lum(b)], reverse=True)
            return (x + 0.05) / (y + 0.05)
        for k in design.ROLE_ORDER:
            self.assertGreater(cr(design.ROLES[k][1], design.TILE_FILL), 1.3, k)


class PaneBlockSize(unittest.TestCase):
    def test_a_block_in_a_pane_uses_the_pane_text_size(self):
        """Trial 37, defect 4 -- an alert block's text inside a pane printed one size larger than the neighboring pane's text."""
        import build_deck
        B = chr(92)
        out = chr(10).join(build_deck.pane_body(
            {"text": "Pane text.", "block": {"kind": "alert", "title": "Open", "text": "Block text."}},
            None, "figs", [], {"n": 1, "title": "T"}))
        i = out.index("Block text.")
        self.assertIn(B + "footnotesize Block text.", out[i - 20:i + 12])


class BottomBandShare(unittest.TestCase):
    def _warn(self, note):
        import build_figs
        d = {"kind": "strip", "rows": [{"label": "one timetable", "bars": 30, "groups": [30]},
                                        {"label": "per team", "bars": 30, "groups": [13, 9, 8]}],
             "note": note, "takeaway": "Each third of the line keeps its own timetable."}
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        w = []
        build_figs.draw_strip(d, os.path.join(tmp, "x.png"), slot=(5.5, 2.3), warn=w)
        return w

    def test_note_and_takeaway_share_the_band_by_length(self):
        """Trial 37, defect 5 -- adding a `note` left the `takeaway` unable to fit in its half and got clipped, and the warning never said why."""
        self.assertEqual([x for x in self._warn("Bar heights are shape.") if "doesn't fit" in x], [])
        long = ("Bar heights are shape, not data; the accent bar is the stop the argument turns on, "
                "every other bar is only there to show the grouping, and both rows are drawn at "
                "one height so the page stays quiet around that single accent bar.")
        got = self._warn(long)
        self.assertTrue(any("share one line" in x for x in got), got)


class ListTableNames(unittest.TestCase):
    def test_row_names_of_a_list_table_are_a_note_not_a_demand(self):
        """Trial 37, defect 6 -- following §3's rule to speak all seven row names turned into a "wall of names"."""
        import prose_audit
        NL = chr(10)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "s.yaml")
        lines = ["meta: {title: T, author: A, venue: V, date: D}", "slides:",
                 "  - kind: table", '    title: "What have others tried?"',
                 "    table:", "      header: [Work, How]", "      rows:"]
        lines += ['        - ["%s", "by site"]' % n for n in ("GSX", "HRV", "KTM", "PLW", "QMB")]
        lines += ['    say: ["Most of them work by site."]', ""]
        deckspec.spit(p, NL.join(lines))
        buf = io.StringIO()
        with redirect_stdout(buf):
            prose_audit.main(p)
        out = buf.getvalue()
        sec = out[out.index("3. "):out.index("4. ")]
        self.assertIn(": don't read", sec)
        self.assertNotIn("   slide   1  ", sec)


class PercentWord(unittest.TestCase):
    def test_percent_said_aloud_is_the_papers_percent_sign(self):
        """Trial 37 -- the manuscript uses only the symbol, and the deck spoke "percent," which got flagged as a word absent from the manuscript."""
        import deckcheck
        B = chr(92)
        self.assertEqual(deckcheck.coined_terms("percent percent percent of cells",
                                                "the cells hold 92.4" + B + "% of capacity"), [])
        self.assertEqual(deckcheck.coined_terms("percent percent percent of cells",
                                                "the cells hold capacity"), [("percent", 3)])


class BackupOnlyFindings(unittest.TestCase):
    def test_a_finding_only_on_backup_slides_is_listed(self):
        """Trials 36/37 -- a results paragraph existing only in a backup table was counted as "the deck used it," even though it never appeared in the main body."""
        import diffcheck
        B, NL = chr(92), chr(10)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        tex = os.path.join(tmp, "p.tex")
        deckspec.spit(tex, B + "begin{document}" + NL
                      + "Weekday deliveries take 13.35 minutes on average." + NL
                      + "Sunday deliveries take 21.85 minutes." + NL
                      + B + "end{document}" + NL)
        main = "Weekday deliveries take 13.35 minutes."
        deck = main + NL + "Backup: 21.85"
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source(deck, tex, 5, "", [], [deck], main)
        out = buf.getvalue()
        self.assertIn("only on a backup slide", out)
        self.assertIn("21.85", out[out.index("only on a backup slide"):])
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source(deck, tex, 5, "", [], [deck], deck)
        self.assertNotIn("only on a backup slide", buf.getvalue())


class ScaffoldThirtyEighth(unittest.TestCase):
    """Blind trial 38 -- typesetting command arguments, a value spanning columns, a bibliography environment, an extensionless figure, trim/clip."""

    def test_rule_arguments_do_not_land_in_cells(self):
        import scaffold
        B = chr(92)
        got = scaffold.clean(B + "rule{0pt}{2.0ex}Cell A " + B + "specialrule{1pt}{-1pt}{0pt}")
        self.assertEqual(got, "Cell A")

    def test_a_value_spanning_columns_fills_each_and_bibliography_is_not_a_section(self):
        import scaffold
        from PIL import Image
        B, NL = chr(92), chr(10)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "Figures"))
        Image.new("RGB", (100, 200), "white").save(os.path.join(tmp, "Figures", "Rig-1.png"))
        tex = os.path.join(tmp, "p.tex")
        deckspec.spit(tex, NL.join([
            B + "documentclass{article}", B + "begin{document}", B + "section{Results}",
            "Route A takes 13.35 minutes.",
            B + "begin{figure}" + B + "includegraphics[width=0.5" + B + "linewidth, trim=0 0 0 50, clip]{Figures/Rig-1}"
            + B + "caption{The rig.}" + B + "end{figure}",
            B + "begin{tabular}{lcc}", B + "toprule",
            "Route & " + B + "multicolumn{2}{c}{Minutes} " + B + B,
            " & day & night " + B + B, B + "midrule",
            "North & " + B + "multicolumn{2}{c}{21.85} " + B + B,
            "South & 13.35 & 14.05 " + B + B, B + "bottomrule", B + "end{tabular}",
            B + "section{Conclusion}", "It works.",
            B + "begin{thebibliography}{9}", B + "bibitem{a} A. In Proc. 44th Annual Meeting.",
            B + "end{thebibliography}", B + "end{document}", ""]))
        out = os.path.join(tmp, "s.yaml")
        scaffold.build(tex, out)
        y = deckspec.slurp(out)
        self.assertIn('["North", "21.85", "21.85"]', y)
        self.assertIn('"Minutes day", "Minutes night"', y)
        self.assertNotIn("44", y)
        self.assertIn('path: "Rig-1.png"', y)
        self.assertIn("crop: {x: 0.0, y: 0.25, w: 1.0, h: 0.75}", y)


class TitleWrapFont(unittest.TestCase):
    def test_big_text_of_a_pasted_figure_is_not_a_second_title_line(self):
        """Trial 38, defect 6 -- large text in a pasted-in PDF figure was read as a second title line, reporting "the title wraps to two lines"."""
        import fitz
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        pdf = os.path.join(tmp, "d.pdf")
        doc = fitz.open()
        for lines in ((("helv", 20, "One line title"),),
                      (("helv", 20, "Title here"), ("cour", 26, "Figure Label")),
                      (("helv", 20, "A title that"), ("helv", 45, "wraps twice"))):
            pg = doc.new_page(width=454, height=255)
            for font, y, txt in lines:
                pg.insert_text((20, y), txt, fontname=font, fontsize=12)
        doc.save(pdf)
        doc.close()
        self.assertEqual([n for n, _ in deckspec.title_wraps(pdf)], [3])


class StandoutBulletsCount(unittest.TestCase):
    def test_a_thesis_written_in_standout_bullets_counts(self):
        """Trial 38, defect 7 -- placing the conclusion in a `standout`'s `bullets`, as the `layouts` examples show, only registered "thesis coverage 30%"."""
        import prose_audit
        th = "Weekday deliveries run faster than Sunday deliveries across every route"
        sl = [{"n": 1, "kind": "standout", "big": [{"value": "13.35"}, {"value": "21.85"}],
               "bullets": [th]}]
        self.assertGreater(prose_audit.thesis_coverage(sl, th), 0.9)
        sl2 = [{"n": 1, "kind": "standout", "flow": ["weekday routes", "Sunday routes", th]}]
        self.assertGreater(prose_audit.thesis_coverage(sl2, th), 0.9)


class PptxMathThirtyEighth(unittest.TestCase):
    def test_a_multi_letter_subscript_drops_as_one(self):
        """Trial 38, defect 8 -- "dₘodel" / "P_d rop": after the braces were stripped, only one letter dropped to subscript."""
        import build_pptx
        B = chr(92)
        got = build_pptx._scripts_split(build_pptx.math_runs("$d_{" + B + "mathrm{model}}$"))
        self.assertEqual(got, [("d", None), ("model", "-25000")])
        got = build_pptx._scripts_split(build_pptx.math_runs("$P_{drop}$"))
        self.assertEqual(got, [("P", None), ("drop", "-25000")])

    def test_a_function_name_after_a_command_is_not_glued(self):
        r"""Trial 38, defect 9 -- `\cdot\min` was left as "\cdotmin"."""
        B = chr(92)
        got = deckspec.math_to_text("$a" + B + "cdot" + B + "min(b, c)$")
        self.assertNotIn(B, got)
        self.assertIn("min(b, c)", got)


class LogTicksAtData(unittest.TestCase):
    def test_a_log_x_with_a_few_settings_ticks_at_each_setting(self):
        """Trial 38, defect 10 -- with data points at 1/4/8/16/32, the log axis put ticks at 1/2/5/10/20, so the audience couldn't read the points."""
        import build_figs
        import figs_extra
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        t = {"header": ["route", "stops", "minutes"],
             "rows": [["north", x, y] for x, y in (("1", "7.25"), ("4", "6.95"), ("8", "6.85"),
                                                  ("16", "6.65"), ("32", "7.15"))]}
        got = {}
        old = build_figs.save_fig

        def grab(fig, *a, **k):
            got["x"] = [round(v) for v in fig.axes[0].get_xticks()]
            return old(fig, *a, **k)
        build_figs.save_fig = grab
        try:
            figs_extra.draw_lines(t, os.path.join(tmp, "l.png"), (6.0, 3.0), [], build_figs,
                                  None, None, True, None)
        finally:
            build_figs.save_fig = old
        self.assertEqual(got["x"], [1, 4, 8, 16, 32])


class PlanIsAHedge(unittest.TestCase):
    def test_a_plan_turned_into_a_need_is_flagged(self):
        """Trial 38, defect 12 -- the manuscript's "we plan to investigate" was reworded by the deck as "need," and it went uncaught."""
        import diffcheck
        B, NL = chr(92), chr(10)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        tex = os.path.join(tmp, "p.tex")
        deckspec.spit(tex, B + "begin{document}" + NL
                      + "We plan to extend the delivery planner to refrigerated trucks and overnight routes."
                      + NL + B + "end{document}" + NL)
        deck = "The delivery planner must be extended to refrigerated trucks and overnight routes."
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source(deck, tex, 5, "", [], [deck])
        out = buf.getvalue()
        self.assertIn("plan to", out[out.index("more strongly than the manuscript"):])


class SpokenForPanel(unittest.TestCase):
    def test_the_panel_script_has_only_spoken_lines(self):
        """Trial 38, defect 13 -- `cue` and timing used to be stripped out by hand from the script handed to a panel."""
        import build_script
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, chr(10).join([
            "meta: {title: T, author: A, venue: V, date: D}", "slides:",
            "  - kind: content", "    title: Routes", "    bullets: [Weekday routes run faster]",
            "    cue: Point at the first row", "    say: [Weekday routes run faster.]",
            "  - kind: content", "    title: Spare", "    backup: true", "    bullets: [x]",
            "    say: [Only if asked.]", ""]))
        got = build_script.spoken_text(p)
        self.assertIn("Weekday routes run faster.", got)
        self.assertNotIn("Point at", got)
        self.assertNotIn("Only if asked", got)


class CaptionCaveat(unittest.TestCase):
    def test_a_caption_caveat_missing_from_the_main_talk_is_listed(self):
        """Trial 38, T10 -- "per-wordpiece ... should not be compared" existed only in the caption, while the main body still compared that value."""
        import diffcheck
        B, NL = chr(92), chr(10)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        tex = os.path.join(tmp, "p.tex")
        deckspec.spit(tex, B + "begin{document}" + NL + "Routes vary." + NL
                      + B + "begin{table}" + B + "caption{Delivery minutes per route. Listed minutes are "
                      "door-to-door and should not be compared to depot-to-depot minutes.}" + B + "end{table}"
                      + NL + B + "end{document}" + NL)
        deck = "North minutes 13.35 against South minutes 21.85."
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source(deck, tex, 5, "", [], [deck], deck)
        self.assertIn("comparison caveats", buf.getvalue())
        buf = io.StringIO()
        ok = deck + " These are door-to-door minutes, not depot-to-depot minutes; do not compare them."
        with redirect_stdout(buf):
            diffcheck.against_source(ok, tex, 5, "", [], [ok], ok)
        self.assertNotIn("comparison caveats", buf.getvalue())


class BigMainTable(unittest.TestCase):
    def test_a_big_full_width_table_on_a_main_slide_points_to_dots(self):
        """Trial 38 -- a 10-row, 5-column leaderboard table filled the full width and was unreadable from the back row. This does not flag backup slides or tables inside a pane."""
        import build_deck
        t = {"header": ["Route", "a", "b", "c", "d"],
             "rows": [["r%d" % i, "1", "2", "3", "4"] for i in range(10)]}
        w = []
        build_deck.render_table(t, w, "slide")
        self.assertTrue(any("planning §leaderboard" in x for x in w))
        w = []
        build_deck.render_table(t, w, "slide", main=False)
        self.assertFalse(any("planning §leaderboard" in x for x in w))


class ScaffoldThirtyNinth(unittest.TestCase):
    def test_preamble_macros_figure_tabulars_and_cell_citations(self):
        """Trial 39 -- a `section` inside a macro definition turned into a slide, a `tabular` inside a figure turned into a table, and a citation inside a cell got stripped."""
        import scaffold
        B, NL = chr(92), chr(10)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        tex = os.path.join(tmp, "p.tex")
        deckspec.spit(tex, NL.join([
            B + "documentclass{article}",
            B + "newcommand" + B + "Section[2]{" + B + "section{#2}" + B + "label{sec:#1}}",
            B + "definecolor{blue1}{rgb}{0.15,0.35,0.85}",
            B + "begin{document}", B + "section{Routes}", "Weekday routes are faster.",
            B + "begin{figure}" + B + "begin{tabular}{cc} North & South " + B + B + " "
            + B + "end{tabular}" + B + "caption{An example.}" + B + "end{figure}",
            B + "begin{table}" + B + "begin{tabular}{ll}" + B + "toprule", "Feature & Note " + B + B,
            B + "midrule", "Stops & as in " + B + "citet{doe2015} " + B + B, B + "bottomrule",
            B + "end{tabular}" + B + "caption{Features.}" + B + "end{table}",
            B + "end{document}", ""]))
        out = os.path.join(tmp, "s.yaml")
        scaffold.build(tex, out)
        y = deckspec.slurp(out)
        self.assertNotIn("#2", y)
        self.assertNotIn("0.85", y)
        self.assertNotIn('"North"', y)
        self.assertIn("[doe2015]", y)


class ProseAuditThirtyNinth(unittest.TestCase):
    def test_a_dimension_table_is_not_the_first_result(self):
        """Trial 39, defect 4 -- a related-work dimension table's size column triggered "no figure before the first numeric slide"."""
        import prose_audit
        sl = [{"n": 1, "tables": [{"rows": [["A", "crowd", "spans", "100"], ["B", "logs", "free", "3000"],
                                             ["C", "tests", "choice", "514"], ["D", "cloze", "word", "688"]]}]},
              {"n": 2, "tables": [{"rows": [["x", "1.1", "2.2"], ["y", "3.3", "4.4"]]}]}]
        self.assertEqual(prose_audit.concept_before_results(sl)[0], 2)

    def test_an_impact_slide_note_is_not_a_title(self):
        """Trial 39, defect 5 -- an impact slide's `big` note, "but too small," was counted as a conjunction-opening title."""
        import prose_audit
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, chr(10).join([
            "meta: {title: T, author: A, venue: V, date: D}", "slides:",
            "  - kind: standout", "    lead: Pick one", "    gap: or",
            "    big: [{text: large, note: but too noisy}, {text: small, note: but too few}]", ""]))
        sl = prose_audit.from_spec(p)
        self.assertFalse(sl[0]["own_title"])


class TableNoteSize(unittest.TestCase):
    def test_a_note_is_sized_against_the_shrunk_table(self):
        """When a table shrinks, its own text can end up smaller than the note below it -- the table is measured and compared against the shrunk text's actual size."""
        import build_deck
        B = chr(92)
        tex = build_deck.render_table({"header": ["a", "b"], "rows": [["x", "1.0"]],
                                       "note": "A note."}, fit=B + "linewidth")
        self.assertIn(B + "sbox{" + B + "ptTbl}", tex)
        self.assertIn(B + "ptTblPt pt*" + B + "linewidth/" + B + "wd" + B + "ptTbl", tex)
        self.assertIn(B + "adjustbox{max width=" + B + "linewidth}{" + B + "usebox{" + B + "ptTbl}}", tex)
        self.assertIn(B + "newsavebox{" + B + "ptTbl}", build_deck.PREAMBLE)


class ThirtyFourthTrial(unittest.TestCase):
    """Blind trial 34 (a diffusion-model paper -- formula-centric, a table inside a figure, algorithm boxes, user macros)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_subscript_groups_with_bold_letters_keep_their_subscript(self):
        """`\\mathbb{E}_{t,\\mathbf{x}_0,\\epsilon}` came out in the PPTX glued together as "Et,x₀,ε"."""
        B = chr(92)
        f = deckspec.math_to_text
        self.assertEqual(f("$" + B + "mathbb{E}_{t," + B + "mathbf{x}_0," + B + "epsilon}$"), u"E_(t,x₀,ε)")
        self.assertEqual(f("$" + B + "sqrt{" + B + "bar" + B + "alpha_t}$"), u"√ᾱₜ")
        self.assertEqual(f("$" + B + "frac{b}{" + B + "sqrt{1-a}}$"), u"b/√(1-a)")
        self.assertEqual(f("$x_{" + B + "text{large}}$"), "x_large")      # a text chunk is left as-is

    def test_macro_bodies_with_nested_braces_expand(self):
        """`\\newcommand{\\bmu}{{\\boldsymbol{\\mu}}}` failed to expand, and the symbol vanished from the table's row names."""
        B = chr(92)
        NL = chr(10)
        src = (B + "newcommand{" + B + "bmu}{{" + B + "boldsymbol{" + B + "mu}}}" + NL
               + B + "begin{document}" + NL + "The $" + B + "tilde" + B + "bmu$ prediction." + NL
               + B + "end{document}" + NL)
        d = self._tmp()
        p = os.path.join(d, "p.tex")
        deckspec.spit(p, src)
        self.assertIn(u"μ", deckspec.math_to_text(deckspec.read_tex(p)))

    def test_scaffold_keeps_header_figures_plots_and_algorithms(self):
        """A header figure (before `\\maketitle`), a pgfplots figure, and an algorithm box were all missing from the skeleton."""
        B = chr(92)
        NL = chr(10)
        src = (B + "begin{document}" + NL
               + B + "begin{figure}" + B + "includegraphics{head.png}" + B + "caption{Header.}" + B + "end{figure}" + NL
               + B + "maketitle" + NL + B + "section{Method}" + NL + "Text." + NL
               + B + "begin{figure}" + B + "begin{algorithm}" + B + "caption{Training}" + B + "begin{algorithmic}"
               + B + "STATE step" + B + "end{algorithmic}" + B + "end{algorithm}" + B + "end{figure}" + NL
               + B + "begin{figure}" + B + "begin{tikzpicture}" + B + "begin{axis}" + B + "addplot coordinates {(1,2)};"
               + B + "end{axis}" + B + "end{tikzpicture}" + B + "caption{Rate against distortion.}" + B + "end{figure}" + NL
               + B + "end{document}" + NL)
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        out = os.path.join(d, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(tex, out)
        with io.open(out, encoding="utf-8") as f_:
            body = f_.read()
        self.assertIn('path: "head.png"', body)
        self.assertIn("Algorithm box in the paper: Training", body)
        self.assertIn("Plot drawn with pgfplots/TikZ in the paper: Rate against distortion", body)
        deckspec.load(out)                     # left only as a comment, so the spec still loads cleanly

    def test_steps_become_numbered_lines(self):
        """With no shape to hold an algorithm, training/sampling algorithms used to be moved into the script text only."""
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + "  - title: x\n    steps: ['Take a clean sample.', 'Add noise.']\n")
        _m, slides, _ = deckspec.load(p)
        self.assertEqual(slides[0]["bullets"], ["> 1. Take a clean sample.", "> 2. Add noise."])
        self.assertEqual(deckspec.strip_markup(slides[0]["bullets"][0]), "1. Take a clean sample.")

    def test_plus_joined_names_count_as_said(self):
        import prose_audit
        slides = [{"n": 1, "screen": "PumpNet2+ADA reaches 3.35", "say": ["PumpNet2 plus ADA is close."]}]
        self.assertEqual(prose_audit.unspoken_terms(slides), [])

    def test_dot_labels_keep_a_connector_with_the_next_word(self):
        """"StyleGAN2 + ADA" used to wrap as "StyleGAN2 +" / "ADA," breaking the connector from its word."""
        import design
        if design.font_family() == design.FALLBACK_FAMILY:
            self.skipTest("deck font (Latin Modern Sans) not installed; the sizes depend on its metrics")
        import build_figs
        import figs_extra
        from unittest import mock
        d = self._tmp()
        t = {"header": ["", "FID"], "rows": [["Gated PixelCNN", "65.93"], ["PumpNet2 + ADA", "3.35"],
                                             ["Ours, simple", "3.17"]]}
        drawn = []
        real = build_figs.plt.Axes.set_yticklabels

        def spy(self_, labels, *a, **k):
            drawn.extend(str(x) for x in labels)
            return real(self_, labels, *a, **k)
        warn = []
        with mock.patch.object(build_figs.plt.Axes, "set_yticklabels", spy):
            figs_extra.draw_dots(t, os.path.join(d, "d.png"), (2.2, 2.0), warn, build_figs, log=True)
        self.assertEqual(warn, [])
        pump = [x for x in drawn if "PumpNet2" in x]
        self.assertTrue(pump, drawn)
        self.assertFalse(pump[0].split("\n")[0].rstrip().endswith("+"), pump)


class ThirtyFifthTrial(unittest.TestCase):
    """Blind trial 35 (SAC -- results are learning curves only, stages inside a pane, ICML authors, PPTX subscripts)."""

    HEAD = 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'

    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_pptx_math_subscripts_are_real_subscripts(self):
        """A letter with no Unicode subscript form printed in the PPTX as "V_ψ" / "Q_θ1," underscore and all."""
        import build_pptx
        B = chr(92)
        runs = build_pptx._scripts_split(build_pptx.math_runs("Value $V_" + B + "psi$: fit"))
        self.assertEqual(runs, [("Value V", None), (u"ψ", "-25000"), (": fit", None)])
        runs = build_pptx._scripts_split(build_pptx.math_runs("$Q_{" + B + "theta_1}$"))
        self.assertEqual(runs, [("Q", None), (u"θ1", "-25000")])
        # underscores and currency signs outside math are left untouched
        self.assertEqual(build_pptx._scripts_split(build_pptx.math_runs("max_len costs $4,150")),
                         [("max_len costs $4,150", None)])

    def test_steps_in_a_pane_hang_their_second_line(self):
        """`steps` could not be used inside a pane, and a "> 1." bullet's second line used to sit to the left of the number."""
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + "  - kind: columns\n    title: x\n    left:\n"
                                     "      steps: ['Fit the value.', 'Fit both Q-functions.']\n"
                                     "    right:\n      bullets: ['why']\n")
        _m, slides, _ = deckspec.load(p)
        self.assertEqual(slides[0]["left"]["bullets"], ["> 1. Fit the value.", "> 2. Fit both Q-functions."])
        self.assertEqual(build_deck.item_tex("> 2. Fit both Q-functions."), "\\item[2.] Fit both Q-functions.")
        self.assertEqual(build_deck.item_tex("> a caveat"), "\\item[] \\hspace{1em}a caveat")

    def test_pptx_parts_text_is_measured_at_the_pane_width(self):
        import build_pptx
        long = "The inverse temperature. Too small: near-uniform policy. Too large: near-deterministic, poor local minima."
        self.assertGreater(build_pptx._part_text_h({"text": long}, 2.45),
                           deckspec.fig_reserve({"text": long}))

    def test_ably_folds_to_able(self):
        self.assertEqual(deckcheck.fold("comparably"), deckcheck.fold("comparable"))
        self.assertFalse(deckcheck.coined_terms("comparable comparable comparable", "performs comparably"))

    def test_formula_slide_is_not_bullets_only(self):
        import refcheck
        d = self._tmp()
        p = os.path.join(d, "s.yaml")
        deckspec.spit(p, self.HEAD + "  - title: x\n    formula: '$a=b$'\n    bullets: ['a is b']\n")
        self.assertEqual(refcheck.bullets_only_slides(p), [])

    def test_scaffold_reads_icml_authors_and_lone_algorithms(self):
        B = chr(92)
        NL = chr(10)
        src = (B + "begin{document}" + NL + B + "icmlauthor{Ann Kettle}{lab}" + NL + B + "icmlauthor{Bo Ray}{lab}" + NL
               + B + "icmlaffiliation{lab}{Pump Lab, North University}" + NL + B + "section{Method}" + NL + "Text." + NL
               + B + "begin{algorithm}" + B + "caption{Pump cycle}" + B + "begin{algorithmic}" + B + "STATE x"
               + B + "end{algorithmic}" + B + "end{algorithm}" + NL + B + "end{document}" + NL)
        d = self._tmp()
        tex = os.path.join(d, "p.tex")
        deckspec.spit(tex, src)
        out = os.path.join(d, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(tex, out)
        with io.open(out, encoding="utf-8") as f_:
            body = f_.read()
        self.assertIn('author: "Ann Kettle, Bo Ray"', body)
        self.assertIn('institute: "Pump Lab, North University"', body)
        self.assertIn("Algorithm box in the paper: Pump cycle", body)

    def test_a_grid_of_paper_panels_counts_as_shown_for_shape(self):
        self.assertTrue(deckspec.pasted_with_highlight(
            {"kind": "figure", "figure": {"grid": {"images": [["a.pdf", "b.pdf"]]}}}))
        self.assertFalse(deckspec.pasted_with_highlight({"kind": "figure", "figure": {"path": "a.pdf"}}))


class ThirtyNinthTrialPptxBullets(unittest.TestCase):
    def test_a_wrapped_bullet_hangs_and_a_lone_list_is_centred(self):
        """Trial 39, defect 7 -- a PPTX bullet's second line used to tuck under the bullet marker, and a figure-less list stuck to the top."""
        try:
            import pptx  # noqa: F401
        except ImportError:
            self.skipTest("python-pptx not installed")
        import build_pptx
        tmp = tempfile.mkdtemp()
        try:
            spec = os.path.join(tmp, "s.yaml")
            deckspec.spit(spec,
                          'meta: {title: T}\nslides:\n'
                          '  - title: "Short list"\n'
                          "    bullets:\n"
                          "      - 'A first point that runs long enough to wrap onto a second line of the slide body.'\n"
                          "      - 'A second point.'\n")
            out = os.path.join(tmp, "t.pptx")
            build_pptx.build(spec, out)
            from pptx import Presentation
            prs = Presentation(out)
            H = prs.slide_height
            got = []
            for sl in prs.slides:
                for sh in sl.shapes:
                    if not sh.has_text_frame:
                        continue
                    for p in sh.text_frame.paragraphs:
                        if p.text.startswith(u"• "):
                            pPr = p._p.pPr
                            got.append((sh.top, int(pPr.get("marL")), int(pPr.get("indent"))))
            self.assertTrue(got)
            top, marL, ind = got[0]
            self.assertGreater(marL, 0)
            self.assertEqual(ind, -marL)                 # a hanging indent
            self.assertGreater(top, H * 0.25)            # centered instead of sitting right under the title
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ThirtyNinthTrialTickGap(unittest.TestCase):
    def _warn(self, names):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="tg-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        build_figs.draw_bars(
            {"header": ["", "one", "two"],
             "rows": [[n, "%.1f" % (10 + i), "%.1f" % (40 + i)] for i, n in enumerate(names)]},
            os.path.join(tmp, "b.png"), None, "share (%)", None, (5.51, 2.44), warn)
        return [w for w in warn if u"touch each other" in w]

    def test_names_that_touch_after_layout_are_reported(self):
        """Trial 39, defect 9 -- the estimate passed, yet neighboring names ended up touching once actually laid out."""
        long = ["Wednesday", "Thursday", "Saturday", "September", "November",
                "December", "Mountains", "Riverbank", "Lighthouse", "Waterfall"]
        self.assertTrue(self._warn(long))

    def test_short_names_pass(self):
        self.assertEqual(self._warn(["North", "East", "South", "West"]), [])

class ThirtyNinthTrialSiblingSize(unittest.TestCase):
    def test_group_names_and_counts_share_one_size(self):
        """Trial 39 -- a one-cell group name and its long count were shrunk on their own, printing at a different size from their siblings."""
        import design
        if design.font_family() == design.FALLBACK_FAMILY:
            self.skipTest("deck font (Latin Modern Sans) not installed; the sizes depend on its metrics")
        import build_figs
        d = {"kind": "pipeline", "rows": [{"label": "kitchen v2", "stages": [
            {"label": "recipes", "group": "1 choose the dishes", "count": "48", "inner": ["of top 900"]},
            {"label": "portions", "group": "1 choose the dishes", "count": "12,406", "inner": ["300+ grams"]},
            {"label": "orders", "group": "2 cook and taste", "count": "61,730", "mark": "a",
             "inner": ["up to 4 each", "by hand"]},
            {"label": "second tasting", "group": "3 more tasters", "count": "3+ per plate",
             "inner": ["lunch and dinner"]}],
            "out": "dinner"}]}
        got = {}
        real = build_figs.fit_text
        def spy(fig, ax, cx, cy, bw, bh, s, fs, *a, **k):
            got.setdefault(s, []).append(real(fig, ax, cx, cy, bw, bh, s, fs, *a, **k))
            return got[s][-1]
        build_figs.fit_text = spy
        tmp = tempfile.mkdtemp(prefix="sb-")
        try:
            build_figs.draw_diagram(d, os.path.join(tmp, "p.png"), slot=(5.5, 2.4), warn=[])
        finally:
            build_figs.fit_text = real
            shutil.rmtree(tmp, ignore_errors=True)
        grp = set(got[g][0] for g in ("1 choose the dishes", "2 cook and taste", "3 more tasters"))
        cnt = set(got[c][0] for c in ("48", "12,406", "61,730", "3+ per plate"))
        self.assertEqual(len(grp), 1, got)
        self.assertEqual(len(cnt), 1, got)
        chips = set(got[c][0] for c in ("of top 900", "300+ grams", "up to 4 each", "by hand",
                                        "lunch and dinner"))
        self.assertEqual(len(chips), 1, got)

    def test_sibling_pt_is_set_by_the_tightest(self):
        import build_figs
        fig, ax, xs, ys = build_figs._frame((4.0, 1.0))
        wide = build_figs.sibling_pt(fig, [("short", 2.0, 1.0)], 10)
        tight = build_figs.sibling_pt(fig, [("short", 2.0, 1.0), ("a much longer name", 0.6, 1.0)], 10)
        self.assertEqual(wide, 10)
        self.assertLess(tight, 10)

class FortiethTrialNotation(unittest.TestCase):
    """Blind trial 40 -- asterisk notation, old-style font switches, a superscript after a subscript, a LyX table, banned-word base forms."""

    def _marks(self, s):
        h = {k: (lambda k: lambda x: "<%s>%s</%s>" % (k, x, k))(k)
             for k in ("b", "i", "hit", "safe", "hi", "c")}
        return deckspec.render_markup(s, h)

    def test_a_star_after_a_letter_or_script_is_notation(self):
        self.assertEqual(self._marks(r"$B_*/L$ with $B_* \approx 2$"), r"$B_*/L$ with $B_* \approx 2$")
        self.assertEqual(self._marks(r"$C^* \sim$, $N^* \sim$"), r"$C^* \sim$, $N^* \sim$")
        self.assertEqual(self._marks("L* is small and L* again"), "L* is small and L* again")
        self.assertEqual(self._marks("a *word* and **this**"), "a <i>word</i> and <b>this</b>")
        self.assertEqual(self._marks("(*x*)"), "(<i>x</i>)")

    def test_old_font_switch_leaves_no_command(self):
        self.assertEqual(deckspec.math_to_text(r"$n_{\rm layer}$"), "n_layer")
        self.assertNotIn("\\", deckspec.math_to_text(r"$B_{\rm crit} \cdot {\bf x}$"))

    def test_factors_after_a_long_subscript_stay_apart(self):
        self.assertEqual(deckspec.math_to_text(r"$n_{\rm layer}d_{\rm model}$"), "n_layer d_model")
        self.assertEqual(deckspec.math_to_text(r"$x_{t+1}^2$"), u"x\u209c\u208a\u2081\u00b2")

    def test_pptx_subscript_stops_before_a_superscript(self):
        import build_pptx as bp
        got = bp.math_runs(r"$d_\mathrm{model}^2$")
        self.assertIn(bp.SUB_ON + "model" + bp.SUB_OFF + u"\u00b2", got)

    def test_tabularnewline_ends_a_row(self):
        import scaffold
        nl = "\\tabularnewline\n"
        src = ("\\begin{tabular}{ll}\\hline\nName & Size" + nl + "\\hline\n"
               "north & 12" + nl + "south & 34" + nl + "\\hline\n\\end{tabular}")
        pos = []
        got = scaffold.tables(src, pos)
        tbl = got[0] if isinstance(got, list) else got[0][0]
        self.assertTrue(tbl, got)
        self.assertIn("south", repr(got))
        self.assertIn("north", repr(got))

    def test_a_banned_word_catches_its_base_form_and_shows_itself(self):
        import deckcheck
        cfg = {"_read": lambda p: "proves\nshows that\n", "ban_file": "x"}
        pats = deckcheck.ban_patterns(cfg)
        hit = lambda t: any(re.search(p, t, re.I) for p in pats)
        for t in ("prove it", "was proven", "it proved", "show that", "it shown that"):
            self.assertTrue(hit(t), t)
        for t in ("improve", "provide", "not proven"):
            self.assertFalse(hit(t), t)
        self.assertEqual([deckcheck.example_for(p) for p in pats], ["proves", "shows that"])

class FortiethTrialTitleCopy(unittest.TestCase):
    PAPER = ("The loss scales as a power-law in T for a fixed model. "
             "Performance has a power-law relationship with each of the three scale factors.")

    def _copied(self, title):
        import prose_audit
        return prose_audit.titles_copied_from_paper([{"n": 3, "kind": "content", "title": title}],
                                                    self.PAPER)

    def test_a_run_of_function_words_is_not_copying(self):
        """Trial 40 -- "as a power law in" (three of five words being function words) was flagged as copying."""
        self.assertEqual(self._copied("Loss falls as a power law in each factor"), [])

    def test_a_run_of_content_words_still_is(self):
        self.assertTrue(self._copied("Performance has a power law relationship with each factor"))

class FortiethTrialReciprocalForms(unittest.TestCase):
    """Trial 40 -- the screen shows one form (exponent 2.5), the script shows its reciprocal form (0.4). All five panelists got stuck here."""

    def _deck(self, say):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="rf-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, "meta: {title: T}\nslides:\n"
                         "  - title: \"Queue length follows the wait\"\n"
                         "    bullets: ['Length grows as $W^{2.5}$ for every lane']\n"
                         "    say: ['%s']\n" % say)
        return prose_audit.reciprocal_forms(prose_audit.read_slides(p))

    def test_the_other_form_alone_is_reported(self):
        self.assertEqual(self._deck("The exponent is 0.4 in every lane."), [(1, 2.5, 0.4)])

    def test_saying_both_links_them(self):
        self.assertEqual(self._deck("It grows as W to the 2.5, one over the 0.4 we fit."), [])

    def test_unrelated_numbers_pass(self):
        self.assertEqual(self._deck("The exponent is 0.7 in every lane."), [])

class FortyFirstTrialScripts(unittest.TestCase):
    """Blind trial 41 -- an acronym spoken out in full, empty reference parentheses, the PPTX minus sign, rounding at a timing gate, callout color."""

    def _slides(self, bullets, say):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="ab-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, "meta: {title: T}\nslides:\n  - title: \"Where the queue stalls\"\n"
                         "    bullets: [%s]\n    say: ['%s']\n" % (bullets, say))
        return prose_audit.unspoken_terms(prose_audit.read_slides(p))

    def test_an_acronym_said_in_full_counts_as_said(self):
        self.assertEqual(self._slides("'The QM and the RTT stay flat, n/a elsewhere'",
                                      "The queue manager and the round-trip time stay flat."), [])

    def test_an_acronym_never_said_is_still_reported(self):
        got = self._slides("'The QM stays flat'", "The manager stays flat.")
        self.assertEqual([w for _, w in got], ["QM"])

    def test_an_emptied_reference_leaves_no_brackets(self):
        import scaffold
        self.assertEqual(scaffold.clean("The line (Sec.~\\ref{s:a}) has four stops."),
                         "The line has four stops.")
        self.assertEqual(scaffold.clean("value (\\ref{e}) and (Tab. \\ref{t}) here"), "value and here")

    def test_pptx_negative_numbers_use_the_minus_sign(self):
        try:
            import pptx  # noqa: F401
        except ImportError:
            self.skipTest("python-pptx")
        import build_pptx
        from pptx import Presentation
        prs = Presentation()
        tb = prs.slides.add_slide(prs.slide_layouts[6]).shapes.add_textbox(0, 0, 100, 100)
        from pptx.dml.color import RGBColor
        build_pptx.add_runs(tb.text_frame.paragraphs[0], "costs -5.9 at the low-cost stop", 12,
                            RGBColor(0, 0, 0))
        t = tb.text_frame.text
        self.assertIn(u"−5.9", t)
        self.assertIn("low-cost", t)

    def test_a_callout_takes_the_colour_of_the_bar_it_points_at(self):
        import build_figs
        import matplotlib.axes
        seen = []
        real = matplotlib.axes.Axes.annotate

        def spy(self_, *a, **k):
            seen.append(k.get("color"))
            return real(self_, *a, **k)
        tmp = tempfile.mkdtemp(prefix="co-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        t = {"header": ["", "one"], "rows": [["North", "-3.1"], ["East", "+0.0"], ["South", "<hit>-12.6</hit>"]]}
        matplotlib.axes.Axes.annotate = spy
        try:
            build_figs.draw_bars(t, os.path.join(tmp, "a.png"), None, "dT", None, (5.5, 2.4), [],
                                 {"at": "East", "series": 0, "text": "no change"})
            build_figs.draw_bars(t, os.path.join(tmp, "b.png"), None, "dT", None, (5.5, 2.4), [],
                                 {"at": "South", "series": 0, "text": "the drop"})
        finally:
            matplotlib.axes.Axes.annotate = real
        self.assertEqual(seen, [build_figs.INK, build_figs.HIT])

class FortyFirstTrialStandoutFlow(unittest.TestCase):
    def test_a_bold_last_step_that_wraps_does_not_overlap(self):
        """Trial 41 -- `flow`'s last box (bold) wrapped to two lines and overlapped the text below it. Height had been measured using regular weight."""
        try:
            import pptx  # noqa: F401
        except ImportError:
            self.skipTest("python-pptx")
        import build_pptx
        import fitcheck
        tmp = tempfile.mkdtemp(prefix="fl-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, "meta: {title: T}\nslides:\n  - kind: standout\n"
                         "    lead: \"Each parcel passes several hands.\"\n"
                         "    flow: [\"the depot clerk, the sorting belt and the night driver\", "
                         "\"the van that reaches the door before the working day is over\"]\n"
                         "    bullets: [\"Where does a parcel wait longest?\"]\n")
        out = os.path.join(tmp, "t.pptx")
        build_pptx.build(p, out)
        self.assertEqual([b for b in fitcheck.check_pptx(out) if u"overlap" in b[1]], [])

class FortyFirstTrialVerdictOverflow(unittest.TestCase):
    def test_a_verdict_spilling_into_the_next_tile_is_not_just_tight(self):
        """Trial 41 -- a verdict's text touched the neighboring tile's text, and this was reported merely as "tight"."""
        import build_figs
        tb1 = {"header": ["", "one", "two", "three"],
               "rows": [["alpha", "+27.1", "+33.6", "-11.7"],
                        ["beta", "not run", "<hit>-31.8</hit>", "<hit>-12.6</hit>"]]}
        tb2 = {"header": ["", "one", "two", "three"],
               "rows": [["alpha", "<hit>-18.9</hit>", "+24.1", "-14.3"],
                        ["beta", "not run", "<hit>-27.1</hit>", "+11.7"]]}
        tmp = tempfile.mkdtemp(prefix="vo-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        build_figs.draw_tiles([("A", tb1), ("B", tb2)], os.path.join(tmp, "v.png"),
                              slot=(4.0, 1.9), warn=warn,
                              verdict={"hit": "below the target", "plain": "within the stated target"})
        self.assertTrue([w for w in warn if u"doesn't fit" in w], warn)
        self.assertFalse([w for w in warn if u"fills to the margin" in w], warn)

class MinusMeasuredAsPrinted(unittest.TestCase):
    def test_a_hyphen_before_a_digit_is_measured_as_the_minus_it_prints_as(self):
        """PowerPoint prints U+2212, but measuring it at hyphen width made a table of negative numbers wider than estimated (regression from trial 23)."""
        w = deckspec.text_width_in
        self.assertAlmostEqual(w("-31.8", 12), w(u"−31.8", 12))
        self.assertAlmostEqual(w("low-cost", 12), w("low-cost", 12))
        self.assertLess(w("a-b", 12), w(u"a−b", 12) + 1e-9)

class FortySecondTrial(unittest.TestCase):
    """Blind trial 42 -- a bar for a missing value, a dots legend, feed for a two-row pipeline, reading a symbol aloud, a period inside a name, feedback warnings, labels."""

    def test_a_missing_value_is_not_drawn_as_a_zero_bar(self):
        import build_figs
        tmp = tempfile.mkdtemp(prefix="mb-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        seen = build_figs.draw_bars({"header": ["", "one", "two"],
                                     "rows": [["North", "-27.1", "-"], ["South", "-33.6", "-11.7"]]},
                                    os.path.join(tmp, "b.png"), None, "dT", None, (5.5, 2.4), [])
        said = [t for _p, t in seen]
        self.assertNotIn("+0.0", said)
        self.assertIn("-", said)

    def test_a_dots_series_that_starts_empty_keeps_its_legend(self):
        import figs_extra
        import build_figs
        import matplotlib.axes
        got = []
        real = matplotlib.axes.Axes.scatter

        def spy(self_, *a, **k):
            if k.get("label"):
                got.append(k["label"])
            return real(self_, *a, **k)
        tmp = tempfile.mkdtemp(prefix="dl-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        matplotlib.axes.Axes.scatter = spy
        try:
            figs_extra.draw_dots({"header": ["", "spring", "autumn"],
                                  "rows": [["North", "27.1", "-"], ["South", "33.6", "11.7"]]},
                                 os.path.join(tmp, "d.png"), (5.5, 2.4), [], build_figs)
        finally:
            matplotlib.axes.Axes.scatter = real
        self.assertIn("autumn", got)
        self.assertIn("spring", got)

    def test_feeds_sit_closer_to_their_own_row_than_to_the_next(self):
        import build_figs
        rows = [{"label": "North", "stages": [{"label": "receive", "feed": {"label": "orders"}},
                                              {"label": "sort"}]},
                {"label": "South", "stages": [{"label": "receive"}, {"label": "sort"}]}]
        tops = []
        real = build_figs._round

        def spy(ax, x, y, w, h, face, *a, **kw):
            tops.append((round(y, 3), round(y + h, 3), face))
            return real(ax, x, y, w, h, face, *a, **kw)
        tmp = tempfile.mkdtemp(prefix="fr-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        build_figs._round = spy
        try:
            build_figs.draw_pipeline({"kind": "pipeline", "rows": rows},
                                     os.path.join(tmp, "p.png"), (5.5, 2.55), [])
        finally:
            build_figs._round = real
        mods = sorted(set((y0, y1) for y0, y1, f in tops if f != "#FFFFFF"), reverse=True)
        feed = [(y0, y1) for y0, y1, f in tops if f == "#FFFFFF"]
        self.assertTrue(len(mods) >= 2 and feed, tops)
        north_bottom, south_top = mods[0][0], mods[-1][1]
        f_top, f_bottom = max(y1 for _, y1 in feed), min(y0 for y0, _ in feed)
        self.assertGreater(f_bottom - south_top, 2 * (north_bottom - f_top))

    def test_spoken_symbols_are_counted(self):
        import timing
        self.assertEqual(timing.words(u"ΔT fell by 12%"), 6)
        self.assertEqual(timing.words("no symbols here"), 3)

    def test_a_dotted_version_stays_one_name(self):
        import prose_audit
        self.assertIn("Model2.5-0.5B", prose_audit.JARGON.findall("We use Model2.5-0.5B here."))
        self.assertEqual(prose_audit.JARGON.findall("It ends here. Then v3"), ["It", "ends", "here", "Then", "v3"])

    def test_a_feedback_round_does_not_reprint_the_same_warnings(self):
        import build
        printed = set()
        buf = io.StringIO()
        with redirect_stdout(buf):
            build._say("x", ["same one", "other"], printed)
        first = buf.getvalue()
        buf = io.StringIO()
        with redirect_stdout(buf):
            build._say("x", ["same one", "new one"], printed)
        second = buf.getvalue()
        self.assertIn("same one", first)
        self.assertNotIn("same one", second)
        self.assertIn("new one", second)

    def test_a_label_with_nowhere_clean_to_go_is_reported(self):
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="lc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "ink.png")
        im = Image.new("RGB", (200, 200), (255, 255, 255))
        for yy in range(0, 200, 4):
            for xx in range(200):
                im.putpixel((xx, yy), (0, 0, 0))
        im.save(p)
        deckspec.LABEL_COVERED.clear()
        deckspec.label_place({"x": 0.2, "y": 0.3, "w": 0.5, "h": 0.4, "label": "look here"}, p)
        self.assertTrue(deckspec.LABEL_COVERED)
        deckspec.LABEL_COVERED.clear()
        clean = os.path.join(tmp, "clean.png")
        Image.new("RGB", (200, 200), (255, 255, 255)).save(clean)
        deckspec.label_place({"x": 0.2, "y": 0.3, "w": 0.5, "h": 0.4, "label": "look here"}, clean)
        self.assertFalse(deckspec.LABEL_COVERED)

class FortyFourthTrial(unittest.TestCase):
    """Blind trial 44 (PDF manuscript) -- the builder's own typesetting counted as a word, space-separated thousands, splitting `--omit`, reading large numbers aloud, subscripts, references, titles."""

    def test_the_builders_own_font_size_macro_is_not_a_deck_word(self):
        cleaned = deckcheck.screen_text(r"a \xdef\ptTblPt{\csname f@size\endcsname}% b")
        self.assertNotIn("size", cleaned)

    def test_space_separated_thousands_are_one_number(self):
        self.assertEqual(deckcheck.flat_thousands("1 in 203 000 years"), "1 in 203000 years")
        self.assertEqual(deckcheck.flat_thousands("Table 2 150 trials"), "Table 2 150 trials")

    def test_omit_list_splits_the_same_in_any_order(self):
        import diffcheck
        self.assertEqual(sorted(diffcheck.split_omit("0.99,108,109")),
                         sorted(diffcheck.split_omit("108,109,0.99")))
        self.assertEqual(diffcheck.split_omit("a phrase;14,562;0.99"), ["a phrase", "14,562", "0.99"])

    def test_large_integers_are_counted_as_spoken(self):
        import timing
        self.assertEqual(timing.words("203000"), 4)
        self.assertEqual(timing.words("1916"), 2)
        self.assertEqual(timing.words("1500"), 2)

    def _pdf(self, draw):
        import fitz
        tmp = tempfile.mkdtemp(prefix="pp-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "p.pdf")
        d = fitz.open()
        pg = d.new_page()
        draw(pg)
        d.save(p)
        return fitz.open(p)

    def test_a_raised_small_number_becomes_a_superscript(self):
        import pdf_paper

        def draw(pg):
            pg.insert_text((72, 100), "a distance of 10", fontsize=10)
            x = 72 + fitz_len("a distance of 10", 10)
            pg.insert_text((x, 96), "13", fontsize=7)
            pg.insert_text((x + fitz_len("13", 7) + 1, 100), " km away", fontsize=10)

        def fitz_len(t, sz):
            import fitz
            return fitz.get_text_length(t, fontsize=sz)
        doc = self._pdf(draw)
        txt = " ".join(t for t, _s, _b, _r in pdf_paper._lines(doc[0]))
        self.assertIn("10^13", txt)

    def test_a_numbered_reference_list_gets_a_heading_and_authors_are_dropped(self):
        import pdf_paper
        md = ("# Title\n\n## CONCLUSION\n\nWe saw it.\n\n"
              "[1] A. Writer, J. Journal 12, 34 (1999). [2] B. Author, Rev. 5, 6 (2001).\n\n"
              "A. One,^1 B. Two,^2 C. Three,^1,3 D. Four,^4\n")
        out = pdf_paper.back_matter(md)
        self.assertIn("## References", out)
        self.assertIn("[2] B. Author", out)
        self.assertNotIn("B. Two", out)
        self.assertTrue(out.index("## References") > out.index("We saw it."))

    def test_deckcheck_reads_a_markdown_source_only_up_to_its_references(self):
        tmp = tempfile.mkdtemp(prefix="rc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = os.path.join(tmp, "paper.md")
        deckspec.spit(src, u"# T\n\nWe measured 27.1 here.\n\n## References\n\n[1] X, J. 33.6 (1999).\n")
        cfg = {"_read": lambda p: deckspec.slurp(p) if p and os.path.isfile(p) else "",
               "_P": lambda p: p, "source": [src], "derivative": {}}
        S = deckcheck.Stuff(cfg)
        self.assertIn("27.1", S.source)
        self.assertNotIn("33.6", S.source)

    def test_the_largest_first_page_line_is_the_title(self):
        import pdf_paper

        def draw(pg):
            pg.insert_text((72, 80), "A Short Paper Title", fontsize=12.4999)
            for i in range(30):
                pg.insert_text((72, 120 + 14 * i), "body text line number %d of the paper" % i, fontsize=10.5)
        doc = self._pdf(draw)
        self.assertTrue(pdf_paper.to_markdown(doc).startswith("# A Short Paper Title"))

class FortyThirdTrial(unittest.TestCase):
    """Blind trial 43 -- a LaTeX `--` blank cell, PPTX pane ordering, a section that points at a figure."""

    def test_a_latex_dash_is_a_blank_cell(self):
        import build_figs
        self.assertIn("--", build_figs.BLANK_CELLS)
        self.assertIn("---", build_figs.BLANK_CELLS)

    def test_a_pane_block_comes_before_its_text_in_the_pptx_as_in_the_deck(self):
        try:
            import pptx  # noqa: F401
        except ImportError:
            self.skipTest("python-pptx")
        import build_pptx
        from pptx import Presentation
        tmp = tempfile.mkdtemp(prefix="po-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, "meta: {title: T}\nslides:\n  - kind: columns\n    title: \"Two sides\"\n"
                         "    left: {bullets: [\"a point\"]}\n"
                         "    right: {block: {title: \"Box title\", text: \"box words\"}, text: \"pane footnote\"}\n")
        out = os.path.join(tmp, "t.pptx")
        build_pptx.build(p, out)
        tops = {}
        for sh in Presentation(out).slides[0].shapes:
            if sh.has_text_frame:
                for k in ("Box title", "pane footnote"):
                    if k in sh.text_frame.text:
                        tops[k] = sh.top
        self.assertLess(tops["Box title"], tops["pane footnote"])

    def test_a_figure_cited_elsewhere_says_where(self):
        import scaffold
        tmp = tempfile.mkdtemp(prefix="fc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = os.path.join(tmp, "paper.tex")
        deckspec.spit(src, "\\documentclass{article}\\begin{document}\n"
                           "\\section{Method}\nWe plan the routes.\n\n"
                           "\\begin{figure}\\includegraphics{routes.png}\\caption{Routes.}\\label{fig:routes}\\end{figure}\n\n"
                           "\\section{Results}\nLate buses cluster at noon (Fig.~\\ref{fig:routes}).\n\n"
                           "\\end{document}\n")
        out = os.path.join(tmp, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(src, out)
        txt = deckspec.slurp(out)
        self.assertIn("# cited in: Results", txt)

class SpokenValuesOnScreen(unittest.TestCase):
    """Trials 41/43 -- a number spoken in the script was missing from the screen. A Roman-numeral table number is not jargon."""

    def _audit(self, body):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="sv-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, "meta: {title: T}\nslides:\n" + body)
        return prose_audit.spoken_only_values(prose_audit.read_slides(p))

    def test_a_spoken_value_missing_from_the_screen_is_reported(self):
        got = self._audit("  - title: \"Late buses\"\n    bullets: [\"Route 7 runs 27.1 minutes late\"]\n"
                          "    say: [\"Route 7 runs 27.1 minutes late, and route 12 only 11.7.\"]\n")
        self.assertEqual([(n, v) for n, v, _p in got], [(1, [11.7])])

    def test_a_value_on_the_screen_or_the_slide_before_passes(self):
        got = self._audit("  - title: \"Late buses\"\n    bullets: [\"Route 12 runs 11.7 minutes late\"]\n"
                          "  - title: \"Why\"\n    bullets: [\"Traffic\"]\n"
                          "    say: [\"The 11.7 minutes come from one junction.\"]\n")
        self.assertEqual(got, [])

    def test_a_roman_table_number_is_not_jargon(self):
        import prose_audit
        self.assertFalse(prose_audit.looks_like_jargon("III"))
        self.assertTrue(prose_audit.looks_like_jargon("RTT"))


class FortySixthTrial(unittest.TestCase):
    """Blind trial 46 (a position paper -- no tables or figures) -- typesetting-as-word, wrapping big text,
    one size for graph nodes, an author `\\&`, comma-joined institutions, font family, neighbor-node hedges/scope hedges."""

    def test_the_font_size_macro_is_not_a_term_either(self):
        got = deckcheck.term_text(r"\begin{frame}a \xdef\ptTblPt{\csname f@size\endcsname}% b\end{frame}",
                                  "latex")
        self.assertNotIn("size", str(got))

    def test_a_long_standout_value_and_note_wrap_inside_their_cell(self):
        import build_deck
        got = "\n".join(build_deck.big_body({"big": [{
            "value": "Say what the cell holds before you say how it was charged on the bench",
            "note": "a second line that is also far too long to sit on one line under the value, "
                    "because it goes on to name the rack, the charger and the room it stood in"}]}))
        self.assertEqual(got.count(chr(92) + "parbox{"), 2, got)
        short = "\n".join(build_deck.big_body({"big": [{"value": "4 cells", "note": "per rack"}]}))
        self.assertNotIn(chr(92) + "parbox{", short)

    def test_graph_node_labels_share_one_size(self):
        import build_figs
        sizes = []
        real = build_figs.fit_text

        def _spy(fig, ax, x, y, w, h, text, fs, *a, **k):
            if k.get("fontweight") == "bold":
                sizes.append(fs)
            return real(fig, ax, x, y, w, h, text, fs, *a, **k)
        d = {"kind": "graph",
             "nodes": [{"id": "a", "label": "rack", "col": 0, "row": 0},
                       {"id": "b", "label": "the second cell on the rack",
                        "col": 1, "row": 0},
                       {"id": "c", "label": "shelf", "col": 2, "row": 0},
                       {"id": "e", "label": "room", "col": 3, "row": 0}],
             "edges": [{"from": "a", "to": "b"}]}
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(build_figs, "fit_text", _spy):
            build_figs.draw_diagram(d, os.path.join(tmp, "g.png"), warn=[])
        self.assertEqual(len(sizes), 4, sizes)
        self.assertEqual(len(set(sizes)), 1, sizes)
        self.assertLess(sizes[0], build_figs.BODY_PT)

    def _scaffold(self, author):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "p.tex")
        deckspec.spit(p, "\\documentclass{article}\\title{Cells}\n\\author{" + author + "}\n"
                         "\\begin{document}\\section{Results}Text.\\end{document}\n")
        o = os.path.join(tmp, "s.yaml")
        with redirect_stdout(io.StringIO()):
            scaffold.build(p, o)
        return deckspec.slurp(o)

    def test_an_ampersand_separates_author_names(self):
        got = self._scaffold("Ann Lee \\enskip \\& Bo Kim")
        self.assertIn('author: "Ann Lee, Bo Kim"', got)

    def test_institutes_joined_by_commas_are_split_only_at_top_level_names(self):
        got = self._scaffold("Ann Lee \\qquad Bo Kim \\\\\n\\large North University, South Institute")
        self.assertIn('institute: ["North University", "South Institute"]', got)
        got = self._scaffold("Ann Lee \\qquad Bo Kim \\\\\n\\large Cell Lab, North University")
        self.assertIn('institute: "Cell Lab, North University"', got)

    def test_font_family_drops_subset_weight_style_and_size(self):
        import fitcheck
        self.assertEqual(fitcheck.font_family("ABCDEF+LMSans8-Oblique"), "LMSans")
        self.assertEqual(fitcheck.font_family("LMSans10-Bold"), "LMSans")
        self.assertEqual(fitcheck.font_family("Helvetica"), "Helvetica")

    def _flat_note(self, title):
        import prose_audit
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, 'meta: {title: T, author: A, venue: V, date: D}\nslides:\n'
                         '  - kind: figure\n    title: "%s"\n'
                         '    diagram:\n      kind: flow\n      boxes:\n'
                         '        - {label: "Intake"}\n        - {label: "Pump"}\n'
                         '    say: ["Two parts."]\n' % title)
        buf = io.StringIO()
        with redirect_stdout(buf):
            prose_audit.main(p)
        return buf.getvalue()

    def test_the_arrow_note_appears_only_when_an_arrow_was_printed(self):
        out = self._flat_note("How the water moves")
        self.assertIn(u"have no emphasis at all.", out)
        self.assertNotIn(u"This points to", out)
        out = self._flat_note("The pump sets the rate")
        self.assertIn(u"\"Pump\"", out)
        self.assertIn(u"This points to", out)

    def test_sentences_that_announce_a_count_are_listed(self):
        import diffcheck
        body = ("Queues grow for two reasons. Staff take breaks. Orders arrive in bursts. "
                "The two reasons interact on Mondays. The kiosk has a different limit. "
                "We ran two sites.")
        got = diffcheck.announced_counts(body, diffcheck.sentences)
        self.assertEqual(got, ["Queues grow for two reasons.", "The kiosk has a different limit."])

    def test_drawn_bar_values_use_the_same_minus_as_the_ticks(self):
        import build_figs
        from matplotlib.axes import Axes
        drawn = []
        real = Axes.text

        def _spy(ax, x, y, s, *a, **k):
            drawn.append(str(s))
            return real(ax, x, y, s, *a, **k)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(Axes, "text", _spy):
            build_figs.draw_bars({"header": ["", "one"], "rows": [["North", "-2.85"], ["East", "+3.1"]]},
                                 os.path.join(tmp, "b.png"), None, "dT", None, (5.5, 2.4), [])
        self.assertIn(u"−2.85", drawn)
        self.assertNotIn("-2.85", drawn)

    def test_space_grouped_thousands_on_the_deck_side_are_one_number(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        deckspec.spit(os.path.join(tmp, "p.tex"), "The rack held 1 in 311 000 cells.\n")
        deckspec.spit(os.path.join(tmp, "d.tex"), "\\begin{frame}1 in 311 000 cells\\end{frame}\n")
        deckspec.spit(os.path.join(tmp, "c.yaml"), "root: .\nsource: [p.tex]\nderivative: {deck: d.tex}\n"
                                                   "syntax: latex\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            deckcheck.main(os.path.join(tmp, "c.yaml"))
        self.assertIn(u"decimals", buf.getvalue())
        self.assertNotIn(u"integers not in the source: 000", buf.getvalue())
        self.assertNotIn(u"integers not in the source: 311", buf.getvalue())

    def test_script_times_add_up_to_the_total(self):
        import build_script
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        words = "rack cell shelf spare charge room door lamp wire".split()
        for k in range(1, 7):
            p = os.path.join(tmp, "s%d.yaml" % k)
            body = "".join('  - title: "Rack %d"\n    bullets: ["Cells"]\n    say: ["%s."]\n'
                           % (i, " ".join(words[(i * k + j) % 9] for j in range(3 + (i * k) % 11)))
                           for i in range(12))
            deckspec.spit(p, "meta: {title: T, author: A, venue: V, date: D}\nslides:\n" + body)
            out = os.path.join(tmp, "script%d.md" % k)
            with redirect_stdout(io.StringIO()):
                build_script.build(p, out)
            md = deckspec.slurp(out)
            each = [int(x) for x in re.findall(r"`\d+:\d\d`\s+\S+(?: slide)? (\d+)s", md)]
            runs = re.findall(r"^`(\d+):(\d\d)`", md, re.M)
            last = int(runs[-1][0]) * 60 + int(runs[-1][1])
            self.assertEqual(len(each), 12, md[:600])
            self.assertEqual(sum(each), last, k)
            # per slide -- the running total is the sum of per-slide seconds up through that slide
            acc = [sum(each[:i + 1]) for i in range(len(each))]
            self.assertEqual(acc, [int(a) * 60 + int(b) for a, b in runs], k)
            tot = re.search(r"\*\*(?:Total|전체) (\d+):(\d\d)\*\*", md)
            self.assertEqual(int(tot.group(1)) * 60 + int(tot.group(2)), last, k)

    def test_captions_are_clipped_at_a_sentence_or_a_word(self):
        cap = ("One trial of the dry cell, run from the same charge under four chargers. "
               "The task is to hold the charge through a cold night on the bench.")
        got = scaffold.clip_caption(cap, 110)
        self.assertEqual(got, "One trial of the dry cell, run from the same charge under four chargers.")
        got = scaffold.clip_caption("word " * 40, 30)
        self.assertTrue(got.endswith("word..."), got)
        self.assertEqual(scaffold.clip_caption("short", 110), "short")

    def test_a_one_line_figure_lead_leaves_the_picture_its_height(self):
        import build_pptx
        from PIL import Image
        from pptx import Presentation
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        Image.new("RGB", (1600, 520), "white").save(os.path.join(tmp, "wide.png"))
        spec = os.path.join(tmp, "s.yaml")
        deckspec.spit(spec, 'meta: {title: T}\nslides:\n  - title: "The rack"\n'
                            '    figure: {path: wide.png, lead: "Boxed: the two shelves"}\n'
                            '    bullets: ["Each shelf holds one cell and one spare, and the spare is charged first."]\n'
                            '    fine: ["The rack stood in the cold room for the whole test."]\n')
        out = os.path.join(tmp, "t.pptx")
        with redirect_stdout(io.StringIO()):
            build_pptx.build(spec, out, figdir=tmp)
        sl = Presentation(out).slides[0]
        lead = [sh for sh in sl.shapes if sh.has_text_frame and "Boxed" in sh.text_frame.text][0]
        self.assertLess(lead.height / 914400.0, 0.5)

    def test_a_full_height_box_label_that_covers_ink_is_reported(self):
        from PIL import Image
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "ink.png")
        im = Image.new("RGB", (200, 200), (255, 255, 255))
        for yy in range(0, 30, 3):
            for xx in range(200):
                im.putpixel((xx, yy), (0, 0, 0))
        im.save(p)
        deckspec.LABEL_COVERED.clear()
        self.addCleanup(deckspec.LABEL_COVERED.clear)
        at = deckspec.label_place({"x": 0.3, "y": 0.0, "w": 0.4, "h": 1.0, "label": "middle rack"}, p)
        self.assertEqual(at, "inside")
        self.assertTrue(deckspec.LABEL_COVERED)

    def _over(self, paper, deck):
        return Overclaims._run(self, paper, deck)

    def test_a_hedge_in_the_next_clause_is_not_the_deck_sentences_hedge(self):
        paper = ("\\section{Terms}The dry cell may seem steady; its charge capacity drops in the "
                 "cold on each bench test.\n")
        out = self._over(paper, ["Charge capacity drops in the cold on each bench test."])
        self.assertIn(u"none — the deck doesn't state as flat claims", out)

    def test_a_scope_hedge_in_the_deck_is_a_hedge(self):
        paper = "\\section{Results}The dry cell may beat the wet cell in charge capacity on the bench.\n"
        out = self._over(paper, ["In the rooms we tested, the dry cell always beats the wet cell in "
                                 "charge capacity on the bench."])
        self.assertIn(u"none — the deck doesn't state as flat claims", out)
        out = self._over(paper, ["In the rooms, the dry cell always beats the wet cell in "
                                 "charge capacity on the bench."])
        self.assertNotIn(u"none — the deck doesn't state as flat claims", out)

class FortySeventhTrial(unittest.TestCase):
    """Blind trial 47 (a reproducibility paper) -- a space after a minus sign, quoted figure paths, stacked
    lines in a cell, legend ordering, a chart title inside a pane, cover-page year."""

    def test_the_builders_minus_and_its_space_read_as_one_negative_number(self):
        got = deckcheck.screen_text("\\begin{frame}t = \\textminus 7.25 and \\textminus{}3\\end{frame}")
        self.assertIn("-7.25", got)
        self.assertIn("-3", got)

    def test_quoted_figure_paths_lose_their_quotes(self):
        self.assertEqual(scaffold._gpath('"images/Rack,_Cold_Room_"'), "images/Rack,_Cold_Room_")
        self.assertEqual(scaffold._gpath("images/rack.png"), "images/rack.png")

    def test_stacked_lines_in_a_cell_are_one_cell(self):
        src = ("\\begin{tabular}{|c|c|}\\hline\n"
               "\\begin{tabular}[c]{@{}l@{}}Rack\\\\ (cold)\\end{tabular} & Cells \\\\ \\hline\n"
               "A & \\shortstack{t=3.1\\\\p=0.2} \\\\ \\hline\nB & 3 \\\\ \\hline\n\\end{tabular}\n")
        flat = scaffold.flatten_stacks(src)
        self.assertEqual(len(flat), len(src))
        got = scaffold.tables(flat)
        tabs = got[0] if isinstance(got, tuple) else got
        self.assertEqual(len(tabs), 1, got)
        align, head, rows = tabs[0][:3]
        self.assertIn("Rack (cold)", " ".join(head))
        self.assertEqual(len(rows), 2, rows)
        self.assertIn("t=3.1 p=0.2", " ".join(rows[0]))

    def _legend_labels(self, series):
        import build_figs
        from matplotlib.axes import Axes
        got = []
        real = Axes.legend

        def _spy(ax, *a, **k):
            got.append(([h.get_label() for h in k.get("handles") or []], k.get("ncol")))
            return real(ax, *a, **k)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        rows = [["North"] + ["%d" % (i + 2) for i in range(len(series))],
                ["East"] + ["%d" % (i + 3) for i in range(len(series))]]
        with mock.patch.object(Axes, "legend", _spy):
            build_figs.draw_bars({"header": [""] + series, "rows": rows},
                                 os.path.join(tmp, "b.png"), None, "cells", None, (5.5, 2.4), [])
        return got[-1]

    def test_a_four_series_legend_reads_in_bar_order(self):
        labs, nc = self._legend_labels(["rack", "shelf", "door", "lamp"])
        # matches column order for a legend that fills vertically: read across, it's rack shelf / door lamp
        r = -(-4 // nc)
        shown = [labs[j * r + k] for k in range(r) for j in range(nc) if j * r + k < 4]
        self.assertEqual(shown, ["rack", "shelf", "door", "lamp"])
        self.assertIn(nc, (4, 2))

    def test_a_chart_title_folds_to_its_slot(self):
        import build_figs
        from matplotlib.axes import Axes
        titles = []
        real = Axes.set_title

        def _spy(ax, s, *a, **k):
            titles.append(s)
            return real(ax, s, *a, **k)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(Axes, "set_title", _spy):
            build_figs.draw_bars({"header": ["", "one"], "rows": [["North", "2"], ["East", "3"]]},
                                 os.path.join(tmp, "b.png"),
                                 "Charge held by each rack after a night in the cold room", "cells",
                                 None, (2.2, 2.4), [])
        self.assertTrue(titles and "\n" in titles[-1], titles)

    def test_title_page_years_are_not_content_numbers(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        deckspec.spit(os.path.join(tmp, "p.tex"), "The rack held 31 cells.\n")
        deckspec.spit(os.path.join(tmp, "d.tex"),
                      "\\begin{frame}Cold Rooms 2031\\end{frame}\\begin{frame}31 cells\\end{frame}\n")
        deckspec.spit(os.path.join(tmp, "s.yaml"), "meta: {title: T, venue: Cold Rooms 2031}\nslides:\n"
                                                   "  - title: \"R\"\n    bullets: [\"31 cells\"]\n")
        deckspec.spit(os.path.join(tmp, "c.yaml"), "root: .\nsource: [p.tex]\nspec: s.yaml\n"
                                                   "derivative: {deck: d.tex}\nsyntax: latex\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            deckcheck.main(os.path.join(tmp, "c.yaml"))
        self.assertNotIn(u"integers not in the source: 2031", buf.getvalue())
        self.assertIn(u"decimals", buf.getvalue())

    def _unused(self, paper):
        import diffcheck
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        src = os.path.join(tmp, "p.tex")
        deckspec.spit(src, paper)
        buf = io.StringIO()
        with redirect_stdout(buf):
            diffcheck.against_source("The rack held 27.1 cells.", src, 10, "", (), ["The rack held 27.1 cells."])
        out = buf.getvalue()
        return out[:out.index("prompt to check by eye")]

    def test_the_latex_bibliography_is_cut_before_counting_values(self):
        body = ("\\begin{document}\\section{Results}" + "The rack held 27.1 cells on the bench. " * 12
                + "\n\\bibliography{refs}\nAuthor notes: the shelf report runs to 33.6 pages.\n"
                  "\\end{document}\n")
        self.assertNotIn("33.6", self._unused(body))

    def test_numbered_citations_are_not_values(self):
        body = ("\\begin{document}\\section{Results}The rack held 27.1 cells [108,109], as before [8\u201310]."
                "\\end{document}\n")
        out = self._unused(body)
        self.assertNotIn("108", out)
        self.assertNotIn("8\u201310", out)


class TranslationReview(unittest.TestCase):
    """Bugs the English translation of the scripts introduced, found by comparing it with the original."""

    def test_settle_keeps_a_clipped_text_warning_while_folding_small_text(self):
        """\u2605The fold filter matched a bare "on screen", which the clipped-text warning also contains
        ("... doesn't appear on screen"), so that warning vanished."""
        import build_figs
        pend = (u"racks.png: 3 rows x 4 columns in this space doesn't fit. width falls short by 0.42 inches",
                False, "racks.png")
        small = u"racks.png: text is 5.9pt on screen (floor 7pt): 'Rack 3'"
        clipped = u"racks.png: text was clipped outside the figure -- it doesn't appear on screen: 'Rack 12'"
        out = []
        build_figs._settle(out, pend, [small, clipped])
        self.assertIn(clipped, out)                   # a different problem is passed on
        self.assertNotIn(small, out)                  # the small-text line is folded into the summary
        self.assertTrue(any(u"this fits the space, but" in x and u"5.9" in x for x in out), out)

    def test_a_tile_row_names_its_blank_count_before_its_cell_count(self):
        import build_figs
        tb = {"header": ["", "Mon", "Tue", "Wed", "Thu"],
              "rows": [["Bus 7", "+2.4", "-", "-", "n/a"],
                       ["Bus 12", "+0.7", "+1.2", "-0.3", "+0.4"],
                       ["Bus 31", "<hit>-2.2</hit>", "+0.1", "+0.9", "+1.1"]]}
        tmp = tempfile.mkdtemp(prefix="tr-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        build_figs.draw_tiles([("Depot", tb)], os.path.join(tmp, "t.png"), warn=warn)
        got = [re.search(u"\"Bus 7\" has (\\d+) of (\\d+) cells blank", w) for w in warn]
        got = [m for m in got if m]
        self.assertEqual(len(got), 1, warn)
        self.assertEqual((int(got[0].group(1)), int(got[0].group(2))), (3, 4))

    def test_small_text_with_an_apostrophe_is_grouped(self):
        """\u2605`%r` quotes text containing an apostrophe with double quotes, and the grouping pattern
        only accepted single quotes, so those lines were printed one by one."""
        import build
        import build_figs
        warn = []
        build_figs._note_size(5.9, "the bus's route", warn, None, "buses.png")
        build_figs._note_size(5.9, "the driver's shift", warn, None, "buses.png")
        self.assertEqual(len(warn), 2, warn)
        self.assertTrue(all(u'"' in w for w in warn), warn)
        with redirect_stdout(io.StringIO()):
            got = build._say("x", warn + ["other"])
        self.assertEqual(len(got), 2, got)
        self.assertTrue(any(u"buses.png: 2 string(s)" in w for w in got), got)

    def test_a_count_mismatch_reads_as_a_sentence(self):
        import prose_audit
        tmp = tempfile.mkdtemp(prefix="tr-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "s.yaml")
        deckspec.spit(p, "meta: {title: T, author: A, venue: V, date: D}\nslides:\n"
                         '  - kind: figure\n    title: "The five rooms we compare"\n'
                         '    figure: {path: f.png, shows: 3}\n    say: ["Here."]\n')
        buf = io.StringIO()
        with redirect_stdout(buf):
            prose_audit.main(p)
        self.assertIn(u"the text says 5 but there are 3 items in the figure", buf.getvalue())

    def test_the_no_gap_warning_names_the_upper_box_first(self):
        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt
        except ImportError:
            self.skipTest("python-pptx")
        import fitcheck
        tmp = tempfile.mkdtemp(prefix="tr-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        # the lower box is added first, so shape order alone would put it first
        for y, text in ((2.22, "Lower rack"), (2.0, "Upper rack")):
            tb = sl.shapes.add_textbox(Inches(0.6), Inches(y), Inches(6.0), Inches(0.5))
            tb.text_frame.word_wrap = True
            r = tb.text_frame.paragraphs[0].add_run()
            r.text = text
            r.font.size = Pt(18)
        p = os.path.join(tmp, "g.pptx")
        prs.save(p)
        msgs = [m for _, k, m in fitcheck.check_pptx(p) if k == u"overlap"]
        self.assertEqual(len(msgs), 1, msgs)
        self.assertTrue(msgs[0].startswith(u"\"Upper rack\" has \"Lower rack\" directly below it with no gap"), msgs)

    def test_the_underfill_advice_is_one_sentence(self):
        """\u2605The kind-specific way ends in ", " and the fallback used to start with a capital,
        which gave "... each layer, Push the figure ...". With no kind-specific way, the fallback
        opens the sentence and keeps its capital."""
        from PIL import Image
        import build_figs
        tmp = tempfile.mkdtemp(prefix="tr-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "thin.png")
        Image.new("RGB", (1100, 100), "white").save(p)
        warn = []
        build_figs.underfill(p, (5.51, 2.44), "thin.png", warn, "stack")
        self.assertEqual(len(warn), 1, warn)
        self.assertIn(u"write in what changes at each layer, or push the figure to one side", warn[0])
        self.assertIn(u"(minimum %d%%)" % round(build_figs.FIG_SHARE_MIN * 100), warn[0])
        warn = []
        build_figs.underfill(p, (5.51, 2.44), "thin.png", warn, "graph")
        self.assertEqual(len(warn), 1, warn)
        self.assertIn(u"there's little to show: Push the figure to one side", warn[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
