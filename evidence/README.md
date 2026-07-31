# Archived run records — July 2026 study

These are the actual outputs of the harness run that produced the WP3 findings
(F14–F26 in the public register). Pins for that run: iamf-tools @ `93597f1`
(CMake port), libiamf v1.1.0, EAR 2.1.0, IAMF v1.1.0. Everything here is
reproducible from the repo root: generate the corpus, build the toolchain, run
the harness scripts in README order.

| File | Contents |
|---|---|
| `ingest_results.json` | The full ingest matrix: per corpus file × profile (× importance threshold where exercised), return code, stderr tail, wall time, and a structural probe of every produced bitstream |
| `expectation_verdicts.json` | Observed outcome vs the manifest's pre-registered expectation, per matrix cell — `MATCH` or the mismatch that became a finding |
| `fidelity_report.json` | Raw fidelity metrics for every successfully encoded bitstream: spectral routing survival, RMS error (raw / gain-matched), windowed envelopes, energy-vector angular error, measured vs declared loudness |
| `density_probe.json` | The automation-density boundary map (block-count grid → encode outcome) behind the F15 finding |
| `common_defs_map.json` | The BS.2094 common-definitions pack/channel mapping used by the generator's `cd` family |

**Withheld records.** Five of the 70 ingest records, the five corresponding
expectation verdicts, and one crash backtrace are withheld from this archive
pending the conclusion of a coordinated-disclosure process for one encoder
finding (F14 — described at symptom level in the public register). They will be
restored here when that process concludes. Nothing else is edited: all remaining
records are verbatim.
