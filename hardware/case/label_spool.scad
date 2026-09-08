// MTG Kiosk - label roll arm
//
// An L that bolts to the CENTRE of the riser's back wall and cantilevers a
// spindle out behind the printer, so the roll hangs centred on the machine and
// the web pays off straight into the middle of the rear slot.
//
// It used to bolt to one END of that wall. That hung the roll's centre about
// 129mm off the centreline of a 220mm-wide printer - past its corner - and fed
// the web in at an angle. Centred, the roll's centre of mass sits directly
// behind the bolt pattern, so the 500g load is pure bending at 70mm reach with
// no twisting couple about the printer at all. It is the better joint as well
// as the one that feeds straight.
//
// TWO PARTS, and the split is the point:
//
//   arm      Plate, leg and hub. Prints lying flat: 38mm tall, both long faces
//            on the bed, no overhangs, and the leg's layer lines running along
//            its length - which is the direction the bending stress runs.
//
//   spindle  A plain bar. Prints standing on its free end, so the surface the
//            roll turns on comes off the machine round and unsupported rather
//            than scarred by support material. Use a brim; it is a 116mm
//            column on a 24mm foot.
//
// One piece would have forced a choice between those two, because the spindle
// is perpendicular to the leg - there is no orientation that prints both well.
// Splitting also means core_d, the one number here still unmeasured, costs a
// spindle reprint if it is wrong instead of the whole bracket.
//
//   openscad -o arm.stl     -D part="arm"     label_spool.scad
//   openscad -o spindle.stl -D part="spindle" label_spool.scad
//   openscad -o cap.stl     -D part="cap"     label_spool.scad

// -------------------------------------------------------------- roll (check)
// Common values for 4x6 thermal stock, NOT measurements of the roll in hand.
// This printer's own paperwork has already been wrong twice; measure a roll.
// roll_width sets where the leg sits, so that the roll ends up centred.
roll_max_d   = 105.0;   // outside diameter, full roll
roll_width   =  80.0;   // production stock here is 3in = 76.2
core_d       =  25.4;   // 1in core; 38mm (1.5in) is the other common size

// --------------------------------------------------- interface with the riser
// These four must match display_cradle.scad.
arm_mount_dx =  52.0;
arm_mount_dz =  18.0;
screw_d      =   3.40;  // M3 clearance, opened up for PETG
screw_pilot  =   2.60;  // M3 self-tapping into PETG

// ------------------------------------------------------------------- geometry
plate_w      = 104.0;
plate_h      =  38.0;
plate_t      =   6.0;

// How far back the spindle sits from the riser's wall.
//
// The obvious answer - push it back until a full roll clears the rear
// connectors - is the wrong one. Reach is what tips the machine: a 500g roll
// at 70mm is a 0.34 Nm tipping moment against about 0.99 Nm of restoring
// moment from the printer and the display stack, and going to 102mm to clear
// the cables horizontally cuts that margin from ~2.9x to ~2.0x.
//
// So the roll clears the cables *vertically* instead. The spindle sits level
// with the riser's mid-height, roughly 123mm above the table, which hangs a
// full roll between about 70mm and 176mm - entirely above the rear connectors
// on a 102mm-tall body.
//
// The rear label slot measures 56mm above the table, which settles the height
// as a measurement rather than a guess: the web leaves the top of a full roll
// at 70.5mm and drops 14.5mm forward into the slot, growing to 54.3mm as the
// roll empties. Downhill throughout. Lowering the roll so a FULL one paid off
// level with the slot would put it at 56-161mm, overlapping the printer body
// at only 17.5mm behind it - straight into the USB and power tails, which is
// the clash this height exists to avoid.
arm_reach    =  70.0;
leg_w        =  10.0;   // web thickness; its inner face is the roll's thrust wall
hub_w        =  24.0;   // local thickening at the far end, to take the spigot
hub_y        =  26.0;

// Spindle joint. A round spigot in a teardrop socket, held axially by one set
// screw dropping into a groove. Deliberately not keyed: the roll turning the
// spindle inside its socket is a bearing, not a failure, and a groove locks it
// axially at any rotation - so there is no orientation to get right on
// assembly, which a hex or a cross-bolt would both have demanded.
spigot_d     =  16.0;
spigot_len   =  22.0;
bore_fit     =   0.5;   // on top of the PETG allowance already in screw sizes
groove_at    =  11.0;   // from the shoulder
groove_d     =  13.0;
groove_w     =   4.0;

spindle_d    = core_d - 1.2;    // turns freely inside the core
spindle_len  = roll_width + 14; // roll plus room for the cap

cap_d        = spindle_d + 14;
cap_t        =   5.0;
cap_spigot_d = spindle_d - 7.4; // locates the cap in the spindle's end bore

part = "arm";           // "arm" | "spindle" | "cap" | "both"

$fn = 72;

// -------------------------------------------------------------------- derived
// Put the leg so the roll's centre lands on x = 0. The roll starts at the
// leg's inner face and is roll_width wide, so that face has to sit half a roll
// to the left of centre.
leg_x   = -(leg_w / 2 + roll_width / 2);
face_x  = leg_x + leg_w / 2;    // the plane the roll's end bears against

