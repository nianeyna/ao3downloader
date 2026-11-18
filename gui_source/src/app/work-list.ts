import { HIDE_WARNING_KEY } from './preferences';
import { LOOSE_PREFIX } from './unindexed-works';
import { Component, computed, inject, input, linkedSignal, signal } from '@angular/core';
import { WorkLink } from './work-link';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Library, LocalCopy, OPENABLE_FORMATS, OpenableFormat, copyName, hiddenKey, viewableInBrowser } from './library';
import { safeGet, safeSet } from './storage';
import { Jobs } from './jobs';
import { Collection, isCustomCollection } from './collections';
import { CollectionItems, CustomCollections, canCollect, canTick, itemsOf } from './custom-collections';
import { CollectionEditor } from './collection-editor';
import { TagFilter } from './tag-filter';
import { TagChoice, buildTagIndex, matchesTags } from './tags';
import {
  Bookmark,
  BookmarkType,
  authorLink,
  bookmarkTypeOf,
  chapterCount,
  dateStamp,
  isBookmarkEntry,
  isEntryComplete,
  isWorkEntry,
  ORIGINS,
  Origin,
  originOf,
  pageItems,
  paragraphs,
  placeholderWork,
  ratingClass,
  warningClass,
} from './bookmarks';

const PER_PAGE = 20;

/** the orderings the filter panel offers; '' is the order the folder was read in */
export type WorkSort =
  | ''
  | 'created-desc'
  | 'created-asc'
  | 'bookmarked-desc'
  | 'bookmarked-asc'
  | 'updated-desc'
  | 'updated-asc';

/** the date each sort orders by */
function sortField(sort: WorkSort): 'date_created' | 'date_bookmarked' | 'date_updated' {
  if (sort.startsWith('created')) return 'date_created';
  if (sort.startsWith('updated')) return 'date_updated';
  return 'date_bookmarked';
}

/**
 * How the works are listed until someone asks otherwise: most recently bookmarked first,
 * which is how ao3 shows your bookmarks. The index no longer keeps a listing position of
 * its own, so this is what puts the list in that order.
 */
export const DEFAULT_SORT: WorkSort = 'bookmarked-desc';

/**
 * A paginated listing of works, in ao3's own blurb style.
 *
 * This is the whole of the bookmarks page's table, and is reused as-is for the works
 * inside a collection - the two are the same listing over a different set of works.
 */
@Component({
  selector: 'app-work-list',
  host: { '(document:click)': 'closeMenu()', '(document:keydown.escape)': 'closeMenu()' },
  imports: [DecimalPipe, NgTemplateOutlet, CollectionEditor, TagFilter, WorkLink],
  styleUrl: './work-list.css',
  templateUrl: './work-list.html',
})
export class WorkList {
  private readonly library = inject(Library);

  readonly works = input.required<Bookmark[]>();
  /** whose listing this is, shown in the heading and on the bookmarker's section */
  readonly owner = input('');
  /** what the things being counted are called: '1 - 20 of 25 Bookmarks' */
  readonly label = input('Bookmarks');
  /** the Works tab's line under the heading: how many of the works listed are your bookmarks */
  readonly countBookmarks = input(false);
  readonly emptyMessage = input('This export has no works in it.');
  /** shown under the heading, above the listing */
  readonly note = input('');
  /** the library's first read is still going: the heading shows, no filters and no 'empty' yet */
  readonly loading = input(false);
  /** whether works can be ticked and put in a custom collection */
  readonly selectable = input(false);
  /** the collection being shown, when it is one: a custom one can have works taken out */
  readonly collection = input<Collection | null>(null);

  private readonly custom = inject(CustomCollections);

  protected readonly htmlFiles = this.library.htmlFiles;
  private readonly copies = this.library.copies;

  // What to narrow the listing to. All four are 'no opinion' when empty, so an untouched
  // panel shows everything - the filters are for finding something, not for hiding things
  // by default.
  protected readonly titleQuery = signal('');
  protected readonly authorQuery = signal('');
  protected readonly updatedFrom = signal('');
  protected readonly updatedTo = signal('');
  protected readonly bookmarkedFrom = signal('');
  protected readonly bookmarkedTo = signal('');
  /** one kind of bookmark only - works, series or external works - or '' for all of them */
  protected readonly typeFilter = signal<'' | BookmarkType>('');
  /** where a work came from - your bookmarks, a collection, anything else - or '' for all */
  protected readonly originFilter = signal<'' | Origin>('');
  /**
   * Works with a downloaded copy in one format, or with none at all ('none') - read from the
   * files in the library, by work number; '' for any.
   */
  protected readonly formatFilter = signal<'' | 'none' | OpenableFormat>('');
  protected readonly formats = OPENABLE_FORMATS;
  /** bookmarks you wrote a note on, and bookmarks you marked as a rec */
  protected readonly withNotes = signal(false);
  protected readonly recommended = signal(false);
  /** hidden works are left out unless this is ticked - and then shown, marked as hidden */
  protected readonly showHidden = signal(false);
  /** tags a work must carry, every one of them, and tags it must not carry - as on ao3 */
  protected readonly includeTags = signal<TagChoice[]>([]);
  protected readonly excludeTags = signal<TagChoice[]>([]);
  /**
   * Whether the Filter panel is open. The tag filters are only drawn while it is, so a listing
   * nobody filters never counts its tags.
   */
  protected readonly filtersOpen = signal(false);
  /** this listing's tags by kind, for the folds to tick from - rebuilt only when the works change */
  protected readonly listingTags = computed(() => buildTagIndex(this.works()));

