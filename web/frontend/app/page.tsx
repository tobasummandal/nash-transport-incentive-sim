"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import Controls from "@/components/Controls";
import CorridorViz from "@/components/CorridorViz";
import StatsBar from "@/components/StatsBar";

export interface SimParams {
  n_agents: number;
  duration_hours: number;
  seed: number;
  carpool_enabled: boolean;
  carpool_budget: number;
  carpool_reward_per_passenger: number;
  pacer_enabled: boolean;
  pacer_budget: number;
  pacer_reward_per_mile: number;
  departure_shift_enabled: boolean;
  departure_shift_budget: number;
  allocator: string;
}

export interface TrajectoryFrame {
  t: number;
  n: number;
  agents: Array<{ p: number; m: string; inc: boolean }>;
}

export interface RunResult {
  label: string;
  metrics: Record<string, number | Record<string, number>>;
  time_series: Array<Record<string, number>>;
  incentive_summary: Record<
    string,
    {
      offers: number;
      accepted: number;
      completed: number;
      total_spent: number;
      budget: number;
    }
  >;
  corridor_state: {
    peak_volume: number;
    instantaneous_capacity?: number;
    peak_vc_ratio?: number;
    peak_congestion_factor?: number;
    active_pacers_now?: number;
    [key: string]: number | undefined;
  };
  trajectories: TrajectoryFrame[];
  wall_time_seconds: number;
}

export interface CompareResult {
  baseline: RunResult;
  incentivized: RunResult;
}

const DEFAULT_PARAMS: SimParams = {
  n_agents: 200,
  duration_hours: 3,
  seed: 42,
  carpool_enabled: true,
  carpool_budget: 5000,
  carpool_reward_per_passenger: 2.5,
  pacer_enabled: true,
  pacer_budget: 3000,
  pacer_reward_per_mile: 0.15,
  departure_shift_enabled: false,
  departure_shift_budget: 2000,
  allocator: "always",
};

function formatTime(seconds: number): string {
  const totalSec = 6 * 3600 + seconds;
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h > 12 ? h - 12 : h === 0 ? 12 : h;
  return `${h12}:${m.toString().padStart(2, "0")} ${period}`;
}

