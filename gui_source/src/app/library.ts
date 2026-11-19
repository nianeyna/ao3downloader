import { hasWorkSkin, shownWork } from './skin-html';
import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import {
  Bookmark,
  BookmarksExport,
  bookmarkTypeOf,
  flattenRecord,
  isBookmarkEntry,
  isListedEntry,
  isNewerCopy,
  isWorkEntry,
  ownerFromSource,
  workIdFromFilename,
} from './bookmarks';
import { Collection, flattenCollection, isCollectionRecord } from './collections';
import { APP_FOLDER_PATH, applyChanges, DropboxError, DropboxFile, DropboxSession } from './dropbox';
import { DirectoryHandle, FolderStore } from './folder-store';
import { isRunRecord } from './jobs';
import { LibrarySetup, SetupTarget, WORKS_FOLDER } from './library-setup';
import { DropboxLibraryStore, LibraryStore, LocalLibraryStore } from './library-store';
import { unzip } from './unzip';
import { DummyData, DummyKind } from './dummy-data';
import { buildTagIndex } from './tags';
import { namePatternText } from './naming';
import { CachedIndexFile, CachedListing, IndexCache } from './index-cache';
import { VisitLog } from './visit-log';

/**
 * A downloaded work that can be opened from the listing: a file already in hand for a
 * local folder, or where to fetch it from for Dropbox - fetched only when clicked, since
 * reading every work up front would mean downloading the whole library to show a list.
 */

/** how the visit log names where a Dropbox check took something from, when not Dropbox */
const CACHE = "this browser's cache";
export type LocalCopy = File | DropboxCopy;

/** a file in `works/` the listing can open, with what its name and the file itself say */
export interface WorksFile {
  name: string;
  /** when the file last changed, where that is known */
  modified: number | null;
  format: OpenableFormat;
  copy: LocalCopy;
}

export interface DropboxCopy {
  dropboxPath: string;
  modified: number;
}

/**
 * Every format ao3 offers a download in, as the listing knows its files - in the order the
 * listing shows their buttons. The title opens the html, so html has no button of its own.
 */
const OPENABLE = {
  html: /\.html?$/i,
  pdf: /\.pdf$/i,
  epub: /\.epub$/i,
  mobi: /\.mobi$/i,
  azw3: /\.azw3$/i,
} as const;
export type OpenableFormat = keyof typeof OPENABLE;
export const OPENABLE_FORMATS = Object.keys(OPENABLE) as OpenableFormat[];

/** the downloaded copies the listing can open, by work number, for each format */
export type Copies = Record<OpenableFormat, Map<string, LocalCopy>>;

export function emptyCopies(): Copies {
  return Object.fromEntries(OPENABLE_FORMATS.map((f) => [f, new Map()])) as Copies;
}

/** how a tab is told to show each format, or a saved file to be typed */
const SHOWN_AS: Record<OpenableFormat, string> = {
  html: 'text/html',
  pdf: 'application/pdf',
  epub: 'application/epub+zip',
  mobi: 'application/x-mobipocket-ebook',
  azw3: 'application/vnd.amazon.ebook',
};

/**
 * Whether a browser can show the format itself. Html and pdf open in a tab; an e-book has no
 * viewer in any browser - a tab handed one only saves it under a made-up name - so those are
 * saved, under the file's own name, for an e-reader to open.
 */
export function viewableInBrowser(format: OpenableFormat): boolean {
  return format === 'html' || format === 'pdf';
}

/** a downloaded copy's own file name, to save it under */
export function copyName(copy: LocalCopy): string {
  if (copy instanceof Blob) return (copy as File).name ?? 'work';
  return copy.dropboxPath.split('/').pop() ?? 'work';
}

/** the folders whose json is the index, read in one zip each */
const INDEX_FOLDERS = ['indexing', 'collections'];
/** how many files to fetch at once when a folder is too big to come as one zip */
const PARALLEL_DOWNLOADS = 6;
/**
 * how many changed index files in a folder are fetched one at a time rather than as the folder's
 * zip - past this, one zip of the whole folder is fewer requests and usually quicker
 */
const DOWNLOAD_EACH_UP_TO = 40;

/** the least a Try again button waits after a failed read: 3, 2, 1 - asking straight away again is what gets a library rate-limited */
export const READ_RETRY_SECONDS = 3;

/**
 * How far reading a Dropbox library has got, for the bar shown while it loads.
 *
 * Each stage says only what is known at that point. A listing comes a page at a time with no
 * total, so it counts what it has found. A folder's zip is built by Dropbox as it sends it, so
 * its size is usually unknown (`total` null) and the bar can only say how much has arrived;
 * which folder of how many is known. Entries fetched one at a time (a folder too big for one
 * zip) and entries read once downloaded both have a real total.
 */
export type ReadProgress =
  | { stage: 'listing'; found: number }
  | { stage: 'downloading'; folder: number; folders: number; bytes: number; total: number | null }
  | { stage: 'fetching'; done: number; total: number }
  | { stage: 'reading'; done: number; total: number };

type NoteProgress = (progress: ReadProgress) => void;

const count = new Intl.NumberFormat('en');

