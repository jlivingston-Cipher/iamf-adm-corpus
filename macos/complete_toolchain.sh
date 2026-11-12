#!/bin/bash
# complete_toolchain.sh -- add to an IAMF toolchain root the tools that
# iamf-tools' own build does not produce, so every Loom route can run there.
#
#   kernel   sentinel-dsp, the BS.1770 loudness kernel    -> bin/sentinel-dsp
#   libiamf  libiamf v2.0.1 and its iamfdec test tool     -> src/build-iamfdec/iamfdec
#            (renders through the OAR submodule)             src/build-libiamf/test/tools/iamfdec/iamfdec
#   ffmpeg   FFmpeg n8.1.3, lean, static                  -> bin/ffmpeg-install/bin/{ffmpeg,ffprobe}
#   mp4box   GPAC v26.07.0 MP4Box, static                 -> bin/MP4Box
#   donor    a 4 s H.264 picture for the A/V tests        -> share/loom-test-video.mp4
#   manifest version, commit and sha256 of every tool     -> logs/complete-manifest.txt
#
# usage: complete_toolchain.sh ROOT [STAGE ...]     (default: all six, in that order)
#   ROOT must already hold iamf-tools as built by upstream's build_cmake.sh:
#   src/build-iamf/{encoder_main,decoder_main} and the src/iamf-tools checkout
#   (its testdata feeds the libiamf smoke test).  Nothing already there is modified.
# env:   PRO_SRC       iamf-sentinel-pro checkout holding sentinel-dsp/
#        JOBS          parallel jobs (default 8)
#        DONOR_FFMPEG  an ffmpeg with libx264, used for the donor only
#        FORCE=1       redo a stage whose marker exists
#        LIBIAMF_C_FLAGS  override the ARM workaround flag (see the libiamf stage)
# Then run Loom's suite with:
#   LOOM_TOOLCHAIN=ROOT LOOM_REQUIRE_TOOLCHAIN=1 LOOM_TEST_VIDEO=ROOT/share/loom-test-video.mp4
#
# Written for and run on macOS 15 / arm64 with Homebrew cmake 4.3, opus 1.6.1 and
# python3.12; needs no pkg-config, no ninja, and installs nothing outside ROOT.
# Needs network (GitHub, GitLab, Bitbucket, downloads.xiph.org) and about 1 GB
# of scratch, most of which it removes.
# Stage markers: logs/complete-stages/<stage>.done    Logs: logs/complete-*.log
set -uo pipefail
[ $# -gt 0 ] || { echo "usage: $0 ROOT [STAGE ...]"; exit 2; }
ROOT=$1
shift
STAGES=${*:-kernel libiamf ffmpeg mp4box donor manifest}
PRO_SRC=${PRO_SRC:-$(cd "$(dirname "$0")/../.." && pwd)/iamf-sentinel-pro}   # default: a sibling clone
JOBS=${JOBS:-8}
BREW=${BREW:-/opt/homebrew}
CMAKE=${CMAKE:-$BREW/bin/cmake}
PYTHON=${PYTHON:-$BREW/bin/python3.12}
DONOR_FFMPEG=${DONOR_FFMPEG:-$BREW/bin/ffmpeg}
SRC=$ROOT/src
LOG=$ROOT/logs
MARK=$LOG/complete-stages
CUR=none
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:$BREW/bin
# A UTF-8 locale is required: under the C locale (what a detached shell gets)
# CMake cannot unpack flac-1.4.2.tar.xz, one of libiamf's codec downloads
# ("Pathname can't be converted from UTF-8 to current locale").
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
mkdir -p "$SRC" "$LOG" "$MARK" "$ROOT/bin" "$ROOT/share" || exit 1

fail() {  # fail WHAT [LOGFILE]
  echo "COMPLETE-FAIL [$CUR]: $1"
  if [ -n "${2:-}" ] && [ -f "$2" ]; then echo "--- tail $2"; tail -40 "$2"; fi
  exit 1
}
note() { echo "$*" | tee -a "$LOG/complete-provenance-$CUR.txt"; }   # one provenance file per stage
has() {  # has TEXT CMD... -- whether CMD's output contains TEXT.  Not `CMD | grep -q`:
  local text=$1 out          # under pipefail an early-exiting grep can fail the writer.
  shift
  out=$("$@" 2>&1) || true
  case "$out" in *"$text"*) return 0 ;; esac
  return 1
}
skip_done() {
  [ "${FORCE:-0}" != 1 ] && [ -f "$MARK/$1.done" ] || return 1
  echo "stage $1: marker present, skipping (FORCE=1 to redo)"
}
[ -x "$SRC/build-iamf/encoder_main" ] && [ -x "$SRC/build-iamf/decoder_main" ] \
  || { echo "COMPLETE-FAIL: no iamf-tools in $ROOT (src/build-iamf/{encoder_main,decoder_main}); build that first"; exit 1; }

