# -*- coding: utf-8 -*-
"""Defects a blind trial reported: two checkers counting the same word differently, figure
pieces drawn over each other with no warning, a warning that misstated its count, feedback
that shrank nothing, and claims that could only be pinned by a LaTeX regex.

    python -m unittest discover tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import deckcheck      # noqa: E402
import deckspec       # noqa: E402


class CheckersAndFigures(unittest.TestCase):

    def _tmp(self):
        d = tempfile.mkdtemp(prefix="r48-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_prose_audit_counts_words_inside_figures_once(self):
        """deckcheck H read a chart's takeaway from the sidecar and failed on a word used three
        times, while prose_audit 0a said 0 kinds. The title was also counted twice."""
        import prose_audit
        s = {"title": "Each coating wrecks a different station",
             "chart": {"from": "self", "kind": "bars",
                       "takeaway": "Wax wrecks the coast; resin wrecks the hills."}}
        self.assertIn("resin wrecks the hills", " ".join(prose_audit.figure_words(s)))
        row = {"screen": "Each coating wrecks a different station",
               "fig_words": " ".join(prose_audit.figure_words(s))}
        self.assertEqual(prose_audit.deck_words([row]).count("wrecks"), 3)

    def test_feed_arrow_does_not_run_through_the_count(self):
        """A stage's input arrow climbed straight up the middle, through its count text."""
        import build_figs
        import matplotlib.pyplot as plt
        arrows, texts = [], []
        real_arrow, real_text = build_figs._arrow_at, build_figs.fit_text

        def spy_arrow(ax, p0, p1, weight="normal"):
            arrows.append((p0, p1))
            return real_arrow(ax, p0, p1, weight)

        def spy_text(fig, ax, x, y, *a, **k):
            texts.append((x, a[2] if len(a) > 2 else None))
            return real_text(fig, ax, x, y, *a, **k)
        d = {"kind": "pipeline", "rows": [
            {"label": "North", "stages": [
                {"label": "Sensor array", "count": "12 sensors",
                 "feed": {"label": "rain gauge", "sub": "hourly"}},
                {"label": "Logger", "count": "2 units"}]},
            {"label": "South", "stages": [{"label": "Sensor array", "count": "7 sensors"},
                                          {"label": "Logger", "count": "1 unit"}]}]}
        with mock.patch.object(build_figs, "_arrow_at", spy_arrow), \
                mock.patch.object(build_figs, "fit_text", spy_text):
            build_figs.draw_pipeline(d, os.path.join(self._tmp(), "p.png"), (8.0, 3.45), [])
        plt.close("all")
        up = [p0[0] for p0, p1 in arrows if abs(p0[0] - p1[0]) < 1e-9 and p1[1] > p0[1]]
        count_x = [x for x, t in texts if t == "12 sensors"]
        self.assertTrue(up and count_x, (arrows, texts))
        self.assertGreater(abs(up[0] - count_x[0]), 1e-6)

    def test_callout_on_a_bar_pointing_away_does_not_cross_a_neighbour_label(self):
        """A callout on a long negative bar came in at an angle across the neighbouring "+0.0"
        label, and repeated the value already printed on the bar. Neither was reported."""
        import build_figs
        t = {"header": ["site", "wax", "resin"],
             "rows": [["Coast", "-12.3", "-3.9"], ["Hills", "+0.0", "-71.2"],
                      ["Plain", "-27.5", "-33.4"]]}
        warn = []
        build_figs.draw_bars(t, os.path.join(self._tmp(), "b.png"), None, "points", None,
                             (3.45, 2.55), warn, {"at": "Hills", "series": 1, "text": "-71.2"})
        self.assertTrue([w for w in warn if "repeats the value" in w], warn)
        self.assertEqual([w for w in warn if "arrow crosses" in w], [], warn)

    def test_tiles_blank_row_is_left_alone_when_the_slide_says_what_blanks_mean(self):
        """A factor-by-factor grid with combinations that were not run was told to drop the row,
        with no way to say the blanks are the design."""
        import build_figs
        tb = {"header": ["", "daily", "weekly", "monthly"],
              "rows": [["wax", "-12.3", "+0.0", "-1.85"], ["oil", "-3.9", "-", "-"],
                       ["resin", "-", "-27.5", "+0.0"]]}
        for said in (False, True):
            warn = []
            build_figs.draw_tiles([(None, tb)], os.path.join(self._tmp(), "t.png"),
                                  slot=(5.0, 2.4), warn=warn, blanks_said=said)
            blank = [w for w in warn if "cells blank" in w]
            self.assertEqual(bool(blank), not said, warn)
        self.assertTrue(build_figs.blanks_said({"fine": [u"–: not tested."]}))
        self.assertFalse(build_figs.blanks_said({"fine": ["Red: significant."]}))

    def test_tiles_width_warning_counts_columns_at_the_aimed_size(self):
        """It said "up to 1 column(s) per panel fit" while all three were drawn."""
        import build_figs
        tb = {"header": ["", "reapplied daily", "reapplied weekly", "reapplied monthly"],
              "rows": [["wax coating", "-12.3", "+0.0", "-1.85"],
                       ["resin coating", "-61.3", "-27.5", "-33.4"]]}
        warn = []
        build_figs.draw_tiles([("Coast", tb), ("Hills", tb)],
                              os.path.join(self._tmp(), "t.png"), slot=(4.0, 2.0), warn=warn)
        wide = [w for w in warn if "width falls short" in w]
        if wide:
            self.assertRegex(wide[0], r"only \d of 3 column\(s\) per panel fit, so all of them")


