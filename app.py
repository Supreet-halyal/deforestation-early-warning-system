from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
from pywebpush import webpush, WebPushException

load_dotenv()

from database import (
    create_tables,
    save_location,
    get_observations,
    save_observation,
    create_alert,
    get_all_alerts,
    acknowledge_alert,
    get_all_location_histories
)

from sentinel_test import (
    get_satellite_observations,
    scan_forest_boundary,
    get_forest_change_map
)


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

create_tables()


# =========================================================
# NORMALIZE LOCATION
# =========================================================

def normalize_location(latitude, longitude):

    # Approximately 100m monitoring grid
    grid_size = 0.001

    grid_latitude = (
        round(latitude / grid_size)
        * grid_size
    )

    grid_longitude = (
        round(longitude / grid_size)
        * grid_size
    )

    return (
        grid_latitude,
        grid_longitude
    )


# =========================================================
# CALCULATE NDVI CHANGE
# =========================================================

def calculate_change(previous, present):

    if previous is None:
        return None

    if present is None:
        return None

    if previous == 0:
        return None

    change = (
        (
            present -
            previous
        )
        /
        abs(previous)
    ) * 100

    return change


# =========================================================
# CALCULATE FOREST AREA CHANGE
# =========================================================

def calculate_forest_area_change(previous, present):

    if previous is None:
        return None

    if present is None:
        return None

    if previous == 0:
        return None

    change = (
        (
            present -
            previous
        )
        /
        previous
    ) * 100

    return change


# =========================================================
# TREND ANALYSIS
# =========================================================

def analyze_trend(observations):

    if len(observations) < 3:

        return {
            "trend": "INSUFFICIENT_DATA",
            "declining_periods": 0,
            "trend_message":
                "Not enough observations for trend analysis."
        }

    ndvi_values = []

    for observation in observations:

        if observation["ndvi"] is not None:

            ndvi_values.append(
                observation["ndvi"]
            )

    if len(ndvi_values) < 3:

        return {
            "trend": "INSUFFICIENT_DATA",
            "declining_periods": 0,
            "trend_message":
                "Not enough valid NDVI observations."
        }

    # -----------------------------------------------------
    # COUNT DECLINING PERIODS
    # -----------------------------------------------------

    declining_periods = 0

    for i in range(
        1,
        len(ndvi_values)
    ):

        if (
            ndvi_values[i]
            <
            ndvi_values[i - 1]
        ):

            declining_periods += 1

    # -----------------------------------------------------
    # LAST 3 OBSERVATIONS
    # -----------------------------------------------------

    recent_values = ndvi_values[-3:]

    recent_declines = 0

    for i in range(
        1,
        len(recent_values)
    ):

        if (
            recent_values[i]
            <
            recent_values[i - 1]
        ):

            recent_declines += 1

    # -----------------------------------------------------
    # DECLINING
    # -----------------------------------------------------

    if recent_declines >= 2:

        return {
            "trend": "DECLINING",
            "declining_periods":
                declining_periods,
            "trend_message":
                "Vegetation shows a recent declining trend."
        }

    # -----------------------------------------------------
    # IMPROVING
    # -----------------------------------------------------

    if (
        recent_values[-1]
        >
        recent_values[0]
    ):

        return {
            "trend": "IMPROVING",
            "declining_periods":
                declining_periods,
            "trend_message":
                "Vegetation condition is improving."
        }

    # -----------------------------------------------------
    # STABLE
    # -----------------------------------------------------

    return {
        "trend": "STABLE",
        "declining_periods":
            declining_periods,
        "trend_message":
            "Vegetation condition is relatively stable."
    }


# =========================================================
# RISK CALCULATION
# =========================================================

