import sys, json, re
from rpc_client import rpc_call
import generator
txid = sys.argv[1]
tx = None
try:
    wtx = rpc_call('gettransaction', [txid, True], wallet='stamp_wallet')
    tx = rpc_call('decoderawtransaction', [wtx['hex']])
    conf = wtx.get('confirmations', 0)
except Exception:
    tx = rpc_call('getrawtransaction', [txid, True])
    conf = tx.get('confirmations', 0)
print(f"链上交易: {txid}")
print(f"确认数: {conf}")
hex_data = None
for vout in tx['vout']:
    spk = vout['scriptPubKey']
    if spk.get('type') == 'nulldata':
        asm = spk['asm']
        m = re.search(r'OP_RETURN\s+([0-9a-fA-F]+)', asm)
        if m:
            hex_data = m.group(1)
            break
assert hex_data, "未找到 OP_RETURN 铭文数据"
payload = bytes.fromhex(hex_data).decode('utf-8')
print(f"\n从链上抠出的铭文: {payload}")
data = json.loads(payload)
assert data.get('p') == 'cc-stamp', f"不是 cc-stamp 协议: {data}"
assert data.get('op') == 'gen', f"不是 gen 类型: {data}"
seed = data['s']
print(f"协议: {data['p']} | 操作: {data['op']} | SEED: {seed}")
svg, info = generator.gen(seed)
print(f"还原成功! head: {info[0]} | 徽章: {info[1]}")
out_svg = f'restored_{txid[:8]}.svg'
with open(out_svg, 'w') as f:
    f.write(svg)
print(f"\n✅ 已从链上还原渲染: {out_svg}")
print("用 rsvg-convert 转 PNG 即可查看")
