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
# 0+5+0 (BS.2051 System B), same channel order convention: L R C LFE Ls Rs.
# Verified against the corpus's own spectral ground truth: rendering
# cd_bed_5dot1 through EAR at 0+5+0 leaves each identifier tone dominant in
# its own output channel (identity mapping, 73.5-133.0 dB dominance), and
# each bed channel's banded energy vector lands on its speaker to 0.0 deg.
SPK_050 = [(30, 0), (-30, 0), (0, 0), None, (110, 0), (-110, 0)]
# Layouts the analytic energy-vector metric is defined on.
#
# 0+2+0 is DELIBERATELY ABSENT. Two front speakers at +/-30 span only the
# front arc, so the energy vector cannot represent a rear-authored object at
# all: measured on dlb_obj_static4 x 2.0 x EAR, the az 180 object scores
# 180.0 deg and the az +/-90 objects 60.0 deg. Those are downmix facts, not
# conversion loss, and emitting them as "angular error" would read as the
# latter. Stereo error stays the business of err_metrics(), which is
# renderer-vs-renderer and well posed there.
SPK_BY_LAYOUT = {"7.1.4": SPK_474, "5.1": SPK_050}


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


def _unit(az_deg, el_deg):
    a, e = math.radians(az_deg), math.radians(el_deg)
    return np.array([-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e),
                     math.sin(e)])


def _gt_lookup(blocks, jump_authored):
    """Return f(t) -> (az, el) implementing the manifest's declared
    block_convention.

    The manifest states: "audioBlockFormat position = ground-truth trajectory
    value at the block END time (BS.2076 interpolate-to-end)". So for an
    ordinarily-authored object the trajectory INTERPOLATES toward each block's
    position, and sampling the containing block's value as if it were held for
    the block's duration overstates the error. Measured (x 7.1.4 x EAR,
    per-object banded metric):

        dlb_obj_auto_slow  (10 blocks, interpolated)  held 14.2-24.4 deg
                                                      interp  6.2-8.6 deg
        dlb_obj_jump       (10 blocks, jumpPosition)  held  4.3-6.2 deg
                                                      interp 14.9-23.3 deg

    A double dissociation: each model wins on exactly the fixture whose
    authoring convention it matches, by 8-19 deg. jumpPosition=1 means "do not
    interpolate", so held is correct there and only there. Grids finer than the
    100 ms window (auto_dense 50 ms, auto_ultra 10 ms) are insensitive to the
    choice (delta 0.0 deg on all four objects of each).
    """
    if not blocks:
        return None
    if jump_authored:
        def held(t):
            for b in blocks:
                if b["rtime"] <= t <= b["rtime"] + b["duration"] + 1e-9:
                    return b["az"], b["el"]
            return blocks[-1]["az"], blocks[-1]["el"]
        return held
    ts = [blocks[0]["rtime"]] + [b["rtime"] + b["duration"] for b in blocks]
    azs = np.unwrap(np.radians([blocks[0]["az"]] + [b["az"] for b in blocks]))
    els = np.radians([blocks[0]["el"]] + [b["el"] for b in blocks])
    ts = np.array(ts)

    def interp(t):
        return (math.degrees(float(np.interp(t, ts, azs))),
                math.degrees(float(np.interp(t, ts, els))))
    return interp


