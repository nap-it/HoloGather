#!/usr/bin/env bash
set -euo pipefail

# Override MQTT_HOST for a non-local broker; do not commit deployment addresses.
mosquitto_pub -h "${MQTT_HOST:-localhost}" -p "${MQTT_PORT:-1883}" \
  -t "${MQTT_TOPIC:-vam_set_heading}" -m '{"heading": 223}'
