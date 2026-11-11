#!/usr/bin/env python3
# adm_corpus_gen.py — synthetic ADM BWF corpus generator for the WP3
# ADM->IAMF conversion-fidelity study.
#
# Original work (WP3, IAMF project). No third-party code derived. Follows the
# WP1 spectral-identity convention: every track carries a unique identifier
# sine so downstream routing/loss/duplication is detectable by FFT alone.
# Ground truth (positions, trajectories, gains, loudness metadata) is emitted
# as a machine-readable manifest next to the WAVs.
#
# The corpus spans the two ingest families implemented by iamf-tools'
# adm_to_user_metadata (read, not derived — behavioral surface only):
#   family "cd"  — BS.2094 common-definitions ADM (beds, HOA, binaural),
#                  selected by audioPackFormatID; no dbmd chunk.
#   family "dlb" — "Dolby ADM" mode, triggered by the presence of a dbmd
#                  chunk: user-defined packs, DirectSpeakers beds with
#                  RoomCentric* channel names, Objects (1 ch/pack/track each)
#                  with cartesian block positions.
# Each file records expectations (ok/reject per profile) to be checked, not
# assumed, by the ingest runner.
#
# Usage: adm_corpus_gen.py [outdir]

import json
import math
import os
import struct
import sys

import numpy as np
from scipy.special import lpmv

SR = 48000
DUR_S = 10.0
N = int(SR * DUR_S)
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("SENTINEL_TOOLCHAIN", "/home/claude/iamf-wp1"), "adm-corpus")

DEF_AMP_DBFS = -18.0
LOW_AMP_DBFS = -24.0  # for high object counts (3OA fold headroom)


def amp(dbfs):
    return 10.0 ** (dbfs / 20.0)


def track_freq(k, is_lfe=False):
    """Unique non-harmonic identifier frequency per track index."""
    if is_lfe:
        return 40.0
    return 313.0 + 139.0 * k  # k<=27 -> max 4066 Hz, all distinct, non-harmonic


def sine(freq, amplitude, fade_ms=20.0):
    t = np.arange(N) / SR
    sig = amplitude * np.sin(2 * np.pi * freq * t)
    k = int(SR * fade_ms / 1000.0)
    env = np.ones(N)
    env[:k] = np.linspace(0.0, 1.0, k)
    env[-k:] = np.linspace(1.0, 0.0, k)
    return sig * env


def sn3d_acn(order, az_rad, el_rad):
    """Real spherical harmonics, ACN/SN3D, Condon-Shortley cancelled."""
    x = np.sin(el_rad)
    out = np.empty(((order + 1) ** 2, len(az_rad)))
    for l in range(order + 1):
        for m in range(-l, l + 1):
            acn = l * l + l + m
            am = abs(m)
            norm = math.sqrt((2.0 if am > 0 else 1.0)
                             * math.factorial(l - am) / math.factorial(l + am))
            leg = lpmv(am, l, x) * ((-1.0) ** am)
            if m > 0:
                ang = np.cos(am * az_rad)
            elif m < 0:
                ang = np.sin(am * az_rad)
            else:
                ang = np.ones_like(az_rad)
            out[acn] = norm * leg * ang
    return out


# --------------------------------------------------------------------------
# BW64/RIFF writer with bext/chna/axml/dbmd chunks
# --------------------------------------------------------------------------

def chunk(ckid, payload):
    b = ckid.encode("ascii") + struct.pack("<I", len(payload)) + payload
    if len(payload) % 2:
        b += b"\x00"
    return b


def chna_chunk(entries):
    """entries: list of (track_num_1based, uid, track_ref, pack_ref)."""
    payload = struct.pack("<HH", len(entries), len(entries))
    for num, uid, tref, pref in entries:
        payload += struct.pack("<H", num)
        payload += uid.encode("ascii").ljust(12, b"\x00")
        payload += tref.encode("ascii").ljust(14, b"\x00")
        payload += pref.encode("ascii").ljust(11, b"\x00")
        payload += b"\x00"
    return chunk("chna", payload)


def bext_chunk():
    payload = bytearray(602)
    desc = b"WP3 synthetic ADM corpus"
    payload[0:len(desc)] = desc
    payload[320:352] = b"2026-07-21".ljust(10)[:10] + b"00:00:00".ljust(8)[:8] + bytes(14)
    payload[352:354] = struct.pack("<H", 2)  # version 2 (BS.2076 axml expected)
    return chunk("bext", bytes(payload))


def dbmd_chunk():
    # iamf-tools only checks for the chunk's existence to select Dolby-ADM
    # handling; content is a placeholder version header + zero payload.
    return chunk("dbmd", struct.pack("<I", 0x01000000) + bytes(28))


def write_bwf(path, data, axml_xml, chna_entries, dolby=False, bits=24):
    """data: float array shape (N, ch)."""
    n, ch = data.shape
    clipped = np.clip(data, -1.0, 1.0 - 2.0 ** -(bits - 1))
    if bits == 24:
        ints = np.round(clipped * (2 ** 23)).astype(np.int32)
        b = ints.astype("<i4").tobytes()
        raw = np.frombuffer(b, dtype=np.uint8).reshape(-1, 4)[:, :3].tobytes()
        bytes_per = 3
    elif bits == 16:
        ints = np.round(clipped * (2 ** 15)).astype(np.int16)
        raw = ints.astype("<i2").tobytes()
        bytes_per = 2
    else:
        raise ValueError(bits)
    fmt = struct.pack("<HHIIHH", 1, ch, SR, SR * ch * bytes_per,
                      ch * bytes_per, bits)
    body = chunk("fmt ", fmt) + bext_chunk()
    if dolby:
        body += dbmd_chunk()
    if chna_entries:
        body += chna_chunk(chna_entries)
    if axml_xml is not None:
        body += chunk("axml", axml_xml.encode("utf-8"))
    body += chunk("data", raw)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)


