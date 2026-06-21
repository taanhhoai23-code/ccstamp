import os

import sys, json, time, re, sqlite3

from flask import Blueprint, request, jsonify, Response

from rpc_client import rpc_call

wallet_bp = Blueprint('wallet', __name__)

DB = os.environ.get('CCSTAMP_DB', 'ccstamp.db')

DUST = 0.001

DEFAULT_FEERATE = 2.0

COIN = 100_000_000

ADDR_RE = re.compile(r'^cc1[0-9a-z]{20,90}$')

def _db():

    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

import threading as _threading

import fcntl as _fcntl

import os as _os_lock

_SCAN_LOCK = _threading.Lock()

_SCAN_FLOCK_PATH = '/tmp/ccstamp_scantxoutset.lock'

_SCAN_CACHE = {}

_SCAN_TTL = 8.0

class _ScanBusy(Exception):

    pass

def _scan_cache_get(addrs):

    key = frozenset(addrs)

    v = _SCAN_CACHE.get(key)

    if v and (time.time() - v[0]) < _SCAN_TTL:

        return v[1]

    return None

def _scan_cache_put(addrs, result):

    _SCAN_CACHE[frozenset(addrs)] = (time.time(), result)

    if len(_SCAN_CACHE) > 200:

        now = time.time()

        for k in [k for k, vv in _SCAN_CACHE.items() if now - vv[0] >= _SCAN_TTL]:

            _SCAN_CACHE.pop(k, None)

def _scantxoutset_locked(scan_args):

    last_err = None

    for attempt in range(5):

        with _SCAN_LOCK:

            lf = None

            try:

                lf = open(_SCAN_FLOCK_PATH, 'w')

                _fcntl.flock(lf.fileno(), _fcntl.LOCK_EX)

                r = rpc_call('scantxoutset', ['start', scan_args])

                if r.get('success'):

                    return r

                last_err = 'scantxoutset 未成功'

            except Exception as e:

                last_err = str(e)

            finally:

                if lf is not None:

                    try:

                        _fcntl.flock(lf.fileno(), _fcntl.LOCK_UN)

                        lf.close()

                    except Exception:

                        pass

        time.sleep(0.5 * (attempt + 1))

    raise _ScanBusy(last_err or 'scantxoutset 节点繁忙')

def _valid_addr(a):

    if not a or not ADDR_RE.match(a):

        return False

    try:

        return bool(rpc_call('validateaddress', [a]).get('isvalid'))

    except Exception:

        return False

def _feerate_sat_vb():

    try:

        r = rpc_call('estimatesmartfee', [2])

        fr = r.get('feerate')

        if fr and fr > 0:

            return max(1.0, fr * COIN / 1000.0)

    except Exception:

        pass

    return DEFAULT_FEERATE

def _scan_utxos(address):

    cached = _scan_cache_get([address])

    if cached is not None:

        return cached

    r = _scantxoutset_locked([f'addr({address})'])

    out = []

    for u in r.get('unspents', []):

        sats = int(round(u['amount'] * COIN))

        out.append({

            'txid': u['txid'], 'vout': u['vout'],

            'amount': u['amount'], 'sats': sats,

            'scriptPubKey': u['scriptPubKey'], 'height': u.get('height', 0),

            'address': address,

        })

    _scan_cache_put([address], out)

    return out

def _scan_utxos_multi(addresses):

    addrs = [a for a in dict.fromkeys(addresses) if a]

    if not addrs:

        return []

    cached = _scan_cache_get(addrs)

    if cached is not None:

        return cached

    scan = [f'addr({a})' for a in addrs]

    r = _scantxoutset_locked(scan)

    out = []

    for u in r.get('unspents', []):

        d = u.get('desc') or ''

        m = re.search(r'addr\(([^)]+)\)', d)

        a = m.group(1) if m else None

        sats = int(round(u['amount'] * COIN))

        out.append({

            'txid': u['txid'], 'vout': u['vout'],

            'amount': u['amount'], 'sats': sats,

            'scriptPubKey': u['scriptPubKey'], 'height': u.get('height', 0),

            'address': a,

        })

    _scan_cache_put(addrs, out)

    return out

