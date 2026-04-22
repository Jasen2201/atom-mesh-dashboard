#!/usr/bin/env python3
"""One-shot: pull DeepSeek-R1 FP8 MI355X mori-sglang reference data from
the public InferenceX API and write data/infx_*.json + refresh data/index.json.

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

from update_data import rebuild_index  # share the index-rebuild logic

API = "https://inferencex.semianalysis.com/api/v1/benchmarks?model=DeepSeek-R1-0528"
HARDWARE = "mi355x"
FRAMEWORK = "mori-sglang"
PRECISION = "fp8"
RUN_PREFIX = "infx_"


def fetch():
    print(f"GET {API}", file=sys.stderr)
    req = urllib.request.Request(API, headers={"User-Agent": "atom-mesh-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def to_runs(rows):
    matches = [
        r for r in rows
        if r.get("hardware") == HARDWARE
        and r.get("framework") == FRAMEWORK
        and r.get("precision") == PRECISION
    ]
    print(f"{len(matches)} rows after filter "
          f"(hardware={HARDWARE}, framework={FRAMEWORK}, precision={PRECISION})",
          file=sys.stderr)

    groups = defaultdict(list)
    for r in matches:
        key = (
            r["precision"], bool(r["disagg"]),
            r["prefill_tp"], r["decode_tp"],
            r["num_prefill_gpu"], r["num_decode_gpu"],
            r["isl"], r["osl"],
        )
        groups[key].append(r)

    runs = []
    for key, rows_in in groups.items():
        prec, disagg, ptp, dtp, pgpu, dgpu, isl, osl = key
        # latest date wins per concurrency
        latest_per_conc = {}
        for r in rows_in:
            c = r["conc"]
            if c not in latest_per_conc or r["date"] > latest_per_conc[c]["date"]:
                latest_per_conc[c] = r

        points = []
        latest_date = ""
        for c in sorted(latest_per_conc):
            r = latest_per_conc[c]
            m = r.get("metrics", {})
            tpot_s = m.get("mean_tpot")
            ttft_s = m.get("mean_ttft")
            intvty = m.get("mean_intvty")  # output tokens/sec/user
            output_tput = intvty * c if (intvty is not None and c is not None) else None

            def ms(x):
                return round(x * 1000, 4) if x is not None else None

            points.append({
                "isl": isl, "osl": osl, "concurrency": c, "ratio": None,
                "ttft_ms": ms(ttft_s),
                "ttft_p99": ms(m.get("p99_ttft")),
                "tpot_ms": ms(tpot_s),
                "tpot_p99": ms(m.get("p99_tpot")),
                "itl_ms":  ms(m.get("mean_itl")),
                "e2el_ms": ms(m.get("mean_e2el")),
                "output_tput": round(output_tput, 4) if output_tput is not None else None,
                "total_tput": None,  # InferenceX exposes per-GPU throughput; total ambiguous
                "req_tput": None, "completed": None, "duration": None, "num_prompts": None,
            })
            if r["date"] > latest_date:
                latest_date = r["date"]

        config_label = (
            f"mori-sglang_{prec}_{ptp}p{dtp}d_{pgpu}+{dgpu}gpu"
            + ("_disagg" if disagg else "")
        )
        run_id = f"{RUN_PREFIX}{HARDWARE}_{config_label}_isl{isl}_osl{osl}"
        try:
            ts = int(time.mktime(time.strptime(latest_date, "%Y-%m-%d")) * 1000)
        except ValueError:
            ts = None
        runs.append({
            "run_id": run_id,
            "date": latest_date,
            "timestamp": ts,
            "model": "DeepSeek-R1-0528",
            "backend": FRAMEWORK,
            "config_label": config_label,
            "source": "InferenceX",
            "points": points,
            "gsm8k": None,
        })
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-d", "--data-dir", default=str(Path(__file__).parent / "data"))
    ap.add_argument("--prune", action="store_true",
                    help="Also delete infx_*.json files whose config no longer appears "
                         "in the API response. Default: keep them as a permanent snapshot.")
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

    # Append-only by default: an old InferenceX snapshot stays even if their
    # API later drops the config. Use --prune to actually delete.
    leftovers = [f for f in data_dir.glob(f"{RUN_PREFIX}*.json") if f.name not in written]
    if leftovers:
        action = "removing" if args.prune else "kept (use --prune to delete)"
        for f in leftovers:
            print(f"  {action}: {f.name}", file=sys.stderr)
            if args.prune:
                f.unlink()

    rebuild_index(data_dir)
    print(f"Done. {len(runs)} InferenceX runs written to {data_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
