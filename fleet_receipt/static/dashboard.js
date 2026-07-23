(() => {
  "use strict";

  const FLEET_MARKER_CLASSES = Object.freeze({
    "Holland America Line": "fleet-map-marker--hal",
    Seabourn: "fleet-map-marker--seabourn",
    "Celebrity Cruises": "fleet-map-marker--celebrity",
    "Royal Caribbean International": "fleet-map-marker--royal-caribbean",
    "Carnival Cruise Line": "fleet-map-marker--carnival",
    "Princess Cruises": "fleet-map-marker--princess",
    Cunard: "fleet-map-marker--cunard",
    "P&O Cruises": "fleet-map-marker--p-and-o",
    "Costa Cruises": "fleet-map-marker--costa",
    "AIDA Cruises": "fleet-map-marker--aida",
  });

  document.addEventListener("DOMContentLoaded", initializeFleetMap, { once: true });

  function initializeFleetMap() {
    const mapElement = document.getElementById("fleet-map");
    const dataElement = document.getElementById("fleet-map-data");

    if (!mapElement || !dataElement) {
      return;
    }

    if (typeof window.L === "undefined") {
      showMapError(mapElement, "The map service is temporarily unavailable.");
      return;
    }

    let ships;
    try {
      ships = JSON.parse(dataElement.textContent);
      if (!Array.isArray(ships)) {
        throw new TypeError("Ship map data must be an array");
      }
    } catch (error) {
      console.error("Fleet map data could not be parsed.", error);
      showMapError(mapElement, "Map data is unavailable.");
      return;
    }

    // Leaflet does not remove existing children from its container.
    // Clear the loading state before it creates panes and controls.
    mapElement.replaceChildren();

    let map;
    try {
      map = window.L.map(mapElement, {
        zoomControl: true,
        worldCopyJump: true,
        preferCanvas: true,
      });

      window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);
    } catch (error) {
      console.error("Leaflet map initialization failed.", error);
      showMapError(mapElement, "The map could not be initialized.");
      return;
    }

    const bounds = [];
    ships.forEach((ship) => {
      try {
        addShipMarker(map, ship, bounds);
      } catch (error) {
        console.error("A ship marker could not be rendered.", ship?.name, error);
      }
    });

    setInitialView(map, bounds);

    // Leaflet measures its canvas during initialization. Recalculate once the
    // browser has completed layout so tiles and marker overlays use the same size.
    window.requestAnimationFrame(() => map.invalidateSize({ pan: false }));
    window.addEventListener(
      "load",
      () => map.invalidateSize({ pan: false }),
      { once: true },
    );
  }

  function addShipMarker(map, ship, bounds) {
    if (!ship || typeof ship !== "object") {
      return;
    }

    const latitude = Number(ship.latitude);
    const longitude = Number(ship.longitude);
    if (
      !Number.isFinite(latitude) ||
      !Number.isFinite(longitude) ||
      latitude < -90 ||
      latitude > 90 ||
      longitude < -180 ||
      longitude > 180
    ) {
      return;
    }

    const marker = window.L.marker([latitude, longitude], {
      icon: fleetIcon(ship.fleet),
      riseOnHover: true,
    });
    marker.bindPopup(popupContent(ship));
    marker.addTo(map);
    bounds.push([latitude, longitude]);
  }

  function fleetIcon(fleet) {
    const markerClass =
      FLEET_MARKER_CLASSES[String(fleet)] || "fleet-map-marker--unknown";
    return window.L.divIcon({
      className: `fleet-map-marker ${markerClass}`,
      html: "",
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      popupAnchor: [0, -10],
    });
  }

  function setInitialView(map, bounds) {
    if (bounds.length === 0) {
      map.setView([20, 0], 2);
    } else if (bounds.length === 1) {
      map.setView(bounds[0], 7);
    } else {
      map.fitBounds(bounds, { padding: [28, 28], maxZoom: 8 });
    }
  }

  function showMapError(mapElement, message) {
    const notice = document.createElement("p");
    notice.className = "map-empty";
    notice.textContent = message;
    mapElement.replaceChildren(notice);
  }

  function popupContent(ship) {
    const container = document.createElement("div");
    const title = document.createElement("strong");
    const fleet = document.createElement("span");
    const details = document.createElement("dl");
    const link = document.createElement("a");

    title.className = "popup-title";
    title.textContent = safeText(ship.name);
    fleet.className = "popup-fleet";
    fleet.textContent = safeText(ship.fleet);
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
      description.textContent = safeText(value);
      details.append(term, description);
    });

    link.className = "popup-link";
    link.href =
      typeof ship.details_url === "string" && ship.details_url.startsWith("/")
        ? ship.details_url
        : "/";
    link.textContent = "View Details →";
    container.append(title, fleet, details, link);
    return container;
  }

  function safeText(value) {
    return value === null || value === undefined || value === ""
      ? "Unavailable"
      : String(value);
  }
})();
