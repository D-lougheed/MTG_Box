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

// Print tolerances. 0.3 is a comfortable slip fit on a well-tuned FDM printer;
// raise it if the panel is tight, lower it if it rattles.
fit          = 0.30;
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
screw_d       = 3.20;   // M3 clearance
screw_head_d  = 6.20;
boss_d        = 8.00;

// Depth below the panel for the Pi 5 bolted to the panel's 58x49 holes on the
// supplied copper pillars, plus its connectors and the FPC ribbon's bend
// radius. The ribbon is the constraint, not the board.
rear_clearance = 34.00;

part = "cradle";        // "cradle" | "retainer" | "both" | "template"

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
      cylinder(h = floor_t + panel_t + fit + 2, d = screw_d - 0.6);
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

if (part == "cradle")        cradle();
else if (part == "retainer") retainer();
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
