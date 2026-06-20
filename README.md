# Ultimate Measure

A Glyphs 3 reporter plugin for live, Figma-style measurement in the Edit View:
stem/edge thickness and point-to-point X/Y distances. It draws only while you
hold **Option**, and what it shows depends on whether a single node is selected.

## Install

1. Quit Glyphs.
2. If an earlier copy is installed, trash it:
   `~/Library/Application Support/Glyphs 3/Plugins/UltimateMeasure.glyphsReporter`
   (and any older `UltimateThickness.glyphsReporter` or `ShowStemThicknessOption.glyphsReporter` if present).
3. Unzip and double-click `UltimateMeasure.glyphsReporter` (or copy it into
   that Plugins folder).
4. Launch Glyphs. If macOS blocks the bundled binary on first launch (only
   relevant when installed from a downloaded zip, not via Plugin Manager):
   `xattr -dr com.apple.quarantine "$HOME/Library/Application Support/Glyphs 3/Plugins/UltimateMeasure.glyphsReporter"`

## Use

Turn it on once in **View → Ultimate Measure**. Nothing shows until Option is
held.

### Nothing selected (or several nodes) — stem ruler

Hold Option and move near an outline. A perpendicular ray measures the stem or
edge under the cursor: a **pink** tag where the span crosses ink, **grey** across
a counter. The origin snaps to a nearby on-curve node (within ~10 px) and locks
to that node's curve normal, so it holds steady rather than wobbling.

At a **corner** the perpendicular is ambiguous, so it switches to axis legs: the
lengths of the *straight* segments meeting at that corner (curve legs are
skipped — the chord to the next point isn't useful), coloured **blue** for the
horizontal leg and **purple** for the vertical. Hovering just outside a corner,
or inside between features, snaps to the vertex instead of firing a diagonal.

**Option + Shift** — full slice: measure every gap across the outline along the
ray, not just the nearest stem.

Everything in this mode is measured on the *visible* outline: a cached,
overlap-removed, decomposed copy of the layer. So overlapping shapes and
components are handled, and overlap crossings behave as real corners.

### One node selected — X/Y to a hovered point

Select a node, hold Option, and hover any node, handle, **or overlap corner**
within ~10 px. It shows the horizontal (**blue, 003BFF**) and vertical (**purple,
8000FF**) distance from the selected node to that point, drawn as a right-angle
connector with the remaining two sides of the rectangle dashed. A leg that is
zero is omitted. (Selecting more than one node falls back to the stem ruler.)

### Hidden

**Option + Command** draws nothing — that combination is Glyphs' zoom gesture.

## Tuning

Constants at the top of `Contents/Resources/plugin.py`, in screen pixels unless
noted. Edit and restart Glyphs.

- `SNAP_PX` (10) — snap the ruler origin to a node within this of the cursor.
- `CATCH_PX` (10) — selection mode: catch a node/handle/overlap point this close.
- `VERTEX_TOL_PX` (3) — treat the nearest outline point as "on a vertex" within this.
- `CORNER_TURN_DEG` (20) — a snapped node sharper than this counts as a corner.
- `DOT_PX` (8) — endpoint dot size (uniform).
- `TAG_H` / `TAG_PAD` / `TAG_RADIUS` / `TAG_FONT` / `TAG_TEXT_DY` — tag geometry.
- `MIN_LEG` (0.5) — don't draw an X/Y leg shorter than this (em units).
- `MAX_SPAN` (2000) — ignore stem spans longer than this (em units).

## Notes

- Errors print to **Window → Macro Panel** with an `UltimateMeasure:` prefix.
- The overlap-removed copy is rebuilt only when the outline changes, so hovering
  stays cheap; very heavy glyphs may still cost a little on the first rebuild.

## Credits & licence

A Python port and substantial extension of **StemThickness** by Rafał Buchner,
with code samples by Georg Seifert, Rainer Scheichelbauer and Mark Frömberg.
<https://github.com/RafalBuchner/StemThickness> — the Python loader stub is from
the GlyphsSDK. Licensed under the Apache License 2.0, as the original.
