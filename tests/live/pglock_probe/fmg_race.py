"""Same FMG API key, two FortiSOAR HA nodes, two packages, at the same instant.

Before the cluster-wide lock this failed about 1 in 3 (-10147: one node's unlock dropped
the other's lock). Each round: node A adds a policy to pkg default, node B to pkg2,
both through fortinet-fortimanager-json-rpc-locktest (minimal locking, API key). Then
both are deleted. Env: ADDRESS PORT API_KEY (for setup/cleanup straight to FMG).

Usage: python fmg_race.py <pyfsr-alias-node-a> <pyfsr-alias-node-b> [rounds]
"""
import os, sys, threading, time, requests, urllib3
from pyfsr.instances import InstanceRegistry
urllib3.disable_warnings()
N = "fortinet-fortimanager-json-rpc-locktest"
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 6
FMG = f"{os.getenv('ADDRESS').rstrip('/')}:{os.getenv('PORT')}/jsonrpc"
H = {"Authorization": f"Bearer {os.getenv('API_KEY')}"}
def fmg(m, u, d=None):
    p = {"url": u}
    if d is not None: p["data"] = d
    return requests.post(FMG, json={"id": 1, "method": m, "params": [p]}, headers=H, verify=False, timeout=120).json()["result"][0]
reg = InstanceRegistry.load()
nodes = {sys.argv[1]: "default", sys.argv[2]: "lock-test-pkg2"}
clients = {a: reg.configs[a].client(timeout=600) for a in nodes}

print("workspace-mode on:", fmg("set", "/cli/global/system/global", {"workspace-mode": 1})["status"])
fmg("exec", "/dvmdb/adom/root/workspace/lock")
fmg("add", "/pm/pkg/adom/root", {"name": "lock-test-pkg2", "type": "pkg"})
fmg("exec", "/dvmdb/adom/root/workspace/commit"); fmg("exec", "/dvmdb/adom/root/workspace/unlock")
bad = 0
try:
    for rnd in range(ROUNDS):
        go = threading.Barrier(len(nodes)); out = {}
        def run(alias, pkg):
            name = f"hа-lock-{rnd}-{pkg}"[:35].replace("а", "a")
            go.wait(); t = time.time()
            try:
                r = clients[alias].connectors.execute(N, "json_rpc_add", params={
                    "url": f"/pm/config/adom/root/pkg/{pkg}/firewall/policy",
                    "data": {"data": [{"name": name, "srcintf": ["any"], "dstintf": ["any"],
                                       "srcaddr": ["all"], "dstaddr": ["all"], "service": ["ALL"],
                                       "schedule": ["always"], "action": 0, "logtraffic": 0}]}})
                d = getattr(r, "data", r)
                out[alias] = (d.get("status"), round(time.time() - t, 1), d.get("add_response"))
            except Exception as e:
                out[alias] = (f"{type(e).__name__}", round(time.time() - t, 1), str(e)[:200])
        ts = [threading.Thread(target=run, args=kv) for kv in nodes.items()]
        [t.start() for t in ts]; [t.join() for t in ts]
        ok = all(v[0] == 0 for v in out.values())
        bad += not ok
        print(f"round {rnd}: " + "  ".join(f"{a.split('-')[-1]}={v[0]} ({v[1]}s)" for a, v in out.items())
              + ("" if ok else f"  FAIL {out}"))
        locks = fmg("get", "/dvmdb/adom/root/workspace/lockinfo").get("data")
        if locks: print("  locks left:", locks)
finally:
    fmg("exec", "/dvmdb/adom/root/workspace/lock")
    for pkg in nodes.values():
        pol = fmg("get", f"/pm/config/adom/root/pkg/{pkg}/firewall/policy", {"fields": ["policyid", "name"]} and None).get("data") or []
        for p in pol:
            if str(p.get("name", "")).startswith("ha-lock-"):
                fmg("delete", f"/pm/config/adom/root/pkg/{pkg}/firewall/policy/{p['policyid']}")
    fmg("delete", "/pm/pkg/adom/root/lock-test-pkg2")
    fmg("exec", "/dvmdb/adom/root/workspace/commit"); fmg("exec", "/dvmdb/adom/root/workspace/unlock")
    print("workspace-mode off:", fmg("set", "/cli/global/system/global", {"workspace-mode": 0})["status"])
print(f"{bad}/{ROUNDS} rounds failed")
