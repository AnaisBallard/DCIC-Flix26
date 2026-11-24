import { Activity, ArrowLeft, ChevronDown, Database, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getAuditRunDetails,
  getAuditRuns,
  getHealth,
  getSystemStatus,
  type AuditDetail,
  type AuditRun,
  type SystemStatus,
} from "../services/api";

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function formatStatus(value: string): string {
  return value.replace(/[_.]/g, " ");
}

function MetricList({ metrics }: { metrics?: Record<string, number> }) {
  const entries = Object.entries(metrics ?? {}).sort(([left], [right]) =>
    left.localeCompare(right),
  );
  if (entries.length === 0) {
    return <p className="audit-metrics-empty">No se registraron cambios.</p>;
  }
  return (
    <div className="audit-metrics">
      {entries.map(([name, count]) => (
        <div className="audit-metric" key={name}>
          <span>{formatStatus(name)}</span>
          <strong>{count}</strong>
        </div>
      ))}
    </div>
  );
}

export function AuditPage() {
  const [services, setServices] = useState<Record<string, string> | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [runs, setRuns] = useState<AuditRun[]>([]);
  const [details, setDetails] = useState<Record<string, AuditDetail[]>>({});
  const [detailTotals, setDetailTotals] = useState<Record<string, number>>({});
  const [selectedRun, setSelectedRun] = useState("");
  const [error, setError] = useState("");
  const [detailsLoading, setDetailsLoading] = useState("");

  const refresh = useCallback(async () => {
    const [healthResult, statusResult, auditResult] = await Promise.allSettled([
      getHealth(),
      getSystemStatus(),
      getAuditRuns(),
    ]);
    if (healthResult.status === "fulfilled") {
      setServices(healthResult.value.services);
    }
    if (statusResult.status === "fulfilled") {
      setStatus(statusResult.value);
    }
    if (auditResult.status === "fulfilled") {
      setRuns(auditResult.value.items);
    }
    const failure = [healthResult, statusResult, auditResult].find(
      (result) => result.status === "rejected",
    );
    setError(
      failure?.status === "rejected"
        ? failure.reason instanceof Error
          ? failure.reason.message
          : "No se pudo cargar el informe."
        : "",
    );
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 10000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  async function toggleDetails(runId: string) {
    if (selectedRun === runId) {
      setSelectedRun("");
      return;
    }
    setSelectedRun(runId);
    if (details[runId]) return;
    setDetailsLoading(runId);
    try {
      const result = await getAuditRunDetails(runId);
      setDetails((current) => ({ ...current, [runId]: result.items }));
      setDetailTotals((current) => ({ ...current, [runId]: result.total }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudieron cargar los cambios.");
    } finally {
      setDetailsLoading("");
    }
  }

  async function loadMoreDetails(runId: string) {
    const offset = details[runId]?.length ?? 0;
    setDetailsLoading(runId);
    try {
      const result = await getAuditRunDetails(runId, 50, offset);
      setDetails((current) => ({
        ...current,
        [runId]: [...(current[runId] ?? []), ...result.items],
      }));
      setDetailTotals((current) => ({ ...current, [runId]: result.total }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudieron cargar más cambios.");
    } finally {
      setDetailsLoading("");
    }
  }

  const cleaningStatus = status?.catalog.cleaning_status ?? "desconocido";
  const recommendationStatus = status?.recommendations.status ?? "desconocido";
  const latestRun = runs[0];

  return (
    <main className="audit-page">
      <div className="audit-intro">
        <Link className="audit-back" to="/">
          <ArrowLeft size={15} /> Volver a DCIC-Flix
        </Link>
        <p className="eyebrow">ZONA DE OBSERVACIÓN · AUDITORÍA</p>
        <h1>El lado de<br /><em>los datos.</em></h1>
        <p>Estado durable del catálogo, correcciones verificables e intervenciones del modelo.</p>
      </div>

      <section className="audit-status">
        <div className="audit-card-heading">
          <Activity size={19} />
          <div><span>ESTADO DE LOS SERVICIOS</span><small>Salud de proceso y estado del pipeline</small></div>
        </div>
        {services ? (
          <div className="service-status-grid">
            {Object.entries(services).map(([name, serviceStatus]) => (
              <div className="service-status" key={name}>
                <span className={serviceStatus === "ok" ? "service-dot is-ok" : "service-dot"} />
                <span>{name}</span><strong>{serviceStatus}</strong>
              </div>
            ))}
          </div>
        ) : <p className="audit-loading">Consultando estado…</p>}
        {status && (
          <div className="pipeline-status-grid">
            <div><span>CATÁLOGO</span><strong>{formatStatus(cleaningStatus)}</strong></div>
            <div><span>RECOMENDACIONES</span><strong>{formatStatus(recommendationStatus)}</strong></div>
            <div><span>CRÍTICAS</span><strong>{status.capabilities.reviews ? "disponibles" : "pausadas"}</strong></div>
            <div><span>ÍNDICE</span><strong>{status.capabilities.recommendations ? "disponible" : "no disponible"}</strong></div>
          </div>
        )}
        {status?.catalog.error_code && (
          <p className="audit-error">Error del catálogo: {status.catalog.error_code}</p>
        )}
        {error && <p className="audit-error">{error}</p>}
      </section>

      <section className="audit-unavailable-grid">
        <article className="audit-info-card">
          <span className="audit-card-icon"><Database size={19} /></span>
          <span className="audit-card-label">CALIDAD DE DATOS</span>
          <strong>{latestRun ? `${latestRun.movies_examined ?? 0} películas` : "Sin informe todavía"}</strong>
          <p>
            {latestRun
              ? `${latestRun.reviews_examined ?? 0} críticas examinadas. Ejecución: ${latestRun.status}.`
              : "Las métricas aparecerán tras finalizar la primera ejecución del catálogo."}
          </p>
          {latestRun && (
            <div className="audit-metric-breakdown">
              <span className="audit-card-label">CAMBIOS POR CATEGORÍA</span>
              <MetricList metrics={latestRun.metrics} />
            </div>
          )}
          <span className="audit-badge">
            <Database size={13} />
            {latestRun ? `${Object.values(latestRun.metrics ?? {}).reduce((sum, count) => sum + count, 0)} cambios auditados` : formatStatus(cleaningStatus)}
          </span>
        </article>
        <article className="audit-info-card audit-info-card--lilac">
          <span className="audit-card-icon"><Sparkles size={19} /></span>
          <span className="audit-card-label">INTERVENCIONES DEL LLM</span>
          <strong>{latestRun ? `${latestRun.llm_inferences ?? 0} ratings` : "Sin intervenciones"}</strong>
          <p>
            {latestRun
              ? `${latestRun.unresolved_ratings ?? latestRun.llm_unresolved ?? 0} ratings sin resolver (${latestRun.llm_unresolved ?? 0} por confianza baja). No se envían identificadores ni correos al proveedor.`
              : "Las inferencias ambiguas se registrarán con confianza y explicación, sin datos de identidad."}
          </p>
          <span className="audit-badge">
            <Sparkles size={13} />
            {latestRun ? "Solo casos ambiguos" : "Esperando limpieza"}
          </span>
        </article>
      </section>

      <section className="audit-runs">
        <div className="audit-card-heading">
          <Database size={19} />
          <div><span>HISTORIAL Y TRAZABILIDAD</span><small>Valores antes/después paginados por ejecución</small></div>
        </div>
        {runs.length === 0 ? (
          <p className="audit-loading">Todavía no hay ejecuciones de limpieza registradas.</p>
        ) : runs.map((run) => (
          <div className="audit-run" key={run.run_id}>
            <button className="audit-run-toggle" onClick={() => void toggleDetails(run.run_id)}>
              <span><strong>{formatStatus(run.status)}</strong><small>{new Date(run.started_at).toLocaleString()}</small></span>
              <span>{run.llm_inferences ?? 0} LLM · {Object.values(run.metrics ?? {}).reduce((sum, count) => sum + count, 0)} cambios</span>
              <ChevronDown size={16} className={selectedRun === run.run_id ? "is-expanded" : ""} />
            </button>
            {selectedRun === run.run_id && (
              <div className="audit-details">
                {detailsLoading === run.run_id ? (
                  <p className="audit-loading">Cargando cambios…</p>
                ) : (
                  <>
                    <div className="audit-run-metrics">
                      <span className="audit-card-label">MÉTRICAS DE LA EJECUCIÓN</span>
                      <MetricList metrics={run.metrics} />
                    </div>
                    {details[run.run_id]?.length
                      ? details[run.run_id].map((detail) => (
                        <article
                          className="audit-detail"
                          key={`${detail.entity_id}-${detail.category}-${detail.field}`}
                        >
                          <div>
                            <strong>{formatStatus(detail.category)}</strong>
                            <small>
                              {detail.collection} · {detail.entity_id} · {detail.field} · {detail.method}
                            </small>
                          </div>
                          <p>{detail.reason}</p>
                          <div className="audit-before-after">
                            <span><b>Antes</b>{displayValue(detail.before)}</span>
                            <span><b>Después</b>{displayValue(detail.after)}</span>
                          </div>
                          {Object.keys(detail.evidence ?? {}).length > 0 && (
                            <details className="audit-evidence">
                              <summary>Evidencia</summary>
                              <pre>{displayValue(detail.evidence)}</pre>
                            </details>
                          )}
                        </article>
                      ))
                      : <p className="audit-loading">No hay cambios para mostrar.</p>}
                  </>
                )}
                {(details[run.run_id]?.length ?? 0) < (detailTotals[run.run_id] ?? 0) && (
                  <button className="audit-load-more" disabled={detailsLoading === run.run_id} onClick={() => void loadMoreDetails(run.run_id)}>
                    {detailsLoading === run.run_id ? "Cargando…" : "Cargar más cambios"}
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </section>
      <p className="audit-footnote">
        Huella del catálogo: {status?.catalog.source_fingerprint ?? "no disponible"} · Los resultados no se inventan ni se marcan listos antes de tiempo.
      </p>
    </main>
  );
}
