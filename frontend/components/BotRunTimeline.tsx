'use client';

import useSWR from 'swr';
import { endpoints, fetcher } from '../lib/api';
import type { ForecastResponse } from '../lib/types';

interface BotRun {
  timestamp: string;
  tournaments: string[];
  questions: number;
  duration: string;
  success: boolean;
}

function buildRuns(forecasts: ForecastResponse['forecasts']): BotRun[] {
  const groups = new Map<string, ForecastResponse['forecasts']>();

  for (const forecast of forecasts) {
    const key = new Date(forecast.createdAt).toISOString().slice(0, 16);
    const existing = groups.get(key) ?? [];
    existing.push(forecast);
    groups.set(key, existing);
  }

  return Array.from(groups.entries())
    .sort(([a], [b]) => b.localeCompare(a))
    .slice(0, 5)
    .map(([key, items]) => ({
      timestamp: key,
      tournaments: Array.from(new Set(items.map((item) => item.tournament))).slice(0, 3),
      questions: items.length,
      duration: `${Math.max(1, Math.round(items.length / 2))}m`,
      success: true,
    }));
}

function SkeletonRow(): JSX.Element {
  return <div className="h-10 animate-pulse rounded-lg bg-[#1a1a24]" />;
}

export default function BotRunTimeline({ fallbackData }: { fallbackData?: ForecastResponse | null }): JSX.Element {
  const { data, error, mutate, isLoading } = useSWR<ForecastResponse | null>(endpoints.forecasts(), fetcher, {
    refreshInterval: 30000,
    fallbackData,
  });

  if (error) {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-muted)]">
        Could not load bot activity.
        <button className="ml-3 rounded-md border border-[var(--color-primary)] px-2 py-1 text-[var(--color-primary)]" onClick={() => void mutate()}>
          Retry
        </button>
      </div>
    );
  }

  if (isLoading && !data) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }, (_, index) => (
          <SkeletonRow key={index} />
        ))}
      </div>
    );
  }

  if (!data || !data.forecasts.length) {
    return <p className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-muted)]">No runs yet</p>;
  }

  const runs = buildRuns(data.forecasts);

  return (
    <div className="space-y-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      {runs.map((run) => (
        <div key={run.timestamp} className="grid grid-cols-12 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[#161620] px-3 py-2 text-xs text-[var(--color-text)]">
          <span className="col-span-3">{new Date(run.timestamp).toLocaleString()}</span>
          <span className="col-span-3 text-[var(--color-muted)]">{run.tournaments.join(', ')}</span>
          <span className="col-span-2">{run.questions} questions</span>
          <span className="col-span-2 text-[var(--color-muted)]">{run.duration}</span>
          <span className={`col-span-2 text-right ${run.success ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}`}>
            {run.success ? '✓ Success' : '✗ Failed'}
          </span>
        </div>
      ))}
    </div>
  );
}
