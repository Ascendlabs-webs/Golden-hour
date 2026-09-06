import React, { useState, useEffect, useMemo, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, Legend,
} from "recharts";
import {
  AlertTriangle, MapPin, Radio, Users, Activity, CheckCircle2, Shield, Bell,
  X, RefreshCw, Clock, Layers, Eye, EyeOff, Truck, BarChart2, Database,
  Satellite, Plus, WifiOff,
} from "lucide-react";
import MapView from "./components/MapView.jsx";
import * as api from "./services/api.js";
import { fallbackZones, fallbackTeams, fallbackGeoJSON, classify as localClassify } from "./lib/demo.js";

/* ================= constants (prototype design language preserved) ================= */
const FIELD_LABELS = {
  populationRisk: "Population Risk",
  urgency: "Urgency",
  vulnerability: "Vulnerability",
  severity: "Severity",
  confidence: "Confidence",
  accessibility: "Accessibility",
};
const CLASS_COLORS = {
  Critical: { badge: "bg-red-950 text-red-300 border border-red-700", dot: "bg-red-500" },
  High: { badge: "bg-amber-950 text-amber-300 border border-amber-700", dot: "bg-amber-400" },
  Medium: { badge: "bg-sky-950 text-sky-300 border border-sky-700", dot: "bg-sky-500" },
  Low: { badge: "bg-slate-800 text-slate-300 border border-slate-600", dot: "bg-slate-400" },
};
const PIE_COLORS = ["#34d399", "#38bdf8", "#fbbf24", "#f87171", "#94a3b8"];
const SOURCE_STATUS = {
  connected: "bg-emerald-950 text-emerald-300 border border-emerald-700",
  demo: "bg-amber-950 text-amber-300 border border-amber-700",
  unavailable: "bg-red-950 text-red-300 border border-red-700",
  disabled: "bg-slate-800 text-slate-400 border border-slate-600",
  misconfigured: "bg-amber-950 text-amber-300 border border-amber-700",
  ready: "bg-emerald-950 text-emerald-300 border border-emerald-700",
};

function timeAgo(iso) {
  if (!iso) return "unknown";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.round(m / 60)} h ago`;
}

/* ================= small UI primitives ================= */
function Badge({ label, cls }) {
  const c = CLASS_COLORS[cls] || CLASS_COLORS.Low;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium ${c.badge}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} /> {label}
    </span>
  );
}
function StatusPill({ label, status }) {
  const cls = SOURCE_STATUS[status] || SOURCE_STATUS.disabled;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border ${cls}`}>
      {label}: {status}
    </span>
  );
}
function Bar1({ label, value, tone = "bg-teal-500" }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span>{label}</span>
        <span className="text-slate-200 font-medium">{Math.round(v)}</span>
      </div>
      <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full ${tone} rounded-full`} style={{ width: `${v}%` }} />
      </div>
    </div>
  );
}
function KPI({ label, value, icon: Icon, tone }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center gap-3">
      <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${tone}`}>
        <Icon className="w-4 h-4 text-white" />
      </div>
      <div>
        <div className="text-xl font-semibold text-slate-100 leading-tight">{value}</div>
        <div className="text-xs text-slate-500">{label}</div>
      </div>
    </div>
  );
}

/* Satellite before/after previews from the latest cached analysis. */
function SatellitePreviews({ zoneId, satProducts }) {
  const latest = (satProducts?.analyses || [])[0];
  if (!latest) {
    return <div className="text-[11px] text-slate-600 mt-2">Satellite preview unavailable for this zone.</div>;
  }
  const shots = [
    ["Before", latest.s1_pre_product],
    ["After", latest.s1_product],
    ["Optical", latest.s2_product],
  ].filter(([, pid]) => pid);
  if (!shots.length) {
    return <div className="text-[11px] text-slate-600 mt-2">Satellite preview unavailable for this zone.</div>;
  }
  return (
    <div className="grid grid-cols-3 gap-2 mt-2">
      {shots.map(([label, pid]) => (
        <div key={label}>
          <div className="text-[10px] text-slate-500 mb-1">{label}</div>
          <img
            src={api.previewUrl(pid)}
            alt={`${label} satellite preview for ${zoneId}`}
            className="rounded-md border border-slate-700 w-full object-cover"
            loading="lazy"
            onError={(e) => { e.currentTarget.style.display = "none"; }}
          />
        </div>
      ))}
    </div>
  );
}

