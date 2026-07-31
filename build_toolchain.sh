#!/bin/bash
# WP3 step zero — deterministic rebuild of the WP1 IAMF toolchain.
# Recipe: 10-wp1-toolchain-validation.md §2 + 11-wp1-failure-modes.md F10/F11.
# Layout mirrors WP1 exactly so wp1-scripts run unchanged. Default root
# /home/claude/iamf-wp1; override with SENTINEL_TOOLCHAIN (doc 76 convention).
set -uo pipefail
ROOT=${SENTINEL_TOOLCHAIN:-/home/claude/iamf-wp1}
SRC=$ROOT/src
DEPS=$ROOT/deps
LOG=$ROOT/build-logs
mkdir -p $SRC $DEPS $LOG $ROOT/bin $ROOT/out $ROOT/essence
export DEBIAN_FRONTEND=noninteractive
stage() { echo "=== STAGE $1 [$(date +%H:%M:%S)] ==="; }
done_marker() { touch $LOG/.done-$1; }
skip() { [ -f $LOG/.done-$1 ]; }

# ---------- S0: system packages ----------
if ! skip s0; then
stage s0-apt
apt-get install -y cmake nasm pkg-config libopus-dev libflac-dev \
  libexpat1-dev libeigen3-dev > $LOG/apt.log 2>&1 || { echo "APT FAILED"; exit 1; }
apt-get install -y libfdk-aac-dev >> $LOG/apt.log 2>&1 || echo "note: libfdk-aac-dev unavailable (will use source pin)"
pip install numpy scipy --break-system-packages --quiet > $LOG/pip.log 2>&1 || true
done_marker s0
fi

# ---------- S1: clones ----------
git config --global advice.detachedHead false
clone() { # name url ref shallow(y/n)
  local name=$1 url=$2 ref=$3 shallow=$4
  [ -d $SRC/$name/.git ] && { echo "clone $name: exists"; return 0; }
  if [ "$shallow" = y ]; then
    git clone --depth 1 ${ref:+--branch $ref} $url $SRC/$name > $LOG/clone-$name.log 2>&1
  else
    git clone $url $SRC/$name > $LOG/clone-$name.log 2>&1 && \
      ( cd $SRC/$name && git checkout $ref >> $LOG/clone-$name.log 2>&1 )
  fi
  [ -d $SRC/$name ] && echo "clone $name: OK" || { echo "clone $name: FAILED"; return 1; }
}
if ! skip s1; then
stage s1-clones
clone abseil-cpp https://github.com/abseil/abseil-cpp 20260107.1 y || \
  clone abseil-cpp https://github.com/abseil/abseil-cpp "" n || exit 1
clone protobuf https://github.com/protocolbuffers/protobuf v33.5 y || \
  clone protobuf https://github.com/protocolbuffers/protobuf "" n || exit 1
clone iamf-tools https://github.com/AOMediaCodec/iamf-tools 93597f1 n || exit 1
clone fdk_aac https://github.com/mstorsjo/fdk-aac ee76460 n || exit 1
clone loudness_ebur128 https://github.com/google/loudness_ebur128 "" y || exit 1
clone obr https://github.com/google/obr "" y || exit 1
clone audio_to_tactile https://github.com/google/audio-to-tactile "" y || exit 1
clone pffft https://github.com/marton78/pffft "" y || exit 1
clone libiamf https://github.com/AOMediaCodec/libiamf v1.1.0 y || exit 1
clone FFmpeg https://github.com/FFmpeg/FFmpeg n8.1.2 y || exit 1
( cd $SRC/protobuf && git submodule update --init --depth 1 third_party/jsoncpp 2>/dev/null; true )
done_marker s1
fi

