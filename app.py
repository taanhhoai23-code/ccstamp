import sys, json, sqlite3, time, hashlib, re, os, base64, subprocess, random, threading
from flask import Flask, request, jsonify, render_template, redirect
from rpc_client import rpc_call
import generator
from wallet_api import wallet_bp
import wallet_api as wallet_api_mod
app = Flask(__name__)
app.register_blueprint(wallet_bp)
DB = os.environ.get('CCSTAMP_DB', 'ccstamp.db')
WALLET = 'stamp_fee_wallet'
MINT_WALLET = 'stamp_wallet'
TREASURY_KEY = 'mint_treasury_addr'
PRICE_FLOOR = 2.1
PRICE_SHOW = 2.11
LIMIT_PER_ADDR = 50
PHASE1_LIMIT_PER_ADDR = 10
PHASE1_AIRDROP_QTY = 10
PUBLIC_LIMIT_PER_ADDR = 50
TOTAL_SUPPLY = 21000
ORDER_TTL = 30 * 60
START_HEIGHT = 50029
TARGET_HEIGHT = 51000
MINT_HEIGHT = TARGET_HEIGHT
TEST_FORCE_LIVE = True
TEST_MINT_LIVE = False
LAUNCH_BJ = "2026-06-17 18:00"
RATE_SAMPLE = 144
_rate_cache = {'t': 0, 'data': None}
_TIP_TTL = 3
_tip_cache = {'t': 0, 'h': None}
_tip_lock = threading.Lock()
def cached_tip():
    now = time.time()
    with _tip_lock:
        if _tip_cache['h'] is not None and now - _tip_cache['t'] < _TIP_TTL:
            return _tip_cache['h']
    h = rpc_call('getblockcount')
    with _tip_lock:
        _tip_cache['t'] = time.time()
        _tip_cache['h'] = h
    return h
import hmac as _hmac
ALLOWED_ORIGINS = ('https://nft.btc-classic.org',)
MINT_TOKEN_TTL = 300
_used_nonces = {}
_nonce_lock = threading.Lock()
def _mint_secret():
    c = db()
    row = c.execute("SELECT value FROM app_meta WHERE key='mint_token_secret'").fetchone()
    if row and row['value']:
        c.close(); return row['value'].encode()
    sec = base64.b64encode(os.urandom(32)).decode()
    c.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('mint_token_secret',?)", (sec,))
    c.commit(); c.close()
    return sec.encode()
