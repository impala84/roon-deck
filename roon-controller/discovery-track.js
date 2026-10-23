'use strict';
const {field,resolve,list,item}=require('./discovery-model');

const normal=value=>String(value||'').normalize('NFKC').trim().toLocaleLowerCase();

async function playMixTrack(client,sdk,{id,zoneId,action,track}) {
  if(!/^[a-f0-9]{2,160}$/i.test(id||'')||id.length%2||!/^[a-f0-9]{36}$/i.test(zoneId||'')||!['play','queue'].includes(action)||track?.kind!=='track')throw Error('Invalid track action');
  const zones=[...client.graph.objects.values()].filter(object=>/\.Zone$/.test(object.typeName)&&Buffer.isBuffer(field(object,'ZoneId'))&&field(object,'ZoneId').toString('hex')===zoneId.toLowerCase());
  if(zones.length!==1)throw Error('The selected Roon zone could not be matched safely');
  const {Arg,buildArgs}=sdk,ns='Sooloos.Broker.Api';
  const mixResult=await client.remoting.callMethod(client.serviceOid('Library'),`${ns}.Library::GetMix(System.Sooid, Base.ResultCallback<${ns}.Mix>)`,buildArgs([Arg.sooid(Buffer.from(id,'hex'))]));
  if(!mixResult.success)throw Error('The mix is unavailable');
  const mixReference=client.graph.decodeReturnValue(Uint8Array.from(mixResult.payload));
  const mix=resolve(client.graph,mixReference);
  if(!mixReference?.$ref||!mix||!Buffer.isBuffer(field(mix,'MixId'))||field(mix,'MixId').toString('hex')!==id.toLowerCase())throw Error('The mix identity could not be verified');
  const tracksResult=await client.remoting.callMethod(BigInt(mixReference.$ref),`${ns}.Mix::GetItems(Base.ResultCallback<${ns}.DataList<${ns}.MixItem>>)`,Buffer.alloc(0));
  if(!tracksResult.success)throw Error('The mix track list could not be loaded');
  const root=client.graph.decodeReturnValue(Uint8Array.from(tracksResult.payload));
  const candidates=list(client.graph,root,20).flatMap(group=>list(client.graph,field(group,'Tracks'),20)).filter(Boolean);
  const matches=candidates.filter(candidate=>{const value=item(client.graph,candidate,'track');return value&&normal(value.title)===normal(track.title)&&normal(value.artist)===normal(track.artist)&&normal(value.album)===normal(track.album)&&(track.roon_id?String(value.roon_id)===String(track.roon_id):track.id?String(value.id)===String(track.id):true);});
  if(matches.length!==1)throw Error('The selected mix track could not be matched safely');
  const type=`${ns}.PlayParameters`;
  const parameters=client.structArg(type,[{name:`${ns}.PlayPriority ${type}::Priority`,propType:9,value:buildArgs([Arg.enum_(action==='play'?0:4)])},{name:`bool ${type}::Shuffle`,propType:2,value:buildArgs([Arg.bool(false)])}]);
  const result=await client.remoting.callMethod(client.serviceOid('Transport'),`${ns}.Transport::PlayTrack(${ns}.Zone, System.Sooid, ${type}, ${ns}.TrackBase, Base.ResultCallback<${ns}.PlayFeedback>)`,Buffer.concat([buildArgs([Arg.ref(zones[0].oid),Arg.sooid(client.profile())]),parameters,buildArgs([Arg.ref(matches[0].oid)])]));
  if(!result.success)throw Error('Roon did not confirm the track request');
  return {accepted:true,action};
}
module.exports={playMixTrack};
