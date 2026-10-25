# RoonDeck working expectations

## Publishing completed changes

The user expects requested RoonDeck changes to be delivered through the Pi's
updater (Settings → Software), not left as local edits. Do not ask for
publishing confirmation on every build: the user has authorised this routine
workflow, including direct pushes to the beta branch and GitHub prereleases.

### Where releases come from

- Current development is the Beta channel. Commit and push beta work to
  `hotfix/beta27-physical-baseline`. `main` was merged with the beta line on
  26 October 2026 and carries the same code plus the project website; the Pi
  installs tagged releases, not a branch. Bring `main` up to date with a normal
  merge (never a force-push) when the user asks.
- The Pi's Beta channel installs the newest published GitHub **prerelease** that
  is tagged `v1.1.7-beta.N` (releases up to beta.91 end in `-alpine`; the updater
  accepts both), at that tag's exact commit. It does not require the Alpine
  verification workflow to pass (see `appliance/alpine/updater.py`).
- Stable is different: it requires a passing Alpine verification run and is
  released only when the user asks for a stable release.

### Steps for a beta release

1. Implement and verify the change locally (see the checks below).
2. Add a `## 1.1.7-beta.N Alpine — <date>` entry at the top of `CHANGELOG.md`
   (N is the next number; check `gh release list --repo impala84/roon-deck`).
3. Run `tools/release-beta` from the `hotfix/beta27-physical-baseline` branch.
   It bumps the version in every file, runs `tools/check fast`, commits,
   rebases onto the latest `origin/hotfix/beta27-physical-baseline`, pushes
   (never forced), publishes the prerelease with the changelog entry as its
   notes, and confirms it is listed. `tools/release-beta --dry-run` shows what
   it would do. Update affected web asset cache versions yourself first.

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
