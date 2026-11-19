import { Component, OnDestroy, computed, inject, output, signal } from '@angular/core';
import { NamePatternEditor } from './name-pattern';
import { ReadingSkinsSettings } from './reading-skins-settings';
import { NamePattern } from './naming';
import { HelperConnection } from './helper-connection';
import { GuestMode } from './guest';
import { AlwaysKind, DefaultName, Jobs, OwnWaitQuestion, ServerConfig } from './jobs';
import {
  BUILT_IN_ANSWERS,
  BUILT_IN_QUESTION_TIMEOUT,
  QUESTION_DEFAULTS,
  QuestionDefault,
  PROMPTS,
  promptLabels,
  PROMPT_AREAS,
  Prompt,
  UPDATE_BANNER_KEY,
  promptAsks,
  ao3TimeZone,
  browserTimeZone,
  knownTimeZones,
  saveAo3TimeZone,
  saveAnswerDefaults,
  saveDefaultFiletypes,
  saveQuestionTimeout,
  savedAnswerDefaults,
  savedQuestionTimeout,
  setPromptAsks,
  startingFiletypes,
  ALWAYS_LABELS,
  BUILT_IN_GUESSED_DATE_TIMEOUT,
  saveGuessedDateTimeout,
  savedGuessedDateTimeout,
  saveAlwaysAnswer,
  savedAlwaysAnswers,
  OWN_WAITS,
  saveOwnWait,
  savedOwnWaits,
  saveNobodyHere,
  savedNobodyHere,
} from './preferences';
import { UpdateCheck } from './updates';
import { LibraryImports } from './imports';
import { Library } from './library';
import { IndexCache } from './index-cache';
import { DropboxSession } from './dropbox';
import { REMEMBER_USERNAME_KEY, SAVED_USERNAME_KEY } from './preferences';
import { safeRemove } from './storage';
import { StorageChoice } from './storage-choice';
import { DebugMode } from './debug';
import { saveText } from './issues';

/** settings.ini's sizes for the helper's log file and the update logs, in MB */
const LOG_FILE_SETTINGS = ['LogFileMaxMB', 'UpdateLogMaxMB'];
import {
  RECENT_RUN_LOGS, RUN_LOG_LINES_DEFAULT, RUN_LOG_LINES_MAX, RUN_LOG_LINES_MIN, RUN_LOG_LINES_SETTING,
  TRIM_OLD_RUN_LOGS_SETTING, runLogLines, saveRunLogLines, saveTrimOldRunLogs, savedRunLogLines,
  savedTrimOldRunLogs,
} from './run-logs';
import { VISIT_LOG_LIMIT, VISIT_LOG_MAX, VISIT_LOG_MIN, VisitLog } from './visit-log';
import { CHIME_SOUNDS, Chime, DEFAULT_SOUND, soundById } from './chime';
import { Appearance, CUSTOM_FONT, DEFAULT_FONT, DEFAULT_PALETTE, FONTS, FONT_GROUPS, PALETTES, fontById, fontStack, paletteById } from './appearance';

export type Asking = 'ask' | 'skip';

/** one setting in the helper's settings.ini, as `GET /api/settings-file` describes it */
export interface IniSetting {
  key: string;
  value: string;
  default: string;
  kind: 'boolean' | 'integer' | 'text' | 'choice';
  /** a 'choice' setting's answers */
  choices?: string[];
  about: string;
}

interface IniFile {
  editable: boolean;
  file?: string;
  settings: IniSetting[];
  /** where the helper's log file and (in the downloaded app) the update logs are */
  logFiles?: { logFile?: string; updateLogs?: string[] };
}

/** one value Reset to defaults would change, as its window lists it */
export interface ResetChange {
  group: 'Appearance' | 'Prompts' | 'Answers to always use' | 'Download formats' | 'AO3 time zone' | 'Questions' | 'Visit log' | 'Run logs' | 'settings.ini';
  name: string;
  current: string;
  default: string;
}

/** something the Clear data window can clear from this browser */
export type BrowserClear = 'settings' | 'username' | 'visitLog' | 'dropboxCache' | 'library';

export interface ClearOption {
  id: BrowserClear;
  label: string;
  /** said under the label, when there is more to say */
  hint?: string;
  /** why it cannot be ticked now, if it cannot */
  held?: string;
}

export interface Toast {
  text: string;
  kind: 'saved' | 'problem';
}

/** how long a toast stays up - long enough to read, short enough not to pile up */
export const TOAST_MS = 2500;
/** a problem stays longer: it says what did not happen, which is worth the time to read */
export const PROBLEM_TOAST_MS = 6000;

/**
 * The User settings tab: what this browser remembers, and - on a helper on this computer -
 * the helper's settings.ini.
 *
 * **Every change is saved the moment it is made**, and a toast says so (or says what went
 * wrong) - there is no Save button to forget. A settings.ini value is sent when its box is
 * left or Enter is pressed (`change`, not `input`), so a number half-typed is never written,
 * and one the helper refuses goes back to what the file still says.
 *
 * Every prompt with a "don't ask again" box is listed, from `PROMPTS`, whether or not this
 * browser has met it yet. settings.ini is offered only where the page's helper is on this
 * computer and says it may be edited (`editable`): a hosted copy's file is written by its
 * deployment, and an edit there would be lost on the next restart.
 */
