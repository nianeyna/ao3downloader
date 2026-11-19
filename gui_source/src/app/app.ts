import { ReadingSkins } from './reading-skins';
import { ProgressBar } from './progress-bar';
import { UnindexedWorks } from './unindexed-works';
import { NamePattern, namePatternText } from './naming';
import { formatsOfPattern } from './renames';
import { inAo3Zone, shownTime } from './preferences';
export { shownTime } from './preferences';
import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { BrowserNotice, browserNoticeSeen } from './browser-notice';
import { CollectionsView } from './collections-view';
import { DownloadDialog } from './download-dialog';
import { Faq } from './faq';
import { Feedback } from './feedback';
import { History } from './history';
import { ImportDialog } from './import-dialog';
import { DebugTab } from './debug-tab';
import { DebugMode } from './debug';
import { DummyData } from './dummy-data';
import { VisitLog } from './visit-log';
import { DatingResult, ImportRequest, LibraryImports, importIssueCounts, importIssueLines } from './imports';
import { IMPORT_OFFER_KEY } from './preferences';
import { safeGet, safeSet, safeRemove } from './storage';
import { FolderWarning, folderWarningDismissed } from './folder-warning';
import { ActiveRun, BUILT_IN_CONFIG, JobAction, Jobs } from './jobs';
import { HelperConnection } from './helper-connection';
import { GuestMode } from './guest';
import { DeviceSupport } from './device-support';
import { Library, describeReadProgress } from './library';
import type { LibraryStore } from './library-store';
import { LibraryFreshness } from './freshness';
import { LibrarySetup } from './library-setup';
import { PasscodeGate } from './passcode-gate';
import { SetupOverlay } from './setup-overlay';
import { WorkList } from './work-list';
import { Bookmark, ownerFromSource } from './bookmarks';
import { APP_FOLDER_PATH, DropboxSession } from './dropbox';
import { StorageChoice, StorageMode } from './storage-choice';
import { UpdateCheck } from './updates';
import { UserSettings } from './user-settings';

/** why a guest cannot pick a library: the tour is of the dummy one */
const GUEST_LOCKED_TITLE = 'Not available in guest mode - log in, or run FicFairy on your own computer';

/** how often the page asks whether a run in progress has finished, while one is */
const ACTIVE_RUN_POLL_MS = 30_000;

/** the two things this folder holds, the pages that show them, and the two reading pages */
export type View = 'bookmarks' | 'collections' | 'history' | 'faq' | 'bug' | 'settings' | 'debug';

@Component({
  selector: 'app-root',
  imports: [ProgressBar, DebugTab, DecimalPipe, NgTemplateOutlet, BrowserNotice, DownloadDialog, Faq, FolderWarning, History, WorkList,
    CollectionsView, Feedback, PasscodeGate, SetupOverlay, UserSettings, ImportDialog],
  styleUrl: './app.css',
  templateUrl: './app.html',
  // a tab coming back into view is when a run elsewhere is most likely to have finished
  host: { '(document:visibilitychange)': 'lookAgain()' },
})
export class App {
  protected readonly library = inject(Library);
  protected readonly freshness = inject(LibraryFreshness);
  /** made as the app starts, so the reading skin chosen is in force from the first work opened */
  private readonly readingSkins = inject(ReadingSkins);
  protected readonly refreshing = this.library.refreshing;
  protected readonly jobs = inject(Jobs);
  private readonly storage = inject(StorageChoice);
  private readonly dropbox = inject(DropboxSession);
  private readonly helper = inject(HelperConnection);
  /** the hosted copy, on GitHub Pages: its helper is not on this computer */
  protected readonly hosted = !this.helper.isLocal();
  /** a visitor to the hosted copy without its passcode - a tour, with nothing real (`guest.ts`) */
  protected readonly guest = inject(GuestMode);
  /** a phone, or a browser that cannot write to a folder, with a library from this device open */
  protected readonly device = inject(DeviceSupport);
  private readonly updates = inject(UpdateCheck);

