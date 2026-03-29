interface StatCardProps {
  label: string;
  value: string | number;
  accent: string;
  sublabel?: string;
}

export default function StatCard({ label, value, accent, sublabel }: StatCardProps): JSX.Element {
  return (
    <article className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 transition hover:-translate-y-0.5" style={{ borderBottomColor: accent, borderBottomWidth: 2 }}>
      <p className="text-sm text-[var(--color-muted)]">{label}</p>
      <p className="mt-2 text-3xl font-semibold" style={{ color: accent }}>
        {value}
      </p>
      {sublabel ? <p className="mt-1 text-xs text-[var(--color-muted)]">{sublabel}</p> : null}
    </article>
  );
}
