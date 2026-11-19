/**
 * A short ding when the page stops and waits for an answer - a question during a run, or
 * Resolve issues asking which copy to keep - so someone in another tab or away from the screen
 * knows to come back. Made with the browser's own Web Audio, so there is no sound file to ship.
 * On to begin with; this browser can turn it off, or pick another of `CHIME_SOUNDS` (User
 * settings, Appearance).
 */
import { Injectable, inject, signal } from '@angular/core';
import { safeGet, safeRemove, safeSet } from './storage';
import SOUND_LIST from './chime-sounds.json';

/** `off` when this browser turned the ding off; nothing stored means on */
export const CHIME_KEY = 'ao3.waitChime';
/** which sound this browser chose; nothing stored means the default, `DEFAULT_SOUND` */
export const CHIME_SOUND_KEY = 'ao3.waitChimeSound';

/** one note of a sound: its pitch, when it starts, how loud and how long it rings */
export interface ChimeNote {
  f: number;
  at: number;
  gain: number;
  decay: number;
  type: OscillatorType;
}

export interface ChimeSound {
  id: string;
  name: string;
  about: string;
  notes: ChimeNote[];
}

/**
 * The sounds on offer, as notes rather than files - in `chime-sounds.json`, so a preview can be
 * rendered from the very same notes the page plays. The first is the default.
 */
export const CHIME_SOUNDS = SOUND_LIST as ChimeSound[];
export const DEFAULT_SOUND = CHIME_SOUNDS[0].id;

export function soundById(id: string): ChimeSound {
  return CHIME_SOUNDS.find((s) => s.id === id) ?? CHIME_SOUNDS[0];
}

/**
 * Plays the ding. A seam of its own so the specs can count dings: jsdom has no Web Audio, and
 * a test should never make a sound.
 */
@Injectable({ providedIn: 'root' })
export class ChimePlayer {
  private context: AudioContext | null = null;

  play(sound: ChimeSound = CHIME_SOUNDS[0]): void {
    try {
      const Context = globalThis.AudioContext ?? (globalThis as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Context) return;
      this.context ??= new Context();
      const audio = this.context;
      // a browser holds a context made before any click; the page has had clicks by the time
      // anything waits on one, so this lets it sound
      void audio.resume().catch(() => {});
      const start = audio.currentTime;
      // each note rises in 10ms and fades out over its decay
      for (const note of sound.notes) {
        const tone = audio.createOscillator();
        const level = audio.createGain();
        tone.type = note.type;
        tone.frequency.value = note.f;
        level.gain.setValueAtTime(0.0001, start + note.at);
        level.gain.exponentialRampToValueAtTime(note.gain, start + note.at + 0.01);
        level.gain.exponentialRampToValueAtTime(0.0001, start + note.at + note.decay);
        tone.connect(level).connect(audio.destination);
        tone.start(start + note.at);
        tone.stop(start + note.at + note.decay + 0.05);
      }
    } catch {
      // a ding that will not play is no reason for anything else to fail
    }
  }
}

@Injectable({ providedIn: 'root' })
export class Chime {
  private readonly player = inject(ChimePlayer);
  /** whether the page dings when it waits for an answer - this browser's choice */
  readonly on = signal(safeGet(CHIME_KEY) !== 'off');
  /** which sound - this browser's choice too; one no longer offered reads as the default */
  readonly sound = signal(soundById(safeGet(CHIME_SOUND_KEY) ?? DEFAULT_SOUND).id);
  private last = 0;

  choose(id: string): void {
    const sound = soundById(id).id;
    this.sound.set(sound);
    if (sound === DEFAULT_SOUND) safeRemove(CHIME_SOUND_KEY);
    else safeSet(CHIME_SOUND_KEY, sound);
  }

  set(on: boolean): void {
    this.on.set(on);
    if (on) safeRemove(CHIME_KEY);
    else safeSet(CHIME_KEY, 'off');
  }

  /** The page is waiting for an answer: ding, unless turned off or it dinged a moment ago. */
  waiting(): void {
    if (!this.on()) return;
    const now = Date.now();
    // two waits arriving together (or one asked again at once) ding once
    if (now - this.last < CHIME_GAP_MS) return;
    this.last = now;
    this.player.play(soundById(this.sound()));
  }

  /** the chosen sound, whatever the setting - User settings' *Play it* */
  sample(): void {
    this.player.play(soundById(this.sound()));
  }
}

/** no second ding within this long of the first */
export const CHIME_GAP_MS = 1500;
