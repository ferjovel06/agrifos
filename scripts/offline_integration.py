"""Run the real SQLite -> HTTP FastAPI -> PostgreSQL acceptance path.

Requires OFFLINE_TEST_DATABASE_URL: a loopback agrifos_offline_* fixture DB.
Never resets data. Each run creates fresh UUIDs. Test credentials stay in ignored
.dart_tool files and are not part of the evidence output.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker-tool-container")
    parser.add_argument("--client-host", default="127.0.0.1")
    parser.add_argument("--flutter", default="flutter")
    parser.add_argument("--sensor", action="store_true", help="Test synthetic raw provenance over real SQLite/HTTP/PostgreSQL")
    args = parser.parse_args()
    if not os.environ.get("OFFLINE_TEST_DATABASE_URL"):
        raise SystemExit("NOT RUN: supply a disposable, loopback agrifos_offline_* database URL.")
    # Configure before importing the application or its integration fixture.
    os.environ.setdefault("DATABASE_URL", os.environ["OFFLINE_TEST_DATABASE_URL"])
    os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:59998")
    import uvicorn
    from sqlalchemy import text
    from tests.test_offline_postgres import OfflinePostgresTests
    from app.main import app
    fixture = OfflinePostgresTests(methodName="test_lost_response_and_concurrent_delivery_create_exactly_one_record")
    OfflinePostgresTests.setUpClass()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    fixture_path = ROOT / "app_flutter/.dart_tool/offline-fixture.json"
    result_path = ROOT / "app_flutter/.dart_tool/offline-result.json"
    try:
        fixture.setUp()
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        config = {"base_url":f"http://{args.client_host}:{port}",
            "user":str(fixture.user), "token":fixture.token(fixture.user, fixture.email),
            "farm":fixture.farm, "parcel":fixture.parcel, "lab_payload":fixture.operation("lab_analyses")["payload"]}
        if args.sensor:
            from datetime import UTC, datetime, timedelta
            import uuid
            acquired = (datetime.now(UTC) - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
            config["reading_payload"] = {"nitrogen":20, "recorded_at":acquired,
                "measurement":{"contract_version":1,"session_id":str(uuid.uuid4()),
                    "device_id":"synthetic-integration-device","sensor_model":"synthetic-fixture-not-hardware",
                    "protocol_version":"synthetic-test-v1","profile_id":"synthetic-integration-profile",
                    "acquired_at":acquired,"point_id":"fixture-independent-point",
                    "variables":{"nitrogen":{"raw_value":20,"unit":"mg/kg","analyte":"N","read_status":"valid"}}}}
        fixture_path.write_text(json.dumps(config), encoding="utf-8")
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("Loopback fixture HTTP server did not start.")
        command = [args.flutter, "test", "--no-pub", "test/integration/offline_http_test.dart",
                   "--dart-define=OFFLINE_FIXTURE_PATH=.dart_tool/offline-fixture.json"]
        if args.docker_tool_container:
            command = ["docker", "exec", args.docker_tool_container, *command]
        child = subprocess.run(command, cwd=ROOT / "app_flutter", check=False)
        if child.returncode:
            raise SystemExit(child.returncode)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        async def verify():
            async with fixture.sessions() as db:
                records = (await db.execute(text("SELECT count(*) FROM readings WHERE id=CAST(:id AS uuid)"), {"id":result["reading"]})).scalar()
                receipts = (await db.execute(text("SELECT count(*) FROM sync_receipts WHERE user_id=CAST(:user AS uuid) AND operation_id=CAST(:id AS uuid)"), {"user":str(fixture.user),"id":result["operation"]})).scalar()
                lab_records = (await db.execute(text("SELECT count(*) FROM lab_analyses WHERE id=CAST(:id AS uuid)"), {"id":result["lab"]})).scalar()
                value = (await db.execute(text("SELECT nitrogen FROM lab_analyses WHERE id=CAST(:id AS uuid)"), {"id":result["lab"]})).scalar()
                assert records == receipts == 1, (records, receipts)
                assert value == 77, value
                assert lab_records == 1
                assert result["initial_queued_operations"] == 2
                evidence = {"status":"PASS", "reading_records":records,"operation_receipts":receipts,
                        "lab_records":lab_records,"initial_queued_operations":2,
                        "remote_lab_nitrogen":value,"lost_response_replayed":True,"sqlite_reopened":True,
                        "real_http":True,"real_postgresql":True,"jwt_es256":True,"conflict_review":True}
                if args.sensor:
                    row = (await db.execute(text("SELECT measurement,recorded_at,received_at,phosphorus,humidity FROM readings WHERE id=CAST(:id AS uuid)"), {"id":result["reading"]})).one()
                    def preserves(actual, original):
                        if isinstance(original,dict):
                            return isinstance(actual,dict) and all(key in actual and preserves(actual[key],value) for key,value in original.items())
                        return actual == original
                    assert preserves(row.measurement,config["reading_payload"]["measurement"]), row.measurement
                    assert row.recorded_at == datetime.fromisoformat(config["reading_payload"]["recorded_at"])
                    assert row.received_at > row.recorded_at
                    assert row.phosphorus is None and row.humidity is None
                    derived = (await db.execute(text("SELECT payload FROM reading_results WHERE reading_id=CAST(:id AS uuid)"), {"id":result["reading"]})).scalars().all()
                    assert len(derived) == 1, len(derived)
                    assert derived[0]["variables"]["nitrogen"]["raw"]["value"] == 20
                    assert derived[0]["variables"]["nitrogen"]["accuracy_state"] == "uncalibrated"
                    assert result["deferred_processing_returned"] is True
                    evidence.update(raw_provenance_preserved=True, acquisition_time_preserved=True,
                                    unmeasured_variables_absent=True, derived_result_records=len(derived),
                                    deferred_processing_returned=True, processing_replay_idempotent=True,
                                    physical_usb="NOT RUN")
                return evidence
        evidence = asyncio.run(verify())
        target = ROOT / ("tmp/sensor/real-integration.json" if args.sensor else "tmp/offline/real-integration.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence))
    finally:
        # Only ephemeral test-token file created by this invocation is removed.
        fixture_path.unlink(missing_ok=True)
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=10)
        sock.close()
        OfflinePostgresTests.tearDownClass()


if __name__ == "__main__":
    main()
