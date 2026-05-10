#!/usr/bin/env -S uv run --with websockets --with httpx --quiet python
"""
Idempotently create the four new LCARS dashboards (Overview, Helm, Navigation,
Systems) and the two missing aggregate template sensors (solar power now, solar
yield today). Re-runnable: existing dashboards/sensors are detected by url_path
or entry title and skipped if already present, but their config is always
re-saved so this script is the source of truth.

Reads HOME_ASSISTANT_ACCESS_TOKEN from env or repo .env.

Why one script: the four dashboards share LCARS card-builder helpers, and they
all need the same WS connection. Splitting would duplicate the connection
plumbing for no benefit.
"""

import asyncio
import json
import os
import pathlib
import sys

import httpx
import websockets

HA_HOST = os.environ.get("HA_HOST", "homeassistant.local:8123")
WS_URL = f"ws://{HA_HOST}/api/websocket"
REST_BASE = f"http://{HA_HOST}/api"


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


# --------------------------------------------------------------------------- #
# Template sensor helpers (REST flow API).                                    #
# --------------------------------------------------------------------------- #

SOLAR_POWER_NOW_TPL = (
    "{{ "
    "(states('sensor.port_bimini_solar_power') | float(0)) + "
    "(states('sensor.starboard_bimini_solar_power') | float(0)) + "
    "(states('sensor.port_davits_solar_power') | float(0)) + "
    "(states('sensor.starboard_davits_solar_power') | float(0)) "
    "}}"
)
SOLAR_YIELD_TODAY_TPL = (
    "{{ "
    "(states('sensor.port_bimini_yield_today') | float(0)) + "
    "(states('sensor.starboard_bimini_yield_today') | float(0)) + "
    "(states('sensor.port_davits_yield_today') | float(0)) + "
    "(states('sensor.starboard_davits_yield_today') | float(0)) "
    "}}"
)

TEMPLATE_HELPERS = [
    {
        "template_type": "sensor",
        "config": {
            "name": "Solar Power Now",
            "state": SOLAR_POWER_NOW_TPL,
            "unit_of_measurement": "W",
            "state_class": "measurement",
            "device_class": "power",
        },
    },
    {
        "template_type": "sensor",
        "config": {
            "name": "Solar Yield Today",
            "state": SOLAR_YIELD_TODAY_TPL,
            "unit_of_measurement": "Wh",
            "state_class": "total_increasing",
            "device_class": "energy",
        },
    },
]


def create_template_helpers(token: str) -> None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=10.0) as client:
        entries = client.get(
            f"{REST_BASE}/config/config_entries/entry?domain=template"
        ).json()
        existing = {e.get("title") for e in entries if isinstance(e, dict)}

        for h in TEMPLATE_HELPERS:
            name = h["config"]["name"]
            if name in existing:
                print(f"  = template {name!r} already exists")
                continue
            init = client.post(
                f"{REST_BASE}/config/config_entries/flow",
                json={"handler": "template", "show_advanced_options": False},
            ).json()
            flow_id = init.get("flow_id")
            if init.get("type") != "menu" or not flow_id:
                print(f"  ! flow init failed for {name!r}: {init}")
                continue
            picked = client.post(
                f"{REST_BASE}/config/config_entries/flow/{flow_id}",
                json={"next_step_id": h["template_type"]},
            ).json()
            if picked.get("type") != "form":
                print(f"  ! menu select failed for {name!r}: {picked}")
                continue
            done = client.post(
                f"{REST_BASE}/config/config_entries/flow/{flow_id}",
                json=h["config"],
            ).json()
            if done.get("type") == "create_entry":
                print(f"  + created template sensor {name!r}")
            else:
                print(f"  ! create failed for {name!r}: {done}")


# --------------------------------------------------------------------------- #
# LCARS card builders.                                                        #
# --------------------------------------------------------------------------- #

def lcars_multimeter(entity, label, vmin=0, vmax=100, mode="gauge", columns=12, rows=4):
    """LCARS multimeter card (gauge or slider) with Picard styling."""
    return {
        "type": "custom:cb-lcars-multimeter-card",
        "template": ["cb-lcars-animation-geo-array"],
        "enable_resize_observer": True,
        "variables": {
            "_mode": mode,
            "_vertical": False,
            "_slider_mode": "brightness",
            "gauge": {
                "sub_meter": {"show_sub_meter": False, "tick_count": 0},
                "range": {"enabled": True},
            },
            "slider_track": {
                "bar_thickness": 10,
                "gap": 5,
                "bar_border_radius": 0,
            },
            "animation": {
                "geo_array": {
                    "animation_axis": "col",
                    "grid": {"num_cols": 3, "num_rows": 1},
                }
            },
            "_min": vmin,
            "_max": vmax,
            "_increment": 1,
            "_show_unit_of_measurement": True,
            "entity": entity,
            "_gauge_style": "picard",
        },
        "tap_action": {"action": "more-info"},
        "double_tap_action": {"action": "none"},
        "hold_action": {"action": "none"},
        "show_label": True,
        "label": label,
        "grid_options": {"columns": columns, "rows": rows},
    }