def _req_addresses():

    addrs = []

    data = request.get_json(silent=True) or {}

    if isinstance(data.get('addresses'), list):

        addrs += [str(a).strip() for a in data['addresses']]

    qs = request.args.get('addresses')

    if qs:

        addrs += [a.strip() for a in qs.split(',')]

    one = (request.args.get('address') or data.get('address') or '').strip()

    if one:

        addrs.append(one)

    seen, valid = set(), []

    for a in addrs:

        if a and a not in seen and _valid_addr(a):

            seen.add(a); valid.append(a)

        if len(valid) >= 100:

            break

    return valid

def _est_vsize(n_in, n_out, has_opreturn=False, opreturn_bytes=0):

    v = 11 + 68 * n_in + 31 * n_out

    if has_opreturn:

        v += 9 + opreturn_bytes

    return int(v * 1.05)

@wallet_bp.route('/api/wallet/utxos', methods=['GET', 'POST'])

def api_utxos():

    addrs = _req_addresses()

    if not addrs:

        return jsonify({'error': '地址无效'}), 400

    primary = addrs[0]

    try:

        utxos = _scan_utxos_multi(addrs)

    except Exception as e:

        return jsonify({'error': f'UTXO 查询失败: {e}'}), 503

    try:

        tip = rpc_call('getblockcount') or 0

    except Exception:

        tip = 0

    cset = set()

    for a in addrs:

        for c in _carrier_utxos(a):

            cset.add((c['txid'], c['vout']))

    spendable, locked = 0, 0

    spendable_confirmed, spendable_pending = 0, 0

    locked_confirmed, locked_pending = 0, 0

    for u in utxos:

        h = u.get('height', 0) or 0

        conf = (tip - h + 1) if h > 0 else 0

        u['confirmations'] = max(conf, 0)

        if (u['txid'], u['vout']) in cset:

            u['inscription'] = True

            locked += u['sats']

            if u['confirmations'] >= 1: locked_confirmed += u['sats']

            else: locked_pending += u['sats']

        else:

            u['inscription'] = False

            spendable += u['sats']

            if u['confirmations'] >= 1: spendable_confirmed += u['sats']

            else: spendable_pending += u['sats']

    return jsonify({

        'address': primary,

        'addresses': addrs,

        'tip': tip,

        'utxos': utxos,

        'balance_sats': spendable + locked,

        'spendable_sats': spendable,

        'spendable_confirmed_sats': spendable,

        'spendable_pending_sats': spendable_pending,

        'inscription_locked_sats': locked,

        'inscription_confirmed_sats': locked_confirmed,

        'inscription_pending_sats': locked_pending,

        'balance': round((spendable + locked) / COIN, 8),

        'spendable': round(spendable / COIN, 8),

        'pending': round(spendable_pending / COIN, 8),

        'count': len(utxos),

    })

@wallet_bp.route('/api/wallet/build', methods=['POST'])

def api_build():

    d = request.get_json(force=True) or {}

    typ = d.get('type')

    frm = (d.get('from') or '').strip()

    to  = (d.get('to') or '').strip()

    if not _valid_addr(frm):

        return jsonify({'error': '付款地址无效'}), 400

    if not _valid_addr(to):

        return jsonify({'error': '收款地址无效'}), 400

    from_addrs = []

    if isinstance(d.get('from_addresses'), list):

        for a in d['from_addresses']:

            a = str(a).strip()

            if a and _valid_addr(a) and a not in from_addrs:

                from_addrs.append(a)

    if frm not in from_addrs:

        from_addrs.insert(0, frm)

    try:

        if typ == 'transfer':

            return _build_transfer(frm, to, d, from_addrs)

        elif typ == 'inscription':

            return _build_inscription_transfer(frm, to, d, from_addrs)

        else:

            return jsonify({'error': 'type 必须为 transfer 或 inscription'}), 400

    except _ScanBusy:

        return jsonify({'error': '节点正忙(查询UTXO繁忙)，请稍候几秒重试'}), 503

    except ValueError as e:

        return jsonify({'error': str(e)}), 400

    except Exception as e:

        return jsonify({'error': f'构造失败: {e}'}), 500

