"""Constants used by the Netatmo Bubendorff component."""
from homeassistant.const import Platform

API = "api"

DOMAIN = "netatmo_bubendorff"
MANUFACTURER = "Netatmo"
DEFAULT_ATTRIBUTION = f"Data provided by {MANUFACTURER}"

# Bubendorff shutter target_position special values (Netatmo API).
# The hardware only honours open/closed/stop/preferred — intermediate 0-100
# values are rejected. We emulate intermediate positions by sending an
# open or close and then a stop after a time proportional to the requested
# position (see cover.async_set_cover_position).
SHUTTER_POSITION_CLOSED = 0
SHUTTER_POSITION_OPEN = 100
SHUTTER_POSITION_STOP = -1
SHUTTER_POSITION_PREFERRED = -2  # Jalousie/slats mode for Bubendorff

# Options-flow keys (stored per config entry in entry.options).
CONF_TRAVEL_TIMES = "travel_times"           # dict: entity_id -> seconds
CONF_DEFAULT_TRAVEL_TIME = "default_travel_time"

# IMPORTANT: travel_time here is the PHYSICAL motor run time, NOT the
# Netatmo API response time. Those are very different:
#
#   • Netatmo API round-trip for a shutter command ≈ 10–12 s regardless
#     of shutter size (measured empirically across 219 cm and 165 cm
#     shutters — no correlation with size, so it's a fixed API timeout).
#   • Physical motor time to travel from fully closed to fully open ranges
#     widely — commonly 25–60 s depending on motor model and shutter
#     height. That's what matters for set_cover_position timing.
#
# Default below is a middle-ground guess. Users MUST calibrate per cover
# by timing a full open or close with a stopwatch and entering seconds
# via Settings → Devices & Services → Configure → Shutter travel times.
DEFAULT_TRAVEL_TIME_SECONDS = 25.0
DEFAULT_TILT_EXTRA_SECONDS = 3.0

# Store (persistent position tracker) — one key per config entry.
POSITION_STORE_VERSION = 1
POSITION_STORE_KEY_PREFIX = "netatmo_bubendorff_positions"

# Confidence labels for position estimates.
POSITION_CONFIDENCE_KNOWN = "known"          # just arrived at 0 or 100
POSITION_CONFIDENCE_ESTIMATED = "estimated"  # computed from time + direction
POSITION_CONFIDENCE_UNKNOWN = "unknown"      # HA restart, physical button, first use

