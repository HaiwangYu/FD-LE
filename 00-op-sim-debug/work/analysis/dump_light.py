#!/usr/bin/env python3
"""Dump everything the light-simulation bug plots need from one (re)simulated event.

usage (inside the SL7 container with dunesw set up):
    dump_light.py <detsim.root> <ophit.root> <stored reco.root | -> <out.npz>

<detsim.root>  art file with the photon backtracker (OpDetBacktrackerRecords, from Geant4/PDFastSim), the sensor output
               (OpDetDivRecs, one product per sipm* module), the digitiser output (raw::OpDetWaveforms, opdigi10ppm) and
               the MC truth (MCTruth, MCParticle).
<ophit.root>   art file with the recob::OpHits (ophit10ppm) found on those waveforms.
<reco.root>    the event as first simulated; its waveforms and DivRecs are hashed to check a rerun reproduces them.

Written to <out.npz> (one row per item; every array is small enough to keep for all events):
  snip      [S,4]  per stored waveform snippet: OpChannel, TimeStamp [us], number of samples, RMS of the first 15 samples
  dup       [4]    samples stored, samples stored again by a later snippet of the same channel, of those how many differ
                   in ADC, snippets starting on the same tick as an earlier one (snippets with |TimeStamp| > 1e6 us skipped)
  hits      [H,5]  per OpHit: OpChannel, PeakTime [us], Width [us], Area [ADC], PE
  prod      [4]    the DivRec product labels; the per-product arrays below follow this order
  pe_total, pe_marley, pe_dark, ph_marley   [4]  PE in the DivRecs (all / MARLEY tracks / dark counts = track 0) and
                   MARLEY photons in the matching backtracker product
  dark      [K,3]  dark-count PE: product index, OpDet, time [ns as stored]
  n1        [4,6,16]  for (OpDet, ns) cells holding exactly one backtracker SDP with N = 1..5 photons: counts of the PE
                   the sensor simulation stored in that cell (0..15); row 0 unused
  t_all, t_marley [8600]  photoelectrons (dark counts excluded) per 1 us from -4300 to +4300 us: all / MARLEY
  late_*    MARLEY Ar photons (PDFastSimAr) by arrival time after the event's first photon on that OpDet (late_evt) and
            after the first photon of the same track on that OpDet (late_trk), photon-weighted, bins late_edges [ns]
  wfhash, wfhash_stored, divhash, divhash_stored   FNV-1a hashes (strings)
The MARLEY / background split follows the trackID -> generator join of Xin Qian's fdvd_sim dump_light_truth.py
(MCTruth <-> MCParticle associations, mother chain, ParticleAncestryMap, |trackID|).
"""
import sys

import numpy as np
import ROOT

ROOT.gROOT.SetBatch(True)
ROOT.gSystem.Load("libgallery")
for h in ("gallery/Event.h", "canvas/Persistency/Common/Assns.h", "lardataobj/RawData/OpDetWaveform.h",
          "lardataobj/RecoBase/OpHit.h", "lardataobj/Simulation/OpDetBacktrackerRecord.h",
          "dunecore/DuneObj/OpDetDivRec.h"):
    ROOT.gInterpreter.ProcessLine(f'#include "{h}"')
