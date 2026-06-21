import json
import os
import sqlite3
import time
from typing import Dict, Optional, Set

DB_PATH = os.environ.get("CCSTAMP_DB", "ccstamp.db")
RPC_START_HEIGHT = int(os.environ.get("CCSTAMP_START_HEIGHT", "0"))
ISSUER_ADDRESSES: Set[str] = {
    x.strip() for x in os.environ.get("CCSTAMP_ISSUER_ADDRS", "").split(",") if x.strip()
}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rpc_call(method: str, params=None):
    raise NotImplementedError("请在部署环境接入 BTCC RPC")


def _vout_addr(tx: Dict, n: int) -> Optional[str]:
    vout = tx.get("vout") or []
    if len(vout) <= n:
        return None
    return (vout[n].get("scriptPubKey") or {}).get("address")


def _vin_addrs(tx: Dict) -> Set[str]:
    out = set()
    for vin in tx.get("vin") or []:
        spk = ((vin.get("prevout") or {}).get("scriptPubKey") or {})
        addr = spk.get("address")
        if addr:
            out.add(addr)
    return out


def _issuer_tx(tx: Dict) -> bool:
    if not ISSUER_ADDRESSES:
        return True
    return bool(_vin_addrs(tx) & ISSUER_ADDRESSES)


def decode_stamp_tx(tx: Dict) -> Optional[Dict]:
    vout = tx.get("vout") or []
    if len(vout) < 2:
        return None
    spk0 = vout[0].get("scriptPubKey") or {}
    if spk0.get("type") != "nulldata":
        return None
    asm = (spk0.get("asm") or "").split()
    if len(asm) < 2:
        return None
    try:
        data = json.loads(bytes.fromhex(asm[1]).decode("utf-8"))
    except Exception:
        return None
    if data.get("p") != "cc-stamp":
        return None
    if data.get("op") not in ("gen", "xfer"):
        return None
    seed = data.get("s")
    owner = _vout_addr(tx, 1)
    if not seed or not owner:
        return None
    return {"seed": seed, "op": data["op"], "owner_addr": owner, "txid": tx.get("txid")}


def _valid_xfer(conn, seed: str, tx: Dict) -> bool:
    row = conn.execute("SELECT txid, carrier_vout FROM seeds WHERE seed=? AND status='inscribed'", (seed,)).fetchone()
    if not row or not row["txid"]:
        return False
    want_txid = row["txid"]
    want_vout = row["carrier_vout"] if row["carrier_vout"] is not None else 1
    for vin in tx.get("vin") or []:
        if vin.get("txid") == want_txid and int(vin.get("vout", -1)) == int(want_vout):
            return True
    return False


def process_block(height: int):
    block_hash = rpc_call("getblockhash", [height])
    block = rpc_call("getblock", [block_hash, 3])
    if not block:
        return 0
    conn = db()
    changed = 0
    try:
        for tx in block.get("tx", []):
            item = decode_stamp_tx(tx)
            if not item:
                continue
            before = conn.total_changes
            if item["op"] == "gen":
                if not _issuer_tx(tx):
                    continue
                conn.execute(
                    """
                    UPDATE seeds
                       SET owner_addr=?, txid=?, height_at=?, carrier_vout=1, status='inscribed'
                     WHERE seed=? AND status!='inscribed'
                    """,
                    (item["owner_addr"], item["txid"], height, item["seed"]),
                )
            else:
                if not _valid_xfer(conn, item["seed"], tx):
                    continue
                conn.execute(
                    """
                    UPDATE seeds
                       SET owner_addr=?, txid=?, height_at=?, carrier_vout=1
                     WHERE seed=? AND status='inscribed'
                    """,
                    (item["owner_addr"], item["txid"], height, item["seed"]),
                )
            changed += conn.total_changes - before
        conn.commit()
    finally:
        conn.close()
    return changed


def run_forever(start_height: Optional[int] = None):
    height = start_height if start_height is not None else RPC_START_HEIGHT
    while True:
        tip = rpc_call("getblockcount")
        while height <= tip:
            n = process_block(height)
            if n:
                print(f"height={height} updated={n}")
            height += 1
        time.sleep(5)


if __name__ == "__main__":
    run_forever()