def _select_coins(utxos, target_sats, feerate, n_out, exclude=None, opreturn_bytes=0):

    exclude = exclude or set()

    pool = [u for u in utxos if (u['txid'], u['vout']) not in exclude]

    pool.sort(key=lambda x: ((x.get('height') or 0) > 0, x['sats']), reverse=True)

    sel, acc = [], 0

    has_or = opreturn_bytes > 0

    for u in pool:

        sel.append(u); acc += u['sats']

        fee = int(_est_vsize(len(sel), n_out, has_or, opreturn_bytes) * feerate)

        if acc >= target_sats + fee:

            change = acc - target_sats - fee

            if 0 < change < int(DUST * COIN):

                fee += change; change = 0

            return sel, fee, change

    available = sum(u['sats'] for u in pool)

    need = target_sats + int(_est_vsize(max(1, len(pool)), n_out, has_or, opreturn_bytes) * feerate)

    raise ValueError(f'余额不足：当前可用 {available/COIN:.8f} BTCC，本次至少需要 {need/COIN:.8f} BTCC（含预估手续费）')

def _make_psbt(inputs, outputs, utxos_by_op):

    psbt = rpc_call('createpsbt', [

        [{'txid': i['txid'], 'vout': i['vout']} for i in inputs],

        outputs

    ])

    psbt2 = rpc_call('utxoupdatepsbt', [psbt])

    return psbt2

def _all_carrier_keys(addr):

    c = _db()

    try:

        rows = c.execute(

            "SELECT txid FROM seeds WHERE owner_addr=? AND status='inscribed' AND txid IS NOT NULL",

            (addr,)

        ).fetchall()

    finally:

        c.close()

    return {(r['txid'], 1) for r in rows}

def _build_transfer(frm, to, d, from_addrs=None):

    amount = d.get('amount')

    if amount is None or float(amount) <= 0:

        raise ValueError('金额必须 > 0')

    amount_sats = int(round(float(amount) * COIN))

    addrs = from_addrs or [frm]

    utxos = _scan_utxos_multi(addrs)

    cset = set()

    for a in addrs:

        cset |= _all_carrier_keys(a)

    feerate = _feerate_sat_vb()

    sel, fee, change = _select_coins(utxos, amount_sats, feerate, 2, exclude=cset)

    outputs = [{to: round(amount_sats / COIN, 8)}]

    if change > 0:

        outputs.append({frm: round(change / COIN, 8)})

    psbt = _make_psbt(sel, outputs, None)

    input_meta = [{'change': 0, 'index': 0} for _ in sel]

    return jsonify({

        'psbt': psbt, 'inputs': input_meta,

        'fee_sats': fee, 'feerate': round(feerate, 2),

        'change_sats': change, 'n_inputs': len(sel),

        'summary': {

            'action': '转账', 'from': frm, 'to': to,

            'amount': round(amount_sats / COIN, 8),

            'fee': round(fee / COIN, 8),

            'total': round((amount_sats + fee) / COIN, 8),

        }

    })

def _build_inscription_transfer(frm, to, d, from_addrs=None):

    seed = (d.get('seed') or '').strip()

    carrier = d.get('carrier') or {}

    ctxid, cvout = carrier.get('txid'), carrier.get('vout')

    if not seed:

        raise ValueError('缺少 seed')

    if not ctxid or cvout is None:

        raise ValueError('缺少载体 UTXO(carrier)')

    addrs = from_addrs or [frm]

    owned = _carrier_utxos(frm)

    match = next((c for c in owned if c['txid'] == ctxid and c['vout'] == cvout and c['seed'] == seed), None)

    if not match:

        raise ValueError('该铭文载体不属于此地址或已转移')

    utxos = _scan_utxos_multi(addrs)

    carrier_utxo = next((u for u in utxos if u['txid'] == ctxid and u['vout'] == cvout), None)

    if not carrier_utxo:

        raise ValueError('载体 UTXO 已花费(铭文可能已转移)')

    if (carrier_utxo.get('height') or 0) <= 0:

        raise ValueError('铭文待确认中, 1 个块确认后即可转移')

    payload = json.dumps({"p": "cc-stamp", "op": "xfer", "s": seed}, separators=(',', ':'))

    hex_data = payload.encode('utf-8').hex()

    or_bytes = len(payload)

    feerate = _feerate_sat_vb()

    dust_sats = int(DUST * COIN)

    cset = set()

    for a in addrs:

        for c in _carrier_utxos(a):

            cset.add((c['txid'], c['vout']))

    cset.discard((ctxid, cvout))

    other = [u for u in utxos if (u['txid'], u['vout']) not in cset

             and not (u['txid'] == ctxid and u['vout'] == cvout)]

    other.sort(key=lambda x: x['sats'], reverse=True)

    sel = [carrier_utxo]

    acc = carrier_utxo['sats']

    n_out = 3

    def need(nsel):

        fee = int(_est_vsize(nsel, n_out, True, or_bytes) * feerate)

        return dust_sats + fee

    i = 0

    while acc < need(len(sel)) and i < len(other):

        sel.append(other[i]); acc += other[i]['sats']; i += 1

    fee = int(_est_vsize(len(sel), n_out, True, or_bytes) * feerate)

    if acc < dust_sats + fee:

        raise ValueError('余额不足以支付铭文转移(dust + 手续费)')

    change = acc - dust_sats - fee

    outputs = [{'data': hex_data}, {to: round(dust_sats / COIN, 8)}]

    if change >= dust_sats:

        outputs.append({frm: round(change / COIN, 8)})

    else:

        fee += change; change = 0

    psbt = _make_psbt(sel, outputs, None)

    input_meta = [{'change': 0, 'index': 0} for _ in sel]

    return jsonify({

        'psbt': psbt, 'inputs': input_meta,

        'fee_sats': fee, 'feerate': round(feerate, 2),

        'change_sats': change, 'n_inputs': len(sel),

        'summary': {

            'action': '转移铭文', 'seed': seed, 'from': frm, 'to': to,

            'fee': round(fee / COIN, 8),

            'note': 'OP_RETURN 重刻 + dust 载体转新持有人',

        }

    })

