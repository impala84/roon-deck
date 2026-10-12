import {database, json, parseBody, requireUser, sameOrigin} from '../_auth.js';

export default async function handler(request, response) {
  try {
    const user = await requireUser(request, response);
    if (!user) return;
    const sql = database();
    if (request.method === 'GET') {
      const rows = await sql`select content_key, content_value, updated_at from cms_content order by content_key`;
      return json(response, 200, {content: Object.fromEntries(rows.map(row => [row.content_key, row.content_value]))});
    }
    if (request.method !== 'PUT') return json(response, 405, {error: 'Method not allowed.'});
    if (!sameOrigin(request)) return json(response, 403, {error: 'Invalid request origin.'});
    const body = parseBody(request);
    const entries = Object.entries(body.content || {});
    if (entries.length > 150) return json(response, 400, {error: 'Too many content fields.'});
    for (const [key, value] of entries) {
      if (!/^[a-z0-9_.-]{1,100}$/.test(key) || typeof value !== 'string' || value.length > 5000) return json(response, 400, {error: 'One or more content fields is invalid.'});
      await sql`insert into cms_content (content_key, content_value, updated_by) values (${key}, ${value}, ${user.id}) on conflict (content_key) do update set content_value = excluded.content_value, updated_by = excluded.updated_by, updated_at = now()`;
    }
    return json(response, 200, {ok: true});
  } catch (error) {
    console.error('CMS content request failed', error);
    return json(response, 503, {error: 'Content could not be saved.'});
  }
}

