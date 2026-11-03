REASON = {
    "pit": "more pit-stop time (pit-lane loss plus lost track position)",
    "wear": "heavier tyre wear over its stints",
    "pace": "slower compound pace",
}
GAIN = {"pit": "pit time", "pace": "compound pace", "wear": "tyre wear"}


def pit_laps_from(stint_laps):
    out, total = [], 0
    for n in stint_laps[:-1]:
        total += n
        out.append(total)
    return out


def shape(r):
    return {
        "stops": r["stops"],
        "compounds": r["compounds"].split(" > "),
        "stint_laps": r["stint_laps"],
        "pit_laps": pit_laps_from(r["stint_laps"]),
        "total_s": round(r["total_s"], 2),
        "delta_s": None if r["delta_s"] is None else round(r["delta_s"], 2),
        "cost": {
            "pit": round(r["pit_cost_s"], 2),
            "pace": round(r["pace_cost_s"], 2),
            "wear": round(r["wear_cost_s"], 2),
        },
    }


def why_best(best):
    net = best["wear_cost_s"] + best["pace_cost_s"]
    return (f"Lowest total time cost ({best['total_s']:.1f}s): {best['stops']} stop(s) "
            f"costing {best['pit_cost_s']:.1f}s in pit time, with tyre wear and "
            f"compound pace netting {net:+.1f}s.")


def why_not(best, alt):
    diff = {k: alt[f"{k}_cost_s"] - best[f"{k}_cost_s"] for k in ("pit", "pace", "wear")}
    worse = {k: v for k, v in diff.items() if v > 0.05}
    better = {k: -v for k, v in diff.items() if v < -0.05}
    text = f"{alt['delta_s']:.1f}s slower than the best plan."
    if worse:
        main = max(worse, key=worse.get)
        text += f" Biggest loss: {REASON[main]} (+{worse[main]:.1f}s)."
    if better:
        gains = ", ".join(f"{GAIN[k]} ({v:.1f}s)" for k, v in better.items())
        text += f" It gains on {gains}, but not enough to make up for it."
    return text, {k: round(v, 2) for k, v in diff.items()}


def why_rejected(r):
    return (f"Not viable: {r['limiting_compound']} would have to run about "
            f"{round(r['overrun_laps'])} laps past its usable life here in these conditions.")


def build_response(rows):
    ok = [r for r in rows if r["feasible"]]
    bad = sorted((r for r in rows if not r["feasible"]), key=lambda r: r["overrun_laps"])

    rejected = [{**shape(r), "why_not": why_rejected(r)} for r in bad[:3]]
    if not ok:
        return {"best": None, "alternatives": [], "rejected": rejected,
                "message": "No viable strategy found for these conditions."}

    best = ok[0]
    alternatives = []
    for r in ok[1:4]:
        text, breakdown = why_not(best, r)
        alternatives.append({**shape(r), "why_not": text, "vs_best": breakdown})

    return {
        "best": {**shape(best), "why": why_best(best)},
        "alternatives": alternatives,
        "rejected": rejected,
    }
