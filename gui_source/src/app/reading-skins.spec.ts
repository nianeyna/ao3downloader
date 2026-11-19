import { TestBed } from '@angular/core/testing';
import { DebugMode } from './debug-mode';
import { Library } from './library';
import { MemoryStore } from './memory-store';
import { BROWSER_SKINS_KEY, BUILT_IN_READING_SKINS, DEFAULT_SKIN_KEY, ReadingSkins, skinProblem } from './reading-skins';
import { ReadingSkinsSettings } from './reading-skins-settings';
import { hasWorkSkin, withReadingSkin } from './skin-html';

/** AO3's downloaded html, as it is shaped - its own small style block, and no #workskin */
const DOWNLOADED = `<!DOCTYPE html>
<html><head><meta charset="utf-8" /><title>A Work</title>
<style type="text/css">.meta h1 { text-align: center; }</style>
</head>
<body>
<div id="preface">
  <p class="message"><b>A Work</b> Posted originally on the Archive of Our Own.</p>
  <div class="meta">
    <dl class="tags">
      <dt>Archive Warning:</dt>
      <dd><a href="https://archiveofourown.org/tags/No">No Archive Warnings Apply</a></dd>
      <dt>Characters:</dt>
      <dd><a href="https://archiveofourown.org/tags/A">A</a>, <a href="https://archiveofourown.org/tags/B">B</a></dd>
      <dt>Additional Tags:</dt>
      <dd><a href="https://archiveofourown.org/tags/Fluff">Fluff</a></dd>
      <dt>Language:</dt>
      <dd>English</dd>
    </dl>
    <h1>A Work</h1>
    <div class="byline">by <a rel="author" href="https://archiveofourown.org/users/w">Writer</a></div>
    <p>Summary</p>
    <blockquote class="userstuff"><p>What happens.</p></blockquote>
  </div>
</div>
<div id="chapters" class="userstuff"><p>Once upon a time.</p></div>
</body>
</html>`;

const SKIN = '#workskin p { line-height: 1.6; }';

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
}

describe('withReadingSkin', () => {
  function shownDoc(html: string): Document {
    return new DOMParser().parseFromString(html, 'text/html');
  }

  it('puts the skin last in the head and the work, after its tags, inside #workskin', () => {
    const shown = withReadingSkin(DOWNLOADED, SKIN);
    const doc = shownDoc(shown);

    const styles = Array.from(doc.head.querySelectorAll('style')).map((x) => x.textContent ?? '');
    expect(styles.at(-1)).toContain(SKIN);
    expect(styles.at(-1)!.indexOf('dl.work.meta')).toBeLessThan(styles.at(-1)!.indexOf(SKIN));
    const order = Array.from(doc.body.children).map((x) => x.id || x.className);
    expect(order).toEqual(['message', 'work meta group', 'workskin']);
    expect(doc.querySelector('#workskin #chapters')?.textContent).toContain('Once upon a time.');
    expect(hasWorkSkin(shown)).toBe(true);
  });

  it('shapes the work as AO3\'s page is, so skins written for it match', () => {
    const doc = shownDoc(withReadingSkin(DOWNLOADED, SKIN));

    const tags = doc.querySelector('dl.work.meta.group')!;
    expect(tags.closest('#workskin')).toBeNull();
    expect(tags.querySelector('dt.warning.tags')?.textContent).toContain('Archive Warning');
    expect(tags.querySelectorAll('dd.character.tags a.tag').length).toBe(2);
    expect(tags.querySelector('dd.freeform.tags a.tag')?.textContent).toBe('Fluff');
    // not a tag, so its words are not links classed as one
    expect(tags.querySelector('dd.language')?.textContent).toBe('English');
    const preface = doc.querySelector('#workskin div.preface.group')!;
    expect(preface.querySelector('h2.title.heading')?.textContent).toBe('A Work');
    expect(preface.querySelector('h3.byline.heading')?.textContent?.trim()).toBe('Writer');
    expect(preface.querySelector('div.summary.module > h3.heading')?.textContent).toBe('Summary:');
    expect(preface.querySelector('div.summary.module > blockquote')?.textContent).toBe('What happens.');
  });

  it('leaves a file it cannot shape as it is, skinned all the same', () => {
    const plain = '<html><head></head><body><p>Just text.</p></body></html>';
    const doc = shownDoc(withReadingSkin(plain, SKIN));

    expect(doc.querySelector('#workskin p')?.textContent).toBe('Just text.');
    expect(doc.querySelector('dl.work')).toBeNull();
  });

  it('never covers a work\'s own skin', () => {
    const own = DOWNLOADED.replace('<body>', '<body>\n<div id="workskin">').replace('</body>', '</div></body>');

    expect(withReadingSkin(own, SKIN)).toBe(own);
  });

  it('leaves the file as it is for an empty skin, one that closes its own style, or no head and body', () => {
    expect(withReadingSkin(DOWNLOADED, '  ')).toBe(DOWNLOADED);
    expect(withReadingSkin(DOWNLOADED, 'p {} </style><script>')).toBe(DOWNLOADED);
    expect(withReadingSkin('<p>just text</p>', SKIN)).toBe('<p>just text</p>');
  });
});

