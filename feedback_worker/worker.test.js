// The feedback Worker, with the bot check and GitHub stood in for - nothing here
// reaches either. Run with `node --test` from this folder (CI does, in the tests workflow).

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { ISSUE_BODY_LIMIT, LIMITS, LOG_LEFT_OUT, handle, issueFor, readForm, scrubPasswords } from './worker.js';

const ENV = {
  GITHUB_REPO: 'someone/ao3downloader',
  ALLOWED_ORIGINS: 'https://someone.github.io, http://localhost:4200',
  GITHUB_TOKEN: 'a-token',
  TURNSTILE_SECRET: 'a-secret',
};

const FORM = {
  kind: 'general',
  message: 'The quick scan is great.\nThank you!',
  name: 'Reader',
  log: 'logging in\nnew download: 1 A.html',
  version: '1.0.2',
  copy: 'Windows app',
  storage: 'Dropbox',
  browser: 'Chrome 140',
  turnstileToken: 'token-1',
};

/** The bot check's verify endpoint and GitHub's issues endpoint, answering as told, noting each call */
function services({ human = true, github = 201 } = {}) {
  const calls = [];
  const fetcher = async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url).includes('siteverify')) {
      return new Response(JSON.stringify({ success: human }));
    }
    if (github >= 400) return new Response('{}', { status: github });
    return new Response(JSON.stringify({ number: 12, html_url: 'https://github.com/someone/ao3downloader/issues/12' }),
      { status: 201 });
  };
  return { calls, fetcher };
}

function post(body, origin = 'https://someone.github.io', method = 'POST') {
  return new Request('https://feedback.example.workers.dev/', {
    method,
    headers: { Origin: origin, 'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.5' },
    body: method === 'POST' ? JSON.stringify(body) : undefined,
  });
}

describe('sending feedback', () => {
  it('opens a labelled issue and answers with where it is', async () => {
    const { calls, fetcher } = services();
    const response = await handle(post(FORM), ENV, fetcher);

    assert.equal(response.status, 201);
    assert.deepEqual(await response.json(),
      { ok: true, number: 12, url: 'https://github.com/someone/ao3downloader/issues/12' });
    const issue = calls.find((c) => c.url.endsWith('/repos/someone/ao3downloader/issues'));
    const sent = JSON.parse(issue.init.body);
    assert.deepEqual(sent.labels, ['feedback', 'general feedback']);
    assert.equal(sent.title, 'Feedback: The quick scan is great.');
    assert.equal(issue.init.headers.Authorization, 'Bearer a-token');
    // where the library lives - the kind, never a folder's name
    assert.match(sent.body, /- \*\*Library:\*\* Dropbox/);
  });

  it('lets the page that sent it read the answer', async () => {
    const { fetcher } = services();
    const response = await handle(post(FORM, 'http://localhost:4200'), ENV, fetcher);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:4200');
  });

  it('answers a browser asking first, for an allowed page only', async () => {
    const allowed = await handle(post(null, 'https://someone.github.io', 'OPTIONS'), ENV);
    assert.equal(allowed.status, 204);
    assert.equal(allowed.headers.get('Access-Control-Allow-Methods'), 'POST, OPTIONS');
    const other = await handle(post(null, 'https://elsewhere.example', 'OPTIONS'), ENV);
    assert.equal(other.headers.get('Access-Control-Allow-Origin'), null);
  });

  it('refuses a page it does not know, before asking anyone anything', async () => {
    const { calls, fetcher } = services();
    const response = await handle(post(FORM, 'https://elsewhere.example'), ENV, fetcher);
    assert.equal(response.status, 403);
    assert.equal(calls.length, 0);
  });

  it('opens no issue when the bot check fails, and checks it with the secret and address', async () => {
    const { calls, fetcher } = services({ human: false });
    const response = await handle(post(FORM), ENV, fetcher);

    assert.equal(response.status, 403);
    assert.equal(calls.length, 1);
    const asked = calls[0].init.body;
    assert.equal(asked.get('secret'), 'a-secret');
    assert.equal(asked.get('response'), 'token-1');
    assert.equal(asked.get('remoteip'), '203.0.113.5');
  });

  it('opens no issue without a bot check token at all', async () => {
    const { calls, fetcher } = services();
    const response = await handle(post({ ...FORM, turnstileToken: '' }), ENV, fetcher);
    assert.equal(response.status, 403);
    assert.equal(calls.length, 0);
  });

  it('says so when GitHub will not take it', async () => {
    const { fetcher } = services({ github: 403 });
    const response = await handle(post(FORM), ENV, fetcher);
    assert.equal(response.status, 502);
    assert.match((await response.json()).error, /GitHub/);
  });

  it('takes the form only by POST', async () => {
    const response = await handle(post(null, 'https://someone.github.io', 'GET'), ENV);
    assert.equal(response.status, 405);
  });
});

describe('the form', () => {
  it('needs a kind and a message, and nothing else', () => {
    assert.match(readForm({ ...FORM, kind: 'meh' }).error, /general feedback, a feature suggestion or a bug report/);
    assert.match(readForm({ ...FORM, kind: '' }).error, /bug report/);
    assert.match(readForm({ ...FORM, message: '   ' }).error, /empty/);
    const { form } = readForm({ kind: 'Bug', message: 'It crashed' });
    assert.equal(form.kind, 'bug');
    assert.deepEqual(form.ratings, {});
    assert.equal(form.name, '');
    assert.equal(form.log, '');
  });

  it('refuses a message or name over the limit, and keeps a long log to its end', () => {
    assert.match(readForm({ ...FORM, message: 'x'.repeat(LIMITS.message + 1) }).error, /longer/);
    assert.match(readForm({ ...FORM, name: 'x'.repeat(LIMITS.name + 1) }).error, /longer/);
    const log = 'start\n' + 'x'.repeat(LIMITS.log) + '\nthe end';
    const { form } = readForm({ ...FORM, log });
    assert.equal(form.log.length, LIMITS.log);
    assert.ok(form.log.endsWith('the end'));
  });

  it('takes out anything in the log that looks like a password', () => {
    assert.equal(scrubPasswords('password=hunter2 and Password: "two words"'),
      'password=[removed] and Password: [removed]');
    assert.equal(readForm({ ...FORM, log: '{"password": "x"}' }).form.log, '{"password": [removed]}');
  });
});

