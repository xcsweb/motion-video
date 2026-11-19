import { readFile } from 'node:fs/promises';
import { parseSrt } from './edit.js';
import { CodeCutError, ExitCode } from './errors.js';
import type { TranscriptIssue, TranscriptReport } from './schema.js';

export interface TranscriptCheckOptions {
  srtPath: string;
  maxGap?: number;
  maxCharacters?: number;
  maxDuration?: number;
}

const DEFAULT_MAX_GAP = 1.2;
const DEFAULT_MAX_CHARACTERS = 24;
const DEFAULT_MAX_DURATION = 8;
const EPSILON = 1e-6;
const HESITATION = /[嗯呃额唔]/u;
const LEADING_FILLER = /^(?:嗯+|啊+|呃+|额+|唔+|那个|就是)/u;
const PUNCTUATION_OR_SYMBOL = /[\s\p{P}\p{S}]/gu;
const LEADING_FILLER_STRIP = /^(?:嗯+|啊+|呃+|额+|唔+|那个|然后|就是)+/u;

function countCharacters(text: string): number {
  return text.replace(PUNCTUATION_OR_SYMBOL, '').length;
}

function normalizeForDuplicate(text: string): string {
  return text
    .toLowerCase()
    .replace(PUNCTUATION_OR_SYMBOL, '')
    .replace(LEADING_FILLER_STRIP, '');
}

function isDuplicate(previous: string, current: string): boolean {
  const left = normalizeForDuplicate(previous);
  const right = normalizeForDuplicate(current);
  if (left.length < 2 || right.length < 2) return false;
  if (left === right) return true;
  const shorter = left.length <= right.length ? left : right;
  const longer = left.length <= right.length ? right : left;
  return shorter.length >= 4 && longer.startsWith(shorter);
}

function isFiller(text: string): boolean {
  const trimmed = text.trim();
  if (HESITATION.test(trimmed)) return true;
  return LEADING_FILLER.test(trimmed) && countCharacters(trimmed) <= 10;
}

function issue(
  type: TranscriptIssue['type'],
  severity: TranscriptIssue['severity'],
  cue: number,
  start: number,
  end: number,
  message: string,
): TranscriptIssue {
  return { type, severity, cue, start, end, message };
}

export async function checkTranscript(options: TranscriptCheckOptions): Promise<TranscriptReport> {
  const maxGap = options.maxGap ?? DEFAULT_MAX_GAP;
  const maxCharacters = options.maxCharacters ?? DEFAULT_MAX_CHARACTERS;
  const maxDuration = options.maxDuration ?? DEFAULT_MAX_DURATION;
  let source: string;
  try {
    source = await readFile(options.srtPath, 'utf8');
  } catch (cause) {
    throw new CodeCutError('SRT_READ_FAILED', 'Could not read SRT subtitle file', ExitCode.ProjectValidation, {
      stage: 'transcript.check',
      path: options.srtPath,
      cause,
      retryable: true,
    });
  }

  const cues = parseSrt(source);
  const issues: TranscriptIssue[] = [];
  for (const [index, cue] of cues.entries()) {
    const cueNumber = index + 1;
    const previous = index > 0 ? cues[index - 1] : undefined;
    if (previous) {
      const gap = cue.start - previous.end;
      if (gap < -EPSILON) {
        issues.push(issue(
          'overlap',
          'error',
          cueNumber,
          cue.start,
          cue.end,
          `Cue overlaps the previous cue by ${Math.abs(gap).toFixed(3)}s; rectime it before importing.`,
        ));
      } else if (gap > maxGap) {
        issues.push(issue(
          'long-gap',
          'warning',
          cueNumber,
          cue.start,
          cue.end,
          `There is a ${gap.toFixed(2)}s pause before this cue (limit ${maxGap}s); consider tightening the cut or keeping it intentionally.`,
        ));
      }
      if (isDuplicate(previous.text, cue.text)) {
        issues.push(issue(
          'duplicate',
          'warning',
          index,
          previous.start,
          previous.end,
          `Cue ${index} looks like a false start or repeat of cue ${cueNumber}; usually keep the later, fuller line and trim the earlier one.`,
        ));
      }
    }
    if (isFiller(cue.text)) {
      issues.push(issue(
        'filler',
        'warning',
        cueNumber,
        cue.start,
        cue.end,
        'Cue is mostly filler or hesitation; consider trimming it or cleaning the transcript.',
      ));
    }
    const duration = cue.end - cue.start;
    const characters = countCharacters(cue.text);
    if (duration > maxDuration || characters > maxCharacters) {
      issues.push(issue(
        'too-long',
        'warning',
        cueNumber,
        cue.start,
        cue.end,
        `Cue runs ${duration.toFixed(2)}s with ${characters} characters (limits ${maxDuration}s / ${maxCharacters}); split it for readability.`,
      ));
    }
  }

  const warnings = issues.filter((entry) => entry.severity === 'warning').length;
  return {
    path: options.srtPath,
    cueCount: cues.length,
    duration: cues.length === 0 ? 0 : cues[cues.length - 1]!.end,
    warnings,
    errors: issues.length - warnings,
    issues,
  };
}
