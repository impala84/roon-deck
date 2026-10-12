import {createSession, database, json, parseBody, requestIpHash, sameOrigin, verifyPassword} from '../_auth.js';

export default async function handler(request, response) {
  if (request.method !== 'POST') return json(response, 405, {error: 'Method not allowed.'});
  if (!sameOrigin(request)) return json(response, 403, {error: 'Invalid request origin.'});
  try {
    const {email = '', password = ''} = parseBody(request);
    const sql = database();
    const ipHash = requestIpHash(request);
    const recent = await sql`select count(*)::int as count from cms_login_attempts where ip_hash = ${ipHash} and attempted_at > now() - interval '15 minutes'`;
    if ((recent[0]?.count || 0) >= 8) return json(response, 429, {error: 'Too many sign-in attempts. Please wait 15 minutes.'});
    await sql`insert into cms_login_attempts (ip_hash) values (${ipHash})`;
    const rows = await sql`select id, email, password_hash from cms_admin_users where lower(email) = lower(${String(email).trim()}) limit 1`;
    const user = rows[0];
    if (!user || !(await verifyPassword(String(password), user.password_hash))) return json(response, 401, {error: 'Email or password is incorrect.'});
    await sql`delete from cms_login_attempts where ip_hash = ${ipHash}`;
    await createSession(response, user.id);
    return json(response, 200, {ok: true, user: {id: user.id, email: user.email}});
  } catch (error) {
    console.error('CMS login failed', error);
    return json(response, 503, {error: 'Sign-in is temporarily unavailable.'});
  }
}