  /** a newer release than this page's own, once GitHub has said so - the footer says it always */
  protected readonly newerRelease = this.updates.newer;
  /** ...and the banner until it is dismissed */
  protected readonly bannerRelease = computed(() => (this.updates.dismissed() ? null : this.updates.newer()));
  /** only once GitHub has answered: not knowing is not the same as being the latest */
  protected readonly upToDate = computed(() => this.updates.checked() && !this.updates.newer());
  protected readonly latestReleaseUrl = computed(() => {
    this.helper.settings();
    return this.updates.latestUrl();
  });
  protected readonly currentVersion = computed(() => this.helper.settings().version);
  protected readonly repositoryName = computed(() => this.helper.settings().releasesRepo);
  protected readonly repositoryUrl = computed(() => `https://github.com/${this.repositoryName()}`);
  protected readonly issuesUrl = computed(() => `${this.repositoryUrl()}/issues`);
  /** whether the feedback tab is there to point at - only on a copy built with its Worker */
  protected readonly feedbackOffered = computed(() => !!this.helper.settings().feedbackUrl && !this.guest.active());
  /** the Report a bug page's button opens the same window the Feedback tab does */
  protected openFeedback(): void {
    this.feedback()?.show();
  }
  /** only the Windows, Mac or Linux app can install an update itself; anywhere else the banner links it */
  protected readonly canUpdate = this.updates.canUpdate;
  protected readonly updateProgress = this.updates.updating;
  protected readonly updateTarget = computed(() => {
    const progress = this.updateProgress();
    return progress.state === 'updating' ? progress.version : '';
  });
  protected readonly updateError = computed(() => {
    const progress = this.updateProgress();
    return progress.state === 'failed' ? progress.error : '';
  });

  protected readonly view = signal<View>('bookmarks');
  /**
   * Whether the passcode window is up - on a copy set up with one and not yet given it, or
   * whenever the helper turns the saved one down.
   */
  protected readonly passcodeWanted = this.helper.passcodeWanted;
  /** which download dialog is open, if any */
  protected readonly dialogAction = signal<JobAction | null>(null);
  /** the run a custom run opens set to resume, when opened from the history */
  protected readonly resumeFrom = signal('');
  /** a background run the window opens onto, from the history's View progress */
  protected readonly attachTo = signal<ActiveRun | null>(null);
  /** a work number for the single-fic run's link box, when it was opened from a listing */
  protected readonly prefillLink = signal('');
  /** an import's works and choices, for the run window it opens */
  protected readonly importing = signal<ImportRequest | null>(null);

  /** the library's works with files and no index entry, kept current */
  protected readonly imports = inject(LibraryImports);
  /** this browser's debug mode: a banner at the top, and the DEBUG tab */
  protected readonly debugMode = inject(DebugMode);
  private readonly visit = inject(VisitLog);
  protected readonly dummyData = inject(DummyData);
  /** the formats an import can fetch: the helper's, or what any helper offers until it answers */
  protected readonly importFormats = computed(
    () => this.jobs.config()?.filetypes ?? BUILT_IN_CONFIG.filetypes,
  );
  /** whether the import window is up */
  protected readonly importOpen = signal(false);
  /** the work Resolve issues was opened to look up, from the Works tab - none when opened otherwise */
  protected readonly importLookUp = signal<string[] | null>(null);
  /** the formats an old naming pattern left, ticked on the rename step once it was just changed */
  protected readonly renameFrom = signal<string[]>([]);
  /**
   * A run ended having met files with no date in the app's own form, and the reader chose to
   * date them: the library is read again, and Resolve issues opens once that read - and the
   * check that follows it - is done (`at`: when the choice was made).
   */
  private readonly resolveAfterRead = signal<{ store: LibraryStore; at: number } | null>(null);
  /** whether the import window opens by itself when a library turns out to have some */
  protected readonly importOffered = signal(safeGet(IMPORT_OFFER_KEY) !== 'off');
  /** the library whose reminder above the tabs was dismissed, this visit */
  private readonly reminderDismissedFor = signal<object | null>(null);
  /** the reminder above the tabs: something to resolve in the library open now, not dismissed,
   *  and not turned off for good */
  protected readonly importReminder = computed(() => {
    const store = this.library.store();
    return this.importOffered() && this.imports.hasIssues() && !!store && !this.library.loading() &&
      this.imports.checkedStore() === store && this.reminderDismissedFor() !== store;
  });

  protected dismissImportReminder(): void {
    this.reminderDismissedFor.set(this.library.store());
  }

  /** the libraries the import window has opened by itself for already, this visit */
  private readonly offeredFor = new WeakSet<object>();

  /**
   * The run the helper is working on, if any.
   *
   * The helper runs one at a time, so while there is one nothing else can start: the page
   * says so at the top and the run buttons wait, rather than letting someone fill in a
   * whole run window only to be refused at the end of it.
   */
  protected readonly activeRun = computed(() => this.jobs.activeRuns()[0] ?? null);
  /**
   * Whether the one-off browser note is up.
   *
   * Said on the first visit and never again: writing into a folder you chose needs the
   * File System Access API, which only Chromium browsers have. Waiting until it bites
   * would mean saying it after a folder is picked and a run started.
   */
  protected readonly browserNotice = signal(!browserNoticeSeen());

