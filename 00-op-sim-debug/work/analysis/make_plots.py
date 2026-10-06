#!/usr/bin/env python3
"""Before/after plots and numbers for the FD-VD light-simulation bugs (host python3 with numpy + matplotlib).

usage:  make_plots.py <data dir> <figure dir>

Reads <data>/rerun/<config>/<sol|mix>/evt<i>/light.npz (analysis/dump_light.py) and writes, into <figure dir>:
  fig_B_*.pdf, fig_C_*.pdf, fig_D_*.pdf, fig_E_*.pdf, fig_N1_*.pdf   one figure set per bug
  numbers.tex      \\newcommand macros with every number quoted in the note
  numbers.txt      the same numbers, readable
  gates.txt        the reproducibility gates (stock rerun == stored products; each fix changes only what it should)
Configurations (scripts/run_rerun.sh): stock, legacy (= E fixed), fixB, fixC, fixD, fixN1, default, all.
"""
import glob
import math
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

DATA, FIG = sys.argv[1], sys.argv[2]
os.makedirs(FIG, exist_ok=True)
CFGS = ["stock", "legacy", "fixB", "fixC", "fixD", "fixN1", "default", "all"]
WRAP = 1e6          # |TimeStamp| or |PeakTime| above this [us] = wrapped start tick (bug E)
Q_XE = 0.027 * 0.69 / 0.05    # detection probability per simulated Xe photon (QE x Correction / ScintPreScale)
CT = 0.20                     # SiPM cross-talk probability
plt.rcParams.update({"font.size": 9, "axes.titlesize": 9, "legend.fontsize": 8, "figure.dpi": 150,
                     "savefig.bbox": "tight"})
C_BEFORE, C_AFTER, C_REF = "#c0392b", "#2471a3", "#7f8c8d"

# ------------------------------------------------------------------------------------------------- load
D = {}
for f in glob.glob(os.path.join(DATA, "rerun", "*", "*", "evt*", "light.npz")):
    c, s, e = f.split(os.sep)[-4:-1]
    D[(c, s, int(e[3:]))] = dict(np.load(f, allow_pickle=False))
EV = {s: sorted({i for (c, ss, i) in D if ss == s and all((cc, s, i) in D for cc in CFGS)}) for s in ("sol", "mix")}
print("complete events:", {s: len(v) for s, v in EV.items()})
NUM = {}


def num(name, value, fmt):
    NUM[name] = (value, fmt.format(value) if not isinstance(value, str) else value)


def ev(c, s):
    return [D[(c, s, i)] for i in EV[s]]


def tot(c, s, key, f=lambda x: x):
    return float(sum(f(d[key]) for d in ev(c, s)))


def save(fig, name):
    fig.savefig(os.path.join(FIG, name))
    plt.close(fig)


num("Nsol", len(EV["sol"]), "{:d}")
num("Nmix", len(EV["mix"]), "{:d}")

# ------------------------------------------------------------------------------------------------- gates
G = ["# reproducibility gates"]
for s in ("sol", "mix"):
    for i in EV[s]:
        st, lg = D[("stock", s, i)], D[("legacy", s, i)]
        g1 = st["wfhash"] == st["wfhash_stored"] and all(st["divhash"] == st["divhash_stored"])
        g2 = all(lg["divhash"] == st["divhash"])
        # legacy differs from stock only by bug E: the snippets that differ are wrapped ones (stock) and snippets
        # starting at the first tick of the window (legacy)
        key = lambda a: set(map(tuple, np.round(a, 6)))  # noqa: E731
        ks, kl = key(st["snip"]), key(lg["snip"])
        only_s, only_l = ks - kl, kl - ks
        g3 = all(abs(x[1]) > WRAP for x in only_s) and all(abs(x[1] + 4255.0) < 1e-3 for x in only_l)
        gB = all(D[("fixB", s, i)]["divhash"] == lg["divhash"])
        gC = all(D[("fixC", s, i)]["divhash"][[1, 3]] == lg["divhash"][[1, 3]])
        G.append(f"{s} {i:3d}  stock==stored {g1}  legacy DivRec==stock {g2}  legacy-vs-stock snippets differ only "
                 f"by E {g3} ({len(only_s)} wrapped -> {len(only_l)} clamped)  fixB DivRec unchanged {gB}  "
                 f"fixC Xe DivRec unchanged {gC}")
        for k, v in (("stock_eq_stored", g1), ("legacy_div_eq", g2), ("E_only", g3), ("B_div", gB), ("C_xe", gC)):
            NUM.setdefault("gate_" + k, [0, 0])
            NUM["gate_" + k][0] += int(v)
            NUM["gate_" + k][1] += 1