  /**
   * The parts lists that are open. A series card is keyed by the series id; a work's
   * 'Part N of' line by the work and the series, so opening it on one card does not open it
   * on every other work of the same series.
   */
  protected readonly openSeries = signal<ReadonlySet<string>>(new Set());
  private readonly worksById = this.library.worksById;
  private readonly seriesById = this.library.seriesById;

  /**
   * How the listing is ordered. Empty keeps the order the folder was read in.
   *
   * A work with no date for the chosen field goes **last in both directions** - it cannot
   * be placed, and putting it first on an ascending sort would bury every dated work under
   * a pile of blanks.
   */
  protected readonly sortBy = signal<WorkSort>(DEFAULT_SORT);

  protected readonly filtering = computed(
    () =>
      !!(
        this.titleQuery().trim() ||
        this.authorQuery().trim() ||
        this.updatedFrom() ||
        this.updatedTo() ||
        this.bookmarkedFrom() ||
        this.bookmarkedTo() ||
        this.typeFilter() ||
        this.originFilter() ||
        this.formatFilter() ||
        this.withNotes() ||
        this.recommended() ||
        this.includeTags().length ||
        this.excludeTags().length
      ),
  );

  /** a sort narrows nothing, so it is not 'filtering' - but it is still something to clear */
  protected readonly anythingToClear = computed(() => this.filtering() || this.sortBy() !== DEFAULT_SORT
  );

  /**
   * The works this listing is actually showing.
   *
   * Every filter that has been filled in has to match - they narrow together rather than
   * widening, which is what someone hunting for one fic expects.
   *
   * **A work with no readable date is excluded by a date filter, not kept.** It cannot be
   * placed in the range, and including it would make the range a lie. With no date filter
   * set it is shown like anything else.
   */
  protected readonly filtered = computed(() => {
    const title = this.titleQuery().trim().toLowerCase();
    const author = this.authorQuery().trim().toLowerCase();
    const updatedFrom = this.updatedFrom();
    const updatedTo = this.updatedTo();
    const bookmarkedFrom = this.bookmarkedFrom();
    const bookmarkedTo = this.bookmarkedTo();
    const type = this.typeFilter();
    const include = this.includeTags();
    const exclude = this.excludeTags();
    const origin = this.originFilter();
    const format = this.formatFilter();
    const copies = this.copies();
    const withNotes = this.withNotes();
    const recommended = this.recommended();

    return this.visibleWorks().filter((work) => {
      if (type && bookmarkTypeOf(work) !== type) return false;
      if (origin && originOf(work) !== origin) return false;
      if (format) {
        // a series or an external work has no copy of its own to be downloaded as
        const id = isWorkEntry(work) ? work.id : null;
        const held = (f: OpenableFormat) => !!id && copies[f].has(id);
        if (format === 'none' ? !id || OPENABLE_FORMATS.some(held) : !held(format)) return false;
      }
      if (withNotes && !(work.bookmark_notes ?? '').trim()) return false;
      if (recommended && !work.bookmark_rec) return false;
      if (!matchesTags(work, include, exclude)) return false;
      if (title && !(work.title ?? '').toLowerCase().includes(title)) return false;
      if (author && !(work.authors ?? []).some((name) =>
        name.toLowerCase().includes(author))) return false;

      if (updatedFrom || updatedTo) {
        const updated = dateStamp(work.date_updated);
        if (!updated) return false;
        if (updatedFrom && updated < updatedFrom) return false;
        if (updatedTo && updated > updatedTo) return false;
      }

      if (bookmarkedFrom || bookmarkedTo) {
        const bookmarked = dateStamp(work.date_bookmarked);
        if (!bookmarked) return false;
        if (bookmarkedFrom && bookmarked < bookmarkedFrom) return false;
        if (bookmarkedTo && bookmarked > bookmarkedTo) return false;
      }

      return true;
    });
  });

