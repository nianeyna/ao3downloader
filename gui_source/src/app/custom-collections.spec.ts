import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { CustomCollections, CUSTOM_COLLECTIONS_FOLDER, blankFields, canCollect, fieldsOf, itemsOf } from './custom-collections';
import { Collection, collectionLink, flattenCollection, isCollectionRecord, isCustomCollection } from './collections';
import { Bookmark } from './bookmarks';
import { CollectionsView } from './collections-view';
import { Library } from './library';
import { LibraryStore } from './library-store';
import { WorkList } from './work-list';

/**
 * Collections of your own: works ticked in the listing, grouped under a name, saved in the
 * library beside the collections read from ao3 - and never mixed up with them.
 */

function work(id: string, type?: Bookmark['bookmark_type']): Bookmark {
  return {
    id,
    bookmark_type: type,
    link: `https://archiveofourown.org/works/${id}`,
    title: `Work ${id}`,
    authors: ['Writer'],
    date_created: null,
    date_updated: '01 Jan 2020',
    fandoms: [],
    warnings: [],
    tags: { rating: '', categories: [], relationships: [], characters: [], additional: [] },
    summary: '',
    words: null,
    chapters_published: 1,
    chapters_total: 1,
    comments: null,
    kudos: null,
    bookmarks: null,
    hits: null,
    date_bookmarked: '',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
  } as Bookmark;
}

/** a library in memory: what is written can be read back */
class MemoryStore implements LibraryStore {
  readonly label = 'memory';
  readonly files = new Map<string, string>();
  async check() {}
  async list() {
    return [...this.files.keys()];
  }
  async read(path: string) {
    return this.files.get(path) ?? null;
  }
  async write(path: string, body: Response) {
    const text = await body.text();
    this.files.set(path, text);
    return text.length;
  }
  async size(path: string) {
    return this.files.get(path)?.length ?? null;
  }
  async delete(path: string) {
    this.files.delete(path);
  }
  async rename() {}
  async mkdir() {}
}

const AO3_COLLECTION = flattenCollection({
  name: 'yuletide2024',
  title: 'Yuletide 2024',
  link: 'https://archiveofourown.org/collections/yuletide2024',
  work_ids: ['1'],
  bookmark_ids: [],
})!;

let library: Library;
let store: MemoryStore;
let custom: CustomCollections;

function written(name: string): Record<string, unknown> {
  return JSON.parse(store.files.get(`${CUSTOM_COLLECTIONS_FOLDER}/${name}.json`)!);
}

beforeEach(() => {
  library = TestBed.inject(Library);
  store = new MemoryStore();
  library.store.set(store);
  library.collections.set([AO3_COLLECTION]);
  library.worksById.set(new Map(['1', '2', '3'].map((id) => [id, work(id)])));
  custom = TestBed.inject(CustomCollections);
});

describe('telling a custom collection from one off ao3', () => {
  it('says so in the file, and a collection with no such flag is ao3s', () => {
    expect(isCustomCollection(AO3_COLLECTION)).toBe(false);
    expect(isCustomCollection(flattenCollection({ name: 'custom-1', custom: true, work_ids: [] })!)).toBe(true);
  });

  it('never links a custom collection to ao3, even with no link of its own', () => {
    const mine = flattenCollection({ name: 'custom-1', custom: true, link: null, work_ids: [] })!;
    expect(collectionLink(mine)).toBe('');
    // an older ao3 file with no link still gets its ao3 address
    expect(collectionLink(flattenCollection({ name: 'old', work_ids: [] })!)).toContain('/collections/old');
  });
});

