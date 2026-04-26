"use client";

import { useRef, useEffect, useCallback } from "react";
import type { RunResult, TrajectoryFrame } from "@/app/page";

interface Props {
  result: RunResult;
  side: "left" | "right";
  frameIdx: number;
}

const LANE_COUNT = 3;
const AGENT_RADIUS = 3;
const ROAD_PAD_Y = 60;

function formatTime(seconds: number): string {
  const totalSec = 6 * 3600 + seconds;
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h > 12 ? h - 12 : h === 0 ? 12 : h;
  return `${h12}:${m.toString().padStart(2, "0")} ${period}`;
}

export default function CorridorViz({ result, side, frameIdx }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const frames = result.trajectories;
  const currentFrame = frames[frameIdx] || frames[0];

  const draw = useCallback(
    (canvas: HTMLCanvasElement, frame: TrajectoryFrame) => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const W = canvas.width;
      const H = canvas.height;
      const dpr = window.devicePixelRatio || 1;

      ctx.clearRect(0, 0, W, H);

      const roadTop = ROAD_PAD_Y * dpr;
      const roadBottom = H - ROAD_PAD_Y * dpr;
      const roadHeight = roadBottom - roadTop;
      const laneHeight = roadHeight / LANE_COUNT;
      const roadLeft = 40 * dpr;
      const roadRight = W - 20 * dpr;
      const roadWidth = roadRight - roadLeft;

      ctx.fillStyle = "#0f1218";
      ctx.fillRect(roadLeft, roadTop, roadWidth, roadHeight);

      ctx.setLineDash([8 * dpr, 12 * dpr]);
      ctx.strokeStyle = "#1e2430";
      ctx.lineWidth = 1 * dpr;
      for (let i = 1; i < LANE_COUNT; i++) {
        const y = roadTop + i * laneHeight;
        ctx.beginPath();
        ctx.moveTo(roadLeft, y);
        ctx.lineTo(roadRight, y);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      ctx.strokeStyle = "#2a3348";
      ctx.lineWidth = 1.5 * dpr;
      ctx.beginPath();
      ctx.moveTo(roadLeft, roadTop);
      ctx.lineTo(roadRight, roadTop);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(roadLeft, roadBottom);
      ctx.lineTo(roadRight, roadBottom);
      ctx.stroke();

      ctx.fillStyle = "#2a3040";
      ctx.font = `${9 * dpr}px "JetBrains Mono", monospace`;
      ctx.textAlign = "center";
      for (let mi = 0; mi <= 4; mi++) {
        const x = roadLeft + (mi / 4) * roadWidth;
        ctx.fillText(`${mi} mi`, x, roadTop - 8 * dpr);
      }

      ctx.fillStyle = "#1e2430";
      ctx.font = `${10 * dpr}px "JetBrains Mono", monospace`;
      ctx.textAlign = "right";
      ctx.fillText("→ Downtown", roadRight, roadBottom + 20 * dpr);
      ctx.textAlign = "left";
      ctx.fillText("SE suburbs", roadLeft, roadBottom + 20 * dpr);

      const agents = frame.agents;
      const rng = mulberry32(frameIdx * 1000);

      for (let i = 0; i < agents.length; i++) {
        const a = agents[i];
        const x = roadLeft + a.p * roadWidth;
        const laneIdx = Math.floor(rng() * LANE_COUNT);
        const y =
          roadTop + laneIdx * laneHeight + laneHeight * 0.3 + rng() * laneHeight * 0.4;

        const r = AGENT_RADIUS * dpr;

        if (a.inc) {
          ctx.shadowColor = "#3b82f6";
          ctx.shadowBlur = 6 * dpr;
          ctx.fillStyle = "#60a5fa";
        } else {
          ctx.shadowColor = "transparent";
          ctx.shadowBlur = 0;
          ctx.fillStyle = "#6b7280";
        }

        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      ctx.fillStyle = "#e2e4e9";
      ctx.font = `bold ${13 * dpr}px "JetBrains Mono", monospace`;
      ctx.textAlign = "left";
      ctx.fillText(formatTime(frame.t), roadLeft, 28 * dpr);

      ctx.fillStyle = "#4a5060";
      ctx.font = `${10 * dpr}px "JetBrains Mono", monospace`;
      ctx.textAlign = "right";
      ctx.fillText(`${frame.n} vehicles`, roadRight, 28 * dpr);
    },
    [frameIdx]
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      draw(canvas, frames[frameIdx] || frames[0]);
    };

    resize();
    const obs = new ResizeObserver(resize);
    obs.observe(container);
    return () => obs.disconnect();
  }, [draw, frames, frameIdx]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas && frames.length > 0) {
      draw(canvas, frames[frameIdx] || frames[0]);
    }
  }, [frameIdx, draw, frames]);

  const incCount = currentFrame?.agents.filter((a) => a.inc).length || 0;
  const totalInc = Number(result.metrics.total_incentive_cost ?? 0);
  const peakCf = result.corridor_state.peak_congestion_factor ?? result.corridor_state.congestion_factor ?? 0;

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className={`w-1.5 h-1.5 rounded-full ${
              side === "left" ? "bg-[var(--text-muted)]" : "bg-[var(--accent-blue)]"
            }`}
          />
          <span className="text-xs font-mono font-medium text-[var(--text-secondary)]">
            {result.label}
          </span>
        </div>
        <div className="flex gap-3 text-[10px] font-mono text-[var(--text-muted)]">
          {incCount > 0 && (
            <span className="text-[var(--accent-blue)]">{incCount} inc</span>
          )}
          <span>peak: {result.corridor_state.peak_volume}</span>
          {peakCf > 1 && <span>cf: {peakCf.toFixed(2)}x</span>}
          <span>${totalInc.toFixed(0)}</span>
        </div>
      </div>

      <div ref={containerRef} className="flex-1 relative bg-[var(--bg-deep)]">
        <canvas ref={canvasRef} className="absolute inset-0" />
      </div>
    </div>
  );
}

function mulberry32(seed: number) {
  let t = seed + 0x6d2b79f5;
  return () => {
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
