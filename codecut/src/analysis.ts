import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';
import { CodeCutError, ExitCode } from './errors.js';
import type { JobAnalysisRequest } from './jobs-store.js';
import type { AssetAnalysisResult } from './schema.js';

const MAX_ANALYSIS_RESULTS = 10_000;

function analysisError(message: string, path: string, cause?: unknown): CodeCutError {
  return new CodeCutError('ANALYSIS_RESULT_INVALID', message, ExitCode.Media, {
    stage: 'analysis.parse',
    path,
    ...(cause === undefined ? {} : { cause }),
    retryable: false,
  });
}

function boundedTime(value: number, offset: number, end: number): number {
  return Math.min(end, Math.max(0, offset + value));
}

export async function parseAnalysisLog(
  spec: JobAnalysisRequest,
  logPath: string,
  resultPath: string,
): Promise<AssetAnalysisResult> {
  const points: { time: number; score: number }[] = [];
  const intervals: { start: number; end: number; duration: number }[] = [];
  let pendingSceneTime: number | undefined;
  let pendingSilenceStart: number | undefined;
  try {
    const lines = createInterface({
      input: createReadStream(logPath, { encoding: 'utf8' }),
      crlfDelay: Infinity,
    });
    for await (const line of lines) {
      if (spec.type === 'scenes') {
        const time = /pts_time:([0-9]+(?:\.[0-9]+)?)/.exec(line);
        if (time) pendingSceneTime = Number(time[1]);
        const score = /lavfi\.scene_score=([0-9]+(?:\.[0-9]+)?)/.exec(line);
        if (score && pendingSceneTime !== undefined) {
          if (points.length >= MAX_ANALYSIS_RESULTS) {
            throw analysisError(`Scene analysis exceeded ${MAX_ANALYSIS_RESULTS} candidate points`, logPath);
          }
          points.push({
            time: boundedTime(pendingSceneTime, spec.start, spec.end),
            score: Math.min(1, Math.max(0, Number(score[1]))),
          });
          pendingSceneTime = undefined;
        }
      } else {
        const start = /silence_start:\s*([-+0-9.]+)/.exec(line);
        if (start) {
          const parsed = Number(start[1]);
          if (Number.isFinite(parsed)) pendingSilenceStart = boundedTime(parsed, spec.start, spec.end);
        }
        const end = /silence_end:\s*([-+0-9.]+)\s*\|\s*silence_duration:\s*([-+0-9.]+)/.exec(line);
        if (end && pendingSilenceStart !== undefined) {
          if (intervals.length >= MAX_ANALYSIS_RESULTS) {
            throw analysisError(`Silence analysis exceeded ${MAX_ANALYSIS_RESULTS} intervals`, logPath);
          }
          const intervalEnd = boundedTime(Number(end[1]), spec.start, spec.end);
          if (intervalEnd > pendingSilenceStart) {
            intervals.push({
              start: pendingSilenceStart,
              end: intervalEnd,
              duration: intervalEnd - pendingSilenceStart,
            });
          }
          pendingSilenceStart = undefined;
        }
      }
    }
  } catch (error) {
    if (error instanceof CodeCutError) throw error;
    throw analysisError('Could not read FFmpeg analysis output', logPath, error);
  }

  if (spec.type === 'silence' && pendingSilenceStart !== undefined && spec.end > pendingSilenceStart) {
    intervals.push({
      start: pendingSilenceStart,
      end: spec.end,
      duration: spec.end - pendingSilenceStart,
    });
  }
  const base = {
    assetId: spec.assetId,
    start: spec.start,
    end: spec.end,
    resultPath,
  };
  return spec.type === 'scenes'
    ? { type: 'scenes', ...base, threshold: spec.threshold, points }
    : {
      type: 'silence',
      ...base,
      noiseDb: spec.noiseDb,
      minimumDuration: spec.minimumDuration,
      intervals,
    };
}
