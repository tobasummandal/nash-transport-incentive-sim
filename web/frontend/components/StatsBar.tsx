"use client";

import type { RunResult } from "@/app/page";

interface Props {
  baseline: RunResult;
  incentivized: RunResult;
}

function Stat({
  label,
  baseVal,
  incVal,
  unit,
  lowerBetter,
}: {
  label: string;
  baseVal: number;
  incVal: number;
  unit?: string;
  lowerBetter?: boolean;
}) {
  const diff = incVal - baseVal;
  const pct = baseVal !== 0 ? (diff / baseVal) * 100 : 0;
  const improved = lowerBetter ? diff < 0 : diff > 0;
  const diffColor = improved
    ? "text-[var(--accent-green)]"
    : Math.abs(pct) < 0.5
    ? "text-[var(--text-muted)]"
    : "text-[var(--accent-red)]";

  return (
    <div className="flex flex-col items-center gap-0.5 min-w-[90px]">
      <span className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <div className="flex items-baseline gap-1.5">
        <span className="text-xs font-mono text-[var(--text-muted)] tabular-nums">
          {fmt(baseVal)}
        </span>
        <span className="text-[10px] text-[var(--text-muted)]">→</span>
        <span className="text-xs font-mono font-bold text-[var(--text-primary)] tabular-nums">
          {fmt(incVal)}
          {unit && (
            <span className="text-[var(--text-muted)] font-normal ml-0.5 text-[10px]">
              {unit}
            </span>
          )}
        </span>
      </div>
      {Math.abs(pct) >= 0.5 && (
        <span className={`text-[10px] font-mono tabular-nums ${diffColor}`}>
          {pct > 0 ? "+" : ""}
          {pct.toFixed(1)}%
        </span>
      )}
    </div>
  );
}

function Solo({
  label,
  value,
  color,
  unit,
}: {
  label: string;
  value: string | number;
  color?: string;
  unit?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-[70px]">
      <span className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <span
        className={`text-xs font-mono font-bold tabular-nums ${
          color ?? "text-[var(--text-primary)]"
        }`}
      >
        {value}
        {unit && (
          <span className="text-[var(--text-muted)] font-normal ml-0.5 text-[10px]">
            {unit}
          </span>
        )}
      </span>
    </div>
  );
}

function fmt(v: number): string {
  if (v >= 1000) return v.toFixed(0);
  if (v >= 100) return v.toFixed(0);
  if (v >= 10) return v.toFixed(1);
  return v.toFixed(1);
}

export default function StatsBar({ baseline, incentivized }: Props) {
  const bm = baseline.metrics;
  const im = incentivized.metrics;

  const bVehicles = Number(bm.vehicles ?? bm.total_trips ?? 0);
  const iVehicles = Number(im.vehicles ?? im.total_trips ?? 0);
  const bPeak = Number(bm.peak_vehicles ?? baseline.corridor_state.peak_volume ?? 0);
  const iPeak = Number(im.peak_vehicles ?? incentivized.corridor_state.peak_volume ?? 0);
  const bAvg = Number(bm.avg_travel_time ?? 0) / 60;
  const iAvg = Number(im.avg_travel_time ?? 0) / 60;
  const bCf = Number(baseline.corridor_state.peak_congestion_factor ?? 1);
  const iCf = Number(incentivized.corridor_state.peak_congestion_factor ?? 1);

  const carpoolRate = Number(im.carpool_rate ?? 0);
  const iSpend = Number(im.total_incentive_cost ?? 0);
  const passengersRemoved = Number(im.passengers_removed ?? 0);

  const incKeys = Object.keys(incentivized.incentive_summary);
  const totalOffers = incKeys.reduce(
    (s, k) => s + incentivized.incentive_summary[k].offers,
    0
  );
  const totalAccepted = incKeys.reduce(
    (s, k) => s + incentivized.incentive_summary[k].accepted,
    0
  );
  const acceptRate =
    totalOffers > 0 ? ((totalAccepted / totalOffers) * 100).toFixed(0) : "—";

  const dsShifted = incentivized.incentive_summary.departure_shift?.accepted ?? 0;

  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg-panel)] px-6 py-3 flex items-center justify-between gap-4 overflow-x-auto animate-slide-in">
      <Stat
        label="Vehicles"
        baseVal={bVehicles}
        incVal={iVehicles}
        lowerBetter
      />
      <Stat
        label="Peak simul."
        baseVal={bPeak}
        incVal={iPeak}
        lowerBetter
      />
      <Stat
        label="Peak congest."
        baseVal={bCf}
        incVal={iCf}
        unit="x"
        lowerBetter
      />
      <Stat
        label="Avg time"
        baseVal={bAvg}
        incVal={iAvg}
        unit="min"
        lowerBetter
      />

      <div className="h-6 w-px bg-[var(--border)]" />

      {passengersRemoved > 0 && (
        <Solo
          label="Cars removed"
          value={passengersRemoved}
          color="text-[var(--accent-green)]"
        />
      )}
      {carpoolRate > 0 && (
        <Solo
          label="Carpool %"
          value={`${carpoolRate}%`}
          color="text-[var(--accent-blue)]"
        />
      )}
      {dsShifted > 0 && (
        <Solo
          label="Shifted"
          value={dsShifted}
          color="text-[var(--accent-green)]"
        />
      )}
      <Solo
        label="Incentive $"
        value={`$${iSpend.toFixed(0)}`}
        color="text-[var(--accent-amber)]"
      />
      <Solo label="Accept" value={`${acceptRate}%`} />
      <Solo
        label="Wall"
        value={`${(baseline.wall_time_seconds + incentivized.wall_time_seconds).toFixed(1)}s`}
        color="text-[var(--text-muted)]"
      />
    </div>
  );
}