def calculate_risk(
    change_percentage,
    trend
):

    if change_percentage is None:

        return (
            "LOW",
            "Insufficient data for a strong warning."
        )

    # HIGH

    if (
        change_percentage <= -20
        and
        trend == "DECLINING"
    ):

        return (
            "HIGH",
            "Significant and continuing vegetation decline detected."
        )

    # MODERATE

    if (
        change_percentage <= -10
        or
        trend == "DECLINING"
    ):

        return (
            "MODERATE",
            "Vegetation decline requires monitoring."
        )

    # LOW

    return (
        "LOW",
        "No significant vegetation decline detected."
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# =========================================================
# LOCATION API
# =========================================================

@app.route(
    "/location",
    methods=["POST"]
)
def location():

    try:

        data = request.get_json()

        if not data:

            return jsonify({
                "success": False,
                "message":
                    "No location data received."
            }), 400

        latitude = float(
            data.get("latitude")
        )

        longitude = float(
            data.get("longitude")
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not -90 <= latitude <= 90:

            return jsonify({
                "success": False,
                "message":
                    "Invalid latitude."
            }), 400

        if not -180 <= longitude <= 180:

            return jsonify({
                "success": False,
                "message":
                    "Invalid longitude."
            }), 400

        # -------------------------------------------------
        # NORMALIZE
        # -------------------------------------------------

        (
            grid_latitude,
            grid_longitude
        ) = normalize_location(
            latitude,
            longitude
        )

        print(
            "\n===================================="
        )

        print(
            "📍 User clicked:"
        )

        print(
            latitude,
            longitude
        )

        print(
            "\n🗺️ Monitoring grid:"
        )

        print(
            grid_latitude,
            grid_longitude
        )

        # -------------------------------------------------
        # FIND / CREATE LOCATION
        # -------------------------------------------------

        location_id = save_location(
            grid_latitude,
            grid_longitude
        )

        print(
            "\n📌 Location ID:",
            location_id
        )

        # -------------------------------------------------
        # CHECK CACHE
        # -------------------------------------------------

        observations = get_observations(
            location_id
        )

        print(
            "💾 Stored observations:",
            len(observations)
        )

        # =================================================
        # CACHE HIT
        # =================================================

        if len(observations) > 0:

            print(
                "\n⚡ CACHE HIT"
            )

            print(
                "❌ Copernicus request skipped."
            )

            data_source = "CACHED"

        # =================================================
        # CACHE MISS
        # =================================================

        else:

            print(
                "\n🛰️ CACHE MISS"
            )

            print(
                "🛰️ Requesting Sentinel-2..."
            )

            satellite_data = (
                get_satellite_observations(
                    grid_latitude,
                    grid_longitude
                )
            )

            # -------------------------------------------------
            # SAVE SATELLITE DATA
            # -------------------------------------------------

            for observation in satellite_data:

                save_observation(
                    location_id,
                    observation["date"],
                    observation["ndvi"],
                    observation["forest_cover"],
                    observation["forest_area_acres"],
                    "Sentinel-2"
                )

            # -------------------------------------------------
            # READ SAVED DATA
            # -------------------------------------------------

            observations = get_observations(
                location_id
            )

            data_source = "LIVE"

            print(
                "💾 Satellite data saved."
            )

        # =================================================
        # PREVIOUS / PRESENT NDVI
        # =================================================

        previous_ndvi = None
        present_ndvi = None
        change_percentage = None

        if len(observations) >= 2:

            previous_ndvi = (
                observations[-2]["ndvi"]
            )

            present_ndvi = (
                observations[-1]["ndvi"]
            )

            change_percentage = (
                calculate_change(
                    previous_ndvi,
                    present_ndvi
                )
            )

        # =================================================
        # PREVIOUS / PRESENT FOREST AREA
        # =================================================

        previous_forest_area = None
        present_forest_area = None
        forest_area_change_percentage = None
        forest_area_loss_acres = None

        if len(observations) >= 2:

            previous_forest_area = (
                observations[-2]["forest_area_acres"]
            )

            present_forest_area = (
                observations[-1]["forest_area_acres"]
            )

            forest_area_change_percentage = (
                calculate_forest_area_change(
                    previous_forest_area,
                    present_forest_area
                )
            )

            if (
                previous_forest_area is not None
                and
                present_forest_area is not None
            ):

                forest_area_loss_acres = (
                    previous_forest_area
                    -
                    present_forest_area
                )

        # =================================================
        # TREND
        # =================================================

        trend_result = analyze_trend(
            observations
        )

        trend = trend_result["trend"]

        # =================================================
        # RISK
        # =================================================

        (
            risk_level,
            message
        ) = calculate_risk(
            change_percentage,
            trend
        )

        # =================================================
        # ALERT
        # =================================================

        if data_source == "LIVE":

            # -------------------------------------------------
            # DUPLICATE ALERT PROTECTION
            # -------------------------------------------------
            # Do not send the same alert repeatedly for the
            # same monitoring grid, risk level and change.
            # A materially different future change can still
            # generate a new alert.
            existing_alerts = get_all_alerts()

            duplicate_alert = any(
                abs(float(alert.get("latitude", 0)) - float(grid_latitude)) < 0.00001
                and
                abs(float(alert.get("longitude", 0)) - float(grid_longitude)) < 0.00001
                and
                alert.get("risk_level") == risk_level
                and
                abs(
                    float(alert.get("change_percentage", 0))
                    - float(change_percentage or 0)
                ) < 0.01
                for alert in existing_alerts
            )

            if duplicate_alert:
                print("⚠️ Duplicate alert detected. Notification skipped.")
            else:
                create_alert(
                    location_id,
                    change_percentage,
                    risk_level,
                    message
                )

                push_body = (
                    f"{message} "
                    f"NDVI change: {change_percentage:.2f}% at "
                    f"{latitude:.5f}, {longitude:.5f}."
                )

                send_push_notification(
                    title=f"🚨 {risk_level} Deforestation Alert",
                    body=push_body,
                    url="/officer"
                )

                email_body = f"""Deforestation Early Warning System

    Risk Level: {risk_level}

    {message}

   Location:
Latitude: {latitude:.5f}
Longitude: {longitude:.5f}

Google Maps Location / Directions:
https://www.google.com/maps/dir/?api=1&destination={latitude:.5f},{longitude:.5f}

    NDVI Change: {change_percentage:.2f}%

    Present Forest Area: {present_forest_area:.2f} acres
    Forest Area Loss: {forest_area_loss_acres:.2f} acres

    Trend: {trend}

    Please open the Officer Dashboard for more details.
    """

                send_email_notification(
                    subject=f"🚨 {risk_level} Deforestation Alert",
                    body=email_body
                )

        # =================================================
        # PRINT
        # =================================================

        print(
            "\n📊 DATA SOURCE:",
            data_source
        )

        print(
            "📈 TREND:",
            trend
        )

        print(
            "🌳 PRESENT FOREST AREA:",
            present_forest_area,
            "acres"
        )

        print(
            "📉 FOREST AREA LOSS:",
            forest_area_loss_acres,
            "acres"
        )

        print(
            "🚦 RISK:",
            risk_level
        )

        print(
            "===================================="
        )

        # =================================================
        # RESPONSE
        # =================================================

        return jsonify({

            "success": True,

            "location_id":
                location_id,

            "latitude":
                latitude,

            "longitude":
                longitude,

            "monitoring_latitude":
                grid_latitude,

            "monitoring_longitude":
                grid_longitude,

            "observations":
                observations,

            "previous_ndvi":
                previous_ndvi,

            "present_ndvi":
                present_ndvi,

            "change_percentage":
                change_percentage,

            "previous_forest_area":
                previous_forest_area,

            "present_forest_area":
                present_forest_area,

            "forest_area_change_percentage":
                forest_area_change_percentage,

            "forest_area_loss_acres":
                forest_area_loss_acres,

            "trend":
                trend,

            "declining_periods":
                trend_result[
                    "declining_periods"
                ],

            "trend_message":
                trend_result[
                    "trend_message"
                ],

            "risk_level":
                risk_level,

            "message":
                message,

            "data_source":
                data_source

        })

    except Exception as error:

        print(
            "\n❌ ERROR:"
        )

        print(
            type(error).__name__,
            ":",
            error
        )

        return jsonify({
            "success": False,
            "message":
                str(error)
        }), 500


# =========================================================
# SERVICE WORKER
# =========================================================
#
# The service worker must be available at the website root
# so it can control the Officer Dashboard.
# =========================================================

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        "static",
        "service-worker.js",
        mimetype="application/javascript"
    )



# =========================================================
# PUSH SUBSCRIPTION
# =========================================================
#
# Step 4:
# Save the browser/device PushSubscription.
# This does not send notifications yet.
# =========================================================


# =========================================================
# EMAIL NOTIFICATIONS
# =========================================================

def send_email_notification(subject, body):
    """Send an alert email to the configured officer address."""

    smtp_server = os.getenv("SMTP_SERVER", "smtp-relay.brevo.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_login = os.getenv("SMTP_LOGIN", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    email_from = os.getenv("EMAIL_FROM", smtp_login)
    officer_email = os.getenv("OFFICER_EMAIL", "")

    if not smtp_login or not smtp_password or not email_from or not officer_email:
        print("⚠️ SMTP email settings are incomplete. Email skipped.")
        return {"sent": False, "skipped": True}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_from
    message["To"] = officer_email
    message.set_content(body)

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_login, smtp_password)
            server.send_message(message)

        print("📧 Email notification sent.")
        return {"sent": True, "skipped": False}

    except Exception as error:
        print("❌ EMAIL DELIVERY ERROR:", error)
        return {"sent": False, "skipped": False, "error": str(error)}


PUSH_SUBSCRIPTIONS_FILE = (
    Path(__file__).resolve().parent /
    "push_subscriptions.json"
)


def load_push_subscriptions():
    if not PUSH_SUBSCRIPTIONS_FILE.exists():
        return []

    try:
        return json.loads(
            PUSH_SUBSCRIPTIONS_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return []


def save_push_subscriptions(subscriptions):
    PUSH_SUBSCRIPTIONS_FILE.write_text(
        json.dumps(
            subscriptions,
            indent=2
        ),
        encoding="utf-8"
    )


def send_push_notification(title, body, url="/officer"):
    """Send a Web Push notification to every registered officer device."""

    private_key_path = os.getenv("VAPID_PRIVATE_KEY_PATH", "private_key.pem")
    claims_email = os.getenv("VAPID_CLAIMS_EMAIL", "")

    if not claims_email:
        print("⚠️ VAPID_CLAIMS_EMAIL is not configured. Push notification skipped.")
        return {"sent": 0, "removed": 0, "skipped": True}

    private_key = Path(private_key_path)
    if not private_key.is_absolute():
        private_key = Path(__file__).resolve().parent / private_key

    if not private_key.exists():
        print("⚠️ VAPID private key file not found:", private_key)
        return {"sent": 0, "removed": 0, "skipped": True}

    subscriptions = load_push_subscriptions()
    if not subscriptions:
        print("📱 No registered push devices.")
        return {"sent": 0, "removed": 0, "skipped": False}

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "icon": "/static/icon-192.png",
        "badge": "/static/icon-192.png"
    })

    active_subscriptions = []
    sent = 0
    removed = 0

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=str(private_key),
                vapid_claims={
                    "sub": claims_email if claims_email.startswith("mailto:") else "mailto:" + claims_email
                }
            )
            sent += 1
            active_subscriptions.append(subscription)
            print("📱 Push notification sent.")

        except WebPushException as error:
            status_code = getattr(error, "status_code", None)
            print("❌ PUSH DELIVERY ERROR:", error)

            # 404/410 means the browser subscription is no longer valid.
            if status_code in (404, 410):
                removed += 1
                print("🗑️ Removed expired push subscription.")
            else:
                active_subscriptions.append(subscription)

        except Exception as error:
            print("❌ PUSH DELIVERY ERROR:", error)
            active_subscriptions.append(subscription)

    if active_subscriptions != subscriptions:
        save_push_subscriptions(active_subscriptions)

    return {
        "sent": sent,
        "removed": removed,
        "skipped": False
    }


