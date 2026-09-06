/**
 * Deterministic offline fallback — mirrors backend/demo/chennai.py.
 * Seeded hashes only (no Math.random), so the offline demo is reproducible.
 * Used ONLY when the backend is unreachable; the UI labels it DEMO DATA.
 */

function hint(seed) {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < seed.length; i++) {
    const ch = seed.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (h2 >>> 0) % 10000;
}

const h01 = (s) => hint(s) / 10000;
const hrange = (s, lo, hi) => lo + (hint(s) % (hi - lo + 1));

export const WEIGHTS = {
  populationRisk: 0.24,
  urgency: 0.23,
  vulnerability: 0.18,
  severity: 0.17,
  confidence: 0.11,
  accessibility: 0.07,
};

const PROFILES = {
  "Trapped Under Rubble": { base: 92, decay: 0.12, rising: false },
  "Medical Emergency": { base: 80, decay: 0.35, rising: false },
  "Stranded on Rooftop": { base: 70, decay: 0.2, rising: false },
  "Flooding - Rising Water": { base: 55, decay: 0, rising: true },
  "Property Damage": { base: 35, decay: 0.5, rising: false },
};

export function computeUrgency(type, t = 0) {
  const p = PROFILES[type] || { base: 50, decay: 0.2, rising: false };
  if (p.rising) {
    if (t <= 45) return Math.max(0, Math.min(100, p.base + 0.45 * t));
    return Math.max(0, Math.min(100, p.base + 0.45 * 45 - 0.6 * (t - 45)));
  }
  return Math.max(5, Math.min(100, p.base - p.decay * t));
}

export function computeGHS(z, t = 0) {
  const urgency = computeUrgency(z.incident_type, t);
  const values = {
    severity: z.severity,
    populationRisk: z.population_risk,
    vulnerability: z.vulnerability,
    urgency,
    confidence: z.confidence,
    accessibility: z.accessibility,
  };
  const breakdown = {};
  let total = 0;
  for (const [k, w] of Object.entries(WEIGHTS)) {
    breakdown[k] = Math.round(values[k] * w);
    total += values[k] * w;
  }
  return { total: Math.round(total), values, breakdown, urgency };
}

export function classify(v) {
  if (v >= 85) return "Critical";
  if (v >= 65) return "High";
  if (v >= 40) return "Medium";
  return "Low";
}

const NAMES = [
  "Ennore", "Manali", "Madhavaram", "Kolathur", "Perambur", "Tondiarpet",
  "Korukkupet", "Royapuram", "Ayanavaram", "Kilpauk", "Egmore", "Chepauk",
  "Chetpet", "Nungambakkam", "T. Nagar", "Saidapet", "Mylapore", "Triplicane",
  "Kotturpuram", "Adyar", "Guindy", "Velachery", "Perungudi", "Tharamani",
  "St. Thomas Mount", "Pallavaram", "Medavakkam", "Pallikaranai",
  "Sholinganallur", "Karapakkam", "Tambaram", "Chromepet", "Selaiyur",
  "Kovilambakkam", "Nanmangalam", "Medavakkam South",
];
const LATS = [
  13.221, 13.193, 13.17, 13.145, 13.125, 13.125, 13.11, 13.1, 13.1, 13.085,
  13.077, 13.065, 13.075, 13.06, 13.04, 13.025, 13.035, 13.055, 13.015, 13.005,
  13.01, 12.975, 12.965, 12.98, 12.995, 12.965, 12.955, 12.945, 12.935, 12.95,
  12.925, 12.945, 12.935, 12.945, 12.935, 12.915,
];
const LONS = [
  80.315, 80.27, 80.24, 80.215, 80.235, 80.285, 80.285, 80.29, 80.23, 80.225,
  80.26, 80.28, 80.24, 80.24, 80.235, 80.225, 80.27, 80.275, 80.245, 80.26,
  80.215, 80.22, 80.245, 80.25, 80.195, 80.185, 80.205, 80.215, 80.235, 80.25,
  80.165, 80.175, 80.185, 80.195, 80.175, 80.205,
];
const CYCLE = [
  "Flooding - Rising Water", "Stranded on Rooftop", "Medical Emergency",
  "Trapped Under Rubble", "Property Damage", "Flooding - Rising Water",
];
const BBOX = [80.05, 12.9, 80.32, 13.25];