describe('CustomCollections', () => {
  it('makes a collection in collections/custom, read back as a collection by its shape', async () => {
    const made = await custom.create('  Comfort reads  ', { works: ['2', '1', '2'], externals: ['9'] });

    expect(made.name).toMatch(/^custom-[0-9a-f]{10}$/);
    const file = written(made.name!);
    expect(file).toMatchObject({ custom: true, title: 'Comfort reads', work_ids: ['2', '1'], external_ids: ['9'] });
    expect(isCollectionRecord(file)).toBe(true);
    expect(library.collections().map((c) => c.title)).toEqual(['Comfort reads', 'Yuletide 2024']);
  });

  it('names a collection so it can never be an ao3 one, which have no hyphens', async () => {
    const made = await custom.create('Yuletide 2024', { works: ['1'], externals: [] });
    expect(made.name).not.toBe('yuletide2024');
    expect(made.name).toContain('-');
  });

  it('adds to a custom collection, keeping what it held and its order', async () => {
    const made = await custom.create('Mine', { works: ['1'], externals: [] });

    await custom.add(made.name!, { works: ['3', '1', '2'], externals: [] });

    expect(written(made.name!)['work_ids']).toEqual(['1', '3', '2']);
  });

  it('adds a work it already holds only once, by work number', async () => {
    const made = await custom.create('Mine', { works: ['1', '2'], externals: ['9'] });

    const result = await custom.add(made.name!, { works: ['2', '3', '3'], externals: ['9'] });

    expect(written(made.name!)).toMatchObject({ work_ids: ['1', '2', '3'], external_ids: ['9'] });
    expect(result.added).toEqual({ works: ['3'], externals: [] });
    expect(result.already).toBe(2);
  });

  it('writes every field it is given, in ao3s own shape', async () => {
    const made = await custom.create({
      ...blankFields('Rec list'),
      description: 'The best ones',
      tags: [' fluff ', '', 'fluff', 'angst'],
      maintainers: ['me'],
      challenge_type: 'Gift Exchange',
      moderated: true,
      multifandom: true,
    });

    expect(written(made.name!)).toMatchObject({
      title: 'Rec list',
      description: 'The best ones',
      tags: ['fluff', 'angst'],
      maintainers: ['me'],
      challenge_type: 'Gift Exchange',
      moderated: true,
      multifandom: true,
      flags: ['Open', 'Moderated'],
    });
  });

  it('changes what is said about a collection and leaves what it holds alone', async () => {
    const made = await custom.create('Mine', { works: ['1', '2'], externals: [] });

    await custom.update(made.name!, { ...fieldsOf(made), title: 'Renamed', tags: ['new'] });

    expect(written(made.name!)).toMatchObject({ name: made.name, title: 'Renamed', tags: ['new'], work_ids: ['1', '2'] });
    await expect(custom.update('yuletide2024', blankFields('x'))).rejects.toThrow(/AO3/);
  });

  it('takes works out of a custom collection', async () => {
    const made = await custom.create('Mine', { works: ['1', '2', '3'], externals: ['9'] });

    await custom.remove(made.name!, { works: ['2'], externals: ['9'] });

    expect(written(made.name!)).toMatchObject({ work_ids: ['1', '3'], external_ids: [] });
  });

  it('refuses to change a collection from ao3, and writes nothing', async () => {
    await expect(custom.add('yuletide2024', { works: ['2'], externals: [] })).rejects.toThrow(/AO3/);
    await expect(custom.remove('yuletide2024', { works: ['1'], externals: [] })).rejects.toThrow(/AO3/);
    expect(store.files.size).toBe(0);
  });

  it('needs a name, and a library that can be written to', async () => {
    await expect(custom.create('   ', { works: ['1'], externals: [] })).rejects.toThrow(/name/);
    library.store.set(null);
    expect(custom.writable()).toBe(false);
    await expect(custom.create('Mine', { works: ['1'], externals: [] })).rejects.toThrow(/read/);
  });

  it('takes works and external works, and leaves series out', () => {
    const entries = [work('1'), work('5', 'external work'), work('7', 'series bookmark')];
    expect(entries.map(canCollect)).toEqual([true, true, false]);
    expect(itemsOf(entries)).toEqual({ works: ['1'], externals: ['5'] });
  });
});

