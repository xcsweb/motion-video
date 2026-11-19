import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { addAsset } from '../dist/assets.js';
import { applyEdit } from '../dist/edit.js';
import { initProject } from '../dist/project.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');

function execute(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) reject(new Error(`${command} failed: ${stderr || error.message}`));
      else resolve({ stdout, stderr });
    });
  });
}

function cli(args) {
  return new Promise((resolve) => {
    execFile(process.execPath, [cliPath, ...args], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
      resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

test('colour grade, volume automation and loudness normalization reach the render plan', { timeout: 120_000 }, async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-grade-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const project = join(directory, 'project');
  await initProject(project);

  const visual = join(project, 'visual.mp4');
  await execute('ffmpeg', [
    '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x804020:s=64x64:r=8:d=3',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', visual,
  ]);
  const tone = join(project, 'tone.wav');
  await execute('ffmpeg', [
    '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3',
    '-c:a', 'pcm_s16le', tone,
  ]);
  await addAsset(project, { id: 'visual', path: visual });
  await addAsset(project, { id: 'tone', path: tone });

  await applyEdit(project, [
    {
      type: 'addClip',
      trackId: 'v1',
      clip: {
        id: 'shot', type: 'video', assetId: 'visual', start: 0, duration: 3,
        grade: { warmth: 0.4, contrast: 1.1, saturation: 1.15 },
      },
    },
    {
      type: 'addClip',
      trackId: 'a1',
      clip: {
        id: 'bed', type: 'audio', assetId: 'tone', start: 0, duration: 3,
        volumePoints: [{ at: 0, volume: 0 }, { at: 1, volume: 0.3 }, { at: 3, volume: 0.3 }],
      },
    },
  ]);

  const projectPath = join(project, 'project.json');
  const data = JSON.parse(await readFile(projectPath, 'utf8'));
  data.output = { ...data.output, path: 'out.mp4', width: 64, height: 64, frameRate: 8, loudness: { target: -14 } };
  await writeFile(projectPath, `${JSON.stringify(data, null, 2)}\n`, 'utf8');

  const dry = await cli(['render', '--project', project, '--dry-run', '--json']);
  assert.equal(dry.status, 0, dry.stderr);
  const plan = JSON.parse(dry.stdout).plan;
  assert.match(plan.filter_graph, /eq=contrast=1\.1:saturation=1\.15/);
  assert.match(plan.filter_graph, /colorbalance=rm=0\.06:gm=0\.02:bm=-0\.06/);
  assert.match(plan.filter_graph, /volume=eval=frame:volume='if\(lt\(t,0\),0,if\(lt\(t,1\)/);
  assert.match(plan.filter_graph, /loudnorm=I=-14:TP=-1\.5:LRA=11/);
  assert.match(plan.filter_graph, /aresample=48000/);

  const render = await cli(['render', '--project', project, '--force']);
  assert.equal(render.status, 0, render.stderr);

  const probe = await execute('ffprobe', [
    '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', join(project, 'out.mp4'),
  ]);
  assert.ok(Math.abs(Number(probe.stdout.trim()) - 3) < 0.1, probe.stdout);

  const loudness = await execute('ffmpeg', ['-i', join(project, 'out.mp4'), '-af', 'ebur128', '-f', 'null', '-']);
  const matches = [...loudness.stderr.matchAll(/I:\s*(-?\d+(?:\.\d+)?) LUFS/g)];
  assert.ok(matches.length > 0, loudness.stderr.slice(-500));
  const integrated = Number(matches[matches.length - 1][1]);
  assert.ok(integrated > -17 && integrated < -11, `integrated loudness ${integrated}`);
});
