'use client';

import useSWR from 'swr';
import { Line, LineChart, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { endpoints, fetcher } from '../lib/api';
import type { CalibrationResponse } from '../lib/types';

const perfectLine = [
  { bucket: '0%', predicted: 0, observed: 0 },
  { bucket: '25%', predicted: 0.25, observed: 0.25 },
  { bucket: '50%', predicted: 0.5, observed: 0.5 },
  { bucket: '75%', predicted: 0.75, observed: 0.75 },
  { bucket: '100%', predicted: 1, observed: 1 },
];

function Skeleton(): JSX.Element {
  return <div className="h-80 animate-pulse rounded-xl bg-[#1a1a24]" />;
}

export default function CalibrationChart({ fallbackData }: { fallbackData?: CalibrationResponse | null }): JSX.Element {
  const { data, error, mutate, isLoading } = useSWR<CalibrationResponse | null>(endpoints.calibration(), fetcher, {
    refreshInterval: 30000,
    fallbackData,
  });

  if (error) {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-muted)]">
        Failed to load calibration data.
        <button className="ml-3 rounded-md border border-[var(--color-primary)] px-2 py-1 text-[var(--color-primary)]" onClick={() => void mutate()}>
          Retry
        </button>
      </div>
    );
  }

  if (isLoading && !data) {
    return <Skeleton />;
  }

  const points = data?.points ?? [];

  return (
    <div className="h-80 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 10, right: 12, left: 12, bottom: 10 }}>
          <CartesianGrid stroke="#1e1e2e" strokeDasharray="3 3" />
          <XAxis dataKey="bucket" stroke="#64748b" label={{ value: 'Predicted Probability', position: 'insideBottom', dy: 10, fill: '#64748b' }} />
          <YAxis stroke="#64748b" domain={[0, 1]} label={{ value: 'Actual Frequency', angle: -90, dx: -4, fill: '#64748b' }} />
          <Tooltip
            contentStyle={{ backgroundColor: '#12121a', border: '1px solid #1e1e2e', borderRadius: 8, color: '#f1f5f9' }}
            labelStyle={{ color: '#f1f5f9' }}
          />
          <Line data={perfectLine} dataKey="observed" stroke="#64748b" strokeDasharray="6 4" dot={false} name="Perfect Calibration" />
          <Line dataKey="observed" stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} name="OracleDeck" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
