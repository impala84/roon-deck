'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const {matches,openDiscovery}=require('./discovery-bridge');
const track={kind:'track',title:'Song',artist:'Artist'};
test('only exact title, artist and category resolve; private IDs are never browse keys',()=>{
  assert.ok(matches(track,{title:'Song',subtitle:'Artist, Guest',result_type:'tracks'}));
  for(const candidate of [{title:'Song live',subtitle:'Artist',result_type:'tracks'},{title:'Song',subtitle:'Other',result_type:'tracks'},{title:'Song',subtitle:'Artist',result_type:'albums'},{title:'Song',subtitle:'Artist',result_type:'tracks',action:true}])assert.equal(matches(track,candidate),false);
});
test('mix tracks open direct play and queue controls without searching editions',async()=>{
  const calls=[];const browser={run:async(...args)=>{calls.push(args);throw Error('must not search');}};
  const result=await openDiscovery(browser,'isolated',track);
  assert.equal(result.action_menu,true);assert.equal(result.discovery_track_actions,true);assert.deepEqual(result.items.map(item=>item.title),['Play Now','Queue']);assert.equal(calls.length,0);
});
test('several matching editions open the first and never play; no match stays a manual choice',async()=>{
  const album={kind:'album',title:'Album',artist:'Artist'};const calls=[];
  const result=await openDiscovery({run:async(s,action,data)=>{calls.push(action);return action==='search'?{items:[1,2].map(id=>({title:'Album',subtitle:'Artist',result_type:'albums',item_key:String(id)}))}:{opened:data.item_key};}},'s',album);
  assert.equal(result.opened,'1');assert.deepEqual(calls,['search','open']);
  const none=await openDiscovery({run:async()=>({items:[]})},'s',album);assert.equal(none.discovery_ambiguous,true);
});
test('expired selections fail before any official API call',async()=>{
  await assert.rejects(()=>openDiscovery({run:()=>{throw new Error('Must not call');}},'s',null),/no longer available/);
});
test('an album is searched by title and artist first, then by title alone',async()=>{
  const queries=[];const album={kind:'album',title:'Lull',artist:'Antix'};
  const browser={run:async(session,action,data)=>{queries.push(data.query||action);
    if(action==='search'&&data.query==='Lull Antix')return {items:[{title:'Lull',subtitle:'Antix',result_type:'albums',item_key:'7'}]};
    if(action==='search')return {items:[{title:'Lullabies',subtitle:'Other',result_type:'albums',item_key:'1'}]};
    return {opened:data.item_key};}};
  const result=await openDiscovery(browser,'s',album);
  assert.deepEqual(queries,['Lull Antix','open']);assert.equal(result.opened,'7');
  const fallback=[];
  const second=await openDiscovery({run:async(session,action,data)=>{fallback.push(data.query||action);return data.query==='Lull'?{items:[{title:'Lull',subtitle:'Antix',result_type:'albums',item_key:'9'}]}:action==='search'?{items:[]}:{opened:data.item_key};}},'s',album);
  assert.deepEqual(fallback,['Lull Antix','Lull','open']);assert.equal(second.opened,'9');
});
