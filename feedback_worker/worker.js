/**
 * The app's feedback form, turned into a GitHub issue.
 *
 * The page cannot open an issue itself: that needs a GitHub token, and anything built into a
 * page anyone can download is public. So the page posts the form here, and this - which holds
 * the token - opens the issue, labelled `feedback` and its kind (general feedback, feature
 * suggestion or bug), and answers with its address. The person never leaves the page or signs up for
 * anything.
 *
 * It is deliberately not the hosted helper: that one holds an ao3 login and answers its owner
 * alone, behind a passcode. This answers anyone, and can do nothing but file feedback.
 *
 * What keeps it from being a spam cannon:
 * - **A bot check** on every submission. The page shows the widget; its token is checked
 *   here before anything else, and a token works once.
 * - **The page's origin.** Only the origins in ALLOWED_ORIGINS (the hosted page, and
 *   localhost for the apps) get an answer a browser will let a page read.
 * - **Sizes.** Every field is capped, so nobody can post a novel.
 */

export const LIMITS = { message: 5000, name: 100, log: 60000, visit: 30000, version: 40, copy: 60, storage: 60, browser: 300 };
/** GitHub refuses an issue whose body is longer than this */
export const ISSUE_BODY_LIMIT = 65536;
export const LOG_LEFT_OUT = 'A run log was attached, but left out: it would have made this issue longer than GitHub allows.';
/**
 * What kind of feedback it is, chosen on the form: how the issue's first line and title name
 * it, and the label it gets beside `feedback` (the deploy makes each one).
 */
export const KINDS = {
  general: { name: 'General feedback', label: 'general feedback', title: 'Feedback' },
  feature: { name: 'Feature suggestion', label: 'feature suggestion', title: 'Feature suggestion' },
  bug: { name: 'Bug report', label: 'bug', title: 'Bug report' },
};
/** a page from before the kinds sent one of these; it is taken as general feedback */
export const OLD_SENTIMENTS = ['positive', 'negative'];
/**
 * The form's optional quick questions, each answered 1 to 5 by one of five words (`scale`, 1
 * first) - only those the person picked are sent. The issue says the word they chose; the page
 * shows the same words (`RATING_QUESTIONS`).
 */
export const RATINGS = {
  easy: { question: 'How easy is FicFairy to use?',
    scale: ['Very hard', 'Hard', 'Neutral', 'Easy', 'Very easy'] },
  useful: { question: 'How useful do you find it?',
    scale: ['Not useful', 'Slightly useful', 'Neutral', 'Useful', 'Very useful'] },
  confusing: { question: 'How confusing do you find it?',
    scale: ['Not at all confusing', 'Slightly confusing', 'Neutral', 'Confusing', 'Very confusing'] },
  complete: { question: 'Does it do everything you want?',
    scale: ['Missing a lot', 'Missing some', 'Neutral', 'Mostly', 'Does everything I want'] },
};
const SITEVERIFY = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const GITHUB_API = 'https://api.github.com';

/** the origins allowed to read this Worker's answers, from ALLOWED_ORIGINS */
export function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || '')
    .split(',')
    .map((origin) => origin.trim().replace(/\/+$/, ''))
    .filter(Boolean);
}

function cors(origin, env) {
  const headers = { Vary: 'Origin' };
  if (origin && allowedOrigins(env).includes(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS';
    headers['Access-Control-Allow-Headers'] = 'Content-Type';
    headers['Access-Control-Max-Age'] = '86400';
  }
  return headers;
}

function answer(status, body, origin, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...cors(origin, env) },
  });
}

/**
 * A second pass over the log, here, for anything that looks like a password. The page removes
 * the ao3 username before sending - only it knows the name - and no run ever prints a password,
 * so this is a backstop and not the main rule.
 */
