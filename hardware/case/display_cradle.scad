// MTG Kiosk - display cradle
//
// Holds the 7in DSI module (and, bolted to its back, the Pi 5) as the top
// surface of the table-centre enclosure. Screen faces up.
//
// Every dimension below is from the panel's own datasheet
// (7inch-DSI-Display_User_Manual-V1.1.pdf, section 3 "Dimensional Drawing"),
// not measured or guessed. Change a number here and re-render; nothing is
// hardcoded further down.
//
//   openscad -o display_cradle.stl display_cradle.scad
//   openscad -D part=\"retainer\" -o retainer.stl display_cradle.scad

// ---------------------------------------------------------------- parameters

// Panel, from the datasheet.
panel_w      = 164.90;  // PCB/BL outline
panel_h      = 102.00;
panel_t      = 12.25;   // "12.25 Total" on the side view
lens_w       = 164.28;  // LENS OD - the glass reaches almost to the PCB edge
lens_h       =  99.17;
active_w     = 154.68;  // V.A - never cover this
active_h     =  87.02;

// The module's own mounting holes: 154.89 x 91.92, centres 5mm in from each
// edge. Deliberately NOT used to retain the panel - see the note by the
// retainer below - but modelled so the clearance is real.
panel_hole_dx = 154.89;
panel_hole_dy =  91.92;

// Print tolerances, set for PETG. It lays down slightly fatter than PLA and
// holes come out tighter, so a clearance that suits PLA gives a pocket the
// panel has to be forced into - and this pocket holds bonded glass.
//
// PETG's other property matters more than it looks: it softens around 80C
// against PLA's ~60C, and this whole assembly sits on top of a thermal print
// head. PLA would have been the wrong material here regardless of fit.
fit          = 0.40;
wall         = 3.00;
floor_t      = 2.40;

// The window is sized to clear the active area with a visible margin, and is
// smaller than the lens so the frame has something to overlap. It CANNOT be
// pulled in far enough to reach the mounting holes: those sit 5mm from the
// edge while the active area starts 5.11mm from it, so any lip that reached a
// hole would be sitting on live screen. That is why the panel is trapped
// rather than screwed.
window_margin = 1.60;   // frame overlap onto the black border, per side

// Rear retainer.
retainer_t    = 3.00;
screw_d       = 3.40;   // M3 clearance, opened up for PETG
screw_pilot   = 2.60;   // M3 self-tapping into PETG
screw_head_d  = 6.20;
boss_d        = 8.00;

// Depth below the panel for the Pi 5 bolted to the panel's 58x49 holes on the
// supplied copper pillars, plus its connectors and the FPC ribbon's bend
// radius. The ribbon is the constraint, not the board.
rear_clearance = 34.00;

// Printer, measured on the unit (the manual's 252 x 180 x 152 is the carton or
// another variant). USB, DC in, the power rocker and the label inflow are all
// on the back, and the top face is clear - so the display can sit on top with
// nothing to work around.
printer_w    = 220.0;
printer_d    = 112.0;
printer_h    = 102.0;

// Height of the gap the riser opens up between the printer's top face and the
// cradle's underside. The Pi is bolted to the panel's back on the supplied
// copper pillars, so it hangs down into this space along with the FPC ribbon's
// bend and the USB and power tails that have to reach the back of the printer.
riser_h      = 42.0;
flange_t     = 3.0;

// Derived, not chosen. The outer plate is sized as boss centre + boss radius +
// `wall`, so a skirt exactly `wall` thick puts its inner surface precisely
// tangent to the bosses - which is not a solid, and OpenSCAD rightly refuses
// to call it 2-manifold. Making the skirt thicker than `wall` by a definite
// amount forces a real intersection, and keeps doing so if boss_d or wall
// change later.
riser_boss_overlap = 1.5;
riser_wall   = wall + riser_boss_overlap;

