# Install

## Requirements

- Python 3.10 or newer
- The Python packages in `requirements.txt`: `pyyaml`, `python-pptx`, `matplotlib`, `pymupdf`, `pillow`
- A TeX distribution with Beamer and the metropolis theme, plus `lmodern`
  (TeX Live or MiKTeX; on Debian/Ubuntu: `texlive-latex-extra texlive-fonts-recommended lmodern`)

```bash
pip install -r requirements.txt
```

Optional:

| For | You need |
|---|---|
| Papers with EPS figures | `epstopdf` (ships with TeX Live) |
| Korean or other non-Latin decks | `xelatex` and a font for the script (`kotex` for Korean) |
| Rendering the PPTX to images to look at it | PowerPoint, or LibreOffice (`soffice --headless --convert-to pdf`) |

No service, no API key, no network access at runtime.

---

## As an agent skill

### Claude Code / Codex

```bash
npx skills add kcy4334-lgtm/paper2podium
```

Then ask for it by name, or let the agent pick it up from the task:

```
Build the conference deck from paper/paper.tex
```

### Manual install

Copy the folder to wherever your agent reads skills from:

| Agent | Path |
|---|---|
| Claude Code (user-wide) | `~/.claude/skills/paper2podium/` |
| Claude Code (per project) | `<repo>/.claude/skills/paper2podium/` |
| Codex | `~/.codex/skills/paper2podium/` |

```bash
git clone https://github.com/kcy4334-lgtm/paper2podium \
  ~/.claude/skills/paper2podium
```

The agent reads `SKILL.md` and calls everything else from there.

---

## As plain command-line tools

You don't need an agent. Every script also runs on its own.

```bash
git clone https://github.com/kcy4334-lgtm/paper2podium
cd paper2podium
pip install -r requirements.txt

cp config.example.yaml my-deck.yaml
$EDITOR my-deck.yaml                      # point it at your files
python scripts/deckcheck.py my-deck.yaml
```

Other tools:

```bash
# Paper -> slides.yaml skeleton -> every output in one command
# (build_figs, build_deck, pdflatex with overflow fed back, build_pptx, build_script)
python scripts/scaffold.py     paper/paper.tex -o slides.yaml
python scripts/build.py        slides.yaml -o out --limit 15 --qa 3

# Prose measurements, straight from the spec
python scripts/prose_audit.py slides.yaml
```

The build reports the talk time; `--limit` and `--qa` turn it into a pass/fail gate.
`TOKEN_WORDS` in `timing.py` is deliberately empty. How long an acronym takes to say depends
on the field, so it belongs in the spec as `meta.acronyms: {NASA: 1, SoC: 3}`, not in the
script.

`scripts/sidecar.py` is imported by your figure generators rather than run:

```python
from sidecar import write
write("figs/values.txt", {"fig1"}, ["fig1\tbakery\tweekday\t27.1\t5.9e-05"])
```

---

## In CI

`deckcheck.py` exits with status 1 on any failure, so it can go straight into a workflow:

```yaml
- run: pip install -r requirements.txt
- run: python scripts/deckcheck.py slides/deckcheck.yaml
```

This repository's own workflow (`.github/workflows/test.yml`) runs the test suite with
`ResourceWarning` promoted to an error, runs the checker against both fixtures, and on
Linux builds `examples/filled-slides.yaml` end to end.

---

## Verifying the install

```bash
python -m unittest discover tests
```

It should print `OK`. The test count is not quoted here, because a number written into three
documents went out of date in all three.

Then confirm that the checker fails when it should. The test suite does this, but it is
useful to see once:

```bash
cd tests/fixtures/latex
sed -i 's/92\.4/77\.7/' deck.tex        # a number that isn't in the paper
python ../../../scripts/deckcheck.py config.yaml   # must exit 1 and print 77.7
git checkout deck.tex
```

A checker that only ever prints zero tells you nothing. Once you have written your own
`config.yaml`, run the same test against it automatically, on every section:

```bash
python scripts/deckcheck.py your-config.yaml --selftest
```

It reports any section configured in a way that cannot fail: an empty `claims:` list, a
`ban_file` that did not load, a `coverage_pattern` that matches nothing, a missing PPTX.
Without the self-test, these all look exactly like a clean pass.
