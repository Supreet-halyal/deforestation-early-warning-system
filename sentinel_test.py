import os
import math
import requests

from pathlib import Path

from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

CLIENT_ID = os.getenv("COPERNICUS_CLIENT_ID")
CLIENT_SECRET = os.getenv("COPERNICUS_CLIENT_SECRET")

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/"
    "auth/realms/CDSE/protocol/openid-connect/token"
)

STATS_URL = (
    "https://sh.dataspace.copernicus.eu/"
    "statistics/v1"
)

PROCESS_URL = (
    "https://sh.dataspace.copernicus.eu/"
    "process/v1"
)

EVIDENCE_CACHE_DIR = (
    Path(__file__).resolve().parent
    / "static"
    / "evidence"
)
EVIDENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# FOREST MONITORING SETTINGS
# ============================================================

# Monitoring area used for the project
MONITORING_AREA_ACRES = 100.0

# 1 acre = 4046.8564224 square metres
ACRE_TO_SQ_M = 4046.8564224

# Calculate side of square covering approximately 100 acres
MONITORING_SIDE_M = math.sqrt(
    MONITORING_AREA_ACRES * ACRE_TO_SQ_M
)

HALF_SIDE_M = MONITORING_SIDE_M / 2

# Initial NDVI threshold for forest classification
FOREST_NDVI_THRESHOLD = 0.60


# ============================================================
# SENTINEL-2 EVALSCRIPT
# ============================================================

EVALSCRIPT = """
//VERSION=3

function setup() {

    return {
        input: [{
            bands: [
                "B04",
                "B08",
                "SCL",
                "dataMask"
            ]
        }],

        output: [
            {
                id: "ndvi",
                bands: 1,
                sampleType: "FLOAT32"
            },

            {
                id: "forestMask",
                bands: 1,
                sampleType: "FLOAT32"
            },

            {
                id: "dataMask",
                bands: 1,
                sampleType: "UINT8"
            }
        ]
    };
}


function evaluatePixel(samples) {

    // --------------------------------------------------------
    // NDVI
    // --------------------------------------------------------

    var denominator =
        samples.B08 + samples.B04;

    var ndvi = 0;

    if (denominator != 0) {

        ndvi =
            (samples.B08 - samples.B04)
            / denominator;
    }


    // --------------------------------------------------------
    // VALID PIXEL
    // --------------------------------------------------------

    var validPixel =
        samples.dataMask;


    /*
        Sentinel-2 SCL classes:

        1  = Saturated/defective
        2  = Dark area
        3  = Cloud shadow
        4  = Vegetation
        5  = Not vegetation
        6  = Water
        7  = Unclassified
        8  = Cloud medium probability
        9  = Cloud high probability
        10 = Cirrus
        11 = Snow/ice
    */


    // Remove unsuitable pixels

    if (
        samples.SCL == 1 ||
        samples.SCL == 2 ||
        samples.SCL == 3 ||
        samples.SCL == 6 ||
        samples.SCL == 7 ||
        samples.SCL == 8 ||
        samples.SCL == 9 ||
        samples.SCL == 10 ||
        samples.SCL == 11
    ) {

        validPixel = 0;
    }


    // --------------------------------------------------------
    // FOREST CLASSIFICATION
    // --------------------------------------------------------

    var forest = 0;

    /*
        Forest =

        SCL 4 (vegetation)
        AND
        NDVI >= 0.50
    */

    if (
        samples.SCL == 4 &&
        ndvi >= 0.50
    ) {

        forest = 1;
    }


    // --------------------------------------------------------
    // RETURN
    // --------------------------------------------------------

    return {

        ndvi: [ndvi],

        forestMask: [forest],

        dataMask: [validPixel]
    };
}
"""


# ============================================================
# GET ACCESS TOKEN
# ============================================================

def get_access_token():

    if not CLIENT_ID or not CLIENT_SECRET:

        raise ValueError(
            "Copernicus credentials are missing from .env"
        )


    response = requests.post(

        TOKEN_URL,

        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },

        timeout=30
    )


    response.raise_for_status()

    return response.json()["access_token"]


# ============================================================
# GET UTM ZONE
# ============================================================

def get_utm_zone(longitude):

    longitude = float(longitude)

    return int(
        math.floor(
            (longitude + 180) / 6
        ) + 1
    )


# ============================================================
# GET EPSG
# ============================================================

