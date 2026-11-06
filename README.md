# F1 Pit Stop Optimizer & Race Analytics Platform

An academic and engineering Database Management Systems (DBMS) platform built on **PostgreSQL**, **FastAPI**, **SQLAlchemy**, and **vanilla HTML5/CSS/JavaScript with Chart.js**, powered by official historical Formula 1 telemetry via **FastF1** and **OpenF1**.

---

## 🏁 Key Features

### 1. Pit Stop Strategy Decision Support System (DSS)
- **Recursive CTE Planning:** Computes optimal 1-stop, 2-stop, and 3-stop strategies within PostgreSQL.
- **Empirical vs. Theoretical Comparison:** Evaluates mathematical wear models against measured historical pit stop loss and tyre degradation curves.
- **Plain-English Explanations:** Stint-by-stint breakdowns and tactical explanations of why the winning strategy succeeds and why alternatives fail.
- **Safety Car Scenario Sensitivity:** Quantifies pit delta advantages under Virtual Safety Car (VSC) and full Safety Car (SC) conditions.

### 2. Historical F1 Data Ingestion Pipeline
- **Dual Telemetry Source:** Direct OpenF1 REST API integration with FastF1 Python SDK fallback.
- **Local Disk Caching:** Telemetry cached in `.fastf1_cache/` to eliminate redundant network overhead.
- **Idempotent Bulk UPSERT:** PostgreSQL `ON CONFLICT DO UPDATE` guarantees duplicate-free re-runs.
- **Session Tracking:** Automated job logging in the `ingestion_jobs` metadata table.
- **CLI & REST API Support:** Import via `python -m app.data_ingestion.cli --season 2024 --round 1` or directly from the frontend UI.

### 3. Interactive Race Analytics & Telemetry Dashboard
- **Lap-by-Lap Pace Progression:** High-resolution timing line charts comparing two drivers head-to-head.
- **Pace Delta Bar Chart:** Quantifies lap-by-lap advantage and gap evolution in seconds.
- **Tyre Degradation Scatter & Regression:** Empirical lap time vs. tyre age (laps on set) curves for SOFT, MEDIUM, and HARD compounds.
- **Driver Stints & Pit Stops:** Detailed breakdown of tyre stints, lap ranges, stationary times, and crew efficiency.

### 4. Multi-Season Championship Standings (Materialized View)
- Accurately tracks verified historical and active championship standings:
  - **2024 Champion:** Max Verstappen (437 pts)
  - **2025 Champion:** Lando Norris (423 pts)
  - **2026 World Champion:** Kimi Antonelli (380 pts, clinched in Mexico City)
- Precomputed via indexed `mv_driver_championship` with on-demand zero-downtime refresh.

### 5. Curated Academic DBMS Showcase
- **20 Syllabus Queries:** Inner joins, outer joins, aggregations with HAVING, nested scalar subqueries, correlated subqueries, set operations (INTERSECT/EXCEPT), relational division (double NOT EXISTS), and window functions.
- **EXPLAIN ANALYZE Visualizer:** Interactive inspection of query plans, buffer reads, and index scans.
- **Stored Procedures & ACID Transactions:** Live execution of `sp_apply_safety_car` with row-level locks.
- **Change Data Capture (CDC):** Row-level audit triggers logging old and new states in `JSONB`.
- **Row-Level Security (RLS):** Team-isolated multi-tenancy.
- **Horizontal Table Partitioning:** Declarative range partitioning of `lap_telemetry` by `race_id`.

---

## 🛠️ Tech Stack

- **Database:** PostgreSQL 14+ (PL/pgSQL, Recursive CTEs, Deferred Triggers, Partitioning, Materialized Views, RLS)
- **Backend API:** Python 3.10+, FastAPI, SQLAlchemy, Pydantic, Uvicorn
- **Data Ingestion:** FastF1 (v3.9+), OpenF1 API, Requests-Cache, Pandas
- **Frontend:** Vanilla HTML5, Modern Dark CSS, Vanilla ES6+ JavaScript, Chart.js

---

## 🚀 Quickstart Guide

### 1. Clone & Set Up Environment

```bash
git clone https://github.com/Mathi-25/F1-Pitstop-Optimizer.git
cd F1-Pitstop-Optimizer

# Create and activate Python virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/WSL/macOS:
source venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

### 2. Configure Database Environment

Create a `.env` file in the root directory:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/f1_pitstop
POSTGRES_DB=f1_pitstop
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### 3. Initialize PostgreSQL Schema & Seed Data

In PostgreSQL or via command line:

```bash
# 1. Create database
psql -U postgres -c "CREATE DATABASE f1_pitstop;"

