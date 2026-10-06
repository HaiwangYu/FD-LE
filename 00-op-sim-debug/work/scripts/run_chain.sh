#!/bin/bash
# The minimum FD-VD low-energy light workflow for one event: gen -> g4 stage 1 -> g4 stage 2 -> light detsim -> OpHits,
# with the stock dunesw v10_26_00d00 from CVMFS.
#
#   scripts/run_chain.sh <sol|mix> <idx>       (re-executes itself inside the SL7 container)
#
#   sol  solar-only: one MARLEY 8B-like nu_e CC event, nothing else
#   mix  the same MARLEY generator plus the DUNE radiological background model (~130k decays over +-4.25 ms)
#
# Steps (official job fcls of the FD-VD 1x8x14_3view_30deg workspace):
#   1 gen     prodmarley_solar_cc_flat[_radiological_decay0]_dunevd10kt_1x8x14_3view_30deg.fcl
#   2 g4s1    supernova_g4stage1_dunevd10kt_1x8x14_3view_30deg.fcl   (Geant4, charge depos, Ar scintillation light)
#   3 g4s2    standard_g4stage2_dunevd10kt_1x8x14_3view_30deg.fcl    (Xe light from the same depos)
#   4 detsim  fcl/detsim_light_only.fcl                              (photons -> PE -> digitised snippets)
#   5 reco    fcl/reco_ophit_only.fcl                                (snippets -> OpHits)
# Seeds: NuRandomService policy "random", masterSeed = SEED0 + 10*idx + step, the scheme of Xin Qian's fdvd_sim
# Stage A, so event <s> <idx> here is the same event as in his samples.  (The stock job fcls seed from the wall clock,
# which makes every rerun a different event.)
# Output: data/events/<s>/evt<idx>/{reco.root, job_*.fcl, *.log, status.txt}; the intermediate gen/g4/detsim files are
# deleted unless KEEP_INTERMEDIATE=1.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -n "${APPTAINER_NAME:-}" ] || exec $HERE/env/in-sl7.sh /bin/bash "$0" "$@"
S=$1; I=$2
case "$S" in
  mix) GENFCL=prodmarley_solar_cc_flat_radiological_decay0_dunevd10kt_1x8x14_3view_30deg.fcl; SEED0=100000; RUN=1 ;;
  sol) GENFCL=prodmarley_solar_cc_flat_dunevd10kt_1x8x14_3view_30deg.fcl;                     SEED0=200000; RUN=2 ;;
  *) echo "usage: $0 sol|mix <idx>" >&2; exit 2 ;;
esac
[ -n "$I" ] || { echo "usage: $0 sol|mix <idx>" >&2; exit 2; }
W=${DATA:-$HERE/data}/events/$S/evt$I
grep -q DONE $W/status.txt 2>/dev/null && { echo "$S $I already done"; exit 0; }
mkdir -p $W && cd $W || exit 3
: > status.txt
export FHICL_FILE_PATH="$HERE/fcl:$FHICL_FILE_PATH"

wrap() {   # $1 step name, $2 job fcl, $3 step number: the job fcl plus a fixed seed
  { echo "#include \"$2\""
    echo "services.NuRandomService.policy: \"random\""
    echo "services.NuRandomService.masterSeed: $((SEED0 + 10*I + $3))"
    [ "$1" = gen ] && { echo "source.firstRun: $RUN"; echo "source.firstSubRun: $((I + 1))"; }
  } > job_$1.fcl
}
step() {   # $1 step name, rest: lar arguments
  local name=$1; shift
  /usr/bin/time -v lar "$@" > $name.log 2>&1
  local rc=$?
  echo "$name rc=$rc" >> status.txt
  [ $rc -eq 0 ] || { echo "FAILED at $name" >> status.txt; echo "$S $I FAILED at $name"; exit $rc; }
}
wrap gen    $GENFCL 1
wrap g4s1   supernova_g4stage1_dunevd10kt_1x8x14_3view_30deg.fcl 2
wrap g4s2   standard_g4stage2_dunevd10kt_1x8x14_3view_30deg.fcl 3
wrap detsim detsim_light_only.fcl 4
wrap reco   reco_ophit_only.fcl 5
step gen    -c job_gen.fcl    -n 1 -o gen.root
step g4s1   -c job_g4s1.fcl   -s gen.root    -o g4s1.root
step g4s2   -c job_g4s2.fcl   -s g4s1.root   -o g4s2.root
step detsim -c job_detsim.fcl -s g4s2.root   -o detsim.root
step reco   -c job_reco.fcl   -s detsim.root -o reco.root
[ "${KEEP_INTERMEDIATE:-0}" = 1 ] || rm -f gen.root g4s1.root g4s2.root detsim.root
echo DONE >> status.txt
echo "$S $I done $(date +%T)"
