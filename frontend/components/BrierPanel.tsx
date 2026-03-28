'use client';

import useSWR from 'swr';
import { endpoints, fetcher } from '../lib/api';
import type { BrierResponse } from '../lib/types';

export default function BrierPanel(): JSX.Element {
  const { data, error } = useSWR<BrierResponse>(endpoints.brier(), fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: true,
  });

  if (error) {
    return <p className="text-red-400">Failed to load Brier score</p>;
  }

  if (!data) {
    return <p className="text-slate-400">Loading Brier score...</p>;
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h3 className="font-semibold">Brier Score</h3>
      <p className="mt-2 text-2xl">{data.brier === null ? 'n/a' : data.brier.toFixed(4)}</p>
      <p className="text-sm text-slate-400">Resolved forecasts: {data.count}</p>
    </div>
  );
}
