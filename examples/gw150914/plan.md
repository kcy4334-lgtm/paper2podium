# plan.md: GW150914 talk (15-min slot, 3 min questions, so 12 min spoken)

Source: `paper/paper.md` (converted from `../paper/paper.pdf` by `pdf_paper.py`).
Paper: "Observation of Gravitational Waves from a Binary Black Hole Merger",
Phys. Rev. Lett. 116, 061102 (2016), LIGO Scientific Collaboration and Virgo Collaboration.

## The argument as a chain (planning.md "Arcs": single-observation paper)

1. Nobody had seen it: GR predicted the waves in 1916; the binary pulsar showed they
   exist, but no direct detection and no black-hole merger had ever been observed (Intro).
2. The observation: the same transient in both LIGO detectors, 6.9 ms apart, SNR 24,
   sweeping up in frequency (Observation, Fig. 1).
3. What it must be: chirp mass ≃30 M⊙ and a 75 Hz orbit leave black holes as the only
   known objects compact enough; the waveform after the peak rings down like a Kerr black
   hole (Observation, Fig. 2).
4. Alternatives ruled out: the instrument (Detectors), the environment (Detector
   validation), and chance (Searches: time-shift background, two independent searches,
   >5.1σ and 4.6σ, Fig. 4).
5. The value with its uncertainty: Table I masses, spin, distance; 3.0 M⊙c² radiated
   (Source discussion).
6. What it implies, and what it does not cover: GR tests, graviton bound with the
   paper's own "does not improve on" hedge, astrophysical implications and rate range,
   limits (two detectors give ~600 deg², secondary spin weakly constrained, 16 days of data),
   outlook (Outlook), then the last sentence (Conclusion).

Order: the paper's own section order is kept. No link was moved.
The single-observation arc's "how often chance does this" link is the paper's Searches
section, which already sits after the detector and validation sections, so no reordering
was needed.

## Slides

| # | link | paper section | signal found (quote) | principle | slide kind |
|---|---|---|---|---|---|
| 1 | — | title | "LIGO Scientific Collaboration and Virgo Collaboration" | planning §title-page | title |
| 2 | 1 | Introduction | "black hole mergers have not previously been observed"; binary pulsar "demonstrated the existence of gravitational waves" | §turn / §prior (indirect vs direct): the section describes a sequence of events, not works on shared dimensions, so a `flow` diagram, not a table | figure (diagram flow) |
| 3 | 2 | Observation, Fig. 1 top row | "GW150914 arrived first at L1 and 6.9 ms later at H1 … shifted in time by this amount and inverted" | §case: the observation itself, paper figure one panel (`crop`) + `highlight`; §plots: no numbers printed for the curves | figure (crop, highlight) |
| 4 | 2 | Observation, Fig. 1 bottom row | "Over 0.2 s, the signal increases in frequency and amplitude in about 8 cycles from 35 to 150 Hz" | §case / §plots: one panel, highlight the track | figure (crop, highlight) |
| 5 | 3 | Observation (chirp mass) | "we obtain a chirp mass of M ≃ 30M⊙ … This leaves black holes as the only known objects compact enough" | §shapes: object's defining formula once, large (`formula:`) + reasoning as `steps:`; question title (SKILL "Some slides must ask") | content (formula, steps) |
| 6 | 3 | Observation | same; the turning point of the argument (inference to black holes) | SKILL "three or four standout slides at the turning points"; layouts "flow narrows in steps" | standout (flow) |
| 7 | 3 | Observation, Fig. 2 | "decay of the waveform after it peaks is consistent with the damped oscillations of a black hole relaxing to a final stationary Kerr configuration"; NR waveform "confirmed to 99.9%"; reconstructions "94% overlap" | §case / §plots: paper figure + highlight (no printed data) | figure (highlight) |
| 8 | 4 | Detectors, Fig. 3 | "measures gravitational-wave strain as a difference in length of its orthogonal arms"; ×300, 20 W → 700 W → 100 kW | §object: "If the paper already draws the object as a wide diagram … use that figure alone"; layouts "one pane shows, the other says how to read it" | columns (figure + parts) |
| 9 | 4 | Detector validation | "no evidence to suggest that GW150914 could be an instrumental artifact"; "too small to account for more than 6% of its strain amplitude" | §objection: titled as the objection; the check drawn as a `flow` whose last box is `safe` (the check confirms). A first draft drew the sensor list as a `strip` beside a `block: good`; the strip labels overprinted in a half-width pane, so the sensor list moved to the diagram note | figure (diagram flow) |
| 10 | 4 | Searches, two subsections | "GW150914 is confidently detected by two different types of searches … independent methods" | §insides: two systems compared → `pipeline`, one row per search, what is inside each stage | figure (diagram pipeline) |
| 11 | 4 | Searches | "it is not possible to shield the detector from gravitational waves"; time-shift; "leads to an overestimate of the noise background and therefore to a more conservative assessment" | SKILL ② "Carry the paper's explanations" (without X, Y happens); question title | figure (diagram flow) |
| 12 | 4 | Generic / binary search, Fig. 4 | "ρ̂c = 23.6 is larger than any background event"; "ηc = 20.0 … strongest event of the entire search" | §plots: whole figure (two panels are the two searches), `highlight` on the event; §table caveat: C2+C3 4.4σ kept in say | figure (highlight) |
| 13 | 4 | Generic / binary search | ">5.1σ and 4.6σ for the binary coalescence and the generic transient searches, respectively" | layouts "composed impact slide": `big` pair with `gap` | standout (big pair) |
| 14 | 5 | Source discussion, Table I | Table I; "All uncertainties define 90% credible intervals"; 3.0 M⊙c² radiated | §table "keep the full table in view"; "nothing moves"/lookup claim → the table itself, one pane shows, the other reads it | columns (table + parts) |
| 15 | 6 | Source discussion (GR tests) | "all three tests are consistent with the predictions of general relativity"; graviton bound "does not improve on the model-dependent bounds" | §prior-like dimension table (three tests on the same dimensions: what is compared, result); §closing hedge travels with value; question title | table |
| 16 | 6 | Source discussion (astrophysics) | "demonstrates the existence of stellar-mass black holes more massive than ≃25M⊙"; rates "2–400 Gpc−3 yr−1 … only the lowest event rates being excluded" | §closing: rules to take away in the paper's wording, no stronger | content |
| 17 | 6 | Observation (600 deg²), Source (secondary spin), Searches (16 days), Outlook | "With only two detectors … localized to an area of approximately 600 deg2"; "spin of the secondary is only weakly constrained"; "3 times higher SNR"; Virgo, KAGRA, LIGO-India | §closing limits: one bullet per limit in the main talk | columns |
| 18 | 6 | Conclusion | "This is the first direct detection of gravitational waves and the first observation of a binary black hole merger." | §closing "The last slide: the thesis as one sentence in a standout" | standout |
| B1 | 4 | Searches | full significance numbers (FAR, probability, σ, background years, C2+C3, second event 1 per 2.3 yr, p 0.02) | SKILL ⑤ backup + `ask` | table, backup |
| B2 | 4 | Detectors | calibration <10% amplitude / 10 degrees phase; GPS 10 μs; <1 μPa; 40-kg test masses | backup + `ask` | table, backup |

