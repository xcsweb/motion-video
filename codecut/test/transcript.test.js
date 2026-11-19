import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { checkTranscript } from '../dist/transcript.js';

const SRT = `1
00:00:00,000 --> 00:00:02,000
嗯，我们开始吧。

2
00:00:02,500 --> 00:00:04,000
我们开始吧

3
00:00:05,600 --> 00:00:06,200
嗯。

4
00:00:06,000 --> 00:00:14,500
今天我们来聊一个特别特别长的一句话看看字幕会不会太长
`;

async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-transcript-'));
  const path = join(directory, 'talk.srt');
  await writeFile(path, SRT, 'utf8');
  return path;
}

function cli(args, cwd) {
  return new Promise((resolve) => {
    execFile(process.execPath, [new URL('../dist/cli.js', import.meta.url).pathname, ...args], { cwd }, (error, stdout, stderr) => {
      resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

test('transcript check finds overlap, gaps, repeats, fillers, and long cues', async () => {
  const path = await fixture();
  const report = await checkTranscript({ srtPath: path });
  const types = new Set(report.issues.map((issue) => issue.type));

  assert.equal(report.cueCount, 4);
  assert.ok(types.has('overlap'));
  assert.ok(types.has('long-gap'));
  assert.ok(types.has('duplicate'));
  assert.ok(types.has('filler'));
  assert.ok(types.has('too-long'));
  assert.equal(report.errors, 1);
  assert.equal(report.warnings, 5);

  const duplicate = report.issues.find((issue) => issue.type === 'duplicate');
  assert.equal(duplicate.cue, 1);
  assert.match(duplicate.message, /false start/);
});

test('transcript thresholds are configurable', async () => {
  const path = await fixture();
  const relaxed = await checkTranscript({
    srtPath: path,
    maxGap: 2,
    maxCharacters: 100,
    maxDuration: 20,
  });
  assert.ok(!relaxed.issues.some((issue) => issue.type === 'long-gap'));
  assert.ok(!relaxed.issues.some((issue) => issue.type === 'too-long'));

  const strict = await checkTranscript({ srtPath: path, maxGap: 0.2, maxCharacters: 8, maxDuration: 1 });
  assert.ok(strict.issues.filter((issue) => issue.type === 'too-long').length > 1);
});

test('transcript check is exposed through the CLI', async () => {
  const path = await fixture();
  const json = await cli(['transcript', 'check', '--srt', path, '--json'], tmpdir());
  assert.equal(json.status, 0);
  const report = JSON.parse(json.stdout);
  assert.equal(report.ok, true);
  assert.equal(report.command, 'transcript.check');
  assert.equal(report.cueCount, 4);
  assert.equal(report.errors, 1);

  const text = await cli(['transcript', 'check', '--srt', path, '--max-gap', '2'], tmpdir());
  assert.equal(text.status, 0);
  assert.match(text.stdout, /Cues: 4/);
  assert.match(text.stdout, /\[error\] cue 4/);

  const missing = await cli(['transcript', 'check'], tmpdir());
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /requires --srt PATH/);
});

test('transcript report schema is registered and compilable', async () => {
  const result = await cli(['schema', '--json'], tmpdir());
  const schemas = JSON.parse(result.stdout);
  assert.ok(schemas.transcriptReport);
  assert.match(schemas.transcriptReport.$id, /transcript-report-v1/);
  assert.equal(schemas.transcriptReport.properties.cueCount.type, 'integer');
});
