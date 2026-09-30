# -*- coding: utf-8 -*-
"""Builds everything in one pass: figures -> deck -> PDF -> (if overfull, feed back once more) -> PPTX -> script.

    python scripts/build.py slides.yaml -o out

Why this is a separate step: it used to run stage by stage, with compiling handled
outside the skill. LaTeX would log that a slide overflowed, but nobody read the log,
so a slide could overflow silently even when every checker reported a pass.

The overflow happens because counting figure space does not count the gap between
blocks of text. That gap could be hard-coded as a constant, but in this repository
the measuring side and the drawing side kept drifting apart when it was. So instead
the build measures and corrects: it takes what the log reports, subtracts it from
that slide's figure space (`deckspec.EXTRA_RESERVE`), and draws once more. The
figure is the only thing on a slide that grows or shrinks, so one pass is usually
enough. If it still overflows, that slide has too much text, and the build says so.

Paths: `-o` is resolved relative to the current directory, not the spec file.
pdflatex also runs from the current directory, because `\\graphicspath` is written
relative to it.
"""
import argparse
import glob
import io
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckspec  # noqa: E402

# Max number of overflow feedback passes. One is usually enough: if it is
# still overflowing on the second pass, shrinking the figure further will not
# help, because there is too much text on that slide.
FIT_PASSES = 2


def _latex(tex, outdir, engine="pdflatex"):
    """Runs twice (page numbers, table of contents). On failure, shows the tail of the log.

    Follows `meta.engine`. The code always called pdflatex, so `engine: xelatex` was a dead
    feature: the deck uses a full page of fontspec commands that pdflatex cannot process.
    Papers with lots of Greek letters or Hangul had to drop the one-command build and run
    it by hand.
    """
    engine = str(engine or "pdflatex").lower()
    exe = shutil.which(engine)
    if not exe:
        print("   %s not found. Install a TeX distribution. Stopping without a PDF." % engine)
        return False
    # Runs from the output folder: `\\graphicspath{{figs/}}` is relative to where
    # typesetting happens.
    for _ in range(2):
        p = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error",
                            os.path.basename(tex)],
                           capture_output=True, cwd=outdir)
        if p.returncode != 0:
            log = os.path.join(outdir, os.path.splitext(
                os.path.basename(tex))[0] + ".log")
            tail = ""
            if os.path.exists(log):
                with io.open(log, encoding="latin-1") as f:
                    tail = "".join(f.readlines()[-25:])
            print("   %s failed:\n" % engine + tail)
            return False
    return True


def _why_small(fig, texts):
    """The fix that matches the cause of shrunken text. `build_figs.BOUND` records the
    width or height that decided each string.

    If the fix doesn't match the cause, it fixes the wrong thing. In a box where width
    decides the size, dropping the slide's `fine` text makes the figure taller instead
    of wider, so the text shrinks even more.
    """
    try:
        import build_figs
    except Exception:
        return ""
    # When a string has no record of its own, fall back to the record for the whole figure
    # (figures that fix font size before drawing: strip, pipeline, tiles)
    # A figure that worked out its own advice from its bands (strip) says it here.
    if build_figs.BOUND.get((fig, "hint")):
        return build_figs.BOUND[(fig, "hint")]
    got = [build_figs.BOUND.get((fig, t[:48])) or build_figs.BOUND.get((fig, "*")) for t in texts]
    w, h = got.count("w"), got.count("h")
    if not (w or h):
        return ""
    if w >= h:
        return (u" — width decides it (%d/%d): shorten the long name (abbreviate or wrap to "
                u"two lines), or drop a side column, left-hand name, or subtitle to widen the "
                u"figure. Dropping lines or `fine` won't make it bigger" % (w, w + h))
    return u" — height decides it (%d/%d): drop lines, subtitle, `note`, or the slide's `fine`" % (h, w + h)


