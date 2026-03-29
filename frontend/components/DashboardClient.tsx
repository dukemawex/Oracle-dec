'use client';

import useSWR from 'swr';
import { endpoints, fetcher } from '../lib/api';
import type { BrierResponse, Forecast, ForecastResponse } from '../lib/types';
import BotRunTimeline from './BotRunTimeline';
import CalibrationChart from './CalibrationChart';
import ExtremizationPanel from './ExtremizationPanel';
import ProbabilityPill from './ProbabilityPill';
import StatCard from './StatCard';
import StatusDot from './StatusDot';
import TournamentBadge from './TournamentBadge';
import type { CalibrationResponse, ExtremizationResponse } from '../lib/types';

interface DashboardClientProps {
  fallbackForecasts: ForecastResponse | null;
  fallbackBrier: BrierResponse | null;
  fallbackCalibration: CalibrationResponse | null;
  fallbackExtremization: ExtremizationResponse | null;
}

function minutesAgo(timestamp: string): number {
  const diffMs = Date.now() - new Date(timestamp).getTime();
  return Math.max(0, Math.round(diffMs / 60000));
}

function truncate(text: string, max = 60): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function getAccuracyRate(forecasts: Forecast[]): number {
  const resolved = forecasts.filter((forecast) => forecast.resolved && forecast.outcome !== null);
  if (!resolved.length) {
    return 0;
  }

  const hits = resolved.filter((forecast) => (forecast.finalProbability >= 0.5) === Boolean(forecast.outcome)).length;
  return (hits / resolved.length) * 100;
}

function getMetricColor(value: number, thresholds: [number, number], invert = false): string {
  if (invert) {
    if (value >= thresholds[1]) return 'var(--color-success)';
    if (value >= thresholds[0]) return 'var(--color-warning)';
    return 'var(--color-danger)';
  }

  if (value < thresholds[0]) return 'var(--color-success)';
  if (value < thresholds[1]) return 'var(--color-warning)';
  return 'var(--color-danger)';
}

function SkeletonBlock({ className }: { className: string }): JSX.Element {
  return <div className={`animate-pulse rounded-xl bg-[#1a1a24] ${className}`} />;
}

