#!/usr/bin/env -S uv run --with httpx --with websockets --quiet python
"""
Idempotently provision the S/V Defiant power-analytics stack in Home Assistant.

Now that all four MPPT controllers, the wind-gen smart shunt, and the new
1000 A house shunt report into HA, this builds the calc layer on top:

  1. Power-flow source of truth + BMS drift watch
     - The 1000 A shunt (`House Bank …id_289…`) is treated as truth.
     - The nine BANK I/II/III LiFePO4 packs are summed from their per-pack BMS
       power sensors as a sanity check (ELECTROPOOPER is a separate bank and is
       deliberately excluded — see create_power_analytics answers).
     - Drift (W and %) and a live "packs reporting" count surface when packs
       drop off BLE so a wide drift reads as "stale BMS", not "lost charge".

  2. Production-vs-consumption WITHOUT shore power
     - Production = solar (4 MPPT, via existing sensor.solar_power_now) + wind.
     - Consumption = DC system load + AC load (the honest off-grid load: what
       the inverter *would* have had to carry off-grid).
     - Riemann integral -> daily utility_meter -> a plain-language verdict:
       "would I have out-consumed my generation today?"

  3. Lightweight generation forecast + battery time-to-empty
     - met.no cloud_coverage scaled against an observed clear-day baseline
       (input_number you tune). No extra integration / API key.

  4. High-consumption activity tagging + learned signatures
     - Tag what you're doing (kettle, hot shower, …); an event detector
       captures peak W / duration / Wh and folds it into a per-activity
       running average so "what does coffee actually cost" becomes a number.

  5. Per-Pi consumption ESTIMATE
     - No per-Pi metering exists on the boat, so this is an explicit model:
       idle_w + slope * cpu_load%. Clearly labelled as an estimate.

Re-runnable. Template/integration/utility_meter helpers are matched by title,
input_* helpers by name/id, automations by id (REST upsert). Automations and
input_* changes apply on a plain re-run. Config-flow helpers (template /
integration / utility_meter) have no in-place edit, so after changing one of
those tables re-run with RECREATE set to the changed titles, e.g.:

    RECREATE='Shunt BMS Drift Pct,Wind Power' scripts/ha_setup/create_power_analytics.py
    RECREATE=ALL scripts/ha_setup/create_power_analytics.py   # rebuild all

Reads HOME_ASSISTANT_ACCESS_TOKEN from env or repo .env (same as the other
ha_setup scripts).
"""
import asyncio
import json
import os
import pathlib
import sys

import httpx
import websockets

HA_HOST = os.environ.get("HA_HOST", "homeassistant.local:8123")
REST_BASE = f"http://{HA_HOST}/api"
WS_URL = f"ws://{HA_HOST}/api/websocket"


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
# Entity wiring — the only place real entity_ids live.                         #
# --------------------------------------------------------------------------- #

SHUNT = "sensor.smartshunt_1000a_50mv_id_289"  # the 1000 A house shunt = truth
SHUNT_POWER = f"{SHUNT}_power"                  # signed W, <0 = discharge
SHUNT_SOC = f"{SHUNT}_charge"                   # %
SHUNT_CAPACITY = f"{SHUNT}_capacity"            # Ah
SHUNT_DC_CURRENT = f"{SHUNT}_dc_bus_current"    # signed A, <0 = discharge

# The nine house packs (BANK I/II/III A/B/C). ELECTROPOOPER (xdzn_001_fbd5)
# is intentionally NOT here — separate bank, own MPPT.
BMS_PACK_POWER = [
    "sensor.xdzn_001_070f_power",   # BANK I A
    "sensor.xdzn_001_7986_power",   # BANK I B
    "sensor.xdzn_001_9bfe_power",   # BANK I C
    "sensor.xdzn_001_75ed_power",   # BANK II A
    "sensor.xdzn_001_160b_power",   # BANK II B
    "sensor.xdzn_001_791e_power",   # BANK II C
    "sensor.wtaeaaa25342478_power", # BANK III A
    "sensor.c0_d6_3c_58_86_c0_power",  # BANK III B
    "sensor.wtaeaaa25344520_power", # BANK III C
]
BMS_PACKS_EXPECTED = len(BMS_PACK_POWER)

