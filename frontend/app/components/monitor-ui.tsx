import type { ReactNode } from "react";
import { formatMetric, metrics, modes, type MetricKey, type Mode } from "../lib/telemetry";

export type IconName = "flow" | "info" | "chart" | "line" | "output" | "battery" | "load" | "chip" | "time";

export function Icon({ name }: { name: IconName }) {
  return <span aria-hidden="true" className={`icon icon-${name}`} />;
}

export function MetricValue({ metric, value }: { metric: MetricKey; value: number | null | undefined }) {
  return value == null
    ? <span className="missing" aria-label="Sin lectura">—</span>
    : <>{formatMetric(metric, value)} <span className="unit">{metrics[metric].unit}</span></>;
}

export function ModePill({ mode, className = "" }: { mode: Mode; className?: string }) {
  return <span className={`pill mode-${mode} ${className}`}><span className="status-dot" />{modes[mode]}</span>;
}

export function ReadingRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="reading-row"><dt>{label}</dt><dd>{children}</dd></div>;
}
