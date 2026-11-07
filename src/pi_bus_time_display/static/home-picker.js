(() => {
  // Browse Home Assistant for the devices shown on the touchscreen Home page, instead of typing entity IDs.
  const LIMIT = 8;
  const textarea = document.querySelector('textarea[name="home_assistant_entities"]');
  if (!textarea) return;
  const label = textarea.closest('label');
  const box = document.createElement('div'); box.className = 'home-picker'; box.hidden = true;
  const chosen = document.createElement('ol'); chosen.className = 'home-picked';
  const count = document.createElement('small'); count.className = 'home-count';
  const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Search your Home Assistant devices'; search.autocomplete = 'off'; search.setAttribute('aria-label', 'Search Home Assistant');
  const results = document.createElement('ul'); results.className = 'home-results';
  box.append(chosen, count, search, results);
  label.before(box);
  let catalog = [], lastValue = null;

  const ids = () => textarea.value.split(',').map(item => item.trim()).filter(Boolean);
  const nameOf = id => catalog.find(item => item.entity_id === id)?.name || id;
  function write(list) {
    textarea.value = list.join(', '); lastValue = textarea.value;
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
    render();
  }
  function button(text, onclick, title) {
    const node = document.createElement('button'); node.type = 'button'; node.className = 'secondary home-mini'; node.textContent = text; if (title) node.setAttribute('aria-label', title); node.onclick = onclick; return node;
  }
  function render() {
    const list = ids();
    chosen.replaceChildren(...list.map((id, index) => {
      const item = document.createElement('li');
      const text = document.createElement('span'); text.className = 'home-name'; text.textContent = nameOf(id);
      const small = document.createElement('small'); small.textContent = id; text.append(small);
      item.append(text,
        button('↑', () => { if (index) { [list[index - 1], list[index]] = [list[index], list[index - 1]]; write(list); } }, `Move ${id} up`),
        button('↓', () => { if (index < list.length - 1) { [list[index + 1], list[index]] = [list[index], list[index + 1]]; write(list); } }, `Move ${id} down`),
        button('Remove', () => write(list.filter(other => other !== id)), `Remove ${id}`));
      return item;
    }));
    count.textContent = `${list.length} of ${LIMIT} shown on the touchscreen, in this order.`;
    const query = search.value.trim().toLowerCase();
    const matches = catalog.filter(item => !list.includes(item.entity_id) && (!query || item.name.toLowerCase().includes(query) || item.entity_id.includes(query))).slice(0, 40);
    results.replaceChildren(...matches.map(item => {
      const row = document.createElement('li');
      const text = document.createElement('span'); text.className = 'home-name'; text.textContent = item.name;
      const small = document.createElement('small'); small.textContent = item.entity_id; text.append(small);
      const add = button('Add', () => write([...ids(), item.entity_id]), `Add ${item.name}`); add.disabled = list.length >= LIMIT;
      row.append(text, add); return row;
    }));
  }
  search.oninput = render;
  async function load() {
    try {
      const response = await fetch('/api/admin/home-catalog', {cache: 'no-store'});
      if (!response.ok) throw new Error('unavailable');
      catalog = (await response.json()).entities || [];
    } catch (_) { catalog = []; }
    // With nothing to browse (no address or token yet), keep the plain text box so devices can still be typed.
    box.hidden = !catalog.length; label.hidden = !!catalog.length;
    lastValue = null; render();
  }
  setInterval(() => { if (textarea.value !== lastValue && !box.hidden) { lastValue = textarea.value; render(); } }, 500);
  // Re-load after the Home Assistant panel is opened or saved, so a freshly entered address starts working.
  document.addEventListener('click', event => { if (event.target.closest?.('[data-service-tab="home"], [data-save="home"]')) setTimeout(load, 1200); });
  load();
})();
