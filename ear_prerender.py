#!/usr/bin/env python3
# ear_prerender.py — WP3 helper: pre-render the EAR reference set into the
# cache location fidelity_measure.py expects (original work, WP3).
import json
import os
import subprocess
import sys

ROOT = os.environ.get("SENTINEL_TOOLCHAIN", "/home/claude/iamf-wp1")
CORPUS = f"{ROOT}/adm-corpus"
OUT = f"{ROOT}/out/adm-fidelity/ear"
EAR = os.environ.get("EAR_RENDER", "/home/claude/earenv/bin/ear-render")
LAYOUTS = {"2.0": "0+2+0", "5.1": "0+5+0", "7.1.4": "4+7+0"}
MANIFEST = json.load(open(f"{CORPUS}/corpus_manifest.json"))


def layouts_for(meta):
    kind = meta.get("kind", "")
    if kind == "binaural":
        return ["2.0"]
    if kind == "bed":
        lay = meta.get("layout", meta.get("bed", ""))
        if "stereo" in lay:
            return ["2.0"]
        if "7dot1dot4" in lay or "7dot1dot2" in lay:
            return ["2.0", "5.1", "7.1.4"]
        return ["2.0", "5.1"]
    return ["2.0", "5.1", "7.1.4"]


os.makedirs(OUT, exist_ok=True)
for name, meta in MANIFEST["files"].items():
    if meta.get("expect", {}).get("base") == "reject" and \
            meta.get("expect", {}).get("enhanced") == "reject" and \
            meta.get("kind") != "objects_no_dbmd":
        # still render rejects that are valid ADM (they serve as evidence the
        # file is renderable); skip only the structurally broken one
        if meta.get("kind") == "no_axml":
            continue
    for layout in layouts_for(meta):
        out = os.path.join(OUT, f"{name}_{layout.replace('.', '')}.wav")
        if os.path.exists(out):
            continue
        r = subprocess.run([EAR, "-s", LAYOUTS[layout],
                            "--enable-block-duration-fix",
                            f"{CORPUS}/{name}.wav", out],
                           capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.exists(out)
        print(f"{'OK ' if ok else 'FAIL'} {name} {layout}", flush=True)
        if not ok:
            print("   " + "\n   ".join(
                (r.stderr or "").strip().splitlines()[-2:]), flush=True)
print("done")