SOLAR_POWER_NOW = "sensor.solar_power_now"      # existing aggregate of 4 MPPT
SOLAR_YIELD_TODAY = "sensor.solar_yield_today"  # existing aggregate (Wh)
WIND_CURRENT = "sensor.windy_current"           # A (wind-gen smart shunt)
WIND_VOLTAGE = "sensor.windy_voltage"           # V

DC_LOAD = "sensor.gx_device_dc_consumption"             # W, DC system loads
AC_LOAD = "sensor.gx_device_consumption_power_l1"       # W, AC loads
WEATHER = "weather.forecast_home"                       # met.no, has cloud_coverage

# Per-Pi CPU-load sensors -> power estimate model (idle_w, slope W per %CPU).
PI_MODELS = [
    ("ironclaw",     "sensor.ironclaw_cpu_load",                 3.0, 0.045),
    ("boatflix",     "sensor.boatflix_cpu_load",                 3.5, 0.060),
    ("openplotter",  "sensor.openplotter_cpu_load",              2.5, 0.035),
    ("homeassistant","sensor.system_monitor_processor_use",      3.0, 0.045),
]

# Tagged activities for signature learning. Keep tight — every entry is a
# handful of helper entities.
ACTIVITIES = [
    ("kettle",          "Electric Kettle"),
    ("hot_shower",      "Instant Hot Shower"),
    ("microwave",       "Microwave"),
    ("induction",       "Induction Cooktop"),
    ("watermaker",      "Watermaker"),
    ("air_conditioning","Air Conditioning"),
]


# --------------------------------------------------------------------------- #
# 1+2+3+5: template sensors (simple state templates via the template flow).    #
# --------------------------------------------------------------------------- #

def _sum_available(entities):
    """Jinja that sums numeric states, skipping unknown/unavailable."""
    lst = "[" + ", ".join(f"'{e}'" for e in entities) + "]"
    return (
        "{% set ns = namespace(t=0.0) %}"
        f"{{% for e in {lst} %}}"
        "{% set v = states(e) %}"
        "{% if v not in ['unknown','unavailable','none', none] and is_number(v) %}"
        "{% set ns.t = ns.t + (v | float) %}"
        "{% endif %}{% endfor %}"
        "{{ ns.t | round(1) }}"
    )


def _count_available(entities):
    lst = "[" + ", ".join(f"'{e}'" for e in entities) + "]"
    return (
        "{% set ns = namespace(n=0) %}"
        f"{{% for e in {lst} %}}"
        "{% set v = states(e) %}"
        "{% if v not in ['unknown','unavailable','none', none] and is_number(v) %}"
        "{% set ns.n = ns.n + 1 %}"
        "{% endif %}{% endfor %}"
        "{{ ns.n }}"
    )


WIND_POWER_TPL = (
    "{% set i = states('" + WIND_CURRENT + "') | float(0) %}"
    "{% set v = states('" + WIND_VOLTAGE + "') | float(0) %}"
    "{{ [0, (i * v)] | max | round(1) }}"
)

RENEWABLE_PROD_TPL = (
    "{{ ((states('" + SOLAR_POWER_NOW + "') | float(0)) "
    "+ (states('sensor.wind_power') | float(0))) | round(1) }}"
)

HOUSE_LOAD_TPL = (
    "{{ ((states('" + DC_LOAD + "') | float(0)) "
    "+ (states('" + AC_LOAD + "') | float(0))) | round(1) }}"
)

NET_OFFGRID_TPL = (
    "{{ ((states('sensor.renewable_production_power') | float(0)) "
    "- (states('sensor.house_load_power') | float(0))) | round(1) }}"
)

DRIFT_TPL = (
    "{{ ((states('" + SHUNT_POWER + "') | float(0)) "
    "- (states('sensor.bms_pack_power_total') | float(0))) | round(1) }}"
)

DRIFT_PCT_TPL = (
    "{% set s = states('" + SHUNT_POWER + "') | float(0) %}"
    "{% set d = states('sensor.shunt_bms_power_drift') | float(0) %}"
    # below ~25 W net flow the packs sit at float reporting ~0; a % here is
    # noise, so report 0 and rely on the absolute-W drift sensor instead.
    "{% if s | abs < 25 %}0{% else %}{{ (d / (s | abs) * 100) | round(1) }}{% endif %}"
)