/** settings.ini's answers for a file without the app's own date (the helper's SCENARIO_SETTINGS) */
/** settings.ini switches shown as On / Off rather than true / false */
const ON_OFF_SETTINGS = new Set(['NobodyHereTakeDefaults']);

/** settings.ini's other question defaults, by the question each answers (the helper's ANSWER_SETTING_FOR) */
const ANSWER_SETTINGS: Record<string, DefaultName> = {
  QuickScanFloorAnswer: 'quick-floor', FicHubAnswer: 'fichub',
  OverwriteNewerCopyAnswer: 'overwrite-older', RetryRereadAnswer: 'retry-reread',
};

const KEEP_OR_REPLACE_SETTINGS = new Set([
  'AO3GuessedOlderAnswer', 'AO3GuessedNewerAnswer', 'AO3UnknownDateAnswer',
  'FicHubGuessedOlderAnswer', 'FicHubGuessedNewerAnswer', 'FicHubUnknownDateAnswer',
]);

@Component({
  selector: 'app-user-settings',
  imports: [NamePatternEditor, ReadingSkinsSettings],
  templateUrl: './user-settings.html',
  styleUrl: './user-settings.css',
  host: { '(document:keydown.escape)': 'escape()' },
})
export class UserSettings implements OnDestroy {
  private readonly jobs = inject(Jobs);
  private readonly helper = inject(HelperConnection);
  private readonly updates = inject(UpdateCheck);
  private readonly imports = inject(LibraryImports);
  private readonly library = inject(Library);
  private readonly indexCache = inject(IndexCache);
  private readonly dropbox = inject(DropboxSession);
  protected readonly debugMode = inject(DebugMode);
  /** FileNamePattern saved from Advanced: the old pattern, for `App.namePatternChanged` */
  readonly namePatternChanged = output<NamePattern>();
  /** the file naming is edited only on a helper on this computer - a hosted one's settings.ini comes from its deployment */
  protected readonly namingOffered = this.helper.isLocal();
  private readonly visit = inject(VisitLog);
  /**
   * Where the exclusion lists are kept: in the library itself, so they follow it - in Dropbox,
   * or in the folder on this computer - whichever this page has open
   */
  private readonly storage = inject(StorageChoice);
  protected readonly libraryPlace = computed(() =>
    this.storage.mode() === 'dropbox' ? 'your Dropbox library' : 'your library folder',
  );

  protected readonly appearance = inject(Appearance);
  protected readonly chime = inject(Chime);
  protected readonly chimeSounds = CHIME_SOUNDS;
  protected readonly palettes = PALETTES;
  protected readonly fonts = FONTS;
  protected readonly fontGroups = FONT_GROUPS;
  /** the palettes, dark ones first, each kind under its own heading */
  protected readonly paletteGroups = [
    { mode: 'dark', name: 'Dark', palettes: PALETTES.filter((p) => p.mode === 'dark') },
    { mode: 'light', name: 'Light', palettes: PALETTES.filter((p) => p.mode === 'light') },
  ];
  protected readonly customFontId = CUSTOM_FONT;
  /** what a font choice looks like, for its preview line */
  protected readonly fontPreview = computed(() => fontStack(this.appearance.font(), this.appearance.customFont()));

  /** a guest changes only the time zone and the appearance, which are theirs (`guest.ts`) */
  protected readonly guest = inject(HelperConnection).guest;
  /** the owner's login, from the Advanced section a guest sees last */
  protected readonly guestMode = inject(GuestMode);

  /**
   * Whether a change is refused for being a guest's - checked in every handler but the time
   * zone's and the appearance's, so a box made clickable again in the page's html still saves
   * nowhere.
   */
  private guestRefused(): boolean {
    if (!this.guest()) return false;
    this.say('Not available in guest mode - only your time zone and appearance can be changed', 'problem');
    return true;
  }

  protected setPalette(id: string): void {
    this.appearance.setPalette(id);
    this.say(`Saved: the ${paletteById(id).name} palette`);
  }

  protected setFont(id: string): void {
    this.appearance.setFont(id);
    if (id === CUSTOM_FONT && !this.appearance.customFont()) {
      this.say('Type the name of a font on this computer to use it');
      return;
    }
    this.say(`Saved: the font is ${this.fontName()}`);
  }

  /** Appearance, so a guest can turn it off too */
  protected setChime(on: boolean): void {
    this.chime.set(on);
    this.say(on ? 'Saved: the page dings when it is waiting for you' : 'Saved: no sound when the page is waiting for you');
  }

  protected setChimeSound(id: string): void {
    this.chime.choose(id);
    this.chime.sample();
    this.say(`Saved: the sound is ${soundById(id).name}`);
  }

  /** sent on change, like a settings.ini box, so the page does not jump about mid-word */
  protected setCustomFont(name: string): void {
    this.appearance.setFont(CUSTOM_FONT, name);
    this.say(this.appearance.customFont()
      ? `Saved: the font is ${this.appearance.customFont()} - if this computer does not have it, the default is used`
      : 'Saved: no font named - the default is used');
  }

  private fontName(): string {
    const font = this.appearance.font();
    return font === CUSTOM_FONT ? this.appearance.customFont() || 'the default' : fontById(font).name;
  }

  protected readonly visitLogMin = VISIT_LOG_MIN;
  protected readonly visitLogMax = VISIT_LOG_MAX;
  protected readonly visitLogDefault = VISIT_LOG_LIMIT;
  protected readonly visitLimit = computed(() => this.visit.limit());
  protected readonly visitSize = computed(() => this.visit.count());

