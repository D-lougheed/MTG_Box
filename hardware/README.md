# Enclosure

The display sits on top of the printer rather than in a box around it. The
printer's top face is clear — USB, DC in, the power rocker and the label inflow
are all on the back — so a riser lifts the screen above it and the Pi lives in
the gap.

```
        display (164.9 x 102, screen up)
   ┌─────────────────────────────┐
   │  cradle + retainer          │  188.7 x 108.6 x 15
   ├─────────────────────────────┤
   │  riser  (Pi hangs in here)  │  42 tall, open all round
   ├─────────────────────────────┤
   │  printer  220 x 112 x 102   │  measured, not from the manual
   └─────────────────────────────┘        ~159 mm overall
```

The label roll hangs off an L-shaped arm bolted to the riser's back wall — part
of the same assembly, supported from one side only, so a roll slides on from the
free end and a cap screws over it. Anchors exist at both ends of that wall, so
the arm can go on whichever side suits; the arm itself is unhanded.

```bash
openscad -o cradle.stl   -D 'part="cradle"'   case/display_cradle.scad
openscad -o retainer.stl -D 'part="retainer"' case/display_cradle.scad
openscad -o riser.stl    -D 'part="riser"'    case/display_cradle.scad
openscad -o drill.stl    -D 'part="drill"'    case/display_cradle.scad
openscad -o template.stl -D 'part="template"' case/display_cradle.scad

openscad -o arm.stl      -D 'part="arm"'      case/label_spool.scad
openscad -o cap.stl      -D 'part="cap"'      case/label_spool.scad
```

One M3 screw per corner runs up through the riser and the retainer into the
cradle, so a single fastener carries the whole stack. Four more go down through
the riser's flange into the printer's top shell.

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

## Still to confirm before printing

**The roll.** `label_spool.scad`'s three roll figures are the common values for
4x6 thermal stock, not measurements: outside diameter 105, width 80 (production
stock here is 3in = 76.2), core 25.4 (1in — 38mm is the other common size).
Measure a real roll and change those three numbers.

**Where the rear label slot sits.** `spindle_drop` is 0, which hangs a full roll
between roughly 70 and 176 mm above the table — chosen to clear the printer's
rear connectors vertically rather than reaching further back to clear them
horizontally, because reach is what tips the machine. Increase it to hang the
roll lower once the slot's real height is known.

**Where the printer's top shell will take a screw.** The riser's four holes are
on a 150 x 74 pattern; `drill.stl` puts them in the right place, but it assumes
there is something behind the shell worth screwing into. Check what the top
looks like from the inside before drilling — if it's unsupported thin plastic,
the load wants spreading rather than four point fixings.

## Why the arm reaches 70 mm and not further

Pushing the spindle back until a full roll clears the rear cables horizontally
would need about 102 mm, and reach is the thing that tips this over. A 500 g
roll at 70 mm is a 0.34 Nm tipping moment against roughly 0.99 Nm of restoring
moment from the printer and the display stack — about 2.9x. At 102 mm that
margin falls to 2.0x.

Going up instead of back costs nothing: at 70 mm the roll hangs clear above a
102 mm-tall printer's connectors, and the label pays off downward and forward
into the slot, which is the path it wants to take anyway.

Strength was never the constraint. Even at 102 mm the arm sees under 1 MPa
against PLA's ~50 MPa. **Print the arm on its side** — standing it up puts the
layer lines square across the bending stress at the root, which is the one way
to break a part loaded this lightly.