for s in ("sol", "mix"):
    same = [i for i in EV[s] if D[("fixB", s, i)]["wfhash"] == D[("legacy", s, i)]["wfhash"]]
    nolap = [i for i in EV[s] if D[("legacy", s, i)]["dup"][1] == 0]
    NUM[f"gate_Bident_{s}"] = (len(same), f"{len(same)}/{len(EV[s])}")
    NUM[f"gate_Bnolap_{s}"] = (len(nolap), f"{len(nolap)}/{len(EV[s])}")
    NUM[f"gate_Bidentnolap_{s}"] = (int(set(nolap) <= set(same)), "yes" if set(nolap) <= set(same) else "NO")
    G.append(f"{s}: fixB waveforms identical to legacy in {len(same)} events {same}; legacy has no sample stored "
             f"twice in {len(nolap)} events {nolap}")
for k in [k for k in NUM if k.startswith("gate_") and isinstance(NUM[k], list)]:
    p, n = NUM[k]
    NUM[k] = (p, f"{p}/{n}")
open(os.path.join(FIG, "gates.txt"), "w").write("\n".join(G) + "\n")

# ------------------------------------------------------------------------------------------------- bug B
def hit_dups(h):
    """duplicate OpHits: same channel and PeakTime as another hit; the largest-area copy is kept"""
    if not len(h):
        return np.zeros(0, bool)
    order = np.lexsort((-h[:, 3], h[:, 1], h[:, 0]))
    hs = h[order]
    same = np.r_[False, (hs[1:, 0] == hs[:-1, 0]) & (hs[1:, 1] == hs[:-1, 1])]
    dup = np.zeros(len(h), bool)
    dup[order[same]] = True
    return dup


for c in ("legacy", "fixB", "default", "stock"):
    for s in ("sol", "mix"):
        sa, ag = tot(c, s, "dup", lambda x: x[0]), tot(c, s, "dup", lambda x: x[1])
        nh = tot(c, s, "hits", len)
        good = lambda h: h[np.abs(h[:, 1]) < WRAP] if len(h) else h  # noqa: E731
        nd = sum(hit_dups(good(d["hits"])).sum() for d in ev(c, s))
        pe = tot(c, s, "hits", lambda h: h[:, 4].sum() if len(h) else 0)
        ped = sum(good(d["hits"])[hit_dups(good(d["hits"])), 4].sum() for d in ev(c, s))
        num(f"B{c}{s}samples", sa / 1e6, "{:.1f}")
        num(f"B{c}{s}again", 100 * ag / max(sa, 1), "{:.2f}")
        num(f"B{c}{s}snip", tot(c, s, "snip", len), "{:,.0f}")
        num(f"B{c}{s}hits", nh, "{:,.0f}")
        num(f"B{c}{s}duphits", 100 * nd / max(nh, 1), "{:.2f}")
        num(f"B{c}{s}hitpe", pe, "{:,.0f}")
        num(f"B{c}{s}duppe", 100 * ped / max(pe, 1e-9), "{:.2f}")
        num(f"B{c}{s}dedupe", pe - ped, "{:,.0f}")
        num(f"B{c}{s}dedhits", nh - nd, "{:,.0f}")
        rms = np.concatenate([d["snip"][(d["snip"][:, 3] >= 0) & (np.abs(d["snip"][:, 1]) < WRAP), 3] for d in ev(c, s)])
        num(f"B{c}{s}rms", float(np.median(rms)), "{:.2f}")