  /** whether the naming note is up, waiting to be read before the picker opens */
  protected readonly warning = signal(false);

  /** the fallback picker, for browsers with no directory picker of their own */
  private readonly feedback = viewChild(Feedback);
  private readonly destroyRef = inject(DestroyRef);
  private readonly folderInput = viewChild<ElementRef<HTMLInputElement>>('folderInput');
  /** the version bar, measured so what is pinned to the bottom sits just above it */
  private readonly footer = viewChild<ElementRef<HTMLElement>>('appFooter');

  /**
   * Open a run's window at once. Nothing it needs from the helper or the library holds it up:
   * the helper is asked for its config, and a quick scan's newest floor is looked for, in the
   * background (`Jobs.connecting`, `Jobs.floorAhead`) - a hosted helper asleep on a free
   * plan takes most of a minute to wake, and the options can be chosen meanwhile. The run page
   * waits on them only when Start is pressed (`DownloadDialog.readyToStart`). Runs left
   * 'running' are checked for in the background too: nothing in starting a run depends on it,
   * and the Retry list checks again itself.
   */
  protected openRun(action: JobAction, link = ''): void {
    // held on a phone or a browser that cannot write to a folder: said, rather than doing nothing
    if (this.device.blocked()) {
      this.device.explain();
      return;
    }
    if (this.activeRun()) return;
    const store = this.library.store();
    this.jobs.connecting = this.jobs.loadConfig();
    this.jobs.floorAhead = action === 'quick' ? this.jobs.loadNewestFloor(store) : null;
    void this.jobs.settleInterrupted(store);
    this.visit.note(`Run window opened: ${action}${link ? ', with a work number filled in' : ''}`);
    this.prefillLink.set(link);
    this.dialogAction.set(action);
  }

  /** a time of day, for when a paused background run will be abandoned */
  protected timeOf(stamp: string): string {
    const parsed = new Date(stamp);
    return Number.isNaN(parsed.getTime())
      ? ''
      : parsed.toLocaleTimeString([], inAo3Zone({ hour: '2-digit', minute: '2-digit' }));
  }

  /** from the banner: the history, where the run in progress is pinned to the top */
  protected goToRun(): void {
    this.view.set('history');
  }

  /** from the history: open the progress window onto a background run already going */
  protected viewProgress(run: ActiveRun): void {
    this.attachTo.set(run);
    this.dialogAction.set(run.action);
  }

  /** what the Works tab's button has found, in a few words */
  /** counted and worded as the import window's own overview, in files, so the two agree */
  protected readonly importIssuesSaid = computed(() =>
    importIssueLines(importIssueCounts(this.imports.found(), this.imports.undatedIndexed(), this.imports.duplicates(),
      this.imports.misnamed().formats, this.imports.leftovers()))
      .map((line) => line.text)
      .join('; '),
  );

  /** from the Works tab's button: the import window, by hand */
  protected openImport(): void {
    if (this.activeRun() || this.dialogAction()) return;
    this.visit.note('Resolve issues window opened, by hand');
    this.importOpen.set(true);
  }

  /** from the end of a run: read the library again, then open Resolve issues on what it finds */
  protected resolveIssuesAfterRun(): void {
    const store = this.library.store();
    if (!store) return;
    this.visit.note('Refresh library and resolve issues, from the end of a run');
    this.resolveAfterRead.set({ store, at: Date.now() });
    void this.library.refresh();
  }

  /**
   * FileNamePattern was changed from the DEBUG tab: files named the old way are no longer read
   * as works, so the library is read again and Resolve issues opened on renaming them, with the
   * old pattern's formats ticked.
   */
  protected namePatternChanged(old: NamePattern): void {
    this.renameFrom.set(formatsOfPattern(old));
    this.visit.note('File name pattern changed - reading the library again to offer renames');
    this.resolveIssuesAfterRun();
  }

  /** the import window closed without starting a run - the files it dated are taken in */
  protected importClosed(dated: DatingResult | null): void {
    this.importOpen.set(false);
    this.importLookUp.set(null);
    this.renameFrom.set([]);
    void this.takeInDating(dated);
  }

  /** the import window's choices made: on to the run window, which asks the rest */
  protected importStart(chosen: { request: ImportRequest; dated: DatingResult | null }): void {
    this.importOpen.set(false);
    this.importLookUp.set(null);
    this.renameFrom.set([]);
    void this.takeInDating(chosen.dated);
    this.importing.set(chosen.request);
    this.openRun('import');
  }

