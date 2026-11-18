import { BUILT_IN_CONFIG, Jobs, ServerConfig } from './jobs';
import { TestBed } from '@angular/core/testing';
import { DebugMode } from './debug-mode';
import { DUMMY_DATA_KEY, DummyData, dummyLibrary } from './dummy-data';
import { readRunHistory } from './library-store';
import { workIdFromFilename } from './bookmarks';
import library from './dummy-library.json';

describe('dummyLibrary', () => {
  it('is the README screenshots\' library, the same for both storage choices', async () => {
    const local = await dummyLibrary('local');
    const dropbox = await dummyLibrary('dropbox');
    expect(await local.list('', true)).toEqual(await dropbox.list('', true));
    expect(local.label).toContain('this computer');
    expect(dropbox.label).toContain('Dropbox');
    const index = await local.list('indexing');
    expect(index.length).toBe(library.works.length);
    expect(index).toContain('indexing/80000002 Pizza time! - extra_cheese_please.json');
  });

  it('holds works, an AO3 collection, a custom one and a run history that reads as a real one does', async () => {
    const store = await dummyLibrary('local');
    expect(await store.list('collections')).toContain('collections/spookyoctoberfest2026.json');
    expect((await store.list('collections/custom')).length).toBe(1);
    const runs = await readRunHistory(store);
    expect(runs.length).toBe(library.runs.length);
    expect(runs.every((run) => run.status !== 'running')).toBe(true);
  });

  it('gives each html copy its title over lorem ipsum', async () => {
    const store = await dummyLibrary('local');
    const html = (await store.list('works')).filter((p) => p.endsWith('.html'));
    expect(html.length).toBeGreaterThan(0);
    const page = (await store.read(html[0])) ?? '';
    expect(page).toContain('<h1>');
    expect(page).toContain('Lorem ipsum');
    expect(page).not.toContain('Chapter');
  });

  it('gives every work file an index entry, so nothing offers to repair it', async () => {
    const store = await dummyLibrary('dropbox');
    const indexed = new Set((await store.list('indexing')).map((p) => workIdFromFilename(p.split('/').pop()!)));
    for (const path of await store.list('works')) {
      expect(indexed.has(workIdFromFilename(path.split('/').pop()!))).toBe(true);
    }
  });

  it('names no real AO3 account', () => {
    const text = JSON.stringify(library);
    for (const name of text.match(/users\/[^/"]+/g) ?? []) expect(name).toBe('users/Example_Reader');
  });
});

describe('DummyData', () => {
  beforeEach(() => localStorage.clear());

  it('is only in force while debug mode is on', () => {
    const dummy = TestBed.inject(DummyData);
    const debug = TestBed.inject(DebugMode);
    dummy.set(true);
    expect(localStorage.getItem(DUMMY_DATA_KEY)).toBe('on');
    expect(dummy.active()).toBe(false);
    debug.set(true);
    expect(dummy.active()).toBe(true);
    debug.set(false);
  });

  it('keeps one library per choice while on, and a fresh one after being turned off', async () => {
    const dummy = TestBed.inject(DummyData);
    dummy.set(true);
    const first = await dummy.library('local');
    expect(await dummy.library('local')).toBe(first);
    dummy.set(false);
    expect(await dummy.library('local')).not.toBe(first);
    expect(localStorage.getItem(DUMMY_DATA_KEY)).toBeNull();
  });
});
