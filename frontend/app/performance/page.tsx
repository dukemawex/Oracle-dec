import PerformanceClient from '../../components/PerformanceClient';
import { endpoints, fetcher } from '../../lib/api';
import type { BrierResponse, CalibrationResponse, ExtremizationResponse, ForecastResponse } from '../../lib/types';

export const revalidate = 30;

export default async function PerformancePage(): Promise<JSX.Element> {
  const [fallbackForecasts, fallbackBrier, fallbackCalibration, fallbackExtremization] = await Promise.all([
    fetcher<ForecastResponse>(endpoints.forecasts()),
    fetcher<BrierResponse>(endpoints.brier()),
    fetcher<CalibrationResponse>(endpoints.calibration()),
    fetcher<ExtremizationResponse>(endpoints.extremization()),
  ]);

  return (
    <PerformanceClient
      fallbackForecasts={fallbackForecasts}
      fallbackBrier={fallbackBrier}
      fallbackCalibration={fallbackCalibration}
      fallbackExtremization={fallbackExtremization}
    />
  );
}