def _record_mempool_tx(txid, addr, summary, kind):

    if not addr or not summary:

        return

    try:

        c = _idb()

        c.execute("""CREATE TABLE IF NOT EXISTS mempool_txs(
            txid TEXT PRIMARY KEY, address TEXT NOT NULL,
            direction TEXT NOT NULL, tx_type TEXT NOT NULL,
            amount_sat INTEGER NOT NULL, counterparty TEXT,
            broadcast_ts INTEGER NOT NULL, seed TEXT
        )""")

        import time as _t

        amt = summary.get('amount') or 0

        amount_sat = int(round(float(amt) * COIN)) if amt else 0

        if amount_sat == 0 and kind == 'inscription':

            amount_sat = int(DUST * COIN)

        tx_type = 'inscription' if kind == 'inscription' else 'transfer'

        cp = summary.get('to') or ''

        seed = summary.get('seed')

        c.execute("INSERT OR REPLACE INTO mempool_txs"

                  "(txid,address,direction,tx_type,amount_sat,counterparty,broadcast_ts,seed) "

                  "VALUES(?,?,?,?,?,?,?,?)",

                  (txid, addr, 'out', tx_type, amount_sat, cp, int(_t.time()), seed))

        if kind == 'inscription' and cp and seed:

            c.execute("""CREATE TABLE IF NOT EXISTS mempool_inbound(
                txid TEXT NOT NULL, address TEXT NOT NULL, seed TEXT NOT NULL,
                broadcast_ts INTEGER NOT NULL, PRIMARY KEY(txid, address, seed)
            )""")

            c.execute("INSERT OR REPLACE INTO mempool_inbound(txid,address,seed,broadcast_ts) "

                      "VALUES(?,?,?,?)", (txid, cp, seed, int(_t.time())))

        c.commit(); c.close()

    except Exception:

        pass

def _inscription_carriers_spent(vins):

    if not vins:

        return []

    txids = list({v['txid'] for v in vins})

    spent = []

    try:

        c = _db()

        q = ','.join('?' * len(txids))

        rows = c.execute(

            f"SELECT txid, seed FROM seeds WHERE status='inscribed' AND txid IN ({q})",

            txids

        ).fetchall()

        c.close()

    except Exception:

        return []

    seed_by_txid = {r['txid']: r['seed'] for r in rows}

    for v in vins:

        if v['txid'] in seed_by_txid and v['vout'] == 1:

            spent.append((v['txid'], v['vout'], seed_by_txid[v['txid']]))

    return spent

