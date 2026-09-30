# -*- coding: utf-8 -*-
"""A set of figure types for build_figs: a graph with crossing arrows, a dot plot, and a line plot.

Why these live separately: they became necessary for a different kind of
paper than the base set covers.
  A systems paper's task graph, with data/control/state edges crossing
  rows, couldn't be drawn with flow/pipeline, so the paper's own figure
  had to be pasted in as-is instead.
  A result clustered in a narrow range (21-25%) showed no visible
  difference as a bar starting at 0. A dot plot sets its axis to the
  data's own range instead.
build_figs.py is already 3000 lines, so new figure types live here.
Helpers are borrowed from there.
"""
import os
import re

import design
import deckspec

EDGE_STYLE = {
    # kind: (line style, weight multiplier, color role)
    "data": ("-", 1.0, None),
    "control": ((0, (4, 3)), 1.0, None),
    "state": ("-", 2.2, None),
    "plain": ("-", 1.0, None),
}
EDGE_NAME = {"data": "data", "control": "control", "state": "state", "plain": ""}


def graph_size(d, slot):
    """The size (in inches) that follows from the node grid. The slot is a limit."""
    nodes = d.get("nodes") or []
    ncol = max([int(n.get("col", 0)) for n in nodes] or [0]) + 1
    nrow = max([int(n.get("row", 0)) for n in nodes] or [0]) + 1
    w = min(slot[0], max(3.0, ncol * 1.55))
    h = min(slot[1], max(1.2, nrow * 0.62 + 0.35
                         + (0.30 if d.get("takeaway") or d.get("note") else 0.0)
                         + (0.25 if _kinds(d) else 0.0)))
    return w, h


def _kinds(d):
    ks = []
    for e in d.get("edges") or []:
        k = e.get("kind", "plain")
        if k != "plain" and k not in ks:
            ks.append(k)
    return ks