  /**
   * A different set of works is a different listing, so it starts at its first page.
   *
   * Sourced on the filtered set rather than the input, so narrowing the listing also
   * goes back to page 1 - staying on page 9 of a result that now has two pages would
   * show an empty listing and look like the filter had found nothing.
   */
  /** the filtered works, in the order asked for */
  protected readonly sorted = computed(() => {
    const sort = this.sortBy();
    const works = this.filtered();
    if (!sort) return works;

    const field = sortField(sort);
    const ascending = sort.endsWith('asc');
    return works
      .map((work, at) => ({ work, at, stamp: dateStamp(work[field] ?? '') }))
      .sort((a, b) => {
        if (!a.stamp !== !b.stamp) return a.stamp ? -1 : 1;
        if (a.stamp !== b.stamp) {
          const order = a.stamp < b.stamp ? -1 : 1;
          return ascending ? order : -order;
        }
        // equal dates keep the order they were read in, so the sort is stable to look at
        return a.at - b.at;
      })
      .map((x) => x.work);
  });

  /**
   * Whether the chosen sort has nothing to sort on.
   *
   * Publication dates are only recorded by a per-work lookup this app does not run, so on
   * most libraries no work has one and a date-created sort changes nothing. Saying so beats
   * a control that silently does nothing.
   */
  protected readonly sortHasNoDates = computed(() => {
    const sort = this.sortBy();
    // the default is not something anyone chose, so it is not worth a note that it does
    // nothing - a collection of works you never bookmarked has no bookmark dates at all
    if (!sort || sort === DEFAULT_SORT) return false;
    const field = sortField(sort);
    return this.filtered().length > 0 &&
      !this.filtered().some((work) => dateStamp(work[field] ?? ''));
  });

  protected readonly page = linkedSignal<Bookmark[], number>({
    source: this.sorted,
    computation: () => 1,
  });