def _say(stage, warns, printed=None):
    """Prints the warnings that come back. Not printing them is the same as not checking.

    Given `printed`, it does not reprint warnings already printed in an earlier pass; it
    only states the count. Otherwise, running the feedback loop more than once prints the
    same block of warnings each time, burying the new ones among the repeats.
    """
    # Print each warning only once. A figure gets redrawn while its space is being measured,
    # and the same warning fires each time; printed twice, it looks like two problems.
    # Shrinking one whole figure can produce one "below the floor" warning per string. Group
    # them into one line per figure so the noise does not bury the real warning.
    _small, _rest, _tight = {}, [], {}
    for w in warns or []:
        # These match build_figs.fit_text's own warning text. Change both together.
        # The text is written with %r, so it is quoted with " when it contains an apostrophe
        m = re.match(r"(.+?\.png): text is ([\d.]+)pt on screen \(floor ([\d.]+)pt\): (['\"])(.*)\4$", str(w))
        t = re.match(r"(.+?\.png): text fills to the margin \(([\d.]+)pt, (\d+)% of the space's width\): "
                     r"(['\"])(.*)\4$", str(w))
        if m:
            _small.setdefault((m.group(1), m.group(3)), []).append((float(m.group(2)), m.group(5)))
        elif t:
            _tight.setdefault(t.group(1), []).append((-int(t.group(3)), t.group(5)))
        else:
            _rest.append(w)
    # Tight-fitting text also gets one line per figure. It still looks like it fits, so this
    # is for reference only.
    for fig, items in _tight.items():
        items.sort()
        _rest.append(u"%s: (info) %d string(s) reach the box's margin (up to %d%% of slot width) — %s"
                     % (fig, len(items), -items[0][0], ", ".join("'%s'" % x[1] for x in items[:3])))
    for (fig, floor), items in _small.items():
        items.sort()
        if len(items) == 1:
            line = u"%s: %.1fpt on screen (floor %spt): '%s'" % (fig, items[0][0], floor, items[0][1])
        else:
            line = (u"%s: %d string(s) are below the %spt floor (smallest %.1fpt) — %s ..."
                    % (fig, len(items), floor, items[0][0],
                       ", ".join("'%s'" % x[1] for x in items[:3])))
        _rest.append(line + _why_small(fig, [x[1] for x in items]))
    warns = _rest
    seen, out, again = set(), [], 0
    for w in warns or []:
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if printed is not None and w in printed:
            again += 1
            continue
        print("   %s" % w)
        if printed is not None:
            printed.add(w)
    if again:
        print("   (%d warning(s) same as the previous pass omitted)" % again)
    return out


IMG_EXT = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".gif", ".bmp", ".tif", ".tiff")


def user_figdir(spec, meta):
    """User figure folder: `meta.figdir` (default `figs`), relative to the spec file."""
    fd = str(meta.get("figdir") or "figs")
    if not os.path.isabs(fd):
        fd = os.path.join(os.path.dirname(os.path.abspath(spec)), fd)
    return os.path.normpath(fd)


def bring_user_figures(spec, meta, figdir):
    """Copies figures next to the spec into `<out>/figs`. Returns the list of names copied.

    The builder finds figures by file name; it does not look at the folder. So this also
    flattens figures out of subfolders, and reports when two share a name.
    """
    src = user_figdir(spec, meta)
    dst = os.path.normpath(os.path.abspath(figdir))
    if not os.path.isdir(src) or src == dst:
        return []
    got, seen = [], {}
    for root, _dirs, files in os.walk(src):
        if os.path.normpath(os.path.abspath(root)).startswith(dst):
            continue                         # skip if the output folder is inside it
        for f in files:
            if not f.lower().endswith(IMG_EXT):
                continue
            if f in seen:
                print("   two figures share the same name: %s and %s. The builder only "
                      "looks them up by name. Rename one of them" % (seen[f], os.path.join(root, f)))
                continue
            seen[f] = os.path.join(root, f)
            shutil.copy2(seen[f], os.path.join(dst, f))
            got.append(f)
            if f.lower().endswith(".eps"):
                eps_to_pdf(os.path.join(dst, f))
    return got