def energy_vector_error_v2(d, blocks, spk, band_hz, jump_authored=False,
                           band_width_hz=60.0, rel_floor=1e-6):
    """Per-object windowed energy-vector direction vs analytic ground truth.

    Generalises energy_vector_error() off single-object files. Per-speaker
    energy is taken in a narrow band around this object's identifier tone
    instead of broadband, which isolates one object inside a multi-object
    speaker render. The corpus's WP1 spectral-identity convention gives every
    object a unique sine (313 + 139k Hz, minimum separation 139.0 Hz = 13.9
    FFT bins at this window length), so the bands do not overlap.

    Measured separation quality (dlb_obj_static4 x 7.1.4 x EAR, four static
    objects at az 0 / 90 / -90 / 180): matched object-to-own-GT scores 0.0 deg
    median AND p95 on all four; scoring each object's band against another
    object's GT scores >= 20 deg on 12 of 12 mismatched pairs, at exactly the
    authored angular separations. Insensitive to band width over 40/60/90 Hz.

    NB the returned angle is NOT a pure conversion-loss figure on a reduced
    layout: a renderer's own panning spread contributes, and that contribution
    is layout-dependent. Read it against the same metric on the reference
    (EAR) render of the same fixture, which is what the caller emits.
    """
    vecs = [None if s is None else _unit(s[0], s[1]) for s in spk]
    gt = _gt_lookup(blocks, jump_authored)
    if gt is None:
        return None
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    sel = np.abs(freqs - band_hz) <= band_width_hz / 2.0
    han = np.hanning(WIN)
    n_win = d.shape[0] // WIN
    ens = []
    for w in range(n_win):
        seg = d[w * WIN:(w + 1) * WIN]
        sp = np.fft.rfft(seg * han[:, None], axis=0)
        ens.append(np.sum(np.abs(sp[sel]) ** 2, axis=0))
    # Relative floor, so gain-automated and importance-culled objects drop out
    # of the median instead of contributing a direction read off noise.
    peak = max((float(e.sum()) for e in ens), default=0.0)
    floor = peak * rel_floor
    errs = []
    for w in range(n_win):
        en = ens[w]
        v = np.zeros(3)
        tot = 0.0
        for ch, sv in enumerate(vecs):
            if sv is None or ch >= len(en):
                continue
            v += en[ch] * sv
            tot += en[ch]
        if tot <= floor or tot < 1e-30:
            errs.append(None)
            continue
        v /= np.linalg.norm(v) + 1e-12
        gaz, gel = gt((w + 0.5) * WIN / SR)
        errs.append(round(math.degrees(math.acos(float(
            np.clip(np.dot(v, _unit(gaz, gel)), -1, 1)))), 1))
    vv = [e for e in errs if e is not None]
    if not vv:
        return None
    return {"angular_err_median_deg": round(float(np.median(vv)), 1),
            "angular_err_p95_deg": round(float(np.percentile(vv, 95)), 1),
            "n_windows_scored": len(vv)}


def energy_vector_objects(meta, layout, d_iamf, d_ear):
    """B3-2a/b/c: the analytic anchor for every object of an eligible record.

    Returns None when the record is not eligible. Emits the metric for BOTH
    renders, because the reference render's value is the achievable floor for
    that (fixture, layout, object) and the difference is the quantity of
    interest. EAR is not uniformly zero once the gate is off single static
    front objects: measured 0.0-13.2 deg on 7.1.4 and 0.0-60.0 deg on 5.1,
    which is the renderer's panning spread, not metric error (bed channels,
    which are true point sources at speakers, score 0.0 deg on every non-LFE
    channel of both layouts).
    """
    spk = SPK_BY_LAYOUT.get(layout)
    if spk is None or meta.get("kind") not in ("objects", "mixed_bed_objects"):
        return None
    out = []
    for i, t in enumerate(meta.get("tracks") or []):
        if t.get("kind") != "object" or not t.get("blocks"):
            continue
        if t.get("freq_hz") is None:
            continue
        row = {"track_index": i, "freq_hz": t["freq_hz"],
               "jump_authored": bool(t.get("jump_authored"))}
        for tag, d in (("iamf", d_iamf), ("ear", d_ear)):
            if d is None:
                continue
            r = energy_vector_error_v2(d, t["blocks"], spk, t["freq_hz"],
                                       bool(t.get("jump_authored")))
            if r is not None:
                row[tag] = r
        if "iamf" in row and "ear" in row:
            row["excess_median_deg"] = round(
                row["iamf"]["angular_err_median_deg"]
                - row["ear"]["angular_err_median_deg"], 1)
        out.append(row)
    if not out:
        return None
    res = {"spk_layout": layout, "band_width_hz": 60.0, "objects": out}
    for tag in ("iamf", "ear"):
        vals = [o[tag]["angular_err_median_deg"] for o in out if tag in o]
        if vals:
            res[f"{tag}_median_deg"] = round(float(np.median(vals)), 1)
    if "iamf_median_deg" in res and "ear_median_deg" in res:
        res["excess_median_deg"] = round(
            res["iamf_median_deg"] - res["ear_median_deg"], 1)
    res["n_objects"] = len(out)
    return res


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
                # Widened analytic anchor (B3-2a/b/c). Strictly additive: the
                # legacy keys above keep their code path and their recorded
                # values (dlb_obj_static1 x 7.1.4: IAMF 2.3/2.3, EAR 0.0/0.0).
                ev = energy_vector_objects(
                    meta, layout, d_iamf,
                    read_wav(ear_wav) if ear_wav is not None else None)
                if ev is not None:
                    rec["energy_vector"] = ev
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
