#!/bin/bash
# Everything behind the tech-note, end to end: events, patched build, reruns in 8 configurations, plots.
#
#   scripts/run_all.sh [NSOL [NMIX [NJOBS]]]      defaults 20 20 12
#
# Resources (dunebuild03, AlmaLinux 9 host + SL7 container): a mixed event takes ~5 min in Geant4 and peaks at 6.2 GB;
# a solar-only event takes ~1 min.  Mixed Geant4 jobs are limited to 7 in parallel (~45 GB).  20+20 events and 8
# configurations take about 1.5 h with 12 cores.  For a quick look use  scripts/run_all.sh 1 1 4 .
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NSOL=${1:-20}; NMIX=${2:-20}; NJ=${3:-12}
cd $HERE || exit 1
mkdir -p data/logs
echo "== 1. events ($NSOL solar-only, $NMIX mixed)"
{ for i in $(seq 0 $((NMIX-1))); do echo mix $i; done; } | xargs -P $(( NJ < 7 ? NJ : 7 )) -n 2 scripts/run_chain.sh &
{ for i in $(seq 0 $((NSOL-1))); do echo sol $i; done; } | xargs -P $(( NJ > 8 ? NJ-7 : 1 )) -n 2 scripts/run_chain.sh &
echo "== 2. patched duneopdet"
NJ=4 scripts/build_duneopdet.sh || exit 2
wait
echo "== 3. reruns"
for c in stock legacy fixB fixC fixD fixN1 default all; do
  for i in $(seq 0 $((NMIX-1))); do echo $c mix $i; done
  for i in $(seq 0 $((NSOL-1))); do echo $c sol $i; done
done | xargs -P $NJ -n 3 scripts/run_rerun.sh
echo "== 4. plots and numbers"
python3 analysis/make_plots.py data ../tech-note/figs