@app.route(
    "/api/push/subscribe",
    methods=["POST"]
)
def push_subscribe():
    try:

        subscription = request.get_json() or {}

        endpoint = subscription.get("endpoint")
        keys = subscription.get("keys") or {}

        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            return jsonify({
                "success": False,
                "message": "Invalid push subscription."
            }), 400

        subscriptions = load_push_subscriptions()

        # Replace an existing subscription from the same browser/device.
        subscriptions = [
            item
            for item in subscriptions
            if item.get("endpoint") != endpoint
        ]

        subscriptions.append(subscription)

        save_push_subscriptions(subscriptions)

        print(
            "📱 Push subscription registered. "
            "Total devices:",
            len(subscriptions)
        )

        return jsonify({
            "success": True,
            "message": "Push subscription registered successfully.",
            "devices": len(subscriptions)
        })

    except Exception as error:

        print(
            "❌ PUSH SUBSCRIPTION ERROR:",
            error
        )

        return jsonify({
            "success": False,
            "message": str(error)
        }), 500



# =========================================================
# TEST PUSH NOTIFICATION
# =========================================================
# This is a manual test. It does not call Sentinel-2.
# =========================================================

@app.route("/api/push/test", methods=["POST"])
def push_test():
    try:
        result = send_push_notification(
            title="🔔 Deforestation System Test",
            body="Push notifications are working correctly on this device.",
            url="/officer"
        )
        return jsonify({
            "success": True,
            "message": "Test notification sent.",
            **result
        })
    except Exception as error:
        print("❌ PUSH TEST ERROR:", error)
        return jsonify({
            "success": False,
            "message": str(error)
        }), 500


