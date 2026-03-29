'use client';

import { useMemo, useState } from 'react';
import useSWR from 'swr';
import { endpoints, fetcher } from '../lib/api';
import type { ForecastResponse } from '../lib/types';
import ProbabilityPill from './ProbabilityPill';
import TournamentBadge from './TournamentBadge';

const types = ['All', 'Binary', 'Numeric', 'Multiple Choice'] as const;
const tournaments = ['All', 'Spring AIB 2026', 'MiniBench', 'Market Pulse Q1'] as const;
const PAGE_SIZE = 20;
type ForecastType = (typeof types)[number];

function Button({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs ${active ? 'border-[var(--color-primary)] text-[var(--color-primary)]' : 'border-[var(--color-border)] text-[var(--color-muted)]'}`}
    >
      {children}
    </button>
  );
}

export default function ForecastsClient({ fallbackData }: { fallbackData: ForecastResponse | null }): JSX.Element {
  const [typeFilter, setTypeFilter] = useState<(typeof types)[number]>('All');
  const [tournamentFilter, setTournamentFilter] = useState<(typeof tournaments)[number]>('All');
  const [page, setPage] = useState(1);

  const { data, error, mutate, isLoading } = useSWR<ForecastResponse | null>(endpoints.forecasts(), fetcher, {
    refreshInterval: 30000,
    fallbackData,
  });

  const filtered = useMemo(() => {
    const source = data?.forecasts ?? [];

    const getForecastType = (_item: ForecastResponse['forecasts'][number]): Exclude<ForecastType, 'All'> => 'Binary';

    return source
      .filter((item) => (tournamentFilter === 'All' ? true : item.tournament === tournamentFilter))
      .filter((item) => {
        if (typeFilter === 'All') {
          return true;
        }
        return getForecastType(item) === typeFilter;
      });
  }, [data, tournamentFilter, typeFilter]);

  if (error || data === null) {
    return (
      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 text-sm text-[var(--color-muted)]">
        Failed to load forecasts.
        <button className="ml-3 rounded-md border border-[var(--color-primary)] px-2 py-1 text-[var(--color-primary)]" onClick={() => void mutate()}>
          Retry
        </button>
      </section>
    );
  }

  if (isLoading && !data) {
    return <div className="h-48 animate-pulse rounded-xl bg-[#1a1a24]" />;
  }

  if (!filtered.length) {
    return (
      <section className="space-y-4">
        <h1 className="text-3xl font-bold">All Forecasts</h1>
        <p className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-sm text-[var(--color-muted)]">
          No forecasts yet — bot will run every 30 minutes
        </p>
      </section>
    );
  }

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const clampedPage = Math.min(page, totalPages);
  const rows = filtered.slice((clampedPage - 1) * PAGE_SIZE, clampedPage * PAGE_SIZE);

  return (
    <section className="space-y-4">
      <h1 className="text-3xl font-bold">All Forecasts</h1>

      <div className="space-y-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <div className="flex flex-wrap gap-2">
          {types.map((type) => (
            <Button
              key={type}
              active={typeFilter === type}
              onClick={() => {
                setTypeFilter(type);
                setPage(1);
              }}
            >
              {type}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {tournaments.map((tournament) => (
            <Button
              key={tournament}
              active={tournamentFilter === tournament}
              onClick={() => {
                setTournamentFilter(tournament);
                setPage(1);
              }}
            >
              {tournament === 'Market Pulse Q1' ? 'Market Pulse' : tournament}
            </Button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
            <tr>
              <th className="px-3 py-2">Question</th>
              <th className="px-3 py-2">Tournament</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Probability</th>
              <th className="px-3 py-2">Extremized</th>
              <th className="px-3 py-2">Models Used</th>
              <th className="px-3 py-2">Time</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((forecast) => {
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
                      {forecast.questionTitle}
                    </a>
                  </td>
                  <td className="px-3 py-2">
                    <TournamentBadge tournament={forecast.tournament} />
                  </td>
                  <td className="px-3 py-2 text-[var(--color-muted)]">Binary</td>
                  <td className="px-3 py-2">
                    <ProbabilityPill probability={forecast.finalProbability} extremized={extremized} />
                  </td>
                  <td className="px-3 py-2">{extremized ? '⚡' : '—'}</td>
                  <td className="px-3 py-2 text-[var(--color-muted)]">{forecast.model}</td>
                  <td className="px-3 py-2 text-[var(--color-muted)]">{new Date(forecast.createdAt).toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm text-[var(--color-muted)]">
        <span>
          Page {clampedPage} of {totalPages}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-md border border-[var(--color-border)] px-3 py-1 disabled:opacity-50"
            disabled={clampedPage <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            Previous
          </button>
          <button
            type="button"
            className="rounded-md border border-[var(--color-border)] px-3 py-1 disabled:opacity-50"
            disabled={clampedPage >= totalPages}
            onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
