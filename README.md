# paper2podium

paper2podium turns a finished paper into a conference talk. From one source file it builds a
PDF deck, a PowerPoint file and a speaker script with timings, then checks all three against
the paper.

It is an agent skill for Claude Code (or any agent that reads `SKILL.md`), plus the Python
scripts the skill runs. It needs no service or API key, and nothing leaves your machine.

[![The example deck, all pages](examples/gw150914/preview.png)](examples/gw150914/)

The deck above was built by an agent from the GW150914 detection paper (CC BY 3.0) and
nothing else. The PDF, the PowerPoint, the script and the slide plan are in
[`examples/gw150914/`](examples/gw150914/).

## Quick start

You need Python 3.10+ and a TeX distribution with Beamer and the metropolis theme.
[INSTALL.md](INSTALL.md) has the details.

```bash
git clone https://github.com/kcy4334-lgtm/paper2podium
cd paper2podium
pip install -r requirements.txt
```

To use it as a skill, install it with `npx skills add kcy4334-lgtm/paper2podium` (or copy the
folder into `~/.claude/skills/`), then ask Claude Code something like:

```
Make a 15-minute conference talk from paper/main.tex
```

The skill tells the agent what to do step by step: sketch the slide plan, fill in the slides,
build, run the checks and fix what they find.

To check your install, build the bundled example:

```bash
python scripts/build.py examples/filled-slides.yaml -o out
```

## What it checks

- Every number on the slides and in the script appears in the paper.
- The slides do not claim more than the paper. If the paper says "up to 3x faster", a slide
  that says "3x faster" is flagged.
- The rendered PDF and PowerPoint contain what was written, with no overflowing, overlapping
  or unreadably small text.
- The talk fits your time slot.
- The deck, the PowerPoint and the script say the same thing. All three come from one
  `slides.yaml`, so there is nothing to keep in sync by hand.

## Using the scripts directly

You don't need an agent. The same steps by hand:

```bash
python scripts/scaffold.py paper/paper.tex -o slides.yaml   # skeleton with TODOs
$EDITOR slides.yaml                                          # titles and what you'll say
python scripts/build.py    slides.yaml -o out --limit 15 --qa 3
cp config.example.yaml deckcheck.yaml                        # once, point it at your paper
python scripts/deckcheck.py deckcheck.yaml
python scripts/outcheck.py  slides.yaml --deck out/talk.pdf --pptx out/talk.pptx \
                            --script out/script.md --sidecar out/figs/values.txt
```

`scaffold` does not write the talk for you. It pulls out the section order, the tables and
each section's numbers, and marks with `TODO:` every place where you have to decide
something. `python scripts/deckspec.py --keys` lists everything `slides.yaml` accepts.

## How it works

```
paper.tex ──scaffold──▶ slides.yaml ──┬──build_deck───▶ talk.tex ──pdflatex──▶ talk.pdf
                        (you fill it) ├──build_pptx───▶ talk.pptx
                                      └──build_script─▶ script.md
                                      │                     │
                    deckcheck ◀───────┘                     │  is every number in the paper?
                    outcheck  ◀─────────────────────────────┘  did what you wrote arrive?
```

`deckcheck` reads the generated source and compares it with the paper. `outcheck` reads the
PDF and PowerPoint that came out at the end, so it also catches text that the renderer
dropped. `fitcheck` looks for overflow and overlap in the rendered pages, and `diffcheck` lists
what the paper has that the deck never used.

Part of the `deckcheck` report on the example:

```
A. Are the numbers shown on the derivative in the source?
   24 decimals · 0 values not in the source
B. Key claims — on both the derivative and the source
   OK   binary search significance 5.1     derivative present · source present
   ...  (12 claims, all OK)
E. Reverse direction — values the source has that the derivative never uses
   8 kinds in the source · 0 value(s) never used anywhere in the derivative
total
   all 0 — passed
```

It exits with status 1 on any failure, so it can run in CI. `deckcheck.py <config> --selftest`
plants a deliberate error in your config and reports any section that fails to catch it, so
a check that silently does nothing shows up.

## Limitations

- It has been tested by giving a fresh agent only a paper and the skill, on several real
  papers from different fields. It has not had many outside users yet.
- It does not plot raw data. It draws charts from tables in the spec and can crop and mark up
  figures taken from the paper.
- LaTeX input works best. PDF input works, but tables come through as text.
- It checks the talk against the paper. It cannot tell whether the paper is right.

## Tests

```bash
python -m unittest discover tests
```

Most tests inject an error into a small fixture and check that it gets caught.

## License

MIT. See [LICENSE](LICENSE).
