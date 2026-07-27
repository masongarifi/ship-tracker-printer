# Fleet Receipt

Fleet Receipt is an offline-first Python application for producing readable
multi-brand fleet operations briefings. Its target is an Epson TM-L90 connected
to a Raspberry Pi; the safe text backend supports development before printer
hardware is connected.

The fleet is configuration, not application code. All 208 configured vessels
and their IMO/MMSI identifiers are in `config/fleet.yaml`.

| Profile | Fleet | Vessels |
| --- | --- | ---: |
| `hal` | Holland America Line | 11 |
| `seabourn` | Seabourn | 5 |
| `celebrity` | Celebrity Cruises | 15 |
| `royal-caribbean` | Royal Caribbean International | 30 |
| `carnival` | Carnival Cruise Line | 29 |
| `princess` | Princess Cruises | 17 |
| `cunard` | Cunard | 4 |
| `p-and-o` | P&O Cruises | 7 |
| `costa` | Costa Cruises | 9 |
| `aida` | AIDA Cruises | 11 |
| `msc` | MSC Cruises | 23 |
| `ncl` | Norwegian Cruise Line | 21 |
| `dcl` | Disney Cruise Line | 8 |
| `vv` | Virgin Voyages | 4 |
| `oceania` | Oceania Cruises | 8 |
| `regent` | Regent Seven Seas Cruises | 6 |

## Phase 1 capabilities

- Complete fixture receipt for all configured active vessels
- Cruise-line grouping and alphabetical vessel ordering
- Actual readable AIS navigational status wording
- Current location kept separate from reported destination
- Offline port, region, and coordinate location fallbacks
- Estimated local time and natural comparison with Seattle
- Configurable word-safe receipt wrapping
- Persistent SQLite position cache with stale and unavailable-position output
- Live AISstream.io position collection filtered to configured fleet MMSIs
- Local receipt-style web view with health and plain-text endpoints
- Text-only preview that cannot consume paper

CUPS/ESC-POS printing, systemd, and GPIO are later deployment phases.

## Continuously cache live AISstream.io data

Put the API key in the repository-root `.env` file:

```dotenv
AISSTREAM_API_KEY=your-key-here
```

The file is ignored by Git. Install the updated dependencies, then run the
long-lived listener:

```bash
python -m pip install -e .
python -m fleet_receipt listen
```

It reconnects automatically and transactionally updates one SQLite row whenever
a configured vessel transmits. Keep this process running as a background service
on the Raspberry Pi.

## Persistent cache storage

The cache is deliberately outside the Git checkout and virtual environment.
Default locations are:

- Raspberry Pi/Linux: `~/.local/share/ship-tracker-printer/ais-cache.sqlite3`
- Windows: `%LOCALAPPDATA%\ship-tracker-printer\ais-cache.sqlite3`
- macOS: `~/Library/Application Support/ship-tracker-printer/ais-cache.sqlite3`

Linux honors `XDG_DATA_HOME`. For a deliberate operational override, set
`SHIP_TRACKER_DATA_DIR` to the directory that should contain the database.

SQLite uses write-ahead logging, full synchronous writes, one transaction per
AIS update, and one row per vessel. A listener restart loads every existing row
before connecting to AISstream. Therefore old positions are immediately
printable and remain available through reboots, editable installs, Git pulls,
checkout replacement, listener crashes, and unexpected power loss.

On first startup after upgrading from the old implementation, the listener
automatically imports `work/position-cache.json` into the external SQLite
database if the database does not already exist. The legacy file is left intact
as a recovery copy.

The button/print path reads the cache immediately and does not contact
AISstream.io:

```bash
python -m fleet_receipt preview --cached
```

For a one-off diagnostic collection, the bounded live preview remains available:

```bash
python -m fleet_receipt preview --live --wait 60
```

AISstream.io only emits new radio reports. The cache retains the newest received
position for every vessel across reconnects and reports its age on the receipt.
The subscription sends only the configured MMSIs and requests `PositionReport`
plus `ShipStaticData` messages. Static reports supply destination and ETA when
the vessel broadcasts them.