def draw_graph(d, path, slot, warn, bf):
    """Nodes and edges. `bf` is the build_figs module (helpers are borrowed from it).

    nodes: [{id, label, col, row, mark, shape: box|oval}]
    edges: [{from, to, kind: data|control|state|plain, label}]
    """
    plt = bf.plt
    tag = os.path.basename(path)
    seen, words = [], []
    nodes = [n for n in (d.get("nodes") or []) if isinstance(n, dict)]
    ids = {}
    for n in nodes:
        ids[str(n.get("id", n.get("label")))] = n
    w, h = graph_size(d, slot)
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    xs, ys = w / 100.0, h / 100.0
    ncol = max([int(n.get("col", 0)) for n in nodes] or [0]) + 1
    nrow = max([int(n.get("row", 0)) for n in nodes] or [0]) + 1
    kinds = _kinds(d)
    bot = (30 / h if (d.get("takeaway") or d.get("note")) else 4.0) \
        + (25.0 / h if kinds else 0.0)
    top = 96
    cw = 100.0 / ncol
    rh = (top - bot) / nrow
    bw, bh = cw * 0.72, rh * 0.62
    fs = bf.BODY_PT
    colour = bf.role_map([n.get("mark") for n in nodes])
    # Node names are one size. Fitting each name to its own box makes short
    # names big and long names small, so size ends up reading as weight,
    # which breaks the rule that one grid uses one size throughout a
    # layout. Uses a single size that fits everything instead.
    _npt = bf.sibling_pt(fig, [(bf.strip_markup(str(n.get("label", k))), bw * 0.86 * xs, bh * 0.80 * ys)
                               for k, n in ids.items()], fs, weight="bold", max_lines=2)
    node_fs = _npt if round(_npt, 1) >= bf.WARN_PT else fs
    pos = {}
    for key, n in ids.items():
        cx = cw * (int(n.get("col", 0)) + 0.5)
        cy = top - rh * (int(n.get("row", 0)) + 0.5)
        pos[key] = (cx, cy)
        face = colour.get(n.get("mark"), bf.TILE_BG)
        edge = bf.ROLE_INK.get(n.get("mark")) if n.get("mark") else "none"
        if n.get("shape") == "oval":
            from matplotlib.patches import Ellipse
            ax.add_patch(Ellipse((cx, cy), bw, bh, facecolor=face,
                                 edgecolor=edge if edge != "none" else design.NEUTRAL_LINE,
                                 linewidth=design.BASE, zorder=2))
        else:
            bf._round(ax, cx - bw / 2, cy - bh / 2, bw, bh, face, xs, ys, zorder=2,
                      edge=edge, lw=design.BASE if n.get("mark") else 0.0)
        lab = bf.strip_markup(str(n.get("label", key)))
        bf.fit_text(fig, ax, cx, cy, bw * 0.86 * xs, bh * 0.80 * ys, lab, node_fs,
                    warn=warn, seen=seen, what=tag, max_lines=2, ha="center",
                    va="center", zorder=3, fontweight="bold", color=bf.INK)
        words.append(lab)

    def anchor(a, b):
        """The point on box a's edge heading toward b."""
        (ax_, ay_), (bx_, by_) = pos[a], pos[b]
        dx, dy = (bx_ - ax_) * xs, (by_ - ay_) * ys
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return ax_, ay_
        hw, hh = bw * xs / 2.0, bh * ys / 2.0
        t = min(hw / abs(dx) if dx else 1e9, hh / abs(dy) if dy else 1e9)
        return ax_ + dx * t / xs, ay_ + dy * t / ys

    for e in d.get("edges") or []:
        a, b = str(e.get("from")), str(e.get("to"))
        if a not in pos or b not in pos:
            if warn is not None:
                warn.append(u"%s: edge %s -> %s — no such node (nodes: %s)"
                            % (tag, a, b, ", ".join(sorted(pos))))
            continue
        k = e.get("kind", "plain")
        ls, wmul, _ = EDGE_STYLE.get(k, EDGE_STYLE["plain"])
        col = {"hit": bf.HIT, "safe": bf.SAFE}.get(e.get("mark"), design.INK3)
        p0, p1 = anchor(a, b), anchor(b, a)
        ax.annotate("", xy=p1, xytext=p0, zorder=1,
                    arrowprops=dict(arrowstyle="-|>,head_width=0.16,head_length=0.30",
                                    color=col, linewidth=design.BASE * wmul,
                                    linestyle=ls, shrinkA=1, shrinkB=1,
                                    connectionstyle="arc3,rad=%s" % e.get("bend", 0.0)))
        if e.get("label"):
            mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
            lab = bf.strip_markup(str(e["label"]))
            bf.fit_text(fig, ax, mx, my + rh * 0.14, cw * 0.9 * xs,
                        max(0.20, rh * 0.30 * ys), lab, fs - 1, warn=warn, seen=seen,
                        what=tag, max_lines=1,
                        ha="center", va="center", zorder=4, color=bf.MUTE,
                        bbox=dict(boxstyle="square,pad=0.1", fc=fig.get_facecolor(),
                                  ec="none"))
            words.append(lab)
    if kinds:
        # When an edge's style carries meaning, that meaning is spelled out
        # in the figure; without it, the audience has to guess.
        ly = bot - 12.0 / h
        n = len(kinds)
        for i, k in enumerate(kinds):
            ls, wmul, _ = EDGE_STYLE[k]
            x0 = 50 - n * 9 + i * 18
            ax.plot([x0, x0 + 6], [ly, ly], color=design.INK3, lw=design.BASE * wmul,
                    linestyle=ls, solid_capstyle="butt")
            name = str((d.get("edge_names") or {}).get(k, EDGE_NAME[k]))
            ax.text(x0 + 7, ly, name, fontsize=fs - 2, va="center", ha="left",
                    color=bf.MUTE)
            seen.append((round(float(fs - 2), 2), name))
            words.append(name)
    if d.get("note") or d.get("takeaway"):
        words += bf.bottom_band(fig, ax, xs, ys, 12.0 / h, 20 / h, d.get("note"),
                                d.get("takeaway"), fs - 1, fs, warn, seen, tag)
    bf.save_fig(fig, path, seen, warn, tag)
    return [x for x in words if x], seen


