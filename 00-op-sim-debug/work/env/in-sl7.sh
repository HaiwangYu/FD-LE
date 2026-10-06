#!/bin/bash
# Run a command in the Fermilab SL7 container with dunesw v10_26_00d00 (e26:prof) set up.
#
#   env/in-sl7.sh <command ...>
#
# dunesw v10 is built for SL7 (glibc 2.17); the dunegpvm/dunebuild hosts run AlmaLinux 9, so every LArSoft
# command runs inside the container.  Variables:
#   SL7_SETUP=none   bare container, no dunesw setup (used by the mrb build script, which sets up itself)
#   OPDEV=<dir>      also set up the local duneopdet build in that mrb area (localProducts + mrbslp)
IMG=/cvmfs/singularity.opensciencegrid.org/fermilab/fnal-dev-sl7:latest
if [ -z "${APPTAINER_NAME:-}" ]; then
  # /pnfs is not mounted on dunebuild03; binding it would kill the container
  exec /usr/bin/apptainer exec -B /cvmfs -B /exp -B /nashome $IMG /bin/bash "$0" "$@"
fi
if [ "${SL7_SETUP:-dunesw}" != none ]; then
  source /cvmfs/dune.opensciencegrid.org/products/dune/setup_dune.sh > /dev/null 2>&1
  setup dunesw v10_26_00d00 -q e26:prof > /dev/null 2>&1 || { echo "dunesw setup failed" >&2; exit 90; }
  if [ -n "${OPDEV:-}" ]; then
    source $OPDEV/localProducts*/setup > /dev/null 2>&1
    mrbslp > /dev/null 2>&1
  fi
fi
exec "$@"
