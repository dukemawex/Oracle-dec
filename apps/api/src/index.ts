import cors from 'cors';
import dotenv from 'dotenv';
import express, { type NextFunction, type Request, type Response } from 'express';
import { PrismaClient } from '@prisma/client';
import { forecastBatchSchema, type ForecastBatchInput } from './shared/index.js';

dotenv.config();

const app = express();
const prisma = new PrismaClient();

const port = Number(process.env.PORT ?? '8080');
const metaculusToken = process.env.METACULUS_TOKEN;
const metaculusApiBase = (process.env.METACULUS_API_BASE ?? 'https://www.metaculus.com/api2').replace(/\/$/, '');
const vercelDeployHook = process.env.VERCEL_DEPLOY_HOOK_URL;

if (!metaculusToken) {
  throw new Error('METACULUS_TOKEN is required');
}

app.use(cors());
app.use(express.json({ limit: '2mb' }));

interface CalibrationPoint {
  bucket: string;
  predicted: number;
  observed: number;
  count: number;
}

interface ExtremizationPoint {
  questionId: number;
  original: number;
  extremized: number;
  createdAt: Date;
}

async function buildCalibrationPoints(): Promise<CalibrationPoint[]> {
  const resolved = await prisma.forecast.findMany({ where: { resolved: true } });
  const bins = Array.from({ length: 10 }, (_, i) => ({ bin: i / 10, count: 0, avgPred: 0, hitRate: 0 }));

  for (const forecast of resolved) {
    const idx = Math.min(9, Math.floor(forecast.finalProbability * 10));
    const current = bins[idx];
    if (!current) {
      continue;
    }
    current.count += 1;
    current.avgPred += forecast.finalProbability;
    current.hitRate += forecast.outcome ? 1 : 0;
  }

  return bins
    .filter((b) => b.count > 0)
    .map((b) => ({
      bucket: `${Math.round(b.bin * 100)}-${Math.round((b.bin + 0.1) * 100)}%`,
      predicted: b.avgPred / b.count,
      observed: b.hitRate / b.count,
      count: b.count,
    }));
}

async function buildBrier(): Promise<{ count: number; brier: number | null }> {
  const resolved = await prisma.forecast.findMany({ where: { resolved: true } });
  if (resolved.length === 0) {
    return { count: 0, brier: null };
  }

  const brier =
    resolved.reduce((acc: number, f: (typeof resolved)[number]) => {
      const outcome = f.outcome ? 1 : 0;
      return acc + (f.finalProbability - outcome) ** 2;
    }, 0) / resolved.length;

  return { count: resolved.length, brier };
}

async function buildExtremizationPoints(): Promise<ExtremizationPoint[]> {
  const recent = await prisma.forecast.findMany({
    orderBy: { createdAt: 'desc' },
    take: 200,
  });

  return recent.map((f: (typeof recent)[number]) => {
    const original = f.tinyfishProbability ?? f.finalProbability;
    return {
      questionId: f.questionId,
      original,
      extremized: f.finalProbability,
      createdAt: f.createdAt,
    };
  });
}

function auth(req: Request, res: Response, next: NextFunction): void {
  const authHeader = req.header('authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    res.status(401).json({ error: 'Missing bearer token' });
    return;
  }

  const token = authHeader.slice('Bearer '.length).trim();
  if (token !== metaculusToken) {
    res.status(403).json({ error: 'Invalid token' });
    return;
  }

  next();
}

app.get('/healthz', (_req, res) => {
  res.json({ ok: true });
});

app.get('/health', (_req, res) => {
  res.json({ ok: true });
});