def draw_dots(t, path, slot, warn, bf, xlabel=None, log=False, takeaway=None):
    """Dot plot: one item per row, one dot per series. The axis is set to the data's own range.

    A bar has to start at 0 to be honest, so a difference between 21% and
    25% doesn't show up as a bar. A dot states its value by position, not
    length, so narrowing the axis doesn't mislead.
    """
    plt = bf.plt
    tag = os.path.basename(path)
    seen = []
    header = t.get("header") or []
    rows = t["rows"]
    series = [bf.strip_markup(str(h)) for h in header[1:]] or [""]
    labels = [bf.strip_markup(str(r[0])) for r in rows]
    fs = bf.BODY_PT
    multi = len([s for s in series if s]) > 1
    # Row names get up to 45% of the width; a longer name wraps to two
    # lines. Capping only the slot's width at 45% can still let the front
    # of a long name get cut off outside the figure, so the wrap below
    # measures the actual text.
    _max_lab = 0.45 * slot[0] - 0.25

    def _wrap(s):
        # A standalone connector symbol (the + in "StyleGAN2 + ADA")
        # attaches to the word after it, rather than wrapping alone as
        # "StyleGAN2 +" / "ADA." Joining it solid instead would produce a
        # spelling that doesn't appear in the paper, so it can still break
        # before the symbol: "StyleGAN2" / "+ ADA" even in a narrow cell.
        s = re.sub(r"\s+([+&/=\u00d7-])\s+", u" \\1\u00a0", s)
        if bf.text_w(s, fs, "bold") <= _max_lab or " " not in s:
            return s
        words_, lines_ = s.split(" "), [""]
        for wd in words_:
            cand = (lines_[-1] + " " + wd).strip()
            if lines_[-1] and bf.text_w(cand, fs, "bold") > _max_lab:
                lines_.append(wd)
            else:
                lines_[-1] = cand
        return "\n".join(lines_)
    shown = [_wrap(s) for s in labels]
    wrapped = any("\n" in s for s in shown)
    # Margins stack up in inches: ticks, axis label, takeaway. The legend
    # goes on top, since on the bottom it would compete with the axis
    # label. Sizing it as a fraction instead pushes the legend and axis
    # label outside the figure.
    row_in = (0.46 if multi else 0.34) + (0.16 if wrapped else 0.0)
    # The takeaway wraps to fit the width; left on one line, its ends get
    # cut off in a narrow cell.
    tk_lines = _wrap_to(bf, bf.strip_markup(str(takeaway)), fs, slot[0] - 0.2) if takeaway else []
    b_in = 0.30 + (0.24 if xlabel else 0.0) + (0.06 + 0.20 * len(tk_lines) if tk_lines else 0.0)
    w = slot[0]
    # The legend is measured before the figure is sized. Centred over the axes (which
    #   sit right of the row names) it ran off the right edge and "whole treatment plant"
    #   was cut to "whole treat". It is centred over the figure now, and stacked one name per
    #   line when one line cannot hold them.
    _names = [bf.strip_markup(str(s)) for s in series if s]
    _leg_w = (sum(bf.text_w(s, fs - 1) + 0.30 for s in _names)
              + 1.2 * (fs - 1) / 72.0 * max(0, len(_names) - 1))
    leg_stack = multi and _leg_w > w - 0.1
    t_in = ((0.12 + 0.20 * len(_names)) if leg_stack else 0.30) if multi else 0.10
    h = min(slot[1], max(1.3, row_in * len(rows) + b_in + t_in))
    fig = plt.figure(figsize=(w, h))
    lab_w = max([bf.text_w(ln, fs, "bold") for s in shown for ln in s.split("\n")]
                or [0.5]) + 0.25
    left = min(0.45, lab_w / w)
    if lab_w / w > 0.45 and warn is not None:
        # Picks out the widest line by measured width, not by character
        # count, which can flag the wrong name.
        _widest = max((ln for s_ in shown for ln in s_.split("\n")),
                      key=lambda ln: bf.text_w(ln, fs, "bold"))
        warn.append(u"%s: a row name doesn't fit even on two lines — it's cut off outside the "
                    u"figure. Shorten it: %r"
                    % (tag, _widest.replace(u"\u00a0", " ")[:40]))
    ax = fig.add_axes([left, b_in / h, 0.96 - left, 1.0 - (b_in + t_in) / h])
    palette = list(design.SERIES)
    vals = []
    # Each series is offset up and down. When values are close, a dot and
    # its value text on the same line would overlap each other. The offset
    # is 0.4 of the line spacing, smaller than the gap between lines, so
    # it still reads as belonging to its row.
    off = 0.40 / max(1, len(series) - 1) if multi else 0.0
    anns = []
    for si in range(len(series)):
        # The legend name is attached to that series' first dot, not its
        # first row: a series whose first row is empty would otherwise
        # vanish from the legend, leaving just its color behind.
        _named = False
        for bi, r in enumerate(rows):
            kind, plain = bf.cell_kind(r[si + 1]) if si + 1 < len(r) else (None, "")
            v = bf.num(plain)
            if v is None:
                continue
            if log and v <= 0:
                if warn is not None:
                    warn.append(u"%s: value %r <= 0 on a log axis — that point was dropped" % (tag, plain))
                continue
            vals.append(v)
            y = len(rows) - 1 - bi - off * (si - (len(series) - 1) / 2.0)
            ec = {"hit": bf.HIT, "safe": bf.SAFE}.get(kind, "none")
            ax.scatter([v], [y], s=46, color=palette[si % len(palette)], zorder=3,
                       edgecolors=ec, linewidths=1.8 if ec != "none" else 0,
                       label=None if _named else series[si])
            _named = True
            txt = plain.strip()
            anns.append(ax.annotate(
                txt, (v, y), xytext=(6, 0), textcoords="offset points",
                va="center", ha="left", fontsize=fs - 1, fontweight="bold",
                color={"hit": bf.HIT, "safe": design.text_of("safe")}.get(kind, bf.INK)))
            seen.append((round(float(fs - 1), 2), txt))
    if not vals:
        plt.close(fig)
        if warn is not None:
            warn.append(u"%s: nothing to plot in the dot plot" % tag)
        return seen
    lo, hi = min(vals), max(vals)
    if log:
        ax.set_xscale("log")
        ax.set_xlim(lo / 1.6, hi * 2.2)
    else:
        span = max(hi - lo, abs(hi) * 0.05, 1e-6)
        ax.set_xlim(lo - span * 0.15, hi + span * 0.35)
    # The value text sits to the right of the dot, and the axis is
    # extended by measuring the space the largest value's text actually
    # needs. A fixed multiplier (hi x 2.2 above) is only a starting point;
    # left alone, it can still cut a value like "37.71" down to "37.7."
    fig.canvas.draw()
    _r = fig.canvas.get_renderer()
    for _ in range(4):
        _ax_bb = ax.get_window_extent(_r)
        over = max([a.get_window_extent(_r).x1 for a in anns] + [0]) - _ax_bb.x1
        if over <= 1:
            break
        x0, x1 = ax.get_xlim()
        frac = (over + 4) / max(1.0, _ax_bb.width - over - 4)
        if log:
            import math as _m
            span_l = _m.log10(x1) - _m.log10(x0)
            ax.set_xlim(x0, 10 ** (_m.log10(x1) + span_l * frac))
        else:
            ax.set_xlim(x0, x1 + (x1 - x0) * frac)
        fig.canvas.draw()
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(list(reversed(shown)), fontsize=fs, fontweight="bold")
    ax.set_ylim(-0.6, len(rows) - 0.4)
    # When value texts overlap, the smaller value's text (or the later
    # series, if tied) flips to the dot's left side. Two series with the
    # same value (81.8 / 81.8) would otherwise always overlap with no way
    # to untangle them.
    fig.canvas.draw()
    for i1 in range(len(anns)):
        for i2 in range(i1 + 1, len(anns)):
            b1, b2 = anns[i1].get_window_extent(_r), anns[i2].get_window_extent(_r)
            if b1.x0 < b2.x1 and b2.x0 < b1.x1 and b1.y0 < b2.y1 and b2.y0 < b1.y1:
                a = anns[i2] if anns[i2].xy[0] <= anns[i1].xy[0] else anns[i1]
                a.set_ha("right")
                a.xyann = (-6, 0)
                fig.canvas.draw()
    # If text flipped to the left goes outside the axis, into the
    # row-name area, extend the axis to the left too, the same idea as on
    # the right.
    for _ in range(4):
        _ax_bb = ax.get_window_extent(_r)
        over = _ax_bb.x0 - min([a.get_window_extent(_r).x0 for a in anns] + [_ax_bb.x0])
        if over <= 1:
            break
        x0, x1 = ax.get_xlim()
        frac = (over + 4) / max(1.0, _ax_bb.width - over - 4)
        if log:
            import math as _m
            span_l = _m.log10(x1) - _m.log10(x0)
            ax.set_xlim(10 ** (_m.log10(x0) - span_l * frac), x1)
        else:
            ax.set_xlim(x0 - (x1 - x0) * frac, x1)
        fig.canvas.draw()
    ax.grid(axis="x", color=bf.GRID, linewidth=0.6, zorder=0)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", labelsize=fs - 1)
    for s in labels:
        seen.append((float(fs), s))
    if xlabel:
        ax.set_xlabel(bf.strip_markup(str(xlabel)), fontsize=fs - 1)
        seen.append((float(fs - 1), bf.strip_markup(str(xlabel))))
    if multi:
        fig.legend(*ax.get_legend_handles_labels(), fontsize=fs - 1, frameon=False,
                   ncol=1 if leg_stack else min(4, len(series)),
                   loc="upper center", bbox_to_anchor=(0.5, 1.0), borderaxespad=0.1,
                   handletextpad=0.3, columnspacing=1.2)
        for s in series:
            seen.append((float(fs - 1), s))
    if tk_lines:
        fig.text(0.5, 0.04 / h, "\n".join(tk_lines), ha="center", va="bottom",
                 fontsize=fs, fontweight="bold", color=bf.INK, linespacing=1.15)
        seen.append((float(fs), bf.strip_markup(str(takeaway))))
    bf.save_fig(fig, path, seen, warn, tag)
    return seen


