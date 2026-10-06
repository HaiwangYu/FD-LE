#!/bin/bash
# Re-run the light simulation of one event with a chosen duneopdet build and settings, find OpHits, dump the results.
#
#   scripts/run_rerun.sh <config> <sol|mix> <idx>          (re-executes itself in the SL7 container)
#
# Starts from data/events/<s>/evt<idx>/reco.root (scripts/run_chain.sh), which keeps the photons Geant4 delivered to each
# photon detector (OpDetBacktrackerRecords), so every configuration sees exactly the same photons.  The event's own
# detsim seed is reused, so the stock rerun reproduces the stored waveforms bit for bit.
#
# config   build                     settings                                               isolates
#   stock    CVMFS duneopdet v10_26   -                                                       (all bugs present)
#   legacy   patched (data/opdev)     every knob at its legacy value                          E fixed only (no knob)
#   fixB     patched                  legacy + MergeOverlappingRanges true                    B: duplicate snippets
#   fixC     patched                  legacy + LateLightReference "Track" (Ar products)       C: late-light reference
#   fixD     patched                  legacy + DarkNoiseTimeInNs true                         D: dark-count times
#   fixN1    patched                  legacy + BinomialQE true                                N1: Poisson-on-Poisson QE
#   default  patched                  the patch's defaults: B, D, E, N1 fixed, C legacy       proposed default
#   all      patched                  default + LateLightReference "Track"                    every fix
# Output: data/rerun/<config>/<s>/evt<idx>/{light.npz, *.log, detsim.fcl, build.txt}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA=${DATA:-$HERE/data}
CFG=$1; S=$2; I=$3
case $CFG in
  stock) ;;
  legacy|fixB|fixC|fixD|fixN1|default|all) export OPDEV=${OPDEV:-$DATA/opdev} ;;
  *) echo "unknown config '$CFG'" >&2; exit 2 ;;
esac
[ -n "${APPTAINER_NAME:-}" ] || exec $HERE/env/in-sl7.sh /bin/bash "$0" "$@"
IN=$DATA/events/$S/evt$I
W=$DATA/rerun/$CFG/$S/evt$I
[ -f $W/light.npz ] && [ -z "${FORCE:-}" ] && { echo "$CFG $S $I already done"; exit 0; }
grep -q DONE $IN/status.txt 2>/dev/null || { echo "$CFG $S $I: input event not ready ($IN)"; exit 3; }
# another job is already running this one (several queues may share the work)
mkdir -p $(dirname $W)
mkdir $W.lock 2>/dev/null || { echo "$CFG $S $I in progress elsewhere"; exit 0; }
trap 'rmdir $W.lock' EXIT
rm -rf $W; mkdir -p $W && cd $W || exit 3
echo "config $CFG, duneopdet $(ups active | awk '$1=="duneopdet"{print $2, $NF}')" > build.txt
export FHICL_FILE_PATH="$HERE/fcl:$FHICL_FILE_PATH"

legacy_knobs() {
  echo "physics.producers.opdigi10ppm.MergeOverlappingRanges: false"
  for p in sipmAr10ppm sipmXe10ppm sipmAr10ppmExt sipmXe10ppmExt; do
    echo "physics.producers.$p.DarkNoiseTimeInNs: false"
    echo "physics.producers.$p.BinomialQE: false"
  done
}
track_knobs() {
  echo "physics.producers.sipmAr10ppm.LateLightReference: \"Track\""
  echo "physics.producers.sipmAr10ppmExt.LateLightReference: \"Track\""
}
{ echo '#include "detsim_light_rerun.fcl"'
  echo "services.NuRandomService.masterSeed: $(awk '/masterSeed/{print $2}' $IN/job_detsim.fcl)"
  case $CFG in
    legacy) legacy_knobs ;;
    fixB)   legacy_knobs; echo "physics.producers.opdigi10ppm.MergeOverlappingRanges: true" ;;
    fixC)   legacy_knobs; track_knobs ;;
    fixD)   legacy_knobs; for p in sipmAr10ppm sipmXe10ppm sipmAr10ppmExt sipmXe10ppmExt; do
              echo "physics.producers.$p.DarkNoiseTimeInNs: true"; done ;;
    fixN1)  legacy_knobs; for p in sipmAr10ppm sipmXe10ppm sipmAr10ppmExt sipmXe10ppmExt; do
              echo "physics.producers.$p.BinomialQE: true"; done ;;
    all)    track_knobs ;;
  esac
} > detsim.fcl
lar -c detsim.fcl --debug-config detsim_config.txt > /dev/null 2>&1
lar -c detsim.fcl -s $IN/reco.root -n 1 > detsim.log 2>&1 || { echo "$CFG $S $I detsim FAILED"; exit 4; }
lar -c reco_ophit_rerun.fcl -s detsim_rerun.root -n 1 > ophit.log 2>&1 || { echo "$CFG $S $I ophit FAILED"; exit 5; }
python3 $HERE/analysis/dump_light.py detsim_rerun.root ophit_rerun.root $IN/reco.root light.tmp.npz > dump.log 2>&1 \
  && mv light.tmp.npz light.npz || { echo "$CFG $S $I dump FAILED"; exit 6; }
[ "${KEEP:-0}" = 1 ] || rm -f detsim_rerun.root ophit_rerun.root *_hist.root
echo "$CFG $S $I ok $(date +%T)"