test_wav() {  # test_wav PATH CHANNELS SECONDS -- a deterministic 24-bit sine WAV
  "$PYTHON" -c 'import sys,math,struct
p,ch,sec=sys.argv[1],int(sys.argv[2]),float(sys.argv[3]); n=int(48000*sec); d=bytearray()
for i in range(n):
    for c in range(ch):
        d+=struct.pack("<i",int(0.125*8388607*math.sin(2*math.pi*(440+60*c)*i/48000)))[:3]
b=ch*3
open(p,"wb").write(b"RIFF"+struct.pack("<I",36+len(d))+b"WAVEfmt "+struct.pack("<IHHIIHH",16,1,ch,48000,48000*b,b,24)+b"data"+struct.pack("<I",len(d))+bytes(d))' "$1" "$2" "$3"
}
wav_stats() {  # wav_stats FILE -> "ch=2 frames=N rate=48000 bits=16 peak=-6.02 dBFS"; exit 3 on silence
  "$PYTHON" -c 'import sys,wave,math
w=wave.open(sys.argv[1]); n,ch,sw=w.getnframes(),w.getnchannels(),w.getsampwidth(); d=w.readframes(n)
pk=max((abs(int.from_bytes(d[i:i+sw],"little",signed=True)) for i in range(0,len(d),sw)),default=0)
db="%.2f" % (20*math.log10(pk/2**(sw*8-1))) if pk else "-inf (all samples zero)"
print(f"ch={ch} frames={n} rate={w.getframerate()} bits={sw*8} peak={db} dBFS")
sys.exit(0 if pk and n else 3)' "$1"
}

