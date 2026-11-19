import { DebugMode } from './debug-mode';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { Jobs, ServerConfig } from './jobs';
import {
  ANSWER_DEFAULTS_KEY,
  AO3_TIME_ZONE_KEY,
  BROWSER_NOTICE_KEY,
  QUESTION_TIMEOUT_KEY,
  DEFAULT_FILETYPES_KEY,
  FOLDER_WARNING_KEY,
  HIDE_WARNING_KEY,
  PROMPTS,
  SYNC_ACK_KEY,
  UPDATE_BANNER_KEY,
  startingFiletypes, promptLabels } from './preferences';
import { UpdateCheck } from './updates';
import { IMPORT_EXCLUDED_FILE, LibraryImports } from './imports';
import { Library } from './library';
import { LibraryStore } from './library-store';
import { CUSTOM_FONT, CUSTOM_FONT_KEY, FONT_KEY, PALETTES, PALETTE_KEY, paletteById } from './appearance';
import { CHIME_KEY, CHIME_SOUND_KEY, Chime, ChimePlayer } from './chime';
import { IniSetting, TOAST_MS, UserSettings } from './user-settings';
import { GuestMode } from './guest';
import { RUN_LOG_LINES_KEY, RUN_LOG_LINES_MIN, TRIM_OLD_RUN_LOGS_KEY } from './run-logs';
import { VISIT_LOG_LIMIT, VISIT_LOG_LIMIT_KEY, VISIT_LOG_MAX, VISIT_LOG_MIN, VisitLog } from './visit-log';

const CONFIG: ServerConfig = {
  username: '',
  filetypes: ['JSON', 'HTML', 'EPUB', 'PDF'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
};

const INI: IniSetting[] = [
  { key: 'ExtraWaitTime', value: '15', default: '40', kind: 'integer', about: 'seconds to wait' },
  { key: 'EnableDebugLogging', value: 'false', default: 'false', kind: 'boolean', about: 'more in the log file' },
];

let fixture: ComponentFixture<UserSettings>;
let element: HTMLElement;
let posted: unknown[];
let iniAnswer: { editable: boolean; file?: string; settings: IniSetting[]; logFiles?: { logFile?: string; updateLogs?: string[] } };

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  fixture.detectChanges();
}

async function open(): Promise<void> {
  fixture = TestBed.createComponent(UserSettings);
  element = fixture.nativeElement as HTMLElement;
  await settle();
}

function choose(selector: string, value: string): void {
  const select = element.querySelector<HTMLSelectElement>(selector)!;
  select.value = value;
  select.dispatchEvent(new Event('change'));
}

function tick(name: string, on: boolean): void {
  const box = element.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
  box.checked = on;
  box.dispatchEvent(new Event('change'));
}

function toast(): string {
  return element.querySelector('.toast')?.textContent?.trim() ?? '';
}

async function leave(selector: string, value: string): Promise<void> {
  const input = element.querySelector<HTMLInputElement>(selector)!;
  input.value = value;
  input.dispatchEvent(new Event('change'));
  await settle();
}