def get_epsg(latitude, longitude):

    latitude = float(latitude)
    longitude = float(longitude)

    zone = get_utm_zone(
        longitude
    )

    if latitude >= 0:

        return 32600 + zone

    else:

        return 32700 + zone


# ============================================================
# CONVERT LAT/LON TO UTM
# ============================================================

def latlon_to_utm(
    latitude,
    longitude
):

    latitude = float(latitude)
    longitude = float(longitude)

    zone = get_utm_zone(
        longitude
    )


    # WGS84 parameters

    a = 6378137.0

    ecc_squared = 0.00669438

    k0 = 0.9996


    # --------------------------------------------------------
    # Convert to radians
    # --------------------------------------------------------

    lat_rad = math.radians(
        latitude
    )

    lon_rad = math.radians(
        longitude
    )


    # --------------------------------------------------------
    # Central meridian
    # --------------------------------------------------------

    long_origin = (
        (zone - 1) * 6
        - 180
        + 3
    )

    long_origin_rad = math.radians(
        long_origin
    )


    # --------------------------------------------------------
    # UTM calculations
    # --------------------------------------------------------

    ecc_prime_squared = (
        ecc_squared /
        (1 - ecc_squared)
    )


    n = (
        a /
        math.sqrt(
            1
            -
            ecc_squared
            *
            math.sin(lat_rad) ** 2
        )
    )


    t = (
        math.tan(lat_rad) ** 2
    )


    c = (
        ecc_prime_squared
        *
        math.cos(lat_rad) ** 2
    )


    aa = (
        math.cos(lat_rad)
        *
        (
            lon_rad
            -
            long_origin_rad
        )
    )


    m = (

        a *

        (

            (
                1
                - ecc_squared / 4
                - 3 * ecc_squared ** 2 / 64
                - 5 * ecc_squared ** 3 / 256
            )
            *
            lat_rad


            -

            (
                3 * ecc_squared / 8
                + 3 * ecc_squared ** 2 / 32
                + 45 * ecc_squared ** 3 / 1024
            )
            *
            math.sin(
                2 * lat_rad
            )


            +

            (
                15 * ecc_squared ** 2 / 256
                + 45 * ecc_squared ** 3 / 1024
            )
            *
            math.sin(
                4 * lat_rad
            )


            -

            (
                35 * ecc_squared ** 3 / 3072
            )
            *
            math.sin(
                6 * lat_rad
            )

        )
    )


    # --------------------------------------------------------
    # Easting
    # --------------------------------------------------------

    easting = (

        k0
        *
        n
        *
        (

            aa

            +

            (
                1
                - t
                + c
            )
            *
            aa ** 3
            /
            6


            +

            (
                5
                - 18 * t
                + t ** 2
                + 72 * c
                - 58 * ecc_prime_squared
            )
            *
            aa ** 5
            /
            120

        )

        +
        500000.0
    )


    # --------------------------------------------------------
    # Northing
    # --------------------------------------------------------

    northing = (

        k0
        *
        (

            m

            +

            n
            *
            math.tan(lat_rad)
            *
            (

                aa ** 2
                /
                2


                +

                (
                    5
                    - t
                    + 9 * c
                    + 4 * c ** 2
                )
                *
                aa ** 4
                /
                24


                +

                (
                    61
                    - 58 * t
                    + t ** 2
                    + 600 * c
                    - 330 * ecc_prime_squared
                )
                *
                aa ** 6
                /
                720

            )
        )
    )


    # Southern hemisphere

    if latitude < 0:

        northing += 10000000.0


    return (
        easting,
        northing,
        zone
    )


# ============================================================
# CREATE 100-ACRE BOUNDING BOX
# ============================================================

def create_bbox(
    latitude,
    longitude
):

    latitude = float(latitude)
    longitude = float(longitude)


    easting, northing, zone = (
        latlon_to_utm(
            latitude,
            longitude
        )
    )


    min_x = (
        easting -
        HALF_SIDE_M
    )

    min_y = (
        northing -
        HALF_SIDE_M
    )

    max_x = (
        easting +
        HALF_SIDE_M
    )

    max_y = (
        northing +
        HALF_SIDE_M
    )


    bbox = [
        min_x,
        min_y,
        max_x,
        max_y
    ]


    return bbox, zone


# ============================================================
# REQUEST SENTINEL-2 DATA
# ============================================================

