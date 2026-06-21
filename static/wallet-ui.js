/* BTCC 钱包前端交互 — 调 window.BTCCWallet(私钥侧) + 后端只读/构造/广播 API */
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

  // ---------- 旧多账户元数据键(已废弃, 仅用于清理) ----------
  const META_KEY = 'ccstamp_wallet_meta';
  // HD 聚合: 每个助记词钱包聚合自己的前 GAP 个收款地址(0/0..0/(GAP-1))。
  // 找零统一回 0/0, 所以 web 原生钱包的钱都落在收款链, 固定窗口即可覆盖。
  const HD_GAP = 20;

  // ---------- 自动锁定 ----------
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

  // ---------- 视图切换 ----------
  function go(view) {
    document.querySelectorAll('.view').forEach(v => v.classList.add('hide'));
    const el = $('v-' + view);
    if (el) el.classList.remove('hide');
    // 内容少的单卡视图垂直居中
    document.body.classList.toggle('centered', ['welcome', 'unlock'].includes(view));
    if (view === 'create') initCreate();
    if (view === 'import') initImport();
    if (view === 'send') initSend();
    if (view === 'receive') initReceive();
    if (view === 'delete') { $('delPw').value = ''; $('delErr').textContent = ''; }
    window.scrollTo(0, 0);
  }

  // ---------- 启动: 判断钱包状态 ----------
  function boot() {
    document.body.classList.remove('boot-welcome', 'boot-unlock');
    if (!window.BTCCWallet) { alert('钱包核心加载失败，请刷新'); return; }
    if (!BTCCWallet.exists()) { go('welcome'); setNet(false, '无钱包'); }
    else if (BTCCWallet.isUnlocked()) { enterHome(); }
    else { go('unlock'); setNet(false, '已锁定'); }
  }

  // ========== 创建流程 ==========
  function initCreate() {
    state.mnemonic = BTCCWallet.generateMnemonic(128);  // 12 词
    // 已解锁(本机已有钱包) → 新增模式: 复用会话密码, 跳过设密码步
    state.createMode = (BTCCWallet.exists() && BTCCWallet.isUnlocked()) ? 'add' : 'first';
    const words = state.mnemonic.split(' ');
    const grid = $('mnGrid'); grid.innerHTML = '';
    words.forEach((w, i) => {
      const d = document.createElement('div'); d.className = 'mn-cell';
      d.innerHTML = `<span class="i">${i + 1}</span><span>${w}</span>`;
      grid.appendChild(d);
    });
    // 新增模式: 隐藏密码输入区, 按钮文案改"创建钱包"(无需再设密码)
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
    // 随机抽 3 个位置让用户选
    const idxs = [];
    while (idxs.length < 3) {
      const r = Math.floor(Math.random() * words.length);
      if (!idxs.includes(r)) idxs.push(r);
    }
    idxs.sort((a, b) => a - b);
    state.verify = { positions: idxs, picked: [null, null, null] };
    const box = $('verifyBox'); box.innerHTML = '';
    idxs.forEach((pos, qi) => {
      // 干扰项: 该正确词 + 5 个其它随机词
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
    // 复用 step1 容器里追加一个"下一步"按钮
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
    // 新增模式: 本机已有钱包且已解锁 → 复用会话密码, 把展示给用户抄写的这串助记词存为新钱包(无需再设密码)
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
    // 首个钱包: 设密码 → save(写旧 v1 槽, 向后兼容)
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

  // ========== 导入助记词 ==========
  // 进入导入页时调用: 已解锁(本机已有钱包) → 新增模式, 隐藏密码区
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
    // 新增模式: 本机已有钱包且已解锁 → 作为又一个独立钱包导入(复用会话密码, 不再设密码, 绝不覆盖原钱包)
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
    // 首个钱包: 设密码 → save(写旧 v1 槽)
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

  // ========== 导入私钥 / Descriptor ==========
  // 预览输入(WIF 或 descriptor), 不落盘, 仅显示将导入的地址
  function previewImportKey() {
    let raw = $('impKeyInput').value.trim();
    const box = $('impKeyPreview'); const err = $('impKeyErr');
    err.textContent = ''; box.innerHTML = '';
    if (!raw) return;
    // 容错: 去掉外层包裹的引号 / 行首的 "desc": 之类
    raw = raw.replace(/^["'\s]+|["'\s]+$/g, '');
    const wpkhMatch = /wpkh\s*\(/i.exec(raw);
    try {
      if (wpkhMatch) {
        // 从 wpkh( 开始截取, 容忍前面粘到的 JSON 字段名等噪音
        const sub = raw.slice(wpkhMatch.index);
        // 实际跑一遍解析, 解析失败要暴露真实原因, 不再笼统报"无法识别"
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
        err.textContent = 'descriptor 解析失败：' + msg + '（请确认复制的是 listdescriptors 里 /0/* 收款那条 wpkh(...)，含 Up3U 开头的私钥）';
      } else {
        err.textContent = '无法识别：这不是有效的 WIF 私钥（应 L/K 开头），也不含 wpkh(...)。若导整个钱包，请粘 listdescriptors 里的 wpkh(...) 那条。原因：' + msg;
      }
    }
  }
  async function finishImportKey() {
    let raw = $('impKeyInput').value.trim().replace(/^["'\s]+|["'\s]+$/g, '');
    const label = $('impKeyLabel').value.trim();
    const targetEl = $('impKeyTarget');
    const target = targetEl ? targetEl.value.trim() : '';
    const err = $('impKeyErr'); err.textContent = '';
    if (!raw) { err.textContent = '请粘贴私钥或 descriptor'; return; }
    if (!BTCCWallet.isUnlocked()) { err.textContent = '请先解锁钱包'; return; }
    const btn = $('impKeyBtn'); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    const wpkhMatch = /wpkh\s*\(/i.exec(raw);
    const isDesc = wpkhMatch || /^(\[[^\]]*\])?(xprv|Up3U|tprv)/.test(raw);
    try {
      let added;
      if (target) {
        // 填了目标地址: 先确认这地址确实属于这条 descriptor(防粘错), 再导入整条钱包(收款链+找零链), 覆盖完整余额
        if (!isDesc) throw new Error('填了目标地址时，上面要粘 descriptor(wpkh... 或 Up3U 开头那串)，不能是单个 WIF');
        const sub = wpkhMatch ? raw.slice(wpkhMatch.index) : raw;
        const maxScan = Math.max(parseInt($('impKeyRange').value) || 200, 200);
        // 第一步: 在 descriptor 双链里定位目标地址, 确认它属于这个钱包(否则报错, 防止粘错 descriptor)
        const loc = await BTCCWallet.findAddressInDescriptor(sub, target, maxScan);
        // 第二步: 导入整条钱包的收款链+找零链(双链), 这样找零地址/完整余额都在。
        // 若目标地址 index 较深, 自动把导入范围扩到能覆盖它(+1 含目标本身)
        const rangeN = Math.max(parseInt($('impKeyRange').value) || 20, 20, (loc && loc.index != null) ? loc.index + 1 : 0);
        added = await BTCCWallet.importDescriptor(sub, rangeN, label);
        if (!added.length) throw new Error('该 descriptor 中的地址均已导入');
        toast('已导入整个钱包(含找零) ' + added.length + ' 个地址');
      } else if (isDesc) {
        const rangeN = parseInt($('impKeyRange').value) || 20;
        const sub = wpkhMatch ? raw.slice(wpkhMatch.index) : raw;
        added = await BTCCWallet.importDescriptor(sub, rangeN, label);
        if (!added.length) throw new Error('该 descriptor 中的地址均已导入');
        toast('已导入 ' + added.length + ' 个地址');
      } else {
        const addr = await BTCCWallet.importWIF(raw, label);
        added = [addr];
        toast('已导入地址');
      }
      $('impKeyInput').value = ''; $('impKeyLabel').value = '';
      if (targetEl) targetEl.value = '';
      $('impKeyPreview').innerHTML = '';
      // 切到刚导入地址所在的组(聚合): 用 listImportGroups 找到含 added[0] 的那组
      const groups = (BTCCWallet.listImportGroups && BTCCWallet.listImportGroups()) || [];
      const g = groups.find(x => (x.addresses || []).indexOf(added[0]) !== -1);
      if (g) { state.sel = 'imp:' + g.group; switchWallet(state.sel); }
      refreshWalletBar();
      go('home');
    } catch (e) {
      err.textContent = '导入失败：' + e.message;
    } finally {
      btn.disabled = false; btn.textContent = '确认导入';
    }
  }
  // 已导入钱包管理列表(按组聚合: 一个 descriptor 导入的多地址显示为一条, 整组一起移除)
  function renderImportList() {
    const wrap = $('impListWrap'); if (!wrap) return;
    const groups = (BTCCWallet.listImportGroups && BTCCWallet.listImportGroups()) || [];
    if (!groups.length) { wrap.innerHTML = '<div class="empty">还没有导入的钱包。</div>'; return; }
    wrap.innerHTML = '';
    groups.forEach((g) => {
      const row = document.createElement('div'); row.className = 'set-row';
      const sub = g.count > 1 ? (g.address + ' 等 ' + g.count + ' 个地址') : g.address;
      row.innerHTML = '<div class="set-label">' + (g.label || '导入钱包') +
        '<span class="set-sub mono">' + sub + '</span></div>';
      const btn = document.createElement('button'); btn.className = 'mini danger'; btn.textContent = '移除';
      btn.onclick = async () => {
        const msg = g.count > 1
          ? ('移除该导入钱包？将删除本机保存的这 ' + g.count + ' 个地址的私钥，原节点钱包不受影响。')
          : '移除该导入地址？私钥将从本机删除，原节点钱包不受影响。';
        if (!confirm(msg)) return;
        if (BTCCWallet.removeImportGroup) await BTCCWallet.removeImportGroup(g.group);
        else for (const a of (g.addresses || [g.address])) await BTCCWallet.removeImport(a);
        renderImportList(); refreshWalletBar();
        // 若删的是当前选中的组, 回到第一个可用钱包
        if (state.sel === 'imp:' + g.group) enterHome();
        toast('已移除');
      };
      row.appendChild(btn); wrap.appendChild(row);
    });
  }
  function openImportKey() { $('impKeyInput').value = ''; $('impKeyLabel').value = '';
    $('impKeyPreview').innerHTML = ''; $('impKeyErr').textContent = ''; go('importkey'); }
  function openManageImports() { renderImportList(); go('manageimports'); }

  // ========== 解锁 ==========
  async function doUnlock() {
    const pw = $('unlockPw').value;
    const err = $('unlockErr'); err.textContent = '';
    if (!pw) { err.textContent = '请输入密码'; return; }
    try {
      await BTCCWallet.unlock(pw);
      $('unlockPw').value = '';
      enterHome();
    } catch (e) { err.textContent = '密码错误'; }
  }
  function confirmReset() {
    if (confirm('重置将删除本机所有助记词钱包(包括你新建/导入的全部钱包)。请确认每个钱包的助记词都已备份，否则资产将永久丢失。继续？')) {
      BTCCWallet.destroy(); localStorage.removeItem(META_KEY); localStorage.removeItem('ccstamp_active_sel');
      state.walletIdx = 0;
      go('welcome'); setNet(false, '无钱包');
    }
  }
  function lock() {
    if (_lockTimer) { clearTimeout(_lockTimer); _lockTimer = null; }
    BTCCWallet.lock(); go('unlock'); setNet(false, '已锁定');
  }

  // ========== 收款二维码 ==========
  function initReceive() {
    $('recvAddr').textContent = state.addr || '—';
    const canvas = $('qrCanvas');
    if (!canvas) return;
    if (!window.QRCode) { toast('二维码组件未加载'); return; }
    window.QRCode.toCanvas(canvas, state.addr, {
      width: 200, margin: 1,
      color: { dark: '#171717', light: '#ffffff' },
      errorCorrectionLevel: 'M'
    }, (err) => { if (err) toast('二维码生成失败'); });
  }

  // ========== 删除钱包(需密码确认) ========== 删当前激活的助记词钱包(其它钱包不受影响)
  async function confirmDelete() {
    const pw = $('delPw').value;
    const err = $('delErr'); err.textContent = '';
    if (!pw) { err.textContent = '请输入密码'; return; }
    // 用密码校验身份: 尝试解锁
    try {
      await BTCCWallet.unlock(pw);
    } catch (e) {
      err.textContent = '密码错误，无法删除';
      return;
    }
    const wallets = (BTCCWallet.listWallets && BTCCWallet.listWallets()) || [];
    const imps = (BTCCWallet.listImports && BTCCWallet.listImports()) || [];
    try {
      if (wallets.length > 1) {
        // 多个助记词钱包 → 只删当前激活的那个, 其余保留
        const idx = (BTCCWallet.activeWallet ? BTCCWallet.activeWallet() : state.walletIdx) || 0;
        await BTCCWallet.removeWallet(idx);
        toast('已删除该钱包');
        enterHome();
        return;
      }
      // 只剩 1 个助记词钱包: 删它。若还有导入地址, 进导入地址视图; 否则回欢迎页
      if (_lockTimer) { clearTimeout(_lockTimer); _lockTimer = null; }
      const idx = (BTCCWallet.activeWallet ? BTCCWallet.activeWallet() : 0) || 0;
      await BTCCWallet.removeWallet(idx);
      state.walletIdx = 0; state.addr = null; state.insList = [];
      if (imps.length) { toast('已删除该钱包'); enterHome(); }
      else { localStorage.removeItem(META_KEY); toast('钱包已删除'); go('welcome'); setNet(false, '无钱包'); }
    } catch (e) {
      err.textContent = '删除失败: ' + e.message;
    }
  }

  // ========== 主页 ==========
  function enterHome() {
    // 默认选中第一个助记词钱包(若有), 否则第一个导入地址
    const wallets = (BTCCWallet.listWallets && BTCCWallet.listWallets()) || [];
    if (wallets.length) {
      // 保持当前激活钱包(可能是切换后进来的), 否则用核心库当前激活值
      const cur = BTCCWallet.activeWallet ? BTCCWallet.activeWallet() : 0;
      state.walletIdx = cur;
      state.sel = 'hd:' + cur;
      state.isImport = false;
      state.addr = BTCCWallet.getAddress(0);
    } else {
      const groups = (BTCCWallet.listImportGroups && BTCCWallet.listImportGroups()) || [];
      if (groups.length) {
        state.sel = 'imp:' + groups[0].group;
        state.isImport = true;
        state.impGroup = groups[0].group;
        state.addr = groups[0].address;
      }
    }
    refreshWalletBar();
    $('myAddr').textContent = state.addr;
    persistActiveSel();
    setNet(true, 'BTCC 主网');
    // 注册名下全部地址到索引器(幂等): 聚合钱包的非主地址也要注册, 否则其收款/转账不进交易记录
    try {
      fetch('/api/wallet/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ addresses: activeAddrs() })
      });
    } catch (e) {}
    // 自动锁定下拉回显 + 启动计时器
    const sel = $('autoLockSel'); if (sel) sel.value = String(autoLockMs());
    resetLockTimer();
    go('home');
    clearBalanceUI();
    refresh();
  }
  // 填充钱包切换条: 每个助记词钱包一条(各自独立余额), 导入地址各一条, 末尾"+ 新建/导入钱包"。
  // 仅 1 个助记词钱包且无导入地址时, 隐藏切换条(无需切换), 但仍保留新建入口在设置区。
  function refreshWalletBar() {
    const sel = $('walletSel'); if (!sel) return;
    const bar = $('walletBar');
    const wallets = (BTCCWallet.listWallets && BTCCWallet.listWallets()) || [];
    const groups = (BTCCWallet.listImportGroups && BTCCWallet.listImportGroups()) || [];
    // 只有 1 个助记词钱包且没有导入钱包 → 无需切换, 隐藏切换条
    if (wallets.length <= 1 && !groups.length) {
      if (bar) bar.classList.add('hide');
      return;
    }
    if (bar) bar.classList.remove('hide');
    sel.innerHTML = '';
    // 助记词钱包: 每个独立一条(各自独立余额/地址)
    if (wallets.length) {
      const gHd = document.createElement('optgroup'); gHd.label = '我的钱包';
      wallets.forEach((w) => {
        const o = document.createElement('option');
        o.value = 'hd:' + w.index;
        o.textContent = w.label + ' · ' + w.address.slice(0, 8) + '…' + w.address.slice(-4);
        if (state.sel === 'hd:' + w.index) o.selected = true;
        gHd.appendChild(o);
      });
      sel.appendChild(gHd);
    }
    // 导入钱包(外部私钥/descriptor): 一个 group 一条(余额聚合, 不再一堆零散地址)
    if (groups.length) {
      const gImp = document.createElement('optgroup'); gImp.label = '导入的钱包';
      groups.forEach((g) => {
        const o = document.createElement('option');
        o.value = 'imp:' + g.group;
        const tail = g.count > 1 ? (' · ' + g.count + ' 个地址') : '';
        o.textContent = (g.label || '导入地址') + ' · ' + g.address.slice(0, 8) + '…' + g.address.slice(-4) + tail;
        if (state.sel === 'imp:' + g.group) o.selected = true;
        gImp.appendChild(o);
      });
      sel.appendChild(gImp);
    }
  }
  // 切换钱包(某个助记词钱包 'hd:N' 或某个导入地址 'imp:地址')
  // 把"当前选中的钱包"持久化到 localStorage, 供铸造页(独立页面)读取同步。
  // 存 sel(hd:N / imp:grp)+ 解析出的主地址 + 该选择下的全部地址(铸造页据此判资格/查余额)。
  function persistActiveSel() {
    try {
      localStorage.setItem('ccstamp_active_sel', JSON.stringify({
        sel: state.sel || null,
        isImport: !!state.isImport,
        addr: state.addr || null,
        addrs: (activeAddrs() || []),
        ts: Date.now()
      }));
    } catch (e) {}
  }
  function switchWallet(selVal) {
    selVal = String(selVal);
    if (selVal === 'hd' || selVal.startsWith('hd:')) {
      // 切到第 N 个助记词钱包: 让核心库激活它, 主地址=该钱包 0/0
      const idx = selVal === 'hd' ? 0 : (parseInt(selVal.slice(3)) || 0);
      try { BTCCWallet.switchWallet(idx); } catch (e) { toast('切换失败: ' + e.message); return; }
      state.walletIdx = idx;
      state.sel = 'hd:' + idx;
      state.isImport = false;
      state.addr = BTCCWallet.getAddress(0);
      const w = (BTCCWallet.listWallets() || [])[idx];
      toast('已切换到 ' + ((w && w.label) || ('钱包 ' + (idx + 1))));
    } else if (selVal.startsWith('imp:')) {
      const grp = selVal.slice(4);
      const groups = (BTCCWallet.listImportGroups && BTCCWallet.listImportGroups()) || [];
      const g = groups.find(x => x.group === grp);
      state.sel = selVal;
      state.isImport = true;
      state.impGroup = grp;
      state.addr = g ? g.address : grp;     // 兼容旧 imp:地址 形态(找不到组就用原值)
      toast('已切换到 ' + ((g && g.label) || '导入钱包'));
    }
    state.insList = [];
    $('myAddr').textContent = state.addr;
    clearBalanceUI();
    persistActiveSel();
    try {
      fetch('/api/wallet/register', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ addresses: activeAddrs() }) });
    } catch (e) {}
    refresh();
  }
  // 新建钱包入口: 进创建流程(initCreate 会判定为 'add' 模式, 生成新助记词让用户抄写)
  function addWallet() {
    const wallets = (BTCCWallet.listWallets && BTCCWallet.listWallets()) || [];
    if (wallets.length >= 20) { toast('最多 20 个钱包'); return; }
    go('create');
  }
  // HD 聚合(单个助记词钱包内部): 当前激活钱包的前 HD_GAP 个收款地址 0/0..0/(HD_GAP-1)。
  // 余额合计、转账跨地址凑币都用这个列表。找零统一回 0/0, 固定窗口即可覆盖 web 原生钱包资金。
  // 注意: 这只聚合"当前钱包自己"的派生地址, 不跨钱包(各钱包资产独立)。
  function hdAddresses() {
    const out = [];
    const pc = (BTCCWallet.hdPathCount && BTCCWallet.hdPathCount()) || 1;
    for (let ai = 0; ai < pc; ai++) {
      for (let i = 0; i < HD_GAP; i++) {
        try { out.push(BTCCWallet.getAddress(i, ai)); } catch (e) {}
      }
    }
    return [...new Set(out)];
  }
  // 当前选择下参与查询/凑币的地址集合: 助记词钱包=该钱包全部收款地址; 导入钱包=该组全部地址。
  function activeAddrs() {
    if (state.isImport) {
      if (state.impGroup && BTCCWallet.importGroupAddresses) {
        const a = BTCCWallet.importGroupAddresses(state.impGroup);
        if (a && a.length) return a;
      }
      return [state.addr];
    }
    const a = hdAddresses();
    return a.length ? a : [state.addr];
  }
  // 切换/导入钱包后, 余额查询是异步的; 在 fetch 返回前必须先清掉上一个钱包的余额数字,
  // 否则新钱包(尤其空钱包)会短暂显示上一个钱包的余额 → 用户误以为"导入的空钱包有币却用不了"。
  function clearBalanceUI() {
    const sp = $('balSpendable'); if (sp) sp.textContent = '…';
    const lk = $('balLock'); if (lk) lk.classList.add('hide');
    const pd = $('balPending'); if (pd) pd.classList.add('hide');
    const tw = $('txWrap'); if (tw) tw.innerHTML = '<div class="muted" style="padding:12px">加载中…</div>';
    state.insList = [];
  }
  async function refresh(userTriggered) {
    // 用户手动点刷新时给出明确视觉反馈(按钮转圈/禁用 + 完成提示)，避免"点了没反应"的错觉
    const btn = userTriggered ? $('refreshBtn') : null;
    let btnOld = '';
    if (btn) {
      btnOld = btn.textContent;
      btn.disabled = true;
      btn.classList.add('loading');
      btn.textContent = '刷新中…';
    }
    let balOk = true;
    try {
      const r = await fetch('/api/wallet/utxos', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ addresses: activeAddrs() })
      }).then(x => x.json());
      if (r.error) throw new Error(r.error);
      // 优先显示"已确认可用余额"
      const confirmedSats = r.spendable_confirmed_sats != null ? r.spendable_confirmed_sats : r.spendable_sats;
      $('balSpendable').textContent = fmt(confirmedSats);
      // 锁定提示(铭文载体)
      if (r.inscription_locked_sats > 0) {
        $('balLock').classList.remove('hide');
        $('balLock').textContent = `另有 ${fmt(r.inscription_locked_sats)} BTCC 锁定在 ${state.insList.length || '若干'} 枚铭文载体中`;
      } else $('balLock').classList.add('hide');
      // 待确认提示
      const pendSats = r.spendable_pending_sats || 0;
      const pendBox = $('balPending');
      if (pendSats > 0) {
        pendBox.classList.remove('hide');
        pendBox.textContent = `${fmt(pendSats)} BTCC 待确认中(1 个块确认后可花费)`;
      } else pendBox.classList.add('hide');
    } catch (e) { balOk = false; toast('余额刷新失败'); }
    // 同时刷新当前 tab 的内容 + 另一个 tab 的计数；等两者都完成再恢复按钮，确保"刷新中"覆盖真实加载过程
    try {
      await Promise.all([loadInscriptions(), loadHistory()]);
    } catch (e) { /* 单个面板失败已各自处理 */ }
    if (btn) {
      btn.disabled = false;
      btn.classList.remove('loading');
      btn.textContent = btnOld || '刷新';
      if (balOk) toast('已刷新');
    }
  }

  // ===== Tab 切换 =====
  function switchTab(name) {
    state.curTab = name;
    $('tab-tx').classList.toggle('active', name === 'tx');
    $('tab-ins').classList.toggle('active', name === 'ins');
    $('panel-tx').classList.toggle('hide', name !== 'tx');
    $('panel-ins').classList.toggle('hide', name !== 'ins');
  }

  // ===== 交易记录 =====
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

  // ========== 铭文详情 + 转移 ==========
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
    // 这枚铭文实际所在地址(可能不是主地址) = it.owner; 校验/构造都以它为 from
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

  // ========== 转账 ==========
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

  // ========== 签名弹窗 ==========
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
      // 1) 浏览器内用私钥签 PSBT(私钥不离开此处)
      // signPsbt 按每个输入的地址自动匹配 HD 派生 key 或导入 key;
      // signPsbt 按每个输入的 witnessUtxo 地址在内存索引(当前激活钱包 0..19 收款+找零链 + 导入地址)
      // 里自动匹配私钥, 跨地址混合输入天然能签。inputMeta 仅作匹配失败时的 HD 回退。
      const rawtx = BTCCWallet.signPsbt(tx.psbt, tx.inputs || []);
      // 2) 后端广播 (附带 from_addr/summary/kind 让后端落 mempool 记录, 让交易列表立即可见)
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

  // ---------- 工具 ----------
  function copyAddr() {
    navigator.clipboard.writeText(state.addr).then(() => {
      const c = $('copyAddr'); c.textContent = '已复制'; c.classList.add('ok');
      setTimeout(() => { c.textContent = '复制'; c.classList.remove('ok'); }, 1500);
    });
  }

  // 暴露给 HTML onclick
  window.W = {
    go, toVerify, finishCreate, finishImport, doUnlock, confirmReset, lock,
    refresh, prepareSend, prepareInsTransfer, copyAddr, closeSign, confirmSign,
    switchWallet, addWallet, setAutoLock, confirmDelete, switchTab,
    previewImportKey, finishImportKey, openImportKey, openManageImports,
  };
  document.addEventListener('DOMContentLoaded', () => { bindActivity(); boot(); });
})();
