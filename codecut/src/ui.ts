import {
  createStdinDriver,
  createStdoutRenderer,
  createTerminalApp,
  installTerminalCleanup,
  type StdinDriver,
  type StdoutRenderer,
  type TerminalApp,
} from '@simon_he/vue-tui/cli';
import { TText, useTerminal, useTerminalNode } from '@simon_he/vue-tui/vue';
import {
  defineComponent,
  Fragment,
  h,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
  type VNode,
} from 'vue';
import { CodeCutError, ExitCode } from './errors.js';
import { diffRevisions, listHistory, type ProjectDiffEntry } from './history.js';
import { readJobLogs } from './diagnostics.js';
import { JobService } from './jobs.js';
import type { JobRecord } from './jobs-store.js';
import { createUiLogAdapter, type UiLogAdapter, type UiLogAdapterOptions } from './ui-log.js';

interface DashboardState {
  jobs: JobRecord[];
  selectedIndex: number;
  selectedJob: JobRecord | null;
  revisions: string;
  revisionDiff: ProjectDiffEntry[];
  message: string;
  closed: boolean;
  logMode: string;
}

export interface DashboardOptions {
  projectDirectory: string;
  jobId?: string;
  cols?: number;
  rows?: number;
  pollMs?: number;
  service?: JobService;
  logAdapter?: UiLogAdapterOptions;
}

export interface DashboardSession {
  app: TerminalApp;
  controller: DashboardController;
  logAdapter: UiLogAdapter;
  closed: Promise<void>;
  refresh(): Promise<void>;
  dispose(): void;
}

function outputPaths(job: JobRecord): string[] {
  const data = typeof job.result?.data === 'object' && job.result.data !== null
    ? job.result.data as Record<string, unknown>
    : {};
  return [...new Set([
    job.result?.outputPath,
    typeof data.outputPath === 'string' ? data.outputPath : undefined,
    job.outputPath,
  ].filter((value): value is string => typeof value === 'string' && value.length > 0))];
}

export class DashboardController {
  readonly state: DashboardState;
  readonly service: JobService;
  private timer: NodeJS.Timeout | undefined;
  private refreshing: Promise<void> | undefined;
  private refreshQueued = false;
  private disposed = false;
  private closeNotification: (() => void) | undefined;
  readonly closed: Promise<void>;

  constructor(
    private readonly options: DashboardOptions,
    private readonly logs: UiLogAdapter,
  ) {
    this.service = options.service ?? new JobService({ projectDirectory: options.projectDirectory });
    this.state = reactive<DashboardState>({
      jobs: [],
      selectedIndex: 0,
      selectedJob: null,
      revisions: 'No revisions',
      revisionDiff: [],
      message: 'Loading jobs…',
      closed: false,
      logMode: logs.mode,
    });
    this.closed = new Promise<void>((resolveClosed) => {
      this.closeNotification = resolveClosed;
    });
  }

  start(): void {
    if (this.options.pollMs && this.options.pollMs > 0 && !this.timer) {
      this.timer = setInterval(() => void this.refresh(), this.options.pollMs);
      this.timer.unref();
    }
  }

  private selectedId(): string | undefined {
    return this.state.selectedJob?.id ?? this.options.jobId;
  }

  async refresh(): Promise<void> {
    if (this.disposed) return;
    if (this.refreshing) {
      this.refreshQueued = true;
      return this.refreshing;
    }
    this.refreshing = (async () => {
      do {
        this.refreshQueued = false;
        await this.performRefresh();
      } while (this.refreshQueued && !this.disposed);
    })().finally(() => {
      this.refreshing = undefined;
    });
    return this.refreshing;
  }

  private async performRefresh(): Promise<void> {
    try {
      const previousId = this.selectedId();
      const jobs = await this.service.list();
      this.state.jobs = jobs;
      if (jobs.length === 0) {
        this.state.selectedIndex = 0;
        this.state.selectedJob = null;
        this.logs.clear();
        this.state.message = 'No jobs';
      } else {
        const selectedIndex = Math.max(0, jobs.findIndex((job) => job.id === previousId));
        this.state.selectedIndex = selectedIndex;
        const selected = jobs[selectedIndex]!;
        this.state.selectedJob = await this.service.show(selected.id);
        const result = await readJobLogs(this.service.store.projectDirectory, { jobId: selected.id, tail: this.logs.maxLines });
        this.logs.clear();
        this.logs.appendLines(result.logs.map((entry) => `[${entry.level}] ${entry.stream}: ${entry.line}`));
        this.state.message = `${jobs.length} job(s); logs retained=${this.logs.source.lineCount()}/${this.logs.maxLines}`;
      }
      try {
        const history = await listHistory(this.service.store.projectDirectory);
        const current = history.revisions.find((revision) => revision.id === history.currentId);
        this.state.revisions = current
          ? `${current.id} r${current.projectRevision}: ${current.summary}`
          : 'No revisions';
        this.state.revisionDiff = current?.parentId
          ? (await diffRevisions(this.service.store.projectDirectory, current.parentId, current.id)).diff
          : [];
      } catch {
        this.state.revisions = 'No project history';
        this.state.revisionDiff = [];
      }
    } catch (error) {
      this.state.message = error instanceof Error ? error.message : String(error);
    }
  }