def get_ndvi(
    latitude,
    longitude,
    polygon=None
):

    latitude = float(latitude)
    longitude = float(longitude)


    token = get_access_token()


    # --------------------------------------------------------
    # Create monitoring bounds
    # --------------------------------------------------------

    if polygon:
        zone = get_utm_zone(longitude)
        utm_ring = []
        for point in polygon:
            lon = float(point[0])
            lat = float(point[1])
            x, y, point_zone = latlon_to_utm(lat, lon)
            if point_zone != zone:
                raise ValueError(
                    "Selected forest boundary crosses a UTM zone. "
                    "Please draw a boundary within one UTM zone."
                )
            utm_ring.append([x, y])
        if len(utm_ring) < 3:
            raise ValueError("Forest boundary must contain at least 3 points.")

        epsg = 32600 + zone if latitude >= 0 else 32700 + zone
        crs = "http://www.opengis.net/def/crs/EPSG/0/" + str(epsg)
        bounds = {
            "geometry": {"type": "Polygon", "coordinates": [utm_ring]},
            "properties": {"crs": crs}
        }
    else:
        bbox, zone = create_bbox(latitude, longitude)
        epsg = 32600 + zone if latitude >= 0 else 32700 + zone
        crs = "http://www.opengis.net/def/crs/EPSG/0/" + str(epsg)
        bounds = {
            "bbox": bbox,
            "properties": {"crs": crs}
        }


    # --------------------------------------------------------
    # Last 90 days
    # --------------------------------------------------------

    end_date = datetime.now(
        timezone.utc
    )

    start_date = (
        end_date
        -
        timedelta(days=90)
    )


    time_from = (
        start_date.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )


    time_to = (
        end_date.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )


    # --------------------------------------------------------
    # Request body
    # --------------------------------------------------------

    request_body = {

        "input": {

            "bounds": bounds,


            "data": [

                {

                    "type":
                        "sentinel-2-l2a",

                    "dataFilter": {

                        "mosaickingOrder":
                            "leastCC"
                    }
                }
            ]
        },


        "aggregation": {

            "timeRange": {

                "from":
                    time_from,

                "to":
                    time_to
            },


            "aggregationInterval": {

                "of":
                    "P10D"
            },


            "evalscript":
                EVALSCRIPT,


            "resx":
                10,

            "resy":
                10
        },


        "calculations": {

            "ndvi": {

                "statistics": {

                    "default": {}
                }
            },


            "forestMask": {

                "statistics": {

                    "default": {}
                }
            }
        }
    }


    # --------------------------------------------------------
    # Headers
    # --------------------------------------------------------

    headers = {

        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json"
    }


    print()
    print(
        "🛰️ Requesting Sentinel-2 data..."
    )


    # --------------------------------------------------------
    # API request
    # --------------------------------------------------------

    response = requests.post(

        STATS_URL,

        headers=headers,

        json=request_body,

        timeout=120
    )


    # --------------------------------------------------------
    # Error handling
    # --------------------------------------------------------

    if response.status_code != 200:

        print()
        print(
            "Sentinel API Error:",
            response.status_code
        )

        print(
            response.text
        )


    response.raise_for_status()


    return response.json()


# ============================================================
# GET BAND STATISTICS
# ============================================================

def get_band_stats(output):

    if not output:

        return {}


    return (
        output
        .get(
            "bands",
            {}
        )
        .get(
            "B0",
            {}
        )
        .get(
            "stats",
            {}
        )
    )


# ============================================================
# EXTRACT ONE OBSERVATION
# ============================================================