# 2. Run initial schema, functions, and seed data
psql -U postgres -d f1_pitstop -f db/schema.sql
psql -U postgres -d f1_pitstop -f db/functions.sql
psql -U postgres -d f1_pitstop -f db/seed.sql

# 3. Apply the FastF1 Analytics Upgrade Migration
psql -U postgres -d f1_pitstop -f db/migrations/001_fastf1_analytics_upgrade.sql
```

### 4. Start the Application

```bash
uvicorn app.main:app --reload --port 8000
```

Open your browser at:
- **Interactive Engineering Dashboard:** [http://localhost:8000/ui](http://localhost:8000/ui)
- **FastAPI OpenAPI Interactive Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📥 Ingesting Real Historical F1 Data

You can import real Grand Prix timing and stint telemetry using the CLI:

```bash
# Import a specific round (e.g. 2024 Round 1 - Bahrain Grand Prix)
python -m app.data_ingestion.cli --season 2024 --round 1

# Import an entire season (with optional limit)
python -m app.data_ingestion.cli --season 2024 --max-rounds 5

# Enable verbose debug logging
python -m app.data_ingestion.cli --season 2024 --round 1 --verbose
```

Or trigger imports interactively from the **Data Ingestion Hub** tab in the web UI.

---

## 📂 Project Directory Structure

```
F1-Pitstop-Optimizer/
├── app/
│   ├── main.py                  # FastAPI application and REST endpoints
│   ├── database.py              # SQLAlchemy engine and connection manager
│   ├── strategy.py              # Pit stop optimizer and empirical metrics
│   ├── data_ingestion/          # Modular historical ingestion pipeline
│   │   ├── __init__.py
│   │   ├── fastf1_client.py     # OpenF1 and FastF1 client with disk cache
│   │   ├── cleaner.py           # Timing and driver normalization
│   │   ├── importer.py          # Idempotent PostgreSQL bulk upsert
│   │   └── cli.py               # Command-line ingestion interface
│   └── static/
│       └── index.html           # Single-page dashboard with Chart.js
├── db/
│   ├── schema.sql               # Base DDL and table definitions (15 tables)
│   ├── functions.sql            # Recursive CTEs, triggers, and procedures
│   ├── seed.sql                 # Multi-season calibration seed data
│   ├── queries.sql              # 20 Academic syllabus SQL queries
│   ├── security.sql             # RBAC roles and Row-Level Security
│   ├── concurrency_and_acid.sql # Transaction isolation demonstrations
│   ├── performance_benchmarks.sql # EXPLAIN ANALYZE benchmark tests
│   └── migrations/
│       └── 001_fastf1_analytics_upgrade.sql # Schema upgrade migration
├── docs/
│   └── DBMS_ACADEMIC_REPORT.md  # Comprehensive academic report and viva guide
├── requirements.txt             # Python dependencies (FastAPI, FastF1, etc.)
└── README.md                    # Project documentation
```

---

## 🎓 Academic DBMS Reference

| Concept | File / Implementation | Description |
| :--- | :--- | :--- |
| **Recursive CTE** | `db/functions.sql` (`plan_strategies`) | Dynamic graph generation of stint permutations |
| **Materialized View** | `db/schema.sql` (`mv_driver_championship`) | Cached multi-season driver standings |
| **Deferred Triggers** | `db/functions.sql` (`check_plan_laps`) | Assertion substitute for multi-row validation |
| **Table Partitioning** | `db/schema.sql` (`lap_telemetry`) | Range partitioning by `race_id` with default partition |
| **Row-Level Security** | `db/security.sql` (`p_team_isolation`) | Multi-tenant cryptographic team isolation |
| **Stored Procedures** | `db/functions.sql` (`sp_apply_safety_car`) | In-race recalibration within ACID transactions |
| **Change Data Capture** | `db/functions.sql` (`log_strategy_changes`) | Row-level JSONB audit trail |
| **Index Types** | `db/schema.sql`, `db/migrations/` | B-Tree, Partial, Functional/Expression, and Composite indexes |

---

## 📄 License

Academic Educational Project — Designed for Database Management Systems Coursework & Research.

