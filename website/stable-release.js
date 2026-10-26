// Keep every displayed stable version in sync with GitHub's published stable release.
// The checked-in version remains visible if GitHub is unavailable or rate limited.
(async function updateStableReleaseVersion() {
  try {
    const response = await fetch('https://api.github.com/repos/impala84/roon-deck/releases/latest', {
      headers: {Accept: 'application/vnd.github+json'}
    });
    if (!response.ok) return;
    const release = await response.json();
    if (release.draft || release.prerelease) return;
    const match = /^v(\d+\.\d+\.\d+)(?:-alpine)?$/.exec(release.tag_name);
    if (!match) return;
    const version = match[1];
    document.querySelectorAll('[data-stable-version]').forEach((element) => {
      element.textContent = version;
    });
    document.querySelectorAll('[data-stable-download]').forEach((element) => {
      element.setAttribute('aria-label', `View RoonDeck stable release version ${version}`);
    });
  } catch {
    // Preserve the visible fallback version and working release links.
  }
})();