export default function DashboardClient({
  fallbackForecasts,
  fallbackBrier,
  fallbackCalibration,
  fallbackExtremization,
}: DashboardClientProps): JSX.Element {
  const forecastsSwr = useSWR<ForecastResponse | null>(endpoints.forecasts(), fetcher, {
    refreshInterval: 30000,
    fallbackData: fallbackForecasts,
  });
  const brierSwr = useSWR<BrierResponse | null>(endpoints.brier(), fetcher, {
    refreshInterval: 30000,
    fallbackData: fallbackBrier,
  });

  const isLoading = (forecastsSwr.isLoading && !forecastsSwr.data) || (brierSwr.isLoading && !brierSwr.data);
  const hasFetchFailure = forecastsSwr.data === null || brierSwr.data === null;

  if (isLoading) {
    return (
      <section className="space-y-4">
        <SkeletonBlock className="h-24" />
        <div className="grid gap-3 md:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <SkeletonBlock key={index} className="h-28" />
          ))}
        </div>
        <SkeletonBlock className="h-72" />
      </section>
    );
  }

  if (hasFetchFailure) {
    return (
      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-sm text-[var(--color-muted)]">
        Unable to reach backend data endpoints.
        <button
          className="ml-3 rounded-md border border-[var(--color-primary)] px-3 py-1 text-[var(--color-primary)]"
          onClick={() => {
            void forecastsSwr.mutate();
            void brierSwr.mutate();
          }}
        >
          Retry
        </button>
      </section>
    );
  }

  const forecasts = forecastsSwr.data?.forecasts ?? [];
  const brier = brierSwr.data?.brier ?? null;
  const total = forecasts.length;
  const resolved = forecasts.filter((forecast) => forecast.resolved).length;
  const accuracy = getAccuracyRate(forecasts);
  const brierColor = brier === null ? 'var(--color-muted)' : getMetricColor(brier, [0.15, 0.25]);
  const accuracyColor = getMetricColor(accuracy, [60, 75], true);

  const sortedForecasts = [...forecasts].sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt));
  const lastRun = sortedForecasts[0]?.createdAt;
  const staleMins = lastRun ? minutesAgo(lastRun) : null;
  const active = staleMins !== null && staleMins < 35;

  const tournaments = ['Spring AIB 2026', 'MiniBench', 'Market Pulse Q1'].map((name) => {
    const matches = forecasts.filter((forecast) => forecast.tournament === name);
    const latest = matches.sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))[0];

    return {
      name,
      count: matches.length,
      lastActive: latest ? `${minutesAgo(latest.createdAt)}m ago` : '—',
      active: Boolean(latest) && minutesAgo(latest.createdAt) < 45,
    };
  });

  return (
    <section className="space-y-6">
      <header className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 glow-indigo">
        <h1 className="text-4xl font-bold tracking-tight text-white">OracleDeck</h1>
        <p className="mt-2 text-sm text-[var(--color-muted)]">
          Autonomous Superforecaster — Spring AIB 2026 · MiniBench · Market Pulse
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <StatusDot active={active} label={active ? 'Bot Active' : 'Bot Idle'} />
          <span className="text-sm text-[var(--color-muted)]">
            Last forecast run: {staleMins === null ? 'No runs yet' : `${staleMins} minutes ago`}
          </span>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-4">
        <StatCard label="Total Forecasts" value={total} accent="var(--color-primary)" />
        <StatCard label="Resolved" value={resolved} accent="var(--color-success)" />
        <StatCard
          label="Mean Brier Score"
          value={brier === null ? 'n/a' : brier.toFixed(4)}
          accent={brierColor}
        />
        <StatCard label="Accuracy Rate" value={`${accuracy.toFixed(1)}%`} accent={accuracyColor} />
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Bot Activity Panel</h2>
        <BotRunTimeline fallbackData={fallbackForecasts} />
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Tournament Status</h2>
        <div className="grid gap-3 md:grid-cols-3">
          {tournaments.map((tournament) => (
            <article key={tournament.name} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
              <TournamentBadge tournament={tournament.name} active={tournament.active} />
              <p className="mt-3 text-sm text-[var(--color-muted)]">Questions: {tournament.count}</p>
              <p className="text-sm text-[var(--color-muted)]">Last active: {tournament.lastActive}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Calibration Curve</h2>
        <p className="text-sm text-[var(--color-muted)]">How well-calibrated are the probability estimates?</p>
        <CalibrationChart fallbackData={fallbackCalibration} />
      </section>

      <ExtremizationPanel fallbackData={fallbackExtremization} />

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Recent Forecasts</h2>
        <div className="overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
              <tr>
                <th className="px-3 py-2">Question</th>
                <th className="px-3 py-2">Tournament</th>
                <th className="px-3 py-2">Probability</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Extremized</th>
                <th className="px-3 py-2">Time</th>
              </tr>
            </thead>
            <tbody>
              {sortedForecasts.slice(0, 10).map((forecast) => {
                const extremized =
                  forecast.tinyfishProbability !== null && Math.abs(forecast.finalProbability - forecast.tinyfishProbability) > 0.001;

                return (
                  <tr key={forecast.id} className="border-b border-[var(--color-border)] hover:bg-[#171722]">
                    <td className="px-3 py-2">
                      <a
                        href={`https://www.metaculus.com/questions/${forecast.questionId}`}
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-[var(--color-primary)]"
                      >
                        {truncate(forecast.questionTitle, 60)}
                      </a>
                    </td>
                    <td className="px-3 py-2">
                      <TournamentBadge tournament={forecast.tournament} />
                    </td>
                    <td className="px-3 py-2">
                      <ProbabilityPill probability={forecast.finalProbability} extremized={extremized} />
                    </td>
                    <td className="px-3 py-2 text-[var(--color-muted)]">Binary</td>
                    <td className="px-3 py-2">{extremized ? '⚡' : '—'}</td>
                    <td className="px-3 py-2 text-[var(--color-muted)]">{new Date(forecast.createdAt).toLocaleString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)] pt-4 text-xs text-[var(--color-muted)]">
        <span>Powered by Claude Sonnet 4.6 · GPT-4.5 · Exa · Tinyfish</span>
        <a href="https://github.com/dukemawex/Oracle-dec" target="_blank" rel="noreferrer" className="hover:text-[var(--color-primary)]">
          GitHub
        </a>
        <span>Updates every 30s via SWR polling</span>
      </footer>
    </section>
  );
}
