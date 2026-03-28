export interface Forecast {
  id: string;
  questionId: number;
  questionTitle: string;
  tournament: string;
  tinyfishProbability: number | null;
  finalProbability: number;
  model: string;
  createdAt: string;
  resolved: boolean;
  outcome: boolean | null;
}

export interface ForecastResponse {
  forecasts: Forecast[];
}

export interface CalibrationPoint {
  bucket: string;
  predicted: number;
  observed: number;
  count: number;
}

export interface CalibrationResponse {
  points: CalibrationPoint[];
}

export interface BrierResponse {
  count: number;
  brier: number | null;
}

export interface ExtremizationPoint {
  questionId: number;
  original: number;
  extremized: number;
  createdAt: string;
}

export interface ExtremizationResponse {
  points: ExtremizationPoint[];
}
