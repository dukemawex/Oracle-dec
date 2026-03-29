'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

const navItems = [
  { href: '/', label: 'Dashboard' },
  { href: '/forecasts', label: 'Forecasts' },
  { href: '/performance', label: 'Performance' },
];

function NavLinks({ mobile = false, onNavigate }: { mobile?: boolean; onNavigate?: () => void }): JSX.Element {
  const pathname = usePathname();

  return (
    <div className={mobile ? 'flex flex-col gap-2' : 'hidden items-center gap-6 md:flex'}>
      {navItems.map((item) => {
        const isActive = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={`text-sm ${isActive ? 'text-[var(--color-text)]' : 'text-[var(--color-muted)] hover:text-[var(--color-text)]'}`}
          >
            <span className={`border-b-2 pb-1 ${isActive ? 'border-[var(--color-primary)]' : 'border-transparent'}`}>{item.label}</span>
          </Link>
        );
      })}
    </div>
  );
}

export default function AppNav(): JSX.Element {
  const [open, setOpen] = useState(false);

  return (
    <nav className="border-b border-[var(--color-border)] bg-[var(--color-bg)]/90 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="text-lg font-semibold tracking-tight text-white">
          OracleDeck
        </Link>

        <NavLinks />

        <button
          type="button"
          aria-label="Toggle navigation"
          className="rounded-md border border-[var(--color-border)] px-2 py-1 text-sm text-[var(--color-text)] md:hidden"
          onClick={() => setOpen((value) => !value)}
        >
          ☰
        </button>
      </div>
      {open ? (
        <div className="mx-auto max-w-7xl px-4 pb-3 md:hidden">
          <NavLinks mobile onNavigate={() => setOpen(false)} />
        </div>
      ) : null}
    </nav>
  );
}
