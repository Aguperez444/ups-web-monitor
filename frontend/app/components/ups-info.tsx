"use client";

import { useState, type CSSProperties } from "react";
import { chargerLabels, metrics, modes, type Current, type MetricKey } from "../lib/telemetry";
import { Icon, MetricValue, ReadingRow, type IconName } from "./monitor-ui";

const sections = [
  { id: "input", title: "Información de entrada", icon: "line", keys: ["input_voltage"] },
  { id: "ups", title: "Información del UPS", icon: "chip", keys: ["input_voltage", "output_voltage"] },
  { id: "battery", title: "Información de batería", icon: "battery", keys: ["battery_voltage", "battery_charge"] },
  { id: "output", title: "Información de salida", icon: "output", keys: ["output_voltage", "output_frequency", "load_percent"] },
] satisfies { id: string; title: string; icon: IconName; keys: MetricKey[] }[];

function Gauge({ metric, data, accent, icon }: {
  metric: "battery_charge" | "load_percent"; data: Current | null; accent: string; icon: IconName;
}) {
  const value = data?.[metric];
  const shown = Math.min(100, Math.max(0, value ?? 0));
  const note = value == null ? "Sin lectura" : value > 100 ? "Por encima del límite nominal" : null;

  return (
    <section className={`panel gauge-panel accent-${accent}`}>
      <header className="panel-header">
        <h2>{metrics[metric].label}</h2>
        <span className="icon-tile"><Icon name={icon} /></span>
      </header>
      <div className="gauge" style={{ "--gauge-progress": `${shown * 0.75}%` } as CSSProperties}>
        <div className="gauge-center">
          <div className="primary-number"><MetricValue metric={metric} value={value} /></div>
          {note && <span>{note}</span>}
        </div>
      </div>
      <div className="gauge-scale" aria-hidden="true"><span>0%</span><span>100%</span></div>
    </section>
  );
}

export function UpsInfo({ data }: { data: Current | null }) {
  const [open, setOpen] = useState<string[]>(["ups"]);
  const allExpanded = open.length === sections.length;

  function toggle(id: string) {
    setOpen(previous => previous.includes(id) ? previous.filter(item => item !== id) : [...previous, id]);
  }

  return (
    <div className="info-layout">
      <div className="gauges">
        <Gauge metric="battery_charge" data={data} accent="violet" icon="battery" />
        <Gauge metric="load_percent" data={data} accent="amber" icon="load" />
      </div>
      <section className="panel information-panel" aria-labelledby="information-title">
        <header className="panel-header">
          <h2 id="information-title">Datos del equipo</h2>
          <button type="button" className="secondary-button" onClick={() => setOpen(allExpanded ? [] : sections.map(({ id }) => id))}>
            {allExpanded ? "Contraer todo" : "Expandir todo"}
          </button>
        </header>
        {sections.map(({ id, title, icon, keys }) => {
          const expanded = open.includes(id);
          return (
            <div className="information-section" key={id}>
              <h3>
                <button type="button" id={`button-${id}`} aria-expanded={expanded} aria-controls={`values-${id}`} onClick={() => toggle(id)}>
                  <span className="icon-tile"><Icon name={icon} /></span>{title}<span aria-hidden="true" className="chevron" />
                </button>
              </h3>
              <div id={`values-${id}`} hidden={!expanded}>
                <dl>
                  {keys.map(key => (
                    <ReadingRow key={key} label={metrics[key].label}>
                      <MetricValue metric={key} value={data?.[key]} />
                    </ReadingRow>
                  ))}
                  {id === "ups" && <>
                    <ReadingRow label="Identificador NUT">{data?.ups_name ?? "—"}</ReadingRow>
                    <ReadingRow label="Fabricante">{data?.manufacturer ?? "—"}</ReadingRow>
                    <ReadingRow label="Modelo">{data?.model ?? "—"}</ReadingRow>
                    <ReadingRow label="Modo de operación">{data ? modes[data.mode] : "—"}</ReadingRow>
                    <ReadingRow label="Estado NUT">{data?.status ? <code>{data.status}</code> : "—"}</ReadingRow>
                  </>}
                  {id === "battery" && <ReadingRow label="Cargador">{data?.charger ? chargerLabels[data.charger] : "—"}</ReadingRow>}
                </dl>
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