class PagesAndClaims(unittest.TestCase):

    def test_pages_map_to_slides_with_and_without_a_title_slide(self):
        """`\\maketitle` always makes page 1. A spec with no title slide was read one page off,
        so an overflow was fed back to nothing."""
        a, b = {"n": 1, "title": "x"}, {"n": 2, "title": "y", "chart": {"kind": "bars"}}
        self.assertIs(deckspec.slide_at_page([a, b], 2), a)
        t = {"n": 0, "kind": "title"}
        self.assertIs(deckspec.slide_at_page([t, a, b], 2), a)
        self.assertIsNone(deckspec.slide_at_page([t, a], 1))
        self.assertFalse(deckspec.has_figure(a))
        self.assertTrue(deckspec.has_figure(b))
        self.assertTrue(deckspec.has_figure({"kind": "columns", "right": {"figure": "f.png"}}))

    def test_overflow_on_a_slide_with_no_figure_is_not_fed_back(self):
        """A long table with no figure went round two feedback passes shrinking nothing."""
        for x in (deckspec.EXTRA_RESERVE, deckspec.LAST_OVER, deckspec.TEXT_BOUND,
                  deckspec.NO_FIGURE):
            x.clear()
            self.addCleanup(x.clear)
        slides = [{"n": 1, "title": "long table", "table": {"rows": [["a"]]}},
                  {"n": 2, "title": "chart", "chart": {"kind": "bars"}}]
        with mock.patch.object(deckspec, "log_overfull", return_value=[(2, 40.0), (3, 10.0)]):
            got = deckspec.fit_from_log("x.pdf", slides)
        self.assertEqual(sorted(got), [2])
        self.assertEqual(deckspec.NO_FIGURE, {1})

    def test_claim_context_is_plain_words(self):
        """Pinning a claim meant a regex on LaTeX (`a drop of \\$27\\.5\\$ points`)."""
        tex = u"a drop of $27.5$~points, \\textbf{p}\\,<\\,$10^{-3}$"
        self.assertIn(deckcheck.plain_context("A drop of 27.5 points"),
                      deckcheck.plain_context(tex))
        self.assertIn("p < 10^-3", deckcheck.plain_context(tex))
        self.assertNotIn(deckcheck.plain_context("a drop of 27.6 points"),
                         deckcheck.plain_context(tex))


if __name__ == "__main__":
    unittest.main(verbosity=2)
