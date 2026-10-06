#!/bin/bash
# Build the tech-note PDF from tex/ (figures and numbers.tex come from work/analysis/make_plots.py in figs/).
#   tech-note/build.sh      -> tech-note/fdvd-light-sim-tech-note.pdf
cd "$(dirname "${BASH_SOURCE[0]}")/tex" || exit 1
for i in 1 2; do pdflatex -interaction=nonstopmode -halt-on-error fdvd-light-sim.tex > build.log 2>&1 || { tail -30 build.log; exit 1; }; done
cp fdvd-light-sim.pdf ../fdvd-light-sim-tech-note.pdf
echo "wrote $(cd ..; pwd)/fdvd-light-sim-tech-note.pdf ($(grep -c 'Warning' build.log) warnings)"
