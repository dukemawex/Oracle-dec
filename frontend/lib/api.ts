import type { BrierResponse, CalibrationResponse, ExtremizationResponse, ForecastResponse } from './types';

const backendUrl = (process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8080').replace(/\/$/, '');

export function getApiUrl(path: string): string {
  return `${backendUrl}${path}`;
}

export async function fetcher<T>(url: string): Promise<T> {
  const response = await fetch(url, { next: { revalidate: 30 } });
  if (!response.ok) {
    throw new Error(`Failed request: ${response.status}`);
  }
  return (await response.json()) as T;
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
