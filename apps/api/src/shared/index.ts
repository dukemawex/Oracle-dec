import { z } from 'zod';

export const forecastRecordSchema = z.object({
  tournament: z.string().min(1),
  questionId: z.number().int().positive(),
  questionTitle: z.string().min(1),
  tinyfishProbability: z.number().min(0).max(1).nullable(),
  finalProbability: z.number().min(0).max(1),
  model: z.string().min(1),
  createdAt: z.string().datetime(),
});

export const forecastBatchSchema = z.object({
  batchTimestamp: z.string().datetime(),
  records: z.array(forecastRecordSchema),
});

export type ForecastRecordInput = z.infer<typeof forecastRecordSchema>;
export type ForecastBatchInput = z.infer<typeof forecastBatchSchema>;
