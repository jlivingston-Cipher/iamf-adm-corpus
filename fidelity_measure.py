#!/usr/bin/env python3
# fidelity_measure.py — WP3 ADM->IAMF conversion-fidelity metrics.
#
# Original work (WP3, IAMF project). For every bitstream the ingest matrix
# produced: render with iamf-tools decoder_main on BS.2051 reference layouts;
# render the SAME source ADM with the independent EBU ADM Renderer (EAR,
# BS.2127) on the same layouts; then measure
#   - routing survival: per-channel dominant identifier frequency
#     (WP1 spectral-identity method) vs corpus ground truth,
#   - per-channel and overall RMS error (raw and after optimal global gain),
#   - 100 ms windowed error envelope (exposes automation staircase),
#   - energy-vector angular error vs analytic ground-truth trajectories,
#   - BS.1770 integrated loudness of each render (ffmpeg ebur128) and the
#     delta between converted and reference renders,
#   - bitstream-declared loudness (probe metadata, from ingest results) for
#     later comparison against measured values.
# EAR and the IAMF renderer legitimately differ (BS.2127 point-source panner
# vs 3OA fold + OBR); the per-file baseline (static single object) separates
# renderer divergence from conversion loss. Metrics are emitted raw to JSON;
# interpretation happens in the report.

import json
import math
import os
import re
import subprocess
import sys

import numpy as np

ROOT = os.environ.get("SENTINEL_TOOLCHAIN", "/home/claude/iamf-wp1")
DEC = f"{ROOT}/src/build-iamf/decoder_main"
FF = f"{ROOT}/bin/ffmpeg-install/bin/ffmpeg"
EAR = os.environ.get("EAR_RENDER", "/home/claude/earenv/bin/ear-render")
CORPUS = f"{ROOT}/adm-corpus"
INGEST = f"{ROOT}/out/adm-ingest"
OUT = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/out/adm-fidelity"

MANIFEST = json.load(open(f"{CORPUS}/corpus_manifest.json"))
INGEST_RESULTS = json.load(open(f"{INGEST}/ingest_results.json"))

SR = 48000
WIN = SR // 10  # 100 ms

# decoder_main layout name -> (EAR system, channel count)
LAYOUTS = {"2.0": ("0+2+0", 2), "5.1": ("0+5+0", 6), "7.1.4": ("4+7+0", 12)}

# 4+7+0 speaker unit vectors (az deg CCW-from-front, el deg), LFE excluded.
SPK_474 = [(30, 0), (-30, 0), (0, 0), None, (90, 0), (-90, 0),
           (135, 0), (-135, 0), (45, 45), (-45, 45), (135, 45), (-135, 45)]


def layouts_for(meta):
    ch = meta.get("channels", 0)
    kind = meta.get("kind", "")
    if kind in ("binaural",):
        return ["2.0"]
    if kind == "bed":
        lay = meta.get("layout", meta.get("bed", ""))
        if "stereo" in lay:
            return ["2.0"]
        if "7dot1dot4" in lay or "7dot1dot2" in lay:
            return ["2.0", "5.1", "7.1.4"]
        return ["2.0", "5.1"]
    return ["2.0", "5.1", "7.1.4"]


def read_wav(path):
    from scipy.io import wavfile
    _sr, d = wavfile.read(path)
    if d.dtype == np.int16:
        d = d.astype(np.float64) / 2 ** 15
    elif d.dtype == np.int32:
        d = d.astype(np.float64) / 2 ** 31
    else:
        d = d.astype(np.float64)
    if d.ndim == 1:
        d = d[:, None]
    return d


