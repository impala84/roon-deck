import crypto from 'node:crypto';
import {promisify} from 'node:util';
import {neon} from '@neondatabase/serverless';

const scrypt = promisify(crypto.scrypt);
const COOKIE_NAME = 'roondeck_admin';
const SESSION_SECONDS = 60 * 60 * 24 * 14;

export function database() {
  if (!process.env.DATABASE_URL) throw new Error('DATABASE_URL is not configured.');
  return neon(process.env.DATABASE_URL);
}

export function json(response, status, body, headers = {}) {
  response.status(status).setHeader('Content-Type', 'application/json');
  response.setHeader('Cache-Control', 'no-store');
  for (const [name, value] of Object.entries(headers)) response.setHeader(name, value);
  response.end(JSON.stringify(body));
}

export function parseBody(request) {
  if (typeof request.body === 'string') return JSON.parse(request.body || '{}');
  return request.body || {};
}

export function hashToken(token) {
  return crypto.createHash('sha256').update(token).digest('hex');
}

export function requestIpHash(request) {
  const forwarded = String(request.headers['x-forwarded-for'] || '').split(',')[0].trim();
  const address = forwarded || request.socket?.remoteAddress || 'unknown';
  return hashToken(`${process.env.FEEDBACK_HASH_SALT || 'roondeck-cms'}:${address}`);
}

export async function hashPassword(password) {
  const salt = crypto.randomBytes(16);
  const derived = await scrypt(password, salt, 64);
  return `scrypt:${salt.toString('hex')}:${derived.toString('hex')}`;
}

export async function verifyPassword(password, stored) {
  const [algorithm, saltHex, hashHex] = String(stored).split(':');
  if (algorithm !== 'scrypt' || !saltHex || !hashHex) return false;
  const derived = await scrypt(password, Buffer.from(saltHex, 'hex'), 64);
  const expected = Buffer.from(hashHex, 'hex');
  return expected.length === derived.length && crypto.timingSafeEqual(expected, derived);
}

function cookies(request) {
  return Object.fromEntries(String(request.headers.cookie || '').split(';').map(part => part.trim().split('=').map(decodeURIComponent)).filter(pair => pair.length === 2));
}

export async function currentUser(request) {
  const token = cookies(request)[COOKIE_NAME];
  if (!token) return null;
  const sql = database();
  const rows = await sql`select u.id, u.email from cms_admin_sessions s join cms_admin_users u on u.id = s.user_id where s.token_hash = ${hashToken(token)} and s.expires_at > now() limit 1`;
  return rows[0] || null;
}

export async function requireUser(request, response) {
  const user = await currentUser(request);
  if (!user) json(response, 401, {error: 'Please sign in.'});
  return user;
}

export async function createSession(response, userId) {
  const token = crypto.randomBytes(32).toString('base64url');
  const sql = database();
  await sql`insert into cms_admin_sessions (token_hash, user_id, expires_at) values (${hashToken(token)}, ${userId}, now() + interval '14 days')`;
  response.setHeader('Set-Cookie', `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_SECONDS}`);
}

export function clearSession(response) {
  response.setHeader('Set-Cookie', `${COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`);
}

export function sameOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return true;
  const host = request.headers['x-forwarded-host'] || request.headers.host;
  return origin === `https://${host}` || origin === `http://${host}`;
}

export function validPassword(password) {
  return typeof password === 'string' && password.length >= 12 && password.length <= 200;
}
