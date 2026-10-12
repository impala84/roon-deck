import {clearSession, currentUser, database, hashToken, json, sameOrigin} from '../_auth.js';

export default async function handler(request, response) {
  if (request.method !== 'POST') return json(response, 405, {error: 'Method not allowed.'});
  if (!sameOrigin(request)) return json(response, 403, {error: 'Invalid request origin.'});
  try {
    await currentUser(request);
    const raw = String(request.headers.cookie || '').match(/(?:^|;\s*)roondeck_admin=([^;]+)/)?.[1];
    if (raw) await database()`delete from cms_admin_sessions where token_hash = ${hashToken(decodeURIComponent(raw))}`;
    clearSession(response);
    return json(response, 200, {ok: true});
  } catch (error) {
    clearSession(response);
    return json(response, 200, {ok: true});
  }
}

