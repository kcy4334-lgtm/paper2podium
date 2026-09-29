---
name: paper2podium
description: Use when turning a finished academic paper or thesis into a conference presentation — a slide deck (Beamer/PDF), a PowerPoint (.pptx) version for the venue machine, and the speaker script with timings. Triggers include "convert my paper to ppt", "make slides from this paper", "turn my paper into a pptx", "build my conference deck", "make my ICASSP/NeurIPS talk", "write my speaker notes", "how long will this talk run", and revising a deck already built this way. Reads LaTeX (best supported), Markdown, or a compiled PDF when that is all there is (text and figures are extracted; tables arrive as text). NOT for documents built from nested bullets with no section structure, NOT for slide decks with no source document to check against, NOT for posters, and NOT for drafting the paper itself.
license: MIT
---
# paper2podium

Almost every mistake in a talk built from a finished paper has one of two shapes:

- a number gets retyped wrong, or
- a summary claims something the paper does not.

This skill makes a machine catch both. Deciding what to say is still your job.

## 0. Settle this first

The source is **authoritative**. If the deck disagrees with the paper, the deck is wrong.
Decide this before you start, or you will end up editing the paper to match a slide.

If the source is not final yet, do not use this skill: you would build everything twice.

## 1. What's here

| File | What it does |
|---|---|
| `scripts/scaffold.py` | Paper source → a `slides.yaml` skeleton with `TODO:` where a human decides |
| `scripts/pdf_paper.py` | For a paper that exists only as a PDF: PDF → `<name>.md` (headings recovered from type size) + `figs/fig_N.png` cut at each caption |
| `scripts/deckspec.py` | Loads and validates `slides.yaml`, the single source the three builders share |
| `scripts/design.py` | Stroke weights, role colours, spacing unit, radius: the single source for how it looks |
| `scripts/build.py` | One command: figures, deck, PDF, PPTX, script. Reads the LaTeX log and, where a slide overflowed, shrinks that slide's figure by exactly that much and builds again |
| `scripts/build_deck.py` | `slides.yaml` → `talk.tex` (Beamer + metropolis), traps already handled |
| `scripts/build_pptx.py` | `slides.yaml` → `talk.pptx`, real text, notes transplanted |
| `scripts/build_script.py` | `slides.yaml` → `script.md` with running time and slide thumbnails |
| `scripts/deckcheck.py` | The gate: a nine-section (A–I), two-way check against the source. `--selftest` proves it can still fail |
| `scripts/outcheck.py` | Did what you wrote arrive? Reads text back out of the rendered PDF/PPTX/script |
| `scripts/fitcheck.py` | Does it fit? Reads coordinates out of the rendered PDF: overflow, overlap, text too small |
| `scripts/build_figs.py` (+ `scripts/figs_extra.py`: `graph`, `dots`, `lines`) | Draws a chart from a table already in the spec, and diagrams for the slides that have no table; writes the sidecar from the same values |
| `scripts/diffcheck.py` | What the source has and the deck never used: its numbers, the sentences where it explains why, and the hedges ("up to", "comparable", "may") the deck dropped |
| `scripts/refcheck.py` | Design density, the mechanical form of "this looks thin" |
| `scripts/sidecar.py` | Makes numbers rendered into figures visible to a text-based checker |
| `scripts/timing.py` | Talk duration, counting numbers and acronyms as the words they are read as |
| `scripts/prose_audit.py` | Can the audience follow it? Screen jargon never said aloud · undefined colour key · one word with two values · unexplained blanks · a cast never drawn · prose |

Reference files. None is loaded until you need it; read each at the point given here:

| File | Read it when |
|---|---|
| [references/planning.md](references/planning.md) | Always, at step ①, before filling any slide. How many slides each section needs, read off signals in the paper; ends with the `plan.md` you write |
| [references/looking.md](references/looking.md) | No reference deck exists (the normal case): read it at step ② instead. Also before accepting a deck that passed everything |
| [references/layouts.md](references/layouts.md) | `refcheck` says bullets-only is high · you are about to paste a paper table onto a slide · an impact slide is one big sentence · `refcheck` says two-column is low and names slides |
| [references/traps.md](references/traps.md) | Before you start (it is a short read, and half of it is about Windows and heredocs), and again when a check behaves oddly or a build succeeds with wrong output |
| [references/design.md](references/design.md) | Before writing any colour, line width, radius or padding into a generator, and whenever a figure is correct but looks amateur |
| [references/audience-panel.md](references/audience-panel.md) | You are ready to put it in front of people (step ⑨). Every check in parts 3 and 4 of `prose_audit`'s output ("never said aloud", "where the audience trips") started as a finding from this protocol |

