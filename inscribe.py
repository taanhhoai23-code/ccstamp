import os
import sys, json
from rpc_client import rpc_call
WALLET = 'stamp_wallet'
SEED = sys.argv[1] if len(sys.argv) > 1 else 'CC-STAMP-00001-7a3f'
DUST = 0.001
payload = json.dumps({"p": "cc-stamp", "op": "gen", "s": SEED}, separators=(',', ':'))
hex_data = payload.encode('utf-8').hex()
print(f"铭文内容: {payload}")
print(f"字节数: {len(payload)} (上限520)")
print(f"hex: {hex_data}")
recv_addr = rpc_call('getnewaddress', ['nft-holder', 'bech32'], wallet=WALLET)
print(f"接收地址(NFT归属): {recv_addr}")
outputs = [
    {"data": hex_data},
    {recv_addr: DUST},
]
raw = rpc_call('createrawtransaction', [[], outputs])
funded = rpc_call('fundrawtransaction', [raw, {"changePosition": 2}], wallet=WALLET)
print(f"预估矿工费: {funded['fee']} BTCC")
signed = rpc_call('signrawtransactionwithwallet', [funded['hex']], wallet=WALLET)
assert signed['complete'], f"签名失败: {signed}"
txid = rpc_call('sendrawtransaction', [signed['hex']], wallet=WALLET)
print(f"\n✅ 铭文已上链!")
print(f"TXID: {txid}")
print(f"SEED: {SEED}")
print(f"载体vout: 1 -> {recv_addr}")
with open(os.environ.get('CCSTAMP_LAST_INSCRIPTION', 'last_inscription.json'), 'w') as f:
    json.dump({"txid": txid, "seed": SEED, "payload": payload,
               "recv_addr": recv_addr, "carrier_vout": 1}, f, indent=2)
print("\n已存 last_inscription.json")