export default function Home() {
  const [params, setParams] = useState<SimParams>(DEFAULT_PARAMS);
  const [data, setData] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Shared playback state
  const [frameIdx, setFrameIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const frameAccum = useRef(0);
  const animRef = useRef(0);

  const maxFrames = data
    ? Math.max(
        data.baseline.trajectories.length,
        data.incentivized.trajectories.length
      )
    : 0;

  // Reset playback when new data arrives
  useEffect(() => {
    setFrameIdx(0);
    setPlaying(false);
    frameAccum.current = 0;
  }, [data]);

  // Animation loop (shared)
  useEffect(() => {
    if (!playing || maxFrames === 0) return;

    let last = performance.now();
    const tick = (now: number) => {
      const dt = now - last;
      last = now;
      frameAccum.current += dt;

      const msPerFrame = 50 / speed;
      while (frameAccum.current >= msPerFrame) {
        frameAccum.current -= msPerFrame;
        setFrameIdx((prev) => {
          if (prev >= maxFrames - 1) {
            setPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }
      animRef.current = requestAnimationFrame(tick);
    };

    animRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animRef.current);
  }, [playing, speed, maxFrames]);

  const runCompare = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${api}/api/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
      const d: CompareResult = await res.json();
      setData(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [params]);

  const togglePlay = () => {
    if (frameIdx >= maxFrames - 1) setFrameIdx(0);
    setPlaying((p) => !p);
  };

  const currentTime = data
    ? (data.baseline.trajectories[frameIdx] || data.baseline.trajectories[0])?.t ?? 0
    : 0;

  return (
    <main className="flex-1 flex flex-col">
      {/* Header */}
      <header className="border-b border-[var(--border)] px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-[var(--accent-green)] animate-pulse" />
          <span className="text-xs font-mono font-medium tracking-widest uppercase text-[var(--text-secondary)]">
            Nashville I-24 Corridor
          </span>
        </div>
        <span className="text-[10px] font-mono text-[var(--text-muted)]">
          agent-based incentive simulation
        </span>
      </header>

      <div className="flex-1 flex">
        {/* Sidebar controls */}
        <aside className="w-72 border-r border-[var(--border)] overflow-y-auto">
          <Controls
            params={params}
            onChange={setParams}
            onRun={runCompare}
            loading={loading}
          />
        </aside>

        {/* Main area */}
        <section className="flex-1 flex flex-col overflow-hidden">
          {error && (
            <div className="mx-6 mt-4 rounded border border-red-900/50 bg-red-950/30 px-4 py-2 text-xs text-red-400 font-mono">
              {error}
            </div>
          )}

          {!data && !loading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center space-y-2">
                <p className="text-sm text-[var(--text-muted)]">
                  Configure parameters, then run to compare
                </p>
                <p className="text-xs text-[var(--text-muted)] opacity-50">
                  baseline (no incentives) vs your configuration
                </p>
              </div>
            </div>
          )}

          {loading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex flex-col items-center gap-4">
                <div className="relative">
                  <div className="h-10 w-10 border-2 border-[var(--accent-blue)] border-t-transparent rounded-full animate-spin" />
                  <div className="absolute inset-0 h-10 w-10 border-2 border-[var(--accent-blue)]/20 rounded-full" />
                </div>
                <div className="text-center">
                  <p className="text-sm text-[var(--text-secondary)] font-mono">
                    Simulating {params.n_agents} agents
                  </p>
                  <p className="text-xs text-[var(--text-muted)] mt-1">
                    two runs: baseline + incentivized
                  </p>
                </div>
              </div>
            </div>
          )}

          {data && !loading && (
            <div className="flex-1 flex flex-col animate-slide-in">
              {/* Stats comparison bar */}
              <StatsBar baseline={data.baseline} incentivized={data.incentivized} />

              {/* Dual corridor visualization */}
              <div className="flex-1 grid grid-cols-2 divide-x divide-[var(--border)]">
                <CorridorViz
                  result={data.baseline}
                  side="left"
                  frameIdx={frameIdx}
                />
                <CorridorViz
                  result={data.incentivized}
                  side="right"
                  frameIdx={frameIdx}
                />
              </div>

              {/* Unified playback controls */}
              <div className="border-t border-[var(--border)] bg-[var(--bg-panel)] px-6 py-3 flex items-center gap-4">
                <button
                  onClick={togglePlay}
                  className="flex items-center justify-center w-8 h-8 rounded-md border border-[var(--border)] bg-[var(--bg-deep)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent-blue)] transition-colors"
                  title={playing ? "Pause" : "Play"}
                >
                  {playing ? "⏸" : "▶"}
                </button>

                <div className="flex-1 flex flex-col gap-1">
                  <input
                    type="range"
                    min={0}
                    max={maxFrames - 1}
                    value={frameIdx}
                    onChange={(e) => {
                      setFrameIdx(Number(e.target.value));
                      setPlaying(false);
                    }}
                    className="w-full h-1.5 accent-[var(--accent-blue)] cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] font-mono text-[var(--text-muted)] tabular-nums">
                    <span>{formatTime(currentTime)}</span>
                    <span>
                      frame {frameIdx + 1} / {maxFrames}
                    </span>
                    <span>
                      {formatTime(
                        data.baseline.trajectories[maxFrames - 1]?.t ?? 0
                      )}
                    </span>
                  </div>
                </div>

                <select
                  value={speed}
                  onChange={(e) => setSpeed(Number(e.target.value))}
                  className="text-xs font-mono bg-[var(--bg-deep)] text-[var(--text-secondary)] border border-[var(--border)] rounded px-2 py-1 focus:outline-none focus:border-[var(--accent-blue)] cursor-pointer"
                >
                  <option value={0.5}>0.5x</option>
                  <option value={1}>1x</option>
                  <option value={2}>2x</option>
                  <option value={4}>4x</option>
                  <option value={8}>8x</option>
                </select>

                <div className="flex gap-4 text-[10px] font-mono text-[var(--text-muted)] tabular-nums min-w-[160px] justify-end">
                  <span>
                    base: {data.baseline.trajectories[frameIdx]?.n ?? 0} veh
                  </span>
                  <span className="text-[var(--accent-blue)]">
                    inc: {data.incentivized.trajectories[frameIdx]?.n ?? 0} veh
                  </span>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
