export type Mode = "line" | "battery" | "bypass" | "off" | "unknown";
export type Charger = "charging" | "discharging" | "floating" | "resting";

export type Metrics = {
  input_voltage: number | null;
  output_voltage: number | null;
  output_frequency: number | null;
  load_percent: number | null;
  battery_voltage: number | null;
  battery_charge: number | null;
};

export type Sample = Metrics & {
  timestamp: string;
  status: string | null;
  mode: Mode;
};

export type Current = Sample & {
  ups_name: string;
  manufacturer: string | null;
  model: string | null;
  charger: Charger | null;
};

export type History = {
  start: string;
  end: string;
  sample_interval_seconds: number;
  bucket_seconds: number | null;
  samples: Sample[];
};

export type MetricKey = keyof Metrics;

export const metrics = {
  input_voltage: { label: "Voltaje de entrada", unit: "V", decimals: 1, color: "#47e5b5" },
  output_voltage: { label: "Voltaje de salida", unit: "V", decimals: 1, color: "#6aafff" },
  output_frequency: { label: "Frecuencia de salida", unit: "Hz", decimals: 1, color: "#54cce8" },
  load_percent: { label: "Nivel de carga", unit: "%", decimals: 0, color: "#eeb071" },
  battery_voltage: { label: "Voltaje de batería", unit: "V", decimals: 1, color: "#afa0ff" },
  battery_charge: { label: "Capacidad de batería", unit: "%", decimals: 0, color: "#afa0ff" },
} satisfies Record<MetricKey, { label: string; unit: string; decimals: number; color: string }>;

export const modes: Record<Mode, string> = {
  line: "En línea",
  battery: "En batería",
  bypass: "En bypass",
  off: "Apagado",
  unknown: "Modo desconocido",
};

export const chargerLabels: Record<Charger, string> = {
  charging: "En carga",
  discharging: "En descarga",
  floating: "En flotación",
  resting: "En reposo",
};

export function formatMetric(key: MetricKey, value: number) {
  const { decimals } = metrics[key];
  return new Intl.NumberFormat("es-AR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals + 1,
  }).format(value);
}

export function formatClock(timestamp: string) {
  return new Intl.DateTimeFormat("es-AR", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date(timestamp));
}
