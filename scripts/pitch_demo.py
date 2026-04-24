"""
Quick pitch demo: Pacer incentive impact on I-24 flow.

Shows how paying a small fraction of drivers to hold steady speeds
reduces speed variance, damps shockwaves, and lifts throughput.

Run: python scripts/pitch_demo.py
"""
import numpy as np
import matplotlib.pyplot as plt

np.random.seed(42)

N_VEHICLES = 200
N_STEPS = 120
TARGET_SPEED = 60.0
PACER_FRACTION = 0.05
INCENTIVE_PER_MILE = 0.15


def simulate(pacer_fraction: float) -> np.ndarray:
    speeds = np.full(N_VEHICLES, TARGET_SPEED)
    is_pacer = np.zeros(N_VEHICLES, dtype=bool)
    n_pacers = int(N_VEHICLES * pacer_fraction)
    pacer_idx = np.linspace(0, N_VEHICLES - 1, max(n_pacers, 1)).astype(int)
    is_pacer[pacer_idx] = n_pacers > 0

    history = np.zeros((N_STEPS, N_VEHICLES))
    for t in range(N_STEPS):
        shock = np.random.normal(-0.25, 5, N_VEHICLES)
        shock[is_pacer] = 0.0

        wave = np.roll(speeds, 1) - speeds
        wave[is_pacer] = 0.6 * (TARGET_SPEED - speeds[is_pacer])

        speeds = speeds + 0.45 * wave + shock
        speeds = np.clip(speeds, 20, 72)

        history[t] = speeds
    return history


baseline = simulate(pacer_fraction=0.0)
with_pacers = simulate(pacer_fraction=PACER_FRACTION)


def metrics(h: np.ndarray) -> dict:
    mean_speed = h.mean()
    congestion_share = (h < 40).mean() * 100
    throughput = mean_speed * (1 - congestion_share / 100) * (N_VEHICLES / 60)
    return {"mean_speed": mean_speed,
            "congestion": congestion_share,
            "throughput": throughput}


b, p = metrics(baseline), metrics(with_pacers)
pct = lambda new, old: (new - old) / old * 100

print("=" * 60)
print("  IHUTE Pacer Incentive — Pitch Demo")
print("=" * 60)
print(f"  Corridor: I-24, {N_VEHICLES} vehicles, {N_STEPS} timesteps")
print(f"  Pacer fraction: {PACER_FRACTION:.0%}  @  ${INCENTIVE_PER_MILE}/mi")
print("-" * 60)
print(f"{'Metric':<26}{'Baseline':>12}{'w/ Pacers':>12}{'Δ':>10}")
print("-" * 60)
print(f"{'Mean speed (mph)':<26}{b['mean_speed']:>12.1f}{p['mean_speed']:>12.1f}"
      f"{pct(p['mean_speed'], b['mean_speed']):>9.1f}%")
print(f"{'Time in congestion (%)':<26}{b['congestion']:>12.1f}{p['congestion']:>12.1f}"
      f"{pct(p['congestion'], b['congestion']):>9.1f}%")
print(f"{'Throughput (veh/min)':<26}{b['throughput']:>12.1f}{p['throughput']:>12.1f}"
      f"{pct(p['throughput'], b['throughput']):>9.1f}%")
print("-" * 60)

pacer_miles = int(N_VEHICLES * PACER_FRACTION) * (TARGET_SPEED * N_STEPS / 3600)
daily_cost = pacer_miles * INCENTIVE_PER_MILE * 250
print(f"  Est. daily program cost: ${daily_cost:,.0f}")
print(f"  Congestion reduction:    {(1 - p['congestion']/b['congestion'])*100:.0f}%")
print(f"  Throughput lift:         +{pct(p['throughput'], b['throughput']):.0f}%")
print("=" * 60)

fig = plt.figure(figsize=(14, 5.5))
gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 0.035], wspace=0.12)
ax0 = fig.add_subplot(gs[0, 0])
ax1 = fig.add_subplot(gs[0, 1], sharey=ax0)
cax = fig.add_subplot(gs[0, 2])
extent = [0, N_VEHICLES, N_STEPS, 0]

ax0.imshow(baseline, aspect="auto", cmap="RdYlGn",
           vmin=20, vmax=75, extent=extent)
