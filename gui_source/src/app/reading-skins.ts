import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { DebugMode } from './debug-mode';
import { Library } from './library';
import { LibraryStore } from './library-store';
import { breaksOutOfStyle } from './skin-html';
import { safeGet, safeRemove, safeSet } from './storage';

/**
 * Reading skins: CSS of your own, shown on every downloaded work when you open it from FicFairy -
 * the part a site skin plays on AO3, so on a work with its own work skin it goes underneath it
 * (`withAo3Shape`). Nothing is written into the work's file and AO3 is never asked for anything -
 * the skin is put in as the work is opened (`Library.openCopy`, through `shownWork`), so a new
 * default shows on every work at once. Debug mode only, for now.
 */

/** skins kept in this browser, as a list of {name, css} */
export const BROWSER_SKINS_KEY = 'ao3.readingSkins';
/** which skin to show by default, as `browser:<name>` or `library:<name>`; none when unset */
export const DEFAULT_SKIN_KEY = 'ao3.readingSkinDefault';
/** 'off' when the reading skin is left off a work with its own skin; layered under it otherwise */
export const LAYER_SKIN_KEY = 'ao3.readingSkinLayer';
/** where the library keeps skins of your own - apart from `skins/<worknum>.css`, AO3's */
export const LIBRARY_SKINS_FOLDER = 'skins/custom';
/** a skin longer than this is refused - AO3's own work skins are far shorter */
export const SKIN_MAX_CHARS = 100_000;
export const SKIN_NAME_MAX = 60;

export type SkinPlace = 'browser' | 'library';

export interface ReadingSkin {
  name: string;
  place: SkinPlace;
  css: string;
}

export function skinId(skin: Pick<ReadingSkin, 'name' | 'place'>): string {
  return `${skin.place}:${skin.name}`;
}

