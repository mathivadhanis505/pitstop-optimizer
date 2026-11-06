import sys
import os
from pathlib import Path

# Add project directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient
from app.main import app
from app.database import engine
from sqlalchemy import text

client = TestClient(app)

def run_system_audit():
    print("=" * 70)
    print("  F1 PITSTOP OPTIMIZER — FULL SYSTEM & DATA INTEGRITY AUDIT")
    print("=" * 70)

    passed = 0
    failed = 0

    def assert_test(name, condition, extra=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {name} {extra}")
        else:
            failed += 1
            print(f"  [FAIL] {name} {extra}")

    # 1. Database Row Counts
    print("\n--- 1. Database Row Counts ---")
    with engine.connect() as conn:
        counts = {
            "races": conn.execute(text("SELECT count(*) FROM races")).scalar(),
            "tracks": conn.execute(text("SELECT count(*) FROM tracks")).scalar(),
            "drivers": conn.execute(text("SELECT count(*) FROM drivers")).scalar(),
            "teams": conn.execute(text("SELECT count(*) FROM teams")).scalar(),
            "results": conn.execute(text("SELECT count(*) FROM results")).scalar(),
            "stints": conn.execute(text("SELECT count(*) FROM stints")).scalar(),
            "pit_stops": conn.execute(text("SELECT count(*) FROM pit_stops")).scalar(),
            "lap_telemetry": conn.execute(text("SELECT count(*) FROM lap_telemetry")).scalar(),
            "mv_driver_championship": conn.execute(text("SELECT count(*) FROM mv_driver_championship")).scalar(),
        }
        for table, cnt in counts.items():
            print(f"    - {table:25s}: {cnt:7d} rows")

        assert_test("lap_telemetry rows > 10,000", counts["lap_telemetry"] > 10000, f"({counts['lap_telemetry']} rows)")
        assert_test("stints rows > 500", counts["stints"] > 500, f"({counts['stints']} rows)")
        assert_test("pit_stops rows > 300", counts["pit_stops"] > 300, f"({counts['pit_stops']} rows)")
        assert_test("mv_driver_championship populated", counts["mv_driver_championship"] > 0, f"({counts['mv_driver_championship']} rows)")

    # 2. Calendar & Session Mapping Audit (2024 Miami, 2026 Miami, 2026 Monaco)
    print("\n--- 2. Calendar & Session Mapping Audit ---")
    res = client.get("/analytics/races?season=2024")
    assert_test("2024 calendar API 200 OK", res.status_code == 200)
    races_2024 = {r["round_no"]: r for r in res.json()}

    # Check 2024 Miami (Round 6)
    m24 = races_2024.get(6)
    assert_test("2024 Round 6 is Miami", m24 and "Miami" in m24["track_name"], f"({m24['track_name'] if m24 else 'None'})")
    assert_test("2024 Miami has > 1,000 laps", m24 and m24["lap_count"] > 1000, f"({m24['lap_count'] if m24 else 0} laps)")
    assert_test("2024 Miami has pit stops", m24 and m24["pit_count"] > 20, f"({m24['pit_count'] if m24 else 0} stops)")

    # Check 2026 Miami (Round 6) & Monaco (Round 8)
    res_26 = client.get("/analytics/races?season=2026")
    assert_test("2026 calendar API 200 OK", res_26.status_code == 200)
    races_2026 = {r["round_no"]: r for r in res_26.json()}
    m26 = races_2026.get(6)
    mon26 = races_2026.get(8)
    assert_test("2026 Round 6 is Miami", m26 and "Miami" in m26["track_name"], f"({m26['track_name'] if m26 else 'None'})")
    assert_test("2026 Miami has 0 laps (Future session)", m26 and m26["lap_count"] == 0, f"({m26['lap_count'] if m26 else -1} laps)")
    assert_test("2026 Round 8 is Monaco", mon26 and "Monaco" in mon26["track_name"], f"({mon26['track_name'] if mon26 else 'None'})")
    assert_test("2026 Monaco has 0 laps (Future session)", mon26 and mon26["lap_count"] == 0, f"({mon26['lap_count'] if mon26 else -1} laps)")

    # 3. Authoritative Championship Standings Verification
    print("\n--- 3. Authoritative Championship Standings Audit ---")
    for year, expected_champ, expected_pts in [
        (2026, "Kimi Antonelli", 380),
        (2025, "Lando Norris", 423),
        (2024, "Max Verstappen", 437)
    ]:
        res_champ = client.get(f"/academic/championship?season={year}")
        assert_test(f"{year} standings API 200 OK", res_champ.status_code == 200)
        standings = res_champ.json()
        assert_test(f"{year} standings not empty", len(standings) > 0, f"({len(standings)} drivers)")
        if standings:
            p1 = standings[0]
            assert_test(
                f"{year} Champion is {expected_champ} ({expected_pts} pts)",
                p1["full_name"] == expected_champ and p1["total_points"] == expected_pts,
                f"(Actual: {p1['full_name']} with {p1['total_points']} pts, Rank {p1['championship_rank']})"
            )
            ranks = [s["championship_rank"] for s in standings]
            assert_test(f"{year} Ranks are unique 1..N (No duplicates)", len(ranks) == len(set(ranks)), f"(Unique ranks: {len(set(ranks))}/{len(ranks)})")

    # 4. Telemetry Endpoints Audit for Miami (race_id = 7)
    print("\n--- 4. Telemetry Endpoints Audit (2024 Miami) ---")
    miami_race_id = m24["race_id"]
    res_drivers = client.get(f"/analytics/drivers?race_id={miami_race_id}")
    assert_test("Miami drivers endpoint 200 OK", res_drivers.status_code == 200)
    drivers = res_drivers.json()
    assert_test("Miami has >= 18 drivers", len(drivers) >= 18, f"({len(drivers)} drivers)")

    res_comp = client.get(f"/analytics/driver-comparison?race_id={miami_race_id}&driver1=VER&driver2=NOR")
    assert_test("Miami VER vs NOR pace comparison 200 OK", res_comp.status_code == 200)
    comp_laps = res_comp.json()
    assert_test("Miami VER vs NOR laps > 40", len(comp_laps) > 40, f"({len(comp_laps)} comparison laps)")

    res_tyres = client.get(f"/analytics/tyre-degradation?race_id={miami_race_id}")
    assert_test("Miami tyre degradation endpoint 200 OK", res_tyres.status_code == 200)
    tyres_data = res_tyres.json()
    assert_test("Miami tyre degradation records > 0", len(tyres_data) > 0, f"({len(tyres_data)} degradation data points)")

    res_stints = client.get(f"/analytics/stints?race_id={miami_race_id}")
    assert_test("Miami stints endpoint 200 OK", res_stints.status_code == 200)
    stints_data = res_stints.json()
    assert_test("Miami stints > 20", len(stints_data) > 20, f"({len(stints_data)} stints)")

    res_pits = client.get(f"/analytics/pit-stops?race_id={miami_race_id}")
    assert_test("Miami pit stops endpoint 200 OK", res_pits.status_code == 200)
    pits_data = res_pits.json()
    assert_test("Miami pit stops > 20", len(pits_data) > 20, f"({len(pits_data)} pit stops)")

    # 5. Stored Procedure & Safety Car Audit
    print("\n--- 5. Stored Procedure & ACID Safety Car Audit ---")
    res_proc = client.post("/academic/safety-car-procedure?plan_id=1&discount_pct=50.0")
    assert_test("sp_apply_safety_car endpoint 200 OK", res_proc.status_code == 200)
    proc_data = res_proc.json()
    assert_test("Safety car time saved is positive (>0)", proc_data.get("time_saved_s", 0) > 0, f"(Saved: {proc_data.get('time_saved_s')}s)")
    assert_test("Safety car new delta is strictly less than old delta", proc_data.get("new_delta_s", 0) < proc_data.get("old_delta_s", 0), f"({proc_data.get('old_delta_s')}s -> {proc_data.get('new_delta_s')}s)")

    # 6. All 20 Academic SQL Queries Execution Audit
    print("\n--- 6. All 20 Academic SQL Queries Execution Audit ---")
    res_queries = client.get("/academic/queries")
    assert_test("Academic queries list 200 OK", res_queries.status_code == 200)
    queries = res_queries.json()
    assert_test("Catalogue contains 20 academic queries", len(queries) == 20, f"({len(queries)} queries)")

    for q in queries:
        qid = q["id"]
        title = q["title"]
        res_q = client.post(f"/academic/query/{qid}/run")
        if res_q.status_code == 200:
            qdata = res_q.json()
            assert_test(f"Query {qid:2d}: {title[:35]:35s}", True, f"({qdata['row_count']} rows in {qdata['execution_time_ms']} ms)")
        else:
            assert_test(f"Query {qid:2d}: {title[:35]:35s}", False, f"(Status {res_q.status_code}: {res_q.text[:60]})")

    # 7. Audit Log & Trigger Simulation
    print("\n--- 7. CDC Audit Log & Trigger Simulation Audit ---")
    res_sim = client.post("/academic/audit/simulate", json={"action": "INSERT"})
    assert_test("CDC INSERT simulation 200 OK", res_sim.status_code == 200)
    res_audit = client.get("/academic/audit-log")
    assert_test("Audit log retrieve 200 OK", res_audit.status_code == 200)
    logs = res_audit.json()
    assert_test("Audit log contains records", len(logs) > 0, f"({len(logs)} audit entries)")

    # Summary
    print("\n" + "=" * 70)
    print(f"  SYSTEM AUDIT COMPLETED: {passed} PASSED, {failed} FAILED (TOTAL {passed + failed})")
    print("=" * 70 + "\n")
    return failed == 0

if __name__ == "__main__":
    success = run_system_audit()
    sys.exit(0 if success else 1)