  /** said as the length is typed, and kept once a value out of range is moved to the limit */
  protected readonly visitLogLimitWarning = signal('');
  protected checkVisitLogLimit(box: HTMLInputElement): void {
    this.visitLogLimitWarning.set(outOfRange(box.value, VISIT_LOG_MIN, VISIT_LOG_MAX));
  }

  protected setVisitLogLimit(box: HTMLInputElement): void {
    if (this.guestRefused()) return;
    this.visitLogLimitWarning.set(outOfRange(box.value, VISIT_LOG_MIN, VISIT_LOG_MAX));
    const raw = box.value.trim();
    const limit = this.visit.setLimit(raw === '' ? null : Number(raw));
    box.value = String(limit);
    this.say(`Saved: the visit log keeps ${limit.toLocaleString()} entries`);
  }

  /** the whole of this visit's log, as it is - the user's own copy, so nothing is taken out */
  protected downloadVisitLog(): void {
    this.visit.note('Downloaded the visit log');
    saveText(this.visit.text() + '\n', `ficfairy-visit-log-${new Date().toISOString().slice(0, 10)}`);
  }

  // run logs: settings.ini's two keys on a helper on this computer, this browser's own on a
  // hosted copy (sent with every run). shown in Advanced, so left out of the settings.ini list
  protected readonly RUN_LOG_KEYS = [RUN_LOG_LINES_SETTING, TRIM_OLD_RUN_LOGS_SETTING, ...LOG_FILE_SETTINGS];
  // the helper's log file and the update logs: on this computer only, where the files are
  protected readonly LOG_FILE_SETTINGS = LOG_FILE_SETTINGS;
  protected logFileSetting(key: string): IniSetting | undefined {
    return this.ini()?.settings.find((x) => x.key === key);
  }
  /** a size box left: written to settings.ini, 0 or more whole MB */
  protected async setLogFileSize(key: string, box: HTMLInputElement): Promise<void> {
    const setting = this.logFileSetting(key);
    if (!setting) return;
    const n = Math.round(Number(box.value.trim() || setting.default));
    if (!Number.isFinite(n) || n < 0) {
      box.value = setting.value;
      this.say('Not saved: a size is a whole number of MB, 0 or more (0 for no limit)', 'problem');
      return;
    }
    box.value = String(n);
    await this.editIni(setting, String(n), box);
  }
  protected readonly runLogMin = RUN_LOG_LINES_MIN;
  protected readonly runLogMax = RUN_LOG_LINES_MAX;
  protected readonly runLogDefault = RUN_LOG_LINES_DEFAULT;
  protected readonly recentRunLogs = RECENT_RUN_LOGS;
  private readonly savedLogLines = signal(savedRunLogLines());
  private readonly savedTrimLogs = signal(savedTrimOldRunLogs());
  private iniSetting(key: string): IniSetting | undefined {
    return this.ini()?.settings.find((x) => x.key === key);
  }
  /** a local copy offers them once its settings.ini is read; a hosted copy always */
  protected readonly runLogsOffered = computed(() => !this.local || !!this.ini()?.editable);
  protected readonly runLogLinesNow = computed(() => {
    if (this.local) return runLogLines(this.iniSetting(RUN_LOG_LINES_SETTING)?.value);
    return this.savedLogLines() ?? RUN_LOG_LINES_DEFAULT;
  });
  protected readonly trimOldRunLogsNow = computed(() => {
    if (this.local) return this.iniSetting(TRIM_OLD_RUN_LOGS_SETTING)?.value !== 'false';
    return this.savedTrimLogs() ?? true;
  });

  /** said as the length is typed, and kept once a value out of range is moved to the limit */
  protected readonly runLogLinesWarning = signal('');
  private runLogLinesProblem(raw: string): string {
    return outOfRange(raw, RUN_LOG_LINES_MIN, RUN_LOG_LINES_MAX);
  }
  protected checkRunLogLines(box: HTMLInputElement): void {
    this.runLogLinesWarning.set(this.runLogLinesProblem(box.value));
  }

  protected async setRunLogLines(box: HTMLInputElement): Promise<void> {
    if (this.guestRefused()) return;
    this.runLogLinesWarning.set(this.runLogLinesProblem(box.value));
    const raw = box.value.trim();
    const lines = raw === '' ? RUN_LOG_LINES_DEFAULT : runLogLines(raw);
    box.value = String(lines);
    if (this.local) {
      const setting = this.iniSetting(RUN_LOG_LINES_SETTING);
      if (setting) await this.editIni(setting, String(lines), box);
      return;
    }
    this.savedLogLines.set(saveRunLogLines(lines) === RUN_LOG_LINES_DEFAULT ? null : lines);
    this.say(`Saved: a run's log keeps ${lines.toLocaleString()} lines - from the next run`);
  }

  protected async setTrimOldRunLogs(box: HTMLInputElement): Promise<void> {
    if (this.guestRefused()) return;
    const on = box.checked;
    if (this.local) {
      const setting = this.iniSetting(TRIM_OLD_RUN_LOGS_SETTING);
      if (setting) await this.editIni(setting, on ? 'true' : 'false');
      return;
    }
    saveTrimOldRunLogs(on);
    this.savedTrimLogs.set(on ? null : false);
    this.say(on ? `Saved: only the last ${RECENT_RUN_LOGS} runs keep their logs` : 'Saved: every run keeps its log');
  }