# B1: one channel, before and after.  The example (mixed event 4, OpChannel 601, -296.7 us) was picked as a place with
# >= 3 legacy snippets starting on the same tick where the legacy and the fixed readout cover exactly the same samples
# (12 such places in mixed events 0-19).  Elsewhere the readouts also differ because the doubled noise of bug B fires
# extra triggers.
EX_EV, EX_CH, EX_T = 4, 601, -18542 * 0.016
d0, d1 = D[("legacy", "mix", EX_EV)], D[("fixB", "mix", EX_EV)]


def window(d):
    s_ = d["snip"]
    m = (s_[:, 0] == EX_CH) & (s_[:, 1] > EX_T - 7) & (s_[:, 1] < EX_T + 12)
    rows = s_[m][np.argsort(s_[m][:, 1], kind="stable")]
    ticks = set()
    for r in rows:
        t0 = int(round(r[1] / 0.016))
        ticks.update(range(t0, t0 + int(r[2])))
    return rows, ticks


fig, axs = plt.subplots(2, 1, figsize=(7, 3.4), sharex=True)
for ax, d, lab, col in ((axs[0], d0, "before (legacy)", C_BEFORE), (axs[1], d1, "after (MergeOverlappingRanges)", C_AFTER)):
    rows, ticks = window(d)
    for k, r in enumerate(rows):
        ax.barh(k, r[2] * 0.016, left=r[1] - EX_T, height=0.7, color=col, alpha=0.8)
    ax.set_yticks([])
    ax.set_ylim(-0.6, max(len(rows), 2) - 0.4)
    ax.set_ylabel("snippets")
    ax.set_title(f"{lab}: {len(rows)} snippet{'s' if len(rows) > 1 else ''}, {int(rows[:, 2].sum())} samples stored, "
                 f"{len(ticks)} of them different", loc="left")
axs[1].set_xlabel(f"time [us] relative to {EX_T:.2f} us   (OpChannel {EX_CH}, mixed event {EX_EV})")
save(fig, "fig_B_snippets.pdf")

# B2: summary bars
fig, axs = plt.subplots(1, 3, figsize=(7.2, 2.6))
items = [("samples stored twice [%]", "again"), ("duplicate OpHits [%]", "duphits"), ("PE in duplicate OpHits [%]", "duppe")]
for ax, (title, k) in zip(axs, items):
    vals = [NUM[f"Blegacymix{k}"][0], NUM[f"BfixBmix{k}"][0], NUM[f"Blegacysol{k}"][0]]
    bars = ax.bar(["mixed\nbefore", "mixed\nafter", "solar-only\nbefore"], vals, color=[C_BEFORE, C_AFTER, C_REF])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_title(title)
    ax.set_ylim(0, max(vals) * 1.25 + 0.5)
save(fig, "fig_B_summary.pdf")

# B3: baseline noise
fig, ax = plt.subplots(figsize=(4.6, 2.8))
bins = np.linspace(0, 8, 81)
for c, s, lab, col, ls in (("legacy", "mix", "mixed, before", C_BEFORE, "-"), ("fixB", "mix", "mixed, after", C_AFTER, "-"),
                           ("legacy", "sol", "solar-only", C_REF, "--")):
    r = np.concatenate([d["snip"][(d["snip"][:, 3] >= 0) & (np.abs(d["snip"][:, 1]) < WRAP), 3] for d in ev(c, s)])
    ax.hist(r, bins, histtype="step", density=True, color=col, ls=ls, lw=1.4,
            label=f"{lab}: median {np.median(r):.2f} ADC")