// Screws down into the printer's own top shell. Positions are echoed by the
// drill template so the holes get made once, in the right place.
mount_screw_d = 3.40;   // M3 clearance into a tapped shell
mount_dx      = 150.0;
mount_dy      =  74.0;

// Anchor pads for the label arm, on the CENTRE of the riser's back wall.
//
// They used to sit at the two ends, which hung the roll's centre about 129mm
// off the printer's centreline - past the corner of a 220mm machine - and fed
// the web into the rear slot at an angle. Centred, the roll's centre of mass
// is directly behind the bolt pattern, so the 500g load is pure bending at
// 70mm reach with no twisting couple about the printer at all.
//
// Four screws in a rectangle rather than two in a line: the vertically spread
// pair is what resists the roll levering the plate's top off the wall.
arm_mount_dx  = 52.0;
arm_mount_dz  = 18.0;
arm_mount_z   = 21.0;
arm_boss_d    =  8.0;
arm_boss_len  = 11.0;

// Solid column on the back wall carrying those anchors. The rear cable opening
// splits into two windows either side of it - which suits the cabling anyway,
// since the USB lead and the USB-C power lead go to opposite ends of the Pi.
arm_column_w  = 76.0;
rear_window_w = 46.0;

// The flange is a frame, not a plate. A solid one covered essentially the whole
// of the printer's top face - it would have sat on the printer's own button,
// blocked air under the Pi, and cost ~60 cm3 of filament to do it.
flange_border = 14.0;
mount_pad_d   = 14.0;

// Clearance for the printer's button IF it falls under that remaining 14mm
// border. Anything in the middle of the top face is already clear.
//
// MEASUREMENT NEEDED - button_d stays 0 (no cut) until the button's position is
// known. Give it from the centre of the printer's top face: +x to the right and
// +y toward the front, both looking at the machine from the front.
button_d      = 0.0;
button_x      = 0.0;
button_y      = 0.0;

part = "cradle";        // "cradle" | "retainer" | "riser" | "both"
                        // "template" (paper, panel fit) | "drill" (printer top)

$fn = 64;

// ------------------------------------------------------------------ geometry

pocket_w = panel_w + fit * 2;
pocket_h = panel_h + fit * 2;

window_w = active_w + window_margin * 2;
window_h = active_h + window_margin * 2;

// Retainer screws sit wholly outside the panel footprint, clear of the glass,
// and the outer plate is sized to contain them. An earlier version put the
// boss centres only half a wall out, so each boss was half-eaten by the panel
// pocket and still overhung the outer edge - visible the moment it was
// rendered, invisible in the echoed dimensions.
//
// They go beyond the panel's SHORT ends, two per end, rather than at the four
// corners. Corners cost boss diameter on both axes; the printer this mounts to
// measures 112mm across its narrow face, and a corner layout put the cradle at
// 125.8mm - overhanging by 7mm a side. Ends-only keeps the narrow axis to the
// panel plus two walls and spends the width on the long axis, where the
// printer has 220mm to give.
boss_inset = boss_d / 2 + 0.6;
boss_dx = pocket_w / 2 + boss_inset;
boss_dy = pocket_h / 4;          // paired across the short axis, inside it

outer_w  = (boss_dx + boss_d / 2 + wall) * 2;
outer_h  = pocket_h + wall * 2;

module boss_positions() {
  for (x = [-1, 1], y = [-1, 1]) translate([x * boss_dx, y * boss_dy, 0]) children();
}

module rounded_plate(w, h, t, r = 4) {
  hull() for (x = [-1, 1], y = [-1, 1])
    translate([x * (w / 2 - r), y * (h / 2 - r), 0]) cylinder(h = t, r = r);
}