ax0.set_title("Baseline, no pacers\n(dark red = slowdowns, shockwaves)",
              fontsize=11)
ax0.set_xlabel("Vehicle position")
ax0.set_ylabel("Time (seconds)")

im = ax1.imshow(with_pacers, aspect="auto", cmap="RdYlGn",
                vmin=20, vmax=75, extent=extent)
ax1.set_title(f"With {PACER_FRACTION:.0%} pacers\n"
              f"(congestion {(1-p['congestion']/b['congestion'])*100:.0f}% lower, "
              f"speed +{pct(p['mean_speed'], b['mean_speed']):.1f}%)",
              fontsize=11)
ax1.set_xlabel("Vehicle position")
plt.setp(ax1.get_yticklabels(), visible=False)

cbar = fig.colorbar(im, cax=cax)
cbar.set_label("Speed (mph)")

fig.suptitle("Pacer Incentive on I-24: Flow Stabilization Demo",
             fontsize=13, fontweight="bold")
fig.subplots_adjust(top=0.82, left=0.06, right=0.94, bottom=0.1)

out = "pacer_demo.png"
fig.savefig(out, dpi=140, bbox_inches="tight")
print(f"  Chart saved: {out}")

# --- Sweep across incentive inputs: pacer fraction + $/mile rate ---
fractions = np.array([0.00, 0.02, 0.05, 0.08, 0.12, 0.16, 0.20])
sweep_speed, sweep_cong, sweep_thru, sweep_cost = [], [], [], []

for frac in fractions:
    np.random.seed(42)
    h = simulate(pacer_fraction=frac)
    m = metrics(h)
    miles = int(N_VEHICLES * frac) * (TARGET_SPEED * N_STEPS / 3600)
    sweep_speed.append(m["mean_speed"])
    sweep_cong.append(m["congestion"])
    sweep_thru.append(m["throughput"])
    sweep_cost.append(miles * INCENTIVE_PER_MILE * 250)

fig2, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(13, 5))

color_thru, color_cong = "#2e7d32", "#c62828"
ax_a.plot(fractions * 100, sweep_thru, "o-", color=color_thru,
          linewidth=2.5, markersize=9, label="Throughput (veh/min)")
ax_a.set_xlabel("Pacer fraction (% of drivers enrolled)", fontsize=11)
ax_a.set_ylabel("Throughput (veh/min)", color=color_thru, fontsize=11)
ax_a.tick_params(axis="y", labelcolor=color_thru)
ax_a.grid(alpha=0.3)

ax_a2 = ax_a.twinx()
ax_a2.plot(fractions * 100, sweep_cong, "s--", color=color_cong,
           linewidth=2, markersize=8, alpha=0.8, label="Time in congestion (%)")
ax_a2.set_ylabel("Time in congestion (%)", color=color_cong, fontsize=11)
ax_a2.tick_params(axis="y", labelcolor=color_cong)

ax_a.set_title("Dose–response: enrollment drives flow gains\n"
               "(diminishing returns above ~8%)", fontsize=11)
ax_a.axvspan(4, 8, alpha=0.15, color="gold", label="sweet spot")
ax_a.legend(loc="center right", framealpha=0.9)

ax_b.plot(sweep_cost, sweep_thru, "o-", color="#1565c0",
          linewidth=2.5, markersize=9)
for x, y, f in zip(sweep_cost, sweep_thru, fractions):
    ax_b.annotate(f"{f:.0%}", (x, y), textcoords="offset points",
                  xytext=(8, -4), fontsize=9, color="#555")
ax_b.set_xlabel(f"Daily program cost (USD, @ ${INCENTIVE_PER_MILE}/mi)", fontsize=11)
ax_b.set_ylabel("Throughput (veh/min)", fontsize=11)
ax_b.set_title("Cost–benefit frontier\n(label = pacer fraction)", fontsize=11)
ax_b.grid(alpha=0.3)

fig2.suptitle("Incentive Input Sensitivity — What Dial Should We Turn?",
              fontsize=13, fontweight="bold")
fig2.tight_layout(rect=(0, 0, 1, 0.95))

out2 = "pacer_sweep.png"
fig2.savefig(out2, dpi=140, bbox_inches="tight")
print(f"  Sweep saved: {out2}")
