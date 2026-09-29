# Traps

## Contents

- [Checkers](#checkers)
- [Building](#building)
- [Colour and legibility](#colour-and-legibility)
- [Measurement](#measurement)
- [Multiple outputs](#multiple-outputs)
- [Environment (Windows)](#environment-windows)
- [A figure's own text is not checked unless you make it checkable](#a-figures-own-text-is-not-checked-unless-you-make-it-checkable)
- [A brace group at the start of a frame eats what is inside it](#a-brace-group-at-the-start-of-a-frame-eats-what-is-inside-it)
- [The PowerPoint's geometry is not checked by anything else](#the-powerpoints-geometry-is-not-checked-by-anything-else)
- [A paper that exists only as a PDF](#a-paper-that-exists-only-as-a-pdf)

Each of these cost real time. Read this when a check behaves oddly, when a build succeeds
but the output is wrong, or before changing any checker.

---

## Checkers

- When a checker prints a pile of failures, suspect the checker before the document.
  Look at the actual strings it printed; a pile of failures has more than once been a
  checker bug.
- A checker that prints zero has told you one of two things, and you cannot tell which:
  the document is clean, or the check is dead. `deckcheck.py <cfg> --selftest` decides it.
  It plants a deliberate error in sections A–D, F and I of your config and reports any
  section that fails to notice. For E, G and H it only checks that the input is not empty.
- Never hardcode a reference value. Read slide count and page-number denominators from the
  thing being checked. If you hardcode one, then on the day it changes the checker prints a
  warning it does not add to the total, which is a silent pass.
- Never identify something by what it looks like when the producer could label it. Page
  numbers were once found by matching `n/m` anywhere on the slide. A footnote reading
  `ratio 3/12` became "slide 3 of 12", and the section reported failures against a deck
  that was fine. The builder now names the page-number box, and the checker reads that box.
- Keep the banned list in one file. Two copies will diverge.
- Do not make the user write a regex where a word will do. A regex can be valid and still
  match nothing, and nothing in the output distinguishes that from a clean document. In one
  config 12 of 20 patterns were dead: the reason had been written on the same line and had
  become part of the pattern. The banned list now takes plain words, and `re:` marks a
  genuine pattern. This removes the failure mode instead of detecting it, which is the only
  kind of fix that holds.
- Never use a lazy regex on nested braces. `\note{...$x{=}2$...}` stops at the first `}`,
  and the rest of the note gets counted as body text.
- A permissive default is a silent failure waiting to happen. A claim with no `source:`
  pattern matches the bare digits, and if the paper says `12.3` in four places, the check
  passes on the wrong one. When a shortcut is safe only sometimes, make it fail the rest
  of the time instead of documenting the caveat.
- Fixing a checker puts holes in it. After every change, feed it a deliberately broken
  input and confirm it fails.
- Check the rendered output, not the source you generated. Every check that reads the
  `.tex` shares one blind spot: whatever the renderer silently dropped. `outcheck.py` reads
  text back out of the PDF and PPTX; `fitcheck.py` reads coordinates out of the PDF.
- False alarms hide real ones. Superscripts made `p<10⁻⁶` reduce differently on the two
  sides, so healthy fragments were reported as missing; footnote daggers were reported as
  "text too small". Both were fixed as bugs, not tolerated as noise.

---

## Building

- Emitting LaTeX is not the same as producing a deck. Compile it. A generator can write
  plausible `.tex` that `pdflatex` refuses.
- A missing figure stops the whole document. Emit a visible placeholder and warn, rather
  than a reference that halts the run.
- Bounding one dimension does not bound the box. An image grid given only a width stacks
  past the bottom of the slide; pdflatex says nothing and the last row is not there. Bound
  the height too, and reserve the share the surrounding content needs.
- Beamer drops overflow silently. Content pushed past the frame is not placed off-page
  where a coordinate check would find it; it is not drawn at all. That is why `outcheck`
  (did the text arrive?) and `fitcheck` (is it inside the frame?) are two different checks,
  and you need both.
- Table- or figure-only frames sit at the top by default, and the bottom third reads as
  empty when projected. Centre them.
- In a `\begin{frame}[standout]` whose next line starts with `{`, that line is taken as the
  frame subtitle, which metropolis does not draw. There are zero errors and the line
  vanishes.
- Do not rewrite inside `$...$`. A minus-sign pass turned `$p<10^{-6}$` into
  `$p<10^{\textminus 6}$`, which compiles with the wrong exponent. Hand-written maths is the
  author's.
- Money and significance stars are text. Write `$30,230` and `0.128**` as they are. A `$`
  before a number with thousands separators, or before a number and a word, is a dollar
  sign in every output, and stars right after a number are never bold markup.
  `$5 \times 10$` and `$0.5$` stay maths.
- metropolis's title page reports `Overfull \vbox (13.8pt)` whatever you put in it. This
  is upstream and cosmetic, so leave it, but check any other overfull.
- Default arguments bind early. `def f(font=FONT)` captures the value at definition time,
  so changing the module global later has no effect on that function. Resolve the value
  inside the function.

---

## Colour and legibility

- Never let colour carry meaning alone. The `<hit>`/`<safe>` pair is this skill's
  reading device, and it was once red against green only. Simulated at deuteranopia the two
  fall to the same olive: RGB distance goes from 181 to 41.5, 23% of what it was;
  protanopia gives 31%, the dark-slide variants 32%. A caption reading "Red = below target"
  then points at a colour that is not on the screen for roughly 8% of men in the room. The
  builders now add a second channel (underline in deck and PPTX, hatching in generated
  heatmaps).
- Measure text size relative to the slide, not in points. 5pt means nothing until you know
  the slide is 255pt tall, so `fitcheck.py` reports height as a percentage. On one
  hand-made example deck the smallest text is 2.75% and nothing real sits below it. That is
  a measurement, not the check. `fitcheck` fails text below 0.7× the deck's median size
  (never below 0.6× the body size). It counts only three things as notes: text on backup
  slides, text inside figures the builder drew at its own floor, and small print inside a
  pasted paper figure that carries a highlight. A backup table printed at 5pt therefore
  passes with a note; the same table on a main slide fails.
- PowerPoint cannot embed fonts. Pin one the venue machine has. The default was once
  Windows-only (`Segoe UI`) in a deliverable meant for the venue machine; on a Mac it is
  substituted silently, and the column-width warnings no longer hold.
- PowerPoint does not report a table row's rendered height, so a wrapped cell cannot be
  corrected afterwards. Estimate the text width up front and warn.

---

## Measurement

- The wrong denominator gives false positives. Measure title/opening overlap against the
  opening sentence, not the title: a long explanatory paragraph will cover a title's words
  by accident.
- Tightening one thing loosens another. If you strip discourse markers, your guidance goes
  with them and titles and opening lines converge on the same sentence. Measure both
  together.
- Never write a baseline value you did not measure. Two numbers in the design baseline
  were once typed in by hand (2.6 bullets of 11 words); the example deck it was measured on
  actually ran 1.0 of 18.8. That invented pair became written guidance telling a fresh
  agent to cut every argument into short labels, the shape that deck avoids. A fabricated
  reference value does not stay a number; it becomes advice.

---

## Multiple outputs

- One spec, three outputs: never hand-edit a generated file. This is why `slides.yaml`
  exists. Multi-turn editing of a rendered deck degrades measurably and monotonically with
  each turn; regenerating from a single source does not.
- A derivative overclaims more easily than the source. For every flat assertion you write,
  find the sentence it came from. Read the sentence before it too, because that is where
  the scope qualifier usually is. Carry the subject across as well.
- Diff the limitations section by item count. Summarizing drops whole items.
- Automatic marks and hand-written notes have to check each other. A "can be cut" mark
  once landed on the one paragraph annotated "do not cut."
- When you add a feature to one builder, add it to the other in the same pass. Six spec
  features once existed in the deck and not in the PPTX, and nothing reported it until a
  check read both outputs back.

---

## Environment (Windows)

- Heredocs strip one layer of backslashes and read stdin in the locale encoding. Write
  patches containing backslashes or non-ASCII to a file and run that file.
- Double quotes in `slides.yaml` consume LaTeX. In `"0.19\textheight"` the `\t` is a tab;
  `\f`, `\b`, `\v`, `\a`, `\r` and `\n` go the same way. Put any value that holds a
  backslash in single quotes (`'0.19\textheight'`). `deckspec.load` stops and names the
  key when it finds one, so the deck never shows `extheight`.
- The replacement string of `re.sub` also interprets `\t`. Use a lambda replacement.
- Wrap stderr as well as stdout in UTF-8. Otherwise the one line that tells you what went
  wrong is the one line you cannot read.

## A figure's own text is not checked unless you make it checkable

Every checker in this skill reads text. Text drawn into a PNG is pixels, so a figure can be
unreadable and pass everything.

In one generated deck the schematic labels came out at 4.4pt (body is 10pt), grid column
headers overprinted into `MondayTuesdayWednesday`, and a chart title was clipped at both
ends. Seven checks reported zero.

The cause was not the drawing code. The figure was **drawn at one size and placed at
another**. `build_figs` drew at 7.2in wide; `build_deck` squeezed it into 5.0–5.4cm. The
measured scale was 0.337 in a two-column pane and 0.483 full width. A declared
`fontsize=13` landed on screen at 4.4–6.3pt. Nothing in the source says "4.4pt", so nothing
could flag it.

Three things prevent it now:

- `deckspec.slot()` owns the geometry, and both builders ask it. If one side hard-codes a
  height again, the scaling comes back, and with it a wrong font size.
- Labels are measured against their own box and wrapped, then shrunk, then reported. The
  `wrap=True` option of `matplotlib` wraps to the figure width, not the box, so it does
  nothing for a narrow box.
- `build_figs` writes `figs/textsize.tsv`; `fitcheck` reads it and counts that text on the
  same scale as everything else. Matching is by image fingerprint, not by size. Two figures
  drawn for the same slot have identical pixel dimensions, and matching on size put one
  figure's warning on two other slides.

## A brace group at the start of a frame eats what is inside it

One deck's opening evidence slide came out completely blank: no images, no row or column
labels, no LaTeX error, nothing in the log. The `.tex` was correct.

The cause is narrow: if the first thing in a Beamer frame body is `{...}`, the group's
content is swallowed. An image grid triggers it only when the slide also has bullets and no
`lead`. A `lead` puts text before the group, and with no bullets `\vfill` sits there
instead.

The `standout` path already carried `\vspace{0pt}%` with the comment *"without it the next
`{..}` is eaten as the frame title"*, but the guard existed on that one path only.
`build_deck.guard_group()` now inserts it on every return, so a layout added later is
protected without anyone remembering.

The general lesson: a fix applied where the bug was found, rather than where the bug
lives, **comes back**. The same shape appeared three times: `\centering` leaking, typeset
arguments eating content, and this.

## The PowerPoint's geometry is not checked by anything else

`deckcheck` section F compares the text sets of deck and pptx; section G compares slide
counts and page numbers. Neither looks at where anything sits. On four slides of a
generated deck, bullets printed straight across the figure, with measured overlaps of 0.54
to 2.58 inches, and every check passed.

The cause was this file's own rule, unfixed on one side. `build_pptx` called
`add_picture(..., width=...)` with no height and placed what followed at a fixed offset.
Pictures are now bound in both axes, and following content starts at the picture's real
bottom; `fitcheck --pptx` measures it.

## A paper that exists only as a PDF

Some papers have no source you can read: arXiv sometimes holds nothing but a
`\includepdf` wrapper. `scripts/pdf_paper.py` turns the PDF into a `.md` named after it plus
`figs/fig_N.png`. Every checker also accepts the `.pdf` directly and converts it the same
way. Still, point `source:` at the `.md` so that you can read what they read.

- Headings are guessed from type: a line counts as a heading if it is larger than the body
  text, bold, or numbered in capitals. Skim `paper.md` once. A missed heading merges two
  sections into one slide in the skeleton.
- Tables arrive as running text. The skeleton has `table` slides only for Markdown tables,
  so copy the rows you need off the PDF page by hand. deckcheck still checks every value
  against `paper.md`.
- Figures are cut at their captions. A crop takes the drawings and images between the
  caption and the previous caption in the same column. It also takes labels set beside or
  rotated against the figure. Text inside a figure (axis ticks, legends) is kept out of
  `paper.md`, so tick values do not pose as results. Open every crop. The tool names the
  figures it could not cut, usually code listings set in the body font. Cut those by hand
  or leave them out, and say so in `plan.md`.
- The first page's running head is kept, because it is often the only place the venue and
  year appear; the repeats on later pages are dropped.
- A crop is a picture, not data. Redraw a plot only when the paper prints its numbers.
  Otherwise paste the crop and point at what matters with `figure.highlight`
  (planning §plots).