def lcars_label(entity, label_template="[[[ return entity.state; ]]]"):
    """Big LCARS square label, used for state readouts."""
    return {
        "type": "custom:cb-lcars-label-card",
        "label": label_template,
        "enable_resize_observer": True,
        "cblcars_card_type": "cb-lcars-label-picard-square",
        "show_label": True,
        "variables": {"entity": entity},
        "tap_action": {"action": "more-info"},
        "double_tap_action": {"action": "none"},
        "hold_action": {"action": "none"},
    }


def lcars_button(entity, label, tap="more-info", color_zero="var(--lcars-alt-dark-gray)",
                 color_nonzero="var(--lcars-alert-blue)", show_state=True, show_icon=True):
    """LCARS Picard pill-button. Use for state-indicating buttons."""
    return {
        "type": "custom:cb-lcars-button-card",
        "cblcars_card_type": "cb-lcars-button-picard",
        "show_label": True,
        "variables": {
            "label": label,
            "entity": entity,
            "card": {
                "color": {
                    "zero": color_zero,
                    "non_zero": color_nonzero,
                }
            },
        },
        "tap_action": {"action": tap},
        "double_tap_action": {"action": "none"},
        "hold_action": {"action": "more-info"},
        "show_icon": show_icon,
        "show_state": show_state,
        "show_advanced": False,
    }


def heading(text, style="title", icon=None):
    h = {"type": "heading", "heading_style": style, "heading": text}
    if icon:
        h["icon"] = icon
    return h


def gauge(entity, name, vmin=0, vmax=100, severity=None, unit=None):
    g = {
        "type": "gauge",
        "entity": entity,
        "name": name,
        "needle": True,
        "min": vmin,
        "max": vmax,
        "tap_action": {"action": "more-info"},
    }
    if severity:
        g["severity"] = severity
    if unit:
        g["unit"] = unit
    return g


def md(content, columns=None):
    c = {"type": "markdown", "content": content}
    if columns is not None:
        c["grid_options"] = {"columns": columns, "rows": "auto"}
    return c


def grid_section(cards, column_span=4):
    return {"type": "grid", "cards": cards, "column_span": column_span}


# --------------------------------------------------------------------------- #
# Dashboard configs.                                                          #
# --------------------------------------------------------------------------- #

