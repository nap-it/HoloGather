# Recordings Dashboard

The recordings dashboard is a local browser tool for reviewing HoloLens service
recordings. It brings synchronized video, location, and orientation data
together so you can spot missing streams, timing problems, and spatial
inconsistencies before using a recording in a dataset.

## What it shows

- **GPS and RGB:** compare the camera video with the VAM or phone location track
  and device heading on a map.
- **RGB and depth:** play and seek the color and depth videos together.
- **Heading field:** inspect heading vectors along the recorded route.
- **Head pose:** view pitch and roll alongside the synchronized recording.

The dashboard is a review aid. It does not alter recordings or determine
automatically whether a run passes validation.

## Requirements

- Python 3.10 or later.
- `msgpack`, needed only when generating dashboard data from `.hlp2` files.
- Internet access in the browser for the Leaflet map library and map tiles.

The server and dashboard pages use only the Python standard library. Install the
extractor dependency from this directory:

```bash
python3 -m pip install -r requirements.txt
```

## Configure recordings

Set `recordings_path` in [`config.json`](config.json) to the directory that
contains the `hololens_recording_*` folders. Relative paths are resolved from
this dashboard directory. The default points to `publisher/recordings` in this
repository; an absolute path can be used for recordings stored elsewhere.

Each recording folder can contain HLP2 streams and, optionally, the generated
video files:

```text
hololens_recording_<timestamp>/
├── HololensCamera_1.hlp2
├── vam_location_1.hlp2
├── phone_location_1.hlp2
├── unity_heading_1.hlp2
├── unity_imu_1.hlp2
├── validation_rgb.mp4       # optional
└── validation_depth.mp4    # optional
```

The extractor uses the HLP2 streams to create the map, orientation, and timing
data. The MP4 files are optional and are served directly from the recordings
directory; they are not copied into this repository. `validation_rgb.mp4` and
`validation_depth.mp4` must be created separately and placed in the matching
recording folder.

## Generate data and start the dashboard

From this directory, rebuild the dashboard data after adding or removing
recordings:

```bash
python3 scripts/extract_dashboard_data.py
```

The extractor writes one JSON file per recording and refreshes
`data/index.json`. To use a different recordings directory for one run, pass it
directly:

```bash
python3 scripts/extract_dashboard_data.py --recordings /path/to/recordings
```

Start the local server:

```bash
python3 scripts/serve_dashboard.py
```

Then open <http://localhost:8080/pages/index.html>. Choose another port with `--port`:

```bash
python3 scripts/serve_dashboard.py --port 9000
```

The server supports byte-range requests so browser video seeking works. Stop it
with `Ctrl+C`.

Alternatively, use the convenience script to serve the checked-in data, or
rebuild data before serving:

```bash
./run-dashboard.sh
./run-dashboard.sh --extract
```

## Repository contents

| Path | Description |
|---|---|
| `pages/index.html` | Recording catalogue and dashboard entry point |
| `pages/validate_gps.html` | GPS, heading, and RGB review |
| `pages/validate_depth.html` | Synchronized RGB and depth review |
| `pages/heading_field.html` | Heading vectors along the route |
| `data/` | Generated JSON used by the dashboard; sample index and runs are included |
| `scripts/extract_dashboard_data.py` | Reads HLP2 recordings and builds the JSON data |
| `scripts/serve_dashboard.py` | Serves pages, data, and configured videos locally |
| `run-dashboard.sh` | Convenience launcher for the server and optional extraction |

## Data and privacy

Recording files and generated videos should remain outside the repository.
Generated dashboard JSON can contain precise location traces, timestamps, and
orientation data. Review it before committing or publishing, and only share data
that has been approved for release.

The browser loads Leaflet and map tiles from external services, so map display
requires an internet connection. Video and recording data are served by the
local dashboard server.

## Attribution

Developed by Rodrigo Abreu as part of the SafeXCity project.
