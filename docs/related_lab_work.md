# Code from the Work lab and the I-24 MOTION org

I went through both GitHub orgs to see what I should be reusing or citing
instead of rebuilding. Three repos I'm using directly, three I'm citing,
and the rest aren't relevant to this project.

## Using

**I24-MOTION/VT_tools** (Ji et al. 2024, FISTS). Turns fragmented v1.x
trajectories into a clean spatiotemporal speed field, then generates
"virtual trajectories" through it.
- `macro_data_processing.get_speed_mean_field` builds an Edie-box speed
  field (TTD/TTT per cell) straight from the JSON. That's the same
  construction as my `Trajectories.edie()`, which was reassuring to find.
- `ASM.smooth_raw_data` is the Treiber–Helbing adaptive smoothing method.
  Its congested-wave kernel assumes `c_cong = 13 mph` (−21 km/h) and the
  free-flow kernel `c_free = −43 mph`. So the group's working wave speed
  for I-24 is 21 km/h, which is what I measured.
- I ran their ASM on my lane-3 window and re-estimated wave speed on the
  smoothed field as a check on my own estimator. They agree.

**I24-MOTION/wave-analysis** (Ji et al. 2026, TR-C 182:105385). The
group's stop-and-go wave identification on INCEPTION. It ships
`results/wave_cluster/2022-11-22/lane_{1..4}/CC_15.csv` with clustered
wave fronts and tails at a 15 mph critical speed. Fitting space against
time per cluster gave me the published wave speed (19.3 km/h, lane 3) and
inter-wave period (8.5 min at MM 60) for Nov 22, one week before my day.
That's the reference my estimator and my simulation both have to hit.

**I24-MOTION/data_tutorial**. Streaming parse with ijson, speed by
differentiating x_position. My loader does the same thing; nothing more to
take from it.

## Citing

**Lab-Work/AIMSUN_with_AVs** (Wang, Li, Work 2016, TR-C). Mixed human/AV
freeway simulation with inflow penetration sampled from U(0, p) for p up
to 1.0, ten replications each. The lab's own penetration-vs-effect study.
My open-road dose-response that replaces Figure 10 should cite it and use
the same replication discipline.

**Lab-Work/TRB_Conference_2016** (Wu, Stern). Fuel consumption in
oscillatory traffic from the ring experiments. Backs my use of mean |accel|
as a fuel proxy.

**Lab-Work/flow** (fork of Berkeley Flow). Ring and highway RL
environments for wave dissipation; the CIRCLES lineage. I'll compare
against it rather than adopt it, since it drags in SUMO and the RL stack.
Only relevant if the bandit stretch item happens.

## Not relevant here

VSL controllers (`marl-vsl-controller`, `i24-vsl-orl`), the LADDMS lidar
repos, `SUMO_from_data` (signalized arterials), and the 2013–2017 traffic
state estimation filters.
