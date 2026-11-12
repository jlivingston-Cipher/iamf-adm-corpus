# Completing an IAMF toolchain root on macOS

`complete_toolchain.sh ROOT [STAGE ...]` adds to a toolchain root the tools that iamf-tools' own
build does not produce, so that every route of [`iamf-loom`](https://github.com/jlivingston-Cipher/iamf-loom)
and both decoder oracles of [`iamf-sentinel-pro`](https://github.com/jlivingston-Cipher/iamf-sentinel-pro)
run there:

| Stage | What it builds | Where it lands in ROOT |
|---|---|---|
| `kernel` | `sentinel-dsp`, the BS.1770 loudness kernel, from an iamf-sentinel-pro checkout (`PRO_SRC`, default a sibling clone) | `bin/sentinel-dsp` |
| `libiamf` | libiamf v2.0.1 and its `iamfdec` reference decoder (static) | `src/build-iamfdec/iamfdec` |
| `ffmpeg` | FFmpeg n8.1.3, lean and LGPL, libopus linked statically | `bin/ffmpeg-install/bin/{ffmpeg,ffprobe}` |
| `mp4box` | GPAC v26.07.0 `MP4Box`, static | `bin/MP4Box` |
| `donor` | a 4 s H.264 picture for the audio-with-video tests | `share/loom-test-video.mp4` |
| `manifest` | version, commit and sha256 of every tool | `logs/complete-manifest.txt` |

ROOT must already hold iamf-tools as built by its own CMake path (`build_cmake.sh` in the
iamf-tools tree, the path `iamf-sentinel-pro/oci/toolchain-build.sh` uses on Linux):
`src/build-iamf/{encoder_main,decoder_main}` and the `src/iamf-tools` checkout, whose test data
feeds the libiamf smoke decode. Nothing already in ROOT is modified. Each stage leaves a marker
under `logs/complete-stages/`; `FORCE=1` redoes a stage.

Written for and run on macOS 15 / arm64 with Homebrew `cmake`, `opus` and `python3.12`; it needs
no `pkg-config` or `ninja`, installs nothing outside ROOT, needs network access to GitHub,
GitLab, Bitbucket and downloads.xiph.org, and about 1 GB of scratch. The donor stage uses an
`ffmpeg` with libx264 (`DONOR_FFMPEG`, default Homebrew's), because the lean build has no H.264
encoder by design.

On ARM the libiamf stage builds with `-Ddef_oar_arch_arm`; the comment above that stage says why
(without it, `iamfdec` writes silence on arm64).

Then run the suites against the root:

```bash
export LOOM_TOOLCHAIN=ROOT SENTINEL_TOOLCHAIN=ROOT
LOOM_REQUIRE_TOOLCHAIN=1 LOOM_TEST_VIDEO=ROOT/share/loom-test-video.mp4 python -m pytest   # in iamf-loom
```

Some tests also read archived sample trees; `SENTINEL_SAMPLES` names the directory holding them
(`wp1/wp1-samples`, `wp3/wp3-samples`, `f31/f31-samples`, `f32/f32-samples`, `wp2-l3`). Without
them those tests skip and say where they looked.