  select(delta: number): void {
    if (this.state.jobs.length === 0) return;
    const count = this.state.jobs.length;
    this.state.selectedIndex = (this.state.selectedIndex + delta + count) % count;
    this.state.selectedJob = this.state.jobs[this.state.selectedIndex]!;
    void this.refresh();
  }

  async cancel(): Promise<void> {
    const id = this.state.selectedJob?.id;
    if (!id || this.disposed) return;
    await this.service.cancel(id);
    await this.refresh();
  }

  async retry(): Promise<void> {
    const id = this.state.selectedJob?.id;
    if (!id || this.disposed) return;
    const replacement = await this.service.retry(id, { detach: true });
    this.state.selectedJob = replacement;
    await this.refresh();
  }

  handleKey(key: string, ctrlKey = false): void {
    if (this.disposed) return;
    if (key === 'q' || ctrlKey && key.toLowerCase() === 'c') {
      this.close();
      return;
    }
    if (key === 'ArrowDown' || key === 'j') this.select(1);
    else if (key === 'ArrowUp' || key === 'k') this.select(-1);
    else if (key === 'c') void this.cancel().catch((error: unknown) => {
      this.state.message = error instanceof Error ? error.message : String(error);
    });
    else if (key === 'r') void this.retry().catch((error: unknown) => {
      this.state.message = error instanceof Error ? error.message : String(error);
    });
    else if (key === 'R') void this.refresh();
  }

  close(): void {
    if (this.state.closed) return;
    this.state.closed = true;
    this.closeNotification?.();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
    this.close();
  }
}

function text(x: number, y: number, value: string, w: number, hValue = 1, bold = false) {
  return h(TText, {
    key: `${x}:${y}:${value}`,
    x, y, value, w, h: hValue, wrap: false,
    ...(bold ? { style: { bold: true, fg: 'cyanBright' } } : {}),
  });
}

function createDashboardComponent(controller: DashboardController, logs: UiLogAdapter) {
  return defineComponent({
    name: 'CodeCutDashboard',
    setup() {
      const { terminal, events } = useTerminal();
      const size = ref(terminal.size());
      const node = useTerminalNode(() => ({
        rect: { x: 0, y: 0, w: size.value.cols, h: size.value.rows },
        zIndex: 10,
        focusable: true,
        handlers: {
          keydownCapture: (event) => {
            controller.handleKey(event.key, event.ctrlKey);
            event.preventDefault();
          },
        },
      }));
      const unsubscribeResize = terminal.on('resize', (next) => {
        size.value = next;
      });
      onMounted(() => {
        void nextTick(() => {
          if (node.id.value) events.value?.focus(node.id.value);
        });
      });
      watch(node.id, (id) => {
        if (id) events.value?.focus(id);
      });
      onBeforeUnmount(unsubscribeResize);

      return () => {
        const cols = size.value.cols;
        const rows = size.value.rows;
        const jobsWidth = Math.max(24, Math.min(42, Math.floor(cols * 0.36)));
        const detailX = jobsWidth + 2;
        const detailWidth = Math.max(1, cols - detailX);
        const state = controller.state;
        const selected = state.selectedJob;
        const children: VNode[] = [
          text(0, 0, 'CodeCut diagnostics  ↑/↓/j/k select  c cancel  r retry  R refresh  q quit', cols, 1, true),
          text(0, 1, 'Jobs', jobsWidth, 1, true),
          text(detailX, 1, 'Job / revisions / logs', detailWidth, 1, true),
        ];
        const jobRows = Math.max(0, rows - 3);
        state.jobs.slice(0, jobRows).forEach((job, index) => {
          const marker = index === state.selectedIndex ? '>' : ' ';
          const percent = Math.round((job.progress?.percent ?? 0) * 10) / 10;
          children.push(text(0, 2 + index, `${marker} ${job.id} ${job.status} ${job.stage} ${percent}%`, jobsWidth));
        });
        if (state.jobs.length === 0) children.push(text(0, 2, 'No jobs', jobsWidth));

        const details = selected ? [
          `Job: ${selected.id}`,
          `Kind: ${selected.kind}`,
          `Status: ${selected.status}  Health: ${selected.health ?? 'ok'}`,
          `Stage: ${selected.stage}  Progress: ${selected.progress?.percent ?? 0}%`,
          `Revision: ${selected.projectRevision}  PID: ${selected.pid ?? selected.workerPid ?? '-'}`,
          `Created: ${selected.createdAt}`,
          `Error: ${selected.error ? `${selected.error.code}: ${selected.error.message}` : '-'}`,
          `Diagnostics: ${selected.diagnostics.directory}`,
          `Filter graph: ${selected.diagnostics.filterGraph ?? '-'}`,
          `Preview/output: ${outputPaths(selected).join(', ') || '-'}`,
          `stdout: ${selected.logs.stdout}`,
          `stderr: ${selected.logs.stderr}`,
        ] : ['Select a job to inspect it'];
        details.forEach((line, index) => children.push(text(detailX, 2 + index, line, detailWidth)));
        const revisionY = 2 + details.length + 1;
        children.push(text(detailX, revisionY, `Revision: ${state.revisions}`, detailWidth, 1, true));
        const diffLines = state.revisionDiff.length === 0
          ? ['Diff: no parent diff']
          : state.revisionDiff.slice(0, 3).map((entry) => `Diff: ${entry.op} ${entry.path}`);
        diffLines.forEach((line, index) => children.push(text(detailX, revisionY + 1 + index, line, detailWidth)));
        const logY = revisionY + 2 + diffLines.length;
        children.push(text(detailX, logY, `Logs (${logs.mode})  ${state.message}`, detailWidth, 1, true));
        const logHeight = Math.max(0, rows - logY - 1);
        if (logHeight > 0 && logs.mode === 'experimental' && logs.component) {
          children.push(h(logs.component, {
            x: detailX,
            y: logY + 1,
            w: detailWidth,
            h: logHeight,
            source: logs.source,
            version: logs.version.value,
            autoFocus: false,
            autoStickToBottom: true,
            wrap: false,
            ansi: false,
            overscan: 2,
          }));
        } else if (logHeight > 0) {
          const visible = logs.lines().slice(-logHeight);
          visible.forEach((line, index) => children.push(text(detailX, logY + 1 + index, line, detailWidth)));
        }
        return h(Fragment, children);
      };
    },
  });
}

