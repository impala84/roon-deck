'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {playMixTrack}=require('./discovery-track');
const sdk=require('./vendor/roon-research/sdk.cjs');

function fixture(){
  const album={fields:{Title:'The Mix',PerformedBy:'Artist'}};
  const tracks=['First','Selected','Last'].map((title,index)=>({oid:BigInt(20+index),fields:{Title:title,PerformedBy:'Artist',TrackId:String(index),Album:album}}));
  const mix={oid:2n,typeName:'Test.Mix',fields:{MixId:Buffer.from('aabb','hex')}};
  const zone={oid:1n,typeName:'Test.Zone',fields:{ZoneId:Buffer.alloc(18,1)}};
  const objects=new Map([[1n,zone],[2n,mix],...tracks.map(track=>[track.oid,track])]);
  const calls=[];let decoded=0;
  const client={profile:()=>Buffer.alloc(16),serviceOid:()=>3n,structArg:()=>Buffer.alloc(0),graph:{objects,getObject:id=>objects.get(id),decodeReturnValue:()=>decoded++===0?{$ref:2n}:{$items:[{Tracks:{$items:tracks}}]}},remoting:{callMethod:async(_oid,method)=>{calls.push(method);return {success:true,payload:Buffer.alloc(0)}}}};
  return {client,calls,track:{kind:'track',title:'Selected',artist:'Artist',album:'The Mix',id:'1'}};
}

test('Play Now starts the verified mix from the selected track while Queue adds only that track',async()=>{
  const request={id:'aabb',zoneId:'01'.repeat(18)};
  const playing=fixture();await playMixTrack(playing.client,sdk,{...request,action:'play',track:playing.track});assert.match(playing.calls.at(-1),/Transport::PlayMix\(/);
  const queued=fixture();await playMixTrack(queued.client,sdk,{...request,action:'queue',track:queued.track});assert.match(queued.calls.at(-1),/Transport::PlayTrack\(/);
});

test('a non-unique track identity is refused before changing the queue',async()=>{
  const f=fixture();f.track.id='';f.track.title='Missing';await assert.rejects(playMixTrack(f.client,sdk,{id:'aabb',zoneId:'01'.repeat(18),action:'play',track:f.track}));assert.equal(f.calls.some(call=>call.includes('Transport::')),false);
});