# =========================================================
# TEST EMAIL NOTIFICATION
# =========================================================
# This is a manual test. It does not call Sentinel-2.
# =========================================================

@app.route("/api/email/test", methods=["POST"])
def email_test():
    try:
        result = send_email_notification(
            subject="🔔 Deforestation System Email Test",
            body="""Deforestation Early Warning System

This is a test email.

If you received this message, email notifications are working correctly.
"""
        )

        return jsonify({
            "success": bool(result.get("sent")),
            "message": (
                "Test email sent."
                if result.get("sent")
                else "Test email was not sent. Check the Flask terminal for the error."
            ),
            **result
        })

    except Exception as error:
        print("❌ EMAIL TEST ERROR:", error)
        return jsonify({
            "success": False,
            "message": str(error)
        }), 500


# =========================================================
# OFFICER DASHBOARD
# =========================================================

@app.route("/officer")
def officer_dashboard():

    return render_template(
        "officer.html"
    )


# =========================================================
# STORED LOCATION HISTORY
# =========================================================

@app.route("/api/location-histories")
def location_histories():

    try:

        histories = get_all_location_histories()

        return jsonify({
            "success": True,
            "locations": histories
        })

    except Exception as error:

        print(
            "\n❌ LOCATION HISTORY ERROR:"
        )

        print(error)

        return jsonify({
            "success": False,
            "message":
                "Unable to load stored location history."
        }), 500


