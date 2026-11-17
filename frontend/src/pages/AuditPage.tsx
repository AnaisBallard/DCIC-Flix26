import { Activity, ArrowLeft, CircleHelp, Database, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHealth } from "../services/api";

export function AuditPage() {
  const [services, setServices] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getHealth().then((result) => setServices(result.services)).catch((reason: Error) => setError(reason.message));
  }, []);
  return (
    <main className="audit-page">
      <div className="audit-intro"><Link className="audit-back" to="/"><ArrowLeft size={15} /> Volver a DCIC-Flix</Link><p className="eyebrow">ZONA DE OBSERVACIÓN · NO PÚBLICA</p><h1>El lado de<br /><em>los datos.</em></h1><p>Un espacio para entender cómo está el sistema. Los informes de limpieza aparecerán cuando esa etapa esté conectada.</p></div>
      <section className="audit-status">
        <div className="audit-card-heading"><Activity size={19} /><div><span>ESTADO DE LOS SERVICIOS</span><small>Comprobación real de la gateway</small></div></div>
        {error ? <p className="audit-error">{error}</p> : services ? <div className="service-status-grid">{Object.entries(services).map(([name, status]) => <div className="service-status" key={name}><span className={status === "ok" ? "service-dot is-ok" : "service-dot"} /><span>{name}</span><strong>{status}</strong></div>)}</div> : <p className="audit-loading">Consultando estado…</p>}
      </section>
      <section className="audit-unavailable-grid">
        <article className="audit-info-card"><span className="audit-card-icon"><Database size={19} /></span><span className="audit-card-label">CALIDAD DE DATOS</span><strong>Sin informe todavía</strong><p>Las anomalías, correcciones y comparaciones antes/después no están expuestas por una API en este momento.</p><span className="audit-badge"><CircleHelp size={13} /> Datos no disponibles</span></article>
        <article className="audit-info-card audit-info-card--lilac"><span className="audit-card-icon"><Sparkles size={19} /></span><span className="audit-card-label">INTERVENCIONES DEL LLM</span><strong>Etapa en preparación</strong><p>El agente de limpieza aún no ofrece estadísticas ni historial de intervenciones para mostrar.</p><span className="audit-badge"><CircleHelp size={13} /> Sin intervenciones registradas</span></article>
      </section>
      <p className="audit-footnote">No mostramos cifras de ejemplo: cuando exista información real, aparecerá aquí.</p>
    </main>
  );
}
