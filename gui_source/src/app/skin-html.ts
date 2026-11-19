/**
 * Putting a skin into a downloaded work's html, for showing it - kept apart from everything else
 * so the library can use it without importing the skins service, which imports the library.
 *
 * The helper does the same to a download when a run fetches AO3's work skin (`ao3.with_skin`),
 * and every skin rule is written `#workskin .<class>`, as on AO3: so the CSS goes at the end of
 * the `<head>` and the body is wrapped in `<div id="workskin">`.
 */

/** whether a work's html already carries a skin of its own - one the helper put in */
export function hasWorkSkin(html: string): boolean {
  return /id\s*=\s*["']workskin["']/i.test(html);
}

/** a skin's CSS that would close its own `<style>` and run on into the page */
export function breaksOutOfStyle(css: string): boolean {
  return /<\/style/i.test(css);
}

/**
 * The work's html shown with `css` as its skin - or exactly as it was when it has a skin of its
 * own (an author's always wins), the CSS is empty or would close its own style, or the file has
 * no head and body to place it in.
 */
export function withReadingSkin(html: string, css: string): string {
  if (!css.trim() || breaksOutOfStyle(css) || hasWorkSkin(html)) return html;
  const lower = html.toLowerCase();
  const headEnd = lower.indexOf('</head>');
  const body = /<body[^>]*>/i.exec(html);
  const bodyEnd = lower.lastIndexOf('</body>');
  if (headEnd < 0 || !body || bodyEnd < body.index + body[0].length) return html;
  const bodyStart = body.index + body[0].length;
  const style = `<style type="text/css">\n/* your reading skin, from FicFairy */\n${css}\n</style>\n`;
  return (
    html.slice(0, headEnd) + style + html.slice(headEnd, bodyStart) + '\n<div id="workskin">' +
    html.slice(bodyStart, bodyEnd) + '</div>\n' + html.slice(bodyEnd)
  );
}
