'use client';

import useSWR from 'swr';
import { endpoints, fetcher } from '../lib/api';
import type { BrierResponse } from '../lib/types';

export default function BrierPanel(): JSX.Element {
  const { data, error, mutate, isLoading } = useSWR<BrierResponse | null>(endpoints.brier(), fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: true,
  });

  if (error || data === null) {
    return (
      <p className="text-red-400">
        Failed to load Brier score
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
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h3 className="font-semibold">Brier Score</h3>
      <p className="mt-2 text-2xl">{data?.brier === null ? 'n/a' : data?.brier?.toFixed(4)}</p>
      <p className="text-sm text-slate-400">Resolved forecasts: {data?.count ?? 0}</p>
    </div>
  );
}
