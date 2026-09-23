# Related code from the Work lab and I-24 MOTION org

What to reuse, what to cite, what to ignore. Checked 2026-10-09.

## Reuse

**I24-MOTION/VT_tools** (Ji et al. 2024, FISTS). Turns fragmented v1.x
trajectories into a clean spatiotemporal speed field, then generates
"virtual trajectories" through it.
- `macro_data_processing.get_speed_mean_field` builds an Edie-box speed
  field (TTD/TTT per cell) straight from the JSON. Same construction as
  `Trajectories.edie()` here, which is reassuring.
- `ASM.smooth_raw_data` is the Treiber–Helbing adaptive smoothing method.
  Its congested-wave kernel assumes `c_cong = 13 mph` (−21 km/h) and the
  free-flow kernel `c_free = −43 mph`. That assumed wave speed is the
  group's working number for I-24 and sits inside our −22 to −25 km/h.
- Use: run ASM on our lane window and estimate wave speed on the smoothed
  field as a cross-check on our raw-grid estimator. Virtual trajectories
  are what the wave-analysis tool consumes, so they are also the path to
  comparing against the published wave catalog.

**I24-MOTION/wave-analysis** (Ji et al. 2026, TR-C 182:105385). Official
stop-and-go wave identification on INCEPTION. Ships `results/wave_cluster/
2022-11-22/lane_{1..4}/wave_front_15.csv` and `wave_tail_15.csv`: traced
wave fronts and tails at a 15 mph critical speed. Fitting space vs time
per trace gives the published wave speed and inter-wave period for
Nov 22, the day one week before ours. That is the reference our estimator
and our simulation both have to hit.

**I24-MOTION/data_tutorial**. Streaming parse with ijson, speed by
differentiating x_position, same as our loader. Nothing more to take.

## Cite

**Lab-Work/AIMSUN_with_AVs** (Wang, Li, Work 2016, TR-C). Mixed
human/AV freeway simulation with inflow penetration sampled from U(0, p)
for p up to 1.0, ten replications each. The lab's own prior
penetration-vs-effect study. The open-road dose-response that replaces
Figure 10 should reference it and use the same replication discipline.

**Lab-Work/TRB_Conference_2016** (Wu, Stern). Fuel consumption in
oscillatory traffic from the ring experiments. Grounds our mean |accel|
fuel proxy.

**Lab-Work/flow** (fork of Berkeley Flow). Ring and highway RL
environments for wave dissipation; the CIRCLES lineage. Compare against,
do not adopt: it drags in SUMO and the RL stack. Relevant only if the
bandit stretch item happens.

## Ignore for this project

VSL controllers (`marl-vsl-controller`, `i24-vsl-orl`), LADDMS lidar
repos, `SUMO_from_data` (signalized arterials), and the 2013–2017 traffic
state estimation filters.
