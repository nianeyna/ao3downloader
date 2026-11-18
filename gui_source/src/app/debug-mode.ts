/**
 * Debug mode itself: this browser's alone (`DEBUG_MODE_KEY`), turned on and off in User
 * settings. Apart from debug.ts so the library can ask about it without importing the mock.
 *
 * **It is the one switch for every debug tool** - the DEBUG tab and banner, the quick scan's
 * date range, the [DEBUG] run buttons and the run window's debug panel - which settings.ini's
 * `EnableDebugTools` used to turn on, until it was taken out at the owner's request. Offered
 * everywhere but to a guest (`guest.ts`), from User settings' *Advanced*, folded away; where it
 * is not allowed it is off, whatever this browser saved.
 */

import { Injectable, computed, inject, signal } from '@angular/core';
import { HelperConnection } from './helper-connection';
import { safeGet, safeRemove, safeSet } from './storage';

export const DEBUG_MODE_KEY = 'ao3.debugMode';

@Injectable({ providedIn: 'root' })
export class DebugMode {
  private readonly helper = inject(HelperConnection);
  /** what this browser chose */
  readonly chosen = signal(safeGet(DEBUG_MODE_KEY) === 'on');
  /** whether it may be offered here: to anyone but a guest */
  readonly allowed = computed(() => !this.helper.guest());
  /** in force: chosen, and allowed */
  readonly on = computed(() => this.chosen() && this.allowed());

  set(on: boolean): void {
    this.chosen.set(on);
    if (on) safeSet(DEBUG_MODE_KEY, 'on');
    else safeRemove(DEBUG_MODE_KEY);
  }
}