// The frame the panel drops into from below, lens upward against the window.
module cradle() {
  difference() {
    union() {
      rounded_plate(outer_w, outer_h, floor_t + panel_t + fit);
      boss_positions() cylinder(h = floor_t + panel_t + fit, d = boss_d);
    }

    // Viewing window, through the top face.
    translate([0, 0, -1])
      rounded_plate(window_w, window_h, floor_t + 2, r = 2);

    // Panel pocket: starts at the window shoulder and runs out through the
    // rear face, so the module loads from behind. Written from an explicit
    // corner rather than centred - a centred cube here put the pocket half
    // below the floor, which quietly ate the window shoulder.
    translate([-pocket_w / 2, -pocket_h / 2, floor_t])
      cube([pocket_w, pocket_h, panel_t + fit + 1]);

    // Screw pilots for the retainer.
    boss_positions() translate([0, 0, -1])
      cylinder(h = floor_t + panel_t + fit + 2, d = screw_pilot);
  }
}

// Trapping the panel rather than screwing through it is deliberate: the only
// holes it offers are level with the edge of the active area, so using them
// would mean a lip over live screen. This presses on the PCB back instead, and
// stays tolerant of a panel revision moving a hole.
module retainer() {
  difference() {
    union() {
      rounded_plate(outer_w, outer_h, retainer_t);
      boss_positions() cylinder(h = retainer_t, d = boss_d);
    }

    // Open the middle: the Pi bolts to the panel behind here, and the FPC has
    // to reach the DSI socket.
    rounded_plate(pocket_w - 16, pocket_h - 16, retainer_t * 3, r = 3);

    boss_positions() {
      translate([0, 0, -1]) cylinder(h = retainer_t + 2, d = screw_d);
      translate([0, 0, retainer_t - 1.8]) cylinder(h = 2, d = screw_head_d);
    }
  }
}

// A 1:1 paper template. Printed on paper and laid on the real panel, it shows
// whether the datasheet matches the hardware in hand before any filament is
// committed - the panel is third-party and the drawing is the only source.
module template() {
  difference() {
    rounded_plate(outer_w, outer_h, 0.4);
    translate([0, 0, -1]) rounded_plate(window_w, window_h, 3, r = 2);
    boss_positions() translate([0, 0, -1]) cylinder(h = 3, d = screw_d);
    // Panel outline scored, so the module can be laid straight onto it.
    difference() {
      translate([0, 0, -0.5]) cube([pocket_w, pocket_h, 3], center = true);
      translate([0, 0, -0.5]) cube([pocket_w - 0.8, pocket_h - 0.8, 4], center = true);
    }
  }
}

module mount_positions() {
  for (x = [-1, 1], y = [-1, 1]) translate([x * mount_dx / 2, y * mount_dy / 2, 0]) children();
}

// Each mount screw needs a landing, and opening the flange's middle took it
// away. These run a pad from the screw out to the frame at the nearest edge.
module mount_pads() {
  for (x = [-1, 1], y = [-1, 1])
    hull() {
      translate([x * mount_dx / 2, y * mount_dy / 2, 0])
        cylinder(h = flange_t, d = mount_pad_d);
      translate([x * mount_dx / 2, y * (outer_h / 2 - 4), 0])
        cylinder(h = flange_t, d = mount_pad_d);
    }
}

// Four anchor points, centred on the inside of the back wall.
module arm_anchor_positions() {
  for (dx = [-1, 1], dz = [-1, 1])
    translate([dx * arm_mount_dx / 2,
               -outer_h / 2 + riser_wall,
               arm_mount_z + dz * arm_mount_dz / 2])
      rotate([-90, 0, 0]) children();
}

