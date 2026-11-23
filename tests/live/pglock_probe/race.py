"""Fire pglock-probe on several HA nodes at the same instant; check they take turns."""
import sys, threading, time, json
from pyfsr.instances import InstanceRegistry
reg = InstanceRegistry.load()
aliases = sys.argv[1].split(",")
mode = sys.argv[2] if len(sys.argv) > 2 else "release"
hold = int(sys.argv[3]) if len(sys.argv) > 3 else 15
clients = {a: reg.configs[a].client(timeout=300) for a in aliases}
go = threading.Barrier(len(aliases)); res = {}
def run(a):
    go.wait()
    try:
        r = clients[a].connectors.execute("pglock-probe", "probe_lock", params={
            "lock_key": 424242, "hold_seconds": hold, "wait_seconds": 120, "mode": mode})
        d = getattr(r, "data", None)
        res[a] = d if isinstance(d, dict) else (r.get("data", r) if isinstance(r, dict) else r)
    except Exception as e:
        res[a] = f"{type(e).__name__}: {e}"
ts = [threading.Thread(target=run, args=(a,)) for a in aliases]
[t.start() for t in ts]; [t.join() for t in ts]
rows = sorted((v for v in res.values() if isinstance(v, dict)), key=lambda d: d["acquired_at"])
for v in res.values():
    if not isinstance(v, dict): print("ERR", v)
for d in rows:
    print(f"{d['node']:28} pg={d['pg_server']:14} waited={d['waited_s']:6}s acquired={d['acquired']} "
          f"held {d['acquired_at']:.1f}->{d['released_at']:.1f}")
overl = any(rows[i+1]["acquired_at"] < rows[i]["released_at"] - 0.05 for i in range(len(rows)-1))
print("OVERLAP (lock not shared!)" if overl else "no overlap: nodes took turns")
