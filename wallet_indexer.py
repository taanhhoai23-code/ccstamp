import json

import os

import sqlite3

import time

from typing import Dict, Iterable, Optional

DB_PATH = os.environ.get("CCSTAMP_DB", "ccstamp.db")

RPC_START_HEIGHT = int(os.environ.get("CCSTAMP_START_HEIGHT", "0"))

def db():

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn

def rpc_call(method: str, params=None):

    raise NotImplementedError("请在生产环境接入 BTCC RPC")

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

        payload = bytes.fromhex(asm[1]).decode("utf-8")

        data = json.loads(payload)

    except Exception:

        return None

    if data.get("p") != "cc-stamp":

        return None

    if data.get("op") not in ("gen", "xfer"):

        return None

    if not data.get("s"):

        return None

    owner = (vout[1].get("scriptPubKey") or {}).get("address")

    if not owner:

        return None

    return {

        "seed": data["s"],

        "op": data["op"],

        "owner_addr": owner,

        "txid": tx.get("txid"),

    }

def process_block(height: int):

    block_hash = rpc_call("getblockhash", [height])

    block = rpc_call("getblock", [block_hash, 2])

    if not block:

        return 0

    conn = db()

    changed = 0

    try:

        for tx in block.get("tx", []):

            item = decode_stamp_tx(tx)

            if not item:

                continue

            conn.execute(

                """
                UPDATE seeds
                   SET owner_addr=?, txid=?, height_at=?, status='inscribed'
                 WHERE seed=?
                """,

                (item["owner_addr"], item["txid"], height, item["seed"]),

            )

            changed += 1

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