def _client_ip():
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.headers.get('X-Real-IP') or request.remote_addr or '?'
def issue_mint_token():
    ts = str(int(time.time()))
    rand = base64.urlsafe_b64encode(os.urandom(9)).decode().rstrip('=')
    sig = _hmac.new(_mint_secret(), f"{ts}|{rand}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"{ts}.{rand}.{sig}"
def _check_origin():
    ref = request.headers.get('Origin', '') or request.headers.get('Referer', '')
    if not ref:
        return True
    return any(ref.startswith(o) for o in ALLOWED_ORIGINS)
def _admin_token():
    c = db()
    row = c.execute("SELECT value FROM app_meta WHERE key='admin_token'").fetchone()
    if row and row['value']:
        c.close(); return row['value']
    tok = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip('=')
    c.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('admin_token',?)", (tok,))
    c.commit(); c.close()
    return tok
def _check_admin():
    got = request.headers.get('X-Admin-Token', '')
    if not got:
        return False
    return _hmac.compare_digest(got, _admin_token())
def verify_mint_token(token):
    try:
        ts_s, rand, sig = token.split('.')
        ts = int(ts_s)
    except Exception:
        return False, 'nonce 格式错误'
    now = int(time.time())
    if now - ts > MINT_TOKEN_TTL or ts - now > 60:
        return False, 'nonce 已过期，请刷新页面重试'
    expect = _hmac.new(_mint_secret(), f"{ts_s}|{rand}".encode(), hashlib.sha256).hexdigest()[:24]
    if not _hmac.compare_digest(expect, sig):
        return False, 'nonce 校验失败'
    try:
        c = db()
        c.execute("CREATE TABLE IF NOT EXISTS used_nonces(token TEXT PRIMARY KEY, exp INTEGER)")
        c.execute("DELETE FROM used_nonces WHERE exp < ?", (now,))
        try:
            c.execute("INSERT INTO used_nonces(token, exp) VALUES(?,?)", (token, ts + MINT_TOKEN_TTL))
            c.commit()
        except sqlite3.IntegrityError:
            c.close()
            return False, 'nonce 已使用，请勿重复提交'
        c.close()
    except Exception:
        with _nonce_lock:
            if token in _used_nonces:
                return False, 'nonce 已使用，请勿重复提交'
            _used_nonces[token] = ts + MINT_TOKEN_TTL
    return True, None
COMMUNITY_URL = 'https://t.me/Bitcoin_Classic_CN'
PHASE2_SECONDS = 3 * 60 * 60
TEST_PATH = 'mint-test-7f3c9a2b4d6e'
PHASES = [
    {'no': '一', 'idx': 1, 'name': '第一批', 'tag': '空投',   'qty': 2100,  'price': None, 'note': '白名单每地址10枚，官方直接发放', 'cur': True},
    {'no': '二', 'idx': 2, 'name': '第二批', 'tag': '公开',   'qty': 10000, 'price': 2.11, 'note': '开放 3 小时', 'cur': False},
    {'no': '三', 'idx': 3, 'name': '第三批', 'tag': '公开',   'qty': 8900,  'price': 4.22, 'note': '承接第二批剩余', 'cur': False},
]
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA synchronous=NORMAL")
    return c
def init_db():
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS seeds(
        idx INTEGER PRIMARY KEY, seed TEXT UNIQUE,
        status TEXT DEFAULT 'free', order_id TEXT, txid TEXT, owner_addr TEXT,
        locked_at INTEGER, inscribed_at INTEGER, height_at INTEGER, carrier_vout INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY, qty INTEGER, recv_addr TEXT, pay_addr TEXT UNIQUE,
        pay_to TEXT, auth_msg TEXT, auth_sig TEXT,
        amount_floor REAL, amount_show REAL, seed_ids TEXT,
        status TEXT DEFAULT 'awaiting', paid_amount REAL DEFAULT 0, pay_txid TEXT,
        created_at INTEGER, expires_at INTEGER, phase_idx INTEGER);
    CREATE TABLE IF NOT EXISTS whitelist_addresses(
        address TEXT PRIMARY KEY, note TEXT, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS app_meta(
        key TEXT PRIMARY KEY, value TEXT);
    ''')
    seed_cols = {r['name'] for r in c.execute("PRAGMA table_info(seeds)").fetchall()}
    if 'height_at' not in seed_cols:
        c.execute("ALTER TABLE seeds ADD COLUMN height_at INTEGER")
    if 'carrier_vout' not in seed_cols:
        c.execute("ALTER TABLE seeds ADD COLUMN carrier_vout INTEGER DEFAULT 1")
    cols = {r['name'] for r in c.execute("PRAGMA table_info(orders)").fetchall()}
    if 'phase_idx' not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN phase_idx INTEGER")
    if 'pay_to' not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN pay_to TEXT")
    if 'auth_msg' not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN auth_msg TEXT")
    if 'auth_sig' not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN auth_sig TEXT")
    c.executescript('''
    CREATE INDEX IF NOT EXISTS idx_seeds_status      ON seeds(status);
    CREATE INDEX IF NOT EXISTS idx_seeds_order       ON seeds(order_id);
    CREATE INDEX IF NOT EXISTS idx_seeds_owner       ON seeds(owner_addr);
    CREATE INDEX IF NOT EXISTS idx_orders_recv       ON orders(recv_addr);
    CREATE INDEX IF NOT EXISTS idx_orders_phase      ON orders(phase_idx);
    CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders(status);
    CREATE INDEX IF NOT EXISTS idx_orders_recv_phase ON orders(recv_addr, phase_idx);
    ''')
    c.commit(); c.close()
def ensure_seed_pool():
    c = db()
    n = c.execute('SELECT COUNT(*) FROM seeds').fetchone()[0]
    if n >= TOTAL_SUPPLY:
        c.close(); return
    seeds = generator.build_collection(TOTAL_SUPPLY)
    c.executemany('INSERT OR IGNORE INTO seeds(idx,seed) VALUES(?,?)',
                  [(i+1, s) for i, s in enumerate(seeds)])
    c.commit(); c.close()
    print(f"seed池就绪 {len(seeds)}")
def launch_ts():
    try:
        bh = rpc_call('getblockhash', [TARGET_HEIGHT])
        return int(rpc_call('getblockheader', [bh])['time'])
    except Exception:
        return int(time.time())
def _unconfirmed_chain_depth(wallet_name):
    try:
        uts = rpc_call('listunspent', [0, 9999999], wallet=wallet_name)
    except Exception:
        return 0
    depth = 0
    for u in uts or []:
        if u.get('confirmations', 0) == 0:
            try:
                mp = rpc_call('getmempoolentry', [u['txid']])
                depth = max(depth, mp.get('ancestorcount', 1))
            except Exception:
                depth = max(depth, 1)
    return depth
CHAIN_SAFE_LIMIT = 23
POOL_FEE_WALLET = 'stamp_fee_wallet'
POOL_UTXO_VALUE = 0.002
POOL_MIN = 50
POOL_REFILL = 200
_pool_lock = threading.Lock()
_pool_last_refill_ts = 0
def _count_pool_utxos():
    try:
        uts = rpc_call('listunspent', [1, 9999999], wallet=MINT_WALLET) or []
    except Exception:
        return 0
    return sum(1 for u in uts if abs(u.get('amount', 0) - POOL_UTXO_VALUE) < 1e-6)
def _refill_utxo_pool(n=POOL_REFILL):
    addrs = [rpc_call('getnewaddress', ['utxopool', 'bech32'], wallet=MINT_WALLET) for _ in range(n)]
    outputs = {a: POOL_UTXO_VALUE for a in addrs}
    raw = rpc_call('createrawtransaction', [[], outputs])
    funded = rpc_call('fundrawtransaction', [raw], wallet=POOL_FEE_WALLET)
    if not funded or not funded.get('hex'):
        raise RuntimeError('补池 fundrawtransaction 返回空(fee_wallet 余额不足?)')
    signed = rpc_call('signrawtransactionwithwallet', [funded['hex']], wallet=POOL_FEE_WALLET)
    if not signed or not signed.get('complete'):
        raise RuntimeError('补池交易签名失败')
    return rpc_call('sendrawtransaction', [signed['hex']], wallet=POOL_FEE_WALLET)
def _ensure_utxo_pool():
    global _pool_last_refill_ts
    try:
        if _count_pool_utxos() >= POOL_MIN:
            return
        with _pool_lock:
            if _count_pool_utxos() >= POOL_MIN:
                return
            if time.time() - _pool_last_refill_ts < 60:
                return
            txid = _refill_utxo_pool(POOL_REFILL)
            _pool_last_refill_ts = time.time()
            print(f"[utxo-pool] 已确认池UTXO不足{POOL_MIN}，补池{POOL_REFILL}个 txid={txid}")
    except Exception as e:
        print(f"[utxo-pool] 补池失败(限速逻辑兜底): {e}")
def _chain_too_long_err(msg):
    m = (msg or '').lower()
    return 'too-long-mempool-chain' in m or 'chain of transactions' in m or 'too long mempool chain' in m
def _inscribe_seed_to_addr(seed, recv_addr):
    payload = json.dumps({"p":"cc-stamp","op":"gen","s":seed}, separators=(',', ':'))
    hex_data = payload.encode('utf-8').hex()
    outputs = [{"data": hex_data}, {recv_addr: 0.001}]
    raw = rpc_call('createrawtransaction', [[], outputs])
    last_err = None
    for wallet_name in (MINT_WALLET, WALLET):
        try:
            funded = rpc_call('fundrawtransaction', [raw, {"changePosition": 2}], wallet=wallet_name)
            if not funded or not funded.get('hex'):
                last_err = 'fundrawtransaction 返回空'
                continue
            signed = rpc_call('signrawtransactionwithwallet', [funded['hex']], wallet=wallet_name)
            if not signed or not signed.get('complete'):
                last_err = '铭文交易签名失败'
                continue
            txid = rpc_call('sendrawtransaction', [signed['hex']], wallet=wallet_name)
            if isinstance(txid, str) and len(txid) == 64 and all(ch in '0123456789abcdef' for ch in txid.lower()):
                return txid
            last_err = f'sendrawtransaction 返回非法txid: {txid!r}'
            continue
        except Exception as e:
            last_err = str(e)
            if _chain_too_long_err(last_err):
                raise ChainTooLong(last_err)
    if _chain_too_long_err(last_err):
        raise ChainTooLong(last_err)
    raise RuntimeError(last_err or '铭文交易构造失败')
class ChainTooLong(Exception):
    pass
def _process_minting_order(c, o, max_items=20):
    try:
        seed_ids = json.loads(o['seed_ids'] or '[]')
    except Exception:
        seed_ids = []
    if not seed_ids:
        return o['status']
    ph = ','.join('?'*len(seed_ids))
    rows = c.execute(f"SELECT idx,seed,status,txid FROM seeds WHERE idx IN ({ph}) ORDER BY idx", seed_ids).fetchall()
    done = 0
    for r in rows:
        if r['status'] == 'inscribed':
            done += 1
            continue
        if r['status'] != 'locked':
            continue
        if max_items <= 0:
            break
        depth = _unconfirmed_chain_depth(MINT_WALLET)
        if depth >= CHAIN_SAFE_LIMIT:
            break
        try:
            txid = _inscribe_seed_to_addr(r['seed'], o['recv_addr'])
        except ChainTooLong:
            break
        if not (isinstance(txid, str) and len(txid) == 64 and all(ch in '0123456789abcdef' for ch in txid.lower())):
            continue
        now = int(time.time())
        c.execute("UPDATE seeds SET status='inscribed', txid=?, owner_addr=?, inscribed_at=? WHERE idx=? AND order_id=? AND status='locked'",
                  (txid, o['recv_addr'], now, r['idx'], o['order_id']))
        try:
            c.commit()
        except Exception:
            pass
        try:
            _track_address(o['recv_addr'])
        except Exception:
            pass
        done += 1
        max_items -= 1
    if done >= len(rows):
        c.execute("UPDATE orders SET status='completed' WHERE order_id=? AND status='minting'", (o['order_id'],))
        return 'completed'
    return 'minting'
def _mint_worker_loop():
    while True:
        try:
            c = db()
            c.execute("UPDATE orders SET status='minting' WHERE status='paid'")
            c.commit()
            _now = int(time.time())
            try:
                exp_orders = c.execute(
                    "SELECT order_id FROM orders WHERE "
                    "(status='awaiting' AND ? > COALESCE(expires_at,0)) OR "
                    "(status='payment_seen' AND (pay_txid IS NULL OR pay_txid='') AND ? > COALESCE(expires_at,0)+86400)",
                    (_now, _now)).fetchall()
                for eo in exp_orders:
                    c.execute("UPDATE orders SET status='expired' WHERE order_id=? AND status IN('awaiting','payment_seen')", (eo['order_id'],))
                    c.execute("UPDATE seeds SET status='free', order_id=NULL, txid=NULL, owner_addr=NULL, locked_at=NULL, inscribed_at=NULL WHERE order_id=? AND status='locked'", (eo['order_id'],))
                if exp_orders:
                    c.commit()
            except Exception:
                c.rollback()
            pend = c.execute(
                "SELECT * FROM orders WHERE status IN('awaiting','payment_seen') "
                "AND pay_txid IS NOT NULL AND pay_txid!='' ORDER BY created_at ASC").fetchall()
            pend += c.execute(
                "SELECT * FROM orders WHERE status IN('awaiting','payment_seen') "
                "AND (pay_txid IS NULL OR pay_txid='') ORDER BY created_at ASC LIMIT 20").fetchall()
            for o in pend:
                try:
                    _refresh_order_state(c, o)
                    c.commit()
                except Exception:
                    c.rollback()
            rows = c.execute("SELECT * FROM orders WHERE status='minting' ORDER BY created_at ASC LIMIT 5").fetchall()
            if rows:
                _ensure_utxo_pool()
            for o in rows:
                try:
                    _process_minting_order(c, o, max_items=20)
                    c.commit()
                except Exception:
                    c.rollback()
            c.close()
        except Exception:
            pass
        time.sleep(3)
def _track_address(addr):
    if not addr:
        return
    c = db()
    try:
        c.execute("INSERT OR IGNORE INTO tracked_addresses(address, first_seen) VALUES(?,?)", (addr, int(time.time())))
        c.commit()
    except Exception:
        pass
    finally:
        c.close()
def _expire_order_release(c, order_id):
    c.execute("UPDATE orders SET status='expired' WHERE order_id=? AND status='awaiting'", (order_id,))
    return c.execute("UPDATE seeds SET status='free', order_id=NULL, txid=NULL, owner_addr=NULL, locked_at=NULL, inscribed_at=NULL WHERE order_id=? AND status='locked'", (order_id,)).rowcount
def _refresh_order_state(c, o):
    st = o['status']
    if st in ('completed', 'expired', 'refunded'):
        return st
    if st == 'minting':
        return _process_minting_order(c, o)
    if st == 'paid':
        c.execute("UPDATE orders SET status='minting' WHERE order_id=? AND status='paid'", (o['order_id'],))
        o2 = c.execute("SELECT * FROM orders WHERE order_id=?", (o['order_id'],)).fetchone()
        return _process_minting_order(c, o2)
    now = int(time.time())
    if now > (o['expires_at'] or 0) and st == 'awaiting':
        _expire_order_release(c, o['order_id'])
        return 'expired'
    if st in ('awaiting', 'payment_seen'):
        pay_track = o['pay_to'] or o['recv_addr']
        mem = c.execute("SELECT txid FROM mempool_txs WHERE address=? AND counterparty=? AND amount_sat>=? AND broadcast_ts>=? ORDER BY broadcast_ts DESC LIMIT 1",
                        (o['recv_addr'], o['pay_to'] or '', int(round(float(o['amount_floor'] or 0)*100000000)), o['created_at'] or 0)).fetchone()
        if mem:
            c.execute("UPDATE orders SET status='payment_seen', pay_txid=COALESCE(pay_txid, ?) WHERE order_id=? AND status='awaiting'", (mem['txid'], o['order_id']))
            st = 'payment_seen'
        txid = o['pay_txid'] or (mem['txid'] if mem else '')
        confirmed = False
        amount_known = False
        if txid:
            try:
                gt = rpc_call('gettransaction', [txid, True], wallet=WALLET)
                pay_to_addr = o['pay_to'] or o['recv_addr']
                recv_amt = 0.0
                conf_n = 0
                if gt:
                    conf_n = gt.get('confirmations', 0) or 0
                    for d in gt.get('details', []):
                        if d.get('category') == 'receive' and d.get('address') == pay_to_addr:
                            recv_amt += float(d.get('amount', 0) or 0)
                if conf_n > 0 and recv_amt > 0:
                    amount_known = True
                    spent = c.execute(
                        "SELECT COALESCE(SUM(amount_floor),0) FROM orders "
                        "WHERE pay_txid=? AND order_id!=? AND status IN('paid','minting','completed')",
                        (txid, o['order_id'])).fetchone()[0] or 0.0
                    remaining = recv_amt - float(spent)
                    confirmed = bool(remaining + 1e-8 >= float(o['amount_floor'] or 0))
                else:
                    confirmed = False
            except Exception:
                confirmed = False
        if not confirmed and not amount_known:
            conf = c.execute("SELECT txid, height FROM wallet_txs WHERE address=? AND txid=? ORDER BY height DESC LIMIT 1", (pay_track, txid)).fetchone()
            confirmed = bool(conf and (conf['height'] or 0) > 0)
        if confirmed:
            c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status IN('awaiting','payment_seen')", (o['order_id'],))
            st = 'paid'
        if (not confirmed) and st == 'payment_seen':
            grace = 3600
            if amount_known and now > (o['expires_at'] or 0) + grace:
                c.execute("UPDATE orders SET status='expired' WHERE order_id=? AND status='payment_seen'", (o['order_id'],))
                c.execute("UPDATE seeds SET status='free', order_id=NULL, txid=NULL, owner_addr=NULL, locked_at=NULL, inscribed_at=NULL WHERE order_id=? AND status='locked'", (o['order_id'],))
                return 'expired'
            if (not txid) and now > (o['expires_at'] or 0) + 86400:
                c.execute("UPDATE orders SET status='expired' WHERE order_id=? AND status='payment_seen'", (o['order_id'],))
                c.execute("UPDATE seeds SET status='free', order_id=NULL, txid=NULL, owner_addr=NULL, locked_at=NULL, inscribed_at=NULL WHERE order_id=? AND status='locked'", (o['order_id'],))
                return 'expired'
    if st == 'paid':
        c.execute("UPDATE orders SET status='minting' WHERE order_id=? AND status='paid'", (o['order_id'],))
        o2 = c.execute("SELECT * FROM orders WHERE order_id=?", (o['order_id'],)).fetchone()
        return _process_minting_order(c, o2)
    return st
def _meta_get(c, key):
    r = c.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    return r['value'] if r else None
def _meta_set(c, key, value):
    c.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)", (key, str(value)))
def _claimed_count(c):
    return c.execute("SELECT COUNT(*) FROM seeds WHERE status!='free'").fetchone()[0]
def _phase_claimed(c, phase_idx):
    return c.execute("SELECT COALESCE(SUM(qty),0) FROM orders WHERE phase_idx=? AND status NOT IN('expired','refunded')", (phase_idx,)).fetchone()[0]
def ensure_treasury_addr(c):
    addr = _meta_get(c, TREASURY_KEY)
    if addr:
        return addr
    addr = rpc_call('getnewaddress', ['stamp_fee', 'bech32'], wallet=WALLET)
    if not addr:
        raise RuntimeError('无法生成铸造收款地址')
    _meta_set(c, TREASURY_KEY, addr)
    c.commit()
    return addr
def ensure_order_pay_to(c):
    addr = rpc_call('getnewaddress', ['mint_order', 'bech32'], wallet=WALLET)
    if not addr:
        raise RuntimeError('无法生成订单收款地址')
    return addr
def _phase2_window(c, now):
    start = _meta_get(c, 'phase2_start_ts')
    if not start:
        start = now
        _meta_set(c, 'phase2_start_ts', start)
        c.commit()
    start = int(start)
    return start, start + PHASE2_SECONDS
def phase_state(inscribed=None, now=None):
    now = int(now or time.time())
    c = db()
    claimed = _claimed_count(c)
    inscribed_count = c.execute("SELECT COUNT(*) FROM seeds WHERE status IN('inscribed','burned')").fetchone()[0]
    try:
        tip = cached_tip()
    except Exception:
        tip = MINT_HEIGHT
    live = True if TEST_MINT_LIVE else (tip >= MINT_HEIGHT)
    p1_used = _phase_claimed(c, 1)
    p2_used = _phase_claimed(c, 2)
    p3_used = _phase_claimed(c, 3)
    p1_left = max(0, PHASES[0]['qty'] - p1_used)
    p2_left = max(0, PHASES[1]['qty'] - p2_used)
    p3_self = max(0, PHASES[2]['qty'] - p3_used)
    if not live:
        active_i, ends_at = 0, None
    else:
        p2_start, p2_end = _phase2_window(c, now)
        if now < p2_end and p2_left > 0:
            active_i, ends_at = 1, p2_end
        else:
            active_i, ends_at = 2, None
    p = PHASES[active_i]
    if active_i == 0:
        available = p1_left
    elif active_i == 1:
        available = p2_left
    else:
        available = p3_self + p1_left + p2_left
    out_phases = []
    for i, ph in enumerate(PHASES):
        if i == 0:
            rem = 0 if active_i == 2 else p1_left
            current = active_i == 0
            started = live
            ended = live and (p1_left <= 0 or active_i == 2)
            status_label = '白名单开放' if (live and p1_left > 0 and active_i != 2) else ('已结束' if live else '待开放')
        elif i == 1:
            rem = 0 if active_i == 2 else p2_left
            current = active_i == 1
            started = live
            ended = live and not current
            status_label = '进行中' if current else ('已结束' if live else '待开放')
        else:
            rem = p3_self + (p1_left + p2_left if active_i == 2 else 0)
            current = active_i == 2
            started = live and current
            ended = False
            status_label = '进行中' if current else '待开放'
        out_phases.append({**ph, 'active': current, 'current': current, 'started': started, 'ended': ended,
                           'status_label': status_label, 'remaining_scope': rem, 'claimed': [p1_used,p2_used,p3_used][i]})
    c.close()
    return {'no': p['no'], 'idx': p['idx'], 'name': p['name'], 'tag': p['tag'], 'price': p['price'],
            'qty': p['qty'], 'available': available, 'ends_at': ends_at,
            'seconds_left': max(0, ends_at - now) if ends_at else None,
            'unlimited': ends_at is None, 'live': live, 'target_height': MINT_HEIGHT, 'tip': tip,
            'block_remaining': max(0, MINT_HEIGHT - tip), 'claimed': claimed,
            'inscribed': inscribed_count, 'phases': out_phases}
def _addr_limit_for_phase(phase_idx):
    return PHASE1_LIMIT_PER_ADDR if phase_idx == 1 else PUBLIC_LIMIT_PER_ADDR
def _phase_for_address(c, addr, now=None):
    now = int(now or time.time())
    ph_pub = phase_state(now=now)
    whitelisted = c.execute("SELECT 1 FROM whitelist_addresses WHERE address=?", (addr,)).fetchone() is not None
    p1_left = max(0, PHASES[0]['qty'] - _phase_claimed(c, 1))
    p2_left = max(0, PHASES[1]['qty'] - _phase_claimed(c, 2))
    p3_self = max(0, PHASES[2]['qty'] - _phase_claimed(c, 3))
    p3_left = p3_self + (p1_left + p2_left if ph_pub.get('idx') == 3 else 0)
    if not ph_pub.get('live'):
        return None, 0, whitelisted, f"铸造将在第 {MINT_HEIGHT} 区块开启"
    if whitelisted and p1_left > 0 and ph_pub.get('idx') != 3:
        ph = {**PHASES[0], 'live': True, 'available': p1_left, 'seconds_left': None, 'unlimited': True}
        return ph, p1_left, whitelisted, None
    if ph_pub['idx'] == 2 and p2_left > 0:
        ph = {**PHASES[1], 'live': True, 'available': p2_left, 'seconds_left': ph_pub.get('seconds_left'), 'unlimited': False}
        return ph, p2_left, whitelisted, None
    if p3_left > 0:
        ph = {**PHASES[2], 'live': True, 'available': p3_left, 'seconds_left': None, 'unlimited': True}
        return ph, p3_left, whitelisted, None
    return None, 0, whitelisted, '本批余量不足'
@app.route('/')
def index():
    try:
        h = cached_tip()
        if (not TEST_FORCE_LIVE) and h < TARGET_HEIGHT:
            return render_template('countdown.html', target=TARGET_HEIGHT,
                                   launch_bj=LAUNCH_BJ, total=TOTAL_SUPPLY, price=PRICE_SHOW,
                                   phases=PHASES, community=COMMUNITY_URL)
    except Exception:
        pass
    return render_template('mint.html', price=PRICE_SHOW, limit=LIMIT_PER_ADDR, total=TOTAL_SUPPLY)
@app.route('/wallet')
def wallet_page():
    return render_template('wallet.html')
@app.route('/mint/')
def mint_path_page():
    try:
        h = cached_tip()
        if (not TEST_FORCE_LIVE) and h < MINT_HEIGHT:
            return redirect('/')
    except Exception:
        pass
    return render_template('mint.html', price=PRICE_SHOW, limit=LIMIT_PER_ADDR, total=TOTAL_SUPPLY)
@app.route('/' + TEST_PATH)
def mint_test_page():
    return render_template('mint.html', price=PRICE_SHOW, limit=LIMIT_PER_ADDR, total=TOTAL_SUPPLY)
_showcase_cache = None
@app.route('/api/showcase')
def showcase():
    global _showcase_cache
    if _showcase_cache is not None:
        return jsonify(_showcase_cache)
    out = []
    try:
        c = db()
        rows = c.execute("SELECT seed FROM seeds ORDER BY idx LIMIT 4000").fetchall()
        c.close()
        seeds = [r['seed'] for r in rows]
        if len(seeds) >= 40:
            picks = random.sample(seeds, 40)
        else:
            picks = seeds
        for s in picks:
            svg, _ = generator.gen(s)
            uri = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()
            out.append(uri)
    except Exception as e:
        print('showcase err', e)
    _showcase_cache = {'items': out}
    return jsonify(_showcase_cache)
@app.route('/api/blockinfo')
def blockinfo():
    now = int(time.time())
    try:
        tip = cached_tip()
    except Exception:
        return jsonify({'error': 'rpc'}), 503
    if now - _rate_cache['t'] > 30 or not _rate_cache['data']:
        try:
            h0 = max(1, tip - RATE_SAMPLE)
            hash_tip = rpc_call('getblockhash', [tip])
            hash_h0 = rpc_call('getblockhash', [h0])
            t_tip = rpc_call('getblockheader', [hash_tip])['time']
            t_h0 = rpc_call('getblockheader', [hash_h0])['time']
            cnt = tip - h0
            avg = (t_tip - t_h0) / cnt if cnt > 0 else 600
            _rate_cache.update({'t': now, 'data': {'avg': avg, 'tip_time': t_tip}})
        except Exception:
            _rate_cache.update({'t': now, 'data': {'avg': 600, 'tip_time': now}})
    avg = _rate_cache['data']['avg']
    remaining = max(0, TARGET_HEIGHT - tip)
    span = max(1, TARGET_HEIGHT - START_HEIGHT)
    done = min(span, max(0, tip - START_HEIGHT))
    progress = round(done / span * 100, 1)
    eta_secs = int(remaining * avg)
    live = (tip >= TARGET_HEIGHT)
    return jsonify({
        'tip': tip, 'target': TARGET_HEIGHT, 'start': START_HEIGHT,
        'remaining': remaining, 'progress': progress,
        'avg_block_secs': round(avg, 1), 'eta_secs': eta_secs,
        'eta_ts': now + eta_secs, 'live': live, 'server_now': now
    })
@app.route('/api/stats')
def stats():
    c = db()
    ins = c.execute("SELECT COUNT(*) FROM seeds WHERE status IN('inscribed','burned')").fetchone()[0]
    c.close()
    phase = phase_state(ins)
    return jsonify({'inscribed': ins, 'total': TOTAL_SUPPLY, 'remaining': TOTAL_SUPPLY-ins,
                    'price': PRICE_SHOW, 'phase': phase})
@app.route('/api/whitelist', methods=['POST'])
def add_whitelist():
    if not _check_admin():
        return jsonify({'error': '未授权'}), 403
    d = request.get_json(force=True) or {}
    addrs = d.get('addresses') or []
    if not isinstance(addrs, list) or not addrs:
        return jsonify({'error': '缺少地址列表'}), 400
    now = int(time.time())
    c = db()
    n = 0
    for a in addrs:
        a = str(a).strip()
        if not a:
            continue
        c.execute('INSERT OR IGNORE INTO whitelist_addresses(address,note,created_at) VALUES(?,?,?)', (a, '', now))
        n += 1
    c.commit(); c.close()
    return jsonify({'ok': True, 'added': n})
def _airdrop_to_address(c, addr, qty=PHASE1_AIRDROP_QTY):
    addr = (addr or '').strip()
    if not addr:
        return {'address': addr, 'ok': False, 'error': '地址为空'}
    try:
        if not rpc_call('validateaddress', [addr]).get('isvalid'):
            return {'address': addr, 'ok': False, 'error': '地址无效'}
    except Exception:
        return {'address': addr, 'ok': False, 'error': '地址校验失败'}
    used = c.execute("SELECT order_id,phase_idx,status FROM orders WHERE recv_addr=? AND status NOT IN('expired','refunded') ORDER BY created_at LIMIT 1", (addr,)).fetchone()
    if used:
        return {'address': addr, 'ok': False, 'skipped': True, 'error': f'已存在第{used["phase_idx"]}批订单', 'order_id': used['order_id'], 'status': used['status']}
    p1_used = _phase_claimed(c, 1)
    p1_left = max(0, PHASES[0]['qty'] - p1_used)
    if qty > p1_left:
        return {'address': addr, 'ok': False, 'error': f'第一批余量不足，仅剩 {p1_left} 枚'}
    rows = c.execute("SELECT idx,seed FROM seeds WHERE status='free' ORDER BY RANDOM() LIMIT ?", (qty,)).fetchall()
    if len(rows) < qty:
        return {'address': addr, 'ok': False, 'error': 'seed 余量不足'}
    now = int(time.time())
    order_id = hashlib.sha256(f"airdrop|{addr}|{now}|{qty}|{os.urandom(6).hex()}".encode()).hexdigest()[:16]
    ids = [r['idx'] for r in rows]
    phm = ','.join('?'*len(ids))
    cur = c.execute(f"UPDATE seeds SET status='locked',order_id=?,locked_at=? WHERE idx IN ({phm}) AND status='free'", [order_id, now]+ids)
    if cur.rowcount != qty:
        return {'address': addr, 'ok': False, 'error': '并发冲突'}
    c.execute("INSERT INTO orders(order_id,qty,recv_addr,pay_addr,pay_to,auth_msg,auth_sig,amount_floor,amount_show,seed_ids,status,created_at,expires_at,phase_idx) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (order_id, qty, addr, None, None, 'AIRDROP', 'AIRDROP', 0, 0, json.dumps(ids), 'minting', now, now + 30*24*60*60, 1))
    c.execute('INSERT OR IGNORE INTO whitelist_addresses(address,note,created_at) VALUES(?,?,?)', (addr, 'airdrop', now))
    return {'address': addr, 'ok': True, 'order_id': order_id, 'qty': qty, 'seeds': [r['seed'] for r in rows]}
@app.route('/api/airdrop/whitelist', methods=['POST'])
def airdrop_whitelist():
    if not _check_admin():
        return jsonify({'error': '未授权'}), 403
    d = request.get_json(force=True) or {}
    addrs = d.get('addresses') or []
    qty = int(d.get('qty') or PHASE1_AIRDROP_QTY)
    if qty < 1 or qty > PHASE1_LIMIT_PER_ADDR:
        return jsonify({'error': f'数量需 1~{PHASE1_LIMIT_PER_ADDR}'}), 400
    if isinstance(addrs, str):
        addrs = re.split(r'[\s,，]+', addrs)
    if not isinstance(addrs, list) or not addrs:
        return jsonify({'error': '缺少地址列表'}), 400
    clean = []
    seen = set()
    for a in addrs:
        a = str(a).strip()
        if a and a not in seen:
            clean.append(a); seen.add(a)
    c = db()
    results = []
    ok = 0
    try:
        for a in clean:
            r = _airdrop_to_address(c, a, qty)
            results.append(r)
            if r.get('ok'):
                ok += 1
        c.commit()
    except Exception as e:
        c.rollback(); c.close()
        return jsonify({'error': str(e), 'results': results}), 500
    c.close()
    return jsonify({'ok': True, 'requested': len(clean), 'created': ok, 'qty_each': qty, 'results': results})
@app.route('/api/preview')
def preview():
    c = db()
    rows = c.execute("SELECT seed FROM seeds WHERE status='free' ORDER BY idx LIMIT 8").fetchall()
    c.close()
    out = []
    for r in rows:
        svg, info = generator.gen(r['seed'])
        out.append({'seed': r['seed'], 'svg': svg, 'head': info[0], 'rarity': info[1]})
    return jsonify({'previews': out})
@app.route('/api/eligibility')
def eligibility():
    addr = (request.args.get('addr') or '').strip()
    if not addr:
        return jsonify({'connected': False, 'eligible': False, 'reason': '未连接钱包'})
    try:
        if not rpc_call('validateaddress', [addr]).get('isvalid'):
            return jsonify({'connected': True, 'eligible': False, 'reason': '钱包地址无效'}), 400
    except Exception:
        return jsonify({'connected': True, 'eligible': False, 'reason': '钱包地址校验失败'}), 400
    c = db()
    ph, avail, whitelisted, phase_err = _phase_for_address(c, addr)
    held = c.execute("SELECT COUNT(*) FROM seeds WHERE owner_addr=? AND status IN('inscribed','minting')", (addr,)).fetchone()[0]
    pending = c.execute("SELECT COALESCE(SUM(qty),0) FROM orders WHERE recv_addr=? AND status IN('awaiting','payment_seen','paid','minting')", (addr,)).fetchone()[0]
    minted = held + pending
    got_p1 = c.execute("SELECT 1 FROM orders WHERE recv_addr=? AND phase_idx=1 AND status NOT IN('expired','refunded') LIMIT 1", (addr,)).fetchone() is not None
    c.close()
    remaining_quota = max(0, LIMIT_PER_ADDR - minted)
    eligible = True; reason = '符合当前批次资格'
    if ph and ph.get('idx') == 1:
        eligible = False
        reason = '已领取第一批空投' if got_p1 else '第一批为空投发放，无需连接钱包或签名'
    elif phase_err:
        eligible = False; reason = phase_err
    elif not ph:
        eligible = False; reason = '当前批次不可参与'
    elif remaining_quota <= 0:
        eligible = False; reason = f'该地址已达每地址上限 {LIMIT_PER_ADDR} 枚'
    elif minted > 0:
        reason = f'已铸 {minted} 枚，还可铸 {remaining_quota} 枚'
    return jsonify({'address': addr, 'eligible': eligible, 'reason': reason,
                    'whitelisted': whitelisted, 'minted': minted, 'remaining_quota': remaining_quota,
                    'limit': LIMIT_PER_ADDR, 'phase': ph})
@app.route('/api/mint_token')
def api_mint_token():
    if not _check_origin():
        return jsonify({'error': '非法来源'}), 403
    return jsonify({'token': issue_mint_token(), 'ttl': MINT_TOKEN_TTL})
@app.route('/api/order', methods=['POST'])
def create_order():
    if not _check_origin():
        return jsonify({'error': '请通过官网铸造页面操作'}), 403
    d = request.get_json(force=True)
    token = (d.get('mint_token') or request.headers.get('X-Mint-Token') or '').strip()
    if not token:
        return jsonify({'error': '缺少铸造令牌，请刷新页面重试'}), 403
    ok_tok, tok_err = verify_mint_token(token)
    if not ok_tok:
        return jsonify({'error': tok_err}), 403
    qty = int(d.get('qty', 1))
    recv = (d.get('recv_addr') or '').strip()
    auth_msg = (d.get('auth_msg') or '').strip()
    auth_sig = (d.get('auth_sig') or '').strip()
    try:
        if not rpc_call('validateaddress', [recv]).get('isvalid'):
            return jsonify({'error': '接收地址无效'}), 400
    except Exception:
        return jsonify({'error': '接收地址校验失败'}), 400
    c = db()
    ph, avail, whitelisted, phase_err = _phase_for_address(c, recv)
    if phase_err or not ph:
        c.close(); return jsonify({'error': phase_err or '当前批次不可参与'}), 400
    if ph['idx'] == 1:
        c.close(); return jsonify({'error': '第一批为空投发放，无需用户签名或下单'}), 400
    if qty < 1 or qty > _addr_limit_for_phase(ph['idx']):
        c.close(); return jsonify({'error': f'数量需 1~{_addr_limit_for_phase(ph["idx"])}'}), 400
    dup_p1 = c.execute("SELECT 1 FROM orders WHERE recv_addr=? AND phase_idx=1 AND status NOT IN('expired','refunded') LIMIT 1", (recv,)).fetchone()
    if ph['idx'] == 1 and dup_p1:
        c.close(); return jsonify({'error': '该地址已领取第一批空投，不能重复领取'}), 400
    if phase_err:
        c.close(); return jsonify({'error': phase_err}), 400
    if qty > avail:
        c.close(); return jsonify({'error': f'本批最多还能铸 {avail} 枚'}), 400
    if ph['idx'] == 1 and not whitelisted:
        c.close(); return jsonify({'error': '当前为第一批白名单免费铸造，该地址不在白名单'}), 403
    if ph['idx'] == 1:
        af = ash = 0
        pay_to = None
        if not auth_msg or not auth_sig:
            c.close(); return jsonify({'error': '第一批需要钱包签名'}), 400
    elif ph['idx'] == 2:
        af = ash = round(qty * 2.11, 8)
        try:
            pay_to = ensure_treasury_addr(c)
        except Exception as e:
            c.close(); return jsonify({'error': f'收款地址初始化失败: {e}'}), 500
    else:
        af = ash = round(qty * 4.22, 8)
        try:
            pay_to = ensure_treasury_addr(c)
        except Exception as e:
            c.close(); return jsonify({'error': f'收款地址初始化失败: {e}'}), 500
    held = c.execute("SELECT COUNT(*) FROM seeds WHERE owner_addr=? AND status IN('inscribed','minting')", (recv,)).fetchone()[0]
    pending = c.execute("SELECT COALESCE(SUM(qty),0) FROM orders WHERE recv_addr=? AND status IN('awaiting','payment_seen','paid','minting')", (recv,)).fetchone()[0]
    if held + pending + qty > LIMIT_PER_ADDR:
        c.close(); return jsonify({'error': f'超限购: 已持有/进行中 {held+pending}, 本单 {qty}, 上限 {LIMIT_PER_ADDR}'}), 400
    now = int(time.time())
    order_id = hashlib.sha256(f"{recv}{now}{qty}{os.urandom(6).hex()}".encode()).hexdigest()[:16]
    try:
        cur = c.execute(
            "UPDATE seeds SET status='locked',order_id=?,locked_at=? "
            "WHERE idx IN (SELECT idx FROM seeds WHERE status='free' ORDER BY RANDOM() LIMIT ?) AND status='free'",
            (order_id, now, qty))
        if cur.rowcount != qty:
            c.rollback(); c.close(); return jsonify({'error': '余量不足或并发冲突,请重试'}), 409
        rows = c.execute("SELECT idx,seed FROM seeds WHERE order_id=? ORDER BY idx", (order_id,)).fetchall()
        ids = [r['idx'] for r in rows]
        c.execute("INSERT INTO orders(order_id,qty,recv_addr,pay_addr,pay_to,auth_msg,auth_sig,amount_floor,amount_show,seed_ids,status,created_at,expires_at,phase_idx) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (order_id, qty, recv, None, pay_to, auth_msg, auth_sig, af, ash, json.dumps(ids), 'minting' if ph['idx'] == 1 else 'awaiting', now, now + (ORDER_TTL if ph['idx'] != 1 else 30*24*60*60), ph['idx']))
        c.commit()
    except Exception as e:
        try: c.rollback()
        except Exception: pass
        c.close(); return jsonify({'error': f'下单失败: {e}'}), 500
    c.close()
    return jsonify({'order_id': order_id, 'qty': qty, 'amount_show': ash,
                    'amount_floor': af, 'expires_at': now + (ORDER_TTL if ph['idx'] != 1 else 30*24*60*60),
                    'phase_idx': ph['idx'], 'free': ph['idx'] == 1, 'whitelisted': whitelisted,
                    'pay_to': pay_to, 'status': 'minting' if ph['idx'] == 1 else 'awaiting',
                    'seeds': [r['seed'] for r in rows]})
@app.route('/api/mint/build', methods=['POST'])
def mint_build():
    d = request.get_json(force=True) or {}
    order_id = (d.get('order_id') or '').strip()
    frm = (d.get('from') or '').strip()
    if not order_id:
        return jsonify({'error': '缺少订单'}), 400
    if not frm:
        return jsonify({'error': '缺少钱包地址'}), 400
    c = db()
    o = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    c.close()
    if not o:
        return jsonify({'error': '订单不存在'}), 404
    try:
        if not rpc_call('validateaddress', [frm]).get('isvalid'):
            return jsonify({'error': '钱包地址无效'}), 400
    except Exception:
        return jsonify({'error': '钱包地址校验失败'}), 400
    pay_to = (o['pay_to'] or '').strip() if o['pay_to'] else None
    if float(o['amount_show'] or 0) <= 0:
        return jsonify({'error': '免费订单不需要签名付款'}), 400
    if not pay_to:
        return jsonify({'error': '订单缺少收款地址'}), 500
    return wallet_api_mod._build_transfer(frm, pay_to, {'amount': o['amount_show']})
@app.route('/api/order/<order_id>/cancel', methods=['POST'])
def cancel_order(order_id):
    d = request.get_json(silent=True) or {}
    recv = (d.get('recv_addr') or '').strip()
    c = db()
    o = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not o:
        c.close(); return jsonify({'error': '订单不存在'}), 404
    if recv and recv != o['recv_addr']:
        c.close(); return jsonify({'error': '地址不匹配'}), 403
    if o['status'] != 'awaiting':
        c.close(); return jsonify({'ok': True, 'status': o['status'], 'released': 0})
    released = _expire_order_release(c, order_id)
    c.commit(); c.close()
    return jsonify({'ok': True, 'status': 'expired', 'released': released})
@app.route('/api/order/<order_id>')
def order_status(order_id):
    c = db()
    o = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not o:
        c.close(); return jsonify({'error': 'not found'}), 404
    st = _refresh_order_state(c, o)
    c.commit()
    o = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    seeds = json.loads(o['seed_ids']); ph = ','.join('?'*len(seeds))
    items = c.execute(f"SELECT seed,status,txid FROM seeds WHERE idx IN ({ph})", seeds).fetchall()
    c.close()
    inscribed_n = sum(1 for i in items if i['status'] == 'inscribed' and i['txid'])
    total_n = len(items)
    pending_n = total_n - inscribed_n
    return jsonify({'order_id': order_id, 'status': o['status'], 'qty': o['qty'], 'amount_show': o['amount_show'],
                    'expires_at': o['expires_at'],
                    'paid_amount': o['paid_amount'],
                    'inscribed': inscribed_n, 'total': total_n, 'pending': pending_n,
                    'items': [{'seed': i['seed'], 'status': i['status'], 'txid': i['txid']} for i in items]})
init_db()
ensure_seed_pool()
if __name__ == '__main__':
    if os.environ.get('CCSTAMP_NO_WORKER') != '1':
        threading.Thread(target=_mint_worker_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5002, debug=False)
