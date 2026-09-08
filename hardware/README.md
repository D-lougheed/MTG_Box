# Enclosure

The display sits on top of the printer rather than in a box around it. The
printer's top face is clear — USB, DC in, the power rocker and the label inflow
are all on the back — so a riser lifts the screen above it and the Pi lives in
the gap, bolted down through the printer's top shell.

```
        display (164.9 x 102, screen up)
   ┌─────────────────────────────┐
   │  cradle + retainer          │  188.9 x 108.8 x 15
   ├─────────────────────────────┤
   │  riser  (Pi hangs in here)  │  42 tall, open all round
   ├─────────────────────────────┤
   │  printer  220 x 112 x 102   │  measured, not from the manual
   └─────────────────────────────┘        ~159 mm overall
```

The label roll hangs off an L-shaped arm bolted to the **centre** of the riser's
back wall, which puts the roll centred on the printer and pays the web straight
into the middle of the rear slot. It is supported from one side only, so a roll
slides on from the free end and a cap screws over it.

```bash
openscad -o cradle.stl   -D 'part="cradle"'   case/display_cradle.scad
openscad -o retainer.stl -D 'part="retainer"' case/display_cradle.scad
openscad -o riser.stl    -D 'part="riser"'    case/display_cradle.scad
openscad -o drill.stl    -D 'part="drill"'    case/display_cradle.scad
openscad -o template.stl -D 'part="template"' case/display_cradle.scad

openscad -o arm.stl      -D 'part="arm"'      case/label_spool.scad
openscad -o spindle.stl  -D 'part="spindle"'  case/label_spool.scad
openscad -o cap.stl      -D 'part="cap"'      case/label_spool.scad
```

One M3 screw per corner runs up through the riser and the retainer into the
cradle, so a single fastener carries the whole stack. Four more go down through
the riser's flange into the printer's top shell — `drill.stl` is a 1:1 guide so
those four holes get made once, in the right place.

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

## Three things that shaped the design

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

**The flange is a frame, not a plate.** A solid one covered essentially the
whole of the printer's top face: it would have sat on the printer's own button,
blocked airflow under the Pi, and spent ~60 cm³ of filament doing it. It is now
a 14 mm border with a pad running out to each of the four mount screws, leaving
161 x 81 mm open over the middle of the printer.

## The label arm

**Why it reaches 70 mm and not further.** Pushing the spindle back until a full
roll clears the rear cables horizontally would need about 102 mm, and reach is
the thing that tips this over. A 500 g roll at 70 mm is a 0.34 Nm tipping
moment against roughly 0.99 Nm of restoring moment from the printer and the
display stack — about 2.9x. At 102 mm that margin falls to 2.0x. Going up
instead of back costs nothing, so the roll clears the cables vertically.

**Why it mounts at the centre.** It used to bolt to one end of the back wall.
That hung the roll's centre about 129 mm off the centreline of a 220 mm-wide
printer — past its corner — and fed the web in at an angle. Centred, the roll's
centre of mass sits directly behind the bolt pattern, so the load is pure
bending at 70 mm reach with no twisting couple about the printer at all.

**Why it is two parts.** The spindle is perpendicular to the leg, and no single
print orientation is good for both: the leg wants its layer lines running along
its length, because that is the direction the bending stress runs, and the
spindle wants to come off the machine round and unsupported, because the roll
turns on it and support scarring would make it drag. Split, each gets what it
needs — and `core_d`, the one number here still unmeasured, now costs a spindle
reprint if it is wrong rather than the whole bracket.

- **arm** — prints lying flat. 38 mm tall, both long faces on the bed, no
  overhangs anywhere.
- **spindle** — prints standing on its free end. Use a brim; it is a 116 mm
  column on a 24 mm foot.

The joint is a round spigot in a teardrop socket, locked axially by one set
screw dropping into a groove. Deliberately unkeyed: the roll turning the
spindle in its socket is a bearing, not a failure, and a groove locks at any
rotation — so there is no orientation to get right on assembly, which a hex or
a cross-bolt would both have demanded.

Strength was never the constraint anywhere on this arm — even at 102 mm reach
it sees under 1 MPa against PETG's ~50 MPa. The joints and the print
orientation are the whole game.

## The rear slot, and why the roll stays high

The printer's label slot is **56 mm** above the table. With the spindle at
123 mm the web leaves the top of a full roll at 70.5 mm and drops 14.5 mm
forward into the slot; as the roll empties the pay-off point rises and the drop
grows to 54.3 mm. Downhill throughout, which is the way the stock wants to feed.

Lowering the roll to bring a full one level with the slot would put the spindle
at 108.5 mm and hang the roll from 56 to 161 mm — overlapping the 102 mm-tall
printer body at just 17.5 mm behind it, which is where the USB and power tails
live. That reintroduces exactly the clash the high mount exists to avoid, so
`spindle_drop` stays at 0.

## Material

**PETG.** Two reasons, one of which is not optional: the assembly sits directly
above a thermal print head, and PETG softens around 80 °C against PLA's ~60 °C.
A PLA cradle would be a slow creep problem, not a sudden one.

Tolerances in both `.scad` files are set for PETG, which extrudes slightly
fatter than PLA and closes holes up: `fit` is 0.40 (not 0.30), M3 clearance
holes are 3.40, and self-tapping pilots are a separate `screw_pilot` at 2.60 so
that opening a clearance hole can't silently loosen every pilot with it.

PETG also bonds between layers much better than PLA, which softens the print
orientation requirement on the arm — but it costs nothing to get right, so the
orientation notes above still stand.

## Before printing

Render the `template` part and print it **on paper at 100% scale**, then lay the
real panel on it. The panel is third-party and the drawing is the only source
for its dimensions; a sheet of paper is a cheap way to find out the drawing is
wrong, and a failed 4-hour print is not.

## Still to confirm

**The roll.** `label_spool.scad`'s three roll figures are the common values for
4x6 thermal stock, not measurements: outside diameter 105, width 80 (production
stock here is 3in = 76.2), core 25.4 (1in — 38mm is the other common size).
Measure a real roll and change those three numbers. `roll_width` is not just
cosmetic: it sets where the leg sits, which is what centres the roll.

**The printer's button.** The flange's open middle clears anything on the
central 161 x 81 mm of the top face, so this only matters if the button falls
under the 14 mm border. If it does, set `button_d` to something a finger fits
through and give `button_x` / `button_y` from the centre of the top face — +x
to the right, +y toward the front, looking at the machine from the front.
`button_d` is 0 (no cut) until that is known.
