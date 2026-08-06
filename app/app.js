const ZONE_LABELS = {
  MON_TUE: "Mon/Tue", WED_THU: "Wed/Thu", WED_FRI: "Wed/Fri",
  THU_FRI: "Thu/Fri", DAILY: "Daily (except Sun)", MON_THU: "Mon/Thu", OTHER: "Other",
};
const ZONE_COLORS = {
  MON_TUE: "#2a78d6", WED_THU: "#e34948", WED_FRI: "#eb6834",
  THU_FRI: "#4a3aa7", DAILY: "#e87ba4", MON_THU: "#eda100", OTHER: "#898781",
};
const ZONE_ORDER = ["MON_TUE", "WED_THU", "WED_FRI", "THU_FRI", "MON_THU", "DAILY", "OTHER"];
const TODAY_ABBR = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][new Date().getDay()];

const map = L.map("map", { zoomControl: false, attributionControl: true })
  .setView([40.622, -74.018], 14);

L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: "abcd",
  maxZoom: 20,
}).addTo(map);

let geoLayer = null;
let todayMode = false;

let statusTimer = null;
function showStatus(message, autoHideMs) {
  const toast = document.getElementById("status-toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(statusTimer);
  if (autoHideMs) {
    statusTimer = setTimeout(() => toast.classList.add("hidden"), autoHideMs);
  }
}
function hideStatus() {
  document.getElementById("status-toast").classList.add("hidden");
}

const LOCATE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"></circle>
  <path d="M12 2v3M12 19v3M2 12h3M19 12h3"></path>
</svg>`;

const LocateControl = L.Control.extend({
  options: { position: "bottomright" },
  onAdd: function () {
    const container = L.DomUtil.create("div", "leaflet-bar locate-control");
    const button = L.DomUtil.create("a", "locate-button", container);
    button.href = "#";
    button.title = "Show my location";
    button.innerHTML = LOCATE_ICON;
    L.DomEvent.disableClickPropagation(container);
    L.DomEvent.on(button, "click", (e) => {
      L.DomEvent.preventDefault(e);
      toggleLocate(button);
    });
    this._button = button;
    return container;
  },
});
map.addControl(new LocateControl());

const USER_DOT_HTML = `
  <div class="user-dot-wrap">
    <div class="user-dot-pulse"></div>
    <div class="user-heading"></div>
    <div class="user-dot"></div>
  </div>`;
const USER_DOT_ICON = L.divIcon({
  html: USER_DOT_HTML,
  className: "user-dot-icon",
  iconSize: [36, 36],
  iconAnchor: [18, 18],
});
const DRIVING_ZOOM = 17;

let watchId = null;
let userMarker = null;
let userAccuracyCircle = null;
let followMode = false;
let locateButtonEl = null;
let hasCenteredOnUser = false;

function setHeading(headingDeg) {
  if (!userMarker) return;
  const el = userMarker.getElement();
  if (!el) return;
  const wrap = el.querySelector(".user-dot-wrap");
  const arrow = el.querySelector(".user-heading");
  if (headingDeg === null || headingDeg === undefined || Number.isNaN(headingDeg)) {
    arrow.classList.remove("visible");
  } else {
    arrow.classList.add("visible");
    wrap.style.transform = `rotate(${headingDeg}deg)`;
  }
}

function onPositionUpdate(pos) {
  hideStatus();
  const { latitude, longitude, accuracy, heading, speed } = pos.coords;
  const latlng = [latitude, longitude];

  if (!userMarker) {
    userAccuracyCircle = L.circle(latlng, {
      radius: accuracy, color: "#2a78d6", weight: 1, fillColor: "#2a78d6", fillOpacity: 0.08,
    }).addTo(map);
    userMarker = L.marker(latlng, { icon: USER_DOT_ICON, zIndexOffset: 1000 }).addTo(map);
  } else {
    userMarker.setLatLng(latlng);
    userAccuracyCircle.setLatLng(latlng);
    userAccuracyCircle.setRadius(accuracy);
  }

  const showHeading = heading !== null && heading !== undefined && (speed === null || speed > 0.5);
  setHeading(showHeading ? heading : null);

  if (followMode) {
    if (!hasCenteredOnUser) {
      map.setView(latlng, DRIVING_ZOOM, { animate: true });
      hasCenteredOnUser = true;
    } else {
      map.panTo(latlng, { animate: true });
    }
  }
}

function startTracking(shouldFollow) {
  if (!window.isSecureContext) {
    if (shouldFollow) showStatus("Location needs a secure (https) connection to work in Safari.", 4000);
    return;
  }
  if (!navigator.geolocation) {
    if (shouldFollow) showStatus("Location isn't supported in this browser.", 4000);
    return;
  }

  if (shouldFollow) showStatus("Locating…");
  followMode = shouldFollow;
  if (shouldFollow && locateButtonEl) locateButtonEl.classList.add("active");
  watchId = navigator.geolocation.watchPosition(onPositionUpdate, (err) => {
    if (shouldFollow) {
      let msg = "Couldn't get your location.";
      if (err.code === err.PERMISSION_DENIED) {
        msg = "Location permission denied — enable it in Settings > Privacy > Location Services > Safari Websites.";
      } else if (err.code === err.TIMEOUT) {
        msg = "Timed out getting your location.";
      }
      showStatus(msg, 5000);
    }
    stopTracking();
  }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 });
}

function stopTracking() {
  if (watchId !== null) navigator.geolocation.clearWatch(watchId);
  watchId = null;
  followMode = false;
  hasCenteredOnUser = false;
  if (locateButtonEl) locateButtonEl.classList.remove("active");
  hideStatus();
}

function toggleLocate(button) {
  locateButtonEl = button;
  if (watchId === null) {
    startTracking(true);
  } else if (!followMode) {
    // tracking but user panned away — tapping again resumes following
    followMode = true;
    button.classList.add("active");
    if (userMarker) map.panTo(userMarker.getLatLng(), { animate: true });
  } else {
    stopTracking();
  }
}

// A user-initiated drag pauses auto-recentering without killing GPS tracking,
// so a stray pan while driving doesn't stop location updates.
map.on("dragstart", () => {
  if (watchId !== null && followMode) {
    followMode = false;
    if (locateButtonEl) locateButtonEl.classList.remove("active");
  }
});

function baseStyle(feature) {
  return {
    color: feature.properties.color,
    weight: 4,
    opacity: 0.85,
    lineCap: "round",
  };
}

function applyTodayMode() {
  if (!geoLayer) return;
  geoLayer.eachLayer((layer) => {
    const isToday = layer.feature.properties.all_days.includes(TODAY_ABBR);
    if (!todayMode) {
      layer.setStyle({ opacity: 0.85, weight: 4 });
    } else {
      layer.setStyle(
        isToday ? { opacity: 1, weight: 6 } : { opacity: 0.12, weight: 3 }
      );
    }
  });
}

function scheduleRowsHtml(props) {
  return props.schedules
    .map((s) => `<div class="schedule-row"><span class="dot" style="background:${props.color}"></span>${s}</div>`)
    .join("");
}

function openDetail(props) {
  const sheet = document.getElementById("detail-sheet");
  const content = document.getElementById("detail-content");
  const sideWord = { N: "North side", S: "South side", E: "East side", W: "West side" }[props.side] || props.side;
  content.innerHTML = `
    <h2>${props.street}</h2>
    <p class="cross-streets">${sideWord} &middot; between ${props.from} &amp; ${props.to} &middot; <strong>${props.zone_label}</strong> zone</p>
    ${scheduleRowsHtml(props)}
  `;
  sheet.classList.remove("hidden");
}

fetch("data/bayridge.geojson")
  .then((r) => r.json())
  .then((data) => {
    geoLayer = L.geoJSON(data, {
      style: baseStyle,
      onEachFeature: (feature, layer) => {
        layer.on("click", () => openDetail(feature.properties));
      },
    }).addTo(map);
    if (!hasCenteredOnUser) {
      map.fitBounds(geoLayer.getBounds(), { padding: [20, 20] });
    }
  });

document.getElementById("detail-close").addEventListener("click", () => {
  document.getElementById("detail-sheet").classList.add("hidden");
});

document.getElementById("today-toggle").addEventListener("click", (e) => {
  todayMode = !todayMode;
  e.target.setAttribute("aria-pressed", String(todayMode));
  applyTodayMode();
});

function buildLegend() {
  const el = document.getElementById("legend");
  el.innerHTML = ZONE_ORDER
    .map((key) => `<div class="legend-item"><span class="legend-swatch" style="background:${ZONE_COLORS[key]}"></span><span class="legend-label">${ZONE_LABELS[key]}</span></div>`)
    .join("");
}
buildLegend();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("service-worker.js");
  });
}

locateButtonEl = document.querySelector(".locate-button");
startTracking(false);