def _check_burn_safe(rawtx):

    try:

        decoded = rpc_call('decoderawtransaction', [rawtx])

    except Exception as e:

        return False, f'交易解码失败，拒绝广播: {e}'

    if not decoded:

        return False, '交易解码为空，拒绝广播'

    vins = [{'txid': vi.get('txid'), 'vout': vi.get('vout')} for vi in decoded.get('vin', []) if vi.get('txid')]

    spent_carriers = _inscription_carriers_spent(vins)

    if not spent_carriers:

        return True, ''

    vouts = decoded.get('vout', [])

    has_opreturn_seed = False

    has_dust_carrier = False

    spent_seeds = {s for _, _, s in spent_carriers}

    for vo in vouts:

        spk = vo.get('scriptPubKey', {}) or {}

        if spk.get('type') == 'nulldata':

            asm = spk.get('asm', '') or ''

            m = re.search(r'OP_RETURN\s+([0-9a-fA-F]+)', asm)

            if m:

                try:

                    payload = bytes.fromhex(m.group(1)).decode('utf-8', 'ignore')

                    obj = json.loads(payload)

                    if obj.get('p') == 'cc-stamp' and obj.get('s') in spent_seeds:

                        has_opreturn_seed = True

                except Exception:

                    pass

        else:

            val_sats = int(round(float(vo.get('value') or 0) * COIN))

            if abs(val_sats - int(DUST * COIN)) <= int(DUST * COIN):

                if val_sats >= int(DUST * COIN) * 0 + 1:

                    has_dust_carrier = True

    if has_opreturn_seed and has_dust_carrier:

        return True, ''

    burned = ', '.join(s for _, _, s in spent_carriers)

    return False, f'检测到该交易会烧毁铭文({burned})：花掉了铭文载体但未正确重刻 OP_RETURN+新载体。已拒绝广播以保护铭文。'

@wallet_bp.route('/api/wallet/broadcast', methods=['POST'])

def api_broadcast():

    d = request.get_json(force=True) or {}

    rawtx = (d.get('rawtx') or '').strip()

    if not rawtx or not re.match(r'^[0-9a-fA-F]+$', rawtx):

        return jsonify({'error': 'rawtx 无效'}), 400

    ok, reason = _check_burn_safe(rawtx)

    if not ok:

        return jsonify({'error': reason, 'ok': False, 'burn_protected': True}), 400

    try:

        txid = rpc_call('sendrawtransaction', [rawtx])

        _record_mempool_tx(

            txid,

            (d.get('from_addr') or '').strip(),

            d.get('summary') or {},

            d.get('kind') or 'transfer'

        )

        return jsonify({'txid': txid, 'ok': True})

    except Exception as e:

        return jsonify({'error': f'广播失败: {e}', 'ok': False}), 400

def _carrier_utxos(address):

    out = []

    try:

        c = _db()

        rows = c.execute(

            "SELECT seed, txid, owner_addr FROM seeds WHERE owner_addr=? AND status='inscribed' AND txid IS NOT NULL",

            (address,)

        ).fetchall()

        c.close()

    except Exception:

        return out

    if not rows:

        return out

    real_rows = [r for r in rows if r['txid'] and len(r['txid']) == 64

                 and all(ch in '0123456789abcdefABCDEF' for ch in r['txid'])]

    live_map = {}

    scan_ok = False

    try:

        for u in _scan_utxos(address):

            live_map[(u['txid'], u['vout'])] = u.get('height') or 0

        scan_ok = True

    except Exception:

        scan_ok = False

    for r in real_rows:

        vout = 1

        key = (r['txid'], vout)

        h = live_map.get(key)

        if h is not None:

            out.append({'seed': r['seed'], 'txid': r['txid'], 'vout': vout,

                        'status': 'inscribed', 'height': h})

            continue

        rpc_ok = True

        try:

            txout = rpc_call('gettxout', [r['txid'], vout, True])

        except Exception:

            txout = None

            rpc_ok = False

        if txout:

            spk = txout.get('scriptPubKey', {}) or {}

            a = spk.get('address') or (spk.get('addresses') or [None])[0]

            if a == address:

                out.append({'seed': r['seed'], 'txid': r['txid'], 'vout': vout,

                            'status': 'inscribed', 'height': 0})

        elif not rpc_ok:

            out.append({'seed': r['seed'], 'txid': r['txid'], 'vout': vout,

                        'status': 'inscribed', 'height': 0})

    seen_keys = {(it['txid'], it['vout']) for it in out}

    seen_seeds = {it['seed'] for it in out}

    try:

        my_utxos = _scan_utxos(address) if scan_ok else []

    except Exception:

        my_utxos = []

    dust_sats = int(DUST * COIN)

    cdb = None

    try:

        cdb = _db()

        for u in my_utxos:

            key = (u['txid'], u['vout'])

            if key in seen_keys:

                continue

            if u['vout'] != 1:

                continue

            usats = u.get('sats')

            if usats is not None and usats != dust_sats:

                continue

            try:

                txout0 = rpc_call('gettxout', [u['txid'], 0, True])

            except Exception:

                txout0 = None

            if not txout0:

                continue

            spk0 = txout0.get('scriptPubKey', {}) or {}

            if spk0.get('type') != 'nulldata':

                continue

            asm = spk0.get('asm', '') or ''

            parts = asm.split()

            if len(parts) < 2:

                continue

            try:

                payload = bytes.fromhex(parts[1]).decode('utf-8', errors='ignore')

                if 'cc-stamp' not in payload:

                    continue

                seed = json.loads(payload).get('s')

            except Exception:

                continue

            if not seed or seed in seen_seeds:

                continue

            sr = cdb.execute(

                "SELECT seed FROM seeds WHERE seed=? AND status='inscribed' LIMIT 1",

                (seed,)

            ).fetchone()

            if sr:

                out.append({'seed': seed, 'txid': u['txid'], 'vout': 1,

                            'status': 'inscribed', 'height': u.get('height') or 0})

                seen_keys.add(key); seen_seeds.add(seed)

    except Exception:

        pass

    finally:

        if cdb is not None:

            try: cdb.close()

            except Exception: pass

    return out

