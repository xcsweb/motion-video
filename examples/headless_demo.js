#!/usr/bin/env node
'use strict';

const { execFile } = require('node:child_process');
const { mkdir, mkdtemp, readFile, readdir, writeFile } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');

const repositoryRoot = resolve(__dirname, '..');
const cliPath = join(repositoryRoot, 'codecut', 'dist', 'cli.js');
const sourcePath = join(repositoryRoot, 'media', 'railgun_omr_v4_preview.mp4');
let activeOutputDirectory;

function execute(command, args) {
  return new Promise((resolvePromise, reject) => {
    execFile(command, args, {
      cwd: repositoryRoot,
      env: { ...process.env, CI: '1' },
      encoding: 'utf8',
      maxBuffer: 16 * 1024 * 1024,
      timeout: 180_000,
    }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') {
        reject(error);
        return;
      }
      resolvePromise({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

function clipIds(project) {
  return project.tracks.flatMap((track) => track.clips.map((clip) => clip.id));
}

async function prepareOutputDirectory(argument) {
  if (argument === undefined) return mkdtemp(join(tmpdir(), 'codecut-headless-demo-'));
  const directory = resolve(argument);
  await mkdir(directory, { recursive: true });
  const entries = await readdir(directory);
  if (entries.length > 0) {
    throw new Error(`Output directory must be empty so the demo starts from an empty project: ${directory}`);
  }
  return directory;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length > 1) throw new Error('Usage: node examples/headless_demo.js [empty-output-directory]');

  const outputDirectory = await prepareOutputDirectory(args[0]);
  activeOutputDirectory = outputDirectory;
  const projectDirectory = join(outputDirectory, 'project');
  const operationsDirectory = join(outputDirectory, 'operations');
  const commands = [];

  async function cli(cliArgs, expectedStatuses = [0]) {
    const result = await execute(process.execPath, [cliPath, ...cliArgs]);
    commands.push({ executable: cliPath, args: cliArgs, status: result.status });
    if (!expectedStatuses.includes(result.status)) {
      throw new Error([
        `codecut ${cliArgs.join(' ')} exited with ${result.status}; expected ${expectedStatuses.join('/')}`,
        result.stdout && `stdout: ${result.stdout}`,
        result.stderr && `stderr: ${result.stderr}`,
      ].filter(Boolean).join('\n'));
    }
    if (!result.stdout) throw new Error(`codecut ${cliArgs.join(' ')} returned no JSON result: ${result.stderr}`);
    let value;
    try {
      value = JSON.parse(result.stdout);
    } catch {
      throw new Error(`codecut ${cliArgs.join(' ')} returned non-JSON stdout: ${result.stdout}`);
    }
    if (value.ok !== true) throw new Error(`codecut ${cliArgs.join(' ')} did not return an ok envelope`);
    return value;
  }

  await cli(['project', 'init', projectDirectory, '--name', 'Railgun Headless Demo', '--json']);

  // Output settings have no edit operation; configure the authoritative JSON before
  // the first transactional asset write, then validate it through the real CLI.
  const projectPath = join(projectDirectory, 'project.json');
  const initialProject = JSON.parse(await readFile(projectPath, 'utf8'));
  Object.assign(initialProject.output, {
    path: 'artifacts/railgun-headless.mp4',
    width: 320,
    height: 180,
    frameRate: 12,
  });
  await writeFile(projectPath, `${JSON.stringify(initialProject, null, 2)}\n`, 'utf8');
  await cli(['project', 'validate', '--project', projectDirectory, '--json']);

  const added = await cli([
    'asset', 'add', sourcePath, '--id', 'railgun', '--kind', 'video',
    '--project', projectDirectory, '--json',
  ]);
  const probed = await cli(['asset', 'probe', 'railgun', '--project', projectDirectory, '--json']);

  const scenesQueued = await cli([
    'asset', 'analyze', 'scenes', 'railgun', '--start', '0', '--end', '8', '--threshold', '0.12',
    '--project', projectDirectory, '--detach', '--json',
  ]);
  const silenceQueued = await cli([
    'asset', 'analyze', 'silence', 'railgun', '--start', '0', '--end', '8',
    '--noise-db', '-45', '--minimum-duration', '0.2', '--project', projectDirectory, '--detach', '--json',
  ]);
  const scenesJobId = scenesQueued.job.id;
  const silenceJobId = silenceQueued.job.id;
  const scenesWaited = await cli(['jobs', 'wait', scenesJobId, '--project', projectDirectory, '--json']);
  const silenceWaited = await cli(['jobs', 'wait', silenceJobId, '--project', projectDirectory, '--json']);
  const scenesShown = await cli(['jobs', 'show', scenesJobId, '--project', projectDirectory, '--json']);
  const silenceShown = await cli(['jobs', 'show', silenceJobId, '--project', projectDirectory, '--json']);

  await mkdir(operationsDirectory, { recursive: true });
  const baseOperations = [
    { type: 'addTrack', track: { id: 'captions', kind: 'video', name: 'Captions', clips: [] } },
    {
      type: 'addClip', trackId: 'v1',
      clip: {
        id: 'main', type: 'video', assetId: 'railgun', start: 0, duration: 2.4,
        sourceStart: 2, volume: 0.65,
      },
    },
    {
      type: 'addClip', trackId: 'v2',
      clip: {
        id: 'broll', type: 'video', assetId: 'railgun', start: 0.4, duration: 1.2,
        sourceStart: 4.8, scale: 0.25, position: { x: 232, y: 8 }, opacity: 0.85,
      },
    },
    {
      type: 'addText', trackId: 'captions',
      clip: {
        id: 'title', type: 'text', text: 'RAILGUN // CODECUT', start: 0.2, duration: 1.6,
        fontFamily: 'sans', fontSize: 16, color: '#FFFFFFFF', align: 'center',
      },
    },
    {
      type: 'addText', trackId: 'captions',
      clip: {
        id: 'footer', type: 'text', text: 'OFFLINE / 02.400s', start: 1.9, duration: 0.5,
        fontFamily: 'sans', fontSize: 10, color: '#FFFFFFFF', align: 'center',
      },
    },
    {
      type: 'addClip', trackId: 'a1',
      clip: {
        id: 'music-bed', type: 'audio', assetId: 'railgun', start: 0, duration: 2.4,
        sourceStart: 2, volume: 0.22, fadeIn: 0.15, fadeOut: 0.15,
      },
    },
    {
      type: 'addClip', trackId: 'a2',
      clip: {
        id: 'accent', type: 'audio', assetId: 'railgun', start: 0.3, duration: 1.5,
        sourceStart: 5.5, volume: 0.12,
      },
    },
  ];
  const baseOperationsPath = join(operationsDirectory, 'base.json');
  await writeFile(baseOperationsPath, `${JSON.stringify(baseOperations, null, 2)}\n`, 'utf8');
  await cli([
    'edit', 'apply', '--operations', baseOperationsPath, '--project', projectDirectory,
    '--dry-run', '--summary', 'Preview multitrack railgun edit', '--json',
  ]);
  const baseEdit = await cli([
    'edit', 'apply', '--operations', baseOperationsPath, '--project', projectDirectory,
    '--summary', 'Build multitrack railgun edit', '--json',
  ]);

  const failureOperations = [{
    type: 'addClip', trackId: 'v1',
    clip: {
      id: 'broken-transition', type: 'video', assetId: 'railgun', start: 2.15, duration: 0.8,
      sourceStart: 6.2, transition: { type: 'xfade', duration: 0.25, name: 'codecut_invalid_xfade' },
    },
  }];
  const failureOperationsPath = join(operationsDirectory, 'inject-invalid-xfade.json');
  await writeFile(failureOperationsPath, `${JSON.stringify(failureOperations, null, 2)}\n`, 'utf8');
  const brokenEdit = await cli([
    'edit', 'apply', '--operations', failureOperationsPath, '--project', projectDirectory,
    '--summary', 'Inject a real FFmpeg xfade failure', '--json',
  ]);
  const revisionDiff = await cli([
    'history', 'diff', baseEdit.revision.id, brokenEdit.revision.id,
    '--project', projectDirectory, '--json',
  ]);
  const failedRender = await cli([
    'render', '--project', projectDirectory, '--output', 'artifacts/injected-failure.mp4', '--json',
  ], [4]);
  const failedJob = failedRender.job;
  const mediaFailureCodes = new Set(['MEDIA_PROCESS_FAILED', 'FFMPEG_PROGRESS_INVALID']);
  if (failedJob.status !== 'failed' || !mediaFailureCodes.has(failedJob.error?.code)
    || !/codecut_invalid_xfade|xfade|transition/i.test(failedJob.logTail?.stderr ?? '')) {
    throw new Error(`The invalid xfade did not produce a real media failure: ${JSON.stringify(failedJob)}`);
  }

  const undone = await cli(['history', 'undo', '--project', projectDirectory, '--json']);
  const redone = await cli(['history', 'redo', '--project', projectDirectory, '--json']);
  const finalUndo = await cli(['history', 'undo', '--project', projectDirectory, '--json']);
  const history = await cli(['history', 'list', '--project', projectDirectory, '--json']);

  const frameResult = await cli([
    'preview', 'frame', '--at', '0.8', '--width', '320', '--height', '180',
    '--output', 'artifacts/frame.png', '--project', projectDirectory, '--json',
  ]);
  const sheetResult = await cli([
    'preview', 'sheet', '--start', '0', '--end', '2.4', '--interval', '0.6',
    '--columns', '4', '--rows', '1', '--width', '160', '--height', '90',
    '--output', 'artifacts/sheet.png', '--project', projectDirectory, '--json',
  ]);
  const proxyResult = await cli([
    'preview', 'proxy', '--width', '160', '--height', '90', '--crf', '32',
    '--audio-bitrate', '64', '--output', 'artifacts/proxy.mp4', '--project', projectDirectory, '--json',
  ]);

  const renderQueued = await cli(['render', '--project', projectDirectory, '--detach', '--json']);
  const renderJobId = renderQueued.job.id;
  const renderWaited = await cli(['jobs', 'wait', renderJobId, '--project', projectDirectory, '--json']);
  const renderShown = await cli(['jobs', 'show', renderJobId, '--project', projectDirectory, '--json']);
  const finalProject = await cli(['project', 'show', '--project', projectDirectory, '--json']);
  const jobs = await cli(['jobs', 'list', '--project', projectDirectory, '--json']);

  // These three diagnostic entry points intentionally use their public CLI contract.
  const doctor = await cli(['doctor', '--project', projectDirectory, '--json']);
  const failureLogs = await cli(['logs', failedJob.id, '--project', projectDirectory, '--json']);
  const diagnosis = await cli(['diagnose', failedJob.id, '--project', projectDirectory, '--json']);

  const summary = {
    ok: true,
    outputDirectory,
    summaryPath: join(outputDirectory, 'summary.json'),
    projectDirectory,
    projectPath,
    source: {
      path: sourcePath,
      analysisRange: { start: 0, end: 8 },
      maximumClipSourceEnd: 7,
      metadata: probed.asset.metadata,
    },
    configuration: { width: 320, height: 180, frameRate: 12, duration: 2.4, representativeTime: 0.8 },
    commands,
    revisions: {
      assetAdd: added.revision,
      assetProbe: probed.revision,
      baseEdit: baseEdit.revision,
      brokenEdit: brokenEdit.revision,
      undo: undone.revision,
      redo: redone.revision,
      finalUndo: finalUndo.revision,
    },
    history: {
      list: history,
      diff: revisionDiff,
      undoClipIds: clipIds(undone.project),
      redoClipIds: clipIds(redone.project),
      finalClipIds: clipIds(finalUndo.project),
    },
    analysis: {
      scenes: { jobId: scenesJobId, result: scenesWaited.job.result.data, shown: scenesShown.job },
      silence: { jobId: silenceJobId, result: silenceWaited.job.result.data, shown: silenceShown.job },
    },
    previews: {
      frame: { job: frameResult.job, outputPath: frameResult.outputPath, parameters: frameResult.result.parameters },
      sheet: { job: sheetResult.job, outputPath: sheetResult.outputPath, parameters: sheetResult.result.parameters },
      proxy: { job: proxyResult.job, outputPath: proxyResult.outputPath, parameters: proxyResult.result.parameters },
    },
    render: { job: renderWaited.job, shown: renderShown.job, outputPath: renderWaited.job.result.outputPath },
    failure: {
      injection: 'FFmpeg xfade transition codecut_invalid_xfade',
      commandStatus: 4,
      job: failedJob,
      logs: failureLogs,
      diagnosis,
    },
    doctor,
    jobs: jobs.jobs,
    finalProject: finalProject.project,
    finalTimeline: finalProject.timeline,
  };
  await writeFile(summary.summaryPath, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

main().catch((error) => {
  process.exitCode = 1;
  process.stderr.write(`${JSON.stringify({
    ok: false,
    outputDirectory: activeOutputDirectory,
    error: error instanceof Error ? error.message : String(error),
  }, null, 2)}\n`);
});
