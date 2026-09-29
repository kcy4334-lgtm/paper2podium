# What looking finds that counting cannot

## Contents

- [Why this file exists](#why-this-file-exists)
- [The five differences](#the-five-differences)
- [A standout slide is composed, not just large](#a-standout-slide-is-composed-not-just-large)
- [Things that were invisible to every check](#things-that-were-invisible-to-every-check)
- [What to do with this](#what-to-do-with-this)

---

## Why this file exists

A deck generated from a paper and one hand-made example deck for the same paper scored
within a couple of points of each other on figures, tables, impact slides and emphasis.
Rendered and put side by side, they looked nothing alike.

Two of the differences below became measurable only after someone looked, and `refcheck`
now checks them. The rest cannot be mechanized, which is why they are written down.

---

## The five differences

### 1. Show the evidence; don't assert it in a large font

If the audience could watch the claim happen, show it happening. Say a paper finds that a
dye fades faster in warm storage. One slide shows a 2×3 grid of the actual micrographs
(two storage times down, three dyes across) with the measured intensity printed under
each image. Another slide says the same thing as one line of large white text on a dark
slide.

Both count as one slide. Only the first lets the audience see it.

That is the cost of a figure gap, and it is not decoration. Use `figure.grid` (see
`python scripts/deckspec.py --keys`): rows, columns, per-column captions, and a
per-column `mark: ok|fail` border when an outcome really is pass or fail.

### 2. Let the layout carry the claim

When the claim is a comparison, give each thing compared its own place on the slide (its
own panel, column or row band), so the claim is visible in the shape before a single
number is read.

A flat list with two attributes in one cell (`City, 2019` / `City, 2020` /
`Coast, 2019` …) holds the same numbers, but the claim is not visible; the reader has to
rebuild it by reading.

`refcheck` now flags a first column that keeps repeating a prefix.

### 3. Two columns must hold two different things

A generated deck put a table on the left and a chart of that same table on the right, on
four slides. That scores as a two-column slide, so the count went up, but it is
duplication, not comparison. Two columns need to hold two different things: two subjects,
or a table and the figure that explains it.

`refcheck` now flags a chart drawn from a table displayed on the same slide.

One idiom to use: show something in one pane and say how to read it in the other.
`chart: {from: self}` works inside a pane. For a long time it silently did not, and
generated decks lost this idiom without anyone noticing. See
[layouts.md](layouts.md#two-columns-one-pane-shows-the-other-says-how-to-read-it).

### 4. Tell the audience how to read the table

The line directly under a table is where the eye goes next. Use it to point: which cell,
row or column holds the claim, then one coloured line of conclusion. A generated deck put
a caveat there instead.

The first directs the eye; the second explains a limitation. Both belong in the talk, but
only the first belongs directly under the table.

### 5. Spend colour sparingly or it stops meaning anything

Red on a few cells stands out. Red on most cells says nothing. A generated deck coloured
nearly every cell of its heatmap and coloured the same numbers again in the table beside
it.

Never let colour carry the meaning alone. See "Colour and legibility" in
[traps.md](traps.md), and `meta.colorblind: true` in `SKILL.md` §7.

---

## A standout slide is composed, not just large

An impact slide that works is built from parts: two values set against each other with
what each one is, or one number and the thing it is measured against, or a question and
the smallest piece of evidence that answers it. A single large sentence is a different,
weaker slide.

`refcheck` counted the standout slides of a generated deck and a hand-made one at nearly
the same share and called them "matched". They did completely different work. The count
tells you a standout slide exists. It cannot tell you whether anything was composed on it.

---

## Things that were invisible to every check

Each of these compiled with zero errors and passed every checker:

- a title with two words silently deleted (a `\\` line break followed by a word, read as
  a command)
- a table overrunning its column and printing on top of the text beside it
- rules drawn through the middle of table rows, when a header cell wrapped
- `\centering` leaking past a table and centring the note underneath it
- a `foot` line pushed off the bottom of the slide: present in the `.tex`, absent from the
  PDF

`fitcheck.py` and `outcheck.py` now catch the last three. The first two were found by a
person opening the image.

---

## What to do with this

Render the deck and open at least **the title, one table slide, and one figure slide**.

Then ask of each: could the audience get the claim without reading every number? If the
answer comes from the shape of the slide, the slide works. If it comes from reading, the
layout adds nothing and the slide is a paragraph in slide form.
