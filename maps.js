// Simple original vector zone layouts per map, in the same coordinate space as pos_x / pos_y.
// Each zone: { name, rect: [x0, y0, x1, y1] } or { name, poly: [[x, y], ...] }.
// A map with no entry here falls back to the bounding box of its cast positions.
// PLACEHOLDER: the fracture coordinates below are rough guesses to check the format, not the real layout.
window.MAPS = {
  fracture: {
    placeholder: true,
    zones: [
      { name: 'A Site',    rect: [3800, -2600, 6200, 1400] },
      { name: 'A Main',    rect: [3800, 1800, 6200, 4400] },
      { name: 'Mid',       rect: [7000, -3200, 10500, 800] },
      { name: 'Connector', poly: [[6300, -400], [6900, -400], [6900, 1400], [10600, 1400], [10600, 2200], [6300, 2200]] },
      { name: 'B Site',    rect: [11300, -2600, 13700, 1400] },
      { name: 'B Main',    rect: [11300, 1800, 13700, 4400] }
    ]
  }
};
