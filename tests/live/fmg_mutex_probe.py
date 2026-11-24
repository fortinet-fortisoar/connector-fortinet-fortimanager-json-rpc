"""Can an FMG global table act as a cluster-wide mutex? add twice -> second must fail."""
import os, requests, urllib3, json
urllib3.disable_warnings()
url = f"{os.getenv('ADDRESS').rstrip('/')}:{os.getenv('PORT')}/jsonrpc"
H = {"Authorization": f"Bearer {os.getenv('API_KEY')}"}
def rpc(m, u, d=None):
    p = {"url": u}
    if d is not None: p["data"] = d
    r = requests.post(url, json={"id": 1, "method": m, "params": [p]}, headers=H, verify=False, timeout=30).json()
    return r["result"][0]["status"], r["result"][0].get("data")
cands = {
 "/cli/global/system/admin/group": {"name": "fsrmutex-probe"},
 "/cli/global/system/meta": {"name": "fsrmutex-probe"},
 "/cli/global/system/alert-event": {"name": "fsrmutex-probe"},
 "/cli/global/system/sql/custom-index": None,
}
for u, d in cands.items():
    if d is None: continue
    a = rpc("add", u, d); b = rpc("add", u, d); g = rpc("get", f"{u}/fsrmutex-probe"); x = rpc("delete", f"{u}/fsrmutex-probe")
    print(u, "\n  add1", a[0], "\n  add2", b[0], "\n  get", g[0]["code"], json.dumps(g[1])[:200], "\n  del", x[0])
