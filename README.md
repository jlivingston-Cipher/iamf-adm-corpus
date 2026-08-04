# iamf-adm-corpus — a synthetic ADM corpus and measurement harness for ADM→IAMF conversion fidelity


> **Name.** The project name is **`iamf-adm-corpus`**. This is an independent project,
> not an AOM or EBU deliverable; "IAMF" and "ADM" appear throughout as descriptive
> nominative use of the format names, not as product names.

Code comments cite an internal numbered design docset (`doc NN`), failure-register entries
(`F-numbers`), and pre-registered expectation labels — **[DESIGN-NOTES.md](DESIGN-NOTES.md)**
explains the notation and indexes every cited document.

**One line:** this repo generates a ground-truth-carrying synthetic ADM BWF corpus, drives it
through an ADM→IAMF encoder, and measures — against an independent reference renderer — exactly
what survives the conversion: routing, level, position, automation, loudness metadata.

## Why this exists

ADM (ITU-R BS.2076) is professional audio's interchange format for object-based masters; IAMF is
the open distribution format those masters increasingly need to reach. The conversion between them
is where content silently dies: channels re-routed, gains discarded, positions zeroed, automation
flattened — all in files that remain syntactically valid and fully decodable. Decoders can't see
it, encoders self-certify, and no public instrument measured it. This is that instrument.

Two design choices do the work:

1. **Spectral identity.** Every track in every corpus file carries a unique, non-harmonic
   identifier sine (313 + 139·k Hz; LFE at 40 Hz). Any downstream routing loss, duplication, or
   swap is detectable from the output alone by FFT — no reference alignment, no perceptual model.
2. **Pre-registered expectations.** The corpus manifest records, per file and per encoder
   profile, what *should* happen (`ok` / `reject`) — written before the encoder ever ran. The
   harness checks outcomes against those expectations rather than assuming them. Where reality
   disagreed with the manifest, that disagreement was the finding.

## The corpus

34 ADM BWF files, 230 tracks, generated deterministically in ~10 seconds — the corpus is the
generator, not a payload of WAVs. Two ingest families, matching the two ADM dialects the
`adm_to_user_metadata` surface implements, plus negative cases:

- **`cd_*`** — BS.2094 common-definitions ADM: beds from stereo to 7.1.4, FOA/3OA HOA, binaural,
  authored-loudness variants, multi-programme, mixed bed+HOA, and structural negatives.
- **`dlb_*`** — "Dolby ADM" dialect (dbmd chunk present): DirectSpeakers beds, object counts from
  1 to 28, position automation from slow to pathological, gain automation, spherical coordinates,
  importance ladders, a 16-bit reject case.

Ground truth (positions, trajectories, gains, loudness metadata, per-track identifier
frequencies) is emitted as `corpus_manifest.json` next to the WAVs; a reference copy of that
manifest ships at the repo root. Generation is byte-stable: two runs produce identical bytes, and
the shipped manifest is byte-identical to a fresh generation.

```bash
pip install numpy scipy
python3 adm_corpus_gen.py [outdir]        # default: $SENTINEL_TOOLCHAIN/adm-corpus
```

## The harness

Four scripts, run in order; all paths default to the WP1 toolchain layout and honor
`SENTINEL_TOOLCHAIN` (toolchain root) and `EAR_RENDER` (EAR binary) overrides:

| Script | What it does |
|---|---|
| `build_toolchain.sh` | Deterministic rebuild of the reference toolchain (iamf-tools, libiamf, FFmpeg; ~35 min cold on 2 cores) |
| `adm_ingest_run.py` | The ingest matrix: every corpus file × both IAMF profiles × the importance-threshold axis; captures rc/stderr/timing, probes every produced bitstream, and diffs outcomes against the manifest's pre-registered expectations |
| `ear_prerender.py` | Pre-renders the same source ADM with the EBU ADM Renderer (EAR, BS.2127) on BS.2051 reference layouts — the independent oracle |
| `fidelity_measure.py` | Per bitstream: decode on reference layouts, then measure routing survival (spectral identity), per-channel and overall RMS error (raw and gain-matched), 100 ms windowed error envelopes, energy-vector angular error vs analytic trajectories, and BS.1770 loudness of each render vs the bitstream's declared values |
| `density_probe.py` | Maps the automation-density failure boundary of the encoder's wav splicer across block-count grids |

EAR and an IAMF renderer legitimately differ (BS.2127 point-source panning vs the encoder's
rendering model); the harness separates renderer divergence from conversion loss with a
per-file static baseline. Metrics are emitted raw to JSON; interpretation is deliberately kept
out of the measurement scripts.

## What it found

The July 2026 study run of this harness (iamf-tools @ `93597f1`, libiamf v1.1.0, EAR 2.1.0)
produced the F14–F26 band of the failure register published in the companion validator's
[`F_TO_CHECK.md`](https://github.com/jlivingston-Cipher/iamf-sentinel/blob/main/F_TO_CHECK.md) —
among them: no authored ADM gain of any kind survives conversion, spherical position coordinates
are silently zeroed to origin (+6 dB collapse), the importance threshold silently does nothing,
and roughly half of plausible automation grids abort the encoder. Archived run records are in
[`evidence/`](evidence/README.md).

## Related projects

- [`iamf-sentinel`](https://github.com/jlivingston-Cipher/iamf-sentinel) — IAMF conformance & QC
  validator (the output-side instrument; this corpus is the input-side one)
- [`iamf-sentinel-pro`](https://github.com/jlivingston-Cipher/iamf-sentinel-pro) — rendered-QC
  plugin whose `adm-compare` mode applies this corpus's source-referenced method to real masters
- [`iamf-loom`](https://github.com/jlivingston-Cipher/iamf-loom) — manifest-driven IAMF packager
- [`Inseglet`](https://github.com/inseglet-audio/inseglet) — authoring-side companion (a native
  REAPER MCP extension): an independent native ADM producer exercised against this corpus's
  cross-validation method

## License

Apache-2.0. See [NOTICE](NOTICE) for provenance: the corpus generator authors ADM structures
clean-room from the BS.2076-2 / BS.2094 texts; encoders, decoders, and the EAR renderer are
invoked strictly as subprocess oracles. Maintained best-effort by a single maintainer;
consulting available — see the [iamf-sentinel SUPPORT
posture](https://github.com/jlivingston-Cipher/iamf-sentinel/blob/main/SUPPORT.md).
