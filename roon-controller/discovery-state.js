'use strict';
const {fork} = require('node:child_process');
const path = require('node:path');
const {createHash} = require('node:crypto');
class DiscoveryManager {
  constructor({spawn = fork, now = Date.now, timeoutMs = 20000} = {}) {
    this.spawn = spawn; this.now = now; this.timeoutMs = timeoutMs;
    this.target = null; this.cache = new Map(); this.pending = new Map(); this.tail = Promise.resolve(); this.child = null; this.images = new Map();
    this.actions = new Map(); this.actionBusy = false;
    this.interests = new Map(); this.activeKey = null;
  }
  setTarget(target) {
    if (JSON.stringify(target) === JSON.stringify(this.target)) return;
    this.target = target; this.cache.clear(); this.images.clear(); this.pending.clear(); this.interests.clear(); this.child?.kill();
  }
  rememberInterest(client, keys) {
    if (!client) return;
    if (!/^[\w-]{1,80}$/.test(client)) throw new Error('Invalid Discover session');
    this.interests.set(client,{keys:new Set(keys),at:this.now()});
    while(this.interests.size>64)this.interests.delete(this.interests.keys().next().value);
  }
  state(section, id = '', client = '', keepInterest = false) {
    if (!['recent', 'added', 'daily', 'picks', 'releases', 'mix'].includes(section)) throw new Error('Unknown Discover section');
    if (section === 'mix' && (!/^[a-f0-9]{2,160}$/i.test(id) || id.length % 2)) throw new Error('Invalid mix reference');
    if (!this.target) return {status: 'unavailable', message: 'Connect and authorise Roon to use Discover.', items: []};
    const key = `${section}:${id}`; const cached = this.cache.get(key);
    if (client && !keepInterest) this.rememberInterest(client,[key]);
    const wanted = () => !client || [...this.interests.values()].some(value=>value.keys?.has(key) && this.now()-value.at<60000);
    if ((!cached || cached.expires <= this.now()) && !this.actionBusy && !this.pending.has(key) && this.pending.size < 4) {
      const target = this.target;
      const job = this.tail.catch(() => {}).then(() => {
        if (target !== this.target || !wanted()) return null;
        this.activeKey = key;
        return this.run(target, section, id);
      }).then(data => {
        if (!data || target !== this.target) return;
        this.cache.set(key, {...this.decorate(data), expires: this.now() + (data.status === 'ready' ? 300000 : 60000)});
        while (this.cache.size > 24) this.cache.delete(this.cache.keys().next().value);
      }).finally(() => {if(this.activeKey===key)this.activeKey=null;if (this.pending.get(key) === job) this.pending.delete(key);});
      this.pending.set(key, job); this.tail = job;
    }
    if (cached) {const {expires, ...data} = cached; return {...data, refreshing: this.pending.has(key)};}
    return {status: 'loading', message: 'Loading…', items: []};
  }
  home(client = '') {
    if (client) this.rememberInterest(client,['daily:','picks:']);
    const mixes = this.state('daily', '', client, true);
    const picks = this.state('picks', '', client, true);
    const ready = mixes.status === 'ready' || picks.status === 'ready';
    if (!ready) {
      const unavailable = mixes.status === 'unavailable' && picks.status === 'unavailable';
      return {status: unavailable ? 'unavailable' : 'loading', message: unavailable ? 'Daily recommendations are unavailable.' : 'Loading…', items: [], groups: []};
    }
    return {
      status: 'ready', items: mixes.status === 'ready' ? mixes.items || [] : [], groups: picks.status === 'ready' ? picks.groups || [] : [],
      mixes_status: mixes.status, mixes_message: mixes.message || '',
      refreshing: mixes.status !== 'ready' || picks.status !== 'ready' || !!mixes.refreshing || !!picks.refreshing,
    };
  }
  decorate(data) {
    const visit = value => {
      if (!value || typeof value !== 'object') return value;
      if (Array.isArray(value)) return value.map(visit);
      const result = Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'artwork' && key !== 'object_ref').map(([key,v])=>[key, visit(v)]));
      if (value.kind && value.title) result.key = createHash('sha256').update(JSON.stringify([value.kind,value.id,value.title,value.artist,value.album,value.release_id])).digest('hex').slice(0,24);
      if (value.artwork?.url) {
        const key = createHash('sha256').update(value.artwork.url).digest('hex').slice(0,24);
        this.images.set(key,value.artwork.url); result.artwork_key=key;
        while(this.images.size>256) this.images.delete(this.images.keys().next().value);
      }
      return result;
    };
    return visit(data);
  }
  find(key) {
    for(const cached of this.cache.values()) {
      const items=[...(cached.items||[]),...(cached.groups||[]).flatMap(group=>group.items||[])];
      const match=items.find(item=>item.key===key); if(match)return match;
    }
    return null;
  }
  // size: the touchscreen's large Discover tiles ask for 480 or 640 instead of the default 256 thumbnail.
  imageUrl(key, size=256) {
    const url=this.images.get(key); if(!url||!this.target)return null;
    size=[256,480,640].includes(Number(size))?Number(size):256;
    if(/^broker:\/\/\/image\/[A-Za-z0-9_-]+\.__ROON_IMAGE_SIZE__\.jpg$/.test(url)) return `http://${this.target.host}:${this.target.httpPort||9330}/${url.slice('broker:///'.length).replace('__ROON_IMAGE_SIZE__',String(size))}`;
    try {const target=new URL(url); return target.protocol==='https:'&&target.hostname==='images.tidal.com'?url:null;} catch {return null;}
  }
  async mixAction(id,zoneId,action,nonce) {
    if(!this.target)throw Error('Roon is not connected');
    if(!/^[a-f0-9]{2,160}$/i.test(id||'')||id.length%2||!/^[a-f0-9]{36}$/i.test(zoneId||'')||!['play','queue'].includes(action)||!/^[a-zA-Z0-9-]{16,64}$/.test(nonce||''))throw Error('Invalid mix request');
    const identity=JSON.stringify([this.target.coreId,id,zoneId,action,nonce]);
    if(this.actions.has(identity))return this.actions.get(identity);
    if(this.actionBusy||this.pending.size)throw Error('Discover is busy. Wait for loading to finish.');
    const target=this.target; this.actionBusy=true;
    const job=this.run(target,'mix-action',id,{zoneId,action}).then(data=>{
      if(target!==this.target||!data.accepted)throw Error('The mix request could not be confirmed. Check the Roon queue before trying again.');
      return {accepted:true,count:data.count,action:data.action};
    }).finally(()=>{this.actionBusy=false;});
    this.actions.set(identity,job);while(this.actions.size>64)this.actions.delete(this.actions.keys().next().value);
    return job;
  }
  async trackAction(key,zoneId,action,nonce) {
    if(!this.target)throw Error('Roon is not connected');
    if(!/^[a-f0-9]{24}$/i.test(key||'')||!/^[a-f0-9]{36}$/i.test(zoneId||'')||!['play','queue'].includes(action)||!/^[a-zA-Z0-9-]{16,64}$/.test(nonce||''))throw Error('Invalid track request');
    let track=null,mixId='';
    for(const [cacheKey,cached] of this.cache){const match=(cached.items||[]).find(item=>item.key===key);if(match?.kind==='track'&&cacheKey.startsWith('mix:')){track=match;mixId=cacheKey.slice(4);break;}}
    if(!track||!mixId)throw Error('This mix track is no longer available');
    const identity=JSON.stringify([this.target.coreId,key,zoneId,action,nonce]);
    if(this.actions.has(identity))return this.actions.get(identity);
    if(this.actionBusy||this.pending.size)throw Error('Discover is busy. Wait for loading to finish.');
    const target=this.target;this.actionBusy=true;
    const job=this.run(target,'track-action',mixId,{zoneId,action,track}).then(data=>{if(target!==this.target||!data.accepted)throw Error('The track request could not be confirmed.');return {accepted:true,action:data.action};}).finally(()=>{this.actionBusy=false;});
    this.actions.set(identity,job);while(this.actions.size>64)this.actions.delete(this.actions.keys().next().value);return job;
  }
  run(target, section, id, extra={}) {
    return new Promise(resolve => {
      let child, timer, settled = false;
      const finish = result => {
        if (settled) return; settled = true; clearTimeout(timer);
        if (this.child === child) this.child = null;
        child?.kill(); resolve(result);
      };
      const unavailable = () => finish({status: 'unavailable', message: 'Discover could not reach Roon. Normal playback controls are unaffected.', items: []});
      try {
        child = this.spawn(path.join(__dirname, 'discovery-worker.js'), [], {execArgv: ['--max-old-space-size=128'], stdio: ['ignore', 'ignore', 'ignore', 'ipc'], env: {PATH: process.env.PATH}});
        this.child = child; timer = setTimeout(unavailable, this.timeoutMs);
        child.once('message', result => result?.ok ? finish({status: 'ready', ...result.data, updated_at: new Date(this.now()).toISOString()}) : unavailable());
        child.once('error', unavailable); child.once('exit', unavailable);
        child.send({...target, section, id, ...extra});
      } catch {unavailable();}
    });
  }
}
module.exports = {DiscoveryManager};
