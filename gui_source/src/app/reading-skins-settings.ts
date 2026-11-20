import { Component, computed, inject, signal } from '@angular/core';
import { ReadingSkin, ReadingSkins, SkinPlace, skinId } from './reading-skins';

/**
 * User settings' *Reading skins* section (inside its `details`, which User settings draws): your
 * skins, where each is saved, which is the default, and a form to add one - pasted, or from a
 * `.css` file. Debug mode only for now.
 */
@Component({
  selector: 'app-reading-skins-settings',
  templateUrl: './reading-skins-settings.html',
  styleUrl: './reading-skins-settings.css',
})
export class ReadingSkinsSettings {
  protected readonly skins = inject(ReadingSkins);
  protected readonly id = skinId;

  protected readonly name = signal('');
  protected readonly css = signal('');
  protected readonly place = signal<SkinPlace>('browser');
  protected readonly saving = signal(false);
  /** what the last add or remove did, or what went wrong */
  protected readonly outcome = signal('');
  protected readonly problem = signal('');
  /** a skin asked to be removed, until the second press */
  protected readonly confirmingRemove = signal('');

  protected readonly canSave = computed(
    () => !this.saving() && !!this.name().trim() && !!this.css().trim() &&
      (this.place() === 'browser' || this.skins.libraryWritable()),
  );

  protected placeWords(skin: ReadingSkin): string {
    return skin.place === 'browser' ? 'Saved to this browser' : 'Saved in your library';
  }

  protected setDefault(id: string): void {
    this.skins.setDefault(id);
    this.problem.set('');
    const chosen = this.skins.defaultSkin();
    this.outcome.set(chosen ? `"${chosen.name}" is now your default reading skin.` : 'No default reading skin.');
  }

  protected setLayer(on: boolean): void {
    this.skins.setLayer(on);
    this.problem.set('');
    this.outcome.set(on
      ? 'Your reading skin now goes under a work\'s own skin.'
      : 'A work with its own skin now shows that skin alone.');
  }

  /** a `.css` file chosen: its text goes in the box, and its name in the name box if that is empty */
  protected async chooseFile(input: HTMLInputElement): Promise<void> {
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    try {
      this.css.set(await file.text());
      if (!this.name().trim()) this.name.set(file.name.replace(/\.css$/i, ''));
      this.problem.set('');
    } catch {
      this.problem.set('That file could not be read.');
    }
  }

  protected async save(): Promise<void> {
    if (!this.canSave()) return;
    this.saving.set(true);
    this.outcome.set('');
    const name = this.name().trim();
    const problem = await this.skins.add(name, this.css(), this.place());
    this.saving.set(false);
    if (problem) {
      this.problem.set(problem);
      return;
    }
    this.problem.set('');
    this.outcome.set(`"${name}" saved ${this.place() === 'browser' ? 'to this browser' : 'in your library'}.`);
    this.name.set('');
    this.css.set('');
  }

  protected async remove(skin: ReadingSkin): Promise<void> {
    if (this.confirmingRemove() !== skinId(skin)) {
      this.confirmingRemove.set(skinId(skin));
      return;
    }
    this.confirmingRemove.set('');
    const problem = await this.skins.remove(skin);
    this.problem.set(problem ?? '');
    this.outcome.set(problem ? '' : `"${skin.name}" removed.`);
  }
}
