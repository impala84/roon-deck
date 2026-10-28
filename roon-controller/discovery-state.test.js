'use strict';
const test = require('node:test'); const assert = require('node:assert/strict'); const {EventEmitter} = require('node:events');
const {DiscoveryManager} = require('./discovery-state');
const tick = () => new Promise(resolve => setImmediate(resolve));
test('Daily exposes failed mixes even when recommendations succeed', () => {
  const manager = new DiscoveryManager();
  manager.state = section => section === 'daily' ? {status:'unavailable', message:'Mixes unavailable'} : {status:'ready', groups:[{items:[]}]};
  const home = manager.home();
  assert.equal(home.status, 'ready');
  assert.equal(home.mixes_status, 'unavailable');
  assert.equal(home.mixes_message, 'Mixes unavailable');
  assert.equal(home.groups.length, 1);
});
test('worker failures are cached, concurrent polls coalesce and private work is memory-bounded', async () => {
  let count = 0, child;
  const manager = new DiscoveryManager({spawn: (_, args, options) => {count++; assert.deepEqual(options.execArgv, ['--max-old-space-size=128']); child = new EventEmitter(); child.send = () => {}; child.kill = () => {}; return child;}});
  manager.setTarget({host:'example',brokerId:'00'});
  assert.equal(manager.state('daily').status, 'loading'); manager.state('daily'); await tick(); assert.equal(count,1);
  child.emit('error', new Error('private data')); await tick(); assert.equal(manager.state('daily').status,'unavailable'); assert.equal(count,1);
  assert.doesNotMatch(JSON.stringify(manager.state('daily')), /private data/);
});
test('cached results expire, and unpairing discards in-flight personal data', async () => {
  let now=0, child; const manager = new DiscoveryManager({now:()=>now,spawn:()=>{child=new EventEmitter();child.send=()=>{};child.kill=()=>{};return child;}});
  manager.setTarget({host:'example'}); manager.state('recent'); await tick(); child.emit('message',{ok:true,data:{items:[{title:'Example'}]}}); await tick();
  assert.equal(manager.state('recent').status,'ready'); now=300001; assert.equal(manager.state('recent').refreshing,true); await tick();
  manager.setTarget(null); child.emit('message',{ok:true,data:{items:[{title:'Personal'}]}}); await tick();
  assert.equal(manager.cache.size,0); assert.equal(manager.state('recent').status,'unavailable');
});
test('worker deadline terminates a hung reader and leaves the controller responsive', async () => {
  let killed=false; const manager=new DiscoveryManager({timeoutMs:5,spawn:()=>{const child=new EventEmitter();child.send=()=>{};child.kill=()=>{killed=true};return child;}});
  manager.setTarget({host:'example'}); manager.state('daily'); await manager.tail;
  assert.equal(killed,true); assert.equal(manager.state('daily').status,'unavailable');
});
test('public data replaces private artwork URLs with bounded keys and validates image origins',()=>{
  const manager=new DiscoveryManager();manager.setTarget({host:'example',httpPort:9330});
  const publicData=manager.decorate({items:[{kind:'album',id:'123',title:'Title',artist:'Artist',object_ref:'internal',artwork:{url:'broker:///image/example.__ROON_IMAGE_SIZE__.jpg'}}]});
  assert.equal(publicData.items[0].object_ref,undefined);assert.equal(publicData.items[0].artwork,undefined);
  assert.equal(publicData.items[0].key.length,24);assert.equal(manager.imageUrl(publicData.items[0].artwork_key),'http://example:9330/image/example.256.jpg');
  assert.equal(manager.imageUrl(publicData.items[0].artwork_key,480),'http://example:9330/image/example.480.jpg');assert.equal(manager.imageUrl(publicData.items[0].artwork_key,99999),'http://example:9330/image/example.256.jpg');
  manager.images.set('unsafe','https://example.com/private');assert.equal(manager.imageUrl('unsafe'),null);
  manager.images.set('invalid','https://[');assert.equal(manager.imageUrl('invalid'),null);
  assert.equal(manager.imageUrl('unregistered'),null);
});
test('obsolete queued pages are skipped per client, without cancelling another device',async()=>{
  const manager=new DiscoveryManager();manager.setTarget({host:'example'});const calls=[];
  manager.run=async(_target,section)=>{calls.push(section);return {status:'ready',items:[]};};
  manager.state('daily','','phone');manager.state('daily','','touch');manager.state('releases','','phone');manager.state('added','','phone');
  await manager.tail;assert.deepEqual(calls,['daily','added']);assert.equal(manager.pending.size,0);
});
test('Discover session interests and caches remain bounded',()=>{const manager=new DiscoveryManager();manager.setTarget({host:'example'});manager.actionBusy=true;for(let i=0;i<100;i++)manager.state('recent','',`client-${i}`);assert.equal(manager.interests.size,64);assert.throws(()=>manager.state('recent','','invalid session'),/Invalid/);});
test('Daily home progressively combines mixes and recommendations',()=>{
  const manager=new DiscoveryManager();manager.setTarget({host:'example'});manager.actionBusy=true;
  manager.cache.set('daily:',{status:'ready',items:[{title:'Mix'}],expires:99});
  let home=manager.home('touch');assert.equal(home.status,'ready');assert.equal(home.items.length,1);assert.deepEqual(home.groups,[]);assert.equal(home.refreshing,true);
  manager.cache.set('picks:',{status:'ready',items:[],groups:[{seed:{title:'Seed'},items:[]}],expires:99});
  home=manager.home('touch');assert.equal(home.groups.length,1);assert.equal(home.refreshing,false);
});
test('leaving Daily drops its queued recommendation work instead of delaying the selected page',async()=>{
  const manager=new DiscoveryManager();manager.setTarget({host:'example'});const calls=[];
  manager.run=async(_target,section)=>{calls.push(section);return {status:'ready',items:[]};};
  manager.home('touch');manager.state('releases','','touch');
  await manager.tail;assert.deepEqual(calls,['releases']);
});
test('track actions resolve only an exact cached mix track and use the selected zone',async()=>{
  const manager=new DiscoveryManager();manager.setTarget({coreId:'core',host:'example'});manager.cache.set('mix:aabb',{items:[{kind:'track',key:'1234567890abcdef12345678',title:'Song',artist:'Artist',album:'Album'}]});
  let call;manager.run=async(target,section,id,extra)=>(call={target,section,id,extra},{accepted:true,action:extra.action});
  const result=await manager.trackAction('1234567890abcdef12345678','1234567890abcdef1234567890abcdef1234','queue','1234567890abcdef');
  assert.equal(result.accepted,true);assert.equal(call.section,'track-action');assert.equal(call.id,'aabb');assert.equal(call.extra.action,'queue');assert.equal(call.extra.track.title,'Song');
  await assert.rejects(()=>manager.trackAction('abcdefabcdefabcdefabcdef','1234567890abcdef1234567890abcdef1234','play','abcdefabcdefabcd'),/no longer available/);
});