def cfg_overview():
    """Exception-surface + activity timeline. Default home: 'is anything wrong'
    and 'what's happening on the boat'. Desktop-first wide layout. Live numbers
    live on Power/Helm/etc — Overview is signal, not status."""

    # Entities tracked by "Last seen" — a subsystem is considered offline if its
    # state hasn't changed in too long. Tuples: (entity, label, stale_minutes).
    LAST_SEEN = [
        ("sensor.openplotter_status", "openplotter (nav Pi)", 30),
        ("sensor.boatflix_status", "boatflix (media Pi)", 60),
        ("sensor.ironclaw_status", "ironclaw (agent Pi)", 30),
        ("sensor.gx_device_dc_battery_voltage", "Cerbo GX", 15),
        ("sensor.lithium_core_voltage", "Lithium Core BMS", 15),
        ("sensor.defiant_signal_k_defiant_latitude", "Signal K nav", 30),
        ("sensor.pro_check_universal_705d_tank_level", "Propane sensor", 240),
        ("sensor.defiant_analogs_fuel_sender_voltage", "Fuel sender", 30),
        ("sensor.ethans_iphone_battery_level", "iPhone", 60),
    ]

    last_seen_md = (
        "| Subsystem | Last update | State |\n"
        "|---|---|---|\n"
        + "".join(
            f"| {{% set s = states.{e} %}}{label} "
            f"| {{% if s %}}{{{{ relative_time(s.last_updated) }}}} ago"
            f"{{% else %}}—{{% endif %}} "
            f"| {{% if s %}}"
            f"{{% set age_m = (now() - s.last_updated).total_seconds() / 60 %}}"
            f"{{% if age_m > {stale} %}}🟥 stale"
            f"{{% elif s.state in ['unavailable','unknown'] %}}🟥 {{{{ s.state }}}}"
            f"{{% else %}}🟢 {{{{ s.state }}}}{{% endif %}}"
            f"{{% else %}}🟥 missing{{% endif %}} |\n"
            for e, label, stale in LAST_SEEN
        )
    )

    return {
        "views": [
            {
                "title": "Status",
                "icon": "mdi:sail-boat",
                "type": "sections",
                "max_columns": 3,
                "sections": [
                    # ---------------- Banner: one line, computed ----------------
                    grid_section([
                        md(
                            "{% set alarms = ["
                            "'sensor.multi_id_276_low_battery_alarm',"
                            "'sensor.multi_id_276_overload_alarm',"
                            "'sensor.multi_id_276_high_temperature_alarm',"
                            "'sensor.multi_id_276_grid_lost_alarm',"
                            "'sensor.multi_id_276_high_dc_voltage_alarm',"
                            "'sensor.multi_id_276_high_dc_current_alarm',"
                            "'sensor.multi_id_276_voltage_sensor_alarm',"
                            "'sensor.multi_id_276_temperature_sensor_alarm',"
                            "'sensor.lithium_core_alarm',"
                            "'sensor.windy_alarm'"
                            "] %}"
                            "{% set probs = ["
                            "'binary_sensor.xdzn_001_070f_problem',"
                            "'binary_sensor.xdzn_001_7986_problem',"
                            "'binary_sensor.xdzn_001_9bfe_problem',"
                            "'binary_sensor.xdzn_001_75ed_problem',"
                            "'binary_sensor.xdzn_001_160b_problem',"
                            "'binary_sensor.xdzn_001_791e_problem',"
                            "'binary_sensor.wtaeaaa25342478_problem',"
                            "'binary_sensor.c0_d6_3c_58_86_c0_problem',"
                            "'binary_sensor.wtaeaaa25344520_problem',"
                            "'binary_sensor.xdzn_001_fbd5_problem'"
                            "] %}"
                            "{% set safe = ['no_alarm','unknown','unavailable','none','no_error'] %}"
                            "{% set active = alarms | reject('in', safe, attribute=none) | list %}"
                            "{% set bad_bms = probs | select('is_state','on') | list %}"
                            "{% set bad_alarms = alarms | rejectattr('0') | list %}"
                            "{% set bad = namespace(c=0) %}"
                            "{% for a in alarms %}{% if states(a) not in safe %}{% set bad.c = bad.c + 1 %}{% endif %}{% endfor %}"
                            "{% set total = bad.c + (bad_bms | count) %}"
                            "{% if total == 0 %}"
                            "## ✅ All systems nominal\n"
                            "_Mode_ {{ states('input_select.defiant_mode') }} "
                            "&nbsp;·&nbsp; _AC_ {{ states('sensor.gx_device_ac_active_input_source') }} "
                            "&nbsp;·&nbsp; _SOC_ {{ states('sensor.lithium_core_battery') }}% "
                            "&nbsp;·&nbsp; _Solar_ {{ states('sensor.solar_power_now') | float(0) | round(0) }} W"
                            "{% else %}"
                            "## 🚨 {{ total }} active alert{{ 's' if total > 1 else '' }}\n"
                            "_See alerts panel below._"
                            "{% endif %}"
                        ),
                    ], column_span=3),

                    # ---------------- Conditional: alerts panel ----------------
                    {
                        "type": "grid",
                        "column_span": 3,
                        "cards": [
                            heading("Alerts", "subtitle"),
                            {
                                "type": "conditional",
                                "conditions": [
                                    {"condition": "or", "conditions": [
                                        {"condition": "state",
                                         "entity": e,
                                         "state_not": s}
                                        for e in [
                                            "sensor.multi_id_276_low_battery_alarm",
                                            "sensor.multi_id_276_overload_alarm",
                                            "sensor.multi_id_276_high_temperature_alarm",
                                            "sensor.multi_id_276_grid_lost_alarm",
                                            "sensor.multi_id_276_high_dc_voltage_alarm",
                                            "sensor.multi_id_276_high_dc_current_alarm",
                                            "sensor.multi_id_276_voltage_sensor_alarm",
                                            "sensor.multi_id_276_temperature_sensor_alarm",
                                            "sensor.lithium_core_alarm",
                                            "sensor.windy_alarm",
                                        ]
                                        for s in ["no_alarm"]
                                    ] + [
                                        {"condition": "state",
                                         "entity": f"binary_sensor.{p}_problem",
                                         "state": "on"}
                                        for p in [
                                            "xdzn_001_070f", "xdzn_001_7986", "xdzn_001_9bfe",
                                            "xdzn_001_75ed", "xdzn_001_160b", "xdzn_001_791e",
                                            "wtaeaaa25342478", "c0_d6_3c_58_86_c0",
                                            "wtaeaaa25344520", "xdzn_001_fbd5",
                                        ]
                                    ]}
                                ],
                                "card": md(
                                    "{% set alarms = ["
                                    "'sensor.multi_id_276_low_battery_alarm',"
                                    "'sensor.multi_id_276_overload_alarm',"
                                    "'sensor.multi_id_276_high_temperature_alarm',"
                                    "'sensor.multi_id_276_grid_lost_alarm',"
                                    "'sensor.multi_id_276_high_dc_voltage_alarm',"
                                    "'sensor.multi_id_276_high_dc_current_alarm',"
                                    "'sensor.multi_id_276_voltage_sensor_alarm',"
                                    "'sensor.multi_id_276_temperature_sensor_alarm',"
                                    "'sensor.lithium_core_alarm',"
                                    "'sensor.windy_alarm'"
                                    "] %}"
                                    "{% set safe = ['no_alarm','unknown','unavailable','none','no_error'] %}"
                                    "{% for a in alarms %}{% if states(a) not in safe %}"
                                    "- 🚨 **{{ state_attr(a,'friendly_name') }}**: {{ states(a) }}\n"
                                    "{% endif %}{% endfor %}"
                                    "{% set probs = ["
                                    "'binary_sensor.xdzn_001_070f_problem',"
                                    "'binary_sensor.xdzn_001_7986_problem',"
                                    "'binary_sensor.xdzn_001_9bfe_problem',"
                                    "'binary_sensor.xdzn_001_75ed_problem',"
                                    "'binary_sensor.xdzn_001_160b_problem',"
                                    "'binary_sensor.xdzn_001_791e_problem',"
                                    "'binary_sensor.wtaeaaa25342478_problem',"
                                    "'binary_sensor.c0_d6_3c_58_86_c0_problem',"
                                    "'binary_sensor.wtaeaaa25344520_problem',"
                                    "'binary_sensor.xdzn_001_fbd5_problem'"
                                    "] %}"
                                    "{% for p in probs %}{% if is_state(p, 'on') %}"
                                    "- ⚠️ **{{ state_attr(p,'friendly_name') }}** reporting problem\n"
                                    "{% endif %}{% endfor %}"
                                ),
                            },
                        ],
                    },

                    # ---------------- Activity timeline ----------------
                    grid_section([
                        heading("Activity (48h)", "subtitle"),
                        {
                            "type": "logbook",
                            "entities": [
                                "input_select.defiant_mode",
                                "input_text.defiant_location_name",
                                "sensor.gx_device_ac_active_input_source",
                                "sensor.multi_id_276_state",
                                "sensor.gx_device_system_state",
                                "device_tracker.defiant_signal_k_defiant",
                                "device_tracker.ethans_iphone",
                                "automation.defiant_shore_power_docked",
                                "automation.defiant_shore_power_lost_notice",
                                "automation.defiant_sog_stopped_while_underway_notice",
                                "automation.defiant_sog_sustained_underway",
                                "sensor.openplotter_status",
                                "sensor.boatflix_status",
                            ],
                            "hours_to_show": 48,
                        },
                    ], column_span=2),

                    # ---------------- Last seen ----------------
                    grid_section([
                        heading("Last seen", "subtitle"),
                        md(last_seen_md),
                        md(
                            "**Backups** &nbsp;·&nbsp; "
                            "{% set last = as_timestamp(states('sensor.backup_last_successful_automatic_backup')) %}"
                            "{% set age_h = ((now().timestamp() - last) / 3600) | round(1) %}"
                            "{% if age_h < 36 %}🟢{% else %}🟥{% endif %} "
                            "last successful {{ age_h }}h ago"
                        ),
                    ]),

                    # ---------------- Forecast (decision input) ----------------
                    grid_section([
                        heading("Weather at Windmill Point", "subtitle"),
                        {
                            "type": "weather-forecast",
                            "entity": "weather.forecast_home",
                            "forecast_type": "daily",
                            "show_forecast": True,
                            "show_current": True,
                        },
                        md(
                            "🌅 {{ as_timestamp(states('sensor.sun_next_rising')) | timestamp_custom('%H:%M', true) }} "
                            "&nbsp;·&nbsp; "
                            "🌇 {{ as_timestamp(states('sensor.sun_next_setting')) | timestamp_custom('%H:%M', true) }}"
                        ),
                    ]),

                    # ---------------- Quick state (single glance row) ----------------
                    grid_section([
                        heading("Now", "subtitle"),
                        {
                            "type": "glance",
                            "show_name": True,
                            "show_state": True,
                            "columns": 6,
                            "entities": [
                                {"entity": "input_select.defiant_mode", "name": "Mode"},
                                {"entity": "sensor.gx_device_ac_active_input_source", "name": "AC"},
                                {"entity": "sensor.lithium_core_battery", "name": "SOC"},
                                {"entity": "sensor.solar_power_now", "name": "Solar"},
                                {"entity": "sensor.defiant_fuel_level", "name": "Diesel"},
                                {"entity": "sensor.propane_tank_percentage", "name": "Propane"},
                            ],
                        },
                    ], column_span=3),
                ],
            },
        ],
    }