# --------------------------------------------------------------------------
# ADM XML builders
# --------------------------------------------------------------------------

XML_HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ebuCoreMain xmlns="urn:ebu:metadata-schema:ebuCore_2016">'
            '<coreMetadata><format>'
            '<audioFormatExtended version="ITU-R_BS.2076-2">\n')
XML_TAIL = '</audioFormatExtended></format></coreMetadata></ebuCoreMain>\n'

# Common-definitions (BS.2094) map, extracted from the published common
# definitions XML. Channel lists are in canonical pack order.
CD = {
    "stereo":   ("AP_00010002", ["AT_00010001_01", "AT_00010002_01"]),
    "5dot1":    ("AP_00010003", ["AT_00010001_01", "AT_00010002_01",
                                 "AT_00010003_01", "AT_00010004_01",
                                 "AT_00010005_01", "AT_00010006_01"]),
    "5dot1dot2": ("AP_00010004", ["AT_00010001_01", "AT_00010002_01",
                                  "AT_00010003_01", "AT_00010004_01",
                                  "AT_00010005_01", "AT_00010006_01",
                                  "AT_0001000d_01", "AT_0001000f_01"]),
    "5dot1dot4": ("AP_00010005", ["AT_00010001_01", "AT_00010002_01",
                                  "AT_00010003_01", "AT_00010004_01",
                                  "AT_00010005_01", "AT_00010006_01",
                                  "AT_0001000d_01", "AT_0001000f_01",
                                  "AT_00010010_01", "AT_00010012_01"]),
    "7dot1":    ("AP_0001000f", ["AT_00010001_01", "AT_00010002_01",
                                 "AT_00010003_01", "AT_00010004_01",
                                 "AT_0001000a_01", "AT_0001000b_01",
                                 "AT_0001001c_01", "AT_0001001d_01"]),
    "7dot1dot4": ("AP_00010017", ["AT_00010001_01", "AT_00010002_01",
                                  "AT_00010003_01", "AT_00010004_01",
                                  "AT_0001000a_01", "AT_0001000b_01",
                                  "AT_0001001c_01", "AT_0001001d_01",
                                  "AT_00010022_01", "AT_00010023_01",
                                  "AT_0001001e_01", "AT_0001001f_01"]),
    "foa": ("AP_00040001", [f"AT_000400{i + 1:02x}_01" for i in range(4)]),
    "3oa": ("AP_00040003", [f"AT_000400{i + 1:02x}_01" for i in range(16)]),
    "binaural": ("AP_00050001", ["AT_00050001_01", "AT_00050002_01"]),
}
# LFE track index within CD bed layouts (0-based), for identifier freq choice.
CD_LFE_IDX = {"5dot1": 3, "5dot1dot2": 3, "5dot1dot4": 3, "7dot1": 3,
              "7dot1dot4": 3}


def t_hms(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:08.5f}"


def loudness_xml(integrated=None, max_true_peak=None, dialogue=None):
    if integrated is None:
        return ""
    parts = [f"<integratedLoudness>{integrated:.2f}</integratedLoudness>"]
    if max_true_peak is not None:
        parts.append(f"<maxTruePeak>{max_true_peak:.2f}</maxTruePeak>")
    if dialogue is not None:
        parts.append(f"<dialogueLoudness>{dialogue:.2f}</dialogueLoudness>")
    return "<loudnessMetadata>" + "".join(parts) + "</loudnessMetadata>"


def programme_xml(pid, name, content_refs, pack_refs, loudness=""):
    refs = "".join(f"<audioContentIDRef>{c}</audioContentIDRef>"
                   for c in content_refs)
    prefs = "".join(f"<audioPackFormatIDRef>{p}</audioPackFormatIDRef>"
                    for p in pack_refs)
    return (f'<audioProgramme audioProgrammeID="{pid}" '
            f'audioProgrammeName="{name}" start="00:00:00.00000" '
            f'end="{t_hms(DUR_S)}">{loudness}{refs}{prefs}</audioProgramme>\n')


def content_xml(cid, name, object_refs):
    refs = "".join(f"<audioObjectIDRef>{o}</audioObjectIDRef>"
                   for o in object_refs)
    return (f'<audioContent audioContentID="{cid}" audioContentName="{name}">'
            f"{refs}</audioContent>\n")


def object_xml(oid, name, pack_ref, track_uid_refs, importance=None,
               gain=None):
    imp = f' importance="{importance}"' if importance is not None else ""
    g = f"<gain>{gain}</gain>" if gain is not None else ""
    body = f"<audioPackFormatIDRef>{pack_ref}</audioPackFormatIDRef>"
    body += "".join(f"<audioTrackUIDRef>{u}</audioTrackUIDRef>"
                    for u in track_uid_refs)
    return (f'<audioObject audioObjectID="{oid}" audioObjectName="{name}" '
            f'start="00:00:00.00000" duration="{t_hms(DUR_S)}"{imp}>'
            f"{g}{body}</audioObject>\n")


def track_uid_xml(uid, track_ref, pack_ref):
    return (f'<audioTrackUID UID="{uid}" sampleRate="{SR}" bitDepth="24">'
            f"<audioTrackFormatIDRef>{track_ref}</audioTrackFormatIDRef>"
            f"<audioPackFormatIDRef>{pack_ref}</audioPackFormatIDRef>"
            f"</audioTrackUID>\n")


def custom_pack_xml(pack_id, name, type_label, type_def, chan_ids):
    refs = "".join(f"<audioChannelFormatIDRef>{c}</audioChannelFormatIDRef>"
                   for c in chan_ids)
    return (f'<audioPackFormat audioPackFormatID="{pack_id}" '
            f'audioPackFormatName="{name}" typeLabel="{type_label}" '
            f'typeDefinition="{type_def}">{refs}</audioPackFormat>\n')


