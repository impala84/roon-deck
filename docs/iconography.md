# RoonDeck icon family

`tools/build_icons.py` is the single editable catalogue. Run it after changing a
path; `--check` and the unit suite verify committed outputs. No icon dependency.
All vectors use a 64-unit viewBox, 2-unit monoline stroke, rounded caps/joins,
`currentColor` and no background fills. Optically sized geometry leaves room
for each silhouette, rather than stretching every subject to identical bounds.

## Audit and migration

| Existing consumer | Family implementation |
| --- | --- |
| 21 genre placeholders | Bespoke reference concepts, including trumpet Blues, palm Reggae and Comedy |
| Browse menu/category/playlist placeholders | Album sleeve, performer, paired notes, three-track play symbol, magnifier |
| Previous/play/pause/next, Surprise refresh/play | Shared semantic SVGs in native and web adapters |
| Queue now-playing badge, play artist/mix and queue actions | Shared play/playlist symbols, replacing font triangles |
| Add-to-library, favourite | Add and heart; filled favourite is retained as a meaningful state exception |
| Settings cog | Shared cog on native and web screens |
| Home fan/light/switch | Shared monoline controls; existing colour, opacity and touch gestures retained |
| Missing artwork | Generated album/artist placeholders |
| Back, forward, overflow, status, brightness, orientation, Home/Bus/Discover | Catalogue ready for existing/future pictorial consumers; text-only controls remain text |

`native-display/icon_family.py` renders original SVG vectors as GTK images,
resolving CSS colour in each snapshot so theme and disabled/active states remain
inherited. It deliberately avoids symbolic masking, which previously filled SVG
holes. Texture caching avoids rerasterising unchanged icons. Web `icons.js` is
generated from the same catalogue, with a shared SVG/DOM component.

## Intentional preservation

The live analogue clock keeps its existing moving hands and outlined circle;
the full digital clock remains text. Text navigation, sliders, native checkboxes
and dropdown affordances remain native accessible widgets. Loading dots are an
animation, not a pictogram. Branding favicons remain unchanged. Layout, hit
targets, callbacks, labels and active/inactive colours are not redesigned.

Artwork loading placeholders deliberately retain the smaller neutral pre-upgrade
disc and person designs; these are distinct from Browse category symbols. Native
playback/library controls and the cog use a 3-unit optical stroke for touchscreen
legibility; genres and other family symbols retain the 2-unit base stroke.

Native screenshot fixtures cover four display dimensions and all 21 genres.
They are deterministic GTK renders, not proof of physical touchscreen gestures.