def eps_to_pdf(path):
    """EPS -> a PDF of the same name. The deck uses that PDF, and PPTX converts it to PNG again.

    pdflatex cannot read EPS directly, and automatic conversion may or may not happen depending
    on the TeX distribution and shell setup. Converting it once here means both see the same
    figure.
    """
    pdf = os.path.splitext(path)[0] + ".pdf"
    if os.path.isfile(pdf) and os.path.getmtime(pdf) >= os.path.getmtime(path):
        return pdf
    exe = shutil.which("epstopdf")
    if not exe:
        print("   EPS figure %s: epstopdf not found (it ships with a TeX distribution). "
              "Convert it to PDF and put it in figdir" % os.path.basename(path))
        return None
    r = subprocess.run([exe, path, "--outfile=" + pdf], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(pdf):
        print("   EPS -> PDF failed: %s\n%s" % (path, (r.stderr or r.stdout)[-400:]))
        return None
    return pdf


def build(spec, outdir, pptx=True, script=True, limit=None, qa=0):
    import build_figs
    import build_deck

    # Paths are joined with forward slashes: they go straight into the deck's `\\graphicspath`.
    outdir = str(outdir).replace(chr(92), "/").rstrip("/")
    figdir = outdir + "/figs"
    tex = outdir + "/talk.tex"
    pdf = outdir + "/talk.pdf"
    meta, slides, _ = deckspec.load(spec)
    os.makedirs(figdir, exist_ok=True)
    got = bring_user_figures(spec, meta, figdir)
    if got:
        print("   brought %d user figure(s) from `%s` to `%s`"
              % (len(got), user_figdir(spec, meta), figdir))

    deckspec.EXTRA_RESERVE.clear()
    deckspec.LAST_OVER.clear()
    deckspec.TEXT_BOUND.clear()
    deckspec.NO_FIGURE.clear()
    over = None
    _printed = set()
    for attempt in range(FIT_PASSES + 1):
        tag = "" if attempt == 0 else "  (feedback pass %d)" % attempt
        print("== Figures%s" % tag)
        # Deletes figures the previous build drew. If a slide moves, a figure left over under
        # the old number can be picked up by a different slide. User figures have different
        # names, so they are untouched.
        if attempt == 0:
            for old in (glob.glob(figdir + "/chart_*.png")
                        + glob.glob(figdir + "/diagram_*.png")):
                try:
                    os.remove(old)
                except OSError:
                    pass
        _, _, fw = build_figs.build(spec, figdir, figdir + "/values.txt")
        last = {"figures": _say("figures", fw, _printed)}
        print("== Deck%s" % tag)
        last["deck"] = _say("deck", build_deck.build(spec, tex, "figs")[2], _printed)
        print("== PDF%s" % tag)
        if not _latex(tex, outdir, meta.get("engine")):
            return 1
        over = deckspec.log_overfull(pdf) or []
        if not over:
            if attempt:
                print("   Fed the overfull slide(s) back and redrew them. Nothing overflows now.")
            break
        if attempt == FIT_PASSES:
            break
        got = deckspec.fit_from_log(pdf, slides)
        # Nothing left that a smaller figure could fix: another pass would only redraw.
        _n = [deckspec.slide_at_page(slides, p_).get("n", p_) for p_, _ in over
              if deckspec.slide_at_page(slides, p_) is not None]
        if _n and all(n_ in deckspec.NO_FIGURE or n_ in deckspec.TEXT_BOUND for n_ in _n):
            break
        print("   Body text overflowed on %d page(s): %s. Shrinking each of those slides' "
              "figure space by its overflow and drawing once more."
              % (len(over), ", ".join("p.%d %.1fpt" % x for x in over)))
        print("     feedback: %s" % ", ".join("slide %s -%.2fin" % kv
                                         for kv in sorted(got.items())))

    wraps = deckspec.title_wraps(pdf)
    # Impact slides and the title slide have no title band. The `lead` above them would
    # otherwise be flagged as "title wraps to two lines".
    wraps = [(n_, t_) for n_, t_ in wraps
             if (deckspec.slide_at_page(slides, n_) or {"kind": "title"}).get("kind")
             not in ("standout", "title")]
    if wraps:
        print("   %d page(s) where the title wraps to two lines. It eats into body height:" % len(wraps))
        for n_, t_ in wraps:
            print("       p.%3d  %s" % (n_, t_[:64]))
        print("     The title is one line spoken by the presenter. Send result sentences to "
              "`lead` or `say`")
        print("     (references/planning.md §voice).")
        last["deck"] = list(last.get("deck") or []) + ["title wraps to two lines: %d" % len(wraps)]

    if deckspec.TEXT_BOUND:
        print("   Slide(s) where shrinking the figure did not reduce the overflow: %s. The "
              "figure(s) were restored to their original size."
              % ", ".join("slide %s" % n_ for n_ in sorted(deckspec.TEXT_BOUND)))
        print("     What overflows is that slide's text (bullets or blocks in a panel, or `fine`).")
    if deckspec.NO_FIGURE:
        print("   Slide(s) with no figure that overflow: %s. There is no figure to shrink, "
              "so they were not fed back."
              % ", ".join("slide %s" % n_ for n_ in sorted(deckspec.NO_FIGURE)))
    if over:
        print("   Still overflowing: %s" % ", ".join("p.%d %.1fpt" % x for x in over))
        print("     A smaller figure will not fix it: this slide has too much text.")
        print("     Cut `fine`/`foot` first, move it to `say`, or split the slide.")

    if pptx:
        import build_pptx
        print("== PPTX")
        last["PPTX"] = _say("PPTX", build_pptx.build(
            spec, outdir + "/talk.pptx", "figs")[2])
    if script:
        import build_script
        print("== Script")
        # The time gate is also enforced here. If it had to be run separately, it would not be.
        argv = [spec, "-o", outdir + "/script.md", "--thumbs", pdf]
        if limit:
            argv += ["--limit", str(limit), "--qa", str(qa or 0)]
        late = build_script.main(argv)
    n = sum(len(v) for v in last.values())
    print()
    print("   %d warning(s) (%s)%s" % (
        n, " · ".join("%s %d" % (k, len(v)) for k, v in last.items()),
        " — all printed above" if n else ""))
    return 1 if (over or (script and late)) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="figures -> deck -> PDF (feeds back overflow) -> PPTX -> script")
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("--no-pptx", action="store_true")
    ap.add_argument("--no-script", action="store_true")
    ap.add_argument("--limit", type=float, default=None, metavar="MIN",
                    help="talk length in minutes. If the calculation goes over, it fails")
    ap.add_argument("--qa", type=float, default=0, metavar="MIN",
                    help="Q&A minutes included within --limit")
    a = ap.parse_args(argv)
    try:
        return build(a.spec, a.out, not a.no_pptx, not a.no_script, a.limit, a.qa)
    except ValueError as e:
        # A spec error shows only the message. A traceback would bury the guidance,
        # and the spec is what needs fixing.
        print("spec error: %s" % e)
        return 2


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