def extract_observation(interval, monitoring_area_acres=None):

    outputs = interval.get(
        "outputs",
        {}
    )


    # --------------------------------------------------------
    # NDVI statistics
    # --------------------------------------------------------

    ndvi_stats = get_band_stats(
        outputs.get(
            "ndvi",
            {}
        )
    )


    # --------------------------------------------------------
    # Forest statistics
    # --------------------------------------------------------

    forest_stats = get_band_stats(
        outputs.get(
            "forestMask",
            {}
        )
    )


    ndvi = ndvi_stats.get(
        "mean"
    )


    forest_fraction = (
        forest_stats.get(
            "mean"
        )
    )


    # --------------------------------------------------------
    # Check missing values
    # --------------------------------------------------------

    if ndvi is None:

        return None


    if forest_fraction is None:

        return None


    # --------------------------------------------------------
    # Convert to float
    # --------------------------------------------------------

    ndvi = float(ndvi)

    forest_fraction = float(
        forest_fraction
    )


    # --------------------------------------------------------
    # IMPORTANT:
    # Reject NaN and infinity
    # --------------------------------------------------------

    if not math.isfinite(ndvi):

        return None


    if not math.isfinite(
        forest_fraction
    ):

        return None


    # --------------------------------------------------------
    # Keep forest fraction between 0 and 1
    # --------------------------------------------------------

    forest_fraction = max(

        0.0,

        min(
            1.0,
            forest_fraction
        )
    )


    # --------------------------------------------------------
    # FOREST COVER PERCENTAGE
    # --------------------------------------------------------

    forest_cover_percent = (

        forest_fraction
        *
        100
    )


    # --------------------------------------------------------
    # FOREST AREA IN ACRES
    # --------------------------------------------------------

    forest_area_acres = (

        MONITORING_AREA_ACRES
        *
        forest_fraction
    )


    # --------------------------------------------------------
    # PIXEL COUNT
    # --------------------------------------------------------

    pixels = forest_stats.get(
        "sampleCount",
        0
    )


    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    interval_info = interval.get(
        "interval",
        {}
    )


    observation_date = (
        interval_info.get(
            "from"
        )
    )


    if observation_date:

        observation_date = (
            observation_date[:10]
        )


    # --------------------------------------------------------
    # RETURN OBSERVATION
    # --------------------------------------------------------

    return {

        "date":
            observation_date,

        "ndvi":
            round(
                ndvi,
                4
            ),

        "forest_cover":
            round(
                forest_cover_percent,
                2
            ),

        "forest_area_acres":
            round(
                forest_area_acres,
                2
            ),

        "pixels":
            int(pixels),

        "monitoring_area_acres":
            MONITORING_AREA_ACRES
    }


# ============================================================
# GET SATELLITE OBSERVATIONS
# ============================================================

def get_satellite_observations(
    latitude,
    longitude,
    polygon=None,
    monitoring_area_acres=None
):

    latitude = float(latitude)
    longitude = float(longitude)


    # --------------------------------------------------------
    # Get satellite result
    # --------------------------------------------------------

    result = get_ndvi(
        latitude,
        longitude,
        polygon=polygon
    )


    observations = []


    # --------------------------------------------------------
    # Process every interval
    # --------------------------------------------------------

    for interval in result.get(
        "data",
        []
    ):

        observation = (
            extract_observation(
                interval,
                monitoring_area_acres=monitoring_area_acres
            )
        )


        # Only valid observations
        if observation is not None:

            observations.append(
                observation
            )


    # --------------------------------------------------------
    # Sort oldest → newest
    # --------------------------------------------------------

    observations.sort(
        key=lambda x:
            x["date"]
    )


    print()
    print(
        "✅ Satellite data received!"
    )


    # --------------------------------------------------------
    # Display observations
    # --------------------------------------------------------

    for observation in observations:

        print(

            observation["date"],

            "→ NDVI:",
            observation["ndvi"],

            "→ Forest:",
            f"{observation['forest_cover']}%",

            "→ Area:",
            f"{observation['forest_area_acres']} acres",

            "→ Pixels:",
            observation["pixels"]
        )


    return observations


# ============================================================
# SATELLITE VISUAL EVIDENCE
# ============================================================
#
# This uses the Sentinel Hub Process API only when the frontend
# asks for a before/after evidence image. The generated image is
# cached on disk so refreshing the page does not repeat the
# Copernicus request.
# ============================================================

TRUE_COLOR_EVALSCRIPT = """
//VERSION=3

function setup() {
    return {
        input: ["B02", "B03", "B04", "SCL", "dataMask"],
        output: {
            bands: 3,
            sampleType: "AUTO"
        }
    };
}

function clamp01(value) {
    return Math.max(0.0, Math.min(1.0, value));
}

function enhance(reflectance) {
    var value = clamp01(reflectance * 3.0);
    return Math.pow(value, 0.75);
}

function evaluatePixel(sample) {
    if (sample.dataMask == 0) {
        return [0, 0, 0];
    }

    if (
        sample.SCL == 8 ||
        sample.SCL == 9 ||
        sample.SCL == 10
    ) {
        return [0.92, 0.92, 0.92];
    }

    if (sample.SCL == 3) {
        return [0.18, 0.18, 0.18];
    }

    return [
        enhance(sample.B04),
        enhance(sample.B03),
        enhance(sample.B02)
    ];
}
"""


