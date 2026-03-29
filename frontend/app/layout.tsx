import './globals.css';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import AppNav from '../components/AppNav';

export const metadata: Metadata = {
  title: 'OracleDeck Dashboard',
  description: 'Autonomous Superforecaster dashboard',
};

export default function RootLayout({ children }: { children: ReactNode }): JSX.Element {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
        <AppNav />
        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
