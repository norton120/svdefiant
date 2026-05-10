#!/usr/bin/env -S uv run --with httpx --quiet python
"""
Idempotently create template-sensor helpers in Home Assistant via the
config_entries flow REST API (handler="template"). Re-runnable.

Reads HOME_ASSISTANT_ACCESS_TOKEN from env or repo .env, like create_helpers.py.

Why a separate script: the input_* helpers in create_helpers.py use the
uniform `<domain>/list` + `<domain>/create` WS commands. Template helpers are
created through the config_entries config flow, which is a different shape
(menu → form → create), so the two don't share machinery cleanly.
"""
import os
import sys
import pathlib

import httpx

HA_HOST = os.environ.get("HA_HOST", "homeassistant.local:8123")
BASE = f"http://{HA_HOST}/api"

# Defiant fuel tank: US-standard sender, 240 Ω empty → 33 Ω full (linear).
# pct = clamp((240 - R) / (240 - 33) * 100, 0, 100)
FUEL_LEVEL_TEMPLATE = (
    "{% set r = states('sensor.defiant_analogs_fuel_sender_resistance') | float(none) %}"
    "{% if r is none %}unknown"
    "{% else %}{{ [0, [100, ((240 - r) / 207 * 100)] | min] | max | round(1) }}"
    "{% endif %}"
)

TEMPLATE_HELPERS = [
    {
        "template_type": "sensor",
        "config": {
            "name": "Defiant Fuel Level",
            "state": FUEL_LEVEL_TEMPLATE,
            "unit_of_measurement": "%",
            "state_class": "measurement",
        },
    },
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


def main() -> None:
    token = load_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    with httpx.Client(headers=headers, timeout=10.0) as client:
        # Existing template config entries — match by title to skip already-created helpers.
        entries = client.get(f"{BASE}/config/config_entries/entry?domain=template").json()
        existing_titles = {e.get("title") for e in entries if isinstance(e, dict)}

        for h in TEMPLATE_HELPERS:
            name = h["config"]["name"]
            if name in existing_titles:
                print(f"  = template.{h['template_type']} {name!r} already exists")
                continue

            # Step 1: init the template config flow → menu of template types.
            init = client.post(
                f"{BASE}/config/config_entries/flow",
                json={"handler": "template", "show_advanced_options": False},
            ).json()
            flow_id = init.get("flow_id")
            if init.get("type") != "menu" or not flow_id:
                print(f"  ! flow init failed for {name!r}: {init}")
                continue

            # Step 2: pick the template_type from the menu.
            picked = client.post(
                f"{BASE}/config/config_entries/flow/{flow_id}",
                json={"next_step_id": h["template_type"]},
            ).json()
            if picked.get("type") != "form":
                print(f"  ! flow menu select failed for {name!r}: {picked}")
                continue

            # Step 3: submit the actual config (name + state template + unit, etc.).
            submitted = client.post(
                f"{BASE}/config/config_entries/flow/{flow_id}",
                json=h["config"],
            ).json()
            if submitted.get("type") == "create_entry":
                print(f"  + created template.{h['template_type']} {name!r}")
            else:
                print(f"  ! create failed for {name!r}: {submitted}")


if __name__ == "__main__":
    main()
