'use strict';

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const viewEl = $('#view');
  const esc = (v) =>
    String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
  const fmt = (n, d = 2) => (n === null || n === undefined ? '–' : Number(n).toFixed(d));

  const DISMISSALS = [
    ['bowled', 'Bowled'],
    ['caught', 'Caught'],
    ['run_out', 'Run out'],
    ['stumped', 'Stumped'],
    ['hit_wicket', 'Hit wicket'],
    ['other', 'Other'],
  ];
  const STRIKER_ONLY = ['bowled', 'caught', 'stumped', 'hit_wicket'];
  const EXTRAS = [
    ['wide', 'Wide'],
    ['no_ball', 'No ball'],
  ];
  const EXTRA_ABBR = { wide: 'Wd', no_ball: 'Nb', bye: 'B', leg_bye: 'Lb' };
  const MAX_RUNS = 50;

  // ---------------------------------------------------------------- chrome --

  const THEMES = ['dark', 'light', 'contrast'];
  const THEME_NAMES = { dark: 'Dark', light: 'Light', contrast: 'High contrast' };
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    localStorage.setItem('theme', t);
  }
  applyTheme(localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'));
  $('#theme-btn').addEventListener('click', () => {
    const next = THEMES[(THEMES.indexOf(document.documentElement.dataset.theme) + 1) % THEMES.length];
    applyTheme(next);
    toast(`Theme: ${THEME_NAMES[next]}`);
  });

  let toastTimer;
  function toast(msg, ms = 2500) {
    const t = $('#toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), ms);
  }

  function setTitle(text, back) {
    $('#title').textContent = text;
    $('#brand').classList.toggle('brand-home', !back && text === 'Indoor Cricket Scoring App');
    $('#nav-back').hidden = !back;
  }

  async function hasScorerAccess() {
    try {
      const session = await Api.scorerSession();
      if (!session.authenticated) {
        sessionStorage.removeItem('scorer_unlocked');
        return !navigator.onLine && sessionStorage.getItem('scorer_unlocked') === 'true';
      }
      sessionStorage.setItem('scorer_unlocked', 'true');
      return true;
    } catch (err) {
      if (err.status === 401) sessionStorage.removeItem('scorer_unlocked');
      return !navigator.onLine && sessionStorage.getItem('scorer_unlocked') === 'true';
    }
  }

  async function requireScorer(returnTo) {
    if (await hasScorerAccess()) return true;
    setTitle('Scorer access', true);
    viewEl.innerHTML = `<form id="scorer-login" class="stack form">
      <label>Scorer password<input name="password" type="password" autocomplete="current-password" required></label>
      <button class="btn btn-primary" type="submit">Unlock scorer</button>
    </form>`;
    $('#scorer-login').addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = e.currentTarget.elements.password;
      const submit = e.currentTarget.querySelector('button[type="submit"]');
      submit.disabled = true;
      try {
        await Api.loginScorer(input.value);
        sessionStorage.setItem('scorer_unlocked', 'true');
        if (pendingImportFile) {
          const file = pendingImportFile;
          pendingImportFile = null;
          if (location.hash === returnTo) await route();
          else location.hash = returnTo;
          return importMatchFile(file);
        }
        if (location.hash === returnTo) route();
        else location.hash = returnTo;
      } catch (err) {
        toast(err.message || 'Scorer login failed', 4000);
        input.select();
      } finally {
        submit.disabled = false;
      }
    });
    return false;
  }

  async function lockScorer() {
    try {
      await Api.logoutScorer();
      sessionStorage.removeItem('scorer_unlocked');
      location.hash = '#/';
    } catch (err) {
      toast(err.message || 'Could not lock scorer', 4000);
    }
  }

  function updateNet() {
    $('#net').hidden = navigator.onLine;
  }
  addEventListener('online', () => {
    updateNet();
    syncOutbox();
  });
  addEventListener('offline', updateNet);
  updateNet();

  let sheetHandler = null;
  function openSheet(html, handler) {
    $('#sheet-body').innerHTML = html;
    $('#sheet').hidden = false;
    sheetHandler = handler;
  }
  function closeSheet() {
    $('#sheet').hidden = true;
    sheetHandler = null;
  }
  $('#sheet').addEventListener('click', (e) => {
    if (e.target.id === 'sheet') return closeSheet();
    const btn = e.target.closest('[data-act]');
    if (!btn || btn.disabled) return;
    if (btn.dataset.act === 'close') return closeSheet();
    if (sheetHandler) sheetHandler(btn.dataset.act, btn.dataset);
  });

  function showError(err) {
    viewEl.innerHTML = `<div class="stack"><div class="card error">${esc(err.message || err)}</div>
      <a class="btn" href="#/">Home</a></div>`;
  }

  // ---------------------------------------------------------------- router --

  const ctx = { matchId: null, view: null, draft: null, picks: null, syncError: null, chain: Promise.resolve() };

  const routes = [
    [/^#?\/?$/, renderHome],
    [/^#\/new$/, renderNew],
    [/^#\/match\/([\w-]+)$/, renderMatch],
    [/^#\/match\/([\w-]+)\/scorecard$/, renderScorecard],
    [/^#\/match\/([\w-]+)\/details$/, renderDetails],
  ];

  function route() {
    closeSheet();
    ctx.matchId = null;
    ctx.picks = null;
    const hash = location.hash || '#/';
    for (const [re, fn] of routes) {
      const m = hash.match(re);
      if (m) return Promise.resolve(fn(...m.slice(1))).catch(showError);
    }
    return renderHome().catch(showError);
  }
  addEventListener('hashchange', route);
  $('#nav-back').addEventListener('click', () => {
    const h = location.hash;
    if (h.endsWith('/details')) location.hash = h.replace(/\/details$/, '');
    else location.hash = '#/';
  });

  // ------------------------------------------------------------------ home --

  async function renderHome() {
    setTitle('Indoor Cricket Scoring App', false);
    viewEl.innerHTML = `<div class="stack">
      <a class="btn btn-primary btn-xl" href="#/new">+ New Match</a>
      <h2>Resume Match</h2><div id="list-progress" class="list"><div class="muted">Loading…</div></div>
      <h2>Completed Matches</h2><div id="list-done" class="list"></div>
      <label class="import-link">Import match JSON<input type="file" id="import-file" accept="application/json,.json" hidden></label>
    </div>`;
    $('#import-file').addEventListener('change', onImport);

    let matches;
    try {
      matches = await Api.listMatches();
    } catch (e) {
      $('#list-progress').innerHTML = `<div class="muted">${esc(e.offline ? 'Offline – match list unavailable.' : e.message)}</div>`;
      return;
    }
    const card = (m) => {
      const pending = Store.outbox(m.id).length;
      const href = `#/match/${esc(m.id)}/scorecard`;
      return `<div class="card match-card">
        <a class="card-main" href="${href}">
          <strong>${esc(m.name)}</strong>
          <span class="muted">${esc(m.teams.join(' v '))} · ${esc(m.date)}${m.venue ? ' · ' + esc(m.venue) : ''}</span>
          <span>${esc(m.headline)}${pending ? ` <span class="badge">${pending} unsynced</span>` : ''}</span>
        </a>
        <div class="card-actions">
          <a class="btn btn-small" href="#/match/${esc(m.id)}">Scorer</a>
          <a class="btn btn-small" href="#/match/${esc(m.id)}/details">Setup</a>
          <a class="btn btn-small" href="${Api.pdfUrl(m.id)}" download>PDF</a>
        </div></div>`;
    };
    const progress = matches.filter((m) => m.status !== 'completed');
    const done = matches.filter((m) => m.status === 'completed');
    $('#list-progress').innerHTML = progress.map(card).join('') || '<div class="muted">No matches in progress.</div>';
    $('#list-done').innerHTML = done.map(card).join('') || '<div class="muted">No completed matches.</div>';
  }

  let pendingImportFile = null;

  async function onImport(e) {
    const file = e.target.files[0];
    e.target.value = '';
    await importMatchFile(file);
  }

  async function importMatchFile(file) {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) return toast('File is too large');
    try {
      const v = await Api.importMatch(await file.text());
      Store.saveView(v.match.id, v);
      toast('Match imported');
      location.hash = `#/match/${v.match.id}${v.match.status === 'completed' ? '/scorecard' : ''}`;
    } catch (err) {
      if (err.status === 401) {
        pendingImportFile = file;
        await requireScorer(location.hash || '#/');
        return;
      }
      toast(err.message, 5000);
    }
  }

  async function deleteMatch(id, name) {
    if (!(await requireScorer(location.hash || '#/'))) return;
    openSheet(
      `<h2>Delete match</h2>
      <div>Delete <b>${esc(name)}</b>? This cannot be undone.</div>
      <form id="delete-form" class="form stack">
        <label>Delete password<input id="delete-password" type="password" autocomplete="off" required></label>
        <button class="btn btn-danger btn-xl" type="submit">Delete Match</button>
      </form>
      <button class="btn" data-act="close">Cancel</button>`,
      () => {}
    );
    const input = $('#delete-password');
    input.focus();
    $('#delete-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!input.value) return toast('Enter the delete password');
      try {
        await Api.deleteMatch(id, input.value);
        closeSheet();
        Store.forget(id);
        toast('Match deleted');
        if (location.hash === '#/' || location.hash === '') renderHome();
        else location.hash = '#/';
      } catch (err) {
        toast(err.message, 4000);
        input.select();
      }
    });
  }

  // ------------------------------------------------------------- new match --

  function parsePlayers(text) {
    return text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .map((name) => ({ name }));
  }

  async function renderNew() {
    if (!(await requireScorer('#/new'))) return;
    setTitle('New Match', true);
    const now = new Date();
    const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    const num = (name, label, value, min, max) =>
      `<label>${label}<input type="number" name="${name}" value="${value}" min="${min}" max="${max}" inputmode="numeric" required></label>`;
    const team = (i) => `<fieldset><legend>Team ${i + 1}</legend>
        <label>Team name<input name="team${i}" required maxlength="40" value="${i ? 'Team B' : 'Team A'}"></label>
        <label>Players <span class="muted">one per line</span>
          <textarea name="players${i}" rows="8" required placeholder="Alex&#10;Sam&#10;Jordan"></textarea></label>
      </fieldset>`;
    viewEl.innerHTML = `<form id="new-form" class="stack form" novalidate>
      <fieldset><legend>Match details</legend>
        <label>Match name<input name="name" required maxlength="80" value="Match ${today}"></label>
        <div class="row2"><label>Date<input type="date" name="date" required value="${today}"></label>
        <label>Venue<input name="venue" maxlength="80"></label></div>
      </fieldset>
      <fieldset><legend>Innings settings</legend>
        <div class="row3">${num('overs', 'Overs', 16, 1, 50)}${num('balls_per_over', 'Balls/over', 6, 1, 12)}
          <label>Innings<select name="innings"><option value="1">1</option><option value="2" selected>2</option><option value="4">4</option></select></label></div>
        <div class="row3">${num('wide_runs', 'Wide runs', 2, 0, 10)}${num('no_ball_runs', 'No-ball runs', 2, 0, 10)}${num('last_over_extra_runs', 'Last over Wd/Nb', 1, 0, 10)}</div>
        <div class="muted">Wides and no balls count as a ball, except in the last over where they are re-bowled.</div>
        ${num('pairing_overs', 'Pairing overs (0 = off)', 0, 0, 50)}
        <div class="muted">During the first pairing overs of each innings, a dismissed batsman stays in; the wicket still counts.</div>
      </fieldset>
      ${team(0)}${team(1)}
      <button class="btn btn-primary btn-xl" type="submit">Create Match</button>
    </form>`;
    $('#new-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const body = {
        name: f.get('name'),
        date: f.get('date'),
        venue: f.get('venue'),
        settings: {
          overs: Number(f.get('overs')),
          balls_per_over: Number(f.get('balls_per_over')),
          innings: Number(f.get('innings')),
          wide_runs: Number(f.get('wide_runs')),
          no_ball_runs: Number(f.get('no_ball_runs')),
          last_over_extra_runs: Number(f.get('last_over_extra_runs')),
          pairing_overs: Number(f.get('pairing_overs')),
        },
        teams: [0, 1].map((i) => ({ name: f.get(`team${i}`), players: parsePlayers(f.get(`players${i}`)) })),
      };
      if (body.teams.some((t) => t.players.length < 2)) return toast('Each team needs at least 2 players');
      try {
        const v = await Api.createMatch(body);
        Store.saveView(v.match.id, v);
        location.hash = `#/match/${v.match.id}`;
      } catch (err) {
        toast(err.offline ? 'Creating a match needs a connection' : err.message, 5000);
      }
    });
  }

  // ----------------------------------------------------------------- match --

  function resetDraft() {
    ctx.draft = { striker: null, custom: '', extra: null };
  }

  function playerName(id) {
    for (const t of ctx.view?.match.teams || []) for (const p of t.players) if (p.id === id) return p.name;
    return id;
  }

  async function renderMatch(id) {
    if (!(await requireScorer(`#/match/${id}`))) return;
    ctx.matchId = id;
    ctx.syncError = null;
    resetDraft();
    setTitle('Scoring', true);
    const cached = Store.lastView(id);
    if (cached) {
      ctx.view = cached;
      drawMatch();
    } else {
      viewEl.innerHTML = '<div class="muted pad-top">Loading…</div>';
    }
    try {
      const v = await Api.getMatch(id);
      if (ctx.matchId !== id) return;
      setView(v);
    } catch (e) {
      if (!(e.offline && cached)) throw e;
    }
    syncOutbox();
  }

  function setView(v) {
    ctx.view = v;
    ctx.lastStatus = v.match.status;
    Store.saveView(v.match.id, v);
    resetDraft();
    drawMatch();
  }

  function drawMatch() {
    if (!ctx.view || ctx.matchId !== ctx.view.match.id) return;
    const { match, state } = ctx.view;
    setTitle(match.name, true);
    const pending = Store.outbox(match.id);
    let body;
    if (pending.length) body = scoringHtml(pending);
    else if (state.next_action === 'match_complete') body = completeHtml();
    else if (state.next_action === 'start_innings') body = startInningsHtml();
    else if (state.next_action === 'select_batsman')
      body =
        scoreboardHtml() +
        pickerHtml(
          'Select incoming batsman',
          state.available_batsmen.map((b) => ({ id: b.id, name: b.name, sub: b.retired ? 'Retired – returning' : '' })),
          'pick-batsman'
        ) +
        (state.can_cancel_retire
          ? '<div class="util"><button class="btn btn-small" data-act="cancel-retire">Do Not Retire</button></div>'
          : '') +
        utilHtml() +
        undoHtml();
    else if (state.next_action === 'select_bowler')
      body = scoreboardHtml() + pickerHtml(`Select bowler for over ${overNumber()}`, bowlerItems(), 'pick-bowler') + utilHtml() + undoHtml();
    else body = scoringHtml([]);
    viewEl.innerHTML = syncBannerHtml(pending) + body;
  }

  function overNumber() {
    const c = ctx.view.state.current;
    return c ? Math.floor(c.legal_balls / ctx.view.match.settings.balls_per_over) + 1 : 1;
  }

  function bowlerItems() {
    return ctx.view.state.bowlers.map((b) => ({
      id: b.id,
      name: b.name,
      sub: `${b.overs}-${b.runs}-${b.wickets}${b.bowled_last_over ? ' · bowled last over' : ''}`,
    }));
  }

  function syncBannerHtml(pending) {
    if (ctx.syncError) {
      return `<div class="banner banner-error">Sync failed: ${esc(ctx.syncError)}
        <div class="banner-actions"><button class="btn btn-small" data-act="retry-sync">Retry</button>
        <button class="btn btn-small btn-danger" data-act="discard-outbox">Discard ${pending.length} unsynced</button></div></div>`;
    }
    if (pending.length) {
      return `<div class="banner">Offline: ${pending.length} action${pending.length > 1 ? 's' : ''} saved on this device – will sync automatically. Stats below are from the last sync.</div>`;
    }
    return '';
  }

  function scoreboardHtml() {
    const { match, state } = ctx.view;
    const c = state.current;
    if (!c) return '<div class="scoreboard"><div class="muted">Innings not started</div></div>';
    const ch = c.chase;
    const chase = ch
      ? `<div class="chase">Need <b>${ch.runs_required}</b> off <b>${ch.balls_remaining}</b> · Target ${ch.target} · RRR ${fmt(ch.required_run_rate)}</div>`
      : '';
    return `<div class="scoreboard">
      <div class="sb-team">${esc(c.batting_team_name)} <span class="muted">· Innings ${c.innings_number}</span>${
        c.in_pairing ? ` <span class="badge">Pairs · ${state.pairing_overs} ov</span>` : ''
      }</div>
      <div class="sb-main">
        <span class="sb-score">${c.runs}/${c.wickets}</span>
        <span class="sb-overs">${c.overs}<small> / ${state.overs ?? match.settings.overs} ov</small></span>
        <span class="sb-rr">RR ${fmt(c.run_rate)}</span>
      </div>${chase}</div>`;
  }

  function battersHtml() {
    const c = ctx.view.state.current;
    if (!c) return '';
    const chosen = ctx.draft.striker;
    const card = (b) =>
      b
        ? `<button class="batter ${b.id === chosen ? 'on-strike' : ''} ${chosen ? '' : 'prompt'}" data-act="striker" data-id="${esc(b.id)}">
            <span class="b-name">${esc(b.name)}</span>
            <span class="b-stats"><b>${b.runs}</b> (${b.balls}) · SR ${fmt(b.strike_rate, 1)}${
              b.pair_dismissals?.length ? ` · <span class="outs">out ${b.pair_dismissals.length}×</span>` : ''
            }</span><span class="b-stats">Wides faced: ${b.wides_faced ?? 0}</span></button>`
        : '<div class="batter vacant">Awaiting batsman</div>';
    const title = chosen ? '' : '<div class="facing-prompt">Who is facing this ball?</div>';
    return `${title}<div class="batters">${card(c.striker)}${card(c.non_striker)}</div>`;
  }

  function bowlerLineHtml() {
    const c = ctx.view.state.current;
    if (!c) return '';
    const b = c.bowler;
    const bowl = b
      ? `<span><b>${esc(b.name)}</b> ${b.overs}-${b.runs}-${b.wickets} · Econ ${fmt(b.economy)}</span>`
      : '<span class="muted">No bowler</span>';
    return `<div class="infoline">${bowl}<span>P'ship <b>${c.partnership.runs}</b> (${c.partnership.balls})</span></div>`;
  }

  function overHtml(pending) {
    const c = ctx.view.state.current;
    const chips = (c?.this_over || []).map((l) => `<span class="chip ${chipClass(l)}">${esc(l)}</span>`);
    const pend = pending.map((p) => `<span class="chip chip-pending">${esc(pendingLabel(p))}</span>`);
    return `<div class="over"><span class="muted">This over</span>${chips.join('')}${pend.join('')}</div>`;
  }

  function chipClass(label) {
    if (label.includes('W')) return 'chip-w';
    if (/^(4|6)/.test(label)) return 'chip-boundary';
    if (/^(Wd|Nb|B|Lb)/.test(label)) return 'chip-extra';
    return '';
  }

  function pendingLabel(item) {
    if (item.kind === 'undo') return 'Undo';
    if (item.kind === 'cancel_retire') return 'Unretire';
    const e = item.event;
    if (e.type !== 'ball') {
      return { bowler: 'Bowler', new_batsman: 'In', retire: 'Retire', end_innings: 'End', innings_start: 'Start', set_overs: 'Overs', set_pairing_overs: 'Pairs' }[e.type] || e.type;
    }
    let s = String(e.runs) + (e.additional || []).map((a) => `+${a}`).join('');
    if (e.extra) s = EXTRA_ABBR[e.extra] + s;
    if (e.dismissal) s += e.dismissal.type === 'retired' ? ' R' : ' W';
    return s;
  }

  function draftHtml() {
    if (!ctx.draft.striker && ctx.view.state.current) {
      return '<div class="draft muted">Select the striker, then tap runs</div>';
    }
    if (ctx.draft.extra === 'no_ball') {
      return '<div class="draft armed">No ball selected</div>';
    }
    return '<div class="draft muted">Tap runs, Wide or No ball to record the ball</div>';
  }

  function utilHtml(offline = false) {
    const id = esc(ctx.matchId);
    return `<div class="util">
      <button class="btn btn-small" data-act="change-bowler">Bowler</button>
      ${!offline && ctx.view.state.current?.recent_balls?.length ? '<button class="btn btn-small" data-act="edit-ball-list">Edit Ball</button>' : ''}
      ${offline ? '<button class="btn btn-small" data-act="new-batsman">Batsman in</button>' : ''}
      <a class="btn btn-small" href="#/match/${id}/scorecard">Scorecard</a>
      <a class="btn btn-small" href="#/match/${id}/details">Setup</a>
      <button class="btn btn-small" data-act="end-innings">End innings</button>
      <button class="btn btn-small" data-act="lock-scorer">Lock scorer</button>
    </div>`;
  }

  function undoHtml() {
    const can = ctx.view.state.can_undo || Store.outbox(ctx.matchId).length;
    return `<button class="btn-undo" data-act="undo" ${can ? '' : 'disabled'}>UNDO LAST BALL</button>`;
  }

  function scoringHtml(pending) {
    const offline = pending.length > 0;
    const d = ctx.draft;
    // Striker must be chosen for every ball; without a current innings (queued offline) the server decides.
    const lock = !d.striker && ctx.view.state.current ? 'disabled' : '';
    const extraRuns = ctx.view.state.current?.extra_runs || { wide: 2, no_ball: 2 };
    return `<div class="scoring-screen">${scoreboardHtml()}${battersHtml()}${bowlerLineHtml()}${overHtml(pending)}${draftHtml()}
      <div class="pad pad-runs">
        ${range(0, 6).map((n) => `<button class="btn-run" data-act="runs" data-n="${n}" ${lock}>${n}</button>`).join('')}
        <button class="btn-run btn-out" data-act="wicket" ${lock}>OUT</button>
      </div>
      <div class="custom-runs">
        <input id="custom-runs" type="number" inputmode="numeric" min="0" max="${MAX_RUNS}" step="1"
          placeholder="Custom runs" aria-label="Custom runs" value="${esc(d.custom)}">
        <button class="btn" data-act="custom-runs" ${lock}>Record</button>
      </div>
      <div class="pad pad-extras">
        ${EXTRAS.map(([k, l]) => `<button class="btn-extra ${d.extra === k ? 'active' : ''}" data-act="extra" data-x="${k}" ${k === 'no_ball' ? `aria-pressed="${d.extra === k}"` : ''} ${lock}>${l} +${extraRuns[k]}</button>`).join('')}
      </div>
      <div class="pad pad-retire">
        <button class="btn-retire" data-act="retire-one">Retire Batsman</button>
        <button class="btn-retire" data-act="retire-both">Retire Both</button>
      </div>
      ${utilHtml(offline)}${undoHtml()}</div>`;
  }

  function pickerHtml(title, items, act) {
    return `<h2 class="picker-title">${esc(title)}</h2><div class="grid2">${items
      .map(
        (i) => `<button class="choice" data-act="${act}" data-id="${esc(i.id)}"><span>${esc(i.name)}</span>${
          i.sub ? `<small>${esc(i.sub)}</small>` : ''
        }</button>`
      )
      .join('')}</div>`;
  }

  function startInningsHtml() {
    const { match, state } = ctx.view;
    const fixed = state.next_batting_team !== null && state.next_batting_team !== undefined;
    const p = (ctx.picks ||= { team: fixed ? state.next_batting_team : 0, openers: [], bowler: null });
    const bat = match.teams[p.team];
    const bowl = match.teams[1 - p.team];
    const n = (state.current?.innings_number || 0) + 1;
    const prev = state.current
      ? `<div class="card">Previous: ${esc(state.current.batting_team_name)} ${state.current.runs}/${state.current.wickets} (${state.current.overs} ov)</div>`
      : '';
    const teamPick = fixed
      ? `<div class="card"><b>${esc(bat.name)}</b> to bat</div>`
      : `<div class="grid2">${match.teams
          .map((t, i) => `<button class="choice ${p.team === i ? 'sel' : ''}" data-act="bat-team" data-team="${i}">${esc(t.name)} bat</button>`)
          .join('')}</div>`;
    const openers = bat.players
      .map((pl) => {
        const idx = p.openers.indexOf(pl.id);
        const tag = idx === 0 ? '<small>Striker</small>' : idx === 1 ? '<small>Non-striker</small>' : '';
        return `<button class="choice ${idx >= 0 ? 'sel' : ''}" data-act="opener" data-id="${esc(pl.id)}"><span>${esc(pl.name)}</span>${tag}</button>`;
      })
      .join('');
    const bowlers = bowl.players
      .map((pl) => `<button class="choice ${p.bowler === pl.id ? 'sel' : ''}" data-act="open-bowler" data-id="${esc(pl.id)}">${esc(pl.name)}</button>`)
      .join('');
    const ready = p.openers.length === 2 && p.bowler;
    return `<div class="stack">${prev}<h2>Innings ${n}</h2>${teamPick}
      <h3>Opening batsmen <span class="muted">(first tap = striker)</span></h3><div class="grid2">${openers}</div>
      <h3>Opening bowler</h3><div class="grid2">${bowlers}</div>
      <button class="btn btn-primary btn-xl" data-act="start-innings" ${ready ? '' : 'disabled'}>Start Innings</button>
      ${ctx.view.state.can_undo ? undoHtml() : ''}</div>`;
  }

  function completeHtml() {
    const { state } = ctx.view;
    return `${scoreboardHtml()}<div class="card result-card"><div class="result">${esc(state.result?.text || 'Match complete')}</div></div>
      <a class="btn btn-primary btn-xl" href="#/match/${esc(ctx.matchId)}/scorecard">View Scorecard &amp; Summary</a>
      ${undoHtml()}`;
  }

  // ------------------------------------------------------------ submitting --

  function submit(kind, event) {
    const id = ctx.matchId;
    const item = { kind, event, op_id: newOpId() };
    resetDraft();
    ctx.chain = ctx.chain.then(() => send(id, item));
    return ctx.chain;
  }

  function callApi(id, item) {
    if (item.kind === 'undo') return Api.undo(id, item.op_id);
    if (item.kind === 'cancel_retire') return Api.cancelRetire(id, item.op_id);
    return Api.addEvent(id, item.event, item.op_id);
  }

  async function send(id, item) {
    if (Store.outbox(id).length) {
      Store.pushOutbox(id, item);
      drawMatch();
      return syncOutbox();
    }
    try {
      const v = await callApi(id, item);
      if (ctx.matchId === id) setView(v);
      else Store.saveView(id, v);
    } catch (e) {
      if (e.offline) {
        Store.pushOutbox(id, item);
        toast('Offline – saved on this device');
      } else {
        toast(e.message, 4000);
      }
      drawMatch();
    }
  }

  let syncing = false;
  async function syncOutbox() {
    const id = ctx.matchId;
    if (!id || syncing) return;
    let items = Store.outbox(id);
    if (!items.length) return;
    syncing = true;
    ctx.syncError = null;
    let synced = false;
    try {
      while (items.length) {
        const it = items[0];
        const v = await callApi(id, it);
        items = Store.outbox(id).slice(1);
        Store.setOutbox(id, items);
        Store.saveView(id, v);
        if (ctx.matchId === id) ctx.view = v;
        synced = true;
      }
      toast('All scoring synced');
    } catch (e) {
      if (!e.offline) ctx.syncError = e.message;
    } finally {
      syncing = false;
      if (synced || ctx.syncError) drawMatch();
    }
  }
  setInterval(() => navigator.onLine && syncOutbox(), 15000);

  function submitBall(runs, dismissal, extra = ctx.draft.extra) {
    const d = ctx.draft;
    const ev = { type: 'ball', runs, extra };
    if (d.striker) ev.striker = d.striker;
    if (dismissal) ev.dismissal = dismissal;
    if (navigator.vibrate) navigator.vibrate(15);
    return submit('event', ev);
  }

  function battingTeamGuess() {
    const { state } = ctx.view;
    for (const it of Store.outbox(ctx.matchId).slice().reverse()) {
      if (it.event?.type === 'innings_start') return it.event.batting_team ?? state.next_batting_team ?? 0;
    }
    return state.current?.batting_team ?? 0;
  }

  function openBowlerSheet() {
    let items = bowlerItems();
    if (!items.length) {
      items = ctx.view.match.teams[1 - battingTeamGuess()].players.map((p) => ({ id: p.id, name: p.name }));
    }
    openSheet(`${pickerHtml('Change bowler', items, 'pick')}<button class="btn" data-act="close">Cancel</button>`, (act, ds) => {
      closeSheet();
      submit('event', { type: 'bowler', bowler: ds.id });
    });
  }

  function openBatsmanSheet() {
    const st = ctx.view.state;
    let items = st.available_batsmen.map((b) => ({ id: b.id, name: b.name, sub: b.retired ? 'Retired' : '' }));
    if (!items.length) items = ctx.view.match.teams[battingTeamGuess()].players.map((p) => ({ id: p.id, name: p.name }));
    openSheet(`${pickerHtml('Incoming batsman', items, 'pick')}<button class="btn" data-act="close">Cancel</button>`, (act, ds) => {
      closeSheet();
      submit('event', { type: 'new_batsman', batsman: ds.id });
    });
  }

  function crease() {
    const c = ctx.view.state.current;
    const strikerId = ctx.draft.striker;
    if (!strikerId) return [];
    const other = c?.striker?.id === strikerId ? c?.non_striker : c?.striker;
    return [strikerId, other?.id].filter(Boolean);
  }

  function openRetireSheet() {
    const c = ctx.view.state.current;
    const items = [c?.striker, c?.non_striker].filter(Boolean).map((b) => ({ id: b.id, name: b.name }));
    openSheet(`${pickerHtml('Retire which batsman? (not out)', items, 'pick')}<button class="btn" data-act="close">Cancel</button>`, (act, ds) => {
      closeSheet();
      submit('event', { type: 'retire', batsman: ds.id });
    });
  }

  function retireBoth() {
    const c = ctx.view.state.current;
    const ids = [c?.striker?.id, c?.non_striker?.id].filter(Boolean);
    if (ids.length < 2) return toast('Both batsmen must be at the crease');
    ids.forEach((id) => submit('event', { type: 'retire', batsman: id }));
  }

  const MAX_FIELDERS = { caught: 1, run_out: 2, stumped: 1 };

  function openWicketSheet() {
    const [strikerId, nonId] = crease();
    if (!strikerId) return toast('Select the striker first');
    const c = ctx.view.state.current;
    const fieldingSide = ctx.view.match.teams[c?.bowling_team ?? 1 - battingTeamGuess()].players;
    const w = { type: null, batsman: strikerId, fielders: [] };
    const fieldersHtml = () => {
      const max = MAX_FIELDERS[w.type];
      if (!max) return '';
      const title =
        w.type === 'caught' ? 'Caught by' : w.type === 'stumped' ? 'Stumped by' : 'Run out by <span class="muted">(1 for a direct hit, or 2)</span>';
      return `<h3>${title}</h3><div class="grid3">${fieldingSide
        .map((p) => {
          const idx = w.fielders.indexOf(p.id);
          const tag = p.id === c?.bowler?.id ? '<small>Bowler</small>' : '';
          return `<button class="choice ${idx >= 0 ? 'sel' : ''}" data-act="dfielder" data-id="${esc(p.id)}"><span>${esc(p.name)}</span>${tag}</button>`;
        })
        .join('')}</div>`;
    };
    const ready = () => Boolean(w.type) && (!MAX_FIELDERS[w.type] || w.fielders.length > 0);
    const draw = () =>
      openSheet(
        `<div class="dismissal-screen"><h2>Dismissal</h2>
        ${ctx.draft.extra === 'no_ball' ? '<div class="muted">No ball</div>' : ''}
        <div class="grid3">${DISMISSALS.map(
          ([t, l]) => `<button class="choice ${w.type === t ? 'sel' : ''}" data-act="dtype" data-t="${t}" ${ctx.draft.extra === 'no_ball' && STRIKER_ONLY.includes(t) ? 'disabled' : ''}>${l}</button>`
        ).join('')}</div>
        <h3>Batsman</h3><div class="grid2">${[strikerId, nonId]
          .filter(Boolean)
          .map(
            (pid) => `<button class="choice ${w.batsman === pid ? 'sel' : ''}" data-act="dbat" data-id="${esc(pid)}"
              ${STRIKER_ONLY.includes(w.type) && pid !== strikerId ? 'disabled' : ''}>
              <span>${esc(playerName(pid))}</span><small>${pid === strikerId ? 'Striker' : 'Non-striker'}</small></button>`
          )
          .join('')}</div>
        ${fieldersHtml()}
        <h3>Runs on this ball <span class="muted">${!w.type ? '(select dismissal first)' : ready() ? '(tap to record)' : '(select fielder first)'}</span></h3>
        <div class="grid4">${range(0, 6)
          .map((n) => `<button class="btn-run" data-act="druns" data-n="${n}" ${ready() ? '' : 'disabled'}>${n}</button>`)
          .join('')}</div>
        <div class="grid3">${[-1, -2, -3]
          .map((n) => `<button class="btn-minus" data-act="druns" data-n="${n}" ${ready() ? '' : 'disabled'}>${n}</button>`)
          .join('')}</div>
        <button class="btn" data-act="close">Cancel</button></div>`,
        (act, ds) => {
          if (act === 'dtype') {
            w.type = ds.t;
            w.fielders = [];
            if (STRIKER_ONLY.includes(w.type)) w.batsman = strikerId;
            draw();
          } else if (act === 'dbat') {
            w.batsman = ds.id;
            draw();
          } else if (act === 'dfielder') {
            const max = MAX_FIELDERS[w.type];
            const i = w.fielders.indexOf(ds.id);
            if (i >= 0) w.fielders.splice(i, 1);
            else if (max === 1) w.fielders = [ds.id];
            else if (w.fielders.length < max) w.fielders.push(ds.id);
            draw();
          } else if (act === 'druns') {
            closeSheet();
            const dismissal = { type: w.type, batsman: w.batsman };
            if (w.fielders.length) dismissal.fielders = w.fielders.slice();
            submitBall(Number(ds.n), dismissal);
          }
        }
      );
    draw();
  }

  function openEditList() {
    const balls = ctx.view.state.current?.recent_balls || [];
    if (!balls.length) return toast('No balls to edit in this innings');
    openSheet(
      `<h2>Edit a ball</h2><div class="muted">Most recent first</div>
      <div class="stack">${balls
        .map(
          (b, i) => `<button class="choice edit-row" data-act="pick-edit" data-i="${i}">
            <span><b>${esc(b.label)}</b> · over ${b.over}</span><small>${esc(b.striker_name)} facing</small></button>`
        )
        .join('')}</div>
      <button class="btn" data-act="close">Cancel</button>`,
      (act, ds) => {
        if (act === 'pick-edit') openEditBall(balls[Number(ds.i)], ctx.matchId, (v) => setView(v));
      }
    );
  }

  function openEditBall(rb, matchId, onSaved) {
    const names = { [rb.striker]: rb.striker_name, [rb.non_striker]: rb.non_striker_name };
    const ev = rb.event || {};
    const e = {
      striker: ev.striker || rb.striker,
      runs: (ev.runs ?? 0) + (ev.additional || []).reduce((a, b) => a + b, 0),
      extra: ev.extra || null,
    };
    const dismissalNote = ev.dismissal
      ? `<div class="muted">Dismissal (${esc(ev.dismissal.type.replace('_', ' '))}) is kept. To change it, undo back to this ball.</div>`
      : '';
    const draw = () =>
      openSheet(
        `<h2>Edit ball · over ${rb.over}</h2>
        <h3>Facing</h3><div class="grid2">${[rb.striker, rb.non_striker]
          .filter(Boolean)
          .map((pid) => `<button class="choice ${e.striker === pid ? 'sel' : ''}" data-act="e-striker" data-id="${esc(pid)}">${esc(names[pid] || pid)}</button>`)
          .join('')}</div>
        <h3>Ball type</h3><div class="grid3">${[[null, 'Normal'], ['wide', 'Wide'], ['no_ball', 'No ball']]
          .map(([k, l]) => `<button class="choice ${e.extra === k ? 'sel' : ''}" data-act="e-extra" data-x="${k ?? ''}">${l}</button>`)
          .join('')}</div>
        <h3>Runs <span class="muted">(currently ${e.runs})</span></h3>
        <div class="grid4">${range(0, 6)
          .map((n) => `<button class="btn-run ${e.runs === n ? 'sel-run' : ''}" data-act="e-runs" data-n="${n}">${n}</button>`)
          .join('')}</div>
        <div class="grid3">${[-1, -2, -3]
          .map((n) => `<button class="btn-minus ${e.runs === n ? 'sel-run' : ''}" data-act="e-runs" data-n="${n}">${n}</button>`)
          .join('')}</div>
        <div class="custom-runs"><input id="edit-custom" type="number" inputmode="numeric" min="0" max="${MAX_RUNS}" placeholder="Custom runs"
          value="${e.runs > 6 ? e.runs : ''}"><button class="btn" data-act="e-custom">Set</button></div>
        ${dismissalNote}
        <button class="btn btn-primary btn-xl" data-act="e-save">Save Ball</button>
        <button class="btn" data-act="close">Cancel</button>`,
        async (act, ds) => {
          if (act === 'e-striker') e.striker = ds.id;
          else if (act === 'e-extra') e.extra = ds.x || null;
          else if (act === 'e-runs') e.runs = Number(ds.n);
          else if (act === 'e-custom') {
            const n = Number($('#edit-custom').value);
            if (!Number.isInteger(n) || n < 0 || n > MAX_RUNS) return toast(`Enter 0 to ${MAX_RUNS}`);
            e.runs = n;
          } else if (act === 'e-save') {
            const event = { type: 'ball', striker: e.striker, runs: e.runs };
            if (e.extra) event.extra = e.extra;
            if (ev.dismissal) event.dismissal = ev.dismissal;
            try {
              const v = await Api.editBall(matchId, rb.event_index, event, newOpId());
              closeSheet();
              Store.saveView(matchId, v);
              onSaved(v);
              toast('Ball updated');
            } catch (err) {
              toast(err.offline ? 'Editing a ball needs a connection' : err.message, 6000);
            }
            return;
          }
          draw();
        }
      );
    draw();
  }

  function doUndo() {
    const id = ctx.matchId;
    const pending = Store.outbox(id);
    if (pending.length) {
      pending.pop();
      Store.setOutbox(id, pending);
      ctx.syncError = null;
      drawMatch();
      return toast('Removed last unsynced action');
    }
    if (!confirm('Undo the last ball?')) return;
    submit('undo', null);
  }

  // ------------------------------------------------------------- scorecard --

  async function renderScorecard(id) {
    setTitle('Scorecard', true);
    viewEl.innerHTML = '<div class="muted pad-top">Loading…</div>';
    const sc = await Api.scorecard(id);
    const scorerUnlocked = await hasScorerAccess();
    ctx.scorecard = { id, innings: sc.innings };
    ctx.lastStatus = sc.match.status;
    setTitle(sc.match.name, true);
    const s = sc.summary;
    const tb = s.top_batsman;
    const tw = s.top_bowler;
    const summary = `<section class="card summary">
      <div class="result">${esc(s.result?.text || 'Match in progress')}</div>
      ${s.team_scores
        .map((t) => `<div class="row-between"><span>${esc(t.name)}</span><b>${esc(t.innings.join(' & ') || 'Yet to bat')}</b></div>`)
        .join('')}
      ${tb ? `<div class="row-between"><span>Top batsman</span><span>${esc(tb.name)} <b>${tb.runs}</b> (${tb.balls})</span></div>` : ''}
      ${tw ? `<div class="row-between"><span>Top bowler</span><span>${esc(tw.name)} <b>${tw.wickets}/${tw.runs}</b> (${tw.overs})</span></div>` : ''}
      <div class="muted">${esc(sc.match.date)}${sc.match.venue ? ' · ' + esc(sc.match.venue) : ''}</div>
    </section>`;
    const innings = sc.innings
      .map((inn) => {
        const bat = inn.batting
          .map(
            (b) => `<tr class="${b.status === 'retired' ? 'retired' : ''}"><td><div>${esc(b.name)}</div>
              <small>${esc(b.dismissal || '')}</small>${(b.pair_dismissals || [])
                .map((dismissal, i) => `<small class="pair-dismissal">Pair ${i + 1}: ${esc(dismissal)}</small>`)
                .join('')}</td>
              <td><b>${b.runs}</b></td><td>${b.balls}</td><td>${b.wides_faced ?? 0}</td><td>${b.fours}</td><td>${b.sixes}</td><td>${fmt(b.strike_rate, 1)}</td></tr>`
          )
          .join('');
        const bowl = inn.bowling
          .map(
            (b) => `<tr><td>${esc(b.name)}</td><td>${b.overs}</td><td>${b.runs}</td><td><b>${b.wickets}</b></td><td>${fmt(b.economy)}</td><td>${b.wides}</td><td>${b.no_balls}</td></tr>`
          )
          .join('');
        const x = inn.extras;
        const fow = inn.fall_of_wickets.map((f) => `${f.wicket}-${f.runs} (${esc(f.name)}, ${f.overs})`).join(', ');
        const overs = [];
        inn.balls.forEach((b, bi) => {
          const last = overs[overs.length - 1];
          if (!last || last.over !== b.over) overs.push({ over: b.over, bowler: b.bowler_name, balls: [], total: 0 });
          overs[overs.length - 1].total += b.total;
          const chip = scorerUnlocked
            ? `<button class="chip chip-btn ${chipClass(b.label)}" data-act="sc-edit" data-inn="${inn.number - 1}" data-i="${bi}"
                title="${esc(b.striker_name)} facing">${esc(b.label)}</button>`
            : `<span class="chip ${chipClass(b.label)}" title="${esc(b.striker_name)} facing">${esc(b.label)}</span>`;
          overs[overs.length - 1].balls.push(chip);
        });
        const ballByBall = overs.length
          ? `<details class="bbb"><summary>Ball by ball ${scorerUnlocked ? '<span class="muted">(tap a ball to edit)</span>' : ''}</summary>
              ${overs
                .map((o) => `<div class="bbb-over"><span class="muted">Ov ${o.over} · ${esc(o.bowler)} · Total: ${o.total}</span><div class="bbb-balls">${o.balls.join('')}</div></div>`)
                .join('')}</details>`
          : '';
        return `<section class="card">
          <h2>${esc(inn.batting_team_name)} <span class="muted">Innings ${inn.number}</span></h2>
          <div class="sb-score small">${inn.runs}/${inn.wickets} <small>(${inn.overs} ov, RR ${fmt(inn.run_rate)})</small></div>
          ${inn.target ? `<div class="muted">Target ${inn.target}</div>` : ''}
          <table class="tbl"><thead><tr><th>Batting</th><th>R</th><th>B</th><th title="Wides faced">Wd</th><th>4s</th><th>6s</th><th>SR</th></tr></thead><tbody>${bat}</tbody></table>
          <div class="row-between"><span>Extras</span><span><b>${x.total}</b> (wd ${x.wide}, nb ${x.no_ball})</span></div>
          <div class="row-between"><span>Total</span><b>${inn.runs}/${inn.wickets} (${inn.overs} ov)</b></div>
          ${inn.retired.length ? `<div><span class="muted">Retired not out:</span> ${esc(inn.retired.join(', '))}</div>` : ''}
          ${inn.did_not_bat.length ? `<div><span class="muted">Did not bat:</span> ${esc(inn.did_not_bat.join(', '))}</div>` : ''}
          ${fow ? `<div><span class="muted">Fall of wickets:</span> ${fow}</div>` : ''}
          <table class="tbl"><thead><tr><th>Bowling</th><th>O</th><th>R</th><th>W</th><th>Econ</th><th>Wd</th><th>Nb</th></tr></thead><tbody>${bowl}</tbody></table>
          ${ballByBall}
        </section>`;
      })
      .join('');
    const actions = `<div class="stack">
      <a class="btn btn-primary btn-xl" href="#/match/${esc(id)}">Scorer</a>
      <a class="btn" href="#/match/${esc(id)}/details">Edit Match Setup</a>
      <a class="btn" href="${Api.pdfUrl(id)}" download>Export PDF Scorecard</a>
      <button class="btn btn-danger" data-act="delete" data-id="${esc(id)}" data-name="${esc(sc.match.name)}">Delete Match</button>
      <a class="backup-link" href="${Api.exportUrl(id)}" download>Backup Match as JSON</a>
    </div>`;
    viewEl.innerHTML = `<div class="stack">${summary}${innings}${actions}</div>`;
  }

  // --------------------------------------------------------- match details --

  async function renderDetails(id) {
    if (!(await requireScorer(`#/match/${id}/details`))) return;
    setTitle('Match Setup', true);
    viewEl.innerHTML = '<div class="muted pad-top">Loading…</div>';
    const v = await Api.getMatch(id);
    const done = v.state.status === 'completed';
    const ed = {
      name: v.match.name,
      date: v.match.date,
      venue: v.match.venue || '',
      overs: String(v.state.overs ?? v.match.settings.overs),
      pairing_overs: String(v.state.pairing_overs ?? v.match.settings.pairing_overs ?? 0),
      teams: v.match.teams.map((t) => ({ name: t.name, players: t.players.map((p) => ({ ...p })) })),
    };

    const playerRow = (p, ti, pi) => `<div class="player-row">
        <input data-team="${ti}" data-player="${pi}" data-field="name" maxlength="40" value="${esc(p.name)}" placeholder="Player name">
        <button type="button" class="btn btn-small btn-danger" data-ed="remove" data-team="${ti}" data-player="${pi}" aria-label="Remove player">&#10005;</button>
      </div>`;

    const draw = () => {
      viewEl.innerHTML = `<form id="details-form" class="stack form" novalidate>
        <fieldset><legend>Match details</legend>
          <label>Match name<input name="name" maxlength="80" value="${esc(ed.name)}"></label>
          <div class="row2"><label>Date<input type="date" name="date" value="${esc(ed.date)}"></label>
          <label>Venue<input name="venue" maxlength="80" value="${esc(ed.venue)}"></label></div>
          <label>Overs per innings<input type="number" name="overs" min="1" max="50" inputmode="numeric" value="${esc(ed.overs)}" ${done ? 'disabled' : ''}></label>
          <label>Pairing overs (0 = off)<input type="number" name="pairing_overs" min="0" max="50" inputmode="numeric" value="${esc(ed.pairing_overs)}" ${done ? 'disabled' : ''}></label>
          <div class="muted">${done ? 'Match is complete; overs can no longer be changed.' : 'A change of overs applies from now on, including the current innings.'}</div>
        </fieldset>
        ${ed.teams
          .map(
            (t, ti) => `<fieldset><legend>Team ${ti + 1}</legend>
            <label>Team name<input data-team="${ti}" data-field="team-name" maxlength="40" value="${esc(t.name)}"></label>
            <div class="muted">Name · remove</div>
            ${t.players.map((p, pi) => playerRow(p, ti, pi)).join('')}
            <button type="button" class="btn btn-small" data-ed="add" data-team="${ti}">+ Add player</button>
          </fieldset>`
          )
          .join('')}
        <button class="btn btn-primary btn-xl" type="submit">Save Changes</button>
        <a class="btn" href="#/match/${esc(id)}">Cancel</a>
      </form>`;

      const form = $('#details-form');
      form.addEventListener('input', (e) => {
        const el = e.target;
        if (el.name && el.name in ed) {
          ed[el.name] = el.value;
          return;
        }
        if (el.dataset.team === undefined) return;
        const team = ed.teams[el.dataset.team];
        if (el.dataset.field === 'team-name') team.name = el.value;
        else if (el.dataset.field === 'name') team.players[el.dataset.player].name = el.value;
      });
      form.addEventListener('click', (e) => {
        const b = e.target.closest('[data-ed]');
        if (!b) return;
        const team = ed.teams[b.dataset.team];
        if (b.dataset.ed === 'add') team.players.push({ id: null, name: '' });
        else team.players.splice(Number(b.dataset.player), 1);
        draw();
      });
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const body = {
          name: ed.name,
          date: ed.date,
          venue: ed.venue,
          teams: ed.teams.map((t) => ({
            name: t.name,
            players: t.players
              .filter((p) => p.name.trim())
              .map((p) => ({ ...(p.id ? { id: p.id } : {}), name: p.name.trim() })),
          })),
        };
        try {
          let view = await Api.updateDetails(id, body);
          const overs = Number(ed.overs);
          if (!done && overs !== view.state.overs) {
            view = await Api.addEvent(id, { type: 'set_overs', overs }, newOpId());
          }
          const pairing = Number(ed.pairing_overs);
          if (!done && pairing !== view.state.pairing_overs) {
            view = await Api.addEvent(id, { type: 'set_pairing_overs', pairing_overs: pairing }, newOpId());
          }
          Store.saveView(id, view);
          toast('Match updated');
          location.hash = `#/match/${id}`;
        } catch (err) {
          toast(err.offline ? 'Editing match setup needs a connection' : err.message, 5000);
        }
      });
    };
    draw();
  }

  // ------------------------------------------------------- click dispatcher --

  function submitCustomRuns() {
    const raw = String(ctx.draft.custom).trim();
    const n = Number(raw);
    if (raw === '' || !Number.isInteger(n) || n < 0 || n > MAX_RUNS) {
      return toast(`Enter a whole number of runs between 0 and ${MAX_RUNS}`);
    }
    if (!ctx.draft.striker && ctx.view.state.current) return toast('Select the striker first');
    return submitBall(n, null);
  }

  viewEl.addEventListener('input', (e) => {
    if (e.target.id === 'custom-runs' && ctx.draft) ctx.draft.custom = e.target.value;
  });
  viewEl.addEventListener('keydown', (e) => {
    if (e.target.id === 'custom-runs' && e.key === 'Enter') {
      e.preventDefault();
      submitCustomRuns();
    }
  });

  viewEl.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn || btn.disabled) return;
    const ds = btn.dataset;
    switch (ds.act) {
      case 'delete':
        return deleteMatch(ds.id, ds.name);
      case 'lock-scorer':
        return lockScorer();
      case 'runs':
        return submitBall(Number(ds.n), null);
      case 'custom-runs':
        return submitCustomRuns();
      case 'extra':
        if (ds.x === 'no_ball') {
          ctx.draft.extra = ctx.draft.extra === 'no_ball' ? null : 'no_ball';
          return drawMatch();
        }
        return submitBall(0, null, ds.x);
      case 'striker':
        ctx.draft.striker = ds.id;
        return drawMatch();
      case 'retire-one':
        return openRetireSheet();
      case 'retire-both':
        return retireBoth();
      case 'cancel-retire':
        return submit('cancel_retire', null);
      case 'wicket':
        return openWicketSheet();
      case 'sc-edit': {
        const sc = ctx.scorecard;
        const ball = sc?.innings[Number(ds.inn)]?.balls[Number(ds.i)];
        if (ball) openEditBall(ball, sc.id, () => renderScorecard(sc.id));
        return;
      }
      case 'edit-ball-list':
        return openEditList();
      case 'change-bowler':
        return openBowlerSheet();
      case 'new-batsman':
        return openBatsmanSheet();
      case 'end-innings':
        if (confirm('End this innings now?')) submit('event', { type: 'end_innings' });
        return;
      case 'undo':
        return doUndo();
      case 'pick-batsman':
        return submit('event', { type: 'new_batsman', batsman: ds.id });
      case 'pick-bowler':
        return submit('event', { type: 'bowler', bowler: ds.id });
      case 'bat-team':
        ctx.picks = { team: Number(ds.team), openers: [], bowler: null };
        return drawMatch();
      case 'opener': {
        const o = ctx.picks.openers;
        const i = o.indexOf(ds.id);
        if (i >= 0) o.splice(i, 1);
        else if (o.length < 2) o.push(ds.id);
        return drawMatch();
      }
      case 'open-bowler':
        ctx.picks.bowler = ds.id;
        return drawMatch();
      case 'start-innings': {
        const p = ctx.picks;
        ctx.picks = null;
        return submit('event', {
          type: 'innings_start',
          batting_team: p.team,
          striker: p.openers[0],
          non_striker: p.openers[1],
          bowler: p.bowler,
        });
      }
      case 'retry-sync':
        ctx.syncError = null;
        return syncOutbox();
      case 'discard-outbox':
        if (confirm('Discard all unsynced actions for this match?')) {
          Store.setOutbox(ctx.matchId, []);
          ctx.syncError = null;
          drawMatch();
        }
        return;
    }
  });

  // ----------------------------------------------------------------- start --

  if ('serviceWorker' in navigator) {
    const hadController = !!navigator.serviceWorker.controller;
    let reloaded = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (hadController && !reloaded) {
        reloaded = true;
        location.reload();
      }
    });
    navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).then((r) => r.update()).catch(() => {});
  }
  route().finally(() => {
    const splash = $('#splash');
    splash.classList.add('hide');
    setTimeout(() => splash.remove(), 400);
  });
})();
