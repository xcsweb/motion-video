import { ref, type Component, type Ref } from 'vue';

export interface UiLogSource {
  lineCount(): number;
  getLine(index: number): string;
  getLineKey(index: number): number;
}

export interface UiLogAdapter {
  readonly mode: 'experimental' | 'fallback';
  readonly source: UiLogSource;
  readonly version: Ref<number>;
  readonly component?: Component;
  readonly maxLines: number;
  appendLine(line: string): void;
  appendLines(lines: readonly string[]): void;
  clear(): void;
  lines(): string[];
  dispose(): void;
}

export interface UiLogAdapterOptions {
  maxLines?: number;
  loadExperimental?: () => Promise<unknown>;
}

interface ExperimentalStore {
  source: UiLogSource;
  version: Ref<number>;
  appendLine(line: string): void;
  appendLines(lines: readonly string[]): void;
  clear(): void;
}

interface ExperimentalModule {
  TLogView: Component;
  createAppendOnlyLogStore(options: { maxLines: number }): ExperimentalStore;
}

function isExperimentalModule(value: unknown): value is ExperimentalModule {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<ExperimentalModule>;
  return (typeof candidate.TLogView === 'object' || typeof candidate.TLogView === 'function')
    && typeof candidate.createAppendOnlyLogStore === 'function';
}

function validStore(value: ExperimentalStore): boolean {
  return typeof value?.source?.lineCount === 'function'
    && typeof value.source.getLine === 'function'
    && typeof value.version?.value === 'number'
    && typeof value.appendLine === 'function'
    && typeof value.appendLines === 'function'
    && typeof value.clear === 'function';
}

function fallbackAdapter(maxLines: number): UiLogAdapter {
  let retained: string[] = [];
  const version = ref(0);
  const source: UiLogSource = {
    lineCount: () => retained.length,
    getLine: (index) => retained[index] ?? '',
    getLineKey: (index) => index,
  };
  const appendLines = (lines: readonly string[]) => {
    if (lines.length === 0) return;
    retained.push(...lines);
    if (retained.length > maxLines) retained = retained.slice(-maxLines);
    version.value += 1;
  };
  return {
    mode: 'fallback',
    source,
    version,
    maxLines,
    appendLine: (line) => appendLines([line]),
    appendLines,
    clear: () => {
      retained = [];
      version.value += 1;
    },
    lines: () => [...retained],
    dispose: () => {
      retained = [];
    },
  };
}

export async function createUiLogAdapter(options: UiLogAdapterOptions = {}): Promise<UiLogAdapter> {
  const maxLines = Math.max(1, Math.floor(options.maxLines ?? 500));
  try {
    const loaded = await (options.loadExperimental ?? (() => import('@simon_he/vue-tui/experimental')))();
    if (!isExperimentalModule(loaded)) throw new TypeError('Vue TUI experimental log exports are incompatible');
    const store = loaded.createAppendOnlyLogStore({ maxLines });
    if (!validStore(store)) throw new TypeError('Vue TUI append-only log store is incompatible');
    return {
      mode: 'experimental',
      source: store.source,
      version: store.version,
      component: loaded.TLogView,
      maxLines,
      appendLine: (line) => store.appendLine(line),
      appendLines: (lines) => store.appendLines(lines),
      clear: () => store.clear(),
      lines: () => Array.from({ length: store.source.lineCount() }, (_, index) => store.source.getLine(index)),
      dispose: () => store.clear(),
    };
  } catch {
    return fallbackAdapter(maxLines);
  }
}
