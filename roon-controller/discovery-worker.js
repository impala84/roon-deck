'use strict';
// This process has a memory ceiling/deadline imposed by its parent. It only
// reads discovery data, or handles one explicitly requested whole-mix action,
// closes its socket and exits; no recurring connection or playback retries.
const sdk = require('./vendor/roon-research/sdk.cjs');
const {readDiscovery, waitFor} = require('./discovery-read');
const {playMix} = require('./discovery-mix');
const {playMixTrack} = require('./discovery-track');
const {libraryOperation}=require('./library-protocol');
process.once('message', async ({host, brokerId, section, id, zoneId, action, album, track, albumId, favorite}) => {
  const client = new sdk.RoonClient({host, serverBrokerId: Buffer.from(brokerId, 'hex'), settleMs:['mix-action','track-action'].includes(section)?2000:0});
  try {
    await client.connect();
    if(!['mix-action','track-action'].includes(section)) await waitFor(()=>{try{client.profile();client.serviceOid('Library');return true;}catch{return undefined;}});
    const data = section === 'library' ? await libraryOperation(client,sdk,{zoneId,action,album,track,albumId,favorite}) : section === 'mix-action' ? await playMix(client,sdk,{id,zoneId,action}) : section === 'track-action' ? await playMixTrack(client,sdk,{id,zoneId,action,track}) : await readDiscovery(client, sdk, section, id);
    process.send({ok: true, data}, () => {client.close(); process.exit(0);});
  } catch {
    client.close();
    // Do not leak signed artwork URLs, profile IDs or raw graph/error dumps.
    process.send({ok: false}, () => process.exit(1));
  }
});
