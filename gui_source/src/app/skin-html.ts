/**
 * Putting a skin into a downloaded work's html, for showing it - kept apart from everything else
 * so the library can use it without importing the skins service, which imports the library.
 *
 * Skins are written for AO3's work page, not for its download, and the two are laid out
 * differently: on the page the tags are a box of their own (`dl.work.meta.group`, each line
 * classed by what it is - `warning tags`, `character tags` ...) outside `#workskin`, and the
 * title, author and summary are AO3's own headings (`div.preface.group`, `h2.title.heading`,
 * `h3.byline.heading`, `div.summary.module` with its `h3.heading`). The download has a plain
 * `dl.tags`, an `h1`, a `div.byline` and `<p>Summary</p>`. So the file is shaped like the page as
 * it is shown (`shapeLikeAo3`) and then wrapped: everything after the tags box goes inside
 * `<div id="workskin">`, which every work skin rule names, and the CSS goes at the end of the
 * `<head>`. Only what is shown changes - the file itself is never written.
 */

/** whether a work's html already carries a skin of its own - one the helper put in */
export function hasWorkSkin(html: string): boolean {
  return /id\s*=\s*["']workskin["']/i.test(html);
}

/** a skin's CSS that would close its own `<style>` and run on into the page */
export function breaksOutOfStyle(css: string): boolean {
  return /<\/style/i.test(css);
}

/** a tags box line's label, as the download writes it, to AO3's class for it */
const TAG_KINDS: Record<string, string> = {
  rating: 'rating tags',
  ratings: 'rating tags',
  'archive warning': 'warning tags',
  'archive warnings': 'warning tags',
  category: 'category tags',
  categories: 'category tags',
  fandom: 'fandom tags',
  fandoms: 'fandom tags',
  relationship: 'relationship tags',
  relationships: 'relationship tags',
  character: 'character tags',
  characters: 'character tags',
  'additional tags': 'freeform tags',
  language: 'language',
  series: 'series',
  collections: 'collections',
  stats: 'stats',
};

/** `<p>Summary</p>` and the like, as the download labels a part of the preface, to AO3's module */
const MODULES: Record<string, { kind: string; heading: string }> = {
  summary: { kind: 'summary', heading: 'Summary:' },
  notes: { kind: 'notes', heading: 'Notes:' },
};

/**
 * A few of AO3's own page styles, for the shape `shapeLikeAo3` gives - what the download's own
 * styles did for its old shape, which no longer match it. Put before the skin, so the skin's own
 * rules win as they do on AO3.
 */
export const AO3_BASICS = `
dl.work.meta { border: 1px solid; padding: 1em; margin: 1em 0; }
dl.work.meta dt { float: left; clear: left; width: 10em; margin: 0; }
dl.work.meta dd { margin: 0 0 0.3em 10.5em; }
.preface .title.heading { text-align: center; font-size: 1.5em; margin: 0.5em 0 0.2em; }
.preface .byline.heading { text-align: center; font-size: 1em; font-weight: normal; margin: 0 0 1em; }
.preface .module .heading { font-size: 1em; margin: 1em 0 0.3em; }
@media (max-width: 42em) {
  dl.work.meta dt { float: none; width: auto; margin: 0.5em 0 0; }
  dl.work.meta dd { margin: 0 0 0 1em; }
}
`;

function addClasses(element: Element, classes: string): void {
  for (const name of classes.split(' ')) if (name) element.classList.add(name);
}

function renamed(doc: Document, element: Element, tag: string, classes: string): Element {
  const made = doc.createElement(tag);
  addClasses(made, classes);
  while (element.firstChild) made.appendChild(element.firstChild);
  element.replaceWith(made);
  return made;
}

/**
 * Shape a downloaded work like AO3's work page, in place: the tags box taken out ahead of
 * everything else and classed as AO3 classes it, and the preface's title, author, summary and
 * notes given AO3's own elements and classes. Answers the tags box (or null when there is none),
 * which is left outside `#workskin` as it is on AO3. Anything not found is left as it was.
 */
export function shapeLikeAo3(doc: Document): Element | null {
  const preface = doc.getElementById('preface');
  if (!preface) return null;
  const meta = preface.querySelector('.meta');
  let tags = meta?.querySelector('dl.tags') ?? null;
  if (tags) {
    tags = renamed(doc, tags, 'dl', 'work meta group');
    let kind = '';
    for (const line of Array.from(tags.children)) {
      if (line.tagName === 'DT') {
        kind = TAG_KINDS[(line.textContent ?? '').replace(/:\s*$/, '').trim().toLowerCase()] ?? '';
      }
      if (kind) addClasses(line, kind);
      if (line.tagName === 'DD' && kind.endsWith('tags')) {
        for (const link of Array.from(line.querySelectorAll('a'))) link.classList.add('tag');
      }
    }
    tags.remove();
  }
  if (meta) {
    const group = renamed(doc, meta, 'div', 'preface group');
    const title = group.querySelector(':scope > h1');
    if (title) renamed(doc, title, 'h2', 'title heading');
    const byline = group.querySelector(':scope > .byline');
    if (byline) {
      const shown = renamed(doc, byline, 'h3', 'byline heading');
      // AO3 names the author alone; the download says "by" first
      const first = shown.firstChild;
      if (first?.nodeType === 3) first.textContent = (first.textContent ?? '').replace(/^\s*by\s+/i, '');
    }
    for (const label of Array.from(group.querySelectorAll(':scope > p'))) {
      const module = MODULES[(label.textContent ?? '').trim().toLowerCase()];
      const quote = label.nextElementSibling;
      if (!module || quote?.tagName !== 'BLOCKQUOTE') continue;
      const box = doc.createElement('div');
      addClasses(box, `${module.kind} module`);
      const heading = doc.createElement('h3');
      addClasses(heading, 'heading');
      heading.textContent = module.heading;
      label.replaceWith(box);
      box.append(heading, quote);
    }
  }
  return tags;
}

/**
 * The work's html shown with `css` as its skin - or exactly as it was when it has a skin of its
 * own (an author's always wins), the CSS is empty or would close its own style, or the file has
 * no head and body to place it in.
 */
export function withReadingSkin(html: string, css: string): string {
  if (!css.trim() || breaksOutOfStyle(css) || hasWorkSkin(html)) return html;
  if (!/<head[\s>]/i.test(html) || !/<body[\s>]/i.test(html)) return html;
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const tags = shapeLikeAo3(doc);

  const workskin = doc.createElement('div');
  workskin.id = 'workskin';
  // AO3's note at the top of a download (where the work was posted) stays above, as the page's
  // own furniture does
  const message = doc.querySelector('#preface > p.message');
  while (doc.body.firstChild) workskin.appendChild(doc.body.firstChild);
  if (message) doc.body.appendChild(message);
  if (tags) doc.body.appendChild(tags);
  doc.body.appendChild(workskin);

  const style = doc.createElement('style');
  style.setAttribute('type', 'text/css');
  style.textContent = `\n/* AO3's own page basics */${AO3_BASICS}\n/* your reading skin, from FicFairy */\n${css}\n`;
  doc.head.appendChild(style);
  return '<!DOCTYPE html>\n' + doc.documentElement.outerHTML;
}

/**
 * A download that already carries its own work skin (the run's *Fetch work skin for HTML
 * downloads* put it in, the whole body inside `#workskin`), shaped like AO3's work page as it is
 * shown - as `withReadingSkin` shapes one with your reading skin - so the author's skin lands as it
 * does on AO3: the tags box taken out ahead of `#workskin` and classed as AO3 classes it, the
 * preface given AO3's elements, and `AO3_BASICS` put in just before the work skin's own styles,
 * so they win as they do on AO3. A file with no work skin, or none that can be found, is left as
 * it is. Only what is shown changes - the file itself is never written.
 */
export function withAo3Shape(html: string, readingSkin = ''): string {
  if (!hasWorkSkin(html)) return html;
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const workskin = doc.getElementById('workskin');
  if (!workskin) return html;
  const message = doc.querySelector('#preface > p.message');
  const tags = shapeLikeAo3(doc);
  // ahead of the work, in the order AO3's page has them
  if (message && workskin.contains(message)) workskin.before(message);
  if (tags) workskin.before(tags);

  // AO3's basics, then your reading skin - the site skin's part - then the work's own skin, as
  // AO3 layers its site skin under a work skin: where they clash, the author's rule wins
  const layers = [`\n/* AO3's own page basics */${AO3_BASICS}`];
  if (readingSkin.trim() && !breaksOutOfStyle(readingSkin)) {
    layers.push(`\n/* your reading skin, from FicFairy - under the work's own skin */\n${readingSkin}\n`);
  }
  // before the work skin's own style (the one naming #workskin), or else last, in turn
  const styles = Array.from(doc.head.querySelectorAll('style'));
  const skin = styles.find((x) => (x.textContent ?? '').includes('#workskin'));
  for (const text of layers) {
    const style = doc.createElement('style');
    style.setAttribute('type', 'text/css');
    style.textContent = text;
    if (skin) skin.before(style);
    else doc.head.append(style);
  }
  return '<!DOCTYPE html>\n' + doc.documentElement.outerHTML;
}

/**
 * How a downloaded work's html is shown when opened from the app: a work with a skin of its own
 * shaped like AO3's page around it, with `readingSkin` layered under its skin unless `layer` is
 * off (`withAo3Shape`);
 * one without, given `readingSkin` when there is one (`withReadingSkin`); otherwise exactly as it
 * is.
 */
export function shownWork(html: string, readingSkin: string, layer = true): string {
  if (hasWorkSkin(html)) return withAo3Shape(html, layer ? readingSkin : '');
  return readingSkin ? withReadingSkin(html, readingSkin) : html;
}

