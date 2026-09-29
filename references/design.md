# Design: why the figures look the way they do

## Contents

- [Read this when](#read-this-when)
- [The ten rules, in the order they matter](#the-ten-rules-in-the-order-they-matter)
- [What makes a generated figure look generated](#what-makes-a-generated-figure-look-generated)
- [Where the numbers came from, and how far to trust them](#where-the-numbers-came-from-and-how-far-to-trust-them)
- [The one place these values live](#the-one-place-these-values-live)
- [What was learned by looking (side by side with a hand-made deck)](#what-was-learned-by-looking-side-by-side-with-a-hand-made-deck)

---

## Read this when

You are about to write a colour, a line width, a corner radius, a padding or a font
weight into a generator. Do not. Put it in `scripts/design.py`, or use what is already
there. This file gives the reasoning behind those values.

Also read it when a figure is correct and still looks amateur. The cause is almost always
one of the ten rules below, and almost never the thing the author suspects.

---

## The ten rules, in the order they matter

### 1. Three stroke weights

Use three stroke weights, each twice the last, and always draw a container lighter than
its contents: `HAIR 0.5 / BASE 1.0 / EMPH 2.0` pt. Technical drawing gets by on two
weights in a 1:2 ratio (ISO 128-2). Two weights closer than 1.5× do not read as a
hierarchy; they read as a mistake. Assign from heaviest to lightest: the one path the
speaker narrates, then structural outlines, then grouping frames, dividers and grid.
Layout engines do the opposite and draw a cluster box at node weight, and that alone
accounts for much of the graphviz look.

### 2. Three colour steps per role

One semantic role spans three colour steps, and the step you use depends on how much area
it covers. Saturation falls as the coloured region grows (Munzner ch. 10).

| step | where | why |
|---|---|---|
| `fill_of`: very pale | a large box | a large saturated area uses the figure's whole contrast budget, so the label inside it and the arrow beside it have to compete with it; this is why a solid green box looks cheap |
| `mark_of`: mid | a small cell, a legend swatch | a small mark at low saturation disappears |
| `line_of`: strong | strokes, small coloured text | a pale line does not read as a line |

Both directions go wrong in practice: a solid green box that swallows its own contents, and
pale small cells that all look alike.

### 3. One bold element per figure

Every other level comes from size and grey value. "If everything is emphasised, then
nothing is emphasised" (Butterick). Ranked text: `INK #23373B` at 1.0×, then
`INK2 #666666` at 0.80×, then `INK3 #757575` at 0.70×. A secondary label is smaller and
lighter, not un-bolded. In a sans face, italic is not emphasis; use it only as a content
class (a model name, a variable).

### 4. Snap near-alignments

Make any two coordinates within one spacing unit equal. A reader registers a 0.5 pt
misalignment as wrong without being able to name it, and layout code produces such
misalignments constantly. `design.snap()` does this.

### 5. One spacing unit and a proximity ladder

Set `u = figure_height / 24`; then inner padding : gap between siblings : gap between
groups = 1 : 2 : 4. With this right, grouping reads without drawing anything, which is the
cheapest ink there is. Do not import the 8-point grid literally. Its stated justification
is that screen sizes divide by 8, a device-pixel argument that means nothing in a vector
figure. What carries over is consistency, and one unit is enough for that.

### 6. Type size as a fraction of image height

State type size as a fraction of final image height, never in points, because points stop
being meaningful once the figure is rescaled. On a 7.5 in slide, primary ≈ 3.3 % ≈ 18 pt
and the floor ≈ 2.5 % ≈ 13.5 pt. Figure-internal text almost never reaches this. This
skill's figures aim for 8 pt, warn below 7 pt and never go below 6.5 pt
(`deckspec.FIG_FLOOR_PT`), which is below the standard. One hand-made example deck ran
6–9 pt, and its author recorded that as a trap. To state it plainly: the figures in a talk
like this are below the projection standard, and that is a known compromise, not an
oversight.

### 7. Optical, not mathematical, centring

Perceptually equal is not measurably equal. A circle must be measurably taller than a
square to look the same height (Hoefler & Frere-Jones; about 3 % overshoot on O and 5 % on
A, per Karow). Two consequences follow. A one-line label centred on its bounding box sits
visibly low, because the box includes descender space the label never uses. An
arrowhead's optical centre is at about a third of its height, not half.

### 8. At most three hues per figure, and never hue alone

`design.ROLES` holds the role colours. The unnamed roles (`a`–`d`: blue, amber, two
greys; `e`, `f` in reserve) take their hues from Paul Tol: safe for red/green colour
blindness, and inside sRGB ∩ CMYK so they survive print. `hit` and `safe` are a fixed red
and green, because their meaning is fixed. That pair is not colour-blind safe on its own,
so `meta.colorblind: true` adds the second channel (underline in deck and PPTX, hatching
in heatmaps). Make every colour distinction redundant with a second channel (position,
label, stroke style), because a conference projector will not render your hues the way
your monitor does.

### 9. One grouping cue per grouping

In order of preference: whitespace, then a tint region, then a hairline frame, then a
connecting line. Stop at the first one that works. Gestalt cues are redundant by design,
so stacking whitespace, a box and a tint is non-data ink. This removes roughly half the
strokes in a typical generated diagram at no information cost.

### 10. Padding from the em, surplus as symmetric margin

Keep equal edges rather than equal areas. `pad_x ≈ 0.75–1.0 em`, `pad_y ≈ 0.5–0.75 em`,
measured from the type actually set in the box, never from the box. When a box in a
uniform grid is bigger than its content, the surplus becomes symmetric margin and nothing
else: symmetric leftover reads as intentional, asymmetric leftover reads as a bug. Do not
stretch type or add a filler icon.

The only legitimate occupant of surplus space is a demotion: one more line at 0.8× in
mid-grey carrying a real fact (a count, a unit, a size). If you have no such fact, leave
the space empty. Dead space often signals that the grid is wrong: six equal boxes with two
nearly empty is usually a four-box diagram with two annotations.

### Below the cut

Two things are deliberately left out of the ten, because they matter less than they
look. Corner radius: use one small absolute value, or zero; a square corner never looks
amateur, and a fat radius often does. Shape variety: rectangles plus one alternate is
plenty.

---

## What makes a generated figure look generated

Graphviz and its relatives optimise the published graph-drawing aesthetics: crossing
number, area, bend count, edge-length uniformity, angular resolution, symmetry. None of
those criteria is consistent whitespace, a shared coordinate set, or typographic
hierarchy. An engine can be optimal by every metric in that literature and still look
machine-made, because the metrics never covered what a designer controls.

The tells, each fixable in code:

1. one stroke weight everywhere (the model has no importance ranking, so none is drawn)
2. near-alignments a unit apart that should be identical
3. padding derived from string metrics, so text nearly touches box edges
4. fill colour carrying nothing: every node a different pastel, no legend
5. recognisable default palettes (graphviz X11, matplotlib `tab10`, mermaid lavender)
6. crossings and dogleg bends a human would have removed by swapping two nodes
7. splines whose curvature does not match from edge to edge
8. unlabelled edges, or arrowheads at both ends
9. no key and no title
10. a figure font that does not match the deck's font
11. labels colliding with lines, with no knockout behind them
12. container boxes drawn at node weight

---

## Where the numbers came from, and how far to trust them

The sources are graded, because a confident-sounding invention is worse than a gap.

**Opened and verified.** Paul Tol's palettes and their CVD/print constraints
(sronpersonalpages.nl/~pault). Butterick's *Practical Typography* on bold/italic, point
size and presentations. The C4 model's notation page (keys are mandatory, notation is
yours, every line unidirectional and labelled) and Simon Brown's InfoQ piece: "the
majority of the software architecture diagrams you've seen are a confused mess of boxes
and lines". IBM Carbon's spacing scale, from source. NN/g on the proximity principle,
which states explicitly that it gives no numeric ratios. Smashing Magazine on Gestalt
common region and uniform connectedness. ColorBrewer's scheme types and the Brewer 1994
citation. Bertin's visual variables: size and value are dissociative and therefore the
only ones that can carry hierarchy; hue and shape cannot. Graphviz's own theory page for
what `dot` optimises. Hoefler & Frere-Jones and Karow on overshoot. AVIXA's published
standards list (V202.01 *Display Image Size*, V201.01 *Image System Contrast Ratio*); both
are real and both are paywalled, so no numbers are quoted from them here.

**Cited from the literature but not re-opened.** ISO 128-2 line conventions and the
ISO 9175-1 √2 pen ladder; Tufte on data-ink and the smallest effective difference;
Munzner ch. 10 on saturation against area; Refactoring UI on ambiguous spacing;
Material's shape scale; ISO 5807 flowchart symbols.

**Synthesis: defensible, not quotable.** The 1:2:4 proximity ladder, the ≥1.5× stroke
separation, the three-step colour model, `u = height/24`, the coordinate-snapping rule,
and the account of why generated figures look generated.

**Folklore, labelled as such.** The "24 pt minimum" and Kawasaki's 10/20/30; "bold under
10 % of type"; a trapezoid meaning that something gets narrower or wider. The last is a
convention copied within one field's figures, with no standard behind it. Use such a shape
because your audience already reads it, not because it is specified.

Most research block diagrams have no standard. Flowcharts have ISO 5807, schematics have
IEC 60617, software has UML and C4; the block diagrams in most papers have only imitation.
With no authority to appeal to, consistency within your own figure set is all that matters,
which is the subject of the next section.

---

## The one place these values live

`scripts/design.py`. Every generator imports it: the chart and diagram kinds, the Beamer
deck and the PPTX.

This is enforced by structure, not by habit. Before `design.py` existed, `build_figs.py`
alone held 39 distinct colours and 12 line widths, and the result was a different grey
and a different stroke on different pages of the same deck. A reviewer's requirement was
that design be consistent across every page, and a careful author cannot maintain that by
hand across every generator. It has to be impossible to get wrong.

If you need a colour or a size missing from `design.py`, **add it there**. Once a
generator writes its own hex code, the deck starts drifting again, and no check will
report it.


## What was learned by looking (side by side with a hand-made deck)

These came from putting a hand-made deck's pages next to the generated ones as images, not
from counting. Each became a rule in a generator, and each has a test.

1. Order is meaning. If a row's name starts below the group band, an eye reading top to
   bottom takes the band as the end of the row above. Spacing does not fix it; putting
   the name above its row does.
2. Use one grouping device. Laying a card under every row and letting the cards touch
   groups nothing and only adds a colour. Proximity (the gap) is enough.
3. A box is as tall as what it holds. Sized as a fraction of the row, an empty box looks
   biggest, and every line added outside the box stretches the whole row several times
   over.
4. The figure font is the deck font. The same pt looks a different size in another font,
   so with two fonts "figure text is smaller than body text" can only be kept by
   measurement. That problem appears on every page, not one.
5. The deck never prints its own markup. `**shape**` once reached the screen with its
   stars while ten checkers passed, because all of them read the spec and none read the
   output's text. There were two causes: markup unwrapped one layer only, and one path
   that skipped `fmt`. Both compile with zero LaTeX errors.
6. Identical drawings say nothing. If rows differ only in width or grouping, the meaning
   is in a difference the viewer has to measure. Say it on the figure: a light shade on
   the group that holds the marked bar (`mark_at`), and one `note` line per row saying
   what its grouping changes. Without those it is the same material in the same place;
   `build_figs` warns when rows differ only in grouping and carry no note.
7. The peak of the talk serves the paper's claim. The audience is most attentive on an
   impact slide. If that slide asks something other than what the paper argues, the
   slides after it spend their time answering that question instead. Hence `meta.thesis`:
   a claim can be checked only if it is written down.
