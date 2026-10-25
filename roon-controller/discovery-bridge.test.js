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
test('ambiguous editions remain a manual choice and never auto-open or play',async()=>{
  let calls=0;const album={kind:'album',title:'Album',artist:'Artist'};const result=await openDiscovery({run:async()=>{calls++;return {items:[1,2].map(id=>({title:'Album',subtitle:'Artist',result_type:'albums',item_key:String(id)}))};}},'s',album);
  assert.equal(calls,1);assert.equal(result.discovery_ambiguous,true);
});
test('expired selections fail before any official API call',async()=>{
  await assert.rejects(()=>openDiscovery({run:()=>{throw new Error('Must not call');}},'s',null),/no longer available/);
});
