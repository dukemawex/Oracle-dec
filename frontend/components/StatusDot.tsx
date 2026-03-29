interface StatusDotProps {
  active: boolean;
  label: string;
}

export default function StatusDot({ active, label }: StatusDotProps): JSX.Element {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs font-medium text-[var(--color-text)]">
      <span
        className={`h-2.5 w-2.5 rounded-full ${active ? 'animate-pulse bg-[var(--color-success)]' : 'bg-[var(--color-danger)]'}`}
      />
      {label}
    </span>
  );
}