# ---------------------------------------------------------------- kernel
stage_kernel() {
  local B=$SRC/build-sentinel-dsp S=$PRO_SRC/sentinel-dsp static=ON
  [ -f "$S/CMakeLists.txt" ] || fail "kernel source not found at $S (set PRO_SRC)"
  # The kernel's default (SENTINEL_DSP_STATIC=ON) passes -static-libgcc, which
  # Apple clang refuses at link ("unsupported option '-static-libgcc'"); on
  # macOS it is linked against the system libc++ instead.
  [ "$(uname -s)" = Darwin ] && static=OFF
  rm -rf "$B"
  "$CMAKE" -S "$S" -B "$B" -DCMAKE_BUILD_TYPE=Release -DSENTINEL_DSP_STATIC=$static \
    > "$LOG/complete-kernel-cfg.log" 2>&1 || fail kernel-cfg "$LOG/complete-kernel-cfg.log"
  "$CMAKE" --build "$B" -j"$JOBS" > "$LOG/complete-kernel-build.log" 2>&1 \
    || fail kernel-build "$LOG/complete-kernel-build.log"
  cp "$B/sentinel-dsp" "$ROOT/bin/sentinel-dsp" || fail kernel-install
  rm -rf "$B"
  note "sentinel-dsp: iamf-sentinel-pro $(git -C "$PRO_SRC" rev-parse HEAD)" \
       "(uncommitted changes under sentinel-dsp/: $(git -C "$PRO_SRC" status --porcelain -- sentinel-dsp | wc -l | tr -d ' ');" \
       "SENTINEL_DSP_STATIC=$static)"
  # smoke: one argv, one JSON, a finite integrated loudness for a stereo sine
  test_wav "$LOG/complete-kernel-smoke.wav" 2 3
  "$ROOT/bin/sentinel-dsp" "$LOG/complete-kernel-smoke.wav" --layout 2.0 \
    > "$LOG/complete-kernel-smoke.json" 2> "$LOG/complete-kernel-smoke.err" \
    || fail kernel-smoke "$LOG/complete-kernel-smoke.err"
  rm -f "$LOG/complete-kernel-smoke.wav"
  grep -q '"integrated_lufs":-1[0-9]' "$LOG/complete-kernel-smoke.json" \
    || fail "kernel smoke: no plausible integrated loudness" "$LOG/complete-kernel-smoke.json"
  echo "kernel smoke: $(grep -o '"version":"[^"]*"\|"integrated_lufs":[-0-9.]*' "$LOG/complete-kernel-smoke.json" | tr '\n' ' ')"
}

# ---------------------------------------------------------------- libiamf
# libiamf's own instructions (code/README.md): `cmake -B build; cmake --build
# build`, with -DIAMF_TEST_TOOL=ON for iamfdec; CMake >= 3.28.  Its build
# downloads and builds its own codecs (opus 1.4, fdk-aac, flac 1.4.2, installed
# into code/dep_codecs) and, for OAR's binaural renderer, abseil / eigen /
# pffft / googletest (FetchContent, <build>/_deps).
# Two departures, both about the machine:
#  - the clone takes code/ only.  A plain `git clone --recurse-submodules` of
#    this repository measured ~8 GB on disk (3.2 GB of history plus the tests/
#    conformance vectors); this one is under 100 MB.  The tag's commit and the
#    submodule commit are the same either way.
#  - -DIAMF_BUILD_SHARED_LIB=OFF, an option its README documents, so iamfdec is
#    one self-contained file that can be copied and hashed.
# One workaround, on ARM only: -DCMAKE_C_FLAGS=-Ddef_oar_arch_arm.
#    Built exactly as instructed, iamfdec v2.0.0 on arm64 exits 0 and writes
#    all-zero samples for every input (measured: LPCM, Opus, FLAC and AAC, four
#    build variants).  OAR 3d1d23b defines def_oar_arch_arm in matrix_render.h
#    under __ARM_NEON.  matrix_render.c includes that header and so calls
#    multiply_channels_by_matrix_neon(); matrix_render_arm.c tests the macro
#    WITHOUT including the header, so that function compiles to a bare `ret`
#    and nothing is ever written to the render output.  Defining the macro on
#    the command line compiles the NEON body in; the result is sample-identical
#    to a build forced onto the plain-C path (-U__ARM_NEON).  No source file is
#    changed.  LIBIAMF_C_FLAGS= (empty) builds without it and shows the silence.
#    (Measured on v2.0.0; v2.0.1 is built with the same flag and its smoke
#    decode reads the same as v2.0.0's.)
LIBIAMF_TAG=v2.0.1
stage_libiamf() {
  local L=$SRC/libiamf B=$SRC/build-libiamf cflags
  if [ ! -d "$L/.git" ]; then
    git clone --depth 1 --branch "$LIBIAMF_TAG" --filter=blob:none --sparse \
      https://github.com/AOMediaCodec/libiamf "$L" > "$LOG/complete-libiamf-clone.log" 2>&1 \
      || fail libiamf-clone "$LOG/complete-libiamf-clone.log"
    git -C "$L" sparse-checkout set code >> "$LOG/complete-libiamf-clone.log" 2>&1 \
      || fail libiamf-sparse "$LOG/complete-libiamf-clone.log"
    git -C "$L" submodule update --init --recursive --depth 1 >> "$LOG/complete-libiamf-clone.log" 2>&1 \
      || fail libiamf-submodules "$LOG/complete-libiamf-clone.log"
  fi
  case "$(uname -m)" in
    arm64|aarch64) cflags=${LIBIAMF_C_FLAGS--Ddef_oar_arch_arm} ;;
    *)             cflags=${LIBIAMF_C_FLAGS-} ;;
  esac
  rm -rf "$B"
  "$CMAKE" -S "$L/code" -B "$B" -DCMAKE_BUILD_TYPE=Release -DIAMF_TEST_TOOL=ON \
    -DIAMF_BUILD_SHARED_LIB=OFF ${cflags:+-DCMAKE_C_FLAGS=$cflags} \
    > "$LOG/complete-libiamf-cfg.log" 2>&1 || fail libiamf-cfg "$LOG/complete-libiamf-cfg.log"
  "$CMAKE" --build "$B" -j"$JOBS" > "$LOG/complete-libiamf-build.log" 2>&1 \
    || fail libiamf-build "$LOG/complete-libiamf-build.log"
  [ -x "$B/test/tools/iamfdec/iamfdec" ] || fail "iamfdec was not produced" "$LOG/complete-libiamf-build.log"
  mkdir -p "$SRC/build-iamfdec" && cp "$B/test/tools/iamfdec/iamfdec" "$SRC/build-iamfdec/iamfdec" \
    || fail iamfdec-copy
  note "libiamf: $LIBIAMF_TAG $(git -C "$L" rev-parse HEAD)" \
       "(Release, IAMF_TEST_TOOL=ON, IAMF_BUILD_SHARED_LIB=OFF, CMAKE_C_FLAGS='$cflags')"
  git -C "$L" submodule status --recursive | while read -r sha path _; do
    note "libiamf submodule: $path ${sha#[+-]}"
  done
  for d in "$B"/_deps/*-src; do
    [ -d "$d/.git" ] && note "libiamf fetched dependency: $(basename "$d" -src) $(git -C "$d" rev-parse HEAD)"
  done
  grep -E 'URL |GIT_TAG ' "$L/code/dep_codecs/CMakeLists.txt" | sed 's/^ *//' | while read -r line; do
    note "libiamf codec dependency: $line"
  done
  # Keep the one file the second lookup path names; drop ~380 MB of objects.
  find "$B" -mindepth 1 -maxdepth 1 ! -name test -exec rm -rf {} +
  find "$B/test" -type f ! -path "$B/test/tools/iamfdec/iamfdec" -delete
  find "$B/test" -type d -empty -delete
  libiamf_smoke
}