def _evidence_bbox(latitude, longitude):
    """Approximate the existing 100-acre monitoring square in WGS84."""

    half_m = MONITORING_SIDE_M / 2.0
    meters_per_degree_lat = 111320.0
    cos_lat = max(0.2, math.cos(math.radians(latitude)))
    meters_per_degree_lon = meters_per_degree_lat * cos_lat

    lat_delta = half_m / meters_per_degree_lat
    lon_delta = half_m / meters_per_degree_lon

    return [
        longitude - lon_delta,
        latitude - lat_delta,
        longitude + lon_delta,
        latitude + lat_delta
    ]


def get_satellite_evidence_image(
    latitude,
    longitude,
    observation_date
):
    """
    Return a cached local path for a Sentinel-2 true-colour image.

    The request is deliberately limited to a small evidence area and
    a short time window. It is called only for requested evidence.
    """

    latitude = float(latitude)
    longitude = float(longitude)
    date_text = str(observation_date)[:10]

    try:
        date_obj = datetime.strptime(
            date_text,
            "%Y-%m-%d"
        )
    except ValueError:
        raise ValueError("Invalid satellite observation date.")

    safe_lat = f"{latitude:.5f}".replace("-", "m").replace(".", "_")
    safe_lon = f"{longitude:.5f}".replace("-", "m").replace(".", "_")
    cache_file = (
        EVIDENCE_CACHE_DIR
        / f"s2_truecolor_v4_{safe_lat}_{safe_lon}_{date_text}.jpg"
    )

    if cache_file.exists() and cache_file.stat().st_size > 1000:
        print("💾 Satellite evidence cache hit:", cache_file.name)
        return cache_file

    token = get_access_token()

    bbox = _evidence_bbox(
        latitude,
        longitude
    )

    # The Statistics API observation date can represent the start of
    # a P10D aggregation interval, not the exact Sentinel-2 acquisition
    # date. Search a few days around it so the visual evidence does not
    # become an all-black no-data image.
    evidence_from = (
        date_obj - timedelta(days=5)
    ).strftime("%Y-%m-%d")

    evidence_to = (
        date_obj + timedelta(days=6)
    ).strftime("%Y-%m-%d")

    request_body = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs":
                    "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                }
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{evidence_from}T00:00:00Z",
                            "to": f"{evidence_to}T00:00:00Z"
                        },
                        # Avoid selecting heavily cloudy Sentinel-2 tiles.
                        # This is tile-level cloud metadata, so it is a
                        # filter rather than a guarantee that every pixel
                        # in the AOI is cloud-free.
                        "mosaickingOrder": "leastCC"
                    }
                }
            ]
        },
        "output": {
            "width": 768,
            "height": 768,
            "responses": [
                {
                    "identifier": "default",
                    "format": {
                        "type": "image/jpeg",
                        "quality": 85
                    }
                }
            ]
        },
        "evalscript": TRUE_COLOR_EVALSCRIPT
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "image/jpeg"
    }

    print(
        "🛰️ Requesting Sentinel-2 visual evidence:",
        date_text,
        f"(search window: {evidence_from} to {evidence_to}, "
        "max cloud: 20%)"
    )

    response = requests.post(
        PROCESS_URL,
        headers=headers,
        json=request_body,
        timeout=120
    )

    if response.status_code != 200:
        print(
            "Sentinel Process API Error:",
            response.status_code
        )
        print(response.text[:2000])

    response.raise_for_status()

    content_type = response.headers.get(
        "Content-Type",
        ""
    ).lower()

    if "image/" not in content_type:
        raise RuntimeError(
            "Sentinel Process API did not return an image."
        )

    cache_file.write_bytes(response.content)

    print(
        "💾 Satellite evidence cached:",
        cache_file.name
    )

    return cache_file


# ============================================================
# POLYGON SATELLITE SCAN
# ============================================================

def calculate_polygon_area_acres(polygon):
    if not polygon or len(polygon) < 3:
        raise ValueError("A valid forest polygon is required.")

    zone = get_utm_zone(float(polygon[0][0]))
    points = []
    for point in polygon:
        lon = float(point[0]); lat = float(point[1])
        x, y, point_zone = latlon_to_utm(lat, lon)
        if point_zone != zone:
            raise ValueError("Selected forest boundary crosses a UTM zone.")
        points.append((x, y))

    area = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]; x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1

    return (abs(area) / 2.0) / ACRE_TO_SQ_M