One listener tracks every active ship from every configured fleet profile over
one AISstream.io websocket connection. Because AISstream.io permits at most 50
MMSIs per subscription, the listener rotates a deduplicated 50-ship window
across all 208 ships every 30 seconds. Five consecutive windows cover the full
fleet. All updates are written to the same persistent SQLite cache.
Fleet-specific commands and web pages only filter what is displayed; they do
not start another listener or create another database.

AIS destination strings are normalized before printing using the complete
official UNECE UN/LOCODE release. Routes such as `GB SOU > NL RTM` become
`Southampton, United Kingdom → Rotterdam, Netherlands`, and ETA is explicitly
labelled UTC. Unknown endpoints remain visible in a cleaned, title-cased form
rather than being discarded.

## Complete UN/LOCODE database

The listener automatically downloads and indexes the official UNECE 2025-1
release the first time it starts. The release contains more than 100,000
locations. The resulting offline index is stored outside Git at:

```text
~/.local/share/ship-tracker-printer/unlocode.sqlite3
```

This keeps receipt lookup fast and available without network access. It also
avoids redistributing UNECE data through this repository. To manage it manually:

```bash
fleet-receipt unlocode status
fleet-receipt unlocode sync
```

The small `UNLOCODE_PORTS` dictionary in `formatting_helpers.py` is only an
emergency fallback for a few common codes when the official index has not yet
been downloaded. The primary lookup uses the full local database.

Official source and usage terms:

- <https://unlocode.unece.org/publications/>
- <https://unlocode.unece.org/terms/>

The receipt begins with per-line reporting counts and identifies the AIS source.
Ships with cached but old positions remain in the report under `Last AIS report`.
Ships never observed by the listener are consolidated under `NO RECENT AIS`;
listener health determines whether that section describes a feed error or the
normal limits of terrestrial AIS coverage.

## Local web interface

Run the web interface from the activated project environment:

```bash
fleet-receipt web
```

It listens on `0.0.0.0:8000` by default. From a laptop or phone on the same
network, open either:

```text
http://raspberrypi.local:8000/
http://YOUR_PI_IP_ADDRESS:8000/
```

The homepage is a responsive maritime operations dashboard built directly from
the persistent SQLite cache. It includes fleet summary cards, an interactive
Leaflet/OpenStreetMap world map, fleet statistics, cache-derived spotlights,
and ship search by name, IMO, or MMSI. It never contacts an AIS provider.

The fleet-specific pages continue using the same narrow receipt renderer as
`fleet-receipt preview --cached`, so cached positions appear immediately even
when the listener is restarting or AISstream.io is temporarily disconnected.
Those receipt pages automatically refresh every 30 seconds.

Available routes:

- `/` — Fleet Tracker dashboard
- `/hal-seabourn` — combined Holland America and Seabourn receipt report
- `/hal` — Holland America receipt report
- `/seabourn` — Seabourn receipt report
- `/celebrity` — Celebrity Cruises report
- `/profile/celebrity` — alternate Celebrity Cruises route
- `/royal-caribbean` — Royal Caribbean International report
- `/profile/royal-caribbean` — alternate Royal Caribbean route
- `/carnival` and `/profile/carnival` — Carnival Cruise Line report
- `/princess` and `/profile/princess` — Princess Cruises report
- `/cunard` and `/profile/cunard` — Cunard report
- `/p-and-o` and `/profile/p-and-o` — P&O Cruises report
- `/costa` and `/profile/costa` — Costa Cruises report
- `/aida` and `/profile/aida` — AIDA Cruises report
- `/msc` and `/profile/msc` — MSC Cruises report
- `/ncl` and `/profile/ncl` — Norwegian Cruise Line report
- `/dcl` and `/profile/dcl` — Disney Cruise Line report
- `/virgin-voyages` and `/profile/vv` — Virgin Voyages report
- `/oceania` and `/profile/oceania` — Oceania Cruises report
- `/regent` and `/profile/regent` — Regent Seven Seas Cruises report
- `/all` — every configured fleet, grouped by cruise line
- `/search?q=...` — ship search by name, IMO, or MMSI
- `/ship/{ship-name}` — cached vessel details
- `/api/report` — the same rendered report as UTF-8 plain text
- `/health` — cache availability, vessel count, and newest AIS update age

