import { Component, computed, effect, inject, input, linkedSignal, output, signal, untracked, OnInit } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import {
  DatingResult,
  DuplicateGroup,
  duplicateKey,
  formatOf,
  ModifiedTimes,
  RemovingResult,
  Rename,
  bestGuessOf,
  byRecency,
  modifiedTimes,
  newestOf,
  removeFiles,
  FoundFile,
  FoundWork,
  ImportRequest,
  LibraryImports,
  ToDate,
  UpdateScope,
  dateFiles,
  importLinks,
  inferDate,
  isFileDate,
  renamesFor,
  undatedFiles, importIssueCounts, importIssueLines, SwapLeftover, leftoverAction, patiently } from './imports';
import { dateFromFilename, dateStamp } from './bookmarks';
import { WORKS_FOLDER } from './library-setup';
import { activePattern, patternText } from './naming';
import { Misnamed, MisnamedFile, NameFormat } from './renames';
import { Jobs } from './jobs';
import { Library } from './library';
import { LibraryStore } from './library-store';
import { DropboxError } from './dropbox';
import { VisitLog } from './visit-log';
import { Chime } from './chime';
import { inAo3Zone, writtenDate } from './preferences';

type Step = 'overview' | 'leftovers' | 'rename' | 'renaming' | 'duplicates' | 'choose' | 'removing' | 'dates' | 'repair' | 'dating' | 'index' | 'formats' | 'filetypes';

/** what sifting by hand decided for one group: a file to keep, skipped, or its most recent */
/** what *Sort any remaining in bulk* can do with the rest */
export type BulkChoice = 'skip' | 'skip-remember' | 'recent';
export type SiftOutcome = { kind: 'pick'; path: string } | { kind: 'skip'; remember?: boolean } | { kind: 'recent' };

/** what to do with one group of duplicates */
export type DuplicateChoice = 'skip' | 'recent' | 'choose';

/** how many groups a page of the duplicates list holds */
export const DUPLICATES_PAGE_SIZE = 7;

/** how many rows a page of the dates list holds */
export const DATES_PAGE_SIZE = 7;

/** what to do with a set marked Keep most recent whose most recent cannot be told */
export type UndecidedHow = 'choose' | 'guess' | 'keep';

/** how long the removing page waits on that question before keeping every file of the set */
export const UNDECIDED_WAIT_MS = 5 * 60_000;

/** one set of duplicates as the removing page works through it */
type RemovalStep = { group: DuplicateGroup; remove: string[] } | { group: DuplicateGroup; undecided: true };

/**
 * Resolving what reading a library found: works with files but no index entry, and files with
 * no date in their name. One page per question, each passed over when it has nothing to ask:
 *
 * 1. **overview** - what was found, in a sentence each; nothing listed yet;
 * 2. **dates** - only with undated files: a date for each, one for all (*Use for all*), skips,
 *    or *Infer date*, which reads a date out of each name however it is written. Rows are by
 *    name, a page at a time or as one scrolling list;
 * 3. **dating** - the renames, with a bar; no going back from here, and closing stops it;
 * 4. **index** - only with unindexed works: fetch their entries from AO3 now?
 * 5. **formats** - other formats to download, and whether to replace a copy AO3 has a newer
 *    version of. Anything to do hands over to the run window (`start`), which asks the rest -
 *    background (a hosted copy), the login - as for any run.
 *
 * **Never while a run is going** (`busy`): the run reads and writes the library, and renaming
 * files under it - or a second run, which the helper refuses anyway - is not safe.
 */
@Component({
  selector: 'app-import-dialog',
  imports: [DecimalPipe],
  templateUrl: './import-dialog.html',
  styleUrl: './import-dialog.css',
})
export class ImportDialog implements OnInit {
  private readonly jobs = inject(Jobs);
  private readonly library = inject(Library);
  private readonly imports = inject(LibraryImports);
  private readonly visit = inject(VisitLog);
  private readonly chime = inject(Chime);

  readonly worksFound = input.required<FoundWork[]>({ alias: 'works' });
  /** undated files of works the index does have - offered for dating beside the rest */
  readonly undatedFound = input<FoundFile[]>([], { alias: 'undatedElsewhere' });
  /** works with more than one file in one format, offered before anything else */
  readonly duplicates = input<DuplicateGroup[]>([]);
  /**
   * Files the rename step would have named the same as a file already there (or as another file
   * it was renaming): not renamed, but put with that file as duplicates of one work and format,
   * which cannot be skipped. By path, each with the name it takes if it is the one kept.
   */
  private readonly clashes = signal<{ files: FoundFile[]; renameTo: Record<string, string> }>({ files: [], renameTo: {} });
  /**
   * Every set of duplicates: those reading the library found, with the rename step's clashes
   * joined to the set of their work and format. A file removed here leaves its set, and a set
   * left with one file is gone.
   */
  protected readonly groups = computed(() => {
    const removed = this.removedPaths();
    const byKey = new Map<string, DuplicateGroup>();
    const add = (key: string, id: string, format: DuplicateGroup['format'], files: FoundFile[]) => {
      const group = byKey.get(key) ?? { key, id, format, files: [] };
      const known = new Set(group.files.map((f) => f.path.toLowerCase()));
      group.files = [...group.files, ...files.filter((f) => !removed.has(f.path) && !known.has(f.path.toLowerCase()))];
      byKey.set(key, group);
    };
    for (const group of this.duplicates()) add(group.key, group.id, group.format, group.files);
    for (const file of this.clashes().files) add(duplicateKey(file.id, file.format), file.id, file.format, [file]);
    return [...byKey.values()].filter((g) => g.files.length > 1);
  });

  /** a set holding a file the rename step could not rename for its name being taken */
  protected isClash(group: DuplicateGroup): boolean {
    const renameTo = this.clashes().renameTo;
    return group.files.some((f) => f.path in renameTo);
  }

  /** whether this file is one the rename step held back for its new name being taken */
  protected isClashFile(file: FoundFile): boolean {
    return file.path in this.clashes().renameTo;
  }
  /** files the app cannot match to a work, by the format they are named in - the first step */
  readonly misnamed = input<Misnamed>({ formats: [], unreadable: [] });
  /** formats to tick to begin with: an old naming pattern's, just after it was changed */
  readonly renameFrom = input<string[]>([]);
  /** the files removed as duplicates here: gone from every page after */
  private readonly removedPaths = signal<ReadonlySet<string>>(new Set());
  /** what was found, less anything removed as a duplicate */
  protected readonly works = computed(() => {
    const removed = this.removedPaths();
    if (!removed.size) return this.worksFound();
    return this.worksFound()
      .map((w) => ({ ...w, files: w.files.filter((f) => !removed.has(f.path)) }))
      .filter((w) => w.files.length);
  });
  protected readonly undatedElsewhere = computed(() => {
    const removed = this.removedPaths();
    return this.undatedFound().filter((f) => !removed.has(f.path));
  });
  readonly store = input<LibraryStore | null>(null);
  /** the formats the helper offers, JSON among them */
  readonly formats = input<string[]>(['HTML', 'EPUB', 'PDF', 'MOBI', 'AZW3', 'JSON']);
  /**
   * A mock, from the DEBUG tab: the store is one in memory, and nothing reaches the real
   * library - exclusion lists are noted (`sandboxNotes`) instead of written, and no listing is
   * refreshed. Starting hands back the request, which the DEBUG tab shows rather than runs.
   */
  readonly sandbox = input(false);
  /** what a mock would have written to the exclusion lists, in words */
  readonly sandboxNoted = output<string>();
  /** a run is going: nothing may be renamed or started */
  readonly busy = input(false);
  /** how long the removing page waits for an answer about a set it cannot tell, before keeping it all */
  readonly answerWaitMs = input(UNDECIDED_WAIT_MS);

  /** closed without starting anything; `dated` is what was renamed, if anything */
  readonly closed = output<DatingResult | null>();
  /** start the import run with these */
  readonly start = output<{ request: ImportRequest; dated: DatingResult | null }>();
  /** 'No, never ask me again' chosen: neither this window nor the reminder, from now on */
  readonly askAgainChanged = output<boolean>();
  /** 'Not now, remind me again next time I open my library': the reminder goes too, until then */
  readonly remindLater = output<void>();

  protected readonly step = signal<Step>('overview');

  /**
   * Opened from a work's *Look up its index from AO3 here* in the Works tab: the window opens
   * straight on the index question, every page before it passed over, and asks whether to look
   * up just that work or every work with no index entry.
   */
  readonly lookUpWorks = input<string[] | null>(null);
  /** the works the window was opened for - one, or those ticked */
  protected readonly focus = signal<string[] | null>(null);
  /**
   * Works with no index entry the exclusion lists keep out of `works` - only ever looked up when
   * the window was opened for one of them, or for every missing index, ignored ones included.
   */
  readonly ignored = input<FoundWork[]>([]);
  /** just the work the window was opened for, every work with no index entry, or those and the ignored ones too */
  protected readonly lookupFor = signal<'this' | 'all' | 'ignored'>('this');

