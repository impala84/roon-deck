'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {KefRoonControl} = require('./kef-control');
function fixture() {
  const output = {output_id:'kef', source_controls:[{status:'standby',supports_standby:true}], volume:{type:'number',min:0,max:100,value:28,is_muted:false}};
  const calls=[];
  const transport = {
    convenience_switch(o,opts,done) {calls.push(['wake',o.output_id]);output.source_controls[0].status='selected';done(false);},
    standby(o,opts,done) {calls.push(['standby',o.output_id]);output.source_controls[0].status='standby';done(false);},
    change_volume(o,mode,value,done) {calls.push(['volume',o.output_id,value]);output.volume.value=value;done(false);},
    mute(o,mode,done) {calls.push(['mute',o.output_id,mode]);output.volume.is_muted=mode==='mute';done(false);},
  };
  const control = new KefRoonControl({zones:()=>[{outputs:[output]}],transport:()=>transport,delay:async()=>{}});
  return {control,output,transport,calls};
}
test('a speaker Roon can no longer read a volume from is reported as off',()=>{
  const {control,output}=fixture(); output.source_controls[0].status='selected';
  assert.equal(control.status('kef').powered,true);
  delete output.volume; const off=control.status('kef');
  assert.equal(off.powered,false); assert.equal(off.volume,null);
});
test('wake and standby target the saved output without starting playback',async()=>{
  const {control,calls}=fixture();
  assert.equal((await control.command('kef','input','wifi',50)).input,'wifi');
  assert.equal((await control.command('kef','power',false,50)).powered,false);
  assert.deepEqual(calls,[['wake','kef'],['standby','kef']]);
});
test('never fall back to another available room or guess a physical input',async()=>{
  const {control,calls}=fixture();
  await assert.rejects(control.command('missing','power',true,50),/unavailable/);
  await assert.rejects(control.command('kef','input','aux',50),/direct speaker/);
  assert.deepEqual(calls,[]);
});
test('volume is bounded and mute readback is confirmed',async()=>{
  const {control,output}=fixture();
  assert.equal((await control.command('kef','volume_delta',50,40)).volume,40);
  assert.equal((await control.command('kef','mute',null,40)).muted,true);
  output.volume.type='db';
  await assert.rejects(control.command('kef','volume',20,40),/device-volume/);
});
test('an acknowledgement without a subscription change is not success or a repeated write',async()=>{
  const {control,transport,calls}=fixture();
  transport.convenience_switch=(o,opts,done)=>{calls.push('write');done(false);};
  await assert.rejects(control.command('kef','power',true,50),/not confirmed/);
  assert.deepEqual(calls,['write']);
});
