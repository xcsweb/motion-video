import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { createDefaultProject } from '../dist/project.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');
const require = createRequire(import.meta.url);
const Ajv2020 = require('ajv/dist/2020.js');
const addFormats = require('ajv-formats');

function cli(args, cwd = root) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, [cliPath, ...args], { cwd }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') {
        reject(error);
        return;
      }
      resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-cli-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

test('project lifecycle emits only parseable result JSON on stdout', async (t) => {
  const directory = await temporaryDirectory(t);
  const projectDirectory = join(directory, 'edit');

  const initialized = await cli(['--json', 'project', 'init', projectDirectory, '--name', 'demo']);
  assert.equal(initialized.status, 0);
  assert.equal(initialized.stderr, '');
  const initResult = JSON.parse(initialized.stdout);
  assert.equal(initResult.ok, true);
  assert.equal(initResult.command, 'project.init');
  assert.equal(initResult.project.name, 'demo');
  assert.equal(initResult.timeline.duration, 0);

  const shown = await cli(['project', 'show', projectDirectory, '--json']);
  assert.equal(shown.status, 0);
  assert.equal(shown.stderr, '');
  const showResult = JSON.parse(shown.stdout);
  assert.equal(showResult.project.schemaVersion, 1);
  assert.equal(showResult.timeline.tracks.length, 4);

  const validated = await cli(['project', 'validate', '--project', join(projectDirectory, 'project.json'), '--json']);
  assert.equal(validated.status, 0);
  assert.equal(validated.stderr, '');
  assert.equal(JSON.parse(validated.stdout).valid, true);
});

test('schema and capabilities are complete, compilable, and consistent', async () => {
  const schemaResult = await cli(['schema', '--json']);
  assert.equal(schemaResult.status, 0);
  assert.equal(schemaResult.stderr, '');
  const schemas = JSON.parse(schemaResult.stdout);
  for (const key of [
    'project', 'asset', 'assetOperation', 'assetPreviewRequest', 'assetPreviewResult',
    'assetAnalysisRequest', 'assetAnalysisResult', 'editOperation', 'job', 'revision',
  ]) {
    assert.ok(schemas[key], `missing ${key} schema`);
  }
  assert.match(schemas.project.$schema, /2020-12/);

  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  const validateEdit = ajv.compile(schemas.editOperation);
  assert.equal(validateEdit({
    type: 'addClip',
    trackId: 'v1',
    clip: { id: 'background', type: 'color', color: '#000000', start: 0, duration: 1 },
  }), true, ajv.errorsText(validateEdit.errors));
  assert.ok(ajv.compile(schemas.job));
  assert.ok(ajv.compile(schemas.revision));
  const assetAjv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(assetAjv);
  for (const key of [
    'asset', 'assetOperation', 'assetPreviewRequest', 'assetPreviewResult',
    'assetAnalysisRequest', 'assetAnalysisResult',
  ]) assert.ok(assetAjv.compile(schemas[key]), `could not compile ${key}`);

  const capabilitiesResult = await cli(['capabilities', '--json']);
  assert.equal(capabilitiesResult.status, 0);
  assert.equal(capabilitiesResult.stderr, '');
  const capabilities = JSON.parse(capabilitiesResult.stdout).capabilities;
  const schemaOperations = schemas.editOperation.anyOf.map((operation) => operation.properties.type.const);
  assert.deepEqual(capabilities.operations, schemaOperations);
  assert.deepEqual(capabilities.clipTypes, ['video', 'audio', 'image', 'color', 'text']);
  assert.deepEqual(capabilities.transitions, ['cut', 'xfade']);
  assert.ok(capabilities.commands.available.includes('project validate'));
  assert.ok(capabilities.commands.available.includes('edit apply'));
  assert.ok(capabilities.commands.available.includes('history list/diff/undo/redo'));
  assert.ok(capabilities.commands.available.includes('jobs list/show/wait/cancel/retry'));
  assert.ok(capabilities.commands.available.includes('asset add/list/status/probe/remove'));
  assert.ok(capabilities.commands.available.includes('asset thumbnail/sheet'));
  assert.ok(capabilities.commands.available.includes('asset analyze scenes/silence'));
  assert.deepEqual(capabilities.assets.analyses, ['scenes', 'silence']);
  assert.ok(capabilities.commandDetails['asset sheet'].options.includes('--interval SECONDS'));
  assert.ok(capabilities.commandDetails['asset analyze silence'].options.includes('--noise-db DB'));
  assert.ok(capabilities.commandDetails['edit apply'].options.includes('--dry-run'));
  assert.ok(capabilities.commands.available.includes('render'));
  assert.ok(capabilities.commands.available.includes('doctor'));
  assert.ok(capabilities.commands.available.includes('logs'));
  assert.ok(capabilities.commands.available.includes('diagnose'));
  assert.ok(capabilities.commands.available.includes('ui'));
  assert.deepEqual(capabilities.commands.planned, []);
  assert.deepEqual(Object.values(capabilities.exitCodes), [0, 1, 2, 3, 4, 5, 6]);
});

