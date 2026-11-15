You are fixing a 3D-printed part that does not fit the rest of its assembly.

The assembly is an electronics enclosure. Four parts are loaded in the `fitfix` MCP server:

- `enclosure` (the only part you may change): an open-top printed case with 4 screw standoffs and an opening for a USB-C plug in its front wall.
- `pcb` (fixed): the circuit board sitting on the standoffs, with a USB-C receptacle at its front edge.
- `usb_plug` (fixed): a USB-C cable plug shown fully inserted into the receptacle; it passes through the enclosure's front wall.
- `lid` (fixed): the top cover, whose lip drops into the enclosure from above.

Goal: change the enclosure so the whole assembly fits.

- The USB plug must pass through the front wall without touching it. The gap between the plug and the edge of the opening must be within the clearance band from `get_task` on every side (typical for FDM printing: a few tenths of a millimetre).
- Nothing else may collide: the enclosure must not overlap the pcb or the lid.
- Keep the part functional: all 4 standoffs with their pilot holes, the outer shape and roughly the same volume.
- Keep it printable: no wall thinner than the minimum in `get_task`.
- Change as little as necessary.

Units are millimetres, z points up. Call `get_task` first for the exact constraints and coordinate frame.

Tools: inspect with `list_parts`, `part_info`, `check_interference`, `min_clearance`, `section`, `find_holes`, `check_printability`; edit the enclosure with `add_box`, `subtract_box`, `add_cylinder`, `subtract_cylinder`, `undo`. `test_fit` gives a full fit report but has a small budget, like a real test print. Coordinates are snapped to 0.001 mm.

When you are done, call `submit`. The enclosure is graded as saved when the episode ends.