def draw_lines(t, path, slot, warn, bf, xlabel=None, ylabel=None, log=False,
               takeaway=None, callout=None):
    """Line plot: how y moves as x changes (performance vs. scale, accuracy vs. budget).

    One table row is one point: `[series, x, y]`. x can differ across
    series, since each method may have a different number of training
    parameters. If there's a header row, the second and third cells are
    the axis labels.

    Without this figure type, a shape like "as the parameter count grows,
    some methods get worse while others hold up" would have to be squeezed
    into a single-axis dot plot with x hidden inside the row name, which
    hides the shape.

    Instead of a legend, names are attached to the end of each line, so
    the eye never has to travel between a legend and the lines.
    """
    plt = bf.plt
    tag = os.path.basename(path)
    seen = []
    header = [bf.strip_markup(str(h)) for h in (t.get("header") or [])]
    xlabel = xlabel or (header[1] if len(header) > 1 else None)
    ylabel = ylabel or (header[2] if len(header) > 2 else None)
    fs = bf.BODY_PT
    series, order = {}, []
    # `<safe>`/`<hit>` in a series-name cell sets that line's color. With
    # only the default color order, the third and fourth series come out
    # gray, which can leave the method the paper favors as the faintest
    # line on the plot.
    mark_of, suf = {}, set()
    # `log: true` means the x-axis, `log: y` the y-axis, `log: both` means
    # both, since some curves (model size vs. optimal token count) span
    # orders of magnitude on both axes.
    logx = log is True or str(log).lower() in ("x", "both", "true")
    logy = str(log).lower() in ("y", "both")
    for r in t["rows"]:
        if len(r) < 3:
            if warn is not None:
                warn.append(u"%s: a line-plot row is [series, x, y] — %r was dropped" % (tag, r))
            continue
        name = bf.strip_markup(str(r[0])).strip()
        _sk, _ = bf.cell_kind(r[0])
        x = bf.num(bf.strip_markup(str(r[1])))
        kind, plain = bf.cell_kind(r[2])
        y = bf.num(plain)
        for ax_i, cell in (("x", r[1]), ("y", r[2])):
            for u in re.findall(r"\d\s*([kKMGBT](?![A-Za-z])|thousand|million|billion|trillion)",
                                str(cell), re.I):
                suf.add((ax_i, {"thousand": "K", "million": "M", "billion": "B",
                                "trillion": "T"}.get(u.lower(), u.upper() if u in "kK" else u)))
        if x is None or y is None or (logx and x <= 0) or (logy and y <= 0):
            if warn is not None:
                warn.append(u"%s: row %r can't be read as a point — dropped" % (tag, r))
            continue
        if name not in series:
            series[name] = []
            order.append(name)
        if _sk in ("safe", "hit"):
            mark_of[name] = _sk
        series[name].append((x, y, kind))
    pts = [p_ for s_ in series.values() for p_ in s_]
    if not pts:
        if warn is not None:
            warn.append(u"%s: no points to plot in the line plot" % tag)
        return seen
    w = slot[0]
    # Uses the full slot's width. Capping it at a fraction of the width
    # instead can leave the figure at only half the slot's height in a
    # narrow cell.
    h = min(slot[1], max(2.0, w * 0.80))
    lab_w = max(bf.text_w(n_, fs - 1, "bold") for n_ in order) + 0.18
    # The takeaway wraps to fit the width; left on one line, its ends get
    # cut off in a narrow cell.
    tk_lines = _wrap_to(bf, bf.strip_markup(str(takeaway)), fs, w - 0.2) if takeaway else []
    b_in = 0.27 + (0.20 if xlabel else 0.0) + (0.04 + 0.20 * len(tk_lines) if tk_lines else 0.0)
    l_in = 0.55 + (0.22 if ylabel else 0.0)
    r_in = min(w * 0.40, lab_w + 0.10)
    t_in = 0.25                    # room for a line name raised above the plot; a smaller value clips at the top edge
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([l_in / w, b_in / h, 1.0 - (l_in + r_in) / w, 1.0 - (b_in + t_in) / h])
    palette = list(design.SERIES)
    styles = ["-", (0, (5, 2)), (0, (1, 1.5)), (0, (6, 2, 1, 2))]
    ends = []
    for i, name in enumerate(order):
        pts_ = sorted(series[name])
        xs, ys = [p_[0] for p_ in pts_], [p_[1] for p_ in pts_]
        c = palette[i % len(palette)]
        ls = styles[(i // len(palette)) % len(styles)]
        lw = 2.0
        if name in mark_of:
            c, lw = {"safe": bf.SAFE, "hit": bf.HIT}[mark_of[name]], 3.0
        ax.plot(xs, ys, linestyle=ls, color=c, linewidth=lw, marker="o", markersize=5,
                zorder=4 if name in mark_of else 3)
        for x, y, kind in pts_:
            if kind in ("hit", "safe"):
                ax.scatter([x], [y], s=110, facecolors="none", zorder=5, linewidths=2.0,
                           edgecolors={"hit": bf.HIT, "safe": bf.SAFE}[kind])
        ends.append([ys[-1], xs[-1], name, c])
    # Tick labels are shown in the same style as the cells: if a cell reads
    # `8.65M` or `1.5 Trillion`, ticks read 1M and 1T too, instead of
    # matplotlib's default 10^6 / 2x10^2 style, which makes the audience
    # translate it once more. A log axis spanning less than one order of
    # magnitude also gets labels on its minor ticks.
    from matplotlib.ticker import FuncFormatter, NullFormatter, LogLocator

    def _formatter(ax_i, compact):
        units = {s for a_, s in suf if a_ == ax_i}

        def _fmt(v, _p):
            for d, s in ((1e12, "T"), (1e9, "B" if "B" in units else "G"), (1e6, "M"), (1e3, "K")):
                if (units or compact) and abs(v) >= d:
                    return "%g%s" % (v / d, s)
            return "%g" % v
        return FuncFormatter(_fmt), bool(units)
    for ax_i, on, axis in (("x", logx, ax.xaxis), ("y", logy, ax.yaxis)):
        vals = [p_[0] if ax_i == "x" else p_[1] for p_ in pts]
        # A large number with no unit is shortened (10000 -> 10K); left
        # alone, in a narrow cell it can run together as "100 100010000."
        compact = 1e3 <= max(vals) < 1e9
        fmt, has_units = _formatter(ax_i, compact)
        if on:
            (ax.set_xscale if ax_i == "x" else ax.set_yscale)("log")
            # Tick count follows the axis length, one per 0.55in. When
            # there are too many, whole orders of magnitude are skipped.
            _len = (w - l_in - r_in) if ax_i == "x" else (h - b_in - t_in)
            axis.set_major_locator(LogLocator(base=10, numticks=max(3, int(_len / 0.55))))
            # A very large number with no unit (1e+19) reads better in
            # matplotlib's 10^n form, so it's left as-is in that case.
            _dx = sorted(set(vals))
            if ax_i == "x" and 2 <= len(_dx) <= 8:
                # If x is a handful of settings (1, 4, 8, 16, 32 heads),
                # tick every one of them. Log ticks at 1, 2, 5, 10, 20
                # instead can leave an audience unable to tell which point
                # is which. Same rule as for a linear axis.
                from matplotlib.ticker import FixedLocator, NullLocator
                axis.set_major_locator(FixedLocator(_dx))
                axis.set_major_formatter(fmt)
                axis.set_minor_locator(NullLocator())
                continue
            if has_units or max(vals) < 1e9:
                axis.set_major_formatter(fmt)
                _span = max(vals) / max(min(vals), 1e-300)
                if 10 <= _span < 100:
                    # An axis spanning less than two orders of magnitude
                    # has only one 10^n tick otherwise (just "1K" across
                    # 128-4096), so this labels the 2x and 5x points too.
                    axis.set_minor_locator(LogLocator(base=10, subs=(2.0, 5.0)))
                    axis.set_minor_formatter(fmt)
                else:
                    axis.set_minor_formatter(fmt if _span < 10 else NullFormatter())
        elif has_units or compact:
            axis.set_major_formatter(fmt)
        # If x is a handful of integers (grades 1-5), tick every value.
        # The default locator can plot only 2 and 4 and skip the third grade.
        if ax_i == "x" and not on:
            _xs = sorted(set(vals))
            if 2 <= len(_xs) <= 12 and all(float(v).is_integer() for v in _xs):
                from matplotlib.ticker import FixedLocator
                axis.set_major_locator(FixedLocator(_xs))
    ax.grid(color=bf.GRID, linewidth=0.6, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(which="both", labelsize=fs - 1)   # minor-tick labels the same size too
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=fs - 1)
        seen.append((float(fs - 1), xlabel))
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=fs - 1)
        seen.append((float(fs - 1), ylabel))
    # A name sits next to its line's last point. The spot is chosen in
    # screen coordinates: the first, among right/above/below/left-center,
    # that doesn't overlap another name or another point. Nudging it
    # vertically in data units instead can leave names floating far from
    # their point on a log axis, or let a single-point series' name cover
    # the point next to it.
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    tr = ax.transData
    dots_px = [tuple(tr.transform((p_[0], p_[1]))) for p_ in pts]
    pt_px = fs / 72.0 * fig.dpi
    placed = []
    for yl, xl, name, c in sorted(ends, key=lambda e: -e[0]):
        px, py = tr.transform((xl, yl))
        tw_ = bf.text_w(name, fs - 1, "bold") * fig.dpi
        th_ = pt_px * 1.2
        own = (px, py)
        best = None
        for dx, dy, ha, va in ((6, 0, "left", "center"), (0, 8, "center", "bottom"),
                               (0, -8, "center", "top"), (-6, 0, "right", "center"),
                               (6, 12, "left", "bottom"), (6, -12, "left", "top")):
            ox = px + dx * fig.dpi / 72.0
            oy = py + dy * fig.dpi / 72.0
            x0 = {"left": ox, "center": ox - tw_ / 2, "right": ox - tw_}[ha]
            y0 = {"center": oy - th_ / 2, "bottom": oy, "top": oy - th_}[va]
            box = (x0, y0, x0 + tw_, y0 + th_)
            hit = any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3])
                      for b in placed)
            hit = hit or any(box[0] - 4 <= q[0] <= box[2] + 4 and box[1] - 4 <= q[1] <= box[3] + 4
                             for q in dots_px if abs(q[0] - own[0]) + abs(q[1] - own[1]) > 1)
            if not hit:
                best = (dx, dy, ha, va, box)
                break
        if best is None:
            best = (6, 0, "left", "center", (px, py - th_ / 2, px + tw_, py + th_ / 2))
            if warn is not None:
                warn.append(u"%s: no free spot for the line name %r — it may overlap" % (tag, name))
        placed.append(best[4])
        ax.annotate(name, (xl, yl), xycoords="data", xytext=best[:2], textcoords="offset points",
                    va=best[3], ha=best[2], fontsize=fs - 1, fontweight="bold", color=c,
                    annotation_clip=False)
        seen.append((float(fs - 1), name))
    # Points to one spot: `callout: {series, at, text}`. Marks a crossing
    # or a bend instead of only describing it in words, such as "they
    # cross between 512 and 1024" with nothing to point at.
    if callout:
        _cs = bf.strip_markup(str(callout.get("series", order[0] if order else "")))
        _at = bf.num(str(callout.get("at", "")))
        _pts = sorted(series.get(_cs) or [], key=lambda p_: abs(p_[0] - (_at or 0)))
        _txt = bf.strip_markup(str(callout.get("text") or ""))
        if not _pts or _at is None:
            if warn is not None:
                warn.append(u"%s: no point matches callout series=%r, at=%r. Write the series "
                            u"name and x value exactly as they appear in the table." % (tag, _cs, callout.get("at")))
        elif _txt:
            px_, py_ = tr.transform((_pts[0][0], _pts[0][1]))
            _bb = ax.get_window_extent(rend)
            # Text goes to the empty side within the axis: down if the
            # point is high, left if it's on the right.
            _dx = -60 if px_ > (_bb.x0 + _bb.x1) / 2 else 60
            _dy = -36 if py_ > (_bb.y0 + _bb.y1) / 2 else 36
            _col = {"safe": bf.SAFE}.get(callout.get("mark"), bf.HIT)
            ax.annotate(_txt, (_pts[0][0], _pts[0][1]), xytext=(_dx, _dy),
                        textcoords="offset points", ha="center", va="center",
                        fontsize=fs - 1, fontweight="bold", color=_col, zorder=6,
                        bbox=dict(boxstyle="square,pad=0.15", fc=fig.get_facecolor(), ec="none"),
                        arrowprops=dict(arrowstyle="->", color=_col, lw=1.4, shrinkA=2,
                                        shrinkB=4))
            seen.append((float(fs - 1), _txt))
    if tk_lines:
        fig.text(0.5, 0.04 / h, "\n".join(tk_lines), ha="center", va="bottom",
                 fontsize=fs, fontweight="bold", color=bf.INK, linespacing=1.15)
        seen.append((float(fs), bf.strip_markup(str(takeaway))))
    bf.save_fig(fig, path, seen, warn, tag)
    return seen


def _wrap_to(bf, s, fs, width_in):
    """Wraps `s` word by word to fit `width_in` at bold `fs`pt. Returns a list of lines."""
    lines_ = [""]
    for wd in s.split():
        cand = (lines_[-1] + " " + wd).strip()
        if lines_[-1] and bf.text_w(cand, fs, "bold") > width_in:
            lines_.append(wd)
        else:
            lines_[-1] = cand
    return [x for x in lines_ if x]