ax.axvline(2.6, color="k", lw=0.6, ls=":")
ax.axvline(2.6 * math.sqrt(2), color="k", lw=0.6, ls=":")
ax.text(2.6, 0.9, "2.6 ", fontsize=7, ha="right", transform=ax.get_xaxis_transform())
ax.text(3.68, 0.9, r" 2.6$\sqrt{2}$", fontsize=7, ha="left", transform=ax.get_xaxis_transform())
ax.set_xlabel("RMS of the first 15 samples of each snippet [ADC]")
ax.set_ylabel("snippets (normalised)")
ax.legend(frameon=False, loc="center right", fontsize=7)
ax.set_xlim(0, 8)
save(fig, "fig_B_noise.pdf")

# ------------------------------------------------------------------------------------------------- bug C
for c in ("legacy", "fixC", "stock", "all", "default"):
    for s in ("sol", "mix"):
        pe = tot(c, s, "pe_marley", lambda x: x[0])
        ph = tot(c, s, "ph_marley", lambda x: x[0])
        num(f"C{c}{s}ratio", pe / max(ph, 1), "{:.3f}")
        num(f"C{c}{s}marley", tot(c, s, "pe_marley", np.sum), "{:,.0f}")
        num(f"C{c}{s}total", tot(c, s, "pe_total", np.sum), "{:,.0f}")
for s in ("sol", "mix"):
    num(f"Cgain{s}marley", 100 * (NUM[f"CfixC{s}marley"][0] / NUM[f"Clegacy{s}marley"][0] - 1), "{:.1f}")
    num(f"Cgain{s}total", 100 * (NUM[f"CfixC{s}total"][0] / NUM[f"Clegacy{s}total"][0] - 1), "{:.1f}")
    num(f"Cgain{s}ratio", NUM[f"Clegacy{s}ratio"][0] / NUM[f"CfixC{s}ratio"][0], "{:.3f}")

fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.8))
for ax, s, title in ((axs[0], "sol", "solar-only"), (axs[1], "mix", "mixed (with radiological background)")):
    ds = [d for d in ev("legacy", s) if "late_evt" in d]
    e = ds[0]["late_edges"]
    he = sum(d["late_evt"] for d in ds)
    ht = sum(d["late_trk"] for d in ds)
    x = np.maximum(e[:-1], 0.5)
    ax.stairs(he / he.sum(), np.r_[0.5, e[1:]], color=C_BEFORE, lw=1.4,
              label="before: reference = first photon of the event")
    ax.stairs(ht / ht.sum(), np.r_[0.5, e[1:]], color=C_AFTER, lw=1.4,
              label="after: reference = first photon of the same track")
    ax.set_ylim(0, 1.25 * max((he / he.sum()).max(), (ht / ht.sum()).max()))
    ax.axvspan(0.5, 10, color="0.9", zorder=0)
    yt = ax.get_ylim()[1]
    ax.text(0.6, 0.97 * yt, "kept", fontsize=7, va="top")
    ax.text(14, 0.97 * yt, "'late': x0.31", fontsize=7, va="top")
    ax.text(14, 0.85 * yt, f"photons < 10 ns:\n  before {100 * he[:3].sum() / he.sum():.0f}%\n  after {100 * ht[:3].sum() / ht.sum():.0f}%",
            fontsize=7, va="top")
    ax.set_xscale("log")
    ax.set_title(title)
axs[0].set_ylabel("fraction of photons")
fig.supxlabel("arrival time of the MARLEY argon photons after the reference [ns]", fontsize=9, y=-0.04)
h, l = axs[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.17))
save(fig, "fig_C_arrival.pdf")

fig, ax = plt.subplots(figsize=(4.6, 2.8))
xs = np.arange(2)
for k, (c, lab, col) in enumerate((("legacy", "before (event reference)", C_BEFORE), ("fixC", "after (track reference)", C_AFTER))):
    v = [NUM[f"C{c}solratio"][0], NUM[f"C{c}mixratio"][0]]
    b = ax.bar(xs + (k - 0.5) * 0.36, v, 0.36, color=col, label=lab)
    for bb, vv in zip(b, v):
        ax.text(bb.get_x() + bb.get_width() / 2, vv, f"{vv:.3f}", ha="center", va="bottom", fontsize=8)