def cfg_helm():
    """Wall/iPad kiosk view. Always-on, large fonts, dark, glanceable.
    Star-Trek bridge vibe — full LCARS."""
    return {
        "views": [
            {
                "title": "Helm",
                "icon": "mdi:steering",
                "type": "sections",
                "max_columns": 2,
                "sections": [
                    grid_section([
                        heading("S/V Defiant — Helm"),
                        lcars_label("input_select.defiant_mode"),
                        lcars_label("input_text.defiant_location_name"),
                    ]),
                    grid_section([
                        heading("Position", "title"),
                        lcars_multimeter(
                            "sensor.defiant_signal_k_defiant_speed_over_ground",
                            "SOG (kn)", vmin=0, vmax=10, mode="gauge",
                            columns="full", rows=4,
                        ),
                        lcars_multimeter(
                            "sensor.defiant_signal_k_defiant_course_over_ground",
                            "COG", vmin=0, vmax=360, mode="gauge",
                            columns="full", rows=4,
                        ),
                        md(
                            "**Lat** {{ states('input_number.defiant_latitude') | float(0) | round(5) }} "
                            "&nbsp;·&nbsp; "
                            "**Lon** {{ states('input_number.defiant_longitude') | float(0) | round(5) }}"
                        ),
                    ]),
                    grid_section([
                        heading("Power", "title"),
                        lcars_multimeter(
                            "sensor.lithium_core_battery", "Battery %",
                            vmin=0, vmax=100, columns="full", rows=4,
                        ),
                        lcars_button("sensor.gx_device_ac_active_input_source", "AC Source"),
                        lcars_button("sensor.multi_id_276_state", "Inverter"),
                        lcars_multimeter(
                            "sensor.solar_power_now", "Solar (W)",
                            vmin=0, vmax=2000, columns="full", rows=4,
                        ),
                    ]),
                    grid_section([
                        heading("Time & Sky", "title"),
                        md("# {{ now().strftime('%H:%M') }}\n### {{ now().strftime('%a %d %b') }}"),
                        {
                            "type": "weather-forecast",
                            "entity": "weather.forecast_home",
                            "forecast_type": "hourly",
                            "show_forecast": True,
                            "show_current": True,
                        },
                        md(
                            "🌅 {{ as_timestamp(states('sensor.sun_next_rising')) | timestamp_custom('%H:%M', true) }} "
                            "&nbsp;·&nbsp; "
                            "🌇 {{ as_timestamp(states('sensor.sun_next_setting')) | timestamp_custom('%H:%M', true) }}"
                        ),
                    ]),
                ],
            },
        ],
    }