/** what is wrong with a skin before it is saved, or null when nothing is */
export function skinProblem(name: string, css: string): string | null {
  const shown = name.trim();
  if (!shown) return 'Give the skin a name.';
  if (shown.length > SKIN_NAME_MAX) return `Keep the name to ${SKIN_NAME_MAX} characters.`;
  // the name is the file name in the library, so it may hold nothing a file name cannot
  if (/[\\/:*?"<>|]/.test(shown) || shown.startsWith('.')) {
    return 'The name cannot hold \\ / : * ? " < > | or start with a dot.';
  }
  if (!css.trim()) return 'The skin has no CSS in it.';
  if (css.length > SKIN_MAX_CHARS) return `The skin is too long - keep it under ${SKIN_MAX_CHARS.toLocaleString()} characters.`;
  if (breaksOutOfStyle(css)) return 'The CSS cannot contain "</style".';
  return null;
}

function readBrowserSkins(): ReadingSkin[] {
  try {
    const kept = JSON.parse(safeGet(BROWSER_SKINS_KEY) || '[]');
    if (!Array.isArray(kept)) return [];
    return kept
      .filter((x) => x && typeof x.name === 'string' && typeof x.css === 'string')
      .map((x) => ({ name: x.name, css: x.css, place: 'browser' as const }));
  } catch {
    return [];
  }
}

function libraryPath(name: string): string {
  return `${LIBRARY_SKINS_FOLDER}/${name}.css`;
}

@Injectable({ providedIn: 'root' })
export class ReadingSkins {
  private readonly library = inject(Library);
  private readonly debugMode = inject(DebugMode);

  readonly browserSkins = signal<ReadingSkin[]>(readBrowserSkins());
  readonly librarySkins = signal<ReadingSkin[]>([]);
  /** the library's skins are being read */
  readonly reading = signal(false);
  /** what went wrong reading the library's skins, if anything */
  readonly readProblem = signal('');
  readonly skins = computed(() => [...this.browserSkins(), ...this.librarySkins()]);
  readonly defaultId = signal(safeGet(DEFAULT_SKIN_KEY));
  /** whether the reading skin goes under a work's own skin (the default), or is left off it */
  readonly layer = signal(safeGet(LAYER_SKIN_KEY) !== 'off');
  readonly defaultSkin = computed(() => this.skins().find((x) => skinId(x) === this.defaultId()) ?? null);
  /** whether the open library can take a skin */
  readonly libraryWritable = computed(() => !!this.library.store());

  private readGeneration = 0;

  constructor() {
    // the library's own skins, read again whenever another library is opened
    effect(() => {
      const store = this.library.store();
      void this.readLibrarySkins(store);
    });
    // what the library shows: the default skin while debug mode is on, nothing otherwise
    effect(() => {
      this.library.readingSkin.set(this.debugMode.on() ? this.defaultSkin()?.css ?? '' : '');
      this.library.layerReadingSkin.set(this.layer());
    });
  }

  async readLibrarySkins(store: LibraryStore | null = this.library.store()): Promise<void> {
    const generation = ++this.readGeneration;
    this.readProblem.set('');
    if (!store) {
      this.librarySkins.set([]);
      return;
    }
    this.reading.set(true);
    try {
      const paths = (await store.list(LIBRARY_SKINS_FOLDER, false)).filter((x) => x.toLowerCase().endsWith('.css'));
      const found: ReadingSkin[] = [];
      for (const path of paths.sort()) {
        const css = await store.read(path);
        const name = path.split('/').pop()!.replace(/\.css$/i, '');
        if (css !== null) found.push({ name, place: 'library', css });
      }
      if (generation === this.readGeneration) this.librarySkins.set(found);
    } catch (e) {
      if (generation === this.readGeneration) {
        this.librarySkins.set([]);
        this.readProblem.set(e instanceof Error ? e.message : String(e));
      }
    } finally {
      if (generation === this.readGeneration) this.reading.set(false);
    }
  }

  /** save a new skin; answers what was wrong, or null once it is saved */
  async add(name: string, css: string, place: SkinPlace): Promise<string | null> {
    const problem = skinProblem(name, css);
    if (problem) return problem;
    const shown = name.trim();
    const there = place === 'browser' ? this.browserSkins() : this.librarySkins();
    if (there.some((x) => x.name.toLowerCase() === shown.toLowerCase())) {
      return `A skin called "${shown}" is already saved ${place === 'browser' ? 'in this browser' : 'in your library'}.`;
    }
    const skin: ReadingSkin = { name: shown, place, css };
    if (place === 'browser') {
      const kept = [...this.browserSkins(), skin];
      try {
        localStorage.setItem(BROWSER_SKINS_KEY, JSON.stringify(kept.map(({ name, css }) => ({ name, css }))));
      } catch {
        return 'This browser would not keep it - its storage may be full. Try saving it to your library instead.';
      }
      this.browserSkins.set(kept);
      return null;
    }
    const store = this.library.store();
    if (!store) return 'Open a library first, to save a skin there.';
    try {
      await store.write(libraryPath(shown), new Response(css));
    } catch (e) {
      return `It could not be saved to your library: ${e instanceof Error ? e.message : String(e)}`;
    }
    this.librarySkins.set([...this.librarySkins(), skin].sort((a, b) => a.name.localeCompare(b.name)));
    return null;
  }

  /** remove a skin; answers what was wrong, or null once it is gone */
  async remove(skin: ReadingSkin): Promise<string | null> {
    if (skin.place === 'browser') {
      const kept = this.browserSkins().filter((x) => x.name !== skin.name);
      if (kept.length) safeSet(BROWSER_SKINS_KEY, JSON.stringify(kept.map(({ name, css }) => ({ name, css }))));
      else safeRemove(BROWSER_SKINS_KEY);
      this.browserSkins.set(kept);
    } else {
      const store = this.library.store();
      if (!store) return 'Open the library it is saved in first.';
      try {
        await store.delete(libraryPath(skin.name));
      } catch (e) {
        return `It could not be removed from your library: ${e instanceof Error ? e.message : String(e)}`;
      }
      this.librarySkins.set(this.librarySkins().filter((x) => x.name !== skin.name));
    }
    if (this.defaultId() === skinId(skin)) this.setDefault('');
    return null;
  }

  setLayer(on: boolean): void {
    this.layer.set(on);
    if (on) safeRemove(LAYER_SKIN_KEY);
    else safeSet(LAYER_SKIN_KEY, 'off');
  }

  setDefault(id: string): void {
    this.defaultId.set(id);
    if (id) safeSet(DEFAULT_SKIN_KEY, id);
    else safeRemove(DEFAULT_SKIN_KEY);
  }
}
