import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CHIME_GAP_MS, CHIME_KEY, CHIME_SOUND_KEY, CHIME_SOUNDS, Chime, ChimePlayer, soundById } from './chime';

/** counts dings instead of making a sound */
export class CountingPlayer extends ChimePlayer {
  played = 0;
  sounds: string[] = [];
  override play(sound?: { id: string }): void {
    this.played++;
    if (sound) this.sounds.push(sound.id);
  }
}

describe('Chime', () => {
  let player: CountingPlayer;

  function chime(): Chime {
    TestBed.configureTestingModule({ providers: [{ provide: ChimePlayer, useValue: player }] });
    return TestBed.inject(Chime);
  }

  beforeEach(() => {
    localStorage.clear();
    player = new CountingPlayer();
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  // region dinging

  it('dings when the page is waiting, being on to begin with', () => {
    const c = chime();
    expect(c.on()).toBe(true);

    c.waiting();
    expect(player.played).toBe(1);
  });

  it('dings once for two waits arriving together, and again for one a while later', () => {
    vi.useFakeTimers();
    const c = chime();

    c.waiting();
    c.waiting();
    expect(player.played).toBe(1);

    vi.advanceTimersByTime(CHIME_GAP_MS);
    c.waiting();
    expect(player.played).toBe(2);
  });

  it('stays quiet once turned off, and remembers it in this browser', () => {
    chime().set(false);
    expect(localStorage.getItem(CHIME_KEY)).toBe('off');

    TestBed.resetTestingModule();
    const again = chime();
    expect(again.on()).toBe(false);
    again.waiting();
    expect(player.played).toBe(0);
  });

  it('plays its sample whatever the setting, so it can be heard before turning it on', () => {
    const c = chime();
    c.set(false);
    c.sample();
    expect(player.played).toBe(1);
  });

  it('turned back on, keeps nothing in this browser', () => {
    const c = chime();
    c.set(false);
    c.set(true);
    expect(localStorage.getItem(CHIME_KEY)).toBeNull();
  });

  it('plays nothing, and throws nothing, where the browser has no Web Audio', () => {
    expect(() => new ChimePlayer().play()).not.toThrow();
  });

  // endregion

  it('rings the sound this browser chose, and the bell for one no longer offered', () => {
    localStorage.setItem(CHIME_SOUND_KEY, 'harp');
    const c = chime();
    c.waiting();
    expect(player.sounds).toEqual(['harp']);
    expect(soundById('kazoo').id).toBe('bell');
  });

  it('keeps every sound short and quiet enough to be a notification', () => {
    for (const sound of CHIME_SOUNDS) {
      const end = Math.max(...sound.notes.map((n) => n.at + n.decay));
      expect(end, sound.id).toBeLessThan(2);
      for (const n of sound.notes) expect(n.gain, sound.id).toBeLessThanOrEqual(0.25);
    }
  });
});
