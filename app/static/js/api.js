'use strict';

/* Thin REST client plus on-device persistence used for offline scoring. */

const Api = (() => {
  function detail(data) {
    if (!data) return null;
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join('; ');
    return null;
  }

  async function request(method, url, body, raw = false, headers = {}) {
    const opts = { method, headers: { ...headers } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = raw ? body : JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      const err = new Error('You are offline');
      err.offline = true;
      throw err;
    }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const err = new Error(detail(data) || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  const m = (id) => `/api/matches/${encodeURIComponent(id)}`;

  return {
    scorerSession: () => request('GET', '/api/scorer/session'),
    loginScorer: (password) => request('POST', '/api/scorer/session', { password }),
    logoutScorer: () => request('DELETE', '/api/scorer/session'),
    listMatches: () => request('GET', '/api/matches'),
    createMatch: (body) => request('POST', '/api/matches', body),
    getMatch: (id) => request('GET', m(id)),
    deleteMatch: (id, password) => request('DELETE', m(id), undefined, false, { 'X-Delete-Password': password }),
    addEvent: (id, event, opId) => request('POST', `${m(id)}/events`, { op_id: opId, event }),
    undo: (id, opId) => request('POST', `${m(id)}/undo`, { op_id: opId }),
    editBall: (id, index, event, opId) => request('PUT', `${m(id)}/events/${index}`, { op_id: opId, event }),
    cancelRetire: (id, opId) => request('POST', `${m(id)}/cancel-retire`, { op_id: opId }),
    scorecard: (id) => request('GET', `${m(id)}/scorecard`),
    updateDetails: (id, body) => request('PUT', `${m(id)}/details`, body),
    importMatch: (jsonText) => request('POST', '/api/matches/import', jsonText, true),
    exportUrl: (id) => `${m(id)}/export`,
    pdfUrl: (id) => `${m(id)}/export.pdf`,
  };
})();

const Store = (() => {
  const read = (key, fallback) => {
    try {
      const v = localStorage.getItem(key);
      return v ? JSON.parse(v) : fallback;
    } catch {
      return fallback;
    }
  };
  const write = (key, value) => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage full or unavailable */
    }
  };
  return {
    outbox: (id) => read(`outbox:${id}`, []),
    setOutbox: (id, items) => (items.length ? write(`outbox:${id}`, items) : localStorage.removeItem(`outbox:${id}`)),
    pushOutbox(id, item) {
      const items = this.outbox(id);
      items.push(item);
      this.setOutbox(id, items);
    },
    lastView: (id) => read(`view:${id}`, null),
    saveView: (id, view) => write(`view:${id}`, view),
    forget(id) {
      localStorage.removeItem(`outbox:${id}`);
      localStorage.removeItem(`view:${id}`);
    },
  };
})();

function newOpId() {
  if (self.crypto && crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
