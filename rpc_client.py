import base64
import json
import os
import urllib.request

RPC_URL = os.environ.get("BTCC_RPC_URL", "http://127.0.0.1:28476")
RPC_USER = os.environ.get("BTCC_RPC_USER", "")
RPC_PASSWORD = os.environ.get("BTCC_RPC_PASSWORD", "")


def rpc_call(method, params=None, wallet=None):
    url = RPC_URL.rstrip("/")
    if wallet:
        url = f"{url}/wallet/{wallet}"
    body = json.dumps({"jsonrpc": "2.0", "id": "ccstamp", "method": method, "params": params or []}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    if RPC_USER or RPC_PASSWORD:
        token = base64.b64encode(f"{RPC_USER}:{RPC_PASSWORD}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("result")