// --------------------------------------------------------------------- parts

module mount_holes() {
  for (dx = [-1, 1], dz = [-1, 1])
    translate([dx * arm_mount_dx / 2, -1, dz * arm_mount_dz / 2])
      rotate([-90, 0, 0]) cylinder(h = plate_t + 2, d = screw_d);
}

// A horizontal bore that prints without support: a circle with a 45 degree
// peak on top. A plain round hole this size has a flat unsupported roof that
// droops into the bore, and the spindle then has to be hammered in.
module teardrop(d, len) {
  r = d / 2;
  union() {
    rotate([0, -90, 0]) cylinder(h = len, d = d);
    rotate([45, 0, 0]) translate([-len / 2, 0, 0])
      cube([len, r * 2, r * 2], center = true);
  }
}

module hub() {
  translate([face_x - hub_w, arm_reach - hub_y / 2, -plate_h / 2])
    cube([hub_w, hub_y, plate_h]);
}

module arm() {
  difference() {
    union() {
      // Plate against the riser's back wall.
      translate([-plate_w / 2, 0, -plate_h / 2])
        cube([plate_w, plate_t, plate_h]);

      // Leg, widening from the plate into the hub. Hulled rather than stepped
      // so the section grows toward the load, and every face stays vertical -
      // which is what lets the whole part print with no support at all.
      //
      // Its inner face is a single plane at face_x running the full length, so
      // the roll's end bears on the leg the whole way rather than on a pad.
      hull() {
        translate([leg_x - leg_w / 2, plate_t, -plate_h / 2])
          cube([leg_w, 0.1, plate_h]);
        hub();
      }
    }

    mount_holes();

    // Spindle socket.
    translate([face_x + 1, arm_reach, 0])
      teardrop(spigot_d + bore_fit, spigot_len + 4);

    // Set screw, down through the hub into the spigot's groove.
    translate([face_x - groove_at, arm_reach, 0])
      cylinder(h = plate_h / 2 + 1, d = screw_pilot);
  }
}

// Prints standing on its free end (z = 0 here). The only diameter change runs
// inward going up, so there is nothing to support.
module spindle() {
  difference() {
    union() {
      cylinder(h = spindle_len, d = spindle_d);
      translate([0, 0, spindle_len]) cylinder(h = spigot_len, d = spigot_d);
    }

    // Groove the arm's set screw drops into.
    translate([0, 0, spindle_len + groove_at - groove_w / 2])
      difference() {
        cylinder(h = groove_w, d = spigot_d + 2);
        cylinder(h = groove_w, d = groove_d);
      }

    // The cap's spigot locates in here, so the cap stays square to the axis
    // instead of pivoting on its single screw. Printed free-end-down, this is
    // just a hole in the first layer.
    translate([0, 0, -1]) cylinder(h = 9, d = cap_spigot_d + 0.4);

    // Pilot for the cap screw, below that bore - deep enough for a real length
    // of thread rather than the 6mm the counterbore would otherwise leave.
    translate([0, 0, -1]) cylinder(h = 22, d = screw_pilot);
  }
}

// Slides on after the roll and takes one M3 into the spindle's end.
module cap() {
  difference() {
    union() {
      cylinder(h = cap_t, d = cap_d);
      // Spigot into the spindle's pilot bore, so the cap stays square to the
      // axis rather than pivoting on a single screw.
      translate([0, 0, -6]) cylinder(h = 6.5, d = cap_spigot_d);
    }
    translate([0, 0, -8]) cylinder(h = cap_t + 12, d = screw_d);
    translate([0, 0, cap_t - 2.4]) cylinder(h = 3, d = screw_d * 2);
    // Finger grip.
    for (a = [0 : 45 : 359])
      rotate([0, 0, a]) translate([cap_d / 2, 0, -1])
        cylinder(h = cap_t + 2, d = 3.4);
  }
}

if (part == "arm")          arm();
else if (part == "spindle") spindle();
else if (part == "cap")     cap();
else {
  // Assembled, with the cap backed off so the joint is visible. The spindle
  // has to go in spigot-first, so it is mirrored relative to how it prints -
  // getting that backwards here shows a part that could not be fitted.
  arm();
  translate([face_x + spindle_len, arm_reach, 0]) rotate([0, -90, 0]) spindle();
  translate([face_x + spindle_len + 12, arm_reach, 0]) rotate([0, 90, 0]) cap();
}

echo(str("roll spans x = ", face_x, " to ", face_x + roll_width,
         " -> centre at ", face_x + roll_width / 2, " mm (want 0)"));
echo(str("arm: ", plate_w, " wide plate, leg at x = ", leg_x,
         ", hub out to x = ", face_x - hub_w));
echo(str("spindle: ", spindle_d, " dia x ", spindle_len,
         " plus a ", spigot_len, " spigot = ", spindle_len + spigot_len,
         " mm tall standing up"));
echo(str("roll clearance behind the wall: ",
         arm_reach - roll_max_d / 2, " mm at full diameter"));
