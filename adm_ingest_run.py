#!/usr/bin/env python3
# adm_ingest_run.py — WP3 ADM->IAMF ingest matrix runner.
#
# Original work (WP3, IAMF project). Drives iamf-tools encoder_main across
# the synthetic ADM corpus, both IAMF profiles, and the importance-threshold
# axis; captures rc/stderr/wall-time, probes every produced bitstream with
# probe_main, and diffs observed outcomes against the corpus manifest's
# pre-registered expectations.

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.environ.get("SENTINEL_TOOLCHAIN", "/home/claude/iamf-wp1")
ENC = f"{ROOT}/src/build-iamf/encoder_main"
PROBE = f"{ROOT}/src/build-iamf/probe_main"
CORPUS = f"{ROOT}/adm-corpus"
OUT = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/out/adm-ingest"

MANIFEST = json.load(open(f"{CORPUS}/corpus_manifest.json"))

PROFILES = ("base", "enhanced")


def probe(path):
    r = subprocess.run([PROBE, f"--input_filename={path}",
                        "--format=json", "--scan=counts"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"probe_error": (r.stderr or r.stdout).strip().splitlines()[-3:]}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"probe_error": ["unparseable probe output"]}


def run_one(name, profile, threshold=None, tag=None):
    tag = tag or f"{name}__{profile}"
    outdir = os.path.join(OUT, tag)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)
    cmd = [ENC, f"--adm_filename={CORPUS}/{name}.wav",
           f"--adm_profile_version={profile}",
           f"--output_iamf_directory={outdir}"]
    if threshold is not None:
        cmd.append(f"--adm_importance_threshold={threshold}")
    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    wall = round(time.monotonic() - t0, 2)
    produced = sorted(f for f in os.listdir(outdir) if f.endswith(".iamf"))
    ok = r.returncode == 0 and bool(produced)
    entry = {
        "corpus_file": name, "profile": profile,
        "importance_threshold": threshold,
        "ok": ok, "returncode": r.returncode, "wall_s": wall,
        "outputs": [{"file": os.path.join(tag, f),
                     "size": os.path.getsize(os.path.join(outdir, f)),
                     "probe": probe(os.path.join(outdir, f))}
                    for f in produced],
        "stderr_tail": (r.stderr or r.stdout).strip().splitlines()[-6:],
    }
    return entry


def main():
    os.makedirs(OUT, exist_ok=True)
    results = []
    verdicts = []
    for name, meta in MANIFEST["files"].items():
        for profile in PROFILES:
            e = run_one(name, profile)
            results.append(e)
            expected = meta.get("expect", {}).get(profile, "ok")
            observed = "ok" if e["ok"] else "reject"
            verdict = "MATCH" if expected == observed else "SURPRISE"
            verdicts.append({"corpus_file": name, "profile": profile,
                             "expected": expected, "observed": observed,
                             "verdict": verdict,
                             "stderr_tail": e["stderr_tail"] if not e["ok"]
                             else None})
            print(f"{'OK ' if e['ok'] else 'REJ'} {verdict:8s} "
                  f"{name:28s} {profile:9s} {e['wall_s']:7.1f}s "
                  f"{len(e['outputs'])} out")
    # importance-threshold axis on the importance file
    for thr in (5, 11):
        e = run_one("dlb_importance", "base", threshold=thr,
                    tag=f"dlb_importance__base_thr{thr}")
        results.append(e)
        print(f"{'OK ' if e['ok'] else 'REJ'} threshold={thr:2d} "
              f"dlb_importance base {e['wall_s']:5.1f}s "
              f"{len(e['outputs'])} out")
    with open(os.path.join(OUT, "ingest_results.json"), "w") as f:
        json.dump(results, f, indent=1)
    with open(os.path.join(OUT, "expectation_verdicts.json"), "w") as f:
        json.dump(verdicts, f, indent=1)
    n_sur = sum(1 for v in verdicts if v["verdict"] == "SURPRISE")
    print(f"\n{len(verdicts)} expectation checks, {n_sur} surprises "
          f"-> {OUT}/expectation_verdicts.json")


if __name__ == "__main__":
    main()
