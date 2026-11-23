"""Race N parallel adds of one alert-event name (same key): exactly one must win, every round."""
import os, requests, urllib3, threading
from collections import Counter
urllib3.disable_warnings()
url = f"{os.getenv('ADDRESS').rstrip('/')}:{os.getenv('PORT')}/jsonrpc"
H = {"Authorization": f"Bearer {os.getenv('API_KEY')}"}
U = "/cli/global/system/alert-event"
def rpc(m, u, d=None):
    p = {"url": u}; 
    if d is not None: p["data"] = d
    return requests.post(url, json={"id": 1, "method": m, "params": [p]}, headers=H, verify=False, timeout=60).json()["result"][0]["status"]["code"]
bad = 0
for rnd in range(10):
    res = []; go = threading.Barrier(12)
    def w(i):
        go.wait(); res.append(rpc("add", U, {"name": "fsrmutex-race", "generic-text": f"w{i}"}))
    ts = [threading.Thread(target=w, args=(i,)) for i in range(12)]
    [t.start() for t in ts]; [t.join() for t in ts]
    c = Counter(res); print(rnd, dict(c)); bad += c[0] != 1
    rpc("delete", f"{U}/fsrmutex-race")
print("rounds with != 1 winner:", bad)
