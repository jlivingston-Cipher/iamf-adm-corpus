#!/bin/bash
# build_toolchain.sh -- build the toolchain this harness runs on, on Linux.
#
# One recipe, not two (IA-0105, 2026-11-11). The reference toolchain is built
# by iamf-sentinel-pro's oci/toolchain-build.sh at a pinned commit, the recipe
# that builds Pro's own oracles and is proved on Debian trixie by Pro's
# toolchain workflow (run 43121877149, at the commit pinned below). That
# script builds iamf-tools v4.0.0 by upstream's own build_cmake.sh (every
# dependency pinned and checked), libiamf v2.0.1 with its iamfdec, and FFmpeg
# n8.1.3, and assembles the layout this harness reads. Its assemble stage
# keeps decoder_main only; this script adds encoder_main and probe_main from
# the same build, so all three come from one compile.
#
# The July 2026 study was built differently (iamf-tools 93597f1 through a
# CMake port, libiamf v1.1.0, FFmpeg n8.1.2, four unpinned clones); the
# archived records in evidence/2026-07-study/ came from that build.
#
# usage: build_toolchain.sh [STAGE ...]   (default: toolchain ear)
#   toolchain  Pro's recipe at PRO_SHA, then encoder_main/probe_main beside
#              decoder_main                      (~25 min on 4 cores)
#   ear        the EBU ADM Renderer 2.1.0 (BS.2127) in $ROOT/earenv, the
#              independent oracle for fidelity_measure.py / ear_prerender.py
# env: SENTINEL_TOOLCHAIN  toolchain root (default /home/claude/iamf-wp1)
#      TCB_WORK            scratch build root (default $ROOT/tc-build)
#      PRO_SRC             an iamf-sentinel-pro checkout to use instead of a
#                          fresh clone (it must be at PRO_SHA)
#      JOBS, TCB_SKIP_APT  passed through to Pro's script
# Needs root for the apt stage (as in a debian:trixie container), GCC >= 13,
# network. On macOS use upstream build_cmake.sh and macos/complete_toolchain.sh.
#
# Layout produced (what adm_ingest_run.py / fidelity_measure.py read):
#   $ROOT/src/build-iamf/{encoder_main,decoder_main,probe_main}
#   $ROOT/bin/ffmpeg-install/bin/ffmpeg
#   $ROOT/earenv/bin/ear-render                    (export EAR_RENDER to it)
set -uo pipefail
[ "$(uname -s)" = Linux ] || {
  echo "build_toolchain.sh builds on Linux; on macOS see macos/README.md"; exit 2; }
ROOT=${SENTINEL_TOOLCHAIN:-/home/claude/iamf-wp1}
WORK=${TCB_WORK:-$ROOT/tc-build}
STAGES=${*:-toolchain ear}
PRO_URL=https://github.com/jlivingston-Cipher/iamf-sentinel-pro
PRO_SHA=9d45879078e84eb9efef105a72f04fb2a9bc4f63
EAR_VERSION=2.1.0
# EAR 2.1.0 imports pkg_resources, which setuptools 81 removed and which a
# fresh venv does not carry at all: pinned below, or ear-render fails at import.
EAR_SETUPTOOLS='setuptools<81'
mkdir -p "$ROOT" "$WORK" || exit 1
stage() { echo "=== STAGE $1 [$(date +%H:%M:%S)] ==="; }
fail() { echo "BUILD-FAIL: $*"; exit 1; }

for s in $STAGES; do
  case $s in
  toolchain)
    stage toolchain
    PRO=${PRO_SRC:-$WORK/iamf-sentinel-pro}
    if [ ! -d "$PRO/.git" ]; then
      git clone -q "$PRO_URL" "$PRO" || fail "clone $PRO_URL"
    fi
    git -C "$PRO" -c advice.detachedHead=false checkout -q "$PRO_SHA" \
      || fail "iamf-sentinel-pro has no commit $PRO_SHA"
    [ "$(git -C "$PRO" rev-parse HEAD)" = "$PRO_SHA" ] \
      || fail "iamf-sentinel-pro is not at $PRO_SHA"
    bash "$PRO/oci/toolchain-build.sh" "$ROOT" "$WORK" || fail "Pro's recipe"
    for t in encoder_main probe_main; do
      install -m 755 "$WORK/it/src/build-iamf/$t" "$ROOT/src/build-iamf/$t" \
        || fail "copy $t"
    done
    for t in encoder_main decoder_main probe_main; do
      [ -x "$ROOT/src/build-iamf/$t" ] || fail "missing $t"
      echo "$t $(sha256sum "$ROOT/src/build-iamf/$t" | cut -c1-16)"
    done
    [ -x "$ROOT/bin/ffmpeg-install/bin/ffmpeg" ] || fail "missing ffmpeg"
    ;;
  ear)
    stage ear
    python3 -m venv "$ROOT/earenv" || fail "venv (python3-venv installed?)"
    "$ROOT/earenv/bin/pip" install -q "ear==$EAR_VERSION" "$EAR_SETUPTOOLS" \
      || fail "pip install ear==$EAR_VERSION"
    "$ROOT/earenv/bin/ear-render" --help > /dev/null 2>&1 || fail "ear-render"
    echo "export EAR_RENDER=$ROOT/earenv/bin/ear-render"
    ;;
  *) fail "unknown stage $s" ;;
  esac
done
stage ALL-DONE
