# Design notes — reading the provenance references in this codebase

This project was developed against an internal, numbered design docset: every work
cycle produced a numbered document recording what was decided, what was measured, and
the evidence behind both. Code comments cite those records rather than restating them
(`doc 10`, `F10`, `E-FAIL`, …). The docset itself is not published — it contains
work-in-progress material beyond this repo's scope — but the notation is simple and the
index below preserves the context each citation carries, so a comment like "Recipe:
10-wp1-toolchain-validation.md §2" reads as "this exists because of a recorded, tested
procedure," not as a dangling pointer.

## Notation

| Form | Meaning |
|---|---|
| `doc NN` (§ optional) | A numbered internal design/evidence document; the index below gives each cited number's one-line content. |
| `WP1`, `WP3` | Work packages: WP1 = toolchain validation (real encoder/decoder behaviour, the spectral-identity convention), WP3 = the ADM→IAMF conversion-fidelity study this repo is the instrument for. |
| `F1` … `F26` | Entries in the failure-mode register: real defects and pitfalls found in the ecosystem's toolchains. The public register is [`F_TO_CHECK.md`](https://github.com/jlivingston-Cipher/iamf-sentinel/blob/main/F_TO_CHECK.md) in the companion validator repo. F10/F11, cited by the July `build_toolchain.sh`, are WP1 build workarounds; F14–F26 are the WP3 findings this harness surfaced. |
| `G1` … `G11` | WP1 validation gates (doc 10): measured pass/fail criteria for the reference toolchain. |
| `E-…` | A pre-registered expectation: written down *before* an experiment ran, then confirmed or refuted. The corpus manifest's per-file `expect` blocks are this convention applied per corpus file. |
| `BS.xxxx` | ITU-R Recommendations (BS.2076 ADM, BS.2094 common definitions, BS.2127 EAR rendering, BS.2051 layouts, BS.1770 loudness); EBU Tech 3285 is the BW64/axml container spec. |

## Index of cited documents

| Doc | What it established |
|---|---|
| doc 10 | WP1 toolchain validation: deterministic build recipes for the reference toolchain and the G1–G11 validation gates. The July `build_toolchain.sh` followed its build procedure; since 2026-11 the script builds by iamf-sentinel-pro's pinned recipe instead. |
| doc 11 | WP1 failure-mode catalogue (F1–F13): build/runtime pitfalls of the reference tools; F10/F11 were the build workarounds the July `build_toolchain.sh` scripted. |
| doc 16 | The WP3 ADM→IAMF conversion-fidelity report: survival tables, metric definitions, and the interpreted results of the run archived in `evidence/2026-07-study/`. |
| doc 17 | The WP3 failure-mode catalogue (F14–F26): symptom → root cause → workaround for the findings this harness surfaced; summarized publicly in the validator's `F_TO_CHECK.md`. |
| doc 76 | Pre-publication quality audit; established the `SENTINEL_TOOLCHAIN` environment-override convention these scripts follow. |