```bash
python scripts/scaffold.py     paper/paper.tex -o slides.yaml
python scripts/build.py        slides.yaml -o out --limit 15 --qa 3   # figs, tex, pdf (overflow fed back), pptx, script, time gate
cp config.example.yaml deckcheck.yaml                  # once: set the paths (source = the paper only)
python scripts/deckcheck.py    deckcheck.yaml          # exit 1 on any failure
python scripts/deckcheck.py    deckcheck.yaml --selftest   # is the gate awake?
python scripts/outcheck.py     slides.yaml --deck out/talk.pdf --pptx out/talk.pptx \
                               --script out/script.md --sidecar out/figs/values.txt
python scripts/diffcheck.py    out/talk.pdf --source paper/paper.tex --sidecar out/figs/values.txt --script out/script.md
python scripts/refcheck.py     slides.yaml
python scripts/prose_audit.py  slides.yaml          # shown-but-never-said, and prose
python -m unittest discover tests
```

Give your slot and the time becomes a gate instead of a printout: `--limit 15 --qa 3` exits 1
when the calculated time runs over. Put your own images in `meta.figdir` beside `slides.yaml`;
`build.py` copies them into `out/figs` next to the ones it draws. Tool messages are in English;
`script.md` follows `meta.lang` (en | ko), or the language of `say` when it is unset.

`slides.yaml` is the **single source**. Deck, PowerPoint and script are all generated from it.
Never hand-edit a generated file: the edit is lost on the next build and the three outputs
drift apart. This one rule replaces a whole class of bookkeeping between the three outputs.

No project-specific value lives in the scripts. Paths, claims and banned wording all sit in
the config. A value hardcoded into a script stops the script from being reused.

## 2. The order

### ① Skeleton — keep the paper's section order as the slide order

```bash
python scripts/scaffold.py paper/paper.tex -o slides.yaml
```

That gives you one slide per section, the tables already transcribed, and each section's
numbers listed in a comment. Everything a human decides is marked `TODO:`. While any `TODO:`
remains in the file, it is a draft.

If you only have a PDF, run `python scripts/pdf_paper.py paper/paper.pdf -o paper/` and use the
`.md` it writes (named after the PDF) as the paper everywhere. Read [traps.md](references/traps.md)
"A paper that exists only as a PDF" before trusting its crops or tables.

