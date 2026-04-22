#!/usr/bin/env python3
"""One-shot: pull DeepSeek-R1 reference data from the public InferenceX API
and write data/infx_*.json + refresh data/index.json.

All configs for a given (hardware, framework, precision, ISL, OSL) are merged
into ONE run file so the dashboard draws a single combined Pareto curve per
combo — matching InferenceX's own presentation.

This is a snapshot, not a recurring job. Re-run only when you want to refresh
the InferenceX baseline (e.g. they publish new numbers).

Usage:
    ./fetch_external.py
    ./fetch_external.py -d data/
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path

from update_data import rebuild_index

API = "https://inferencex.semianalysis.com/api/v1/benchmarks?model=DeepSeek-R1-0528"
SPEC_METHOD = "none"
RUN_PREFIX = "infx_"
ISL_OSL_FILTER = [(8192, 1024)]

SOURCES = [
    {"hardware": "mi355x", "framework": "mori-sglang", "precisions": ["fp8", "fp4"]},
    {"hardware": "b200",   "framework": "dynamo-trt",  "precisions": ["fp8", "fp4"]},
]


def fetch():
    print(f"GET {API}", file=sys.stderr)
    req = urllib.request.Request(API, headers={"User-Agent": "atom-mesh-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def ms(x):
    return round(x * 1000, 4) if x is not None else None


def to_runs(rows):
    all_runs = []
    for src in SOURCES:
        hardware = src["hardware"]
        framework = src["framework"]
        for precision in src["precisions"]:
            matches = [
                r for r in rows
                if r.get("hardware") == hardware
                and r.get("framework") == framework
                and r.get("precision") == precision
                and r.get("spec_method") == SPEC_METHOD
            ]
            print(f"{len(matches)} rows for {hardware}/{framework}/{precision} "
                  f"(spec_method={SPEC_METHOD})",
                  file=sys.stderr)

            groups = defaultdict(list)
            for r in matches:
                key = (r["isl"], r["osl"])
                if ISL_OSL_FILTER and key not in ISL_OSL_FILTER:
                    continue
                groups[key].append(r)

            for (isl, osl), group_rows in sorted(groups.items()):
                latest_date = max(r["date"] for r in group_rows)
                latest_rows = [r for r in group_rows if r["date"] == latest_date]

                points = []
                for r in latest_rows:
                    m = r.get("metrics", {})
                    ptp, dtp = r["prefill_tp"], r["decode_tp"]
                    pgpu, dgpu = r["num_prefill_gpu"], r["num_decode_gpu"]
                    total_gpu = pgpu + dgpu
                    conc = r["conc"]
                    mean_intvty = m.get("mean_intvty")
                    median_intvty = m.get("median_intvty")
                    tput_per_gpu = m.get("tput_per_gpu")
                    output_tput_per_gpu = m.get("output_tput_per_gpu")
                    input_tput_per_gpu = m.get("input_tput_per_gpu")
                    output_tput = mean_intvty * conc if (mean_intvty is not None and conc) else None

                    def rnd(v):
                        return round(v, 4) if v is not None else None

                    points.append({
                        "isl": isl, "osl": osl, "concurrency": conc, "ratio": None,
                        "ttft_ms": ms(m.get("mean_ttft")),
                        "ttft_p99": ms(m.get("p99_ttft")),
                        "tpot_ms": ms(m.get("mean_tpot")),
                        "tpot_p99": ms(m.get("p99_tpot")),
                        "itl_ms": ms(m.get("mean_itl")),
                        "e2el_ms": ms(m.get("mean_e2el")),
                        "interactivity": rnd(median_intvty),
                        "tput_per_gpu": rnd(tput_per_gpu),
                        "output_tput_per_gpu": rnd(output_tput_per_gpu),
                        "input_tput_per_gpu": rnd(input_tput_per_gpu),
                        "output_tput": rnd(output_tput),
                        "total_tput": None,
                        "req_tput": None, "completed": None, "duration": None, "num_prompts": None,
                        "prefill_tp": ptp, "decode_tp": dtp,
                        "prefill_ep": r.get("prefill_ep"),
                        "prefill_dpa": r.get("prefill_dp_attention"),
                        "prefill_workers": r.get("prefill_num_workers"),
                        "decode_ep": r.get("decode_ep"),
                        "decode_dpa": r.get("decode_dp_attention"),
                        "decode_workers": r.get("decode_num_workers"),
                        "num_prefill_gpu": pgpu, "num_decode_gpu": dgpu,
                        "total_gpu": total_gpu,
                        "image": r.get("image"),
                        "point_date": r["date"],
                        "precision": precision,
                        "hardware": hardware,
                    })

                run_id = f"{RUN_PREFIX}{hardware}_{framework}_{precision}_isl{isl}_osl{osl}"
                try:
                    ts = int(time.mktime(time.strptime(latest_date, "%Y-%m-%d")) * 1000)
                except ValueError:
                    ts = None
                all_runs.append({
                    "run_id": run_id,
                    "date": latest_date,
                    "timestamp": ts,
                    "model": "DeepSeek-R1-0528",
                    "backend": framework,
                    "config_label": f"{hardware}_{framework}_{precision}",
                    "source": "InferenceX",
                    "hardware": hardware,
                    "points": points,
                    "gsm8k": None,
                })
    return all_runs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-d", "--data-dir", default=str(Path(__file__).parent / "data"))
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        rows = fetch()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"ERROR: external fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    runs = to_runs(rows)
    written = set()
    for run in runs:
        f = data_dir / f"{run['run_id']}.json"
        f.write_text(json.dumps(run, indent=2) + "\n")
        written.add(f.name)
        print(f"  wrote {f.name}: {len(run['points'])} points (latest {run['date']})",
              file=sys.stderr)

    rebuild_index(data_dir)
    print(f"Done. {len(runs)} InferenceX runs written to {data_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