  protected setDebugMode(on: boolean): void {
    if (this.guestRefused()) return;
    this.debugMode.set(on);
    this.say(on ? 'Saved: debug mode is on - the DEBUG tab is beside User settings' : 'Saved: debug mode is off');
  }

  /** a library open that can be written to: the exclusion lists live in it */
  protected readonly canResetExclusions = computed(() => !!this.library.store());
  protected readonly resettingExclusions = signal(false);

  /** empties every exclusion list for imports in the library open now */
  protected async resetExclusions(): Promise<void> {
    if (this.guestRefused()) return;
    if (this.resettingExclusions()) return;
    this.resettingExclusions.set(true);
    try {
      await this.imports.resetExclusions();
      this.say('Reset: every exclusion list for imports is empty - everything found is offered again');
    } catch (e) {
      this.say(`Not reset: ${e instanceof Error ? e.message : String(e)}`, 'problem');
    } finally {
      this.resettingExclusions.set(false);
    }
  }

  /** how many index files this browser keeps for Dropbox libraries, once counted */
  protected readonly cachedFiles = signal<number | null>(null);
  protected readonly clearingCache = signal(false);

  protected async countCache(): Promise<void> {
    this.cachedFiles.set(await this.indexCache.count());
  }

  /**
   * Forget this browser's copy of every Dropbox library's index. Nothing in Dropbox changes; the
   * next time a library is opened, its whole index is downloaded again.
   */
  protected async clearCache(): Promise<void> {
    if (this.guestRefused()) return;
    if (this.clearingCache()) return;
    this.clearingCache.set(true);
    try {
      await this.indexCache.clear();
      this.cachedFiles.set(0);
      this.say('Cleared: the next time your Dropbox library opens, its whole index is downloaded again');
    } finally {
      this.clearingCache.set(false);
    }
  }

  // region clearing what this browser keeps

  /** the window that picks what to clear, open */
  protected readonly choosingClear = signal(false);
  /** what is ticked in it, by id */
  protected readonly clearTicked = signal<ReadonlySet<BrowserClear>>(new Set());
  protected readonly clearingBrowser = signal(false);

  /**
   * What the window offers, in the order shown - each one only where this copy keeps it: the
   * passcode on a hosted copy, debug mode where it can be turned on. Disconnecting the library is
   * held while a run is going, as the library's own buttons are.
   */
  protected readonly clearOptions = computed<ClearOption[]>(() => {
    return [
      { id: 'settings', label: 'Reset user settings back to their defaults' },
      { id: 'username', label: 'Forget any saved AO3 username' },
      { id: 'visitLog', label: 'Empty the visit log',
        hint: 'This always gets cleared upon closing the page.' },
      { id: 'dropboxCache', label: 'Clear the Dropbox library cache',
        hint: 'The next time your Dropbox library opens, its whole index will need to be downloaded again.' },
      { id: 'library', label: 'Forget the open library, and sign out of Dropbox',
        hint: 'Close the file storage location this browser was given, and/or sign out of Dropbox.',
        held: this.jobs.activeRuns().length > 0 ? 'Cannot be changed while an active run is in progress' : '' },
    ];
  });

  protected readonly clearChosen = computed(() =>
    this.clearOptions().filter((o) => !o.held && this.clearTicked().has(o.id)),
  );

  /** open the window with everything it can clear ticked */
  protected chooseWhatToClear(): void {
    if (this.guestRefused()) return;
    this.clearTicked.set(new Set(this.clearOptions().filter((o) => !o.held).map((o) => o.id)));
    this.choosingClear.set(true);
  }

