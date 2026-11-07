#!/bin/sh
# Runs INSIDE the p9build container: rebuild the 7.3.1 test kernel and fail loudly.
# Refuses to leave a stale Image behind (lesson from 2026-11-01: a modpost ERROR was
# filtered out and old kernels were repackaged for an hour).
set -u
cd /work/linux-7.3.1
OUT=${OUT:-/work/out7min}
before=$(stat -c %Y $OUT/arch/arm64/boot/Image 2>/dev/null || echo 0)
make O=$OUT ARCH=arm64 -j8 Image > /work/kbuild.log 2>&1
rc=$?
after=$(stat -c %Y $OUT/arch/arm64/boot/Image 2>/dev/null || echo 0)
grep -E "warning: |error:|ERROR|Error [0-9]" /work/kbuild.log | grep -v "^make.*Leaving" | head -20
if [ $rc -ne 0 ]; then echo "KBUILD FAILED rc=$rc (see /work/kbuild.log)"; exit 1; fi
if [ "$after" -le "$before" ] && [ "$before" != 0 ]; then
  # make had nothing to do: fine only if nothing changed
  echo "KBUILD: Image unchanged (nothing to rebuild)"
else
  echo "KBUILD OK: new Image $(stat -c %s $OUT/arch/arm64/boot/Image) bytes"
fi