@wallet_bp.route('/api/wallet/inscriptions', methods=['GET', 'POST'])

def api_inscriptions():

    addrs = _req_addresses()

    if not addrs:

        return jsonify({'error': '地址无效'}), 400

    primary = addrs[0]

    items = []

    for a in addrs:

        for it in _carrier_utxos(a):

            it['owner'] = a

            items.append(it)

    try:

        tip = rpc_call('getblockcount') or 0

    except Exception:

        tip = 0

    for it in items:

        h = it.get('height') or 0

        it['confirmations'] = (tip - h + 1) if h > 0 else 0

        it['transferable'] = it['confirmations'] >= 1

    try:

        import generator

        for it in items:

            try:

                svg, info = generator.gen(it['seed'])

                gid = 'g_' + re.sub(r'[^a-zA-Z0-9_]', '_', it['seed'])

                svg = svg.replace("id='g'", "id='" + gid + "'").replace('url(#g)', 'url(#' + gid + ')')

                it['svg'] = svg

                it['head'] = info[0] if info else None

                it['rarity'] = info[1] if len(info) > 1 else None

            except Exception:

                it['svg'] = None

    except Exception:

        pass

    return jsonify({'address': primary, 'addresses': addrs, 'inscriptions': items, 'count': len(items), 'tip': tip})

_SEED_RE = re.compile(r'^CC-STAMP-\d{5}-\d+$')

@wallet_bp.route('/api/wallet/stamp/<seed>.png')

def stamp_png(seed):

    if not _SEED_RE.match(seed):

        return jsonify({'error': 'bad seed'}), 400

    try:

        size = int(request.args.get('size', 1024))

    except ValueError:

        size = 1024

    try:

        import stamp_render

        data = stamp_render.render_png(seed, size)

    except Exception as e:

        return jsonify({'error': str(e)}), 500

    return Response(data, mimetype='image/png', headers={

        'Content-Disposition': f'attachment; filename="{seed}.png"',

        'Cache-Control': 'public, max-age=31536000, immutable',

    })

@wallet_bp.route('/api/wallet/stamp/<seed>.svg')

def stamp_svg(seed):

    if not _SEED_RE.match(seed):

        return jsonify({'error': 'bad seed'}), 400

    try:

        import stamp_render

        svg = stamp_render.render_svg(seed)

    except Exception as e:

        return jsonify({'error': str(e)}), 500

    return Response(svg, mimetype='image/svg+xml', headers={

        'Content-Disposition': f'attachment; filename="{seed}.svg"',

        'Cache-Control': 'public, max-age=31536000, immutable',

    })

import os as _os

_INDEXER_DB = os.environ.get('CCSTAMP_DB', 'ccstamp.db')

