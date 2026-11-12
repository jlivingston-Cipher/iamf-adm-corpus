# Run records

Two runs of this harness over the same corpus (the generator's output is byte-identical
across them). Each directory holds that run's raw records; interpretation stays out of the
measurement scripts.

| Directory | Encoder and renderers | Status |
|---|---|---|
| [`2026-11-v4.0.0/`](2026-11-v4.0.0/) | iamf-tools **v4.0.0** (`28e5b07`), libiamf v2.0.1, FFmpeg n8.1.3, EAR 2.1.0 | current |
| [`2026-07-study/`](2026-07-study/) | iamf-tools `93597f1` (CMake port), libiamf v1.1.0, FFmpeg n8.1.2, EAR 2.1.0 | the July 2026 study behind findings F14–F26 in the public register; kept verbatim |

`common_defs_map.json` (the BS.2094 common-definitions pack/channel mapping used by the
generator's `cd` family) applies to both.

| File | Contents |
|---|---|
| `ingest_results.json` | The ingest matrix: per corpus file × profile (× importance threshold where exercised), return code, stderr tail, wall time, and a structural probe of every produced bitstream |
| `expectation_verdicts.json` | Observed outcome vs the manifest's pre-registered expectation, per matrix cell — `MATCH` or `SURPRISE` |
| `fidelity_report.json` | Per produced bitstream and layout: spectral routing survival, RMS error (raw / gain-matched), windowed envelopes, energy-vector angular error, measured vs declared loudness |
| `conversion_report.json` | *(v4.0.0 run only)* Per produced bitstream: per-track level (S-333) and direction (S-334) readings from iamf-sentinel-pro, each with its margin and call |
| `density_probe.json` | The automation-density map (block-count grid → encode outcome) behind F15 |

**Withheld records.** In both runs five of the 70 ingest records and the five corresponding
expectation verdicts are withheld, the same five cells each time; in the v4.0.0 run so is
every fidelity and conversion record derived from those cells. They are withheld pending the
conclusion of a coordinated-disclosure process for one encoder finding (F14 — described at
symptom level in the public register) and will be restored when that process concludes. The
July archive also withholds one crash backtrace. Nothing else is edited, except that in the
v4.0.0 records local path prefixes are replaced by `$SENTINEL_TOOLCHAIN`, `<iamf-tools>/` and
`<earenv>/`.

## The v4.0.0 run (2026-11-11)

Run on macOS (arm64) against a root built by upstream's `build_cmake.sh` and completed by
`macos/complete_toolchain.sh`; `build_toolchain.sh` builds the same pins on Linux and
`.github/workflows/toolchain.yml` proves it there. Binaries (sha256, first 16):
`encoder_main a94450df40ece102`, `decoder_main 05347c5b4c80f68a`, `probe_main 5623e7d453357547`.
Measures from iamf-sentinel-pro `14295c0`.

- **Expectations.** All 63 published cells meet the manifest's pre-registered expectation.
  In July four did not: `dlb_obj_auto_dense` (encoder abort, F15) and `dlb_obj_objgain`
  (refusal on an object `<gain>`, F16), both profiles; both now encode. The importance axis
  (thresholds 5 and 11) encodes, as in July.
- **Automation density.** All 19 block counts on the grid (1 to 2000 blocks over 10 s)
  encode; in July 4 of the 19 aborted.
- **Bitstreams.** Every produced file differs from July's in its descriptors. On all 53 the
  annotations are names (`MainMix`, `Bed_5dot1`, …) where July's were the encoder's template
  labels (`test_mix_pres`, …; F24), and output mix-gain parameter ids moved; in
  `cd_mixed_bed_hoa` and `dlb_mixed_5dot1_4obj` the audio elements are listed in a different
  order; declared loudness changed on `cd_binaural`, `dlb_mixed_5dot1_4obj` and
  `dlb_obj_spherical`.
- **Fidelity.** Of the 119 render records July and this run share, the gain-matched error
  and the loudness delta against EAR agree within 0.05 on all but nine and eight. The large
  changes are `dlb_obj_spherical`: −21.2 dB error and −7.5 LU on 2.0, −11.35 dB / −2.8 LU on
  5.1, −9.11 dB / −3.5 LU on 7.1.4 (the origin collapse, F19). The others are under 2 dB.
- **Conversion (S-333 level).** 161 judged tracks: 80 FAIL, every one at least 1.57 dB from
  the source; 81 pass, every one within 0.010 dB; none UNDETERMINED; the largest margin on a
  judged track is 0.014 dB. Not judged: common-definition HOA tracks, and `cd_hoa_3oa`
  (source tracks too alike to separate).
- **Conversion (S-334 direction).** 156 readings: 124 FAIL, 32 pass. Every FAIL is a
  Cartesian position (an object, or a Dolby bed channel) realised within 2° of the plain
  trigonometric reading of that position (for an object, the direction the corpus authored)
  and 10° or more from the §10.1.2 reading below. The passes are the spherically authored
  objects (4) and Cartesian positions where the two readings coincide (28). No reading sits
  on neither.

**What a Cartesian position means.** The corpus writes an object's Cartesian position with
plain spherical trigonometry (`adm_corpus_gen.py`, above `sph_to_cart`). BS.2127-0 §10.1.2's
conversion of that position to polar (`bs2127_position.py`, equal to EAR's own to 4e-15)
differs off the five mid-layer speaker azimuths: the left-wall centre is azimuth 70, not 90,
and on this corpus up to 27.9°. EAR, the standard's reference renderer, renders a Cartesian
object with its allocentric panner, so the direction it plays depends on the layout: on 7.1.4
it plays the authored direction (static wall-centre objects 0.0° from it, 20.0° from the
§10.1.2 reading), on 5.1 the §10.1.2 reading (the reverse). `fidelity_report.json` therefore
scores every Cartesian object twice: against the authored trajectory (the keys as before) and
against the §10.1.2 reading (`*_bs2127`). The encoder realises the authored direction, which
is what every S-334 FAIL above measures; S-334 takes its expected direction from §10.1.2.
