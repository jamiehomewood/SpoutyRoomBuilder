# Room Builder

Build a scenario room in the browser, render it in Blender as full-quality 360° panoramas, and keep the results in a
library that anyone using this PC can reuse.

## Start it

Double-click **start-roombuilder.bat**. It starts the server and opens http://localhost:8030/ in your browser.
Leave the black window open while you work: renders run from it.

Needs: Windows Python 3 (any recent version, standard library only) and Blender (found automatically in
`C:\Program Files\Blender Foundation\`, or set the path in **Settings**).

## What's where

| Folder / file | What it is |
| --- | --- |
| `builder/` | The builder page, the live 360 page (`live.html`) and the library viewer (`pano.html`) |
| `generator/generate.py` | The Blender script that turns a room spec into the panoramas |
| `catalogue/models/<id>/` | The model library: the model files plus `model.json` (status, notes, licence record) |
| `library/<id>/` | Finished rooms: `view_<name>.png/.jpg`, `credits.md`, `spec.json`, `room.blend` |
| `rooms/` | Rooms you saved with **Save** (the spec only) |
| `presets/finishes.json` | Finish types, colour palettes, conditions and what each room type starts with |
| `textures/patterns/` | Wallpaper / carpet pattern masks (own work, made by `tools/make_patterns.py`) |
| `presets/rooms.json` | The physical rooms. Add the other rooms here once measured (or use **Save this size as a room**) |
| `examples/` | Example specs (the Glenda room) |
| `jobs/` | The render queue, logs and the speed figures used for time estimates |
| `config.json` | Blender path, Sketchfab token, network setting (made on first run) |
| `tools/seed_catalogue.py` | Copies the Poly Haven models from the Glenda project into the library |

## Using it

1. **Room**: pick a physical room or type a custom size (it must match the room the render will play in), then the room type
   (home / hospital / court / custody / outdoor), the **condition** and the light (day / dusk / night).
   **Finishes**: walls (paint, wallpaper, tiles, blockwork, brick, panelling, bare plaster), lower walls (panelling, tiles,
   two-tone paint or paper up to a dado rail), floor (carpet, wood, laminate, vinyl, lino, tiles, resin, concrete), ceiling
   and skirting/coving, each with its own colours and options. The room type fills in its usual finishes; change any of them.
   **Condition** (new / lived-in / worn / neglected / derelict) ages whatever finishes you chose: scuffs, grime, yellowing,
   damp stains, peeling, worn and stained floors. A neglected or derelict home also gets the run-down fittings (bare bulb,
   nets, dated kitchen).
2. **Walls**: give any wall its own finish (a feature wall, a tiled wall) under **Wall finishes**, and any alcove its own. Add alcoves, doors, windows, arches (to a kitchen or an empty room) and kitchenettes. These are built
   beyond the real walls, so deep furniture can stand in them without covering the projected floor.
3. **Models**: add models from the library (room-tested ones first), or find more on Poly Haven / Sketchfab and import them.
   Drag them in Plan view; **R** rotates, **Back to wall** pushes one against the nearest wall facing into the room.
   A red outline and the warning box mean a model reaches onto the projected floor.
   **Outside** (Room tab): every window and outside door looks out on a real 360° photo from Poly Haven (CC0), which
   also lights the room. Pick garden, street, hospital grounds, car park or upper floor; day / dusk / night follows the
   Light setting, and **Turn the view** swings it round until the right part shows through the windows. Photos download
   once into `textures/hdri/` (about 100 MB each at full quality).
   **Windows** can have blinds, curtains, nets + curtains or frosted glass. **Doors** open onto a corridor that suits the
   style (a ward corridor for hospital, a hallway with a front door for homes), straight outside, a dark corridor, or stay shut.
4. **Views**: "centre" is where students stand. Add more (e.g. looking into the kitchen) for extra tablet buttons.
5. **Render**: pick the quality, check the time estimate and press **Render this room**. Keep working while it renders.
6. **Library**: view the result in 360°, download the PNG/JPG with its credits, show it in IglooPreview through Spouty
   (the "Raw" link), or open it as a copy to make a variant.

**See it in the room while editing:** give Spouty `http://localhost:8030/builder/live.html` (4096 × 2048). It shows a plain
version of the room you're editing and updates as you change it.

## Licences

- Poly Haven models and outside photos (HDRIs) are CC0: no credit needed, but they are listed in `credits.md`.
- Sketchfab: only CC0 and CC-BY models can be searched for and imported (the server refuses anything else). A CC-BY model
  needs a credit to the author and Sketchfab wherever the images are used: it is saved with the model and written into
  each room's `credits.md`, which is included in every download.
- BlenderKit models are not used by Room Builder: BlenderKit's terms don't allow their assets in other tools.

## Setting up from the repo

The repo holds the code, presets, examples, room textures and the model library's records (`model.json` + thumbnail).
These stay on the PC only and are not in the repo:

- `config.json`: made on first run (Blender path, your Sketchfab token). Never commit it.
- `library/` (finished renders), `jobs/` (queue and logs), `rooms/` (saved specs).
- `textures/hdri/`: the outside photos. They download again automatically the first time a room needs them.
- The model files (`.glb`) in `catalogue/models/`. To get them back on a new PC:
  - Own models (`rb_*`: ward, court, custody, park): `blender -b --factory-startup -P tools\make_ward_models.py`
  - Poly Haven models from the Glenda project: `python tools\seed_catalogue.py`
  - Anything imported from Poly Haven / Sketchfab in the builder: import it again from the Models tab (the record says where it came from).

## The room spec

A room is one JSON file (see `examples/glenda_modern.json`). Metres; origin at the centre of the physical room on the
floor; x = east, y = north. A feature's `pos` is its centre along its wall (x for north/south walls, y for east/west).
Item `rot` is in degrees: 0 faces south (into the room from the north wall), 180 north, 90 east, -90 west.
View `yaw` is a compass bearing for the centre of the panorama (0 = north).

Render one from the command line without the server:

    blender -b --factory-startup -P generator\generate.py -- examples\glenda_modern.json out draft
