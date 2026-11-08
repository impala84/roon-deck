# RoonDeck development workflow

RoonDeck uses one local-first verification entry point. GitHub Actions calls the
same commands and is the final release gate, not the layout-development loop.

## Prerequisites

- Python 3.11 or newer
- Node.js and npm
- Git
- A running local Linux container engine for native GTK and appliance checks

The native checks run Alpine Linux in an ARM64 container. On an ARM64 Mac this
does not require CPU emulation, but the Docker-compatible container engine must
be running.

## Select checks by the change

The beta.133 audit (9 November 2026) found that the old blanket candidate rule
was the main source of unnecessary work. `candidate` runs `fast`, every native
screen family at every viewport, then an ARM64 appliance build and its smoke
checks. The release helper and GitHub baseline each run `fast` again. The
previous instructions also required a manual Alpine run for every beta even
though native checks in that workflow are advisory and the beta updater does
not require Alpine verification.

Use this policy for future work:

| Change | During implementation | Final verification before a beta |
| --- | --- | --- |
| Documentation only | Read the edited text and links | `git diff --check`; no runtime tests or new beta solely for documentation |
| A default, label or small settings change | Relevant validation/serialization test; inspect the affected UI if visible | `fast` once; verify saving and reloading when persistence changed |
| Backend or Roon controller behaviour | Tests for the changed request, state transition or error path | `fast` once; exercise the affected API flow |
| Browser layout or Home builder | Use the affected browser flow, including save/reload for builder changes | `fast` once for code changes; no native screenshots unless touchscreen output also changed |
| Native page layout | Render that page at the affected viewport; inspect the screenshot | `fast` once; affected page across six viewports only for shared sizing, placement or responsive changes |
| Shared native CSS, navigation or display scaling | Representative small landscape and portrait views first | `fast` once; expand to all affected page families and viewports once |
| Updater, service, root helper or packaged dependencies | Relevant safety tests and error paths | `fast` once plus `appliance` when Alpine integration changed |
| Boot, provisioning, disk/storage or fresh-image dependencies | Relevant component checks | Fresh image build/verification when needed; actual boot/hardware acceptance for changed physical behaviour |
| Stable release or a broad cross-cutting change | Targeted checks while developing | Explicit `candidate` sweep; image verification for stable image releases |

A new test should protect a meaningful behaviour or failure path. Do not add
one just to restate a constant or mirror a simple implementation.

### Commands

```sh
# Final Python/controller/syntax suite; beta.133 took about 14 seconds for
# 610 Python tests (2 skipped), plus about 2 seconds for 168 controller tests.
tools/check fast

# One affected native page and viewport while developing:
tools/check screen listening touch-v1-landscape

# Expand only that page when responsive layout changed:
tools/check screen listening

# Alpine runtime/service/updater integration when the change requires it:
tools/check appliance

# Deliberate broad regression or image verification, not routine UI work:
tools/check candidate
tools/check image
```

`listening` covers KEF Home tiles; `settings` covers native settings/setup;
`discover` covers Discover. `layout` is a report-only allocation diagnostic and
is not included in `all`. There is no general Home screen target in this runner:
verify non-KEF Home changes with the relevant fixture or browser flow rather
than assuming `screen all` covers them.

Screenshots and galleries are under `dist/native-review/<screen>/`. Rendering
uses a cached Alpine/GTK container. Only those checks and appliance checks need
a running container engine. A full image build requires ARM64 Linux.

### Avoid repeating work

- Use targeted tests while editing; run the final fast suite once. The release
  helper already runs it, so do not run it immediately before the helper.
- Treat a passing result as valid until the code or dependency it covers changes.
  A documentation edit does not invalidate a screenshot or controller test.
- GitHub baseline is one independent check on the final push. Do not manually
  dispatch Alpine verification for an ordinary source-only beta.
- Build the container once per relevant dependency/runtime change and reuse the
  cached image. Do not rebuild a disk image to verify application source updates.
- Report pre-existing unrelated fixture failures separately. The beta.133 broad
  sweeps hit existing Discover tooltip/alignment assertions; those failures do
  not prove a KEF, bus tint or performance-profile regression. New or related
  failures still need investigation before publishing.
- Physical tests are for changed hardware behaviour, with the user's live-device
  authorization. Unit tests and screenshots do not prove audio, touch, wake,
  infrared reception, boot or display hardware behaviour.

## Supported displays

`tools/viewports.json` is the single authoritative screen matrix. Local checks,
GTK allocation tests and GitHub verification all read this file. Do not copy
the dimensions into another workflow or script.

## Release sequence

1. Keep iterative changes local and use the relevant row of the table above.
2. Finish the implementation; inspect affected UI and persistence/readback.
3. Run final checks once for the final code. `tools/release-beta` includes
   `fast`; connector-based publishing requires running it locally first.
4. Push the consolidated beta once and verify the published tag and baseline
   result. Do not add a blanket candidate or manual Alpine run.
5. Leave Pi installation separate from publishing; it requires authorization.

### Release tooling safeguards

- The beta publisher runs after a successful **push** baseline on `main`, checks
  out that run's exact commit and tags that commit. Failed runs and PR runs
  cannot publish. A changelog-only push also triggers baseline; other Markdown
  edits remain exempt. The publisher reuses the result rather than rerunning tests.
- `tools/release-beta` commits/rebases before its final `fast` run. If the rebase
  changes the release version or notes it stops for review. After pushing, it
  watches baseline and confirms the published tag resolves to the checked commit;
  it no longer creates a release independently.
- `appliance` contains runtime, updater and privilege checks without GTK visual
  assertions. `appliance-visual` runs the older GTK smoke checks separately using
  the existing appliance image. `candidate` runs safety checks before native
  rendering, so a Discover assertion cannot prevent safety checks from running.
- The manual Alpine workflow installs Pillow under Python 3.13, matching baseline.
- Old Discover tooltip/alignment fixtures still need a separate layout review.
  They have not been bypassed or silently marked passing.

## Resource priority

System → Device → Performance priority switches between `playback` (the
existing modest Roon Bridge boost) and `dashboard` (prefer the display, API and
controller; return the Bridge to ordinary priority). The privileged Alpine
helper writes owned OpenRC overrides and adjusts existing worker threads and
OOM scores without restarting audio. It retains the selection in
`/var/lib/pi-home/performance-profile` and reapplies it on helper startup.
This is scheduling and memory-pressure protection, not fixed RAM allocation.
Operator-owned service overrides are preserved.
