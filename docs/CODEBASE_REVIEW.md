# RoonDeck codebase review — 11 October 2026

## Executive assessment

The project has strong regression coverage and deliberate safety boundaries,
but several modules and verification scripts have accumulated too many
responsibilities. The immediate priority is shortening the feedback loop, not a
large rewrite. Refactoring should proceed behind the existing tests in small,
behaviour-preserving slices.

## Current strengths

- 305 Python and 123 controller tests execute in roughly four seconds locally.
- Privileged system actions, updater staging and application rollback have
  dedicated tests.
- Native GTK allocation checks cover both orientations and multiple physical
  display classes.
- The appliance build is explicit about what container validation cannot prove
  on physical Raspberry Pi hardware.
- JavaScript protocol/state modules generally keep tests beside their source.

## Priority findings

### 1. Native display is a monolith

`native-display/roondeck_native.py` is approximately 4,000 lines and contains app
startup, HTTP interaction, screen construction, responsive layout, artwork,
navigation, gesture handling and settings. Small layout changes consequently
touch a file with a very large behavioural surface.

Recommendation: extract one screen at a time, beginning with Settings because
it already has real allocation tests. Keep shared responsive primitives and
brand components separate from screen controllers. Do not redesign while
extracting.

### 2. Python server combines unrelated routes and services

`src/pi_bus_time_display/server.py` is approximately 1,500 lines. It mixes HTTP
routing, authentication/session behaviour, configuration, proxying, appliance
actions and page delivery.

Recommendation: retain one server entry point but move route groups into small
modules (`admin`, `roon_proxy`, `system_actions`, `static`). Add contract tests
before moving each group.

### 3. Alpine setup service has a wide privileged surface

`appliance/alpine/setup_service.py` is approximately 875 lines and coordinates
networking, credentials, services, display configuration and optional software.
Its tests are extensive, but the module is difficult to reason about as one
unit.

Recommendation: separate pure validation/state transitions from command
adapters. Preserve the existing fixed-command allow-list and completion lock.

### 4. Some tests assert source text rather than behaviour

Several regression tests search for exact strings in source or workflow YAML.
These are useful tripwires but make safe refactors unnecessarily expensive and
can pass without exercising runtime behaviour.

Recommendation: retain source assertions only for security invariants. Replace
layout and workflow-string checks with tests against parsed viewport data,
rendered allocations and command exit results.

### 5. Branding and static assets span several delivery surfaces

The project contains more than 100 static assets across the Python web GUI,
Roon controller, native display and public website. This makes brand updates
easy to apply inconsistently.

Recommendation: define a checked brand manifest listing the canonical source
SVG and every required generated destination. Validate hashes/dimensions in the
fast suite and generate raster derivatives through one script.

### 6. Internal `pi-home` compatibility names need an explicit policy

Runtime paths, service names and updater compatibility still use `pi-home`
while user-facing identity is RoonDeck. Renaming system identifiers casually
could break installed appliances.

Recommendation: document which identifiers are frozen compatibility contracts
and which may migrate. Change visible strings immediately; migrate service,
path and API identifiers only through an explicit backward-compatible release.

### 7. Release metadata is manually repeated

The application version appears in Python, TOML, npm metadata, visual fixtures,
README and changelog. Manual updates are error-prone even though a consistency
test covers some locations.

Recommendation: add one release-preparation command that updates every intended
location, refuses a dirty/unverified candidate and produces release notes. Keep
publishing as a separate explicit action.

### 8. Documentation has version and status drift

Some Alpine documentation describes older current releases and prototype
limitations that have since changed.

Recommendation: divide durable architecture from release status. Generate the
displayed current version from package metadata where practical, and review
hardware limitations at every stable release.

## Recommended sequence

1. Finish and adopt the local-first verification workflow.
2. Use it for at least one normal change and record actual timings.
3. Extract the Settings screen from the native monolith without changing UI.
4. Separate pure setup validation from privileged command execution.
5. Split server route groups.
6. Add the brand manifest and release-preparation command.
7. Reconcile durable documentation and compatibility identifiers.

Avoid a broad rewrite. Each extraction should leave the full fast suite and the
affected native viewport gallery unchanged before merging.
