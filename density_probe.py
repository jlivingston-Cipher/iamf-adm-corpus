#!/usr/bin/env python3
# density_probe.py — WP3 helper (original work): map the automation-density
# failure boundary of the ADM wav-splicer (SIGABRT via unsigned-underflow
# sample-count CHECK, found on 200 blocks / 20 per s). Generates single-object
# variants at a range of uniform block counts and records encode outcomes.
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adm_corpus_gen as g  # reuse builders; OUTDIR overridden below

ROOT = os.environ.get("SENTINEL_TOOLCHAIN", "/home/claude/iamf-wp1")
OUT = f"{ROOT}/adm-density-probe"
ENC = f"{ROOT}/src/build-iamf/encoder_main"
g.OUTDIR = OUT

COUNTS = [1, 5, 10, 20, 40, 50, 80, 100, 125, 160, 200, 250, 320, 400, 500,
          640, 800, 1000, 2000]

os.makedirs(OUT, exist_ok=True)
results = []
for n in COUNTS:
    name = f"probe_{n:05d}"
    if not os.path.exists(os.path.join(OUT, f"{name}.wav")):
        g.make_dlb_objects(name, 1, n_blocks=n, trajectories="circle")
    outdir = os.path.join(OUT, f"out_{n:05d}")
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run(
        [ENC, f"--adm_filename={OUT}/{name}.wav",
         "--adm_profile_version=base", f"--output_iamf_directory={outdir}"],
        capture_output=True, text=True, timeout=600)
    produced = [f for f in os.listdir(outdir) if f.endswith(".iamf")]
    ok = r.returncode == 0 and bool(produced)
    sig = -r.returncode if r.returncode < 0 else None
    results.append({"n_blocks": n, "block_dur_ms": round(10000.0 / n, 3),
                    "ok": ok, "returncode": r.returncode, "signal": sig,
                    "tail": (r.stderr or "").strip().splitlines()[-1:]})
    print(f"{n:5d} blocks ({10000.0 / n:8.2f} ms) -> "
          f"{'OK' if ok else f'FAIL rc={r.returncode}'}", flush=True)
with open(f"{OUT}/density_probe.json", "w") as f:
    json.dump(results, f, indent=1)