export function fallbackZones() {
  const zones = [];
  for (let i = 0; i < 36; i++) {
    const id = `Z-${String(i + 1).padStart(3, "0")}`;
    const flood = h01(`fld-${i}`);
    zones.push({
      zone_id: id,
      neighbourhood: NAMES[i],
      row: Math.floor(i / 6),
      col: i % 6,
      latitude: LATS[i],
      longitude: LONS[i],
      severity: hrange(`sev-${i}`, 28, 92),
      population_risk: hrange(`pop-${i}`, 25, 95),
      vulnerability: hrange(`vul-${i}`, 25, 92),
      accessibility: hrange(`acc-${i}`, 28, 95),
      confidence: hrange(`con-${i}`, 42, 96),
      reports_count: hrange(`rep-${i}`, 0, 11),
      incident_type: CYCLE[i % CYCLE.length],
      flood_extent: Math.round(flood * 1000) / 1000,
      estimated_population: hrange(`exppop-${i}`, 800, 24000),
      manual_override: false,
      last_updated: new Date().toISOString(),
    });
  }
  return zones.map((z) => {
    const s = computeGHS(z, 0);
    return {
      ...z,
      golden_hour_score: s.total,
      breakdown: s.breakdown,
      values: s.values,
      urgency: Math.round(s.urgency * 10) / 10,
      priority_class: z.manual_override ? "Critical" : classify(s.total),
      silent_zone: z.population_risk >= 65 && z.reports_count <= 2,
    };
  });
}

export function fallbackGeoJSON(zones) {
  const [minLon, minLat, maxLon, maxLat] = BBOX;
  const dLon = (maxLon - minLon) / 6;
  const dLat = (maxLat - minLat) / 6;
  return {
    type: "FeatureCollection",
    features: zones.map((z) => {
      const top = maxLat - z.row * dLat;
      const left = minLon + z.col * dLon;
      return {
        type: "Feature",
        properties: {
          zone_id: z.zone_id,
          neighbourhood: z.neighbourhood,
          golden_hour_score: z.golden_hour_score,
          priority_class: z.priority_class,
          severity: z.severity,
          population_risk: z.population_risk,
          vulnerability: z.vulnerability,
          accessibility: z.accessibility,
          confidence: z.confidence,
          reports_count: z.reports_count,
          incident_type: z.incident_type,
          flood_extent: z.flood_extent,
          silent_zone: z.silent_zone,
          breakdown: z.breakdown,
        },
        geometry: {
          type: "Polygon",
          coordinates: [[
            [left, top], [left + dLon, top], [left + dLon, top - dLat],
            [left, top - dLat], [left, top],
          ]],
        },
      };
    }),
  };
}

const TEAM_NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
  "Golf", "Hotel", "India", "Juliet", "Kilo", "Lima"];

export function fallbackTeams() {
  return TEAM_NAMES.map((n, i) => ({
    team_id: i + 1,
    name: `Team ${n}`,
    status: hint(`team-${n}`) % 100 > 35 ? "Available" : "Dispatched",
    capacity: 2 + (hint(`team-${n}`) % 5),
    current_lat: Math.round((13.06 - (hint(`team-${n}`) % 40) / 1000) * 1e5) / 1e5,
    current_lon: Math.round((80.2 + (hint(`team-${n}`) % 40) / 1000) * 1e5) / 1e5,
    assigned_zone: null,
    eta_min: 6 + (hint(`team-${n}`) % 30),
  }));
}