def block_xml_cart(bid_base, idx, rtime, dur, x, y, z, gain=None, jump=None):
    g = f"<gain>{gain:.6f}</gain>" if gain is not None else ""
    # BS.2076: the jumpPosition BOOLEAN is element CONTENT, and
    # interpolationLength is an optional ATTRIBUTE. There is no `switch`
    # attribute in ADM. The earlier `switch="1"` form left the element text
    # empty, so every conforming reader saw an unparseable bool
    # (EAR 2.1.x: "could not parse bool:") and refused the whole axml —
    # see doc 123 §5. The literal below matches EAR's own writer
    # (`jump_position_to_xml`: text = "1", attribute = "{:07.5f}").
    j = (f'<jumpPosition interpolationLength="0.00000">1</jumpPosition>'
         if jump else "")
    return (f'<audioBlockFormat audioBlockFormatID="{bid_base}_{idx + 1:08x}" '
            f'rtime="{t_hms(rtime)}" duration="{t_hms(dur)}">'
            f"<cartesian>1</cartesian>"
            f'<position coordinate="X">{x:.6f}</position>'
            f'<position coordinate="Y">{y:.6f}</position>'
            f'<position coordinate="Z">{z:.6f}</position>{g}{j}'
            f"</audioBlockFormat>")


def block_xml_sph(bid_base, idx, rtime, dur, az, el, dist):
    return (f'<audioBlockFormat audioBlockFormatID="{bid_base}_{idx + 1:08x}" '
            f'rtime="{t_hms(rtime)}" duration="{t_hms(dur)}">'
            f'<position coordinate="azimuth">{az:.4f}</position>'
            f'<position coordinate="elevation">{el:.4f}</position>'
            f'<position coordinate="distance">{dist:.4f}</position>'
            f"</audioBlockFormat>")


def custom_channel_xml(chan_id, name, type_label, type_def, blocks):
    return (f'<audioChannelFormat audioChannelFormatID="{chan_id}" '
            f'audioChannelFormatName="{name}" typeLabel="{type_label}" '
            f'typeDefinition="{type_def}">{"".join(blocks)}'
            f"</audioChannelFormat>\n")


def custom_stream_track_xml(stream_id, track_id, chan_id):
    return (f'<audioStreamFormat audioStreamFormatID="{stream_id}" '
            f'audioStreamFormatName="PCM_{chan_id}" formatLabel="0001" '
            f'formatDefinition="PCM">'
            f"<audioChannelFormatIDRef>{chan_id}</audioChannelFormatIDRef>"
            f"</audioStreamFormat>\n"
            f'<audioTrackFormat audioTrackFormatID="{track_id}" '
            f'audioTrackFormatName="PCM_{chan_id}" formatLabel="0001" '
            f'formatDefinition="PCM">'
            f"<audioStreamFormatIDRef>{stream_id}</audioStreamFormatIDRef>"
            f"</audioTrackFormat>\n")


# ADM cartesian speaker positions (Atmos-style room-centric cube) for Dolby
# DirectSpeakers beds; (x right, y front, z up).
DLB_SPEAKERS = {
    "RoomCentricLeft":              (-1.0, 1.0, 0.0, "M+030"),
    "RoomCentricRight":             (1.0, 1.0, 0.0, "M-030"),
    "RoomCentricCenter":            (0.0, 1.0, 0.0, "M+000"),
    "RoomCentricLFE":               (-1.0, 1.0, -1.0, "LFE1"),
    "RoomCentricLeftSurround":      (-1.0, -1.0, 0.0, "M+110"),
    "RoomCentricRightSurround":     (1.0, -1.0, 0.0, "M-110"),
    "RoomCentricLeftSideSurround":  (-1.0, 0.0, 0.0, "M+090"),
    "RoomCentricRightSideSurround": (1.0, 0.0, 0.0, "M-090"),
    "RoomCentricLeftRearSurround":  (-1.0, -1.0, 0.0, "M+135"),
    "RoomCentricRightRearSurround": (1.0, -1.0, 0.0, "M-135"),
    "RoomCentricLeftTopSurround":   (-1.0, 0.0, 1.0, "U+090"),
    "RoomCentricRightTopSurround":  (1.0, 0.0, 1.0, "U-090"),
    # 4-top variant channels (not in the importer's whitelist -> reject test)
    "RoomCentricLeftTopFront":      (-1.0, 1.0, 1.0, "U+045"),
    "RoomCentricRightTopFront":     (1.0, 1.0, 1.0, "U-045"),
    "RoomCentricLeftTopRear":       (-1.0, -1.0, 1.0, "U+135"),
    "RoomCentricRightTopRear":      (1.0, -1.0, 1.0, "U-135"),
}

DLB_BEDS = {
    "5dot1": ["RoomCentricLeft", "RoomCentricRight", "RoomCentricCenter",
              "RoomCentricLFE", "RoomCentricLeftSurround",
              "RoomCentricRightSurround"],
    "7dot1dot2": ["RoomCentricLeft", "RoomCentricRight", "RoomCentricCenter",
                  "RoomCentricLFE", "RoomCentricLeftSideSurround",
                  "RoomCentricRightSideSurround",
                  "RoomCentricLeftRearSurround",
                  "RoomCentricRightRearSurround",
                  "RoomCentricLeftTopSurround",
                  "RoomCentricRightTopSurround"],
    "7dot1dot4": ["RoomCentricLeft", "RoomCentricRight", "RoomCentricCenter",
                  "RoomCentricLFE", "RoomCentricLeftSideSurround",
                  "RoomCentricRightSideSurround",
                  "RoomCentricLeftRearSurround",
                  "RoomCentricRightRearSurround",
                  "RoomCentricLeftTopFront", "RoomCentricRightTopFront",
                  "RoomCentricLeftTopRear", "RoomCentricRightTopRear"],
}


