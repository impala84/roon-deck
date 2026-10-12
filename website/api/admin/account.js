import {clearSession, database, hashPassword, json, parseBody, requireUser, sameOrigin, validPassword, verifyPassword} from '../_auth.js';

export default async function handler(request, response) {
  if (request.method !== 'PUT') return json(response, 405, {error: 'Method not allowed.'});
  if (!sameOrigin(request)) return json(response, 403, {error: 'Invalid request origin.'});
  try {
    const user = await requireUser(request, response);
    if (!user) return;
    const {currentPassword = '', email = '', newPassword = ''} = parseBody(request);
    const sql = database();
    const rows = await sql`select password_hash from cms_admin_users where id = ${user.id} limit 1`;
    if (!rows[0] || !(await verifyPassword(String(currentPassword), rows[0].password_hash))) return json(response, 401, {error: 'Current password is incorrect.'});
    const normalizedEmail = String(email).trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) return json(response, 400, {error: 'Enter a valid email address.'});
    if (newPassword && !validPassword(newPassword)) return json(response, 400, {error: 'New passwords must contain at least 12 characters.'});
    if (newPassword) {
      const passwordHash = await hashPassword(newPassword);
      await sql`update cms_admin_users set email = ${normalizedEmail}, password_hash = ${passwordHash}, updated_at = now() where id = ${user.id}`;
    } else {
      await sql`update cms_admin_users set email = ${normalizedEmail}, updated_at = now() where id = ${user.id}`;
    }
    await sql`delete from cms_admin_sessions where user_id = ${user.id}`;
    clearSession(response);
    return json(response, 200, {ok: true, signedOut: true});
  } catch (error) {
    console.error('CMS account update failed', error);
    return json(response, 503, {error: 'Account settings could not be saved.'});
  }
}