  protected readonly total = computed(() => this.filtered().length);
  /** how many there were before any filter, so the listing can say what it is hiding */
  protected readonly totalUnfiltered = computed(() => this.visibleWorks().length);
  /** your bookmarks among what is listed (hidden works left out, as the heading leaves them) */
  protected readonly bookmarkCount = computed(() => this.visibleWorks().filter(isBookmarkEntry).length);
  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PER_PAGE)));
  protected readonly pages = computed(() => pageItems(this.page(), this.totalPages()));

  protected readonly pageWorks = computed(() => {
    const start = (this.page() - 1) * PER_PAGE;
    return this.sorted().slice(start, start + PER_PAGE);
  });

  protected readonly rangeStart = computed(() =>
    this.total() === 0 ? 0 : (this.page() - 1) * PER_PAGE + 1,
  );
  protected readonly rangeEnd = computed(() => Math.min(this.page() * PER_PAGE, this.total()));

  /** how many of the listed works actually have a downloaded html file alongside them */
  // region where a work came from, and hiding works

  protected readonly origins = ORIGINS;
  protected readonly originOf = originOf;

  /**
   * The works this listing shows at all, before any filter: everything but what was hidden -
   * unless 'Show hidden works' is ticked. Hiding is not a filter someone set just now, so it
   * is not counted as one; the heading says how many are hidden instead.
   */
  private readonly visibleWorks = computed(() => {
    if (this.showHidden()) return this.works();
    const hidden = this.library.hidden();
    return hidden.size ? this.works().filter((w) => !w.id || !hidden.has(hiddenKey(w))) : this.works();
  });
  /** how many of this listing's works are hidden, said in the heading */
  protected readonly hiddenCount = computed(() => {
    const hidden = this.library.hidden();
    return hidden.size ? this.works().filter((w) => w.id && hidden.has(hiddenKey(w))).length : 0;
  });
  /** hiding is saved in the library, so only where the page can write to it */
  protected readonly canHide = computed(() => !!this.library.store());

  /** the works the 'are you sure' is about, while it is up - one, or every one ticked */
  protected readonly confirmingHide = signal<Bookmark[] | null>(null);
  protected readonly dontWarnAgain = signal(false);
  protected readonly hideProblem = signal('');

  protected isHidden(work: Bookmark): boolean {
    return !!work.id && this.library.hidden().has(hiddenKey(work));
  }

  /** what to call where a work came from, on its badge - nothing for your own bookmarks */
  protected originNote(work: Bookmark): string {
    switch (originOf(work)) {
      case 'collection': {
        const names = work.from_collections ?? [];
        return `From ${names.length === 1 ? 'the collection ' + names[0] : names.length + ' collections'}`;
      }
      case 'link':
        return 'Downloaded by ID or URL';
      case 'external':
        return 'Imported from an external source';
      default:
        return '';
    }
  }

  /** where an entry came from, worded as the Came from filter words it - the icon's name */
  protected originLabel(work: Bookmark): string {
    const origin = originOf(work);
    return 'Came from: ' + (ORIGINS.find((x) => x.origin === origin)?.label ?? '');
  }

  protected originTitle(work: Bookmark): string {
    switch (originOf(work)) {
      case 'collection':
        return `Not in your AO3 bookmarks - it is here because an indexed collection holds it: ${(work.from_collections ?? []).join(', ')}`;
      case 'link':
        return 'Not in your AO3 bookmarks - downloaded by its link or work number';
      case 'external':
        return 'Not in your AO3 bookmarks - its file was already in your library, and an import indexed it';
      default:
        return 'Not in your AO3 bookmarks - where it came from is not recorded, such as an imported index';
    }
  }

  /** the warning first, unless it has been turned off - then straight to hiding */
  protected askHide(work: Bookmark): void {
    this.hideProblem.set('');
    this.hidingTicked = false;
    if (safeGet(HIDE_WARNING_KEY) === 'off') {
      void this.doHide([work]);
      return;
    }
    this.dontWarnAgain.set(false);
    this.confirmingHide.set([work]);
  }

  protected async confirmHide(): Promise<void> {
    const works = this.confirmingHide();
    if (!works) return;
    if (this.dontWarnAgain()) safeSet(HIDE_WARNING_KEY, 'off');
    this.confirmingHide.set(null);
    await this.doHide(works);
  }

  /** nothing is hidden, and anything ticked stays ticked */
  protected cancelHide(): void {
    this.confirmingHide.set(null);
    this.hidingTicked = false;
  }

  protected async unhide(work: Bookmark): Promise<void> {
    this.hideProblem.set('');
    try {
      await this.library.unhide(work);
    } catch (error) {
      this.hideProblem.set(error instanceof Error ? error.message : String(error));
    }
  }

  /** whether the hide waiting on the warning is the ticked works, so a hide can clear them */
  private hidingTicked = false;

  private async doHide(works: Bookmark[]): Promise<void> {
    try {
      await this.library.hide(works);
      if (this.hidingTicked) {
        this.selected.set(new Set());
        this.outcome.set(`Hid ${worksCount(works.length)}. Tick Show hidden works under Filter to see them again.`);
      }
    } catch (error) {
      this.hideProblem.set(error instanceof Error ? error.message : String(error));
    } finally {
      this.hidingTicked = false;
    }
  }

  // region marking entries as bookmarks by hand

  private readonly jobs = inject(Jobs);
  /** a run reads and writes the index: marking by hand waits until it has ended */
  protected readonly runGoing = computed(() => this.jobs.activeRuns().length > 0);
  protected readonly markProblem = signal('');

  /** whether an entry can be marked by hand: anything with an index file of its own */
  protected canMark(work: Bookmark): boolean {
    return !!work.id && !work.placeholder && !work.unindexed;
  }

  protected isBookmark(work: Bookmark): boolean {
    return isBookmarkEntry(work);
  }

  /** the ticked entries that are bookmarks and that are not - which decides what the bar offers */
  protected readonly tickedBookmarks = computed(() =>
    this.selectedShown().filter((w) => this.canMark(w) && isBookmarkEntry(w)),
  );
  protected readonly tickedNotBookmarks = computed(() =>
    this.selectedShown().filter((w) => this.canMark(w) && !isBookmarkEntry(w)),
  );
  protected readonly markLabel = computed(() =>
    this.selectedShown().length === 1 ? 'Mark as bookmark' : 'Mark all as bookmarks',
  );
  protected readonly unmarkLabel = computed(() =>
    this.selectedShown().length === 1 ? 'Unmark as bookmark' : 'Unmark all as bookmarks',
  );

  // region downloading or updating from the listing

  /**
   * The work number an entry stands for, to download or update: a work its own (a placeholder
   * too - only its number is known, and that is all a fic run needs). A series and an external
   * work stand for nothing, at the owner's request: an external work is hosted outside AO3, and a
   * series is not one fic - its works are downloaded from their own entries.
   */
  protected worksToFetch(work: Bookmark): string[] {
    // a file named for no work number has nothing to fetch it by
    if (work.id?.startsWith(LOOSE_PREFIX)) return [];
    return work.id && this.typeOf(work) === 'individual work' ? [work.id] : [];
  }

  /** every ticked work once, in the listing's order - series and external works left out */
  protected readonly tickedToFetch = computed(() => {
    const seen = new Set<string>();
    for (const work of this.selectedShown()) for (const id of this.worksToFetch(work)) seen.add(id);
    return [...seen];
  });

  /** what the ticked entries' button leaves out, said on hover */
  protected readonly fetchTickedNote = computed(() => {
    const ticked = this.selectedShown();
    const externals = ticked.filter((w) => this.typeOf(w) === 'external work').length;
    const series = ticked.filter((w) => this.typeOf(w) === 'series bookmark').length;
    const notes: string[] = [];
    if (series) notes.push(`${series === 1 ? 'the series is' : `${series} series are`} left out - download the works in them instead`);
    if (externals) notes.push(`${externals === 1 ? 'the external work is' : `${externals} external works are`} left out - they are hosted outside AO3`);
    return notes.join('; ');
  });

  protected readonly fetchTickedLabel = computed(() => {
    const n = this.tickedToFetch().length;
    return `Download/update ${n.toLocaleString()} ${n === 1 ? 'work' : 'works'} now`;
  });

  /** a placeholder's 'download it now', or an entry's own menu item */
  protected downloadNow(work: Bookmark): void {
    this.menuFor.set(null);
    const works = this.worksToFetch(work);
    if (works.length) this.jobs.fetchWorksAsked.set(works);
  }

  protected downloadTicked(): void {
    const works = this.tickedToFetch();
    if (works.length) this.jobs.fetchWorksAsked.set(works);
  }

  // endregion

  protected menuMark(work: Bookmark, bookmarked: boolean): void {
    this.menuFor.set(null);
    void this.mark([work], bookmarked, false);
  }

  protected markTicked(bookmarked: boolean): void {
    const works = bookmarked ? this.tickedNotBookmarks() : this.tickedBookmarks();
    void this.mark(works, bookmarked, true);
  }

  private async mark(works: Bookmark[], bookmarked: boolean, ticked: boolean): Promise<void> {
    if (!works.length || this.busy() || this.runGoing()) return;
    this.markProblem.set('');
    this.problem.set('');
    this.outcome.set('');
    this.busy.set(true);
    try {
      const changed = await this.library.setBookmarked(works, bookmarked);
      if (ticked) {
        this.selected.set(new Set());
        this.outcome.set(`${bookmarked ? 'Marked' : 'Unmarked'} ${worksCount(changed)} as ${changed === 1 ? 'a bookmark' : 'bookmarks'}.`);
      }
    } catch (error) {
      const said = error instanceof Error ? error.message : String(error);
      if (ticked) this.problem.set(said);
      else this.markProblem.set(said);
    } finally {
      this.busy.set(false);
    }
  }

  // endregion

  // region each entry's own menu

  /** the entry whose ⋯ menu is open, by its key; null when none is */
  protected readonly menuFor = signal<string | null>(null);

  protected menuKey(work: Bookmark): string {
    return keyOf(work);
  }

  protected toggleMenu(work: Bookmark, event: Event): void {
    // the click that opens it must not reach the document and shut it again
    event.stopPropagation();
    this.menuFor.set(this.menuFor() === keyOf(work) ? null : keyOf(work));
  }

  /** a click anywhere else, or Escape, shuts an open menu */
  protected closeMenu(): void {
    if (this.menuFor()) this.menuFor.set(null);
  }

  protected menuHide(work: Bookmark): void {
    this.menuFor.set(null);
    this.askHide(work);
  }

  protected menuUnhide(work: Bookmark): void {
    this.menuFor.set(null);
    void this.unhide(work);
  }

  /** a series cannot go in a collection: the item is there, greyed, and says why */
  protected menuAdd(work: Bookmark): void {
    if (!canCollect(work)) return;
    this.startAdd([work], false);
  }

  // endregion

  // region hiding and unhiding what is ticked

  /**
   * The ticked works that are hidden and that are showing - which decides what the bar offers:
   * one ticked work is offered Hide or Unhide; several all showing, Hide all; several all
   * hidden, Unhide all; and a mix, both. Hidden works can only be ticked while Show hidden
   * works is on, since otherwise they are not in the listing at all.
   */
  protected readonly tickedHidden = computed(() => this.selectedShown().filter((w) => this.isHidden(w)));
  protected readonly tickedShowing = computed(() => this.selectedShown().filter((w) => !this.isHidden(w)));
  protected readonly hideLabel = computed(() => (this.selectedShown().length === 1 ? 'Hide' : 'Hide all'));
  protected readonly unhideLabel = computed(() => (this.selectedShown().length === 1 ? 'Unhide' : 'Unhide all'));

  /** hide every ticked work that is showing - after the same warning a single hide has */
  protected hideTicked(): void {
    const works = this.tickedShowing();
    if (!works.length || this.busy()) return;
    this.hideProblem.set('');
    this.outcome.set('');
    this.hidingTicked = true;
    if (safeGet(HIDE_WARNING_KEY) === 'off') {
      void this.doHide(works);
      return;
    }
    this.dontWarnAgain.set(false);
    this.confirmingHide.set(works);
  }

  /** show every ticked hidden work again - nothing is lost by it, so no warning */
  protected async unhideTicked(): Promise<void> {
    const works = this.tickedHidden();
    if (!works.length || this.busy()) return;
    this.hideProblem.set('');
    this.outcome.set('');
    try {
      await this.library.unhide(works);
      this.selected.set(new Set());
      this.outcome.set(`Unhid ${worksCount(works.length)}.`);
    } catch (error) {
      this.hideProblem.set(error instanceof Error ? error.message : String(error));
    }
  }

  // endregion

  // endregion

  // region picking works for a custom collection

  /** ticking only means something where it can be saved: a library that can be written to */
  protected readonly canSelect = computed(() => this.selectable() && this.custom.writable());
  /** a different listing is a different set of works, so it starts with nothing ticked */
  protected readonly selected = linkedSignal<Bookmark[], ReadonlySet<string>>({
    source: this.works,
    computation: () => new Set(),
  });
  /** what can be ticked among what the filters leave showing - series included */
  private readonly selectableShown = computed(() => this.filtered().filter(canTick));
  /**
   * The ticked works the filters still show. Narrowing the listing narrows what an action
   * acts on, so nothing hidden is added or taken out unseen.
   */
  protected readonly selectedShown = computed(() => {
    const picked = this.selected();
    return this.selectableShown().filter((work) => picked.has(keyOf(work)));
  });
  protected readonly allShownSelected = computed(
    () => this.selectableShown().length > 0 && this.selectedShown().length === this.selectableShown().length,
  );
  /** the open collection, when it is one of the person's own and so can be taken from */
  protected readonly removableFrom = computed(() => {
    const collection = this.collection();
    return collection && isCustomCollection(collection) ? collection : null;
  });
  /** where ticked works can go: every custom collection but the one being shown */
  protected readonly targets = computed(() =>
    this.custom.all().filter((c) => c.name !== this.collection()?.name),
  );

  protected readonly adding = signal(false);
  /**
   * The works an add is for, while one is under way: the ticked works, from the bar, or one
   * work, from its own menu. Kept apart from the ticks so adding one work from its menu
   * neither needs nor disturbs whatever else is ticked. Series are already left out.
   */
  protected readonly addingWith = signal<Bookmark[] | null>(null);
  /** whether the add under way came from the bar, and so clears the ticks once it is done */
  private addFromBar = false;
  /**
   * The series an add was asked to include, which cannot go in a collection - said before
   * anything is added, with the works that will be, until the person says to go on or not.
   */
  protected readonly seriesWarning = signal<{ series: Bookmark[]; rest: Bookmark[]; fromBar: boolean } | null>(null);
  /** among what is ticked, what can go in a collection - not a series */
  protected readonly tickedCollectable = computed(() => this.selectedShown().filter(canCollect));
  /** the custom collection to add to, by name - '' until one is chosen */
  protected readonly target = signal('');
  /**
   * The works a new collection is being made for, while its window is open. Taken when the
   * window opens, so what it starts with is what was ticked then; null when it is shut.
   */
  protected readonly creatingWith = signal<CollectionItems | null>(null);
  protected readonly busy = signal(false);
  protected readonly outcome = signal('');
  protected readonly problem = signal('');

  protected readonly canAdd = computed(
    () => !this.busy() && (this.addingWith() ?? []).length > 0 && !!this.target(),
  );

  protected canCollect(work: Bookmark): boolean {
    return canCollect(work);
  }

  protected canTick(work: Bookmark): boolean {
    return canTick(work);
  }

  protected isSelected(work: Bookmark): boolean {
    return this.selected().has(keyOf(work));
  }

  protected toggleSelected(work: Bookmark): void {
    const picked = new Set(this.selected());
    const key = keyOf(work);
    if (picked.has(key)) picked.delete(key);
    else picked.add(key);
    this.selected.set(picked);
  }

  /** every work the filters show, across every page - or none, when they all are already */
  protected toggleAllShown(): void {
    if (this.allShownSelected()) {
      this.selected.set(new Set());
      return;
    }
    this.selected.set(new Set([...this.selected(), ...this.selectableShown().map(keyOf)]));
  }

  protected clearSelection(): void {
    this.selected.set(new Set());
  }

  /** Add to a collection, from the bar: everything ticked that can go in one */
  protected openAdd(): void {
    this.startAdd(this.selectedShown(), true);
  }

  /**
   * Begin an add for `works`. A series cannot go in a collection, so any among them are named
   * in a warning first - the rest are added only once the person says that is all right.
   */
  protected startAdd(works: Bookmark[], fromBar: boolean): void {
    this.outcome.set('');
    this.problem.set('');
    this.menuFor.set(null);
    const rest = works.filter(canCollect);
    if (!rest.length) return;
    const series = works.filter((w) => bookmarkTypeOf(w) === 'series bookmark');
    if (series.length) {
      this.seriesWarning.set({ series, rest, fromBar });
      return;
    }
    this.proceedAdd(rest, fromBar);
  }

  /** the series were named and the person said go on: add the rest */
  protected addWithoutSeries(): void {
    const warning = this.seriesWarning();
    this.seriesWarning.set(null);
    if (warning) this.proceedAdd(warning.rest, warning.fromBar);
  }

  /** not now: nothing is added, and whatever was ticked stays ticked */
  protected cancelSeriesWarning(): void {
    this.seriesWarning.set(null);
  }

  private proceedAdd(works: Bookmark[], fromBar: boolean): void {
    this.addingWith.set(works);
    this.addFromBar = fromBar;
    // the last one added to stays chosen; otherwise the first, so Add is never waiting on a click
    if (!this.targets().some((c) => c.name === this.target())) this.target.set(this.targets()[0]?.name ?? '');
    // with none of your own to add to, the only answer is a new one - so ask that straight away
    if (this.targets().length === 0) {
      this.newCollection();
      return;
    }
    this.adding.set(true);
  }

  /** the add panel shut without adding: nothing changes */
  protected closeAdd(): void {
    this.adding.set(false);
    this.addingWith.set(null);
  }

  /** open the new-collection window, to start with the works the add is for */
  protected newCollection(): void {
    this.outcome.set('');
    this.problem.set('');
    this.creatingWith.set(itemsOf(this.addingWith() ?? []));
  }

  /** the new collection was made, with the works already in it */
  protected collectionCreated(collection: Collection): void {
    const items = this.creatingWith() ?? { works: [], externals: [] };
    this.creatingWith.set(null);
    this.adding.set(false);
    this.addingWith.set(null);
    this.target.set(collection.name ?? '');
    if (this.addFromBar) this.selected.set(new Set());
    this.outcome.set(`Made ${collection.title}, with ${countOf(items)} in it.`);
  }

  /**
   * Closed without saving: no collection was made, and nothing else changes - the works stay
   * ticked and the add panel stays as it was, so the person can pick another way. Opened
   * straight from Add (there being no collection of their own yet), there is no panel to go
   * back to, so the add is over.
   */
  protected collectionCancelled(): void {
    this.creatingWith.set(null);
    if (!this.adding()) this.addingWith.set(null);
  }

  protected async addSelected(): Promise<void> {
    if (!this.canAdd()) return;
    const items = itemsOf(this.addingWith() ?? []);
    const clear = this.addFromBar;
    await this.act(async () => {
      const { collection, added, already } = await this.custom.add(this.target(), items);
      this.adding.set(false);
      this.addingWith.set(null);
      const count = added.works.length + added.externals.length;
      // a work is in a collection once: those already there are said, not added again
      const skipped = already ? ` ${already.toLocaleString()} ${already === 1 ? 'was' : 'were'} already in it.` : '';
      return count
        ? `Added ${countOf(added)} to ${collection.title}.${skipped}`
        : `${items.works.length + items.externals.length === 1 ? 'That was' : 'Everything ticked was'} already in ${collection.title}.`;
    }, clear);
  }

  protected async removeSelected(): Promise<void> {
    const collection = this.removableFrom();
    if (!collection?.name || this.busy() || this.selectedShown().length === 0) return;
    const items = itemsOf(this.selectedShown());
    await this.act(async () => {
      await this.custom.remove(collection.name!, items);
      return `Took ${countOf(items)} out of ${collection.title}.`;
    });
  }

  private async act(change: () => Promise<string>, clearTicks = true): Promise<void> {
    this.busy.set(true);
    this.problem.set('');
    this.outcome.set('');
    try {
      this.outcome.set(await change());
      if (clearTicks) this.selected.set(new Set());
    } catch (error) {
      this.problem.set(error instanceof Error ? error.message : String(error));
    } finally {
      this.busy.set(false);
    }
  }

  // endregion

  protected clearFilters(): void {
    this.titleQuery.set('');
    this.authorQuery.set('');
    this.updatedFrom.set('');
    this.updatedTo.set('');
    this.bookmarkedFrom.set('');
    this.bookmarkedTo.set('');
    this.typeFilter.set('');
    this.originFilter.set('');
    this.formatFilter.set('');
    this.withNotes.set(false);
    this.recommended.set(false);
    this.includeTags.set([]);
    this.excludeTags.set([]);
    this.sortBy.set(DEFAULT_SORT);
  }

  // template helpers
  protected readonly authorLink = authorLink;
  protected readonly chapterCount = chapterCount;
  protected readonly isComplete = isEntryComplete;
  protected readonly typeOf = bookmarkTypeOf;
  protected readonly paragraphs = paragraphs;
  protected readonly ratingClass = ratingClass;
  protected readonly warningClass = warningClass;

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 1), this.totalPages()));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected hasLocalCopy(work: Bookmark): boolean {
    // a series' or an external work's id is not a work number, and could be one by chance
    return !!this.copyOf(work, 'html');
  }

  protected isOpen(key: string): boolean {
    return this.openSeries().has(key);
  }

  protected toggle(key: string): void {
    const open = new Set(this.openSeries());
    if (open.has(key)) open.delete(key);
    else open.add(key);
    this.openSeries.set(open);
  }

  /**
   * The works a series holds, in the series' own order, as the index describes them. A work
   * the index has no entry for - the series grew since it was last walked - is shown by its
   * number, with a link to ao3, as a collection shows one.
   */
  protected partsOf(ids: string[] | undefined): Bookmark[] {
    const byId = this.worksById();
    return (ids ?? []).map((id) => byId.get(id) ?? placeholderWork(id));
  }

  /** the works in one of the series a work belongs to, when that series has been walked */
  protected seriesParts(seriesId: string): string[] | undefined {
    return this.seriesById().get(seriesId)?.work_ids;
  }

  /**
   * Opens the downloaded html file in a new tab, falling back to the work on ao3 when
   * this folder has no local copy of it.
   */
  protected openWork(work: Bookmark, event: Event): void {
    event.preventDefault();

    const copy = this.copyOf(work, 'html');
    if (copy) {
      this.library.openCopy(copy, 'html', work.link);
      return;
    }
    // a file no entry matches may be held in no html at all: its first format opens instead
    const other = work.unindexed ? this.formatsOf(work)[0] : undefined;
    if (other) {
      this.openFormat(work, other, event);
      return;
    }
    if (work.link) window.open(work.link, '_blank', 'noopener');
  }

  /**
   * The formats this folder holds a downloaded copy of the work in, besides the html its title
   * opens - each one a button beside the title. A series' or an external work's id is not a
   * work number, so they never get one.
   */
  protected formatsOf(work: Bookmark): OpenableFormat[] {
    return OPENABLE_FORMATS.filter((format) => format !== 'html' && !!this.copyOf(work, format));
  }

  /**
   * The work's newest copy in a format: from the library's copies by work number, or - for a
   * file no index entry matches - from the files its row was made from.
   */
  /** opens Resolve issues, which looks a file with no index entry up on AO3 */
  protected resolveIssues(): void {
    if (!this.runGoing()) this.jobs.resolveIssuesAsked.update((n) => n + 1);
  }

  /** a row for a file whose name holds no work number: nothing to hide, tick or fetch it by */
  protected isLoose(work: Bookmark): boolean {
    return !!work.unindexed && !!work.id?.startsWith(LOOSE_PREFIX);
  }

  /** where an unindexed row's date came from, said on hovering it */
  protected unindexedDateTitle(work: Bookmark): string {
    switch (work.unindexed_date) {
      case 'name': return 'The date in its file name';
      case 'guessed': return 'A date guessed from its file name';
      case 'file': return 'When the file last changed - its name has no date';
      default: return 'No date could be read';
    }
  }

  private copyOf(work: Bookmark, format: OpenableFormat): LocalCopy | undefined {
    if (work.unindexed) return work.unindexed_files?.[format];
    return isWorkEntry(work) && work.id ? this.copies()[format].get(work.id) : undefined;
  }

  protected readonly viewable = viewableInBrowser;

  /**
   * Open the work's newest copy in that format: in a new tab where a browser can show it (a
   * pdf), and otherwise saved under its own name, for an e-reader - no browser shows an epub,
   * mobi or azw3, and a tab handed one only saves it under a made-up name.
   */
  protected openFormat(work: Bookmark, format: OpenableFormat, event: Event): void {
    event.preventDefault();
    const copy = this.copyOf(work, format);
    if (!copy) return;
    if (viewableInBrowser(format)) this.library.openCopy(copy, format, null);
    else this.saveCopy(copy, format);
  }

  private saveCopy(copy: LocalCopy, format: OpenableFormat): void {
    void this.library.readCopy(copy, format).then(
      (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = copyName(copy);
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      },
      () => {
        // the file has gone since the folder was read; the button stays, nothing is saved
      },
    );
  }
}

/** set once someone ticks 'do not warn me again' before hiding a work */


/** a work and an external work can share a number, so the kind is part of the key */
function keyOf(work: Bookmark): string {
  return `${bookmarkTypeOf(work)}:${work.id}`;
}

/** '1 work', '3 works', '2 works and 1 external work' */
function countOf(items: { works: string[]; externals: string[] }): string {
  const say = (n: number, one: string) => `${n.toLocaleString()} ${one}${n === 1 ? '' : 's'}`;
  if (!items.externals.length) return say(items.works.length, 'work');
  if (!items.works.length) return say(items.externals.length, 'external work');
  return `${say(items.works.length, 'work')} and ${say(items.externals.length, 'external work')}`;
}

/** '1 work', '3 works' */
function worksCount(n: number): string {
  return `${n.toLocaleString()} ${n === 1 ? 'work' : 'works'}`;
}