# --------------------------------------------------------------------------
# Trajectories (ground truth, ADM polar convention: az deg CCW from front,
# el deg up, dist). Every trajectory below returns dist 1.0, so every object
# in the corpus sits at the reference distance; what sits further out is the
# Dolby beds' room-centric channels (|p| = 1, sqrt 2 or sqrt 3 on the cube).
# (The bound once written here, "dist in [0..~1.4]", was read as objects out
# to |p| ~ 1.4 -- s318 IA-0057 section 6.1; none are.)
# The cartesian form written for an object is plain spherical trig:
# x=-sin(az)cos(el)*d, y=cos(az)cos(el)*d, z=sin(el)*d. That is NOT the
# BS.2127-0 section 10.1 mapping between ADM's polar and Cartesian spaces
# (which puts (-1, 0, 0) at azimuth 70, not 90), so off the five mid-layer
# speaker directions a cartesian object here means, by the standard, a
# different direction from its polar ground truth (s324 IA-0076).
# --------------------------------------------------------------------------

def traj_circle(k_obj, n_obj):
    """Full horizontal circle over the file, phase-offset per object."""
    def f(t):
        az = (360.0 * t / DUR_S + k_obj * (360.0 / max(n_obj, 1))) % 360.0
        el = 45.0 * math.sin(2 * math.pi * t / DUR_S) if k_obj == n_obj - 1 \
            else 0.0
        return az, el, 1.0
    return f


def traj_static(az, el, dist=1.0):
    return lambda t: (az, el, dist)


def sph_to_cart(az, el, dist):
    a, e = math.radians(az), math.radians(el)
    return (-math.sin(a) * math.cos(e) * dist,
            math.cos(a) * math.cos(e) * dist,
            math.sin(e) * dist)


STATIC_POSITIONS = [  # spread over the sphere, dist 1.0 (az, el)
    (0.0, 0.0), (90.0, 0.0), (-90.0, 0.0), (180.0, 0.0),
    (45.0, 30.0), (-45.0, 30.0), (135.0, 30.0), (-135.0, 30.0),
    (30.0, 0.0), (-30.0, 0.0), (110.0, 0.0), (-110.0, 0.0),
    (0.0, 60.0), (90.0, 45.0), (-90.0, 45.0), (180.0, 45.0),
    (60.0, 15.0), (-60.0, 15.0), (150.0, 15.0), (-150.0, 15.0),
    (15.0, 45.0), (-15.0, 45.0), (75.0, -15.0), (-75.0, -15.0),
    (105.0, 30.0), (-105.0, 30.0), (165.0, -10.0), (-165.0, -10.0),
]


# --------------------------------------------------------------------------
# File builders
# --------------------------------------------------------------------------

manifest = {"sample_rate": SR, "duration_s": DUR_S,
            "signal_convention":
                "track k carries a unique sine at 313+139k Hz (LFE: 40 Hz), "
                "constant amplitude, 20 ms fades",
            "block_convention":
                "audioBlockFormat position = ground-truth trajectory value "
                "at the block END time (BS.2076 interpolate-to-end)",
            "files": {}}


def cd_track_entries(layout, uid_start=1):
    pack, tracks = CD[layout]
    ents, uids = [], []
    for i, tr in enumerate(tracks):
        uid = f"ATU_{uid_start + i:08d}"
        ents.append((uid_start + i, uid, tr, pack))
        uids.append(uid)
    return pack, tracks, ents, uids


def make_cd_bed(name, layout, loudness=None, programmes=None):
    pack, tracks, ents, uids = cd_track_entries(layout)
    nch = len(tracks)
    lfe = CD_LFE_IDX.get(layout)
    data = np.stack([sine(track_freq(k, k == lfe), amp(DEF_AMP_DBFS))
                     for k in range(nch)], axis=1)
    xml = XML_HEAD
    if programmes is None:
        programmes = [("APR_1001", "MainMix", loudness)]
    for pid, pname, ld in programmes:
        xml += programme_xml(pid, pname, ["ACO_1001"], [pack],
                             loudness_xml(*(ld or (None,))))
    xml += content_xml("ACO_1001", "Bed", ["AO_1001"])
    xml += object_xml("AO_1001", f"Bed_{layout}", pack, uids)
    for uid, (num, u, tr, pk) in zip(uids, ents):
        xml += track_uid_xml(uid, tr, pk)
    xml += XML_TAIL
    path = os.path.join(OUTDIR, f"{name}.wav")
    write_bwf(path, data, xml, ents)
    manifest["files"][name] = {
        "family": "cd", "kind": "bed", "layout": layout, "channels": nch,
        "pack": pack, "amp_dbfs": DEF_AMP_DBFS,
        "tracks": [{"index": k, "freq_hz": track_freq(k, k == lfe),
                    "is_lfe": k == lfe} for k in range(nch)],
        "loudness": loudness,
        "programmes": [{"id": p, "name": nm, "loudness": ld}
                       for p, nm, ld in programmes],
        "expect": {"base": "ok", "enhanced": "ok"},
    }


