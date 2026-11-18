import { BUILT_IN_CONFIG, Jobs, ServerConfig } from './jobs';
import { DebugMode } from './debug-mode';
import { DummyData } from './dummy-data';
import { TestBed } from '@angular/core/testing';
import { effect } from '@angular/core';
import { beforeEach, describe, expect, it } from 'vitest';
import { Library } from './library';
import { LibrarySetup } from './library-setup';
import { DirectoryHandle, FolderStore } from './folder-store';
import { DEFAULT_NAME_PATTERN, useNamePattern } from './naming';

const SOURCE = 'https://archiveofourown.org/users/Someone/bookmarks';

/** one file per bookmark, as ao3downloader now writes them */
function record(id: string, position: number) {
  return {
    source: SOURCE,
    retrieved: '01/01/2026, 12:00:00',
    position,
    id,
    title: `Work ${id}`,
  };
}

function recordFile(id: string, position: number): File {
  return new File([JSON.stringify(record(id, position))], `${id} Work ${id} - X.json`);
}

/** one file per collection, as the 'index collections' action writes them */
function collectionFile(name: string, title = name): File {
  return new File(
    [
      JSON.stringify({
        name,
        link: `https://archiveofourown.org/collections/${name}`,
        source: 'https://archiveofourown.org/users/Someone/collections',
        last_indexed: '2026-09-10T12:00:00+00:00',
        indexes: [
          {
            indexed_on: '2026-09-10T12:00:00+00:00',
            title,
            challenge_type: 'No Challenge',
            work_ids: ['111'],
            bookmark_ids: [],
          },
        ],
      }),
    ],
    `${name}.json`,
  );
}

function folderFiles(): File[] {
  return [recordFile('111', 1), new File(['<html></html>'], '111 Work 111 - X.html')];
}

/** Stands in for the browser file-system APIs, none of which exist in jsdom. */
class FakeFolderStore extends FolderStore {
  recalled: DirectoryHandle | null = null;
  granted: PermissionState = 'granted';
  requested = 0;
  remembered = 0;
  forgotten = 0;
  files = folderFiles();

  override supported(): boolean {
    return true;
  }
  override async pick(): Promise<DirectoryHandle> {
    return { kind: 'directory', name: 'downloads' } as DirectoryHandle;
  }
  override async recall(): Promise<DirectoryHandle | null> {
    return this.recalled;
  }
  override async remember(): Promise<void> {
    this.remembered += 1;
  }
  override async forget(): Promise<void> {
    this.forgotten += 1;
  }
  override async permission(_handle: DirectoryHandle, request: boolean): Promise<PermissionState> {
    if (request) this.requested += 1;
    return this.granted;
  }
  override async read(): Promise<File[]> {
    return this.files;
  }
  /** works/ holds the html and pdfs among `files` - the tests list a folder's files flat */
  override async readSubfolder(_handle: DirectoryHandle, name: string): Promise<File[]> {
    return name === 'works' ? this.files.filter((f) => /\.(html?|pdf|epub|mobi|azw3)$/i.test(f.name)) : [];
  }

  /** a library already set up, unless a test says otherwise */
  folders = ['indexing', 'collections', 'images', 'runs', 'works'];
  topFiles: string[] = [];
  made: string[] = [];
  moved: string[] = [];
  /** names a move is refused for, as when works/ already has one */
  refuseMove = new Set<string>();

  override async topLevel(): Promise<{ folders: string[]; files: string[] }> {
    return { folders: this.folders, files: this.topFiles };
  }
  override async makeFolder(_handle: DirectoryHandle, name: string): Promise<void> {
    this.made.push(name);
    this.folders = [...this.folders, name];
  }
  override async moveIntoSubfolder(
    _handle: DirectoryHandle,
    name: string,
    subfolder: string,
  ): Promise<boolean> {
    if (this.refuseMove.has(name)) return false;
    this.moved.push(`${subfolder}/${name}`);
    this.topFiles = this.topFiles.filter((x) => x !== name);
    return true;
  }
}

