// MTG Kiosk - label roll arm
//
// An L that bolts to the back wall of the riser and cantilevers a spindle out
// across the back of the printer. The roll slides on from the free end and is
// held by a cap, so reloading is: unscrew cap, old core off, new roll on, cap
// back. No threading a bar through a frame one-handed.
//
// Supported from one side only. A full 3in roll is about 500g, which at this
// reach is roughly 0.3 Nm - under 1 MPa in the arm's section against PETG's
// ~50 MPa. Strength was never the question here; the bolted joint and the
// print orientation are, which is why the joint is four screws in a rectangle
// and why the note below matters.
//
// PRINT THE ARM LYING ON ITS SIDE (largest flat face on the bed). Standing it
// up puts the layer lines square across the bending stress at the root, which
// is the one way to make a part this lightly loaded fail. PETG bonds between
// layers far better than PLA, so this is less critical than it would be - but
// it costs nothing to orient it correctly.
//
//   openscad -o arm.stl -D 'part="arm"' label_spool.scad
//   openscad -o cap.stl -D 'part="cap"' label_spool.scad

// -------------------------------------------------------------- roll (check)
// Common values for 4x6 thermal stock, NOT measurements of the roll in hand.
// This printer's own paperwork has already been wrong twice; measure a roll.
roll_max_d   = 105.0;   // outside diameter, full roll
roll_width   =  80.0;   // production stock here is 3in = 76.2
core_d       =  25.4;   // 1in core; 38mm (1.5in) is the other common size

// --------------------------------------------------- interface with the riser
// These four must match display_cradle.scad.
arm_mount_dx = 22.0;
arm_mount_dz = 18.0;
screw_d      =  3.40;   // M3 clearance, opened up for PETG
riser_h      = 42.0;

// ------------------------------------------------------------------- geometry
plate_w      = arm_mount_dx + 20;
plate_h      = arm_mount_dz + 20;
plate_t      =  6.0;

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
// full roll between about 70mm and 176mm - entirely above the printer's rear
// connectors on a 102mm-tall body. The label then pays off downward and
// forward into the rear slot, which is the natural path anyway.
arm_reach    = 70.0;
arm_w        = 12.0;    // section across the bend
arm_h        = 25.0;    // section in the bending direction

// Spindle axis relative to the mounting plate's centre. Stays at zero, and
// that is now a measured conclusion rather than a placeholder: the printer's
// rear label slot is 56mm above the table, and with the spindle at 123mm the
// label pays off the top of a full roll at 70.5mm and drops 14.5mm forward
// into it - rising to a 54.3mm drop as the roll empties. Downhill the whole
// way, which is the direction the stock wants to go.
//
// Dropping the roll so a FULL roll pays off level with the slot would put the
// spindle at 108.5mm and the roll spanning 56-161mm, i.e. overlapping the
// printer body's 0-102mm at only 17.5mm behind it - straight into the USB and
// power tails. That is precisely the collision the high mount was chosen to
// avoid, so lowering it trades a harmless 14.5mm drop for a cable clash.
spindle_drop = 0.0;

spindle_d    = core_d - 1.2;    // turns freely inside the core
spindle_len  = roll_width + 14; // roll plus room for the cap
cap_d        = spindle_d + 14;
cap_t        =  5.0;
cap_screw_d  =  3.40;

part = "arm";           // "arm" | "cap" | "both"

$fn = 72;

// --------------------------------------------------------------------- parts

module mount_holes() {
  for (dx = [-1, 1], dz = [-1, 1])
    translate([dx * arm_mount_dx / 2, 0, dz * arm_mount_dz / 2])
      rotate([-90, 0, 0]) children();
}

module arm() {
  difference() {
    union() {
      // Plate against the riser wall.
      translate([0, 0, 0])
        cube([plate_w, plate_t, plate_h], center = true);

      // The leg, running back from the plate.
      hull() {
        translate([0, plate_t / 2, -spindle_drop / 2])
          cube([arm_w, 0.1, plate_h * 0.8], center = true);
        translate([0, plate_t / 2 + arm_reach, -spindle_drop])
          cube([arm_w, 0.1, arm_h], center = true);
      }

      // Spindle, cantilevered across the back of the printer.
      translate([arm_w / 2, plate_t / 2 + arm_reach, -spindle_drop])
        rotate([0, 90, 0]) cylinder(h = spindle_len, d = spindle_d);

      // Shoulder where the spindle leaves the leg, so the roll cannot ride
      // back against the leg and bind.
      translate([arm_w / 2, plate_t / 2 + arm_reach, -spindle_drop])
        rotate([0, 90, 0]) cylinder(h = 3, d = spindle_d + 12);
    }

    // Into the riser's anchors.
    mount_holes() translate([0, 0, -plate_t]) cylinder(h = plate_t * 3, d = screw_d);

    // Axial pilot for the retaining cap.
    translate([arm_w / 2 + spindle_len - 12, plate_t / 2 + arm_reach, -spindle_drop])
      rotate([0, 90, 0]) cylinder(h = 14, d = 2.60);   // M3 self-tapping into PETG

    // Hollow the spindle. It is the longest unsupported run on the part and
    // solid bar adds mass at the worst place for a cantilever without adding
    // meaningful stiffness.
    translate([arm_w / 2 + 6, plate_t / 2 + arm_reach, -spindle_drop])
      rotate([0, 90, 0]) cylinder(h = spindle_len - 20, d = spindle_d - 7);
  }
}

// Slides on after the roll and takes one M3 into the spindle's end.
module cap() {
  difference() {
    union() {
      cylinder(h = cap_t, d = cap_d);
      // Spigot into the spindle bore, so the cap stays square to the axis
      // rather than pivoting on a single screw.
      translate([0, 0, -6]) cylinder(h = 6.5, d = spindle_d - 7.4);
    }
    translate([0, 0, -8]) cylinder(h = cap_t + 12, d = cap_screw_d);
    translate([0, 0, cap_t - 2.4]) cylinder(h = 3, d = cap_screw_d * 2);
    // Finger grip.
    for (a = [0 : 45 : 359])
      rotate([0, 0, a]) translate([cap_d / 2, 0, -1])
        cylinder(h = cap_t + 2, d = 3.4);
  }
}

if (part == "arm")      arm();
else if (part == "cap") cap();
else {
  arm();
  translate([arm_w / 2 + spindle_len + 10, plate_t / 2 + arm_reach, -spindle_drop])
    rotate([0, 90, 0]) cap();
}

echo(str("arm reach (wall to spindle axis): ", arm_reach, " mm"));
echo(str("spindle: ", spindle_d, " dia x ", spindle_len,
         " long, for a ", roll_width, " wide roll"));
echo(str("roll clearance behind the wall: ",
         arm_reach - roll_max_d / 2, " mm at full diameter"));