def make_cd_hoa(name, order):
    layout = "foa" if order == 1 else "3oa"
    pack, tracks, ents, uids = cd_track_entries(layout)
    nch = (order + 1) ** 2
    t = np.arange(N) / SR
    azA = 2 * np.pi * t / DUR_S
    sA = sine(440.0, amp(DEF_AMP_DBFS))
    azB = np.full_like(t, np.pi / 2)
    elB = np.full_like(t, np.pi / 4)
    sB = sine(880.0, amp(DEF_AMP_DBFS))
    mix = sn3d_acn(order, azA, np.zeros_like(t)) * sA \
        + sn3d_acn(order, azB, elB) * sB
    data = (mix / 2.0).T
    xml = XML_HEAD
    xml += programme_xml("APR_1001", "HOA", ["ACO_1001"], [pack])
    xml += content_xml("ACO_1001", "Scene", ["AO_1001"])
    xml += object_xml("AO_1001", f"HOA{order}", pack, uids)
    for uid, (num, u, tr, pk) in zip(uids, ents):
        xml += track_uid_xml(uid, tr, pk)
    xml += XML_TAIL
    write_bwf(os.path.join(OUTDIR, f"{name}.wav"), data, xml, ents)
    manifest["files"][name] = {
        "family": "cd", "kind": "hoa", "order": order, "channels": nch,
        "pack": pack, "amp_dbfs": DEF_AMP_DBFS, "convention": "ACN/SN3D",
        "sources": [{"id": "A", "freq_hz": 440.0,
                     "trajectory": "az 0->360 over file, el 0, dist 1"},
                    {"id": "B", "freq_hz": 880.0, "az_deg": 90.0,
                     "el_deg": 45.0}],
        "expect": {"base": "ok", "enhanced": "ok"},
    }


def make_cd_binaural(name):
    pack, tracks, ents, uids = cd_track_entries("binaural")
    data = np.stack([sine(track_freq(0), amp(DEF_AMP_DBFS)),
                     sine(track_freq(1), amp(DEF_AMP_DBFS))], axis=1)
    xml = XML_HEAD
    xml += programme_xml("APR_1001", "BinauralMix", ["ACO_1001"], [pack])
    xml += content_xml("ACO_1001", "Binaural", ["AO_1001"])
    xml += object_xml("AO_1001", "BinauralPair", pack, uids)
    for uid, (num, u, tr, pk) in zip(uids, ents):
        xml += track_uid_xml(uid, tr, pk)
    xml += XML_TAIL
    write_bwf(os.path.join(OUTDIR, f"{name}.wav"), data, xml, ents)
    manifest["files"][name] = {
        "family": "cd", "kind": "binaural", "channels": 2, "pack": pack,
        "amp_dbfs": DEF_AMP_DBFS,
        "tracks": [{"index": k, "freq_hz": track_freq(k)} for k in range(2)],
        "expect": {"base": "ok", "enhanced": "ok"},
    }


def make_cd_mixed_bed_hoa(name):
    pack_b, tracks_b, ents_b, uids_b = cd_track_entries("5dot1", 1)
    pack_h, tracks_h, ents_h, uids_h = cd_track_entries("foa", 7)
    lfe = CD_LFE_IDX["5dot1"]
    bed = np.stack([sine(track_freq(k, k == lfe), amp(DEF_AMP_DBFS))
                    for k in range(6)], axis=1)
    t = np.arange(N) / SR
    sA = sine(440.0, amp(DEF_AMP_DBFS))
    foa = (sn3d_acn(1, 2 * np.pi * t / DUR_S, np.zeros_like(t)) * sA / 2.0).T
    data = np.concatenate([bed, foa], axis=1)
    xml = XML_HEAD
    xml += programme_xml("APR_1001", "BedPlusScene", ["ACO_1001", "ACO_1002"],
                         [pack_b, pack_h])
    xml += content_xml("ACO_1001", "Bed", ["AO_1001"])
    xml += content_xml("ACO_1002", "Scene", ["AO_1002"])
    xml += object_xml("AO_1001", "Bed_5dot1", pack_b, uids_b)
    xml += object_xml("AO_1002", "FOA", pack_h, uids_h)
    for uid, (num, u, tr, pk) in zip(uids_b + uids_h, ents_b + ents_h):
        xml += track_uid_xml(uid, tr, pk)
    xml += XML_TAIL
    write_bwf(os.path.join(OUTDIR, f"{name}.wav"), data, xml,
              ents_b + ents_h)
    manifest["files"][name] = {
        "family": "cd", "kind": "mixed_bed_hoa", "channels": 10,
        "amp_dbfs": DEF_AMP_DBFS,
        "elements": [{"kind": "bed", "layout": "5dot1", "tracks": 6},
                     {"kind": "hoa", "order": 1, "tracks": 4}],
        "bed_tracks": [{"index": k, "freq_hz": track_freq(k, k == lfe)}
                       for k in range(6)],
        "expect": {"base": "ok", "enhanced": "ok"},
    }


