// Shared spacing, section grouping and outline icons for web Settings.
(() => {
const icons={
 roon:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/>',
 bluos:'<rect x="5" y="2" width="14" height="20" rx="2"/><circle cx="12" cy="15" r="4"/><circle cx="12" cy="6" r="1"/>',
 bus:'<rect x="4" y="3" width="16" height="16" rx="3"/><path d="M4 11h16M8 19v2m8-2v2M8 15h1m6 0h1M8 6h8"/>',
 home:'<path d="M3 10l9-7 9 7v11H3zM9 21v-8h6v8"/>',
 overview:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 services:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h10M7 15h4m6-3v6m-3-3h6"/>',
 automation:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 display:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
 controls:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
 network:'<rect x="8" y="3" width="8" height="5" rx="1"/><path d="M12 8v5M5 13h14M5 13v3m14-3v3"/><rect x="2" y="16" width="6" height="5" rx="1"/><rect x="16" y="16" width="6" height="5" rx="1"/>',
 ethernet:'<path d="M5 9V4h14v5M8 4v5m4-5v5m4-5v5M4 9h16v9h-5v3H9v-3H4z"/>',
 wifi:'<path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0m-11 4a6 6 0 0 1 8 0"/><circle cx="12" cy="20" r="1"/>',
 vpn:'<path d="M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="M8 12l3 3 5-6"/>',
 software:'<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
 system:'<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
 preview:'<rect x="2" y="3" width="20" height="15" rx="2"/><path d="M8 22h8m-4-4v4M10 7l6 3.5-6 3.5z"/>'
};
function icon(name){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');svg.innerHTML=icons[name]||icons.system;return svg;}
document.querySelectorAll('[data-tab]').forEach(button=>{const label=document.createElement('span');label.textContent=button.textContent;button.replaceChildren(icon(button.dataset.tab),label);});
document.querySelectorAll('[data-service-tab]').forEach(button=>{const label=document.createElement('span');label.textContent=button.textContent;button.replaceChildren(icon(button.dataset.serviceTab),label);});
document.querySelectorAll('[data-mode-icon]').forEach(button=>{const label=document.createElement('span');label.className='mode-label';label.textContent=button.textContent;button.replaceChildren(icon(button.dataset.modeIcon),label);});
document.querySelectorAll('[data-icon]').forEach(node=>node.append(icon(node.dataset.icon)));
// Direct headings become flat grid groups; existing form IDs and ownership stay intact.
for(const root of document.querySelectorAll('.display-panel,#panel-automation,#system-services,.service-panel:not([data-service-panel="roon"]),.integration-panel')){
 const nodes=[...root.childNodes];let group=null,grid=null;
 for(const node of nodes){
  if(node.nodeType===1&&node.tagName==='H3'){
   if(!grid){grid=document.createElement('div');grid.className='settings-grid';root.insertBefore(grid,node);}
   group=document.createElement('div');group.className='settings-group';grid.append(group);
  }
  if(group)group.append(node);
 }
 for(const group of root.querySelectorAll('.settings-group'))if(group.querySelectorAll(':scope>label').length<2)group.classList.add('single-field');
}
// Keep help with its field, so two-column rows remain aligned.
for(const group of document.querySelectorAll('.settings-group,#vpn-section>div:not(.accessory-actions)')){
 for(const label of group.querySelectorAll(':scope>label:not(.check)'))if(label.nextElementSibling?.tagName==='SMALL')label.append(label.nextElementSibling);
}
// Pack groups into a regular eight-pixel grid without leaving gaps beneath short groups.
const groupSizes=new ResizeObserver(entries=>{for(const {target} of entries){const height=target.getBoundingClientRect().height;if(height>0)target.style.gridRowEnd='span '+Math.ceil((height+28)/8);}});
document.querySelectorAll('.settings-group').forEach(group=>groupSizes.observe(group));
const menu=document.querySelector('.mobile-menu-button'),aside=document.querySelector('.admin-sidebar'),save=document.getElementById('save-bar'),small=matchMedia('(max-width:800px)');
function closeMenu(){document.body.classList.remove('menu-open');menu.setAttribute('aria-expanded','false');}
menu.addEventListener('click',()=>{const open=!document.body.classList.contains('menu-open');document.body.classList.toggle('menu-open',open);menu.setAttribute('aria-expanded',String(open));});
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',closeMenu));
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('menu-open')){closeMenu();menu.focus();}});
document.addEventListener('click',event=>{if(document.body.classList.contains('menu-open')&&!aside.contains(event.target)&&!menu.contains(event.target))closeMenu();});
function responsive(){closeMenu();(small.matches?document.body:aside).append(save);document.getElementById('settings-navigation').setAttribute('aria-orientation','vertical');}
new ResizeObserver(()=>{document.body.style.setProperty('--save-footer-height',(small.matches?save.getBoundingClientRect().height:0)+'px');}).observe(save);
small.addEventListener('change',responsive);responsive();
})();
