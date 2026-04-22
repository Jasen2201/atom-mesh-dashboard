# ATOM Mesh PD Benchmark Dashboard

Static dashboard for SLURM nightly DeepSeek-R1 1P+1D benchmark runs.
Inspired by the ATOM benchmark dashboard, focused on InferenceX-style
latency-throughput Pareto curves.

Live: https://jasen2201.github.io/atom-mesh-dashboard/

## Layout

```
index.html        # single-page dashboard (Chart.js, no build step)
data.js           # generated: window.BENCHMARK_DATA = { runs: [...] }
update_data.py    # rebuild data.js from /it-share/yajizhan/slurm_logs/
.nojekyll         # tell GitHub Pages to serve files as-is
```

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
./update_data.py /other/logs -o data.js         # custom path
git add data.js && git commit -m "data: $(date +%F)" && git push
```

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
            git add data.js && \
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