# =========================================================
# GET ALERTS
# =========================================================

@app.route("/api/alerts")
def api_alerts():

    try:

        alerts = get_all_alerts()

        return jsonify({
            "success": True,
            "alerts": alerts
        })

    except Exception as error:

        print(
            "❌ Alert error:",
            error
        )

        return jsonify({
            "success": False,
            "message":
                str(error)
        }), 500


# =========================================================
# ACKNOWLEDGE ALERT
# =========================================================

@app.route(
    "/api/alerts/<int:alert_id>/acknowledge",
    methods=["POST"]
)
def acknowledge_alert_api(alert_id):

    try:

        acknowledge_alert(
            alert_id
        )

        return jsonify({
            "success": True,
            "message":
                "Alert acknowledged successfully."
        })

    except Exception as error:

        print(
            "❌ Acknowledge error:",
            error
        )

        return jsonify({
            "success": False,
            "message":
                str(error)
        }), 500


# =========================================================
# FOREST BOUNDARY SCAN
# =========================================================

@app.route("/api/alert-change-map", methods=["GET"])
def alert_change_map():
    try:
        latitude = request.args.get("latitude", type=float)
        longitude = request.args.get("longitude", type=float)
        before_date = request.args.get("before", "")
        after_date = request.args.get("after", "")

        if latitude is None or longitude is None:
            return jsonify({"success": False, "message": "Valid coordinates are required."}), 400
        if not before_date or not after_date:
            return jsonify({"success": False, "message": "Before and after observation dates are required."}), 400

        change_map = get_forest_change_map(
            latitude,
            longitude,
            before_date,
            after_date
        )

        return jsonify({
            "success": True,
            "change_map": change_map
        })

    except Exception as error:
        print("❌ ALERT CHANGE MAP ERROR:", error)
        return jsonify({
            "success": False,
            "message": str(error)
        }), 500


# =========================================================
# PUBLIC DEFORESTATION REPORTS
# =========================================================

PUBLIC_REPORTS_FILE = Path("public_reports.json")


def load_public_reports():
    if not PUBLIC_REPORTS_FILE.exists():
        return []

    try:
        with PUBLIC_REPORTS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_public_reports(reports):
    with PUBLIC_REPORTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(reports, file, indent=2, ensure_ascii=False)


