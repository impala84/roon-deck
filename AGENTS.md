# RoonDeck working expectations

## Publishing completed changes

The user expects requested RoonDeck changes to be delivered through the Pi's
updater (Settings → Software), not left as local edits. Do not ask for
publishing confirmation on every build: the user has authorised this routine
workflow, including direct pushes to the beta branch and GitHub prereleases.

### Where releases come from

- Current development is the Beta channel. Commit and push beta work to
  `main` (from 26 October 2026; before that it lived on
  `hotfix/beta27-physical-baseline`, which is now frozen at beta.116). `main`
  also carries the project website, and pushes to it deploy the site on Vercel.
  The Pi installs tagged releases, not a branch, so pushing alone changes
  nothing on a Pi until a release is published.
- The Pi's Beta channel installs the newest published GitHub **prerelease** that
  is tagged `vX.Y.Z-beta.N` (current development: `v1.1.8-beta.N`) (releases up to beta.91 end in `-alpine`; the updater
  accepts both), at that tag's exact commit. It does not require the Alpine
  verification workflow to pass (see `appliance/alpine/updater.py`).
- Stable is different: it requires a passing Alpine verification run and is
  released only when the user asks for a stable release.

### Steps for a beta release

1. Implement and verify the change locally (see the checks below).
2. Add a `## X.Y.Z-beta.N Alpine — <date>` entry at the top of `CHANGELOG.md`
   (N is the next number; check `gh release list --repo impala84/roon-deck`).
3. Run `tools/release-beta` from the `main` branch.
   It bumps the version in every file, runs `tools/check fast`, commits,
   rebases onto the latest `origin/main`, pushes
   (never forced), publishes the prerelease with the changelog entry as its
   notes, and confirms it is listed. `tools/release-beta --dry-run` shows what
   it would do. Update affected web asset cache versions yourself first.

Without a local checkout: pushing a commit to `main` that adds the next
`## X.Y.Z-beta.N Alpine` entry to `CHANGELOG.md` (with the version files bumped
in the same commit) makes the `Publish beta release` GitHub Action publish the
prerelease. Claude sessions cannot run `gh release`, so this is how they
release. `tools/release-beta` remains the way to do it from the user's computer.

### Limits

- Do not overwrite unrelated user changes, force-push, or publish known failing
  work. Report meaningful blockers or operations needing more authority.
- Publishing a release does not authorise remotely installing it or restarting
  the user's Pi.
- State verification accurately: local browser fixtures, Xvfb captures and
  automated tests do not prove native GTK behaviour on the actual touchscreen.
- Only one agent should edit the native layout at a time. Several tools have
  pushed to the beta branch at once; always rebase before pushing.

## Conserve GitHub Actions usage

GitHub-hosted runtime is limited. Do not use repeated pushes or GitHub Actions runs as the development loop for layout work.

- Run unit tests, native rendering, screenshot capture, and the complete supported screen-size matrix locally while developing.
- Keep intermediate fixes local. Consolidate related changes and push only after the local checks pass.
- Do not make a sequence of speculative CI-only commits to adjust screenshot geometry or workflow assertions. Reproduce and resolve those failures locally first.
- For an ordinary release, trigger GitHub Actions only once for the final release candidate. A second run is acceptable only when the first uncovers a failure that could not reasonably be reproduced locally.
- Do not rerun successful jobs, duplicate equivalent workflows, or run the full matrix merely to obtain screenshots that can be generated locally.
- Prefer one consolidated required workflow over multiple workflows that repeat setup, builds, or the same test suites.
- Before pushing, inspect workflow triggers and batch commits so a single release candidate does not cause avoidable runs.
- If a proposed change would materially increase GitHub Actions minutes, explain why and get the user's approval first.

Use the repository's local entry point instead of reconstructing checks by hand:

- `tools/check fast` for code and controller changes.
- `tools/check screen <settings|discover|all>` while developing native layouts.
- `tools/check candidate` before pushing a release candidate.
- `tools/check image` only for stable, boot/provisioning/package, or explicitly requested image work.

The viewport matrix lives only in `tools/viewports.json`. Do not duplicate it in
workflow YAML or another test. Inspect the relevant gallery below
`dist/native-review/` before
pushing layout work. See `docs/DEVELOPMENT.md` for the complete release sequence.

## Optional remote/accessory beta

1.1.8 adds optional features, disabled for existing installations. Hardware acceptance is required for Surface Dial input, reconnection, and actual Roon Bridge playback across WireGuard. A tunnel handshake is not audio acceptance. Preserve Roon Bridge and all saved custom Home colours. Follow docs/REMOTE-ACCESS-AND-DIAL.md; do not claim unperformed physical tests.