export async function createDashboardSession(options: DashboardOptions): Promise<DashboardSession> {
  const logAdapter = await createUiLogAdapter({ maxLines: 500, ...options.logAdapter });
  const controller = new DashboardController(options, logAdapter);
  const app = createTerminalApp({
    cols: options.cols ?? 100,
    rows: options.rows ?? 30,
    component: createDashboardComponent(controller, logAdapter),
  });
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    controller.dispose();
    app.dispose();
    logAdapter.dispose();
  };
  try {
    app.mount();
    app.scheduler.flushNow();
    await controller.refresh();
    app.scheduler.flushNow();
    controller.start();
  } catch (error) {
    dispose();
    throw error;
  }
  return {
    app,
    controller,
    logAdapter,
    closed: controller.closed,
    refresh: () => controller.refresh(),
    dispose,
  };
}

export interface RunTerminalUiOptions extends DashboardOptions {
  stdin?: NodeJS.ReadStream;
  stdout?: NodeJS.WriteStream;
}

export async function runTerminalUi(options: RunTerminalUiOptions): Promise<void> {
  const stdin = options.stdin ?? process.stdin;
  const stdout = options.stdout ?? process.stdout;
  if (!stdin.isTTY || !stdout.isTTY) {
    throw new CodeCutError('USAGE_ERROR', 'codecut ui requires an interactive TTY; use codecut jobs list --json and codecut logs --json instead', ExitCode.Usage, {
      stage: 'ui', retryable: false,
    });
  }
  const session = await createDashboardSession({
    ...options,
    cols: stdout.columns || 100,
    rows: stdout.rows || 30,
    pollMs: options.pollMs ?? 500,
  });
  let renderer: StdoutRenderer | undefined;
  let driver: StdinDriver | undefined;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    driver?.dispose();
    renderer?.dispose();
    session.dispose();
  };
  const cleanup = installTerminalCleanup(() => {
    session.controller.close();
    dispose();
  }, { signalPolicy: 'cleanup-only' });
  try {
    renderer = createStdoutRenderer(session.app.terminal, {
      output: stdout,
      clear: true,
      hideCursor: true,
      altScreen: true,
      trackResize: true,
    });
    renderer.render();
    driver = createStdinDriver({
      dispatch: (event) => session.app.events.dispatch(event),
      stdin,
      stdout,
      autoCleanup: false,
      onExit: () => session.controller.close(),
    });
    await session.closed;
  } finally {
    cleanup.uninstall();
    dispose();
  }
}
