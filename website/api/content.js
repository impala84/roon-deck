import {database, json} from './_auth.js';

export default async function handler(request, response) {
  if (request.method !== 'GET') return json(response, 405, {error: 'Method not allowed.'});
  try {
    const rows = await database()`select content_key, content_value from cms_content order by content_key`;
    const content = Object.fromEntries(rows.map(row => [row.content_key, row.content_value]));
    response.setHeader('Cache-Control', 'no-store, max-age=0');
    response.status(200).setHeader('Content-Type', 'application/json').end(JSON.stringify({content}));
  } catch (error) {
    console.error('CMS public content failed', error);
    return json(response, 200, {content: {}});
  }
}
