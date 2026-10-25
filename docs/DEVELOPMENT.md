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

## Commands

Run the fast suite after ordinary code changes:

```sh
tools/check fast
```

Render one native screen across every supported viewport while iterating:

```sh
tools/check screen settings
tools/check screen discover
```

Use `all` before accepting a group of layout changes:

```sh
tools/check screen all
```

Screenshots and a review gallery are written below
`dist/native-review/<screen>/index.html`. The Alpine GTK test image is cached locally;
packages are not downloaded again for every viewport.

Before pushing a release candidate, run:

```sh
tools/check candidate
```

This adds deterministic updater, appliance and setup smoke tests without
constructing a disk image. It does not replace physical acceptance for touch,
rotation, brightness, DSI or audio.

The complete image factory remains available on ARM64 Linux:

```sh
tools/check image
```

Use it for stable releases, provisioning/boot/package changes, or an explicit
fresh-image test—not for routine source-only beta UI changes.

## Supported displays

`tools/viewports.json` is the single authoritative screen matrix. Local checks,
GTK allocation tests and GitHub verification all read this file. Do not copy
the dimensions into another workflow or script.

## Release sequence

1. Keep iterative changes local.
2. Run the affected targeted screen check and inspect the gallery.
3. Commit the candidate locally once the related work is complete.
4. Run `tools/check candidate` against that exact commit, then push it once.
5. Dispatch Alpine verification once for the same commit. Leave
   `build_image` disabled for a source-only beta.
6. Publish only after the exact commit passes.

GitHub's baseline workflow remains a quick independent test on pushes. The
manual Alpine workflow performs the native release gate. A full disk-image job
runs only when `build_image` is explicitly selected.
