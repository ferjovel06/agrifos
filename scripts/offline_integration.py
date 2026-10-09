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
        fixture_path.write_text(json.dumps({"base_url":f"http://{args.client_host}:{port}",
            "user":str(fixture.user), "token":fixture.token(fixture.user, fixture.email),
            "farm":fixture.farm, "parcel":fixture.parcel, "lab_payload":fixture.operation("lab_analyses")["payload"]}), encoding="utf-8")
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("Loopback fixture HTTP server did not start.")
        command = [args.flutter, "test", "test/integration/offline_http_test.dart",
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
                value = (await db.execute(text("SELECT nitrogen FROM lab_analyses WHERE id=CAST(:id AS uuid)"), {"id":result["lab"]})).scalar()
                assert records == receipts == 1, (records, receipts)
                assert value == 77, value
                return {"status":"PASS", "reading_records":records,"operation_receipts":receipts,
                        "remote_lab_nitrogen":value,"lost_response_replayed":True,"sqlite_reopened":True,
                        "real_http":True,"real_postgresql":True,"jwt_es256":True,"conflict_review":True}
        evidence = asyncio.run(verify())
        target = ROOT / "tmp/offline/real-integration.json"
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