describe('UserSettings', () => {
  beforeEach(() => {
    localStorage.clear();
    posted = [];
    iniAnswer = { editable: true, file: '/home/me/config/settings.ini', settings: INI };
    TestBed.configureTestingModule({ imports: [UserSettings] });
    TestBed.inject(Jobs).config.set(CONFIG);
    const helper = TestBed.inject(HelperConnection);
    vi.spyOn(helper, 'call').mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/api/settings-file' && init?.method === 'POST') {
        const sent = JSON.parse(String(init.body));
        if (sent.reset) {
          posted.push({ reset: true });
          const settings = iniAnswer.settings.map((s) => ({ ...s, value: s.default }));
          return new Response(JSON.stringify({ ...iniAnswer, settings }), { status: 200 });
        }
        const values = sent.values as Record<string, string>;
        posted.push(values);
        const settings = iniAnswer.settings.map((s) => ({ ...s, value: values[s.key] ?? s.value }));
        return new Response(JSON.stringify({ ...iniAnswer, settings }), { status: 200 });
      }
      if (path === '/api/settings-file') return new Response(JSON.stringify(iniAnswer), { status: 200 });
      if (path === '/api/config') return new Response(JSON.stringify(CONFIG), { status: 200 });
      return new Response('{}', { status: 404 });
    });
  });

  // region guest mode

  it("lets a guest change only the time zone and appearance, and saves nothing else even if forced", async () => {
    TestBed.inject(HelperConnection).guest.set(true);
    await open();

    // every other section is faded and out of reach
    expect(element.querySelector('.formats')?.classList).toContain('guest-locked');
    expect(element.querySelector('.formats')?.hasAttribute('inert')).toBe(true);
    expect(element.querySelector('.appearance')?.classList).not.toContain('guest-locked');

    expect(element.querySelector('.ao3-zone')?.classList).not.toContain('guest-locked');
    expect(element.querySelector<HTMLButtonElement>('button.reset-all')!.disabled).toBe(true);

    // a box made clickable again in the page's html still saves nowhere
    tick('format-EPUB', true);
    await settle();
    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();
    expect(toast()).toContain('Not available in guest mode');

    const fairy = element.querySelector<HTMLInputElement>('.palette[data-palette="fairy"] input')!;
    fairy.checked = true;
    fairy.dispatchEvent(new Event('change'));
    await settle();
    expect(localStorage.getItem(PALETTE_KEY)).toBe('fairy');
  });

  it("gives a guest the owner's login last of all, folded under Advanced", async () => {
    const helper = TestBed.inject(HelperConnection);
    helper.settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://ao3-helper.example.com', requirePasscode: true });
    helper.guest.set(true);
    await open();

    const advanced = element.querySelector<HTMLDetailsElement>('details.advanced')!;
    expect(advanced.open).toBe(false);
    // faded like the sections a guest cannot change, but nothing holds it
    expect(advanced.classList).toContain('guest-faded');
    expect(advanced.hasAttribute('inert')).toBe(false);
    expect(advanced.parentElement?.lastElementChild === advanced || advanced.nextElementSibling === null).toBe(true);
    // and nothing else is in it for a guest
    expect(advanced.querySelectorAll('.advanced-part').length).toBe(0);
    expect(advanced.querySelector('input, select')).toBeNull();
    advanced.querySelector<HTMLButtonElement>('button.owner-login')!.click();
    expect(TestBed.inject(GuestMode).loginOpen()).toBe(true);
  });

  it('never offers a passcode on a downloaded copy, which has none to enter', async () => {
    // guest mode reaches a copy on this computer only as a preview - and never asks for a passcode there
    TestBed.inject(HelperConnection).guest.set(true);
    await open();
    expect(element.querySelector('.owner-login')).toBeNull();
    TestBed.inject(GuestMode).openLogin();
    expect(TestBed.inject(GuestMode).loginOpen()).toBe(false);
  });

  it('offers reading skins only in debug mode, after Appearance', async () => {
    await open();
    expect(element.querySelector('details.reading-skins')).toBeNull();

    TestBed.inject(DebugMode).set(true);
    await settle();

    const section = element.querySelector('details.reading-skins')!;
    expect(section.querySelector('app-reading-skins-settings')).not.toBeNull();
    expect(section.previousElementSibling?.classList).toContain('appearance');
  });

  it('folds the file naming and debug mode under Advanced, last of all, for anyone not a guest', async () => {
    await open();
    const advanced = element.querySelector<HTMLDetailsElement>('details.advanced')!;
    expect(advanced.open).toBe(false);
    expect(advanced.nextElementSibling === null || !advanced.nextElementSibling.classList.contains('group')).toBe(true);
    expect(advanced.querySelector('app-name-pattern .pattern-parts')).not.toBeNull();
    expect(advanced.querySelector('.debug-mode input[name="debugMode"]')).not.toBeNull();
    // the owner's way in is a guest's alone
    expect(advanced.querySelector('.owner-login')).toBeNull();
    // and neither is anywhere else on the page
    expect(element.querySelectorAll('app-name-pattern').length).toBe(1);
    expect(element.querySelectorAll('.debug-mode').length).toBe(1);
  });

  it('offers the whole visit log for download, and how many entries it keeps, under Advanced', async () => {
    const visit = TestBed.inject(VisitLog);
    visit.note('Tab opened: works');
    await open();
    const part = element.querySelector('details.advanced .advanced-part.visit-log')!;
    expect(part.querySelector('.saved-to')?.textContent?.trim()).toBe('Saved to this browser');
    expect(element.querySelector<HTMLInputElement>('input[name="visitLogLimit"]')!.value).toBe(String(VISIT_LOG_LIMIT));

    await leave('input[name="visitLogLimit"]', '150');
    expect(visit.limit()).toBe(150);
    expect(localStorage.getItem(VISIT_LOG_LIMIT_KEY)).toBe('150');
    expect(toast()).toContain('150 entries');
    // out of range is kept in range
    await leave('input[name="visitLogLimit"]', '5');
    expect(visit.limit()).toBe(VISIT_LOG_MIN);
    const warning = () => element.querySelector('.visit-log-limit-warning')?.textContent?.trim() ?? null;
    expect(warning()).toBe(`(cannot be smaller than ${VISIT_LOG_MIN.toLocaleString()})`);
    const box = element.querySelector<HTMLInputElement>('input[name="visitLogLimit"]')!;
    box.value = String(VISIT_LOG_MAX + 1);
    box.dispatchEvent(new Event('input'));
    await settle();
    expect(warning()).toBe(`(cannot be larger than ${VISIT_LOG_MAX.toLocaleString()})`);
    box.value = '500';
    box.dispatchEvent(new Event('input'));
    await settle();
    expect(warning()).toBeNull();

    let saved: Blob | null = null;
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      saved = blob as Blob;
      return 'blob:visit';
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    part.querySelector<HTMLButtonElement>('button.download-visit-log')!.click();
    expect(await (saved as unknown as Blob).text()).toContain('Tab opened: works');
    vi.restoreAllMocks();
    visit.setLimit(null);
  });

  it("keeps a run log's length and old runs' logs in settings.ini on this computer, under Advanced", async () => {
    iniAnswer = { ...iniAnswer, settings: [...INI,
      { key: 'RunLogMaxLines', value: '5000', default: '5000', kind: 'integer', about: 'lines' },
      { key: 'KeepLogsOfRecentRunsOnly', value: 'true', default: 'true', kind: 'boolean', about: 'old logs' }] };
    await open();
    const part = element.querySelector('details.advanced .advanced-part.run-logs')!;
    expect(part.querySelector('.saved-to')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('Saved to settings.ini');
    expect(element.querySelector<HTMLInputElement>('input[name="trimOldRunLogs"]')!.checked).toBe(true);
    // shown once, here, not again in the settings.ini list
    expect(element.querySelector('[data-setting="RunLogMaxLines"]')).toBeNull();

    await leave('input[name="runLogMaxLines"]', '20000');
    tick('trimOldRunLogs', false);
    await settle();
    expect(posted).toEqual([{ RunLogMaxLines: '20000' }, { KeepLogsOfRecentRunsOnly: 'false' }]);
  });

  it('sizes the log files in settings.ini on this computer, and says where they are', async () => {
    iniAnswer = { ...iniAnswer, settings: [...INI,
      { key: 'LogFileMaxMB', value: '100', default: '100', kind: 'integer', about: 'log' },
      { key: 'UpdateLogMaxMB', value: '10', default: '10', kind: 'integer', about: 'update log' }],
      logFiles: { logFile: '/home/me/ficfairy/logs/log.jsonl',
                  updateLogs: ['/home/me/ficfairy/update/update.log', '/home/me/ficfairy/update/swap-output.txt'] } };
    await open();
    const part = element.querySelector('details.advanced .advanced-part.log-files')!;
    const paths = Array.from(part.querySelectorAll('.log-path')).map((x) => x.textContent);
    expect(paths).toEqual(['/home/me/ficfairy/logs/log.jsonl', '/home/me/ficfairy/update/update.log', '/home/me/ficfairy/update/swap-output.txt']);
    expect(element.querySelector('[data-setting="LogFileMaxMB"]')).toBeNull();

    await leave('input[name="LogFileMaxMB"]', '250');
    await leave('input[name="UpdateLogMaxMB"]', '-3');
    expect(posted).toEqual([{ LogFileMaxMB: '250' }]);
    expect(toast()).toContain('whole number of MB');
  });

  it('never shows the log files, or where they are, on a hosted copy', async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    await open();
    expect(element.querySelector('.advanced-part.log-files')).toBeNull();
    expect(element.querySelector('.log-path')).toBeNull();
  });

  it("keeps a hosted copy's run-log choices in this browser, in range, and Reset puts them back", async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    await open();
    expect(element.querySelector('.advanced-part.run-logs .saved-to')?.textContent?.trim()).toBe('Saved to this browser');

    const box = element.querySelector<HTMLInputElement>('input[name="runLogMaxLines"]')!;
    const warning = () => element.querySelector('.run-log-lines-warning')?.textContent?.trim() ?? null;
    box.value = '99999';
    box.dispatchEvent(new Event('input'));
    await settle();
    expect(warning()).toBe('(cannot be larger than 50,000)');
    box.value = '7000';
    box.dispatchEvent(new Event('input'));
    await settle();
    expect(warning()).toBeNull();

    await leave('input[name="runLogMaxLines"]', '99');
    expect(warning()).toBe('(cannot be smaller than 500)');
    expect(localStorage.getItem(RUN_LOG_LINES_KEY)).toBe(String(RUN_LOG_LINES_MIN));
    tick('trimOldRunLogs', false);
    await settle();
    expect(localStorage.getItem(TRIM_OLD_RUN_LOGS_KEY)).toBe('false');
    expect(toast()).toContain('every run keeps its log');
    expect(posted).toEqual([]);
  });

  it('never shows a guest the file naming or debug mode, a preview included', async () => {
    TestBed.inject(HelperConnection).guest.set(true);
    TestBed.inject(GuestMode).preview.set(true);
    await open();
    expect(element.querySelector('app-name-pattern')).toBeNull();
    expect(element.querySelector('.debug-mode')).toBeNull();
    expect(element.querySelector('details.advanced')).toBeNull();
  });

  // endregion

  // region appearance

  it('turns the ding off from Appearance, plays it on asking, and Reset turns it back on', async () => {
    const play = vi.spyOn(TestBed.inject(ChimePlayer), 'play').mockImplementation(() => {});
    await open();
    const box = element.querySelector<HTMLInputElement>('.appearance input[name="waitChime"]')!;
    expect(box.checked).toBe(true);

    element.querySelector<HTMLButtonElement>('.appearance button.play-chime')!.click();
    expect(play).toHaveBeenCalledTimes(1);

    box.checked = false;
    box.dispatchEvent(new Event('change'));
    await settle();
    expect(localStorage.getItem(CHIME_KEY)).toBe('off');
    expect(toast()).toContain('no sound');

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    expect(element.querySelector('[data-change="Sound when waiting for you"] .current')?.textContent).toContain('Off');
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();
    expect(localStorage.getItem(CHIME_KEY)).toBeNull();
    expect(TestBed.inject(Chime).on()).toBe(true);
  });


  it('offers a choice of sounds, plays the one chosen, and puts the bell back on reset', async () => {
    const play = vi.spyOn(TestBed.inject(ChimePlayer), 'play').mockImplementation(() => {});
    await open();
    const select = element.querySelector<HTMLSelectElement>('.appearance select[name="waitChimeSound"]')!;
    expect([...select.options].map((o) => o.textContent?.trim())).toEqual(
      ['Bell', 'Fairy sparkle', 'Water droplet', 'Harp']);
    expect(select.value).toBe('bell');

    select.value = 'sparkle';
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    // choosing one plays it, and saves it to this browser
    expect(play.mock.calls.at(-1)![0]!.id).toBe('sparkle');
    expect(localStorage.getItem(CHIME_SOUND_KEY)).toBe('sparkle');
    element.querySelector<HTMLButtonElement>('.appearance button.play-chime')!.click();
    expect(play.mock.calls.at(-1)![0]!.id).toBe('sparkle');

    TestBed.inject(Chime).choose('bell');
    expect(localStorage.getItem(CHIME_SOUND_KEY)).toBeNull();
  });
  it('changes the palette at once, keeps it in this browser, and offers it to Reset', async () => {
    await open();
    expect(element.querySelectorAll('.palette').length).toBe(PALETTES.length);
    expect(element.querySelector('.palette.chosen')?.getAttribute('data-palette')).toBe('charcoal');

    const fairy = element.querySelector<HTMLInputElement>('.palette[data-palette="fairy"] input')!;
    fairy.checked = true;
    fairy.dispatchEvent(new Event('change'));
    await settle();

    expect(localStorage.getItem(PALETTE_KEY)).toBe('fairy');
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe(paletteById('fairy').tokens.bg);
    expect(element.querySelector('.palette.chosen')?.getAttribute('data-palette')).toBe('fairy');
    expect(toast()).toContain('Fairy dust');

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    expect(element.querySelector('[data-change="Palette"] .current')?.textContent).toContain('Fairy dust');
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();
    expect(localStorage.getItem(PALETTE_KEY)).toBeNull();
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe(paletteById('charcoal').tokens.bg);
  });

  it('takes a font by name from this computer, once its box is left, and previews it', async () => {
    await open();
    expect(element.querySelector('input[name="customFont"]')).toBeNull();

    choose('select[name="font"]', CUSTOM_FONT);
    await settle();
    expect(toast()).toContain('Type the name of a font');
    await leave('input[name="customFont"]', 'Comic Sans MS";} body{color:red');
    expect(localStorage.getItem(FONT_KEY)).toBe(CUSTOM_FONT);
    // nothing that could close the quote or the declaration is kept
    expect(localStorage.getItem(CUSTOM_FONT_KEY)).toBe('Comic Sans MS bodycolor:red');
    expect(document.documentElement.style.getPropertyValue('--font-body')).toContain('"Comic Sans MS bodycolor:red"');
    expect(element.querySelector<HTMLElement>('.font-preview')!.style.fontFamily).toContain('Comic Sans MS');

    choose('select[name="font"]', 'serif');
    await settle();
    expect(document.documentElement.style.getPropertyValue('--font-body')).toContain('Georgia');
    expect(toast()).toContain('Book (serif)');
    // the name typed is kept, so the custom font can be picked again
    expect(localStorage.getItem(CUSTOM_FONT_KEY)).toBe('Comic Sans MS bodycolor:red');
  });

  // endregion
  // region exclusion lists for imports

  it('empties every exclusion list for imports on Reset exclusion lists for imports', async () => {
    const texts = new Map<string, string>([[IMPORT_EXCLUDED_FILE, JSON.stringify({ excluded: [
      { id: '1', kind: 'files', files: ['1 a.html'] },
      { id: '2', kind: 'index', files: ['2 b.html'] },
      { id: '3', kind: 'dates', files: ['3 c.html'] },
    ] })]]);
    const store = {
      label: 'memory', check: async () => {}, list: async () => ['works/1 a.html', 'works/2 b.html'],
      read: async (path: string) => texts.get(path) ?? null,
      write: async (path: string, body: Response) => (texts.set(path, await body.text()), 0),
      size: async () => null, delete: async () => {}, rename: async () => {}, mkdir: async () => {},
    } as unknown as LibraryStore;
    TestBed.inject(Library).store.set(store);
    const imports = TestBed.inject(LibraryImports);
    await imports.check();
    expect(imports.found()).toEqual([]);
    await open();

    const section = element.querySelector('.import-exclusions')!;
    // a part of Advanced now
    expect(section.closest('details.advanced')).not.toBeNull();
    expect(section.querySelector('h4')?.textContent).toContain('Exclusion lists for imports');
    expect(section.querySelector('.hint')?.textContent).toContain('files you told FicFairy to ignore');
    const button = section.querySelector<HTMLButtonElement>('button.reset-exclusions')!;
    expect(button.textContent?.trim()).toBe('Reset exclusion lists for imports');
    button.click();
    for (let i = 0; i < 3; i++) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await fixture.whenStable();
    }

    expect(JSON.parse(texts.get(IMPORT_EXCLUDED_FILE)!)).toEqual({ excluded: [] });
    // everything found is offered again
    expect(imports.found().map((w) => w.id)).toEqual(['1', '2']);
    expect(element.textContent).toContain('every exclusion list for imports is empty');
  });

  it('holds the reset until a library is open', async () => {
    await open();
    expect(element.querySelector<HTMLButtonElement>('button.reset-exclusions')!.disabled).toBe(true);
  });

  // endregion

  // region prompts

  it('lists every prompt that offers "do not ask again", grouped by area, even ones never shown', async () => {
    await open();

    const areas = Array.from(element.querySelectorAll('.prompts h4')).map((h) => h.textContent?.trim());
    expect(areas).toEqual(['File imports', 'Your library', 'Runs', 'Updates']);
    const rows = Array.from(element.querySelectorAll('.prompts [data-prompt]'));
    // every one but those kept off the tab (the browser notice), which are still reset
    expect(rows.map((r) => r.getAttribute('data-prompt'))).toEqual(
      PROMPTS.filter((p) => p.listed !== false).map((p) => p.key),
    );
    // nothing stored yet: every one still asks
    for (const row of rows) expect(row.querySelector('select')!.value).toBe('ask');
    const options = Array.from(rows[0].querySelectorAll('option')).map((o) => o.textContent?.trim());
    expect(options).toEqual(['Ask always', 'Do not ask again']);
  });

  it('puts the folder note and the Resolve issues window under File imports, worded for them', async () => {
    await open();
    const imports = [...element.querySelectorAll('.prompts h4')].find((h) => h.textContent?.trim() === 'File imports')!;
    const rows = imports.nextElementSibling!;
    expect([...rows.querySelectorAll('.name')].map((n) => n.textContent?.trim())).toEqual([
      'When loading local files on your machine',
      "Show 'resolve issues' window if a problem was found with your file import",
    ]);
    expect(rows.textContent).toContain('Tell the user how the application finds and identifies files.');
    expect(rows.textContent).toContain('If works are missing an index, files with no date in their name or there are duplicates.');
  });

  it('calls the update banner New app version alert banner, with Show always / Don\'t show', async () => {
    await open();
    const row = element.querySelector(`[data-prompt="${UPDATE_BANNER_KEY}"]`)!;
    expect(row.querySelector('.name')?.textContent?.trim()).toBe('New app version alert banner');
    expect([...row.querySelectorAll('option')].map((o) => o.textContent?.trim())).toEqual(['Show always', "Don't show"]);
  });

  it('shows a prompt already turned off as "Do not ask again"', async () => {
    localStorage.setItem(HIDE_WARNING_KEY, 'off');
    await open();

    expect(element.querySelector<HTMLSelectElement>(`[data-prompt="${HIDE_WARNING_KEY}"] select`)!.value).toBe('skip');
  });

  it('has no Save button: each choice is written the moment it is made, and a toast says so', async () => {
    localStorage.setItem(HIDE_WARNING_KEY, 'off');
    await open();
    expect(element.querySelector('button.save')).toBeNull();
    expect(toast()).toBe('');

    choose(`[data-prompt="${FOLDER_WARNING_KEY}"] select`, 'skip');
    await settle();
    expect(localStorage.getItem(FOLDER_WARNING_KEY)).toBe('true');
    expect(toast()).toBe('Saved: "When loading local files on your machine" - do not ask again');

    choose(`[data-prompt="${SYNC_ACK_KEY}"] select`, 'skip');
    choose(`[data-prompt="${HIDE_WARNING_KEY}"] select`, 'ask');
    await settle();
    expect(localStorage.getItem(SYNC_ACK_KEY)).toBe('true');
    expect(localStorage.getItem(HIDE_WARNING_KEY)).toBeNull();
    expect(toast()).toContain('ask always');
  });

  it('lets the toast go after a moment', async () => {
    vi.useFakeTimers();
    try {
      fixture = TestBed.createComponent(UserSettings);
      element = fixture.nativeElement as HTMLElement;
      fixture.detectChanges();
      choose(`[data-prompt="${FOLDER_WARNING_KEY}"] select`, 'skip');
      fixture.detectChanges();
      expect(toast()).not.toBe('');

      vi.advanceTimersByTime(TOAST_MS + 1);
      fixture.detectChanges();
      expect(toast()).toBe('');
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps the notice about saving to Dropbox or this device off the tab, and still resets it', async () => {
    localStorage.setItem(BROWSER_NOTICE_KEY, 'true');
    await open();
    expect(element.querySelector(`[data-prompt="${BROWSER_NOTICE_KEY}"]`)).toBeNull();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();
    // shown on every visit from now on - not merely once more
    expect(localStorage.getItem(BROWSER_NOTICE_KEY)).toBe('always');
  });

  it('turns the update banner off and on at once, not only on the next visit', async () => {
    const updates = TestBed.inject(UpdateCheck);
    await open();

    choose(`[data-prompt="${UPDATE_BANNER_KEY}"] select`, 'skip');
    expect(updates.dismissed()).toBe(true);

    choose(`[data-prompt="${UPDATE_BANNER_KEY}"] select`, 'ask');
    expect(updates.dismissed()).toBe(false);
    expect(localStorage.getItem(UPDATE_BANNER_KEY)).toBeNull();
  });

  // endregion

  // region download formats

  it("starts from the app's own defaults, with JSON always ticked", async () => {
    await open();

    const json = element.querySelector<HTMLInputElement>('input[name="format-JSON"]')!;
    expect(json.checked && json.disabled).toBe(true);
    expect(element.querySelector<HTMLInputElement>('input[name="format-HTML"]')!.checked).toBe(true);
    expect(element.querySelector<HTMLInputElement>('input[name="format-EPUB"]')!.checked).toBe(false);
  });

  it('saves the formats a run should start with as each is ticked, and leaves the helper defaults alone until then', async () => {
    await open();
    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();

    tick('format-HTML', false);
    tick('format-PDF', true);
    tick('format-EPUB', true);
    await settle();
    expect(toast()).toBe('Saved: runs start with JSON, EPUB, PDF');

    // in the order the helper offers them, whatever order they were ticked in
    expect(JSON.parse(localStorage.getItem(DEFAULT_FILETYPES_KEY)!)).toEqual(['JSON', 'EPUB', 'PDF']);
  });

  it("goes back to the app's defaults", async () => {
    localStorage.setItem(DEFAULT_FILETYPES_KEY, JSON.stringify(['JSON', 'PDF']));
    await open();
    expect(element.querySelector<HTMLInputElement>('input[name="format-PDF"]')!.checked).toBe(true);

    element.querySelector<HTMLButtonElement>('button.reset-formats')!.click();
    await settle();

    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();
  });

  it('starts a run with the saved formats, never dropping the index or adding one not offered', () => {
    localStorage.setItem(DEFAULT_FILETYPES_KEY, JSON.stringify(['PDF', 'AZW3']));

    expect(startingFiletypes(CONFIG)).toEqual(['JSON', 'PDF']);

    localStorage.removeItem(DEFAULT_FILETYPES_KEY);
    expect(startingFiletypes(CONFIG)).toEqual(['JSON', 'HTML']);
  });

  // endregion

  // region settings.ini

  it("offers settings.ini on a helper on this computer, saying where the file is", async () => {
    await open();

    const rows = Array.from(element.querySelectorAll('.ini [data-setting]'));
    expect(rows.map((r) => r.getAttribute('data-setting'))).toEqual(['ExtraWaitTime', 'EnableDebugLogging']);
    expect(element.querySelector('.ini')?.textContent).toContain('/home/me/config/settings.ini');
    expect(rows[0].textContent).toContain('seconds to wait');
  });

  it('writes a setting once its box is left - not while it is being typed', async () => {
    await open();

    const wait = element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!;
    wait.value = '3';
    wait.dispatchEvent(new Event('input'));
    await settle();
    expect(posted).toEqual([]);

    await leave('[data-setting="ExtraWaitTime"] input', '30');
    expect(posted).toEqual([{ ExtraWaitTime: '30' }]);
    expect(toast()).toBe('Saved to settings.ini: ExtraWaitTime=30 - from the next run');

    // leaving it as it is sends nothing
    await leave('[data-setting="ExtraWaitTime"] input', '30');
    expect(posted).toHaveLength(1);
  });

  it('writes a true/false setting as soon as it is picked', async () => {
    await open();

    choose('[data-setting="EnableDebugLogging"] select', 'true');
    await settle();

    expect(posted).toEqual([{ EnableDebugLogging: 'true' }]);
  });

  it('offers a question\'s default answer as a list of the answers it has', async () => {
    iniAnswer = { editable: true, file: 'settings.ini', settings: [
      { key: 'FicHubAnswer', value: 'yes', default: 'yes', kind: 'choice', choices: ['yes', 'no'],
        about: 'whether to ask FicHub' },
    ] };
    await open();

    const options = [...element.querySelectorAll('[data-setting="FicHubAnswer"] option')]
      .map((x) => x.textContent?.trim());
    // in the words of the question's own buttons; the file still holds yes / no
    expect(options).toEqual(['Try FicHub', 'No, leave them']);

    choose('[data-setting="FicHubAnswer"] select', 'no');
    await settle();
    expect(posted).toEqual([{ FicHubAnswer: 'no' }]);
  });

  it('words settings.ini\'s answers for a file with no date of ours as the question\'s own buttons', async () => {
    iniAnswer = { editable: true, file: 'settings.ini', settings: [
      { key: 'AO3GuessedOlderAnswer', value: 'no', default: 'no', kind: 'choice', choices: ['no', 'yes'],
        about: 'a guessed date older than AO3\'s' },
    ] };
    await open();

    const row = element.querySelector('[data-setting="AO3GuessedOlderAnswer"]')!;
    expect([...row.querySelectorAll('option')].map((x) => x.textContent?.trim())).toEqual(['Keep mine', 'Replace it']);
    expect(row.querySelector('.default')?.textContent).toContain('default: Keep mine');

    // the file still holds no / yes
    choose('[data-setting="AO3GuessedOlderAnswer"] select', 'yes');
    await settle();
    expect(posted).toEqual([{ AO3GuessedOlderAnswer: 'yes' }]);
  });

  it('shows nobody\'s here as On / Off, and still writes true / false', async () => {
    iniAnswer = { editable: true, file: 'settings.ini', settings: [
      { key: 'NobodyHereTakeDefaults', value: 'true', default: 'true', kind: 'boolean', about: "nobody's here" },
    ] };
    await open();

    const row = element.querySelector('[data-setting="NobodyHereTakeDefaults"]')!;
    expect([...row.querySelectorAll('option')].map((x) => x.textContent?.trim())).toEqual(['On', 'Off']);
    expect(row.querySelector('.default')?.textContent).toContain('default: On');

    choose('[data-setting="NobodyHereTakeDefaults"] select', 'false');
    await settle();
    expect(posted).toEqual([{ NobodyHereTakeDefaults: 'false' }]);
  });

  it('says when the helper would not take a value, and puts back what the file still says', async () => {
    await open();
    const helper = TestBed.inject(HelperConnection);
    vi.mocked(helper.call).mockImplementation(async () =>
      new Response(JSON.stringify({ error: 'ExtraWaitTime takes a whole number of 0 or more' }), { status: 400 }),
    );

    await leave('[data-setting="ExtraWaitTime"] input', '-3');

    expect(element.querySelector('.toast.problem')?.textContent).toContain(
      'Not saved: ExtraWaitTime takes a whole number',
    );
    expect(element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!.value).toBe('15');
  });

  it('offers no settings.ini when the helper says it cannot be edited', async () => {
    iniAnswer = { editable: false, settings: [] };
    await open();

    expect(element.querySelector('.ini')).toBeNull();
  });

  it('never asks a hosted helper for its settings.ini', async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    await open();

    expect(element.querySelector('.ini')).toBeNull();
    expect(vi.mocked(TestBed.inject(HelperConnection).call).mock.calls.map((c) => c[0])).not.toContain('/api/settings-file');
  });

  it('on a hosted copy, lets this browser choose what unanswered questions take, starting from the helper\'s', async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    TestBed.inject(Jobs).config.set({ ...CONFIG, settings: { ...CONFIG.settings!,
      answerDefaults: { fichub: 'no' }, questionTimeoutMinutes: 20 } });
    await open();
    // folded away like Prompts, saying where it is kept
    const questions = element.querySelector<HTMLDetailsElement>('details.questions')!;
    expect(questions.open).toBe(false);
    // under Appearance, above Prompts
    const order = [...element.querySelectorAll('.group')].map((g) => g.classList[1]);
    expect(order.slice(0, 6)).toEqual(['formats', 'ao3-zone', 'appearance', 'questions', 'always-answers', 'prompts']);
    expect(questions.querySelector('summary .saved-to')?.textContent?.trim()).toBe('Saved to this browser');

    const fichub = element.querySelector<HTMLSelectElement>('[data-question-setting="fichub"] select')!;
    expect(fichub.value).toBe('no');
    expect(element.querySelector<HTMLInputElement>('[data-question-setting="timeout"] input')!.value).toBe('20');

    choose('[data-question-setting="overwrite-older"] select', 'yes');
    await leave('[data-question-setting="timeout"] input', '5');
    expect(JSON.parse(localStorage.getItem(ANSWER_DEFAULTS_KEY)!)).toEqual({ 'overwrite-older': 'yes' });
    expect(localStorage.getItem(QUESTION_TIMEOUT_KEY)).toBe('5');

    // and Reset puts them back to the helper's
    element.querySelector<HTMLButtonElement>('.reset-all')?.click();
    await settle();
    const listed = element.querySelector('.reset-window, [role="dialog"]')?.textContent ?? '';
    expect(listed).toContain('Minutes a question waits for you');
  });

  it('on a hosted copy, gives each question asked once per work its own wait, and lets nobody\'s here be turned off', async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    TestBed.inject(Jobs).config.set({ ...CONFIG, settings: { ...CONFIG.settings!,
      questionTimeouts: { 'overwrite-older': 30, 'unindexed-copy': 15 }, nobodyHere: true } });
    await open();

    const wait = (name: string) => element.querySelector<HTMLInputElement>(`[data-question-setting="${name}-timeout"] input`)!;
    expect(wait('overwrite-older').value).toBe('30');
    expect(wait('unindexed-copy').value).toBe('15');
    expect(element.querySelector<HTMLSelectElement>('[data-question-setting="nobody-here"] select')!.value).toBe('on');

    await leave('[data-question-setting="unindexed-copy-timeout"] input', '2');
    choose('[data-question-setting="nobody-here"] select', 'off');
    await settle();
    expect(JSON.parse(localStorage.getItem('ao3.questionTimeouts')!)).toEqual({ 'unindexed-copy': 2 });
    expect(localStorage.getItem('ao3.nobodyHere')).toBe('off');

    // the defaults are worded as the buttons a question offers
    const options = [...element.querySelectorAll('[data-question-setting="overwrite-older"] option')]
      .map((x) => x.textContent?.trim());
    expect(options).toEqual(['No, keep my newer copy', 'Yes, replace it']);
  });

  it('lists the six cases and the retry question a run can always answer, changes one, and forgets one so it asks again', async () => {
    localStorage.setItem('ao3.alwaysAnswers', JSON.stringify({ 'ao3-older': 'yes' }));
    await open();
    const rows = [...element.querySelectorAll('[data-always]')].map((r) => r.getAttribute('data-always'));
    expect(rows).toEqual(['ao3-older', 'ao3-newer', 'ao3-unknown', 'fichub-older', 'fichub-newer', 'fichub-unknown', 'retry-reread']);
    // each in its own question's words
    expect([...element.querySelectorAll('[data-always="retry-reread"] option')].map((x) => x.textContent?.trim()))
      .toEqual(['Ask every time', 'Always: Yes, read them again', 'Always: No, use the index as it is']);
    expect(element.querySelector<HTMLSelectElement>('[data-always="ao3-older"] select')!.value).toBe('yes');
    // worded as the question's own buttons
    expect([...element.querySelectorAll('[data-always="ao3-older"] option')].map((x) => x.textContent?.trim()))
      .toEqual(['Ask every time', 'Always: Replace it', 'Always: Keep mine', 'Always: Keep both']);

    choose('[data-always="fichub-unknown"] select', 'no');
    await settle();
    expect(JSON.parse(localStorage.getItem('ao3.alwaysAnswers')!)).toEqual({ 'ao3-older': 'yes', 'fichub-unknown': 'no' });

    choose('[data-always="ao3-older"] select', '');
    await settle();
    expect(JSON.parse(localStorage.getItem('ao3.alwaysAnswers')!)).toEqual({ 'fichub-unknown': 'no' });
  });

  it('starts the AO3 time zone at this browser\'s own, keeps another when chosen, and Reset puts it back', async () => {
    const own = Intl.DateTimeFormat().resolvedOptions().timeZone;
    await open();
    const select = () => element.querySelector<HTMLSelectElement>('.ao3-zone select')!;
    expect(select().value).toBe(own);

    const other = own === 'Australia/Sydney' ? 'Europe/London' : 'Australia/Sydney';
    choose('.ao3-zone select', other);
    await settle();
    expect(localStorage.getItem(AO3_TIME_ZONE_KEY)).toBe(other);
    expect(toast()).toContain(`AO3 dates are read in ${other}`);

    // the browser's own is not kept, so the setting follows the browser
    choose('.ao3-zone select', own);
    await settle();
    expect(localStorage.getItem(AO3_TIME_ZONE_KEY)).toBeNull();
  });

  it('keeps no question defaults of its own where settings.ini holds them', async () => {
    await open();
    expect(element.querySelector('.questions')).toBeNull();
  });

  // endregion
  // region where it is kept, and putting it all back

  it('offers debug mode on a downloaded app, now that it is the one switch for every debug tool', async () => {
    localStorage.setItem('ao3.debugMode', 'on');
    await open();
    expect(element.querySelector('.debug-mode')).not.toBeNull();
    expect(TestBed.inject(DebugMode).on()).toBe(true);
    localStorage.removeItem('ao3.debugMode');
  });

  it('says at the top right of every section where it is saved, Advanced always last', async () => {
    await open();

    const sections = [...element.querySelectorAll('.group')];
    const named = sections.map((g) => [
      g.querySelector('h3')?.textContent?.trim(),
      g.querySelector('.group-head .saved-to')?.textContent?.replace(/\s+/g, ' ').trim(),
    ]);
    expect(named[0]).toEqual(['Default download formats', 'Saved to this browser']);
    expect(named[1]).toEqual(['Your AO3 time zone', 'Saved to this browser']);
    expect(named[2]).toEqual(['Appearance', 'Saved to this browser']);
    expect(named.at(-1)?.[0]).toBe('Advanced');
    // and within it, each part says where it is kept
    expect(element.querySelector('.advanced-part.naming > .saved-to')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('Saved to settings.ini');
    expect(element.querySelector('.advanced-part.debug-mode .saved-to')?.textContent?.trim()).toBe('Saved to this browser');
    expect(element.querySelector('.advanced-part.import-exclusions .saved-to')?.textContent?.trim()).toBe('Saved in your library folder');
    // a helper on this computer offers its settings.ini
    expect(named).toContainEqual(['settings.ini', 'Saved to settings.ini']);
    expect(element.querySelector('.browser-note')).toBeNull();
  });

  it('folds Appearance away, with the font above the palettes and no note under its title', async () => {
    await open();
    const appearance = element.querySelector<HTMLDetailsElement>('details.appearance')!;
    expect(appearance.open).toBe(false);
    expect(appearance.querySelector('summary h3')?.textContent).toBe('Appearance');
    expect(appearance.textContent).not.toContain('How this page looks');
    const font = appearance.querySelector('.font-choice')!;
    const palettes = appearance.querySelector('.palettes')!;
    expect(font.compareDocumentPosition(palettes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('folds Prompts away too, with its pill still in its title row', async () => {
    await open();
    const prompts = element.querySelector<HTMLDetailsElement>('details.prompts')!;
    expect(prompts.open).toBe(false);
    expect(prompts.querySelector('summary h3')?.textContent).toBe("'Ask again' Prompts");
    expect(prompts.querySelector('summary .saved-to')?.textContent?.trim()).toBe('Saved to this browser');
  });

  it('shows each setting\'s default beside it', async () => {
    await open();

    expect(element.querySelector('[data-setting="ExtraWaitTime"] .default')?.textContent).toContain('default: 40');
  });

  it('asks before resetting, and Cancel changes nothing', async () => {
    localStorage.setItem(HIDE_WARNING_KEY, 'off');
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    expect(element.querySelector('.modal [role=dialog]')).not.toBeNull();
    Array.from(element.querySelectorAll<HTMLButtonElement>('.confirm-reset button'))
      .find((b) => b.textContent?.trim() === 'Cancel')!.click();
    await settle();

    expect(element.querySelector('.confirm-reset')).toBeNull();
    expect(localStorage.getItem(HIDE_WARNING_KEY)).toBe('off');
    expect(posted).toEqual([]);
  });

  it('resets every prompt to ask always, the formats to the app\'s, and settings.ini to its built defaults', async () => {
    for (const prompt of PROMPTS) localStorage.setItem(prompt.key, prompt.dismissed);
    localStorage.setItem(DEFAULT_FILETYPES_KEY, JSON.stringify(['JSON', 'PDF']));
    const updates = TestBed.inject(UpdateCheck);
    updates.dismissed.set(true);
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    // every value that will change, current then default
    const rows = Array.from(element.querySelectorAll('.changes tbody tr')).map((r) =>
      Array.from(r.children).map((c) => c.textContent?.replace(/\s+/g, ' ').trim()),
    );
    expect(rows).toEqual([
      ...PROMPTS.map((p) => [`Prompts ${p.name}`, promptLabels(p).skip, `→ ${promptLabels(p).ask}`]),
      ['Download formats Formats a run starts with', 'JSON, PDF', '→ JSON, HTML'],
      ['settings.ini ExtraWaitTime', '15', '→ 40'],
    ]);
    expect(element.querySelector('.changes tbody tr:last-child .default-value strong')?.textContent).toBe('40');
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();

    for (const row of Array.from(element.querySelectorAll('.prompts [data-prompt] select'))) {
      expect((row as HTMLSelectElement).value).toBe('ask');
    }
    expect(PROMPTS.every((p) => localStorage.getItem(p.key) !== p.dismissed)).toBe(true);
    expect(updates.dismissed()).toBe(false);
    expect(localStorage.getItem(DEFAULT_FILETYPES_KEY)).toBeNull();
    expect(element.querySelector<HTMLInputElement>('input[name="format-PDF"]')!.checked).toBe(false);
    expect(posted).toEqual([{ reset: true }]);
    expect(element.querySelector<HTMLInputElement>('[data-setting="ExtraWaitTime"] input')!.value).toBe('40');
    expect(toast()).toContain('settings.ini holds its defaults');
  });

  it('resets only what this browser keeps when there is no settings.ini to offer', async () => {
    iniAnswer = { editable: false, settings: [] };
    localStorage.setItem(SYNC_ACK_KEY, 'true');
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();
    expect(element.querySelector('.confirm-reset')?.textContent).not.toContain('settings.ini');
    expect(element.querySelectorAll('.changes tbody tr')).toHaveLength(1);
    element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.click();
    await settle();

    expect(localStorage.getItem(SYNC_ACK_KEY)).toBeNull();
    expect(posted).toEqual([]);
  });

  it('says when everything is already at its default, and offers nothing to press', async () => {
    iniAnswer = { editable: true, file: 'settings.ini', settings: INI.map((x) => ({ ...x, value: x.default })) };
    await open();

    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();

    expect(element.querySelector('.confirm-reset .nothing')?.textContent).toContain('already at its default');
    expect(element.querySelector<HTMLButtonElement>('.confirm-reset button.confirm')!.disabled).toBe(true);
  });

  it('shuts the Reset window on Escape, changing nothing', async () => {
    localStorage.setItem(SYNC_ACK_KEY, 'true');
    await open();
    element.querySelector<HTMLButtonElement>('button.reset-all')!.click();
    await settle();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();

    expect(element.querySelector('.confirm-reset')).toBeNull();
    expect(localStorage.getItem(SYNC_ACK_KEY)).toBe('true');
  });

  // endregion

  // region clearing what this browser keeps

  function clearBox(id: string): HTMLInputElement {
    return element.querySelector<HTMLInputElement>(`[data-clear="${id}"] input`)!;
  }

  async function openClear(): Promise<void> {
    element.querySelector<HTMLButtonElement>('.choose-clear')!.click();
    await settle();
  }

  async function untick(...ids: string[]): Promise<void> {
    for (const id of ids) {
      const box = clearBox(id);
      box.checked = false;
      box.dispatchEvent(new Event('change'));
    }
    await settle();
  }

  it('says nothing in the library is lost, and opens on everything it can clear, ticked', async () => {
    await open();
    expect(element.querySelector('.clear-browser .nothing-lost')?.textContent).toContain('Your downloaded works will not be lost');
    expect(element.querySelector('.choose-clear')?.textContent).toContain('Choose what to clear');
    await openClear();
    const ids = [...element.querySelectorAll('[data-clear]')].map((x) => x.getAttribute('data-clear'));
    // a copy on this computer has no passcode to forget
    expect(ids).toEqual(['settings', 'username', 'visitLog', 'dropboxCache', 'library']);
    expect(ids.every((id) => clearBox(id!).checked)).toBe(true);
    expect(element.querySelector('.confirm-clear')?.textContent?.trim()).toBe('Clear 5 items');
  });

  it('clears only what is ticked, from this browser alone, and never touches settings.ini', async () => {
    localStorage.setItem(PALETTE_KEY, 'charcoal');
    localStorage.setItem(AO3_TIME_ZONE_KEY, 'Europe/London');
    localStorage.setItem('ao3.username', 'Example_Reader');
    localStorage.setItem('ao3.remember', 'true');
    const library = TestBed.inject(Library);
    const forget = vi.spyOn(library, 'forget').mockResolvedValue();
    await open();
    await openClear();
    await untick('visitLog', 'dropboxCache', 'library');
    element.querySelector<HTMLButtonElement>('.confirm-clear')!.click();
    await settle();

    expect(localStorage.getItem(PALETTE_KEY)).toBeNull();
    expect(localStorage.getItem(AO3_TIME_ZONE_KEY)).toBeNull();
    expect(localStorage.getItem('ao3.username')).toBeNull();
    expect(localStorage.getItem('ao3.remember')).toBeNull();
    expect(posted).toEqual([]);
    expect(forget).not.toHaveBeenCalled();
    expect(element.querySelector('.choose-clear-dialog')).toBeNull();
    expect(toast()).toContain('Nothing in your library was touched');
  });

  it('forgets the library and signs out of Dropbox, and empties the visit log and the cache', async () => {
    const library = TestBed.inject(Library);
    const forget = vi.spyOn(library, 'forget').mockResolvedValue();
    const { DropboxSession } = await import('./dropbox');
    const signOut = vi.spyOn(TestBed.inject(DropboxSession), 'signOut').mockResolvedValue();
    const { IndexCache } = await import('./index-cache');
    const cleared = vi.spyOn(TestBed.inject(IndexCache), 'clear').mockResolvedValue();
    const visit = TestBed.inject(VisitLog);
    visit.note('something done earlier');
    await open();
    await openClear();
    await untick('settings', 'username');
    element.querySelector<HTMLButtonElement>('.confirm-clear')!.click();
    await settle();

    expect(signOut).toHaveBeenCalled();
    expect(forget).toHaveBeenCalled();
    expect(cleared).toHaveBeenCalled();
    // emptied after the rest: what came before is gone, and it says it was cleared
    expect(visit.text()).not.toContain('something done earlier');
    expect(visit.text()).toContain('Visit log cleared');
  });

  it('holds the library while a run is going, saying why', async () => {
    TestBed.inject(Jobs).activeRuns.set([{ id: 'r1' }] as never);
    await open();
    await openClear();
    expect(clearBox('library').disabled).toBe(true);
    expect(element.querySelector('[data-clear="library"]')?.textContent).toContain('active run');
    expect(element.querySelector('.confirm-clear')?.textContent?.trim()).toBe('Clear 4 items');
  });

  it('offers neither the passcode nor debug mode, even on a hosted copy that has both', async () => {
    const helper = TestBed.inject(HelperConnection);
    helper.settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://helper.example.com' });
    await open();
    await openClear();
    const ids = [...element.querySelectorAll('[data-clear]')].map((x) => x.getAttribute('data-clear'));
    expect(ids).toEqual(['settings', 'username', 'visitLog', 'dropboxCache', 'library']);
  });

  // endregion
});
