import { Injectable, signal } from '@angular/core';
import { safeGet, safeRemove, safeSet } from './storage';

/**
 * How this copy of the page reaches its helper - read from `app-config.json` beside it.
 *
 * The file is written when the page is built: a build on this computer carries the
 * defaults, and the GitHub Pages build writes it from settings.ini (`HelperUrl`,
 * `RequirePasscode`) and from the helper's public key. **Everything in it is public** -
 * anyone can fetch a published page's files - which is why it holds the passcode *flag* and
 * never the passcode, and a public key and never a private one.
 */
export interface PageConfig {
  /** where the helper answers, with no trailing slash */
  helperUrl: string;
  /** whether to ask for the passcode before doing anything */
  requirePasscode: boolean;
  /** PEM public key the ao3 login is sealed with, or '' to send it as it is */
  publicKey: string;
  /**
   * the version this page was built as - one deployment builds every copy of the page and
   * the Windows app with the same one - or '' for a build made on this computer
   */
  version: string;
  /** owner/name of the GitHub repository its releases are published on */
  releasesRepo: string;
  /**
   * the feedback Worker's https address, or '' for no feedback tab. It is not the
   * helper: feedback goes to a small serverless worker, which opens a GitHub issue, and never to the hosted helper
   */
  feedbackUrl: string;
  /** the Turnstile widget's site key - public by design, the secret half is the Worker's */
  turnstileSiteKey: string;
}

export const DEFAULT_PAGE_CONFIG: PageConfig = {
  helperUrl: 'http://127.0.0.1:4400',
  requirePasscode: false,
  publicKey: '',
  version: '',
  // where the Windows app is published. a deployment writes its own repository here; this is
  // what a page built on this computer points people at to download the app
  releasesRepo: 'alexandria-p/FicFairy',
  feedbackUrl: '',
  turnstileSiteKey: '',
};

export const PAGE_CONFIG_FILE = 'app-config.json';

const PASSCODE_KEY = 'ao3.helperPasscode';

/** what came of offering a passcode to the helper */
export type PasscodeResult = 'accepted' | 'refused' | 'blocked' | 'unreachable';

/** the helper's own limit: an address that sends this many wrong passcodes is refused for an hour */
export const PASSCODE_GUESSES = 3;

/** the start request's login, as the helper is sent it */
export type Login =
  | ({ username: string; password: string } & Record<string, unknown>)
  | { credentials: string };

/**
 * Every request the page makes to its helper goes through here.
 *
 * It adds the passcode, when there is one, and notices when the helper asks for it: a 401
 * from any request raises `passcodeWanted`, which is what puts the passcode window up. That
 * covers a passcode changed on the helper after this browser saved the old one, which the
 * page's config alone could never know about.
 */
@Injectable({ providedIn: 'root' })
export class HelperConnection {
  readonly settings = signal<PageConfig>(DEFAULT_PAGE_CONFIG);
  /** the passcode this browser holds, saved once the helper has accepted it */
  readonly passcode = signal(safeGet(PASSCODE_KEY));
  /** whether the page is waiting for a passcode before it can do anything */
  readonly passcodeWanted = signal(false);
  /** how many minutes the helper said this address is blocked for, after too many wrong passcodes */
  readonly blockedMinutes = signal(0);
  /**
   * Guest mode: a hosted copy that needs a passcode, opened by someone this browser has not
   * yet shown to hold it. Nothing reaches the helper - every request is answered by `standIn`
   * (`guest-helper.ts`) - until the passcode is accepted (`GuestMode`). See `guest.ts`.
   */
  readonly guest = signal(false);
  /** guest mode's stand-in for the helper: answers every request the page would send it */
  standIn: ((path: string, init: RequestInit) => Promise<Response>) | null = null;

  /**
   * Read `app-config.json`. Run once, before the app starts.
   *
   * A missing or unreadable file leaves the defaults - the helper on this computer, no
   * passcode - which is exactly what a page served from this computer wants. It is fetched
   * relative to the page, because a GitHub Pages copy lives under a path, not at the root.
   */
  async loadPageConfig(): Promise<void> {
    try {
      const response = await fetch(new URL(PAGE_CONFIG_FILE, document.baseURI), {
        cache: 'no-store',
      });
      if (response.ok) this.settings.set(readPageConfig(await response.json()));
    } catch {
      // no config file: the defaults stand
    }
    // a hosted copy that needs a passcode opens as a guest - even with a passcode saved here,
    // until the helper has said it is still the one (`GuestMode.checkSaved`)
    if (this.settings().requirePasscode && !this.isLocal()) this.guest.set(true);
    else if (this.settings().requirePasscode && !this.passcode()) this.passcodeWanted.set(true);
  }