// Lifts the display clear of the printer's top so the Pi has somewhere to live.
// Open on all four sides: the Pi needs air, and its USB and power tails have to
// get to the back of the printer where every socket is.
module riser() {
  difference() {
    union() {
      // Bottom flange - a frame, not a plate. See flange_border above.
      difference() {
        rounded_plate(outer_w, outer_h, flange_t);
        translate([0, 0, -1])
          rounded_plate(outer_w - flange_border * 2, outer_h - flange_border * 2,
                        flange_t + 2, r = 3);
      }
      mount_pads();

      // Skirt.
      difference() {
        rounded_plate(outer_w, outer_h, riser_h);
        translate([0, 0, -1])
          rounded_plate(outer_w - riser_wall * 2, outer_h - riser_wall * 2, riser_h + 2);
      }
      // Top bosses, aligned to the cradle's retainer screws so one screw per
      // corner carries cradle, retainer and riser together.
      boss_positions() cylinder(h = riser_h, d = boss_d);

      // Label-arm anchors, centred on the back wall.
      arm_anchor_positions() cylinder(h = arm_boss_len, d = arm_boss_d);
    }

    // Screws up into the cradle.
    boss_positions() translate([0, 0, -1]) cylinder(h = riser_h + 2, d = screw_d);

    // Down into the printer's top shell.
    mount_positions() {
      translate([0, 0, -1]) cylinder(h = flange_t + 2, d = mount_screw_d);
      translate([0, 0, flange_t - 1.4]) cylinder(h = 2, d = screw_head_d);
    }

    // Pilots through the back wall into the arm anchors.
    arm_anchor_positions() translate([0, 0, -riser_wall - 1])
      cylinder(h = arm_boss_len + riser_wall + 2, d = screw_pilot);

    // Front: one wide opening.
    translate([0, outer_h / 2, riser_h / 2 + flange_t / 2])
      cube([outer_w * 0.62, riser_wall * 4, riser_h - flange_t - 6], center = true);

    // Back: two windows either side of the arm's anchor column.
    for (side = [-1, 1])
      translate([side * (arm_column_w / 2 + rear_window_w / 2), -outer_h / 2,
                 riser_h / 2 + flange_t / 2])
        cube([rear_window_w, riser_wall * 4, riser_h - flange_t - 6], center = true);

    // Sides, for air.
    for (side = [-1, 1])
      translate([side * (outer_w / 2), 0, riser_h / 2 + flange_t / 2])
        cube([riser_wall * 4, outer_h * 0.45, riser_h - flange_t - 6], center = true);

    // The printer's button, if it falls under the frame.
    if (button_d > 0)
      translate([button_x, button_y, -1]) cylinder(h = flange_t + 2, d = button_d);
  }
}

// 1:1 drilling guide for the printer's top face. Printed flat and laid on the
// printer, it puts the four holes exactly under the riser's flange - the shell
// only gets drilled once, and not by eye.
module drill_template() {
  difference() {
    rounded_plate(printer_w - 6, printer_d - 6, 1.6);
    mount_positions() translate([0, 0, -1]) cylinder(h = 4, d = mount_screw_d);
    // A window through the middle so the printer's own features stay visible
    // while the template is being lined up.
    rounded_plate(mount_dx - 30, mount_dy - 30, 6, r = 4);
  }
}

if (part == "cradle")        cradle();
else if (part == "retainer") retainer();
else if (part == "riser")    riser();
else if (part == "drill")    drill_template();
else if (part == "template") template();
else {
  cradle();
  translate([0, outer_h + 10, 0]) retainer();
}

echo(str("cradle footprint: ", outer_w, " x ", outer_h,
         " x ", floor_t + panel_t + fit, " mm"));
echo(str("window: ", window_w, " x ", window_h,
         " mm (active area ", active_w, " x ", active_h, ")"));
echo(str("total depth with Pi behind: ",
         floor_t + panel_t + fit + rear_clearance, " mm"));
echo(str("flange frame: ", flange_border, "mm border; middle open ",
         outer_w - flange_border * 2, " x ", outer_h - flange_border * 2,
         " mm over the printer's top"));
echo(str("arm anchors: ", arm_mount_dx, " x ", arm_mount_dz,
         " centred on the back wall, ", arm_mount_z, " mm up"));
