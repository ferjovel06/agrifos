"""Bounded checks of real Supabase Auth infrastructure before Alembic."""
import os
import subprocess
import time

import psycopg2


def main():
    database_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    deadline = time.monotonic() + 180
    while True:
        try:
            with psycopg2.connect(database_url, connect_timeout=5) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT to_regclass('auth.users'), to_regclass('auth.mfa_factors')")
                    if all(cursor.fetchone()):
                        break
        except psycopg2.Error:
            pass  # Never include connection credentials in diagnostic output.
        if time.monotonic() >= deadline:
            raise SystemExit("FAIL: Supabase Auth schema was not ready within 180 seconds.")
        time.sleep(2)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    subprocess.run(["alembic", "current"], check=True)


if __name__ == "__main__":
    main()