describe('skinProblem', () => {
  it('asks for a name a file can carry, and some CSS', () => {
    expect(skinProblem('', SKIN)).toContain('name');
    expect(skinProblem('a/b', SKIN)).toContain('cannot hold');
    expect(skinProblem('.hidden', SKIN)).toContain('cannot hold');
    expect(skinProblem('Cosy', ' ')).toContain('no CSS');
    expect(skinProblem('Cosy', '</style>')).toContain('</style');
    expect(skinProblem('Cosy', SKIN)).toBeNull();
  });
});

describe('ReadingSkins', () => {
  let debugOn: boolean;

  function setUp(store: MemoryStore | null = null) {
    TestBed.configureTestingModule({
      providers: [{ provide: DebugMode, useValue: { on: () => debugOn } }],
    });
    const library = TestBed.inject(Library);
    library.store.set(store);
    const skins = TestBed.inject(ReadingSkins);
    TestBed.tick();
    return { library, skins };
  }

  beforeEach(() => {
    localStorage.clear();
    debugOn = true;
  });

  afterEach(() => localStorage.clear());

  it('keeps a skin saved to this browser in this browser, and nothing in the library', async () => {
    const store = new MemoryStore();
    const { skins } = setUp(store);

    expect(await skins.add('Cosy', SKIN, 'browser')).toBeNull();

    expect(JSON.parse(localStorage.getItem(BROWSER_SKINS_KEY)!)).toEqual([{ name: 'Cosy', css: SKIN }]);
    expect(await store.list('', true)).toEqual([]);
  });

  it('writes a skin saved to the library as skins/custom/<name>.css, and reads it back on opening', async () => {
    const store = new MemoryStore();
    const { skins } = setUp(store);

    expect(await skins.add('Cosy', SKIN, 'library')).toBeNull();
    expect(await store.read('skins/custom/Cosy.css')).toBe(SKIN);
    expect(localStorage.getItem(BROWSER_SKINS_KEY)).toBeNull();

    skins.librarySkins.set([]);
    await skins.readLibrarySkins(store);
    expect(skins.librarySkins()).toEqual([{ name: 'Cosy', place: 'library', css: SKIN }]);
  });

  it('never reads AO3\'s own work skins as yours', async () => {
    const store = new MemoryStore();
    await store.write('skins/41822007.css', new Response('#workskin .centered {}'));
    await store.write('skins/custom/Cosy.css', new Response(SKIN));
    const { skins } = setUp(store);
    await settle();

    expect(skins.librarySkins().map((x) => x.name)).toEqual(['Cosy']);
  });

  it('refuses a second skin of the same name in the same place', async () => {
    const { skins } = setUp(new MemoryStore());
    await skins.add('Cosy', SKIN, 'browser');

    expect(await skins.add('cosy', SKIN, 'browser')).toContain('already saved in this browser');
    expect(await skins.add('Cosy', SKIN, 'library')).toBeNull();
  });

  it('cannot save to a library while none is open', async () => {
    const { skins } = setUp(null);

    expect(skins.libraryWritable()).toBe(false);
    expect(await skins.add('Cosy', SKIN, 'library')).toContain('Open a library');
  });

  it('hands the default skin to the library while debug mode is on, and nothing otherwise', async () => {
    const { library, skins } = setUp(new MemoryStore());
    await skins.add('Cosy', SKIN, 'browser');
    skins.setDefault('browser:Cosy');
    TestBed.tick();

    expect(localStorage.getItem(DEFAULT_SKIN_KEY)).toBe('browser:Cosy');
    expect(library.readingSkin()).toBe(SKIN);
  });

  it('shows no skin with debug mode off', async () => {
    debugOn = false;
    const { library, skins } = setUp(new MemoryStore());
    await skins.add('Cosy', SKIN, 'browser');
    skins.setDefault('browser:Cosy');
    TestBed.tick();

    expect(library.readingSkin()).toBe('');
  });

  it('offers the skins that come with FicFairy, which can be the default and cannot be removed', async () => {
    const { library, skins } = setUp(new MemoryStore());
    const medieval = skins.skins().find((x) => x.name === 'Medieval parchment')!;

    expect(medieval.place).toBe('builtin');
    skins.setDefault('builtin:Medieval parchment');
    TestBed.tick();
    expect(library.readingSkin()).toContain('border-image');
    expect(await skins.remove(medieval)).toContain('cannot be removed');
    expect(skins.skins()).toContain(medieval);
  });

  it('every skin that comes with FicFairy can be put into a work', () => {
    for (const skin of BUILT_IN_READING_SKINS) {
      expect(skinProblem(skin.name, skin.css), skin.name).toBeNull();
      expect(withReadingSkin(DOWNLOADED, skin.css), skin.name).toContain(skin.css);
    }
  });

  it('removing the default skin leaves none chosen', async () => {
    const store = new MemoryStore();
    const { library, skins } = setUp(store);
    await skins.add('Cosy', SKIN, 'library');
    skins.setDefault('library:Cosy');

    expect(await skins.remove(skins.librarySkins()[0])).toBeNull();
    TestBed.tick();

    expect(await store.read('skins/custom/Cosy.css')).toBeNull();
    expect(localStorage.getItem(DEFAULT_SKIN_KEY)).toBeNull();
    expect(library.readingSkin()).toBe('');
  });

  it('shows a work with the default skin as it opens, and leaves the file alone', async () => {
    const { library, skins } = setUp(new MemoryStore());
    await skins.add('Cosy', SKIN, 'browser');
    skins.setDefault('browser:Cosy');
    TestBed.tick();
    const file = new File([DOWNLOADED], '1 A Work - Writer 2025-01-01.html', { type: 'text/html' });
    const tab = { location: { href: '' }, close: () => {} };
    const realOpen = window.open;
    const realCreate = URL.createObjectURL;
    let shown: Blob | null = null;
    window.open = (() => tab) as unknown as typeof window.open;
    URL.createObjectURL = ((blob: Blob) => { shown = blob; return 'blob:the-work'; }) as typeof URL.createObjectURL;
    try {
      library.openCopy(file, 'html', null);
      await settle();
    } finally {
      window.open = realOpen;
      URL.createObjectURL = realCreate;
    }

    expect(tab.location.href).toBe('blob:the-work');
    expect(shown!.type).toBe('text/html');
    expect(await shown!.text()).toContain(SKIN);
    expect(await file.text()).toBe(DOWNLOADED);
  });
});