function handle(name = 'downloads'): DirectoryHandle {
  return { kind: 'directory', name } as DirectoryHandle;
}

describe('Library', () => {
  let store: FakeFolderStore;
  let library: Library;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [{ provide: FolderStore, useClass: FakeFolderStore }],
    });
    store = TestBed.inject(FolderStore) as FakeFolderStore;
    library = TestBed.inject(Library);
  });

  it('shows debug mode\'s dummy data instead of the real library, the same library for either choice', async () => {
    store.recalled = handle();
    TestBed.inject(DebugMode).set(true);
    TestBed.inject(DummyData).set(true);

    await library.showLocal();
    const local = library.data()?.works.map((w) => w.title) ?? [];
    expect(local).toContain('Pizza time!');
    expect(library.store()?.label).toContain('this computer');
    // the top bar names it, in place of a count
    expect(library.openedName()).toBe('Dummy library (this computer)');
    // an AO3 collection and a custom one
    expect(library.collections().length).toBe(2);
    // every work has a copy in at least one format
    const copied = new Set(Object.values(library.copies()).flatMap((m) => [...m.keys()]));
    expect(copied.size).toBe(local.length);
    // every one a work, so no file reads as unindexed and nothing offers to repair it
    expect(library.worksById().size).toBe(local.length);
    // the real folder was never read
    expect(local).not.toContain('Example');

    await library.showDropbox();
    const dropbox = library.data()?.works.map((w) => w.title) ?? [];
    expect(dropbox).toEqual(local);
    expect(library.store()?.label).toContain('Dropbox');

    // turned off, the real folder comes back and nothing dummy stays on screen
    TestBed.inject(DummyData).set(false);
    await library.showLocal();
    expect(library.data()?.works.length).toBe(1);
    expect(library.store()?.label ?? '').not.toContain('dummy');
    expect(library.openedName()).toBe('');
    TestBed.inject(DebugMode).set(false);
  });

  it('does nothing at startup when no folder was ever picked', async () => {
    await library.restore();

    expect(library.data()).toBeNull();
    expect(library.folderName()).toBe('');
    expect(library.needsReconnect()).toBe(false);
  });

  it('reopens the remembered folder with no clicks when permission still holds', async () => {
    store.recalled = handle();

    await library.restore();

    expect(library.folderName()).toBe('downloads');
    expect(library.needsReconnect()).toBe(false);
    expect(library.data()?.works.length).toBe(1);
    expect(library.htmlFiles().get('111')).toBeTruthy();
    // asking for permission needs a user gesture, so startup must not ask
    expect(store.requested).toBe(0);
  });

  it("maps each work's copies again when the file name pattern arrives after the library was read", async () => {
    // named the AO3 way: not a work by the default pattern the library is read with
    store.files = [recordFile('111', 1), new File(['<html></html>'], 'Work 111 - X - 111.html')];
    store.recalled = handle();
    try {
      await library.restore();
      expect(library.htmlFiles().get('111')).toBeUndefined();

      // the helper's config brings FileNamePattern: the same files, read by it, without reading again
      useNamePattern('{title} - {author} - {worknum} {date}');
      TestBed.tick();
      expect(library.htmlFiles().get('111')).toBeTruthy();
    } finally {
      useNamePattern(DEFAULT_NAME_PATTERN);
    }
  });

  it('asks to reconnect instead of loading when permission lapsed', async () => {
    store.recalled = handle();
    store.granted = 'prompt';

    await library.restore();

    expect(library.folderName()).toBe('downloads');
    expect(library.needsReconnect()).toBe(true);
    expect(library.data()).toBeNull();
    expect(store.requested).toBe(0);
  });

  it('loads once reconnect is confirmed from a click', async () => {
    store.recalled = handle();
    store.granted = 'prompt';
    await library.restore();

    store.granted = 'granted';
    await library.reconnect();

    expect(store.requested).toBe(1);
    expect(library.needsReconnect()).toBe(false);
    expect(library.data()?.works.length).toBe(1);
  });

  it('reports a declined reconnect rather than failing silently', async () => {
    store.recalled = handle();
    store.granted = 'prompt';
    await library.restore();

    await library.reconnect();

    expect(library.error()).toContain('declined');
    expect(library.data()).toBeNull();
  });

  it('remembers a newly picked folder so it comes back next time', async () => {
    await library.pickFolder();

    expect(store.remembered).toBe(1);
    expect(library.folderName()).toBe('downloads');
    expect(library.data()?.works.length).toBe(1);
  });

  it('notes when the whole library was last read, and a refresh reads it again without clearing the listing', async () => {
    await library.pickFolder();
    const first = library.lastRead();
    expect(first?.store).toBe(library.store());

    let emptied = false;
    const watching = TestBed.runInInjectionContext(() =>
      effect(() => {
        if (library.data() === null) emptied = true;
      }),
    );
    await library.refresh();
    TestBed.tick();
    watching.destroy();

    expect(emptied).toBe(false);
    expect(library.data()?.works.length).toBe(1);
    expect(library.lastRead()).not.toBe(first);
    expect(library.refreshing()).toBe(false);
    expect(library.listedAt()).not.toBeNull();

    await library.forget();
    expect(library.listedAt()).toBeNull();
  });

  it('clears everything when the folder is forgotten', async () => {
    store.recalled = handle();
    await library.restore();

    await library.forget();

    expect(store.forgotten).toBe(1);
    expect(library.folderName()).toBe('');
    expect(library.data()).toBeNull();
    expect(library.htmlFiles().size).toBe(0);
  });

  it('still accepts a plain file list for browsers without a directory picker', async () => {
    await library.load(folderFiles() as unknown as FileList);

    expect(library.data()?.works.length).toBe(1);
    expect(library.htmlFiles().get('111')).toBeTruthy();
  });

  it('takes the owner from an entry off their bookmarks, whatever was read first', async () => {
    const entry = (id: string, source?: string) => new File(
      [JSON.stringify({ ...record(id, 1), source, bookmarked: !source || source === SOURCE ? undefined : false })],
      `${id} Work ${id} - X.json`);
    // a work a collection brought in, listed ahead of your bookmark
    await library.load([entry('111', 'https://archiveofourown.org/collections/fest/works'), entry('222', SOURCE)] as unknown as FileList);
    expect(library.data()?.source).toBe(SOURCE);

    // only fics downloaded by link or number: nobody's listing
    await library.load([entry('333')] as unknown as FileList);
    expect(library.data()?.source).toBe('');
  });

  it('names a folder handed over as a file list, so the top bar shows it rather than a count', async () => {
    const inFolder = (file: File, path: string) => Object.defineProperty(file, 'webkitRelativePath', { value: path });
    await library.load([
      inFolder(recordFile('111', 1), 'My library/indexing/111.json'),
      inFolder(new File(['<html></html>'], '111 Work 111 - X.html'), 'My library/works/111 Work 111 - X.html'),
    ] as unknown as FileList);
    expect(library.openedName()).toBe('My library');

    // files with no folder path name nothing
    await library.load(folderFiles() as unknown as FileList);
    expect(library.openedName()).toBe('');
  });

  it('explains itself when the folder holds no export', async () => {
    await library.load([new File(['<html></html>'], '111 A Work - X.html')] as unknown as FileList);

    expect(library.error()).toContain('No json files in that folder');
    expect(library.data()).toBeNull();
  });

  it('rejects json that is not an export', async () => {
    await library.load([new File(['{"nope":true}'], 'something.json')] as unknown as FileList);

    expect(library.error()).toContain('none of them look like a FicFairy library');
    expect(library.data()).toBeNull();
  });

  it('reads one file per bookmark', async () => {
    // no listing order is kept any more - the works list sorts them, by when each was
    // bookmarked unless asked otherwise
    store.files = [recordFile('333', 3), recordFile('111', 1), recordFile('222', 2)];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id).sort()).toEqual(['111', '222', '333']);
    expect(library.data()?.count).toBe(3);
    expect(library.data()?.source).toBe(SOURCE);
  });

  it('reads the newest reading out of a versioned file', async () => {
    const versioned = {
      id: '111',
      link: 'https://archiveofourown.org/works/111',
      source: SOURCE,
      bookmark_type: 'individual work',
      last_indexed: '2026-09-10T12:00:00+00:00',
      indexes: [
        { indexed_on: '2026-09-01T10:00:00+00:00', title: 'Old Title', kudos: 1 },
        { indexed_on: '2026-09-10T12:00:00+00:00', title: 'New Title', kudos: 9 },
      ],
    };
    store.files = [new File([JSON.stringify(versioned)], '111 x.json')];
    store.recalled = handle();

    await library.restore();

    const work = library.data()!.works[0];
    expect(work.title).toBe('New Title');
    expect(work.id).toBe('111');
    // the root identity is not overwritten by the reading
    expect(work.bookmark_type).toBe('individual work');
    expect(library.data()!.retrieved).toBe('2026-09-10T12:00:00+00:00');
  });

  it('lists every kind of bookmark, but not a work that is only there through a series', async () => {
    // series and external works are bookmarks too; a work in the index only because a
    // bookmarked series holds it is shown inside that series' card, not on its own
    const entry = (id: string, type: string, extra: object = {}) =>
      new File(
        [JSON.stringify({ id, link: `https://x/${id}`, source: SOURCE, bookmark_type: type,
          indexes: [{ indexed_on: '2026-09-10T12:00:00+00:00', title: `Entry ${id}`, ...extra }] })],
        `${id}.json`,
      );
    store.files = [
      entry('111', 'individual work', { bookmarked: true }),
      entry('333', 'individual work', { bookmarked: false }),
      entry('15213', 'series bookmark', { work_ids: ['333'], bookmarked: true }),
      // reached only through one of your works: not a bookmark of yours
      entry('777', 'series bookmark', { work_ids: ['111'], bookmarked: false }),
      entry('1', 'external work'),
      recordFile('222', 2),
    ];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id).sort()).toEqual(['1', '111', '15213', '222']);
    // every work is still there to look up by number - which a series' card does
    expect([...library.worksById().keys()].sort()).toEqual(['111', '222', '333']);
    // every series is there to look up - a work's 'Part N of' line does - bookmarked or not
    expect([...library.seriesById().keys()].sort()).toEqual(['15213', '777']);
    expect(library.sourceName()).toBe('4 bookmarks');
  });

  it('still reads a flat file written before histories existed', async () => {
    store.files = [recordFile('111', 1)];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
  });

  it('finds records in the indexing subfolder and pairs them with works above it', async () => {
    // the exporter writes json into downloads/indexing/, while works stay in downloads/
    const nested = new File([JSON.stringify(record('111', 1))], '111 Work 111 - X.json');
    Object.defineProperty(nested, 'webkitRelativePath', {
      value: 'downloads/indexing/111 Work 111 - X.json',
    });
    store.files = [nested, new File(['<html></html>'], '111 Work 111 - X.html')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
    expect(library.htmlFiles().get('111')).toBeTruthy();
  });

  it('skips json in the folder that has nothing to do with the export', async () => {
    store.files = [recordFile('111', 1), new File(['{"some":"config"}'], 'other.json')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
  });

  // the run history is a subfolder of the downloads folder, but a folder read here arrives
  // flat - and a run record carries an `id`, which is all it takes to be rendered as a work
  it('does not mistake a run history record for a bookmark', async () => {
    const run = {
      id: '2eabed206b514d24bffc95ffda1f1bf9',
      action: 'custom',
      actionName: 'Custom run',
      started: '2026-09-13T17:56:09',
      finished: null,
      status: 'running',
      filetypes: ['JSON', 'HTML'],
      reindexed: [],
    };
    store.files = [
      recordFile('111', 1),
      new File([JSON.stringify(run)], '2026-09-13T175609-2eabed20.json'),
    ];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
  });

  it('ignores a json file that is corrupt rather than failing the whole folder', async () => {
    store.files = [recordFile('111', 1), new File(['{not json'], 'broken.json')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
    expect(library.error()).toBe('');
  });

  it('still opens an export from the older single-file version', async () => {
    const legacy = {
      source: SOURCE,
      retrieved: '01/01/2026, 12:00:00',
      count: 2,
      works: [
        { id: '111', title: 'Work 111' },
        { id: '222', title: 'Work 222' },
      ],
    };
    store.files = [new File([JSON.stringify(legacy)], 'bookmarks_09062026.json')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111', '222']);
  });

  // region collections

  it('keeps collection files out of the bookmarks listing', async () => {
    // a collection file has a versioned history too, so without telling the two apart
    // it would be flattened and shown as though it were a bookmarked work
    store.files = [recordFile('111', 1), collectionFile('yuletide')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
    expect(library.collections().map((c) => c.name)).toEqual(['yuletide']);
  });

  it('opens a folder that has collections but nothing indexed yet', async () => {
    store.files = [collectionFile('yuletide')];
    store.recalled = handle();

    await library.restore();

    expect(library.error()).toBe('');
    expect(library.data()).toBeNull();
    expect(library.collections()).toHaveLength(1);
  });

  it('reads the newest reading of a collection, keeping the identity at the root', async () => {
    store.files = [
      new File(
        [
          JSON.stringify({
            name: 'yuletide',
            link: 'https://archiveofourown.org/collections/yuletide',
            source: 'https://archiveofourown.org/users/Someone/collections',
            last_indexed: '2026-09-10T12:00:00+00:00',
            indexes: [
              { indexed_on: '2026-09-01T10:00:00+00:00', title: 'Old Name', work_ids: ['1'] },
              { indexed_on: '2026-09-10T12:00:00+00:00', title: 'Yuletide', work_ids: ['1', '2'] },
            ],
          }),
        ],
        'yuletide.json',
      ),
    ];
    store.recalled = handle();

    await library.restore();

    const collection = library.collections()[0];
    expect(collection.title).toBe('Yuletide');
    expect(collection.work_ids).toEqual(['1', '2']);
    expect(collection.name).toBe('yuletide');
  });

  it('sorts collections by title, since they have no listing order of their own', async () => {
    store.files = [collectionFile('beta', 'Beta'), collectionFile('alpha', 'Alpha')];
    store.recalled = handle();

    await library.restore();

    expect(library.collections().map((c) => c.title)).toEqual(['Alpha', 'Beta']);
  });

  it('drops remembered collections when the folder is forgotten', async () => {
    store.files = [collectionFile('yuletide')];
    store.recalled = handle();
    await library.restore();

    await library.forget();

    expect(library.collections()).toEqual([]);
  });

  // endregion

  // region setting a local folder up

  it('makes the folders a library needs in a newly picked folder, then reads it', async () => {
    store.folders = [];
    store.files = [];

    await library.pickFolder();

    expect(store.made).toEqual(['indexing', 'collections', 'images', 'runs', 'works']);
    // a folder just made into a library is an empty one, not the wrong one
    expect(library.error()).toBe('');
  });

  it('offers to move top-level works into works/ and moves only the works', async () => {
    store.topFiles = ['111 A - X.html', '222 B - Y.pdf', 'readme.txt', 'bookmarks.json'];
    const setup = TestBed.inject(LibrarySetup);

    const picking = library.pickFolder();
    await until(() => setup.state() === 'asking');
    expect(setup.looseWorks()).toBe(2);
    setup.choose(true);
    await picking;

    expect(store.moved).toEqual(['works/111 A - X.html', 'works/222 B - Y.pdf']);
    expect(store.topFiles).toEqual(['readme.txt', 'bookmarks.json']);
  });

  it('moves nothing when told to leave them', async () => {
    store.topFiles = ['111 A - X.html'];
    const setup = TestBed.inject(LibrarySetup);

    const picking = library.pickFolder();
    await until(() => setup.state() === 'asking');
    setup.choose(false);
    await picking;

    expect(store.moved).toEqual([]);
    expect(setup.state()).toBe('idle');
  });

  it('says a folder could not be set up rather than reading it half done', async () => {
    store.folders = [];
    store.makeFolder = async () => {
      throw new Error('This folder is read-only.');
    };

    await library.pickFolder();

    expect(library.error()).toContain('Could not set up downloads');
    expect(library.error()).toContain('read-only');
    expect(library.data()).toBeNull();
  });

  it('takes works only from works/ in a folder handed over as a file list', async () => {
    const inWorks = new File(['<html></html>'], '111 Work 111 - X.html');
    Object.defineProperty(inWorks, 'webkitRelativePath', { value: 'downloads/works/111 Work 111 - X.html' });
    const atTop = new File(['<html></html>'], '222 Work 222 - X.html');
    Object.defineProperty(atTop, 'webkitRelativePath', { value: 'downloads/222 Work 222 - X.html' });

    await library.load([recordFile('111', 1), recordFile('222', 2), inWorks, atTop] as unknown as FileList);

    expect(library.htmlFiles().has('111')).toBe(true);
    expect(library.htmlFiles().has('222')).toBe(false);
  });

  // endregion
});

/** wait for something the page does across a few awaits */
async function until(condition: () => boolean): Promise<void> {
  for (let i = 0; i < 50 && !condition(); i++) await new Promise((r) => setTimeout(r, 0));
  expect(condition()).toBe(true);
}

describe('Library, choosing which copy of a work to open', () => {
  let store: FakeFolderStore;
  let library: Library;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [{ provide: FolderStore, useClass: FakeFolderStore }] });
    store = TestBed.inject(FolderStore) as FakeFolderStore;
    library = TestBed.inject(Library);
  });

  function copy(name: string, modified: number): File {
    return new File(['<p>fic</p>'], name, { lastModified: modified });
  }

  it('opens the copy dated newest in its name, not the one changed last', async () => {
    store.files = [
      recordFile('111', 1),
      copy('111 Work - X 2025-06-01.html', 1000),
      // touched more recently - copied, synced - but an older version of the work
      copy('111 Work - X 2024-01-01.html', 9000),
      copy('111 Work - X.html', 9999),
    ];
    store.recalled = handle();

    await library.restore();

    expect((library.htmlFiles().get('111') as File).name).toBe('111 Work - X 2025-06-01.html');
  });

  it("finds each work's newest PDF alongside its html", async () => {
    store.files = [
      recordFile('111', 1),
      copy('111 Work - X 2025-06-01.html', 1000),
      copy('111 Work - X 2024-01-01.pdf', 9000),
      copy('111 Work - X 2025-06-01.pdf', 1000),
    ];
    store.recalled = handle();

    await library.restore();

    expect((library.pdfFiles().get('111') as File).name).toBe('111 Work - X 2025-06-01.pdf');
    expect((library.htmlFiles().get('111') as File).name).toBe('111 Work - X 2025-06-01.html');
  });

  it('finds every other format ao3 offers too, newest first by the date in its name', async () => {
    store.files = [
      recordFile('111', 1),
      copy('111 Work - X 2024-01-01.epub', 9000),
      copy('111 Work - X 2025-06-01.epub', 1000),
      copy('111 Work - X 2025-06-01.mobi', 1000),
      copy('111 Work - X 2025-06-01.azw3', 1000),
    ];
    store.recalled = handle();

    await library.restore();

    const copies = library.copies();
    expect((copies.epub.get('111') as File).name).toBe('111 Work - X 2025-06-01.epub');
    expect((copies.mobi.get('111') as File).name).toBe('111 Work - X 2025-06-01.mobi');
    expect((copies.azw3.get('111') as File).name).toBe('111 Work - X 2025-06-01.azw3');
  });

  it('falls back to the one changed last only between copies with the same date', async () => {
    store.files = [
      recordFile('111', 1),
      copy('111 Old Title - X 2025-06-01.html', 1000),
      copy('111 New Title - X 2025-06-01.html', 5000),
    ];
    store.recalled = handle();

    await library.restore();

    expect((library.htmlFiles().get('111') as File).name).toBe('111 New Title - X 2025-06-01.html');
  });
});
