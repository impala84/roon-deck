const menuButton = document.querySelector('.menu-toggle');
const siteNav = document.querySelector('.site-nav');

const legacySections = {
  '#features': '#about',
  '#home': '#beyond-music',
  '#hardware': '#what-you-need',
  '#build': '#get-started',
};

if (legacySections[location.hash]) {
  history.replaceState(null, '', legacySections[location.hash]);
}

menuButton?.addEventListener('click', () => {
  const open = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!open));
  siteNav.classList.toggle('open', !open);
});

siteNav?.addEventListener('click', (event) => {
  if (!event.target.closest('a')) return;
  menuButton?.setAttribute('aria-expanded', 'false');
  siteNav.classList.remove('open');
});

const revealObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    entry.target.classList.add('visible');
    revealObserver.unobserve(entry.target);
  }
}, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });

document.querySelectorAll('.reveal').forEach((element) => revealObserver.observe(element));

const sections = [...document.querySelectorAll('main section[id]')];
const navLinks = [...document.querySelectorAll('.site-nav a')];

const navObserver = new IntersectionObserver((entries) => {
  const visible = entries
    .filter((entry) => entry.isIntersecting)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!visible) return;
  navLinks.forEach((link) => {
    const linkedSections = (link.dataset.sections || link.hash.slice(1)).split(/\s+/);
    link.classList.toggle('active', linkedSections.includes(visible.target.id));
  });
}, { rootMargin: '-25% 0px -60% 0px', threshold: [0, 0.2, 0.6] });

sections.forEach((section) => navObserver.observe(section));

const featureTabs = [...document.querySelectorAll('.feature-tab')];
const featurePanels = [...document.querySelectorAll('.feature-panel')];

function selectFeature(tab, focus = false) {
  featureTabs.forEach((candidate) => {
    const selected = candidate === tab;
    candidate.setAttribute('aria-selected', String(selected));
    candidate.tabIndex = selected ? 0 : -1;
  });
  featurePanels.forEach((panel) => {
    panel.hidden = panel.id !== tab.getAttribute('aria-controls');
  });
  if (focus) tab.focus();
}

featureTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectFeature(tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const backwards = event.key === 'ArrowUp' || event.key === 'ArrowLeft';
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? featureTabs.length - 1 : (index + (backwards ? -1 : 1) + featureTabs.length) % featureTabs.length;
    selectFeature(featureTabs[nextIndex], true);
  });
});

const endpointTabs = [...document.querySelectorAll('.endpoint-tab')];
const endpointPanels = [...document.querySelectorAll('.endpoint-panel')];

function selectEndpoint(tab, focus = false) {
  endpointTabs.forEach((candidate) => {
    const selected = candidate === tab;
    candidate.setAttribute('aria-selected', String(selected));
    candidate.tabIndex = selected ? 0 : -1;
  });
  endpointPanels.forEach((panel) => {
    panel.hidden = panel.id !== tab.getAttribute('aria-controls');
  });
  if (focus) tab.focus();
}

endpointTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectEndpoint(tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const backwards = event.key === 'ArrowUp' || event.key === 'ArrowLeft';
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? endpointTabs.length - 1 : (index + (backwards ? -1 : 1) + endpointTabs.length) % endpointTabs.length;
    selectEndpoint(endpointTabs[nextIndex], true);
  });
});

const feedbackForm = document.getElementById('feedback-form');
const feedbackStatus = document.getElementById('feedback-status');
const feedbackStartedAt = document.getElementById('feedback-started-at');
if (feedbackStartedAt) feedbackStartedAt.value = String(Date.now());

feedbackForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = feedbackForm.querySelector('button[type="submit"]');
  feedbackStatus.className = 'feedback-status';
  feedbackStatus.textContent = 'Sending…';
  button.disabled = true;
  try {
    const payload = Object.fromEntries(new FormData(feedbackForm));
    const response = await fetch('/api/feedback', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The message could not be sent.');
    feedbackForm.reset();
    feedbackStartedAt.value = String(Date.now());
    feedbackStatus.classList.add('success');
    feedbackStatus.textContent = 'Thanks—your message has been received.';
  } catch (error) {
    feedbackStatus.classList.add('error');
    feedbackStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
