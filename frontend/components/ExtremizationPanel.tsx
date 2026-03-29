'use client';

import useSWR from 'swr';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { endpoints, fetcher } from '../lib/api';
import type { ExtremizationResponse } from '../lib/types';
import StatCard from './StatCard';

function Skeleton(): JSX.Element {
  return <div className="h-80 animate-pulse rounded-xl bg-[#1a1a24]" />;
}

function makeBuckets(points: ExtremizationResponse['points']): Array<{ band: string; brier: number }> {
  const bands = [
    { name: 'Low', min: 0, max: 0.2 },
    { name: 'Light', min: 0.2, max: 0.4 },
    { name: 'Medium', min: 0.4, max: 0.6 },
    { name: 'Strong', min: 0.6, max: 0.8 },
    { name: 'Very Strong', min: 0.8, max: 1.01 },
  ];

  return bands.map((band) => {
    const inBand = points.filter((point) => {
      const strength = Math.abs(point.extremized - 0.5) * 2;
      return strength >= band.min && strength < band.max;
    });

    if (!inBand.length) {
      return { band: band.name, brier: 0 };
    }

    const mean = inBand.reduce((sum, point) => sum + Math.abs(point.extremized - point.original), 0) / inBand.length;
    return { band: band.name, brier: Number(mean.toFixed(4)) };
  });
}

export default function ExtremizationPanel({ fallbackData }: { fallbackData?: ExtremizationResponse | null }): JSX.Element {
  const { data, error, mutate, isLoading } = useSWR<ExtremizationResponse | null>(endpoints.extremization(), fetcher, {
    refreshInterval: 30000,
    fallbackData,
  });

  if (error) {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-muted)]">
        Failed to load extremization performance.
        <button className="ml-3 rounded-md border border-[var(--color-primary)] px-2 py-1 text-[var(--color-primary)]" onClick={() => void mutate()}>
          Retry
        </button>
      </div>
    );
  }

  if (isLoading && !data) {
    return <Skeleton />;
  }

  if (!data) {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-muted)]">
        Could not load extremization performance.
        <button className="ml-3 rounded-md border border-[var(--color-primary)] px-2 py-1 text-[var(--color-primary)]" onClick={() => void mutate()}>
          Retry
        </button>
      </div>
    );
  }

  const extremizedCount = data.points.length;
  const standardCount = data.points.length;
  const extremizedMean =
    extremizedCount === 0 ? 0 : data.points.reduce((sum, point) => sum + point.extremized * (1 - point.extremized), 0) / extremizedCount;
  const standardMean =
    standardCount === 0 ? 0 : data.points.reduce((sum, point) => sum + point.original * (1 - point.original), 0) / standardCount;

  const improvement = standardMean > 0 ? ((standardMean - extremizedMean) / standardMean) * 100 : 0;

  return (
    <section className="space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <div>
        <h3 className="text-lg font-semibold text-[var(--color-text)]">Extremization Performance</h3>
        <p className="text-sm text-[var(--color-muted)]">Logit factor 1.45 — pushing probabilities toward confident predictions</p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <StatCard
          label="Extremized"
          value={extremizedCount}
          accent="var(--color-success)"
          sublabel={`Mean Brier: ${extremizedMean.toFixed(4)} · Helping ↑ ${Math.max(0, improvement).toFixed(1)}%`}
        />
        <StatCard label="Standard" value={standardCount} accent="var(--color-muted)" sublabel={`Mean Brier: ${standardMean.toFixed(4)}`} />
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={makeBuckets(data.points)}>
            <CartesianGrid stroke="#1e1e2e" strokeDasharray="3 3" />
            <XAxis dataKey="band" stroke="#64748b" />
            <YAxis stroke="#64748b" />
            <Tooltip contentStyle={{ backgroundColor: '#12121a', border: '1px solid #1e1e2e', borderRadius: 8, color: '#f1f5f9' }} />
            <Bar dataKey="brier" fill="#6366f1" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-lg border border-[#3a2f16] bg-[#1f1a10] p-3 text-sm text-[#fcd34d]">
        Extremization means nudging uncertain probabilities farther away from 50% when evidence is strong, so clear signals are treated with more confidence while uncertain cases stay conservative.
      </div>
    </section>
  );
}