/* ================= main application ================= */
export default function GoldenHourAI() {
  const [zones, setZones] = useState([]);
  const [geojson, setGeojson] = useState(null);
  const [reports, setReports] = useState([]);
  const [teams, setTeams] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [sources, setSources] = useState([]);
  const [gee, setGee] = useState(null);
  const [audit, setAudit] = useState([]);
  const [projections, setProjections] = useState([]);
  const [weights, setWeights] = useState(null);
  const [studyArea, setStudyArea] = useState("Chennai");
  const [statusInfo, setStatusInfo] = useState(null);
  const [dataVersion, setDataVersion] = useState("");
  const [zoneDetail, setZoneDetail] = useState(null);
  const [satProducts, setSatProducts] = useState({ products: [], analyses: [] });
  const [studyAreas, setStudyAreas] = useState(null);
  const [refreshLog, setRefreshLog] = useState([]);
  const [wsLive, setWsLive] = useState(false);
  const [verifier, setVerifier] = useState("operator");

  const [backendOk, setBackendOk] = useState(true);
  const [mode, setMode] = useState("demo");
  const [lastFetch, setLastFetch] = useState(null);
  const [loading, setLoading] = useState(true);

  const [activeTab, setActiveTab] = useState("overview");
  const [selectedZoneId, setSelectedZoneId] = useState(null);
  const [mapMode, setMapMode] = useState("priority");
  const [layers, setLayers] = useState({ incidents: true, teams: true, silent: true });
  const [timeOffset, setTimeOffset] = useState(0);
  const [notifications, setNotifications] = useState([]);
  const [reportFilter, setReportFilter] = useState("All");
  const [reportSort, setReportSort] = useState("confidence");
  const [expandedReportId, setExpandedReportId] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ zone_id: "Z-020", incident_type: "Medical Emergency", description: "" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, []);

  function pushNotification(text, type = "info") {
    const id = Date.now() + Math.random();
    setNotifications((n) => [{ id, text, type }, ...n].slice(0, 4));
    setTimeout(() => setNotifications((n) => n.filter((x) => x.id !== id)), 5000);
  }

  const loadAll = useCallback(async (tMin = 0, silent = false) => {
    try {
      const [health, cfg, z, gj, reps, tm, an, ds, au, proj, st, sp, sa] = await Promise.all([
        api.getHealth(), api.getConfig(), api.getZones(tMin),
        api.getGeoJSON(mapMode, tMin), api.getReports("All", "confidence"),
        api.getTeams(), api.getAnalytics(), api.getDataSources(),
        api.getAudit(12), api.getProjections(), api.getStatus(),
        api.getSatelliteProducts().catch(() => ({ products: [], analyses: [] })),
        api.getStudyAreas().catch(() => null),
      ]);
      setBackendOk(true);
      setMode(health.mode || cfg.app_mode || "demo");
      setStudyArea(cfg.study_area?.name || health.study_area || "Chennai");
      setWeights(cfg.ghs_weights || null);
      setZones(z);
      setGeojson(gj);
      setReports(reps);
      setTeams(tm);
      setAnalytics(an);
      setSources(ds.sources || []);
      setGee(ds.gee || null);
      setAudit(au);
      setProjections(proj);
      setStatusInfo(st);
      setDataVersion(st.data_version || "");
      setSatProducts(sp);
      setStudyAreas(sa);
      setLastFetch(Date.now());
      if (!silent) setLoading(false);
    } catch (e) {
      // Backend unavailable -> deterministic offline demo, clearly labelled.
      setBackendOk(false);
      setMode("demo");
      const fz = fallbackZones();
      setZones(fz);
      setGeojson(fallbackGeoJSON(fz));
      setTeams(fallbackTeams());
      setReports([]);
      setAnalytics(null);
      setSources([]);
      setAudit([{ id: 0, text: "Backend unavailable — showing deterministic offline demo data." }]);
      setProjections(
        fz.slice(0, 6).map(() => ({ zone_id: "—", now: 0, t15: 0, t30: 0, t60: 0 }))
      );
      setLastFetch(null);
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapMode]);

  useEffect(() => {
    loadAll(0);
    // Smart polling: cheap /api/status check; full reload only when newer.
    const iv = setInterval(async () => {
      try {
        const st = await api.getStatus();
        setStatusInfo(st);
        if (st.data_version && st.data_version !== dataVersionRef.current) {
          loadAll(timeOffsetRef.current, true);
        }
        setLastFetch((lf) => lf); // keep freshness clock honest via status below
      } catch {
        setBackendOk(false);
      }
    }, 45000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // refs so the interval/WS callbacks see current values
  const dataVersionRef = React.useRef("");
  const timeOffsetRef = React.useRef(0);
  useEffect(() => { dataVersionRef.current = dataVersion; }, [dataVersion]);
  useEffect(() => { timeOffsetRef.current = timeOffset; }, [timeOffset]);

  // Fetch enriched zone detail (satellite metrics + evidence) on selection.
  useEffect(() => {
    if (selectedZoneId && backendOk) {
      api.getZone(selectedZoneId, timeOffset).then(setZoneDetail).catch(() => setZoneDetail(null));
    } else {
      setZoneDetail(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedZoneId, zones]);

  // WebSocket live updates (polling above remains as fallback).
  useEffect(() => {
    let ws = null;
    let closed = false;
    try {
      ws = new WebSocket(api.wsUrl());
      ws.onopen = () => setWsLive(true);
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (["zones_updated", "satellite_updated", "report_received",
               "team_dispatched", "override_changed"].includes(msg.event)) {
            loadAll(timeOffsetRef.current, true);
          }
        } catch { /* ignore malformed */ }
      };
      ws.onclose = () => { if (!closed) setWsLive(false); };
      ws.onerror = () => { try { ws.close(); } catch { /* polling fallback */ } };
    } catch {
      setWsLive(false);
    }
    return () => { closed = true; try { ws && ws.close(); } catch { /* noop */ } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (backendOk && zones.length) loadAll(timeOffset, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapMode, timeOffset]);

  function getClass(z) {
    return z.manual_override ? "Critical" : z.priority_class || localClassify(z.golden_hour_score || 0);
  }

  const sortedZones = useMemo(
    () => [...zones].sort((a, b) => (b.golden_hour_score || 0) - (a.golden_hour_score || 0)),
    [zones]
  );
  const criticalCount = zones.filter((z) => getClass(z) === "Critical").length;
  const activeReportsCount = reports.filter((r) => r.status !== "Potential Duplicate" && r.status !== "Duplicate").length;
  const verifiedPct = reports.length
    ? Math.round((100 * reports.filter((r) => ["High Confidence", "Human Verified"].includes(r.status)).length) / reports.length)
    : 0;
  const availableTeamsCount = teams.filter((t) => t.status === "Available").length;
  const avgETA = teams.length ? Math.round(teams.reduce((a, t) => a + (t.eta_min || 0), 0) / teams.length) : 0;
  const selectedZone = zones.find((z) => z.zone_id === selectedZoneId) || null;
  const stale = !lastFetch || Date.now() - lastFetch > 90000;

  async function handleRecalculate(live = false) {
    if (!backendOk) {
      pushNotification("Backend unavailable — cannot recalculate.", "warning");
      return;
    }
    try {
      const res = await api.refreshData(live ? "live" : "demo");
      const steps = res?.analysis?.steps || res?.steps || [];
      if (steps.length) setRefreshLog(steps.slice(-12));
      await loadAll(timeOffset, true);
      if (live) {
        const a = res?.analysis || {};
        if (a.up_to_date) {
          pushNotification("No newer satellite observation available. Existing analysis retained.", "info");
        } else if (a.ok) {
          pushNotification(`Analysis completed. ${a.zones_updated || 36} zones updated.`, "success");
        } else {
          pushNotification("Live data unavailable — previous analysis retained.", "warning");
        }
      } else {
        pushNotification("Priorities recalculated across all zones.", "success");
      }
    } catch {
      pushNotification("Recalculation failed — data temporarily unavailable.", "warning");
    }
  }

  async function handleVerify(reportId) {
    try {
      await api.verifyReport(reportId, verifier || "operator");
      await loadAll(timeOffset, true);
      pushNotification(`Report #${reportId} marked Human Verified.`, "success");
    } catch {
      pushNotification("Verification failed — backend unreachable.", "warning");
    }
  }

  async function handleOverride(zoneId) {
    const z = zones.find((x) => x.zone_id === zoneId);
    if (!z) return;
    if (!backendOk) {
      // offline: local-only toggle
      setZones((zs) => zs.map((x) => (x.zone_id === zoneId ? { ...x, manual_override: !x.manual_override, priority_class: "Critical" } : x)));
      return;
    }
    try {
      const next = !z.manual_override;
      await api.overrideZone(zoneId, next);
      await loadAll(timeOffset, true);
      pushNotification(`Zone ${zoneId} priority manually ${next ? "escalated" : "reset"}.`, "info");
    } catch {
      pushNotification("Override failed — backend unreachable.", "warning");
    }
  }

  async function handleDispatch(teamId) {
    if (!backendOk) {
      pushNotification("Backend unavailable — dispatch disabled in offline demo.", "warning");
      return;
    }
    try {
      const res = await api.dispatchTeam(teamId);
      await loadAll(timeOffset, true);
      pushNotification(`${res.name} dispatched to ${res.assigned_zone} (GHS ${res.target_ghs}).`, "success");
    } catch (e) {
      pushNotification(String(e.message || "Dispatch failed."), "warning");
    }
  }

  async function handleCreateReport(e) {
    e.preventDefault();
    if (!backendOk) {
      pushNotification("Backend unavailable — cannot submit reports.", "warning");
      return;
    }
    const z = zones.find((x) => x.zone_id === form.zone_id);
    try {
      const created = await api.createReport({
        zone_id: form.zone_id,
        incident_type: form.incident_type,
        latitude: z?.latitude || 13.04,
        longitude: z?.longitude || 80.23,
        description: form.description || `Crowdsourced report near ${z?.neighbourhood || form.zone_id}.`,
      });
      setShowForm(false);
      setForm({ ...form, description: "" });
      await loadAll(timeOffset, true);
      pushNotification(`Report #${created.report_id} received (${created.status}).`, "success");
    } catch (err) {
      pushNotification("Report submission failed.", "warning");
    }
  }

  const classCounts = ["Critical", "High", "Medium", "Low"].map((c) => ({
    name: c, count: zones.filter((z) => getClass(z) === c).length,
  }));
  const statusCounts = useMemo(() => {
    const m = {};
    reports.forEach((r) => { m[r.status] = (m[r.status] || 0) + 1; });
    return Object.entries(m).map(([name, value]) => ({ name, value }));
  }, [reports]);

  const tabs = [
    { id: "overview", label: "Overview", icon: Activity },
    { id: "map", label: "Live Map", icon: MapPin },
    { id: "incidents", label: "Incidents", icon: Radio },
    { id: "teams", label: "Rescue Teams", icon: Truck },
    { id: "analytics", label: "Analytics", icon: BarChart2 },
    { id: "sources", label: "Data Sources", icon: Database },
  ];

  const overall = !backendOk ? "unavailable-offline"
    : (statusInfo?.overall || (mode === "live" ? "stale" : "demo"));
  const modeBadge = overall === "live"
    ? { text: "LIVE DATA", cls: "bg-emerald-600 text-white" }
    : overall === "stale"
      ? { text: "STALE DATA", cls: "bg-slate-600 text-white" }
      : overall === "unavailable" || overall === "unavailable-offline"
        ? { text: "DATA UNAVAILABLE", cls: "bg-red-700 text-white" }
        : { text: "DEMO DATA", cls: "bg-amber-600 text-white" };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-200 flex items-center justify-center text-sm">
        Loading GoldenHour AI…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans">
      {/* toasts */}
      <div className="fixed top-4 right-4 z-[1000] w-80 space-y-2">
        {notifications.map((n) => (
          <div key={n.id} className="bg-slate-900 border border-slate-700 rounded-lg p-3 shadow-lg flex items-start gap-2">
            <Bell className="w-4 h-4 text-teal-400 mt-0.5 shrink-0" />
            <div className="text-xs text-slate-300 flex-1">{n.text}</div>
            <button onClick={() => setNotifications((ns) => ns.filter((x) => x.id !== n.id))} className="text-slate-500 hover:text-slate-300">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>

      {/* header */}
      <header className="border-b border-slate-800 bg-slate-950/95 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-teal-600 flex items-center justify-center font-bold text-sm">GH</div>
            <div>
              <div className="font-semibold text-sm tracking-wide">GoldenHour AI</div>
              <div className="text-[10px] text-slate-500 -mt-0.5">Disaster Intelligence &amp; Rescue Prioritization</div>
            </div>
            <span className={`ml-2 text-[10px] font-bold px-2 py-0.5 rounded ${modeBadge.cls}`}>{modeBadge.text}</span>
            {!backendOk && (
              <span className="ml-1 inline-flex items-center gap-1 text-[10px] text-amber-400">
                <WifiOff className="w-3 h-3" /> backend unavailable
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-400">
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
              </span>
              <span className="text-red-400 font-medium">{overall === "live" ? "LIVE" : "SIM"}</span>
            </div>
            <div className="flex items-center gap-1.5" title={wsLive ? "WebSocket live updates" : "Polling every 45s"}>
              <span className={`w-1.5 h-1.5 rounded-full ${wsLive ? "bg-emerald-400" : "bg-slate-500"}`} />
              <span className="hidden md:inline">{wsLive ? "ws" : "poll"}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              {new Date().toLocaleTimeString([], { hour12: false })}
            </div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-6 flex gap-1 overflow-x-auto">
          {tabs.map((t) => {
            const Icon = t.icon;
            const active = activeTab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 whitespace-nowrap ${
                  active ? "border-teal-400 text-teal-300" : "border-transparent text-slate-500 hover:text-slate-300"
                }`}
              >
                <Icon className="w-3.5 h-3.5" /> {t.label}
              </button>
            );
          })}
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {/* ================= OVERVIEW ================= */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-lg font-semibold text-slate-100">Live Disaster Response</div>
                <div className="text-sm text-slate-500">
                  {studyArea} Flood Simulation ·{" "}
                  {lastFetch ? `Last updated ${Math.round((Date.now() - lastFetch) / 1000)}s ago` : "offline demo snapshot"}
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleRecalculate(false)}
                  className="flex items-center gap-2 bg-teal-600 hover:bg-teal-500 text-white text-sm font-medium px-4 py-2 rounded-lg"
                >
                  <RefreshCw className="w-4 h-4" /> Recalculate Priorities
                </button>
                <button
                  onClick={() => handleRecalculate(true)}
                  title="Attempt live satellite/OSM refresh (falls back gracefully)"
                  className="flex items-center gap-2 border border-slate-700 hover:border-teal-500 text-slate-300 text-sm font-medium px-4 py-2 rounded-lg"
                >
                  <Satellite className="w-4 h-4" /> Live Refresh
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <KPI label="Critical Zones" value={criticalCount} icon={AlertTriangle} tone="bg-red-600" />
              <KPI label="Active Reports" value={activeReportsCount} icon={Radio} tone="bg-sky-600" />
              <KPI label="Blocked Roads (est.)" value={analytics?.blocked_roads_estimate ?? "—"} icon={MapPin} tone="bg-amber-600" />
              <KPI label="Available Teams" value={availableTeamsCount} icon={Truck} tone="bg-teal-600" />
              <KPI label="High-Conf. Reports" value={`${verifiedPct}%`} icon={CheckCircle2} tone="bg-emerald-600" />
              <KPI label="Avg Response ETA" value={`${avgETA} min`} icon={Clock} tone="bg-slate-600" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="text-sm font-semibold text-slate-200 mb-3">Top Priority Zones</div>
                <div className="space-y-1">
                  {sortedZones.slice(0, 6).map((z) => (
                    <button
                      key={z.zone_id}
                      onClick={() => { setActiveTab("map"); setSelectedZoneId(z.zone_id); }}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-lg hover:bg-slate-800 text-left"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-slate-200">
                          {z.zone_id} <span className="text-slate-500 font-normal">· {z.neighbourhood}</span>
                        </span>
                        <Badge label={getClass(z)} cls={getClass(z)} />
                        {z.silent_zone && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
                      </div>
                      <span className="text-sm font-semibold text-slate-100">{z.golden_hour_score}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="text-sm font-semibold text-slate-200 mb-3">Audit Log</div>
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {(audit || []).map((a) => (
                    <div key={a.id} className="text-xs text-slate-400 border-l-2 border-slate-700 pl-3 py-0.5">
                      {a.text}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-[11px] text-slate-500">
              GoldenHour AI is an academic/research prototype for disaster-response prioritization. Its scores are
              decision-support heuristics and are not medically validated survival predictions. Satellite observations,
              population estimates, crowdsourced reports, and accessibility estimates may contain errors and should not
              be treated as ground truth.
            </div>
          </div>
        )}

        {/* ================= LIVE MAP ================= */}
        {activeTab === "map" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900 border border-slate-800 rounded-xl p-3">
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-slate-400" />
                {[
                  { id: "priority", label: "Golden Hour Map" },
                  { id: "damage", label: "Damage Map" },
                  { id: "confidence", label: "Confidence Map" },
                  { id: "flood", label: "Flood Extent" },
                  { id: "population", label: "Population" },
                  { id: "accessibility", label: "Access" },
                ].map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setMapMode(m.id)}
                    className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${
                      mapMode === m.id ? "bg-teal-600 border-teal-500 text-white" : "border-slate-700 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => setLayers((l) => ({ ...l, silent: !l.silent }))}
                  className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border ${
                    layers.silent ? "bg-amber-600 border-amber-500 text-white" : "border-slate-700 text-slate-400"
                  }`}
                >
                  {layers.silent ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                  Silent Zones
                </button>
                <button
                  onClick={() => setLayers((l) => ({ ...l, incidents: !l.incidents }))}
                  className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${layers.incidents ? "bg-sky-600 border-sky-500 text-white" : "border-slate-700 text-slate-400"}`}
                >
                  Incidents
                </button>
                <button
                  onClick={() => setLayers((l) => ({ ...l, teams: !l.teams }))}
                  className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${layers.teams ? "bg-teal-600 border-teal-500 text-white" : "border-slate-700 text-slate-400"}`}
                >
                  Teams
                </button>
              </div>
              <div className="flex items-center gap-1">
                {[0, 15, 30, 60].map((m) => (
                  <button
                    key={m}
                    onClick={() => setTimeOffset(m)}
                    className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${
                      timeOffset === m ? "bg-slate-100 text-slate-900 border-slate-100" : "border-slate-700 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {m === 0 ? "Now" : `+${m}m`}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="text-xs text-slate-500 mb-3">
                  {mapMode === "priority" && "Response priority — the Golden Hour Score for every micro-zone. Basemap © OpenStreetMap."}
                  {mapMode === "damage" && "Where the disaster is most severe, independent of rescue priority. Prototype flood detection."}
                  {mapMode === "confidence" && "How much each zone's incoming reports can be trusted (algorithmic confidence)."}
                  {mapMode === "flood" && "Satellite-derived flood extent per zone (Prototype SAR Flood Detection)."}
                  {mapMode === "population" && "Estimated population exposure per zone (ESTIMATED, not a census)."}
                  {mapMode === "accessibility" && "Road accessibility per zone (100 = easily accessible)."}
                </div>
                {geojson ? (
                  <MapView
                    geojson={geojson}
                    zones={zones}
                    reports={reports}
                    teams={teams}
                    selectedId={selectedZoneId}
                    onSelect={setSelectedZoneId}
                    layers={layers}
                    mode={mapMode}
                  />
                ) : (
                  <div className="text-sm text-slate-500 py-16 text-center">Data temporarily unavailable</div>
                )}
                <div className="flex flex-wrap items-center gap-4 mt-4 text-[11px] text-slate-400">
                  {["Critical", "High", "Medium", "Low"].map((label) => (
                    <div key={label} className="flex items-center gap-1.5">
                      <span className={`w-2.5 h-2.5 rounded-sm inline-block ${label === "Critical" ? "bg-red-600" : label === "High" ? "bg-amber-500" : label === "Medium" ? "bg-sky-600" : "bg-slate-600"}`} /> {label}
                    </div>
                  ))}
                  <div className="flex items-center gap-1.5"><AlertTriangle className="w-3 h-3 text-amber-400" /> Silent zone</div>
                  <div className="flex items-center gap-1.5"><Shield className="w-3 h-3 text-slate-300" /> Manual override</div>
                </div>
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                {!selectedZone && (
                  <div className="h-full flex items-center justify-center text-center text-sm text-slate-500 py-16">
                    Select a zone on the map to see its Golden Hour Score breakdown.
                  </div>
                )}
                {selectedZone && (
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <div className="text-sm font-semibold text-slate-100">
                        {selectedZone.zone_id} <span className="text-slate-500 font-normal">· {selectedZone.neighbourhood}</span>
                      </div>
                      <Badge label={getClass(selectedZone)} cls={getClass(selectedZone)} />
                    </div>
                    <div className="text-3xl font-bold text-slate-50 mb-1">
                      {selectedZone.golden_hour_score}<span className="text-sm text-slate-500 font-normal"> / 100</span>
                    </div>
                    <div className="text-xs text-slate-500 mb-4">
                      {selectedZone.incident_type} · Disaster Response Priority Score (prototype)
                    </div>

                    <div className="mb-4">
                      <Bar1 label="Severity" value={selectedZone.values?.severity ?? selectedZone.severity} tone="bg-red-500" />
                      <Bar1 label="Population Risk" value={selectedZone.values?.populationRisk ?? selectedZone.population_risk} tone="bg-amber-500" />
                      <Bar1 label="Vulnerability" value={selectedZone.values?.vulnerability ?? selectedZone.vulnerability} tone="bg-sky-500" />
                      <Bar1 label="Urgency" value={selectedZone.values?.urgency ?? selectedZone.urgency} tone="bg-fuchsia-500" />
                      <Bar1 label="Confidence" value={selectedZone.values?.confidence ?? selectedZone.confidence} tone="bg-emerald-500" />
                      <Bar1 label="Accessibility" value={selectedZone.values?.accessibility ?? selectedZone.accessibility} tone="bg-teal-500" />
                    </div>

                    <div className="border-t border-slate-800 pt-3 mb-4">
                      <div className="text-xs font-semibold text-slate-300 mb-2">Why is this zone high priority?</div>
                      {Object.entries(selectedZone.breakdown || {})
                        .sort((a, b) => b[1] - a[1])
                        .map(([key, val]) => (
                          <div key={key} className="flex justify-between text-xs text-slate-400 py-0.5">
                            <span>{FIELD_LABELS[key] || key}{weights ? ` (${Math.round((weights[key] || 0) * 100)}%)` : ""}</span>
                            <span className="text-slate-200">+{val}</span>
                          </div>
                        ))}
                      <div className="flex justify-between text-xs font-semibold text-slate-100 border-t border-slate-800 mt-1 pt-1">
                        <span>Total</span><span>{selectedZone.golden_hour_score}</span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 mb-3">
                      <div>Flood extent: <span className="text-slate-200">{Math.round((selectedZone.flood_extent || 0) * 100)}%</span> <span className="text-slate-600">SATELLITE</span></div>
                      <div>Est. population: <span className="text-slate-200">{(selectedZone.estimated_population || 0).toLocaleString()}</span> <span className="text-slate-600">ESTIMATED</span></div>
                      <div>Reports: <span className="text-slate-200">{selectedZone.reports_count}</span></div>
                      <div>Updated: <span className="text-slate-200">{timeAgo(selectedZone.last_updated)}</span></div>
                    </div>
                    {selectedZone.silent_zone && (
                      <div className="mt-1 mb-3 flex items-start gap-1.5 text-amber-400 text-xs">
                        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                        <span>Potentially under-reported zone — high estimated exposure with unusually few reports.</span>
                      </div>
                    )}

                    {zoneDetail?.satellite_metrics && (
                      <div className="border border-slate-800 rounded-lg p-3 mb-3 bg-slate-950/60">
                        <div className="text-xs font-semibold text-slate-200 mb-2 flex items-center gap-1.5">
                          <Satellite className="w-3.5 h-3.5 text-teal-400" /> Satellite Evidence
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                          <div>Flood extent: <span className="text-slate-100">{zoneDetail.satellite_metrics.flood_extent_percent}%</span></div>
                          <div>Change score: <span className="text-slate-100">{zoneDetail.satellite_metrics.change_score}</span></div>
                          <div>Sat. confidence: <span className="text-slate-100">{zoneDetail.satellite_metrics.satellite_confidence}</span></div>
                          <div>Analysis: <span className="text-slate-100">{zoneDetail.satellite_metrics.analysis_id}</span></div>
                        </div>
                        <div className="text-[10px] text-slate-600 mt-1">{zoneDetail.satellite_metrics.method}</div>
                        <SatellitePreviews zoneId={selectedZone.zone_id} satProducts={satProducts} />
                      </div>
                    )}

                    {zoneDetail?.evidence_sources && (
                      <div className="mb-3">
                        <div className="text-xs font-semibold text-slate-300 mb-1.5">Evidence</div>
                        <div className="flex flex-wrap gap-1.5 text-[10px]">
                          {[
                            ["Sentinel-1", zoneDetail.evidence_sources.sentinel1],
                            ["Sentinel-2", zoneDetail.evidence_sources.sentinel2],
                            ["OpenStreetMap", zoneDetail.evidence_sources.openstreetmap],
                            ["Population", zoneDetail.evidence_sources.population],
                          ].map(([label, on]) => (
                            <span key={label} className={`px-2 py-0.5 rounded border ${on ? "border-teal-700 text-teal-300 bg-teal-950" : "border-slate-700 text-slate-500"}`}>
                              {label}{on ? "" : " — n/a"}
                            </span>
                          ))}
                          <span className="px-2 py-0.5 rounded border border-sky-700 text-sky-300 bg-sky-950">
                            {zoneDetail.evidence_sources.crowdsourced_reports} reports
                          </span>
                        </div>
                      </div>
                    )}

                    <button
                      onClick={() => handleOverride(selectedZone.zone_id)}
                      className={`w-full text-xs font-medium py-2 rounded-lg border ${
                        selectedZone.manual_override ? "border-slate-600 text-slate-300" : "border-teal-600 text-teal-300 hover:bg-teal-950"
                      }`}
                    >
                      {selectedZone.manual_override ? "Remove Manual Override" : "Manually Escalate to Critical"}
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-sm font-semibold text-slate-200 mb-3">Projected Response Priority Over Time</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 text-left">
                      <th className="py-1.5 pr-4">Zone</th>
                      <th className="py-1.5 pr-4">Now</th>
                      <th className="py-1.5 pr-4">+15 min</th>
                      <th className="py-1.5 pr-4">+30 min</th>
                      <th className="py-1.5 pr-4">+60 min</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(projections.length ? projections : sortedZones.slice(0, 6).map((z) => ({
                      zone_id: z.zone_id, now: z.golden_hour_score, t15: z.golden_hour_score, t30: z.golden_hour_score, t60: z.golden_hour_score,
                    }))).slice(0, 6).map((r) => (
                      <tr key={r.zone_id} className="border-t border-slate-800">
                        <td className="py-1.5 pr-4 font-medium text-slate-200">{r.zone_id}</td>
                        <td className="py-1.5 pr-4">{r.now}</td>
                        <td className="py-1.5 pr-4">{r.t15}</td>
                        <td className="py-1.5 pr-4">{r.t30}</td>
                        <td className="py-1.5 pr-4">{r.t60}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="text-[11px] text-slate-500 mt-2">Prototype Urgency Model — illustrative decay curves, not a medical estimate.</div>
            </div>
          </div>
        )}

        {/* ================= INCIDENTS ================= */}
        {activeTab === "incidents" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900 border border-slate-800 rounded-xl p-3">
              <div className="flex flex-wrap gap-1.5">
                {["All", "High Confidence", "Moderate Confidence", "Medium Confidence", "Low Confidence", "Potential Duplicate", "Human Verified"].map((f) => (
                  <button
                    key={f}
                    onClick={() => setReportFilter(f)}
                    className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${
                      reportFilter === f ? "bg-teal-600 border-teal-500 text-white" : "border-slate-700 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
              <div className="flex gap-1.5">
                <button
                  onClick={() => setReportSort("confidence")}
                  className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${reportSort === "confidence" ? "bg-slate-100 text-slate-900 border-slate-100" : "border-slate-700 text-slate-400"}`}
                >Sort: Confidence</button>
                <button
                  onClick={() => setReportSort("time")}
                  className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${reportSort === "time" ? "bg-slate-100 text-slate-900 border-slate-100" : "border-slate-700 text-slate-400"}`}
                >Sort: Recency</button>
                <button
                  onClick={() => setShowForm((s) => !s)}
                  className="flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded-lg bg-teal-600 text-white"
                ><Plus className="w-3.5 h-3.5" /> New Report</button>
                <input
                  value={verifier}
                  onChange={(e) => setVerifier(e.target.value)}
                  title="Verifier name for human verification"
                  placeholder="verifier"
                  className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-slate-300 w-24"
                />
              </div>
            </div>
            <div className="text-[11px] text-slate-500 px-1">
              Algorithmic Confidence — estimated from evidence flags, not fact-checked. Only a human action marks a report Human Verified.
            </div>

            {showForm && (
              <form onSubmit={handleCreateReport} className="bg-slate-900 border border-teal-800 rounded-xl p-4 grid grid-cols-1 md:grid-cols-4 gap-3">
                <label className="text-xs text-slate-400">Zone
                  <select value={form.zone_id} onChange={(e) => setForm({ ...form, zone_id: e.target.value })} className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-200 p-2">
                    {zones.map((z) => <option key={z.zone_id} value={z.zone_id}>{z.zone_id} · {z.neighbourhood}</option>)}
                  </select>
                </label>
                <label className="text-xs text-slate-400">Incident type
                  <select value={form.incident_type} onChange={(e) => setForm({ ...form, incident_type: e.target.value })} className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-200 p-2">
                    {["Trapped Under Rubble", "Medical Emergency", "Stranded on Rooftop", "Flooding - Rising Water", "Property Damage"].map((t) => <option key={t}>{t}</option>)}
                  </select>
                </label>
                <label className="text-xs text-slate-400 md:col-span-2">Description
                  <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What is happening at this location?" className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-200 p-2" />
                </label>
                <div className="md:col-span-4">
                  <button type="submit" className="text-xs font-medium bg-teal-600 hover:bg-teal-500 text-white px-4 py-2 rounded-lg">Submit Report</button>
                </div>
              </form>
            )}

            {!backendOk && (
              <div className="text-xs text-amber-400 bg-amber-950/40 border border-amber-800 rounded-xl p-3">
                Report feed unavailable — backend unreachable. Showing cached state.
              </div>
            )}

            <div className="space-y-2">
              {reports
                .filter((r) => reportFilter === "All" || r.status === reportFilter || (reportFilter === "Potential Duplicate" && r.status === "Duplicate"))
                .sort((a, b) => (reportSort === "confidence" ? b.score - a.score : new Date(b.timestamp) - new Date(a.timestamp)))
                .map((r) => {
                  const cls = r.status === "Potential Duplicate" || r.status === "Duplicate" ? "Low" : localClassify(r.score);
                  const expanded = expandedReportId === r.report_id;
                  return (
                    <div key={r.report_id} className="bg-slate-900 border border-slate-800 rounded-xl p-3">
                      <button onClick={() => setExpandedReportId(expanded ? null : r.report_id)} className="w-full flex items-center justify-between text-left">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-slate-200">Report #{r.report_id}</span>
                          <span className="text-xs text-slate-500">{r.zone_id} · {r.incident_type}</span>
                          <span className="text-xs text-slate-500">{timeAgo(r.timestamp)}</span>
                        </div>
                        <div className="flex items-center gap-3">
                          <Badge label={r.status} cls={cls} />
                          <span className="text-sm font-semibold text-slate-100">{r.score}%</span>
                        </div>
                      </button>
                      {expanded && (
                        <div className="mt-3 pt-3 border-t border-slate-800">
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mb-3">
                            <div className={`flex items-center gap-1.5 ${r.multiple_nearby ? "text-emerald-400" : "text-slate-600"}`}>
                              <CheckCircle2 className="w-3.5 h-3.5" /> Multiple nearby reports
                            </div>
                            <div className={`flex items-center gap-1.5 ${r.recent_timestamp ? "text-emerald-400" : "text-slate-600"}`}>
                              <CheckCircle2 className="w-3.5 h-3.5" /> Recent timestamp
                            </div>
                            <div className={`flex items-center gap-1.5 ${r.location_consistent ? "text-emerald-400" : "text-slate-600"}`}>
                              <CheckCircle2 className="w-3.5 h-3.5" /> Location consistency
                            </div>
                            <div className={`flex items-center gap-1.5 ${r.supporting_evidence ? "text-emerald-400" : "text-slate-600"}`}>
                              <CheckCircle2 className="w-3.5 h-3.5" /> Supporting evidence
                            </div>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            {r.human_verified
                              ? <span className="text-emerald-400">Human Verified by {r.verified_by || "operator"}</span>
                              : (
                                <button
                                  onClick={() => handleVerify(r.report_id)}
                                  className="flex items-center gap-1 text-teal-300 border border-teal-700 hover:bg-teal-950 px-2.5 py-1 rounded-lg"
                                >
                                  <Shield className="w-3 h-3" /> Mark Human Verified
                                </button>
                              )}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              {reports.length === 0 && (
                <div className="text-xs text-slate-500 text-center py-8">No reports loaded.</div>
              )}
            </div>
          </div>
        )}

        {/* ================= RESCUE TEAMS ================= */}
        {activeTab === "teams" && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {teams.map((t) => (
              <div key={t.team_id} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm font-semibold text-slate-100">{t.name}</div>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-md border ${
                    t.status === "Available" ? "bg-emerald-950 text-emerald-300 border-emerald-700" : "bg-slate-800 text-slate-300 border-slate-600"
                  }`}>{t.status}</span>
                </div>
                <div className="text-xs text-slate-500 mb-1">Capacity: {t.capacity} responders</div>
                <div className="text-xs text-slate-500 mb-1">Assigned zone: {t.assigned_zone || "Unassigned"}</div>
                <div className="text-xs text-slate-500 mb-3">ETA to nearest critical zone: {t.eta_min} min</div>
                <button
                  onClick={() => handleDispatch(t.team_id)}
                  disabled={t.status !== "Available"}
                  className="w-full text-xs font-medium py-2 rounded-lg bg-teal-600 hover:bg-teal-500 disabled:bg-slate-800 disabled:text-slate-500 text-white"
                >
                  Dispatch to Top Priority Zone
                </button>
              </div>
            ))}
          </div>
        )}

        {/* ================= ANALYTICS ================= */}
        {activeTab === "analytics" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <KPI label="Affected Area (est.)" value={`${analytics?.affected_area_km2 ?? "—"} km²`} icon={MapPin} tone="bg-sky-600" />
              <KPI label="Affected Zones" value={analytics?.affected_zones ?? "—"} icon={AlertTriangle} tone="bg-red-600" />
              <KPI label="Critical / High" value={`${analytics?.critical_zones ?? 0} / ${analytics?.high_priority_zones ?? 0}`} icon={Activity} tone="bg-amber-600" />
              <KPI label="Reports Received" value={analytics?.reports_received ?? 0} icon={Radio} tone="bg-teal-600" />
              <KPI label="Potential Duplicates" value={analytics?.potential_duplicates ?? 0} icon={EyeOff} tone="bg-slate-600" />
              <KPI label="Under-Reported" value={(analytics?.under_reported_zones || []).length} icon={Eye} tone="bg-amber-600" />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-sm font-semibold text-slate-200 mb-1">Zones by Priority Class</div>
              <div className="text-[11px] text-slate-500 mb-3">
                Est. exposed population: {(analytics?.estimated_exposed_population || 0).toLocaleString()} · Mean flood extent: {Math.round((analytics?.mean_flood_extent || 0) * 100)}%
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={classCounts}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 12 }} />
                  <Bar dataKey="count" fill="#2dd4bf" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-sm font-semibold text-slate-200 mb-3">Report Verification Status</div>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={statusCounts} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
                    {statusCounts.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 lg:col-span-2">
              <div className="text-sm font-semibold text-slate-200 mb-3">Top Zones — Golden Hour Score Over Simulated Time</div>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={projections.slice(0, 12)}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="zone_id" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]} />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="now" name="Now" stroke="#94a3b8" strokeWidth={2} />
                  <Line type="monotone" dataKey="t15" name="+15 min" stroke="#38bdf8" strokeWidth={2} />
                  <Line type="monotone" dataKey="t30" name="+30 min" stroke="#fbbf24" strokeWidth={2} />
                  <Line type="monotone" dataKey="t60" name="+60 min" stroke="#f87171" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            </div>
          </div>
        )}

        {/* ================= DATA SOURCES ================= */}
        {activeTab === "sources" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900 border border-slate-800 rounded-xl p-3">
              <div className="text-xs text-slate-400">
                Last successful synchronization:{" "}
                <span className="text-slate-200">
                  {(() => {
                    const times = (sources || []).map((s) => s.last_successful_update).filter(Boolean).sort();
                    return times.length ? timeAgo(times[times.length - 1]) : "never";
                  })()}
                </span>
                {statusInfo?.last_satellite_check && (
                  <span className="ml-3">Satellite last checked: <span className="text-slate-200">{timeAgo(statusInfo.last_satellite_check)}</span></span>
                )}
              </div>
              <div className="flex gap-2">
                <button onClick={() => handleRecalculate(true)} className="flex items-center gap-1.5 text-xs font-medium bg-teal-600 hover:bg-teal-500 text-white px-3 py-1.5 rounded-lg">
                  <RefreshCw className="w-3.5 h-3.5" /> Refresh Data
                </button>
                {studyAreas && (
                  <select
                    value={studyAreas.active?.name || "Chennai"}
                    onChange={async (e) => {
                      try {
                        await api.activateStudyArea(e.target.value);
                        await loadAll(0, true);
                        pushNotification(`Study area switched to ${e.target.value}.`, "success");
                      } catch { pushNotification("Study-area switch failed.", "warning"); }
                    }}
                    className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-slate-200"
                    title="Study area"
                  >
                    {Object.keys(studyAreas.presets || {}).map((n) => <option key={n}>{n}</option>)}
                  </select>
                )}
              </div>
            </div>
            {refreshLog.length > 0 && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="text-sm font-semibold text-slate-200 mb-2">Last refresh log</div>
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {refreshLog.map((s, i) => (
                    <div key={i} className="text-xs text-slate-400 border-l-2 border-teal-700 pl-3 py-0.5">{s}</div>
                  ))}
                </div>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {(sources.length ? sources : [
                { source_id: "sentinel1", category: "Satellite", display_name: "Sentinel-1 SAR", status: "demo", last_updated: null, detail: "Prototype flood detection (offline)" },
                { source_id: "sentinel2", category: "Satellite", display_name: "Sentinel-2 Optical", status: "demo", last_updated: null, detail: "NDWI supporting evidence (offline)" },
                { source_id: "osm", category: "Mapping", display_name: "OpenStreetMap Roads", status: "demo", last_updated: null, detail: "Road accessibility proxy (offline)" },
                { source_id: "population", category: "Population", display_name: "Population (worldpop)", status: "demo", last_updated: null, detail: "ESTIMATED exposure proxy (offline)" },
                { source_id: "engine", category: "Processing", display_name: "GoldenHour AI Analysis Engine", status: "connected", last_updated: null, detail: "GHS scoring engine v1 (local)" },
              ]).map((s) => (
                <div key={s.source_id} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-sm font-semibold text-slate-100">{s.display_name}</div>
                    <StatusPill label={s.category} status={s.status} />
                  </div>
                  <div className="text-xs text-slate-500">{s.detail}</div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-slate-600 mt-2">
                    <div>Updated: <span className="text-slate-400">{s.last_updated ? timeAgo(s.last_updated) : "—"}</span></div>
                    <div>Checked: <span className="text-slate-400">{s.last_checked ? timeAgo(s.last_checked) : "—"}</span></div>
                    <div>Acquired: <span className="text-slate-400">{s.acquisition_time ? timeAgo(s.acquisition_time) : "—"}</span></div>
                    <div>Processed: <span className="text-slate-400">{s.processing_time ? timeAgo(s.processing_time) : "—"}</span></div>
                  </div>
                </div>
              ))}
            </div>
            {(satProducts.analyses || []).length > 0 && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="text-sm font-semibold text-slate-200 mb-2">Recent satellite analyses</div>
                <div className="space-y-2">
                  {(satProducts.analyses || []).slice(0, 3).map((a) => (
                    <div key={a.analysis_id} className="text-xs text-slate-400 border-l-2 border-slate-700 pl-3">
                      <span className="text-slate-200 font-medium">{a.analysis_id}</span> · {a.mode} · {a.zones_updated} zones · {timeAgo(a.created_at)}
                      <div className="text-slate-600">S1 {a.s1_product || "—"}{a.s2_product ? ` · S2 ${a.s2_product}` : ""}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {gee && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-xs text-slate-400">
                <span className="font-semibold text-slate-200">Google Earth Engine: </span>
                {gee.enabled ? `${gee.status} — ${gee.detail}` : `disabled — ${gee.detail}`}
              </div>
            )}
            {weights && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="text-sm font-semibold text-slate-200 mb-2">Golden Hour Score — weight configuration (explainable)</div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-slate-400">
                  {Object.entries(weights).map(([k, w]) => (
                    <div key={k} className="bg-slate-800/60 rounded-lg px-3 py-2 flex justify-between">
                      <span>{FIELD_LABELS[k] || k}</span>
                      <span className="text-slate-100 font-medium">{Math.round(w * 100)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="max-w-7xl mx-auto px-6 pb-8 text-[11px] text-slate-600">
        GoldenHour AI · Academic/research prototype · GHS is a Disaster Response Priority Score, not a medical survival
        prediction · Tick {tick}
      </footer>
    </div>
  );
}
