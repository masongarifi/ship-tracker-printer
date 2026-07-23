(() => {
  "use strict";

  const mapElement = document.getElementById("fleet-map");
  const dataElement = document.getElementById("fleet-map-data");

  if (!mapElement || !dataElement) {
    return;
  }

  if (typeof window.L === "undefined") {
    mapElement.innerHTML =
      '<p class="map-empty">The map service is temporarily unavailable.</p>';
    return;
  }

  let ships = [];
  try {
    ships = JSON.parse(dataElement.textContent);
  } catch {
    mapElement.innerHTML = '<p class="map-empty">Map data is unavailable.</p>';
    return;
  }

  const map = window.L.map(mapElement, {
    zoomControl: true,
    worldCopyJump: true,
    preferCanvas: true,
  });

  window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const bounds = [];
  ships.forEach((ship) => {
    if (!Number.isFinite(ship.latitude) || !Number.isFinite(ship.longitude)) {
      return;
    }

    const marker = window.L.circleMarker([ship.latitude, ship.longitude], {
      radius: 6,
      weight: 2,
      color: "#ffffff",
      fillColor: statusColor(ship.status),
      fillOpacity: 0.95,
    });
    marker.bindPopup(popupContent(ship));
    marker.addTo(map);
    bounds.push([ship.latitude, ship.longitude]);
  });

  if (bounds.length === 0) {
    map.setView([20, 0], 2);
  } else if (bounds.length === 1) {
    map.setView(bounds[0], 7);
  } else {
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: 8 });
  }

  function statusColor(status) {
    const normalized = String(status).toLowerCase();
    if (normalized.includes("underway") || normalized.includes("under way")) {
      return "#2186cf";
    }
    if (normalized.includes("moored")) {
      return "#31a66a";
    }
    if (normalized.includes("anchor")) {
      return "#d79b2e";
    }
    return "#667b8d";
  }

  function popupContent(ship) {
    const container = document.createElement("div");
    const title = document.createElement("strong");
    const fleet = document.createElement("span");
    const details = document.createElement("dl");
    const link = document.createElement("a");

    title.className = "popup-title";
    title.textContent = ship.name;
    fleet.className = "popup-fleet";
    fleet.textContent = ship.fleet;
    details.className = "popup-grid";

    [
      ["Status", ship.status],
      ["Speed", ship.speed],
      ["Course", ship.course],
      ["Destination", ship.destination],
      ["ETA", ship.eta],
    ].forEach(([label, value]) => {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = value;
      details.append(term, description);
    });

    link.className = "popup-link";
    link.href = ship.details_url;
    link.textContent = "View Details →";
    container.append(title, fleet, details, link);
    return container;
  }
})();