The dashboard is also available through the configured Cloudflare Tunnel at
`https://fleettracker.masongarifi.com`. Leaflet and OpenStreetMap tiles are
loaded by the browser; all vessel data is rendered from the local cache.

The cache records `underway_since` in each vessel's existing JSON position
payload. It is set when the listener first observes a vessel underway or
observes a transition from a non-underway status, preserved while subsequent
reports remain underway, and cleared when the vessel is no longer underway.
The dashboard's longest-underway value is therefore based on observed AIS
transitions. It may not be the true voyage start when the listener was offline,
AIS coverage was lost, or the vessel was already underway when first observed.
Recent departures, arrivals, and other status history remain unavailable.

To print the Celebrity report from the shared cache:

```bash
fleet-receipt preview --cached --fleet celebrity
```

To print the 30-ship Royal Caribbean report from the same cache:

```bash
fleet-receipt preview --cached --fleet royal-caribbean
```

To preview every configured fleet:

```bash
fleet-receipt preview --cached --fleet all
```

To add another fleet, append one cruise-line object to `config/fleet.yaml` with
a stable `profile`, official display `name`, and active vessels. Each vessel
requires its official name, validated seven-digit IMO, and current nine-digit
MMSI. Optional `aliases` remain separate from the display name and participate
in search. Add one entry to `FLEET_PROFILES` for its homepage card and one pair
of generic web routes that reuse `profile_page`; no listener or database work is
needed.

Fleet membership was checked against Carnival Corporation's May 31, 2026 fleet
report and current brand fleet pages. IMO and current MMSI values were
cross-checked against public AIS vessel registries where available. Carnival
Adventure and Carnival Encounter are included under Carnival following the
closure of P&O Cruises Australia; that former brand is not configured
separately. Announced, ordered, retired, scrapped, and transferred-out ships are
excluded. Costa Fortuna remains included through its scheduled September 2026
departure.

Optional bind overrides are available for local troubleshooting:

```bash
fleet-receipt web --host 127.0.0.1 --port 8080
```

The server does not display API keys, environment variables, or cache paths.
It has no login or TLS, so keep it on a trusted local network and do not expose
port 8000 directly to the public internet.

## Create the Python environment

On Raspberry Pi OS or Debian:

