# HoloGather

HoloGather brings the HoloLens sensor publisher and the subscriber reference
implementations into one repository for the WPMC 2026 artifact.

## Repository layout

- [`publisher/`](publisher/) captures, records, replays, and publishes HoloLens
  and external sensor streams.
- [`subscriber-examples/`](subscriber-examples/) contains reference consumers
  for the published Zenoh streams.

Each application keeps its own configuration, Docker Compose project, Python
dependencies, scripts, and documentation so it can still be run independently.

## Clone

Clone with submodules so both applications receive their pinned `hl2ss`
dependency:

```bash
git clone --recurse-submodules https://code.nap.av.it.pt/ar_vr/hologather.git
cd hologather
```

For an existing clone:

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

## Run

Start the publisher:

```bash
cd publisher
./run-publisher.sh
```

Start the subscriber examples from another terminal:

```bash
cd subscriber-examples
./run-subscriber.sh
```

See each application's README for configuration, endpoints, architecture, and
privacy guidance.
