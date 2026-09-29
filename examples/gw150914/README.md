# Example: GW150914

A 15-minute conference talk built with this skill from one published paper:

> B. P. Abbott et al. (LIGO Scientific Collaboration and Virgo Collaboration),
> "Observation of Gravitational Waves from a Binary Black Hole Merger,"
> *Phys. Rev. Lett.* **116**, 061102 (2016). https://doi.org/10.1103/PhysRevLett.116.061102

The paper is published under the
[Creative Commons Attribution 3.0 License](https://creativecommons.org/licenses/by/3.0/).
The copy in `paper/`, the figures cropped from it (`figs/`, `paper/figs/`) and the deck that
reuses them are redistributed under the same terms, with this attribution. The deck is a
derived work made for demonstration. It is not a talk given by the authors.

![All 20 pages of the deck](preview.png)

## What is here

| Path | What it is |
|---|---|
| `paper/paper.pdf` | The paper as published (the only input) |
| `paper/paper.md`, `paper/figs/` | What `scripts/pdf_paper.py` read out of the PDF |
| `slides.yaml` | The one source for all three outputs |
| `plan.md` | The argument chain, and which signal in the paper each slide comes from |
| `deckcheck.yaml`, `banned.txt` | Checker configuration |
| `out/talk.pdf`, `out/talk.pptx`, `out/script.md` | The deck, the PowerPoint, and the timed speaker script |

## How the deck was made

An agent was given only the paper PDF and this skill, and followed `SKILL.md` to the end.
No one edited the slides by hand. The talk runs as the paper argues:

1. It opens with what was expected, and what had not yet been seen.
2. It then shows the observation itself, with the arrival-time difference and the frequency climb.
3. Next come the reasons it must be two black holes, and each way it could have been noise, taken one at a time.
4. The significance of both searches is set side by side.
5. It gives what the source is.
6. It closes on what two detectors cannot tell yet, and the one-sentence claim.

## Rebuild and check

From the repository root:

```bash
cd examples/gw150914
python ../../scripts/build.py slides.yaml -o out --limit 15 --qa 3
python ../../scripts/deckcheck.py deckcheck.yaml
python ../../scripts/outcheck.py slides.yaml --deck out/talk.pdf --pptx out/talk.pptx --script out/script.md --sidecar out/figs/values.txt
python ../../scripts/fitcheck.py out/talk.pdf --pptx out/talk.pptx
python ../../scripts/diffcheck.py out/talk.pdf --source paper/paper.pdf --sidecar out/figs/values.txt --script out/script.md --omit 0.99
python ../../scripts/refcheck.py slides.yaml
python ../../scripts/prose_audit.py slides.yaml
```

Every checker exits 0. The build prints a handful of warnings: a few diagram labels are at
the 6.5pt floor, and two highlight labels sit on light ink. They are listed on purpose; the
skill reports what it could not make perfect instead of hiding it. `--omit 0.99` names a
search-setup parameter the talk leaves out on purpose (the reason is in `plan.md`).
