'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'static',name),'utf8');
function element(tag){return {tag,attributes:{},children:[],setAttribute(key,value){this.attributes[key]=value;},replaceChildren(...children){this.children=children;}};}
const helpers=vm.runInNewContext(read('discovery.js')+'\n({loadingNotice,responsiveLabel})',{document:{createElement:element}});
test('all pending music navigation uses one discreet accessible loading notice',()=>{
  const status=helpers.loadingNotice();assert.equal(status.textContent,'Loading…');assert.equal(status.className,'loading-notice');assert.equal(status.attributes.role,'status');assert.equal(status.attributes['aria-live'],'polite');
  assert.match(read('app.js'),/list\.append\(loadingNotice\(\)\)/);
  assert.doesNotMatch(read('discovery.js'),/Loading your (mix|Roon recommendations)/);
});
test('responsive labels replace rather than accumulate and retain full and compact names',()=>{
  const link=element('a');for(let i=0;i<3;i++)helpers.responsiveLabel(link,'Now Playing','Playing');
  assert.equal(link.children.length,2);assert.equal(link.children[0].className,'nav-label-full');assert.equal(link.children[0].textContent,'Now Playing');assert.equal(link.children[1].textContent,'Playing');
  assert.match(read('discovery.js'),/\['daily','DAILY','DAILY'\]/);assert.match(read('discovery.js'),/\['surprise','SURPRISE ME','SURPRISE ME'\]/);
});
test('mix tracks remain visible and portrait layout uses horizontal categories with normal-flow Back',()=>{
  assert.doesNotMatch(read('discovery.js'),/createElement\('details'\)|VIEW TRACKS/);
  const css=read('discovery.css');assert.match(css,/\.discovery-view>\.browser-back\{position:static/);
  assert.match(css,/#dashboard-clock\{display:none/);assert.match(css,/\.browser-sidebar\{grid-column:1\/-1;grid-row:1;flex-direction:row/);
});
test('source display uses the selected player or zone name, not the protocol brand',()=>{
  const source=read('app.js'),start=source.indexOf('function sourcePlayerName('),end=source.indexOf('\nfunction renderAmplifier',start);
  const name=vm.runInNewContext(source.slice(start,end)+';sourcePlayerName');assert.equal(name({player:{name:'NAD M33'}},{name:'Living room'}),'NAD M33');assert.equal(name({}, {name:'Living room'}),'Living room');assert.equal(name({},null),'Player');assert.match(read('index.html'),/id="source-zone"/);
});
test('disabled BluOS never exposes saved input selections',()=>{
  const source=fs.readFileSync(path.join(__dirname,'server.js'),'utf8');
  assert.match(source,/if \(!config\.enabled\) return \{enabled: false, connected: false, status: 'Disabled', player: null, inputs: \[\], active_input: null/);
});
test('Recent modes and optional recommendations have restorable URLs and shared desktop typography',()=>{
  assert.match(read('discovery.js'),/Recently Listened/);assert.match(read('discovery.js'),/Recently Added/);assert.match(read('discovery.js'),/FOR YOU/);assert.match(read('app.js'),/params.get\('view'\)==='picks'/);assert.match(read('discovery.css'),/@media\(min-width:901px\)\{#music-nav button,#discover-nav button\{font-size:14px/);
});
test('Daily pages expose every tile in one arrow-free horizontal swipe track',()=>{
  const panel=element('panel');panel.append=(...items)=>panel.children.push(...items);panel.scrollTop=0;
  const create=tag=>{const node=element(tag);node.append=(...items)=>node.children.push(...items);node.classList={add:()=>{}};return node;};
  const context={document:{createElement:create},$:()=>panel};
  vm.createContext(context);vm.runInContext(read('discovery.js')+'; discoveryTab="daily"; discoveryCard=item=>item;',context);
  context.data={status:'ready',items:[1,2,3,4,5]};vm.runInContext('renderDiscover(data)',context);
  const section=panel.children[0],grid=section.children[0];
  assert.deepEqual(Array.from(grid.children),[1,2,3,4,5]);
  assert.equal(section.children.length,1);
  assert.doesNotMatch(read('discovery.js'),/PREVIOUS|NEXT|daily-pager/);
  assert.match(read('discovery.css'),/\.daily-grid\{display:flex;gap:22px;overflow-x:auto/);
});
test('bottom navigation uses equal grid columns when Bus Times is disabled',()=>{
  const css=read('discovery.css');
  assert.match(css,/\.web-nav:has\(a\[hidden\]\)\{grid-template-columns:repeat\(3,minmax\(0,1fr\)\)!important\}/);
  assert.doesNotMatch(css,/\.web-nav:has\(a\[hidden\]\)\{display:flex\}/);
});