def make_cd_userdef_pack(name):
    """User-defined DirectSpeakers pack (quad) -> expect reject."""
    nch = 4
    chan_ids = [f"AC_0001{0x1000 + i + 1:04x}" for i in range(nch)]
    track_ids = [f"AT_0001{0x1000 + i + 1:04x}_01" for i in range(nch)]
    stream_ids = [f"AS_0001{0x1000 + i + 1:04x}" for i in range(nch)]
    pack = "AP_00011001"
    quad = [("QuadL", (-1, 1, 0)), ("QuadR", (1, 1, 0)),
            ("QuadLs", (-1, -1, 0)), ("QuadRs", (1, -1, 0))]
    xml = XML_HEAD
    xml += programme_xml("APR_1001", "Quad", ["ACO_1001"], [pack])
    xml += content_xml("ACO_1001", "Quad", ["AO_1001"])
    uids = [f"ATU_{i + 1:08d}" for i in range(nch)]
    xml += object_xml("AO_1001", "QuadBed", pack, uids)
    xml += custom_pack_xml(pack, "Quad", "0001", "DirectSpeakers", chan_ids)
    for i, (cn, (x, y, z)) in enumerate(quad):
        blk = block_xml_cart(f"AB_0001{0x1000 + i + 1:04x}", 0, 0.0, DUR_S,
                             x, y, z)
        blk = blk.replace("</audioBlockFormat>",
                          f"<speakerLabel>{cn}</speakerLabel>"
                          f"</audioBlockFormat>")
        xml += custom_channel_xml(chan_ids[i], cn, "0001", "DirectSpeakers",
                                  [blk])
        xml += custom_stream_track_xml(stream_ids[i], track_ids[i],
                                       chan_ids[i])
    for i, uid in enumerate(uids):
        xml += track_uid_xml(uid, track_ids[i], pack)
    xml += XML_TAIL
    data = np.stack([sine(track_freq(k), amp(DEF_AMP_DBFS))
                     for k in range(nch)], axis=1)
    ents = [(i + 1, uids[i], track_ids[i], pack) for i in range(nch)]
    write_bwf(os.path.join(OUTDIR, f"{name}.wav"), data, xml, ents)
    manifest["files"][name] = {
        "family": "cd", "kind": "userdef_pack_reject", "channels": nch,
        "amp_dbfs": DEF_AMP_DBFS,
        "expect": {"base": "reject", "enhanced": "reject"},
        "expect_reason": "user-defined pack not under common definitions",
    }


def dlb_objects_xml_and_data(name, objs, beds=(), importance=None,
                             spherical=False, obj_gain=None, amp_dbfs=None,
                             bits=24):
    """objs: list of dicts {name, traj(t)->az,el,dist, blocks:[(rtime,dur)],
    gains: optional per-block linear gain, jump: bool}.
    beds: list of bed layout names from DLB_BEDS. Bed channels precede
    object channels in the WAV. Returns nothing; writes file + manifest."""
    a = amp(amp_dbfs if amp_dbfs is not None else DEF_AMP_DBFS)
    chans, xml_channels, xml_packs, xml_streams = [], [], [], []
    xml_objects, xml_uids, ents, contents = [], [], [], []
    track_no = 0
    uid_no = 0
    manifest_entries = []

    for b_i, bed in enumerate(beds):
        chan_names = DLB_BEDS[bed]
        pack = f"AP_0001{0x1100 + b_i:04x}"
        chan_ids, track_ids = [], []
        for c_i, cn in enumerate(chan_names):
            idx = 0x1100 + b_i * 0x20 + c_i
            cid, tid, sid = (f"AC_0001{idx:04x}", f"AT_0001{idx:04x}_01",
                             f"AS_0001{idx:04x}")
            x, y, z, spk = DLB_SPEAKERS[cn]
            if "labelonly" in name:
                blk = (f'<audioBlockFormat audioBlockFormatID='
                       f'"AB_0001{idx:04x}_00000001" rtime="{t_hms(0)}" '
                       f'duration="{t_hms(DUR_S)}">'
                       f"<speakerLabel>{spk}</speakerLabel>"
                       f"</audioBlockFormat>")
            else:
                blk = block_xml_cart(f"AB_0001{idx:04x}", 0, 0.0, DUR_S,
                                     x, y, z)
                blk = blk.replace("</audioBlockFormat>",
                                  f"<speakerLabel>{spk}</speakerLabel>"
                                  f"</audioBlockFormat>")
            xml_channels.append(custom_channel_xml(cid, cn, "0001",
                                                   "DirectSpeakers", [blk]))
            xml_streams.append(custom_stream_track_xml(sid, tid, cid))
            chan_ids.append(cid)
            track_ids.append(tid)
        xml_packs.append(custom_pack_xml(pack, f"Bed_{bed}", "0001",
                                         "DirectSpeakers", chan_ids))
        uids = []
        for tid in track_ids:
            uid_no += 1
            uid = f"ATU_{uid_no:08d}"
            uids.append(uid)
            ents.append((uid_no, uid, tid, pack))
            xml_uids.append(track_uid_xml(uid, tid, pack))
        oid = f"AO_{1000 + len(xml_objects) + 1}"
        xml_objects.append(object_xml(oid, f"Bed_{bed}", pack, uids))
        contents.append(oid)
        is_lfe = ["LFE" in c for c in chan_names]
        for c_i, cn in enumerate(chan_names):
            chans.append(sine(track_freq(track_no, is_lfe[c_i]), a))
            manifest_entries.append({
                "index": track_no, "kind": "bed_channel", "bed": bed,
                "channel": cn, "freq_hz": track_freq(track_no, is_lfe[c_i]),
                "is_lfe": is_lfe[c_i],
                "position_xyz": list(DLB_SPEAKERS[cn][:3]),
                "label_only_blocks": "labelonly" in name})
            track_no += 1

    for o_i, obj in enumerate(objs):
        idx = 0x1001 + o_i
        pack = f"AP_0003{idx:04x}"
        cid, tid, sid = (f"AC_0003{idx:04x}", f"AT_0003{idx:04x}_01",
                         f"AS_0003{idx:04x}")
        blocks = []
        gt_blocks = []
        for b_i, (rt, du) in enumerate(obj["blocks"]):
            az, el, dist = obj["traj"](rt + du)  # value at block end
            g = (obj.get("gains") or [None] * len(obj["blocks"]))[b_i]
            if spherical:
                blocks.append(block_xml_sph(f"AB_0003{idx:04x}", b_i, rt, du,
                                            az, el, dist))
            else:
                x, y, z = sph_to_cart(az, el, dist)
                blocks.append(block_xml_cart(f"AB_0003{idx:04x}", b_i, rt, du,
                                             x, y, z, gain=g,
                                             jump=obj.get("jump")))
            gt_blocks.append({"rtime": rt, "duration": du, "az": az,
                              "el": el, "dist": dist, "gain": g})
        xml_channels.append(custom_channel_xml(cid, obj["name"], "0003",
                                               "Objects", blocks))
        xml_streams.append(custom_stream_track_xml(sid, tid, cid))
        xml_packs.append(custom_pack_xml(pack, obj["name"], "0003",
                                         "Objects", [cid]))
        uid_no += 1
        uid = f"ATU_{uid_no:08d}"
        ents.append((uid_no, uid, tid, pack))
        xml_uids.append(track_uid_xml(uid, tid, pack))
        oid = f"AO_{1000 + len(xml_objects) + 1}"
        imp = importance[o_i] if importance else None
        og = obj_gain if (obj_gain is not None and o_i == 0) else None
        xml_objects.append(object_xml(oid, obj["name"], pack, [uid],
                                      importance=imp, gain=og))
        contents.append(oid)
        chans.append(sine(track_freq(track_no), a))
        manifest_entries.append({
            "index": track_no, "kind": "object", "name": obj["name"],
            "freq_hz": track_freq(track_no), "importance": imp,
            "object_gain": og, "spherical_authored": spherical,
            "jump_authored": bool(obj.get("jump")),
            "trajectory": obj.get("traj_desc", "static"),
            "blocks": gt_blocks})
        track_no += 1

    xml = XML_HEAD
    xml += programme_xml("APR_1001", name, ["ACO_1001"],
                         [p.split('"')[1] for p in []] or [])
    # programme pack refs: list every pack (reference layout is informative)
    xml = xml.replace("</audioProgramme>",
                      "".join(f"<audioPackFormatIDRef>{e}"
                              f"</audioPackFormatIDRef>"
                              for e in [pk.split('"')[1]
                                        for pk in xml_packs]) +
                      "</audioProgramme>", 1)
    xml += content_xml("ACO_1001", "All", contents)
    xml += "".join(xml_objects) + "".join(xml_packs)
    xml += "".join(xml_channels) + "".join(xml_streams) + "".join(xml_uids)
    xml += XML_TAIL
    data = np.stack(chans, axis=1)
    write_bwf(os.path.join(OUTDIR, f"{name}.wav"), data, xml, ents,
              dolby=True, bits=bits)
    return manifest_entries


