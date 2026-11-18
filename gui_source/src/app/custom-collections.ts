import { Injectable, computed, inject } from '@angular/core';
import { LOOSE_PREFIX } from './unindexed-works';
import { Library } from './library';
import { Bookmark, bookmarkTypeOf } from './bookmarks';
import { Collection, flattenCollection, isCustomCollection } from './collections';

/**
 * Collections made in this app: works picked from the listing and grouped under a name of the
 * person's own choosing, beside the collections indexed from ao3.
 *
 * **They live in `collections/custom/`, and the helper never sees them.** Every helper read
 * of `collections/` lists that folder's own files only, never a folder inside it - so a
 * custom collection is not linked into works' `from_collections`, not counted by the
 * new-bookmarks walk, and cannot be overwritten by a collection run of the same name. The
 * page reads the whole folder and tells collections from works by shape, so it finds them.
 *
 * **A name that can never be an ao3 one.** ao3 collection names are letters, digits and
 * underscores, so a custom collection's `custom-` prefix keeps the two apart for good. The
 * name is the file's name too, so renaming the title later moves nothing.
 *
 * Works from ao3 collections are never changed here: what ao3 says a collection holds is
 * ao3's to say, and the next collection run would only put it back.
 */

/** where custom collections are kept, inside the library */
export const CUSTOM_COLLECTIONS_FOLDER = 'collections/custom';
export const CUSTOM_PREFIX = 'custom-';
/** the longest title a custom collection takes */
export const TITLE_LIMIT = 120;

/**
 * What can go into a custom collection: works, and external works - each by the number ao3
 * gives it, kept apart because the two are numbered separately. Series are left out: a
 * collection holds works, and a series is already a group of its own.
 */
export interface CollectionItems {
  works: string[];
  externals: string[];
}

/** the works and external works among `entries`, by number, in the order given */
export function itemsOf(entries: Bookmark[]): CollectionItems {
  const works: string[] = [];
  const externals: string[] = [];
  for (const entry of entries) {
    if (!entry.id || entry.error) continue;
    const type = bookmarkTypeOf(entry);
    if (type === 'individual work') works.push(entry.id);
    else if (type === 'external work') externals.push(entry.id);
  }
  return { works, externals };
}

/**
 * What a person can say about a collection of their own: the same fields an ao3 collection
 * has, so the page shows the two the same way. The counts ao3 keeps (works, fandoms) are not
 * here - a custom collection's are what it holds.
 */
export interface CollectionFields {
  title: string;
  description: string;
  tags: string[];
  maintainers: string[];
  challenge_type: string;
  closed: boolean;
  moderated: boolean;
  unrevealed: boolean;
  anonymous: boolean;
  /** null is 'not said', as on an ao3 collection that does not say */
  multifandom: boolean | null;
  created: string;
  active_since: string;
}

/** the kinds of challenge ao3 collections are, as ao3 names them */
export const CHALLENGE_TYPES = ['No Challenge', 'Gift Exchange', 'Prompt Meme'];

/** a new collection's fields before anyone has said anything about it */
export function blankFields(title = ''): CollectionFields {
  return {
    title,
    description: '',
    tags: [],
    maintainers: [],
    challenge_type: 'No Challenge',
    closed: false,
    moderated: false,
    unrevealed: false,
    anonymous: false,
    multifandom: null,
    created: new Date().toISOString().slice(0, 10),
    active_since: '',
  };
}

/** a collection's fields, to edit */
export function fieldsOf(collection: Collection): CollectionFields {
  return {
    title: collection.title,
    description: collection.description ?? '',
    tags: [...(collection.tags ?? [])],
    maintainers: [...(collection.maintainers ?? [])],
    challenge_type: collection.challenge_type || 'No Challenge',
    closed: !!collection.closed,
    moderated: !!collection.moderated,
    unrevealed: !!collection.unrevealed,
    anonymous: !!collection.anonymous,
    multifandom: collection.multifandom ?? null,
    created: collection.created ?? '',
    active_since: collection.active_since ?? '',
  };
}

/** what an add did: the collection as saved, and how many were new to it */
export interface Added {
  collection: Collection;
  added: CollectionItems;
  /** how many of those asked for were in it already, and so were left as they were */
  already: number;
}

/**
 * Whether an entry can be ticked in a listing: anything with a number - works, series and
 * external works alike, so all of them can be hidden together. Whether it can then go in a
 * collection is `canCollect`'s to say.
 */
export function canTick(entry: Bookmark): boolean {
  // a file with no work number in its name has nothing to tick it by
  return !!entry.id && !entry.error && !entry.id.startsWith(LOOSE_PREFIX);
}

/** whether an entry can be put in a custom collection at all */
export function canCollect(entry: Bookmark): boolean {
  return canTick(entry) && bookmarkTypeOf(entry) !== 'series bookmark';
}

@Injectable({ providedIn: 'root' })
export class CustomCollections {
  private readonly library = inject(Library);

  /** the custom collections, by title - the targets an add can go to */
  readonly all = computed(() => this.library.collections().filter(isCustomCollection));

  /**
   * Whether this library can be written to. A folder handed over as a list of files, by a
   * browser with no folder picker, can only be read - so nothing can be collected there.
   */
  readonly writable = computed(() => !!this.library.store());

