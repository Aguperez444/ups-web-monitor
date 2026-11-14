import type { MetricKey } from "./telemetry";

const acVoltage = { min: 190, max: 255 };
const percent = { min: 0, max: 100 };
const nominalBounds: Record<MetricKey, { min: number; max: number }> = {
  input_voltage: acVoltage,
  output_voltage: acVoltage,
  output_frequency: { min: 45, max: 55 },
  load_percent: percent,
  battery_voltage: { min: 20, max: 30 },
  battery_charge: percent,
};

export function historyYBounds(metric: MetricKey, points: readonly { y: number | null }[]) {
  let { min, max } = nominalBounds[metric];
  for (const { y } of points) {
    if (y === null || !Number.isFinite(y)) continue;
    min = Math.min(min, y);
    max = Math.max(max, y);
  }
  return { min: Math.floor(min), max: Math.ceil(max) };
}