ROOT.gInterpreter.Declare(r'''
#include <map>
#include <cmath>
#include <cstdint>
#include <string>
#include <vector>
namespace fdle {
inline void fnv(uint64_t& h, const void* p, size_t n) {
  auto c = static_cast<const unsigned char*>(p);
  for (size_t i = 0; i < n; ++i) { h ^= c[i]; h *= 1099511628211ULL; }
}
std::string wfhash(const std::vector<raw::OpDetWaveform>& v) {
  uint64_t h = 1469598103934665603ULL;
  for (auto& w : v) { unsigned ch = w.ChannelNumber(); double t = w.TimeStamp();
    fnv(h, &ch, sizeof ch); fnv(h, &t, sizeof t); if (!w.empty()) fnv(h, w.data(), w.size() * sizeof(w[0])); }
  return std::to_string(v.size()) + ":" + std::to_string(h);
}
std::string divhash(const std::vector<sim::OpDetDivRec>& v) {
  uint64_t h = 1469598103934665603ULL; size_t n = 0;
  for (auto& r : v) { int od = r.OpDetNum(); fnv(h, &od, sizeof od);
    for (auto& tc : r.GetTimeChans()) { double t = tc.time; fnv(h, &t, sizeof t);
      for (auto& p : tc.phots) { int tid = p.trackID; double ph = p.phot; fnv(h, &tid, sizeof tid); fnv(h, &ph, sizeof ph); ++n; } } }
  return std::to_string(n) + ":" + std::to_string(h);
}
std::vector<double> snip(const std::vector<raw::OpDetWaveform>& v, size_t n) {
  std::vector<double> out;
  for (auto& w : v) {
    double rms = -1;
    if (w.size() >= n) { double s = 0, s2 = 0;
      for (size_t k = 0; k < n; ++k) { s += w[k]; s2 += double(w[k]) * w[k]; }
      double mu = s / n; rms = std::sqrt(std::max(0.0, s2 / n - mu * mu)); }
    out.push_back(w.ChannelNumber()); out.push_back(w.TimeStamp()); out.push_back(w.size()); out.push_back(rms);
  }
  return out;
}
std::vector<double> dupcheck(const std::vector<raw::OpDetWaveform>& v) {
  std::map<int, std::map<long, unsigned short>> seen; std::map<int, std::map<long, int>> starts;
  double total = 0, again = 0, differ = 0, same_start = 0;
  for (auto& w : v) {
    if (std::abs(w.TimeStamp()) > 1e6) continue;
    long t0 = std::lround((w.TimeStamp() + 4255.0) / 0.016); auto& m = seen[w.ChannelNumber()];
    if (starts[w.ChannelNumber()][t0]++ > 0) same_start += 1;
    for (size_t k = 0; k < w.size(); ++k) { total += 1; auto it = m.find(t0 + (long)k);
      if (it == m.end()) m[t0 + (long)k] = w[k]; else { again += 1; if (it->second != w[k]) differ += 1; } }
  }
  return {total, again, differ, same_start};
}
std::vector<double> flat_bt(const std::vector<sim::OpDetBacktrackerRecord>& v) {
  std::vector<double> out;   // OpDet, t [ns], trackID, photons
  for (auto& r : v) for (auto& tp : r.timePDclockSDPsMap()) for (auto& s : tp.second) {
    out.push_back(r.OpDetNum()); out.push_back(tp.first); out.push_back(s.trackID); out.push_back(s.numPhotons); }
  return out;
}
std::vector<double> flat_div(const std::vector<sim::OpDetDivRec>& v) {
  std::vector<double> out;   // OpDet, t, trackID, PE
  for (auto& r : v) for (auto& tc : r.GetTimeChans()) for (auto& p : tc.phots) {
    out.push_back(r.OpDetNum()); out.push_back(tc.time); out.push_back(p.trackID); out.push_back(p.phot); }
  return out;
}
// PE stored in (OpDet, time) cells that hold exactly one backtracker SDP with N = 1..nmax photons
std::vector<double> n1(const std::vector<sim::OpDetBacktrackerRecord>& bt, const std::vector<sim::OpDetDivRec>& dr,
                       int nmax, int pemax) {
  std::map<std::pair<int, double>, std::pair<int, int>> cell;   // -> (number of SDPs, photons)
  for (auto& r : bt) for (auto& tp : r.timePDclockSDPsMap()) {
    auto& c = cell[{r.OpDetNum(), tp.first}];
    for (auto& s : tp.second) { c.first += 1; c.second += s.numPhotons; } }
  std::map<std::pair<int, double>, double> pe;
  for (auto& r : dr) for (auto& tc : r.GetTimeChans()) for (auto& p : tc.phots)
    if (p.trackID != 0) pe[{r.OpDetNum(), tc.time}] += p.phot;
  std::vector<double> out((nmax + 1) * (pemax + 1), 0.);
  for (auto& kv : cell) {
    if (kv.second.first != 1 || kv.second.second < 1 || kv.second.second > nmax) continue;
    auto it = pe.find(kv.first);
    int k = it == pe.end() ? 0 : std::min(pemax, (int)std::lround(it->second));
    out[kv.second.second * (pemax + 1) + k] += 1;
  }
  return out;
}
}
''')

