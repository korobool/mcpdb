"""Phase 4: Generate a large SQLite database for stress testing."""

from __future__ import annotations

import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "stress_test.db"

# Seed for reproducibility
random.seed(42)


def generate_large_db(
    num_customers: int = 100_000,
    num_products: int = 50_000,
    num_transactions: int = 1_000_000,
    num_events: int = 2_000_000,
) -> str:
    """Generate a large SQLite database for stress testing.

    Tables:
    - customers (num_customers rows): demographics
    - products (num_products rows): catalog with categories
    - transactions (num_transactions rows): purchases, no secondary indexes
    - events (num_events rows): time-series append-only log

    Returns the database path.
    """
    if DB_PATH.exists():
        print(f"Database already exists at {DB_PATH}")
        print(f"Size: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")
        return str(DB_PATH)

    print(f"Generating large test database at {DB_PATH}")
    print(f"  Customers: {num_customers:,}")
    print(f"  Products: {num_products:,}")
    print(f"  Transactions: {num_transactions:,}")
    print(f"  Events: {num_events:,}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA cache_size = -64000")  # 64MB cache

    _create_tables(conn)
    _insert_customers(conn, num_customers)
    _insert_products(conn, num_products)
    _insert_transactions(conn, num_transactions, num_customers, num_products)
    _insert_events(conn, num_events, num_customers)

    # Only create PK indexes (simulate missing secondary indexes)
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    print(f"\nDatabase created: {size_mb:.1f} MB")
    return str(DB_PATH)


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create tables without secondary indexes."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            age INTEGER,
            gender TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            income_bracket TEXT,
            signup_date TEXT,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            subcategory TEXT,
            price REAL,
            cost REAL,
            weight_kg REAL,
            supplier TEXT,
            created_at TEXT,
            is_available INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            product_id INTEGER,
            amount REAL,
            quantity INTEGER,
            discount_pct REAL,
            tax_amount REAL,
            total_amount REAL,
            payment_method TEXT,
            status TEXT,
            created_at TEXT,
            shipped_at TEXT,
            delivered_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            event_type TEXT,
            event_data TEXT,
            page_url TEXT,
            session_id TEXT,
            device_type TEXT,
            created_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
    """)


CITIES = [
    ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"),
    ("Houston", "TX"), ("Phoenix", "AZ"), ("Philadelphia", "PA"),
    ("San Antonio", "TX"), ("San Diego", "CA"), ("Dallas", "TX"),
    ("San Jose", "CA"), ("Austin", "TX"), ("Jacksonville", "FL"),
    ("Fort Worth", "TX"), ("Columbus", "OH"), ("Charlotte", "NC"),
    ("San Francisco", "CA"), ("Indianapolis", "IN"), ("Seattle", "WA"),
    ("Denver", "CO"), ("Boston", "MA"),
]

INCOME_BRACKETS = ["<25k", "25k-50k", "50k-75k", "75k-100k", "100k-150k", ">150k"]
GENDERS = ["M", "F", "NB"]
CATEGORIES = ["Electronics", "Clothing", "Home", "Sports", "Books", "Food", "Auto", "Health"]
SUBCATEGORIES = {
    "Electronics": ["Phones", "Laptops", "Tablets", "Accessories", "Audio"],
    "Clothing": ["Shirts", "Pants", "Shoes", "Jackets", "Accessories"],
    "Home": ["Furniture", "Kitchen", "Decor", "Garden", "Lighting"],
    "Sports": ["Fitness", "Outdoor", "Team", "Water", "Winter"],
    "Books": ["Fiction", "Non-Fiction", "Technical", "Children", "Reference"],
    "Food": ["Snacks", "Beverages", "Organic", "Frozen", "Fresh"],
    "Auto": ["Parts", "Accessories", "Tools", "Fluids", "Electronics"],
    "Health": ["Supplements", "Equipment", "Personal Care", "First Aid", "Wellness"],
}
PAYMENT_METHODS = ["credit_card", "debit_card", "paypal", "bank_transfer", "crypto"]
STATUSES = ["completed", "completed", "completed", "shipped", "processing", "cancelled", "refunded"]
EVENT_TYPES = ["page_view", "page_view", "click", "search", "add_to_cart", "checkout", "purchase", "login", "logout"]
DEVICES = ["desktop", "mobile", "tablet"]
SUPPLIERS = [f"Supplier_{chr(65+i)}" for i in range(20)]


def _insert_customers(conn: sqlite3.Connection, n: int) -> None:
    """Insert customer records."""
    print(f"  Inserting {n:,} customers...", end=" ", flush=True)
    t0 = time.time()
    base_date = datetime(2018, 1, 1)

    batch = []
    for i in range(1, n + 1):
        city, state = random.choice(CITIES)
        signup = base_date + timedelta(days=random.randint(0, 2500))
        batch.append((
            i,
            f"Customer_{i}",
            f"user{i}@example.com",
            random.randint(18, 80),
            random.choice(GENDERS),
            city, state, "US",
            random.choice(INCOME_BRACKETS),
            signup.strftime("%Y-%m-%d"),
            1 if random.random() > 0.15 else 0,
        ))
        if len(batch) >= 10000:
            conn.executemany(
                "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch
            )
            batch.clear()

    if batch:
        conn.executemany(
            "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch
        )
    conn.commit()
    print(f"{time.time()-t0:.1f}s")


def _insert_products(conn: sqlite3.Connection, n: int) -> None:
    """Insert product records."""
    print(f"  Inserting {n:,} products...", end=" ", flush=True)
    t0 = time.time()
    base_date = datetime(2019, 1, 1)

    batch = []
    for i in range(1, n + 1):
        cat = random.choice(CATEGORIES)
        subcat = random.choice(SUBCATEGORIES[cat])
        price = round(random.lognormvariate(3.5, 1.2), 2)
        cost = round(price * random.uniform(0.3, 0.8), 2)
        batch.append((
            i,
            f"{cat}_{subcat}_{i}",
            cat, subcat,
            price, cost,
            round(random.uniform(0.1, 50.0), 2),
            random.choice(SUPPLIERS),
            (base_date + timedelta(days=random.randint(0, 2000))).strftime("%Y-%m-%d"),
            1 if random.random() > 0.1 else 0,
        ))
        if len(batch) >= 10000:
            conn.executemany(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", batch
            )
            batch.clear()

    if batch:
        conn.executemany(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", batch
        )
    conn.commit()
    print(f"{time.time()-t0:.1f}s")


def _insert_transactions(conn: sqlite3.Connection, n: int, num_customers: int, num_products: int) -> None:
    """Insert transaction records with skewed distributions."""
    print(f"  Inserting {n:,} transactions...", end=" ", flush=True)
    t0 = time.time()
    base_date = datetime(2020, 1, 1)

    batch = []
    for i in range(1, n + 1):
        # Skewed: some customers buy much more than others (power law)
        cust_id = min(int(random.paretovariate(1.5)), num_customers)
        prod_id = random.randint(1, num_products)
        qty = random.choices([1, 2, 3, 5, 10], weights=[50, 25, 15, 8, 2])[0]
        amount = round(random.lognormvariate(3.0, 1.5), 2)
        discount = round(random.choice([0, 0, 0, 5, 10, 15, 20, 25]) / 100, 2)
        tax = round(amount * qty * 0.08, 2)
        total = round(amount * qty * (1 - discount) + tax, 2)
        created = base_date + timedelta(
            days=random.randint(0, 1800),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        shipped = created + timedelta(days=random.randint(0, 5)) if random.random() > 0.1 else None
        delivered = shipped + timedelta(days=random.randint(1, 10)) if shipped and random.random() > 0.2 else None

        batch.append((
            i, cust_id, prod_id,
            amount, qty, discount, tax, total,
            random.choice(PAYMENT_METHODS),
            random.choice(STATUSES),
            created.strftime("%Y-%m-%d %H:%M:%S"),
            shipped.strftime("%Y-%m-%d %H:%M:%S") if shipped else None,
            delivered.strftime("%Y-%m-%d %H:%M:%S") if delivered else None,
        ))
        if len(batch) >= 10000:
            conn.executemany(
                "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch
            )
            batch.clear()

    if batch:
        conn.executemany(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch
        )
    conn.commit()
    print(f"{time.time()-t0:.1f}s")


def _insert_events(conn: sqlite3.Connection, n: int, num_customers: int) -> None:
    """Insert event log records."""
    print(f"  Inserting {n:,} events...", end=" ", flush=True)
    t0 = time.time()
    base_date = datetime(2020, 1, 1)
    pages = [f"/page/{i}" for i in range(100)]

    batch = []
    for i in range(1, n + 1):
        cust_id = min(int(random.paretovariate(1.5)), num_customers) if random.random() > 0.3 else None
        created = base_date + timedelta(
            days=random.randint(0, 1800),
            seconds=random.randint(0, 86399),
        )
        session = f"sess_{random.randint(1, n // 10)}"

        batch.append((
            i,
            cust_id,
            random.choice(EVENT_TYPES),
            None,  # event_data (keep NULL for most)
            random.choice(pages),
            session,
            random.choice(DEVICES),
            created.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        if len(batch) >= 10000:
            conn.executemany(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", batch
            )
            batch.clear()

    if batch:
        conn.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", batch
        )
    conn.commit()
    print(f"{time.time()-t0:.1f}s")


if __name__ == "__main__":
    path = generate_large_db()
    print(f"\nDatabase ready at: {path}")

    # Quick verification
    conn = sqlite3.connect(path)
    for table in ["customers", "products", "transactions", "events"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,} rows")
    conn.close()