ax.set_xticks(xs, ["solar-only", "mixed"])
ax.set_ylabel("MARLEY Ar PE per Ar photon")
ax.set_ylim(0, 0.3)
ax.legend(frameon=False, loc="upper right")
save(fig, "fig_C_yield.pdf")

# ------------------------------------------------------------------------------------------------- bug D
for c in ("legacy", "fixD"):
    t = np.concatenate([d["dark"][:, 2] for s in ("sol", "mix") for d in ev(c, s)])
    num(f"D{c}n", len(t), "{:,d}")
    num(f"D{c}near", 100 * np.mean(np.abs(t) < 5000), "{:.1f}")
    num(f"D{c}min", t.min() / 1000, "{:.2f}")
    num(f"D{c}max", t.max() / 1000, "{:.2f}")
num("Dperevent", NUM["Dlegacyn"][0] / (len(EV["sol"]) + len(EV["mix"])), "{:.1f}")
fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.6), sharey=True)
for ax, c, lab, col in ((axs[0], "legacy", "before", C_BEFORE), (axs[1], "fixD", "after", C_AFTER)):
    t = np.concatenate([d["dark"][:, 2] for s in ("sol", "mix") for d in ev(c, s)]) / 1000.0
    ax.hist(t, np.linspace(-4300, 4300, 87), color=col, alpha=0.8)
    ax.set_yscale("log")
    ax.set_xlabel("dark-count time [us]")
    ax.set_title(f"{lab}: {len(t)} dark PE, {100 * np.mean(np.abs(t) < 5):.0f}% within $\\pm$5 us of t = 0", fontsize=8)
    ax.axvspan(-4255, 4255, color="0.93", zorder=0)
    ax.set_ylim(0.5, 5000)
axs[0].set_ylabel("dark PE / 100 us")
save(fig, "fig_D_dark.pdf")

# ------------------------------------------------------------------------------------------------- bug E
for c in ("stock", "legacy"):
    for s in ("sol", "mix"):
        num(f"E{c}{s}snip", tot(c, s, "snip", lambda a: (np.abs(a[:, 1]) > WRAP).sum()), "{:,.0f}")
        num(f"E{c}{s}hits", tot(c, s, "hits", lambda a: (np.abs(a[:, 1]) > WRAP).sum() if len(a) else 0), "{:,.0f}")
        num(f"E{c}{s}first", tot(c, s, "snip", lambda a: (np.abs(a[:, 1] + 4255.0) < 1e-3).sum()), "{:,.0f}")
wr = [d["snip"][np.abs(d["snip"][:, 1]) > WRAP, 1] for d in ev("stock", "mix")]
wv = float(np.concatenate(wr).min()) if sum(map(len, wr)) else 0.0
ex = int(math.floor(math.log10(wv))) if wv > 0 else 0
num("Ewrapvalue", f"${wv / 10 ** ex:.2f}\\times10^{{{ex}}}$", "{}")
fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.6), gridspec_kw={"width_ratios": [2.2, 1]})
per_s = [int((np.abs(d["snip"][:, 1]) > WRAP).sum()) for d in ev("stock", "mix")]
per_l = [int((np.abs(d["snip"][:, 1]) > WRAP).sum()) for d in ev("legacy", "mix")]
x = np.arange(len(per_s))
axs[0].bar(x - 0.2, per_s, 0.4, color=C_BEFORE, label=f"before: {sum(per_s)} snippets at {NUM['Ewrapvalue'][1]} us")
axs[0].bar(x + 0.2, per_l, 0.4, color=C_AFTER, label=f"after: {sum(per_l)}")
axs[0].set_xticks(x, [str(i) for i in EV["mix"]], fontsize=6)
axs[0].set_xlabel("mixed event")
axs[0].set_ylabel("snippets with wrapped start")
axs[0].legend(frameon=False)
for c, lab, col in (("stock", "before", C_BEFORE), ("legacy", "after", C_AFTER)):
    t = np.concatenate([d["snip"][:, 1] for d in ev(c, "mix")])
    t = t[(t > -4256) & (t < -4245)]
    axs[1].hist(t, np.linspace(-4255.5, -4245.5, 21), histtype="step", lw=1.4, color=col, label=lab)