DIV = ["sipmAr10ppm", "sipmXe10ppm", "sipmAr10ppmExt", "sipmXe10ppmExt"]
BT = ["PDFastSimAr", "PDFastSimXe", "PDFastSimArExternal", "PDFastSimXeExternal"]
LATE_EDGES = np.concatenate([[0, 2, 5, 10, 20, 50], np.logspace(2, 7, 26)])


def open_event(f):
    ev = ROOT.gallery.Event(ROOT.std.vector("string")(1, f))
    assert not ev.atEnd(), f
    return ev


def product(ev, cls, tag):
    return ev.getValidHandle[ROOT.std.vector(cls)](ROOT.art.InputTag(tag)).product()


def branch_labels(f, prefix):
    tf = ROOT.TFile.Open(f)
    out = []
    for br in tf.Get("Events").GetListOfBranches():
        n = br.GetName()
        if n.startswith(prefix):
            out.append(n[len(prefix):].rstrip(".").split("_")[0])
    tf.Close()
    return out


def marley_label_function(ev, f):
    """trackID -> True if the track descends from the MARLEY MCTruth (port of Xin Qian's join)."""
    mct = branch_labels(f, "simb::MCTruths_")
    pid_to_marley = {}
    for lab in mct:
        h = ev.getValidHandle[ROOT.std.vector("simb::MCTruth")](ROOT.art.InputTag(lab))
        for k in range(h.product().size()):
            pid_to_marley[(h.id().value(), k)] = "marley" in lab.lower()
    mcp = branch_labels(f, "simb::MCParticles_")[0]
    parts = product(ev, "simb::MCParticle", mcp)
    mother = {parts[i].TrackId(): parts[i].Mother() for i in range(parts.size())}
    A = ev.getValidHandle["art::Assns<simb::MCTruth,simb::MCParticle,sim::GeneratedParticleInfo>"](
        ROOT.art.InputTag(mcp)).product()
    tid_m = {}
    for j in range(A.size()):
        pr = A.at(j)
        tid_m[parts[pr.second.key()].TrackId()] = pid_to_marley.get((pr.first.id().value(), pr.first.key()), False)
    anc = {}
    try:
        for kv in ev.getValidHandle["sim::ParticleAncestryMap"](ROOT.art.InputTag(mcp)).product().GetMap():
            for d in kv.second:
                anc[d] = kv.first
    except Exception:  # noqa: BLE001
        pass

    def via_mothers(t):
        chain = []
        while t not in tid_m:
            chain.append(t)
            m = mother.get(t)
            if m is None or m == 0:
                t = None
                break
            t = m
        r = tid_m[t] if t is not None else False
        for c in chain:
            tid_m[c] = r
        return r

    cache = {}

    def is_marley(t):
        t = abs(int(t))
        if t == 0:
            return False
        if t not in cache:
            cache[t] = tid_m[t] if t in tid_m else via_mothers(anc[t] if t in anc else t)
        return cache[t]

    def mask(tids):
        u, inv = np.unique(np.abs(tids).astype(np.int64), return_inverse=True)
        return np.array([is_marley(x) for x in u], dtype=bool)[inv.ravel()]

    return mask


