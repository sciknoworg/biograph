# The frontend and visualisation — condensed brief for the WWW paper

Fourth companion to `approach-brief.md`, `harness-brief.md` and
`corpus-and-access-brief.md`. Self-contained: assumes no access to the repository. State at
commit `f52e741` (2026-09-29). Figures carry their denominators.

---

## 1. What it is

One HTML file per subject. `frontend/template.html` (921 lines) is a single-file D3 explorer;
`build_site.py` inlines that subject's graph as JSON and writes `dist/<slug>.html`.

- **No server, no build step, no framework.** One external dependency, D3 7.9.0 from a CDN.
- **No tile server.** The world basemap is a pre-converted GeoJSON embedded in the page.
- **240 pages, 478–564 KB each** (median 488 KB, 116 MB total). The embedded basemap is
  436 KB of that, so **~89% of every page is the map** and the biographical data itself is
  tens of kilobytes. That is the explicit cost of having no runtime map dependency: a page
  that works from a filesystem, offline, with no network calls after D3 loads, and that will
  still open in ten years.

For a WWW audience this is the deployment argument: **a knowledge graph that is readable
without infrastructure.** Archiving a subject means keeping one file.

## 2. Three views plus a persistent timeline

A header (title, entity-type legend, view switcher, search, reset), a main area that swaps
between **Network / Map / Milestones**, and a timeline strip along the bottom that is *not*
one of the switchable views — it stays on screen in all three, because it is the one element
common to every way of reading a life.

## 3. The central design argument: the visualisation does not flatten provenance

Every epistemic distinction the data model makes is visible in the rendering rather than
collapsed. This is the part of the frontend worth arguing in a paper, because it is what
makes the display honest about what is known.

**Two kinds of edge, drawn differently on purpose.**
- A **solid** line is a stated relation from `relations.json` — the source asserts it.
- A **faint dashed** line is *co-presence*: an event lists both entities among its
  participants (or as its location).

"The source says he worked at Bletchley Park" and "these two were named in the same event"
are not the same claim, and the graph must not pretend otherwise. Co-presence edges connect
each participant to the event's **principal** (the participant whose role names them its
subject, else the first listed) rather than to each other, so a ten-person event adds a star
rather than a 45-edge hairball.

**Measured, across all 233 subjects** — the share of a subject's entities that render as
isolated dots:

| | median | mean |
|---|---:|---:|
| relations only | **41.2%** | 39.9% |
| relations + event co-presence | **23.8%** | 23.5% |

So on a median subject, **roughly 17 points of the graph's connectivity lives in
`events.json` and is invisible if only relations are drawn.** Before this was added, two
entities in five appeared unconnected while the connection sat unread in the data.
*(`docs/frontend-guide.md` states this as 39%→22%; the re-measured figures at this commit are
the ones above. Cite these.)*

**Other provenance carried into the rendering:**
- A **verified portrait** gives a person a larger fixed node radius; an unverified identity
  gets no photo at all, so the visual prominence of a node is tied to whether identity was
  confirmed. 150 person entities across 137 of 233 subjects, of which 145 were confirmed by
  mechanical birth-year match and only 5 by model judgement.
- **Place coordinates** carry a `geocode_basis`, and a blank map is rendered as a blank map —
  never as a guess. 800 of 849 places resolved; **two thirds of pins are country-level**, so
  a map figure should be captioned as coverage, not as where work happened.
- **Citation-less links** are handled explicitly in the tooltip and sidebar rather than being
  shown as though sourced.

## 4. Network view

`d3.forceSimulation`, edges deduplicated per unordered pair (parallel relations between one
pair collapse into a single visual link that lists all of them on hover).

- **Node size** scales with graph degree, capped; a portrait overrides with a larger fixed
  radius.
- **Node colour** encodes entity type: person, place, organization, artifact.
- **Label decluttering** — only hub nodes (degree ≥ 2, or carrying a portrait) show their
  label by default; the rest reveal on hover or selection.
- **Legend toggles** each entity type's nodes *and their edges*.

## 5. Map view

Every `place` entity with coordinates, on the embedded basemap.

