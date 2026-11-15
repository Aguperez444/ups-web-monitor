import type { Current, MetricKey, Mode } from "../lib/telemetry";
import { chargerLabels, metrics, modes } from "../lib/telemetry";
import { Icon, MetricValue, ModePill, ReadingRow, type IconName } from "./monitor-ui";

const overview: { metric: MetricKey; icon: IconName; accent: string }[] = [
  { metric: "input_voltage", icon: "line", accent: "mint" },
  { metric: "output_voltage", icon: "output", accent: "blue" },
  { metric: "battery_charge", icon: "battery", accent: "violet" },
  { metric: "load_percent", icon: "load", accent: "amber" },
];

function Station({ place, icon, name, description }: {
  place: string; icon: IconName; name: string; description?: string;
}) {
  return (
    <div className={`station station-${place}`}>
      <span className="station-tile"><Icon name={icon} /></span>
      <span className="station-label">
        <strong>{name}</strong>
        {description && <small>{description}</small>}
      </span>
    </div>
  );
}

function FlowSchematic({ data, stale }: { data: Current | null; stale: boolean }) {
  const mode: Mode = stale || !data ? "unknown" : data.mode;
  const outputAtZero = !stale && data?.output_voltage === 0;
  const charging = !stale && data?.charger === "charging" && mode !== "battery";
  const batteryPath = mode === "battery" ? "discharging" : charging ? "charging" : "idle";
  const description = stale
    ? "Estado actual sin confirmar. Se conserva la última lectura recibida."
    : {
      line: "NUT reporta alimentación de red.",
      battery: "NUT reporta funcionamiento con batería.",
      bypass: "NUT informa que el UPS está en bypass.",
      off: "NUT informa que la salida del UPS está apagada.",
      unknown: "El flujo se activa cuando NUT informa el modo del UPS.",
    }[mode];
  const flowDescription = outputAtZero && mode !== "off" ? `${description} Salida a 0 V.` : description;
  const batteryDescription = !stale && data?.charger ? chargerLabels[data.charger] : undefined;

  return (
    <section className="panel flow-panel" aria-labelledby="schematic-title">
      <header className="panel-header">
        <div>
          <h2 id="schematic-title">Ruta de alimentación</h2>
          <p>{flowDescription}</p>
        </div>
        {data && !stale && <ModePill mode={mode} />}
      </header>
      <div className={`schematic flow-${mode} battery-${batteryPath}${outputAtZero ? " output-zero" : ""}`} role="group" aria-label={`Diagrama eléctrico. ${flowDescription}`}>
        <div className="wire wire-bypass" aria-hidden="true"><i /></div>
        <div className="wire wire-input" aria-hidden="true"><i /></div>
        <div className="wire wire-output" aria-hidden="true"><i /></div>
        <div className="wire wire-battery" aria-hidden="true"><i /></div>
        <span className="bypass-label">Bypass</span>
        <Station place="input" icon="line" name="Entrada AC" />
        <Station place="converter" icon="chip" name="UPS" description="Conversión AC ↔ DC" />
        <Station place="output" icon="output" name="Salida AC" />
        <Station place="battery" icon="battery" name="Batería" description={batteryDescription} />
      </div>
      <div className="flow-legend">
        <span><i className="legend-line" /> Ruta activa</span>
        <span><i className="legend-line battery-line" /> Flujo de batería</span>
        <span><i className="legend-line inactive-line" /> Sin flujo confirmado</span>
      </div>
    </section>
  );
}

export function PowerFlow({ data, stale }: { data: Current | null; stale: boolean }) {
  return (
    <>
      <section className="panel overview-grid" aria-label="Lecturas principales">
        {overview.map(({ metric, icon, accent }) => (
          <div className={`overview-reading accent-${accent}`} key={metric}>
            <h2 className="overview-label"><Icon name={icon} />{metrics[metric].label}</h2>
            <div className="primary-number"><MetricValue metric={metric} value={data?.[metric]} /></div>
          </div>
        ))}
      </section>
      <div className="flow-layout">
        <FlowSchematic data={data} stale={stale} />
        <section className="panel detail-panel" aria-labelledby="detail-title">
          <header className="panel-header">
            <h2 id="detail-title">Lecturas del UPS</h2>
            <span className="icon-tile accent-mint"><Icon name="info" /></span>
          </header>
          <dl>
            <ReadingRow label="Modo de operación">{data ? modes[data.mode] : "—"}</ReadingRow>
            <ReadingRow label="Estado NUT">{data?.status ? <code>{data.status}</code> : "—"}</ReadingRow>
            <ReadingRow label={metrics.output_frequency.label}>
              <MetricValue metric="output_frequency" value={data?.output_frequency} />
            </ReadingRow>
            <ReadingRow label={metrics.battery_voltage.label}>
              <MetricValue metric="battery_voltage" value={data?.battery_voltage} />
            </ReadingRow>
            <ReadingRow label="Cargador">{data?.charger ? chargerLabels[data.charger] : "—"}</ReadingRow>
          </dl>
        </section>
      </div>
    </>
  );
}