describe('the issue', () => {
  it('says what was sent, by whom, from which version, with the log folded away', () => {
    const issue = issueFor(readForm(FORM).form);
    assert.match(issue.body, /\*\*General feedback\*\*/);
    assert.match(issue.body, /The quick scan is great\.\nThank you!/);
    assert.match(issue.body, /\*\*From:\*\* Reader/);
    assert.match(issue.body, /\*\*Version:\*\* 1\.0\.2/);
    assert.match(issue.body, /<details><summary>Latest run log/);
    assert.match(issue.body, /new download: 1 A\.html/);
  });

  it('leaves out a run log that would make the issue longer than GitHub takes, and says so', () => {
    const form = readForm({ ...FORM, message: 'm'.repeat(LIMITS.message), log: 'l'.repeat(LIMITS.log), visit: 'v'.repeat(LIMITS.visit) }).form;
    const issue = issueFor(form);
    assert.ok(issue.body.length <= ISSUE_BODY_LIMIT);
    assert.ok(issue.body.includes(LOG_LEFT_OUT));
    assert.doesNotMatch(issue.body, /Latest run log/);
    // the message is whole, and the visit's log keeps what fits
    assert.ok(issue.body.includes('m'.repeat(LIMITS.message)));
    assert.match(issue.body, /What they did on this visit/);
  });

  it('keeps a run log that fits, however long', () => {
    const issue = issueFor(readForm({ ...FORM, log: 'l'.repeat(LIMITS.log) }).form);
    assert.ok(issue.body.includes('l'.repeat(LIMITS.log)));
    assert.ok(!issue.body.includes(LOG_LEFT_OUT));
  });

  it('says no name was given rather than leaving a blank', () => {
    const issue = issueFor(readForm({ kind: 'bug', message: 'Hm' }).form);
    assert.match(issue.body, /\(no name given\)/);
    assert.doesNotMatch(issue.body, /<details>/);
  });

  it('shortens a long first line in the title', () => {
    const issue = issueFor(readForm({ ...FORM, message: 'a'.repeat(100) }).form);
    assert.equal(issue.title, `Feedback: ${'a'.repeat(57)}...`);
  });

  it('names each kind in the title, the first line and its label', () => {
    for (const [kind, title, first, label] of [
      ['general', 'Feedback', 'General feedback', 'general feedback'],
      ['feature', 'Feature suggestion', 'Feature suggestion', 'feature suggestion'],
      ['bug', 'Bug report', 'Bug report', 'bug'],
    ]) {
      const issue = issueFor(readForm({ kind, message: 'Hello' }).form);
      assert.equal(issue.title, `${title}: Hello`);
      assert.match(issue.body, new RegExp(`^\\*\\*${first}\\*\\*`));
      assert.deepEqual(issue.labels, ['feedback', label]);
    }
  });

  it('takes a page from before the kinds, which sent positive or negative, as general feedback', () => {
    for (const sentiment of ['positive', 'Negative']) {
      const { form } = readForm({ sentiment, message: 'Hi' });
      assert.equal(form.kind, 'general');
    }
  });

  it('lists only the quick questions answered, each by the word chosen, and passes over anything else', () => {
    const { form } = readForm({
      ...FORM,
      ratings: { easy: 4, complete: 2, useful: 9, confusing: 2.5, made_up: 3 },
    });
    assert.deepEqual(form.ratings, { easy: 4, complete: 2 });
    const issue = issueFor(form);
    assert.match(issue.body, /\*\*Quick questions\*\*\n/);
    assert.match(issue.body, /How easy is FicFairy to use\? \*\*Easy\*\*/);
    assert.match(issue.body, /Does it do everything you want\? \*\*Missing some\*\*/);
    assert.doesNotMatch(issue.body, /\(1 = /);
    assert.doesNotMatch(issue.body, /useful|confusing/);
  });

  it('says nothing about quick questions when none were answered', () => {
    assert.doesNotMatch(issueFor(readForm(FORM).form).body, /Quick questions/);
  });

  it('folds what they did on this visit away on its own, kept to its end and without passwords', () => {
    const visit = 'x'.repeat(LIMITS.visit) + '\n[2026-11-06 04:00:00 UTC] Tab opened: history password=hunter2';
    const form = readForm({ ...FORM, visit }).form;
    // kept to its end: the start goes, the newest line stays (and is then scrubbed)
    assert.ok(form.visit.length < visit.length);
    assert.ok(form.visit.endsWith('password=[removed]'));
    const issue = issueFor(form);
    assert.match(issue.body, /<details><summary>What they did on this visit/);
    assert.match(issue.body, /Tab opened: history password=\[removed\]/);
    assert.doesNotMatch(issue.body, /hunter2/);
  });

  it('leaves the visit section out when nothing was attached', () => {
    assert.doesNotMatch(issueFor(readForm(FORM).form).body, /this visit/);
  });

  it('fences the log so backticks in it cannot break out of the block', () => {
    const issue = issueFor(readForm({ ...FORM, log: 'a ``` b ````' }).form);
    assert.match(issue.body, /\n`````\na ``` b ````\n`````\n/);
  });
});