def spectral(d):
    out = []
    n = d.shape[0]
    win = np.hanning(n)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    for ch in range(d.shape[1]):
        x = d[:, ch]
        peak = float(np.abs(x).max())
        if peak < 1e-6:
            out.append({"dominant_hz": None, "rms_dbfs": None})
            continue
        sp = np.abs(np.fft.rfft(x * win))
        rms = float(np.sqrt(np.mean(x ** 2)))
        out.append({"dominant_hz": round(float(freqs[sp.argmax()]), 1),
                    "rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2)})
    return out


def align(a, b, max_lag=4096):
    """Return (a, b) trimmed to common support at the best integer lag of b
    relative to a, using their channel sums."""
    sa, sb = a.sum(axis=1), b.sum(axis=1)
    n = min(len(sa), len(sb), SR * 2)
    lags = np.arange(-max_lag, max_lag + 1)
    best_lag, best_c = 0, -1.0
    fa = sa[:n] - sa[:n].mean()
    fb = sb[:n] - sb[:n].mean()
    corr = np.correlate(fa, fb, mode="full")
    mid = len(corr) // 2
    lo, hi = mid - max_lag, mid + max_lag + 1
    best_lag = int(np.argmax(corr[lo:hi]) - max_lag)
    if best_lag > 0:
        a = a[best_lag:]
    elif best_lag < 0:
        b = b[-best_lag:]
    m = min(len(a), len(b))
    return a[:m], b[:m], best_lag


def err_metrics(ref, test):
    """ref/test: (n, ch). Raw and gain-matched error, per channel + overall."""
    m = min(len(ref), len(test))
    ref, test = ref[:m], test[:m]
    def db(x):
        return round(20 * math.log10(max(x, 1e-12)), 2)
    rr = float(np.sqrt(np.mean(ref ** 2)))
    er = float(np.sqrt(np.mean((ref - test) ** 2)))
    num = float(np.sum(ref * test))
    den = float(np.sum(test ** 2)) or 1e-12
    g = num / den
    eg = float(np.sqrt(np.mean((ref - g * test) ** 2)))
    per_ch = []
    for ch in range(ref.shape[1]):
        rc = float(np.sqrt(np.mean(ref[:, ch] ** 2)))
        ec = float(np.sqrt(np.mean((ref[:, ch] - test[:, ch]) ** 2)))
        per_ch.append({"ref_rms_dbfs": db(rc), "err_db_re_ref":
                       round(db(ec) - db(rc), 2) if rc > 1e-9 else None})
    # windowed error envelope (overall, raw)
    n_win = m // WIN
    env = []
    for w in range(n_win):
        s = slice(w * WIN, (w + 1) * WIN)
        rw = float(np.sqrt(np.mean(ref[s] ** 2)))
        ew = float(np.sqrt(np.mean((ref[s] - test[s]) ** 2)))
        env.append(round(db(ew) - db(rw), 2) if rw > 1e-9 else None)
    envv = [e for e in env if e is not None]
    return {
        "err_db_re_ref": round(db(er) - db(rr), 2),
        "gain_matched_err_db_re_ref": round(db(eg) - db(rr), 2),
        "optimal_gain_db": db(abs(g)),
        "per_channel": per_ch,
        "err_envelope_100ms_db": env,
        "err_envelope_median_db": round(float(np.median(envv)), 2) if envv
        else None,
        "err_envelope_p95_db": round(float(np.percentile(envv, 95)), 2)
        if envv else None,
    }


def energy_vector_error(d, gt_blocks_per_obj, spk=SPK_474):
    """Single-object files only: windowed energy-vector direction vs GT."""
    vecs = []
    for s in spk:
        if s is None:
            vecs.append(None)
            continue
        a, e = math.radians(s[0]), math.radians(s[1])
        vecs.append(np.array([-math.sin(a) * math.cos(e),
                              math.cos(a) * math.cos(e), math.sin(e)]))
    n_win = d.shape[0] // WIN
    errs = []
    for w in range(n_win):
        t_mid = (w + 0.5) * WIN / SR
        seg = d[w * WIN:(w + 1) * WIN]
        en = np.mean(seg ** 2, axis=0)
        v = np.zeros(3)
        tot = 0.0
        for ch, sv in enumerate(vecs):
            if sv is None:
                continue
            v += en[ch] * sv
            tot += en[ch]
        if tot < 1e-12:
            errs.append(None)
            continue
        v /= np.linalg.norm(v) + 1e-12
        gt = None
        for b in gt_blocks_per_obj:
            if b["rtime"] <= t_mid <= b["rtime"] + b["duration"] + 1e-9:
                gt = b
                break
        if gt is None:
            gt = gt_blocks_per_obj[-1]
        a, e = math.radians(gt["az"]), math.radians(gt["el"])
        gv = np.array([-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e),
                       math.sin(e)])
        errs.append(round(math.degrees(
            math.acos(float(np.clip(np.dot(v, gv), -1, 1)))), 1))
    vv = [e for e in errs if e is not None]
    return {"angular_err_deg_per_100ms": errs,
            "angular_err_median_deg": round(float(np.median(vv)), 1) if vv
            else None,
            "angular_err_p95_deg": round(float(np.percentile(vv, 95)), 1)
            if vv else None}


def ebur128(path):
    r = subprocess.run([FF, "-hide_banner", "-nostats", "-i", path,
                        "-filter_complex", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", r.stderr)
    tp = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", r.stderr)
    return (float(m[-1]) if m else None, float(tp[-1]) if tp else None)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    return r.returncode, (r.stderr or r.stdout).strip().splitlines()[-3:]


def ear_render(name, layout, cache={}):
    key = (name, layout)
    if key in cache:
        return cache[key]
    sys_name = LAYOUTS[layout][0]
    out = os.path.join(OUT, "ear", f"{name}_{layout.replace('.', '')}.wav")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if not os.path.exists(out):
        rc, tail = run([EAR, "-s", sys_name, "--enable-block-duration-fix",
                        f"{CORPUS}/{name}.wav", out])
        if rc != 0 or not os.path.exists(out):
            cache[key] = (None, tail)
            return cache[key]
    cache[key] = (out, None)
    return cache[key]


def main():
    os.makedirs(os.path.join(OUT, "iamf"), exist_ok=True)
    report = []
    for entry in INGEST_RESULTS:
        if not entry["ok"] or entry.get("importance_threshold") not in (None, 0):
            continue
        name = entry["corpus_file"]
        profile = entry["profile"]
        meta = MANIFEST["files"][name]
        for outp in entry["outputs"]:
            iamf_path = os.path.join(INGEST, outp["file"])
            for layout in layouts_for(meta):
                tag = f"{name}__{profile}__{layout.replace('.', '')}"
                rec = {"corpus_file": name, "profile": profile,
                       "layout": layout, "iamf": outp["file"]}
                dec_wav = os.path.join(OUT, "iamf", f"{tag}.wav")
                if not os.path.exists(dec_wav):
                    rc, tail = run([DEC, f"--input_filename={iamf_path}",
                                    f"--output_filename={dec_wav}",
                                    f"--output_layout={layout}"])
                    if rc != 0 or not os.path.exists(dec_wav):
                        rec["decode"] = {"ok": False, "stderr_tail": tail}
                        report.append(rec)
                        continue
                rec["decode"] = {"ok": True}
                d_iamf = read_wav(dec_wav)
                rec["iamf_spectral"] = spectral(d_iamf)
                il, tp = ebur128(dec_wav)
                rec["iamf_loudness"] = {"integrated_lufs": il,
                                        "true_peak_dbtp": tp}
                ear_wav, ear_err = ear_render(name, layout)
                if ear_wav is None:
                    rec["ear"] = {"ok": False, "stderr_tail": ear_err}
                else:
                    d_ear = read_wav(ear_wav)
                    rec["ear"] = {"ok": True}
                    rec["ear_spectral"] = spectral(d_ear)
                    eil, etp = ebur128(ear_wav)
                    rec["ear_loudness"] = {"integrated_lufs": eil,
                                           "true_peak_dbtp": etp}
                    if il is not None and eil is not None:
                        rec["loudness_delta_lu"] = round(il - eil, 2)
                    a, b, lag = align(d_ear, d_iamf)
                    if a.shape[1] == b.shape[1]:
                        rec["align_lag"] = lag
                        rec["error"] = err_metrics(a, b)
                    else:
                        rec["error"] = {
                            "channel_mismatch": [a.shape[1], b.shape[1]]}
                if (layout == "7.1.4" and meta.get("kind") == "objects"
                        and meta.get("channels") == 1):
                    blocks = meta["tracks"][0].get("blocks") or \
                        [{"rtime": 0.0, "duration": MANIFEST["duration_s"],
                          **{k: meta["tracks"][0].get(k, 0) for k in ()}}]
                    if meta["tracks"][0].get("blocks"):
                        rec["energy_vector_iamf"] = energy_vector_error(
                            d_iamf, blocks)
                        if ear_wav is not None:
                            rec["energy_vector_ear"] = energy_vector_error(
                                read_wav(ear_wav), blocks)
                report.append(rec)
                e = rec.get("error", {})
                print(f"{tag:44s} err={e.get('err_db_re_ref')} "
                      f"gm={e.get('gain_matched_err_db_re_ref')} "
                      f"dLU={rec.get('loudness_delta_lu')}")
        # incremental save
        with open(os.path.join(OUT, "fidelity_report.json"), "w") as f:
            json.dump(report, f, indent=1)
    print(f"\n{len(report)} measurements -> {OUT}/fidelity_report.json")


if __name__ == "__main__":
    main()