libiamf_smoke() {  # encode iamf-tools' own test vectors, decode each to stereo with iamfdec
  local T=$SRC/iamf-tools/iamf/cli/testdata W=$LOG/complete-libiamf-smoke
  local R=$LOG/complete-libiamf-smoke.txt t rc st
  [ -d "$T" ] || fail "iamf-tools testdata not found at $T (needed for the libiamf smoke test)"
  rm -rf "$W"; mkdir -p "$W"; : > "$R"
  for t in test_000002 test_000021 test_000072 test_000076; do   # LPCM, Opus, FLAC, AAC-LC
    "$SRC/build-iamf/encoder_main" --user_metadata_filename="$T/$t.textproto" \
      --input_wav_directory="$T" --output_iamf_directory="$W" > "$W/$t.enc.log" 2>&1
    [ -s "$W/$t.iamf" ] || { echo "smoke $t: BAD encoder_main produced nothing" >> "$R"; continue; }
    "$SRC/build-iamfdec/iamfdec" -i0 -s0 -disable_limiter -o3 "$W/$t.wav" "$W/$t.iamf" > "$W/$t.dec.log" 2>&1
    rc=$?
    st=$(wav_stats "$W/$t.wav" 2>&1 | tail -1) || st="BAD $st"
    echo "smoke $t: $(grep -o 'CODEC_ID_[A-Z_]*' "$T/$t.textproto" | head -1) iamf=$(wc -c < "$W/$t.iamf" | tr -d ' ')B" \
         "iamfdec rc=$rc -> $st" >> "$R"
  done
  cat "$R"
  grep -q "BAD" "$R" && fail "libiamf smoke: iamfdec did not yield audio" "$R"
  rm -f "$W"/*.wav
}

# ---------------------------------------------------------------- ffmpeg
# Lean: only what Loom's FFmpeg steps and the start-trim copy test use -- the
# native IAMF muxer/demuxer, mp4/mov, WAV, Ogg/Opus, libopus, PCM, and the pan
# / volume / astats filters (plus aresample/aformat, which FFmpeg inserts
# itself).  LGPL, no H.264 encoder (Loom stream-copies video), no docs, no
# ffplay, no network, and nothing auto-detected from the machine.  Static
# against Homebrew's libopus.a, so the binaries depend on system libraries only.
FFMPEG_TAG=n8.1.3
FFMPEG_COMPONENTS="--enable-protocol=file,pipe
 --enable-demuxer=wav,iamf,mov,ogg,flac
 --enable-muxer=wav,iamf,mp4,mov,opus,ogg,flac,null
 --enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,opus,libopus,flac,aac
 --enable-encoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,libopus,opus,flac,aac
 --enable-parser=opus,flac,aac,h264,hevc,av1
 --enable-bsf=aac_adtstoasc,extract_extradata,h264_mp4toannexb,opus_metadata
 --enable-filter=pan,volume,astats,aresample,aformat,anull,atrim,asetpts,channelmap,channelsplit,join,amerge,apad,anullsrc,sine,ebur128
 --enable-indev=lavfi"
write_pkg_config_shim() {  # FFmpeg's configure finds libopus through pkg-config only
  local sh=$1 opus=$2 ver
  ver=$(sed -n 's/^Version: //p' "$opus/lib/pkgconfig/opus.pc" 2>/dev/null)
  mkdir -p "$(dirname "$sh")"
  {
    echo '#!/bin/sh'
    echo '# Stand-in for pkg-config: answers for libopus (static archive) and nothing else.'
    echo 'case " $* " in *" --version "*) echo 0.29.2; exit 0;; esac'
    echo 'case " $* " in *" opus "*) ;; *) exit 1;; esac'
    echo 'for a in "$@"; do case "$a" in'
    echo "  --cflags) printf '%s ' '-I$opus/include/opus';;"
    echo "  --libs) printf '%s ' '$opus/lib/libopus.a';;"
    echo "  --variable=includedir) printf '%s ' '$opus/include';;"
    echo "  --modversion) printf '%s ' '$ver';;"
    echo 'esac; done; echo; exit 0'
  } > "$sh"
  chmod +x "$sh"
}
stage_ffmpeg() {
  local F=$SRC/FFmpeg B=$SRC/build-ffmpeg P=$ROOT/bin/ffmpeg-install
  local SH=$SRC/complete-shims/pkg-config OPUS=${OPUS_PREFIX:-$BREW/opt/opus}
  [ -f "$OPUS/lib/libopus.a" ] && [ -f "$OPUS/include/opus/opus_multistream.h" ] \
    || fail "libopus (libopus.a and headers) not found under $OPUS; Loom's FFmpeg route encodes with libopus"
  if [ ! -d "$F/.git" ]; then
    git clone --depth 1 --branch "$FFMPEG_TAG" https://github.com/FFmpeg/FFmpeg "$F" \
      > "$LOG/complete-ffmpeg-clone.log" 2>&1 || fail ffmpeg-clone "$LOG/complete-ffmpeg-clone.log"
  fi
  write_pkg_config_shim "$SH" "$OPUS"
  rm -rf "$B" "$P"; mkdir -p "$B"
  # shellcheck disable=SC2086
  ( cd "$B" && "$F/configure" --prefix="$P" --disable-doc --disable-ffplay --disable-debug \
      --disable-autodetect --disable-network --disable-everything \
      --enable-libopus --pkg-config="$SH" $FFMPEG_COMPONENTS ) \
    > "$LOG/complete-ffmpeg-cfg.log" 2>&1 || fail ffmpeg-cfg "$LOG/complete-ffmpeg-cfg.log"
  make -C "$B" -j"$JOBS" > "$LOG/complete-ffmpeg-build.log" 2>&1 || fail ffmpeg-build "$LOG/complete-ffmpeg-build.log"
  make -C "$B" install > "$LOG/complete-ffmpeg-install.log" 2>&1 || fail ffmpeg-install "$LOG/complete-ffmpeg-install.log"
  rm -rf "$B"                                                        # objects: not needed again
  find "$P" -mindepth 1 -maxdepth 1 ! -name bin -exec rm -rf {} +    # keep bin/{ffmpeg,ffprobe}
  [ -x "$P/bin/ffmpeg" ] && [ -x "$P/bin/ffprobe" ] || fail "ffmpeg/ffprobe not installed"
  "$P/bin/ffmpeg" -hide_banner -version > "$LOG/complete-ffmpeg-version.txt" 2>&1 || fail ffmpeg-run
  has ' iamf ' "$P/bin/ffmpeg" -hide_banner -muxers || fail "ffmpeg has no iamf muxer"
  has ' iamf ' "$P/bin/ffmpeg" -hide_banner -demuxers || fail "ffmpeg has no iamf demuxer"
  has ' libopus ' "$P/bin/ffmpeg" -hide_banner -encoders || fail "ffmpeg has no libopus encoder"
  note "ffmpeg: $FFMPEG_TAG $(git -C "$F" rev-parse HEAD); libopus" \
       "$(sed -n 's/^Version: //p' "$OPUS/lib/pkgconfig/opus.pc") linked statically from $OPUS"
  note "ffmpeg: $(sed -n 3p "$LOG/complete-ffmpeg-version.txt")"
  head -1 "$LOG/complete-ffmpeg-version.txt"
}

# ---------------------------------------------------------------- mp4box
# Loom routes every MP4 remux through MP4Box (bin/MP4Box under the root, else
# MP4Box on PATH).  This machine has no GPAC, and with the other tools in place
# seven suite tests still failed for want of it, so it is built here: GPAC's
# MP4Box, statically linked against libgpac, with no third-party libraries
# (zlib and libcurl come from the system).
GPAC_TAG=v26.07.0
stage_mp4box() {
  local G=$SRC/gpac B=$SRC/build-gpac W=$LOG/complete-mp4box-smoke
  if [ ! -d "$G/.git" ]; then
    git clone --depth 1 --branch "$GPAC_TAG" https://github.com/gpac/gpac "$G" \
      > "$LOG/complete-gpac-clone.log" 2>&1 || fail gpac-clone "$LOG/complete-gpac-clone.log"
  fi
  rm -rf "$B"; mkdir -p "$B"
  ( cd "$B" && "$G/configure" --prefix="$B/install" --static-bin ) \
    > "$LOG/complete-gpac-cfg.log" 2>&1 || fail gpac-cfg "$LOG/complete-gpac-cfg.log"
  make -C "$B" -j"$JOBS" > "$LOG/complete-gpac-build.log" 2>&1 || fail gpac-build "$LOG/complete-gpac-build.log"
  [ -x "$B/bin/gcc/MP4Box" ] || fail "MP4Box was not produced" "$LOG/complete-gpac-build.log"
  cp "$B/bin/gcc/MP4Box" "$ROOT/bin/MP4Box" || fail mp4box-install
  rm -rf "$B"
  "$ROOT/bin/MP4Box" -version > "$LOG/complete-mp4box-version.txt" 2>&1
  note "MP4Box: gpac $GPAC_TAG $(git -C "$G" rev-parse HEAD); $(head -1 "$LOG/complete-mp4box-version.txt")"
  # smoke: Loom's own remux shape on a freshly encoded raw IAMF file
  rm -rf "$W"; mkdir -p "$W"
  "$SRC/build-iamf/encoder_main" --user_metadata_filename="$SRC/iamf-tools/iamf/cli/testdata/test_000021.textproto" \
    --input_wav_directory="$SRC/iamf-tools/iamf/cli/testdata" --output_iamf_directory="$W" > "$W/enc.log" 2>&1
  "$ROOT/bin/MP4Box" -for-test -add "$W/test_000021.iamf" -new "$W/out.mp4" > "$W/mux.log" 2>&1 \
    || fail "MP4Box could not remux a raw IAMF file" "$W/mux.log"
  "$ROOT/bin/MP4Box" -info "$W/out.mp4" > "$W/info.log" 2>&1
  grep -i "iamf" "$W/info.log" | head -3
  grep -q "soun:iamf" "$W/info.log" || fail "MP4Box output carries no IAMF track" "$W/info.log"
}

# ---------------------------------------------------------------- donor
# The picture the A/V tests stream-copy (Loom never encodes video).  H.264 in
# MP4, because the YouTube preset requires an avc1 track.  Loom's tests have no
# fixed location for it: they read $LOOM_TEST_VIDEO.  This stage writes
# share/loom-test-video.mp4; point the variable there.
# The toolchain FFmpeg has no H.264 encoder by design, so the donor is encoded
# by $DONOR_FFMPEG (Homebrew's, libx264) unless the toolchain build has one.
stage_donor() {
  local TF=$ROOT/bin/ffmpeg-install/bin/ffmpeg TP=$ROOT/bin/ffmpeg-install/bin/ffprobe
  local OUT=$ROOT/share/loom-test-video.mp4 ff
  [ -x "$TF" ] || fail "toolchain ffmpeg missing ($TF); run the ffmpeg stage first"
  if has ' libx264 ' "$TF" -hide_banner -encoders; then ff=$TF; else ff=$DONOR_FFMPEG; fi
  has ' libx264 ' "$ff" -hide_banner -encoders \
    || fail "no ffmpeg with libx264 to encode the donor (tried $ff); set DONOR_FFMPEG"
  # 4 s, 160x90, 25 fps, no B-frames, one thread, bit-exact flags: small and repeatable
  "$ff" -y -hide_banner -f lavfi -i "testsrc2=size=160x90:rate=25" -t 4 -an \
    -c:v libx264 -preset medium -pix_fmt yuv420p -g 25 -bf 0 -threads 1 \
    -map_metadata -1 -fflags +bitexact -flags:v +bitexact -movflags +faststart "$OUT" \
    > "$LOG/complete-donor-encode.log" 2>&1 || fail donor-encode "$LOG/complete-donor-encode.log"
  # the operation the tests perform on it: trim to 3 s by stream copy, with the toolchain build
  "$TF" -y -hide_banner -i "$OUT" -an -c:v copy -t 3.000 "$LOG/complete-donor-trim.mp4" \
    > "$LOG/complete-donor-trim.log" 2>&1 || fail donor-trim "$LOG/complete-donor-trim.log"
  [ -s "$LOG/complete-donor-trim.mp4" ] || fail "donor trim produced nothing" "$LOG/complete-donor-trim.log"
  note "donor: share/loom-test-video.mp4, $(wc -c < "$OUT" | tr -d ' ') bytes, encoded by" \
       "$("$ff" -version | head -1 | cut -d' ' -f1-3) at $ff"
  note "donor after the tests' 3 s stream-copy trim (toolchain ffmpeg):" \
       "$("$TP" -v error -select_streams v:0 -show_entries stream=codec_name,codec_tag_string,width,height,duration,nb_frames -of default=nw=1 "$LOG/complete-donor-trim.mp4" 2>&1 | tr '\n' ' ')"
  rm -f "$LOG/complete-donor-trim.mp4"
}

# ---------------------------------------------------------------- manifest
stage_manifest() {  # every tool in the root: sha256, size, path, version/commit
  local M=$LOG/complete-manifest.txt f v
  {
    echo "# toolchain root $ROOT -- $(date '+%Y-%m-%d %H:%M:%S %Z') -- $(uname -srm)"
    echo "# sha256  bytes  path  version"
    for f in src/build-iamf/encoder_main src/build-iamf/decoder_main src/build-iamf/probe_main \
             src/build-iamfdec/iamfdec src/build-libiamf/test/tools/iamfdec/iamfdec \
             bin/ffmpeg-install/bin/ffmpeg bin/ffmpeg-install/bin/ffprobe bin/MP4Box \
             bin/sentinel-dsp share/loom-test-video.mp4; do
      if [ ! -f "$ROOT/$f" ]; then echo "ABSENT  -  $f"; continue; fi
      case "$f" in
        src/build-iamf/*) v="iamf-tools $(git -C "$SRC/iamf-tools" describe --tags --always 2>/dev/null) $(git -C "$SRC/iamf-tools" rev-parse HEAD 2>/dev/null)" ;;
        *iamfdec) v="libiamf $(git -C "$SRC/libiamf" describe --tags --always 2>/dev/null) $(git -C "$SRC/libiamf" rev-parse HEAD 2>/dev/null) + OAR $(git -C "$SRC/libiamf/code/dep_external/src/oar" rev-parse HEAD 2>/dev/null)" ;;
        */ffmpeg|*/ffprobe) v="$("$ROOT/$f" -version 2>/dev/null | head -1 | cut -d' ' -f1-3) $(git -C "$SRC/FFmpeg" rev-parse HEAD 2>/dev/null)" ;;
        bin/MP4Box) v="$("$ROOT/$f" -version 2>&1 | head -1) $(git -C "$SRC/gpac" rev-parse HEAD 2>/dev/null)" ;;
        bin/sentinel-dsp) v=$(sed -n 's/^sentinel-dsp: //p' "$LOG/complete-provenance-kernel.txt" 2>/dev/null | tail -1) ;;
        *) v=$(sed -n 's/^donor: //p' "$LOG/complete-provenance-donor.txt" 2>/dev/null | head -1) ;;
      esac
      echo "$(shasum -a 256 "$ROOT/$f" | cut -d' ' -f1)  $(wc -c < "$ROOT/$f" | tr -d ' ')  $f  $v"
    done
    echo "# provenance, as each stage recorded it"
    cat "$LOG"/complete-provenance-*.txt 2>/dev/null
  } > "$M"
  cat "$M"
  if grep -q "^ABSENT" "$M"; then fail "the root is missing a tool" "$M"; fi
}

# ---------------------------------------------------------------- main
echo "complete_toolchain: ROOT=$ROOT stages: $STAGES [$(date '+%Y-%m-%d %H:%M:%S')]"
for s in $STAGES; do
  CUR=$s
  case "$s" in
    kernel|libiamf|ffmpeg|mp4box|donor|manifest) ;;
    *) fail "unknown stage (kernel libiamf ffmpeg mp4box donor manifest)" ;;
  esac
  if [ "$s" != manifest ] && skip_done "$s"; then continue; fi
  : > "$LOG/complete-provenance-$s.txt"
  echo "=== STAGE $s [$(date +%H:%M:%S)]"
  "stage_$s"
  date '+%Y-%m-%d %H:%M:%S' > "$MARK/$s.done"
  echo "=== STAGE $s DONE [$(date +%H:%M:%S)]"
done
echo "COMPLETE OK [$(date +%H:%M:%S)] -- $(du -sh "$ROOT" 2>/dev/null | cut -f1) in $ROOT"
