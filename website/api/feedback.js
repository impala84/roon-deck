import crypto from 'node:crypto';
import { neon } from '@neondatabase/serverless';

const categories = new Set(['suggestion', 'feature', 'bug']);
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function reply(response, status, body) {
  response.status(status).setHeader('Content-Type', 'application/json');
  response.setHeader('Cache-Control', 'no-store');
  response.end(JSON.stringify(body));
}

export default async function handler(request, response) {
  if (request.method !== 'POST') return reply(response, 405, {error: 'Method not allowed.'});
  if (!process.env.DATABASE_URL) return reply(response, 503, {error: 'Feedback is temporarily unavailable.'});

  let body;
  try {
    body = typeof request.body === 'string' ? JSON.parse(request.body || '{}') : (request.body || {});
  } catch {
    return reply(response, 400, {error: 'The message could not be read.'});
  }
  const category = String(body.category || '');
  const message = String(body.message || '').trim();
  const email = String(body.email || '').trim();
  const startedAt = Number(body.started_at || 0);
  if (body.website) return reply(response, 200, {ok: true});
  if (!categories.has(category) || message.length < 10 || message.length > 2000) return reply(response, 400, {error: 'Please enter a message between 10 and 2,000 characters.'});
  if (email && !emailPattern.test(email)) return reply(response, 400, {error: 'Please check the reply email address.'});
  if (!startedAt || Date.now() - startedAt < 2500 || Date.now() - startedAt > 86400000) return reply(response, 400, {error: 'Please reload the page and try again.'});

  const forwarded = String(request.headers['x-forwarded-for'] || '').split(',')[0].trim();
  const ipHash = crypto.createHash('sha256').update(`${forwarded}:${process.env.FEEDBACK_HASH_SALT || 'roondeck'}`).digest('hex');
  try {
    const sql = neon(process.env.DATABASE_URL);
    const recent = await sql`select count(*)::int as count from feedback_messages where ip_hash = ${ipHash} and created_at > now() - interval '15 minutes'`;
    if (recent[0].count >= 3) return reply(response, 429, {error: 'Please wait before sending another message.'});

    const inserted = await sql`insert into feedback_messages (category, message, reply_email, ip_hash, user_agent) values (${category}, ${message}, ${email || null}, ${ipHash}, ${String(request.headers['user-agent'] || '').slice(0, 300)}) returning id`;
    let delivered = false;
    if (process.env.RESEND_API_KEY) {
      const mail = await fetch('https://api.resend.com/emails', {method: 'POST', headers: {'Authorization': `Bearer ${process.env.RESEND_API_KEY}`, 'Content-Type': 'application/json'}, body: JSON.stringify({from: process.env.FEEDBACK_FROM || 'RoonDeck <onboarding@resend.dev>', to: ['philipjdall@gmail.com'], reply_to: email || undefined, subject: `RoonDeck ${category.replace('_', ' ')}`, text: `${message}\n\nReply email: ${email || 'Not supplied'}\nSubmission: ${inserted[0].id}`})});
      delivered = mail.ok;
      if (delivered) await sql`update feedback_messages set delivered_at = now() where id = ${inserted[0].id}`;
    }
    return reply(response, 200, {ok: true, delivered});
  } catch (error) {
    console.error('Feedback submission failed', error);
    return reply(response, 503, {error: 'Feedback is temporarily unavailable. Please try again later.'});
  }
}
