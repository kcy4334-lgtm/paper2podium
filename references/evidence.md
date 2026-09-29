# What has evidence behind it, and what does not

## Contents

- [Thresholds borrowed from standards](#thresholds-borrowed-from-standards)
- [Points do not travel; ratios do](#points-do-not-travel-ratios-do)
- [One claim per slide with its evidence is a named method](#one-claim-per-slide-with-its-evidence-is-a-named-method)
- [Advice this skill deliberately does not give](#advice-this-skill-deliberately-does-not-give)
- [The dark impact slides here are a deliberate exception](#the-dark-impact-slides-here-are-a-deliberate-exception)
- [The literature does not say charts beat tables](#the-literature-does-not-say-charts-beat-tables)
- [How big must text be, really](#how-big-must-text-be-really)
- [Claims that do not exist in the literature](#claims-that-do-not-exist-in-the-literature)
- [What the checks could not see until recently](#what-the-checks-could-not-see-until-recently)
- [Are the deck's words the paper's words? (section H)](#are-the-decks-words-the-papers-words-section-h)

Read this when you want to know why a threshold is what it is, or before changing one.
Most presentation advice is folklore; these are the pieces that are not.

---
## Thresholds borrowed from standards

| Check | Basis |
|---|---|
| Text size floor | ANSI/AVIXA V202.01 (DISCAS), Basic Decision Making: element height ≥ viewer distance ÷ 200. Divided through by image height, that is `viewing ratio ÷ 2` as a percentage: 3.0% cap height for a back row 6 image-heights away. `fitcheck` reports the reach your smallest text actually achieves |
| Contrast 4.5:1 | WCAG 2.2 SC 1.4.3 (AA). 3:1 applies only to large text, and the 18pt boundary was inherited from print and does not carry over to a scalable canvas, so this skill applies 4.5:1 to everything |
| Colour is never the only cue | WCAG 2.2 SC 1.4.1. It fails only when colour is the sole cue, which is why the builders add a second channel rather than abandoning colour |
| Edge margin 5% | EBU R 95 graphics safe area for 16:9. It applies because talks get recorded, streamed, and projected through overscan and keystone correction |

## Points do not travel; ratios do

The same 24pt is 4.4% of slide height in PowerPoint, 5.9% in Google Slides and 8.8% in
Beamer. Any check written in points measures the authoring tool, not the room. `fitcheck`
measures percentage of slide height throughout.

## One claim per slide with its evidence is a named method

The method is Michael Alley's *Assertion-Evidence*: a full-sentence assertion as the
headline, supported by visual evidence rather than a bullet list. Its operational numbers
(assertion ≤ 2 lines, ~21 words per slide against ~41 for bullets) are close to what one
hand-made example deck measured: about one bullet a slide, of 18.8 words. The evidence is
real but mixed. The strongest study reports large effects on comprehension and delayed
recall and no effect on immediate multiple-choice, and its control decks have been
criticised as straw men. Treat it as a well-supported default, not a law.

## Advice this skill deliberately does not give

The following are left out on purpose, because the evidence contradicts them or there is
none:

- *"6 lines by 6 words"*: no primary source.
- *"attention drops after 10–15 minutes"*: the cited sources turn out not to be studies.
- *"keep slides simple"* as a rule about text volume: unsupported by systematic review.
- reveal-one-bullet-at-a-time: experts disagree in both directions.

## The dark impact slides here are a deliberate exception

Several studies find dark text on light easier to read, and this skill uses dark slides
anyway: three or four times, as punctuation, for a number that is on screen for seconds.
That is a knowing design choice against the general finding. Do not extend it to body
slides.

---

---

## The literature does not say charts beat tables

This skill used to push toward figures on the strength of a measured gap against one
hand-made deck. That gap is real, but the literature does not say that a chart is better
than a table. The correction matters because it changes what `refcheck`'s numbers mean.

| Finding | Source |
|---|---|
| "Tables usually outperform graphics in reporting on small data sets of 20 numbers or less." | Tufte, *The Visual Display of Quantitative Information* |
| "empirical studies that compared task performance with the two display types frequently revealed either an advantage of tables over graphs or no differences" | Meyer, Shamo & Gopher 1999, *Human Factors* 41(4) 570–587, [doi:10.1518/001872099779656707](https://doi.org/10.1518/001872099779656707) |
| Graphs suit spatial information, tables suit symbolic; performance improves when the representation matches the task | Vessey 1991, *Decision Sciences* 22(2), [doi:10.1111/j.1540-5915.1991.tb00344.x](https://doi.org/10.1111/j.1540-5915.1991.tb00344.x); Vessey & Galletta 1991, N=128 |
| The decision procedure: lookup or precise → table; shape, trend, exception, or a comparison over more than a few values → chart; both → show both | Few, *Effectively Communicating Numbers* (Perceptual Edge 2005) |
| Assertion-Evidence permits tables: evidence may be "images, graphs, or visual arrangements of text (such as a table or text blocks connected by arrows)". What it bans is the bulleted list | Alley & Neeley 2005, *Technical Communication* 52(4), Table 1 |

So the question on a results slide is whether the claim is a lookup claim or a shape
claim, not whether the slide holds a chart. A 3×5 grid of fifteen numbers is under Tufte's
twenty, and a table is defensible. What makes the tile grid better there is not that it is
a picture but that the claim (*every row rises from left to right except the last*) is a
shape claim.

The live-talk consideration is separate from both: "Using a table in a live presentation
is rarely a good idea. As your audience reads it, you lose their ears" (Knaflic,
*Storytelling with Data*, "Tables in live presentations"). Tufte's own remedy for a dense
table is a paper handout, not a slide.

**Never paste a figure out of the paper.** "Never paste PDF of a table from a paper to
slides. Reformat the table to be more readable" (Michael Ernst, UW). "You should abandon
the practice of extracting a figure from your article to be put, as is, in your oral
presentation" (Rougier, Droettboom & Bourne 2014, *PLoS Comput Biol* 10(9):e1003833). For
projection, make lines thicker, points and text bigger, and avoid vertical text; a
multipanel figure becomes one panel per slide (Naegle 2021, Rule 6).

The one exception is a result the paper prints only as a plot. Values read off a curve by
eye have no source, so redrawing would put invented numbers on screen. Paste one panel,
point at the part the slide is about with `figure.highlight`, and say in the caption that
it is the paper's figure (planning §plots). `prose_audit` names a pasted figure that has
no highlight.

Closely grouped values belong on a dot plot, not a bar chart. Ablation results cluster
near the baseline. There a zero-baseline bar spends almost the whole canvas on nothing,
and a truncated bar is, in Robbins' words, "a visual lie". A dot plot "is judged by
position along the horizontal axis" and "does not require a zero baseline" (Robbins,
*Dot Plots: A Useful Alternative to Bar Charts*, Perceptual Edge 2006; Doumont says the
same for "closely grouped data").

## How big must text be, really

The ergonomics literature is blunter than any presentation guide. Character height should
subtend 16–22 minutes of arc (Weston; Sauter; Gilmore; Anshel; Grandjean: five
independent texts). Carried through to a slide with cap height ≈ 0.70 em:

> minimum point size ≈ 0.2244 × θ × (D/H),  θ in arcminutes

| viewing ratio D/H | ≥16′ floor | ≥20′ preferred |
|---|---|---|
| 4 | 14.4 pt | 18.0 pt |
| 6 | 21.5 pt | 26.9 pt |
| 8 | 28.7 pt | 35.9 pt |

**This deck's body text is 10 pt.** metropolis at `aspectratio=169` sets the body at 10 pt
on a 255 pt-tall page, and the hand-made example deck this skill was measured against
runs the same. That is well under the ergonomic floor for any room deeper than about two
image-heights. It is a deck written for a laptop and a small room, and `fitcheck` says so
when it prints the reach the smallest text actually achieves. `build_figs` aims figure
text at 8 pt, warns below 7 pt and never goes below 6.5 pt (`deckspec.FIG_FLOOR_PT`).
None of these is a legibility standard. 8 pt is the smallest size the surrounding deck
already uses (`\footnotesize`), and the job of all three is to stop figure text from being
smaller than the slide it sits on. Raising the real floor means changing the theme's base
size, which is a decision about the room.

## Claims that do not exist in the literature

These are listed so that nobody adds them back believing they are standard:

- No row/column threshold at which a table "becomes" a heatmap.
- No panel count for small multiples. Tufte gives none.
- No visual-to-text ratio in Assertion-Evidence.
- No word or character limit for an A-E headline. The published rule is geometric: two
  lines at 28 pt. (Counting the headlines Alley ships in his own templates gives 13–16
  words / 73–101 characters, but that is a measurement of his examples, not a rule.)
- No "a figure should occupy X% of a slide" rule in Tufte, Doumont, Few, Alley, Naegle or
  Rougier. The nearest published geometry is Alley's official template, whose headline
  band is 9.8% of slide height, leaving ~90% for evidence.
- No ML conference (ICML/NeurIPS/CVPR) publishes guidance on slide content, font size,
  tables, colour, or backup slides. They publish a time budget and nothing else.
- "6 elements per slide" traces to a TEDx talk, not a study. The real working-memory
  anchor is ~4 chunks (Cowan 2001, *BBS* 24(1):87–114); Miller's 7±2 is superseded.

One caution about the A-E literature itself: at least one indexed open-access paper
attributes findings to Garner & Alley and to Alzayed & Alzamel that those papers do not
contain, in one case the opposite of what was found. Check quotes against the PDFs.

## What the checks could not see until recently

Before these two, every check in this skill measured one of two things: whether the numbers are right,
or what shape the deck has. Neither asks whether the deck carried what the paper means.
That gap let a deck name a concept, never explain it, and pass everything.

Two checks close it. Both live in `diffcheck`, because they ask the same question as the
rest of that tool: what does the source have that the deck does not?

| Check | Why it is drawn this way |
|---|---|
| Reasoning the deck left behind | A paper's explanatory sentences usually contain no numbers (*"without X, Y overflows"*, *"therefore Z does not follow"*), so the existing sentence check, which required a number, never saw them. Same overlap measure, wider gate |
| Names the paper gave that the deck does not use | Selecting by frequency does not work: the top of any paper's word list is *data*, *compared*, *evaluated*. Selecting by explicit naming (*called X*, *we call X*, *known as X*, *X denotes Y*) is exact. On one real paper it returned two terms and nothing else, and both were real substitutions the author had not noticed |

Neither check fails a build. They print what was skipped, because a talk legitimately
drops most of a paper. The dropping should be a decision, and before these checks existed
there was nothing to decide against.

Neither is field-specific. They key on how academic prose introduces and justifies
things, not on what a given paper is about.


## Are the deck's words the paper's words? (section H)

**What it measures.** Words the deck uses three times or more that the source never uses.

**Why three.** Once or twice may be a linking word. A word used three times or more is
part of the deck's working vocabulary, and when that differs from the paper's, the talk
and the paper drift apart.

**Basis.** This is not from the literature. It carries a manuscript convention over to the
deck: in a manuscript, coinages absent from the references are replaced with the field's
words. The derivative is held to the same standard.

**What is removed before counting.** Command names, environment names, colour names,
figure file names, comments, and the exponent part of p-values. Without that filtering,
14 of 19 hits were `frame`, `itemize`, `textcolor`, a figure's file name and the `e-05`
of a p-value. If a checker's first line of output is noise, readers stop before the
second.

**Spelling differences are not different words.** `per-bed` and `per bed`, `irrigate` and
`irrigated` count as the same (hyphens dropped, a rough stem, and two neighbouring source
words joined). Otherwise the list fills with spelling variants and the real coinages are
lost among them.

**The way out.** If it is a deliberate plain-language word, list it under `coined_ok:`.
That does not delete it; it declares it, so the next reader knows the word was chosen.
