# Getting Started

## Requirements

- Python 3.8+
- The [`jsonschema`](https://pypi.org/project/jsonschema/) package (the
  only dependency — used to validate a subject's data before building)
- Any modern browser to open the built page in

No Node.js, no npm install, no server. D3 is loaded from a CDN by the
built page itself at view time.

## Install

```bash
pip install jsonschema --break-system-packages
```

!!! note
    `--break-system-packages` is only needed on systems where pip refuses
    a global install by default (e.g. recent Debian/Ubuntu). Drop it if
    you're using a virtualenv.

Schema validation is optional but strongly recommended — without
`jsonschema` installed, `build_site.py` will still build the page, but it
skips every structural and referential-integrity check and just prints a
warning.

## Quick start: build the example subject

The repository ships one worked example, `subjects/suntola/`, extracted
from a real paper on the invention of Atomic Layer Epitaxy. Build it:

```bash
python3 scripts/build_site.py suntola
```

Expected output:

```
Building 'suntola'...
  67 entities, 42 events, 50 relations
  -> dist/suntola.html
```

Then open `dist/suntola.html` in any browser — double-click it, or:

```bash
python3 -m webbrowser dist/suntola.html   # or just open it from your file manager
```

## What you'll see

The page opens on the **Network** view: a force-directed graph of every
person, place, organization, and invention in the subject's life, with a
chronological timeline strip along the bottom.

- **Click any node** (a person, place, organization, or invention) to see
  its connections and its slice of the timeline in the side panel.
- **Click any timeline event** to see its participants and its source
  citation.
- **Drag to pan, scroll to zoom** the graph; the same works on the
  timeline for zooming into a date range.
- **Use the legend** (top right) to toggle entity types on or off.
- **Switch views** with the Network / Map / Milestones control in the
  header — the [Map](frontend-guide.md#map-view) plots every geocoded
  place on a world map, and [Milestones](frontend-guide.md#milestones-view)
  is a scrollable reel of the subject's inventions, patents, publications,
  and awards. All three views and the timeline share selection state, so
  clicking anything anywhere highlights it consistently everywhere.
- **Search** by name in the header search box, or reset the whole view
  with the Reset button.

## Building every subject at once

```bash
python3 scripts/build_site.py --all
```

This builds every subject folder under `subjects/` (skipping any
directory whose name starts with `_`, such as `subjects/_bridges/`) and
writes each one to `dist/<slug>.html`.

## Next steps

- [Usage Guide](usage.md) covers the build script's validation behavior
  and error output in more detail.
- [Adding a new subject](adding-a-subject.md) walks through extracting a
  second biography from a new source paper, end to end.
- [Data model reference](data-model.md) documents exactly what goes in
  each of the four JSON files.