export function scrubPasswords(text) {
  return String(text).replace(/(password["']?\s*[:=]\s*)("[^"]*"|'[^']*'|\S+)/gi, '$1[removed]');
}

/** Read and check the form. Returns `{ form }` or `{ error }`. */
export function readForm(raw) {
  if (!raw || typeof raw !== 'object') return { error: 'the form did not arrive' };
  const text = (value) => (typeof value === 'string' ? value.trim() : '');
  let kind = text(raw.kind).toLowerCase();
  if (!kind && OLD_SENTIMENTS.includes(text(raw.sentiment).toLowerCase())) kind = 'general';
  if (!Object.hasOwn(KINDS, kind)) return { error: 'choose general feedback, a feature suggestion or a bug report' };
  // only the questions it knows, each a whole number 1 to 5; anything else is passed over
  const ratings = {};
  if (raw.ratings && typeof raw.ratings === 'object') {
    for (const key of Object.keys(RATINGS)) {
      const value = raw.ratings[key];
      if (Number.isInteger(value) && value >= 1 && value <= 5) ratings[key] = value;
    }
  }
  const message = text(raw.message);
  if (!message) return { error: 'the message is empty' };
  if (message.length > LIMITS.message) {
    return { error: `the message is longer than ${LIMITS.message} characters` };
  }
  const name = text(raw.name);
  if (name.length > LIMITS.name) return { error: `the name is longer than ${LIMITS.name} characters` };
  // a log is kept to its end - whatever went wrong is at the end - and never refused for length
  let log = typeof raw.log === 'string' ? raw.log : '';
  if (log.length > LIMITS.log) log = log.slice(-LIMITS.log);
  // what the person did on this visit, kept to its end for the same reason
  let visit = typeof raw.visit === 'string' ? raw.visit : '';
  if (visit.length > LIMITS.visit) visit = visit.slice(-LIMITS.visit);
  return {
    form: {
      kind,
      ratings,
      message,
      name,
      log: scrubPasswords(log),
      visit: scrubPasswords(visit),
      version: text(raw.version).slice(0, LIMITS.version),
      copy: text(raw.copy).slice(0, LIMITS.copy),
      storage: text(raw.storage).slice(0, LIMITS.storage),
      browser: text(raw.browser).slice(0, LIMITS.browser),
      token: text(raw.turnstileToken),
    },
  };
}

/** A fence the log cannot close early: longer than any run of backticks inside it. */
function fence(text) {
  const longest = Math.max(2, ...(String(text).match(/`+/g) || []).map((run) => run.length));
  return '`'.repeat(longest + 1);
}

/**
 * The issue's title, labels and body. The page leaves out a run log that would not fit; if one
 * still would not, it is left out here (and said so), and then the visit's log kept to its end -
 * GitHub refusing the whole issue would lose the message too.
 */
export function issueFor(form) {
  const issue = issueOf(form);
  if (issue.body.length <= ISSUE_BODY_LIMIT || !form.log) return trimVisit(issue, form);
  return trimVisit(issueOf({ ...form, log: '', logLeftOut: true }), { ...form, log: '' });
}

function trimVisit(issue, form) {
  const over = issue.body.length - ISSUE_BODY_LIMIT;
  if (over <= 0 || !form.visit) return issue;
  return issueOf({ ...form, visit: form.visit.slice(Math.min(form.visit.length, over + 100)) });
}

function issueOf(form) {
  const firstLine = form.message.split('\n')[0].trim();
  const short = firstLine.length > 60 ? `${firstLine.slice(0, 57)}...` : firstLine;
  const lines = [
    `**${KINDS[form.kind].name}**, sent from the app.`,
    '',
    form.message,
    '',
    '---',
    `- **From:** ${form.name || '(no name given)'}`,
    `- **Version:** ${form.version || '(built on their own computer)'}`,
  ];
  if (form.copy) lines.push(`- **Copy:** ${form.copy}`);
  if (form.storage) lines.push(`- **Library:** ${form.storage}`);
  if (form.browser) lines.push(`- **Browser:** ${form.browser}`);
  const answered = Object.keys(RATINGS).filter((key) => form.ratings?.[key]);
  if (answered.length) {
    lines.push('', '**Quick questions**');
    for (const key of answered) {
      const { question, scale } = RATINGS[key];
      lines.push(`- ${question} **${scale[form.ratings[key] - 1]}**`);
    }
  }
  if (form.logLeftOut) lines.push('', `_${LOG_LEFT_OUT}_`);
  if (form.log) {
    const mark = fence(form.log);
    lines.push(
      '',
      '<details><summary>Latest run log (AO3 username removed)</summary>',
      '',
      mark,
      form.log.replace(/\s+$/, ''),
      mark,
      '',
      '</details>',
    );
  }
  if (form.visit) {
    const mark = fence(form.visit);
    lines.push(
      '',
      '<details><summary>What they did on this visit (AO3 username removed)</summary>',
      '',
      mark,
      form.visit.replace(/\s+$/, ''),
      mark,
      '',
      '</details>',
    );
  }
  return {
    title: `${KINDS[form.kind].title}: ${short}`,
    labels: ['feedback', KINDS[form.kind].label],
    body: lines.join('\n'),
  };
}

async function passesTurnstile(token, request, env, fetcher) {
  if (!token) return false;
  const data = new FormData();
  data.append('secret', env.TURNSTILE_SECRET || '');
  data.append('response', token);
  const ip = request.headers.get('CF-Connecting-IP');
  if (ip) data.append('remoteip', ip);
  try {
    const response = await fetcher(SITEVERIFY, { method: 'POST', body: data });
    const result = await response.json();
    return result && result.success === true;
  } catch {
    return false;
  }
}

async function openIssue(issue, env, fetcher) {
  const response = await fetcher(`${GITHUB_API}/repos/${env.GITHUB_REPO}/issues`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'ao3downloader-feedback',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify(issue),
  });
  if (!response.ok) throw new Error(`GitHub answered ${response.status}`);
  const made = await response.json();
  return { number: made.number, url: made.html_url };
}

/** The whole Worker, with `fetch` passed in so the tests can stand in for the bot check and GitHub. */
export async function handle(request, env, fetcher = fetch) {
  const origin = (request.headers.get('Origin') || '').replace(/\/+$/, '');
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: cors(origin, env) });
  }
  if (request.method !== 'POST') return answer(405, { error: 'send the form with POST' }, origin, env);
  // a browser always says where the page came from; anything else did not come from the app
  if (!allowedOrigins(env).includes(origin)) {
    return answer(403, { error: 'this page may not send feedback here' }, origin, env);
  }

  let raw;
  try {
    raw = await request.json();
  } catch {
    return answer(400, { error: 'the form did not arrive' }, origin, env);
  }
  const { form, error } = readForm(raw);
  if (error) return answer(400, { error }, origin, env);

  if (!(await passesTurnstile(form.token, request, env, fetcher))) {
    return answer(403, { error: 'the bot check did not pass - try again' }, origin, env);
  }

  try {
    const made = await openIssue(issueFor(form), env, fetcher);
    return answer(201, { ok: true, ...made }, origin, env);
  } catch {
    return answer(502, { error: 'GitHub did not take it - try again in a minute' }, origin, env);
  }
}

export default {
  fetch: (request, env) => handle(request, env),
};