# ---------- S2: header shims (F11) ----------
if ! skip s2; then
stage s2-shims
mkdir -p $SRC/shims/flac/include $SRC/shims/opus/include $SRC/shims/expat/expat/lib
ln -sf /usr/include/FLAC $SRC/shims/flac/include/FLAC
for h in /usr/include/opus/*.h; do ln -sf $h $SRC/shims/opus/include/; done
ln -sf /usr/include/expat.h $SRC/shims/expat/expat/lib/expat.h
ln -sf /usr/include/expat_external.h $SRC/shims/expat/expat/lib/expat_external.h
ln -sf /usr/include/expat_config.h $SRC/shims/expat/expat/lib/expat_config.h 2>/dev/null || true
mkdir -p $SRC/port && cp /home/claude/wp3/wp1-scripts/CMakeLists.txt $SRC/port/
done_marker s2
fi

# ---------- S3: abseil ----------
if ! skip s3; then
stage s3-abseil
cmake -S $SRC/abseil-cpp -B $SRC/build-absl -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=$DEPS -DCMAKE_CXX_STANDARD=20 -DABSL_PROPAGATE_CXX_STD=ON \
  -DBUILD_SHARED_LIBS=OFF -DABSL_BUILD_TESTING=OFF > $LOG/absl-cfg.log 2>&1 || { echo ABSL-CFG-FAIL; exit 1; }
cmake --build $SRC/build-absl -j2 --target install > $LOG/absl-build.log 2>&1 || { echo ABSL-BUILD-FAIL; exit 1; }
done_marker s3
fi

# ---------- S4: protobuf ----------
if ! skip s4; then
stage s4-protobuf
cmake -S $SRC/protobuf -B $SRC/build-protobuf -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=$DEPS -DCMAKE_PREFIX_PATH=$DEPS -DCMAKE_CXX_STANDARD=20 \
  -Dprotobuf_BUILD_TESTS=OFF -Dprotobuf_ABSL_PROVIDER=package \
  -Dprotobuf_BUILD_SHARED_LIBS=OFF > $LOG/pb-cfg.log 2>&1 || { echo PB-CFG-FAIL; exit 1; }
cmake --build $SRC/build-protobuf -j2 --target install > $LOG/pb-build.log 2>&1 || { echo PB-BUILD-FAIL; exit 1; }
done_marker s4
fi

# ---------- S5: iamf-tools via CMake port ----------
if ! skip s5; then
stage s5-iamf-tools-port
cmake -S $SRC/port -B $SRC/build-iamf -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=$DEPS > $LOG/port-cfg.log 2>&1 || { echo PORT-CFG-FAIL; exit 1; }
cmake --build $SRC/build-iamf -j2 > $LOG/port-build.log 2>&1 || { echo PORT-BUILD-FAIL; exit 1; }
for t in encoder_main decoder_main probe_main; do
  [ -x $SRC/build-iamf/$t ] || { echo "MISSING $t"; exit 1; }
done
done_marker s5
fi

# ---------- S6: libiamf + iamfdec (F10) ----------
if ! skip s6; then
stage s6-libiamf
LI=$SRC/libiamf/code
[ -d $LI ] || LI=$SRC/libiamf
DC=$LI/dep_codecs
mkdir -p $DC/lib $DC/include
for so in libopus libFLAC libfdk-aac; do
  for f in /usr/lib/x86_64-linux-gnu/$so.so* /usr/lib/x86_64-linux-gnu/$so.a; do
    [ -e "$f" ] && ln -sf $f $DC/lib/; done
done
ln -sfn /usr/include/opus $DC/include/opus
ln -sfn /usr/include/FLAC $DC/include/FLAC
[ -d /usr/include/fdk-aac ] && ln -sfn /usr/include/fdk-aac $DC/include/fdk-aac
cmake -S $LI -B $SRC/build-libiamf -DCMAKE_BUILD_TYPE=Release \
  -DIAMF_ENABLE_BINAURALIZER=OFF -DENABLE_BUILD_CODECS=OFF > $LOG/libiamf-cfg.log 2>&1 || { echo LIBIAMF-CFG-FAIL; exit 1; }
cmake --build $SRC/build-libiamf -j2 > $LOG/libiamf-build.log 2>&1 || { echo LIBIAMF-BUILD-FAIL; exit 1; }
find $SRC/build-libiamf -name iamfdec -type f | head -3
done_marker s6
fi

# ---------- S7: FFmpeg n8.1.2 (lean: no GPL/nonfree needed for WP3) ----------
if ! skip s7; then
stage s7-ffmpeg
cd $SRC/FFmpeg
./configure --prefix=$ROOT/bin/ffmpeg-install --disable-doc --disable-ffplay \
  --disable-debug --enable-libopus > $LOG/ff-cfg.log 2>&1 || { echo FF-CFG-FAIL; exit 1; }
make -j2 > $LOG/ff-build.log 2>&1 || { echo FF-BUILD-FAIL; exit 1; }
make install > $LOG/ff-install.log 2>&1 || { echo FF-INSTALL-FAIL; exit 1; }
done_marker s7
fi

# ---------- S8: essence + scripts in place ----------
if ! skip s8; then
stage s8-essence
cp -r /home/claude/wp3/wp1-scripts $ROOT/wp1-scripts 2>/dev/null || true
python3 $ROOT/wp1-scripts/gen_essence.py $ROOT/essence > $LOG/essence.log 2>&1 || { echo ESSENCE-FAIL; exit 1; }
done_marker s8
fi

stage ALL-DONE
echo "TOOLCHAIN BUILD COMPLETE $(date +%H:%M:%S)"