/** a size people can read: bytes, KB or MB */
export function readableSize(bytes: number): string {
  if (bytes < 1024) return `${count.format(bytes)} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * What the bar shows for a stage: a percentage only where there is a real total to divide
 * by, otherwise null - the bar then moves without claiming a number - and a caption saying
 * what is happening.
 */
export function describeReadProgress(progress: ReadProgress): {
  percent: number | null;
  caption: string;
} {
  const share = (done: number, total: number) =>
    total > 0 ? Math.min(100, Math.floor((done / total) * 100)) : 0;
  switch (progress.stage) {
    case 'listing':
      return {
        percent: null,
        caption: progress.found
          ? `Listing your library in Dropbox - ${count.format(progress.found)} files so far`
          : 'Listing your library in Dropbox...',
      };
    case 'downloading': {
      const folder = progress.folders > 1 ? ` (folder ${progress.folder} of ${progress.folders})` : '';
      const size = progress.total
        ? `${readableSize(progress.bytes)} of ${readableSize(progress.total)}`
        : `${readableSize(progress.bytes)} so far`;
      return {
        percent: progress.total ? share(progress.bytes, progress.total) : null,
        caption: `Downloading the index from Dropbox${folder} - ${size}`,
      };
    }
    case 'fetching':
      return {
        percent: share(progress.done, progress.total),
        caption: `Downloading the index from Dropbox one entry at a time - ` +
          `${count.format(progress.done)} of ${count.format(progress.total)}`,
      };
    case 'reading':
      return {
        percent: share(progress.done, progress.total),
        caption: `Reading the index - ${count.format(progress.done)} of ` +
          `${count.format(progress.total)} entries`,
      };
  }
}

/**
 * Reads a downloads folder that ao3downloader wrote into - on this computer, or in Dropbox.
 *
 * Every time a library is opened it is set up first (`LibrarySetup`): the folders it should
 * have are made, and works left in its top level are offered a move into `works/`. Works
 * are only ever looked for in `works/`, so the listing pairs a fic with the same copy a run
 * would find.
 *
 * A local folder stays in the browser - the files are read in the page, never uploaded. The
 * folder is picked once and the handle is kept, so later visits load it with no clicks. A
 * Dropbox folder is read straight from Dropbox by the page, with the session it signed in
 * for; the helper is not needed just to look.
 */
@Injectable({ providedIn: 'root' })
export class Library {
  readonly data = signal<BookmarksExport | null>(null);
  readonly collections = signal<Collection[]>([]);
  readonly sourceName = signal('');
  readonly folderName = signal('');
  /**
   * The name of a library open on this computer that is not a remembered folder - one handed
   * over as a list of files, or debug mode's dummy library - for the top bar to show in place
   * of a count. Never remembered, so it has no Forget.
   */
  readonly openedName = signal('');
  /** each work's newest downloaded copy in every format, by work number */
  readonly copies = signal<Copies>(emptyCopies());
  /**
   * Every file in `works/` in a format the listing opens, as last listed - what the Works tab
   * shows files with no index entry from (`UnindexedWorks`), whether or not their names can be
   * matched to a work.
   */
  readonly worksFiles = signal<WorksFile[]>([]);
  readonly htmlFiles = computed(() => this.copies().html);
  /** each work's newest downloaded PDF, by work number - what the listing's PDF button opens */
  readonly pdfFiles = computed(() => this.copies().pdf);
  /**
   * Every work in the index by work number - including works that are there only because a
   * series you bookmarked holds them, which the bookmarks listing leaves out. A series' card
   * and a collection both list works by number and look them up here.
   */
  readonly worksById = signal<Map<string, Bookmark>>(new Map());
  /**
   * Every series entry by series id - one you bookmarked, or one reached through a work of
   * yours - so a work's 'Part N of' line can list the rest of its series.
   */
  readonly seriesById = signal<Map<string, Bookmark>>(new Map());
  /**
   * Every external work entry by ao3's number for it - kept apart from works because the two
   * are numbered separately, so a collection's external works are never matched to a work.
   */
  readonly externalsById = signal<Map<string, Bookmark>>(new Map());
  /**
   * Every tag in the library, by kind and most-used first - what the tag filter suggests from.
   * Built from the works already in memory: once per read, and again only when the works change
   * (a run's refresh, another library), never on a keystroke.
   */
  readonly tagIndex = computed(() =>
    buildTagIndex([...this.worksById().values(), ...this.seriesById().values(), ...this.externalsById().values()]),
  );
  readonly error = signal('');
  readonly loading = signal(false);
  /** while a Dropbox library is being read, how far it has got; null otherwise */
  readonly readProgress = signal<ReadProgress | null>(null);
  /** a folder is remembered but the browser wants the permission confirmed again */
  readonly needsReconnect = signal(false);
  /**
   * The library that is open and can be written to, or null. A run reads and writes
   * through this and nothing else - the helper asks, the page does it - and the history
   * page reads the run records out of it.
   */
  readonly store = signal<LibraryStore | null>(null);
  /**
   * The reading skin to show on a work with no skin of its own as it is opened - set by
   * `ReadingSkins` (the default chosen in User settings, while debug mode is on), '' for none.
   * Never written into the file.
   */
  readonly readingSkin = signal('');
  /** whether the reading skin is layered under a work's own skin, or left off such a work */
  readonly layerReadingSkin = signal(true);

  private readonly folders = inject(FolderStore);
  private readonly dropbox = inject(DropboxSession);
  private readonly setup = inject(LibrarySetup);
  private readonly dummy = inject(DummyData);
  /** what is on screen is debug mode's dummy data, not a real library (`showDummy`) */
  private showingDummy = false;

  /** which library is on screen, so switching back to a local folder clears Dropbox's */
  private showing: 'local' | 'dropbox' | null = null;
  /**
   * Bumped every time the page switches library, local or Dropbox. Every read notes the
   * number it started under and throws its result away if it has changed by the time it
   * finishes - a large folder takes seconds to read, and a switch made meanwhile must not
   * have the old library land on top of the new one.
   */
  private generation = 0;
  /**
   * What the copies on screen were worked out from, so a change of `FileNamePattern` - or the
   * helper's config arriving after the library was read - maps them again by the new pattern
   * without reading the library again (`remapCopies`).
   */
  private copySource: (() => Copies) | null = null;
  /** the works/ files the last Dropbox check had, for `takeWorksListing` - and whether that
   * listing came from this browser's cache brought up to date, or was fetched from Dropbox */
  private worksListing: { store: LibraryStore; paths: string[]; fromCache: boolean } | null = null;
  private readonly indexCache = inject(IndexCache);
  /** where each Dropbox check took its data from - this browser's cache or Dropbox - noted for feedback.
   * Every line starts 'Dropbox check' and says, for each thing it names, which of the two it came from */
  private readonly visit = inject(VisitLog);
  private readonly patternWatch = effect(() => {
    namePatternText();
    untracked(() => this.remapCopies());
  });

  /** the copies worked out again from the files last listed, by the pattern in force now */
  private remapCopies(): void {
    if (!this.copySource) return;
    this.copies.set(this.copySource());
  }
  /**
   * Every entry the index holds, as last read - bookmarks and the works a series or a
   * collection brought in alike. Kept so a refresh after a run can swap in only what the run
   * rewrote, rather than reading the whole library again.
   */
  private entries: Bookmark[] = [];
  /**
   * The works hidden from the listing, by `hiddenKey` - kept in the library itself
   * (`HIDDEN_FILE`), so a library in Dropbox hides the same works on every device. Hiding
   * touches nothing else: the files and the index entry stay exactly as they were.
   */
  readonly hidden = signal<Map<string, HiddenWork>>(new Map());

  /** the folder on this computer being shown, to list its works/ again after a run */
  private localHandle: DirectoryHandle | null = null;

  readonly canPickFolder = this.folders.supported();

  private handle: DirectoryHandle | null = null;

  /**
   * The last time the whole library was read, and from which store - what `LibraryFreshness`
   * measures a finished run against. A run's own changes taken in by `refreshAfterRun` do
   * not count as a read: they bring in that run alone.
   */
  readonly lastRead = signal<{ store: LibraryStore; at: number } | null>(null);
  /**
   * When the list on screen was last brought up to date from the library - a full read, a
   * refresh, or a run's changes taken in as it ended (`refreshAfterRun`). Shown above the list.
   */
  readonly listedAt = signal<Date | null>(null);
  /**
   * When the library on screen is this browser's cached copy (`IndexCache`), not yet checked
   * against Dropbox: when that copy was saved, in ms - else null. Works and Collections can be
   * looked through meanwhile; runs and Resolve issues wait for the check (`App.libraryPreparing`),
   * which needs the library as it is now. A check that fails leaves it set.
   */
  readonly fromCache = signal<number | null>(null);
  /** a full read again, with the listing kept on screen meanwhile (`refresh`) */
  readonly refreshing = signal(false);
  /**
   * A read of the library failed and can be asked again (`retryRead`): how long to hold the
   * Try again button first, and whether Dropbox asked us to slow down. Never retried by itself.
   */
  readonly readFailure = signal<{ waitSeconds: number; slowDown: boolean } | null>(null);

  /** Show the folder on this computer: reopen the remembered one if it can still be read. */
  async showLocal(): Promise<void> {
    if (this.dummy.active()) return this.showDummy('local');
    this.leaveDummy();
    if (this.showing === 'dropbox') {
      // Dropbox's library, and the means of writing to it, go with it
      this.clearLibrary();
      this.store.set(null);
      this.openedName.set('');
    }
    this.showing = 'local';
    const generation = ++this.generation;
    this.notReading();
    await this.restore(generation);
  }

  /**
   * A switch of library starts from nothing being read. A read it replaces stops at its next
   * generation check without saying it is done - only the current read may - so when the new
   * library has nothing to read (no folder remembered, or permission to ask for again) the
   * page was left on 'Reading files...' for ever.
   */
  private notReading(): void {
    this.loading.set(false);
    this.readProgress.set(null);
    this.readFailure.set(null);
    // a failure belongs to the library it happened in: switching away leaves it behind
    this.error.set('');
  }

  /**
   * Read the library again after a read failed - only ever from the reader's own click (the
   * Try again button), never by itself. The failure is cleared first, and a new one shows it
   * again.
   */
  async retryRead(): Promise<void> {
    this.error.set('');
    this.readFailure.set(null);
    if (this.showingDummy) return this.showDummy(this.showing ?? 'local');
    if (this.showing === 'dropbox') await this.showDropbox(true);
    else if (this.localHandle) await this.readHandle(this.localHandle, ++this.generation);
  }

  /**
   * Show the Dropbox folder the page is signed in to.
   *
   * One recursive listing says what is there; the index then comes down as a zip per
   * folder. Works are not read at all until one is opened. A folder with nothing in it yet
   * is an empty library, not an error - a folder chosen a minute ago is exactly that.
   */
  async showDropbox(keep = false, fresh = false): Promise<void> {
    if (this.dummy.active()) return this.showDummy('dropbox');
    this.leaveDummy();
    this.showing = 'dropbox';
    const generation = ++this.generation;
    this.notReading();
    // a refresh keeps what is on screen until the new read replaces it, so the listing and its
    // filters stay put; opening the library starts from nothing
    if (!keep) this.clearLibrary();
    // the local folder is not what a run would write to now; Dropbox's replaces it once open
    this.store.set(null);
    this.error.set('');
    this.readFailure.set(null);

    const folder = this.dropbox.folder();
    if (!folder || this.dropbox.status() !== 'signed-in') {
      this.store.set(null);
      return;
    }

    this.loading.set(true);
    // a switch of library meanwhile must not have this read's progress land on the new one
    const note: NoteProgress = (progress) => {
      if (generation === this.generation) this.readProgress.set(progress);
    };
    const cacheKey = this.cacheKey(folder.path);
    try {
      const before = await this.indexCache.listing(cacheKey);
      if (generation !== this.generation) return;
      this.visit.note(
        fresh
          ? `Dropbox check: Refresh pressed - the file listing and every index file will be fetched from Dropbox; nothing is taken from ${CACHE}`
          : before
            ? `Dropbox check: ${CACHE} is from ${new Date(before.savedAt).toISOString()} - asking Dropbox what changed since`
            : `Dropbox check: nothing in ${CACHE} - the file listing and every index file will be fetched from Dropbox`,
      );
      // this browser's copy first, so the library can be looked through while Dropbox is checked;
      // a refresh already has the library on screen
      const showedCached = !keep && (await this.showCached(cacheKey, before, folder.path, generation));
      if (generation !== this.generation) return;
      if (showedCached) this.visit.note(`Dropbox check: showing the list from ${CACHE} (nothing fetched from Dropbox yet) while Dropbox is asked what changed`);
      await this.setup.prepare(this.dropboxTarget(), `Dropbox${APP_FOLDER_PATH}`);
      if (generation !== this.generation) return;
      this.store.set(new DropboxLibraryStore(this.dropbox));
      note({ stage: 'listing', found: 0 });
      // a refresh lists everything afresh; an open asks only for what changed since the copy
      const { files, cursor, fromCopy } = await this.listDropbox(folder.path, fresh ? null : before, (found) =>
        note({ stage: 'listing', found }),
      );
      if (generation !== this.generation) return;
      // files this browser kept were named by no listing this visit: what the copy says of when
      // each last changed is what Resolve issues shows for a duplicate (a listing notes its own)
      if (fromCopy) this.dropbox.noteChanged(files);

      const inside = (file: DropboxFile) =>
        file.path.slice(folder.path.length).split('/').filter(Boolean);
      const indexFiles = files.filter(
        (f) => /\.json$/i.test(f.name) && INDEX_FOLDERS.includes(inside(f)[0]?.toLowerCase()),
      );
      const copies = this.dropboxCopiesOf(files, folder.path);

      const stored = await this.indexCache.files(cacheKey);
      if (generation !== this.generation) return;
      // a fresh read takes nothing from this browser's copy: everything is downloaded again
      const cached = fresh ? new Map<string, CachedIndexFile>() : stored;
      const { read: jsonFiles, put, fetched, zipped } = await this.readDropboxIndex(folder.path, indexFiles, cached, note);
      if (generation !== this.generation) return;
      const listed = new Set(indexFiles.map((f) => f.path.toLowerCase()));
      const gone = [...stored.keys()].filter((path) => !listed.has(path));
      this.visit.note(
        // with the cache brought up to date, nothing was listed: the count is the cache's
        `Dropbox check: file listing of ${files.length} files ` +
          (fromCopy ? `from ${CACHE}, brought up to date (not fetched from Dropbox)` : 'fetched from Dropbox') +
          `; ${indexFiles.length} index files - ` +
          `${indexFiles.length - fetched} from ${CACHE}, ${fetched} fetched from Dropbox` +
          `${zipped ? ` (${zipped} folder${zipped === 1 ? '' : 's'} as a zip)` : ''}` +
          `${gone.length ? `, ${gone.length} gone from Dropbox since` : ''}`,
      );
      if (showedCached && fetched === 0 && gone.length === 0) {
        // every index file is as this browser kept it, and the copy on screen was read from those
        // very files: it is already right, so only what the listing alone says is taken in
        this.copies.set(copies);
        this.listedAt.set(new Date());
        this.visit.note(`Dropbox check: no index file changed - the list on screen, read from ${CACHE}, kept as it is`);
      } else {
        // a library emptied since the cached copy was saved must not go on showing it
        if (jsonFiles.length === 0 && this.fromCache() !== null) this.clearLibrary();
        await this.ingestRecords(jsonFiles, copies, false, note);
      }
      if (generation !== this.generation) return;
      // the listing says whether there is one, so a library with nothing hidden costs no
      // download - nor does one Dropbox says has not changed since this browser kept it
      const hiddenPath = `${folder.path}/${HIDDEN_FILE}`.toLowerCase();
      const hiddenNow = files.find((f) => f.path.toLowerCase() === hiddenPath);
      const hiddenKept = before?.files.find((f) => f.path.toLowerCase() === hiddenPath);
      let hidden: string;
      if (!fresh && hiddenNow?.hash && hiddenKept?.hash === hiddenNow.hash) {
        hidden = before!.hidden;
        this.hidden.set(readHiddenFile(hidden));
        this.visit.note(`Dropbox check: hidden-works file unchanged - from ${CACHE}, not fetched from Dropbox`);
      } else {
        hidden = await this.readHidden(generation, !!hiddenNow);
        this.visit.note(
          hiddenNow
            ? 'Dropbox check: hidden-works file fetched from Dropbox'
            : 'Dropbox check: no hidden-works file in Dropbox - nothing fetched',
        );
      }
      if (generation === this.generation && this.store()) {
        this.fromCache.set(null);
        // Resolve issues' check, which follows this read, lists works/ - this listing already has it
        const worksPrefix = `${folder.path}/${WORKS_FOLDER}/`.toLowerCase();
        this.worksListing = {
          store: this.store()!,
          paths: files
            .filter((f) => f.path.toLowerCase().startsWith(worksPrefix) && !f.path.slice(worksPrefix.length).includes('/'))
            .map((f) => f.path.slice(folder.path.length).replace(/^\/+/, '')),
          fromCache: fromCopy,
        };
        this.lastRead.set({ store: this.store()!, at: Date.now() });
        const changed = `${put.length} added or changed, ${gone.length} removed`;
        // said once the browser has answered: a full store refuses the save, and the visit log is
        // where that shows (a feedback report carries it) - nothing else notices
        void this.indexCache
          .save(cacheKey, { files, hidden, savedAt: Date.now(), ...(cursor ? { cursor } : {}) }, put, gone)
          .then((saved) =>
            this.visit.note(
              saved.kept === 'refused'
                ? `Dropbox check: done - but this browser would not save its cache (${saved.reason}; ` +
                  'perhaps its storage is full) - the next open fetches what it needs from Dropbox'
                : (fresh
                    ? `Dropbox check: done - ${CACHE} replaced with what was fetched from Dropbox`
                    : `Dropbox check: done - ${CACHE} updated with what was fetched from Dropbox (${changed})`) +
                  (saved.kept === 'memory' ? ' - kept for this visit only, as this browser has no IndexedDB' : ''),
            ),
          );
      }
    } catch (error) {
      if (generation !== this.generation) return;
      this.visit.note(
        `Dropbox check failed${this.fromCache() !== null ? ` - still showing the list from ${CACHE}` : ''}: ` +
          (error instanceof Error ? error.message : String(error)),
      );
      this.error.set(
        `Could not read ${APP_FOLDER_PATH} from Dropbox. ` +
          (error instanceof Error ? error.message : ''),
      );
      const slowDown = error instanceof DropboxError && error.status === 429;
      this.readFailure.set({
        waitSeconds: Math.max(READ_RETRY_SECONDS, slowDown ? (error.retryAfter ?? 0) : 0),
        slowDown,
      });
    } finally {
      if (generation === this.generation) {
        this.loading.set(false);
        this.readProgress.set(null);
      }
    }
  }

  /**
   * What is in the Dropbox library now, and the cursor to ask from next time. With a saved copy
   * that kept its cursor, Dropbox is asked only for what changed since (one request when nothing
   * did) and the copy's listing is brought up to date with it; otherwise - no copy, a refresh,
   * or a cursor Dropbox no longer accepts - the whole library is listed, the cursor taken first.
   */
  private async listDropbox(
    root: string,
    before: CachedListing | null,
    found: (count: number) => void,
  ): Promise<{ files: DropboxFile[]; cursor: string; fromCopy: boolean }> {
    if (before?.cursor) {
      const since = await this.dropbox.changesSince(before.cursor);
      if (since) {
        const files = applyChanges(before.files, since.changes);
        found(files.length);
        this.visit.note(
          `Dropbox check: asked Dropbox only what changed since ${CACHE} - ` +
            `${since.changes.length} change${since.changes.length === 1 ? '' : 's'}; the file listing is ${CACHE}'s, ` +
            'brought up to date, not fetched from Dropbox',
        );
        return { files, cursor: since.cursor, fromCopy: true };
      }
      this.visit.note(`Dropbox check: Dropbox no longer accepts ${CACHE}'s bookmark - the whole file listing will be fetched from Dropbox`);
    }
    let cursor = '';
    try {
      cursor = await this.dropbox.latestCursor(root);
    } catch {
      // with no cursor kept, the next open lists the whole library again - nothing worse
    }
    return { files: await this.dropbox.listLibrary(root, found), cursor, fromCopy: false };
  }

  /**
   * The contents of a downloaded work, to open it - typed as the format it is, so a tab
   * shows it rather than offering to save it. Dropbox sends every file as octet-stream.
   */
  /**
   * Show a downloaded copy in a new tab.
   *
   * A copy in Dropbox has to be fetched first. The tab is opened straight away, while the
   * click still counts as the user's - opened after the download it would be a popup, and
   * blocked - and pointed at the file once it arrives. If it cannot be fetched, the tab goes
   * to `fallback` (the work on AO3) rather than staying blank.
   */
  openCopy(copy: LocalCopy, format: OpenableFormat, fallback: string | null): void {
    const tab = window.open('', '_blank');
    const skin = format === 'html' ? this.readingSkin() : '';
    void this.readCopy(copy, format).then(
      async (read) => {
        let blob = read;
        // a work with its own skin is shaped like AO3's page around it, and one without is given
        // the reading skin - only what is shown; a file that cannot be read as text is shown as it
        // is, never not at all
        if (format === 'html') {
          blob = await read.text().then((text) => {
            if (!skin && !hasWorkSkin(text)) return read;
            return new Blob([shownWork(text, skin, this.layerReadingSkin())], { type: read.type });
          }, () => read);
        }
        const url = URL.createObjectURL(blob);
        if (tab) tab.location.href = url;
        else window.open(url, '_blank');
        // the tab keeps its own copy once loaded, so the handle can be released
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      },
      () => {
        if (tab && fallback) tab.location.href = fallback;
        else tab?.close();
      },
    );
  }

  /**
   * Open a work's downloaded html in a new tab, if this library holds one, and say whether it
   * did - so a link to the work on AO3 opens your own copy first, wherever it is shown.
   */
  openWorkCopy(id: string | null | undefined, fallback: string | null): boolean {
    const copy = id ? this.htmlFiles().get(id) : undefined;
    if (!copy) return false;
    this.openCopy(copy, 'html', fallback);
    return true;
  }

  async readCopy(copy: LocalCopy, format: OpenableFormat = 'html'): Promise<Blob> {
    const type = SHOWN_AS[format];
    if (copy instanceof Blob) return copy.type === type ? copy : new Blob([copy], { type });
    return new Blob([await this.dropbox.download(copy.dropboxPath)], { type });
  }

  /** Called at startup: reopen the remembered folder if it can still be read. */
  async restore(generation = this.generation): Promise<void> {
    const handle = await this.folders.recall();
    if (!handle || generation !== this.generation) return;

    this.handle = handle;
    this.folderName.set(handle.name);

    if ((await this.folders.permission(handle, false)) !== 'granted') {
      if (generation !== this.generation) return;
      // asking needs a click behind it, so surface a button instead - and until then this
      // folder cannot be written to, so it is no library for a run
      this.needsReconnect.set(true);
      this.store.set(null);
      return;
    }
    await this.readHandle(handle, generation);
  }

  /** Pick a folder and remember it. */
  async pickFolder(): Promise<void> {
    let handle: DirectoryHandle;
    try {
      handle = await this.folders.pick();
    } catch {
      return; // the picker was dismissed
    }
    this.handle = handle;
    this.folderName.set(handle.name);
    this.needsReconnect.set(false);
    await this.folders.remember(handle);
    await this.readHandle(handle, this.generation);
  }

  /** Confirm permission for the remembered folder, from a click. */
  async reconnect(): Promise<void> {
    if (!this.handle) return;
    if ((await this.folders.permission(this.handle, true)) !== 'granted') {
      this.error.set('Permission to read that folder was declined.');
      return;
    }
    this.needsReconnect.set(false);
    await this.readHandle(this.handle, this.generation);
  }

  async forget(): Promise<void> {
    await this.folders.forget();
    this.handle = null;
    this.folderName.set('');
    this.openedName.set('');
    this.needsReconnect.set(false);
    this.store.set(null);
    this.lastRead.set(null);
    this.clearLibrary();
  }

  /**
   * Read the library open now again, all of it, keeping the listing on screen until the new
   * read replaces it - for changes this page did not make: a background run, another device,
   * files changed by hand.
   */
  /**
   * Read the library again, keeping the listing on screen meanwhile. `fresh` - the Refresh
   * icon, pressed on purpose - downloads a Dropbox library's whole index again and replaces this
   * browser's copy of it, rather than taking from that copy what Dropbox says has not changed.
   */
  async refresh(options: { fresh?: boolean } = {}): Promise<void> {
    if (this.refreshing()) return;
    this.refreshing.set(true);
    try {
      if (this.showingDummy) await this.showDummy(this.showing ?? 'local');
      else if (this.showing === 'dropbox') await this.showDropbox(true, !!options.fresh);
      else if (this.localHandle && this.store()) await this.readHandle(this.localHandle, ++this.generation);
    } finally {
      this.refreshing.set(false);
    }
  }

  /**
   * Show debug mode's dummy library for a storage choice instead of the real one - a different
   * one for each, so it is plain which is on screen. It is read exactly as a real library is
   * (the same json and works/ files, the same `ingestRecords`), from a `MemoryStore`, so History,
   * hiding and custom collections all work on it and none of it reaches a real library.
   */
  private async showDummy(kind: DummyKind): Promise<void> {
    this.showing = kind;
    this.showingDummy = true;
    this.openedName.set(kind === 'local' ? 'Dummy library (this computer)' : '');
    const generation = ++this.generation;
    this.notReading();
    this.clearLibrary();
    this.needsReconnect.set(false);
    const store = await this.dummy.library(kind);
    if (generation !== this.generation) return;
    this.store.set(store);
    this.loading.set(true);
    try {
      const paths = await store.list('', true);
      const files = await Promise.all(
        paths.map(async (path) => {
          const name = path.split('/').pop() ?? path;
          return {
            path,
            file: new File([(await store.read(path)) ?? ''], name, {
              lastModified: (await store.modified(path)) ?? Date.now(),
            }),
          };
        }),
      );
      if (generation !== this.generation) return;
      const works = files.filter((f) => f.path.split('/')[0] === WORKS_FOLDER).map((f) => f.file);
      await this.ingestRecords(jsonOf(files.map((f) => f.file)), this.mapCopies(works), false);
      await this.readHidden(generation, paths.some((p) => p.toLowerCase() === HIDDEN_FILE));
      if (generation === this.generation) this.lastRead.set({ store, at: Date.now() });
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  /** a real library is about to be shown: nothing of the dummy one may stay on screen */
  private leaveDummy(): void {
    if (!this.showingDummy) return;
    this.showingDummy = false;
    this.openedName.set('');
    this.clearLibrary();
    this.store.set(null);
    this.lastRead.set(null);
  }

  /** What is on screen, without touching which local folder is remembered. */
  private clearLibrary(): void {
    this.data.set(null);
    this.listedAt.set(null);
    this.collections.set([]);
    this.sourceName.set('');
    this.copies.set(emptyCopies());
    this.copySource = null;
    this.worksFiles.set([]);
    this.worksListing = null;
    this.fromCache.set(null);
    this.hidden.set(new Map());
    this.entries = [];
    this.worksById.set(new Map());
    this.seriesById.set(new Map());
    this.externalsById.set(new Map());
  }

  /**
   * The index's json, read a folder at a time as a zip. A folder Dropbox will not zip -
   * more than 10,000 files, or a zip this page cannot read - is fetched file by file
   * instead, a few at a time.
   */
  /** which cached copy is this library's: the Dropbox account and the folder */
  private cacheKey(root: string): string {
    const account = (this.dropbox as { account?: () => { id: string } | null }).account?.();
    return `${account?.id ?? ''}|${root.toLowerCase()}`;
  }

  /**
   * Show this browser's cached copy of the library (`IndexCache`), if it has one, as it was
   * when it was saved - the list marked as from then, and `fromCache` set until the check against
   * Dropbox replaces it.
   */
  private async showCached(
    key: string,
    listing: CachedListing | null,
    root: string,
    generation: number,
  ): Promise<boolean> {
    if (!listing || generation !== this.generation) return false;
    const kept = await this.indexCache.files(key);
    if (kept.size === 0 || generation !== this.generation) return false;
    const json = [...kept.values()].map((f) => new File([f.text], f.path.split('/').pop() ?? f.path));
    const { works, collections } = await this.readRecords(json);
    if (generation !== this.generation || (works.length === 0 && collections.length === 0)) return false;
    this.publish(works, collections, this.dropboxCopiesOf(listing.files, root), new Date(listing.savedAt));
    this.hidden.set(readHiddenFile(listing.hidden));
    this.fromCache.set(listing.savedAt);
    return true;
  }

  /**
   * The works/ listing the last Dropbox read made, for the Resolve issues check that follows it -
   * taken once, so any later check (after a run or a rename) lists works/ afresh. Null when there
   * is none for `store`.
   */
  takeWorksListing(store: LibraryStore): { paths: string[]; fromCache: boolean } | null {
    const listing = this.worksListing;
    this.worksListing = null;
    return listing && listing.store === store ? { paths: listing.paths, fromCache: listing.fromCache } : null;
  }

  /**
   * The library's index files: those whose Dropbox hash is the one this browser kept are taken
   * from the cache, and only the rest are downloaded - a folder's worth as one zip when many
   * changed (or there is no cache), one at a time when few did. `put` is what to keep for next
   * time: every downloaded file Dropbox gave a hash.
   */
  private async readDropboxIndex(
    root: string,
    indexFiles: DropboxFile[],
    cached: Map<string, CachedIndexFile>,
    note: NoteProgress = () => {},
  ): Promise<{ read: File[]; put: CachedIndexFile[]; fetched: number; zipped: number }> {
    const read: File[] = [];
    const put: CachedIndexFile[] = [];
    let fetched = 0;
    let zipped = 0;
    const take = (source: DropboxFile, text: string) => {
      fetched++;
      read.push(new File([text], source.name));
      if (source.hash) put.push({ path: source.path, hash: source.hash, text });
    };
    const fresh: DropboxFile[] = [];
    // a file renamed or moved keeps its content, and so its hash: found by that, it is not
    // downloaded again, and is kept under its new path (the old one goes as gone)
    const byHash = new Map([...cached.values()].map((kept) => [kept.hash, kept]));
    for (const file of indexFiles) {
      const atPath = file.hash ? cached.get(file.path.toLowerCase()) : undefined;
      if (atPath && atPath.hash === file.hash) {
        read.push(new File([atPath.text], file.name));
        continue;
      }
      const moved = file.hash ? byHash.get(file.hash) : undefined;
      if (moved) {
        read.push(new File([moved.text], file.name));
        put.push({ path: file.path, hash: moved.hash, text: moved.text });
        continue;
      }
      fresh.push(file);
    }
    const folders = INDEX_FOLDERS.map((name) => {
      const prefix = `${root}/${name}/`.toLowerCase();
      return { name, wanted: fresh.filter((f) => f.path.toLowerCase().startsWith(prefix)) };
    }).filter((f) => f.wanted.length > 0);
    for (const [at, { name, wanted }] of folders.entries()) {
      // with nothing cached, the whole folder comes as one zip, as it always has
      if (cached.size > 0 && wanted.length <= DOWNLOAD_EACH_UP_TO) {
        for (const [source, text] of await this.downloadEach(wanted, note)) take(source, text);
        continue;
      }
      // what the zip brings back that was wanted, by path; anything it did not bring is fetched
      const byPath = new Map(wanted.map((f) => [f.path.toLowerCase(), f]));
      try {
        const zip = await this.dropbox.downloadZip(`${root}/${name}`, (bytes, total) =>
          note({ stage: 'downloading', folder: at + 1, folders: folders.length, bytes, total }),
        );
        zipped++;
        const decoder = new TextDecoder();
        for (const entry of await unzip(zip)) {
          if (!/\.json$/i.test(entry.path)) continue;
          const source = byPath.get(`${root}/${entry.path}`.toLowerCase());
          if (!source) continue;
          byPath.delete(source.path.toLowerCase());
          take(source, decoder.decode(entry.data));
        }
      } catch {
        // too many files for one zip, say: each is fetched instead
      }
      for (const [source, text] of await this.downloadEach([...byPath.values()], note)) take(source, text);
    }
    return { read, put, fetched, zipped };
  }

  private async downloadEach(
    files: DropboxFile[],
    note: NoteProgress = () => {},
  ): Promise<[DropboxFile, string][]> {
    const read: [DropboxFile, string][] = [];
    if (files.length === 0) return read;
    let next = 0;
    let done = 0;
    note({ stage: 'fetching', done, total: files.length });
    const worker = async () => {
      while (next < files.length) {
        const file = files[next++];
        try {
          read.push([file, await (await this.dropbox.download(file.path)).text()]);
        } catch {
          // one unreadable file should not hide the rest of the library
        }
        // counted either way: the bar is how many have been tried, not how many arrived
        note({ stage: 'fetching', done: ++done, total: files.length });
      }
    };
    await Promise.all(Array.from({ length: PARALLEL_DOWNLOADS }, worker));
    return read;
  }

  /** Fallback for browsers without a directory picker, and for loading a single json. */
  async load(fileList: FileList | null): Promise<void> {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    // the folder chosen is the first part of every file's path within it
    const parts = relativePath(files[0]).split(/[\\/]/);
    this.openedName.set(parts.length > 1 ? parts[0] : '');
    await this.ingest(files);
  }

  /**
   * Set a local folder up and read it - unless the page has switched library by the time
   * any step of that finishes, in which case nothing of it is kept.
   */
  private async readHandle(handle: DirectoryHandle, generation: number): Promise<void> {
    this.openedName.set('');
    const current = () => generation === this.generation;
    this.loading.set(true);
    this.readFailure.set(null);
    try {
      try {
        await this.setup.prepare(this.localTarget(handle), handle.name);
      } catch (error) {
        if (!current()) return;
        this.error.set(
          `Could not set up ${handle.name}. ` + (error instanceof Error ? error.message : ''),
        );
        return;
      }
      if (!current()) return;
      this.store.set(new LocalLibraryStore(handle));
      this.localHandle = handle;
      // the index can be anywhere it has ever been written, so all of it is read for json;
      // works only ever come from works/
      const everything = await this.folders.read(handle);
      const works = await this.folders.readSubfolder(handle, WORKS_FOLDER);
      if (!current()) return;
      // not strict: this folder has just been set up as a library, so an empty one is new,
      // not the wrong folder
      await this.ingestRecords(jsonOf(everything), this.mapCopies(works), false);
      await this.readHidden(generation);
      if (current() && this.store()) this.lastRead.set({ store: this.store()!, at: Date.now() });
    } catch {
      if (current()) {
        this.error.set(`Could not read ${handle.name || 'your library folder'}.`);
        this.readFailure.set({ waitSeconds: READ_RETRY_SECONDS, slowDown: false });
      }
    } finally {
      if (current()) this.loading.set(false);
    }
  }

  /**
   * A folder handed over as a list of files, by a browser with no directory picker. It
   * cannot be set up - nothing can be written back - so it is read as it is, works taken
   * from works/ where the list says where each file sat.
   */
  private async ingest(files: File[]): Promise<void> {
    const works = files.filter((f) => {
      const parts = relativePath(f).split(/[\\/]/);
      // [picked folder, works, name] - or a bare file with no path to go on
      return parts.length === 1 || parts[1]?.toLowerCase() === WORKS_FOLDER;
    });
    await this.ingestRecords(jsonOf(files), this.mapCopies(works), true);
    // nothing can be written to a folder handed over this way, but what was hidden still is
    const hidden = files.find((f) => {
      const parts = relativePath(f).split(/[\\/]/);
      return parts.length <= 2 && baseName(f).toLowerCase() === HIDDEN_FILE;
    });
    this.hidden.set(hidden ? readHiddenFile(await hidden.text()) : new Map());
  }

  private localTarget(handle: DirectoryHandle): SetupTarget {
    return {
      topLevel: () => this.folders.topLevel(handle),
      makeFolder: (name) => this.folders.makeFolder(handle, name),
      moveToWorks: async (names, progress) => {
        let moved = 0;
        const notMoved: string[] = [];
        for (const [i, name] of names.entries()) {
          try {
            if (await this.folders.moveIntoSubfolder(handle, name, WORKS_FOLDER)) moved++;
            else notMoved.push(name);
          } catch {
            notMoved.push(name);
          }
          progress(i + 1);
        }
        return { moved, notMoved };
      },
    };
  }

  private dropboxTarget(): SetupTarget {
    return {
      topLevel: () => this.dropbox.topLevel(),
      makeFolder: (name) => this.dropbox.makeFolder(name),
      moveToWorks: (names, progress) => this.dropbox.moveInto(WORKS_FOLDER, names, progress),
    };
  }

  /**
   * Turn the index's json into the listing. `strict` is for a folder the user pointed at
   * by hand, where finding no index at all most likely means the wrong folder was picked;
   * a Dropbox folder chosen for this app and not yet run into is simply empty.
   */
  private async ingestRecords(
    jsonFiles: File[],
    copies: Copies,
    strict: boolean,
    note?: NoteProgress,
  ): Promise<void> {
    this.error.set('');
    this.loading.set(true);
    try {
      if (jsonFiles.length === 0 && !strict) return;
      if (jsonFiles.length === 0) {
        this.error.set(
          'No json files in that folder. Pick the folder your library lives in - the one ' +
            'holding the indexing and works folders.',
        );
        return;
      }

      const { works, collections } = await this.readRecords(jsonFiles, note);
      if (works.length === 0 && collections.length === 0) {
        if (!strict) return;
        this.error.set(
          `Found ${jsonFiles.length} json file(s) in there, but none of them look like a ` +
            'FicFairy library.',
        );
        return;
      }

      this.publish(works, collections, copies);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Bring the listing up to date with what a run just wrote, without reading the whole
   * library again - which, for a large library in Dropbox, is minutes.
   *
   * `changed` is every path the run wrote, deleted or renamed (the page made each of those
   * changes for it, so it knows them all). The index files among them are read again and
   * swapped in for the entries and collections they hold; works/ is listed again if anything
   * in it changed, since a download can replace or rename an older copy. Everything else is
   * kept as it was. An index file the run deleted leaves its entry until the library is next
   * opened - runs do not delete index entries, so that is only ever a file removed by hand.
   */
  async refreshAfterRun(changed: Iterable<string>, store: LibraryStore | null = this.store()): Promise<void> {
    // the run's library is not the one on screen any more: nothing here to bring up to date
    if (!store || store !== this.store()) return;
    const generation = this.generation;
    const paths = [...new Set(changed)].map((p) => p.replace(/^\/+/, ''));
    const top = (path: string) => path.split('/')[0]?.toLowerCase() ?? '';
    const indexPaths = paths.filter((p) => /\.json$/i.test(p) && INDEX_FOLDERS.includes(top(p)));
    const worksChanged = paths.some((p) => top(p) === WORKS_FOLDER);
    if (!indexPaths.length && !worksChanged) return;

    try {
      const read = await Promise.all(
        indexPaths.map(async (path) => {
          const text = await store.read(path).catch(() => null);
          return text === null ? null : new File([text], path.split('/').pop() ?? path);
        }),
      );
      const { works, collections } = await this.readRecords(read.filter((f): f is File => !!f));
      const copies = worksChanged ? await this.listCopies() : this.copies();
      if (generation !== this.generation || store !== this.store()) return;

      const key = (entry: Bookmark) => `${bookmarkTypeOf(entry)}:${entry.id}`;
      const fresh = new Map(works.filter((w) => w.id).map((w) => [key(w), w]));
      const merged = this.entries.map((entry) => (entry.id && fresh.get(key(entry))) || entry);
      const known = new Set(this.entries.filter((e) => e.id).map(key));
      merged.push(...works.filter((w) => !w.id || !known.has(key(w))));

      const freshCollections = new Map(collections.map((c) => [c.name, c]));
      const keptCollections = this.collections().filter((c) => !freshCollections.has(c.name));
      this.publish(merged, [...keptCollections, ...collections], copies ?? this.copies());
    } catch {
      // the listing stays as it was: still right about everything but what the run changed,
      // and the next time the library is opened reads it all again
    }
  }

  /**
   * Hide works from the listing - one, or every one ticked - in a single write. Their files and
   * index entries are left as they are; one already hidden keeps when it was hidden.
   */
  async hide(given: Bookmark | Bookmark[]): Promise<void> {
    const works = (Array.isArray(given) ? given : [given]).filter((w) => w.id);
    const next = new Map(this.hidden());
    const now = new Date().toISOString();
    for (const work of works) {
      if (next.has(hiddenKey(work))) continue;
      next.set(hiddenKey(work), {
        key: hiddenKey(work),
        id: work.id!,
        kind: bookmarkTypeOf(work),
        title: work.title ?? '',
        authors: work.authors ?? [],
        hidden_on: now,
      });
    }
    if (next.size !== this.hidden().size) await this.saveHidden(next);
  }

  /** Show works in the listing again - one, or every one ticked - in a single write. */
  async unhide(given: Bookmark | Bookmark[]): Promise<void> {
    const next = new Map(this.hidden());
    for (const work of Array.isArray(given) ? given : [given]) next.delete(hiddenKey(work));
    if (next.size !== this.hidden().size) await this.saveHidden(next);
  }

  /**
   * Mark entries as your bookmarks, or not - by hand, from the Works tab: works, external works
   * and series. Each one's index file gets a new reading saying `bookmarked` true or false and
   * nothing else changed, so its notes, tags and date bookmarked are kept whichever way it goes
   * (the listing only stops showing them while it is not a bookmark). A later walk of your AO3
   * bookmarks writes what AO3 says over it, as it does over any reading. The listing takes the
   * files in again (`refreshAfterRun`) once they are written. Answers how many changed.
   */
  /**
   * An entry's index file as it is in the library - every reading it has had, its history - or
   * null when it has none. Found by number in its own folder, as Mark as bookmark finds it.
   */
  async indexText(entry: Bookmark): Promise<string | null> {
    const store = this.store();
    if (!store || !entry.id || entry.placeholder || entry.unindexed) return null;
    const folder = indexFolderOf(entry);
    const path = await entryFile(store, await store.list(folder, false).catch(() => []), entry.id);
    return path ? store.read(path) : null;
  }

  async setBookmarked(given: Bookmark | Bookmark[], bookmarked: boolean): Promise<number> {
    const store = this.store();
    if (!store) throw new Error('this library can only be read, so nothing can be marked in it');
    const entries = (Array.isArray(given) ? given : [given]).filter(
      (entry) => entry.id && !entry.placeholder && (entry.bookmarked === true) !== bookmarked,
    );
    const listed = new Map<string, string[]>();
    const written: string[] = [];
    const missing: string[] = [];
    const now = new Date().toISOString();
    for (const entry of entries) {
      const folder = indexFolderOf(entry);
      if (!listed.has(folder)) listed.set(folder, await store.list(folder, false).catch(() => []));
      const path = await entryFile(store, listed.get(folder)!, entry.id!);
      const text = path ? await store.read(path) : null;
      const document = text ? (JSON.parse(text) as Record<string, unknown>) : null;
      if (!path || !document || typeof document !== 'object') {
        missing.push(entry.title || entry.id!);
        continue;
      }
      await store.write(path, new Response(JSON.stringify(markedBookmarked(document, bookmarked, now), null, 2) + '\n'));
      written.push(path);
    }
    if (written.length) await this.refreshAfterRun(written, store);
    if (missing.length) {
      throw new Error(`no index file was found for ${missing.join(', ')}` +
        (written.length ? ` - the other ${written.length} were changed` : ''));
    }
    return written.length;
  }

  /** shown at once and written to the library; if the write fails the change is undone */
  private async saveHidden(next: Map<string, HiddenWork>): Promise<void> {
    const store = this.store();
    if (!store) throw new Error('this library can only be read, so nothing can be hidden in it');
    const before = this.hidden();
    this.hidden.set(next);
    try {
      const document = { hidden: [...next.values()] };
      await store.write(HIDDEN_FILE, new Response(JSON.stringify(document, null, 2) + '\n'));
    } catch (error) {
      this.hidden.set(before);
      throw error;
    }
  }

  /** the hidden-works file read and taken in - its text, '' when there is none */
  private async readHidden(generation: number, exists = true): Promise<string> {
    const store = this.store();
    if (!store || !exists) {
      this.hidden.set(new Map());
      return '';
    }
    try {
      const text = (await store.read(HIDDEN_FILE)) ?? '';
      if (generation === this.generation) this.hidden.set(readHiddenFile(text));
      return text;
    } catch {
      // unreadable: nothing is hidden, and the next hide writes a good file
      if (generation === this.generation) this.hidden.set(new Map());
      return '';
    }
  }

  /** works/ listed again, for the copies a run downloaded, replaced or renamed */
  private async listCopies(): Promise<Copies | null> {
    if (this.showing === 'dropbox') {
      const folder = this.dropbox.folder();
      if (!folder) return null;
      return this.dropboxCopiesOf(await this.dropbox.listFiles(`${folder.path}/${WORKS_FOLDER}`, true), folder.path);
    }
    if (!this.localHandle) return null;
    return this.mapCopies(await this.folders.readSubfolder(this.localHandle, WORKS_FOLDER));
  }

  /** Show `works` and `collections` as the library, with `copies` as its downloaded files. */
  private publish(works: Bookmark[], collections: Collection[], copies: Copies, listedAt = new Date()): void {
    this.entries = works;
    this.listedAt.set(listedAt);
    // no listing order is kept: the works list sorts by when each was bookmarked
    collections.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
    this.collections.set(collections);
    this.copies.set(copies);
    const byId = new Map<string, Bookmark>();
    const seriesById = new Map<string, Bookmark>();
    const externalsById = new Map<string, Bookmark>();
    for (const entry of works) {
      if (!entry.id) continue;
      if (isWorkEntry(entry)) byId.set(entry.id, entry);
      else if (entry.bookmark_type === 'series bookmark') seriesById.set(entry.id, entry);
      else if (entry.bookmark_type === 'external work') externalsById.set(entry.id, entry);
    }
    this.worksById.set(byId);
    this.seriesById.set(seriesById);
    this.externalsById.set(externalsById);

    // the listing is your bookmarks, and every other work in the index marked with where it
    // came from - but not a work that is only here because a series holds it (that is in its
    // card), nor a series you did not bookmark
    const inBookmarkedSeries = new Set(
      [...seriesById.values()].filter(isBookmarkEntry).flatMap((series) => series.work_ids ?? []),
    );
    const bookmarks = works.filter((entry) => isListedEntry(entry, inBookmarkedSeries));
    if (bookmarks.length === 0) {
      // collections synced but nothing indexed yet: the collections page still works
      this.data.set(null);
      this.sourceName.set(`${collections.length} collections`);
      return;
    }

    this.data.set({
      // the listing is someone's only when an entry came off their bookmarks: a fic run's entry
      // has no source, and a series' or a collection's names no user. Of those that do, the one
      // indexed last - so with more than one account scanned, it is the one scanned last
      source: lastScannedSource(works),
      // the newest time any entry was indexed - so a run whose changes are taken into the list
      // as it ends moves it on. newer files record when they were last checked; older ones a
      // single retrieval
      retrieved: newestIndexed(works) ?? works.find((w) => w.retrieved)?.retrieved ?? '',
      count: bookmarks.length,
      works: bookmarks,
    });
    this.sourceName.set(`${bookmarks.length} bookmarks`);
  }

  /**
   * Each json file is one bookmark or one collection. A file holding a `works` array is
   * read as well, so an export from the older single-file version of this still opens.
   *
   * The two kinds are told apart by shape rather than by which folder they came from: a
   * folder read through the file system access api arrives flat, with the paths gone.
   */
  private async readRecords(
    jsonFiles: File[],
    note?: NoteProgress,
  ): Promise<{ works: Bookmark[]; collections: Collection[] }> {
    let done = 0;
    note?.({ stage: 'reading', done, total: jsonFiles.length });
    const parsed = await Promise.all(
      jsonFiles.map(async (file) => {
        try {
          return JSON.parse(await file.text()) as unknown;
        } catch {
          return null; // a folder can hold json that has nothing to do with us
        } finally {
          note?.({ stage: 'reading', done: ++done, total: jsonFiles.length });
        }
      }),
    );

    const works: Bookmark[] = [];
    const collections: Collection[] = [];
    for (const entry of parsed) {
      if (!entry || typeof entry !== 'object') continue;

      // the run history lives in a subfolder of the downloads folder, and a folder read
      // here arrives flat - so a run record has to be recognised by shape and passed over,
      // or it is rendered as a bookmark on the strength of carrying an id
      if (isRunRecord(entry)) continue;

      // checked before the works array, since a collection also holds a list of works
      if (isCollectionRecord(entry)) {
        const collection = flattenCollection(entry);
        if (collection) collections.push(collection);
        continue;
      }

      const aggregate = entry as BookmarksExport;
      if (Array.isArray(aggregate.works)) {
        works.push(...aggregate.works);
        continue;
      }
      const record = flattenRecord(entry);
      if (record) works.push(record);
    }
    return { works, collections };
  }

  /** each work's newest copy in every format, from the files in works/ */
  private mapCopies(files: File[]): Copies {
    this.worksFiles.set(files.filter((f) => openableFormat(baseName(f))).map((f) => ({
      name: baseName(f), modified: f.lastModified || null, format: openableFormat(baseName(f))!, copy: f,
    })));
    this.copySource = () => this.mapFileCopies(files);
    return this.mapFileCopies(files);
  }

  private dropboxCopiesOf(files: DropboxFile[], root: string): Copies {
    this.worksFiles.set(files.filter((f) => {
      const inside = f.path.slice(root.length).split('/').filter(Boolean);
      return inside[0]?.toLowerCase() === WORKS_FOLDER && openableFormat(f.name);
    }).map((f) => ({
      name: f.name, modified: f.modified || null, format: openableFormat(f.name)!,
      copy: { dropboxPath: f.path, modified: f.modified },
    })));
    this.copySource = () => dropboxCopies(files, root);
    return dropboxCopies(files, root);
  }

  private mapFileCopies(files: File[]): Copies {
    const copies = emptyCopies();
    for (const file of files) {
      const format = openableFormat(baseName(file));
      if (!format) continue;
      const id = workIdFromFilename(baseName(file));
      if (!id) continue;
      const map = copies[format];
      const existing = map.get(id) as File | undefined;
      // the newest version by the date in its name, as a run would judge it - not whichever
      // file was touched last, which a copy or a sync tool can change
      if (!existing || isNewerCopy(baseName(file), file.lastModified,
          { name: baseName(existing), modified: existing.lastModified })) {
        map.set(id, file);
      }
    }
    return copies;
  }
}

/** which of the formats the listing opens a file is, if any */
function openableFormat(name: string): OpenableFormat | null {
  for (const format of Object.keys(OPENABLE) as OpenableFormat[]) {
    if (OPENABLE[format].test(name)) return format;
  }
  return null;
}

function relativePath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

function baseName(file: File): string {
  return relativePath(file).split(/[\\/]/).pop() ?? file.name;
}

function jsonOf(files: File[]): File[] {
  return files.filter((f) => /\.json$/i.test(baseName(f)));
}

/**
 * Each work's newest copy in every format, from a Dropbox listing - works/ and nowhere else,
 * the same place a run looks, and newest by the date in its name, as a run would judge it.
 */
function dropboxCopies(files: DropboxFile[], root: string): Copies {
  const copies = emptyCopies();
  for (const file of files) {
    const format = openableFormat(file.name);
    if (!format) continue;
    const inside = file.path.slice(root.length).split('/').filter(Boolean);
    if (inside[0]?.toLowerCase() !== WORKS_FOLDER) continue;
    const id = workIdFromFilename(file.name);
    if (!id) continue;
    const map = copies[format];
    const existing = map.get(id) as DropboxCopy | undefined;
    if (!existing || isNewerCopy(file.name, file.modified,
        { name: existing.dropboxPath, modified: existing.modified })) {
      map.set(id, { dropboxPath: file.path, modified: file.modified });
    }
  }
  return copies;
}

/**
 * The page's list of hidden works, at the top of the library. The helper never reads it - a run
 * only looks for files named for a work - and setting up a library only moves loose works, so
 * nothing else touches it.
 */
export const HIDDEN_FILE = 'hidden-works.json';

/** one hidden work, with enough said about it to recognise it in the file by hand */
export interface HiddenWork {
  key: string;
  id: string;
  kind: string;
  title: string;
  authors: string[];
  hidden_on: string;
}

/** the folder an entry's index file is in, by what the entry is */
function indexFolderOf(entry: Bookmark): string {
  switch (bookmarkTypeOf(entry)) {
    case 'series bookmark':
      return 'indexing/series';
    case 'external work':
      return 'indexing/external';
    default:
      return 'indexing';
  }
}

/**
 * The index file of an entry, by the number its file name starts with - as the helper finds
 * one (`Ao3.entry_path`), never by the name it would be given now. Where an older version left
 * two files for one number, the most recently indexed is the entry, as the helper chooses.
 */
async function entryFile(store: LibraryStore, paths: string[], id: string): Promise<string | null> {
  const found = paths.filter((path) => {
    const name = path.split('/').pop() ?? '';
    return /\.json$/i.test(name) && name.match(/^(\d+)/)?.[1] === id;
  });
  if (found.length < 2) return found[0] ?? null;
  let newest: { path: string; at: string } | null = null;
  for (const path of found) {
    const text = await store.read(path).catch(() => null);
    const at = String((text && (JSON.parse(text) as Record<string, unknown>)['last_indexed']) || '');
    if (!newest || at > newest.at) newest = { path, at };
  }
  return newest?.path ?? found[0];
}

/**
 * An index file with a new reading that says `bookmarked` is now `bookmarked`, and changes
 * nothing else - the bookmark's notes, tags and date carry on in it. A file from before the
 * history existed is flat, and has the field set where it is.
 */
export function markedBookmarked(
  document: Record<string, unknown>,
  bookmarked: boolean,
  now: string,
): Record<string, unknown> {
  const readings = document['indexes'];
  if (!Array.isArray(readings) || !readings.length) return { ...document, bookmarked };
  const latest = readings[readings.length - 1] as Record<string, unknown>;
  return {
    ...document,
    // a file that also says it at its top (an older one, the made-up library) is read that way
    // first (`flattenRecord`), so it is changed there too
    ...('bookmarked' in document ? { bookmarked } : {}),
    last_indexed: now,
    indexes: [...readings, { ...latest, indexed_on: now, bookmarked }],
  };
}

/** a work and an external work can share a number, so the kind is part of the key */
export function hiddenKey(work: Bookmark): string {
  return `${bookmarkTypeOf(work)}:${work.id}`;
}

function readHiddenFile(text: string): Map<string, HiddenWork> {
  try {
    const parsed = JSON.parse(text) as { hidden?: unknown };
    const list = Array.isArray(parsed?.hidden) ? (parsed.hidden as HiddenWork[]) : [];
    return new Map(list.filter((h) => h && typeof h.key === 'string').map((h) => [h.key, h]));
  } catch {
    return new Map();
  }
}

/** the bookmarks listing of the account scanned last: the source naming a user on the entry indexed latest */
function lastScannedSource(works: Bookmark[]): string {
  const owned = works.filter((w) => ownerFromSource(w.source ?? ''));
  const latest = newestIndexed(owned);
  return (latest !== undefined ? owned.find((w) => w.last_indexed === latest) : owned[0])?.source ?? '';
}

/** the latest `last_indexed` among the entries, as written - the first that will not parse is never preferred */
function newestIndexed(works: Bookmark[]): string | undefined {
  let newest: string | undefined;
  let newestAt = -Infinity;
  for (const work of works) {
    if (!work.last_indexed) continue;
    const at = Date.parse(work.last_indexed);
    if (newest === undefined || (!Number.isNaN(at) && at > newestAt)) {
      newest = work.last_indexed;
      newestAt = Number.isNaN(at) ? -Infinity : at;
    }
  }
  return newest;
}
