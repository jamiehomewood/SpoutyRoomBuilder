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
   **Kitchen**: unit style (matt, satin, gloss or wood) and colour, worktop (white quartz, black granite, oak, laminate in any
   colour, stainless steel), splashback (tiles, coloured glass or the wall finish), its own floor or the room's, and appliances.
2. **Walls**: give any wall its own finish (a feature wall, a tiled wall) under **Wall finishes**, and any alcove its own. Add alcoves, doors, windows, arches (to a kitchen or an empty room) and kitchenettes. These are built
   beyond the real walls, so deep furniture can stand in them without covering the projected floor.
3. **Models**: add models from the library (room-tested ones first), or find more on Poly Haven / Sketchfab and import them.
   Drag them in Plan view; **R** rotates, **Back to wall** pushes one against the nearest wall facing into the room.
   A model dragged over a table, bed or worktop sits on it; **Height** lifts it to any height (e.g. a camera on the wall),
   **Put on what's below** and **On the floor** set it back down.
   **Decals** (Models tab > Decals): drawings, graffiti, posters, signs and damage (mould, damp, cracks) stuck on any wall,
   the back of an alcove or the floor. Click one, then click where it goes in 3D or Eye view; sliders set position, size,
   turn and opacity. **Add your own image** (PNG with a transparent background, or JPG) with its real width and licence;
   the licence goes into each render's credits. The starter set is own work, made by `tools/make_decals.py`.
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

**Haunted room (scare layer):** render a room twice, once with the lights on and once with `"lights_on": false` (see
`examples/halloween_flat.json` and `halloween_flat_dark.json`), then give Spouty (or an ICE web layer in
the room) `http://localhost:8030/builder/halloween.html?lit=<library id>&dark=<library id>`. It starts by itself. If a
browser holds the sound back, any click or key press starts it (in Spouty and ICE it plays straight away);
`&autostart=0` brings back a click-to-start screen. It plays an 8-minute loop of flickers, blackouts, lightning (with a figure at the
window), creaks, groans, door slams, footsteps, whispers, a lunging pumpkin, spiders, bats, a ghost, and a hole that opens in
the floor with something in it when the lights go out. Keys: 1 pumpkin, 2 spider, 3 ghost, 4 door, 5 lightning, 6 groan,
7 blackout, 8 swarm, 9 bats, 0 whisper, F flicker, J floor hole, C haunting (shakes, light turns green / red / violet /
blue), R rocking chair (it also rocks by itself every 25–50 s), K knock, A auto on/off, M mute, H help. Items marked `"live": true` in a spec are left out of the render and drawn
live by the page (the rocking chair). The ghost, hanging spider and pumpkin face appear just in front of the
walls (so they land on the projected walls at life size); bats wheel round in front of the walls, between 0.3 m and 2.1 m up (the ceiling is not projected). Add `&cycle=300` for a
5-minute loop, `&hud=0` to hide the help, `&demo=1` for every scare in under 2 minutes, `&look=1` for a flat camera view
that turns to each scare (for screen recordings). Flashes stay under 3 a second.

**Haunted room without a server:** `node tools/make_halloween_standalone.mjs <lit id> <dark id> Halloween_Room.html`
(needs Node and `npm i esbuild` once) makes one file with everything inside it, the two renders included. Copy that one
file to any PC and open it, or point an ICE web layer at it: no Python, no server, no Spouty. It shows the walls only for
hiding effects (no furniture models), which makes no visible difference.

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