def blocks_uniform(n_blocks):
    dur = DUR_S / n_blocks
    return [(i * dur, dur) for i in range(n_blocks)]


def make_dlb_objects(name, n_obj, n_blocks=1, trajectories=None,
                     importance=None, spherical=False, jump=False,
                     gains=None, obj_gain=None, amp_dbfs=None, bits=24,
                     expect=("ok", "ok"), expect_reason=None,
                     traj_desc=None):
    objs = []
    for k in range(n_obj):
        if trajectories == "circle":
            traj = traj_circle(k, n_obj)
            desc = f"circle sweep, phase {k * 360.0 / n_obj:.0f} deg" + \
                (", el=45sin" if k == n_obj - 1 else "")
        else:
            az, el = STATIC_POSITIONS[k % len(STATIC_POSITIONS)]
            traj = traj_static(az, el)
            desc = f"static az={az} el={el} dist=1"
        objs.append({"name": f"Obj{k + 1}", "traj": traj,
                     "blocks": blocks_uniform(n_blocks), "jump": jump,
                     "gains": gains[k] if gains else None,
                     "traj_desc": traj_desc or desc})
    ents = dlb_objects_xml_and_data(name, objs, importance=importance,
                                    spherical=spherical, obj_gain=obj_gain,
                                    amp_dbfs=amp_dbfs, bits=bits)
    manifest["files"][name] = {
        "family": "dlb", "kind": "objects", "channels": n_obj,
        "amp_dbfs": amp_dbfs if amp_dbfs is not None else DEF_AMP_DBFS,
        "n_blocks_per_object": n_blocks, "bits": bits,
        "tracks": ents,
        "expect": {"base": expect[0], "enhanced": expect[1]},
        **({"expect_reason": expect_reason} if expect_reason else {}),
    }


def make_dlb_bed(name, bed, expect=("ok", "ok"), expect_reason=None):
    ents = dlb_objects_xml_and_data(name, [], beds=[bed])
    manifest["files"][name] = {
        "family": "dlb", "kind": "bed", "bed": bed,
        "channels": len(DLB_BEDS[bed]), "amp_dbfs": DEF_AMP_DBFS,
        "tracks": ents,
        "expect": {"base": expect[0], "enhanced": expect[1]},
        **({"expect_reason": expect_reason} if expect_reason else {}),
    }


def make_dlb_mixed(name):
    objs = []
    for k in range(4):
        az, el = STATIC_POSITIONS[k + 4]
        objs.append({"name": f"Obj{k + 1}", "traj": traj_static(az, el),
                     "blocks": blocks_uniform(1),
                     "traj_desc": f"static az={az} el={el}"})
    ents = dlb_objects_xml_and_data(name, objs, beds=["5dot1"])
    manifest["files"][name] = {
        "family": "dlb", "kind": "mixed_bed_objects", "channels": 10,
        "amp_dbfs": DEF_AMP_DBFS, "tracks": ents,
        "expect": {"base": "ok", "enhanced": "ok"},
    }