axs[1].set_xlabel("snippet start [us]")
axs[1].set_title("start of the readout window", fontsize=8)
axs[1].legend(frameon=False)
save(fig, "fig_E_wrapped.pdf")

# ------------------------------------------------------------------------------------------------- bug N1
def pe_dist(k_dist, nmax=15):
    """PE distribution: k detected photons, each 1 + Geometric(CT) PE (the SIPMOpSensorSim cross-talk recursion)"""
    one = np.array([(1 - CT) * CT ** (g - 1) if g >= 1 else 0 for g in range(nmax + 1)])
    out, conv = np.zeros(nmax + 1), np.zeros(nmax + 1)
    conv[0] = 1
    for k, pk in enumerate(k_dist):
        out += pk * conv
        conv = np.convolve(conv, one)[:nmax + 1]
    return out


def pred(n, binomial):
    if binomial:
        k = [math.comb(n, j) * Q_XE ** j * (1 - Q_XE) ** (n - j) for j in range(n + 1)]
    else:
        lam = Q_XE * n
        k = [math.exp(-lam) * lam ** j / math.factorial(j) for j in range(16)]
    return pe_dist(k)


fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.8))
pe = np.arange(16)
for c, lab, col, b in (("legacy", "before", C_BEFORE, False), ("fixN1", "after", C_AFTER, True)):
    m = sum(d["n1"][1] + d["n1"][3] for s in ("sol", "mix") for d in ev(c, s))   # the two Xe products
    for n in (1,):
        f = m[n] / m[n].sum()
        axs[0].plot(pe[:7], f[:7], "o", color=col, ms=4, label=f"{lab}: P(0) = {f[0]:.3f}")
        axs[0].plot(pe[:7], pred(n, b)[:7], "-", color=col, lw=0.9)
        num(f"N{c}P0", f[0], "{:.3f}")
        num(f"N{c}Pgt", 100 * f[2:].sum(), "{:.1f}")
        num(f"N{c}cells", m[n].sum(), "{:,.0f}")
    vm = []
    for n in range(1, 6):
        if m[n].sum() < 50:
            vm.append(np.nan)
            continue
        f = m[n] / m[n].sum()
        mu = (f * pe).sum()
        vm.append(((f * pe ** 2).sum() - mu ** 2) / mu)
    axs[1].plot(range(1, 6), vm, "o", color=col, ms=4, label=lab)
    pv = []
    for n in range(1, 6):
        p = pred(n, b)
        mu = (p * pe).sum()
        pv.append(((p * pe ** 2).sum() - mu ** 2) / mu)
    axs[1].plot(range(1, 6), pv, "-", color=col, lw=0.9)
    num(f"N{c}vm", vm[0], "{:.2f}")
num("Npredpoisson", math.exp(-Q_XE), "{:.3f}")
num("Npredbinomial", 1 - Q_XE, "{:.3f}")
num("Nq", Q_XE, "{:.3f}")
axs[0].set_xlabel("PE stored for a single Xe photon (N = 1)")
axs[0].set_ylabel("fraction of cells")
axs[0].set_yscale("log")
axs[0].legend(frameon=False, title="points: simulation, lines: expectation", title_fontsize=7)
axs[1].set_xlabel("photons N in the cell")
axs[1].set_ylabel("variance / mean of the PE")
axs[1].legend(frameon=False)
save(fig, "fig_N1_qe.pdf")