  ngOnInit(): void {
    const asked = new Set(this.lookUpWorks() ?? []);
    const offered = [...new Set([...this.works(), ...this.ignored()].map((w) => w.id))].filter((id) => asked.has(id));
    if (!offered.length) {
      this.visit.note(`Resolve issues: asked to look up ${asked.size} index(es), none offered - opened at its first page`);
      return;
    }
    this.focus.set(offered);
    this.visit.note(`Resolve issues opened on the index question for ${offered.length} work(s)` +
      (this.ignored().length ? `, ${this.ignored().length} more kept out by an exclusion list` : ''));
    this.step.set('index');
  }

  /** every undated file, by name */
  protected readonly undated = computed(() =>
    [...undatedFiles(this.works()), ...this.undatedElsewhere()].sort((a, b) =>
      a.name.localeCompare(b.name),
    ),
  );
  /** how many files belong to works with no index entry, for the first page */
  protected readonly unindexedFiles = computed(() => this.works().reduce((n, w) => n + w.files.length, 0));
  /** the overview's bullets - worded and counted as the reminder above the tabs is */
  protected readonly issueLines = computed(() =>
    importIssueLines(importIssueCounts(this.works(), this.undatedElsewhere(), this.groups(),
      this.misnamedFound().formats, this.leftoversDone() ? [] : this.leftovers())),
  );

  // region rename to the app's naming pattern

  /** what the rename step offers, less what it has renamed */
  protected readonly misnamedFound = computed(() => {
    const done = new Set([...this.renamedPaths(), ...Object.keys(this.clashes().renameTo)]);
    const found = this.misnamed();
    if (!done.size) return found;
    return {
      ...found,
      formats: found.formats
        .map((f) => ({ ...f, files: f.files.filter((x) => !done.has(x.path)) }))
        .filter((f) => f.files.length),
    };
  });
  private readonly renamedPaths = signal<ReadonlySet<string>>(new Set());
  /** the formats ticked, by key - an old pattern's to begin with */
  protected readonly renameTicked = linkedSignal<ReadonlySet<string>>(() => new Set(this.renameFrom()));
  protected readonly renameCount = computed(() =>
    this.misnamedFound().formats.filter((f) => this.renameTicked().has(f.key)).reduce((n, f) => n + f.files.length, 0),
  );
  /** the new name of each format's first files, as the helper names them */
  protected readonly renamePreview = signal<Record<string, string>>({});
  protected readonly renameProgress = signal<{ done: number; total: number }>({ done: 0, total: 0 });
  protected readonly renaming = signal(false);
  protected readonly renameResult = signal<DatingResult | null>(null);
  /** the pattern files are renamed to, as settings.ini holds it */
  protected readonly appPattern = computed(() => patternText(activePattern()));
  private stopRenaming = false;