def _idb():

    import sqlite3 as _sq

    c = _sq.connect(_INDEXER_DB, timeout=10)

    c.row_factory = _sq.Row

    c.executescript("""
    CREATE TABLE IF NOT EXISTS tracked_addresses(
        address TEXT PRIMARY KEY,
        first_seen INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS wallet_txs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        address TEXT NOT NULL,
        txid TEXT NOT NULL,
        direction TEXT NOT NULL,
        tx_type TEXT NOT NULL,
        amount_sat INTEGER NOT NULL,
        counterparty TEXT,
        height INTEGER NOT NULL,
        block_time INTEGER NOT NULL,
        seed TEXT,
        UNIQUE(address, txid, direction)
    );
    CREATE INDEX IF NOT EXISTS idx_wtx_addr_h ON wallet_txs(address, height DESC);
    CREATE TABLE IF NOT EXISTS mempool_txs(
        txid TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        direction TEXT NOT NULL,
        tx_type TEXT NOT NULL,
        amount_sat INTEGER NOT NULL,
        counterparty TEXT,
        broadcast_ts INTEGER NOT NULL,
        seed TEXT
    );
    """)

    c.commit()

    return c

@wallet_bp.route('/api/wallet/register', methods=['POST'])

def api_register():

    data = request.get_json(silent=True) or {}

    addrs = []

    one = (data.get('address') or request.args.get('address') or '').strip()

    if one:

        addrs.append(one)

    if isinstance(data.get('addresses'), list):

        addrs += [str(a).strip() for a in data['addresses']]

    qs = request.args.get('addresses')

    if qs:

        addrs += [a.strip() for a in qs.split(',')]

    addrs = [a for a in dict.fromkeys(addrs) if a and _valid_addr(a)]

    if not addrs:

        return jsonify({'error': '地址无效'}), 400

    import time as _t

    try:

        c = _idb()

        now = int(_t.time())

        c.executemany("INSERT OR IGNORE INTO tracked_addresses(address, first_seen) VALUES(?,?)",

                      [(a, now) for a in addrs])

        c.commit()

        c.close()

    except Exception as e:

        return jsonify({'error': f'注册失败: {e}'}), 500

    return jsonify({'ok': True, 'addresses': addrs, 'count': len(addrs)})

_mem_chain_cache = {}

_MEM_CACHE_TTL = 90

_MEM_GRACE = 900

_MEM_SCAN_DEPTH = 60

def _mem_tx_chain_state(txid, broadcast_ts, tip):

    now = int(time.time())

    cached = _mem_chain_cache.get(txid)

    if cached and now - cached[0] < _MEM_CACHE_TTL:

        return cached[1], cached[2], cached[3]

    state, height, btime = 'mempool', 0, 0

    try:

        raw = rpc_call('getrawtransaction', [txid])

        if raw:

            state = 'mempool'

        else:

            found_h = None

            lo = max(1, (tip or 0) - _MEM_SCAN_DEPTH)

            for h in range(tip or 0, lo - 1, -1):

                bh = rpc_call('getblockhash', [h])

                if not bh:

                    continue

                blk = rpc_call('getblock', [bh, 1])

                if blk and txid in (blk.get('tx') or []):

                    found_h = h

                    btime = blk.get('time', 0) or 0

                    break

            if found_h:

                state, height = 'mined', found_h

            else:

                state = 'dropped' if (now - (broadcast_ts or now)) > _MEM_GRACE else 'mempool'

    except Exception:

        state = 'mempool'

    _mem_chain_cache[txid] = (now, state, height, btime)

    return state, height, btime

@wallet_bp.route('/api/wallet/history', methods=['GET', 'POST'])

