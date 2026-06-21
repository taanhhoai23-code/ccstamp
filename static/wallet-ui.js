(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const COIN = 1e8;
  const fmt = (sats) => (sats / COIN).toFixed(8).replace(/\.?0+$/, '') || '0';
  const short = (a) => a ? a.slice(0, 10) + '…' + a.slice(-8) : '—';

  let state = {
    mnemonic: null,      // 创建流程临时持有(未保存前)
    verify: null,        // {positions:[i,j,k], answers:[...]}
    pendingTx: null,     // 待签名的 {psbt, inputs, summary, kind}
    addr: null,
    insList: [],
    walletIdx: 0,        // 当前激活的助记词钱包下标(核心库 _wallets 中)
    sel: 'hd:0',         // 当前选中: 'hd:N'(第N个助记词钱包) 或 'imp:地址'
    isImport: false,     // 当前地址是否为导入私钥地址
    impGroup: null,      // 当前选中的导入组 id(聚合该组全部地址)
    createMode: 'first', // 'first'=本机第一个钱包(走设密码) | 'add'=已解锁下新增(复用会话密码)
  };

  const META_KEY = 'ccstamp_wallet_meta';
  const HD_GAP = 20;

  const LOCK_KEY = 'ccstamp_autolock_ms';
  let _lockTimer = null;
  function autoLockMs() {
    const v = parseInt(localStorage.getItem(LOCK_KEY));
    return isNaN(v) ? 1800000 : v;   // 默认 30 分钟
  }
  function resetLockTimer() {
    if (_lockTimer) { clearTimeout(_lockTimer); _lockTimer = null; }
    const ms = autoLockMs();
    if (ms > 0 && BTCCWallet.isUnlocked && BTCCWallet.isUnlocked()) {
      _lockTimer = setTimeout(() => { lock(); toast('已自动锁定'); }, ms);
    }
  }
  function bindActivity() {
    ['click', 'keydown', 'touchstart', 'mousemove'].forEach(ev =>
      document.addEventListener(ev, () => resetLockTimer(), { passive: true }));
  }
  function setAutoLock(ms) {
    localStorage.setItem(LOCK_KEY, String(ms));
    resetLockTimer();
    toast(ms === '0' || ms === 0 ? '已关闭自动锁定' : '已更新自动锁定');
  }

  function toast(msg) {
    const t = $('toast'); t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 1800);
  }
  function setNet(on, txt) {
    $('netDot').classList.toggle('off', !on);
    $('netTxt').textContent = txt;
  }

  function go(view) {
    document.querySelectorAll('.view').forEach(v => v.classList.add('hide'));
    const el = $('v-' + view);
    if (el) el.classList.remove('hide');
    document.body.classList.toggle('centered', ['welcome', 'unlock'].includes(view));
    if (view === 'create') initCreate();
    if (view === 'import') initImport();
    if (view === 'send') initSend();
    if (view === 'receive') initReceive();
    if (view === 'delete') { $('delPw').value = ''; $('delErr').textContent = ''; }
    window.scrollTo(0, 0);
  }

  function boot() {
    document.body.classList.remove('boot-welcome', 'boot-unlock');
    if (!window.BTCCWallet) { alert('钱包核心加载失败，请刷新'); return; }
    if (!BTCCWallet.exists()) { go('welcome'); setNet(false, '无钱包'); }
    else if (BTCCWallet.isUnlocked()) { enterHome(); }
    else { go('unlock'); setNet(false, '已锁定'); }
  }

  function initCreate() {
    state.mnemonic = BTCCWallet.generateMnemonic(128);  // 12 词
    state.createMode = (BTCCWallet.exists() && BTCCWallet.isUnlocked()) ? 'add' : 'first';
    const words = state.mnemonic.split(' ');
    const grid = $('mnGrid'); grid.innerHTML = '';
    words.forEach((w, i) => {
      const d = document.createElement('div'); d.className = 'mn-cell';
      d.innerHTML = `<span class="i">${i + 1}</span><span>${w}</span>`;
      grid.appendChild(d);
    });
    const isAdd = state.createMode === 'add';
    const pwWrap = $('cPwWrap'); if (pwWrap) pwWrap.classList.toggle('hide', isAdd);
    const cFin = $('cFinish'); if (cFin) { cFin.textContent = '创建钱包'; cFin.disabled = false; }
    const addNote = $('cAddNote'); if (addNote) addNote.classList.toggle('hide', !isAdd);
    stepTo(0);
    $('cPw1').value = ''; $('cPw2').value = ''; $('cPwErr').textContent = '';
  }
  function stepTo(n) {
    [0, 1, 2].forEach(i => {
      $('c-step' + i).classList.toggle('hide', i !== n);
      $('cs' + i).classList.toggle('on', i <= n);
    });
  }
  function toVerify() {
    const words = state.mnemonic.split(' ');
    const idxs = [];
    while (idxs.length < 3) {
      const r = Math.floor(Math.random() * words.length);
      if (!idxs.includes(r)) idxs.push(r);
    }
    idxs.sort((a, b) => a - b);
    state.verify = { positions: idxs, picked: [null, null, null] };
    const box = $('verifyBox'); box.innerHTML = '';
    idxs.forEach((pos, qi) => {
      const correct = words[pos];
      const opts = new Set([correct]);
      while (opts.size < 6) {
        const w = words[Math.floor(Math.random() * words.length)];
        opts.add(w);
      }
      const shuffled = [...opts].sort(() => Math.random() - 0.5);
      const q = document.createElement('div');
      q.innerHTML = `<div class="verify-q">第 <b>${pos + 1}</b> 个词是？</div>`;
      const row = document.createElement('div'); row.className = 'word-opts';
      shuffled.forEach(w => {
        const b = document.createElement('div'); b.className = 'word-opt'; b.textContent = w;
        b.onclick = () => {
          row.querySelectorAll('.word-opt').forEach(x => x.classList.remove('sel'));
          b.classList.add('sel'); state.verify.picked[qi] = w; $('verifyErr').textContent = '';
        };
        row.appendChild(b);
      });
      q.appendChild(row); box.appendChild(q);
    });
    if (!$('verifyNext')) {
      const btn = document.createElement('button');
      btn.className = 'btn'; btn.id = 'verifyNext'; btn.style.marginTop = '8px';
      btn.textContent = '验证'; btn.onclick = checkVerify;
      $('c-step1').appendChild(btn);
    }
    stepTo(1);
  }
  function checkVerify() {
    const v = state.verify;
    const words = state.mnemonic.split(' ');
    for (let i = 0; i < 3; i++) {
      if (v.picked[i] !== words[v.positions[i]]) {
        $('verifyErr').textContent = '选择有误，请对照你抄写的助记词重新选择。';
        return;
      }
    }
    stepTo(2);
  }
  async function finishCreate() {
    const btn = $('cFinish');
    if (state.createMode === 'add' && BTCCWallet.isUnlocked()) {
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
      try {
        const r = await BTCCWallet.importWalletMnemonic(state.mnemonic, '');
        state.mnemonic = null;
        state.walletIdx = r.index; state.sel = 'hd:' + r.index; state.isImport = false;
        toast('已新建钱包');
        enterHome();
      } catch (e) {
        $('cPwErr').textContent = '新建失败: ' + e.message;
        btn.disabled = false; btn.textContent = '创建钱包';
      }
      return;
    }
    const p1 = $('cPw1').value, p2 = $('cPw2').value;
    if (p1.length < 8) { $('cPwErr').textContent = '密码至少 8 位'; return; }
    if (p1 !== p2) { $('cPwErr').textContent = '两次密码不一致'; return; }
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    try {
      await BTCCWallet.save(state.mnemonic, p1);   // 加密存 + 解锁
      state.mnemonic = null;                        // 立刻从内存清掉明文
      state.walletIdx = 0; state.sel = 'hd:0'; state.isImport = false;
      toast('钱包已创建');
      enterHome();
    } catch (e) {
      $('cPwErr').textContent = '创建失败: ' + e.message;
      btn.disabled = false; btn.textContent = '创建钱包';
    }
  }

  function initImport() {
    state.createMode = (BTCCWallet.exists() && BTCCWallet.isUnlocked()) ? 'add' : 'first';
    const isAdd = state.createMode === 'add';
    const pwWrap = $('impPwWrap'); if (pwWrap) pwWrap.classList.toggle('hide', isAdd);
    const addNote = $('impAddNote'); if (addNote) addNote.classList.toggle('hide', !isAdd);
    $('impMn').value = ''; $('impPw1').value = ''; $('impPw2').value = '';
    $('impErr').textContent = '';
  }
  async function finishImport() {
    const mn = $('impMn').value.trim().replace(/\s+/g, ' ');
    const err = $('impErr'); err.textContent = '';
    if (!BTCCWallet.validateMnemonic(mn)) { err.textContent = '助记词无效，请检查拼写与词数'; return; }
    if (state.createMode === 'add' && BTCCWallet.isUnlocked()) {
      try {
        const r = await BTCCWallet.importWalletMnemonic(mn, '');
        $('impMn').value = '';
        state.walletIdx = r.index; state.sel = 'hd:' + r.index; state.isImport = false;
        toast(r.dup ? '该助记词已在钱包列表中，已切过去' : '已作为新钱包导入');
        enterHome();
      } catch (e) { err.textContent = '导入失败: ' + e.message; }
      return;
    }
    const p1 = $('impPw1').value, p2 = $('impPw2').value;
    if (p1.length < 8) { err.textContent = '密码至少 8 位'; return; }
    if (p1 !== p2) { err.textContent = '两次密码不一致'; return; }
    try {
      await BTCCWallet.save(mn, p1);
      $('impMn').value = '';
      state.walletIdx = 0; state.sel = 'hd:0'; state.isImport = false;
      toast('钱包已导入');
      enterHome();
    } catch (e) { err.textContent = '导入失败: ' + e.message; }
  }

  function previewImportKey() {
    let raw = $('impKeyInput').value.trim();
    const box = $('impKeyPreview'); const err = $('impKeyErr');
    err.textContent = ''; box.innerHTML = '';
    if (!raw) return;
    raw = raw.replace(/^["'\s]+|["'\s]+$/g, '');
    const wpkhMatch = /wpkh\s*\(/i.exec(raw);
    try {
      if (wpkhMatch) {
        const sub = raw.slice(wpkhMatch.index);
        const metas = BTCCWallet.parseDescriptor ? BTCCWallet.parseDescriptor(sub, 1) : null;
        if (metas && metas.length) {
          box.innerHTML = '<div>Descriptor 已识别，首地址：<span class="mono">' + metas[0].address + '</span><div class="muted" style="margin-top:4px">确认后将导入收款链与找零链的多个地址（聚合为一个钱包），覆盖整个节点钱包余额。</div></div>';
        } else {
          box.innerHTML = '<div class="muted">Descriptor 已识别，确认后将解析并导入其中地址。</div>';
        }
      } else {
        const addr = BTCCWallet.previewWIF(raw);
        box.innerHTML = '<div>将导入地址：<span class="mono">' + addr + '</span></div>';
      }
    } catch (e) {
      const msg = (e && e.message) ? e.message : String(e);
      if (wpkhMatch) {
        err.textContent = 'descriptor 解析失败：' + msg + '（请确认复制的是 listdescriptors 里 /0 }
    if (btn) {
      btn.disabled = false;
      btn.classList.remove('loading');
      btn.textContent = btnOld || '刷新';
      if (balOk) toast('已刷新');
    }
  }

  function switchTab(name) {
    state.curTab = name;
    $('tab-tx').classList.toggle('active', name === 'tx');
    $('tab-ins').classList.toggle('active', name === 'ins');
    $('panel-tx').classList.toggle('hide', name !== 'tx');
    $('panel-ins').classList.toggle('hide', name !== 'ins');
  }

  function shortAddr(a) {
    if (!a) return '—';
    return a.length > 16 ? a.slice(0, 8) + '…' + a.slice(-6) : a;
  }
  function fmtTs(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  async function loadHistory() {
    const wrap = $('txWrap');
    try {
      const r = await fetch('/api/wallet/history?limit=80', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ addresses: activeAddrs() })
      }).then(x => x.json());
      const items = r.items || [];
      if (!items.length) {
        wrap.innerHTML = '<div class="empty">还没有交易。收款或转账后会出现在这里。</div>';
        return;
      }
      const list = document.createElement('div'); list.className = 'tx-list';
      items.forEach((it) => {
        const row = document.createElement('div');
        row.className = 'tx-row ' + (it.direction === 'in' ? 'in' : 'out');
        const dirIcon = it.direction === 'in' ? '↙' : '↗';
        const dirLabel = it.direction === 'in' ? '收款' : '转账';
        const typeTag = it.type === 'inscription' ? '<span class="tag">铭文</span>' : '';
        const sign = it.direction === 'in' ? '+' : '−';
        const amt = (it.amount_sats / 1e8).toFixed(8).replace(/\.?0+$/, '');
        const confClass = (it.state === 'dropped') ? 'dropped' : (it.pending ? 'unconfirmed' : (it.confirmations >= 1 ? '' : 'unconfirmed'));
        const confTxt = (it.state === 'dropped')
          ? '广播失败'
          : (it.confirmations >= 1 ? `${it.confirmations} 确认` : (it.pending ? '确认中' : '待确认'));
        row.innerHTML =
          `<div class="dir">${dirIcon}</div>` +
          `<div class="info">` +
            `<div class="l1">${dirLabel}${typeTag}<span class="muted mono">${fmtTs(it.block_time)}</span></div>` +
            `<div class="l2">${it.direction === 'in' ? '来自 ' : '至 '}${shortAddr(it.counterparty)}</div>` +
          `</div>` +
          `<div class="amt">${sign}${amt} BTCC<span class="c ${confClass}">${confTxt}</span></div>`;
        row.onclick = () => window.open('https://explorer.btc-classic.org/tx/' + it.txid, '_blank');
        list.appendChild(row);
      });
      wrap.innerHTML = '';
      wrap.appendChild(list);
    } catch (e) {
      wrap.innerHTML = '<div class="empty">交易记录加载失败</div>';
    }
  }
  async function loadInscriptions() {
    const wrap = $('insWrap');
    try {
      const r = await fetch('/api/wallet/inscriptions', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        body: JSON.stringify({ addresses: activeAddrs() })
      }).then(x => x.json());
      state.insList = r.inscriptions || [];
      $('insCount').textContent = (r.count || 0) + ' 枚';
      if (!state.insList.length) {
        wrap.innerHTML = '<div class="empty">还没有铭文。在铸造台铸造后会出现在这里。</div>';
        return;
      }
      const grid = document.createElement('div'); grid.className = 'ins-grid';
      state.insList.forEach((it, i) => {
        const card = document.createElement('div'); card.className = 'ins';
        const art = it.svg ? it.svg : '<div style="aspect-ratio:1;background:#f5f5f5"></div>';
        card.innerHTML = art +
          `<div class="meta"><div class="h">${it.head || '#' + (i + 1)}</div>` +
          `<div class="r">${it.rarity || ''}</div></div>`;
        card.onclick = () => showInsDetail(i);
        grid.appendChild(card);
      });
      wrap.innerHTML = ''; wrap.appendChild(grid);
    } catch (e) {
      wrap.innerHTML = '<div class="empty">铭文加载失败，请刷新</div>';
    }
  }

  function showInsDetail(i) {
    const it = state.insList[i];
    const d = $('insDetail');
    const status = it.confirmations >= 1 ? `${it.confirmations} 确认，可转移` : '等待区块确认后可转移';
    const disabled = it.transferable ? '' : 'disabled';
    const btnText = it.transferable ? '转移这枚铭文' : '待确认，暂不可转移';
    const detailSvg = (it.svg || '').replace(/id='([^']+)'/g, "id='$1_detail'").replace(/url\(#([^\)]+)\)/g, 'url(#$1_detail)');
    d.innerHTML = `
      <div style="max-width:260px;margin:0 auto 14px;border:1px solid var(--line);border-radius:14px;overflow:hidden">${detailSvg}</div>
      <div style="display:flex;gap:10px;max-width:260px;margin:0 auto 20px">
        <a class="btn ghost" style="flex:1;text-align:center;text-decoration:none;padding:9px 0;font-size:13px" href="/api/wallet/stamp/${it.seed}.png?size=2048" download>下载</a>
        <a class="btn ghost" style="flex:1;text-align:center;text-decoration:none;padding:9px 0;font-size:13px" href="/api/wallet/stamp/${it.seed}.svg" download>SVG</a>
      </div>
      <h1 style="text-align:center">${it.head || '铭文'}</h1>
      <p class="lead center">${it.rarity || ''}</p>
      <div class="kv"><span class="k">Seed</span><span class="v">${it.seed}</span></div>
      <div class="kv"><span class="k">载体交易</span><span class="v">${short(it.txid)}:${it.vout}</span></div>
      <div class="kv"><span class="k">状态</span><span class="v">${status}</span></div>
      <label>转移给（BTCC 地址）</label>
      <input type="text" id="insTo" class="mono" placeholder="cc1q..." ${disabled}>
      <div class="err" id="insErr"></div>
      <button class="btn" style="margin-top:18px" onclick="W.prepareInsTransfer(${i})" ${disabled}>${btnText}</button>
    `;
    go('ins');
  }
  async function prepareInsTransfer(i) {
    const it = state.insList[i];
    const to = $('insTo').value.trim();
    const err = $('insErr'); err.textContent = '';
    if (!it.transferable || (it.confirmations || 0) < 1) { err.textContent = '这枚铭文还在等待区块确认，确认后才能转移'; return; }
    if (!/^cc1[0-9a-z]{20,90}$/.test(to)) { err.textContent = '收款地址格式不正确'; return; }
    const owner = it.owner || state.addr;
    if (to === owner) { err.textContent = '不能转给自己'; return; }
    try {
      const r = await fetch('/api/wallet/build', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'inscription', from: owner, to, seed: it.seed,
                               carrier: { txid: it.txid, vout: it.vout },
                               from_addresses: activeAddrs() })   // 补付手续费可用名下任意地址的币
      }).then(x => x.json());
      if (r.error) { err.textContent = r.error; return; }
      state.pendingTx = { ...r, kind: 'inscription' };
      openSign({
        title: '转移铭文',
        rows: [
          ['操作', '转移铭文 NFT'],
          ['铭文', it.head || it.seed],
          ['Seed', it.seed],
          ['转给', short(to)],
          ['手续费', fmt(r.fee_sats) + ' BTCC'],
        ]
      });
    } catch (e) { err.textContent = '构造失败: ' + e.message; }
  }

  let _bal = { spendable_sats: 0 };
  function initSend() {
    $('sendTo').value = ''; $('sendAmt').value = ''; $('sendErr').textContent = '';
    fetch('/api/wallet/utxos', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ addresses: activeAddrs() })
    }).then(x => x.json()).then(r => {
      _bal = r;
      $('sendBalHint').textContent = '可用 ' + fmt(r.spendable_sats) + ' BTCC';
    });
  }
  async function prepareSend() {
    const to = $('sendTo').value.trim();
    const amt = parseFloat($('sendAmt').value);
    const err = $('sendErr'); err.textContent = '';
    if (!/^cc1[0-9a-z]{20,90}$/.test(to)) { err.textContent = '收款地址格式不正确'; return; }
    if (!(amt > 0)) { err.textContent = '请输入有效金额'; return; }
    const amtSats = Math.round(amt * COIN);
    if (amtSats > _bal.spendable_sats) { err.textContent = '余额不足'; return; }
    const btn = $('sendBtn'); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    try {
      const r = await fetch('/api/wallet/build', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'transfer', from: state.addr, to, amount: amt,
                               from_addresses: activeAddrs() })   // 跨名下所有地址凑币, 找零回主地址
      }).then(x => x.json());
      btn.disabled = false; btn.textContent = '下一步';
      if (r.error) { err.textContent = r.error; return; }
      state.pendingTx = { ...r, kind: 'transfer' };
      openSign({
        title: '确认转账',
        rows: [
          ['金额', fmt(Math.round(amt * COIN)) + ' BTCC'],
          ['转给', short(to)],
          ['手续费', fmt(r.fee_sats) + ' BTCC'],
          ['合计', fmt(Math.round(amt * COIN) + r.fee_sats) + ' BTCC'],
        ], big: 0
      });
    } catch (e) { btn.disabled = false; btn.textContent = '下一步'; err.textContent = '构造失败: ' + e.message; }
  }

  function openSign({ title, rows, big }) {
    $('signTitle').textContent = title;
    $('signErr').textContent = '';
    const body = $('signBody'); body.innerHTML = '';
    rows.forEach(([k, v], i) => {
      const d = document.createElement('div'); d.className = 'kv';
      d.innerHTML = `<span class="k">${k}</span><span class="v${i === big ? ' big' : ''}">${v}</span>`;
      body.appendChild(d);
    });
    $('signModal').classList.add('show');
  }
  function closeSign() { $('signModal').classList.remove('show'); state.pendingTx = null; }
  async function confirmSign() {
    const tx = state.pendingTx;
    if (!tx) return;
    const btn = $('signConfirm'); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    const err = $('signErr'); err.textContent = '';
    try {
      const rawtx = BTCCWallet.signPsbt(tx.psbt, tx.inputs || []);
      const r = await fetch('/api/wallet/broadcast', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rawtx,
          from_addr: state.addr,
          summary: tx.summary || {},
          kind: tx.kind || 'transfer',
        })
      }).then(x => x.json());
      if (!r.ok) throw new Error(r.error || '广播失败');
      closeSign();
      toast('已广播: ' + r.txid.slice(0, 12) + '…');
      go('home');
      refresh();
      [600, 1500, 3000].forEach(ms => setTimeout(refresh, ms));
    } catch (e) {
      err.textContent = e.message;
      btn.disabled = false; btn.textContent = '确认并签名';
    }
  }

  function copyAddr() {
    navigator.clipboard.writeText(state.addr).then(() => {
      const c = $('copyAddr'); c.textContent = '已复制'; c.classList.add('ok');
      setTimeout(() => { c.textContent = '复制'; c.classList.remove('ok'); }, 1500);
    });
  }

  window.W = {
    go, toVerify, finishCreate, finishImport, doUnlock, confirmReset, lock,
    refresh, prepareSend, prepareInsTransfer, copyAddr, closeSign, confirmSign,
    switchWallet, addWallet, setAutoLock, confirmDelete, switchTab,
    previewImportKey, finishImportKey, openImportKey, openManageImports,
  };
  document.addEventListener('DOMContentLoaded', () => { bindActivity(); boot(); });
})();