  protected setImportOffered(offered: boolean): void {
    this.importOffered.set(offered);
    if (offered) safeRemove(IMPORT_OFFER_KEY);
    else safeSet(IMPORT_OFFER_KEY, 'off');
  }

  /** the renamed files listed again, so the page opens them by their new names */
  private async takeInDating(dated: DatingResult | null): Promise<void> {
    if (!dated?.renamed.length) return;
    await this.library.refreshAfterRun(dated.renamed.flatMap((x) => [x.from, x.to]));
    void this.imports.check();
  }

  /** the run window closed - whatever it was, what is running may have changed */
  protected dialogClosed(): void {
    this.dialogAction.set(null);
    this.importing.set(null);
    this.resumeFrom.set('');
    this.attachTo.set(null);
    this.prefillLink.set('');
    void this.jobs.refreshActiveRuns();
  }

  /** from the history: a custom run, set to pick up where that run left off */
  protected resumeRun(runId: string): void {
    this.resumeFrom.set(runId);
    void this.openRun('custom');
  }

  protected readonly data = this.library.data;
  protected readonly collections = this.library.collections;
  protected readonly error = this.library.error;
  protected readonly loading = this.library.loading;
  /** the bar while a Dropbox library is read: what stage, and how far when that is known */
  protected readonly reading = computed(() => {
    const progress = this.library.readProgress();
    return progress ? describeReadProgress(progress) : null;
  });
  /**
   * Where the library's reading bar goes when the tab showing has no title to put it under:
   * Works before anything is read, and Dropbox's sign-in panel
   */
  protected readonly progressOnTop = computed(() => {
    const view = this.view();
    // Works and Collections show their headings from the first moment of a read, with the
    // bar under them; only a Dropbox library not yet open has no heading to go under
    return this.mode() === 'dropbox' && !this.canRun() && !this.loading() && (view === 'bookmarks' || view === 'collections');
  });
  /**
   * Nothing read yet - the library's first read is going, or failed: no time to say, and no
   * 'nothing here' either, since nobody knows yet
   */
  protected readonly firstRead = computed(
    () => (this.loading() || !!this.library.readFailure()) && !this.data(),
  );
  /** when the list was last read - none yet means nothing to refresh, so no refresh icon */
  protected readonly listedAt = this.library.listedAt;
  /** the open library has been read successfully, so an empty one is known to be empty */
  protected readonly libraryWasRead = computed(() => {
    const store = this.library.store();
    return !!store && this.library.lastRead()?.store === store;
  });
  /** a failed read of the library, offered again by hand */
  protected readonly readFailure = this.library.readFailure;
  /** seconds before Try again can be pressed: 3, 2, 1 - or longer, when Dropbox asked */
  protected readonly retryCountdown = signal(0);
  private countdownTimer: ReturnType<typeof setInterval> | null = null;

  /** hide the failure and read again; a new failure brings the panel back */
  protected tryReadAgain(): void {
    if (this.retryCountdown() > 0) return;
    void this.library.retryRead();
  }
  protected readonly sourceName = this.library.sourceName;
  protected readonly folderName = this.library.folderName;
  protected readonly openedName = this.library.openedName;
  protected readonly needsReconnect = this.library.needsReconnect;
  protected readonly canPickFolder = this.library.canPickFolder;

  /** a folder on this computer, or one in Dropbox - both stay remembered either way */
  protected readonly mode = this.storage.mode;
  protected readonly dropboxStatus = this.dropbox.status;
  protected readonly dropboxAccount = this.dropbox.account;
  protected readonly dropboxError = this.dropbox.error;
  /** what setting a library up could not do - files it could not move, say */
  private readonly librarySetup = inject(LibrarySetup);
  protected readonly setupReport = this.librarySetup.report;
  /** setting the library up, said in the loading bar rather than over the page */
  protected readonly setupWorking = computed(() => this.librarySetup.state() === 'working');
  /** said in the loading panel when a run elsewhere is what it is reading for */
  protected readonly behindNote = computed(() => {
    const cached = this.library.fromCache();
    if (cached !== null) {
      return `Showing your library as this browser saved it ${shownTime(new Date(cached))} - checking Dropbox ` +
        'for changes. Runs and Resolve issues wait until this is done.';
    }
    return this.refreshing() && this.freshness.behind()
      ? 'A run has finished since this library was read - bringing the list up to date...'
      : '';
  });
  protected readonly setupCaption = this.librarySetup.caption;
  protected readonly setupPercent = this.librarySetup.percent;
  /** where the library is in Dropbox - always the app folder, so there is nothing to pick */
  protected readonly appFolderPath = APP_FOLDER_PATH;