app.post('/api/forecasts/batch', auth, async (req, res) => {
  const parse = forecastBatchSchema.safeParse(req.body);
  if (!parse.success) {
    res.status(400).json({ error: parse.error.flatten() });
    return;
  }

  const body: ForecastBatchInput = parse.data;

  const batch = await prisma.forecastBatch.create({
    data: {
      batchTimestamp: new Date(body.batchTimestamp),
      forecasts: {
        create: body.records.map((record) => ({
          tournament: record.tournament,
          questionId: record.questionId,
          questionTitle: record.questionTitle,
          tinyfishProbability: record.tinyfishProbability,
          finalProbability: record.finalProbability,
          model: record.model,
          createdAt: new Date(record.createdAt),
        })),
      },
    },
    include: { forecasts: true },
  });

  if (vercelDeployHook) {
    void fetch(vercelDeployHook, { method: 'POST' }).catch((error: unknown) => {
      const message = error instanceof Error ? error.message : 'unknown error';
      console.error('Deploy hook failed:', message);
    });
  }

  res.status(201).json({ batchId: batch.id, ingested: batch.forecasts.length });
});

app.get('/api/forecasts', async (req, res) => {
  const limitRaw = req.query.limit;
  const parsedLimit = typeof limitRaw === 'string' ? Number(limitRaw) : 200;
  const limit = Number.isFinite(parsedLimit) && parsedLimit > 0 ? Math.min(Math.floor(parsedLimit), 1000) : 200;

  const forecasts = await prisma.forecast.findMany({
    orderBy: { createdAt: 'desc' },
    take: limit,
  });

  res.json({ forecasts });
});

app.get('/api/analytics/calibration', async (_req, res) => {
  const points = await buildCalibrationPoints();
  res.json({ points });
});

app.get('/api/analytics/brier', async (_req, res) => {
  res.json(await buildBrier());
});

app.get('/api/analytics/extremization', async (_req, res) => {
  const points = await buildExtremizationPoints();
  res.json({ points });
});

app.get('/api/performance/calibration', async (_req, res) => {
  try {
    const points = await buildCalibrationPoints();
    res.json({ points });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    res.status(500).json({ error: message });
  }
});

app.get('/api/performance/brier', async (_req, res) => {
  try {
    res.json(await buildBrier());
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    res.status(500).json({ error: message });
  }
});

app.get('/api/performance/extremization', async (_req, res) => {
  try {
    const points = await buildExtremizationPoints();
    res.json({ points });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    res.status(500).json({ error: message });
  }
});

