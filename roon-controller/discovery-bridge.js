'use strict';
const normal = value => String(value || '').normalize('NFKC').trim().toLocaleLowerCase();
function matches(item, candidate) {
  const category = item.kind === 'track' ? 'tracks' : 'albums';
  if (candidate.action || candidate.result_type !== category || normal(item.title) !== normal(candidate.title)) return false;
  const credit = normal(candidate.subtitle);
  const artist = normal(item.artist);
  return artist && (credit === artist || credit.split(/\s*,\s*/).includes(artist));
}
async function openDiscovery(browser, session, item) {
  if (!item || !['album', 'track'].includes(item.kind)) throw new Error('This discovery item is no longer available');
  if (item.kind === 'track') return {status:'ready',layout:'list',action_menu:true,discovery_track_actions:true,items:[{title:'Play Now',action:true,item_key:'play'},{title:'Queue',action:true,item_key:'queue'}]};
  const found = await browser.run(session, 'search', {query:item.title,source:'all'});
  const candidates = (found.items || []).filter(candidate => matches(item,candidate));
  if (candidates.length !== 1) return {...found, message: candidates.length ? 'Several editions match. Choose the version you want.' : 'Roon could not uniquely match this item. Choose a result below.', discovery_ambiguous: true};
  let opened = await browser.run(session,'open',{item_key:candidates[0].item_key});
  // Only unwrap a verified view-only action-list preview. Never choose Play.
  if (item.kind === 'track' && opened.items?.length === 1 && opened.items[0].hint === 'action_list' && !opened.items[0].action && normal(opened.items[0].title) === normal(item.title)) {
    opened = await browser.run(session,'open',{item_key:opened.items[0].item_key});
  }
  return opened;
}
module.exports = {matches,openDiscovery};
