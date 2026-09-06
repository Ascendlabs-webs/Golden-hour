/**
 * Centralised backend access — no fetch() calls scattered in components.
 * All functions degrade gracefully: callers decide fallback behaviour.
 */
const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

async function req(path, opts = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout || 15000);
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...opts,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${text || res.statusText}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export const apiBase = () => BASE;

export const getHealth = () => req("/api/health");
export const getConfig = () => req("/api/config");
export const getZones = (tMin = 0) => req(`/api/zones?t_min=${tMin}`);
export const getZone = (id, tMin = 0) => req(`/api/zones/${id}?t_min=${tMin}`);
export const getGeoJSON = (mode = "priority", tMin = 0) =>
  req(`/api/zones/geojson?mode=${mode}&t_min=${tMin}`);
export const getProjections = () => req("/api/zones/projections");
export const getReports = (status = "All", sort = "confidence") =>
  req(`/api/reports?status=${encodeURIComponent(status)}&sort=${sort}`);
export const createReport = (payload) =>
  req("/api/reports", { method: "POST", body: JSON.stringify(payload) });
export const getTeams = () => req("/api/teams");
export const dispatchTeam = (id, zoneId = null) =>
  req(`/api/teams/${id}/dispatch`, {
    method: "POST",
    body: JSON.stringify(zoneId ? { zone_id: zoneId } : {}),
  });
export const overrideZone = (id, overridden) =>
  req(`/api/zones/${id}/override`, {
    method: "POST",
    body: JSON.stringify({ overridden }),
  });
export const getAnalytics = () => req("/api/analytics");
export const getAudit = (limit = 20) => req(`/api/audit?limit=${limit}`);
export const getStatus = () => req("/api/status");
export const verifyReport = (id, verifier = "operator") =>
  req(`/api/reports/${id}/verify`, {
    method: "POST",
    body: JSON.stringify({ verifier }),
  });
export const satelliteSearch = (payload) =>
  req("/api/satellite/search", { method: "POST", body: JSON.stringify(payload) });
export const runFloodAnalysis = (payload = {}) =>
  req("/api/analysis/flood", { method: "POST", body: JSON.stringify(payload) });
export const getSatelliteProducts = () => req("/api/satellite/products");
export const previewUrl = (productId) => `${BASE}/api/satellite/preview/${productId}`;
export const getStudyAreas = () => req("/api/study-areas");
export const activateStudyArea = (name) =>
  req(`/api/study-areas/${encodeURIComponent(name)}/activate`, { method: "POST" });

export const wsUrl = () =>
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${new URL(BASE).host}/ws/updates`;
export const getDataSources = () => req("/api/data-sources");
export const refreshData = (mode = "demo") =>
  req(`/api/ingest/refresh?mode=${mode}`, { method: "POST" });
