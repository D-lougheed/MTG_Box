// MTG Kiosk - label roll spool
//
// Freestanding holder that sits behind the printer and feeds the rear label
// inflow. Deliberately not bolted to the printer: the back face already
// carries USB, DC in, the power rocker and the label slot, and hanging a roll
// off it would crowd all four.
//
//   openscad -o label_spool.stl -D 'part="upright"' label_spool.scad
//   openscad -o spindle.stl     -D 'part="spindle"' label_spool.scad
//
// CONFIRM THESE AGAINST A REAL ROLL BEFORE PRINTING. They are the common
// values for 4x6 thermal stock, not measurements of the roll in hand, and the
// printer's own paperwork has already been wrong twice.

// -------------------------------------------------------------- roll (check)
roll_max_d   = 105.0;   // outside diameter of a full roll
roll_width   = 80.0;    // production stock here is 3in (76.2mm); 4in is 101.6
core_d       = 25.4;    // 1in core. The other common size is 38mm (1.5in)

// ------------------------------------------------------------------ hardware
spindle_d    = core_d - 1.2;   // slips inside the core and turns freely
spindle_over = 18.0;           // length beyond the roll, each side
slot_w       = spindle_d + 1.0;

base_t       = 5.0;
base_d       = 70.0;
upright_t    = 6.0;
wall         = 3.0;

// Spindle centre height. The roll has to clear the base at full diameter, and
// a little more so a fresh roll doesn't drag as it unwinds.
spindle_h    = roll_max_d / 2 + base_t + 6;

part = "upright";       // "upright" | "spindle" | "both"

$fn = 72;

// ------------------------------------------------------------------ geometry

upright_w = spindle_d + wall * 4;

// One side support. Two are printed; they are mirror images only in placement,
// so the same part is used twice.
module upright() {
  difference() {
    union() {
      // Foot, long in the feed direction so a full roll can't tip it.
      hull() {
        translate([-upright_w / 2, -base_d / 2, 0]) cube([upright_w, base_d, base_t]);
        translate([0, 0, base_t]) cylinder(h = 0.1, d = upright_w);
      }
      // Post.
      hull() {
        translate([-upright_t / 2, -upright_w / 2, 0]) cube([upright_t, upright_w, 1]);
        translate([-upright_t / 2, 0, spindle_h]) rotate([0, 90, 0])
          cylinder(h = upright_t, d = upright_w);
      }

      // Gussets fore and aft. The static weight of the roll is straight down
      // and the post handles that easily, but paying out label pulls the top
      // horizontally toward the printer, and that is a bending moment on a
      // 6mm blade 63mm long. These take it into the foot instead.
      for (dir = [-1, 1])
        hull() {
          translate([-upright_t / 2, dir * (upright_w / 2 - 1), 0])
            cube([upright_t, 1, base_t + 1]);
          translate([-upright_t / 2, dir * (base_d / 2 - wall), 0])
            cube([upright_t, wall, base_t]);
          translate([-upright_t / 2, dir * (upright_w / 2 - 1), spindle_h * 0.55])
            cube([upright_t, 1, 1]);
        }
    }

    // Open-topped slot rather than a bored hole: the spindle lifts straight
    // out with the roll still on it, so reloading doesn't mean threading a bar
    // through a captive frame with one hand.
    translate([-upright_t / 2 - 1, -slot_w / 2, spindle_h])
      cube([upright_t + 2, slot_w, spindle_h]);
    translate([-upright_t / 2 - 1, 0, spindle_h]) rotate([0, 90, 0])
      cylinder(h = upright_t + 2, d = slot_w);

    // Chamfer the slot mouth so the spindle drops in without being aimed.
    // This has to sit at the top of the post; an earlier version put it at
    // twice the spindle height, which is above the part, so it cut nothing.
    translate([-upright_t / 2 - 1, 0, spindle_h + upright_w / 2])
      rotate([0, 90, 0]) cylinder(h = upright_t + 2, d1 = slot_w * 2.4, d2 = slot_w);
  }
}

module spindle() {
  length = roll_width + spindle_over * 2;
  difference() {
    union() {
      cylinder(h = length, d = spindle_d);
      // End flanges stop the roll walking off while it unwinds.
      for (z = [0, length]) translate([0, 0, z])
        cylinder(h = 3, d = spindle_d + 10, center = true);
    }
    // Hollow: this is the longest part on the plate and solid bar is wasted
    // filament with no strength to show for it in bending.
    translate([0, 0, -1]) cylinder(h = length + 2, d = spindle_d - 5);
  }
}

if (part == "upright")      upright();
else if (part == "spindle") spindle();
else {
  span = roll_width + upright_t;
  translate([-span / 2, 0, 0]) upright();
  translate([ span / 2, 0, 0]) upright();
  translate([-(roll_width / 2 + spindle_over), 0, spindle_h]) rotate([0, 90, 0]) spindle();
}

echo(str("spindle centre height: ", spindle_h, " mm"));
echo(str("clear span needed between uprights: ", roll_width, " mm"));
echo(str("overall width with uprights: ",
         roll_width + spindle_over * 2 + upright_t * 2, " mm"));
echo(str("upright footprint: ", upright_w, " x ", base_d, " mm"));
