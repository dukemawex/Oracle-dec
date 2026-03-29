interface ProbabilityPillProps {
  probability: number;
  extremized?: boolean;
}

export default function ProbabilityPill({ probability, extremized = false }: ProbabilityPillProps): JSX.Element {
  const color =
    probability > 0.65
      ? 'var(--color-success)'
      : probability < 0.35
        ? 'var(--color-danger)'
        : 'var(--color-muted)';

  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium text-white" style={{ backgroundColor: color }}>
      {(probability * 100).toFixed(1)}%
      {extremized ? ' ⚡' : ''}
    </span>
  );
}