  /** Make a collection holding `items` - a title alone, or every field - and answer it. */
  async create(
    given: string | CollectionFields,
    items: CollectionItems = { works: [], externals: [] },
  ): Promise<Collection> {
    const fields = typeof given === 'string' ? blankFields(given) : given;
    return this.save({
      ...documentFields(fields),
      name: this.newName(),
      custom: true,
      link: null,
      work_ids: unique(items.works),
      bookmark_ids: [],
      external_ids: unique(items.externals),
    });
  }

  /** Change what is said about a custom collection; what it holds stays as it is. */
  async update(name: string, fields: CollectionFields): Promise<Collection> {
    const collection = this.customNamed(name);
    return this.save({ ...this.documentOf(collection), ...documentFields(fields) });
  }

  /**
   * Add `items` to a custom collection, keeping what it holds and its order. **A work is in
   * a collection once**, by its number: one already there is left where it is, not added
   * again, and the answer says how many that was.
   */
  async add(name: string, items: CollectionItems): Promise<Added> {
    const collection = this.customNamed(name);
    const works = new Set(collection.work_ids.map(String));
    const externals = new Set(collection.external_ids.map(String));
    const added = {
      works: unique(items.works).filter((id) => !works.has(id)),
      externals: unique(items.externals).filter((id) => !externals.has(id)),
    };
    const already =
      unique(items.works).length + unique(items.externals).length -
      added.works.length - added.externals.length;
    const saved = await this.save({
      ...this.documentOf(collection),
      work_ids: [...collection.work_ids, ...added.works],
      external_ids: [...collection.external_ids, ...added.externals],
    });
    return { collection: saved, added, already };
  }

  /** Take `items` out of a custom collection. */
  async remove(name: string, items: CollectionItems): Promise<Collection> {
    const collection = this.customNamed(name);
    const works = new Set(items.works);
    const externals = new Set(items.externals);
    return this.save({
      ...this.documentOf(collection),
      work_ids: collection.work_ids.filter((id) => !works.has(id)),
      external_ids: collection.external_ids.filter((id) => !externals.has(id)),
    });
  }

  /** an ao3 collection is refused here, whatever asked: it is not the app's to change */
  private customNamed(name: string): Collection {
    const collection = this.library.collections().find((c) => c.name === name);
    if (!collection) throw new Error('that collection is not in this library any more');
    if (!isCustomCollection(collection)) {
      throw new Error('a collection from AO3 cannot be changed here - only your own collections can');
    }
    return collection;
  }

  /** what is written for a custom collection: its own fields, not everything flattening added */
  private documentOf(collection: Collection): Record<string, unknown> {
    return {
      ...documentFields(fieldsOf(collection)),
      name: collection.name,
      custom: true,
      link: null,
      work_ids: unique(collection.work_ids),
      bookmark_ids: [],
      external_ids: unique(collection.external_ids),
    };
  }

  private async save(document: Record<string, unknown>): Promise<Collection> {
    const store = this.library.store();
    if (!store) throw new Error('this library can only be read, so nothing can be saved to it');
    const written: Record<string, unknown> = { ...document, last_modified: new Date().toISOString() };
    await store.write(
      `${CUSTOM_COLLECTIONS_FOLDER}/${written['name']}.json`,
      new Response(JSON.stringify(written, null, 2) + '\n'),
    );
    const collection = flattenCollection(written);
    if (!collection) throw new Error('the collection could not be read back');
    // shown at once, as the library would read it back, rather than rereading the library
    const others = this.library.collections().filter((c) => c.name !== collection.name);
    this.library.collections.set(
      [...others, collection].sort((a, b) => (a.title || '').localeCompare(b.title || '')),
    );
    return collection;
  }

  private newName(): string {
    const taken = new Set(this.library.collections().map((c) => c.name));
    for (;;) {
      const bytes = crypto.getRandomValues(new Uint8Array(5));
      const name = CUSTOM_PREFIX + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
      if (!taken.has(name)) return name;
    }
  }
}

function unique(ids: string[]): string[] {
  return [...new Set(ids.map(String))];
}

/**
 * The fields as written - checked, trimmed and in ao3's own shape, so the page reads a custom
 * collection exactly as it reads one from ao3. `flags` is what ao3 shows in brackets after a
 * collection's name, said again as the booleans are.
 */
function documentFields(fields: CollectionFields): Record<string, unknown> {
  const title = fields.title.trim().slice(0, TITLE_LIMIT);
  if (!title) throw new Error('give the collection a name');
  const list = (values: string[]) => unique(values.map((v) => v.trim()).filter(Boolean));
  const flags = [
    fields.closed ? 'Closed' : 'Open',
    fields.moderated ? 'Moderated' : 'Unmoderated',
    ...(fields.unrevealed ? ['Unrevealed'] : []),
    ...(fields.anonymous ? ['Anonymous'] : []),
  ];
  return {
    title,
    description: fields.description.trim(),
    tags: list(fields.tags),
    maintainers: list(fields.maintainers),
    challenge_type: CHALLENGE_TYPES.includes(fields.challenge_type) ? fields.challenge_type : 'No Challenge',
    closed: fields.closed,
    moderated: fields.moderated,
    unrevealed: fields.unrevealed,
    anonymous: fields.anonymous,
    multifandom: fields.multifandom,
    flags,
    created: fields.created.trim(),
    active_since: fields.active_since.trim(),
  };
}