def cfg_navigation():
    """Underway view. Map + nav data + weather + ETA."""
    return {
        "views": [
            {
                "title": "Navigation",
                "icon": "mdi:compass-outline",
                "type": "sections",
                "max_columns": 2,
                "sections": [
                    grid_section([
                        heading("Position"),
                        {
                            "type": "map",
                            "entities": [
                                "device_tracker.defiant_signal_k_defiant",
                                "device_tracker.ethans_iphone",
                            ],
                            "default_zoom": 11,
                            "hours_to_show": 48,
                            "grid_options": {"columns": "full", "rows": 8},
                        },
                        md(
                            "**Lat** {{ states('input_number.defiant_latitude') | float(0) | round(5) }} "
                            "&nbsp;·&nbsp; "
                            "**Lon** {{ states('input_number.defiant_longitude') | float(0) | round(5) }}"
                        ),
                    ]),
                    grid_section([
                        heading("Track"),
                        gauge("sensor.defiant_signal_k_defiant_speed_over_ground",
                              "SOG (kn)", vmin=0, vmax=10,
                              severity={"green": 4, "yellow": 1, "red": 0}),
                        gauge("sensor.defiant_signal_k_defiant_course_over_ground",
                              "COG (°)", vmin=0, vmax=360),
                    ]),
                    grid_section([
                        heading("Destination"),
                        md(
                            "**To:** {{ states('input_text.defiant_destination') or '—' }}\n\n"
                            "**Coords:** "
                            "{{ states('input_number.defiant_destination_latitude') | float(0) | round(4) }}, "
                            "{{ states('input_number.defiant_destination_longitude') | float(0) | round(4) }}\n\n"
                            "**ETA:** {{ states('input_datetime.defiant_eta') }}\n\n"
                            "{% set lat1 = states('input_number.defiant_latitude') | float(0) %}"
                            "{% set lon1 = states('input_number.defiant_longitude') | float(0) %}"
                            "{% set lat2 = states('input_number.defiant_destination_latitude') | float(0) %}"
                            "{% set lon2 = states('input_number.defiant_destination_longitude') | float(0) %}"
                            "{% set R = 3440.065 %}"
                            "{% set toRad = 0.017453292519943295 %}"
                            "{% set dLat = (lat2 - lat1) * toRad %}"
                            "{% set dLon = (lon2 - lon1) * toRad %}"
                            "{% set a = (sin(dLat/2))**2 + cos(lat1*toRad)*cos(lat2*toRad)*(sin(dLon/2))**2 %}"
                            "{% set c = 2 * atan2(sqrt(a), sqrt(1-a)) %}"
                            "**Distance:** {{ (R * c) | round(1) }} nm"
                        ),
                    ]),
                    grid_section([
                        heading("Weather"),
                        {
                            "type": "weather-forecast",
                            "entity": "weather.forecast_home",
                            "forecast_type": "hourly",
                            "show_forecast": True,
                            "show_current": True,
                        },
                    ]),
                    grid_section([
                        heading("Sun"),
                        md(
                            "| Event | Time |\n"
                            "|---|---|\n"
                            "| 🌅 Dawn | {{ as_timestamp(states('sensor.sun_next_dawn')) | timestamp_custom('%a %H:%M', true) }} |\n"
                            "| ☀️ Rise | {{ as_timestamp(states('sensor.sun_next_rising')) | timestamp_custom('%a %H:%M', true) }} |\n"
                            "| 🕛 Noon | {{ as_timestamp(states('sensor.sun_next_noon')) | timestamp_custom('%a %H:%M', true) }} |\n"
                            "| 🌇 Set | {{ as_timestamp(states('sensor.sun_next_setting')) | timestamp_custom('%a %H:%M', true) }} |\n"
                            "| 🌆 Dusk | {{ as_timestamp(states('sensor.sun_next_dusk')) | timestamp_custom('%a %H:%M', true) }} |\n"
                            "| 🌑 Midnight | {{ as_timestamp(states('sensor.sun_next_midnight')) | timestamp_custom('%a %H:%M', true) }} |\n"
                        ),
                    ]),
                ],
            },
        ],
    }


