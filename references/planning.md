# Planning the slides from the paper's argument

Read this before you fill any slide (SKILL step ①). The scaffold gives one slide per
section. A good talk keeps the paper's section order, but a section becomes as many
slides as its argument needs: sometimes none, often two or three. This file says how to
decide that from the paper alone.

## Contents
§voice — The voice: a talk, not the paper in slides
- Arcs: the order comes from the paper
- Showing a result — §case one case · §table a results table · §plots a result only in
  plots · §leaderboard a leaderboard · §spread the spread across conditions · §shapes a
  theorem, one event, nothing moves, a fitted law
- Defending a result — §objection the objection · §pair the minimal pair · §part-whole the
  part and the whole · §second-subject a second subject · §two-subjects one grid, two
  subjects
- Showing what the result is about — §object the object · §insides the objects side by
  side · §structure a structure that is not a row · §matrix a matrix in tiles · §factors
  one drawing per factor
- Setting up the question — §question the assumption · §prior prior work · §turn the turn ·
  §answer the answer that changes
- Closing — §closing explanations, rules, limits, the last sentence
§title-page — The title page
§plan — Write the plan down

Each named item below is a signal to look for in the paper. It does not stand for a
position in a sequence. The items are grouped by the kind of slide they make (showing a
result, defending it, showing what it is about, setting up the question, closing), not by
when they come. Their names are fixed labels that the tools cite ("planning §plots"); they
say nothing about order. The order of the slides comes from the paper's own argument: what
it claims, what it must show before the claim is believable, and what the reader will
doubt on the way. Most talks use a handful of these items, and none uses all of them.
"Arcs" below shows how different kinds of paper order them.

If the paper does not show the signal, **do not make that slide**. A paper with four
results sections gets four results groups. A paper with no opposing assumption gets no
opening question.

The examples use invented topics (a bakery, bus routes, a clinic, a library, weather
stations). None of them is a template to copy word for word.

---

## §voice — The voice: a talk, not the paper in slides

The plan below decides which slides exist. This section decides how they sound. You need
both: a deck can have the right slides in the right order and still be the paper read
aloud.

