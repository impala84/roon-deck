const authView = document.getElementById('auth-view');
const cmsView = document.getElementById('cms-view');
const loginPanel = document.getElementById('login-panel');
const setupPanel = document.getElementById('setup-panel');
const contentForm = document.getElementById('content-form');
let sessionUser = null;

async function request(url, options = {}) {
  const response = await fetch(url, {...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || 'Something went wrong.');
  return body;
}

function status(formOrElement, message, type = '') {
  const element = formOrElement.matches?.('.form-status') ? formOrElement : formOrElement.querySelector('.form-status');
  if (!element) return;
  element.className = `form-status ${type}`;
  element.textContent = message;
}

function showCms(user) {
  sessionUser = user;
  authView.hidden = true;
  cmsView.hidden = false;
  document.getElementById('account-email').textContent = user.email;
  document.querySelector('#account-form [name="email"]').value = user.email;
  loadContent();
}

async function initialise() {
  const token = new URLSearchParams(location.search).get('setup');
  if (token) {
    setupPanel.hidden = false;
    loginPanel.hidden = true;
    setupPanel.dataset.token = token;
    return;
  }
  try {
    const session = await request('/api/admin/session');
    if (session.authenticated) showCms(session.user);
  } catch (error) {
    status(document.getElementById('login-form'), error.message, 'error');
  }
}

document.getElementById('setup-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const data = Object.fromEntries(new FormData(form));
  if (data.password !== data.confirmation) return status(form, 'The passwords do not match.', 'error');
  button.disabled = true;
  status(form, 'Creating your account…');
  const handoff = setTimeout(() => location.replace('/admin'), 8000);
  try {
    await request('/api/admin/setup', {method: 'POST', body: JSON.stringify({token: setupPanel.dataset.token, password: data.password})});
    location.replace('/admin');
  } catch (error) { clearTimeout(handoff); status(form, error.message, 'error'); button.disabled = false; }
});

document.getElementById('login-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button[type="submit"]');
  button.disabled = true; status(form, 'Signing in…');
  const handoff = setTimeout(() => location.replace('/admin'), 8000);
  try { await request('/api/admin/login', {method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form)))}); location.replace('/admin'); }
  catch (error) { clearTimeout(handoff); status(form, error.message, 'error'); button.disabled = false; }
});

document.getElementById('logout-button').addEventListener('click', async () => { await request('/api/admin/logout', {method: 'POST', body: '{}'}); location.href = '/admin'; });

document.querySelectorAll('.nav-button').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.nav-button').forEach(item => item.classList.toggle('active', item === button));
  document.querySelectorAll('.cms-panel').forEach(panel => { panel.hidden = panel.id !== `${button.dataset.view}-view`; });
  if (button.dataset.view === 'feedback') loadFeedback();
}));

const previewPanel = document.querySelector('.preview-panel');
const previewViewport = document.querySelector('.preview-viewport');
const previewFrame = document.getElementById('site-preview');

function sizePreview() {
  const mobile = previewPanel.classList.contains('mobile-preview');
  const width = mobile ? 390 : 1024;
  const scale = mobile ? 1 : Math.min(1, previewViewport.clientWidth / width);
  previewFrame.style.width = `${width}px`;
  previewFrame.style.height = `${760 / scale}px`;
  previewFrame.style.left = mobile ? `${Math.max(0, (previewViewport.clientWidth - width) / 2)}px` : '0';
  previewFrame.style.transform = `scale(${scale})`;
}

document.querySelectorAll('[data-preview-mode]').forEach(button => button.addEventListener('click', () => {
  const mobile = button.dataset.previewMode === 'mobile';
  document.querySelectorAll('[data-preview-mode]').forEach(item => item.classList.toggle('active', item === button));
  previewPanel.classList.toggle('mobile-preview', mobile);
  previewPanel.classList.toggle('desktop-preview', !mobile);
  sizePreview();
}));

new ResizeObserver(sizePreview).observe(previewViewport);
sizePreview();

