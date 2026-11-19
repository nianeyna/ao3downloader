/**
 * Guest mode's stand-in for the helper.
 *
 * In guest mode `HelperConnection.call` hands every request here instead of sending it, so no
 * visitor ever reaches the owner's helper - nor AO3, FicHub or Dropbox through it. This answers
 * each the way the helper would, closely enough for the page to work as it does for its owner:
 * a config with the helper's own defaults, runs started as pretend ones (`GuestRun`) whose events
 * stream exactly as a real run's do, and the run controls - stop, pause, resume, answer.
 * Anything that would change something real is refused: settings.ini, an update, a record.
 */

import { Injectable, Injector, inject } from '@angular/core';
import { DEFAULT_NAME_PATTERN } from './naming';
import { GUEST_ACTION_NAMES, GUEST_USERNAME, GuestRun, GuestRunRequest, GuestWork } from './guest-runs';
import { HelperConnection } from './helper-connection';
import { BUILT_IN_CONFIG, JobAction, ServerConfig } from './jobs';
import { Library } from './library';
import { bookmarkTypeOf, dateStamp } from './bookmarks';

/** what a guest's helper says of itself: the built-in lists, and the helper's own defaults */
export const GUEST_CONFIG: ServerConfig = {
  ...BUILT_IN_CONFIG,
  username: '',
  settings: {
    file: '',
    extraWaitTime: 3,
    fileNamePattern: DEFAULT_NAME_PATTERN,
    fileNameLength: 100,
    fileNameExample: '1234567 The Trees Are Burning - library_of_alexandria 2026-08-23.html',
    maxRetries: 30,
    maxTimeouts: 5,
    debugLogging: false,
    consoleLogging: false,
    pausedRunTimeoutMinutes: 10,
    questionTimeoutMinutes: 30,
    guessedDateTimeoutMinutes: 1,
    nobodyHere: true,
  },
};

const RUN_PATH = /^\/api\/jobs\/([^/]+)\/([a-z-]+)$/;

@Injectable({ providedIn: 'root' })
export class GuestHelper {
  private readonly injector = inject(Injector);
  private readonly runs = new Map<string, GuestRun>();
  private counter = 0;

  constructor() {
    inject(HelperConnection).standIn = (path, init) => this.answer(path, init);
  }

  /** the run going now, if there is one - a guest's helper runs one at a time too */
  private going(): GuestRun | null {
    return [...this.runs.values()].find((run) => !run.done) ?? null;
  }

  async answer(path: string, init: RequestInit = {}): Promise<Response> {
    const method = (init.method ?? 'GET').toUpperCase();
    const route = path.split('?')[0];
    if (route === '/api/config') return json(200, GUEST_CONFIG);
    if (route === '/api/auth') return json(200, { ok: true });
    if (route === '/api/jobs' && method === 'GET') {
      const going = this.going();
      return json(200, {
        active: going ? [going.id] : [],
        jobs: going
          ? [{
              id: going.id, action: going.request.action, actionName: GUEST_ACTION_NAMES[going.request.action] ?? going.request.action,
              background: false, started: going.started, paused: going.held, step: going.current,
            }]
          : [],
      });
    }
    if (route === '/api/jobs' && method === 'POST') return this.start(init);
    if (route === '/api/runs/floors') {
      // the floors a quick scan may measure back to: the dummy library's finished scans
      const runs = (body(init)['runs'] as { action?: string; status?: string }[] | undefined) ?? [];
      return json(200, { runs: runs.filter((run) => ['bookmarks', 'quick'].includes(run.action ?? '') && run.status === 'success') });
    }
    // a pretend library's runs are not retried; nothing else here writes or names anything
    if (route === '/api/runs/retryable') return json(200, { runs: [] });
    if (route === '/api/settings-file') return json(403, { error: 'settings.ini cannot be changed in guest mode' });
    const run = RUN_PATH.exec(route);
    if (run) return this.control(run[1], run[2], init);
    return json(404, { error: 'not found' });
  }

  private start(init: RequestInit): Response {
    if (this.going()) return json(409, { error: 'A run is already in progress.', activeJob: this.going()!.id });
    const request = body(init);
    const library = this.injector.get(Library);
    const works: GuestWork[] = (library.data()?.works ?? [])
      .filter((work) => work.id && bookmarkTypeOf(work) === 'individual work')
      .map((work) => ({
        id: String(work.id),
        title: work.title,
        author: work.authors?.[0] ?? 'Anonymous',
        updated: dateStamp(work.date_updated ?? ''),
      }));
    const id = `guest-${Date.now().toString(36)}-${++this.counter}`;
    const guestRequest: GuestRunRequest = {
      action: request['action'] as JobAction,
      filetypes: (request['filetypes'] as string[]) ?? ['JSON'],
      options: (request['options'] as Record<string, unknown>) ?? {},
      url: typeof request['url'] === 'string' ? request['url'] : '',
      // a sealed login is not opened - a guest's is the made-up one the window typed
      username: typeof request['username'] === 'string' && request['username'] ? request['username'] : GUEST_USERNAME,
      ao3TimeZone: typeof request['ao3TimeZone'] === 'string' ? request['ao3TimeZone'] : '',
      works,
      collections: library.collections().map((c) => c.name ?? '').filter(Boolean),
    };
    // a collection run without its works writes only json, as the helper clamps it
    if ((guestRequest.action === 'collections' || guestRequest.action === 'collection') && !guestRequest.options['collectionWorks']) {
      guestRequest.filetypes = ['JSON'];
    }
    const playing = new GuestRun(id, guestRequest);
    this.runs.set(id, playing);
    void playing.play();
    return json(202, { jobId: id });
  }

  private control(id: string, what: string, init: RequestInit): Response {
    const run = this.runs.get(id);
    if (!run) return json(404, { error: 'no such run' });
    switch (what) {
      case 'events':
        return eventStream(run, init.signal ?? null);
      case 'answer':
        return run.reply(String(body(init)['choice'] ?? '')) ? json(200, { ok: true }) : json(409, { error: 'nothing is being asked' });
      case 'cancel':
        run.stop();
        return json(202, { ok: true });
      case 'force-stop':
        run.stop();
        return json(200, { record: null });
      case 'pause':
        run.pause();
        return json(202, { ok: true });
      case 'resume':
        run.resume();
        return json(202, { ok: true });
      case 'skip':
        run.skip();
        return json(202, { ok: true });
      default:
        // a record, a file to collect: a pretend run keeps none
        return json(404, { error: 'not found' });
    }
  }
}

/** the run's events as the helper streams them: server-sent events, ending with the run */
function eventStream(run: GuestRun, signal: AbortSignal | null): Response {
  const encoder = new TextEncoder();
  let stopListening = () => {};
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let open = true;
      const end = () => {
        if (!open) return;
        open = false;
        stopListening();
        try {
          controller.close();
        } catch {
          // already closed
        }
      };
      stopListening = run.listen(
        (event) => {
          if (open) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        },
        // after the last event has been read, as the helper ends its stream
        () => setTimeout(end, 0),
      );
      signal?.addEventListener('abort', end);
    },
    cancel() {
      stopListening();
    },
  });
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

function json(status: number, value: unknown): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

function body(init: RequestInit): Record<string, unknown> {
  try {
    const parsed = JSON.parse(typeof init.body === 'string' ? init.body : '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}
