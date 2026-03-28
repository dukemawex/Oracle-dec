'use client';

import useSWR from 'swr';
import { endpoints, fetcher } from '../lib/api';
import type { ForecastResponse } from '../lib/types';

export default function ForecastCards(): JSX.Element {
  const { data, error } = useSWR<ForecastResponse>(endpoints.forecasts(), fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: true,
  });

  if (error) {
    return <p className="text-red-400">Failed to load forecasts</p>;
  }

  if (!data) {
    return <p className="text-slate-400">Loading forecasts...</p>;
  }

  return (
    <div className="grid gap-3">
      {data.forecasts.map((forecast) => (
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
