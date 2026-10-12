window.RoonDeckContentFields = [
  ['hero.eyebrow', 'Hero', 'Eyebrow', '.hero-copy .eyebrow', true],
  ['hero.title', 'Hero', 'Main headline', '.hero-title-main'],
  ['hero.title_accent', 'Hero', 'Accent headline', '.hero-copy h1 > span:last-child'],
  ['hero.description', 'Hero', 'Description', '.hero-lede'],
  ['story.eyebrow', 'Why RoonDeck', 'Eyebrow', '.origin-story > .eyebrow', true],
  ['story.title', 'Why RoonDeck', 'Headline', '#origin-story-title'],
  ['story.paragraph_1', 'Why RoonDeck', 'First paragraph', '.origin-story-grid > div p:nth-child(1)'],
  ['story.paragraph_2', 'Why RoonDeck', 'Second paragraph', '.origin-story-grid > div p:nth-child(2)'],
  ['notice.label', 'Roon notice', 'Label', '.api-notice .notice-label', true],
  ['notice.title', 'Roon notice', 'Headline', '#api-notice-title'],
  ['music.title', 'Music browser', 'Headline', '#about .section-heading h2'],
  ['music.description', 'Music browser', 'Introduction', '#about .section-heading > p:last-child'],
  ['music.now.title', 'Music browser', 'Now Playing title', '#feature-tab-now strong'],
  ['music.now.description', 'Music browser', 'Now Playing description', '#feature-tab-now small'],
  ['music.browse.title', 'Music browser', 'Browse title', '#feature-tab-browse strong'],
  ['music.browse.description', 'Music browser', 'Browse description', '#feature-tab-browse small'],
  ['music.daily.title', 'Music browser', 'Daily title', '#feature-tab-daily strong'],
  ['music.daily.description', 'Music browser', 'Daily description', '#feature-tab-daily small'],
  ['music.surprise.title', 'Music browser', 'Surprise Me title', '#feature-tab-surprise strong'],
  ['music.surprise.description', 'Music browser', 'Surprise Me description', '#feature-tab-surprise small'],
  ['music.details.title', 'Music browser', 'Album details title', '#feature-tab-details strong'],
  ['music.details.description', 'Music browser', 'Album details description', '#feature-tab-details small'],
  ['music.orientation.title', 'Music browser', 'Orientation title', '#feature-tab-orientation strong'],
  ['music.orientation.description', 'Music browser', 'Orientation description', '#feature-tab-orientation small'],
  ['endpoints.eyebrow', 'Playback and endpoints', 'Eyebrow', '#endpoints .endpoint-intro .eyebrow', true],
  ['endpoints.title', 'Playback and endpoints', 'Headline', '#endpoints .endpoint-intro h2'],
  ['endpoints.description', 'Playback and endpoints', 'Introduction', '#endpoints .endpoint-intro > p:nth-of-type(2)'],
  ['endpoints.roon.title', 'Playback and endpoints', 'Roon Display title', '#endpoint-panel-roon h3'],
  ['endpoints.roon.description', 'Playback and endpoints', 'Roon Display description', '#endpoint-panel-roon p'],
  ['endpoints.bluos.title', 'Playback and endpoints', 'BluOS title', '#endpoint-panel-bluos h3'],
  ['endpoints.bluos.description', 'Playback and endpoints', 'BluOS description', '#endpoint-panel-bluos p'],
  ['endpoints.bridge.title', 'Playback and endpoints', 'Roon Bridge title', '#endpoint-panel-bridge h3'],
  ['endpoints.bridge.description', 'Playback and endpoints', 'Roon Bridge description', '#endpoint-panel-bridge p'],
  ['endpoints.airplay.title', 'Playback and endpoints', 'AirPlay title', '#endpoint-panel-airplay h3'],
  ['endpoints.airplay.description', 'Playback and endpoints', 'AirPlay description', '#endpoint-panel-airplay p'],
  ['extras.eyebrow', 'Beyond music', 'Eyebrow', '#beyond-music .section-heading .eyebrow', true],
  ['extras.title', 'Beyond music', 'Headline', '#beyond-music .section-heading h2'],
  ['extras.description', 'Beyond music', 'Introduction', '#beyond-music .section-heading > p:last-child'],
  ['extras.home.title', 'Beyond music', 'Home Assistant title', '.utility-list article:nth-child(1) h3 span'],
  ['extras.home.description', 'Beyond music', 'Home Assistant description', '.utility-list article:nth-child(1) p'],
  ['extras.netdata.title', 'Beyond music', 'Netdata title', '.utility-list article:nth-child(2) h3 span'],
  ['extras.netdata.description', 'Beyond music', 'Netdata description', '.utility-list article:nth-child(2) p'],
  ['extras.settings.title', 'Beyond music', 'Settings title', '.utility-list article:nth-child(3) h3'],
  ['extras.settings.description', 'Beyond music', 'Settings description', '.utility-list article:nth-child(3) p'],
  ['hardware.eyebrow', 'What you need', 'Eyebrow', '#what-you-need .section-heading .eyebrow', true],
  ['hardware.title', 'What you need', 'Headline', '.hardware-title-main'],
  ['hardware.title_accent', 'What you need', 'Accent headline', '#what-you-need .accent-line'],
  ['hardware.description', 'What you need', 'Introduction', '#what-you-need .section-heading > p:last-child'],
  ['hardware.optimised', 'What you need', 'Optimisation note', '#what-you-need .lean-note'],
  ['setup.eyebrow', 'Get started', 'Eyebrow', '#get-started .section-heading .eyebrow', true],
  ['setup.title', 'Get started', 'Headline', '#get-started .section-heading h2'],
  ['setup.description', 'Get started', 'Introduction', '#get-started .section-heading > p:last-child'],
  ['setup.download.title', 'Get started', 'Download heading', '#get-started .install-steps li:nth-child(1) h3'],
  ['setup.flash.title', 'Get started', 'Flash heading', '#get-started .install-steps li:nth-child(2) h3'],
  ['setup.connect.title', 'Get started', 'Hardware heading', '#get-started .install-steps li:nth-child(3) h3'],
  ['setup.complete.title', 'Get started', 'Setup heading', '#get-started .install-steps li:nth-child(4) h3'],
  ['setup.complete.description', 'Get started', 'Setup instructions', '#get-started .install-steps li:nth-child(4) p'],
  ['setup.roon.title', 'Get started', 'Connect Roon heading', '#get-started .install-steps li:nth-child(5) h3'],
  ['feedback.eyebrow', 'Feedback form', 'Eyebrow', '#feedback .feedback-copy .eyebrow', true],
  ['feedback.title', 'Feedback form', 'Headline', '#feedback .feedback-copy h2'],
  ['feedback.description', 'Feedback form', 'Introduction', '#feedback .feedback-copy > p:last-child'],
  ['footer.tagline', 'Footer', 'Tagline', '.footer-project p:nth-of-type(1)'],
  ['footer.story', 'Footer', 'Project note', '.footer-project p:nth-of-type(2)']
].map(([key, section, label, selector, optional = false]) => ({key, section, label, selector, optional}));

window.applyRoonDeckContent = async function applyRoonDeckContent(root = document) {
  try {
    const response = await fetch('/api/content');
    if (!response.ok) return;
    const {content = {}} = await response.json();
    for (const field of window.RoonDeckContentFields) {
      if (!Object.hasOwn(content, field.key)) continue;
      const element = root.querySelector(field.selector);
      if (element) {
        element.textContent = content[field.key];
        if (field.optional) element.hidden = !content[field.key].trim();
      }
    }
  } catch {
    // The checked-in page copy remains the reliable fallback.
  }
};
