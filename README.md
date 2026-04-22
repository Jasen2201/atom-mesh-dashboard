# ATOM Mesh PD Benchmark Dashboard

Static dashboard for SLURM nightly DeepSeek-R1 1P+1D benchmark runs.
Inspired by the ATOM benchmark dashboard, focused on InferenceX-style
latency-throughput Pareto curves.

Live: https://jasen2201.github.io/atom-mesh-dashboard/

## Layout

```
index.html             # single-page dashboard (Chart.js, no build step)
data/
├── index.json         # manifest of runs (rebuilt at end of either script)
├── <run_id>.json      # one SLURM run     (written by update_data.py)
└── infx_*.json        # InferenceX runs   (written by fetch_external.py)
update_data.py         # SLURM scan: /it-share/yajizhan/slurm_logs/ → data/<run>.json
fetch_external.py      # ONE-SHOT: pull MI355X mori-sglang FP8 baseline from InferenceX API
.nojekyll              # tell GitHub Pages to serve files as-is
```

The two scripts are independent. They each write only their own files; both
rebuild `data/index.json` at the end by scanning the whole `data/` folder, so
neither script clobbers the other's results. Re-run `fetch_external.py` only
when you want to refresh the InferenceX snapshot — it is not a daily job.

External (InferenceX) lines are drawn **dashed** in the charts to set them
apart from your SLURM runs.

The frontend `fetch()`es `data/index.json` then each per-run JSON in parallel.
This means **the page must be served over http** (`python -m http.server` or
GitHub Pages); opening `index.html` via `file://` will not work because the
browser blocks `fetch` on local files.

## Views

- **Pareto** — TPOT (or TTFT, e2e) vs per-user/total throughput.
  Each line = one (date, ISL, OSL, ratio); each point = one concurrency level.
- **TTFT vs Concurrency** — diagnostic curve, lines per (date, ISL, OSL, ratio).
- **Time Series** — pick a fixed sweep point, plot any metric across dates.
- **Table** — all sweep points, sortable.

Filter bar narrows model / backend / ISL / OSL / ratio / date globally.

## Updating data

```bash
cd /it-share/yajizhan/code/atom-mesh-dashboard
./update_data.py                                # default /it-share/yajizhan/slurm_logs
./update_data.py /other/logs -d data/           # custom path
git add data/ && git commit -m "data: $(date +%F)" && git push
```

`data/` is **append-only** by default — a SLURM run, once captured, stays in
the dashboard history forever, even if the source directory is later purged
from `slurm_logs/` (SLURM logs rotate; the dashboard archive must not).
Both scripts log "kept (use --prune to delete)" for orphaned files; run with
`--prune` only when you actually want to drop them.

`update_data.py` expects directory layout:

```
<MMDD>_<config>_<jobid>/
  bench/pd-mesh-<ISL>-<OSL>-<CONC>-<ratio>.json    # sglang benchmark_serving output
  gsm8k/<ts>_gsm8k/.../results_*.json              # lm_eval output (optional)
```

Year is read from the JSON `date` field (`YYYYMMDD-HHMMSS`); falls back to current year.

## Daily cron

```
# crontab -e
30 6 * * *  cd /it-share/yajizhan/code/atom-mesh-dashboard && \
            ./update_data.py && \
            git add data/ && \
            git -c user.name=slurm-bot -c user.email=slurm-bot@local \
                commit -m "data: $(date +%F)" --allow-empty && \
            git push origin main
```

## First-time GitHub Pages setup

1. Repo Settings → Pages → Source: **Deploy from a branch** → Branch: `main` → `/ (root)`.
2. Wait ~1 min, then open the URL.

The page is fully client-side, so any static host works (`python -m http.server` for local preview).

## Local preview

```bash
cd /it-share/yajizhan/code/atom-mesh-dashboard
python3 -m http.server 8765
# open http://<host>:8765/
```
