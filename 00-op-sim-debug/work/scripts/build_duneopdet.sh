#!/bin/bash
# Build duneopdet v10_26_00d00 with the light-simulation fixes of this note, against dunesw v10_26_00d00 e26:prof.
#
#   scripts/build_duneopdet.sh            (re-executes itself in the SL7 container; ~1-2 min with 12 cores)
#
# Steps: mrb newDev in data/opdev, clone DUNE/duneopdet at tag v10_26_00d00 into srcs/, apply
# patches/duneopdet-light-sim-fixes.patch (also applies to duneopdet develop as of 2026-10), mrb install, then the
# unit test (ctest: FocusList_test).  Use the build with  OPDEV=data/opdev env/in-sl7.sh <cmd>.
# PATCH=<file> builds another patch; PATCH=none builds the unmodified tag.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -n "${APPTAINER_NAME:-}" ] || SL7_SETUP=none exec $HERE/env/in-sl7.sh /bin/bash "$0" "$@"
DEV=${OPDEV:-$HERE/data/opdev}
PATCH=${PATCH:-$HERE/patches/duneopdet-light-sim-fixes.patch}
NJ=${NJ:-12}
source /cvmfs/dune.opensciencegrid.org/products/dune/setup_dune.sh > /dev/null 2>&1
setup dunesw v10_26_00d00 -q e26:prof > /dev/null 2>&1 || { echo "dunesw setup failed"; exit 3; }
setup mrb > /dev/null 2>&1
export MRB_PROJECT=larsoft
mkdir -p $DEV && cd $DEV || exit 3
[ -d srcs ] || { mrb newDev -v v10_26_00d00 -q e26:prof -f > newdev.log 2>&1 || { echo "mrb newDev failed"; exit 4; }; }
source localProducts*/setup > /dev/null 2>&1
if [ ! -d srcs/duneopdet ]; then
  git clone -q -b v10_26_00d00 https://github.com/DUNE/duneopdet.git srcs/duneopdet || { echo "clone failed"; exit 5; }
  if [ "$PATCH" != none ]; then
    git -C srcs/duneopdet apply $PATCH || { echo "patch failed"; exit 6; }
  fi
  (cd srcs && mrb uc > ../uc.log 2>&1) || { echo "mrb uc failed"; exit 7; }
fi
git -C srcs/duneopdet status --porcelain > build-source.txt
mrbsetenv > setenv.log 2>&1 || { echo "mrbsetenv failed"; exit 8; }
mrb i -j$NJ > build.log 2>&1; rc=$?
echo "build rc=$rc ($DEV/build.log)"
[ $rc = 0 ] || exit $rc
(cd $MRB_BUILDDIR/duneopdet && ctest --output-on-failure > $DEV/test.log 2>&1); rc=$?
echo "unit test rc=$rc ($DEV/test.log)"
exit $rc
