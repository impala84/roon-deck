(() => {
  // A colour for each bus route, used on the Bus Times page and the Home bus tile. Stored as "40=blue, 42=green".
  const NAMES = ['blue', 'green', 'violet', 'amber', 'rose', 'teal'], DEFAULTS = {'40': 'blue', '42': 'green', '401': 'violet'};
  const SWATCH = {blue: '#55a9d7', green: '#61c68f', violet: '#a998e0', amber: '#d4a85f', rose: '#e07a95', teal: '#4fc3c0'};
  const form = document.querySelector('form'), services = document.querySelector('[name=services]'), store = document.querySelector('[name=service_colours]'), box = document.getElementById('route-colours');
  if (!services || !store || !box) return;
  const parse = text => Object.fromEntries(String(text || '').split(',').map(part => part.split('=').map(item => item.trim())).filter(([route, name]) => route && NAMES.includes((name || '').toLowerCase())).map(([route, name]) => [route, name.toLowerCase()]));
  const routes = () => services.value.split(',').map(item => item.trim()).filter(Boolean);
  let last = null;
  function draw() {
    const chosen = parse(store.value), list = routes();
    box.replaceChildren();
    if (!list.length) return;
    const title = document.createElement('small'); title.textContent = 'Route colours'; box.append(title);
    for (const route of list) {
      const row = document.createElement('label'), select = document.createElement('select'), dot = document.createElement('i');
      row.className = 'route-colour-row'; row.append(document.createTextNode(`Route ${route}`));
      for (const name of NAMES) { const option = document.createElement('option'); option.value = name; option.textContent = name[0].toUpperCase() + name.slice(1); select.append(option); }
      select.value = chosen[route] || DEFAULTS[route] || 'amber';
      dot.style.cssText = `display:inline-block;width:14px;height:14px;border-radius:50%;margin-right:8px;background:${SWATCH[select.value]}`;
      select.onchange = () => {
        dot.style.background = SWATCH[select.value];
        const next = {...parse(store.value)}; next[route] = select.value;
        store.value = Object.entries(next).filter(([key]) => routes().includes(key)).map(([key, name]) => `${key}=${name}`).join(', ');
        store.dispatchEvent(new Event('input', {bubbles: true})); store.dispatchEvent(new Event('change', {bubbles: true}));
      };
      row.prepend(dot); row.append(select); box.append(row);
    }
  }
  // The values arrive after the page loads and the services box can be edited, so redraw when either changes.
  setInterval(() => { const now = `${services.value}|${store.value}`; if (now !== last) { last = now; draw(); } }, 400);
})();
