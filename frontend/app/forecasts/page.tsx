import ForecastsClient from '../../components/ForecastsClient';
import { endpoints, fetcher } from '../../lib/api';
import type { ForecastResponse } from '../../lib/types';

export const revalidate = 30;

export default async function ForecastsPage(): Promise<JSX.Element> {
  const fallbackData = await fetcher<ForecastResponse>(endpoints.forecasts());
  return <ForecastsClient fallbackData={fallbackData} />;
}