  /**
   * Whether a downloads folder has been chosen yet.
   *
   * Every run reads that folder to work out what it already has and writes everything back
   * into it, so starting one before a folder is picked is starting a run with no idea what
   * it is looking at. The buttons stay disabled until then rather than being hidden: a
   * button you can see and cannot press says what is missing, where an absent one does not.
   */
  protected readonly folderChosen = computed(() => !!this.folderName());

  /**
   * Whether the run buttons are offered: once there is a library open that the page can
   * write to. A run reads and writes through the page, so a folder that is only
   * remembered - waiting on a reconnect - is not enough, and neither is a Dropbox sign-in
   * whose folder has not finished opening.
   */
  protected readonly canRun = computed(() => !!this.library.store());

  /**
   * Whether debug mode is on - which once was settings.ini's `EnableDebugTools`.
   *
   * Gates the runs that are kept for working on the app rather than for using it.
   * They still work, and they are still the passes the recommended run is built
   * from - but offering them beside it invites picking one of the parts when the
   * whole is what was wanted.
   */
  protected readonly debugTools = computed(() => this.debugMode.on());

  /** the banner's way out: debug mode off, and off the DEBUG tab, which goes with it */
  protected leaveDebugMode(): void {
    this.debugMode.set(false);
    if (this.view() === 'debug') this.view.set('bookmarks');
    this.visit.note('Debug mode turned off, from the debug banner');
  }

