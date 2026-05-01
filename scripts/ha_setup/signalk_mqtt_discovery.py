#!/usr/bin/env -S uv run --with httpx --quiet python
"""
Publish HA MQTT discovery configs for the Signal K topics that
`signalk-mqtt-home-assistant` already pushes to the broker.

The plugin publishes raw SK deltas to bare topics:
    navigation.position           -> {"value":{"latitude":...,"longitude":...}, ...}
    navigation.speedOverGround    -> {"value": <float m/s>, ...}
    navigation.courseOverGroundTrue -> {"value": <float rad>, ...}

This script publishes retained `homeassistant/<component>/<id>/config` messages
through HA's own `mqtt.publish` REST service so HA's MQTT discovery picks them
up and creates entities. Idempotent; running again just rewrites the configs.

To remove the entities later, publish an empty payload to each config topic
(also retained) — HA treats that as a deletion.
"""
import json
import os
import pathlib
import sys

import httpx

HA_HOST = os.environ.get("HA_HOST", "homeassistant.local:8123")
DEVICE = {
    "identifiers": ["defiant_signalk"],
    "name": "Defiant Signal K",
    "manufacturer": "OpenPlotter",
    "model": "signalk-mqtt-home-assistant bridge",
}

# (component, object_id, config payload)
DISCOVERIES = [
    (
        "sensor", "defiant_latitude",
        {
            "name": "Defiant Latitude",
            "unique_id": "defiant_signalk_latitude",
            "state_topic": "navigation.position",
            "value_template": "{{ value_json.value.latitude | round(6) }}",
            "unit_of_measurement": "°",
            "icon": "mdi:latitude",
            "device": DEVICE,
        },
    ),
    (
        "sensor", "defiant_longitude",
        {
            "name": "Defiant Longitude",
            "unique_id": "defiant_signalk_longitude",
            "state_topic": "navigation.position",
            "value_template": "{{ value_json.value.longitude | round(6) }}",
            "unit_of_measurement": "°",
            "icon": "mdi:longitude",
            "device": DEVICE,
        },
    ),
    (
        "sensor", "defiant_speed_over_ground",
        {
            "name": "Defiant Speed Over Ground",
            "unique_id": "defiant_signalk_sog",
            "state_topic": "navigation.speedOverGround",
            # SK gives m/s; convert to knots (1 m/s = 1.94384 kn)
            "value_template": "{{ (value_json.value * 1.94384) | round(2) }}",
            "unit_of_measurement": "kn",
            "icon": "mdi:speedometer",
            "device": DEVICE,
        },
    ),
    (
        "sensor", "defiant_course_over_ground",
        {
            "name": "Defiant Course Over Ground",
            "unique_id": "defiant_signalk_cog",
            "state_topic": "navigation.courseOverGroundTrue",
            "value_template": (
                "{{ ((((value_json.value * 180 / 3.141592653589793) % 360) + 360) % 360) | round(1) }}"
            ),
            "unit_of_measurement": "°",
            "icon": "mdi:compass",
            "device": DEVICE,
        },
    ),
    (
        "device_tracker", "defiant",
        {
            "name": "Defiant",
            "unique_id": "defiant_signalk_tracker",
            "state_topic": "navigation.position",
            "json_attributes_topic": "navigation.position",
            "json_attributes_template": (
                "{{ {'latitude': value_json.value.latitude, "
                "'longitude': value_json.value.longitude, "
                "'gps_accuracy': 5, "
                "'source_type': 'gps'} | tojson }}"
            ),
            # state itself is just a "home" placeholder; HA uses the attrs for position
            "value_template": "not_home",
            "icon": "mdi:sail-boat",
            "device": DEVICE,
        },
    ),
]


def load_token() -> str:
    token = os.environ.get("HOME_ASSISTANT_ACCESS_TOKEN")
    if token:
        return token
    here = pathlib.Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        env_file = parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("HOME_ASSISTANT_ACCESS_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("HOME_ASSISTANT_ACCESS_TOKEN not set and not found in .env")


def main():
    token = load_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    base = f"http://{HA_HOST}"

    with httpx.Client(headers=headers, timeout=10.0) as client:
        for component, object_id, config in DISCOVERIES:
            topic = f"homeassistant/{component}/{object_id}/config"
            payload = json.dumps(config, separators=(",", ":"))
            r = client.post(
                f"{base}/api/services/mqtt/publish",
                json={"topic": topic, "payload": payload, "qos": 0, "retain": True},
            )
            r.raise_for_status()
            print(f"  + published discovery: {topic}")

    print("\nDone. Allow up to 60s (the SK plugin's min interval) for first values.")


if __name__ == "__main__":
    main()