  protected tickClear(id: BrowserClear, ticked: boolean): void {
    this.clearTicked.update((all) => {
      const next = new Set(all);
      if (ticked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  /**
   * Clear what was ticked, here in this browser only. Nothing in the library changes: its works,
   * index, collections and run history stay in the folder or in Dropbox.
   */
  protected async clearBrowser(): Promise<void> {
    if (this.guestRefused() || this.clearingBrowser()) return;
    const chosen = new Set(this.clearChosen().map((o) => o.id));
    if (!chosen.size) return;
    this.clearingBrowser.set(true);
    const done: string[] = [];
    try {
      if (chosen.has('settings')) {
        this.resetBrowserSettings();
        done.push('settings reset');
      }
      if (chosen.has('username')) {
        safeRemove(SAVED_USERNAME_KEY);
        safeRemove(REMEMBER_USERNAME_KEY);
        done.push('saved username forgotten');
      }
      if (chosen.has('library') && !this.jobs.activeRuns().length) {
        // signing out of Dropbox clears its cache too
        await this.dropbox.signOut();
        await this.library.forget();
        done.push('library forgotten and signed out of Dropbox');
      }
      if (chosen.has('dropboxCache')) {
        await this.indexCache.clear();
        this.cachedFiles.set(0);
        done.push('Dropbox cache cleared');
      }
      // last, so the visit log notes everything above before it goes
      if (chosen.has('visitLog')) {
        this.visit.clear();
        done.push('visit log emptied');
      }
      this.choosingClear.set(false);
      this.say(`Cleared from this browser: ${done.join(', ')}. Nothing in your library was touched.`);
    } catch (e) {
      this.say(`Not everything was cleared: ${e instanceof Error ? e.message : String(e)}`, 'problem');
    } finally {
      this.clearingBrowser.set(false);
    }
  }

  // endregion

  protected readonly labelsOf = promptLabels;
  protected readonly areas = PROMPT_AREAS.map((area) => ({
    area,
    prompts: PROMPTS.filter((p) => p.area === area && p.listed !== false),
  }));
  protected readonly asking = signal<Record<string, Asking>>(
    Object.fromEntries(PROMPTS.map((p) => [p.key, promptAsks(p) ? 'ask' : 'skip'])),
  );

  protected readonly config = signal<ServerConfig | null>(this.jobs.config());
  protected readonly helperAnswered = signal(true);
  protected readonly formats = signal<string[]>([]);

  protected readonly local = this.helper.isLocal();
  protected readonly ini = signal<IniFile | null>(null);

  /**
   * A hosted copy's question defaults, kept by this browser (its settings.ini cannot be
   * edited from here): what is saved, and what the helper's own deployment says when not.
   */
  protected readonly questions = QUESTION_DEFAULTS;
  private readonly savedAnswers = signal(savedAnswerDefaults());
  private readonly savedTimeout = signal(savedQuestionTimeout());
  protected helperAnswer(name: DefaultName): string {
    return this.config()?.settings?.answerDefaults?.[name] ?? BUILT_IN_ANSWERS[name];
  }
  protected answer(name: DefaultName): string {
    return this.savedAnswers()[name] ?? this.helperAnswer(name);
  }
  protected helperTimeout(): number {
    return this.config()?.settings?.questionTimeoutMinutes ?? BUILT_IN_QUESTION_TIMEOUT;
  }
  protected readonly questionTimeout = computed(() => this.savedTimeout() ?? this.helperTimeout());
  /** the same, for a question about a file without the app's own date (1 minute built in) */
  private readonly savedGuessedTimeout = signal(savedGuessedDateTimeout());
  protected helperGuessedTimeout(): number {
    return this.config()?.settings?.guessedDateTimeoutMinutes ?? BUILT_IN_GUESSED_DATE_TIMEOUT;
  }
  protected readonly guessedTimeout = computed(() => this.savedGuessedTimeout() ?? this.helperGuessedTimeout());
  /** a hosted copy's wait for each question asked once per work that has its own */
  protected readonly ownWaits = OWN_WAITS;
  private readonly savedWaits = signal(savedOwnWaits());
  protected helperWait(name: OwnWaitQuestion): number {
    return this.config()?.settings?.questionTimeouts?.[name] ?? BUILT_IN_QUESTION_TIMEOUT;
  }
  protected ownWait(name: OwnWaitQuestion): number {
    return this.savedWaits()[name] ?? this.helperWait(name);
  }
  /** a hosted copy's 'nobody's here' (on unless turned off) */
  private readonly savedNobody = signal(savedNobodyHere());
  protected helperNobodyHere(): boolean {
    return this.config()?.settings?.nobodyHere ?? true;
  }
  protected readonly nobodyHere = computed(() => this.savedNobody() ?? this.helperNobodyHere());
  /**
   * Answers chosen to always use for a file without the app's own date, by case - ticked on a
   * question during a run, or set here. Every page sends them with every run, local or hosted.
   */
  protected readonly scenarios = ALWAYS_LABELS;
  protected readonly alwaysAnswers = signal(savedAlwaysAnswers());
  /** an answer kept for good, in the words of its question's button */
  protected alwaysWords(choice: string | undefined, kind: AlwaysKind = 'ao3-older'): string {
    const words = ALWAYS_LABELS.find((x) => x.name === kind);
    if (!words) return 'Ask every time';
    if (choice === 'both' && words.both) return `Always: ${words.both}`;
    if (choice !== 'yes' && choice !== 'no') return 'Ask every time';
    return `Always: ${choice === 'yes' ? words.yes : words.no}`;
  }
  protected setAlways(scenario: AlwaysKind, label: string, value: string): void {
    if (this.guestRefused()) return;
    const choice = value === 'yes' || value === 'no' || value === 'both' ? value : null;
    saveAlwaysAnswer(scenario, choice);
    this.alwaysAnswers.set(savedAlwaysAnswers());
    this.say(`${label}: ${this.alwaysWords(choice ?? undefined, scenario)}`);
  }

  /**
   * A settings.ini value as the page words it. The six cases of a file without the app's own
   * date are kept as no / yes, but shown as the question's own buttons - Keep mine / Replace it.
   */
  protected iniWords(key: string, value: string): string {
    // a switch, not a yes/no answer: said On / Off (the file still holds true / false)
    if (ON_OFF_SETTINGS.has(key)) return value === 'true' ? 'On' : value === 'false' ? 'Off' : value;
    const question = QUESTION_DEFAULTS.find((q) => q.name === ANSWER_SETTINGS[key]);
    if (question) return this.choiceLabel(question, value);
    if (!KEEP_OR_REPLACE_SETTINGS.has(key)) return value;
    return value === 'yes' ? 'Replace it' : value === 'no' ? 'Keep mine' : value === 'both' ? 'Keep both' : value;
  }

  protected choiceLabel(question: QuestionDefault, value: string): string {
    return question.choices.find((c) => c.value === value)?.label ?? value;
  }

  /** the zone AO3 shows this person's dates in - this browser's own until changed */
  protected readonly browserZone = browserTimeZone();
  protected readonly zones = knownTimeZones();
  protected readonly ao3Zone = signal(ao3TimeZone());

  protected setAo3Zone(zone: string): void {
    if (!this.zones.includes(zone)) return;
    // this browser's own zone is not kept, so the setting follows the browser if it moves
    saveAo3TimeZone(zone === this.browserZone ? null : zone);
    this.ao3Zone.set(zone);
    this.say(`Saved: AO3 dates are read in ${zone} - from the next run`);
  }

  /** the Reset to defaults window is open */
  protected readonly confirmingReset = signal(false);

  /**
   * Every value Reset would change - only those that differ from their default, so the
   * window shows exactly what pressing it does. Worked out from what is on screen, which
   * is what has been saved: every change here is saved as it is made.
   */
  protected readonly resetChanges = computed<ResetChange[]>(() => {
    const changes: ResetChange[] = [];
    if (this.appearance.palette() !== DEFAULT_PALETTE) {
      changes.push({ group: 'Appearance', name: 'Palette', current: paletteById(this.appearance.palette()).name,
                     default: paletteById(DEFAULT_PALETTE).name });
    }
    if (this.appearance.font() !== DEFAULT_FONT) {
      changes.push({ group: 'Appearance', name: 'Font', current: this.fontName(), default: fontById(DEFAULT_FONT).name });
    }
    if (!this.chime.on()) {
      changes.push({ group: 'Appearance', name: 'Sound when waiting for you', current: 'Off', default: 'On' });
    }
    if (this.chime.sound() !== DEFAULT_SOUND) {
      changes.push({ group: 'Appearance', name: 'Sound', current: soundById(this.chime.sound()).name,
                     default: soundById(DEFAULT_SOUND).name });
    }
    const askingNow = this.asking();
    for (const prompt of PROMPTS) {
      if (askingNow[prompt.key] === 'skip') {
        changes.push({ group: 'Prompts', name: prompt.name, current: promptLabels(prompt).skip, default: promptLabels(prompt).ask });
      }
    }
    const config = this.config();
    if (config) {
      const order = (list: string[]) => config.filetypes.filter((x) => list.includes(x)).join(', ');
      const now = order(this.formats());
      const fresh = order([...config.forced, ...(config.defaults ?? [])]);
      if (now !== fresh) changes.push({ group: 'Download formats', name: 'Formats a run starts with', current: now, default: fresh });
    }
    if (this.ao3Zone() !== this.browserZone) {
      changes.push({ group: 'AO3 time zone', name: 'Your AO3 time zone', current: this.ao3Zone(),
                     default: `${this.browserZone} (this browser)` });
    }
    if (!this.local) {
      if (this.guessedTimeout() !== this.helperGuessedTimeout()) {
        changes.push({ group: 'Questions', name: 'Minutes a question about a file with no date in its name waits',
                       current: String(this.guessedTimeout()), default: String(this.helperGuessedTimeout()) });
      }
      if (this.questionTimeout() !== this.helperTimeout()) {
        changes.push({ group: 'Questions', name: 'Minutes a question waits for you',
                       current: String(this.questionTimeout()), default: String(this.helperTimeout()) });
      }
      for (const { name, label } of OWN_WAITS) {
        if (this.ownWait(name) !== this.helperWait(name)) {
          changes.push({ group: 'Questions', name: label,
                         current: String(this.ownWait(name)), default: String(this.helperWait(name)) });
        }
      }
      if (this.nobodyHere() !== this.helperNobodyHere()) {
        changes.push({ group: 'Questions', name: "When nobody answers, don't wait on the rest",
                       current: this.nobodyHere() ? 'On' : 'Off', default: this.helperNobodyHere() ? 'On' : 'Off' });
      }
      for (const question of QUESTION_DEFAULTS) {
        const now = this.answer(question.name);
        const fresh = this.helperAnswer(question.name);
        if (now !== fresh) {
          changes.push({ group: 'Questions', name: question.label,
                         current: this.choiceLabel(question, now), default: this.choiceLabel(question, fresh) });
        }
      }
    }
    if (!this.local && this.savedLogLines() !== null) {
      changes.push({ group: 'Run logs', name: 'Maximum length of each log file (in lines)', current: this.runLogLinesNow().toLocaleString(),
                     default: RUN_LOG_LINES_DEFAULT.toLocaleString() });
    }
    if (!this.local && this.savedTrimLogs() === false) {
      changes.push({ group: 'Run logs', name: `Only keep logs of the last ${RECENT_RUN_LOGS} runs`, current: 'Off', default: 'On' });
    }
    if (this.visitLimit() !== VISIT_LOG_LIMIT) {
      changes.push({ group: 'Visit log', name: 'Maximum length of the visit log (in lines)', current: this.visitLimit().toLocaleString(),
                     default: VISIT_LOG_LIMIT.toLocaleString() });
    }
    const always = this.alwaysAnswers();
    for (const { name, label } of ALWAYS_LABELS) {
      if (always[name]) {
        changes.push({ group: 'Answers to always use', name: label,
                       current: this.alwaysWords(always[name], name), default: this.alwaysWords(undefined) });
      }
    }
    const file = this.ini();
    if (file?.editable) {
      for (const setting of file.settings) {
        // the naming pattern is left as it is by a reset (the DEBUG tab changes it)
        if (setting.key !== 'FileNamePattern' && setting.value !== setting.default) {
          changes.push({ group: 'settings.ini', name: setting.key, current: this.iniWords(setting.key, setting.value) || '(empty)', default: this.iniWords(setting.key, setting.default) || '(empty)' });
        }
      }
    }
    return changes;
  });

  readonly toast = signal<Toast | null>(null);
  private toastTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    void this.load();
    void this.countCache();
  }

  ngOnDestroy(): void {
    clearTimeout(this.toastTimer);
  }

  /** a toast left from the last change would sit over the window's list, so it goes */
  protected openReset(): void {
    if (this.guestRefused()) return;
    clearTimeout(this.toastTimer);
    this.toast.set(null);
    this.confirmingReset.set(true);
  }

  /** Escape shuts the Reset window without changing anything */
  protected escape(): void {
    this.confirmingReset.set(false);
  }

  private async load(): Promise<void> {
    const config = this.config() ?? (await this.jobs.loadConfig());
    this.config.set(config);
    this.helperAnswered.set(!!config);
    if (config) this.formats.set(startingFiletypes(config));
    if (this.local) await this.loadIni();
  }

  private async loadIni(): Promise<void> {
    try {
      const response = await this.helper.call('/api/settings-file');
      if (!response.ok) throw new Error(String(response.status));
      this.ini.set((await response.json()) as IniFile);
    } catch {
      // an older helper has no such endpoint, and a stopped one does not answer: either
      // way there is nothing here to edit
      this.ini.set(null);
    }
  }

  private say(text: string, kind: Toast['kind'] = 'saved'): void {
    // every setting changed, and what it was set to, goes into this visit's log for a bug report
    this.visit.note(`User settings: ${text}`);
    clearTimeout(this.toastTimer);
    this.toast.set({ text, kind });
    this.toastTimer = setTimeout(() => this.toast.set(null), kind === 'saved' ? TOAST_MS : PROBLEM_TOAST_MS);
  }

  protected choose(prompt: Prompt, value: string): void {
    if (this.guestRefused()) return;
    const asks = value !== 'skip';
    this.asking.update((all) => ({ ...all, [prompt.key]: asks ? 'ask' : 'skip' }));
    setPromptAsks(prompt, asks);
    // the banner reads its flag once, when the page opens - tell it now
    if (prompt.key === UPDATE_BANNER_KEY) this.updates.dismissed.set(!asks);
    const labels = promptLabels(prompt);
    this.say(`Saved: "${prompt.name}" - ${(asks ? labels.ask : labels.skip).toLowerCase()}`);
  }

  protected setAnswer(question: QuestionDefault, value: string): void {
    if (this.guestRefused()) return;
    if (!question.choices.some((c) => c.value === value)) return;
    const answers = { ...this.savedAnswers() };
    // the same as the helper's is not kept, so a later change to the deployment still shows
    if (value === this.helperAnswer(question.name)) delete answers[question.name];
    else answers[question.name] = value;
    saveAnswerDefaults(answers);
    this.savedAnswers.set(answers);
    this.say(`Saved: "${question.label}" - ${this.choiceLabel(question, value)} - from the next run`);
  }

  protected setQuestionTimeout(value: string, input?: HTMLInputElement): void {
    if (this.guestRefused()) return;
    const minutes = Number(value);
    if (value.trim() === '' || !Number.isInteger(minutes) || minutes < 0) {
      if (input) input.value = String(this.questionTimeout());
      this.say('Not saved: the wait is a whole number of minutes, 0 or more', 'problem');
      return;
    }
    const kept = minutes === this.helperTimeout() ? null : minutes;
    saveQuestionTimeout(kept);
    this.savedTimeout.set(kept);
    this.say(`Saved: questions wait ${minutes} minute${minutes === 1 ? '' : 's'} - from the next run`);
  }

  protected setGuessedTimeout(value: string, input?: HTMLInputElement): void {
    if (this.guestRefused()) return;
    const minutes = Number(value);
    if (value.trim() === '' || !Number.isInteger(minutes) || minutes < 0) {
      if (input) input.value = String(this.guessedTimeout());
      this.say('Not saved: the wait is a whole number of minutes, 0 or more', 'problem');
      return;
    }
    const kept = minutes === this.helperGuessedTimeout() ? null : minutes;
    saveGuessedDateTimeout(kept);
    this.savedGuessedTimeout.set(kept);
    this.say(`Saved: questions about a file with no date in its name wait ${minutes} minute${minutes === 1 ? '' : 's'} - from the next run`);
  }

  protected setOwnWait(name: OwnWaitQuestion, label: string, value: string, input?: HTMLInputElement): void {
    if (this.guestRefused()) return;
    const minutes = Number(value);
    if (value.trim() === '' || !Number.isInteger(minutes) || minutes < 0) {
      if (input) input.value = String(this.ownWait(name));
      this.say('Not saved: the wait is a whole number of minutes, 0 or more', 'problem');
      return;
    }
    const kept = minutes === this.helperWait(name) ? null : minutes;
    saveOwnWait(name, kept);
    this.savedWaits.set(savedOwnWaits());
    this.say(`Saved: ${label} - ${minutes} - from the next run`);
  }

  protected setNobodyHere(on: boolean): void {
    if (this.guestRefused()) return;
    saveNobodyHere(on === this.helperNobodyHere() ? null : on);
    this.savedNobody.set(savedNobodyHere());
    this.say(on ? "Saved: once a question goes unanswered, the rest like it take their default at once - from the next run"
                : 'Saved: every question is asked and waits its time - from the next run');
  }

  protected isForced(filetype: string): boolean {
    return this.config()?.forced.includes(filetype) ?? false;
  }

  protected toggleFormat(filetype: string, on: boolean): void {
    if (this.guestRefused()) return;
    const config = this.config();
    if (!config || this.isForced(filetype)) return;
    this.formats.update((all) => (on ? [...all.filter((x) => x !== filetype), filetype] : all.filter((x) => x !== filetype)));
    // in the order the helper offers them, so the stored list reads the same way every time
    saveDefaultFiletypes(config.filetypes.filter((x) => this.formats().includes(x)));
    this.say(`Saved: runs start with ${this.formatList()}`);
  }

  protected resetFormats(): void {
    if (this.guestRefused()) return;
    const config = this.config();
    if (!config) return;
    saveDefaultFiletypes(null);
    this.formats.set(startingFiletypes(config));
    this.say(`Saved: back to the app's defaults - ${this.formatList()}`);
  }

  private formatList(): string {
    const config = this.config();
    return (config?.filetypes ?? []).filter((x) => this.formats().includes(x)).join(', ');
  }

  /**
   * Everything back as it came: every prompt asks always, runs start with the app's own
   * formats, and settings.ini - where it is offered - holds the values this copy was built
   * with (the downloaded app's own; the template's for anything else).
   */
  protected async resetAll(): Promise<void> {
    if (this.guestRefused()) return;
    this.confirmingReset.set(false);
    this.resetBrowserSettings();

    if (!this.ini()?.editable) {
      this.say(this.local
        ? 'Reset: the page looks as it came, every prompt asks always, and runs start with the app\'s default formats'
        : 'Reset: the page looks as it came, every prompt asks always, runs start with the app\'s default formats, and questions take the app\'s default answers');
      return;
    }
    try {
      const response = await this.helper.call('/api/settings-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reset: true }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || `the helper answered ${response.status}`);
      this.ini.set(body as IniFile);
      void this.jobs.loadConfig();
      this.say('Reset: the page looks as it came, every prompt asks always, runs start with the app\'s default formats, and settings.ini holds its defaults');
    } catch (e) {
      this.say(
        `Prompts and formats were reset, but settings.ini was not: ${e instanceof Error ? e.message : String(e)}`,
        'problem',
      );
    }
  }

  /**
   * Every setting this browser keeps back to its default - appearance, prompts, formats, the AO3
   * time zone, question defaults and waits, answers to always use, run-log and visit-log lengths.
   * settings.ini is not this browser's, and is left to Reset to defaults.
   */
  private resetBrowserSettings(): void {
    this.appearance.reset();
    this.chime.set(true);
    this.chime.choose(DEFAULT_SOUND);
    for (const prompt of PROMPTS) setPromptAsks(prompt, true);
    this.asking.set(Object.fromEntries(PROMPTS.map((p) => [p.key, 'ask' as Asking])));
    this.updates.dismissed.set(false);
    saveDefaultFiletypes(null);
    saveAnswerDefaults(null);
    saveQuestionTimeout(null);
    saveGuessedDateTimeout(null);
    this.savedGuessedTimeout.set(null);
    for (const { name } of OWN_WAITS) saveOwnWait(name, null);
    this.savedWaits.set({});
    saveNobodyHere(null);
    this.savedNobody.set(null);
    for (const { name } of ALWAYS_LABELS) saveAlwaysAnswer(name, null);
    this.alwaysAnswers.set({});
    this.visit.setLimit(null);
    saveRunLogLines(null);
    this.savedLogLines.set(null);
    saveTrimOldRunLogs(null);
    this.savedTrimLogs.set(null);
    saveAo3TimeZone(null);
    this.ao3Zone.set(this.browserZone);
    this.savedAnswers.set({});
    this.savedTimeout.set(null);
    const config = this.config();
    if (config) this.formats.set(startingFiletypes(config));
  }

  /** one setting changed and left: write it now. A refused value is put back as the file has it */
  protected async editIni(setting: IniSetting, value: string, input?: HTMLInputElement | HTMLSelectElement): Promise<void> {
    if (this.guestRefused()) return;
    if (value === setting.value) return;
    try {
      const response = await this.helper.call('/api/settings-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: { [setting.key]: value } }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || `the helper answered ${response.status}`);
      this.ini.set(body as IniFile);
      const words = this.iniWords(setting.key, value.trim());
      this.say(`Saved to settings.ini: ${setting.key}=${value.trim()}${words !== value.trim() ? ` (${words})` : ''} - from the next run`);
      // the run window reads these through the config, so it sees the new value at once
      void this.jobs.loadConfig();
    } catch (e) {
      if (input) input.value = setting.value;
      this.say(`Not saved: ${e instanceof Error ? e.message : String(e)}`, 'problem');
    }
  }
}

/** the warning under a length box whose typed number is outside what it takes; '' when it is not */
function outOfRange(raw: string, min: number, max: number): string {
  const n = Number(raw.trim());
  if (raw.trim() === '' || !Number.isFinite(n)) return '';
  if (n < min) return `(cannot be smaller than ${min.toLocaleString()})`;
  if (n > max) return `(cannot be larger than ${max.toLocaleString()})`;
  return '';
}