describe('ReadingSkinsSettings', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('saves a pasted skin where chosen, and offers it as the default', async () => {
    TestBed.configureTestingModule({
      providers: [{ provide: DebugMode, useValue: { on: () => true } }],
    });
    TestBed.inject(Library).store.set(new MemoryStore());
    const fixture = TestBed.createComponent(ReadingSkinsSettings);
    await fixture.whenStable();
    const element: HTMLElement = fixture.nativeElement;

    const name = element.querySelector<HTMLInputElement>('input[name=skinName]')!;
    name.value = 'Cosy';
    name.dispatchEvent(new Event('input'));
    const css = element.querySelector<HTMLTextAreaElement>('textarea[name=skinCss]')!;
    css.value = SKIN;
    css.dispatchEvent(new Event('input'));
    element.querySelector<HTMLInputElement>('input[name=skinPlace][value=library]')!.click();
    await fixture.whenStable();
    element.querySelector<HTMLButtonElement>('button.save-skin')!.click();
    await settle();
    await fixture.whenStable();

    expect(element.querySelector('.skin-outcome')?.textContent).toContain('saved in your library');
    expect(element.querySelector('[data-skin="library:Cosy"] .skin-place')?.textContent).toContain('library');
    const options = [...element.querySelectorAll<HTMLOptionElement>('select[name=defaultReadingSkin] option')];
    expect(options.map((x) => x.value)).toEqual(['', ...BUILT_IN_READING_SKINS.map((x) => `builtin:${x.name}`), 'library:Cosy']);
  });

  it('says a built-in skin comes with FicFairy, what it looks like and that it loads pictures, with no Remove', async () => {
    TestBed.configureTestingModule({
      providers: [{ provide: DebugMode, useValue: { on: () => true } }],
    });
    const fixture = TestBed.createComponent(ReadingSkinsSettings);
    await fixture.whenStable();
    const row = (fixture.nativeElement as HTMLElement).querySelector('[data-skin="builtin:Medieval parchment"]')!;

    expect(row.querySelector('.skin-place')?.textContent).toContain('Comes with FicFairy');
    expect(row.querySelector('.skin-about')?.textContent).toContain('another site');
    expect(row.querySelector('.remove-skin')).toBeNull();
  });

  it('holds Save until there is a name and some CSS', async () => {
    TestBed.configureTestingModule({
      providers: [{ provide: DebugMode, useValue: { on: () => true } }],
    });
    const fixture = TestBed.createComponent(ReadingSkinsSettings);
    await fixture.whenStable();

    expect(fixture.nativeElement.querySelector('button.save-skin').disabled).toBe(true);
  });
});
