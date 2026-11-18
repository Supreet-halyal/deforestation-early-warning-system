import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# =========================================================
# CREATE TABLES
# =========================================================

def create_tables():

    connection = get_connection()
    cursor = connection.cursor()

    # -----------------------------------------------------
    # LOCATIONS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id SERIAL PRIMARY KEY,
            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # SATELLITE OBSERVATIONS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS satellite_observations (
            id SERIAL PRIMARY KEY,
            location_id INTEGER NOT NULL,
            observation_date DATE NOT NULL,
            ndvi DOUBLE PRECISION,
            forest_cover DOUBLE PRECISION,
            forest_area_acres DOUBLE PRECISION,
            data_source VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (location_id)
            REFERENCES locations(id)
            ON DELETE CASCADE
        )
    """)

    # -----------------------------------------------------
    # ADD FOREST AREA COLUMN TO EXISTING TABLE
    # -----------------------------------------------------

    cursor.execute("""
        ALTER TABLE satellite_observations
        ADD COLUMN IF NOT EXISTS forest_area_acres DOUBLE PRECISION
    """)

    # -----------------------------------------------------
    # ALERTS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id SERIAL PRIMARY KEY,
            location_id INTEGER NOT NULL,
            change_percentage DOUBLE PRECISION,
            risk_level VARCHAR(20),
            message TEXT,
            status VARCHAR(20) DEFAULT 'NEW',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (location_id)
            REFERENCES locations(id)
            ON DELETE CASCADE
        )
    """)

    connection.commit()

    cursor.close()
    connection.close()

    print("✅ Database tables are ready!")


# =========================================================
# FIND LOCATION
# =========================================================

def find_location(latitude, longitude):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id
        FROM locations
        WHERE ABS(latitude - %s) < 0.001
        AND ABS(longitude - %s) < 0.001
        ORDER BY id ASC
        LIMIT 1
    """, (
        latitude,
        longitude
    ))

    result = cursor.fetchone()

    cursor.close()
    connection.close()

    if result:
        return result[0]

    return None


# =========================================================
# SAVE LOCATION
# =========================================================

def save_location(latitude, longitude):

    existing_id = find_location(
        latitude,
        longitude
    )

    if existing_id:

        print(
            "⚡ Existing monitoring location:",
            existing_id
        )

        return existing_id

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO locations
        (
            latitude,
            longitude
        )
        VALUES
        (
            %s,
            %s
        )
        RETURNING id
    """, (
        latitude,
        longitude
    ))

    location_id = cursor.fetchone()[0]

    connection.commit()

    cursor.close()
    connection.close()

    print(
        "💾 New monitoring location:",
        location_id
    )

    return location_id


# =========================================================
# GET OBSERVATIONS
# =========================================================

def get_observations(location_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            observation_date,
            ndvi,
            forest_cover,
            forest_area_acres,
            data_source
        FROM satellite_observations
        WHERE location_id = %s
        ORDER BY observation_date ASC
    """, (
        location_id,
    ))

    rows = cursor.fetchall()

    cursor.close()
    connection.close()

    observations = []

    for row in rows:

        observations.append({

            "date":
                row[0].isoformat(),

            "ndvi":
                float(row[1])
                if row[1] is not None
                else None,

            "forest_cover":
                float(row[2])
                if row[2] is not None
                else None,

            "forest_area_acres":
                float(row[3])
                if row[3] is not None
                else None,

            "source":
                row[4]

        })

    return observations


# =========================================================
# GET ALL LOCATION HISTORIES
# =========================================================

def get_all_location_histories():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            l.id,
            l.latitude,
            l.longitude,
            o.observation_date,
            o.ndvi,
            o.forest_cover,
            o.forest_area_acres,
            o.data_source

        FROM locations l

        LEFT JOIN satellite_observations o
            ON l.id = o.location_id

        ORDER BY
            l.id ASC,
            o.observation_date ASC
    """)

    rows = cursor.fetchall()

    cursor.close()
    connection.close()

    locations = {}

    for row in rows:

        location_id = row[0]

        if location_id not in locations:

            locations[location_id] = {
                "id": location_id,
                "latitude": float(row[1]),
                "longitude": float(row[2]),
                "observations": []
            }

        if row[3] is not None:

            locations[location_id]["observations"].append({

                "date":
                    row[3].isoformat(),

                "ndvi":
                    float(row[4])
                    if row[4] is not None
                    else None,

                "forest_cover":
                    float(row[5])
                    if row[5] is not None
                    else None,

                "forest_area_acres":
                    float(row[6])
                    if row[6] is not None
                    else None,

                "source":
                    row[7]

            })

    return list(locations.values())


