import {createSession, database, hashPassword, hashToken, json, parseBody, sameOrigin, validPassword} from '../_auth.js';

export default async function handler(request, response) {
  if (request.method !== 'POST') return json(response, 405, {error: 'Method not allowed.'});
  if (!sameOrigin(request)) return json(response, 403, {error: 'Invalid request origin.'});
  try {
    const {token = '', password = ''} = parseBody(request);
    if (!validPassword(password)) return json(response, 400, {error: 'Use a password of at least 12 characters.'});
    const sql = database();
    const tokens = await sql`update cms_setup_tokens set used_at = now() where token_hash = ${hashToken(String(token))} and used_at is null and expires_at > now() returning token_hash, email`;
    if (!tokens[0]) return json(response, 400, {error: 'This setup link is invalid or has expired.'});
    const passwordHash = await hashPassword(password);
    const users = await sql`insert into cms_admin_users (email, password_hash) values (${tokens[0].email}, ${passwordHash}) on conflict (email) do update set password_hash = excluded.password_hash, updated_at = now() returning id, email`;
    await sql`delete from cms_admin_sessions where user_id = ${users[0].id}`;
    await createSession(response, users[0].id);
    return json(response, 200, {ok: true, user: users[0]});
  } catch (error) {
    console.error('CMS setup failed', error);
    return json(response, 503, {error: 'Setup is temporarily unavailable.'});
  }
}
