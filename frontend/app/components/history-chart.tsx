"use client";

import {
  Chart, Filler, LineController, LineElement, LinearScale, PointElement, Tooltip,
  type ChartConfiguration,
} from "chart.js";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { historyYBounds } from "../lib/history-scale";
import { formatMetric, metrics, type History, type MetricKey } from "../lib/telemetry";
import { MetricValue } from "./monitor-ui";

Chart.register(LineController, LineElement, PointElement, LinearScale, Filler, Tooltip);

type Point = { x: number; y: number | null };
type LineChart = Chart<"line", Point[]>;
const tooltipTime = new Intl.DateTimeFormat("es-AR", { dateStyle: "medium", timeStyle: "medium" });

function buildPoints(history: History, metric: MetricKey): Point[] {
  const points: Point[] = [];
  const maxGap = (history.sample_interval_seconds * 2.5 + (history.bucket_seconds ?? 0) * 2) * 1000;
  for (const sample of history.samples) {
    const x = Date.parse(sample.timestamp);
    const last = points.at(-1);
    if (last && x - last.x > maxGap) points.push({ x: (last.x + x) / 2, y: null });
    points.push({ x, y: sample[metric] });
  }
  return points;
}

function chartConfig(history: History, metric: MetricKey, points: Point[]): ChartConfiguration<"line", Point[]> {
  const { color, unit } = metrics[metric];
  const start = Date.parse(history.start);
  const end = Date.parse(history.end);
  const duration = end - start;
  const axisTime = new Intl.DateTimeFormat("es-AR", {
    ...(duration > 86400000 ? { month: "numeric", day: "numeric" } : {}),
    hour: "2-digit", minute: "2-digit",
    ...(duration < 300000 ? { second: "2-digit" } : {}),
    hour12: false,
  });

  return {
    type: "line",
    data: {
      datasets: [{
        data: points,
        borderColor: color,
        borderWidth: 2,
        backgroundColor: `${color}19`,
        fill: true,
        pointRadius: ({ dataIndex }) => {
          const point = points[dataIndex];
          return point && point.y !== null && points[dataIndex - 1]?.y == null && points[dataIndex + 1]?.y == null ? 2.5 : 0;
        },
        pointHoverRadius: 4,
        spanGaps: false,
      }],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      layout: { padding: { right: 8 } },
      scales: {
        x: {
          type: "linear", min: start, max: end,
          ticks: {
            color: "#a1afc2", font: { size: 11 },
            maxRotation: 0, maxTicksLimit: 5,
            callback: value => axisTime.format(Number(value)),
          },
          grid: { color: "#212c3c", borderColor: "#354256" },
        },
        y: {
          type: "linear", ...historyYBounds(metric, points),
          ticks: { color: "#a1afc2", font: { size: 11 }, maxTicksLimit: 5 },
          grid: { color: "#253144", borderColor: "#354256" },
        },
      },
      plugins: {
        tooltip: {
          displayColors: false,
          backgroundColor: "#090e18",
          borderColor: "#506077",
          borderWidth: 1,
          padding: 10,
          callbacks: {
            title: items => items.length ? tooltipTime.format(items[0].parsed.x) : "",
            label: item => `${formatMetric(metric, item.parsed.y)} ${unit}`,
          },
        },
      },
    },
  };
}

export function HistoryChart({ metric, history, live, stale }: {
  metric: MetricKey;
  history: History;
  live: number | null | undefined;
  stale: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const instance = useRef<LineChart>(null);
  const [selection, setSelection] = useState<{ metric: MetricKey; timestamp: number } | null>(null);
  const points = useMemo(() => buildPoints(history, metric), [history, metric]);
  const hasData = points.some(point => point.y !== null);
  const selected = selection?.metric === metric ? points.find(point => point.x === selection.timestamp) : undefined;
  const { label, unit, color } = metrics[metric];

  useEffect(() => {
    if (!hasData || !canvas.current) {
      instance.current?.destroy();
      instance.current = null;
      return;
    }
    const config = chartConfig(history, metric, points);
    if (instance.current) {
      instance.current.data = config.data;
      instance.current.options = config.options ?? {};
      instance.current.update();
    } else {
      instance.current = new Chart(canvas.current, config);
    }
  }, [history, hasData, metric, points]);

  useEffect(() => () => {
    instance.current?.destroy();
    instance.current = null;
  }, []);

  function move(event: KeyboardEvent<HTMLCanvasElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const valid = points.filter(point => point.y !== null);
    const position = selected ? valid.indexOf(selected) : -1;
    const next = position < 0 ? 0 : Math.max(0, Math.min(valid.length - 1, position + (event.key === "ArrowLeft" ? -1 : 1)));
    const point = valid[next];
    if (point) setSelection({ metric, timestamp: point.x });
  }

  return (
    <section className="panel chart-panel" style={{ "--chart-color": color } as CSSProperties}>
      <header className="chart-header">
        <h2><i aria-hidden="true" />{label}</h2>
        <div className="chart-current">
          <span>{stale && live != null ? "Última lectura" : "Valor actual"}</span>
          <strong className="primary-number"><MetricValue metric={metric} value={live} /></strong>
        </div>
      </header>
      {hasData ? (
        <div className="chart-canvas">
          <canvas
            ref={canvas}
            role="img"
            aria-label={`${label} en ${unit}. Usá las flechas del teclado para recorrer las muestras.`}
            tabIndex={0}
            onKeyDown={move}
            onBlur={() => setSelection(null)}
          />
          <div className={selected?.y == null ? "sr-only" : "chart-selection"} aria-live="polite">
            {selected?.y == null ? "" : `${tooltipTime.format(selected.x)} · ${formatMetric(metric, selected.y)} ${unit}`}
          </div>
        </div>
      ) : <div className="chart-placeholder"><p>Sin lecturas de esta métrica en el intervalo.</p></div>}
    </section>
  );
}