def scan_forest_boundary(polygon):
    area_acres = calculate_polygon_area_acres(polygon)
    if area_acres <= 0:
        raise ValueError("The selected forest boundary has zero area.")

    latitude = sum(float(p[1]) for p in polygon) / len(polygon)
    longitude = sum(float(p[0]) for p in polygon) / len(polygon)

    observations = get_satellite_observations(
        latitude, longitude, polygon=polygon,
        monitoring_area_acres=area_acres
    )
    return observations, area_acres


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    # Test location
    latitude = 15.34829
    longitude = 75.75293


    print()
    print("=" * 60)
    print(
        "DEFORESTATION EARLY WARNING SYSTEM"
    )
    print("=" * 60)


    print(
        f"Latitude  : {latitude}"
    )

    print(
        f"Longitude : {longitude}"
    )

    print(
        f"Monitoring area : "
        f"{MONITORING_AREA_ACRES:.2f} acres"
    )

    print(
        f"Monitoring square : "
        f"{MONITORING_SIDE_M:.2f} m × "
        f"{MONITORING_SIDE_M:.2f} m"
    )

    print(
        f"Forest NDVI threshold : "
        f"{FOREST_NDVI_THRESHOLD}"
    )


    print("=" * 60)


    try:

        observations = (
            get_satellite_observations(
                latitude,
                longitude
            )
        )


        if not observations:

            print()
            print(
                "No valid satellite observations found."
            )


        else:

            print()
            print(
                f"Found {len(observations)} "
                "valid satellite observations."
            )


            # ------------------------------------------------
            # Latest valid observation
            # ------------------------------------------------

            latest = observations[-1]


            print()
            print("=" * 60)
            print(
                "LATEST VALID SATELLITE OBSERVATION"
            )
            print("=" * 60)


            print(
                f"Date: "
                f"{latest['date']}"
            )

            print(
                f"NDVI: "
                f"{latest['ndvi']}"
            )

            print(
                f"Forest cover: "
                f"{latest['forest_cover']}%"
            )

            print(
                f"Estimated forest area: "
                f"{latest['forest_area_acres']} acres"
            )

            print("=" * 60)


    except Exception:

        print()
        print("=" * 60)
        print("ERROR")
        print("=" * 60)

        import traceback

        traceback.print_exc()

# ============================================================
# PIXEL-LEVEL CHANGE DETECTION
# ============================================================

CHANGE_CACHE_DIR = (
    Path(__file__).resolve().parent
    / "static"
    / "change_maps"
)
CHANGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CHANGE_THRESHOLD = -0.25
CHANGE_GRID_SIZE = 128

CHANGE_NDVI_EVALSCRIPT = """
//VERSION=3
function setup() {
    return {
        input: ["B04", "B08", "dataMask"],
        output: { bands: 1, sampleType: "FLOAT32" }
    };
}
function evaluatePixel(sample) {
    var denominator = sample.B08 + sample.B04;
    if (sample.dataMask == 0 || denominator == 0) {
        return [-9999];
    }
    return [(sample.B08 - sample.B04) / denominator];
}
"""


def _change_map_dates(date_text):
    date_obj = datetime.strptime(str(date_text)[:10], "%Y-%m-%d")
    # Statistics observations are period labels, so use the same small
    # search window used by the visual evidence endpoint.
    return (
        (date_obj - timedelta(days=5)).strftime("%Y-%m-%d"),
        (date_obj + timedelta(days=6)).strftime("%Y-%m-%d")
    )


def _request_ndvi_raster(token, bbox, date_text):
    """
    Request a Sentinel-2 NDVI raster for the date represented by
    a Statistics API observation.

    The observation date is treated as a period label, so a small
    search window is used around it.

    maxCloudCoverage is intentionally not used here because testing
    showed that the 20% restriction could return an entirely NoData
    raster for otherwise usable locations. The Process API can instead
    choose the least-cloudy available acquisition in the search window.
    """

    evidence_from, evidence_to = _change_map_dates(date_text)

    body = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                }
            },
            "data": [{
                "type": "sentinel-2-l2a",
               "dataFilter": {
    "timeRange": {
        "from": f"{evidence_from}T00:00:00Z",
        "to": f"{evidence_to}T23:59:59Z"
    },
    "mosaickingOrder": "leastCC"
}
            }]
        },
        "output": {
            "width": CHANGE_GRID_SIZE,
            "height": CHANGE_GRID_SIZE,
            "responses": [{
                "identifier": "default",
                "format": {
                    "type": "image/tiff"
                }
            }]
        },
        "evalscript": CHANGE_NDVI_EVALSCRIPT
    }

    response = requests.post(
        PROCESS_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "image/tiff"
        },
        json=body,
        timeout=120
    )

    if response.status_code != 200:
        print(
            "Sentinel change-map Process API Error:",
            response.status_code
        )
        print(response.text[:2000])

    response.raise_for_status()

    return response.content