@app.route("/api/public-reports", methods=["POST"])
def submit_public_report():
    try:
        latitude = float(request.form.get("latitude", ""))
        longitude = float(request.form.get("longitude", ""))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Valid latitude and longitude are required."
        }), 400

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({
            "success": False,
            "message": "Invalid coordinates."
        }), 400

    description = request.form.get("description", "").strip()

    if not description:
        return jsonify({
            "success": False,
            "message": "Please describe what you observed."
        }), 400

    evidence = request.files.get("evidence")

    if evidence is None or not evidence.filename:
        return jsonify({
            "success": False,
            "message": "Please upload an evidence photo."
        }), 400

    allowed_extensions = {"jpg", "jpeg", "png", "webp"}
    extension = evidence.filename.rsplit(".", 1)[-1].lower() if "." in evidence.filename else ""

    if extension not in allowed_extensions:
        return jsonify({
            "success": False,
            "message": "Only JPG, JPEG, PNG, and WEBP images are allowed."
        }), 400

    # Keep the first implementation simple and portable:
    # store the evidence as a data URL inside the JSON report file.
    # A production deployment should move large files to object/file storage.
    raw_image = evidence.read()

    if not raw_image:
        return jsonify({
            "success": False,
            "message": "The uploaded image is empty."
        }), 400

    import base64
    from datetime import datetime, timezone
    from uuid import uuid4

    if len(raw_image) > 8 * 1024 * 1024:
        return jsonify({
            "success": False,
            "message": "Please keep the evidence image below 8 MB."
        }), 400

    mime_type = evidence.mimetype or "image/jpeg"
    report_id = "PUB-" + uuid4().hex[:10].upper()

    report = {
        "report_id": report_id,
        "latitude": latitude,
        "longitude": longitude,
        "description": description,
        "evidence_filename": evidence.filename,
        "evidence_mime_type": mime_type,
        "evidence_data_url": (
            "data:" + mime_type + ";base64," +
            base64.b64encode(raw_image).decode("ascii")
        ),
        "status": "NEW",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "PUBLIC_USER_REPORT"
    }

    reports = load_public_reports()
    reports.append(report)
    save_public_reports(reports)

    return jsonify({
        "success": True,
        "report_id": report_id,
        "status": "NEW",
        "message": "Your deforestation report has been submitted successfully."
    })


@app.route("/api/public-reports", methods=["GET"])
def get_public_reports():
    reports = load_public_reports()

    # Do not expose the large base64 image payload to the browser list view.
    safe_reports = []
    for report in reports:
        item = dict(report)
        item.pop("evidence_data_url", None)
        safe_reports.append(item)

    return jsonify(safe_reports)


@app.route("/boundary-scan", methods=["POST"])
def boundary_scan():
    try:
        data = request.get_json() or {}
        geometry = data.get("geometry")

        if not geometry or geometry.get("type") != "Polygon":
            return jsonify({
                "success": False,
                "message": "A valid forest polygon is required."
            }), 400

        coordinates = geometry.get("coordinates") or []
        if not coordinates or len(coordinates[0]) < 3:
            return jsonify({
                "success": False,
                "message": "The forest boundary must contain at least 3 points."
            }), 400

        polygon = coordinates[0]

        print("\n====================================")
        print("🌳 SELECTED FOREST BOUNDARY SCAN")
        print("====================================")

        observations, area_acres = scan_forest_boundary(polygon)

        print("🌳 Selected area:", round(area_acres, 2), "acres")
        print("🛰️ Observations:", len(observations))

        return jsonify({
            "success": True,
            "area_acres": round(area_acres, 2),
            "area_hectares": round(area_acres * 0.40468564224, 2),
            "observations": observations,
            "data_source": "Sentinel-2"
        })

    except Exception as error:
        print("\n❌ FOREST BOUNDARY SCAN ERROR:")
        print(error)
        return jsonify({
            "success": False,
            "message": str(error)
        }), 500


# =========================================================
# AUTOMATIC MONITORING
# =========================================================
#
# IMPORTANT:
#
# Automatic satellite scanning is DISABLED.
#
# This endpoint exists only so an old frontend button
# does not produce a 404 error.
#
# It NEVER calls Sentinel-2.
#
# Therefore it does NOT consume Copernicus requests.
#
# Satellite data is requested only through /location
# when a location has no stored observations.
# =========================================================

@app.route(
    "/api/monitor",
    methods=["POST"]
)
def monitor_locations():

    print(
        "\n🛰️ Automatic monitoring request received."
    )

    print(
        "⏸️ Automatic Sentinel-2 scanning is disabled."
    )

    print(
        "💾 Existing stored data will continue to be used."
    )

    return jsonify({

        "success": True,

        "enabled": False,

        "message":
            "Automatic satellite scanning is disabled. "
            "No Sentinel-2 API request was made.",

        "locations_checked": 0,

        "results": []

    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )