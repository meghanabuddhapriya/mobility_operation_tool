"""Generates reproducible sample CSVs (seeded) for the Mobility Operations Intelligence Tool.

Usage:  python data/generate_sample_data.py
Writes drivers.csv, trips.csv and driver_activity.csv next to this script.

Injected data problems (so validation and anomaly modules have something to find):
    17 completed trips with a missing pickup timestamp     3 trips with an unknown driver ID
     4 negative fares                                       2 trips with drop time before pickup
     2 unusually high fares (5000)                          3 completed trips with zero distance
     2 extremely long trips (> 5 hours)                     1 unreadable pickup timestamp
"""
import csv
import os
import random
from datetime import datetime, timedelta

SEED = 42
NUM_DRIVERS = 250
NUM_TRIPS = 4500
START_DATE = datetime(2023, 10, 1)

CITIES = ["Bangalore", "Mumbai", "Delhi"]
ZONES = {"Bangalore": ["Koramangala", "Indiranagar", "Whitefield", "HSR Layout", "Jayanagar"],
         "Mumbai": ["Bandra", "Andheri", "Colaba", "Powai", "Juhu"],
         "Delhi": ["Connaught Place", "Saket", "Vasant Kunj", "Dwarka", "Rohini"]}
NAMES = ["Rahul", "Amit", "Priya", "Neha", "Vikram", "Suresh", "Ravi", "Anjali", "Karan", "Pooja"]
VEHICLE_TYPES = ["Hatchback", "Sedan", "SUV"]
STATUS_DRIVER = ["Active", "Active", "Active", "Active", "Inactive"]
CANCEL_REASONS = ["Driver Cancelled", "Rider Cancelled", "Driver Not Found", "Payment Issue", "Other"]

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

MISSING_PICKUP = {i for i in range(250, 250 * 17 + 1, 250)}          # 17 trips
NEGATIVE_FARE = {50, 150, 350, 450}                                   # 4 trips (not 250: already missing pickup)
UNKNOWN_DRIVER = {100, 600, 900}                                      # 3 trips
DROP_BEFORE_PICKUP = {400, 800}
HIGH_FARE = {1050, 2050}
ZERO_DISTANCE = {1300, 1700, 2600}
LONG_TRIP = {3100, 3600}
BAD_TIMESTAMP = {2200}
FORCE_COMPLETED = (MISSING_PICKUP | NEGATIVE_FARE | DROP_BEFORE_PICKUP | HIGH_FARE
                   | ZERO_DISTANCE | LONG_TRIP | BAD_TIMESTAMP)


def random_date(start, days=30):
    return start + timedelta(days=random.randint(0, days - 1), hours=random.randint(0, 23),
                             minutes=random.randint(0, 59))


def fmt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value


def generate_drivers():
    drivers = []
    with open(os.path.join(OUT_DIR, "drivers.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["driver_id", "driver_name", "city", "vehicle_type", "rating", "status"])
        for i in range(1, NUM_DRIVERS + 1):
            driver = {"driver_id": f"D{100 + i}", "driver_name": random.choice(NAMES),
                      "city": random.choice(CITIES), "vehicle_type": random.choice(VEHICLE_TYPES),
                      "rating": round(random.uniform(3.0, 5.0), 1), "status": random.choice(STATUS_DRIVER)}
            drivers.append(driver)
            writer.writerow(driver.values())
    return drivers


def generate_trips(drivers):
    with open(os.path.join(OUT_DIR, "trips.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["trip_id", "driver_id", "rider_id", "city", "pickup_zone", "drop_zone",
                         "request_time", "pickup_time", "drop_time", "distance_km", "fare",
                         "status", "cancellation_reason"])
        for i in range(1, NUM_TRIPS + 1):
            driver = {"driver_id": "D9999", "city": "Bangalore"} if i in UNKNOWN_DRIVER else random.choice(drivers)
            city = driver["city"]
            pickup_zone = random.choice(ZONES[city])
            drop_zone = random.choice(ZONES[city])
            while drop_zone == pickup_zone:
                drop_zone = random.choice(ZONES[city])
            request_time = random_date(START_DATE)

            is_cancelled = random.random() < 0.115 and i not in FORCE_COMPLETED
            if is_cancelled:
                status = "Cancelled"
                reason = random.choices(CANCEL_REASONS, weights=[35, 25, 20, 10, 10])[0]
                pickup_time = drop_time = ""
                distance_km, fare = 0.0, 0.0
            else:
                status, reason = "Completed", ""
                pickup_time = request_time + timedelta(minutes=random.randint(2, 15))
                distance_km = round(random.uniform(2.0, 25.0), 1)
                drop_time = pickup_time + timedelta(minutes=int(distance_km * random.uniform(2.5, 4.0)))
                fare = round(distance_km * random.uniform(15.0, 25.0) + 50)

                if i in NEGATIVE_FARE:
                    fare = -abs(fare)
                if i in DROP_BEFORE_PICKUP:
                    drop_time = pickup_time - timedelta(minutes=10)
                if i in HIGH_FARE:
                    fare = 5000.0
                if i in ZERO_DISTANCE:
                    distance_km = 0.0
                if i in LONG_TRIP:
                    drop_time = pickup_time + timedelta(hours=5, minutes=30)
                if i in MISSING_PICKUP:
                    pickup_time = ""
                if i in BAD_TIMESTAMP:
                    pickup_time = "31/02/2023 25:61"

            writer.writerow([f"T{1000 + i}", driver["driver_id"], f"R{random.randint(1000, 5000)}", city,
                             pickup_zone, drop_zone, fmt(request_time), fmt(pickup_time), fmt(drop_time),
                             distance_km, fare, status, reason])


def generate_driver_activity(drivers):
    with open(os.path.join(OUT_DIR, "driver_activity.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["driver_id", "timestamp", "status"])
        for driver in drivers:
            if driver["status"] == "Inactive":
                continue
            now = START_DATE + timedelta(days=random.randint(0, 5))
            for _ in range(random.randint(5, 15)):
                writer.writerow([driver["driver_id"], fmt(now), "Online"])
                for _ in range(random.randint(3, 10)):
                    now += timedelta(minutes=random.randint(15, 120))
                    writer.writerow([driver["driver_id"], fmt(now), random.choice(["Busy", "Idle"])])
                now += timedelta(minutes=random.randint(10, 60))
                writer.writerow([driver["driver_id"], fmt(now), "Offline"])
                now += timedelta(hours=random.randint(12, 24))


if __name__ == "__main__":
    random.seed(SEED)
    all_drivers = generate_drivers()
    generate_trips(all_drivers)
    generate_driver_activity(all_drivers)
    print(f"Sample data written to {OUT_DIR}")
