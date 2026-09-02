# Libs Directory

The `libs` directory contains external libraries and deployment configuration
used by the project. Clone with submodules enabled (or initialize them after
cloning):

```bash
git clone --recurse-submodules <repository-url>
# or, in an existing checkout:
git submodule update --init --recursive
```

## Structure

* `hololens_sensor_streaming`: Public `hl2ss` dependency for connecting to and
  processing HoloLens 2 streams.
* `cabasicservice`: Optional MQTT/VAM integration configuration. Its compose
  files refer to local image names by default; provide compatible images using
  the documented environment variables before starting them.

## HoloLens dependency

The publisher imports `hl2ss` through `src/hololens/hl2ss_imports.py`, which
adds the submodule's `viewer` directory to the module search path. Keep the
submodule initialized before enabling HoloLens streams. The dependency is
licensed and maintained upstream. Its license includes a Commons Clause
restriction; review and preserve the upstream terms and release notes before
redistributing a combined source archive.

```python
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm, hl2ss_mp
```