## Deliberate omissions (for diffcheck `--omit`)

- Reference list years/volumes, author list, affiliations: not content (pdf_paper keeps
  them in `paper.md`).
- 16 days of data (Sept 12 – Oct 20, 2015) is said, not shown; the first-run end date
  January 12, 2016 is not used (context only).
- Stochastic background (predictions in [115]): no numbers, one sentence in say on slide 16.
- `0.99`: the binary search's template-bank spin range ("dimensionless spins up to 0.99");
  a search-setup parameter, not a result. Passed to diffcheck `--omit`.

## Audience panel (audience-panel.md), two rounds, five seats each, fresh agents

Each entry gives who raised it, the problem, and the fix.

Round 1:

- 5/5 stalled on slides 10/12: eta_c, rho_c and the search "classes" undefined. Fixed with
  a `fine` definition on slide 10 and say lines.
- 3 seats: the 94% overlap and 99.9% spoken on slide 7 but not on screen. Put in `fine`.
- Chair + adjacent field: 75 Hz vs 150 Hz only in fine print. Now said aloud.
- Grad + chair: metallicity line never spoken. Now said.
- Chair: "1 per 2.3 years" not on screen. Put in `fine`.
- Chair timing estimate 12.5 min at 110 wpm vs tool 10:48 at 135 wpm. Set wpm to 125
  and trimmed the say lines.

Round 2:

- 3 seats: 4.4σ (C2+C3) vs 4.6σ (C3), direction unexplained. The say line now explains the
  shape cut.
- 2 seats: detector-frame vs source-frame masses. Table I note + say.
- 2 seats: C1/C2 undefined. Put in `fine`.

Logged, not fixed:

- Adjacent-field glossary requests (megaparsec, redshift, Hubble time, weak lensing,
  numerical relativity). The paper defines none of them, so a definition would be text with
  no source.
- The merger-rate width (2–400). It is the paper's own result, and its hedge is on screen.