- **Markers stay a constant screen size while zooming.** They live in a layer separate from
  the zoomed geometry, with screen positions recomputed from the zoom transform each tick.
  This is what lets a crowded cluster genuinely spread apart as you zoom, instead of staying
  equally crowded relative to its own labels at every level.
- **Every label is permanently visible**, not hover-only. A layout pass tries each label at
  8 compass positions across up to 3 ring distances, taking the first that collides with
  nothing already placed; busier places claim their preferred spot first. A **leader line**
  is drawn whenever a label had to move off its default slot.
- **Marker size** scales with events-at-that-place plus graph degree.
- **The journey line** — a faint dashed path through places in the order the subject's story
  reaches them, ordered by each place's earliest located event.

## 6. Timeline

Zoomable and pannable, with the extent locked to the timeline's own bounds. Every event is a
mark positioned by `sort_start`/`sort_end`, in **five semantic swimlanes**:

| lane | event types |
|---|---|
| Life | birth, death, education, retirement |
| Career & organizations | employment_start/end, role_change, company_founded/sold/renamed |
| Inventions & process | invention, patent_filed/granted, product_launch, other |
| Travel & gatherings | visit, meeting, relocation, conference, public_demonstration |
| Publications & recognition | publication, award |

Every `event_type` belongs to exactly one lane, and **the lane's colour is the colour of
every mark in it** — row position and colour reinforce one grouping rather than being two
encodings to decode separately.

A `range`-precision event renders as a **bar spanning its bounds**, not a point. This is the
date model surfacing in the visual: 235 of 3,714 events are ranges, and 2,448 are
year-precision, so a timeline of this corpus is intrinsically a timeline of intervals.

## 7. Milestones view

A scrollable chronological reel of "big moment" event types — `company_founded`, `invention`,
`patent_filed`, `patent_granted`, `product_launch`, `public_demonstration`, `publication`,
`award` — each card carrying an icon coloured by its timeline lane, the date, the location if
known, and a short description.

## 8. Selection is global, not per-view

Clicking an entity, an event, a place marker or a milestone card funnels into the same two
functions. Each one: populates the side panel with details, connections and source citations;
**dims everything unrelated in the network, map, milestones and timeline simultaneously**,
including views not currently on screen; and highlights what is related.

So selecting an event in Milestones and switching to Network finds its participants already
highlighted. State is global rather than per-view, which is what makes the three views read as
one document instead of three tools.

## 9. Theming

Colours are CSS custom properties defined once on `:root` and referenced by role. Swapping
the visual theme means editing those variables in one place, not hunting through rendering
code. The categorical palette was chosen and validated for accessibility rather than picked
by eye.

## 10. Honest limitations

- **Degree-based node size is not importance.** A frequently-mentioned colleague outranks a
  pivotal but once-mentioned one. The encoding measures textual salience in one document, not
  historical significance.
- **Two thirds of map pins are country centroids**, so apparent geographic spread is coarser
  than it looks.
- **49 places are unmapped** and simply absent from the map view — mostly buildings and vague
  regions (`Oxford PV facility`, `Merchiston Campus`, `North of Sweden`) that are not
  gazetteer entries at all.
- **Co-presence edges are inferential**, which is why they are dashed and faint; a reader who
  ignores the visual distinction will over-read the graph.
- **One subject per page.** There is no cross-subject view, so the corpus cannot currently be
  browsed as a single network — a real limitation for anyone wanting to see the field rather
  than the person.
- **The 436 KB basemap is duplicated in all 240 pages.** Fine for archival, wasteful for a
  site.

## 11. Must not be claimed

- **That node size reflects importance.** It reflects degree.
- **That the map shows where work happened.** §3, §10.
- **That a solid and a dashed edge are the same kind of evidence.** The distinction is the
  point of drawing them differently.
- **"39% → 22%" for the isolation figure.** Use the re-measured 41.2% → 23.8% median (§3).

## 12. How to re-derive

```bash
python scripts/build_site.py <slug>          # rebuild one page
python scripts/build_site.py --all           # rebuild all 240
python scripts/geocode_places.py --review    # list every weakly-resolved pin
```

`docs/frontend-guide.md` is the long-form version of this brief and stays in the repository
for readers of the code rather than the paper.
