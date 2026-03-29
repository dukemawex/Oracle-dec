'use client';

import useSWR from 'swr';
import { Line, LineChart, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip, PieChart, Pie, Cell } from 'recharts';
import CalibrationChart from './CalibrationChart';
import ExtremizationPanel from './ExtremizationPanel';
import { endpoints, fetcher } from '../lib/api';
import type { BrierResponse, CalibrationResponse, ExtremizationResponse, ForecastResponse } from '../lib/types';

const pieColors = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444'];

interface PerformanceClientProps {
  fallbackForecasts: ForecastResponse | null;
  fallbackBrier: BrierResponse | null;
  fallbackCalibration: CalibrationResponse | null;
  fallbackExtremization: ExtremizationResponse | null;
}

function Skeleton(): JSX.Element {
  return <div className="h-48 animate-pulse rounded-xl bg-[#1a1a24]" />;
}

export default function PerformanceClient({
  fallbackForecasts,
  fallbackBrier,
  fallbackCalibration,
  fallbackExtremization,
}: PerformanceClientProps): JSX.Element {
  const { data: brier, error: brierError, mutate: mutateBrier, isLoading: brierLoading } = useSWR<BrierResponse | null>(endpoints.brier(), fetcher, {
    refreshInterval: 30000,
    fallbackData: fallbackBrier,
  });
  const {
    data: forecasts,
    error: forecastsError,
    mutate: mutateForecasts,
    isLoading: forecastsLoading,
  } = useSWR<ForecastResponse | null>(endpoints.forecasts(), fetcher, {
    refreshInterval: 30000,
    fallbackData: fallbackForecasts,
  });

  if (brierError || forecastsError || brier === null || forecasts === null) {
    return (
      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 text-sm text-[var(--color-muted)]">
        Failed to load performance analytics.
        <button
          className="ml-3 rounded-md border border-[var(--color-primary)] px-2 py-1 text-[var(--color-primary)]"
          onClick={() => {
            void mutateBrier();
            void mutateForecasts();
          }}
        >
          Retry
        </button>
      </section>
    );
  }

  if ((brierLoading && !brier) || (forecastsLoading && !forecasts)) {
    return <Skeleton />;
  }

  const rows = forecasts?.forecasts ?? [];
  const brierSeries = rows.slice(0, 25).map((row) => ({
    time: new Date(row.createdAt).toLocaleDateString(),
    brier: Number((row.finalProbability * (1 - row.finalProbability)).toFixed(4)),
  }));

  const tournamentData = ['Spring AIB 2026', 'MiniBench', 'Market Pulse Q1'].map((tournament) => {
    const scoped = rows.filter((row) => row.tournament === tournament);
    const mean = scoped.length
      ? scoped.reduce((sum, row) => sum + row.finalProbability * (1 - row.finalProbability), 0) / scoped.length
      : 0;
    return {
      tournament,
      count: scoped.length,
      brier: mean,
    };
  });

  const modelUsageMap = rows.reduce<Record<string, number>>((acc, row) => {
    acc[row.model] = (acc[row.model] ?? 0) + 1;
    return acc;
  }, {});

  const modelUsage = Object.entries(modelUsageMap).map(([name, value]) => ({ name, value }));

  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">Performance Analytics</h1>
      </header>

      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-3 text-lg font-semibold">Brier score over time</h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={brierSeries}>
              <CartesianGrid stroke="#1e1e2e" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip contentStyle={{ backgroundColor: '#12121a', border: '1px solid #1e1e2e', borderRadius: 8, color: '#f1f5f9' }} />
              <Line dataKey="brier" stroke="#6366f1" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-sm text-[var(--color-muted)]">Current mean Brier score: {brier?.brier?.toFixed(4) ?? 'n/a'}</p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Calibration curve</h2>
        <CalibrationChart fallbackData={fallbackCalibration} />
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {tournamentData.map((item) => (
          <article key={item.tournament} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
            <h3 className="font-semibold">{item.tournament}</h3>
            <p className="mt-2 text-sm text-[var(--color-muted)]">Forecasts: {item.count}</p>
            <p className="text-sm text-[var(--color-muted)]">Mean Brier: {item.brier.toFixed(4)}</p>
          </article>
        ))}
      </section>

      <ExtremizationPanel fallbackData={fallbackExtremization} />

      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-3 text-lg font-semibold">Model usage breakdown</h2>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={modelUsage} dataKey="value" nameKey="name" outerRadius={120} label>
                {modelUsage.map((entry, index) => (
                  <Cell key={entry.name} fill={pieColors[index % pieColors.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ backgroundColor: '#12121a', border: '1px solid #1e1e2e', borderRadius: 8, color: '#f1f5f9' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </section>
    </section>
  );
}