# Off-grid daily verdict (string state — no state_class).
# MPPT controllers throttle to float once the bank is full, so on a
# shore-powered full-battery day "production" is demand-limited, not
# weather-limited. When that's happening the deficit is overstated (off-grid
# the panels would have kept producing) — flag it so the verdict stays honest.
SOLAR_CURTAILED_TPL = (
    "{% set soc = states('" + SHUNT_SOC + "') | float(0) %}"
    "{% set sun = is_state('sun.sun', 'above_horizon') %}"
    "{% set cs = ['sensor.port_bimini_charge_state',"
    "'sensor.starboard_bimini_charge_state',"
    "'sensor.port_davits_charge_state',"
    "'sensor.starboard_davits_charge_state'] %}"
    "{% set ns = namespace(charging=false) %}"
    "{% for e in cs %}"
    "{% if states(e) in ['bulk','absorption','equalize'] %}"
    "{% set ns.charging = true %}{% endif %}{% endfor %}"
    "{{ sun and soc >= 99 and not ns.charging }}"
)

OFFGRID_VERDICT_TPL = (
    "{% set p = states('sensor.renewable_production_today') | float(none) %}"
    "{% set l = states('sensor.house_load_today') | float(none) %}"
    "{% if p is none or l is none %}unknown"
    "{% else %}{% set d = p - l %}"
    "{% if d >= 0 %}Surplus {{ d | round(2) }} kWh"
    "{% else %}Deficit {{ (-d) | round(2) }} kWh{% endif %}"
    "{% if is_state('binary_sensor.solar_curtailed', 'on') %}"
    " — battery-limited (bank full on shore); true off-grid harvest higher"
    "{% endif %}{% endif %}"
)
OFFGRID_BALANCE_TPL = (
    "{% set p = states('sensor.renewable_production_today') | float(none) %}"
    "{% set l = states('sensor.house_load_today') | float(none) %}"
    "{% if p is none or l is none %}unknown"
    "{% else %}{{ (p - l) | round(3) }}{% endif %}"
)

# Generation forecast: clear-day baseline scaled by met.no cloud_coverage.
GEN_FORECAST_TPL = (
    "{% set base = states('input_number.defiant_clear_day_yield_wh') | float(6000) %}"
    "{% set cc = state_attr('" + WEATHER + "', 'cloud_coverage') | float(40) %}"
    "{{ (base * (1 - 0.75 * cc / 100)) | round(0) }}"
)
GEN_FORECAST_REMAINING_TPL = (
    "{% set f = states('sensor.generation_forecast_today') | float(0) %}"
    "{% set sofar = states('" + SOLAR_YIELD_TODAY + "') | float(0) %}"
    "{{ [0, (f - sofar)] | max | round(0) }}"
)

# Battery time-to-empty (h). Only meaningful while discharging.
TTE_TPL = (
    "{% set soc = states('" + SHUNT_SOC + "') | float(none) %}"
    "{% set cap = states('" + SHUNT_CAPACITY + "') | float(none) %}"
    "{% set a = states('" + SHUNT_DC_CURRENT + "') | float(0) %}"
    "{% if soc is none or cap is none or a >= -0.5 %}unknown"
    "{% else %}{{ ((soc / 100 * cap) / (a | abs)) | round(1) }}{% endif %}"
)

PI_TOTAL_TPL = (
    "{{ (" + " + ".join(
        f"(states('sensor.pi_power_estimate_{h}') | float(0))"
        for h, *_ in PI_MODELS
    ) + ") | round(1) }}"
)

