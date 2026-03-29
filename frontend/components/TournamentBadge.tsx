const colors: Record<string, string> = {
  'Spring AIB 2026': 'var(--color-primary)',
  MiniBench: 'var(--color-success)',
  'Market Pulse Q1': 'var(--color-warning)',
};

interface TournamentBadgeProps {
  tournament: string;
  active?: boolean;
}

export default function TournamentBadge({ tournament, active = true }: TournamentBadgeProps): JSX.Element {
  const color = colors[tournament] ?? 'var(--color-muted)';

  return (
    <span className="inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs text-[var(--color-text)]" style={{ borderColor: color, backgroundColor: 'rgba(18,18,26,0.9)' }}>
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: active ? color : 'var(--color-danger)' }} />
      {tournament}
    </span>
  );
}
