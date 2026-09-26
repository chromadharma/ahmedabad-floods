# Flooding Ahmedabad: who gets cut off?

**Question.** Can a flood model for Ahmedabad be built that is measurably more
accurate than the tools used now, and if so, which parts of the city lose road
access to a hospital, and at what level of flooding?

The test case is the 23–25 July 2026 rain flood (284 mm at Bakrol in about
twelve hours; about three feet of standing water in Bopal and Ghuma). A
Sentinel-1 pass on the morning of 25 July imaged the western belt while the
water was still there. Four flood models, from a lowest-ground null to a 2D
rain-on-grid simulation, are scored against that image. The road network step
reuses the `hazardnet` engine from
[ca-road-fragility](https://github.com/chromadharma/ca-road-fragility).

**Status (27 Sep 2026):** design agreed ([`docs/DESIGN.md`](docs/DESIGN.md));
E1 data fetched; AMC rain and Vasna figures transcribed (`data/manual/`).
One finding already: it was still raining when the 25 July image was taken
(DESIGN §4). No models run yet.

## Run

```
make env      # uv venv (Python 3.12) + requirements.txt, incl. hazardnet v0.1.0
make data     # python scripts/fetch.py all  (~320 MB; see data/README.md)
make test
```

Data sources and licences: [`data/README.md`](data/README.md),
[`DATA_LICENSES.md`](DATA_LICENSES.md). FABDEM-derived outputs are CC BY-NC-SA 4.0.

Author: Sahasrik Ragani