def make_no_axml(name):
    data = np.stack([sine(track_freq(k), amp(DEF_AMP_DBFS))
                     for k in range(2)], axis=1)
    write_bwf(os.path.join(OUTDIR, f"{name}.wav"), data, None, None)
    manifest["files"][name] = {
        "family": "neg", "kind": "no_axml", "channels": 2,
        "amp_dbfs": DEF_AMP_DBFS,
        "expect": {"base": "reject", "enhanced": "reject"},
        "expect_reason": "no axml chunk",
    }


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    # --- common-definitions family ---
    make_cd_bed("cd_bed_stereo", "stereo")
    make_cd_bed("cd_bed_5dot1", "5dot1")
    make_cd_bed("cd_bed_5dot1dot2", "5dot1dot2")
    make_cd_bed("cd_bed_5dot1dot4", "5dot1dot4")
    make_cd_bed("cd_bed_7dot1", "7dot1")
    make_cd_bed("cd_bed_7dot1dot4", "7dot1dot4")
    make_cd_hoa("cd_hoa_foa", 1)
    make_cd_hoa("cd_hoa_3oa", 3)
    make_cd_binaural("cd_binaural")
    make_cd_bed("cd_bed_loudness", "5dot1", loudness=(-23.0, -1.0, -24.0))
    make_cd_bed("cd_bed_no_loudness", "5dot1", loudness=None)
    make_cd_bed("cd_multi_programme", "5dot1", programmes=[
        ("APR_1001", "MainMix", (-23.0, -1.0, None)),
        ("APR_1002", "AltMix", (-20.0, -2.0, None))])
    make_cd_mixed_bed_hoa("cd_mixed_bed_hoa")
    make_cd_userdef_pack("cd_userdef_pack")
    # objects without dbmd -> default mode -> expect reject
    make_dlb_objects("cd_objects_nodolby", 2, expect=("reject", "reject"),
                     expect_reason="Objects type in non-Dolby (default) mode")
    # overwrite: regenerate without the dbmd chunk (family cd)
    ents = manifest["files"]["cd_objects_nodolby"].pop("tracks")
    objs = []
    for k in range(2):
        az, el = STATIC_POSITIONS[k]
        objs.append({"name": f"Obj{k + 1}", "traj": traj_static(az, el),
                     "blocks": blocks_uniform(1),
                     "traj_desc": f"static az={az} el={el}"})
    a = amp(DEF_AMP_DBFS)
    # rebuild via helper, then rewrite the file with dolby=False
    # (simplest: hand-build here)
    # reuse dlb builder output then strip dbmd by regenerating:
    entries = dlb_objects_xml_and_data("cd_objects_nodolby_tmp", objs)
    os.replace(os.path.join(OUTDIR, "cd_objects_nodolby_tmp.wav"),
               os.path.join(OUTDIR, "cd_objects_nodolby_tmp.keep"))
    # Read back the tmp file and drop its dbmd chunk to make the cd variant.
    with open(os.path.join(OUTDIR, "cd_objects_nodolby_tmp.keep"), "rb") as f:
        raw = f.read()
    os.remove(os.path.join(OUTDIR, "cd_objects_nodolby_tmp.keep"))
    out = raw[:12]
    pos = 12
    while pos + 8 <= len(raw):
        ckid = raw[pos:pos + 4]
        sz = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        total = 8 + sz + (sz % 2)
        if ckid != b"dbmd":
            out += raw[pos:pos + total]
        pos += total
    out = out[:4] + struct.pack("<I", len(out) - 8) + out[8:]
    with open(os.path.join(OUTDIR, "cd_objects_nodolby.wav"), "wb") as f:
        f.write(out)
    manifest["files"]["cd_objects_nodolby"].update(
        {"family": "cd", "kind": "objects_no_dbmd", "channels": 2,
         "tracks": entries})

    make_no_axml("neg_no_axml")

    # --- Dolby family ---
    make_dlb_objects("dlb_obj_static1", 1)
    make_dlb_objects("dlb_obj_static4", 4)
    make_dlb_objects("dlb_obj_static16", 16, amp_dbfs=LOW_AMP_DBFS)
    make_dlb_objects("dlb_obj_static28", 28, amp_dbfs=LOW_AMP_DBFS)
    make_dlb_objects("dlb_obj_auto_slow", 4, n_blocks=10,
                     trajectories="circle")
    make_dlb_objects("dlb_obj_auto_dense", 4, n_blocks=200,
                     trajectories="circle")
    make_dlb_objects("dlb_obj_auto_ultra", 4, n_blocks=1000,
                     trajectories="circle")
    make_dlb_objects("dlb_obj_jump", 4, n_blocks=10, trajectories="circle",
                     jump=True)
    gain_stairs = [[10.0 ** (-2.0 * b / 20.0) for b in range(10)],
                   [1.0] * 10]
    make_dlb_objects("dlb_obj_gainauto", 2, n_blocks=10, gains=gain_stairs)
    make_dlb_objects("dlb_obj_objgain", 1, obj_gain=0.25)
    make_dlb_objects("dlb_obj_spherical", 4, spherical=True,
                     expect=("ok", "ok"),
                     expect_reason="valid BS.2076 spherical positions; "
                                   "importer parses only cartesian X/Y/Z")
    make_dlb_bed("dlb_bed_5dot1", "5dot1")
    make_dlb_bed("dlb_bed_5dot1_labelonly", "5dot1")
    make_dlb_bed("dlb_bed_7dot1dot2", "7dot1dot2")
    make_dlb_bed("dlb_bed_7dot1dot4", "7dot1dot4",
                 expect=("reject", "reject"),
                 expect_reason="4-top bed exceeds importer's Dolby bed "
                               "whitelist (max 7.1.2-style, 10 refs)")
    make_dlb_mixed("dlb_mixed_5dot1_4obj")
    make_dlb_objects("dlb_importance", 8,
                     importance=[10, 9, 8, 7, 5, 4, 3, 1])
    make_dlb_objects("dlb_16bit", 2, bits=16, expect=("reject", "reject"),
                     expect_reason="Dolby mode requires 24-bit")

    with open(os.path.join(OUTDIR, "corpus_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    total = sum(v.get("channels", 0) for v in manifest["files"].values())
    print(f"generated {len(manifest['files'])} ADM BWF files "
          f"({total} tracks) in {OUTDIR}")


if __name__ == "__main__":
    main()