  url(path: string): string {
    return this.settings().helperUrl + path;
  }

  /** whether the helper runs on this computer rather than on a server somewhere */
  isLocal(): boolean {
    try {
      const host = new URL(this.settings().helperUrl).hostname.toLowerCase();
      return (
        host === 'localhost' ||
        host === '127.0.0.1' ||
        host === '[::1]' ||
        host.endsWith('.localhost')
      );
    } catch {
      return false;
    }
  }

  private withPasscode(headers?: HeadersInit): Headers {
    const all = new Headers(headers);
    const passcode = this.passcode();
    if (passcode) all.set('Authorization', `Bearer ${passcode}`);
    return all;
  }

  /**
   * `fetch` to the helper, passcode attached. A 401 puts the passcode window up.
   *
   * **Nothing is sent while a passcode is wanted and none is held**: the helper would only
   * refuse it, and on a hosted copy every visitor to the public page would be a request to
   * the owner's helper (waking a sleeping hosted helper, too). The caller gets the 401 the
   * helper would have answered, made here, so it fails exactly as before. Only
   * `tryPasscode` reaches the helper then.
   */
  async call(path: string, init: RequestInit = {}): Promise<Response> {
    // a guest's every request is answered in the page, and none reaches the helper
    if (this.guest()) {
      if (this.standIn) return this.standIn(path, init);
      return new Response(JSON.stringify({ error: 'guest mode' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (this.settings().requirePasscode && !this.passcode()) {
      this.passcodeWanted.set(true);
      return new Response(JSON.stringify({ error: 'passcode required' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const response = await fetch(this.url(path), {
      ...init,
      headers: this.withPasscode(init.headers),
    });
    if (response.status === 401) this.passcodeWanted.set(true);
    return response;
  }

  /**
   * Offer a passcode to the helper, and keep it only if the helper takes it.
   *
   * Checked by the helper rather than here: the page is public, so anything it could check
   * against - the passcode, or a hash of it - would be readable by anyone who looked.
   */
  async tryPasscode(passcode: string): Promise<PasscodeResult> {
    let response: Response;
    try {
      response = await fetch(this.url('/api/auth'), {
        headers: { Authorization: `Bearer ${passcode}` },
        cache: 'no-store',
      });
    } catch {
      return 'unreachable';
    }
    if (response.status === 429) {
      // too many wrong passcodes from here: the helper refuses every one for a while, right or not
      let minutes = 60;
      try {
        minutes = Number((await response.json())?.retryAfterMinutes) || minutes;
      } catch {
        // the hour is the helper's own block
      }
      this.blockedMinutes.set(minutes);
      return 'blocked';
    }
    if (!response.ok) return 'refused';
    this.blockedMinutes.set(0);
    this.passcode.set(passcode);
    safeSet(PASSCODE_KEY, passcode);
    this.passcodeWanted.set(false);
    return 'accepted';
  }

  /** drop the saved passcode, and ask again if this page needs one */
  forgetPasscode(): void {
    this.passcode.set('');
    safeRemove(PASSCODE_KEY);
    // a guest is not asked: the passcode window is theirs to open
    if (this.settings().requirePasscode && !this.guest()) this.passcodeWanted.set(true);
  }

  /**
   * The ao3 login as the helper should be sent it.
   *
   * With a public key configured, the username and password are sealed with RSA-OAEP over
   * SHA-256, together with the time and a random nonce so the helper can refuse one sent
   * twice. Without one they go as they always have, to a helper on this computer.
   */
  async sealLogin(
    username: string,
    password: string,
    extra: Record<string, unknown> = {},
  ): Promise<Login> {
    const pem = this.settings().publicKey;
    if (!pem) return { username, password, ...extra };
    // the browser only offers encryption to a page on https or on this computer
    if (!globalThis.crypto?.subtle) {
      throw new Error(
        'this page cannot encrypt the login because it was not loaded over https. ' +
          'Open it at its https:// address.',
      );
    }
    const key = await crypto.subtle.importKey(
      'spki',
      pemBody(pem),
      { name: 'RSA-OAEP', hash: 'SHA-256' },
      false,
      ['encrypt'],
    );
    // anything else worth as much as the login - a background run's Dropbox sign-in - is
    // sealed inside the same blob rather than sent beside it in the clear
    const login = JSON.stringify({
      username,
      password,
      ...extra,
      sent: Date.now(),
      nonce: crypto.randomUUID(),
    });
    let sealed: ArrayBuffer;
    try {
      sealed = await crypto.subtle.encrypt(
        { name: 'RSA-OAEP' },
        key,
        new TextEncoder().encode(login),
      );
    } catch {
      // the one way this fails with a good key is a login too long for it
      throw new Error(
        'could not encrypt the login - it may be too long for the helper\'s key. ' +
          'A 4096-bit key takes a password of a few hundred characters.',
      );
    }
    return { credentials: toBase64(new Uint8Array(sealed)) };
  }

  /**
   * Follow a server-sent event stream, passcode attached. Returns a function that closes it.
   *
   * `EventSource` would be simpler, but it cannot send an Authorization header, and putting
   * the passcode in the url instead would write it into every log the request passes. So the
   * stream is read with `fetch`, and split into events here. `onClose` is called once, when
   * the stream ends or fails - never after the returned function has been called.
   */
  stream(path: string, onData: (data: string) => void, onClose: () => void): () => void {
    const controller = new AbortController();
    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      onClose();
    };

    void (async () => {
      try {
        const response = await this.call(path, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok || !response.body) throw new Error(String(response.status));
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = drainEvents(buffer, (data) => {
            if (!closed) onData(data);
          });
        }
      } catch {
        // dropped, refused or aborted - all of them end the stream
      }
      close();
    })();

    return () => {
      closed = true;
      controller.abort();
    };
  }
}

/** a config file read defensively: anything missing or the wrong type keeps its default */
export function readPageConfig(raw: unknown): PageConfig {
  const given = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const helperUrl =
    typeof given['helperUrl'] === 'string' && given['helperUrl'].trim()
      ? given['helperUrl'].trim().replace(/\/+$/, '')
      : DEFAULT_PAGE_CONFIG.helperUrl;
  return {
    helperUrl,
    requirePasscode: given['requirePasscode'] === true,
    publicKey: typeof given['publicKey'] === 'string' ? given['publicKey'].trim() : '',
    version:
      typeof given['version'] === 'string' && /^\d+\.\d+\.\d+$/.test(given['version'].trim())
        ? given['version'].trim()
        : '',
    releasesRepo:
      typeof given['releasesRepo'] === 'string' &&
      /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(given['releasesRepo'].trim())
        ? given['releasesRepo'].trim()
        : DEFAULT_PAGE_CONFIG.releasesRepo,
    ...readFeedbackConfig(given),
  };
}

/** both or neither: a form with no bot check key could never be sent, so it is not offered */
function readFeedbackConfig(given: Record<string, unknown>) {
  const url =
    typeof given['feedbackUrl'] === 'string' ? given['feedbackUrl'].trim().replace(/\/+$/, '') : '';
  const key = typeof given['turnstileSiteKey'] === 'string' ? given['turnstileSiteKey'].trim() : '';
  return url.startsWith('https://') && key
    ? { feedbackUrl: url, turnstileSiteKey: key }
    : { feedbackUrl: '', turnstileSiteKey: '' };
}

/**
 * Take every complete event off the front of `buffer`, handing each one's data on, and
 * return what is left - the start of an event still arriving.
 *
 * Events are separated by a blank line; a line starting `:` is a comment (the helper's
 * heartbeat) and carries nothing.
 */
export function drainEvents(buffer: string, onData: (data: string) => void): string {
  const normal = buffer.replace(/\r\n?/g, '\n');
  const events = normal.split('\n\n');
  const rest = events.pop() ?? '';
  for (const event of events) {
    const data = event
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).replace(/^ /, ''))
      .join('\n');
    if (data) onData(data);
  }
  return rest;
}

function pemBody(pem: string): ArrayBuffer {
  const base64 = pem
    .replace(/\\n/g, '\n')
    .replace(/-----(BEGIN|END) [^-]+-----/g, '')
    .replace(/\s+/g, '');
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function toBase64(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