def cfg_systems():
    """Diagnostic / health view. Pi metrics, network, automations, backups."""
    return {
        "views": [
            {
                "title": "Systems",
                "icon": "mdi:server-network",
                "type": "sections",
                "max_columns": 3,
                "sections": [
                    grid_section([
                        heading("homeassistant (host Pi)"),
                        gauge("sensor.system_monitor_processor_use", "CPU", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 60, "red": 85}),
                        gauge("sensor.system_monitor_memory_usage", "Memory", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 70, "red": 90}),
                        gauge("sensor.system_monitor_disk_usage_config", "Disk (/config)", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 75, "red": 90}),
                        md(
                            "**CPU temp** {{ states('sensor.system_monitor_processor_temperature') }} "
                            "{{ state_attr('sensor.system_monitor_processor_temperature', 'unit_of_measurement') }}\n\n"
                            "**Up since** {{ states('sensor.system_monitor_last_boot') }}\n\n"
                            "**Net (end0)** ↑ {{ states('sensor.system_monitor_network_out_end0') }} MiB &nbsp;·&nbsp; "
                            "↓ {{ states('sensor.system_monitor_network_in_end0') }} MiB"
                        ),
                    ]),
                    grid_section([
                        heading("openplotter (nav Pi)"),
                        gauge("sensor.openplotter_cpu_load", "CPU", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 60, "red": 85}),
                        gauge("sensor.openplotter_memory_usage", "Memory", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 70, "red": 90}),
                        gauge("sensor.openplotter_disk_usage", "Disk", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 75, "red": 90}),
                        md(
                            "**Status** {{ states('sensor.openplotter_status') }}\n\n"
                            "**CPU temp** {{ states('sensor.openplotter_cpu_temperature') }} °F\n\n"
                            "**Up since** {{ states('sensor.openplotter_uptime') }}\n\n"
                            "**Net** ↑ {{ states('sensor.openplotter_data_sent') }} MB &nbsp;·&nbsp; "
                            "↓ {{ states('sensor.openplotter_data_received') }} MB"
                        ),
                    ]),
                    grid_section([
                        heading("boatflix (media Pi)"),
                        gauge("sensor.boatflix_cpu_load", "CPU", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 60, "red": 85}),
                        gauge("sensor.boatflix_memory_usage", "Memory", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 70, "red": 90}),
                        gauge("sensor.boatflix_disk_usage", "Disk", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 75, "red": 90}),
                        md(
                            "**Status** {{ states('sensor.boatflix_status') }}\n\n"
                            "**CPU temp** {{ states('sensor.boatflix_cpu_temperature') }} °F\n\n"
                            "**Up since** {{ states('sensor.boatflix_uptime') }}\n\n"
                            "**Net** ↑ {{ states('sensor.boatflix_data_sent') }} MB &nbsp;·&nbsp; "
                            "↓ {{ states('sensor.boatflix_data_received') }} MB"
                        ),
                    ]),
                    grid_section([
                        heading("ironclaw (agent Pi)"),
                        gauge("sensor.ironclaw_cpu_load", "CPU", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 60, "red": 85}),
                        gauge("sensor.ironclaw_memory_usage", "Memory", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 70, "red": 90}),
                        gauge("sensor.ironclaw_disk_usage", "Disk", vmin=0, vmax=100,
                              severity={"green": 0, "yellow": 75, "red": 90}),
                        md(
                            "**Status** {{ states('sensor.ironclaw_status') }}\n\n"
                            "**CPU temp** {{ states('sensor.ironclaw_cpu_temperature') }} °F\n\n"
                            "**Up since** {{ states('sensor.ironclaw_uptime') }}\n\n"
                            "**Net** ↑ {{ states('sensor.ironclaw_data_sent') }} MB &nbsp;·&nbsp; "
                            "↓ {{ states('sensor.ironclaw_data_received') }} MB"
                        ),
                    ]),
                    grid_section([
                        heading("Backups"),
                        lcars_button("sensor.backup_backup_manager_state", "State",
                                     show_icon=False),
                        md(
                            "**Last successful:** {{ as_timestamp(states('sensor.backup_last_successful_automatic_backup')) | timestamp_custom('%a %d %b %H:%M') }}\n\n"
                            "**Last attempted:** {{ as_timestamp(states('sensor.backup_last_attempted_automatic_backup')) | timestamp_custom('%a %d %b %H:%M') }}\n\n"
                            "**Next scheduled:** {{ as_timestamp(states('sensor.backup_next_scheduled_automatic_backup')) | timestamp_custom('%a %d %b %H:%M') }}"
                        ),
                    ]),
                    grid_section([
                        heading("Radio & sensors"),
                        md(
                            "**Z-Stick:** {{ states('sensor.z_stick_10_pro_status') }}\n\n"
                            "**Pi power:** {{ 'OK' if is_state('binary_sensor.rpi_power_status','off') else 'PROBLEM' }}\n\n"
                            "**Remote UI:** {{ states('binary_sensor.remote_ui') }}\n\n"
                            "**Phone batt:** {{ states('sensor.ethans_iphone_battery_level') }}% ({{ states('sensor.ethans_iphone_battery_state') }})"
                        ),
                    ]),
                    grid_section([
                        heading("Automations"),
                        {
                            "type": "entities",
                            "entities": [
                                {"entity": "automation.defiant_shore_power_docked",
                                 "secondary_info": "last-triggered"},
                                {"entity": "automation.defiant_shore_power_lost_notice",
                                 "secondary_info": "last-triggered"},
                                {"entity": "automation.defiant_sog_stopped_while_underway_notice",
                                 "secondary_info": "last-triggered"},
                                {"entity": "automation.defiant_sog_sustained_underway",
                                 "secondary_info": "last-triggered"},
                                {"entity": "automation.defiant_sync_signal_k_position_to_helpers",
                                 "secondary_info": "last-triggered"},
                            ],
                        },
                    ]),
                    grid_section([
                        heading("BLE signal strengths"),
                        {
                            "type": "entities",
                            "entities": [
                                "sensor.lithium_core_signal_strength",
                                "sensor.windy_signal_strength",
                                "sensor.port_bimini_signal_strength",
                                "sensor.starboard_bimini_signal_strength",
                                "sensor.port_davits_signal_strength",
                                "sensor.starboard_davits_signal_strength",
                                "sensor.defiant_analogs_defiant_analogs_wifi_signal",
                            ],
                        },
                    ]),
                ],
            },
        ],
    }