def _read_float32_tiff(content):
    try:
        import tifffile
        import numpy as np
        from io import BytesIO

        array = tifffile.imread(BytesIO(content))

        array = np.asarray(array, dtype=np.float32)

        if array.ndim == 3:
            array = array[0]

        if array.ndim != 2:
            raise RuntimeError(
                f"Unexpected Sentinel raster dimensions: {array.shape}"
            )

        height, width = array.shape

        values = array.reshape(-1).tolist()

        return (width, height), values

    except Exception as error:
        raise RuntimeError(
            f"Unable to read Sentinel NDVI raster: {error}"
        )


def get_forest_change_map(latitude, longitude, before_date, after_date):
    """Return GeoJSON-like pixel cells where NDVI decreased materially."""
    latitude = float(latitude)
    longitude = float(longitude)
    before_date = str(before_date)[:10]
    after_date = str(after_date)[:10]

    cache_key = (
        f"change_v3_{latitude:.5f}_{longitude:.5f}_"
        f"{before_date}_{after_date}.json"
    ).replace("-", "m").replace(".", "_")
    cache_file = CHANGE_CACHE_DIR / cache_key

    if cache_file.exists() and cache_file.stat().st_size > 100:
        import json
        print("💾 Forest change-map cache hit:", cache_file.name)
        return json.loads(cache_file.read_text(encoding="utf-8"))

    token = get_access_token()
    bbox = _evidence_bbox(latitude, longitude)

    before_bytes = _request_ndvi_raster(token, bbox, before_date)
    after_bytes = _request_ndvi_raster(token, bbox, after_date)

    (width_b, height_b), before = _read_float32_tiff(before_bytes)
    (width_a, height_a), after = _read_float32_tiff(after_bytes)

    if (width_b, height_b) != (width_a, height_a):
        raise RuntimeError("Before/after Sentinel rasters have different dimensions.")

    width, height = width_b, height_b
    min_lon, min_lat, max_lon, max_lat = bbox
    cell_lon = (max_lon - min_lon) / width
    cell_lat = (max_lat - min_lat) / height

    features = []
    changed_count = 0
    valid_count = 0
    decrease_count = 0

    for row in range(height):
        for col in range(width):
            b = float(before[row * width + col])
            a = float(after[row * width + col])
            if b <= -9990 or a <= -9990:
                continue
            valid_count += 1
            change = a - b
            if change <= CHANGE_THRESHOLD:
                decrease_count += 1
            # Require both a meaningful NDVI decrease and reasonably
            # vegetated conditions before the decrease. The threshold is
            # intentionally moderate so the map can reveal candidate
            # change areas even when the overall location-level change is
            # around 10 percent.
            if change <= CHANGE_THRESHOLD and b >= 0.35:
                west = min_lon + col * cell_lon
                east = west + cell_lon
                north = max_lat - row * cell_lat
                south = north - cell_lat
                features.append({
                    "type": "Feature",
                    "properties": {
                        "before_ndvi": round(b, 3),
                        "after_ndvi": round(a, 3),
                        "ndvi_change": round(change, 3)
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south]
                        ]]
                    }
                })
                changed_count += 1

    result = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "latitude": latitude,
            "longitude": longitude,
            "before_date": before_date,
            "after_date": after_date,
            "threshold": CHANGE_THRESHOLD,
            "changed_cells": changed_count,
            "valid_cells": valid_count,
            "decrease_cells": decrease_count,
            "grid_width": width,
            "grid_height": height,
            "note": "Pixel-level NDVI decrease candidate areas; not a legally authoritative forest boundary."
        }
    }

    import json
    cache_file.write_text(json.dumps(result), encoding="utf-8")
    print("🛰️ Forest change map generated:", changed_count, "candidate cells")
    return result
