import os
import socket
import time

from connectors.core.connector import Connector, ConnectorError, get_logger

logger = get_logger('pglock-probe')


def _probe_lock(params):
    from django.db import connection
    key = int(params.get("lock_key") or 424242)
    hold = float(params.get("hold_seconds") or 20)
    wait = float(params.get("wait_seconds") or 60)
    mode = params.get("mode") or "release"
    from django.conf import settings
    out = {"node": socket.gethostname(), "pid": os.getpid(), "mode": mode,
           "conn_max_age": settings.DATABASES.get("default", {}).get("CONN_MAX_AGE"),
           "db_aliases": list(settings.DATABASES), "autocommit": connection.get_autocommit(),
           "in_atomic": connection.in_atomic_block}
    with connection.cursor() as cur:
        cur.execute("select inet_server_addr()::text, current_database(), pg_is_in_recovery(), "
                    "pg_backend_pid(), current_user")
        (out["pg_server"], out["database"], out["pg_in_recovery"],
         out["backend_pid"], out["db_user"]) = cur.fetchone()
        start = time.time()
        acquired = False
        while time.time() - start < wait:
            cur.execute("select pg_try_advisory_lock(%s)", [key])
            if cur.fetchone()[0]:
                acquired = True
                break
            time.sleep(0.25)
        out["acquired"] = acquired
        out["waited_s"] = round(time.time() - start, 2)
        out["acquired_at"] = time.time()
        cur.execute("select count(*) from pg_locks where locktype='advisory' and objid=%s", [key])
        out["advisory_holders_before"] = cur.fetchone()[0]
        if acquired:
            time.sleep(hold)
            if mode == "abandon":
                out["released"] = "connection closed without unlock"
            elif mode == "leak":
                out["released"] = "left held on the pooled connection"
            else:
                cur.execute("select pg_advisory_unlock(%s)", [key])
                out["released"] = cur.fetchone()[0]
        out["released_at"] = time.time()
    if mode == "abandon":
        connection.close()
    return out


class PgLockProbe(Connector):
    def execute(self, config, operation, params, **kwargs):
        try:
            if operation == "probe_lock":
                return _probe_lock(params)
            raise ConnectorError(f"unknown operation {operation}")
        except ConnectorError:
            raise
        except Exception as e:
            logger.exception("probe failed")
            raise ConnectorError(f"{type(e).__name__}: {e}")

    def check_health(self, config):
        return True