app.get('/api/performance', async (_req, res) => {
  try {
    const forecasts = await prisma.forecast.findMany({
      orderBy: { createdAt: 'desc' },
      take: 1000,
    });
    const resolved = forecasts.filter((forecast) => forecast.resolved && forecast.outcome !== null);
    const total_forecasts = forecasts.length;
    const resolved_count = resolved.length;

    const mean_brier_score =
      resolved_count === 0
        ? 0
        : resolved.reduce((sum, forecast) => {
            const outcome = forecast.outcome ? 1 : 0;
            return sum + (forecast.finalProbability - outcome) ** 2;
          }, 0) / resolved_count;

    const mean_log_score =
      resolved_count === 0
        ? 0
        : resolved.reduce((sum, forecast) => {
            const outcome = forecast.outcome ? 1 : 0;
            const p = Math.min(0.999999, Math.max(0.000001, forecast.finalProbability));
            return sum - (outcome === 1 ? Math.log(p) : Math.log(1 - p));
          }, 0) / resolved_count;

    const calibration_bins = Array.from({ length: 10 }, (_, i) => ({
      predicted_prob: i * 0.1 + 0.05,
      actual_freq: 0,
      count: 0,
    }));
    for (const forecast of resolved) {
      const idx = Math.min(Math.floor(forecast.finalProbability * 10), 9);
      const bin = calibration_bins[idx];
      if (!bin) {
        continue;
      }
      bin.count += 1;
      bin.actual_freq += forecast.outcome ? 1 : 0;
    }
    for (const bin of calibration_bins) {
      if (bin.count > 0) {
        bin.actual_freq /= bin.count;
      }
    }

    const by_tournament = forecasts.reduce<Record<string, { count: number; resolved_count: number; mean_brier_score: number }>>((acc, forecast) => {
      const entry = acc[forecast.tournament] ?? { count: 0, resolved_count: 0, mean_brier_score: 0 };
      entry.count += 1;
      if (forecast.resolved && forecast.outcome !== null) {
        entry.resolved_count += 1;
        const outcome = forecast.outcome ? 1 : 0;
        const brier = (forecast.finalProbability - outcome) ** 2;
        entry.mean_brier_score =
          entry.resolved_count === 1
            ? brier
            : entry.mean_brier_score + (brier - entry.mean_brier_score) / entry.resolved_count;
      }
      acc[forecast.tournament] = entry;
      return acc;
    }, {});

    const extremized = forecasts.filter(
      (forecast) => forecast.tinyfishProbability !== null && Math.abs(forecast.finalProbability - forecast.tinyfishProbability) > 0.0001,
    );
    const nonExtremized = forecasts.filter(
      (forecast) => forecast.tinyfishProbability === null || Math.abs(forecast.finalProbability - forecast.tinyfishProbability) <= 0.0001,
    );
    const resolvedExtremized = extremized.filter((forecast) => forecast.resolved && forecast.outcome !== null);
    const resolvedNonExtremized = nonExtremized.filter((forecast) => forecast.resolved && forecast.outcome !== null);

    const extremized_mean_brier =
      resolvedExtremized.length === 0
        ? 0
        : resolvedExtremized.reduce((sum, forecast) => {
            const outcome = forecast.outcome ? 1 : 0;
            return sum + (forecast.finalProbability - outcome) ** 2;
          }, 0) / resolvedExtremized.length;

    const non_extremized_mean_brier =
      resolvedNonExtremized.length === 0
        ? 0
        : resolvedNonExtremized.reduce((sum, forecast) => {
            const outcome = forecast.outcome ? 1 : 0;
            return sum + (forecast.finalProbability - outcome) ** 2;
          }, 0) / resolvedNonExtremized.length;

    const by_strength = extremized.reduce<Record<string, number>>((acc, forecast) => {
      const delta = Math.abs(forecast.finalProbability - (forecast.tinyfishProbability ?? forecast.finalProbability));
      const label = delta >= 0.2 ? 'strong' : delta >= 0.1 ? 'medium' : 'light';
      acc[label] = (acc[label] ?? 0) + 1;
      return acc;
    }, {});

    const improvement_pct =
      non_extremized_mean_brier > 0
        ? ((non_extremized_mean_brier - extremized_mean_brier) / non_extremized_mean_brier) * 100
        : 0;

    res.json({
      total_forecasts,
      resolved_count,
      mean_brier_score,
      mean_log_score,
      calibration_bins,
      resolution_rate: total_forecasts > 0 ? resolved_count / total_forecasts : 0,
      by_tournament,
      extremization_stats: {
        extremized_count: extremized.length,
        non_extremized_count: nonExtremized.length,
        extremized_mean_brier,
        non_extremized_mean_brier,
        improvement_pct,
        by_strength,
      },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    res.status(500).json({ error: message });
  }
});

app.post('/api/resolutions/sync', auth, async (_req, res) => {
  const unresolved = await prisma.forecast.findMany({
    where: { resolved: false },
    distinct: ['questionId'],
  });

  let updated = 0;
  for (const row of unresolved) {
    const response = await fetch(`${metaculusApiBase}/questions/${row.questionId}/`, {
      headers: { Authorization: `Token ${metaculusToken}` },
    });

    if (!response.ok) {
      continue;
    }

    const payload: unknown = await response.json();
    if (typeof payload !== 'object' || payload === null) {
      continue;
    }

    const maybeResolution = (payload as { resolution?: unknown }).resolution;
    if (typeof maybeResolution !== 'boolean') {
      continue;
    }

    const result = await prisma.forecast.updateMany({
      where: { questionId: row.questionId, resolved: false },
      data: { resolved: true, outcome: maybeResolution },
    });
    updated += result.count;
  }

  res.json({ updated });
});

app.use((error: unknown, _req: Request, res: Response, _next: NextFunction) => {
  const message = error instanceof Error ? error.message : 'Unknown error';
  console.error(error);
  res.status(500).json({ error: message });
});

app.listen(port, () => {
  console.log(`OracleDeck backend listening on :${port}`);
});