  constructor() {
    // the selection bar is pinned above the version bar, which wraps onto more lines on a
    // narrow window - so its height is measured rather than guessed (--app-footer-height)
    afterNextRender(() => {
      const footer = this.footer()?.nativeElement;
      if (!footer || typeof ResizeObserver === 'undefined') return;
      const note = () =>
        document.documentElement.style.setProperty('--app-footer-height', `${footer.offsetHeight}px`);
      const watching = new ResizeObserver(note);
      watching.observe(footer);
      note();
      this.destroyRef.onDestroy(() => watching.disconnect());
    });
    // runs left 'running' by a page that closed or a helper that stopped are marked
    // interrupted whenever a library is opened or refreshed - in the background, since nothing
    // waits on it (History and the Retry list check again for themselves)
    // 'download it now' on a work known only by its number, from any listing: to the Works tab,
    // with Download/update a specific fic open and the number in its box
    effect(() => {
      const works = this.jobs.fetchWorksAsked();
      if (!works?.length) return;
      untracked(() => {
        this.jobs.fetchWorksAsked.set(null);
        if (this.activeRun() || this.dialogAction()) return;
        this.setView('bookmarks');
        this.openRun(works.length === 1 ? 'work' : 'works', works.join('\n'));
      });
    });
    // 'look up its index' on a file no index entry matches: Resolve issues, as the reminder opens it
    // opened straight on the index question, for that work or every work with none
    effect(() => {
      const works = this.jobs.lookUpAsked();
      if (!works?.length) return;
      untracked(() => {
        this.jobs.lookUpAsked.set(null);
        if (this.activeRun() || this.dialogAction()) return;
        this.importLookUp.set(works);
        this.visit.note(`Look up its index asked for ${works.length} work(s), from the Works tab`);
        this.importOpen.set(true);
      });
    });
    effect(() => {
      const read = this.library.lastRead();
      if (read) untracked(() => void this.jobs.settleInterrupted(read.store));
    });
    // a failed read holds its Try again button for a moment, counting down, so the reader is
    // not invited to ask Dropbox again the instant it said to slow down
    effect(() => {
      const failure = this.readFailure();
      untracked(() => {
        if (this.countdownTimer) clearInterval(this.countdownTimer);
        this.countdownTimer = null;
        this.retryCountdown.set(failure?.waitSeconds ?? 0);
        if (!failure) return;
        this.countdownTimer = setInterval(() => {
          this.retryCountdown.update((n) => Math.max(0, n - 1));
          if (this.retryCountdown() === 0 && this.countdownTimer) {
            clearInterval(this.countdownTimer);
            this.countdownTimer = null;
          }
        }, 1000);
      });
    });
    // whenever the index changes - a read, a refresh, a run's changes taken in - the works
    // with files and no entry are worked out again: one listing of works/
    // - but only once the library is wholly read and set up: the store is set before the index
    // is read, and checked against that empty index every file looked unindexed
    effect(() => {
      this.library.worksById();
      // which file is which work is read by FileNamePattern: a new one changes the answer
      namePatternText();
      const store = this.library.store();
      // a cached copy shown while Dropbox is checked is not the library as it is now
      const reading =
        this.library.loading() || this.librarySetup.state() !== 'idle' || this.library.fromCache() !== null;
      // a read that failed has no index to check against either: every file would look
      // unindexed, and the window would offer to 'repair' the whole library
      const failed = !!this.library.readFailure();
      untracked(() => (store && !reading && !failed ? void this.imports.check() : this.imports.forget()));
    });
    // offered by itself once per library per visit, and never while a run is going: the run
    // reads and writes the library, and renaming files under it is not safe. a run ending
    // changes the index, which checks again, and the offer is made then
    effect(() => {
      const found = this.imports.hasIssues();
      const store = this.imports.checkedStore();
      if (!found || !store || store !== this.library.store()) return;
      if (this.activeRun() || this.dialogAction() || this.importOpen() || !this.importOffered()) return;
      if (this.library.loading() || this.librarySetup.state() !== 'idle') return;
      untracked(() => {
        if (this.offeredFor.has(store)) return;
        this.offeredFor.add(store);
        this.visit.note('Resolve issues window opened by itself - issues were found in the library');
        this.importOpen.set(true);
      });
    });
    // asked for at the end of a run: once the library has been read again since, and checked,
    // Resolve issues opens - by hand, so whether it would offer itself does not matter
    effect(() => {
      const waiting = this.resolveAfterRead();
      if (!waiting) return;
      const read = this.library.lastRead();
      if (waiting.store !== this.library.store()) { untracked(() => this.resolveAfterRead.set(null)); return; }
      if (!read || read.store !== waiting.store || read.at < waiting.at) return;
      if (this.library.loading() || this.librarySetup.state() !== 'idle' || this.imports.checking()) return;
      if (this.imports.checkedStore() !== waiting.store) return;
      untracked(() => {
        this.resolveAfterRead.set(null);
        if (this.activeRun() || this.dialogAction() || this.importOpen()) return;
        if (!this.imports.hasIssues()) return;
        this.visit.note('Resolve issues window opened, after the library was read again');
        this.importOpen.set(true);
      });
    });
    // a passcode saved in this browser is checked with the helper before guest mode ends
    void this.guest.checkSaved();
    // into or out of guest mode (a preview from the DEBUG tab, or a guest logging in): what the
    // other helper said is forgotten and this one asked. the library is read again by the effect
    // below, since dummy data goes with guest mode
    let wasGuest = this.guest.active();
    effect(() => {
      const guest = this.guest.active();
      if (guest === wasGuest) return;
      wasGuest = guest;
      untracked(() => {
        // a guest has no DEBUG or Report a bug tab to stay on
        if (guest && (this.view() === 'debug' || this.view() === 'bug')) this.view.set('bookmarks');
        this.dialogAction.set(null);
        this.importOpen.set(false);
        this.importLookUp.set(null);
        this.jobs.activeRuns.set([]);
        this.jobs.forgetHistory();
        void this.jobs.loadConfig();
        void this.jobs.refreshActiveRuns();
      });
    });
    // finishes a sign-in if this load is the way back from dropbox.com
    void this.dropbox.restore();
    // show whichever library is chosen, and show it again whenever that changes. signing in
    // to dropbox is what opens its folder, so the session is tracked - but only while
    // dropbox is the choice: signing in while looking at a local folder must not make the
    // page read that folder again
    effect(() => {
      // debug mode's dummy data turned on or off reads whichever library is chosen again
      const dummy = this.dummyData.active();
      const mode = this.mode();
      untracked(() => this.visit.note(`Library: ${mode === 'dropbox' ? 'Dropbox' : 'this computer'}${dummy ? ' (dummy data)' : ''}`));
      if (this.mode() === 'dropbox') {
        this.dropboxStatus();
        untracked(() => void this.library.showDropbox());
      } else {
        // reopen the folder picked last time, if the browser still lets us read it
        untracked(() => void this.library.showLocal());
      }
    });
    // for the visit log: each library read, and how it ended
    let wasLoading = false;
    effect(() => {
      const loading = this.library.loading();
      const error = this.library.error();
      untracked(() => {
        if (loading && !wasLoading) this.visit.note('Library read started');
        if (!loading && wasLoading) {
          this.visit.note(error
            ? `Library read failed: ${error}`
            : `Library read finished: ${this.library.data()?.works.length ?? 0} works, ${this.library.collections().length} collections`);
        }
        wasLoading = loading;
      });
    });
    // the buttons on offer depend on settings.ini, so it is read as the page opens
    // rather than when a dialog first needs it
    void this.jobs.loadConfig();
    // a run left going in the background, from this page or another, is said at once
    void this.jobs.refreshActiveRuns();
    // once per opening, and never for a page that has no version or was told not to
    void this.updates.check();
    // whether the helper is the Windows, Mac or Linux app, which can update itself - and whether its last
    // update went through. untracked, or clearing a failure would bring it straight back
    effect(() => {
      const app = this.jobs.config()?.app;
      untracked(() => this.updates.appStatus(app));
    });
    // and asked about again while one is going, so the banner goes when it finishes. only
    // then: with nothing running there is nothing to watch for, and a hosted helper is left
    // to sleep
    // a run that finished since the library was read, with changes this page did not take
    // in: the list brings itself up to date - only while it is in view, and never while a run
    // is going, which may be writing to the library still
    effect(() => {
      const view = this.view();
      if (!this.freshness.behind() || this.activeRun() || this.library.refreshing()) return;
      if (view !== 'bookmarks' && view !== 'collections') return;
      untracked(() => {
        if (this.freshness.claimRefresh()) void this.library.refresh();
      });
    });
    // a run the helper stops listing has ended - whatever it changed may not be on screen
    let going = new Set<string>();
    effect(() => {
      const now = new Set(this.jobs.activeRuns().map((run) => run.id));
      const ended = [...going].some((id) => !now.has(id));
      going = now;
      if (ended) untracked(() => void this.freshness.check());
    });
    this.watch = setInterval(() => {
      if (this.activeRun()) void this.jobs.refreshActiveRuns();
    }, ACTIVE_RUN_POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(this.watch));
  }

