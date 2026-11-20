// The plate's measures: its size, the two rails, the left edge and the motor's centre.

export const W = 760;
export const H = 430;
export const RAIL_TOP = 64;
export const RAIL_BOTTOM = 366;
export const MID = (RAIL_TOP + RAIL_BOTTOM) / 2;
export const LEFT = 132;
export const MOTOR_X = 660;

/** Height at which leg k leaves for the motor. Staggered, so the output wires never overlap. */
export function tapY(k: number, count: number): number {
  return MID + (k - (count - 1) / 2) * (count > 3 ? 18 : 26);
}

export const R_STATOR = 60;
export const R_ROTOR = 42;