# Systemmonitor entities used by the "homeassistant (host Pi)" card on the
# Systems dashboard. The integration registers ~90 entities all disabled by
# default; we flip just the ones we surface so the rest stay quiet.
SYSTEMMONITOR_ENTITIES_TO_ENABLE = [
    "sensor.system_monitor_processor_use",
    "sensor.system_monitor_processor_temperature",
    "sensor.system_monitor_memory_usage",
    "sensor.system_monitor_disk_usage_config",
    "sensor.system_monitor_last_boot",
    "sensor.system_monitor_network_in_end0",
    "sensor.system_monitor_network_out_end0",
]


DASHBOARDS = [
    # (url_path, title, icon, config_fn). url_path=None targets the built-in
    # default Overview (the dashboard that opens when you visit /).
    (None, "Overview", "mdi:sail-boat", cfg_overview),
    ("ha-helm", "Helm", "mdi:steering", cfg_helm),
    ("ha-navigation", "Navigation", "mdi:compass-outline", cfg_navigation),
    ("ha-systems", "Systems", "mdi:server-network", cfg_systems),
]
# Old per-path Overview that should be removed if it's still around.
LEGACY_DASHBOARDS_TO_REMOVE = ["ha-overview"]


# --------------------------------------------------------------------------- #
# WS plumbing.                                                                #
# --------------------------------------------------------------------------- #

