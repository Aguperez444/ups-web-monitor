"use client";

import { useState } from "react";
import { Diagram } from "./components/diagram";
import { Icon } from "./components/monitor-ui";
import { PowerFlow } from "./components/power-flow";
import { UpsInfo } from "./components/ups-info";
import { formatClock, type Current } from "./lib/telemetry";
import { usePollJson } from "./lib/use-poll-json";

const views = [
  { id: "flow", title: "Flujo eléctrico", icon: "flow" },
  { id: "info", title: "Información UPS", icon: "info" },
  { id: "chart", title: "Historial", icon: "chart" },
] as const;

type View = (typeof views)[number]["id"];

export default function Home() {
  const [selected, setSelected] = useState<View>("flow");
  const { data, error, loading } = usePollJson<Current>("/api/ups/current", 2000);
  const view = views.find(view => view.id === selected) ?? views[0];
  const device = data?.model ? [data.manufacturer, data.model].filter(Boolean).join(" ") : data?.ups_name;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><i /></span>
          <div><strong>UPS Monitor</strong><span>Network UPS Tools</span></div>
        </div>
        <nav aria-label="Vistas del monitor">
          {views.map(item => (
            <button
              key={item.id}
              type="button"
              aria-current={item.id === selected ? "page" : undefined}
              onClick={() => setSelected(item.id)}
            >
              <Icon name={item.icon} /> <span>{item.title}</span>
            </button>
          ))}
        </nav>
        <footer className="sidebar-footer">
          <span className="icon-tile"><Icon name="chip" /></span>
          <div><strong>{device ?? "Equipo NUT"}</strong><span>{device && device !== data?.ups_name ? data?.ups_name : "UPS supervisado"}</span></div>
        </footer>
      </aside>
      <main className="workspace">
        <div className="workspace-content">
          <header className="view-header">
            <h1>{view.title}</h1>
            {data && (
              <div className="last-update">
                <Icon name="time" />
                <span>{error ? "Última lectura" : "Actualizado"} <time dateTime={data.timestamp}>{formatClock(data.timestamp)}</time></span>
              </div>
            )}
          </header>
          {error && (
            <div className="notice notice-warning" role="alert">
              <strong>{data ? "Los datos en vivo están desactualizados." : "La lectura en vivo del UPS no está disponible."}</strong>
              <span>{error} Se reintentará automáticamente.</span>
            </div>
          )}
          {loading && <p className="notice" role="status">Consultando el UPS…</p>}
          {selected === "flow" && <PowerFlow data={data} stale={Boolean(error)} />}
          <div hidden={selected !== "info"}><UpsInfo data={data} /></div>
          <div hidden={selected !== "chart"}><Diagram current={data} active={selected === "chart"} stale={Boolean(error)} /></div>
        </div>
      </main>
    </div>
  );
}