  private watch: ReturnType<typeof setInterval> | undefined;

  /** stop saying there is a newer release, in this browser, for good */
  protected dismissUpdates(): void {
    this.updates.dismiss();
  }

  /** the Windows, Mac or Linux app: download the newer release, restart as it, and reload this page */
  protected updateNow(): void {
    void this.updates.updateNow();
  }

  protected clearUpdateError(): void {
    this.updates.acknowledgeFailure();
  }

  private readonly unindexed = inject(UnindexedWorks);
  /** the index's works, then every file in works/ no entry matches - listed from its name */
  protected readonly works = computed<Bookmark[]>(() => [...(this.data()?.works ?? []), ...this.unindexed.rows()]);
  protected readonly owner = computed(() => ownerFromSource(this.data()?.source ?? ''));

  /**
   * Above the listing: when this list was last brought up to date from the library - a read,
   * a refresh, or a run's changes taken in
   */
  protected readonly listingNote = computed(() => {
    const listed = this.library.listedAt();
    return listed ? `List refreshed ${shownTime(listed)}` : '';
  });

  /** a folder with nothing in it at all is what the getting-started panel is for */
  protected readonly isEmpty = computed(
    () => !this.data() && this.collections().length === 0 && !this.loading(),
  );

  /** the helper took the passcode: ask it again for what it refused to say without one */
  protected unlocked(): void {
    // a guest who logged in leaves guest mode, which reads the real helper and library itself
    if (this.guest.active()) {
      this.guest.leave();
      return;
    }
    void this.jobs.loadConfig();
  }

  protected setView(view: View): void {
    if (view !== this.view()) this.visit.note(`Tab opened: ${view}`);
    this.view.set(view);
    if (view === 'bookmarks' || view === 'collections') void this.freshness.check(true);
  }

  /** a works list in view is when it is worth knowing it is behind */
  protected lookAgain(): void {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    const view = this.view();
    if (view === 'bookmarks' || view === 'collections') void this.freshness.check(true);
  }


  protected async choose(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    if (this.guest.active()) return;
    await this.library.load(input.files);
    // let the same folder be picked again after a re-export
    input.value = '';
  }

  /**
   * The naming rule, said once before the folder is chosen.
   *
   * Both ways of choosing go through here - the directory picker where the browser has one,
   * and the hidden file input where it does not - because the rule applies to the folder,
   * not to how it was opened. Dismissing the note is remembered, so a return visit goes
   * straight to the picker.
   */
  protected askBeforePicking(): void {
    if (this.libraryLocked() || this.guest.active()) return;
    if (folderWarningDismissed()) {
      this.openPicker();
      return;
    }
    this.warning.set(true);
  }

  protected warningAccepted(): void {
    this.warning.set(false);
    this.openPicker();
  }

  protected warningCancelled(): void {
    this.warning.set(false);
  }

