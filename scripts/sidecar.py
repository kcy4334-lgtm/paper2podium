# -*- coding: utf-8 -*-
"""Sidecar that makes the values drawn inside a figure visible to the checkers.

Problem: the checkers read the source (`.tex`). A value stamped inside a
figure PNG is invisible to them, so nobody can catch a number drawn in the
figure that isn't in the paper.

Fix: the figure generator writes the values it drew into a TSV alongside it.
The checkers read that too.

    from sidecar import write
    write(PATH, {"fig1"}, ["fig1\t<item>\t<series>\t27.1"])

`write` swaps in only its own tagged lines rather than doing a plain
overwrite or append. A plain overwrite ("w") would wipe out another
generator's lines; append ("a") would pile up duplicates on every rerun.
Which lines survive should not depend on which generator ran last, and the
checker only warns when the file is completely empty, so a partial
overwrite would otherwise pass unnoticed.
"""
import io
import os

HEADER = "# Values drawn in the figure. The checker reads this file. Do not edit it by hand."


def write(path, tags, lines):
    """Replace only the lines matching `tags` with `lines`, keep the rest.

    Produces the same result regardless of call order. Returns the final line count.
    """
    keep = []
    if os.path.isfile(path):
        # `lines` is the parameter name, so the file's existing content is loaded
        # into a separate variable. Reusing `lines` here would overwrite the newly
        # passed values with the old ones.
        with io.open(path, encoding="utf-8") as f:
            existing = f.read().splitlines()
        for ln in existing:
            if not ln.strip() or ln.startswith("#"):
                continue
            if ln.split("\t", 1)[0] not in tags:
                keep.append(ln)
    out = sorted(keep + [l for l in lines if l.strip()])
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n" + "\n".join(out) + "\n")
    return len(out)


def read(path):
    """Tag -> list of lines."""
    d = {}
    if not os.path.isfile(path):
        return d
    with io.open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for ln in lines:
        if ln.strip() and not ln.startswith("#"):
            d.setdefault(ln.split("\t", 1)[0], []).append(ln)
    return d
