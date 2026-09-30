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


class MeasuringSurvivesClose(unittest.TestCase):

    def test_text_is_still_measured_after_the_canvas_is_taken_away(self):
        """In CI, `plt.close("all")` in one test left the shared measuring figure with a bare
        `FigureCanvasBase`, and every later width measurement raised AttributeError."""
        import build_figs
        from matplotlib.backend_bases import FigureCanvasBase
        FigureCanvasBase(build_figs.measurer())
        self.assertGreater(build_figs.text_w("some words", 10), 0)
        fig = build_figs.plt.figure()
        self.addCleanup(build_figs.plt.close, fig)
        FigureCanvasBase(fig)
        self.assertIsNotNone(build_figs._renderer(fig))


class NameGrid(unittest.TestCase):

    def test_a_grid_of_combination_names_is_flagged_and_a_drawn_one_is_not(self):
        """Twice the design's two factors were shown only as a grid of pair names. The same
        grid shape holding what happens in each cell is a real drawing and is left alone."""
        import prose_audit
        names = {"n": 4, "title": "A route is two choices", "diagram": {
            "kind": "grid", "rows": ["express", "local"], "cols": ["morning", "evening"],
            "boxes": [{"label": "morning express"}, {"label": "evening express"},
                      {"label": "morning local"}, {"label": "", "mark": "blank"}]}}
        drawn = {"n": 5, "title": "Where the bus waits", "diagram": {
            "kind": "grid", "rows": ["express", "local"], "cols": ["morning", "evening"],
            "boxes": [{"label": "2 stops"}, {"label": "3 stops"},
                      {"label": "9 stops"}, {"label": "12 stops"}]}}
        got = prose_audit.name_grids([names, drawn])
        self.assertEqual([n for n, _ in got], [4])


class FortyNinthRound(unittest.TestCase):
    """The next blind trial: advice that contradicted another warning, a legend cut at the
    edge, and two prose_audit checks that fought the planning guide."""

    def test_strip_height_advice_keeps_the_notes_it_asked_for(self):
        """Identical bars need a note per row; the height advice then said "drop `note`", and
        dropping `fine` gained 0.09 inches."""
        import build_figs
        rows = [{"label": "express", "bars": 64, "groups": [64], "group_label": "one timetable",
                 "note": "the busiest stop sets the timetable for all"},
                {"label": "local", "bars": 64, "groups": [32, 32],
                 "group_label": "a timetable per 32 stops",
                 "note": "each block of 32 gets its own timetable"},
                {"label": "night", "bars": 64, "groups": [16, 16, 16, 16],
                 "group_label": "per 16", "outer": "a second line-wide timetable",
                 "note": "blocks of 16, plus one line timetable"}]
        d = {"kind": "strip", "rows": rows,
             "takeaway": "Stop pattern, and the timetable that stops share."}
        tmp = tempfile.mkdtemp(prefix="st-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        build_figs.BOUND.clear()
        build_figs.draw_strip(d, os.path.join(tmp, "s.png"), (5.51, 2.55), [])
        hint = build_figs.BOUND.get(("s.png", "hint")) or ""
        self.assertIn("Keep the row notes", hint)
        self.assertNotIn("drop the row notes", hint)
        self.assertIn("takeaway", hint)

    def test_dots_legend_is_not_cut_at_the_edge(self):
        import build_figs
        import figs_extra
        t = {"header": ["setting", "that pump on its own", "whole treatment plant"],
             "rows": [["North, cold start", "-12.3", "-14.1"], ["South, cold start", "-27.5", "-33.4"]]}
        tmp = tempfile.mkdtemp(prefix="dt-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        warn = []
        figs_extra.draw_dots(t, os.path.join(tmp, "d.png"), (3.25, 2.45), warn, build_figs, "points")
        self.assertEqual([w for w in warn if "clipped" in w], [], warn)

    def test_backup_terms_are_not_counted_as_never_said(self):
        """A backup slide has no timed script; its answer is spoken when a question calls for it."""
        import prose_audit
        slides = [{"n": 1, "title": "Main", "screen": "Main", "say": ["Hello."]},
                  {"n": 2, "title": "Backup", "screen": "QZT per row", "say": [], "backup": True}]
        self.assertEqual(prose_audit.unspoken_terms(slides), [])
        slides[1]["backup"] = False
        self.assertTrue(prose_audit.unspoken_terms(slides))

    def test_a_question_in_the_lines_is_not_judged_against_the_thesis(self):
        """planning §question keeps the conclusion's words off that slide, so the overlap check
        must skip it wherever the question is written."""
        import prose_audit
        q = {"n": 3, "kind": "standout", "title": "", "lead": "Same route, same morning.",
             "lines": ["Which one arrives first?"]}
        a = {"n": 9, "kind": "standout", "title": "", "lead": "The timetable decides the wait.",
             "lines": []}
        got = [n for n, _w, _t in prose_audit.standouts_off_thesis(
            [q, a], "The timetable, not the route, decides the wait.")]
        self.assertEqual(got, [9])


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
