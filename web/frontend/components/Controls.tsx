"use client";

import { useState, useRef } from "react";
import type { SimParams } from "@/app/page";

interface Props {
  params: SimParams;
  onChange: (p: SimParams) => void;
  onRun: () => void;
  loading: boolean;
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function NumInput({
  value,
  onChange,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  const [draft, setDraft] = useState<string>(String(value));
  const prevValue = useRef(value);

  if (value !== prevValue.current) {
    prevValue.current = value;
    setDraft(String(value));
  }

  return (
    <input
      type="number"
      value={draft}
      min={min}
      max={max}
      step={step}
      onChange={(e) => {
        setDraft(e.target.value);
        const n = Number(e.target.value);
        if (e.target.value !== "" && !isNaN(n)) {
          onChange(n);
        }
      }}
      onBlur={() => {
        if (draft === "" || isNaN(Number(draft))) {
          setDraft(String(value));
        }
      }}
      className="w-full rounded border border-[var(--border)] bg-[var(--bg-deep)] px-2.5 py-1.5 text-sm font-mono text-[var(--text-primary)] focus:border-[var(--accent-blue)] focus:outline-none transition-colors"
    />
  );
}

function Toggle({
  label,
  checked,
  onChange,
  color = "bg-[var(--accent-blue)]",
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  color?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2 w-full text-left group"
    >
      <div
        className={`relative w-8 h-4 rounded-full transition-colors ${
          checked ? color : "bg-[var(--bg-deep)]"
        } border border-[var(--border)]`}
      >
        <div
          className={`absolute top-0.5 w-2.5 h-2.5 rounded-full bg-white transition-all ${
            checked ? "left-[14px]" : "left-0.5"
          }`}
        />
      </div>
      <span className="text-xs text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">
        {label}
      </span>
    </button>
  );
}

export default function Controls({ params, onChange, onRun, loading }: Props) {
  const set = (patch: Partial<SimParams>) => onChange({ ...params, ...patch });

  return (
    <div className="p-4 space-y-5 text-sm" suppressHydrationWarning>
      {/* Core params */}
      <div className="space-y-3">
        <h3 className="text-[10px] font-mono font-bold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)] pb-1.5">
          Simulation
        </h3>
        <Field label="Agents">
          <NumInput
            value={params.n_agents}
            onChange={(v) => set({ n_agents: v })}
            min={10}
            max={5000}
            step={10}
          />
        </Field>
        <Field label="Duration (hrs)">
          <NumInput
            value={params.duration_hours}
            onChange={(v) => set({ duration_hours: v })}
            min={0.5}
            max={8}
            step={0.5}
          />
        </Field>
        <Field label="Seed">
          <NumInput
            value={params.seed}
            onChange={(v) => set({ seed: v })}
            min={0}
          />
        </Field>
        <Field label="Allocator">
          <select
            value={params.allocator}
            onChange={(e) => set({ allocator: e.target.value })}
            className="w-full rounded border border-[var(--border)] bg-[var(--bg-deep)] px-2.5 py-1.5 text-sm font-mono text-[var(--text-primary)] focus:border-[var(--accent-blue)] focus:outline-none"
          >
            <option value="always">Always accept</option>
            <option value="greedy">Greedy</option>
            <option value="secretary">Secretary</option>
          </select>
        </Field>
      </div>

      {/* Incentives */}
      <div className="space-y-3">
        <h3 className="text-[10px] font-mono font-bold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)] pb-1.5">
          Incentives
        </h3>

        <div className="space-y-2">
          <Toggle
            label="Carpool"
            checked={params.carpool_enabled}
            onChange={(v) => set({ carpool_enabled: v })}
            color="bg-[var(--accent-blue)]"
          />
          {params.carpool_enabled && (
            <div className="pl-10 space-y-2 border-l border-[var(--border)] ml-1">
              <Field label="Budget">
                <NumInput
                  value={params.carpool_budget}
                  onChange={(v) => set({ carpool_budget: v })}
                  min={0}
                  step={500}
                />
              </Field>
              <Field label="$/passenger">
                <NumInput
                  value={params.carpool_reward_per_passenger}
                  onChange={(v) => set({ carpool_reward_per_passenger: v })}
                  min={0}
                  step={0.5}
                />
              </Field>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <Toggle
            label="Pacer"
            checked={params.pacer_enabled}
            onChange={(v) => set({ pacer_enabled: v })}
            color="bg-[var(--accent-green)]"
          />
          {params.pacer_enabled && (
            <div className="pl-10 space-y-2 border-l border-[var(--border)] ml-1">
              <Field label="Budget">
                <NumInput
                  value={params.pacer_budget}
                  onChange={(v) => set({ pacer_budget: v })}
                  min={0}
                  step={500}
                />
              </Field>
              <Field label="$/mile">
                <NumInput
                  value={params.pacer_reward_per_mile}
                  onChange={(v) => set({ pacer_reward_per_mile: v })}
                  min={0}
                  step={0.05}
                />
              </Field>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <Toggle
            label="Departure shift"
            checked={params.departure_shift_enabled}
            onChange={(v) => set({ departure_shift_enabled: v })}
            color="bg-[var(--accent-amber)]"
          />
          {params.departure_shift_enabled && (
            <div className="pl-10 space-y-2 border-l border-[var(--border)] ml-1">
              <Field label="Budget">
                <NumInput
                  value={params.departure_shift_budget}
                  onChange={(v) => set({ departure_shift_budget: v })}
                  min={0}
                  step={500}
                />
              </Field>
            </div>
          )}
        </div>
      </div>

      <button
        onClick={onRun}
        disabled={loading}
        className="w-full rounded bg-[var(--accent-blue)] px-4 py-2 text-xs font-mono font-bold uppercase tracking-wider text-white hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
      >
        {loading ? "Running…" : "Run comparison"}
      </button>
    </div>
  );
}
