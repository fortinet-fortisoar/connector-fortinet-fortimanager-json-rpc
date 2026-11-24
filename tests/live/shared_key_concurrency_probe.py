"""N parallel JSON-RPC reads with one API key vs N password sessions: any 503s?"""
import os, sys, requests, urllib3, threading
from collections import Counter
urllib3.disable_warnings()
url = f"{os.getenv('ADDRESS').rstrip('/')}:{os.getenv('PORT')}/jsonrpc"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6

def call(headers, session=None):
    body = {"id": 1, "method": "get", "params": [{"url": "/pm/config/adom/root/obj/firewall/address"}]}
    if session: body["session"] = session
    return requests.post(url, json=body, headers=headers, verify=False, timeout=60).status_code

def run(label, make):
    codes = Counter(); ts = []
    for _ in range(3):
        for _ in range(N):
            h, s = make()
            t = threading.Thread(target=lambda h=h, s=s: codes.update([call(h, s)])); ts.append(t); t.start()
        for t in ts: t.join()
    print(label, dict(codes))

key = {"Authorization": f"Bearer {os.getenv('API_KEY')}"}
run("API key  ", lambda: (key, None))
def pw():
    r = requests.post(url, json={"id": 1, "method": "exec", "params": [{"url": "/sys/login/user", "data": {
        "user": os.getenv("USERNAME"), "passwd": os.getenv("PASSWORD")}}]}, verify=False).json()
    return {}, r["session"]
run("password ", pw)