# =========================================================
# SAVE OBSERVATION
# =========================================================

def save_observation(
    location_id,
    observation_date,
    ndvi,
    forest_cover,
    forest_area_acres,
    data_source="Sentinel-2"
):

    connection = get_connection()
    cursor = connection.cursor()

    # -----------------------------------------------------
    # CHECK IF OBSERVATION ALREADY EXISTS
    # -----------------------------------------------------

    cursor.execute("""
        SELECT id
        FROM satellite_observations
        WHERE location_id = %s
        AND observation_date = %s
        LIMIT 1
    """, (
        location_id,
        observation_date
    ))

    existing = cursor.fetchone()

    # -----------------------------------------------------
    # UPDATE EXISTING OBSERVATION
    # -----------------------------------------------------

    if existing:

        cursor.execute("""
            UPDATE satellite_observations

            SET
                ndvi = %s,
                forest_cover = %s,
                forest_area_acres = %s,
                data_source = %s

            WHERE id = %s
        """, (
            ndvi,
            forest_cover,
            forest_area_acres,
            data_source,
            existing[0]
        ))

    # -----------------------------------------------------
    # INSERT NEW OBSERVATION
    # -----------------------------------------------------

    else:

        cursor.execute("""
            INSERT INTO satellite_observations
            (
                location_id,
                observation_date,
                ndvi,
                forest_cover,
                forest_area_acres,
                data_source
            )

            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
        """, (
            location_id,
            observation_date,
            ndvi,
            forest_cover,
            forest_area_acres,
            data_source
        ))

    connection.commit()

    cursor.close()
    connection.close()


# =========================================================
# CREATE ALERT
# =========================================================

def create_alert(
    location_id,
    change_percentage,
    risk_level,
    message
):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO alerts
        (
            location_id,
            change_percentage,
            risk_level,
            message
        )

        VALUES
        (
            %s,
            %s,
            %s,
            %s
        )
    """, (
        location_id,
        change_percentage,
        risk_level,
        message
    ))

    connection.commit()

    cursor.close()
    connection.close()


# =========================================================
# GET ALL ALERTS
# =========================================================

def get_all_alerts():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            alerts.id,
            locations.latitude,
            locations.longitude,
            alerts.change_percentage,
            alerts.risk_level,
            alerts.message,
            alerts.status,
            alerts.created_at

        FROM alerts

        JOIN locations
            ON alerts.location_id = locations.id

        ORDER BY alerts.created_at DESC
    """)

    rows = cursor.fetchall()

    cursor.close()
    connection.close()

    alerts = []

    for row in rows:

        alerts.append({

            "id": row[0],

            "latitude": float(row[1]),

            "longitude": float(row[2]),

            "change_percentage":
                float(row[3])
                if row[3] is not None
                else None,

            "risk_level": row[4],

            "message": row[5],

            "status": row[6],

            "created_at":
                row[7].isoformat()
                if row[7]
                else None

        })

    return alerts


# =========================================================
# ACKNOWLEDGE ALERT
# =========================================================

def acknowledge_alert(alert_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE alerts
        SET status = 'ACKNOWLEDGED'
        WHERE id = %s
    """, (
        alert_id,
    ))

    connection.commit()

    cursor.close()
    connection.close()


# =========================================================
# GET ALL MONITORING LOCATIONS
# =========================================================

def get_all_locations():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            latitude,
            longitude
        FROM locations
        ORDER BY id ASC
    """)

    rows = cursor.fetchall()

    cursor.close()
    connection.close()

    locations = []

    for row in rows:

        locations.append({

            "id": row[0],

            "latitude": float(row[1]),

            "longitude": float(row[2])

        })

    return locations


# =========================================================
# RUN DIRECTLY
# =========================================================

if __name__ == "__main__":

    create_tables()