  private openPicker(): void {
    if (this.canPickFolder) {
      void this.library.pickFolder();
      return;
    }
    // no directory picker here, so the folder comes from a file input. clicking it from
    // inside the confirm handler keeps this within the user gesture the browser requires
    this.folderInput()?.nativeElement.click();
  }

  /**
   * A run reads and writes through the library open now, so while one is going the library
   * cannot be changed - not switched between this computer and Dropbox, not signed out of,
   * not pointed at another folder. Checked here as well as on the buttons.
   */
  protected readonly libraryLocked = computed(() => !!this.activeRun());
  /**
   * What the Refresh icon on Works and Collections says: in Dropbox it downloads the whole index
   * again, past this browser's copy of it (`refresh({ fresh: true })`), and says so
   */
  protected readonly refreshWords = computed(() =>
    this.mode() === 'dropbox' && !this.dummyData.active()
      ? {
          label: 'Refresh from Dropbox',
          title: "Refresh from Dropbox - download the library's index again, rather than use the copy saved in this browser",
          busy: 'Refreshing from Dropbox...',
        }
      : { label: 'Refresh the list', title: 'Refresh the list - read the library folder again', busy: 'Refreshing...' },
  );
  protected readonly lockedTitle = 'Cannot be changed while an active run is in progress';
  /**
   * The library is still being read, set up or checked for issues: the Works and Collections
   * buttons wait, and come back as the Resolve issues offer does
   */
  protected readonly libraryPreparing = computed(
    () =>
      this.library.loading() ||
      this.librarySetup.state() !== 'idle' ||
      this.imports.checking() ||
      // a cached copy shown while Dropbox is checked: runs and Resolve issues need it as it is now
      this.library.fromCache() !== null,
  );
  protected readonly preparingTitle = 'Wait until your library has finished loading';
  /**
   * a run cannot start: one is going, the library is not ready yet, or what is on screen is
   * debug mode's dummy data - a run would reach AO3 for real and write into a library that
   * does not exist
   */
  protected readonly runsHeld = computed(
    // a guest's runs are pretend ones, on the dummy library - those may go
    () => !!this.activeRun() || this.libraryPreparing() || (this.dummyData.active() && !this.guest.active()),
  );
  protected readonly dummyTitle = 'Runs are held while debug mode shows dummy data - turn it off in User settings';
  /** why the run buttons are held, when it is not simply a run going */
  protected readonly runsTitle = computed(() =>
    this.libraryPreparing() ? this.preparingTitle : this.dummyData.active() && !this.guest.active() ? this.dummyTitle : null,
  );
  /**
   * The folder and Dropbox sign-in controls: locked while a run is going, and while dummy data
   * stands in for the library - a folder picked or a sign-out then would change nothing shown.
   */
  protected readonly sourceLocked = computed(() => this.libraryLocked() || this.dummyData.active());
  protected readonly sourceLockedTitle = computed(() =>
    this.libraryLocked()
      ? this.lockedTitle
      : this.guest.active()
        ? GUEST_LOCKED_TITLE
        : this.dummyData.active()
          ? 'Cannot be changed while debug mode shows dummy data'
          : null,
  );
  /** the storage switch: held while a run is going, and for a guest, who has only the dummy library */
  protected readonly switchLocked = computed(() => this.libraryLocked() || this.guest.active());
  protected readonly switchLockedTitle = computed(() =>
    this.libraryLocked() ? this.lockedTitle : this.guest.active() ? GUEST_LOCKED_TITLE : null,
  );
  protected readonly store = this.library.store;

  protected setMode(mode: StorageMode): void {
    if (this.switchLocked()) return;
    this.storage.set(mode);
  }

  protected signInToDropbox(): void {
    if (this.sourceLocked() || this.guest.active()) return;
    void this.dropbox.signIn();
  }

  protected async signOutOfDropbox(): Promise<void> {
    if (this.sourceLocked()) return;
    // signing out clears this browser's cached copy of the library too (`forgetSession`)
    await this.dropbox.signOut();
  }

  /** read the library again now, as the list does by itself after a run finished elsewhere */
  protected refreshLibrary(): void {
    if (this.libraryLocked() || this.refreshing()) return;
    // pressed on purpose: Dropbox's whole index is downloaded again, and this browser's copy replaced
    void this.library.refresh({ fresh: true });
  }

  protected async reconnect(): Promise<void> {
    await this.library.reconnect();
  }

  protected async forget(): Promise<void> {
    if (this.sourceLocked()) return;
    await this.library.forget();
  }
}

/** what openRun does before a window opens, in the order its notice names them */

