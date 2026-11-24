"""Do two workers sharing one FMG API key share workspace-lock ownership?

Raw JSON-RPC (no connector) so the result is about the appliance, not our code.
Arms, each on ADOM <adom> with workspace mode on:

  PASSWORD  two password sessions: second lock must be refused (control)
  KEY       two "workers" with the same API key: is the second lock refused?
  UNLOCK    worker B (same key) unlocks: does worker A's lock disappear?
  ORPHAN    worker A locks and walks away: is the lock still held later?

Usage (env: ADDRESS PORT USERNAME PASSWORD API_KEY):
    python shared_api_key_lock_probe.py [--adom root]
"""
import argparse, os, time, requests, urllib3
urllib3.disable_warnings()

def main():
    p = argparse.ArgumentParser(); p.add_argument("--adom", default="root"); a = p.parse_args()
    url = f"{os.getenv('ADDRESS').rstrip('/')}:{os.getenv('PORT')}/jsonrpc"
    adom = a.adom

    class W:
        def __init__(s, key=None):
            s.h = {"Authorization": f"Bearer {key}"} if key else {}
            s.sess = None
            if not key:
                r = s.rpc("exec", "/sys/login/user",
                          {"user": os.getenv("USERNAME"), "passwd": os.getenv("PASSWORD")}, raw=True)
                s.sess = r["session"]
        def rpc(s, method, u, data=None, raw=False):
            body = {"id": 1, "method": method, "params": [dict({"url": u}, **({"data": data} if data else {}))]}
            if s.sess: body["session"] = s.sess
            r = requests.post(url, json=body, headers=s.h, verify=False, timeout=60).json()
            return r if raw else (r["result"][0]["status"]["code"], r["result"][0].get("data"))
        def lock(s): return s.rpc("exec", f"/dvmdb/adom/{adom}/workspace/lock")[0]
        def unlock(s): return s.rpc("exec", f"/dvmdb/adom/{adom}/workspace/unlock")[0]
        def logout(s):
            if s.sess: s.rpc("exec", "/sys/logout")

    def info(w):
        d = w.rpc("get", f"/dvmdb/adom/{adom}/workspace/lockinfo")[1]
        return d if isinstance(d, list) else []

    admin = W()
    print("workspace-mode ->", admin.rpc("set", "/cli/global/system/global", {"workspace-mode": 1})[0])
    key = os.getenv("API_KEY")
    try:
        p1, p2 = W(), W()
        print(f"[PASSWORD] A lock={p1.lock()} B lock={p2.lock()} (expect B != 0)")
        print("  lockinfo:", info(admin)); p1.unlock(); p1.logout(); p2.logout()

        k1, k2 = W(key), W(key)
        print(f"[KEY] A lock={k1.lock()} B lock={k2.lock()}")
        print("  lockinfo:", info(admin))
        print(f"[UNLOCK] B unlock={k2.unlock()} lockinfo after:", info(admin))
        k1.unlock()

        print(f"[ORPHAN] A lock={k1.lock()}; waiting 90s with no unlock")
        time.sleep(90)
        print("  lockinfo after 90s:", info(admin))
        print(f"  fresh password session lock={W().lock()} (non-zero = orphan still blocks)")
    finally:
        W(key).unlock()
        print("final lockinfo:", info(admin))
        print("workspace-mode off ->", admin.rpc("set", "/cli/global/system/global", {"workspace-mode": 0})[0])
        admin.logout()

if __name__ == "__main__":
    main()