def main():
    fsim, fhit, fstored, fout = sys.argv[1:5]
    R = {}
    ev = open_event(fsim)
    wf = product(ev, "raw::OpDetWaveform", "opdigi10ppm")
    R["wfhash"] = str(ROOT.fdle.wfhash(wf))
    R["snip"] = np.array(ROOT.fdle.snip(wf, 15)).reshape(-1, 4)
    R["dup"] = np.array(ROOT.fdle.dupcheck(wf))
    divs = {d: product(ev, "sim::OpDetDivRec", d) for d in DIV}
    bts = {b: product(ev, "sim::OpDetBacktrackerRecord", b) for b in BT}
    R["divhash"] = np.array([str(ROOT.fdle.divhash(divs[d])) for d in DIV])
    if fstored != "-":
        es = open_event(fstored)
        R["wfhash_stored"] = str(ROOT.fdle.wfhash(product(es, "raw::OpDetWaveform", "opdigi10ppm::detsim")))
        R["divhash_stored"] = np.array([str(ROOT.fdle.divhash(product(es, "sim::OpDetDivRec", d + "::detsim")))
                                        for d in DIV])

    eh = open_event(fhit)  # keep the Event alive while its product is read
    hv = product(eh, "recob::OpHit", "ophit10ppm")
    R["hits"] = np.array([(h.OpChannel(), h.PeakTime(), h.Width(), h.Area(), h.PE()) for h in hv]).reshape(-1, 5)

    is_marley = marley_label_function(ev, fsim)
    R["prod"] = np.array(DIV)
    pe_t, pe_m, pe_d, ph_m, dark = [], [], [], [], []
    tedges = np.arange(-4300.0, 4300.0 + 1, 1.0)       # 1 us bins over the light readout window
    th_all, th_mar = np.zeros(len(tedges) - 1), np.zeros(len(tedges) - 1)
    n1 = []
    for k, (d, b) in enumerate(zip(DIV, BT)):
        a = np.array(ROOT.fdle.flat_div(divs[d])).reshape(-1, 4)
        tid = a[:, 2]
        pe_t.append(a[:, 3].sum())
        pe_d.append(a[tid == 0, 3].sum())
        pe_m.append(a[(tid != 0) & is_marley(tid), 3].sum() if len(a) else 0.)
        if len(a):
            sig = (tid != 0) & is_marley(tid)
            th_all += np.histogram(a[tid != 0, 1] / 1000.0, tedges, weights=a[tid != 0, 3])[0]
            th_mar += np.histogram(a[sig, 1] / 1000.0, tedges, weights=a[sig, 3])[0]
        dk = a[tid == 0]
        dark.append(np.column_stack([np.full(len(dk), k), dk[:, 0], dk[:, 1]]))
        bt = np.array(ROOT.fdle.flat_bt(bts[b])).reshape(-1, 4)
        mm = is_marley(bt[:, 2]) if len(bt) else np.zeros(0, bool)
        ph_m.append(bt[mm, 3].sum())
        n1.append(np.array(ROOT.fdle.n1(bts[b], divs[d], 5, 15)).reshape(6, 16))
        if b == "PDFastSimAr" and mm.any():
            od, t, tr, n = bt[:, 0].astype(np.int64), bt[:, 1], bt[:, 2].astype(np.int64), bt[:, 3]
            first_od = np.full(od.max() + 1, np.inf)
            np.minimum.at(first_od, od, t)
            key = od * 10**9 + (tr + 5 * 10**8)
            uk, inv = np.unique(key, return_inverse=True)
            first_tr = np.full(len(uk), np.inf)
            np.minimum.at(first_tr, inv.ravel(), t)
            dt_evt = (t - first_od[od])[mm]
            dt_trk = (t - first_tr[inv.ravel()])[mm]
            R["late_evt"] = np.histogram(dt_evt, LATE_EDGES, weights=n[mm])[0]
            R["late_trk"] = np.histogram(dt_trk, LATE_EDGES, weights=n[mm])[0]
    R["late_edges"] = LATE_EDGES
    R["t_edges"], R["t_all"], R["t_marley"] = tedges, th_all, th_mar
    R["pe_total"], R["pe_marley"], R["pe_dark"], R["ph_marley"] = map(np.array, (pe_t, pe_m, pe_d, ph_m))
    R["dark"] = np.concatenate(dark) if dark else np.zeros((0, 3))
    R["n1"] = np.array(n1)
    np.savez_compressed(fout, **R)
    print("wrote", fout, "snippets", len(R["snip"]), "hits", len(R["hits"]), "PE", R["pe_total"].sum(),
          "MARLEY PE", R["pe_marley"].sum(), "dark", R["pe_dark"].sum())


if __name__ == "__main__":
    main()
