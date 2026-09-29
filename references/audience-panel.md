# Audience panel: a rehearsal protocol

## Contents

- [Why this is not optional](#why-this-is-not-optional)
- [Setup](#setup)
- [Constraints — paste these into the prompt verbatim](#constraints--paste-these-into-the-prompt-verbatim)
- [Five seats with backgrounds that do not overlap](#five-seats-with-backgrounds-that-do-not-overlap)
- [Ask the chair for one extra thing](#ask-the-chair-for-one-extra-thing)
- [Ask each of them for](#ask-each-of-them-for)
- [Deciding](#deciding)
- [Round two](#round-two)
- [What it actually found](#what-it-actually-found)

Some things code cannot check: whether the talk is followable and whether the argument
lands. People have to read for those. Run five agents at once and decide by how many of
them overlap, not by any one opinion.

---

## Why this is not optional

This is the only step with no machine behind it, so it is the only one you can drop with
**every check still green**.

On one deck all seven checks passed and the timing fitted the slot. Every reader still
stalled in the same places, and none of those places was visible to any check.

| What stopped them | Why no check saw it, and what closed it |
|---|---|
| A caption reading "the three sites we compare" above a map showing two | "three" is a word; the map is a PNG. Closed: declare `figure: {path: x.png, shows: 2}` and `prose_audit` compares it to the prose. The PNG cannot be read, so the author is asked |
| Two slides giving different values for the word "control" | Both values are in the paper, so the numbers check passed on both. Closed: `prose_audit` reports one label carrying two values |
| Column headers (`n_eff`, `CI`) never spoken aloud or defined | Every check asked whether what is shown is correct; none asked whether it was explained. Closed: `prose_audit` reports screen jargon absent from `say` |
| A table with a row of missing years, nothing saying whether they were never collected or lost | A checker that reads what is present cannot see an absence. Closed: blank and dash cells are counted, and cleared once any text explains them |
| The talk ranked six bus routes for ten minutes and never showed a map of them | This was once called "a defect no rule could state in advance", which was wrong. Closed: row labels recurring across two or more tables are the cast; if no figure appears before their first use, `prose_audit` says so |

All five are now mechanical. Each looked impossible to mechanize until someone pointed at
it, and the next one will look that way too.

The panel's output is therefore not a list of fixes, it is a list of checks you have not
written yet. Run it, then ask of every finding what would have caught it. The answer has
never been "nothing". Twice it was "ask the author to declare what we cannot see", which is
a good answer and was available from the start.

Say in your handover whether you ran this. "All checks green" and "five readers got
through it" are different claims, and only the second is about the audience. If you did
not run it, write *"checked, not rehearsed"* rather than letting green checks imply it.

---

## Setup

1. Export the deck to one PNG per slide. A PDF lets the reader page back, which the room
   will not allow.
2. Include the speaker script, spoken lines only, with no cues, times or backup slides:
   `python scripts/build_script.py slides.yaml -o out/script.md --spoken panel/spoken.md`.
3. Put those two things in a folder. **Do not include the paper or the raw data.**

## Constraints — paste these into the prompt verbatim

> You are sitting in the audience at a conference. Hold to these constraints.
>
> - You cannot go back. One pass, in slide order.
> - You have not read the paper. Not even the abstract.
> - You cannot hear the speaker's stage directions. The slides and the spoken lines are
>   everything you get.
> - Do not open any file outside the folder you were given, even if you are curious.
>
> Write down every point where you got stuck, with the slide number. Note it even if it
> was resolved later: in the room, that is time you spent lost.

## Five seats with backgrounds that do not overlap

| Seat | What they catch |
|---|---|
| Practitioner who would apply the result | Whether it holds outside the paper's setting; missing conditions |
| Graduate student in the exact topic | Holes in the method; how it sits against prior work |
| Adjacent application researcher | Whether the result is usable on their problem |
| Adjacent field reader who does not know the topic | Missing terms and unstated premises |
| Session chair | Time budget, Q&A defensibility, overall impression |

**Do not seat only experts.** In both rounds so far, the most valuable findings came from the
adjacent-field reader and the chair, the two seats that do not already know the answer.

## Ask the chair for one extra thing

> Estimate the talk length independently. Don't look at our calculation; time it your
> own way.

In both rounds, that estimate caught a bug in the timing model.

## Ask each of them for

1. Where you got stuck: slide number and what stopped you. This is the most important
   item.
2. Anything on screen that was never explained. Readers keep looking at what you skipped.
3. Any claim you didn't believe, and on which slide.
4. A one-line verdict: good / okay / poor, plus one line of why.

## Deciding

- If three or more got stuck at the same place, fix it.
- Log a single mention; do not fix it. The exception is a mention from the chair or the
  adjacent-field reader, because the other three already know too much to stall there.
- Do not be alarmed if round two scores lower than round one. The same readers read
  harder the second time. That is the protocol working, not the deck getting worse.
- **Fix by adding, not by cutting.** "The script says a number the screen does not show"
  is fixed by putting the number on the screen, not by no longer saying it. A result the
  paper reports is part of the talk; dropping it to satisfy a reader loses a finding. This
  matters most when `diffcheck` has said the same sentence appears only in backup: then
  the panel and the checker agree that it belongs on a main slide.

## Round two

Give the same five seats the revised version. **Do not put round one's findings in the
prompt.** Otherwise the readers check whether those were fixed instead of reading the deck
fresh. Start each seat as a new agent with the same persona prompt. Do not continue the
round-one conversation, because it still remembers the first draft and cannot read the
second one fresh.

---

## What it actually found

Two rounds on one talk found the following, which shows the kind of thing to expect:

- Three of four readers stuck in the same place: one word on two slides meant two
  different things, and nothing on screen said which.
- A chart's labels undercut the talk's own point: the talk said one thing mattered, and
  every label on the chart was about something else.
- One item of the paper's limitations section was missing entirely. The reader whose own
  work it bore on found it.
- A slide title stated a conclusion the paper never draws. The paper reports the values
  it rests on and deliberately stops short of that conclusion.
- An auto-generated "can be cut" mark had landed on the one paragraph annotated "do not
  cut." The chair caught it. The general rule: automatic marks and hand-written notes have
  to check each other.
