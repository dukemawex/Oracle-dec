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

  const points = bins
    .filter((b) => b.count > 0)
    .map((b) => ({
      bucket: `${Math.round(b.bin * 100)}-${Math.round((b.bin + 0.1) * 100)}%`,
      predicted: b.avgPred / b.count,
      observed: b.hitRate / b.count,
      count: b.count,
    }));

  res.json({ points });
});

app.get('/api/analytics/brier', async (_req, res) => {
  const resolved = await prisma.forecast.findMany({ where: { resolved: true } });
  if (resolved.length === 0) {
    res.json({ count: 0, brier: null });
    return;
  }

  const brier =
    resolved.reduce((acc: number, f: (typeof resolved)[number]) => {
      const outcome = f.outcome ? 1 : 0;
      return acc + (f.finalProbability - outcome) ** 2;
    }, 0) / resolved.length;

  res.json({ count: resolved.length, brier });
});

app.get('/api/analytics/extremization', async (_req, res) => {
  const recent = await prisma.forecast.findMany({
    orderBy: { createdAt: 'desc' },
    take: 200,
  });

  const points = recent.map((f: (typeof recent)[number]) => {
    const centered = f.finalProbability - 0.5;
    const extremized = Math.max(0.01, Math.min(0.99, 0.5 + centered * 1.15));
    return {
      questionId: f.questionId,
      original: f.finalProbability,
      extremized,
      createdAt: f.createdAt,
    };
  });

  res.json({ points });
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