  protected tickFormat(key: string, ticked: boolean): void {
    this.renameTicked.update((all) => {
      const next = new Set(all);
      if (ticked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  /** each format's first two files, as they would be named - asked of the helper on the way in */
  protected examples(format: NameFormat): MisnamedFile[] {
    return format.files.slice(0, 2);
  }

  private renameItem(file: MisnamedFile): { file: { name: string }; date: string; record?: object; parts: object } {
    return {
      file: { name: file.name },
      date: file.date,
      record: this.library.worksById().get(file.worknum) as object | undefined,
      parts: { worknum: file.worknum, title: file.title, author: file.author },
    };
  }

  private async toRename(): Promise<void> {
    this.step.set('rename');
    const examples = this.misnamedFound().formats.flatMap((f) => this.examples(f));
    if (!examples.length) return;
    const names = await this.jobs.fileNames(examples.map((f) => this.renameItem(f)));
    if (names) this.renamePreview.set(Object.fromEntries(examples.map((f, i) => [f.path, names[i]])));
  }

  /** rename every file of the ticked formats to the app's pattern - never over another file */
  protected async renameTickedFiles(): Promise<void> {
    const store = this.store() ?? this.library.store();
    if (!store || this.busy() || this.renaming()) return;
    const files = this.misnamedFound().formats.filter((f) => this.renameTicked().has(f.key)).flatMap((f) => f.files);
    if (!files.length) {
      this.fromRename();
      return;
    }
    this.stopRenaming = false;
    this.renaming.set(true);
    this.step.set('renaming');
    const result: DatingResult = { renamed: [], failed: [] };
    this.renameResult.set(result);
    this.renameProgress.set({ done: 0, total: files.length });
    const names = await this.jobs.fileNames(files.map((f) => this.renameItem(f)));
    if (!names) {
      result.failed.push(...files.map((f) => ({ path: f.path, error: 'the helper did not answer, so no new name could be made' })));
    } else {
      const renames = files
        .map((f, i) => ({ path: f.path, to: names[i] ? `${WORKS_FOLDER}/${names[i]}` : '' }))
        .filter((r, i) => {
          if (r.to) return true;
          result.failed.push({ path: files[i].path, error: 'no name could be made for it' });
          return false;
        });
      const clear = await this.holdClashes(store, renames, files);
      this.renameProgress.set({ done: 0, total: clear.length });
      await dateFiles(store, clear, (done) => this.renameProgress.set({ done, total: clear.length }),
        () => this.stopRenaming, result);
    }
    this.renamedPaths.set(new Set(result.renamed.map((r) => r.from)));
    // taken in as dating's renames are: the window's close hands them back, and the lists follow
    this.dated.update((d) => ({ renamed: [...(d?.renamed ?? []), ...result.renamed], failed: [...(d?.failed ?? [])] }));
    this.renameResult.set({ ...result });
    this.renaming.set(false);
    if (result.renamed.length && !this.sandbox()) {
      try {
        await this.imports.renamed(result.renamed);
        await this.library.refreshAfterRun(result.renamed.flatMap((r) => [r.from, r.to]), store);
      } catch {
        // the next read catches up
      }
      // a renamed file is a work's file now: the steps after it see it
      void this.imports.check();
    } else if (result.renamed.length) {
      this.note(`renamed to the app's pattern: ${result.renamed.length} files`);
    }
  }

  /** how many files were held back from renaming for their new name being taken */
  protected readonly clashCount = computed(() => Object.keys(this.clashes().renameTo).length);

  /**
   * The renames that can go ahead. One whose new name is already a file in `works/` - or is the
   * new name of another file in this batch - is held back: renaming never goes over a file, and
   * two files of one work and format named alike are duplicates. Each is put with the file(s)
   * of that name as a set of duplicates (`clashes`), which the duplicates step will not let be
   * skipped; whichever is kept there takes the name. Names are compared ignoring case, as
   * Windows, a Mac and Dropbox do.
   */
  private async holdClashes(store: LibraryStore, renames: Rename[], files: MisnamedFile[]): Promise<Rename[]> {
    let listed: string[] = [];
    try {
      listed = await store.list(WORKS_FOLDER, false);
    } catch {
      // not listed: a rename over a file is still refused by the store, and said as a failure
    }
    const taken = new Map(listed.map((p) => [p.toLowerCase(), p]));
    const wanted = new Map<string, number>();
    for (const r of renames) wanted.set(r.to.toLowerCase(), (wanted.get(r.to.toLowerCase()) ?? 0) + 1);
    const byPath = new Map(files.map((f) => [f.path, f]));
    const clear: Rename[] = [];
    const held: FoundFile[] = [];
    const renameTo: Record<string, string> = {};
    for (const r of renames) {
      const target = r.to.toLowerCase();
      const there = r.path.toLowerCase() === target ? undefined : taken.get(target);
      const file = byPath.get(r.path);
      if (!file || (!there && (wanted.get(target) ?? 0) < 2)) {
        clear.push(r);
        continue;
      }
      held.push({ id: file.worknum, path: file.path, name: file.name, format: file.format, date: '' });
      renameTo[file.path] = r.to;
      if (there) {
        const name = there.split('/').pop() ?? there;
        held.push({ id: file.worknum, path: there, name, format: formatOf(name) ?? file.format, date: dateFromFilename(name) });
      }
    }
    if (held.length) {
      this.clashes.update((c) => ({
        files: [...c.files.filter((f) => !held.some((h) => h.path === f.path)), ...held],
        renameTo: { ...c.renameTo, ...renameTo },
      }));
    }
    return clear;
  }

  protected fromRename(): void {
    this.step.set(this.groups().length ? 'duplicates' : this.afterDuplicatesStep());
  }

  // endregion

  // region duplicates

  /** each group's choice, by key; a group not here is skipped */
  protected readonly dupChoices = signal<Record<string, DuplicateChoice>>({});
  protected readonly dupPaged = signal(true);
  protected readonly dupPage = signal(0);
  protected readonly dupPageSize = DUPLICATES_PAGE_SIZE;
  protected readonly dupPages = computed(() => Math.max(1, Math.ceil(this.groups().length / this.dupPageSize)));
  protected readonly shownGroups = computed(() =>
    this.dupPaged()
      ? this.groups().slice(this.dupPage() * this.dupPageSize, (this.dupPage() + 1) * this.dupPageSize)
      : this.groups(),
  );
  protected readonly duplicateFiles = computed(() => this.groups().reduce((n, g) => n + g.files.length, 0));

  protected choiceOf(group: DuplicateGroup): DuplicateChoice {
    // keep most recent unless told otherwise - a set whose newest cannot be told is asked about
    // on the removing page, so nothing is deleted on a guess
    return this.dupChoices()[group.key] ?? 'recent';
  }

  protected setChoice(group: DuplicateGroup, choice: DuplicateChoice): void {
    this.dupChoices.update((c) => ({ ...c, [group.key]: choice }));
  }

  /** the buttons at the top: the same choice in every row, each still changeable after */
  protected chooseForAll(choice: DuplicateChoice): void {
    this.dupChoices.set(Object.fromEntries(this.groups().map((g) => [g.key, choice])));
  }

  protected setDupPaged(paged: boolean): void {
    this.dupPaged.set(paged);
    this.dupPage.set(Math.min(this.dupPage(), this.dupPages() - 1));
  }

  /**
   * When each duplicate file was last changed, by path - asked of the library once the window
   * has the duplicates, to tell apart two sharing the newest date. Unknown until it answers.
   */
  protected readonly modifiedAt = signal<ModifiedTimes>({});

  private readonly loadModified = effect(() => {
    const store = this.store();
    const paths = this.groups().flatMap((g) => g.files.map((f) => f.path));
    const known = untracked(this.modifiedAt);
    const wanted = paths.filter((p) => known[p] === undefined);
    if (!store || !wanted.length) return;
    const errors: unknown[] = [];
    void modifiedTimes(store, wanted, (error) => errors.push(error)).then((times) => {
      if (Object.keys(times).length) this.modifiedAt.update((m) => ({ ...m, ...times }));
      // each shows as 'unknown' under its radio; the visit log says why (a count and the first
      // reason, never a file's name)
      if (errors.length) {
        this.visit.note(
          `Resolve issues: could not read when ${errors.length} of ${wanted.length} duplicate files last changed ` +
            `(first: ${changeTimeProblem(errors[0])}) - shown as unknown`,
        );
      }
    });
  });

  /** the newest file of a group, worked out once per group */
  protected readonly newest = computed(() => {
    return new Map(this.groups().map((g) => [g.key, newestOf(g)]));
  });

  protected newestIn(group: DuplicateGroup): FoundFile | null {
    return this.newest().get(group.key) ?? null;
  }

  protected dateIn(file: FoundFile): string {
    return inferDate(file.name);
  }

  /** the groups marked I'll choose on the list */
  protected readonly toChoose = computed(() => this.groups().filter((g) => this.choiceOf(g) === 'choose'));

  /**
   * Every group ever marked I'll choose, in the order it first was. Never shortened: a group
   * changed to something else on the list and back again returns to its own place, with what
   * was decided for it while sifting.
   */
  private readonly siftOrder = signal<string[]>([]);
  /** what was decided for each group while sifting, by key - kept apart from the list's choice */
  protected readonly siftOutcome = signal<Record<string, SiftOutcome>>({});
  /** the groups to sort through by hand: those marked I'll choose, in sifting order */
  protected readonly siftList = computed(() => {
    const byKey = new Map(this.toChoose().map((g) => [g.key, g]));
    return this.siftOrder().map((key) => byKey.get(key)).filter((g): g is DuplicateGroup => !!g);
  });
  protected readonly chooseAt = signal(0);
  protected readonly choosing = computed(() => this.siftList()[this.chooseAt()] ?? null);
  protected readonly undecidedCount = computed(
    () => this.siftList().filter((g) => !this.siftOutcome()[g.key]).length,
  );
  /** every group sorted through: the done note shows, and Continue is offered */
  protected readonly siftDone = computed(() => this.siftList().length > 0 && this.undecidedCount() === 0);
  /** the list's skipped groups go on the duplicates list, all their files kept - sifting says so per group */
  protected readonly rememberSkipped = signal(false);
  /** every row marked Skip: the step is skipped as a whole */
  protected readonly allSkipped = computed(() => this.groups().every((g) => this.choiceOf(g) === 'skip'));

  private note(said: string): void {
    this.sandboxNoted.emit(said);
  }

  /**
   * A group's files to choose from, the likeliest most recent first: by the date in each name,
   * certain or guessed (undated last), then by when each file last changed, then by name.
   */
  protected byRecency(group: DuplicateGroup): FoundFile[] {
    return byRecency(group, this.modifiedAt());
  }

  /**
   * Said above the top radio: *Most recent* when a certain date settles it, our best guess when
   * the dates in the names or when each file last changed pick one out, and nothing when not.
   */
  protected topLabel(group: DuplicateGroup): string {
    if (this.newestIn(group)) return 'Most recent';
    return this.guessFor(group) ? "This is our best guess for 'most recent'" : '';
  }

  /** what is known of one file, under its radio: the date in its name, and when it last changed */
  protected fileNotes(file: FoundFile): string[] {
    const date = this.dateIn(file);
    const at = this.modifiedAt()[file.path];
    const notes = [
      // a date not written the app's way was only read loosely out of the name: said as a guess
      date ? `Filename dated ${writtenDate(date)}${dateFromFilename(file.name) ? '' : ' (best guess)'}` : 'No date included in the filename',
      at
        ? `File metadata updated at ${new Date(at).toLocaleString('en-GB', inAo3Zone({ day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }))}`
        : 'File metadata updated at: unknown',
    ];
    return notes;
  }

  protected outcomeOf(group: DuplicateGroup): SiftOutcome | undefined {
    return this.siftOutcome()[group.key];
  }

  /**
   * The file picked to keep in a group: the one picked by hand, or - until anything is decided -
   * the top of the list, the most recent where that can be told. Skipped picks none.
   */
  protected pickedIn(group: DuplicateGroup): string {
    const outcome = this.outcomeOf(group);
    if (outcome?.kind === 'pick') return outcome.path;
    if (outcome) return '';
    // nothing is picked to begin with when no file can be picked out as the most recent
    return this.newestIn(group)?.path ?? this.guessFor(group)?.path ?? '';
  }

  private decide(group: DuplicateGroup, outcome: SiftOutcome): void {
    this.siftOutcome.update((o) => ({ ...o, [group.key]: outcome }));
  }

  /** a file picked to keep: this group is sorted */
  protected setPicked(group: DuplicateGroup, file: FoundFile): void {
    this.decide(group, { kind: 'pick', path: file.path });
  }

  /** on to the sifting: newly marked groups join the end, and it opens on the first undecided */
  protected fromDuplicates(): void {
    if (this.busy()) return;
    if (!this.toChoose().length) {
      void this.applyDuplicates();
      return;
    }
    const known = new Set(this.siftOrder());
    this.siftOrder.update((order) => [...order, ...this.toChoose().filter((g) => !known.has(g.key)).map((g) => g.key)]);
    const first = this.siftList().findIndex((g) => !this.outcomeOf(g));
    this.chooseAt.set(first < 0 ? 0 : first);
    this.step.set('choose');
  }

  protected previousEntry(): void {
    if (this.chooseAt() > 0) this.chooseAt.set(this.chooseAt() - 1);
  }

  /**
   * On to the next entry, keeping the file selected here - the top one, until another is picked.
   * From the last entry it goes to the first one still to sort, or the done note.
   */
  protected nextEntry(): void {
    const group = this.choosing();
    // nothing picked (no best guess to begin with): pick a file or skip first
    if (group && !this.outcomeOf(group) && !this.pickedIn(group)) return;
    if (group && !this.outcomeOf(group)) {
      const top = this.pickedIn(group);
      if (top) this.decide(group, { kind: 'pick', path: top });
    }
    if (this.chooseAt() < this.siftList().length - 1) this.chooseAt.set(this.chooseAt() + 1);
    else this.toNextUndecided();
  }

  /**
   * This group skipped: every file kept - for now, or put on the duplicates list so it is not
   * asked about again. Like picking a file, it stays here until Next entry.
   */
  protected skipThis(group: DuplicateGroup, remember: boolean): void {
    this.decide(group, { kind: 'skip', remember });
  }

  protected skipRemembered(group: DuplicateGroup): boolean {
    const outcome = this.outcomeOf(group);
    return outcome?.kind === 'skip' && !!outcome.remember;
  }

  private toNextUndecided(): void {
    const list = this.siftList();
    const at = this.chooseAt();
    const after = [...list.keys()].slice(at + 1).concat([...list.keys()].slice(0, at));
    const next = after.find((i) => !this.outcomeOf(list[i]));
    if (next !== undefined) this.chooseAt.set(next);
  }

  /** what *Sort any remaining in bulk* offers, worded as the radios for one entry are */
  protected readonly bulkOptions: { value: BulkChoice; label: string }[] = [
    { value: 'skip', label: 'Skip for now' },
    { value: 'skip-remember', label: "Skip, don't ask again" },
    { value: 'recent', label: 'Keep most recent' },
  ];
  protected readonly bulkChoice = signal<BulkChoice | null>(null);

  /**
   * Every group not yet sorted: skipped (for now, or not to be asked about again), or its most
   * recent kept. Nothing is removed yet - the done note shows, and Continue goes on.
   */
  protected applyToRest(): void {
    const choice = this.bulkChoice();
    if (!choice) return;
    for (const group of this.siftList()) {
      if (this.outcomeOf(group)) continue;
      this.decide(group, choice === 'recent' ? { kind: 'recent' } : { kind: 'skip', remember: choice === 'skip-remember' });
    }
  }

  protected continueFromChoosing(): void {
    if (this.siftDone()) void this.applyDuplicates();
  }

  protected readonly removeProgress = signal<{ done: number; total: number }>({ done: 0, total: 0 });
  protected readonly removing = signal(false);
  protected readonly removed = signal<RemovingResult | null>(null);
  /**
   * Sets marked Keep most recent whose most recent could not be told, and kept whole - by the
   * answer, or because none came in time (`timedOut`). Offered again next time.
   */
  protected readonly undecided = signal<DuplicateGroup[]>([]);
  protected readonly timedOut = signal<ReadonlySet<string>>(new Set());
  /** sets a best guess was asked for but none could be made - kept whole, and said at the end */
  protected readonly unguessable = signal<DuplicateGroup[]>([]);
  /** sets settled by a best guess, and the file kept for each */
  protected readonly guessed = signal<{ group: DuplicateGroup; kept: FoundFile }[]>([]);
  private stopRemoving = false;

  // the question the removing page stops on, for a set it cannot tell
  protected readonly asking = signal<DuplicateGroup | null>(null);
  protected readonly askHow = signal<UndecidedHow | null>(null);
  protected readonly askPick = signal('');
  /** how many more such sets come after this one */
  protected readonly askMore = signal(0);
  /** the answer given for all the others like it - asked once, then followed */
  protected readonly standing = signal<UndecidedHow | null>(null);
  private answered: ((how: UndecidedHow, path?: string) => void) | null = null;
  private answerTimer: ReturnType<typeof setTimeout> | null = null;
  protected readonly waitMinutes = computed(() => Math.max(1, Math.round(this.answerWaitMs() / 60_000)));
  protected readonly askReady = computed(() => {
    const how = this.askHow();
    if (!how) return false;
    if (how === 'choose' && !this.askPick()) return false;
    const asking = this.asking();
    if (how === 'guess' && asking && !this.guessFor(asking)) return false;
    return true;
  });

  /** what the best guess would keep for the set being asked about */
  protected guessFor(group: DuplicateGroup): FoundFile | null {
    return bestGuessOf(group, this.modifiedAt());
  }

  /**
   * What the choices come to, set by set in the list's order: the files to delete - never every
   * file of a set - or a set to ask about, one marked Keep most recent whose newest cannot be
   * told; and the sets kept as they are that go on the duplicates list (skipped, and told not
   * to ask again). Nothing is deleted before the removing page - sifting only decides.
   */
  private duplicatePlan(): { steps: RemovalStep[]; keep: { group: DuplicateGroup; kept: FoundFile[] }[] } {
    const steps: RemovalStep[] = [];
    const keep: { group: DuplicateGroup; kept: FoundFile[] }[] = [];
    const keepNewest = (group: DuplicateGroup) => {
      const newest = this.newestIn(group);
      steps.push(
        newest
          ? { group, remove: group.files.filter((f) => f !== newest).map((f) => f.path) }
          : { group, undecided: true },
      );
    };
    for (const group of this.groups()) {
      const choice = this.choiceOf(group);
      if (choice === 'skip') {
        if (this.rememberSkipped()) keep.push({ group, kept: group.files });
      } else if (choice === 'recent') {
        keepNewest(group);
      } else if (choice === 'choose') {
        const outcome = this.outcomeOf(group);
        if (outcome?.kind === 'recent') keepNewest(group);
        else if (outcome?.kind === 'pick' && group.files.some((f) => f.path === outcome.path)) {
          steps.push({ group, remove: group.files.filter((f) => f.path !== outcome.path).map((f) => f.path) });
        }
        // skipped while sorting by hand: kept, and on the duplicates list only when told so there
        else if (outcome?.kind === 'skip' && outcome.remember) keep.push({ group, kept: group.files });
        // never sorted: left as it is
      }
    }
    return { steps, keep };
  }

  /**
   * Remove what was chosen, on a page of its own, set by set; nothing to remove or ask about
   * goes straight on. A set it cannot tell stops the bar and asks (`askAbout`).
   */
  protected async applyDuplicates(): Promise<void> {
    const store = this.store();
    if (this.busy()) return;
    const plan = this.duplicatePlan();
    if (plan.keep.length) {
      try {
        // a held-back file is not one the duplicates list can find next time (its number cannot
        // be read from its name), so it goes on the files list too, or the rename step would
        // offer it again and it would clash again
        const held = plan.keep.flatMap((k) => k.kept.filter((f) => this.isClashFile(f)));
        if (this.sandbox()) {
          this.note(`duplicates list: ${plan.keep.map((k) => k.group.key).join(', ')}`);
          if (held.length) this.note(`files list: ${held.map((f) => f.name).join(', ')}`);
        } else {
          await this.imports.excludeDuplicates(plan.keep);
          if (held.length) await this.imports.excludeFiles(held);
        }
      } catch {
        // not written: they are offered again next time, which loses nothing
      }
    }
    if (!store || !plan.steps.length) {
      this.step.set(this.afterDuplicatesStep());
      return;
    }
    this.step.set('removing');
    const result: RemovingResult = { removed: [], failed: [] };
    this.removed.set(result);
    this.undecided.set([]);
    this.guessed.set([]);
    this.unguessable.set([]);
    this.timedOut.set(new Set());
    this.standing.set(null);
    this.removing.set(true);
    this.stopRemoving = false;
    const renamed: DatingResult = { renamed: [], failed: [] };
    this.clashRenamed.set(null);
    // a set still to ask about counts as all but one of its files, until the answer says
    let total = plan.steps.reduce((n, x) => n + ('remove' in x ? x.remove.length : x.group.files.length - 1), 0);
    let done = 0;
    this.removeProgress.set({ done, total });
    for (const [index, item] of plan.steps.entries()) {
      if (this.stopRemoving) break;
      let paths: string[];
      if ('remove' in item) {
        paths = item.remove;
      } else {
        const more = plan.steps.slice(index + 1).filter((x) => !('remove' in x)).length;
        const answer = await this.askAbout(item.group, more);
        if (this.stopRemoving) break;
        if (answer.how === 'keep') {
          this.undecided.update((u) => [...u, item.group]);
          total -= item.group.files.length - 1;
          this.removeProgress.set({ done, total });
          continue;
        }
        const kept =
          answer.how === 'guess'
            ? this.guessFor(item.group)
            : (item.group.files.find((f) => f.path === answer.path) ?? null);
        if (!kept) {
          // no best guess could be made (or the file chosen is gone): nothing deleted, said at the end
          this.unguessable.update((u) => [...u, item.group]);
          total -= item.group.files.length - 1;
          this.removeProgress.set({ done, total });
          continue;
        }
        if (answer.how === 'guess') this.guessed.update((g) => [...g, { group: item.group, kept }]);
        paths = item.group.files.filter((f) => f !== kept).map((f) => f.path);
      }
      const before = done;
      await removeFiles(
        store,
        paths,
        (d) => this.removeProgress.set({ done: before + d, total }),
        () => this.stopRemoving,
        result,
      );
      done = before + paths.length;
      await this.renameKeptClash(store, item.group, paths, renamed);
    }
    this.removedPaths.set(new Set([...result.removed, ...renamed.renamed.map((r) => r.from)]));
    this.removed.set({ ...result });
    this.clashRenamed.set({ ...renamed });
    this.removing.set(false);
    if (renamed.renamed.length) {
      // taken in as the rename step's are: the window's close hands them back, and the lists follow
      this.dated.update((d) => ({ renamed: [...(d?.renamed ?? []), ...renamed.renamed], failed: [...(d?.failed ?? [])] }));
      if (!this.sandbox()) {
        try {
          await this.imports.renamed(renamed.renamed);
        } catch {
          // the next read catches up
        }
      } else this.note(`renamed to the app's pattern: ${renamed.renamed.length} files`);
    }
    // the listing and what was found are brought up to date, so no removed file is offered again
    const changed = [...result.removed, ...renamed.renamed.flatMap((r) => [r.from, r.to])];
    if (changed.length && !this.sandbox()) {
      try {
        await this.library.refreshAfterRun(changed, store);
      } catch {
        // the next read catches up
      }
      void this.imports.check();
    }
  }

  /** the files held back by the rename step that were kept here, and renamed to the app's pattern */
  protected readonly clashRenamed = signal<DatingResult | null>(null);

  /**
   * Once a set's other files are gone, the one kept takes the name it was held back from, if it
   * is a file the rename step held back - the name the rename step gave it (dated only when its
   * own name had a date: dating comes after). Never over a file: a file not removed keeps it
   * from being renamed, and that is said.
   */
  private async renameKeptClash(store: LibraryStore, group: DuplicateGroup, removedNow: string[], renamed: DatingResult): Promise<void> {
    const renameTo = this.clashes().renameTo;
    const gone = new Set(removedNow);
    const kept = group.files.filter((f) => !gone.has(f.path) && f.path in renameTo);
    if (kept.length !== 1 || this.stopRemoving) return;
    await dateFiles(store, [{ path: kept[0].path, to: renameTo[kept[0].path] }], () => undefined, () => false, renamed);
  }

  /**
   * Stop on a set whose most recent cannot be told and ask what to do: choose the file here, a
   * best guess (`bestGuessOf`), or keep them all - and, with more like it to come, whether to
   * do the same for those. An answer given for the others is followed without asking (a
   * remembered *choose* still shows the files). No answer within `answerWaitMs` keeps every
   * file of this set, which deletes nothing, and the next is asked again.
   */
  private askAbout(group: DuplicateGroup, more: number): Promise<{ how: UndecidedHow; path?: string }> {
    const standing = this.standing();
    const guess = this.guessFor(group);
    // a standing best guess stops again for a set no guess can be made for
    if (standing === 'keep' || (standing === 'guess' && guess)) return Promise.resolve({ how: standing });
    return new Promise((resolve) => {
      this.asking.set(group);
      // the bar has stopped until this is answered
      this.chime.waiting();
      // a best guess is picked to begin with - or choosing, when none can be made, or a
      // standing choose, which shows the files straight away
      this.askHow.set(standing === 'choose' || !guess ? 'choose' : 'guess');
      this.askPick.set('');
      this.askMore.set(more);
      this.answered = (how, path) => {
        if (this.answerTimer) clearTimeout(this.answerTimer);
        this.answerTimer = null;
        this.answered = null;
        this.asking.set(null);
        resolve({ how, path });
      };
      this.answerTimer = setTimeout(() => {
        this.timedOut.update((t) => new Set([...t, group.key]));
        this.answered?.('keep');
      }, this.answerWaitMs());
    });
  }

  /** this set's answer - and with `toAll`, every set like it still to come, asked no more */
  protected answerAsked(toAll = false): void {
    const how = this.askHow();
    if (!this.askReady() || !how || !this.answered) return;
    // choosing by hand is answered set by set: there is no standing *choose*
    if (this.standing() === null && toAll && how !== 'choose') this.standing.set(how);
    this.answered(how, how === 'choose' ? this.askPick() : undefined);
  }

  /** after the duplicates: the dates, when anything is undated, then the index question */
  private afterDuplicatesStep(): Step {
    return this.undated().length ? 'dates' : this.afterDatesStep();
  }

  protected fromRemoving(): void {
    this.step.set(this.afterDuplicatesStep());
  }

  // endregion

  // region dates

  /** the date typed or inferred for each undated file, by path; '' is none */
  protected readonly dates = signal<Record<string, string>>({});
  /** the files to leave undated, by path */
  protected readonly skipped = signal<Record<string, boolean>>({});
  /**
   * The files to repair from AO3, by path: replaced in the run with AO3's latest version, named
   * with its date - the way to date a file nobody can (`repair` in the request). A row is dated,
   * skipped or repaired, never two at once.
   */
  protected readonly repairing = signal<Record<string, boolean>>({});
  /**
   * What happens to a file to repair that AO3 will not give - agreed here, before the run: kept
   * (to begin with); replaced with FicHub's copy when dated the same as or later than a date
   * guessed from the file's name (`replace`); or kept and named with FicHub's date for the work,
   * never over another file (`rename`).
   */
  protected readonly repairFallback = signal<'keep' | 'replace' | 'rename'>('keep');
  /**
   * Under each FicHub choice, its two answers: a file whose name looks dated no later than
   * FicHub's copy, and one with no date to guess. A name that looks newer is never touched.
   */
  protected readonly renameOlder = signal(true);
  protected readonly renameUndated = signal(true);
  protected readonly replaceOlder = signal(true);
  protected readonly replaceUndated = signal(false);
  /** where AO3 has the work: overwrite and rename (to begin with), or only rename the file */
  protected readonly repairAo3 = signal<'overwrite' | 'rename'>('overwrite');
  /** before AO3 is asked: name each file with the last-updated date its work's FicFairy index
   *  entry has, where it has one - off to begin with */
  protected readonly indexFirst = signal(false);
  /** with `indexFirst`: the files the index has no date for are left as they are - nothing is
   *  asked of AO3 or FicHub for them, so the choices for those are not shown */
  protected readonly skipAo3Check = signal(false);
  /** the AO3 and FicHub choices apply: some files may still go to a run */
  protected readonly asksAo3 = computed(() => !(this.indexFirst() && this.skipAo3Check()));
  /** files to repair whose work's index entry has a last-updated date, by path: that date */
  protected readonly indexDates = computed(() => {
    const entries = this.library.worksById();
    const dates: Record<string, string> = {};
    for (const file of this.toRepair()) {
      const record = entries.get(file.id) as { date_updated?: string } | undefined;
      const date = dateStamp(String(record?.date_updated ?? ''));
      if (isFileDate(date)) dates[file.path] = date;
    }
    return dates;
  });
  protected readonly indexDateCount = computed(() => Object.keys(this.indexDates()).length);
  /** the files repaired from the index, when that was chosen: renamed here, never sent to a run */
  protected readonly fromIndexRepairs = computed(() =>
    this.indexFirst() ? this.toRepair().filter((f) => this.indexDates()[f.path]) : []);
  /** the files the run repairs from AO3, then FicHub */
  protected readonly runRepairs = computed(() => {
    if (!this.asksAo3()) return [];
    const done = new Set(this.fromIndexRepairs().map((f) => f.path));
    return this.toRepair().filter((f) => !done.has(f.path));
  });
  /** files repaired from the index that were not renamed: the name each would get is taken */
  protected readonly indexClashes = signal<{ path: string; wanted: string }[]>([]);
  /** the files whose date `Infer date` set, and has not been changed by hand since */
  protected readonly inferred = signal<Record<string, boolean>>({});
  /** the rows' order, by path - by name, until `Infer date` moves what it dated to the top */
  protected readonly order = signal<string[] | null>(null);
  protected readonly bulkDate = signal('');
  /** Bulk actions' *Choose my own date...* open: the date and its button, shown in place */
  protected readonly pickingDate = signal(false);
  /** the skipped files go on the dates list, never to be offered for dating again */
  protected readonly rememberSkips = signal(false);
  protected readonly inferring = signal(false);
  /** what the last `Infer date` found: how many it dated, or null before it has run */
  protected readonly inferredCount = signal<number | null>(null);
  protected readonly paged = signal(true);
  protected readonly page = signal(0);
  protected readonly pageSize = DATES_PAGE_SIZE;

  protected readonly rows = computed(() => {
    const byPath = new Map(this.undated().map((f) => [f.path, f]));
    const order = this.order() ?? this.undated().map((f) => f.path);
    return order.map((path) => byPath.get(path)).filter((f): f is FoundFile => !!f);
  });
  protected readonly pages = computed(() => Math.max(1, Math.ceil(this.rows().length / this.pageSize)));
  protected readonly shownRows = computed(() =>
    this.paged()
      ? this.rows().slice(this.page() * this.pageSize, (this.page() + 1) * this.pageSize)
      : this.rows(),
  );

  protected dateOf(file: FoundFile): string {
    return this.dates()[file.path] ?? '';
  }

  protected isSkipped(file: FoundFile): boolean {
    return !!this.skipped()[file.path];
  }

  protected isRepaired(file: FoundFile): boolean {
    return !!this.repairing()[file.path];
  }

  protected isInferred(file: FoundFile): boolean {
    return !!this.inferred()[file.path];
  }

  /** a date set by hand: no longer one `Infer date` worked out, though the row stays put */
  protected setDate(file: FoundFile, date: string): void {
    this.dates.update((d) => ({ ...d, [file.path]: date }));
    this.inferred.update((x) => ({ ...x, [file.path]: false }));
  }

  protected setSkipped(file: FoundFile, skip: boolean): void {
    this.skipped.update((s) => ({ ...s, [file.path]: skip }));
    if (skip) this.repairing.update((r) => ({ ...r, [file.path]: false }));
  }

  protected setRepaired(file: FoundFile, repair: boolean): void {
    this.repairing.update((r) => ({ ...r, [file.path]: repair }));
    if (repair) this.skipped.update((s) => ({ ...s, [file.path]: false }));
  }



  /**
   * The bulk row's four actions each answer only the **remaining** rows - those with no date,
   * no Skip tick and no Repair tick (`needsAnswer`) - so nothing already answered is changed.
   */
  /** the one date put in every remaining row */
  protected dateRemaining(): void {
    const date = this.bulkDate();
    if (!isFileDate(date)) return;
    const left = this.needsAnswer();
    this.dates.update((d) => ({ ...d, ...Object.fromEntries(left.map((f) => [f.path, date])) }));
    this.inferred.update((x) => ({ ...x, ...Object.fromEntries(left.map((f) => [f.path, false])) }));
    this.pickingDate.set(false);
  }

  /** Skip ticked on every remaining row */
  protected skipRemaining(): void {
    const left = this.needsAnswer();
    this.skipped.update((s) => ({ ...s, ...Object.fromEntries(left.map((f) => [f.path, true])) }));
  }

  /**
   * Read a date out of each remaining file's name (`inferDate`). What it dated goes to the top,
   * by name, then the rest by name; a row already answered keeps its answer and its mark.
   */
  protected async inferDates(): Promise<void> {
    if (this.inferring()) return;
    this.inferring.set(true);
    try {
      // a breath for the spinner, and another every so often over a long list
      await new Promise((resolve) => setTimeout(resolve, 0));
      const found: Record<string, string> = {};
      const files = this.undated();
      const left = this.needsAnswer();
      for (const [index, file] of left.entries()) {
        const date = inferDate(file.name);
        if (date) found[file.path] = date;
        if (index % 200 === 199) await new Promise((resolve) => setTimeout(resolve, 0));
      }
      this.dates.update((d) => ({ ...d, ...found }));
      this.inferred.update((x) => ({ ...x, ...Object.fromEntries(Object.keys(found).map((path) => [path, true])) }));
      const byName = (a: FoundFile, b: FoundFile) => a.name.localeCompare(b.name);
      const dated = files.filter((f) => found[f.path]);
      this.order.set([
        ...dated.sort(byName),
        ...files.filter((f) => !found[f.path]).sort(byName),
      ].map((f) => f.path));
      this.inferredCount.set(dated.length);
      this.page.set(0);
    } catch {
      this.inferredCount.set(0);
    } finally {
      this.inferring.set(false);
    }
  }

  /** the files that will be renamed: given a real date, and neither skipped nor repaired */
  protected readonly toDate = computed(() =>
    this.undated().filter((f) => !this.skipped()[f.path] && !this.repairing()[f.path] &&
      isFileDate(this.dates()[f.path] ?? '')),
  );
  /** the files the run is to repair from AO3 */
  protected readonly toRepair = computed(() => this.undated().filter((f) => this.repairing()[f.path]));
  /** every file ticked Skip: the page's button then says the step is skipped, else Continue */
  protected readonly allSkippedDates = computed(() =>
    this.undated().length > 0 && this.undated().every((f) => this.skipped()[f.path]));
  protected readonly anySkipped = computed(() => this.undated().some((f) => this.skipped()[f.path]));

  /** Skip unticked on every row, leaving dates and repairs as they are */
  protected untickAllSkips(): void {
    this.skipped.set({});
  }
  protected readonly bulkValid = computed(() => isFileDate(this.bulkDate()));
  /**
   * Rows neither given a date nor ticked Skip. Continue waits on them, so a file is never left
   * undated by a date box someone missed: each has to be dated or skipped on purpose.
   */
  protected readonly needsAnswer = computed(() =>
    this.undated().filter((f) => !this.skipped()[f.path] && !this.repairing()[f.path] &&
      !isFileDate(this.dates()[f.path] ?? '')),
  );

  protected needsAnswerFor(file: FoundFile): boolean {
    return !this.isSkipped(file) && !this.isRepaired(file) && !isFileDate(this.dateOf(file));
  }

  /** Repair from AO3 ticked on every remaining row */
  protected repairRemaining(): void {
    const left = this.needsAnswer();
    this.repairing.update((r) => ({ ...r, ...Object.fromEntries(left.map((f) => [f.path, true])) }));
  }


  protected setPaged(paged: boolean): void {
    this.paged.set(paged);
    this.page.set(Math.min(this.page(), this.pages() - 1));
  }

  // endregion

  // region dating

  protected readonly datingProgress = signal<{ done: number; total: number }>({ done: 0, total: 0 });
  protected readonly dating = signal(false);
  protected readonly dated = signal<DatingResult | null>(null);
  private stopDating = false;

  // endregion

  // region index and formats

  /** the works with no index entry: look them up now, later, or never offer them again */
  protected readonly lookup = signal<'yes' | 'later' | 'never'>('yes');
  /** which works the formats and replacing are for; `skip` does neither */
  protected readonly updateScope = signal<UpdateScope>('all');
  /** which fics the nested choice last named, so fetching again after a skip comes back to it */
  private readonly lastScope = signal<UpdateScope>('all');
  protected chooseScope(scope: UpdateScope): void {
    this.lastScope.set(scope);
    this.updateScope.set(scope);
  }
  /** *Try and fetch the latest version*: back to whichever fics were last chosen */
  protected fetchLatest(): void {
    this.updateScope.set(this.lastScope());
  }
  /** *Overwrite existing downloads*: fetch every dated copy again, current or not */
  protected readonly overwrite = signal(false);
  /** the formats to fetch for works without them - none ticked to begin with */
  protected readonly picked = signal<string[]>([]);
  /** every downloadable format the helper offers, JSON aside (always written: it is the index) */
  protected readonly offered = computed(() => this.formats().filter((x) => x !== 'JSON'));
  /** the formats the found files are already in, so the page can say so */
  protected readonly held = computed(() => {
    const held = new Set<string>();
    for (const file of [...this.works().flatMap((w) => w.files), ...this.undatedElsewhere()]) {
      held.add(file.format.toUpperCase());
    }
    return held;
  });

  /** the works with no index entry that are looked up now */
  /** works with no index entry that a repair from AO3 indexes anyway - not asked about */
  protected readonly repairIndexes = computed(() => {
    const repaired = new Set(this.runRepairs().map((f) => f.id));
    return this.works().filter((w) => repaired.has(w.id));
  });
  /** the works with no index entry that the index page asks about */
  protected readonly toLookUp = computed(() => {
    const repaired = new Set(this.repairIndexes().map((w) => w.id));
    if (this.focus()) {
      // the works asked about on the index page, and any the formats page is to update - a work
      // has to be indexed before it can be updated (the raw scope: the chosen one reads this)
      const chosen = [...this.worksFor(this.lookupFor()),
        ...(this.updateScope() !== 'skip' ? this.worksFor(this.updateFor()) : [])];
      const seen = new Set<string>();
      return chosen.filter((w) => !seen.has(w.id) && !!seen.add(w.id));
    }
    return this.works().filter((w) => !repaired.has(w.id));
  });
  /** opened for a work's own look-up: which works the formats page updates */
  protected readonly updateFor = signal<'this' | 'all' | 'ignored'>('this');
  /** the works one of the look-up's choices stands for */
  private worksFor(choice: 'this' | 'all' | 'ignored'): FoundWork[] {
    const focus = new Set(this.focus() ?? []);
    if (choice === 'this') {
      const seen = new Set<string>();
      return [...this.works(), ...this.ignored()].filter((w) => focus.has(w.id) && !seen.has(w.id) && !!seen.add(w.id));
    }
    if (choice === 'all') return this.works();
    const ids = new Set(this.works().map((w) => w.id));
    return [...this.works(), ...this.ignored().filter((w) => !ids.has(w.id))];
  }
  /** every work with no index entry, for the *all* choice's count when opened for one work */
  protected readonly allUnindexed = computed(() => this.works().length);
  /** those and every one an exclusion list keeps out, for the choice that takes them all */
  protected readonly withIgnored = computed(() => {
    const ids = new Set(this.works().map((w) => w.id));
    return this.works().length + this.ignored().filter((w) => !ids.has(w.id)).length;
  });
  // opened for a work's own look-up, the answer is yes: the question is not asked
  protected readonly lookups = computed(() =>
    (this.focus() || this.lookup() === 'yes' ? this.toLookUp().map((w) => w.id) : []));
  /**
   * The works with date issues that can be updated: an undated file, of an indexed work or of
   * one looked up now - a work left unindexed is left alone altogether.
   */
  protected readonly dateIssues = computed(() => {
    // opened for one work's lookup, the dates were passed over: only the index is in question
    if (this.focus()) return [];
    const looked = new Set(this.lookups());
    const indexed = new Set(this.works().map((w) => w.id));
    // a file of a work left out of the index question is dated, never looked up for an update
    const files = this.undated().filter((f) => !f.unindexed && (!indexed.has(f.id) || looked.has(f.id)));
    return [...new Set(files.map((f) => f.id))];
  });
  /** the works with an index issue that can be updated: those looked up now */
  protected readonly indexIssues = computed(() => this.lookups());
  /** every work with an issue that can be updated */
  protected readonly allIssues = computed(() => [...new Set([...this.indexIssues(), ...this.dateIssues()])]);
  /** the scope chosen, or every work when the one chosen is no longer offered */
  protected readonly scopeChosen = computed<UpdateScope>(() => {
    const scope = this.updateScope();
    if (scope === 'dates' && !this.dateIssues().length) return 'all';
    if (scope === 'index' && !this.indexIssues().length) return 'all';
    return scope;
  });
  /** the works the formats and replacing are for */
  protected readonly updating = computed(() => {
    if (this.focus()) {
      return this.scopeChosen() === 'skip' ? [] : this.worksFor(this.updateFor()).map((w) => w.id);
    }
    switch (this.scopeChosen()) {
      case 'dates':
        return this.dateIssues();
      case 'index':
        return this.indexIssues();
      case 'skip':
        return [];
      default:
        return this.allIssues();
    }
  });
  /** whether anything is downloaded or replaced: an update chosen, and something to do */
  protected readonly updates = computed(
    // an update always replaces a copy AO3 or FicHub has a newer version of than the date in its
    // name, so choosing which fics to update is enough
    () => this.updating().length > 0,
  );
  /** the works a run is over: those looked up, those updated, and those with a file to repair */
  protected readonly scope = computed(() => {
    const ids = new Set<string>(this.lookups());
    if (this.updates()) for (const id of this.updating()) ids.add(id);
    for (const file of this.runRepairs()) ids.add(file.id);
    return [...ids].map((id) => ({ id, files: [] }));
  });
  /** how many files the window knows of for these works - the copies a replacing run might fetch again */
  private filesOf(ids: Iterable<string>): number {
    const wanted = new Set(ids);
    const paths = new Set<string>();
    for (const w of this.works()) if (wanted.has(w.id)) for (const f of w.files) paths.add(f.path);
    for (const f of this.undatedElsewhere()) if (wanted.has(f.id)) paths.add(f.path);
    return paths.size;
  }
  /** whether there is anything for a run to do: a lookup, or an update */
  protected readonly runs = computed(() => this.scope().length > 0);

  protected toggleFormat(format: string, on: boolean): void {
    this.picked.update((p) => (on ? [...new Set([...p, format])] : p.filter((x) => x !== format)));
  }

  // endregion

  // region moving between pages

  /** the first page's answer: repair now (ticked to begin with), later, never for these files, or never at all */
  protected readonly firstChoice = signal<'repair' | 'later' | 'exclude' | 'never' | null>('repair');

  protected async fromOverview(): Promise<void> {
    switch (this.firstChoice()) {
      case 'repair':
        if (this.busy()) return;
        // files a download was left part-way through replacing come first of all
        if (this.leftovers().length && !this.leftoversDone()) {
          this.step.set('leftovers');
          return;
        }
        await this.afterLeftovers();
        return;
      case 'exclude':
        return this.fromOverviewExclude();
      case 'never':
        this.askAgainChanged.emit(false);
        this.closed.emit(null);
        return;
      case 'later':
        this.remindLater.emit();
        this.closed.emit(null);
        return;
    }
  }

  // region files left part-way through being replaced

  /** files a download replacing them was left part-way through (`swapLeftovers`) */
  readonly leftovers = input<SwapLeftover[]>([]);
  /** put right on their page: not asked about again in this window */
  protected readonly leftoversDone = signal(false);
  protected readonly leftoversBusy = signal(false);
  /** what tidying did: how many put back and removed, and what would not go */
  protected readonly leftoversResult = signal<{ restored: number; removed: number; failed: string[] } | null>(null);
  protected readonly leftoverAction = leftoverAction;
  protected readonly leftoverName = (path: string) => path.split('/').pop() ?? path;

  /**
   * Put back every copy set aside with nothing in its place, and remove what is left over beside
   * a file - an unfinished new copy, or an old one the swap had finished replacing. Renames never
   * write over a file, so a copy put back cannot land on another.
   */
  protected async tidyLeftovers(): Promise<void> {
    const store = this.store();
    if (!store || this.busy() || this.leftoversBusy()) return;
    this.leftoversBusy.set(true);
    const result = { restored: 0, removed: 0, failed: [] as string[] };
    const changed: string[] = [];
    for (const leftover of this.leftovers()) {
      try {
        if (leftoverAction(leftover) === 'restore') {
          // the copy in its place may not be whole: yours always wins, so it goes first
          if (leftover.inPlace) {
            if (this.sandbox()) this.note(`removed: ${leftover.path}`);
            else await patiently(() => store.delete(leftover.path));
            result.removed++;
          }
          if (this.sandbox()) this.note(`put back: ${leftover.old} -> ${leftover.path}`);
          else await patiently(() => store.rename(leftover.old!, leftover.path));
          changed.push(leftover.old!, leftover.path);
          result.restored++;
        }
        if (leftover.fresh) {
          if (this.sandbox()) this.note(`removed: ${leftover.fresh}`);
          else await patiently(() => store.delete(leftover.fresh!));
          changed.push(leftover.fresh);
          result.removed++;
        }
      } catch {
        result.failed.push(this.leftoverName(leftover.path));
      }
    }
    if (changed.length && !this.sandbox()) await this.library.refreshAfterRun(changed, store);
    this.leftoversResult.set(result);
    this.visit.note(`Resolve issues: files left mid-download - put back ${result.restored}, removed ${result.removed}` +
      (result.failed.length ? `, ${result.failed.length} could not be tidied` : ''));
    this.leftoversDone.set(true);
    this.leftoversBusy.set(false);
  }

  /** passed over, or put right: on to the rest of the window */
  protected async fromLeftovers(skip: boolean): Promise<void> {
    if (skip) {
      this.leftoversDone.set(true);
      this.visit.note(`Resolve issues: ${this.leftovers().length} file(s) left mid-download passed over`);
    }
    await this.afterLeftovers();
  }

  /** the repair, from its first ordinary step: renaming, the duplicates, or the dates and on */
  private async afterLeftovers(): Promise<void> {
    // nothing else was found: the window is done
    if (!this.misnamedFound().formats.length && !this.groups().length && !this.undated().length &&
        !this.toLookUp().length && !this.allIssues().length) {
      this.closed.emit(this.dated());
      return;
    }
    if (this.misnamedFound().formats.length) {
      await this.toRename();
      return;
    }
    this.step.set(this.groups().length ? 'duplicates' : this.afterDuplicatesStep());
  }

  // endregion

  /** 'No, do not ask me again for these files': every file found goes on the files list */
  private async fromOverviewExclude(): Promise<void> {
    try {
      const files = new Map<string, FoundFile>();
      for (const file of [
        ...this.works().flatMap((w) => w.files),
        ...this.undatedElsewhere(),
        ...this.groups().flatMap((g) => g.files),
      ]) files.set(file.path, file);
      // a file named another way has no number the app reads: it is listed by name alone
      for (const file of this.misnamedFound().formats.flatMap((f) => f.files)) {
        files.set(file.path, { id: file.worknum, path: file.path, name: file.name, format: file.format, date: '' });
      }
      if (this.sandbox()) this.note(`files list: ${[...files.values()].map((f) => f.name).join(', ')}`);
      else await this.imports.excludeFiles([...files.values()]);
    } catch {
      // not written: offered again next time, which loses nothing
    }
    this.closed.emit(null);
  }

  /** after the dates: the index question, when there are works without an entry */
  private afterDatesStep(): Step {
    return this.toLookUp().length ? 'index' : 'formats';
  }

  /** after the dates and their renaming: the repair page when files are to be repaired */
  private afterDating(): Step {
    return this.toRepair().length ? 'repair' : this.afterDatesStep();
  }

  /**
   * From the dates: the files given a date are renamed at once, on a page of its own; the repair
   * page comes after, then the index and formats. Files repaired from the FicFairy index are
   * renamed last of all, once every question is answered (`finish`)
   */
  protected async fromDates(): Promise<void> {
    if (this.needsAnswer().length) return;
    const skipped = this.undated().filter((f) => this.skipped()[f.path]);
    if (this.rememberSkips() && skipped.length && !this.busy()) {
      try {
        if (this.sandbox()) this.note(`dates list: ${skipped.map((f) => f.name).join(', ')}`);
        else await this.imports.excludeDating(skipped);
      } catch {
        // not written: they are offered for dating again next time, which loses nothing
      }
    }
    const chosen = this.toDate();
    if (!chosen.length || !this.store() || this.busy()) {
      this.step.set(this.afterDating());
      return;
    }
    await this.renameWithDates(chosen, 'dates');
  }

  protected fromRepair(): void {
    this.step.set(this.afterDatesStep());
  }

  /** which renaming the dating page is showing: the dates given, or the repairs from the index */
  protected readonly datingRound = signal<'dates' | 'index'>('dates');
  /** what the renaming on show did - `dated` holds every rename the window has made */
  protected readonly round = signal<DatingResult | null>(null);
  /** the repairs from the FicFairy index have been renamed (or tried), so `finish` goes on */
  private readonly indexRepaired = signal(false);

  /** rename these files with their dates, on the dating page; the cross stops it after the one in hand */
  private async renameWithDates(chosen: FoundFile[], which: 'dates' | 'index'): Promise<void> {
    const store = this.store();
    if (!store) return;
    this.datingRound.set(which);
    this.step.set('dating');
    this.dating.set(true);
    this.stopDating = false;
    const result: DatingResult = { renamed: [], failed: [] };
    this.round.set(result);
    this.datingProgress.set({ done: 0, total: chosen.length });
    const entries = this.library.worksById();
    const indexDates = this.indexDates();
    const items: ToDate[] = chosen.map((file) => ({
      file,
      date: which === 'index' ? indexDates[file.path] : this.dates()[file.path],
      record: entries.get(file.id) as object | undefined,
    }));
    // the helper names every file, by the app's own pattern - the page only falls back to
    // adding the date to the end when it does not answer
    const named = await renamesFor(items, (files) => this.jobs.fileNames(files));
    // a repair from the index never lands on another file's name: held back and listed
    const renames = which === 'index'
      ? await this.holdIndexClashes(store, named, new Set(chosen.map((f) => f.path)))
      : named;
    await dateFiles(
      store,
      renames,
      (done, total) => this.datingProgress.set({ done, total }),
      () => this.stopDating,
      result,
    );
    // a renamed file keeps its place on the exclusion lists - on the index list above all, where
    // a name no longer recorded would ask about its work again - written at once, not on close
    if (result.renamed.length) {
      try {
        if (this.sandbox()) this.note(`renamed in the lists: ${result.renamed.length} files`);
        else await this.imports.renamed(result.renamed);
      } catch {
        // not written: that work's index question may be asked again, which loses nothing
      }
    }
    this.round.set({ ...result });
    this.dated.update((d) => ({
      renamed: [...(d?.renamed ?? []), ...result.renamed],
      failed: [...(d?.failed ?? []), ...result.failed],
    }));
    this.dating.set(false);
  }

  /**
   * The index repairs whose new name is already a file's, or another file's new name in the
   * same batch, taken out of the renames and listed (`indexClashes`) - both files kept.
   */
  private async holdIndexClashes(store: LibraryStore, renames: Rename[], repairs: Set<string>): Promise<Rename[]> {
    this.indexClashes.set([]);
    if (!repairs.size) return renames;
    let listed: string[] = [];
    try {
      listed = await store.list(WORKS_FOLDER, false);
    } catch {
      // not listed: a rename over a file is still refused by the store, and said as a failure
    }
    const taken = new Set(listed.map((p) => p.toLowerCase()));
    const wanted = new Map<string, number>();
    for (const r of renames) if (r.to !== r.path) wanted.set(r.to.toLowerCase(), (wanted.get(r.to.toLowerCase()) ?? 0) + 1);
    const held: { path: string; wanted: string }[] = [];
    const clear = renames.filter((r) => {
      const to = r.to.toLowerCase();
      if (!repairs.has(r.path) || r.to === r.path) return true;
      if (taken.has(to) || (wanted.get(to) ?? 0) > 1) {
        held.push({ path: r.path, wanted: r.to });
        return false;
      }
      return true;
    });
    this.indexClashes.set(held);
    return clear;
  }

  protected fromDating(): void {
    if (this.datingRound() === 'index') void this.finish();
    else this.step.set(this.afterDating());
  }

  /** the formats page only when some work could be updated; with none, the window is done */
  protected fromIndex(): void {
    if (this.allIssues().length) this.step.set('formats');
    else this.finish();
  }

  protected backFrom(step: 'dates' | 'repair' | 'index' | 'formats'): void {
    // the repair page is only choices, so it can always be gone back to; the dates only while
    // nothing has been renamed yet
    const beforeIndex: Step = this.toRepair().length ? 'repair'
      : this.dated() ? 'overview' : this.undated().length ? 'dates' : 'overview';
    if (step === 'dates') this.step.set(this.groups().length && !this.removed() ? 'duplicates' : 'overview');
    else if (step === 'repair') this.step.set(this.dated() ? 'overview' : 'dates');
    else if (step === 'index') this.step.set(beforeIndex);
    else this.step.set(this.toLookUp().length ? 'index' : beforeIndex);
  }

  /** no going back to the dates once files are renamed: they would be offered for dating again */
  protected readonly canGoBack = computed(() => !this.dated() && !this.removed()?.removed.length);

  /**
   * Done: works never to be offered again are written down, and a run - when there is anything
   * for one to do - is handed to the run window. Otherwise the window simply closes.
   */
  protected async finish(): Promise<void> {
    // the files repaired from the FicFairy index are renamed last, once every question is answered
    if (this.fromIndexRepairs().length && !this.indexRepaired() && this.store() && !this.busy()) {
      this.indexRepaired.set(true);
      await this.renameWithDates(this.fromIndexRepairs(), 'index');
      return;
    }
    if (this.lookup() === 'never' && this.toLookUp().length) {
      try {
        if (this.sandbox()) this.note(`index list: ${this.toLookUp().map((w) => w.id).join(', ')}`);
        else await this.imports.excludeFromIndex(this.toLookUp());
      } catch {
        // not written: they are offered again next time, which loses nothing
      }
    }
    if (!this.runs() || this.busy()) {
      this.closed.emit(this.dated());
      return;
    }
    const works = this.scope();
    const taken = new Set(works.map((w) => w.id));
    const updating = new Set(this.updates() ? this.updating() : []);
    const updates = this.updates();
    this.start.emit({
      request: {
        links: importLinks(works),
        count: works.length,
        filetypes: ['JSON', ...(updates ? this.picked() : [])],
        replaceOutdated: updates,
        overwrite: updates && this.overwrite(),
        // every work not updated is only looked up - one with a file to repair gets that alone
        indexOnly: [...taken].filter((id) => !updating.has(id)),
        lookups: this.lookups().filter((id) => taken.has(id)).length,
        scope: updates ? (this.focus() ? 'index' : this.scopeChosen()) : 'skip',
        files: this.filesOf(taken),
        repair: this.runRepairs().map((f) => f.name),
        repairFicHub: this.runRepairs().length > 0 && this.repairFallback() === 'replace',
        repairFicHubOlder: this.repairFallback() === 'rename' ? this.renameOlder()
          : this.repairFallback() === 'replace' ? this.replaceOlder() : true,
        repairFicHubUndated: this.runRepairs().length > 0 &&
          (this.repairFallback() === 'rename' ? this.renameUndated()
            : this.repairFallback() === 'replace' && this.replaceUndated()),
        repairFicHubRename: this.runRepairs().length > 0 && this.repairFallback() === 'rename',
        // FicHub keeps to the date guessed from each name: a name that looks newer is left alone
        repairFicHubCheck: true,
        repairRenameOnly: this.runRepairs().length > 0 && this.repairAo3() === 'rename',
      },
      dated: this.dated(),
    });
  }

  /** closing while files are being renamed stops after the one in hand; what was renamed stays */
  protected close(): void {
    this.stopRenaming = true;
    this.stopDating = true;
    this.stopRemoving = true;
    // a question waiting on the removing page is answered as the one that deletes nothing
    this.answered?.('keep');
    this.closed.emit(this.dated());
  }

  // endregion
}

/**
 * Why a file's change time could not be read, for the visit log: Dropbox's status and its short
 * error code, or only the error's kind otherwise - never its message, which could name a file.
 */
export function changeTimeProblem(error: unknown): string {
  if (error instanceof DropboxError) return `Dropbox ${error.status}${error.summary ? ` ${error.summary}` : ''}`;
  return error instanceof Error ? error.name : 'unknown error';
}
