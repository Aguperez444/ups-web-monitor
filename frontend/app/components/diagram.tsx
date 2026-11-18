"use client";

import { useRef, useState, type FormEvent } from "react";
import { metrics, type Current, type History, type MetricKey } from "../lib/telemetry";
import { usePollJson } from "../lib/use-poll-json";
import { HistoryChart } from "./history-chart";
import { Icon } from "./monitor-ui";

const chartMetrics: MetricKey[] = ["input_voltage", "output_voltage", "output_frequency", "load_percent", "battery_voltage"];
const presets = [
  { minutes: 15, label: "15 min" }, { minutes: 30, label: "30 min" },
  { minutes: 60, label: "1 h" }, { minutes: 180, label: "3 h" },
  { minutes: 360, label: "6 h" }, { minutes: 600, label: "10 h" },
  { minutes: 1440, label: "24 h" }, { minutes: 10080, label: "7 d" },
];

const formatInterval = new Intl.DateTimeFormat("es-AR", { dateStyle: "short", timeStyle: "short" });

type Interval = { minutes: number } | { start: string; end: string };

export function Diagram({ current, active, stale }: { current: Current | null; active: boolean; stale: boolean }) {
  const [interval, setInterval] = useState<Interval>({ minutes: 60 });
  const [custom, setCustom] = useState(false);
  const [customError, setCustomError] = useState<string | null>(null);
  const [selected, setSelected] = useState(chartMetrics);
  const customButton = useRef<HTMLButtonElement>(null);

  const rolling = "minutes" in interval;
  const chosenDates = rolling ? null : formatInterval.formatRange(new Date(interval.start), new Date(interval.end));
  const query = new URLSearchParams(rolling ? { window_minutes: String(interval.minutes) } : interval);
  const { data, error, loading, retry } = usePollJson<History>(
    active ? `/api/metrics?${query.toString()}` : null,
    rolling ? 10000 : 0,
  );

  function changeMetric(key: MetricKey) {
    setSelected(previous => previous.includes(key) ? previous.filter(metric => metric !== key) : [...previous, key]);
  }

  function applyCustom(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const start = new Date(String(fields.get("start")));
    const end = new Date(String(fields.get("end")));
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) {
      setCustomError("Ingresá un inicio anterior al fin del intervalo.");
      return;
    }
    setCustomError(null);
    setCustom(false);
    customButton.current?.focus();
    const next = { start: start.toISOString(), end: end.toISOString() };
    if (!rolling && interval.start === next.start && interval.end === next.end) {
      retry();
    } else {
      setInterval(next);
    }
  }

  const visibleMetrics = chartMetrics.filter(key => selected.includes(key));

  return (
    <>
      <section className="panel history-controls" aria-label="Filtros de historial">
        <div className="history-toolbar">
          <div className="control-label"><Icon name="time" /><strong>Intervalo</strong></div>
          <div className="segments" role="group" aria-label="Intervalo temporal">
            {presets.map(({ minutes, label }) => (
              <button
                type="button"
                key={minutes}
                aria-pressed={rolling && interval.minutes === minutes}
                onClick={() => { setCustom(false); setCustomError(null); setInterval({ minutes }); }}
              >
                {label}
              </button>
            ))}
            <button
              type="button"
              ref={customButton}
              aria-expanded={custom}
              aria-controls="custom-interval"
              aria-describedby={chosenDates ? "chosen-dates" : undefined}
              data-selected={!rolling || undefined}
              onClick={() => setCustom(!custom)}
            >
              Personalizado
            </button>
          </div>
          {chosenDates && <span className="chosen-dates" id="chosen-dates">{chosenDates}</span>}
        </div>
        <form className="custom-interval" id="custom-interval" hidden={!custom} onSubmit={applyCustom}>
          <label htmlFor="history-start">Desde <input type="datetime-local" name="start" id="history-start" required /></label>
          <label htmlFor="history-end">Hasta <input type="datetime-local" name="end" id="history-end" required /></label>
          <button type="submit" className="primary-button">Aplicar</button>
          <p className="local-time">Fechas en hora local.</p>
          {customError && <p className="custom-error" role="alert">{customError}</p>}
        </form>
        <div className="metric-filters" role="group" aria-label="Métricas visibles">
          <strong>Métricas</strong>
          {chartMetrics.map(key => (
            <label key={key}>
              <input type="checkbox" checked={selected.includes(key)} onChange={() => changeMetric(key)} />
              {metrics[key].label}
            </label>
          ))}
        </div>
      </section>
      {error && (
        <div className="notice notice-warning" role="alert">
          <strong>{data ? "El historial no pudo actualizarse." : "No se pudo consultar el historial."}</strong>
          <span>{error} {rolling ? "Se reintentará automáticamente." : ""}</span>
          {!rolling && <button className="secondary-button" type="button" onClick={retry}>Reintentar</button>}
        </div>
      )}
      {data?.bucket_seconds != null && <p className="history-note">Selección de muestras del intervalo · Horas en zona local</p>}
      {!visibleMetrics.length && <p className="notice">Seleccioná una o más métricas para ver los gráficos.</p>}
      {visibleMetrics.length > 0 && loading && <p className="notice" role="status">Cargando historial…</p>}
      {visibleMetrics.length > 0 && data && !data.samples.length && !error && (
        <p className="notice" role="status">
          No hay muestras en este intervalo. {rolling ? "El historial se actualizará cuando se registren lecturas." : "Probá con otro rango."}
        </p>
      )}
      {visibleMetrics.length > 0 && data && data.samples.length > 0 && (
        <div className="charts-grid">
          {visibleMetrics.map(metric => (
            <HistoryChart key={metric} metric={metric} history={data} live={current?.[metric]} stale={stale} />
          ))}
        </div>
      )}
    </>
  );
}
