#!/usr/bin/env python3
"""
experiments.py - Task 4: run GBN and SR on scenarios A, B, C (200 packets, N=4, k=3,
seed 810) and produce the results table (CSV + Markdown) and the comparison graph.

    python experiments.py            # writes results.csv, results_table.md, gbn_vs_sr.png, logs/*.log
    python experiments.py --seeds 20 # also averages over 20 seeds (810..829)
"""
import argparse
import csv
import os
import statistics

from transport import Config, simulate, summary_text

SEED = 810                       
SCENARIOS = {
    "A: Reliable":    dict(loss=0.00, corrupt=0.00, delay=0.00),
    "B: Loss 0.10":   dict(loss=0.10, corrupt=0.00, delay=0.00),
    "C: Mixed errors": dict(loss=0.05, corrupt=0.05, delay=0.10),
}
BASE = dict(packets=200, window=4, seq_bits=3, timeout_ms=800.0)
HERE = os.path.dirname(os.path.abspath(__file__))


def run_all(seed=SEED, write_logs=False):
    rows = []
    for sname, ch in SCENARIOS.items():
        for proto in ("gbn", "sr"):
            cfg = Config(protocol=proto, seed=seed, **BASE, **ch)
            res = simulate(cfg)
            if write_logs:
                tag = sname.split(":")[0]
                os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
                with open(os.path.join(HERE, "logs", f"scenario_{tag}_{proto}.log"), "w") as f:
                    f.write("\n".join(res.lines) + "\n" + summary_text(res) + "\n")
            rows.append(dict(
                scenario=sname, protocol=proto.upper(), seed=seed,
                transmitted=res.transmitted, retransmissions=res.retransmissions,
                timeouts=res.timeouts, delivered=res.delivered_ok,
                correct="yes" if res.correct else "NO",
                time_s=round(res.sim_time_ms / 1000, 2),
                throughput_kbps=round(res.throughput_kbps, 2),
                utilization_pct=round(res.utilization * 100, 2),
                wall_ms=round(res.wall_s * 1000, 1)))
    return rows


def write_table(rows):
    cols = ["scenario", "protocol", "transmitted", "retransmissions", "timeouts", "delivered", "correct",
            "time_s", "throughput_kbps", "utilization_pct", "wall_ms"]
    with open(os.path.join(HERE, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["seed"] + cols)
        w.writeheader()
        w.writerows(rows)
    head = ["Scenario", "Protocol", "Packets transmitted", "Retransmissions", "Delivered correctly (of 200)",
            "Sim. time (s)", "Throughput (kbit/s)", "Link util. (%)", "Run time (ms)"]
    md = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for r in rows:
        md.append(f"| {r['scenario']} | {r['protocol']} | {r['transmitted']} | {r['retransmissions']} | "
                  f"{r['delivered']} | {r['time_s']:.2f} | {r['throughput_kbps']:.2f} | "
                  f"{r['utilization_pct']:.2f} | {r['wall_ms']:.1f} |")
    text = (f"# Results table (200 packets, N = 4, k = 3, timeout = 800 ms, seed = {SEED})\n\n"
            + "\n".join(md) + "\n\n"
            "Throughput = correctly delivered bits / simulated completion time. "
            "Run time = wall-clock time of the simulation program.\n")
    with open(os.path.join(HERE, "results_table.md"), "w") as f:
        f.write(text)
    return text


def make_graph(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(SCENARIOS)
    short = ["A\nReliable", "B\nLoss 0.10", "C\nLoss .05 / Corr .05 / Delay .10"]
    get = lambda p, key: [next(r[key] for r in rows if r["scenario"] == s and r["protocol"] == p) for s in names]
    colors = {"GBN": "#2f6db5", "SR": "#d9772b"}      # blue / orange: CVD-safe pair
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.0), dpi=160)
    panels = [("retransmissions", "Retransmitted data packets", "Retransmissions (lower is better)"),
              ("throughput_kbps", "Throughput (kbit/s)", "Throughput (higher is better)")]
    w = 0.36
    for ax, (key, ylabel, title) in zip(axes, panels):
        for off, proto in ((-w / 2, "GBN"), (w / 2, "SR")):
            vals = get(proto, key)
            xs = [i + off for i in range(3)]
            bars = ax.bar(xs, vals, w * 0.92, color=colors[proto], label=proto)
            for x, v in zip(xs, vals):
                ax.text(x, v, f"{v:g}" if key == "retransmissions" else f"{v:.1f}",
                        ha="center", va="bottom", fontsize=8, color="#222")
        ax.set_xticks(range(3))
        ax.set_xticklabels(short, fontsize=8)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#e3e3e3", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.margins(y=0.15)
    axes[0].legend(frameon=False, fontsize=9, title="Protocol", title_fontsize=9)
    fig.suptitle(f"GBN vs SR - 200 packets, N = 4, k = 3, seed {SEED}", fontsize=11, y=1.0)
    fig.tight_layout()
    out = os.path.join(HERE, "gbn_vs_sr.png")
    fig.savefig(out, bbox_inches="tight")
    return out


def multi_seed(n):
    """Mean over n seeds (810 .. 810+n-1) to show the single-seed result is typical."""
    agg = {}
    for s in range(SEED, SEED + n):
        for r in run_all(seed=s):
            agg.setdefault((r["scenario"], r["protocol"]), []).append(r)
    out = []
    for (sc, pr), rs in agg.items():
        out.append(dict(scenario=sc, protocol=pr, seeds=n,
                        mean_retransmissions=round(statistics.mean(r["retransmissions"] for r in rs), 1),
                        mean_transmitted=round(statistics.mean(r["transmitted"] for r in rs), 1),
                        mean_time_s=round(statistics.mean(r["time_s"] for r in rs), 2),
                        mean_throughput_kbps=round(statistics.mean(r["throughput_kbps"] for r in rs), 2),
                        all_correct=all(r["correct"] == "yes" for r in rs)))
    with open(os.path.join(HERE, "results_multiseed.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=0, help="also average over this many seeds")
    a = ap.parse_args()
    rows = run_all(write_logs=True)
    print(write_table(rows))
    print("graph:", make_graph(rows))
    if a.seeds:
        for r in multi_seed(a.seeds):
            print(r)
