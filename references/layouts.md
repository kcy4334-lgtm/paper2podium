# Layout recipes: the shapes a generated deck keeps missing

## Contents

- [Why these three](#why-these-three)
- [A composed impact slide](#a-composed-impact-slide)
- [The finding slide: a grid, not the table](#the-finding-slide-a-grid-not-the-table)
- [Slides with no table at all](#slides-with-no-table-at-all)
- [Two columns: one pane shows, the other says how to read it](#two-columns-one-pane-shows-the-other-says-how-to-read-it)
- [Draw the idea, not only the results](#draw-the-idea-not-only-the-results)
- [Layers: why a correct deck still reads as a draft](#layers-why-a-correct-deck-still-reads-as-a-draft)
- [Figures that carry their own point](#figures-that-carry-their-own-point)

Read this when `refcheck` says bullets-only is high, when you are about to paste a
paper table onto a slide, when an impact slide is one big sentence, or when the deck
passes every check and still looks unfinished.

---

## Why these three

A deck built from a paper and a hand-made deck for the same paper were put side by side,
page by page. The spine matched. Three kinds of slide did not, and they are the ones that
carry a talk:

| | What carries it | What a generated deck put there |
|---|---|---|
| The opening claim | the evidence itself, shown: a real example, a photograph, a result | one line of large text |
| The finding | a picture whose shape states the claim | the paper's table, pasted |
| The impact | values set against each other, with what separates them named | one large sentence |

The generated deck also had far fewer figures and far more bullets-only slides. The
recipes below close each of these gaps.

---

## A composed impact slide

One big sentence and a pair of colour-coded numbers both score as "one standout slide",
but they do completely different work. A generated deck tends to write the sentence where the pair
was needed. Give `big` a list and it sets the values against each other:

```yaml
kind: standout
big:
  - {value: "+12.6", label: "town branch",   note: "more loans a day"}
  - {value: "+27.1", label: "suburb branch", note: "more loans a day", mark: safe}
gap: "more than twice"     # goes between them; this is the slide's claim
bullets: ["Sunday opening pays most where **nothing else nearby is open**."]
```

The standout keys stack top to bottom, and each has its own job:

- `lead` is one line above, for the context the two values share.
- `big` holds the values.
- `gap` sits between them. A connective ("or", "vs") goes between the values; a phrase
  with a number in it goes small on the name line.
- `lines` goes below, one entry per line, each with its own `size` (`large`, `normal`,
  `small`). Falling sizes read as "what follows from this, then the detail".
- `flow` replaces `big` when the slide narrows in steps instead of setting two things
  side by side.


## The finding slide: a grid, not the table

A booktabs table pasted onto a slide makes the audience read every row. The same numbers
as a coloured grid make the claim visible before anything is read. Put the table in the
spec and let `chart` turn it into the picture. The table is data there, not display, and
the slide shows only the grid:

```yaml
kind: figure
title: "Rain rises toward the coast in every season"
chart: {from: self, kind: heat}
table:                                    # feeds the chart; not drawn
  header: ["mm per month", "spring", "summer", "autumn", "winter"]
  rows:
    - ["inland", "31.8", "18.9", "43.7", "36.2"]
    - ["hills",  "47.6", "27.9", "61.3", "52.4"]
    - ["coast",  "68.1", "39.5", "88.7", "74.3"]
```

---

## Slides with no table at all

This covers Introduction, Background, Method overview, Limitations and Conclusion.

Before drawing, check whether the section **compares several things along the same
dimensions**. A related-work section usually does (what each method changes, what it
adds). Those sentences are a table. The table is the evidence of the gap, and a flow
diagram of the gap loses it.

When the section describes a process or a structure instead, `chart` cannot help: it
draws from a table, and there is none. This is where generated decks fall back on
bullets-only slides. Use `diagram` to draw the schematic:

```yaml
kind: figure
title: "A clinic visit, from the door to the pharmacy"
diagram:
  kind: flow                    # flow | stack | grid
  boxes:
    - {label: "Check-in"}
    - {label: "Triage"}
    - {label: "Wait for a room", mark: hit}
    - {label: "Exam"}
    - {label: "Pharmacy"}
  note: "Patients spend most of the visit in the marked step."
foot: ["A room frees up only when the exam before it ends."]
```

- `flow`: boxes and arrows. Use it to answer `prose_audit`'s "you compare these across
  tables and never draw them."
- `stack`: layers; what sits on what.
- `grid`: two axes combined, such as weekday by time slot. It also draws a matrix split
  into blocks (tiles, a mask, a schedule by row and column). `cols` and `rows` name the
  axes, `boxes` fill row by row, and `mark` colours a block. A box with no label is left
  out unless it has a `mark`. `mark: blank` draws an empty neutral block, so the shape of
  the matrix stays visible:

  ```yaml
  diagram:
    kind: grid
    cols: ["bay 1", "bay 2", "bay 3"]
    rows: ["rack A", "rack B"]
    boxes: [{label: "done", mark: safe}, {label: "now", mark: hit}, {label: "", mark: blank},
            {label: "", mark: blank}, {label: "", mark: blank}, {label: "skip"}]
  ```

A diagram writes its own sidecar, so `outcheck` can see the labels, and it counts as a
figure everywhere a figure counts.

---

## Two columns: one pane shows, the other says how to read it

The most common two-column shape is a visual in one pane (a table, a chart, a schematic)
and, beside it, the sentences that tell you how to read it. The other uses are rarer: two
of the same kind set against each other, or one wide column that centres something.

A ratio that names no slide does not get fixed. `refcheck` names the slides that stack a
narrow visual above its explanation, or says that none qualify (every visual is wide, or
has one line of comment). In that case leave the ratio alone; do not split slides to meet
it.

```yaml
kind: columns
title: "All three questions score higher each year"
left:
  width: 0.56
  chart: {from: self, kind: heat}     # self = this pane, not the slide
  table:                              # the chart uses it; it is not drawn twice
    header: ["Question", "2022", "2023", "2024"]
    rows:
      - ["Staff were helpful", "61.4", "66.2", "71.5"]
      - ["The wait was short", "38.7", "44.9", "52.3"]
      - ["I would come back",  "72.6", "75.1", "79.8"]
right:
  head: "How to read it"
  bullets:
    - "Darker is a larger share. The wait question starts lowest and gains the most."
  text: "Share of respondents answering 4 or 5 out of 5, in percent."
```

Not every visual belongs beside its commentary. When both were converted and rendered to
check, heat grids got better in a pane, and a table with long cells got worse: squeezed
into a narrow pane, it set at a size nobody reads. The rule is **text width, not column
count**. `refcheck` measures the longest cell in each column, and anything over ~55
characters stays full width. A `flow` diagram runs horizontally and stays full width too;
a `stack` is vertical and belongs in a pane.

Pane footnotes go in the pane's own `text:`, not the slide's `foot:`. A slide-level `foot`
hangs below both columns and reads as a footnote to neither.

---

## Draw the idea, not only the results

A hand-made deck spends a good share of its figures on concepts rather than results: what
the object is, and where you change it. These figures come before the first slide that
puts numbers on screen, so the audience knows what the numbers are about.

The generated deck had none of them, because `diagram` could then only make boxes and
arrows. The concept slides became bullets or were skipped, and the deck went straight to
tables. That is what "nothing but numbers" means, and it can be counted: `prose_audit`
reports when the first slide carrying measurements has no figure before it at all.

### `strip` — what a thing is made of

```yaml
diagram:
  kind: strip
  rows:
    - label: "book"
      cells: [{label: shelf, span: 1, mark: place}, {label: author, span: 3, mark: who},
              {label: year, span: 4}, {label: copy, span: 1}]
      note:  "copy tells duplicates apart"
    - label: "journal"
      cells: [{label: shelf, span: 1, mark: place}, {label: title, span: 3, mark: who},
              {label: issue, span: 2}]
    - label: "map"
      cells: [{label: drawer, span: 1, mark: place}, {label: region, span: 2}]
      note:  "filed by drawer"
  legend: {place: where it is kept, who: who or what it is}
```

Use it for anything that is a run of named parts: schedules, record layouts, token
sequences, time slots, pipeline positions. `span` repeats a cell. The units stay visible,
so the reader can count them; add `merge: true` when the span is one piece, not a count
of units.

`mark` is a name you pick, not a colour. Each new name gets the next colour in turn, so
`light` does not mean pale. Leave `mark` out for a neutral grey cell. Colours come from
Paul Tol's *light* scheme, which is designed for coloured areas carrying black text
(SRON/EPS/TN/09-002; his *bright* scheme is too strong behind text).

### `strip` in grouping mode — how things are divided

```yaml
diagram:
  kind: strip
  rows:
    - label: "chapter 3"
      sub:   "pages"
      bars: 39
      groups: [13, 17, 9]
      group_label: "section"
      outer: "one running title"
      mark_at: 22
      note: "bar heights only suggest pages; they are not data"
```

Use it for sections, windows, chunks, tiles, batches. The groups need not be equal.
**The bar heights are shape, not data**, so say so in the note.

For two levels (one name for the whole, then one per group inside it), set `outer` on the
row. It draws a second band across all the bars, above `groups`. Without it the outer
level exists only in the text. `mark_at` puts the one value the argument turns on in the
accent colour.

The same two levels fit an organisation, where the groups are teams and the outer band is
the one person they all report to:

```yaml
diagram:
  kind: strip
  rows:
    - label: "parks department"
      sub:   "staff"
      bars: 51
      groups: [22, 17, 12]
      group_label: "team"
      outer: "one director"
      note: "each team keeps its own rota"
```

### `pipeline` — what the thing is built from, and where you cut

```yaml
diagram:
  kind: pipeline
  rows:
    - label: "Main St bakery"
      sub:   "opens at dawn"
      stages:
        - {label: "dough",   group: "kitchen", count: "3 bakers"}
        - {label: "oven",    group: "kitchen", count: "1 baker", mark: hit}
        - {label: "counter", group: "shop",    count: "2 clerks"}
      out: "bread sold"
    - label: "Market bakery"
      stages:
        - {label: "dough",    group: "kitchen", count: "2 bakers"}
        - {label: "proofing", group: "kitchen", count: "1 baker"}
        - {label: "oven",     group: "kitchen", count: "2 bakers", mark: hit}
        - {label: "counter",  group: "shop",    count: "1 clerk"}
      out: "bread sold"
```

Group headers span consecutive stages and a dashed rule falls between groups, so the
layout shows where one part ends. The two rows need not have the same stages. `count`
goes under each stage. Two rows set two subjects against each other.

A group header only says where a span starts and stops. To say the parts are one thing
(one building, one team), give the row a
`frame: {label: "one kitchen", note: "ovens and staff are shared", mark: a}`. It draws
one outline around every stage, with the name inside its top edge, inputs hanging below
it and the output outside.

The conclusion goes in the figure's `takeaway`, **not its `note`**. `takeaway` is drawn
bold inside the picture and written to the sidecar, so `deckcheck` and `outcheck` see it.
`note` is muted and reads as a caption the eye has already left. A plain image
(`figure.path`) has no `takeaway`. There, and only there, the conclusion goes in the
slide's `foot`.


---

### `graph` — when the arrows cross

```yaml
diagram:
  kind: graph
  nodes:
    - {id: plan, label: "plan charge", col: 1, row: 0, shape: oval}
    - {id: c1,   label: "cell 1",      col: 0, row: 1, mark: a}
    - {id: c2,   label: "cell 2",      col: 2, row: 1, mark: a}
    - {id: upd,  label: "update plan", col: 1, row: 2, mark: b}
  edges:
    - {from: plan, to: c1, kind: control}
    - {from: plan, to: c2, kind: control}
    - {from: c1, to: upd, kind: data}
    - {from: c2, to: upd, kind: data}
    - {from: c1, to: c2, kind: state, label: "shared rack"}
  takeaway: "Control flows down; the rack is shared state."
```

`col`/`row` place each node on a grid (from 0). The edge `kind` sets the line (dashed
control, thin data, heavy state), and a legend appears for the kinds used. Rename them
with `edge_names`. `bend: 0.2` curves an edge that would cross a node.

### `figure.highlight` — pointing into a figure you cannot redraw

```yaml
figure:
  path: queue_by_hour.png               # one panel of the paper's figure
  caption: "From the paper."
  highlight: {x: 0.59, y: 0.17, w: 0.22, h: 0.64, label: "lunch hour"}
```

`x`, `y`, `w`, `h` are fractions of the image measured from its top-left. A list draws
several boxes. With no `mark` the box takes the neutral emphasis colour, meaning "look
here" rather than a verdict. `mark: hit` (red) and `mark: safe` (green) are only for what
the paper itself judges worse or better. The deck draws the box and its label on the
image; the PPTX draws them as shapes over the picture.

The label goes above the box. When the box starts at the top of the image, where a label
would cover the figure's own titles, it goes below; with no room there either, inside.
Force a side with `label_at: above | below | inside`.

To show one panel of a multi-panel figure, cut it with `crop` (fractions from the
top-left, like `highlight`). The builders cut one PNG and both outputs use it. `highlight`
is then measured on the cut image. Cut in the white space between panels. The build warns
when an edge slices through labels (name fragments are left on the slide) or through a
filled band (a colour bar without its tick numbers cannot be read). Widen the crop, or
keep the colour bar whole.

An image that is not data at all (a map of the sites, a photograph of the apparatus) has
nothing to redraw. Say so with `picture: "map of the two sites"`. The reason is required,
and `prose_audit` then stops asking you to redraw it:

```yaml
figure:
  path: charge_curves.png
  crop: {x: 0.36, y: 0, w: 0.64, h: 1}         # the right part: the wet cells
  highlight: {x: 0.39, y: 0.22, w: 0.29, h: 0.67, label: "after 1200 cycles"}
```

### `dots` — values close together, or spanning orders of magnitude

```yaml
chart: {from: self, kind: dots, xlabel: "hours to full"}     # add log: true for 10x spreads
table:
  header: ["charger", "dry", "wet"]
  rows: [["A", "24.5", "25.0"], ["B", "<hit>23.9</hit>", "24.7"]]
```

A bar is honest only from zero, so a difference between 23.9 and 25.0 is invisible as
bars. A dot shows its value by position, so the axis may start at the data. For values
that span ten times or more (throughput, latency), use `log: true`. Bars refuse `log` for
the same reason.

### `lines` — how one quantity moves as another grows

```yaml
chart: {from: self, kind: lines, log: true, takeaway: "The wet cell fades; the dry cell holds."}
table:
  header: ["cell", "charge cycles", "capacity (Ah)"]
  rows:
    - ["dry", "250", "1.93"]
    - ["dry", "1200", "1.88"]
    - ["dry", "4800", "1.84"]
    - ["wet", "250", "1.85"]
    - ["wet", "1200", "1.62"]
    - ["wet", "4800", "<hit>1.40</hit>"]
```

Use it when the paper's point is a shape: what happens as the budget, the size or the
time grows. Each row is one point, `[series, x, y]`, so series may have different x
values. The header names the axes. The series name is written at the end of its line, so
there is no legend to look up. A dots chart puts x inside the row names, and then the
shape is lost.

Copy the cells as the paper prints them. `8.7 Trillion`, `250 Billion`, `8.65M` and
`1.92e+19` are read as numbers, and the ticks use the same units. A series with one row
is a single point, which is how you place real systems next to a fitted curve. `log: both`
(or `y`) puts the other axis on a log scale too. To point at one place on a line, such as
where two lines cross, use `callout: {series: "wet", at: "1200", text: "crosses here"}`.
`at` is the x value as the table prints it.

## Layers: why a correct deck still reads as a draft

With the first three recipes above (impact, finding, no table) applied and every check
clean, the deck still read as a draft next to a hand-made one. Both were then measured
again, this time for how much was on each slide rather than what:

| | Hand-made | Generated |
|---|---|---|
| ink coverage, median | 27.2% | 24.7% |
| items per slide, median | 7 | 6 |
| depth the body reaches | 96% | 96% |

The amounts are nearly the same. The difference was layering: text at several weights
around the one thing to look at, each weight doing a different job. Four keys make that
possible, each for a different need:

- `parts`: a pane whose content has an order of its own. A definition, then the symbols
  it uses, then the formula; or a sentence, a list, and a sentence that closes it. The
  chunks are drawn in the order written.
- `fine`: one step below `foot`, for notation, definitions and caveats, so the
  conclusion and its small print do not share a weight.
- `flow` on a standout: an argument that narrows in steps, top to bottom, instead of
  setting two things side by side.
- `takeaway`: the conclusion drawn inside the figure, where the eye already is.

Without these keys, a pane draws each key once in a fixed order, with `text` always last;
`foot` has a single weight; and an impact slide can only set two things side by side.
Two examples:

```yaml
- title: "How long does a patient wait?"
  left:
    width: 0.38
    parts:                       # chunks, in the order written
      - text: "Patients arrive at random, and one nurse sees them in turn."
      - bullets:
          - "**λ** patients arrive per hour"
          - "**μ** patients are seen per hour"
      - text: 'Mean wait in the queue: $W = \lambda / (\mu(\mu - \lambda))$'
      - {size: fine, text: "Holds only while λ is below μ."}
  right:
    figure: {path: wait_curve.png}
  foot: ["Waits stay short until arrivals near what the nurse can see, then climb fast."]
  fine: ["λ and μ are averaged over one week of the morning clinic."]
```

```yaml
- kind: standout
  lead: "Where should the new stops go?"
  flow: ["59 places riders asked for",
         "39 on a street the bus already uses",
         "the two the budget covers"]
  bullets: ["Those two are where the pilot ran."]
```

Rules that keep this from going wrong:

- `parts` replaces the other keys in that pane. Mixing them would set the order in two
  places, and then the three outputs each pick their own.
- `fine` is notation, definitions and caveats; `foot` is the conclusion. Put them at one
  weight and the audience reads neither.
- `flow` narrows in steps; `big` sets two things side by side. They look similar and do
  different work.

---

## Figures that carry their own point

In one example deck, measured at source resolution, type size was the number that
mattered. A tile value stood 25pt of stroke on screen against a 12pt body, three times
the body size. A grid drawn with its values at body size (9–10pt) reads as a coloured
table.

`fit_text` grows text as well as shrinking it, so a figure's values can stand larger
than body text and emphasis does not have to come from fill and colour alone. A grid
spends spare height on its rows rather than leaving white space beneath.

```yaml
chart:
  kind: tiles
  from: self
  verdict: {hit: "over target", plain: "within target"}   # plain = unmarked cells
  takeaway: "Waits shorten every quarter at both clinics."
  col_notes: ["January to March", "April to June", "July to September"]
table:
  header: ["minutes waited", "Q1", "Q2", "Q3"]
  rows:
    - ["North",   "<hit>33.6</hit>", "<hit>27.1</hit>", "18.9"]
    - ["Harbour", "<hit>31.8</hit>", "24.1", "14.3"]
```

Tiles show **only the rows the argument compares**. A row that is mostly dashes (a clinic
that opened late, quarters with no record) shrinks every tile to make room for empty
cells. Leave it out of the tiles and name it in the `fine` line or a backup table. The
build warns when most of a panel's row is dashes.

```yaml
diagram:
  kind: strip
  legend: {r4: "route 4", r9: "route 9"}
  rows:
    - label: "route 4"
      cells: [{label: "all day", span: 6, mark: r4, merge: true}]
      axis: {ticks: [0, 0.17, 0.22, 0.29, 0.36, 0.59, 1],   # where the stops are
             left: "depot", right: "hospital"}              # a number gives even ticks
      note: "stops cluster around the market"
    - label: "route 9"
      cells: [{label: "peak hours", span: 6, mark: r9, merge: true}]
      axis: {ticks: [0, 0.17, 0.22, 0.87, 0.92, 1], left: "depot", right: "hospital"}
      note: "two stops near each end, none between"
  takeaway: "Route 9 skips the middle of town."
```

```yaml
diagram:
  kind: pipeline
  rows:
    - label: "Office heating"
      stages:
        - {label: "sensor", group: sense, count: "3",
           inner: ["probe 1", "probe N"]}
        - {label: "controller", group: control, count: "2", mark: safe,
           inner: ["estimator", "setpoint"],
           feed: {label: "the schedule", sub: "set temperatures by hour"}}
      out: "heater power"
      loop: "the room warms and the sensor reads it"
      caption: "one controller, updated once a second"
  takeaway: "Sense, decide, heat."
```

`feed` hangs a box under a stage with an arrow up into it. `loop` draws the return path
from `out` back to the front, with its sentence on the line. Together they show a closed
loop rather than a left-to-right row, which is what a feedback controller is. A row is
laid out additively (box, as tall as its own contents, plus `count`, `caption`, `feed`
and `loop`), so a box with nothing inside is drawn short, not stretched.

```yaml
chart:
  kind: bars
  from: self
  callout: {at: "Week 4", series: 0, text: "school holidays begin"}
  takeaway: "Visits climb every week of the summer."
table:
  header: ["week", "visits per day (hundreds)"]
  rows: [["Week 1", "11.7"], ["Week 2", "14.3"], ["Week 3", "18.9"], ["Week 4", "24.1"], ["Week 5", "27.1"]]
```

The same keys point at the one condition that departs from the rest: put the `callout` on
it and name it in the `takeaway` ("Sales rise everywhere except the coast.").

Four rules behind these:

- Words carry meaning; hatching and colour carry a channel. `verdict` writes its words
  ("over target" above) under the value. Without them the audience only infers that red
  is bad, and a colour-blind viewer gets the hatch but still no sentence. Pick the words
  the paper uses for its own judgement. A paper that compares each cell with a baseline
  might say `{hit: "slower than last year", plain: "no clear change"}`.
- The conclusion belongs inside the picture. A caption sits outside it, so the eye has
  already moved on. `takeaway` is bold on the right; `note` stays muted on the left.
- One size per grid. Sizing each cell to its own content makes `+3.1` and `-46.3`
  different sizes, and then size starts meaning something nobody said.
- Cells and a position axis answer different questions. A run of cells says how a thing
  is divided; an axis says where its values fall. Draw the one the argument needs.