async function loadContent() {
  const [{content}, previewResponse] = await Promise.all([request('/api/admin/content'), fetch('/')]);
  const previewHtml = await previewResponse.text();
  const parsed = new DOMParser().parseFromString(previewHtml, 'text/html');
  const groups = new Map();
  for (const field of window.RoonDeckContentFields) {
    if (!groups.has(field.section)) groups.set(field.section, []);
    const fallback = parsed.querySelector(field.selector)?.textContent?.trim() || '';
    groups.get(field.section).push({...field, value: Object.hasOwn(content, field.key) ? content[field.key] : fallback});
  }
  contentForm.replaceChildren(...[...groups].map(([section, fields]) => {
    const group = document.createElement('section'); group.className = 'content-group';
    const heading = document.createElement('h2'); heading.textContent = section; group.append(heading);
    for (const field of fields) {
      const label = document.createElement('label'); label.className = 'content-field'; label.textContent = field.label;
      const input = document.createElement(field.value.length > 90 ? 'textarea' : 'input'); input.name = field.key; input.value = field.value; input.dataset.selector = field.selector; input.dataset.original = field.value;
      input.dataset.optional = field.optional ? 'true' : 'false';
      input.addEventListener('input', () => { try { const target = document.getElementById('site-preview').contentDocument.querySelector(field.selector); if (target) { target.textContent = input.value; if (field.optional) target.hidden = !input.value.trim(); } } catch {} });
      label.append(input); group.append(label);
    }
    return group;
  }));
  const imageGroup = document.createElement('section'); imageGroup.className = 'content-group hero-image-controls';
  const imageHeading = document.createElement('h2'); imageHeading.textContent = 'Hero image crop'; imageGroup.append(imageHeading);
  for (const field of window.RoonDeckHeroImageFields) {
    const saved = Object.hasOwn(content, field.key) ? Number(content[field.key]) : field.defaultValue;
    const value = Number.isFinite(saved) ? saved : field.defaultValue;
    const label = document.createElement('label'); label.className = 'content-field range-field';
    const caption = document.createElement('span'); caption.textContent = field.label;
    const output = document.createElement('output'); output.textContent = `${value}${field.unit}`;
    const input = document.createElement('input'); input.type = 'range'; input.name = field.key; input.min = field.min; input.max = field.max; input.value = value; input.dataset.original = String(value);
    input.addEventListener('input', () => {
      output.textContent = `${input.value}${field.unit}`;
      try { const image = document.getElementById('site-preview').contentDocument.querySelector('.hero-image'); if (image) image.style.setProperty(field.property, field.scale ? String(Number(input.value) / 100) : `${input.value}${field.unit}`); } catch {}
    });
    label.append(caption, output, input); imageGroup.append(label);
  }
  contentForm.prepend(imageGroup);
}

document.getElementById('save-content').addEventListener('click', async event => {
  const button = event.currentTarget; button.disabled = true;
  try {
    const changed = Object.fromEntries([...contentForm.elements].filter(input => input.name && input.value !== input.dataset.original).map(input => [input.name, input.value]));
    if (!Object.keys(changed).length) { status(document.getElementById('content-status'), 'There are no unsaved changes.'); return; }
    await request('/api/admin/content', {method: 'PUT', body: JSON.stringify({content: changed})});
    [...contentForm.elements].forEach(input => { if (input.name) input.dataset.original = input.value; });
    status(document.getElementById('content-status'), 'All page text has been saved.', 'success');
  } catch (error) { status(document.getElementById('content-status'), error.message, 'error'); }
  finally { button.disabled = false; }
});

async function loadFeedback() {
  const list = document.getElementById('feedback-list'); list.textContent = 'Loading…';
  try {
    const {feedback} = await request('/api/admin/feedback');
    if (!feedback.length) { list.textContent = 'No feedback yet.'; return; }
    list.replaceChildren(...feedback.map(item => {
      const article = document.createElement('article'); article.className = 'feedback-item';
      const header = document.createElement('header'); const title = document.createElement('h2'); title.textContent = item.category.replace('_', ' '); const time = document.createElement('time'); time.dateTime = item.created_at; time.textContent = new Date(item.created_at).toLocaleString(); header.append(title, time);
      const message = document.createElement('p'); message.className = 'message'; message.textContent = item.message;
      const meta = document.createElement('div'); meta.className = 'feedback-meta'; const reply = document.createElement(item.reply_email ? 'a' : 'span'); reply.textContent = item.reply_email || 'No reply email'; if (item.reply_email) reply.href = `mailto:${item.reply_email}`;
      const select = document.createElement('select'); select.className = 'status-select'; for (const value of ['new', 'read', 'resolved']) { const option = document.createElement('option'); option.value = value; option.textContent = value[0].toUpperCase() + value.slice(1); option.selected = value === item.status; select.append(option); }
      select.addEventListener('change', async () => { try { await request('/api/admin/feedback', {method: 'PUT', body: JSON.stringify({id: item.id, status: select.value})}); } catch (error) { status(document.getElementById('feedback-status'), error.message, 'error'); } });
      const actions = document.createElement('div'); actions.className = 'feedback-actions';
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'delete-button'; remove.textContent = 'Delete';
      remove.addEventListener('click', async () => {
        if (!confirm('Permanently delete this feedback message?')) return;
        remove.disabled = true;
        try { await request('/api/admin/feedback', {method: 'DELETE', body: JSON.stringify({id: item.id})}); article.remove(); }
        catch (error) { remove.disabled = false; status(document.getElementById('feedback-status'), error.message, 'error'); }
      });
      actions.append(select, remove); meta.append(reply, actions); article.append(header, message, meta); return article;
    }));
  } catch (error) { list.textContent = ''; status(document.getElementById('feedback-status'), error.message, 'error'); }
}

document.getElementById('refresh-feedback').addEventListener('click', loadFeedback);
document.getElementById('account-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget;
  try { await request('/api/admin/account', {method: 'PUT', body: JSON.stringify(Object.fromEntries(new FormData(form)))}); location.href = '/admin'; }
  catch (error) { status(form, error.message, 'error'); }
});

initialise();
