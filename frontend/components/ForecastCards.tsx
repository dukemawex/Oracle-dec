'use client';

import useSWR from 'swr';
import { endpoints, fetcher } from '../lib/api';
import type { ForecastResponse } from '../lib/types';

export default function ForecastCards(): JSX.Element {
  const { data, error, mutate, isLoading } = useSWR<ForecastResponse | null>(endpoints.forecasts(), fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: true,
  });

  if (error || data === null) {
    return (
      <p className="text-red-400">
        Failed to load forecasts
        <button className="ml-2 rounded border border-red-400 px-2 py-0.5 text-xs" onClick={() => void mutate()}>
          Retry
        </button>
      </p>
    );
  }

  if (isLoading && !data) {
    return <div className="h-20 animate-pulse rounded-lg bg-[#1a1a24]" />;
  }

  return (
    <div className="grid gap-3">
      {data?.forecasts.map((forecast) => (
        <article key={forecast.id} className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h3 className="font-semibold">{forecast.questionTitle}</h3>
          <p className="text-sm text-slate-300">Tournament: {forecast.tournament}</p>
          <p className="text-sm text-slate-300">Final: {(forecast.finalProbability * 100).toFixed(1)}%</p>
          <p className="text-sm text-slate-300">tinyfish: {forecast.tinyfishProbability === null ? 'n/a' : `${(forecast.tinyfishProbability * 100).toFixed(1)}%`}</p>
          <p className="text-xs text-slate-500">{new Date(forecast.createdAt).toLocaleString()}</p>
        </article>
      ))}
    </div>
  );
}
