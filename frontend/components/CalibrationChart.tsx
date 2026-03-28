'use client';

import useSWR from 'swr';
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from 'recharts';
import { endpoints, fetcher } from '../lib/api';
import type { CalibrationResponse } from '../lib/types';

export default function CalibrationChart(): JSX.Element {
  const { data, error } = useSWR<CalibrationResponse>(endpoints.calibration(), fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: true,
  });

  if (error) {
    return <p className="text-red-400">Failed to load calibration</p>;
  }

  if (!data) {
    return <p className="text-slate-400">Loading calibration...</p>;
  }

  return (
    <div className="h-72 w-full rounded-lg border border-slate-800 bg-slate-900 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data.points}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="bucket" stroke="#cbd5e1" />
          <YAxis stroke="#cbd5e1" domain={[0, 1]} />
          <Tooltip />
          <Line type="monotone" dataKey="predicted" stroke="#22d3ee" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="observed" stroke="#f472b6" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