PLATFORMS = [
    Platform.CAMERA,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONF_URL_SECURITY = "https://home.netatmo.com/security"
CONF_URL_ENERGY = "https://my.netatmo.com/app/energy"
CONF_URL_WEATHER = "https://my.netatmo.com/app/weather"
CONF_URL_CONTROL = "https://home.netatmo.com/control"
CONF_URL_PUBLIC_WEATHER = "https://weathermap.netatmo.com/"

AUTH = "netatmo_auth"
CONF_PUBLIC = "public_sensor_config"
CAMERA_DATA = "netatmo_camera"
HOME_DATA = "netatmo_home_data"
DATA_HANDLER = "netatmo_data_handler"
SIGNAL_NAME = "signal_name"

NETATMO_CREATE_BATTERY = "netatmo_create_battery"
NETATMO_CREATE_CAMERA = "netatmo_create_camera"
NETATMO_CREATE_CAMERA_LIGHT = "netatmo_create_camera_light"
NETATMO_CREATE_CLIMATE = "netatmo_create_climate"
NETATMO_CREATE_COVER = "netatmo_create_cover"
NETATMO_CREATE_LIGHT = "netatmo_create_light"
NETATMO_CREATE_ROOM_SENSOR = "netatmo_create_room_sensor"
NETATMO_CREATE_SELECT = "netatmo_create_select"
NETATMO_CREATE_SENSOR = "netatmo_create_sensor"
NETATMO_CREATE_SWITCH = "netatmo_create_switch"
NETATMO_CREATE_WEATHER_SENSOR = "netatmo_create_weather_sensor"

CONF_AREA_NAME = "area_name"
CONF_CLOUDHOOK_URL = "cloudhook_url"
CONF_LAT_NE = "lat_ne"
CONF_LAT_SW = "lat_sw"
CONF_LON_NE = "lon_ne"
CONF_LON_SW = "lon_sw"
CONF_NEW_AREA = "new_area"
CONF_PUBLIC_MODE = "mode"
CONF_WEATHER_AREAS = "weather_areas"

OAUTH2_AUTHORIZE = "https://api.netatmo.com/oauth2/authorize"
OAUTH2_TOKEN = "https://api.netatmo.com/oauth2/token"

DATA_CAMERAS = "cameras"
DATA_DEVICE_IDS = "netatmo_device_ids"
DATA_EVENTS = "netatmo_events"
DATA_HOMES = "netatmo_homes"
DATA_PERSONS = "netatmo_persons"
DATA_SCHEDULES = "netatmo_schedules"

NETATMO_EVENT = "netatmo_event"

DEFAULT_DISCOVERY = True
DEFAULT_PERSON = "unknown"
DEFAULT_WEBHOOKS = False

ATTR_CAMERA_LIGHT_MODE = "camera_light_mode"
ATTR_EVENT_TYPE = "event_type"
ATTR_FACE_URL = "face_url"
ATTR_HEATING_POWER_REQUEST = "heating_power_request"
ATTR_HOME_ID = "home_id"
ATTR_HOME_NAME = "home_name"
ATTR_IS_KNOWN = "is_known"
ATTR_PERSON = "person"
ATTR_PERSONS = "persons"
ATTR_PSEUDO = "pseudo"
ATTR_SCHEDULE_ID = "schedule_id"
ATTR_SCHEDULE_NAME = "schedule_name"
ATTR_SELECTED_SCHEDULE = "selected_schedule"

SERVICE_SET_CAMERA_LIGHT = "set_camera_light"
SERVICE_SET_PERSON_AWAY = "set_person_away"
SERVICE_SET_PERSONS_HOME = "set_persons_home"
SERVICE_SET_SCHEDULE = "set_schedule"

# Climate events
EVENT_TYPE_CANCEL_SET_POINT = "cancel_set_point"
EVENT_TYPE_SCHEDULE = "schedule"
EVENT_TYPE_SET_POINT = "set_point"
EVENT_TYPE_THERM_MODE = "therm_mode"
# Camera events
EVENT_TYPE_CAMERA_ANIMAL = "animal"
EVENT_TYPE_CAMERA_HUMAN = "human"
EVENT_TYPE_CAMERA_MOVEMENT = "movement"
EVENT_TYPE_CAMERA_OUTDOOR = "outdoor"
EVENT_TYPE_CAMERA_PERSON = "person"
EVENT_TYPE_CAMERA_PERSON_AWAY = "person_away"
EVENT_TYPE_CAMERA_VEHICLE = "vehicle"
EVENT_TYPE_LIGHT_MODE = "light_mode"
# Door tags
EVENT_TYPE_ALARM_STARTED = "alarm_started"
EVENT_TYPE_DOOR_TAG_BIG_MOVE = "tag_big_move"
EVENT_TYPE_DOOR_TAG_OPEN = "tag_open"
EVENT_TYPE_DOOR_TAG_SMALL_MOVE = "tag_small_move"
EVENT_TYPE_OFF = "off"
EVENT_TYPE_ON = "on"

OUTDOOR_CAMERA_TRIGGERS = [
    EVENT_TYPE_CAMERA_ANIMAL,
    EVENT_TYPE_CAMERA_HUMAN,
    EVENT_TYPE_CAMERA_OUTDOOR,
    EVENT_TYPE_CAMERA_VEHICLE,
]
INDOOR_CAMERA_TRIGGERS = [
    EVENT_TYPE_ALARM_STARTED,
    EVENT_TYPE_CAMERA_MOVEMENT,
    EVENT_TYPE_CAMERA_PERSON_AWAY,
    EVENT_TYPE_CAMERA_PERSON,
]
DOOR_TAG_TRIGGERS = [
    EVENT_TYPE_DOOR_TAG_BIG_MOVE,
    EVENT_TYPE_DOOR_TAG_OPEN,
    EVENT_TYPE_DOOR_TAG_SMALL_MOVE,
]
CLIMATE_TRIGGERS = [
    EVENT_TYPE_CANCEL_SET_POINT,
    EVENT_TYPE_SET_POINT,
    EVENT_TYPE_THERM_MODE,
]
EVENT_ID_MAP = {
    EVENT_TYPE_ALARM_STARTED: "device_id",
    EVENT_TYPE_CAMERA_ANIMAL: "device_id",
    EVENT_TYPE_CAMERA_HUMAN: "device_id",
    EVENT_TYPE_CAMERA_MOVEMENT: "device_id",
    EVENT_TYPE_CAMERA_OUTDOOR: "device_id",
    EVENT_TYPE_CAMERA_PERSON_AWAY: "device_id",
    EVENT_TYPE_CAMERA_PERSON: "device_id",
    EVENT_TYPE_CAMERA_VEHICLE: "device_id",
    EVENT_TYPE_CANCEL_SET_POINT: "room_id",
    EVENT_TYPE_DOOR_TAG_BIG_MOVE: "device_id",
    EVENT_TYPE_DOOR_TAG_OPEN: "device_id",
    EVENT_TYPE_DOOR_TAG_SMALL_MOVE: "device_id",
    EVENT_TYPE_LIGHT_MODE: "device_id",
    EVENT_TYPE_SET_POINT: "room_id",
    EVENT_TYPE_THERM_MODE: "home_id",
}

MODE_LIGHT_AUTO = "auto"
MODE_LIGHT_OFF = "off"
MODE_LIGHT_ON = "on"
CAMERA_LIGHT_MODES = [MODE_LIGHT_ON, MODE_LIGHT_OFF, MODE_LIGHT_AUTO]

WEBHOOK_ACTIVATION = "webhook_activation"
WEBHOOK_DEACTIVATION = "webhook_deactivation"
WEBHOOK_LIGHT_MODE = "NOC-light_mode"
WEBHOOK_NACAMERA_CONNECTION = "NACamera-connection"
WEBHOOK_PUSH_TYPE = "push_type"
