#!/usr/bin/env python3
"""Scan SLURM benchmark log directories and refresh data/ for the dashboard.

Expected layout under <logs_dir>:
    <MMDD>_<config>_<jobid>/
        bench/pd-mesh-<ISL>-<OSL>-<CONC>-<ratio>.json    (sglang benchmark_serving output)
        gsm8k/<ts>_gsm8k/.../results_*.json              (lm_eval output, optional)

Output (under -d / --data-dir):
    index.json              manifest listing every run
    <run_id>.json           one file per run (points + gsm8k + metadata)

Stale per-run files (runs no longer present in <logs_dir>) are deleted.

Usage:
    ./update_data.py                                     # default /it-share/yajizhan/slurm_logs
    ./update_data.py /path/to/slurm_logs -d data/
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

DIR_RE = re.compile(r"^(\d{4})_(.+)$")
FILE_RE = re.compile(r"^pd-mesh-(\d+)-(\d+)-(\d+)-([\d.]+)\.json$")

METRIC_KEYS = [
    ("ttft_ms", "mean_ttft_ms"),
    ("ttft_p99", "p99_ttft_ms"),
    ("tpot_ms", "mean_tpot_ms"),
    ("tpot_p99", "p99_tpot_ms"),
    ("itl_ms", "mean_itl_ms"),
    ("e2el_ms", "mean_e2el_ms"),
    ("output_tput", "output_throughput"),
    ("total_tput", "total_token_throughput"),
    ("req_tput", "request_throughput"),
    ("completed", "completed"),
    ("duration", "duration"),
    ("num_prompts", "num_prompts"),
]


def short_model(model_id: str) -> str:
    return model_id.rstrip("/").split("/")[-1] if model_id else "unknown"


def read_gsm8k(gsm8k_dir: Path):
    if not gsm8k_dir.is_dir():
        return None
    for results in gsm8k_dir.rglob("results_*.json"):
        try:
            d = json.loads(results.read_text())
        except Exception:
            continue
        gsm = d.get("results", {}).get("gsm8k", {})
        for key in ("exact_match,strict-match", "exact_match,flexible-extract"):
            if key in gsm:
                try:
                    return float(gsm[key])
                except (TypeError, ValueError):
                    pass
    return None


def parse_run_dir(run_dir: Path):
    m = DIR_RE.match(run_dir.name)
    if not m:
        return None
    mmdd, rest = m.group(1), m.group(2)
    bench_dir = run_dir / "bench"
    if not bench_dir.is_dir():
        return None

    points = []
    year = None
    timestamp = None
    backend = None
    model = None

    for f in sorted(bench_dir.glob("pd-mesh-*.json")):
        fm = FILE_RE.match(f.name)
        if not fm:
            continue
        isl, osl, conc = int(fm.group(1)), int(fm.group(2)), int(fm.group(3))
        ratio = float(fm.group(4))
        try:
            data = json.loads(f.read_text())
        except Exception as e:
            print(f"  skip {f.name}: {e}", file=sys.stderr)
            continue

        date_str = data.get("date", "")
        if year is None and len(date_str) >= 8 and date_str[:8].isdigit():
            year = date_str[:4]
            try:
                timestamp = int(time.mktime(time.strptime(date_str, "%Y%m%d-%H%M%S")) * 1000)
            except ValueError:
                pass

        backend = backend or data.get("backend")
        model = model or short_model(data.get("model_id", ""))

        point = {"isl": isl, "osl": osl, "concurrency": conc, "ratio": ratio}
        for out_key, in_key in METRIC_KEYS:
            v = data.get(in_key)
            if isinstance(v, float):
                v = round(v, 4)
            point[out_key] = v
        points.append(point)

    if not points:
        return None
    if year is None:
        year = str(time.gmtime().tm_year)

    iso_date = f"{year}-{mmdd[:2]}-{mmdd[2:]}"
    return {
        "run_id": run_dir.name,
        "date": iso_date,
        "timestamp": timestamp,
        "model": model or "unknown",
        "backend": backend or "unknown",
        "config_label": rest,
        "points": points,
        "gsm8k": read_gsm8k(run_dir / "gsm8k"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs_dir", nargs="?", default="/it-share/yajizhan/slurm_logs")
    ap.add_argument("-d", "--data-dir", default=str(Path(__file__).parent / "data"))
    args = ap.parse_args()

    logs_dir = Path(args.logs_dir)
    if not logs_dir.is_dir():
        print(f"error: {logs_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    written_files = set()
    for run_dir in sorted(logs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        run = parse_run_dir(run_dir)
        if not run:
            continue
        runs.append(run)
        run_file = f"{run['run_id']}.json"
        (data_dir / run_file).write_text(json.dumps(run, indent=2) + "\n")
        written_files.add(run_file)
        print(f"  {run['run_id']}: {len(run['points'])} points, gsm8k={run['gsm8k']}",
              file=sys.stderr)

    index = {
        "lastUpdate": int(time.time() * 1000),
        "source": str(logs_dir),
        "runs": [
            {
                "run_id": r["run_id"],
                "date": r["date"],
                "timestamp": r["timestamp"],
                "model": r["model"],
                "backend": r["backend"],
                "config_label": r["config_label"],
                "n_points": len(r["points"]),
                "gsm8k": r["gsm8k"],
                "file": f"{r['run_id']}.json",
            }
            for r in runs
        ],
    }
    (data_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")

    # Drop per-run JSONs whose source dir disappeared from logs_dir.
    stale = [
        f for f in data_dir.glob("*.json")
        if f.name != "index.json" and f.name not in written_files
    ]
    for f in stale:
        print(f"  removing stale {f.name}", file=sys.stderr)
        f.unlink()

    print(f"Wrote {len(runs)} runs ({sum(len(r['points']) for r in runs)} points) to {data_dir}/",
          file=sys.stderr)


if __name__ == "__main__":
    main()