```bash
sudo apt update
sudo apt install -y python3 python3-venv
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

On macOS, use the same commands without `apt` after installing Python 3.10 or
newer. Python 3.11 or newer is recommended for the Raspberry Pi deployment.

## Preview using fixtures

From the repository root:

```bash
. .venv/bin/activate
fleet-receipt preview --fixtures
```

Without installing the console entry point:

```bash
python3 -m fleet_receipt preview --fixtures
```

For the deterministic acceptance snapshot:

```bash
python3 -m fleet_receipt preview --fixtures --at 2026-07-22T23:18:00Z
```

Override the configured width for a preview:

```bash
python3 -m fleet_receipt preview --fixtures --width 48
```

Preview mode writes only to standard output. It does not inspect or contact a printer.

## Emulate printing to a text file

Write the exact receipt payload to a local UTF-8 text file:

```bash
python3 -m fleet_receipt preview --fixtures --output work/fleet-receipt.txt
```

For a deterministic file that can be compared byte-for-byte in tests:

```bash
python3 -m fleet_receipt preview --fixtures --at 2026-07-22T23:18:00Z --output work/fleet-receipt.txt
```

The command creates missing parent directories and never contacts printer hardware.

## Print on the Epson TM-L90

Connect and power on the TM-L90 with its UB-U05 USB interface, then print the
same canonical receipt produced by preview:

```bash
fleet-receipt print --cached
fleet-receipt print --cached --fleet main
```

`print` supports the same receipt inputs and controls as `preview`:
`--fixtures`, `--live`, `--cached`, `--wait`, `--at`, `--width`, and `--fleet`.
It sends the already-formatted text to USB device `04b8:0202`, feeds six blank
lines, and requests a full cut. A failed or unsupported cut is reported after
the receipt has printed so it can be torn off manually.

On Linux, grant the service user access to the USB printer with a udev rule:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04b8", ATTR{idProduct}=="0202", MODE="0660", GROUP="lp"' | sudo tee /etc/udev/rules.d/99-epson-tm-l90.rules
sudo usermod -aG lp "$USER"
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Reconnect the printer and start a new login session after adding the group.
On Windows, the Python USB stack also requires a compatible libusb driver for
the UB-U05 interface. Missing dependencies, an absent printer, USB permission
problems, and failed jobs produce actionable errors without changing preview
or the cached receipt.

## Configure the fleet

Edit `config/fleet.yaml`. It is JSON-compatible YAML so Phase 1 can run even before PyYAML is installed. Each entry supports:

```yaml
{
  "name": "Eurodam",
  "imo": null,
  "mmsi": null,
  "active": true,
  "notes": "IMO and MMSI unresolved"
}
```

The cruise line comes from the containing `cruise_lines` entry. Set `active` to `false` to retain a vessel without printing it. Do not enter an IMO or MMSI until it has been verified from a reliable source.

## AIS status and destination wording

The normalized navigational status is preserved as readable wording. Moored and anchored ships say where their coordinates place them. Underway ships say where they report they are going when a destination exists, or where they currently are when it does not.

A reported AIS destination is never treated as proof that the ship is currently at that port.

## Settings

Edit `config/settings.yaml` to change the receipt width or stale threshold:

```yaml
{
  "receipt_width": 42,
  "stale_after_hours": 6,
  "seattle_timezone": "America/Los_Angeles",
  "update_interval_minutes": 15
}
```

The update interval is reserved for the scheduled-cache phase.

## Run tests

```bash
. .venv/bin/activate
python -m pytest
```

Run with coverage:

```bash
python -m pytest --cov=fleet_receipt --cov-report=term-missing
```

The tests require neither internet access nor printer hardware.

## MarineTraffic configuration

MarineTraffic is the intended production provider, but Phase 1 intentionally contains only a stub. No endpoint, authentication scheme, or response format has been guessed.

When the official API documentation, account plan limits, credentials mechanism, and a redacted sample response are available:

```bash
cp .env.example .env
chmod 600 .env
```

Then set `MARINETRAFFIC_API_KEY` locally. `.env` is ignored by Git. Never place credentials in YAML, fixture data, logs, tests, or source code.

## Printer configuration

The physical backend uses `python-escpos` and raw USB ESC/POS for the Epson
TM-L90 (`04b8:0202`). To inspect a target Raspberry Pi installation:

```bash
uname -a
cat /etc/os-release
lpstat -t
lpinfo -v
lpinfo -m | grep -i epson
lsusb
systemctl status cups --no-pager
journalctl -u cups --no-pager -n 100
```

`lsusb` should list the Epson device before running `fleet-receipt print`.

## GPIO and systemd

GPIO and systemd are intentionally deferred. The settings reserve the action name `fleet_position_report`; the eventual button service will map a configurable pin to that action and print cached data without contacting the API.

The future scheduled updater will use a systemd timer with a 15-minute default. Exact installation commands will be documented when those units exist; there are no placeholder units in Phase 1 that could incorrectly imply a working service.

### Local cached print API

The running web process provides `GET /api/print-report` for the independent
Morning Briefing button service. It reads the existing SQLite cache only: it
does not invoke a provider, refresh AIS, or alter listener/service state. The
JSON includes active Holland America Line and Seabourn ships in line/name order,
including explicit stale and unavailable records. All other cruise lines are
excluded.

The route verifies that the request client is a loopback address and returns
HTTP 403 to LAN clients. Use:

```bash
curl http://127.0.0.1:8000/api/print-report
```

## Troubleshooting

### `No module named yaml`

The committed configuration is JSON-compatible YAML and does not require PyYAML. If you change it to conventional YAML syntax, install project dependencies:

```bash
python -m pip install -e '.[dev]'
```

### Receipt data looks old

Fixture timestamps are intentionally fixed for repeatable tests. Use the deterministic `--at` command shown above to view the designed fresh/stale mix.

### MarineTraffic reports that it is not configured

That is expected in Phase 1. Fixture preview remains fully operational. Live integration waits for the official contract and account details.

### Printer does not appear

Phase 1 does not access printers. Run the read-only Raspberry Pi commands in the printer section and retain their complete output for Phase 2 diagnosis.
