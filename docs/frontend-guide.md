# Architecture: Frontend Guide

`frontend/template.html` is the single-file D3 explorer. `build_site.py`
inlines one subject's data into it to produce `dist/<slug>.html`. This
page documents its three views and the mechanics that tie them together.

## Layout

The page is a header (title, entity-type legend, the view switcher,
search, reset), a main area that swaps between the three views below, and
an always-visible timeline strip along the bottom — the timeline is not
one of the switchable views; it stays on screen no matter which of the
three you're looking at, since it's the one element common to all of
them.

## Network view

The default view: a force-directed graph (`d3.forceSimulation`) of every
entity, with edges deduplicated per unordered pair (parallel relations
between the same two entities collapse into one visual link, listing all
of them on hover/click).

- **Node size** scales with graph degree, capped, with a larger fixed
  size for any person with a [verified portrait](data-accuracy.md#portraits).
- **Node color** follows entity type via the categorical palette:
  person (blue), place (aqua/green), organization (orange), artifact
  (violet).
- **Label decluttering**: only "hub" nodes (degree ≥ 2, or with a
  portrait) show their name by default; others reveal on hover or when
  selected — the same principle the [Map view](#map-view) uses, adapted
  for its own zoom behavior.
- **Legend** (top right) toggles each entity type's nodes and their edges
  on/off.

## Map view

Plots every `place` entity that carries `attributes.lat`/`attributes.lng`
(see [Data model reference](data-model.md#entities) and
[Data Accuracy & Provenance](data-accuracy.md#place-coordinates)) on a
world map, using an embedded, pre-converted GeoJSON basemap — no tile
server, no runtime map-library dependency beyond D3 itself.

- **Marker size** scales with how many events happened at that place plus
  its graph degree — see the formula in
  [Data Accuracy & Provenance](data-accuracy.md), or just: busier places
  get bigger circles.
- **The journey line** — a faint dashed path connecting places in the
  order the subject's story visits them chronologically (by each place's
  earliest located event).
- **Every label is permanently visible**, not hover-only. A small
  layout pass tries each marker's label at 8 compass positions and up to
  3 ring distances around its pin, taking the first spot that doesn't
  collide with an already-placed label or another marker (bigger/more-
  connected places claim their preferred spot first). A thin leader line
  is drawn whenever a label had to move off its default slot, so it's
  still clear which pin a displaced label belongs to.
- **Markers stay a constant screen size while zooming** — they live in a
  layer separate from the zoomed map geometry, with their screen position
  recomputed from the zoom transform on every tick. This is what lets a
  crowded cluster (e.g. several nearby cities) visibly spread apart, and
  its labels re-resolve, as you zoom in — rather than the cluster staying
  just as crowded relative to its own labels at every zoom level.

## Milestones view

A scrollable, chronologically-sorted reel of "big moment" event types:
`company_founded`, `invention`, `patent_filed`, `patent_granted`,
`product_launch`, `public_demonstration`, `publication`, `award`. Each
card shows a small hand-drawn icon colored by its timeline lane (see
below), the date, location if known, and a short description.

## The timeline

A zoomable/pannable horizontal strip (`d3.zoom` with a
`translateExtent`/`extent` locked to the timeline's own bounds) showing
every event as a mark, positioned by `date.sort_start`/`sort_end` and
grouped into five **semantic swimlanes** — every `event_type` belongs to
exactly one lane, and the lane's color *is* the color of every mark in
it, so row position and color reinforce the same grouping rather than
being two separate encodings to decode:

| Lane | Color | Event types |
|---|---|---|
| Life | blue | birth, death, education, retirement |
| Career & organizations | orange | employment_start/end, role_change, company_founded/sold/renamed |
| Inventions & process | violet | invention, patent_filed/granted, product_launch, other |
| Travel & gatherings | green | visit, meeting, relocation, conference, public_demonstration |
| Publications & recognition | gold | publication, award |

A `range`-precision event renders as a bar spanning its bounds rather
than a point.

## Selection state, shared across every view

Clicking an entity, an event, a place marker, or a milestone card all
funnel into the same two functions, `selectEntity(id)` /
`selectEvent(id)`, which:

1. Populate the right-hand side panel with details, connections, and
   source citations.
2. Dim everything *not* related to the selection — in the network graph,
   the map, the milestones list, and the timeline **simultaneously**,
   even in views you aren't currently looking at.
3. Highlight what *is* related.

This is why switching from, say, the Milestones view (having selected an
event there) back to the Network view shows that event's participants
already highlighted — state isn't per-view, it's global.

## Design tokens

Colors are CSS custom properties defined once in `:root` and referenced
by role throughout — see the reference palette in
[Data Accuracy & Provenance](data-accuracy.md#the-color-palette) for how
they were chosen and validated. Swapping the visual theme means editing
those variables in one place, not hunting through the rendering code.
