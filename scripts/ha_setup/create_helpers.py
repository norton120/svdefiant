#!/usr/bin/env -S uv run --with websockets --quiet python
"""
One-shot: create the defiant_* helper entities in Home Assistant.

Reads HOME_ASSISTANT_ACCESS_TOKEN from env (or .env in repo root). Idempotent —
skips creation when an entity with the target unique_id already exists in the
helper's list. Safe to re-run.
"""
import asyncio
import json
import os
import sys
import pathlib

import websockets

HA_HOST = os.environ.get("HA_HOST", "homeassistant.local:8123")
WS_URL = f"ws://{HA_HOST}/api/websocket"

HELPERS = [
    {
        "domain": "input_select",
        "create": {
            "name": "Defiant Mode",
            "icon": "mdi:sail-boat",
            "options": ["underway", "anchored", "moored", "docked", "hauled-out", "unknown"],
            "initial": "unknown",
        },
        "expected_entity_id": "input_select.defiant_mode",
    },
    {
        "domain": "input_text",
        "create": {
            "name": "Defiant Location Name",
            "icon": "mdi:map-marker",
            "max": 100,
        },
        "expected_entity_id": "input_text.defiant_location_name",
    },
    {
        "domain": "input_number",
        "create": {
            "name": "Defiant Latitude",
            "icon": "mdi:latitude",
            "min": -90,
            "max": 90,
            "step": 0.0001,
            "mode": "box",
            "unit_of_measurement": "°",
        },
        "expected_entity_id": "input_number.defiant_latitude",
    },
    {
        "domain": "input_number",
        "create": {
            "name": "Defiant Longitude",
            "icon": "mdi:longitude",
            "min": -180,
            "max": 180,
            "step": 0.0001,
            "mode": "box",
            "unit_of_measurement": "°",
        },
        "expected_entity_id": "input_number.defiant_longitude",
    },
    {
        "domain": "input_text",
        "create": {
            "name": "Defiant Destination",
            "icon": "mdi:map-marker-radius",
            "max": 100,
        },
        "expected_entity_id": "input_text.defiant_destination",
    },
    {
        "domain": "input_number",
        "create": {
            "name": "Defiant Destination Latitude",
            "icon": "mdi:latitude",
            "min": -90,
            "max": 90,
            "step": 0.0001,
            "mode": "box",
            "unit_of_measurement": "°",
        },
        "expected_entity_id": "input_number.defiant_destination_latitude",
    },
    {
        "domain": "input_number",
        "create": {
            "name": "Defiant Destination Longitude",
            "icon": "mdi:longitude",
            "min": -180,
            "max": 180,
            "step": 0.0001,
            "mode": "box",
            "unit_of_measurement": "°",
        },
        "expected_entity_id": "input_number.defiant_destination_longitude",
    },
    {
        "domain": "input_datetime",
        "create": {
            "name": "Defiant ETA",
            "icon": "mdi:clock-outline",
            "has_date": True,
            "has_time": True,
        },
        "expected_entity_id": "input_datetime.defiant_eta",
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


async def main():
    token = load_token()
    msg_id = 0

    async with websockets.connect(WS_URL, max_size=20 * 1024 * 1024) as ws:
        # auth handshake
        hello = json.loads(await ws.recv())
        assert hello["type"] == "auth_required", hello
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth_ok = json.loads(await ws.recv())
        assert auth_ok["type"] == "auth_ok", auth_ok
        print(f"authenticated to HA {auth_ok.get('ha_version')}")

        async def call(payload):
            nonlocal msg_id
            msg_id += 1
            payload = {"id": msg_id, **payload}
            await ws.send(json.dumps(payload))
            while True:
                resp = json.loads(await ws.recv())
                if resp.get("id") == msg_id:
                    return resp

        for h in HELPERS:
            domain = h["domain"]
            expected = h["expected_entity_id"]

            # list existing helpers in this domain
            list_resp = await call({"type": f"{domain}/list"})
            if not list_resp.get("success"):
                print(f"  ! {domain}/list failed: {list_resp}")
                continue

            existing = list_resp["result"]
            match = next(
                (
                    e for e in existing
                    if e.get("name") == h["create"]["name"]
                    or e.get("id") == expected.split(".", 1)[1]
                ),
                None,
            )

            if match:
                print(f"  = {expected} already exists (id={match.get('id')})")
                continue

            create_resp = await call({"type": f"{domain}/create", **h["create"]})
            if create_resp.get("success"):
                created_id = create_resp["result"].get("id")
                print(f"  + created {domain}.{created_id} (name={h['create']['name']!r})")
            else:
                print(f"  ! create failed for {expected}: {create_resp}")


if __name__ == "__main__":
    asyncio.run(main())