async def main():
    token = load_token()
    print("==> template helpers")
    create_template_helpers(token)
    print("==> dashboards")
    msg_id = 0
    async with websockets.connect(WS_URL, max_size=20 * 1024 * 1024) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()

        async def call(payload):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, **payload}))
            while True:
                resp = json.loads(await ws.recv())
                if resp.get("id") == msg_id:
                    return resp

        # Enable the systemmonitor entities we surface on Systems. They're
        # registered disabled by default; flipping disabled_by=None makes them
        # start producing state.
        registry = (await call({"type": "config/entity_registry/list"})).get("result", [])
        sm_by_eid = {
            e["entity_id"]: e for e in registry if e.get("platform") == "systemmonitor"
        }
        for eid in SYSTEMMONITOR_ENTITIES_TO_ENABLE:
            entry = sm_by_eid.get(eid)
            if not entry:
                print(f"  ! systemmonitor entity {eid} not in registry — skipping")
                continue
            if entry.get("disabled_by") is None:
                print(f"  = {eid} already enabled")
                continue
            r = await call({
                "type": "config/entity_registry/update",
                "entity_id": eid,
                "disabled_by": None,
            })
            if r.get("success"):
                print(f"  + enabled {eid}")
            else:
                print(f"  ! enable failed for {eid}: {r}")

        existing = (await call({"type": "lovelace/dashboards/list"})).get("result", [])
        existing_paths = {d["url_path"]: d for d in existing}

        for url_path, title, icon, cfg_fn in DASHBOARDS:
            label = url_path or "(default)"
            if url_path is None:
                # Built-in default — no create step; saving config converts it
                # from auto-generated to storage mode.
                print(f"  = default Overview")
            elif url_path not in existing_paths:
                resp = await call({
                    "type": "lovelace/dashboards/create",
                    "url_path": url_path,
                    "title": title,
                    "icon": icon,
                    "show_in_sidebar": True,
                    "require_admin": False,
                    "mode": "storage",
                })
                if not resp.get("success"):
                    print(f"  ! create dashboard {url_path}: {resp}")
                    continue
                print(f"  + dashboard '{title}' ({url_path}) created")
            else:
                print(f"  = dashboard '{title}' ({url_path}) already exists")

            cfg = cfg_fn()
            save_payload = {"type": "lovelace/config/save", "config": cfg}
            if url_path is not None:
                save_payload["url_path"] = url_path
            save = await call(save_payload)
            if save.get("success"):
                print(f"    config saved to {label} ({len(json.dumps(cfg))} bytes)")
            else:
                print(f"  ! save config for {label}: {save}")

        # Remove legacy dashboards that have been superseded.
        for url_path in LEGACY_DASHBOARDS_TO_REMOVE:
            d = existing_paths.get(url_path)
            if not d:
                continue
            r = await call({
                "type": "lovelace/dashboards/delete",
                "dashboard_id": d["id"],
            })
            if r.get("success"):
                print(f"  - removed legacy dashboard '{url_path}'")
            else:
                print(f"  ! failed to remove legacy '{url_path}': {r}")


if __name__ == "__main__":
    asyncio.run(main())
