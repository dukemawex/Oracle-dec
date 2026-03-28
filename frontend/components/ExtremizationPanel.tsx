'use client';

import useSWR from 'swr';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { endpoints, fetcher } from '../lib/api';
import type { ExtremizationResponse } from '../lib/types';

export default function ExtremizationPanel(): JSX.Element {
  const { data, error } = useSWR<ExtremizationResponse>(endpoints.extremization(), fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: true,
  });

  if (error) {
    return <p className="text-red-400">Failed to load extremization data</p>;
  }

  if (!data) {
    return <p className="text-slate-400">Loading extremization data...</p>;
  }

  const points = data.points.slice(0, 20).map((point) => ({
    name: String(point.questionId),
    original: point.original,
    extremized: point.extremized,
  }));

  return (
    <div className="h-72 w-full rounded-lg border border-slate-800 bg-slate-900 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={points}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="name" stroke="#cbd5e1" />
          <YAxis stroke="#cbd5e1" domain={[0, 1]} />
          <Tooltip />
          <Bar dataKey="original" fill="#38bdf8" />
          <Bar dataKey="extremized" fill="#f97316" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
