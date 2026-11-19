import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';
import { Faq } from './faq';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { AO3_NAME_PATTERN, DEFAULT_NAME_PATTERN, useNamePattern, workNumber } from './naming';

async function faq() {
  const fixture = TestBed.createComponent(Faq);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement };
}

describe('the FAQ', () => {
  it('ends with the privacy policy and the licence, on GitHub', async () => {
    const { element } = await faq();
    const legal = element.querySelector('.legal')!;

    expect(element.querySelector('section.faq')?.lastElementChild).toBe(legal);
    expect(legal.querySelector('.privacy-link')?.getAttribute('href')).toBe(
      'https://github.com/alexandria-p/FicFairy/blob/main/docs/privacy/FicFairy_Privacy-Policy.md',
    );
    expect(legal.querySelector('.licence-link')?.getAttribute('href')).toBe(
      'https://github.com/alexandria-p/FicFairy/blob/main/LICENSE',
    );
  });
});

describe('the FAQ on file names', () => {
  afterEach(() => useNamePattern(DEFAULT_NAME_PATTERN));

  // the example name is built from the pattern in force, so it is one the app reads as its work
  for (const pattern of [DEFAULT_NAME_PATTERN, AO3_NAME_PATTERN, '{date}_{author}_{worknum}_{title}', '{title} ~ {author} ~ {worknum} ~ {date}']) {
    it(`gives an example name the app matches to its work, for ${pattern}`, async () => {
      useNamePattern(pattern);
      const { element } = await faq();
      expect(workNumber(element.querySelector('.example-name code')?.textContent ?? '')).toBe('1234567');
    });
  }

  it('words the default the way it always was', async () => {
    const { element } = await faq();
    expect(element.querySelector('.pattern-words')?.textContent).toBe('{work number} {title} - {author} {date updated}');
    expect(element.querySelector('.example-name')?.textContent).toBe('1234567 The Trees Are Burning - library_of_alexandria 2026-08-23.html');
  });

  it('follows a pattern that changes while it is open', async () => {
    const { fixture, element } = await faq();
    useNamePattern(AO3_NAME_PATTERN);
    await fixture.whenStable();

    expect(element.querySelector('.pattern-words')?.textContent).toBe('{title} - {author} - {work number} {date updated}');
    expect(element.querySelector('.example-name')?.textContent).toBe('The Trees Are Burning - library_of_alexandria - 1234567 2026-08-23.html');
  });
});

describe('the FAQ on background runs', () => {
  const said = async () => (await faq()).element.textContent ?? '';

  it('says how they work only where they are offered: the hosted copy, and never to a guest', async () => {
    expect(await said()).not.toContain('Backgrounded Runs (Dropbox-only)');

    const helper = TestBed.inject(HelperConnection);
    helper.settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://ao3-helper.example.com' });
    expect(await said()).toContain('Backgrounded Runs (Dropbox-only)');

    helper.guest.set(true);
    expect(await said()).not.toContain('Backgrounded Runs (Dropbox-only)');
  });
});

describe('the FAQ on changing the naming', () => {
  it('says where only on a copy whose helper is on this computer, since only there can it change', async () => {
    expect((await faq()).element.querySelector('.pattern-where')?.textContent?.replace(/\s+/g, ' ')).toContain('in User settings, under Advanced');

    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://ao3-helper.example.com' });
    expect((await faq()).element.querySelector('.pattern-where')).toBeNull();
  });
  it('says which run to use, naming every run button by its label', async () => {
    const { element } = await faq();
    const section = element.querySelector('.which-run')?.nextElementSibling?.textContent?.replace(/\s+/g, ' ') ?? '';
    for (const label of ['Quick Scan', '(Full scan) Reindex & Update All', 'Custom run', 'Download/update a specific fic',
      'several fics']) {
      expect(section).toContain(label);
    }
  });
});
