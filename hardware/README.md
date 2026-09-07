# Enclosure

Parametric OpenSCAD source for the table-centre case. Rendered with:

```bash
openscad -o display_cradle.stl -D 'part="cradle"' case/display_cradle.scad
openscad -o retainer.stl      -D 'part="retainer"' case/display_cradle.scad
openscad -o template.stl      -D 'part="template"' case/display_cradle.scad
```

STLs are **generated, not committed** — same rule as the card database. The
`.scad` files are the source of truth, and every dimension is a named parameter
at the top of the file, so a panel revision or a different tolerance is a
one-number change and a re-render.

## Where the numbers come from

The display figures are from the panel's own datasheet
(`7inch-DSI-Display_User_Manual-V1.1.pdf`, section 3), not measured:

| | |
|---|---|
| Module outline | 164.90 x 102.00 x 12.25 mm |
| Active area | 154.68 x 87.02 mm |
| Lens (glass) OD | 164.28 x 99.17 mm |
| Module mounting holes | 154.89 x 91.92 pattern, 5 mm in from each edge |
| Pi mounting holes | 58 x 49 (the Pi 5 pattern), on the panel's back |

## Two things that shaped the design

**The panel's own mounting holes can't hold it in.** They sit 5 mm in from the
edge, while the active area starts 5.11 mm in — so any lip reaching a hole
would be resting on live screen. The panel is trapped between the cradle's
window shoulder and a rear retainer instead, on screws that sit wholly outside
its footprint. That also keeps it tolerant of a panel revision moving a hole.

**The Pi hangs off the display, not off the case.** Per the manual the Pi bolts
to the panel's 58 x 49 holes on the supplied copper pillars and takes 5 V from
pogo pins through the header. So it's one sandwich, and the case only has to
hold the display; `rear_clearance` reserves depth for the board, its connectors
and the FPC ribbon's bend radius — the ribbon is the constraint, not the board.

## Before printing

Render the `template` part and print it **on paper at 100% scale**, then lay the
real panel on it. The panel is third-party and the drawing is the only source
for its dimensions; a sheet of paper is a cheap way to find out the drawing is
wrong, and a failed 4-hour print is not.