- The title is a line the presenter says to the room, not the paper's sentence and not a
  label. The paper writes *"Doubling the proofing time raised loaf volume by 27.1%, and
  nearly all of that gain came in the first hour."* The presenter says *"The first hour
  does almost all the work."* The paper sentence moves to `lead` or `say`.
  - Kinds of spoken line: lead into a story (*"Here is the bus that never came"*), point
    (*"Look at the last bar"*), ask (*"What happens on a holiday?"*), set the stage
    (*"The bench we used"*, *"Three things we never tested"*), turn (*"Then the queue
    gets longer, not shorter"*).
  - Keep it to one line on the slide. Two beats are fine when they are spoken as two
    (*"A year of readings. Watch the coast."*).
  - `prose_audit` §0a lists titles that repeat five or more consecutive words of the
    paper. On one example deck, titles repeated four at most.
- Every slide carries a delivery note (`cue`): where to point first, whether to ask and
  wait, how long. `say` is what the presenter says; `cue` is what the presenter does.
  Without a cue the presenter reads the script.
- The screen holds one thing to look at. Exact values, definitions, p-values and the
  conditions of a result go to `say`, a backup slide, or a fine note under the figure.
- Check every slide: is this what the presenter says and shows to the room, or a
  paragraph of the paper moved onto a slide? If it is the second, rewrite it before
  building.

## Arcs: the order comes from the paper

Before choosing slides, write the paper's argument as a chain of three to six links: the
claim, and what the audience must accept before it. Each link is one or more slides; the
items below say what a link looks like. An arc may move a link ahead of where the paper
puts it (a result before the setup). Keep the paper's order inside each link, and note
the move in `plan.md`. Some common shapes, as a starting point only:

- **A controlled comparison or ablation, result first.** The paper changes some settings
  on purpose, holds the rest fixed, and measures what moves. Open on the headline result,
  drawn so its shape states the claim (§table). Then show how it was measured: what was
  compared and what was held fixed (§insides, with the definitions in `fine`). Then the
  doubt the audience is forming, and the check that answers it (§objection). Then what the
  result does not cover (§closing, limits), and the last sentence. A concept gets a slide
  only when the headline cannot be read without it, and then just before the headline.
- **A controlled comparison, factor by factor.** Use this when the paper varies several
  factors and reports each one's effect in its own paragraph. For each factor in turn:
  first what it is (one drawing, §factors), then what it does (§table), then where the
  paper hedges it (§objection, or the sentence that limits it). Then the synthesis: which
  factor matters most, or what happens when they act together (§part-whole). Then rules
  and limits. Each factor is a run of two or three slides, so the audience never carries a
  definition for ten slides before seeing what it does.
- **A theory paper.** First the object's defining formula (§shapes). Then the assumption
  readers usually make, if the paper argues against it (§question). Then each theorem,
  stated as *what is assumed* followed by *what follows*, and why it holds, in words. Then
  one worked example (§case). Then what the theorem does not cover (limits), and the last
  sentence. Result tables and minimal pairs rarely appear.
- **A single-observation paper.** First the observation (§case). Then each alternative
  explanation, one slide each, as the audience's objection (§objection). Then how often
  chance does this. Then the value with its uncertainty, and then what it implies. Prior
  work often comes late, as "has anyone seen this before?".
- **A benchmark or leaderboard paper.** First what the task is and how it is scored
  (§object, with the task as the object). Then what earlier benchmarks cover (§prior).
  Then the ranking on one metric (§leaderboard), and then where the ranking changes, if it
  does (§spread). Then a few failure cases (§case, placed late), and then the limits of the
  benchmark itself.
- **A dataset paper.** First how the data was collected, as a `pipeline` of collection
  steps (§object). Then what existing datasets lack (§prior). Then what is in it, as charts
  of its composition, and then one example record (§case). Then a short results slide
  (§leaderboard), and then known gaps and biases. The opening question (§question) seldom
  fits.
- **A fitted-law paper.** First the quantity and the range it was measured over. Then the
  plot with the law on it (§shapes), and then what the exponent means, in one sentence.
  Then how well the fit holds, as the objection (§objection). Then where it may stop
  holding (the paper's hedge), and then the rule to take away.
- **A qualitative or interview study.** First who took part and how they were asked
  (§insides, no numbers needed). Then each theme on its own slide, with one quote as its
  case (§case). Then where participants disagreed, then what it implies, then the limits
  of the sample. A table of themes by group can stand in for §prior's dimension table.
  Tiles and minimal pairs rarely fit.
- **A position or argument paper** (no experiments of its own). First the standard it
  argues for, often a question the paper itself asks (§question). Then each pattern it
  criticises, one run of slides each: the pattern, then one of the paper's own examples
  (§case), then what it costs the reader, then what would be better. Then the causes, said
  as the paper says them; they are usually a guess, so keep its hedge. Then the remedies,
  split by who acts, and then the objection the paper answers (§objection). Then earlier
  times the same complaint was made, if the paper gives them, and then the last sentence.
  With no figures in the paper, the slides still need something to look at: the quoted
  example, the two versions side by side, the chain of causes as a `flow`. Do not turn
  "appears to be growing" into a trend nobody measured.

A paper that does not fit any of these still has a chain. Find it; do not force a shape.
Two papers of the same kind can still need different arcs, because the chain is read off
what this paper claims and what its reader will doubt.

---

## Showing a result

### §case — One concrete case.
- **Signal:** the paper shows a single example where the assumption fails (a sample output, a
  record, a photograph, a before/after).
- **Slide:** the paper's figure as it is (photographs are kept; see SKILL ③), with what to
  look at in the order the eye should move. Put that beside it in `columns`, or as a
  `lead` and one bullet under it. Example: a scanned receipt and the text a reading
  program made of it: what was printed, what came out, the one total it misread. Where
  the figure shows outcomes, colour the outcome, not the setting: `<hit>` for what fails,
  `<safe>` for what succeeds.
  - Put on the slide what the audience needs to read this case, and nothing the paper
    does not say. A label in the figure they have not met yet gets its word of
    explanation here. How typical the case is appears only if the paper reports it.
- **Common failure:** cutting the figure into a grid of small crops, which loses the labels
  and outcome marks it already has.

### §table — Each result: the whole table, and what in it carries the claim
- **Signal:** a results table. First ask what shape the claim has.
- When the claim is a trend (waiting time grows with every extra hour the clinic stays
  open), every cell is the finding. Draw the whole row or column as a chart
  (`kind: bars` or `lines`), not two cells picked from it. The table goes to backup, or
  stays beside the chart only for what the chart does not show.
- When a few cells stand out (the paper tests them, or singles them out in the text), show
  them inside the whole, because the unmarked cells are what the marked ones are measured
  against.
  - Show the full table, or a chart of all of it, with the few cells marked and a `fine`
    saying what the marks mean. Mark the cells the paper judges (`<hit>` for worse,
    `<safe>` for the better result it names) and leave the rest unmarked. A green cell
    says "shown to be better", and a difference nobody tested does not show that. With no
    test, the verdict says the direction ("slower than last year's timetable"), not
    "significant".
  - When the table is too large to read from the back, add a zoom: `chart: {kind: tiles}`
    of only the stand-out cells, with a `verdict`. Keep the full table in view or in
    backup.
  - Example: a survey of five library branches on four services, where the paper singles
    out one branch that scores lowest on every service. The stand-outs are one whole row.
    Mark that row; the zoom, if one is needed, is that row alone.
  - `foot`: the key numbers in words.
  - **Common failure:** tiles of every cell. The audience has to find the few that matter.
- Say every results paragraph **in the main talk** at least once. A finding that lives
  only in a backup table is one the audience never hears. One row of a main table or one
  line of `say` is enough. `diffcheck` lists the paper sentences whose result numbers
  appear only on backup slides.
- A caption's caveat travels with its value. If a table caption says the numbers cannot
  be compared to something, and a main slide compares them, that slide states the caveat
  too. `diffcheck` lists caveats whose subject reaches the main talk and whose warning
  does not.

### §plots — When the results live only in the paper's plots.
- **Signal:** the numbers you need are bars or curves in a figure, and the text gives at most
  a range ("3.3–7.1×"). Systems and hardware papers are often like this.
- **Slide:** the paper's figure, one panel (cut it with `figure.crop`), with
  `figure.highlight` on the bars or the region the slide is about, and a `lead` or bullet
  that says what the box shows. Put the range the text does give in words. The caption
  says it is the paper's figure.
- **Do not read values off the plot** to redraw it. A number typed by hand has no source,
  and `deckcheck` rejects it. The highlight lets a pasted plot point the audience at one
  place instead of making them read twenty bars.

### §leaderboard — A leaderboard.
- **Signal:** the rows are methods (earlier work, then the paper's own at the bottom) and the
  columns are metrics (a score, a cost); the paper bolds its best rows. There are no "few
  cells that stand out" to tile. The finding is where the paper's rows sit among the
  rest.
- **Slide:** a `chart: {kind: dots}` of the one metric the claim is about, with the paper's
  rows marked `<safe>` (what the paper bolds). Add a second `dots` for the cost if the
  claim is "better at a fraction of the cost" (`log: true` for costs that span ten
  times). The full table goes to backup. Beside the chart put only what the chart does
  not show (a reading guide, a cost column). The same numbers as a table next to their
  own chart are duplication, and `refcheck` fails it.
- **Common failure:** the full table at full width. Ten rows by five columns print in
  scriptsize, and the back of the room cannot find the two columns the talk is about.

### §spread — Across conditions: the spread is the finding.
- **Signal:** the paper reports the same comparison once per condition (per dataset, site,
  batch, season) and says how it varies: the effect shrinks steadily, it holds everywhere,
  or one condition departs from the rest. It usually gets a paragraph of its own with its
  own numbers.
- **Slide:** a `chart: {kind: bars}` with one group per condition and a `takeaway` in the
  paper's terms ("The gain shrinks the further a branch is from the city."). A `callout`
  points at the condition the paper names: where the trend turns, or the one that departs
  ("Sales rise everywhere except the coast.").
- **Common failure:** folding it into one bullet elsewhere ("varies by site"). The spread is
  the finding, and the audience sees a spread in a chart but not in a list of numbers.

### §shapes — When the result is not a table

Four shapes of result recur that §table's grid does not fit. Look for their signal before
reaching for tiles.

- The result is a theorem or a rate.
  - **Signal:** "Theorem", "under Assumptions …", "converges at rate …", "is valid when …".
  - **Slide:** a `flow` from *what is assumed* to *what follows*, in words. The conclusion box
    is `<safe>`, and the formula goes in `fine`.
  - If the paper contrasts its condition with a stronger one it avoids ("much weaker
    than …"), set the two conditions against each other in a composed standout (§pair).
  - **Scope:** state exactly the class the theorem covers. Put "always" or "guaranteed" on
    screen only when the theorem says so.
  - The object the theorems are about gets its defining formula on screen once, large,
    with each symbol named in words beside it (a `foot` is too small for it). Use
    `formula:` on an ordinary slide, with the symbols in `bullets` beneath it; a standout
    spends one of the three or four turning points on it. Without the formula the
    audience hears two theorems about a thing it never saw.
  - An algorithm box (training, sampling, a protocol) becomes `steps:`: one numbered line
    per step, beside the `formula:` it applies. Do not put it in a paragraph of `say` or
    in pseudocode.
  - Why it holds: if the paper says in words why the theorem is true (a remark after it,
    a proof idea such as "each term shrinks as n grows, but their sum does not"), give
    that one pane: the key step in words, not the proof. The proof itself is backup.
- The result is one observed event or measurement.
  - **Signal:** a single observation reported with its significance and its uncertainty.
  - **Order:**
    1. the observation itself (the case, §case);
    2. each alternative that could have produced it, as the audience's objection (§objection);
    3. how often chance alone does this;
    4. what it is, with the uncertainty written as the paper writes it, e.g. "24.1 (+5.9/−3.3)";
    5. what it implies.
- The result is that nothing moves.
  - **Signal:** the paper's claim is robustness, e.g. "does not substantively change",
    "every method gives about the same".
  - **Slide:** the table, with the spread in the `foot` ("every cell between 41.2 and 42.0").
    Tiles are for the few cells that stand out. With none standing out, they read as a
    coloured table.
- The result is a fitted law.
  - **Signal:** "scales as", "follows a power law", "we fit", a constant and an exponent
    printed in an equation, and the data points only inside log–log figures.
  - **Slide:** the paper's plot, one panel at a time (`crop`), with `highlight` on the range
    the law covers, and the law itself in `formula:`. Say what the exponent does in one
    sentence the audience can reuse ("doubling the input cuts the error by 7%"), not the
    exponent alone.
  - Do not redraw the curve from the formula. Points computed from a fit are not the
    paper's data, and the plot's point is that the data lie on the line.
  - Exponents the paper prints as its result (how fast each quantity should grow) are
    numbers in the text. Redraw those, for example as bars.
  - Inside the range it is a measurement; past it, a prediction. State the range as the
    paper does ("over six orders of magnitude"). Anything extrapolated beyond it keeps the
    paper's hedge ("we conjecture", "uncertain by an order of magnitude").
  - One quantity, several values. A law is often fitted twice (alone and jointly), or
    measured and then predicted. Keep one value per slide and name which it is. Show the
    other only as the comparison ("predicted 0.37, measured 0.36").
  - One quantity, two forms. When the paper writes the same exponent as x in one place and
    1/x in another, put one form on screen and have `say` link the two. `prose_audit`
    reports a spoken reciprocal the screen does not show.

---

## Defending a result

### §objection — The objection the audience is about to raise
- **Signal:** right after a main result, the paper reports a check against an obvious doubt:
  the instrument recalibrated, data from another year, a subset left out.
- **Slide:** titled as the objection ("Could it be the thermometer?"). Show the check as a
  chart, and the answer in a block: `block: {kind: good}` when the check confirms the
  result, `block: {kind: alert}` when it weakens it. Say which, plainly.
- **Common failure:** leaving the check for questions time. The audience stops believing the
  result before then.

### §pair — Turning points: the minimal pair
- **Signal:** two conditions that differ in one factor give very different results, and that
  difference is what the next section explains.
- Choose the pair that differs in **exactly one thing**. Go through the paper's result
  tables and list the pairs whose rows share everything but one setting. The paper often
  says it in words ("the same material", "identical except for"). Prefer the cleanest
  difference over the largest.
  - Test: if the slide needs a line like "but these two also differ in X and Y", you
    picked the wrong pair. That caveat means the audience cannot tell which difference did
    it. Find the pair that makes the caveat unnecessary.
- **Slide:** set the two values against each other and say the one setting that changed. How
  much room it gets follows its weight in the argument:
  - When the signal above holds (the next section explains this difference), the pair is a
    turning point: a `standout` with the two values (`big` as a list; how the keys stack
    is in [layouts.md](layouts.md#a-composed-impact-slide)). Left inside a grid, the
    cleanest pair in the paper is one cell among many and nobody sees it.
  - A pair that illustrates a result but opens no explanation: two bars side by side on
    an ordinary slide, with the gap called out (`callout`).
  - A pair the audience already expects: a sentence in `lead` above the next result.
- In an observational study nothing was held fixed. The groups (a mode, a cohort, a kind
  of user) were observed, not assigned, and they differ in other things too, such as the
  task or the person. Do not write "only X differs". Say what the split is ("Split by
  mode") and name what else moves with it in `lines` or `ask`. The pair can still carry
  the turn, but it cannot claim a cause.
- The same holds when the cleanest pair still differs in one extra thing (the late bus
  also leaves from a different stop). Name that difference on the slide at normal size,
  not in `fine`, and title the slide by what the pair shows, not "only X changes".

### §part-whole — The part and the whole
- **Signal:** a whole-system result, and an ablation: the same system with one component
  removed.
- **Slide:** the whole and the ablation in one view, with the difference between them stated,
  so the audience sees how much of the whole that component accounts for. Mark rows by
  what the paper judges. Example: a delivery network's average delay, and the same
  network with its overnight sorting step removed.
  - Put every system in one view. The rows that break the pattern are part of the
    finding. Leave them out and the bullets count rows the audience cannot see.
  - In a table grouped by system, do not repeat the system name in every row. `refcheck`
    reads a repeated prefix as two attributes in one cell, and prints the grouped form it
    accepts.

### §second-subject — A second subject
- **Signal:** a second system, dataset or setting.
- **Slide:** show the second subject the same way as the first, so the audience compares like
  with like. Add a verdict that says which findings carry over and which do not, each tied
  to the number it comes from. Whether that is one slide or two depends on how much the
  audience must hold in mind at once.

### §two-subjects — One grid, two subjects
- **Signal:** the same grid of conditions is reported for two subjects (two cities, two age
  groups, two seasons).
- **Slide:** both panels in one chart, `chart: {kind: tiles, panels: […]}`, so they share
  colours and scale. For each subject, write one line saying how to read its panel and the
  conclusion the paper states about it. Use `<safe>` only when the paper states it; your
  own reading stays unmarked. What differs between the subjects besides the grid goes in
  `fine`.
  - Example: rent by district and year for two cities. Both panels rise left to right;
    the lines say where each rise is steepest.

---

## Showing what the result is about

### §object — Show the object first.
- **Signal:** the results are reported per part of a system (stages, departments, rooms,
  steps).
- **Slide:**
  - A `pipeline` of the whole thing, with stages named exactly as the results name them.
  - A `frame` around the parts the talk varies. Its `label` is the system's name and its
    `note` says what the talk does to it ("the stages we compare").
  - `feed` boxes for what goes in, `out` for what comes out.
    Name each input the paper names (the raw files, the settings): one `feed` box each,
    on the stage that receives it, with what it is in a short `sub`. "Input" in one box
    says nothing. The named inputs make the system concrete to someone who has never
    seen it.
  - `loop` only if the paper's system really runs in a loop.
  - Example: a clinic's intake as `triage → exam → pharmacy`, with a `feed` "referral
    letter" on triage and "lab results" on exam, and `out` "prescription". No loop.
  - A `lead` above: what the audience needs to know about the system before the first
    result. The `foot`: one sentence on what the system is.
  - If the paper already draws the object as a wide diagram (a graphical model, a chain,
    an architecture), use that figure alone for the slide. Stacking a pipeline on top of a
    wide figure shrinks both until neither reads.
    If the paper's drawing is tall (a stack drawn bottom to top), it prints small on a
    16:9 slide. Redraw it as a `pipeline` in the paper's own part names and put the
    paper's figure in backup.
- Feature: a slide given both `diagram:` and `figure:` puts the figure in a low, wide band
  under the diagram (`figure.share`, 0.24 of the body by default). A tall figure there
  shrinks to a thumbnail; the build warns when it prints at under half the width.
- **Common failure:** starting with results in a paper whose results are named by parts. The
  first result slide then has to explain the parts and the finding at once.
- §object and §insides are **different slides**. §object says what the system does (what
  goes in, what comes out, how it is used). §insides says how the compared systems are
  built (their parts side by side, what is inside each). When the paper shows both
  signals, make both slides; merging them loses one of the two.
  If your §object and §insides slides draw the same picture (the same boxes in a row),
  one of them is wrong. §object should show what enters and leaves; §insides should show
  what is inside each part and how many of it there are.

### §insides — The objects side by side, with their insides.
- **Signal:** two or more systems are compared.
- **Slide:** a `pipeline` with one row per system. The rows need not have the same number of
  stages; a difference in length is itself something to show.
  - Example: two sorting centres, one `receive → sort → dispatch`, the other `receive →
    weigh → scan → sort → dispatch`, with the stages the paper studies ringed.
  - Show what is inside the parts the talk varies (`inner`, `glyph`).
  - Put the stage `group` headers above and a `count` under each stage where the paper
    gives one (staff, machines, shelves).
  - Mark the part under study (`mark: safe` for a green ring). In a system diagram this
    ring means "the part we study", the one place green does not mean "better". Put no
    judgement marks in the same diagram.
  - Use `separate: all` when the paper changes each part independently of the others.
- Definitions the audience needs to read the numbers go in `fine` on the first slide that
  uses them, not on a slide of their own, unless the method is itself a contribution.

### §structure — A structure that is not a row: dependencies, branches, shortcuts.
- **Signal:** the paper's figure has arrows that cross rows (a task graph, a dependency graph,
  a state machine) or jump over parts (a bypass, a shortcut, a residual link).
- **Slide:** `diagram: {kind: graph}` for crossing arrows. Place nodes on a column/row grid
  and give edges a `kind` (`data`, `control`, `state`), so the line style carries the
  meaning and a legend says which is which. For a jump over parts of a row, use
  `pipeline` with `skip`.
- **Common failure:** pasting the paper's figure because "it cannot be drawn". Redraw it with
  only the nodes the talk names; the paper's version has every node and small type.

### §matrix — A matrix split into tiles.
- **Signal:** the method works tile by tile over rows and columns, such as a mask or a
  schedule.
- **Slide:** `diagram: {kind: grid}`. Mark the tile in hand (`hit`) and the tiles already done
  (`safe`), and give the other tiles `mark: blank` so the matrix keeps its shape.
- **Common failure:** squeezing the two axes into one row, which loses the order in which the
  tiles are visited.

### §factors — One drawing per factor, before its first number.
- **Signal:** the results are organised by two or more independent factors (a table whose
  columns group by one choice and rows by another; a design that crosses two settings).
- **Slide:** a drawing of what each factor does, not its name, before the first number that
  depends on it. Use one slide per factor when each needs its own picture, and one slide
  for both when a single drawing shows them together (a `grid` with one factor on each
  axis). Where it goes depends on the arc: all factors up front, or each just before its
  own result.
  - Example: a study of bus delays by route and by hour. The routes as a map; the day as
    a `flow` with the rush hours marked.
  - The title can ask (*"Where does the bus go?"*), point (*"Watch the rush hours"*), or
    count off the factors (*"First: where the bus goes"*). The last is one option, not
    the rule.
  - Pick the diagram by what the factor is: a `grid` for two crossed choices, a `flow` for
    a sequence, a `strip` for a row of named cells ([layouts.md](layouts.md)).
  - A `takeaway` inside the figure, and a `foot` that names the term the paper uses.
- **Common failure:** one grid listing the combinations by name. It shows which combinations
  exist, not what each factor does.

---

## Setting up the question

### §question — The assumption, as a question.
- **Signal:** the thesis goes against something the audience assumes (more rain means more
  flooding, a longer queue means a slower clinic, the newer method wins). Look in the
  abstract and introduction for "rather than", "contrary to", "not … but".
- **Slide:** a question to the room that the slide does not answer. Several forms work:
  - a `standout` with the question as `lead` and the two plain options in `big`
    (`[{text: "a person"}, {text: "a machine"}]`, `gap: "or"`);
  - a question title over the material the audience will judge (two photographs, two
    short records), with a `cue` telling the presenter to ask for a show of hands;
  - a guess: the title asks for a number (*"How long is the average wait?"*) and the next
    slide gives it.
  - The options are what the audience would choose between, in the plain terms they
    already use, which are usually the paper's own terms (a person or a machine, rent or
    buy, one site or many). Neither option may be **your conclusion**.
  - Test: if one option is the phrase your last slide ends on ("a person with a
    checklist"), the question has already answered itself. Put the plain choices there
    instead ("a person" or "a machine").
- **Common failure:** answering it on the same slide, including by putting the answer in one
  of the options.

### §prior — Prior work as a table of dimensions.
- **Signal:** the related-work section compares works along the same dimensions ("A forecasts
  from satellites and adds ground stations; B uses ground stations alone and samples
  hourly").
- **Slide:** a `table`. Rows are the works; columns are the dimensions the paper uses (the
  data, the measure, the year, what each assumes). Put a `lead` question above ("What
  have others tried?"). Below, write one sentence on the gap the table shows: the column
  no row fills, or the place where the rows disagree.
  In `say`, name the dimensions and point at one or two rows; do not read every name. A
  list read aloud is a name dump. `prose_audit` §3 lists the row names you did not say as
  a separate note; that is expected on this slide.
- **Common failure:** a flow diagram of "the gap". It names no prior work.

### §turn — The turn.
- **Signal:** the paper's move differs from the others in one stated way: it uses different
  data, measures something else, or asks a narrower question.
- **Slide:** say what others do, what this paper does instead, and the question that follows,
  without answering it. Forms, by weight:
  - a `standout` with `flow`, top to bottom: others, then this paper, then the question.
    Example: "every earlier survey asked the shop owners", then "we asked the customers",
    then "do the two agree on when the shop is busy?";
  - the prior-work table (§prior) with this paper as its last row, the differing cell
    marked;
  - one `lead` sentence on the first method slide, when the difference is small.

### §answer — The answer that changes.
- **Signal:** the paper answers the same question as a named earlier work, with a different
  number or rule ("the earlier rule: water once a week; ours: water when the soil reads
  dry").
- **Slide:** when you give your answer, put the two side by side. Use a `big` pair (the
  earlier answer, then yours) with the question in `lead`, or two panes. Before your
  method, show only the earlier rule and do not answer yet (§question).
- **Common failure:** the earlier rule appears once, in small type, early in the talk. Your
  answer comes ten slides later, and the audience has to remember what it replaced.

---

## Closing

### §closing — Explanations, rules, limits, the last sentence
- Explanations:
  - **Signal:** the discussion says why the result happens.
  - **Slide:** every mechanism the paper names gets its own space, whether there are one, two
    or three, with a schematic where one exists. Never draw one and drop another. What the
    paper says the explanation does not cover (a case it cannot account for) belongs on
    the same slide; an alert block (`block: {kind: alert}`) is one way to set it apart.
  - Example: a paper says afternoon queues grow because of staff breaks, and notes one
    Monday with no breaks and a long queue anyway. One pane for the cause, with a
    timeline; the Monday beside it.
- Rules to take away: each implication the paper draws, in its own wording and no
  stronger. Forms: bullets; a small table from situation to choice; a diagram when the
  rule is about where something sits. A caveat that qualifies every rule can stand apart
  (a bullet that starts with `> ` is indented and has no marker).
- Limits: one bullet per limitation the paper lists, **in the main talk**. Where they sit
  follows the arc: just before the last slide, right after the result they qualify, or
  with the objection they answer. A talk that keeps its limits only in backup never says
  them.
- The last slide: the thesis as one sentence in a standout, with nothing else on it.

---

## §title-page — The title page

Name the speaker with `meta.presenter` (underlined inside `author`) and give a multi-line
affiliation as a list: `institute: ["Lab", "Institute"]`.

## §plan — Write the plan down

Before step ②, write `plan.md` next to `slides.yaml`: first the paper's argument as the
chain of links from "Arcs", then one row per planned slide.

| # | link in the argument | paper section | signal you found (quote or cite) | principle | slide kind |
|---|---|---|---|---|---|

A slide with no signal in the signal column should not be there. A signal you found that
has no slide is a gap, and the audience will ask about it.