# ------------------------------------------------------------------------------------------------- overall
for c in ("stock", "default", "all"):
    for s in ("sol", "mix"):
        num(f"O{c}{s}pe", tot(c, s, "pe_total", np.sum), "{:,.0f}")
        num(f"O{c}{s}hits", tot(c, s, "hits", lambda a: (np.abs(a[:, 1]) < WRAP).sum() if len(a) else 0), "{:,.0f}")
        num(f"O{c}{s}hitpe", tot(c, s, "hits", lambda a: a[np.abs(a[:, 1]) < WRAP, 4].sum() if len(a) else 0), "{:,.0f}")
        num(f"O{c}{s}marley", tot(c, s, "pe_marley", np.sum), "{:,.0f}")

for s in ("sol", "mix"):
    n = len(EV[s])
    num(f"A{s}pe", NUM[f"Ostock{s}pe"][0] / n, "{:,.0f}")
    num(f"A{s}marley", NUM[f"Ostock{s}marley"][0] / n, "{:,.0f}")
    num(f"A{s}hits", NUM[f"Ostock{s}hits"][0] / n, "{:,.0f}")
    num(f"A{s}snip", tot("stock", s, "snip", len) / n, "{:,.0f}")
    num(f"A{s}samples", tot("stock", s, "dup", lambda x: x[0]) / n / 1e6, "{:.1f}")

# light versus time in one mixed event
d = D[("stock", "mix", EV["mix"][0])]
if "t_all" in d:
    e, ta, tm = d["t_edges"], d["t_all"], d["t_marley"]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.6), gridspec_kw={"width_ratios": [1.6, 1]})
    axs[0].stairs(ta / 1000.0, e, color=C_REF, fill=True, alpha=0.6, label=f"all light: {ta.sum():,.0f} PE")
    axs[0].stairs(tm / 1000.0, e, color=C_BEFORE, lw=1.2, label=f"MARLEY: {tm.sum():,.0f} PE")
    axs[0].set_xlabel("time [us]")
    axs[0].set_ylabel("thousand PE / us")
    axs[0].set_title(f"mixed event {EV['mix'][0]}: the whole light readout window")
    axs[0].legend(frameon=False, loc="upper right")
    m = (e[:-1] >= -20) & (e[:-1] < 20)
    axs[1].stairs(ta[m], e[np.r_[m, False] | np.r_[False, m]], color=C_REF, fill=True, alpha=0.6, label="all")
    axs[1].stairs(tm[m], e[np.r_[m, False] | np.r_[False, m]], color=C_BEFORE, lw=1.2, label="MARLEY")
    axs[1].set_xlabel("time [us]")
    axs[1].set_ylabel("PE / us")
    axs[1].set_title("zoom: +-20 us around the neutrino")
    axs[1].legend(frameon=False)
    save(fig, "fig_overview_light.pdf")
    num("Aexbkgpe", float(ta.sum() - tm.sum()), "{:,.0f}")
    num("Aexmarleype", float(tm.sum()), "{:,.0f}")
    num("Aexbkgperus", float(np.median(ta - tm)), "{:,.0f}")

# ------------------------------------------------------------------------------------------------- write
def macro(k):
    words = dict(zip("0123456789", ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]))
    return "\\" + "num" + re.sub(r"[^A-Za-z]", "", "".join(words.get(ch, ch) for ch in k))


with open(os.path.join(FIG, "numbers.tex"), "w") as f:
    for k, (v, s) in sorted(NUM.items()):
        f.write("\\newcommand{%s}{%s}\n" % (macro(k), s.replace("%", "\\%")))
with open(os.path.join(FIG, "numbers.txt"), "w") as f:
    for k, (v, s) in sorted(NUM.items()):
        f.write(f"{k:28s} {s:>14s}   {macro(k)}\n")
print(open(os.path.join(FIG, "numbers.txt")).read())
