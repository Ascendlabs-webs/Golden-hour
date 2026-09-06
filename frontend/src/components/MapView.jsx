import { useMemo } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";

const CLASS_FILL = {
  Critical: "#dc2626",
  High: "#f59e0b",
  Medium: "#0284c7",
  Low: "#475569",
};

const STATUS_COLOR = {
  Verified: "#34d399",
  "High Confidence": "#38bdf8",
  "Medium Confidence": "#fbbf24",
  "Low Confidence": "#f87171",
  "Potential Duplicate": "#94a3b8",
  Duplicate: "#94a3b8",
};

function FitBounds({ geojson }) {
  const map = useMap();
  useMemo(() => {
    if (!geojson?.features?.length) return;
    try {
      const layer = L.geoJSON(geojson);
      map.fitBounds(layer.getBounds(), { padding: [12, 12] });
    } catch {
      /* keep default view */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geojson]);
  return null;
}

/**
 * Geographic map: OSM basemap + GHS zone polygons + incident / team overlays.
 * No proprietary map provider required.
 */
export default function MapView({
  geojson,
  zones,
  reports,
  teams,
  selectedId,
  onSelect,
  layers,
  mode = "priority",
  center = [13.0475, 80.2013],
}) {
  const zoneById = useMemo(() => {
    const m = {};
    (zones || []).forEach((z) => {
      m[z.zone_id] = z;
    });
    return m;
  }, [zones]);

  const style = (feature) => {
    const cls = feature?.properties?.priority_class || "Low";
    const selected = feature?.properties?.zone_id === selectedId;
    return {
      fillColor: CLASS_FILL[cls] || "#475569",
      weight: selected ? 3 : 1,
      color: selected ? "#ffffff" : "#0f172a",
      fillOpacity: cls === "Low" ? 0.45 : 0.62,
    };
  };

  const MODE_LABEL = {
    priority: "GHS",
    damage: "Damage",
    confidence: "Confidence",
    flood: "Flood",
    population: "Pop. risk",
    accessibility: "Access",
  }[mode] || "GHS";
  const MODE_UNIT = mode === "flood" ? "%" : "";

  const onEach = (feature, layer) => {
    const p = feature.properties || {};
    layer.bindTooltip(
      `<b>${p.zone_id}</b> ${p.neighbourhood || ""}<br/>${MODE_LABEL} ${p.golden_hour_score}${MODE_UNIT} · ${p.priority_class}`,
      { className: "gh-zone-tooltip", sticky: true }
    );
    layer.on("click", () => onSelect && onSelect(p.zone_id));
  };

  return (
    <MapContainer
      center={center}
      zoom={11}
      style={{ height: 460, width: "100%", borderRadius: 12 }}
      scrollWheelZoom
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {geojson && (
        <GeoJSON
          key={`${selectedId}-${geojson.features?.length}-${mode}`}
          data={geojson}
          style={style}
          onEachFeature={onEach}
        />
      )}
      {geojson && <FitBounds geojson={geojson} />}

      {layers.incidents &&
        (reports || []).slice(0, 120).map((r) =>
          r.latitude && r.longitude ? (
            <CircleMarker
              key={`r-${r.report_id}`}
              center={[r.latitude, r.longitude]}
              radius={4}
              pathOptions={{
                color: STATUS_COLOR[r.status] || "#e2e8f0",
                fillColor: STATUS_COLOR[r.status] || "#e2e8f0",
                fillOpacity: 0.9,
                weight: 1,
              }}
            >
              <Tooltip className="gh-zone-tooltip" sticky>
                Report #{r.report_id} · {r.zone_id}
                <br />
                {r.incident_type} · {r.status} ({r.score}%)
              </Tooltip>
            </CircleMarker>
          ) : null
        )}

      {layers.teams &&
        (teams || []).map((t) =>
          t.current_lat && t.current_lon ? (
            <CircleMarker
              key={`t-${t.team_id}`}
              center={[t.current_lat, t.current_lon]}
              radius={6}
              pathOptions={{
                color: "#14b8a6",
                fillColor: t.status === "Available" ? "#14b8a6" : "#f59e0b",
                fillOpacity: 1,
                weight: 2,
              }}
            >
              <Tooltip className="gh-zone-tooltip" sticky>
                {t.name} · {t.status}
                <br />
                {t.assigned_zone ? `Assigned: ${t.assigned_zone}` : "Unassigned"} · ETA{" "}
                {t.eta_min} min
              </Tooltip>
            </CircleMarker>
          ) : null
        )}

      {layers.silent &&
        (zones || [])
          .filter((z) => z.silent_zone)
          .map((z) =>
            z.latitude && z.longitude ? (
              <CircleMarker
                key={`s-${z.zone_id}`}
                center={[z.latitude, z.longitude]}
                radius={9}
                pathOptions={{
                  color: "#fbbf24",
                  fillColor: "transparent",
                  weight: 2,
                  dashArray: "4 3",
                }}
              >
                <Tooltip className="gh-zone-tooltip" sticky>
                  {z.zone_id} · Potentially under-reported zone
                  <br />
                  Population risk {Math.round(z.population_risk)} · {z.reports_count}{" "}
                  reports
                </Tooltip>
              </CircleMarker>
            ) : null
          )}
    </MapContainer>
  );
}