def api_history():

    addrs = _req_addresses()

    if not addrs:

        return jsonify({'error': '地址无效'}), 400

    primary = addrs[0]

    aset = set(addrs)

    aq = ','.join(['?'] * len(addrs))

    try:

        limit = max(1, min(int(request.args.get('limit') or 50), 200))

    except Exception:

        limit = 50

    try:

        offset = max(0, int(request.args.get('offset') or 0))

    except Exception:

        offset = 0

    try:

        tip = rpc_call('getblockcount') or 0

    except Exception:

        tip = 0

    items = []

    try:

        c = _idb()

        has_mem = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mempool_txs'").fetchone()

        mem_rows = c.execute(

            f"SELECT txid, direction, tx_type, amount_sat, counterparty, broadcast_ts, seed "

            f"FROM mempool_txs WHERE address IN ({aq}) ORDER BY broadcast_ts DESC", tuple(addrs)

        ).fetchall() if has_mem else []

        mem_txids = {r['txid'] for r in mem_rows}

        confirmed_meta = {}

        if mem_txids:

            q = ','.join(['?'] * len(mem_txids))

            for rr in c.execute(

                f"SELECT txid, MAX(height) AS height, MAX(block_time) AS block_time FROM wallet_txs "

                f"WHERE address IN ({aq}) AND txid IN ({q}) GROUP BY txid",

                (*addrs, *list(mem_txids))

            ).fetchall():

                confirmed_meta[rr['txid']] = {'height': rr['height'] or 0, 'block_time': rr['block_time'] or 0}

        for r in mem_rows:

            meta = confirmed_meta.get(r['txid']) or {}

            h = meta.get('height') or 0

            conf = (tip - h + 1) if h > 0 else 0

            btime = meta.get('block_time') or r['broadcast_ts'] or 0

            state = 'mined' if conf >= 1 else 'pending'

            if conf < 1 and r['txid']:

                cs, ch, cbt = _mem_tx_chain_state(r['txid'], r['broadcast_ts'], tip)

                if cs == 'mined':

                    h = ch or h

                    conf = (tip - h + 1) if h > 0 else 1

                    btime = cbt or btime

                    state = 'mined'

                elif cs == 'dropped':

                    state = 'dropped'

                else:

                    state = 'pending'

            items.append({

                'txid': r['txid'],

                'direction': r['direction'],

                'amount_sats': r['amount_sat'] or 0,

                'amount': round((r['amount_sat'] or 0) / 1e8, 8),

                'height': h,

                'block_time': btime,

                'counterparty': r['counterparty'] or '',

                'type': r['tx_type'] or 'transfer',

                'seed': r['seed'],

                'confirmations': conf,

                'spendable': conf >= 1,

                'pending': conf <= 0 and state != 'dropped',

                'state': state,

            })

        rows = c.execute(

            f"SELECT txid, direction, amount_sat, height, block_time, counterparty, tx_type, seed "

            f"FROM wallet_txs WHERE address IN ({aq}) ORDER BY height DESC, id DESC LIMIT ? OFFSET ?",

            (*addrs, limit, offset)

        ).fetchall()

        c.close()

        seen_txid = set()

        for r in rows:

            key = (r['txid'], r['direction'])

            if r['txid'] in mem_txids:

                continue

            if key in seen_txid:

                continue

            seen_txid.add(key)

            h = r['height'] or 0

            conf = (tip - h + 1) if h > 0 else 0

            items.append({

                'txid': r['txid'],

                'direction': r['direction'],

                'amount_sats': r['amount_sat'] or 0,

                'amount': round((r['amount_sat'] or 0) / 1e8, 8),

                'height': h,

                'block_time': r['block_time'] or 0,

                'counterparty': r['counterparty'] or '',

                'type': r['tx_type'] or 'transfer',

                'seed': r['seed'],

                'confirmations': conf,

                'spendable': conf >= 1,

                'pending': False,

            })

    except Exception as e:

        return jsonify({'error': f'历史查询失败: {e}', 'items': [], 'tip': tip}), 200

    return jsonify({'address': primary, 'addresses': addrs, 'items': items, 'tip': tip, 'count': len(items)})

@wallet_bp.route('/api/wallet/discover', methods=['POST'])

def api_discover():

    data = request.get_json(silent=True) or {}

    addrs = data.get('addresses') or []

    if not isinstance(addrs, list) or not addrs:

        return jsonify({'error': '缺少地址列表'}), 400

    addrs = [str(a).strip() for a in addrs[:100] if str(a).strip()]

    valid = [a for a in addrs if _valid_addr(a)]

    if not valid:

        return jsonify({'error': '无有效地址'}), 400

    try:

        scan = [f'addr({a})' for a in valid]

        r = _scantxoutset_locked(scan)

    except _ScanBusy:

        return jsonify({'error': '节点正忙(查询UTXO繁忙)，请稍候几秒重试'}), 503

    except Exception as e:

        return jsonify({'error': f'扫描失败: {e}'}), 503

    by_addr = {a: {'utxos': 0, 'sats': 0} for a in valid}

    for u in r.get('unspents', []):

        d = u.get('desc') or ''

        m = re.search(r'addr\(([^)]+)\)', d)

        a = m.group(1) if m else None

        if a is None:

            continue

        if a in by_addr:

            by_addr[a]['utxos'] += 1

            by_addr[a]['sats'] += int(round(u['amount'] * COIN))

    results = []

    for a in valid:

        info = by_addr[a]

        results.append({

            'address': a,

            'has_funds': info['utxos'] > 0,

            'utxos': info['utxos'],

            'sats': info['sats'],

        })

    return jsonify({'results': results, 'count': len(results)})