describe('ticking works in the listing', () => {
  let fixture: ComponentFixture<WorkList>;
  let element: HTMLElement;

  async function listing(works: Bookmark[], collection: Collection | null = null) {
    fixture = TestBed.createComponent(WorkList);
    fixture.componentRef.setInput('works', works);
    fixture.componentRef.setInput('selectable', true);
    fixture.componentRef.setInput('collection', collection);
    await settle();
    element = fixture.nativeElement as HTMLElement;
  }

  async function settle() {
    for (let i = 0; i < 3; i++) {
      await fixture.whenStable();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    fixture.detectChanges();
  }

  function button(text: string): HTMLButtonElement {
    return [...element.querySelectorAll('button')].find((b) => b.textContent?.includes(text))!;
  }

  async function tick(at: number) {
    const boxes = element.querySelectorAll<HTMLInputElement>('input.pick');
    boxes[at].dispatchEvent(new Event('change'));
    await settle();
  }

  it('offers no ticking in a library that can only be read', async () => {
    library.store.set(null);
    await listing([work('1')]);
    expect(element.querySelector('input.pick')).toBeNull();
    expect(element.querySelector('.selection')).toBeNull();
  });

  /** type into the collection window's name box and press its Create */
  async function createInWindow(title: string) {
    const name = element.querySelector<HTMLInputElement>('app-collection-editor input[name="title"]')!;
    name.value = title;
    name.dispatchEvent(new Event('input'));
    await settle();
    element.querySelector('app-collection-editor form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    await settle();
  }

  it('asks for a new collection straight away when there is none of your own to add to', async () => {
    await listing([work('1'), work('2'), work('3')]);
    await tick(0);
    await tick(2);

    button('Add to a collection').click();
    await settle();

    expect(element.querySelector('app-collection-editor')).not.toBeNull();
    expect(element.querySelector('app-collection-editor')!.textContent).toContain('the 2 works you ticked');
    await createInWindow('Favourites');

    const made = custom.all().find((c) => c.title === 'Favourites')!;
    expect(made.work_ids).toEqual(['1', '3']);
    expect(element.querySelector('app-collection-editor')).toBeNull();
    expect(element.textContent).toContain('Made Favourites, with 2 works in it.');
    expect(element.querySelectorAll('input.pick:checked').length).toBe(0);
  });

  it('makes no collection and keeps the ticks when the new collection window is closed unsaved', async () => {
    await custom.create('Mine', { works: [], externals: [] });
    await listing([work('1'), work('2')]);
    await tick(0);
    await tick(1);
    button('Add to a collection').click();
    await settle();

    button('A new collection').click();
    await settle();
    const name = element.querySelector<HTMLInputElement>('app-collection-editor input[name="title"]')!;
    name.value = 'Never saved';
    name.dispatchEvent(new Event('input'));
    await settle();
    // every way out: Escape here; Cancel, the cross and the backdrop go the same way
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();

    expect(element.querySelector('app-collection-editor')).toBeNull();
    expect(custom.all().map((c) => c.title)).toEqual(['Mine']);
    expect([...store.files.keys()].length).toBe(1);
    expect(element.querySelectorAll('input.pick:checked').length).toBe(2);
    expect(element.querySelector('.add-panel')).not.toBeNull();
  });

  it('never adds a work twice, and says which were already there', async () => {
    const made = await custom.create('Mine', { works: ['1'], externals: [] });
    await listing([work('1'), work('2')]);
    // the bar shows only once something is ticked
    await tick(0);
    button('Tick all').click();
    await settle();
    button('Add to a collection').click();
    await settle();
    element.querySelector<HTMLInputElement>('.add-panel input[type="radio"]')!.dispatchEvent(new Event('change'));
    await settle();
    [...element.querySelectorAll('.add-panel button')].find((b) => b.textContent?.trim() === 'Add')!
      .dispatchEvent(new MouseEvent('click'));
    await settle();

    expect(written(made.name!)['work_ids']).toEqual(['1', '2']);
    expect(element.textContent).toContain('Added 1 work to Mine. 1 was already in it.');
  });

  it('offers only your own collections to add to, never one from ao3', async () => {
    await custom.create('Mine', { works: [], externals: [] });
    await listing([work('1')]);
    await tick(0);

    button('Add to a collection').click();
    await settle();

    const offered = [...element.querySelectorAll('.add-panel .choice')].map((c) => c.textContent);
    expect(offered.some((text) => text?.includes('Mine'))).toBe(true);
    expect(offered.some((text) => text?.includes('Yuletide'))).toBe(false);
  });

  it('ticks everything the filters show, across pages', async () => {
    await listing(Array.from({ length: 25 }, (_, i) => work(String(i + 1))));

    // the bar shows only once something is ticked
    await tick(0);
    button('Tick all').click();
    await settle();

    expect(element.textContent).toContain('25 ticked');
  });

  it('shows the selection bar only once something is ticked', async () => {
    await listing([work('1'), work('2')]);
    expect(element.querySelector('.selection-bar')).toBeNull();

    await tick(0);
    expect(element.querySelector('.selection-bar')?.textContent).toContain('1 ticked');
  });

  it('lets a series be ticked too, so it can be hidden with the rest', async () => {
    await listing([work('1'), work('7', 'series bookmark')]);
    expect(element.querySelectorAll('input.pick').length).toBe(2);
  });

  it('names the ticked series before adding, and adds the rest once told it is okay', async () => {
    const made = await custom.create('Mine', { works: [], externals: [] });
    const series = { ...work('7', 'series bookmark'), title: 'A Long Series' };
    await listing([work('1'), work('2'), series]);
    // the bar shows only once something is ticked
    await tick(0);
    button('Tick all').click();
    await settle();

    button('Add to a collection').click();
    await settle();
    const warning = element.querySelector('.series-warning')!;
    expect(warning.textContent).toContain("We'll add everything else - 2 works");
    expect(warning.textContent).toContain('Series 7');
    expect(warning.textContent).toContain('A Long Series');
    expect(warning.textContent).toContain('Is that okay?');
    expect(element.querySelector('.add-panel')).toBeNull();

    button('Add the rest').click();
    await settle();
    [...element.querySelectorAll('.add-panel button')].find((b) => b.textContent?.trim() === 'Add')!
      .dispatchEvent(new MouseEvent('click'));
    await settle();

    expect(written(made.name!)['work_ids']).toEqual(['1', '2']);
  });

  it('adds nothing, and keeps the ticks, when the series warning is cancelled', async () => {
    await custom.create('Mine', { works: [], externals: [] });
    await listing([work('1'), work('7', 'series bookmark')]);
    // the bar shows only once something is ticked
    await tick(0);
    button('Tick all').click();
    await settle();

    button('Add to a collection').click();
    await settle();
    button('Cancel').click();
    await settle();

    expect(element.querySelector('.series-warning')).toBeNull();
    expect(element.querySelector('.add-panel')).toBeNull();
    expect(element.querySelectorAll('input.pick:checked')).toHaveLength(2);
  });

  it('offers no add with only series ticked, and says why on hover', async () => {
    await listing([work('1'), work('7', 'series bookmark')]);
    await tick(1);

    const add = button('Add to a collection');
    expect(add.disabled).toBe(true);
    expect(add.title).toContain('A series cannot be added to a collection');
  });

  // region each entry's own menu

  function menuOf(at: number): HTMLElement {
    return element.querySelectorAll<HTMLElement>('li.blurb')[at];
  }

  async function openMenu(at: number) {
    menuOf(at).querySelector<HTMLButtonElement>('.entry-menu-toggle')!.click();
    await settle();
    return menuOf(at).querySelector('.entry-menu-items')!;
  }

  function item(menu: Element, text: string): HTMLButtonElement {
    return [...menu.querySelectorAll('button')].find((b) => b.textContent?.trim().startsWith(text))!;
  }

  it('gives each entry a menu offering what the bar does, for that one', async () => {
    await listing([work('1')]);
    const menu = await openMenu(0);
    expect([...menu.querySelectorAll('button')].map((b) => b.textContent?.trim())).toEqual([
      'Hide',
      'Download/update now',
      'Mark as bookmark',
      'Add to a collection...',
      'View index history',
    ]);
  });

  it('greys out adding a series in its menu, and says why on hover', async () => {
    await listing([work('7', 'series bookmark')]);
    const menu = await openMenu(0);
    const add = item(menu, 'Add to a collection');

    expect(add.getAttribute('aria-disabled')).toBe('true');
    expect(add.title).toContain('A series cannot be added to a collection');
    add.click();
    await settle();
    expect(element.querySelector('.add-panel')).toBeNull();
    expect(element.querySelector('app-collection-editor')).toBeNull();
  });

  it('adds just that work from its menu, leaving whatever else is ticked alone', async () => {
    const made = await custom.create('Mine', { works: [], externals: [] });
    await listing([work('1'), work('2'), work('3')]);
    await tick(0);
    await tick(2);

    item(await openMenu(1), 'Add to a collection').click();
    await settle();
    expect(element.querySelector('.add-panel h2')?.textContent).toContain('Add Work 2 to a collection');
    [...element.querySelectorAll('.add-panel button')].find((b) => b.textContent?.trim() === 'Add')!
      .dispatchEvent(new MouseEvent('click'));
    await settle();

    expect(written(made.name!)['work_ids']).toEqual(['2']);
    expect(element.querySelectorAll('input.pick:checked')).toHaveLength(2);
  });

  it('hides from the menu', async () => {
    localStorage.setItem('ao3.hideWarningOff', 'off');
    await listing([work('1'), work('2')]);

    item(await openMenu(0), 'Hide').click();
    await settle();

    expect(library.hidden().has('individual work:1')).toBe(true);
    localStorage.clear();
  });

  it('hides a ticked series from the bar, as it does a work', async () => {
    localStorage.setItem('ao3.hideWarningOff', 'off');
    await listing([work('1'), work('7', 'series bookmark')]);
    await tick(1);

    button('Hide').click();
    await settle();

    expect(library.hidden().has('series bookmark:7')).toBe(true);
    localStorage.clear();
  });

  it('shuts the menu on a click anywhere else, and on Escape', async () => {
    await listing([work('1')]);
    await openMenu(0);
    document.body.click();
    await settle();
    expect(element.querySelector('.entry-menu-items')).toBeNull();

    await openMenu(0);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();
    expect(element.querySelector('.entry-menu-items')).toBeNull();
  });

  // endregion

  it('takes ticked works out of the custom collection being shown', async () => {
    const made = await custom.create('Mine', { works: ['1', '2'], externals: [] });
    await listing([work('1'), work('2')], made);
    await tick(1);

    button('Remove from this collection').click();
    await settle();

    expect(written(made.name!)['work_ids']).toEqual(['1']);
    expect(element.textContent).toContain('Took 1 work out of Mine.');
  });

  it('offers no removing inside a collection from ao3', async () => {
    await listing([work('1')], AO3_COLLECTION);
    await tick(0);
    expect(button('Remove from this collection')).toBeUndefined();
  });
});

describe('the collections page', () => {
  it('marks a custom collection only by its first pill, Collection made in Fic Fairy, ahead of any others', async () => {
    await custom.create('Mine', { works: ['1'], externals: [] });
    const fixture = TestBed.createComponent(CollectionsView);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const cards = [...element.querySelectorAll('li.collection')];
    const mine = cards.find((c) => c.textContent?.includes('Mine'))!;
    const ao3 = cards.find((c) => c.textContent?.includes('Yuletide'))!;
    // no star and no colour of its own
    expect(mine.textContent).not.toContain('\u2605');
    expect(mine.querySelector('.flags .badge')?.textContent?.trim()).toBe('Collection made in Fic Fairy');
    expect(ao3.textContent).not.toContain('Collection made in Fic Fairy');
  });
});

describe('making and editing collections from the Collections tab', () => {
  let fixture: ComponentFixture<CollectionsView>;
  let element: HTMLElement;

  async function settle() {
    for (let i = 0; i < 3; i++) {
      await fixture.whenStable();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    fixture.detectChanges();
  }

  function button(text: string): HTMLButtonElement {
    return [...element.querySelectorAll('button')].find((b) => b.textContent?.includes(text))!;
  }

  async function typeIn(name: string, value: string) {
    const input = element.querySelector<HTMLInputElement | HTMLTextAreaElement>(`app-collection-editor [name="${name}"]`)!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    await settle();
  }

  async function submit() {
    element.querySelector('app-collection-editor form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    await settle();
  }

  beforeEach(async () => {
    fixture = TestBed.createComponent(CollectionsView);
    element = fixture.nativeElement as HTMLElement;
    await settle();
  });

  it('makes a new collection from its own button, and opens it', async () => {
    button('New collection').click();
    await settle();
    const create = element.querySelector<HTMLButtonElement>('app-collection-editor button[type="submit"]')!;
    expect(create.disabled).toBe(true);

    await typeIn('title', 'To read');
    await typeIn('description', 'Later');
    await typeIn('tags', 'cosy, long');
    await submit();

    const made = custom.all()[0];
    expect(written(made.name!)).toMatchObject({ title: 'To read', description: 'Later', tags: ['cosy', 'long'], work_ids: [] });
    expect(element.querySelector('app-collection-editor')).toBeNull();
    expect(element.querySelector('h2')?.textContent).toContain('To read');
  });

  it('says a new collection lives only in FicFairy, and not when editing one', async () => {
    button('New collection').click();
    await settle();
    expect(element.querySelector('app-collection-editor .ficfairy-only')?.textContent).toContain(
      'This collection will only exist in FicFairy. It will not be synced back to AO3.',
    );
    button('Cancel').click();
    await settle();

    await custom.create('Mine', { works: ['1'], externals: [] });
    await settle();
    button('Mine').click();
    await settle();
    button('Update collection details').click();
    await settle();
    expect(element.querySelector('app-collection-editor .ficfairy-only')).toBeNull();
  });

  it('makes nothing when the window is cancelled', async () => {
    button('New collection').click();
    await settle();
    await typeIn('title', 'Nope');

    button('Cancel').click();
    await settle();

    expect(custom.all()).toEqual([]);
    expect(store.files.size).toBe(0);
  });

  it('says when the list was refreshed, as the Works tab does', async () => {
    library.listedAt.set(new Date('2026-11-05T10:00:00Z'));
    await settle();
    expect(element.querySelector('.meta-line')?.textContent).toContain('List refreshed');
  });

  it('offers no new collection where nothing can be saved', async () => {
    library.store.set(null);
    await settle();
    expect(button('New collection')).toBeUndefined();
  });

  it('keeps it bare until every ao3 field is asked for, then edits them', async () => {
    const made = await custom.create('Mine', { works: ['1'], externals: [] });
    await settle();
    button('Mine').click();
    await settle();

    button('Update collection details').click();
    await settle();
    expect(element.querySelector('app-collection-editor [name="maintainers"]')).toBeNull();
    expect((element.querySelector<HTMLInputElement>('app-collection-editor [name="title"]'))!.value).toBe('Mine');

    button('Show every field').click();
    await settle();
    await typeIn('maintainers', 'me, a friend');
    const moderated = element.querySelector<HTMLInputElement>('app-collection-editor [name="moderated"]')!;
    moderated.checked = true;
    moderated.dispatchEvent(new Event('change'));
    await settle();
    await submit();

    expect(written(made.name!)).toMatchObject({ maintainers: ['me', 'a friend'], moderated: true, work_ids: ['1'] });
    expect(element.textContent).toContain('a friend');
  });

  it('offers no edit on a collection from ao3', async () => {
    expect(element.querySelector('.pencil')).toBeNull();
    button('Yuletide 2024').click();
    await settle();
    expect(button('Update collection details')).toBeUndefined();
    expect(element.querySelector('.pencil')).toBeNull();
  });

  it('puts Update collection details on the name line, and a pencil by the name that opens the same window', async () => {
    await custom.create('Mine', { works: ['1'], externals: [] });
    await settle();
    // in the listing, beside the name
    element.querySelector<HTMLButtonElement>('.collection .heading .pencil')!.click();
    await settle();
    expect(element.querySelector<HTMLInputElement>('app-collection-editor [name="title"]')!.value).toBe('Mine');
    button('Cancel').click();
    await settle();

    button('Mine').click();
    await settle();
    const row = element.querySelector('.collection-head .title-row')!;
    expect(row.querySelector('h2')!.textContent).toContain('Mine');
    expect(row.querySelector('.edit-collection')!.textContent).toContain('Update collection details');
    row.querySelector<HTMLButtonElement>('.pencil')!.click();
    await settle();
    expect(element.querySelector<HTMLInputElement>('app-collection-editor [name="title"]')!.value).toBe('Mine');
  });
});