# Each entry: title, template_type, config dict (minus name).
TEMPLATE_SENSORS = [
    # --- 1. truth + drift -------------------------------------------------- #
    ("Battery Net Power", "sensor", {
        "state": "{{ states('" + SHUNT_POWER + "') | float(0) | round(1) }}",
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
    ("BMS Pack Power Total", "sensor", {
        "state": _sum_available(BMS_PACK_POWER),
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
    ("BMS Packs Reporting", "sensor", {
        "state": _count_available(BMS_PACK_POWER),
        "unit_of_measurement": "packs", "state_class": "measurement"}),
    ("Shunt BMS Power Drift", "sensor", {
        "state": DRIFT_TPL,
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
    ("Shunt BMS Drift Pct", "sensor", {
        "state": DRIFT_PCT_TPL,
        "unit_of_measurement": "%", "state_class": "measurement"}),
    ("BMS Reporting Degraded", "binary_sensor", {
        "state": "{{ (states('sensor.bms_packs_reporting') | int(0)) < "
                 f"{BMS_PACKS_EXPECTED} }}}}",
        "device_class": "problem"}),
    # --- 2. production vs consumption -------------------------------------- #
    ("Wind Power", "sensor", {
        "state": WIND_POWER_TPL,
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
    ("Renewable Production Power", "sensor", {
        "state": RENEWABLE_PROD_TPL,
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
    ("House Load Power", "sensor", {
        "state": HOUSE_LOAD_TPL,
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
    ("Net Offgrid Power", "sensor", {
        "state": NET_OFFGRID_TPL,
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
    # Production today is read from the MPPT controllers' own full-day,
    # midnight-resetting yield counters (sensor.solar_yield_today) PLUS the
    # wind daily meter — NOT a fresh integral, so it is correct even on the
    # day this is provisioned. Wind has no native daily counter, so that one
    # part is a utility_meter and only accrues from first run (wind output is
    # ~0 at the dock anyway).
    ("Renewable Production Today", "sensor", {
        "state": (
            "{{ (((states('" + SOLAR_YIELD_TODAY + "') | float(0)) / 1000) "
            "+ (states('sensor.wind_today') | float(0))) | round(3) }}"),
        "unit_of_measurement": "kWh", "device_class": "energy",
        "state_class": "total_increasing"}),
    ("Solar Curtailed", "binary_sensor", {
        "state": SOLAR_CURTAILED_TPL}),
    ("Offgrid Balance Today", "sensor", {
        "state": OFFGRID_BALANCE_TPL,
        "unit_of_measurement": "kWh", "device_class": "energy"}),
    ("Offgrid Verdict Today", "sensor", {"state": OFFGRID_VERDICT_TPL}),
    # --- 3. forecast + runway --------------------------------------------- #
    ("Generation Forecast Today", "sensor", {
        "state": GEN_FORECAST_TPL,
        "unit_of_measurement": "Wh", "device_class": "energy"}),
    ("Generation Forecast Remaining", "sensor", {
        "state": GEN_FORECAST_REMAINING_TPL,
        "unit_of_measurement": "Wh", "device_class": "energy"}),
    ("Battery Time To Empty", "sensor", {
        "state": TTE_TPL,
        "unit_of_measurement": "h", "device_class": "duration"}),
    # --- 5. per-Pi estimate ----------------------------------------------- #
    *[
        (f"Pi Power Estimate {host}", "sensor", {
            "state": (
                f"{{{{ ({idle} + {slope} * "
                f"(states('{cpu}') | float(0))) | round(1) }}}}"),
            "unit_of_measurement": "W", "device_class": "power",
            "state_class": "measurement"})
        for host, cpu, idle, slope in PI_MODELS
    ],
    ("Pi Power Estimate Total", "sensor", {
        "state": PI_TOTAL_TPL,
        "unit_of_measurement": "W", "device_class": "power",
        "state_class": "measurement"}),
]

# --------------------------------------------------------------------------- #
# 2: Riemann integral + daily utility_meter (config-flow helpers).             #
# --------------------------------------------------------------------------- #

# Solar energy is taken from the MPPT yield_today counters (see the
# "Renewable Production Today" template), so the only thing we integrate for
# production is wind (no native daily wind counter exists). House load has no
# native daily counter either, so it is integrated too.
INTEGRATION_HELPERS = [
    # title, source sensor (W) -> kWh
    ("Wind Energy", "sensor.wind_power"),
    ("House Load Energy", "sensor.house_load_power"),
]
UTILITY_METERS = [
    # title, source kWh sensor
    ("Wind Today", "sensor.wind_energy"),
    ("House Load Today", "sensor.house_load_energy"),
]


# --------------------------------------------------------------------------- #
# 4: input_* helpers (tagging, thresholds, per-activity accumulators).         #
# --------------------------------------------------------------------------- #

def build_input_helpers():
    helpers = [
        ("input_select", {
            "name": "Defiant Activity Tag", "icon": "mdi:tag",
            "options": ["none"] + [a for a, _ in ACTIVITIES],
            "initial": "none"},
         "input_select.defiant_activity_tag"),
        ("input_button", {
            "name": "Defiant Tag Activity Now", "icon": "mdi:tag-plus"},
         "input_button.defiant_tag_activity_now"),
        ("input_number", {
            "name": "Defiant High Load Threshold", "icon": "mdi:flash-alert",
            "min": 100, "max": 5000, "step": 50, "mode": "box",
            "unit_of_measurement": "W", "initial": 700},
         "input_number.defiant_high_load_threshold"),
        ("input_number", {
            "name": "Defiant Event Min Seconds", "icon": "mdi:timer-sand",
            "min": 5, "max": 600, "step": 5, "mode": "box",
            "unit_of_measurement": "s", "initial": 20},
         "input_number.defiant_event_min_seconds"),
        ("input_number", {
            "name": "Defiant Clear Day Yield Wh",
            "icon": "mdi:white-balance-sunny",
            "min": 500, "max": 30000, "step": 100, "mode": "box",
            "unit_of_measurement": "Wh", "initial": 6000},
         "input_number.defiant_clear_day_yield_wh"),
        # last detected event (any tag)
        ("input_number", {"name": "Defiant Event Peak W", "icon": "mdi:flash",
            "min": 0, "max": 20000, "step": 1, "mode": "box",
            "unit_of_measurement": "W", "initial": 0},
         "input_number.defiant_event_peak_w"),
        ("input_number", {"name": "Defiant Event Energy Wh",
            "icon": "mdi:lightning-bolt",
            "min": 0, "max": 100000, "step": 1, "mode": "box",
            "unit_of_measurement": "Wh", "initial": 0},
         "input_number.defiant_event_energy_wh"),
        ("input_number", {"name": "Defiant Event Duration S",
            "icon": "mdi:timer", "min": 0, "max": 86400, "step": 1,
            "mode": "box", "unit_of_measurement": "s", "initial": 0},
         "input_number.defiant_event_duration_s"),
        ("input_number", {"name": "Defiant Event Start Energy Wh",
            "icon": "mdi:lightning-bolt-outline",
            "min": 0, "max": 100000000, "step": 0.001, "mode": "box",
            "unit_of_measurement": "Wh", "initial": 0},
         "input_number.defiant_event_start_energy_wh"),
        ("input_boolean", {"name": "Defiant Event In Progress",
            "icon": "mdi:progress-clock"},
         "input_boolean.defiant_event_in_progress"),
        ("input_datetime", {"name": "Defiant Event Started",
            "icon": "mdi:clock-start", "has_date": True, "has_time": True},
         "input_datetime.defiant_event_started"),
        ("input_datetime", {"name": "Defiant Event Last Time",
            "icon": "mdi:clock-check", "has_date": True, "has_time": True},
         "input_datetime.defiant_event_last_time"),
        ("input_text", {"name": "Defiant Event Last Summary",
            "icon": "mdi:text-short", "max": 255},
         "input_text.defiant_event_last_summary"),
    ]
    # per-activity running-average accumulators
    for slug, label in ACTIVITIES:
        helpers += [
            ("input_number", {"name": f"Activity {label} Samples",
                "icon": "mdi:counter", "min": 0, "max": 1000000, "step": 1,
                "mode": "box", "initial": 0},
             f"input_number.activity_{slug}_samples"),
            ("input_number", {"name": f"Activity {label} Avg W",
                "icon": "mdi:flash", "min": 0, "max": 20000, "step": 1,
                "mode": "box", "unit_of_measurement": "W", "initial": 0},
             f"input_number.activity_{slug}_avg_w"),
            ("input_number", {"name": f"Activity {label} Avg Wh",
                "icon": "mdi:lightning-bolt", "min": 0, "max": 100000,
                "step": 1, "mode": "box", "unit_of_measurement": "Wh",
                "initial": 0},
             f"input_number.activity_{slug}_avg_wh"),
            ("input_datetime", {"name": f"Activity {label} Last Seen",
                "icon": "mdi:clock-check", "has_date": True,
                "has_time": True},
             f"input_datetime.activity_{slug}_last_seen"),
        ]
    return helpers


# --------------------------------------------------------------------------- #
# 4: automations (REST upsert).                                                #
# --------------------------------------------------------------------------- #

def _avg_update_actions():
    """Per-activity running-average fold, chosen by the tag value."""
    actions = []
    for slug, _ in ACTIVITIES:
        s = f"input_number.activity_{slug}_samples"
        w = f"input_number.activity_{slug}_avg_w"
        wh = f"input_number.activity_{slug}_avg_wh"
        seen = f"input_datetime.activity_{slug}_last_seen"
        actions.append({
            "if": [{"condition": "state",
                    "entity_id": "input_select.defiant_activity_tag",
                    "state": slug}],
            "then": [
                {"service": "input_number.set_value",
                 "target": {"entity_id": w},
                 "data": {"value": (
                     "{% set n = states('" + s + "') | float(0) %}"
                     "{% set o = states('" + w + "') | float(0) %}"
                     "{% set x = states('input_number.defiant_event_peak_w') "
                     "| float(0) %}"
                     "{{ ((o * n + x) / (n + 1)) | round(1) }}")}},
                {"service": "input_number.set_value",
                 "target": {"entity_id": wh},
                 "data": {"value": (
                     "{% set n = states('" + s + "') | float(0) %}"
                     "{% set o = states('" + wh + "') | float(0) %}"
                     "{% set x = "
                     "states('input_number.defiant_event_energy_wh') "
                     "| float(0) %}"
                     "{{ ((o * n + x) / (n + 1)) | round(1) }}")}},
                {"service": "input_number.set_value",
                 "target": {"entity_id": s},
                 "data": {"value":
                          "{{ (states('" + s + "') | float(0)) + 1 }}"}},
                {"service": "input_datetime.set_datetime",
                 "target": {"entity_id": seen},
                 "data": {"datetime": "{{ now().isoformat() }}"}},
            ],
        })
    return actions


def build_automations():
    LOAD = "sensor.house_load_power"
    return [
        # ---- event start: load above threshold for >= min seconds -------- #
        ("defiant_high_load_start", {
            "alias": "Defiant: high-load event start",
            "mode": "single",
            "triggers": [{
                "trigger": "numeric_state", "entity_id": LOAD,
                "above": "input_number.defiant_high_load_threshold",
                "for": {"seconds": 20}}],
            "conditions": [{
                "condition": "state",
                "entity_id": "input_boolean.defiant_event_in_progress",
                "state": "off"}],
            "actions": [
                {"service": "input_boolean.turn_on",
                 "target": {"entity_id":
                            "input_boolean.defiant_event_in_progress"}},
                {"service": "input_datetime.set_datetime",
                 "target": {"entity_id":
                            "input_datetime.defiant_event_started"},
                 "data": {"datetime": "{{ now().isoformat() }}"}},
                {"service": "input_number.set_value",
                 "target": {"entity_id":
                            "input_number.defiant_event_peak_w"},
                 "data": {"value":
                          "{{ states('" + LOAD + "') | float(0) }}"}},
                {"service": "input_number.set_value",
                 "target": {"entity_id":
                            "input_number.defiant_event_start_energy_wh"},
                 "data": {"value": (
                     "{{ (states('sensor.house_load_energy') | float(0)) "
                     "* 1000 }}")}},
            ]}),
        # ---- track running peak while an event is in progress ------------ #
        ("defiant_high_load_peak", {
            "alias": "Defiant: high-load track peak",
            "mode": "single",
            "triggers": [{"trigger": "state", "entity_id": LOAD}],
            "conditions": [
                {"condition": "state",
                 "entity_id": "input_boolean.defiant_event_in_progress",
                 "state": "on"},
                {"condition": "numeric_state", "entity_id": LOAD,
                 "above": "input_number.defiant_event_peak_w"}],
            "actions": [{
                "service": "input_number.set_value",
                "target": {"entity_id":
                           "input_number.defiant_event_peak_w"},
                "data": {"value":
                         "{{ states('" + LOAD + "') | float(0) }}"}}]}),
        # ---- event end: load back below threshold ------------------------ #
        ("defiant_high_load_end", {
            "alias": "Defiant: high-load event end",
            "mode": "single",
            "triggers": [{
                "trigger": "numeric_state", "entity_id": LOAD,
                "below": "input_number.defiant_high_load_threshold",
                "for": {"seconds": 15}}],
            "conditions": [{
                "condition": "state",
                "entity_id": "input_boolean.defiant_event_in_progress",
                "state": "on"}],
            "actions": [
                {"variables": {
                    "dur": ("{{ (as_timestamp(now()) - "
                            "as_timestamp(states("
                            "'input_datetime.defiant_event_started'))) "
                            "| int(0) }}"),
                    "wh": ("{{ [0, ((states('sensor.house_load_energy') "
                           "| float(0)) * 1000) - (states("
                           "'input_number.defiant_event_start_energy_wh') "
                           "| float(0))] | max | round(1) }}"),
                    "tag": "{{ states('input_select.defiant_activity_tag') }}",
                    "peak": ("{{ states('input_number.defiant_event_peak_w') "
                             "| float(0) }}")}},
                {"service": "input_number.set_value",
                 "target": {"entity_id":
                            "input_number.defiant_event_duration_s"},
                 "data": {"value": "{{ dur }}"}},
                {"service": "input_number.set_value",
                 "target": {"entity_id":
                            "input_number.defiant_event_energy_wh"},
                 "data": {"value": "{{ wh }}"}},
                {"service": "input_datetime.set_datetime",
                 "target": {"entity_id":
                            "input_datetime.defiant_event_last_time"},
                 "data": {"datetime": "{{ now().isoformat() }}"}},
                {"service": "input_text.set_value",
                 "target": {"entity_id":
                            "input_text.defiant_event_last_summary"},
                 "data": {"value": (
                     "{{ tag }} | {{ peak | round(0) }} W peak | "
                     "{{ (dur / 60) | round(1) }} min | "
                     "{{ wh | round(0) }} Wh")}},
                {"service": "logbook.log",
                 "data": {
                     "name": "Defiant high-load event",
                     "message": ("{{ tag }} — {{ peak | round(0) }} W peak, "
                                 "{{ (dur/60) | round(1) }} min, "
                                 "{{ wh | round(0) }} Wh"),
                     "entity_id": "sensor.house_load_power"}},
                {"event": "defiant_high_load_event",
                 "event_data": {
                     "tag": "{{ tag }}", "peak_w": "{{ peak }}",
                     "duration_s": "{{ dur }}", "energy_wh": "{{ wh }}"}},
                # fold into the tagged activity's running average
                # (each item is a standalone if/then action)
                *_avg_update_actions(),
                # reset for the next event
                {"service": "input_boolean.turn_off",
                 "target": {"entity_id":
                            "input_boolean.defiant_event_in_progress"}},
                {"service": "input_select.select_option",
                 "target": {"entity_id":
                            "input_select.defiant_activity_tag"},
                 "data": {"option": "none"}},
            ]}),
        # ---- "Tag now" button: snapshot current load as a manual marker -- #
        ("defiant_tag_activity_now", {
            "alias": "Defiant: tag activity now (manual marker)",
            "mode": "single",
            "triggers": [{
                "trigger": "state",
                "entity_id": "input_button.defiant_tag_activity_now"}],
            "actions": [{
                "service": "logbook.log",
                "data": {
                    "name": "Defiant activity marker",
                    "message": ("manual mark: "
                                "{{ states('input_select.defiant_activity_tag') }}"
                                " @ {{ states('sensor.house_load_power') }} W"),
                    "entity_id": "sensor.house_load_power"}}]}),
    ]


# --------------------------------------------------------------------------- #
# Drivers.                                                                     #
# --------------------------------------------------------------------------- #

# Config-flow helpers have no in-place "update": to change a template/
# integration/utility_meter you must delete its config entry and recreate it.
# Set RECREATE to a comma-separated list of titles (or "ALL") to do that on
# this run — this is the supported way to push edits made to the tables above.
RECREATE = {t.strip() for t in os.environ.get("RECREATE", "").split(",")
            if t.strip()}


def provision_flow_helpers(client, handler, items, build_payload):
    """Generic config-flow helper creator, idempotent by entry title.

    Re-creates entries whose title is in $RECREATE (or all if RECREATE=ALL).
    """
    entries = client.get(
        f"{REST_BASE}/config/config_entries/entry?domain={handler}").json()
    by_title = {e.get("title"): e for e in entries if isinstance(e, dict)}
    existing = set(by_title)
    for title, *rest in items:
        if title in existing and (
                title not in RECREATE and "ALL" not in RECREATE):
            print(f"  = {handler} {title!r} already exists")
            continue
        if title in existing:
            client.request(
                "DELETE",
                f"{REST_BASE}/config/config_entries/entry/"
                f"{by_title[title]['entry_id']}")
            print(f"  ~ {handler} {title!r} deleted for recreate")
        init = client.post(
            f"{REST_BASE}/config/config_entries/flow",
            json={"handler": handler, "show_advanced_options": False}).json()
        flow_id = init.get("flow_id")
        if not flow_id:
            print(f"  ! {handler} flow init failed for {title!r}: {init}")
            continue
        if init.get("type") == "menu":
            step = build_payload(title, *rest)["__menu_step__"]
            init = client.post(
                f"{REST_BASE}/config/config_entries/flow/{flow_id}",
                json={"next_step_id": step}).json()
        payload = {k: v for k, v in build_payload(title, *rest).items()
                   if k != "__menu_step__"}
        res = client.post(
            f"{REST_BASE}/config/config_entries/flow/{flow_id}",
            json=payload).json()
        if res.get("type") == "create_entry":
            print(f"  + created {handler} {title!r}")
        else:
            print(f"  ! create failed for {title!r}: {res}")


def tpl_payload(title, ttype, cfg):
    return {"__menu_step__": ttype, "name": title, **cfg}


def integ_payload(title, source):
    return {"name": title, "source": source, "method": "trapezoidal",
            "unit_prefix": "k", "unit_time": "h", "round": 3,
            "max_sub_interval": {"minutes": 2}}


def um_payload(title, source):
    return {"name": title, "source": source, "cycle": "daily",
            "offset": 0, "tariffs": [], "net_consumption": False,
            "delta_values": False, "periodically_resetting": True}


async def provision_input_helpers(token):
    helpers = build_input_helpers()
    msg_id = 0
    async with websockets.connect(WS_URL, max_size=20 * 1024 * 1024) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "auth_required", hello
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"

        async def call(payload):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, **payload}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == msg_id:
                    return r

        for domain, create, expected in helpers:
            lst = await call({"type": f"{domain}/list"})
            if not lst.get("success"):
                print(f"  ! {domain}/list failed: {lst}")
                continue
            want_id = expected.split(".", 1)[1]
            match = next((e for e in lst["result"]
                          if e.get("name") == create["name"]
                          or e.get("id") == want_id), None)
            if match:
                print(f"  = {expected} already exists")
                continue
            res = await call({"type": f"{domain}/create", **create})
            print(f"  + created {domain} {create['name']!r}"
                  if res.get("success")
                  else f"  ! create failed {expected}: {res}")


def provision_automations(client):
    for auto_id, body in build_automations():
        body = {"id": auto_id, **body}
        r = client.post(
            f"{REST_BASE}/config/automation/config/{auto_id}", json=body)
        ok = r.status_code == 200 and r.json().get("result") == "ok"
        print(f"  {'+' if ok else '!'} automation {auto_id}"
              f"{'' if ok else ' FAILED: ' + r.text[:200]}")


def main():
    token = load_token()
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=20.0) as client:
        print("input_* helpers (tagging, thresholds, accumulators):")
        asyncio.run(provision_input_helpers(token))

        print("\ntemplate sensors (truth/drift/prod/load/forecast/pi):")
        provision_flow_helpers(client, "template", TEMPLATE_SENSORS,
                                tpl_payload)

        print("\nRiemann integral helpers (W -> kWh):")
        provision_flow_helpers(client, "integration", INTEGRATION_HELPERS,
                               integ_payload)

        print("\ndaily utility meters:")
        provision_flow_helpers(client, "utility_meter", UTILITY_METERS,
                               um_payload)

        print("\nautomations (event detect + signature learning):")
        provision_automations(client)

    print("\nDone. Re-run any time after editing this file.")


if __name__ == "__main__":
    main()
