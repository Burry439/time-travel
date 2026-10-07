# Brief for Codex: four missing item pictures (D-72)

Four things in the village have no picture, so the game draws a grey "?" in their place. The player saw one at
Hessa's trough from the first minute. Paint the four pictures below. That is the whole task.

## Scope (strict)

- Create only the four PNG files listed below. Nothing else.
- Don't edit any code, JSON, scene, import file or document. Don't run any tool or script, don't use the image API,
  and don't touch `backend/.env`. No git: no commits, branches, stashes or resets.
- Godot makes the `.png.import` files itself when the project next opens. Don't write them.

## Style

Match the existing loose-thing pictures in `assets/generated/materials/`. Look at these first:
- `boards_lane.png` and `yard_elm_planks.png` for wood;
- `yard_horn.png` for horn and leather;
- `steel_file.png` for worked iron.

They are:
- painted, slightly stylised, muted earthy colours, soft light from the top left;
- seen from a three-quarter view above, the thing alone;
- on a fully transparent background, trimmed close, with no shadow, ground, frame or text;
- RGBA PNG, about 256 px on the longest side (for example 256 × 247).

## The four files

1. `assets/generated/materials/trough_boards.png`: **rotten boards by the trough spout.** Two short, soft,
   blackened wooden boards lying side by side, wet-dark and crumbling at the ends, with green-black rot and a
   little moss. A small dead thing (a rat's tail and hind foot) shows from under one edge, grim but not gory.
   About 6 kg of wood: two boards, each roughly a forearm long.
2. `assets/generated/materials/aldos_horn.png`: **battered signal horn.** A cow-horn signal horn, pale and
   yellowed at the mouth, darker toward the tip, on a cracked brown leather carrying strap. A capital "A" is
   scratched into the rim. Old and well used, with scuffs and a chip at the bell.
3. `assets/generated/materials/tongs_mara.png`: **smith's tongs, broken.** A blacksmith's iron tongs, about
   50 cm long, dark forged iron with hammer marks. One jaw is snapped clean off, so one side ends in a bright,
   jagged break.
4. `assets/generated/materials/survival_book.png`: **survival notes.** A small, thick pocket notebook, closed,
   in a worn dark-brown leather cover with soft rounded corners, held shut by a cord wound round it. A few dog-eared
   page edges show. Plain: no title, no lettering. It should read as a personal, much-handled notebook, a little
   out of place in this world.

## When you're done

Say in one line which files you made. Claude then imports them in Godot, takes them off `AWAITING_ART` in
`backend/tests/test_content.py`, and checks them in the game.
