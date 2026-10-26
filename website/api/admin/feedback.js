import {database, json, parseBody, requireUser, sameOrigin} from '../_auth.js';

export default async function handler(request, response) {
  try {
    const user = await requireUser(request, response);
    if (!user) return;
    const sql = database();
    if (request.method === 'GET') {
      const rows = await sql`select id, category, message, reply_email, status, delivered_at, created_at from feedback_messages order by created_at desc limit 200`;
      return json(response, 200, {feedback: rows});
    }
    if (!sameOrigin(request)) return json(response, 403, {error: 'Invalid request origin.'});
    const {id, status} = parseBody(request);
    if (!Number.isInteger(Number(id))) return json(response, 400, {error: 'Invalid feedback item.'});
    if (request.method === 'DELETE') {
      await sql`delete from feedback_messages where id = ${Number(id)}`;
      return json(response, 200, {ok: true});
    }
    if (request.method !== 'PUT') return json(response, 405, {error: 'Method not allowed.'});
    if (!['new', 'read', 'resolved'].includes(status)) return json(response, 400, {error: 'Invalid feedback update.'});
    await sql`update feedback_messages set status = ${status} where id = ${Number(id)}`;
    return json(response, 200, {ok: true});
  } catch (error) {
    console.error('CMS feedback request failed', error);
    return json(response, 503, {error: 'Feedback could not be loaded.'});
  }
}