Keep the paper's order: rearranging loses anyone who read the paper. But one section is rarely
one slide. Read [references/planning.md](references/planning.md). From signals in the paper it
says which slides a section needs (a theorem's assumptions, a leaderboard's one metric, a fitted
law's range, the object before the results, the objection, …), and the order comes from the
paper's argument. Write `plan.md`, one row per slide, before ②.

### ② Fill it

Usually there is no reference deck; that is the normal case. Go straight to the `TODO:`s below,
and read [references/looking.md](references/looking.md) now rather than at step ⑦. It describes
what a hand-made deck does that a generated one does not, which is what reading a reference
would have told you.

If a deck for this work does exist, open it and read all of it: the content of each slide, not
only the frame titles. A talk written from titles alone comes out as a generic bullet deck, and
everyone except its author sees the difference. Then pass it to `refcheck --ref old/talk.tex`
so the comparison is measured too.

Look for these in it, because they are rarely stated anywhere:

- The shape that carries the message. A table may be reordered so a trend reads left to right,
  or so the one row that departs sits apart. That shape is the argument, and a flat list of the
  same numbers throws it away.
- The reading device. Most good decks have one: a colour that means "this is the finding".
  `<hit>` marks what the paper judges bad (a missed target, a proven failure, a significant
  drop, or, with no test, the worse result it names). Anything the paper does not judge stays
  unmarked (grey), because no difference found is not proof of safety. `<safe>` marks what the
  paper shows works or concludes, never your own reading. In a system diagram only,
  `mark: safe` rings the part studied.
- What sits beside what. A table alone is a table; a table beside something that is not already
  in it is an argument, such as the figure that explains it or a second subject read the same
  way. A picture of the same numbers does not count: a chart drawn `from:` the table beside it
  is duplication (`refcheck` fails it), and tiles of only the few cells compared are a zoom
  (planning §table).

Carry the paper's explanations, not only its numbers. A paper spends paragraphs on why:
what a term means, what a design prevents, what a caveat rules out. Those sentences carry no
numbers, so every number-based check passes a deck that names a concept and never explains it.
Read the setup and discussion for "without X, Y happens" and "therefore Z does not follow".
`diffcheck` lists what you skipped, but only at ⑦.

Then fill the `TODO:`s. The spec itself prints what you can write. Never guess a key name, and
never copy a key table out of this file, because a copy drifts:

```bash
python scripts/deckspec.py --keys        # every slide key, pane key and emphasis mark
python scripts/deckspec.py slides.yaml   # validate: an unknown key is an error, not ignored
```

- Titles are what you say to the room. Not "Results", and not the paper's result sentence
  (that goes in `lead` or `say`), but for example "Evening buses run late on every route".
  See planning.md §voice.
- Make each bullet a claim, not a label, and usually one per slide, not three. Measured on one
  example deck: 1.0 bullets per slide, 18.8 words each. Write "Evening buses arrive later every
  month, and by winter one in four misses its connection.", not "Delays grow". Claim and
  evidence travel together; three short labels are a list. Past roughly thirty words, the text
  belongs in `say`.
- Some slides must ask the audience a question: about one in seven on one example deck, such
  as "What does it cost per user?" or "Does it hold on a holiday?". They pre-empt the objection
  the listener is already forming. A paper seldom asks such questions (keep any it does ask),
  so a deck built from its sentences has none; `refcheck` fails on zero.
- `say` holds what you say that the screen cannot show: where to look, why it happens, what
  follows. Never open it by restating the title.
- Mark where to look with `**bold**`, findings with `<hit>` / `<safe>`, and code names with
  single backticks (monospace, not emphasis).
- Keep the full table in view, beside the highlight or just before it. Never hide it.
- Use three or four `standout` slides, at the turning points, and nowhere else.
- Name the paper in `meta.paper:` (a path, or a list). Without it nothing can compare the
  deck's words to the paper's, and a talk drifts from its paper in wording long before it
  drifts in numbers. With it, `prose_audit` and `deckcheck` (H) list every term the deck uses
  three or more times that the paper never uses.
- Write `meta.thesis:`, the one sentence this talk exists to deliver. `prose_audit` checks every
  standout against it. A standout that shares no words with the thesis asks a different
  question at the room's most attentive moment, and every later slide then answers that
  question instead. The closing standout must restate the thesis.

Then measure it instead of trusting your eye:

```bash
python scripts/refcheck.py slides.yaml
```

It counts figures, tables, two-column slides, emphasis, question-titled slides, bullets-only
slides, and how many bullets sit on a slide. Three of those carry across fields, and they are
the numbers to act on:

- Bullets-only fraction high: the mechanical form of "this looks thin". You made nothing to
  show. First ask whether the section compares several things along the same dimensions
  (prior studies by dataset, metric and year). Those sentences are a table, so build it.
  Otherwise, a process or a structure is a `diagram:` (`flow|stack|grid|strip|pipeline|graph`);
  it writes its own sidecar and counts as a figure everywhere.
- Question-titled slides zero: you built a report, not a talk. See above.
- Bullets per slide high: you are listing, not arguing. One example deck runs 1.0.

The rest of the baseline is one deck's profile, not a rule. It came from one example deck, and
a concept talk, a theory talk or a demo has a different shape, as it should. Without `--ref`,
only those three count as failures (emphasis is a note), and you can move the rest with
`--baseline figure=0.2`. Pass `--ref old/talk.tex` only when you are rebuilding a deck that
already exists.

Every number in that baseline is measured from a real deck; make sure yours is too. Two were
once typed by hand (2.6 bullets of 11 words) while the deck ran 1.0 of 18.8, and that invented
pair became written guidance telling a fresh agent to chop every argument into short labels.
A made-up reference value does not stay a number; it becomes advice.

An impact slide needs composing, not only large type, and the finding slide should show a grid,
not the paper's table. Each takes two lines of spec. [references/layouts.md](references/layouts.md)
has four recipes: `big` as a list; `chart` replacing its own table; `diagram` for slides with no
table; one pane that shows and another that says how to read it. One grid for two subjects side
by side (`kind: tiles` with `panels:`) is in [planning.md §two-subjects](references/planning.md).

A slide that holds one thing reads as unfinished, and no check catches it. Measured against one
example deck, ink coverage and object counts matched almost exactly (27.2% against 24.7%), yet
the generated deck still looked like a draft. The difference was layering, not quantity: a
hand-made slide stacks text of several weights around the one thing to look at, and each weight
does a different job. Four keys close that gap: `parts:` (chunks in a pane, in the order
written), `fine:` (notation and caveats, one step below `foot:`), `flow:` (an impact slide
narrowing top to bottom) and `takeaway:` (a figure's conclusion drawn inside the picture).
Worked examples, and the rules that keep them from going wrong, are in
[references/layouts.md](references/layouts.md).

Let the number be big. On one example deck, headline values measure 25pt of stroke on screen
against a 12pt body, three times the size. A comment in this skill once said "9–10pt, the same
as body text", and tiles drawn to that note read as a coloured table rather than a headline.
Fill says where to look; size says how much it matters. `fit_text` grows text as well as
shrinking it, and a grid spends spare height on its rows.

Say what the colour means. On tiles, `verdict: {hit: "below target", …}` writes it under each
value; on bars, dots and lines, say it in the chart's `note`. Hatching does not say it.

Do not read "more figures" out of `refcheck`'s numbers. "A chart beats a table" is unsupported.
Ask whether the claim is a lookup claim or a shape claim; Assertion-Evidence bans the bulleted
list, not the table ([references/evidence.md](references/evidence.md)).

Redraw a paper figure from its numbers. If the paper prints no numbers, use one panel and
`figure.highlight` ([planning §plots](references/planning.md)).

On impact slides, pause before speaking and let the room read first. On any table, the
unmarked cells are what the marked ones are measured against. Removing the flat rows removes
your own evidence.

### ③ Figures — redraw the paper's charts; keep its photographs

Paper charts and schematics are built for print: multiple panels, small type. Projected, they
cannot be read from the back row, so redraw them. Photographs, screenshots and micrographs
cannot be redrawn. Use them as they are, beside a note on what to look for (`prose_audit` tells
the two apart by measuring the image). Sort the rest:

- Schematics: a diagram of the system, a map of the study site, a timeline. These are drawings
  from constants, so nothing stops you making them.
- Charts of numbers you already have in your tables. A curve is `chart: {kind: lines}`.
- Only these need the raw material: record-level things the paper never printed, and anything
  from a video or a recording.

```bash
python scripts/build_figs.py slides.yaml -o out/figs --sidecar out/figs/values.txt
```

Chart and diagram options:

- `chart: {from: left, kind: heat}` draws a table as a grid, colouring the cells you marked
  `<hit>` / `<safe>` (only those; it has no colour ramp). Use it when where the marks fall is the
  message: marks crowding one corner say "only near the coast" faster than any sentence.
  Magnitudes go in `kind: bars`.
- `kind: bars` writes each bar's value and takes `callout: {at, series, text}`, an arrow onto one
  bar: where a trend turns, or the one condition that departs.
- A `diagram: {kind: strip}` row takes `axis: {ticks: 6 | log | […]}`, a number line beside the
  cells that shows where each cell falls on the line. Rows that differ only in `groups` need a
  `note` each; otherwise the meaning sits in the band widths and nobody counts them.
- A `diagram: {kind: pipeline}` stage takes `inner: ["Step 1", "Step N"]` for what is inside the
  box. Boxes that differ only in their captions cannot show how two systems differ.
- `feed: {label, sub}` boxes what enters a stage; `loop: "…"` draws the return path from `out`.
  A closed loop drawn as a row makes a different claim, and the generator then inflates the
  boxes to fill the page.
- A box with nothing inside is drawn low, as an input or output. A part the talk compares
  should show what is inside it (`inner`, `glyph`); otherwise the comparison has nothing to
  point at.

Replace the table with the chart; do not put both on the slide. `from: left` names where the
numbers come from, not a table you also display. Showing both is the duplication `refcheck`
fails you for. The sidecar is written from the same values, so the figure inherits whatever
`deckcheck` already proved about that table.

- Never type a number by hand. Have the generator recompute it from raw data or parse it out of
  the source, and `assert` so it fails if it cannot find the value.
- Emit what you drew into a sidecar (`sidecar.write`), or the checker cannot see it.
- Type size: draw at no more than 2× the final display width and scale the fonts up to match.
  Drawn at 13 in and placed at 5.6 in, 10pt type becomes 4.3pt. Raising a height limit flips
  the constraint to width and makes the figure bigger; if it will not fit, split it into two
  figures.
- Before replacing a paper figure, list what it was doing and carry the list over one item at a
  time. A cleaner redraw quietly drops things.
- To lower density while adding content, merge. Folding a table into a diagram removed a whole
  table while the information went up.

### ④ Deck — same engine as the source

Where you can, use the same typesetting engine, the same image files and the same symbols as the
source (a LaTeX paper becomes a Beamer deck). There is then no conversion step and no conversion
bugs.

### ⑤ Script

```bash
python scripts/build_script.py slides.yaml -o out/script.md --thumbs out/talk.pdf \
                               --limit 15 --qa 3
```

Per slide: the sentences you will actually say, stage and tone notes, and the running time.
Render each deck page to a thumbnail and put it beside its script, because seeing the slide
brings the words back.

Compute time with `timing.py`. Never estimate by eye (§4).

Pass your slot as `--limit` and it becomes a gate. Without it the running time is a number
printed on a screen that nobody acts on, and that is how a talk runs over. `--qa` is the part of
the slot that belongs to questions, so it comes off the budget.

Put slides you only open if asked behind `backup: true`. They move to the end, lose their page
numbers and drop out of the running time: a talk ends in questions, and a spare slide counted in
the budget makes the budget wrong. Write the question you expect next to the slide that provokes
it with `ask:`. The script collects them all into one list at the back, the only form in which
they get read five minutes before you go on.

### ⑥ PowerPoint (if the venue machine is a risk)

```bash
python scripts/build_pptx.py slides.yaml -o out/talk.pptx
```

Do not convert the PDF to PPTX. Every page becomes one flat image and you cannot fix a typo on
site. Assemble title, body and tables as real text with `python-pptx`.

- Pin a font the venue machine has. PPTX **cannot embed fonts**.
- Speaker notes come from the same `slides.yaml` (`say`, `cue`, `note`). Nothing is retyped, so
  the notes and the script cannot diverge.
- Nothing in the PPTX is written by hand either. Section F of `deckcheck.py` confirms it: the
  PPTX and deck text sets must match both ways.

### ⑦ Check — and then look at it

```bash
python scripts/deckcheck.py deckcheck.yaml --selftest          # is the gate awake?
python scripts/deckcheck.py deckcheck.yaml                     # numbers and wording
python scripts/outcheck.py  slides.yaml --deck out/talk.pdf --pptx out/talk.pptx \
                            --script out/script.md --sidecar out/figs/values.txt
python scripts/fitcheck.py  out/talk.pdf --pptx out/talk.pptx # overflow, overlap, tiny text
python scripts/diffcheck.py out/talk.pdf --source paper/paper.tex --sidecar out/figs/values.txt --script out/script.md
python scripts/refcheck.py  slides.yaml                       # design density
python scripts/prose_audit.py slides.yaml                    # can they follow it
```

Run all seven. Each asks a different question, and each has caught something the others passed.

| Check | The question only it answers |
|---|---|
| `deckcheck --selftest` | Is the gate awake? It plants a deliberate error in sections A–D, F and I of your config; for E, G and H it only checks that the input is not empty. In one config, 12 of 20 banned patterns matched nothing while section C printed `-> 0 hit(s)` |
| `deckcheck` | Do the numbers on screen exist in the source? |
| `outcheck` | Did what you wrote arrive? Reads text back out of the rendered PDF and PPTX. On a deck that passed everything else, it found 38 fragments that never reached the page |
| `fitcheck` | Does it fit? Reads coordinates: past the edge, on top of something else, too small to read from the back. With `figs/textsize.tsv` beside the PDF it also counts text drawn inside figures, which it otherwise cannot see |
| `diffcheck` | What does the source have that you never used, both its numbers and its explanations? Give it the `--sidecar`. Values you leave out on purpose go in `--omit v1,v2`, with the reason in plan.md |
| `refcheck` | Does it look like a talk, or a wall of bullets? |
| `prose_audit` | Can the audience follow it? Screen jargon never said aloud · an unexplained colour code · one word with two values · unexplained blanks · a cast compared across tables the deck never draws · a title naming its contents instead of stating its claim · a figure pasted straight out of the paper |

Give `outcheck` and `diffcheck` the `--sidecar`. Text drawn into a PNG is pixels; without the
sidecar, chart titles read as missing and figure values as unused. False alarms hide real ones,
and they also get features deleted: one wrong fit warning was enough to have a figure dropped.

Point `fitcheck` at the PPTX too. The venue machine runs PowerPoint, and nothing else measures
where things sit there. On one deck both `deckcheck` sections passed while text ran across
pictures on four slides.

Text inside a figure is invisible to `fitcheck` too, and fails **silently**. Labels of 4.4pt
have passed all seven checks. `build_figs` draws each figure at the size it will occupy, fits
every label to its box, and writes `figs/textsize.tsv`, which `fitcheck` picks up beside the
PDF. If you move the PDF, you must pass `--figtext`.

There are two checks because Beamer has two failure modes. Content pushed past the frame is not
placed off-page; it is not drawn at all. See [traps.md](references/traps.md) "Building".

Then compile it and look at the rendered pages. Each of these once passed every check and was
obvious on sight; the first two still need eyes:

- a title with two words silently deleted, compiling with zero errors
- a table overrunning its column and printing on top of the text beside it
- rules drawn through the middle of table rows
- `\centering` leaking past a table and centring the note under it

A checker that prints zero has told you the numbers are right. It has not told you the deck is
any good. Render it, open the images and look: at minimum the title, one table slide and one
figure slide.

Before you accept a deck that passed everything, read [references/looking.md](references/looking.md).
A generated deck and a hand-made deck for the same paper scored within a couple of points on
figures, tables, impact slides and emphasis, and looked nothing alike. That file lists the five
differences, with what to do about each.

### ⑧ Hand it over with the artifacts

When you report, attach the rendered PDF, the spec that produced it and, if you compared against
a reference, the reference pages too. A sentence saying it came out well is not a report: the
reader usually cannot open your files, and "zero errors" has been shown to mean nothing about
whether the output is right.

### ⑨ Put it in front of people

Read [references/audience-panel.md](references/audience-panel.md) and follow it. **Skipping it
makes the eight steps above pointless**: the code checks whether you are wrong, not whether you
are understood.

On a deck where all seven checks passed and the timing fitted, every reader stalled in the same
places, and no check saw any of them. Each of those is now a check. Treat every panel finding as
a check you have not written yet, and ask what would have caught it. The answer has never been
"nothing"; twice it was "ask the author to declare what the machine cannot see". Writing "only a
human can catch this" means you stopped looking. In your handover, say whether you ran the
panel: "all checks green" and "the readers got through it" are different claims.

## 3. What the checker looks at

| § | What |
|---|---|
| A | Every number on screen actually exists in the source |
| B | Key claims appear in both derivative and source |
| C | Banned wording: hype, plus phrasings this project decided against |
| D | The spoken script's numbers and wording |
| E | Reverse: values in the source the derivative never uses |
| F | PPTX ↔ deck two-way set difference, banned wording, fonts |
| G | PPTX structure: slide count vs. page-number denominator, gaps, aspect ratio |
| H | Words the deck uses 3+ times that the paper never uses (`coined_ok` exempts a disclosed rewording) |
| I | Text inside quotation marks is verbatim in the manuscript |

What the other checkers look at, because no single one of them is the gate:

| Tool | The question it alone answers |
|---|---|
| `deckcheck --selftest` | Can sections A–D, F and I fail on this config? (E, G, H: is their input non-empty?) |
| `outcheck` | Did every fragment of the spec arrive in the rendered output? |
| `diffcheck --source` | What does the paper have that the deck never used? |
| `refcheck` | Is this a talk or a wall of bullets? |

Section E is the rare one. The other sections find what is wrong; E finds what is missing,
and derivatives fail by quiet omission. Narrow its scope or it produces noise: point
`coverage_pattern` at table cells. Section C comes next. Wording you retired will come back (32
instances did), so add each to `ban_file` with the reason.

## 4. Timing

Estimates went wrong three times in the same place. Eyeballing it was 2 min 30 s out; counting
`-12.3` as one word, 26 s; counting an acronym as one word, 5 min 59 s. `timing.spoken_words()`
handles numbers. It cannot handle acronyms, because how they are read differs by field (`NASA` is
a word, `SoC` is three letters). Measure your own with the carrier sentence differential in
`timing.py`, never by feel, and put them in `meta.acronyms: {NASA: 1, SoC: 3}`, in the spec, not
the script. Do not keep a separate calculator: one written around an acronym table that lived
inside a script understated the time by 15 s. Acronym values go in `meta.acronyms`.

The 135 wpm default assumes a native speaker reading aloud; a non-native speaker enunciating
numbers runs 115–125. One stopwatch reading is more accurate than any model here.

## 5. Traps

Read [references/traps.md](references/traps.md) when a check behaves oddly, when a build succeeds
but the output is wrong, or before changing any checker. The four that recur most:

- When a checker prints a pile of failures, suspect the checker before the document. Look at the
  actual strings it printed.
- A checker printing zero means one of two things, and you cannot tell which: the deck is clean,
  or the check is dead. `deckcheck.py <cfg> --selftest` decides it.
- Check the rendered output, not the source you generated. Everything that reads the `.tex`
  shares one blind spot: whatever the renderer silently dropped.
- Never write a baseline value you did not measure. A fabricated reference number turns into
  advice, and the advice is wrong.

## 6. What transfers and what doesn't

| Transfers (this skill) | Per-project, every time |
|---|---|
| Pipeline order and dependency chain | The claim list and its regexes |
| Sidecar · two-way check · reverse coverage | The banned-wording list |
| Timing model | Figure generators (tied to your raw data) |
| The three prose measurements | Acronym word-equivalents (measure them) |
| Audience panel protocol | |

Everything on the right goes in `deckcheck.yaml` and `ban_file`. Do not edit the scripts.

## 7. Why the thresholds are what they are

The text-size floor, the 4.5:1 contrast bar and the 5% edge margin are borrowed from standards,
not invented here. A colour-blind audience gets a second channel with `meta.colorblind: true`.
The "one claim per slide" advice matches a named method with real but mixed evidence. Read
[references/evidence.md](references/evidence.md) before changing any threshold, or when you want
to know which numbers in this skill are a standard and which are one deck's habit.

Two consequences to keep in mind without opening it. Points do not travel, ratios do: 24pt is
4.4% of slide height in PowerPoint and 8.8% in Beamer. And the dark impact slides are a
deliberate exception: three or four, as punctuation, never for body text.

## Dependencies

`pyyaml` (required) · `python-pptx` (PowerPoint) · `pymupdf` (any PDF read or written) ·
`matplotlib` (`build_figs`) · `pillow` · `pdflatex` with `beamer`, `metropolis`, `booktabs`,
`adjustbox`, `lmodern` and `tikz`. Full list: `requirements.txt` and INSTALL.md.

Install only what you need: every script names the missing package when it cannot import it.
Script paths in this file are relative to the skill's own directory, and each is run through its
interpreter (`python scripts/deckcheck.py ...`), never by bare path.
