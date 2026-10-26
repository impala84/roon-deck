import {currentUser, json} from '../_auth.js';

export default async function handler(request, response) {
  if (request.method !== 'GET') return json(response, 405, {error: 'Method not allowed.'});
  try {
    const user = await currentUser(request);
    return json(response, 200, {authenticated: Boolean(user), user});
  } catch (error) {
    console.error('CMS session check failed', error);
    return json(response, 503, {error: 'The CMS is temporarily unavailable.'});
  }
}