test('usage, validation, and overwrite errors use stderr and stable exit codes', async (t) => {
  const directory = await temporaryDirectory(t);
  const unknown = await cli(['not-a-command', '--json']);
  assert.equal(unknown.status, 2);
  assert.equal(unknown.stdout, '');
  assert.equal(JSON.parse(unknown.stderr).error.code, 'USAGE_ERROR');

  const malformedPath = join(directory, 'project.json');
  await writeFile(malformedPath, '{bad', 'utf8');
  const malformed = await cli(['project', 'validate', directory, '--json']);
  assert.equal(malformed.status, 3);
  assert.equal(malformed.stdout, '');
  const malformedError = JSON.parse(malformed.stderr).error;
  assert.equal(malformedError.code, 'PROJECT_PARSE_ERROR');
  assert.equal(malformedError.stage, 'project.validate');
  assert.equal(malformedError.path, malformedPath);

  await rm(malformedPath);
  assert.equal((await cli(['project', 'init', directory, '--json'])).status, 0);
  const duplicate = await cli(['project', 'init', directory, '--json']);
  assert.equal(duplicate.status, 2);
  assert.equal(duplicate.stdout, '');
  assert.equal(JSON.parse(duplicate.stderr).error.code, 'PROJECT_EXISTS');
  assert.equal((await cli(['project', 'init', directory, '--force', '--json'])).status, 0);

  const plainMissing = await cli(['project', 'show', join(directory, 'missing')]);
  assert.equal(plainMissing.status, 3);
  assert.equal(plainMissing.stdout, '');
  assert.match(plainMissing.stderr, /PROJECT_NOT_FOUND/);
});

test('semantic CLI errors preserve structured issue paths', async (t) => {
  const directory = await temporaryDirectory(t);
  const project = createDefaultProject(directory);
  project.tracks[0].clips = [
    { id: 'broken', type: 'video', assetId: 'absent', start: 0, duration: 1 },
  ];
  await writeFile(join(directory, 'project.json'), JSON.stringify(project), 'utf8');

  const result = await cli(['project', 'validate', directory, '--json']);
  assert.equal(result.status, 3);
  assert.equal(result.stdout, '');
  const error = JSON.parse(result.stderr).error;
  assert.equal(error.code, 'PROJECT_VALIDATION_ERROR');
  assert.equal(error.diagnostics.issues[0].path, '/tracks/0/clips/0/assetId');
  assert.match(error.diagnostics.issues[0].message, /does not exist/);
});

test('non-JSON success text and executable bin entry are stable', async (t) => {
  const directory = await temporaryDirectory(t);
  const result = await cli(['project', 'init', directory]);
  assert.equal(result.status, 0);
  assert.equal(result.stderr, '');
  assert.match(result.stdout, /^Initialized project: /);
  assert.equal(JSON.parse(await readFile(join(directory, 'project.json'), 'utf8')).schemaVersion, 1);

  const version = await cli(['--version']);
  assert.equal(version.status, 0);
  assert.equal(version.stdout, '0.1.0\n');
  assert.equal(version.stderr, '');
});
