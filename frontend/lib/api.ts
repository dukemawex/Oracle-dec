import type { BrierResponse, CalibrationResponse, ExtremizationResponse, ForecastResponse } from './types';

const backendUrl = (process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8080').replace(/\/$/, '');
const FETCH_TIMEOUT_MS = 10_000;

export function getApiUrl(path: string): string {
  return `${backendUrl}${path}`;
}

async function fetchWithTimeout(url: string, init?: RequestInit): Promise<Response | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
    });

    if (!response.ok) {
      return null;
    }

    return response;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetcher<T>(url: string): Promise<T | null> {
  const response = await fetchWithTimeout(url, { next: { revalidate: 30 } });
  if (!response) {
    return null;
  }

  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export const endpoints = {
  forecasts: (): string => getApiUrl('/api/forecasts?limit=100'),
  calibration: (): string => getApiUrl('/api/analytics/calibration'),
  brier: (): string => getApiUrl('/api/analytics/brier'),
  extremization: (): string => getApiUrl('/api/analytics/extremization'),
};

export type ApiResponses = {
  forecasts: ForecastResponse;
  calibration: CalibrationResponse;
  brier: BrierResponse;
  extremization: ExtremizationResponse;
};
