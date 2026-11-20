"use strict";

/* ============================================================
   SIMULASI TRADING — game simulasi trading crypto (uang virtual)
   Harga live: CoinGecko public API (tanpa API key).
   Semua data tersimpan di localStorage, tanpa backend.
   - Spot: beli/jual 8 koin.
   - Futures: Long/Short, leverage 1x-100x, likuidasi sederhana
     (tanpa maintenance margin, tanpa fee).
   - Akun Guest: sampai 5 profil, data per profil terpisah.
   ============================================================ */

var INITIAL_CASH = 5000000;
var STORAGE_KEY = "simulasi-trading-v2";      /* format berprofil */
var STORAGE_KEY_V1 = "simulasi-trading-v1";   /* format lama (tanpa profil) */
var COINGECKO_URL =
  "https://api.coingecko.com/api/v3/simple/price" +
  "?ids=bitcoin,ethereum,binancecoin,solana,ripple,dogecoin,cardano,tron" +
  "&vs_currencies=idr&include_24hr_change=true";
var REFRESH_MS = 30000;
var MAX_HISTORY = 240;
var MAX_PROFILES = 5;
var MAX_LEVERAGE = 100;

/* Daftar aset: id CoinGecko, simbol, nama, ikon, warna merek */
var ASSETS = [
  { id: "bitcoin",     symbol: "BTC",  name: "Bitcoin",  icon: "\u20BF", color: "#f7931a" },
  { id: "ethereum",    symbol: "ETH",  name: "Ethereum", icon: "\u039E", color: "#627eea" },
  { id: "binancecoin", symbol: "BNB",  name: "BNB",      icon: "B",      color: "#f0b90b" },
  { id: "solana",      symbol: "SOL",  name: "Solana",   icon: "S",      color: "#9945ff" },
  { id: "ripple",      symbol: "XRP",  name: "XRP",      icon: "X",      color: "#25a4e8" },
  { id: "dogecoin",    symbol: "DOGE", name: "Dogecoin", icon: "\u00D0", color: "#c2a633" },
  { id: "cardano",     symbol: "ADA",  name: "Cardano",  icon: "A",      color: "#3468d1" },
  { id: "tron",        symbol: "TRX",  name: "Tron",     icon: "T",      color: "#ef0027" }
];

/* Harga contoh — DIPAKAI HANYA bila fetch live gagal, dan selalu
   diberi label tegas "HARGA CONTOH (OFFLINE)". Jangan pernah
   menyajikannya seolah-olah harga live. */
var SAMPLE_PRICES = {
  BTC:  { idr: 1500000000, change: 2.4 },
  ETH:  { idr: 55000000,   change: 1.8 },
  BNB:  { idr: 14000000,   change: -0.9 },
  SOL:  { idr: 2800000,    change: 3.1 },
  XRP:  { idr: 35000,      change: -1.2 },
  DOGE: { idr: 3000,       change: 0.6 },
  ADA:  { idr: 12000,      change: -2.0 },
  TRX:  { idr: 4500,       change: 0.4 }
};

/* ---------------- Profil & penyimpanan ---------------- */

function defaultProfileData() {
  return { cash: INITIAL_CASH, holdings: {}, trades: [], history: [], futures: [] };
}

function newProfileId() {
  return "p" + Date.now().toString(36) + Math.floor(Math.random() * 10000).toString(36);
}

function autoGuestName() {
  return "Guest-" + String(Math.floor(1000 + Math.random() * 9000));
}

function createProfile(name) {
  var p = defaultProfileData();
  p.id = newProfileId();
  p.name = name && name.trim() ? name.trim().slice(0, 20) : autoGuestName();
  p.createdAt = Date.now();
  return p;
}

/* Migrasi data lama (format v1 tanpa profil) menjadi profil pertama
   bernama "Guest". Kunci v1 dibiarkan utuh sebagai cadangan. */
function migrateLegacy() {
  try {
    var raw = localStorage.getItem(STORAGE_KEY_V1);
    if (!raw) return null;
    var s = JSON.parse(raw);
    if (typeof s.cash !== "number") return null;
    var p = defaultProfileData();
    p.id = "p-legacy";
    p.name = "Guest";
    p.createdAt = Date.now();
    p.cash = s.cash;
    p.holdings = s.holdings || {};
    p.trades = s.trades || [];
    p.history = s.history || [];
    p.futures = [];
    return p;
  } catch (e) {
    return null;
  }
}

function loadStore() {
  try {
    var raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      var s = JSON.parse(raw);
      if (s && Array.isArray(s.profiles)) {
        s.profiles.forEach(function (p) {
          p.holdings = p.holdings || {};
          p.trades = p.trades || [];
          p.history = p.history || [];
          p.futures = p.futures || [];
          if (typeof p.cash !== "number") p.cash = INITIAL_CASH;
        });
        return s;
      }
    }
  } catch (e) { /* lanjut ke migrasi / baru */ }
  var legacy = migrateLegacy();
  if (legacy) {
    var migrated = { version: 2, activeProfileId: legacy.id, profiles: [legacy] };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated)); } catch (e) {}
    return migrated;
  }
  return { version: 2, activeProfileId: null, profiles: [] };
}

function saveStore() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(store)); } catch (e) {}
}

var store = loadStore();

function activeProfile() {
  if (!store.activeProfileId) return null;
  for (var i = 0; i < store.profiles.length; i++) {
    if (store.profiles[i].id === store.activeProfileId) return store.profiles[i];
  }
  return null;
}

/* `state` menunjuk ke objek data profil aktif (referensi langsung
   ke dalam store.profiles, jadi mutasi tersimpan otomatis). */
var state = activeProfile();

/* Harga saat ini: { SYM: { idr, change } } + penanda live/offline */
var prices = {};
var prevPrices = {};
var pricesLive = false;
var lastUpdated = null;

/* UI state */
var selectedSymbol = "BTC";
var tradeMode = "buy"; // "buy" | "sell"
var futDirection = "long"; // "long" | "short"
var futLeverage = 10;

/* ---------------- Format angka ---------------- */

var idrFmt = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0
});

function fmtIDR(n) {
  if (!isFinite(n)) return "—";
  return idrFmt.format(Math.round(n));
}

function fmtSignedIDR(n) {
  if (!isFinite(n)) return "—";
  var sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return sign + idrFmt.format(Math.round(Math.abs(n)));
}

function fmtPct(n) {
  if (!isFinite(n)) return "—";
  return (n > 0 ? "+" : "") + n.toFixed(2).replace(".", ",") + "%";
}

/* Jumlah koin: desimal menyesuaikan besarnya angka */
function fmtCoin(n) {
  if (!isFinite(n)) return "—";
  var dec = n >= 1000 ? 2 : n >= 1 ? 4 : n >= 0.01 ? 6 : 8;
  return n.toLocaleString("id-ID", {
    minimumFractionDigits: 0, maximumFractionDigits: dec
  });
}

/* Angka ringkas untuk sumbu grafik, mis. Rp5,2 jt / Rp1,13 M */
function fmtCompact(n) {
  if (!isFinite(n)) return "—";
  var abs = Math.abs(n);
  var scaled, unit;
  if (abs >= 1e9) { scaled = n / 1e9; unit = " M"; }
  else if (abs >= 1e6) { scaled = n / 1e6; unit = " jt"; }
  else if (abs >= 1e3) { scaled = n / 1e3; unit = " rb"; }
  else return fmtIDR(n);
  return "Rp" + scaled.toLocaleString("id-ID", { maximumFractionDigits: 2 }) + unit;
}

function fmtTime(ts) {
  return new Date(ts).toLocaleString("id-ID", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"
  });
}

function fmtClock(ts) {
  return new Date(ts).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function assetOf(symbol) {
  for (var i = 0; i < ASSETS.length; i++) {
    if (ASSETS[i].symbol === symbol) return ASSETS[i];
  }
  return null;
}

/* Gaya ikon koin sesuai warna merek (latar temaram + huruf berwarna) */
function iconStyle(a) {
  if (!a) return "";
  return "background:" + a.color + "1f;color:" + a.color +
    ";border:1px solid " + a.color + "55";
}

function $(id) { return document.getElementById(id); }

/* ---------------- Toast ---------------- */

var toastTimer = null;
function showToast(msg, kind) {
  var t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (kind ? " toast-" + kind : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.className = "toast"; }, 4000);
}

/* ---------------- Harga ---------------- */

function applyPrices(data, live) {
  prevPrices = prices;
  prices = {};
  ASSETS.forEach(function (a) {
    var d = data[a.id];
    if (d && typeof d.idr === "number") {
      prices[a.symbol] = { idr: d.idr, change: d.idr_24h_change || 0 };
    }
  });
  pricesLive = live;
  lastUpdated = Date.now();
  updatePriceBadge();
  checkLiquidations();
  snapshotPortfolio();
  renderAll();
}

async function fetchPrices() {
  setBadgeLoading();
  var controller = new AbortController();
  var timer = setTimeout(function () { controller.abort(); }, 10000);
  try {
    var res = await fetch(COINGECKO_URL, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error("HTTP " + res.status);
    var data = await res.json();
    if (!data || !data.bitcoin || typeof data.bitcoin.idr !== "number") {
      throw new Error("Respons CoinGecko tidak lengkap");
    }
    applyPrices(data, true);
  } catch (e) {
    clearTimeout(timer);
    /* Fallback: harga contoh, DIBERI LABEL OFFLINE di UI. */
    var sample = {};
    Object.keys(SAMPLE_PRICES).forEach(function (sym) {
      var a = assetOf(sym);
      sample[a.id] = {
        idr: SAMPLE_PRICES[sym].idr,
        idr_24h_change: SAMPLE_PRICES[sym].change
      };
    });
    applyPrices(sample, false);
  }
}

function setBadgeLoading() {
  var b = $("priceBadge");
  b.className = "badge badge-loading";
  $("priceBadgeText").textContent = "Memuat harga…";
  $("refreshBtn").classList.add("spinning");
}

function updatePriceBadge() {
  var b = $("priceBadge");
  var banner = $("offlineBanner");
  $("refreshBtn").classList.remove("spinning");
  if (pricesLive) {
    b.className = "badge badge-live";
    $("priceBadgeText").textContent = "HARGA LIVE";
    banner.hidden = true;
  } else {
    b.className = "badge badge-offline";
    $("priceBadgeText").textContent = "HARGA CONTOH (OFFLINE)";
    banner.hidden = false;
  }
}

/* ---------------- Futures: rumus ---------------- */

/* Notional (ukuran posisi) = margin × leverage */
function futNotional(margin, leverage) { return margin * leverage; }

/* Harga likuidasi — rumus SEDERHANA, tanpa maintenance margin,
   tanpa fee. Long = entry × (1 − 1/leverage),
   Short = entry × (1 + 1/leverage). */
function futLiqPrice(entry, direction, leverage) {
  if (direction === "long") return entry * (1 - 1 / leverage);
  return entry * (1 + 1 / leverage);
}

/* PnL mengambang pada harga mark.
   Long = (mark − entry)/entry × notional
   Short = (entry − mark)/entry × notional */
function futPnl(pos, mark) {
  var notional = futNotional(pos.margin, pos.leverage);
  if (pos.direction === "long") return (mark - pos.entry) / pos.entry * notional;
  return (pos.entry - mark) / pos.entry * notional;
}

function futRoe(pos, mark) {
  if (!pos.margin) return 0;
  return futPnl(pos, mark) / pos.margin * 100;
}

function markPrice(symbol) {
  var p = prices[symbol];
  return p ? p.idr : null;
}

/* Periksa semua posisi terbuka setiap kali harga diperbarui.
   Bila harga mark menyentuh/melewati harga likuidasi, posisi
   ditutup otomatis dan margin hangus. */
function checkLiquidations() {
  if (!state || !state.futures.length) return;
  var doomed = [];
  state.futures.forEach(function (pos) {
    var mark = markPrice(pos.symbol);
    if (mark == null) return;
    var liq = futLiqPrice(pos.entry, pos.direction, pos.leverage);
    if ((pos.direction === "long" && mark <= liq) ||
        (pos.direction === "short" && mark >= liq)) {
      doomed.push(pos);
    }
  });
  doomed.forEach(function (pos) { closeFutures(pos.id, "liquidated"); });
}

/* ---------------- Hitung portofolio ---------------- */

function holdingValue(sym) {
  var h = state.holdings[sym];
  var p = prices[sym];
  if (!h || !p) return 0;
  return h.amount * p.idr;
}

function futuresFloatPnl() {
  var total = 0;
  state.futures.forEach(function (pos) {
    var mark = markPrice(pos.symbol);
    if (mark != null) total += futPnl(pos, mark);
  });
  return total;
}

function futuresMarginTotal() {
  var total = 0;
  state.futures.forEach(function (pos) { total += pos.margin; });
  return total;
}

/* Total = kas + nilai koin spot + margin futures + PnL mengambang */
function totalValue() {
  if (!state) return INITIAL_CASH;
  var total = state.cash;
  Object.keys(state.holdings).forEach(function (sym) {
    total += holdingValue(sym);
  });
  total += futuresMarginTotal() + futuresFloatPnl();
  return total;
}

function snapshotPortfolio() {
  if (!state) return;
  var v = totalValue();
  var last = state.history[state.history.length - 1];
  /* Simpan snapshot baru bila nilai berubah atau sudah >60 detik. */
  if (last && last.v === v && Date.now() - last.t < 60000) return;
  state.history.push({ t: Date.now(), v: Math.round(v) });
  if (state.history.length > MAX_HISTORY) {
    state.history = state.history.slice(-MAX_HISTORY);
  }
  saveStore();
}

/* ---------------- Grafik ---------------- */

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawChart() {
  var canvas = $("chart");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var w = canvas.clientWidth || 800;
  var h = canvas.clientHeight || 210;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  if (!state) return;
  var hist = state.history;
  if (hist.length === 0) {
    ctx.fillStyle = "#848e9c";
    ctx.font = "13px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Belum ada data.", w / 2, h / 2 - 10);
    ctx.fillText("Grafik terisi setelah harga diperbarui.", w / 2, h / 2 + 12);
    return;
  }

  var values = hist.map(function (p) { return p.v; });
  values.push(INITIAL_CASH);
  var min = Math.min.apply(null, values);
  var max = Math.max.apply(null, values);
  if (max === min) { max = min + 1; }
  /* Bantalan minimal 2% dari nilai maks — garis datar tetap punya
     label sumbu yang berbeda-beda dan terbaca. */
  var pad = Math.max((max - min) * 0.12, Math.abs(max) * 0.02, 1);
  min -= pad; max += pad;

  var left = 62, right = w - 10, top = 14, bottom = h - 26;
  function x(i) {
    return hist.length === 1 ? (left + right) / 2
      : left + (i / (hist.length - 1)) * (right - left);
  }
  function y(v) { return bottom - ((v - min) / (max - min)) * (bottom - top); }

  /* Garis grid horizontal + label sumbu */
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.textAlign = "left";
  var gridLines = 4;
  for (var g = 0; g <= gridLines; g++) {
    var gv = min + (max - min) * (g / gridLines);
    var gy = y(gv);
    ctx.strokeStyle = "rgba(132, 142, 156, 0.13)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, gy);
    ctx.lineTo(right, gy);
    ctx.stroke();
    ctx.fillStyle = "#5e6673";
    ctx.fillText(fmtCompact(gv), 4, gy + 3);
  }

  /* Garis acuan modal awal (putus-putus) + label */
  var baseY = y(INITIAL_CASH);
  ctx.strokeStyle = "rgba(240,185,11,0.55)";
  ctx.setLineDash([5, 5]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(left, baseY);
  ctx.lineTo(right, baseY);
  ctx.stroke();
  ctx.setLineDash([]);
  var label = "Modal awal " + fmtIDR(INITIAL_CASH);
  ctx.font = "10px Inter, sans-serif";
  var tw = ctx.measureText(label).width;
  ctx.fillStyle = "rgba(240,185,11,0.16)";
  roundRectPath(ctx, left + 4, Math.max(2, baseY - 18), tw + 12, 15, 7);
  ctx.fill();
  ctx.fillStyle = "#f0b90b";
  ctx.fillText(label, left + 10, Math.max(13, baseY - 7));

  /* Garis nilai portofolio — dihaluskan (kurva) + isi gradien */
  var lastV = hist[hist.length - 1].v;
  var up = lastV >= INITIAL_CASH;
  var color = up ? "#0ecb81" : "#f6465d";
  ctx.beginPath();
  ctx.moveTo(x(0), y(hist[0].v));
  for (var i = 1; i < hist.length; i++) {
    var mx = (x(i - 1) + x(i)) / 2;
    var my = (y(hist[i - 1].v) + y(hist[i].v)) / 2;
    ctx.quadraticCurveTo(x(i - 1), y(hist[i - 1].v), mx, my);
  }
  ctx.lineTo(x(hist.length - 1), y(lastV));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.25;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.stroke();

  ctx.lineTo(x(hist.length - 1), bottom);
  ctx.lineTo(x(0), bottom);
  ctx.closePath();
  var grad = ctx.createLinearGradient(0, top, 0, bottom);
  grad.addColorStop(0, up ? "rgba(14,203,129,0.28)" : "rgba(246,70,93,0.28)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = grad;
  ctx.fill();

  /* Label waktu sumbu X (awal & akhir) */
  ctx.fillStyle = "#5e6673";
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.textAlign = "left";
  ctx.fillText(fmtClock(hist[0].t), left, h - 8);
  ctx.textAlign = "right";
  ctx.fillText(fmtClock(hist[hist.length - 1].t), right, h - 8);

  /* Titik terakhir + label nilai */
  var lx = x(hist.length - 1), ly = y(lastV);
  ctx.beginPath();
  ctx.arc(lx, ly, 5.5, 0, Math.PI * 2);
  ctx.fillStyle = "#eaecef";
  ctx.fill();
  ctx.beginPath();
  ctx.arc(lx, ly, 3.5, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.fillStyle = "#eaecef";
  ctx.font = "bold 12px 'IBM Plex Mono', monospace";
  ctx.textAlign = "right";
  ctx.fillText(fmtIDR(lastV), right - 2, Math.max(14, ly - 10));
}

/* ---------------- Render ---------------- */

function renderAll() {
  renderMarket();
  if (!state) return;
  renderPortfolio();
  renderHoldings();
  renderHistory();
  renderTradePanel();
  renderFuturesPanel();
  renderPositions();
  renderProfileUI();
  drawChart();
}

function renderMarket() {
  var list = $("marketList");
  list.innerHTML = "";
  /* Skeleton saat harga belum ada sama sekali (loading awal). */
  if (Object.keys(prices).length === 0) {
    for (var s = 0; s < 8; s++) {
      var sk = document.createElement("div");
      sk.className = "skeleton-row";
      sk.innerHTML =
        '<span class="skeleton circle"></span>' +
        '<span><span class="skeleton line" style="display:block;width:38%"></span>' +
        '<span class="skeleton line short" style="display:block;margin-top:6px"></span></span>' +
        '<span class="skeleton line long"></span>';
      list.appendChild(sk);
    }
    return;
  }
  ASSETS.forEach(function (a) {
    var p = prices[a.symbol];
    var row = document.createElement("button");
    row.type = "button";
    row.className = "market-row" + (a.symbol === selectedSymbol ? " selected" : "");
    var changeCls = p && p.change >= 0 ? "up" : "down";
    var changeTxt = p ? fmtPct(p.change) : "—";
    /* Kilat warna singkat bila harga berubah sejak pembaruan lalu */
    var prev = prevPrices[a.symbol];
    var flashCls = "";
    if (prev && p) {
      if (p.idr > prev.idr) flashCls = " price-flash-up";
      else if (p.idr < prev.idr) flashCls = " price-flash-down";
    }
    row.innerHTML =
      '<span class="coin-icon" style="' + iconStyle(a) + '">' + a.icon + "</span>" +
      '<span class="coin-info">' +
        '<span class="coin-name">' + a.name + "</span>" +
        '<span class="coin-symbol">' + a.symbol + " / IDR</span>" +
      "</span>" +
      '<span class="coin-price">' +
        '<span class="price' + flashCls + '">' + (p ? fmtIDR(p.idr) : "—") + "</span>" +
        '<span class="change ' + changeCls + '">' + changeTxt + "</span>" +
      "</span>";
    row.addEventListener("click", function () {
      selectedSymbol = a.symbol;
      hideConfirm();
      hideFutConfirm();
      renderAll();
      $("amountInput").focus();
    });
    list.appendChild(row);
  });
  $("lastUpdated").textContent = lastUpdated
    ? new Date(lastUpdated).toLocaleTimeString("id-ID")
    : "—";
}

function renderPortfolio() {
  var total = totalValue();
  var pnl = total - INITIAL_CASH;
  var pnlPct = (pnl / INITIAL_CASH) * 100;
  $("totalValue").textContent = fmtIDR(total);
  $("cashBalance").textContent = fmtIDR(state.cash);
  var pnlEl = $("totalPnl");
  pnlEl.textContent = fmtSignedIDR(pnl) + " (" + fmtPct(pnlPct) + ")";
  pnlEl.className = "stat-value " + (pnl > 0 ? "up" : pnl < 0 ? "down" : "");
  var fs = $("futuresSummary");
  if (state.futures.length) {
    fs.textContent = "Termasuk margin futures " + fmtIDR(futuresMarginTotal()) +
      " + PnL mengambang " + fmtSignedIDR(futuresFloatPnl()) + ".";
    fs.hidden = false;
  } else {
    fs.hidden = true;
  }
}

function renderHoldings() {
  var list = $("holdingsList");
  list.innerHTML = "";
  var syms = Object.keys(state.holdings).filter(function (s) {
    return state.holdings[s].amount > 0;
  });
  if (syms.length === 0) {
    list.innerHTML = "<p class=\"empty-note\">Belum ada koin. Pilih koin di pasar lalu beli untuk mulai.</p>";
    return;
  }
  syms.forEach(function (sym) {
    var h = state.holdings[sym];
    var a = assetOf(sym);
    var p = prices[sym];
    var cur = p ? h.amount * p.idr : 0;
    var cost = h.amount * h.avgPrice;
    var pnl = cur - cost;
    var row = document.createElement("div");
    row.className = "holding-row";
    row.innerHTML =
      '<span class="coin-icon" style="' + iconStyle(a) + '">' + (a ? a.icon : "?") + "</span>" +
      '<span class="holding-info">' +
        '<span class="coin-name">' + sym + "</span>" +
        '<span class="holding-detail">' + fmtCoin(h.amount) + " koin &middot; " +
          "harga beli rata-rata " + fmtIDR(h.avgPrice) + "</span>" +
      "</span>" +
      '<span class="holding-value">' +
        '<span class="value">' + fmtIDR(cur) + "</span>" +
        '<span class="change ' + (pnl >= 0 ? "up" : "down") + '">' +
          fmtSignedIDR(pnl) + "</span>" +
      "</span>";
    list.appendChild(row);
  });
}

/* Riwayat hanya bisa dibaca — TIDAK ADA tombol hapus per item. */
function renderHistory() {
  var list = $("tradeHistory");
  list.innerHTML = "";
  if (state.trades.length === 0) {
    list.innerHTML = "<p class=\"empty-note\">Belum ada transaksi.</p>";
    return;
  }
  var sorted = state.trades.slice().sort(function (a, b) { return b.t - a.t; });
  sorted.forEach(function (tr) {
    var row = document.createElement("div");
    row.className = "history-row";
    var titleHtml, detailHtml, valueHtml;
    if (tr.type === "buy" || tr.type === "sell") {
      var isBuy = tr.type === "buy";
      titleHtml = '<span class="trade-type ' + (isBuy ? "up" : "down") + '">' +
        (isBuy ? "BELI " : "JUAL ") + tr.symbol + "</span>";
      detailHtml = fmtTime(tr.t) + " &middot; " +
        fmtCoin(tr.amount) + " " + tr.symbol + " @ " + fmtIDR(tr.price);
      valueHtml = (isBuy ? "−" : "+") + fmtIDR(tr.total);
    } else {
      var dir = (tr.direction || "long").toUpperCase();
      var lev = tr.leverage ? " " + tr.leverage + "x" : "";
      var kind =
        tr.type === "futures-open" ? "BUKA" :
        tr.type === "futures-close" ? "TUTUP" : "LIQUIDATED";
      var cls = tr.type === "futures-liquidated" ? "down" :
        tr.direction === "long" ? "up" : "down";
      titleHtml = '<span class="dir-badge ' +
        (tr.direction === "long" ? "dir-long" : "dir-short") + '">FUTURES</span>' +
        '<span class="trade-type ' + cls + '">' + kind + " " + dir + " " + tr.symbol + lev + "</span>";
      if (tr.type === "futures-open") {
        detailHtml = fmtTime(tr.t) + " &middot; margin " + fmtIDR(tr.margin) +
          " @ " + fmtIDR(tr.entry);
        valueHtml = "−" + fmtIDR(tr.margin);
      } else if (tr.type === "futures-close") {
        detailHtml = fmtTime(tr.t) + " &middot; tutup @ " + fmtIDR(tr.exitPrice) +
          " &middot; PnL " + fmtSignedIDR(tr.pnl);
        valueHtml = "+" + fmtIDR(tr.total);
      } else {
        detailHtml = fmtTime(tr.t) + " &middot; likuidasi @ " + fmtIDR(tr.exitPrice) +
          " &middot; margin hangus";
        valueHtml = "−" + fmtIDR(tr.margin);
      }
    }
    row.innerHTML =
      '<span class="history-info">' + titleHtml +
        '<span class="history-detail">' + detailHtml + "</span>" +
      "</span>" +
      '<span class="history-value"><span class="value">' + valueHtml + "</span></span>";
    list.appendChild(row);
  });
}

/* ---------------- Panel Spot ---------------- */

function currentPrice() {
  var p = prices[selectedSymbol];
  return p ? p.idr : null;
}

function renderTradePanel() {
  var a = assetOf(selectedSymbol);
  var p = currentPrice();
  $("tradeIcon").textContent = a ? a.icon : "?";
  $("tradeIcon").setAttribute("style", iconStyle(a));
  $("tradeName").textContent = a ? a.name : "—";
  $("tradeSymbol").textContent = selectedSymbol;
  $("tradePrice").textContent = p ? fmtIDR(p) + " / " + selectedSymbol : "—";

  var buy = tradeMode === "buy";
  $("tabBuy").className = "tab" + (buy ? " active-buy" : "");
  $("tabSell").className = "tab" + (!buy ? " active-sell" : "");
  $("tabBuy").setAttribute("aria-selected", buy ? "true" : "false");
  $("tabSell").setAttribute("aria-selected", !buy ? "true" : "false");
  $("amountLabel").textContent = buy
    ? "Jumlah Rupiah yang dipakai"
    : "Jumlah " + selectedSymbol + " yang dijual";
  $("amountInput").placeholder = buy
    ? "Contoh: 1000000"
    : "Contoh: " + fmtCoin(holdingsAmount(selectedSymbol) / 2 || 0.001);
  var btn = $("tradeBtn");
  btn.textContent = buy ? "Beli " + selectedSymbol : "Jual " + selectedSymbol;
  btn.className = "btn " + (buy ? "btn-buy" : "btn-sell");
  updatePreview();
}

function holdingsAmount(sym) {
  var h = state.holdings[sym];
  return h ? h.amount : 0;
}

function showError(msg) {
  var el = $("tradeError");
  if (msg) { el.textContent = msg; el.hidden = false; }
  else { el.hidden = true; }
}

function hideConfirm() {
  $("confirmBox").hidden = true;
  $("previewBox").hidden = true;
}

/* ---------------- Panel Futures ---------------- */

function renderFuturesPanel() {
  var a = assetOf(selectedSymbol);
  var p = currentPrice();
  $("futIcon").textContent = a ? a.icon : "?";
  $("futIcon").setAttribute("style", iconStyle(a));
  $("futName").textContent = a ? a.name : "—";
  $("futSymbol").textContent = selectedSymbol;
  $("futPrice").textContent = p ? fmtIDR(p) + " / " + selectedSymbol : "—";

  var isLong = futDirection === "long";
  $("futLong").className = "tab" + (isLong ? " active-long" : "");
  $("futShort").className = "tab" + (!isLong ? " active-short" : "");
  $("futLong").setAttribute("aria-selected", isLong ? "true" : "false");
  $("futShort").setAttribute("aria-selected", !isLong ? "true" : "false");
  $("futLevLabel").textContent = futLeverage + "x";
  var btn = $("futBtn");
  btn.textContent = isLong ? "Buka Long " + selectedSymbol : "Buka Short " + selectedSymbol;
  btn.className = "btn " + (isLong ? "btn-buy" : "btn-sell");
  updateFutPreview();
}

function showFutError(msg) {
  var el = $("futError");
  if (msg) { el.textContent = msg; el.hidden = false; }
  else { el.hidden = true; }
}

function hideFutConfirm() {
  $("futConfirmBox").hidden = true;
  $("futPreview").hidden = true;
}

function renderPositions() {
  var list = $("futPositions");
  list.innerHTML = "";
  if (!state.futures.length) {
    list.innerHTML = "<p class=\"empty-note\">Belum ada posisi futures.</p>";
    return;
  }
  state.futures.forEach(function (pos) {
    var mark = markPrice(pos.symbol);
    var pnl = mark != null ? futPnl(pos, mark) : 0;
    var roe = futRoe(pos, mark != null ? mark : pos.entry);
    var liq = futLiqPrice(pos.entry, pos.direction, pos.leverage);
    var row = document.createElement("div");
    row.className = "position-row";
    row.innerHTML =
      '<span class="position-info">' +
        '<span><span class="dir-badge ' +
          (pos.direction === "long" ? "dir-long" : "dir-short") + '">' +
          pos.direction.toUpperCase() + "</span>" +
          '<strong>' + pos.symbol + " " + pos.leverage + "x</strong></span>" +
        '<span class="position-detail">' +
          "entry " + fmtIDR(pos.entry) + " &middot; mark " + (mark != null ? fmtIDR(mark) : "—") +
          " &middot; likuidasi " + fmtIDR(liq) + "<br>" +
          "margin " + fmtIDR(pos.margin) + " &middot; notional " + fmtIDR(futNotional(pos.margin, pos.leverage)) +
        "</span>" +
      "</span>" +
      '<span class="holding-value">' +
        '<span class="pos-pnl ' + (pnl >= 0 ? "up" : "down") + '">' + fmtSignedIDR(pnl) + "</span>" +
        '<span class="change ' + (roe >= 0 ? "up" : "down") + '">ROE ' + fmtPct(roe) + "</span>" +
      "</span>" +
      '<button type="button" class="btn btn-danger btn-small" data-pos-id="' + pos.id + '">Tutup</button>';
    row.querySelector("[data-pos-id]").addEventListener("click", function () {
      closeFutures(pos.id, "manual");
    });
    list.appendChild(row);
  });
}

/* ---------------- Profil (Guest) ---------------- */

function renderProfileUI() {
  var wrap = $("profileWrap");
  if (!state) { wrap.hidden = true; return; }
  wrap.hidden = false;
  $("profileAvatar").textContent = (state.name || "G").charAt(0).toUpperCase();
  $("profileName").textContent = state.name;
  var list = $("profileList");
  list.innerHTML = "";
  store.profiles.forEach(function (p) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "profile-item" + (p.id === store.activeProfileId ? " active" : "");
    btn.innerHTML =
      '<span class="profile-avatar" style="width:26px;height:26px;font-size:0.8rem">' +
        (p.name || "G").charAt(0).toUpperCase() + "</span>" +
      "<span>" + p.name + "</span>" +
      (p.id === store.activeProfileId ? '<span class="check">&#10003;</span>' : "");
    btn.addEventListener("click", function () { switchProfile(p.id); });
    list.appendChild(btn);
  });
  $("createProfileBtn").disabled = store.profiles.length >= MAX_PROFILES;
  $("profileNote").textContent = store.profiles.length >= MAX_PROFILES
    ? "Maksimal 5 profil tercapai. Data tiap profil tersimpan terpisah di perangkat ini."
    : "Maksimal 5 profil. Data tiap profil tersimpan terpisah di perangkat ini.";
}

/* ---------------- Trading Spot ---------------- */

/* Pratinjau hitungan dari input saat ini; mengembalikan objek
   { ok, amount, coins, total, msg } atau null bila input kosong. */
function computeTrade() {
  var raw = parseFloat($("amountInput").value);
  var price = currentPrice();
  if (!price) return { ok: false, msg: "Harga belum tersedia — tekan Refresh." };
  if (!isFinite(raw) || raw <= 0) return null;

  if (tradeMode === "buy") {
    var coins = raw / price;
    if (raw > state.cash) {
      return { ok: false, msg: "Saldo kas tidak cukup. Kas tersedia: " + fmtIDR(state.cash) + "." };
    }
    return { ok: true, amount: raw, coins: coins, total: raw, price: price };
  } else {
    var owned = holdingsAmount(selectedSymbol);
    var total = raw * price;
    if (raw > owned) {
      return { ok: false, msg: "Koin tidak cukup. Kamu punya " + fmtCoin(owned) + " " + selectedSymbol + "." };
    }
    return { ok: true, amount: raw, coins: raw, total: total, price: price };
  }
}

function updatePreview() {
  var box = $("previewBox");
  var res = computeTrade();
  if (!res) { box.hidden = true; showError(null); return; }
  if (!res.ok) { box.hidden = true; showError(res.msg); return; }
  showError(null);
  if (tradeMode === "buy") {
    box.innerHTML =
      '<div class="row"><span>Harga ' + selectedSymbol + '</span><strong>' + fmtIDR(res.price) + '</strong></div>' +
      '<div class="row"><span>Jumlah Rupiah</span><strong>' + fmtIDR(res.amount) + '</strong></div>' +
      '<div class="row"><span>Koin yang didapat</span><strong>' + fmtCoin(res.coins) + " " + selectedSymbol + "</strong></div>" +
      '<div class="row"><span>Sisa kas setelah beli</span><strong>' + fmtIDR(state.cash - res.amount) + "</strong></div>";
  } else {
    box.innerHTML =
      '<div class="row"><span>Harga ' + selectedSymbol + '</span><strong>' + fmtIDR(res.price) + '</strong></div>' +
      '<div class="row"><span>Koin yang dijual</span><strong>' + fmtCoin(res.coins) + " " + selectedSymbol + "</strong></div>" +
      '<div class="row"><span>Rupiah yang diterima</span><strong>' + fmtIDR(res.total) + '</strong></div>' +
      '<div class="row"><span>Sisa koin setelah jual</span><strong>' + fmtCoin(holdingsAmount(selectedSymbol) - res.coins) + " " + selectedSymbol + "</strong></div>";
  }
  box.hidden = false;
}

function executeTrade(res) {
  var now = Date.now();
  var id = "t" + now + Math.floor(Math.random() * 1000);
  if (tradeMode === "buy") {
    state.cash -= res.amount;
    var h = state.holdings[selectedSymbol] || { amount: 0, avgPrice: 0 };
    var newAmount = h.amount + res.coins;
    h.avgPrice = newAmount > 0
      ? (h.amount * h.avgPrice + res.coins * res.price) / newAmount
      : res.price;
    h.amount = newAmount;
    state.holdings[selectedSymbol] = h;
    state.trades.push({
      id: id, t: now, type: "buy", symbol: selectedSymbol,
      amount: res.coins, price: res.price, total: res.amount
    });
    showToast("Berhasil beli " + fmtCoin(res.coins) + " " + selectedSymbol +
      " seharga " + fmtIDR(res.amount) + ".", "success");
  } else {
    state.cash += res.total;
    var hs = state.holdings[selectedSymbol];
    hs.amount -= res.coins;
    if (hs.amount <= 1e-12) delete state.holdings[selectedSymbol];
    state.trades.push({
      id: id, t: now, type: "sell", symbol: selectedSymbol,
      amount: res.coins, price: res.price, total: res.total
    });
    showToast("Berhasil jual " + fmtCoin(res.coins) + " " + selectedSymbol +
      ", terima " + fmtIDR(res.total) + ".", "success");
  }
  snapshotPortfolio();
  saveStore();
  $("amountInput").value = "";
  hideConfirm();
  renderAll();
}

/* ---------------- Trading Futures ---------------- */

function computeFutures() {
  var margin = parseFloat($("futMarginInput").value);
  var entry = currentPrice();
  if (!entry) return { ok: false, msg: "Harga belum tersedia — tekan Refresh." };
  if (!isFinite(margin) || margin <= 0) return null;
  if (margin > state.cash) {
    return { ok: false, msg: "Margin melebihi saldo kas. Kas tersedia: " + fmtIDR(state.cash) + "." };
  }
  var lev = Math.max(1, Math.min(MAX_LEVERAGE, futLeverage));
  return {
    ok: true, margin: margin, leverage: lev, entry: entry,
    notional: futNotional(margin, lev),
    liq: futLiqPrice(entry, futDirection, lev)
  };
}

function updateFutPreview() {
  var box = $("futPreview");
  var res = computeFutures();
  if (!res) { box.hidden = true; showFutError(null); return; }
  if (!res.ok) { box.hidden = true; showFutError(res.msg); return; }
  showFutError(null);
  var dirTxt = futDirection === "long" ? "Long" : "Short";
  box.innerHTML =
    '<div class="row"><span>Harga entry (' + dirTxt + " " + selectedSymbol + ')</span><strong>' + fmtIDR(res.entry) + '</strong></div>' +
    '<div class="row"><span>Margin</span><strong>' + fmtIDR(res.margin) + '</strong></div>' +
    '<div class="row"><span>Leverage</span><strong>' + res.leverage + 'x</strong></div>' +
    '<div class="row total"><span>Ukuran posisi (notional)</span><strong>' + fmtIDR(res.notional) + '</strong></div>' +
    '<div class="row"><span>Harga likuidasi</span><strong>' + fmtIDR(res.liq) + '</strong></div>' +
    '<div class="row"><span>Sisa kas setelah buka</span><strong>' + fmtIDR(state.cash - res.margin) + "</strong></div>";
  box.hidden = false;
}

function openFutures(res) {
  var now = Date.now();
  var id = "f" + now + Math.floor(Math.random() * 1000);
  state.cash -= res.margin;
  state.futures.push({
    id: id, symbol: selectedSymbol, direction: futDirection,
    leverage: res.leverage, margin: res.margin, entry: res.entry,
    openedAt: now
  });
  state.trades.push({
    id: id, t: now, type: "futures-open", symbol: selectedSymbol,
    direction: futDirection, leverage: res.leverage, margin: res.margin,
    entry: res.entry, total: res.margin
  });
  snapshotPortfolio();
  saveStore();
  $("futMarginInput").value = "";
  hideFutConfirm();
  renderAll();
  showToast("Posisi " + (futDirection === "long" ? "Long" : "Short") + " " + selectedSymbol +
    " " + res.leverage + "x dibuka — margin " + fmtIDR(res.margin) +
    ", likuidasi " + fmtIDR(res.liq) + ".", "success");
}

/* Tutup posisi. reason: "manual" | "liquidated".
   PnL negatif dibatasi sampai −margin agar kas tidak minus. */
function closeFutures(posId, reason) {
  var idx = -1;
  for (var i = 0; i < state.futures.length; i++) {
    if (state.futures[i].id === posId) { idx = i; break; }
  }
  if (idx < 0) return;
  var pos = state.futures[idx];
  var mark = markPrice(pos.symbol);
  if (mark == null) mark = pos.entry;
  var pnl = futPnl(pos, mark);
  var pnlCapped = Math.max(pnl, -pos.margin);
  var returned = reason === "liquidated" ? 0 : pos.margin + pnlCapped;
  state.cash += returned;
  state.futures.splice(idx, 1);
  state.trades.push({
    id: "f" + Date.now() + Math.floor(Math.random() * 1000),
    t: Date.now(),
    type: reason === "liquidated" ? "futures-liquidated" : "futures-close",
    symbol: pos.symbol, direction: pos.direction, leverage: pos.leverage,
    margin: pos.margin, entry: pos.entry, exitPrice: mark,
    pnl: reason === "liquidated" ? -pos.margin : pnlCapped, total: returned
  });
  snapshotPortfolio();
  saveStore();
  renderAll();
  if (reason === "liquidated") {
    showToast("Posisi " + pos.direction.toUpperCase() + " " + pos.symbol + " " +
      pos.leverage + "x TERLIKUIDASI — margin " + fmtIDR(pos.margin) + " hangus.", "error");
  } else {
    showToast("Posisi " + pos.direction.toUpperCase() + " " + pos.symbol + " " +
      pos.leverage + "x ditutup. PnL " + fmtSignedIDR(pnlCapped) +
      ", kembali " + fmtIDR(returned) + ".", "success");
  }
}

/* ---------------- Reset (dua langkah, tanpa alert browser) ---------------- */

var resetArmed = false;
var resetArmTimer = null;

function disarmReset() {
  resetArmed = false;
  clearTimeout(resetArmTimer);
  var btn = $("resetBtn");
  btn.classList.remove("armed");
  btn.textContent = "Reset Simulasi";
}

function doReset() {
  var d = defaultProfileData();
  state.cash = d.cash;
  state.holdings = {};
  state.trades = [];
  state.history = [];
  state.futures = [];
  window._pendingTrade = null;
  window._pendingFut = null;
  hideConfirm();
  hideFutConfirm();
  $("amountInput").value = "";
  $("futMarginInput").value = "";
  saveStore();
  renderAll();
  showToast("Simulasi direset — modal kembali ke Rp5.000.000.", "success");
}

/* ---------------- Profil (Guest) ---------------- */

function switchProfile(id) {
  if (id === store.activeProfileId) { $("profileMenu").hidden = true; return; }
  var p = null;
  store.profiles.forEach(function (x) { if (x.id === id) p = x; });
  if (!p) return;
  store.activeProfileId = p.id;
  state = p;
  saveStore();
  $("profileMenu").hidden = true;
  $("profileBtn").setAttribute("aria-expanded", "false");
  hideConfirm();
  hideFutConfirm();
  renderAll();
  showToast("Beralih ke profil " + p.name + ".", "success");
}

function createGuestProfile(name) {
  if (store.profiles.length >= MAX_PROFILES) {
    showToast("Maksimal 5 profil tercapai.", "error");
    return null;
  }
  var p = createProfile(name);
  store.profiles.push(p);
  store.activeProfileId = p.id;
  state = p;
  saveStore();
  return p;
}

/* ---------------- Event wiring ---------------- */

$("tabBuy").addEventListener("click", function () {
  tradeMode = "buy"; hideConfirm(); renderTradePanel();
});
$("tabSell").addEventListener("click", function () {
  tradeMode = "sell"; hideConfirm(); renderTradePanel();
});
$("amountInput").addEventListener("input", function () {
  hideConfirm(); updatePreview();
});

$("quickRow").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-pct]");
  if (!btn) return;
  var pct = parseFloat(btn.getAttribute("data-pct")) / 100;
  var price = currentPrice();
  if (!price) return;
  if (tradeMode === "buy") {
    $("amountInput").value = Math.floor(state.cash * pct);
  } else {
    var coins = holdingsAmount(selectedSymbol) * pct;
    $("amountInput").value = coins > 0 ? Number(coins.toFixed(8)) : "";
  }
  hideConfirm();
  updatePreview();
});

$("tradeBtn").addEventListener("click", function () {
  var res = computeTrade();
  if (!res) { showError("Masukkan jumlah dulu."); return; }
  if (!res.ok) { showError(res.msg); return; }
  showError(null);
  $("confirmText").innerHTML = tradeMode === "buy"
    ? "Beli <strong>" + fmtCoin(res.coins) + " " + selectedSymbol + "</strong> seharga <strong>" +
      fmtIDR(res.amount) + "</strong> (harga " + fmtIDR(res.price) + " / " + selectedSymbol + ")?"
    : "Jual <strong>" + fmtCoin(res.coins) + " " + selectedSymbol + "</strong> dan terima <strong>" +
      fmtIDR(res.total) + "</strong> (harga " + fmtIDR(res.price) + " / " + selectedSymbol + ")?";
  $("confirmBox").hidden = false;
  window._pendingTrade = res;
});

$("confirmYes").addEventListener("click", function () {
  if (window._pendingTrade) {
    executeTrade(window._pendingTrade);
    window._pendingTrade = null;
  }
});
$("confirmNo").addEventListener("click", function () {
  window._pendingTrade = null;
  hideConfirm();
});

/* Futures */
$("futLong").addEventListener("click", function () {
  futDirection = "long"; hideFutConfirm(); renderFuturesPanel();
});
$("futShort").addEventListener("click", function () {
  futDirection = "short"; hideFutConfirm(); renderFuturesPanel();
});

function setLeverage(lev) {
  futLeverage = Math.max(1, Math.min(MAX_LEVERAGE, Math.round(lev) || 10));
  $("futLeverage").value = futLeverage;
  document.querySelectorAll("#levChips .lev-chip").forEach(function (c) {
    c.classList.toggle("active", parseInt(c.getAttribute("data-lev"), 10) === futLeverage);
  });
  hideFutConfirm();
  renderFuturesPanel();
}
$("futLeverage").addEventListener("input", function () {
  setLeverage(parseInt($("futLeverage").value, 10));
});
$("levChips").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-lev]");
  if (!btn) return;
  setLeverage(parseInt(btn.getAttribute("data-lev"), 10));
});
$("futMarginInput").addEventListener("input", function () {
  hideFutConfirm(); updateFutPreview();
});

$("futBtn").addEventListener("click", function () {
  var res = computeFutures();
  if (!res) { showFutError("Masukkan margin dulu."); return; }
  if (!res.ok) { showFutError(res.msg); return; }
  showFutError(null);
  var dirTxt = futDirection === "long" ? "Long" : "Short";
  $("futConfirmText").innerHTML =
    "Buka posisi <strong>" + dirTxt + " " + selectedSymbol + " " + res.leverage + "x</strong> " +
    "dengan margin <strong>" + fmtIDR(res.margin) + "</strong>?<br>" +
    "Entry " + fmtIDR(res.entry) + " &middot; notional " + fmtIDR(res.notional) +
    " &middot; likuidasi <strong>" + fmtIDR(res.liq) + "</strong>.";
  $("futConfirmBox").hidden = false;
  window._pendingFut = res;
});

$("futConfirmYes").addEventListener("click", function () {
  if (window._pendingFut) {
    openFutures(window._pendingFut);
    window._pendingFut = null;
  }
});
$("futConfirmNo").addEventListener("click", function () {
  window._pendingFut = null;
  hideFutConfirm();
});

/* Reset simulasi — dua langkah, tanpa confirm() browser */
$("resetBtn").addEventListener("click", function () {
  if (!resetArmed) {
    resetArmed = true;
    var btn = $("resetBtn");
    btn.classList.add("armed");
    btn.textContent = "Klik lagi untuk konfirmasi";
    resetArmTimer = setTimeout(disarmReset, 4000);
    return;
  }
  disarmReset();
  doReset();
});

$("refreshBtn").addEventListener("click", function () { fetchPrices(); });

window.addEventListener("resize", drawChart);

/* Profil & layar sambutan */
$("profileBtn").addEventListener("click", function (e) {
  e.stopPropagation();
  var menu = $("profileMenu");
  var open = menu.hidden;
  menu.hidden = !open;
  $("profileBtn").setAttribute("aria-expanded", open ? "true" : "false");
});
document.addEventListener("click", function (e) {
  var menu = $("profileMenu");
  if (!menu.hidden && !e.target.closest(".profile-wrap")) {
    menu.hidden = true;
    $("profileBtn").setAttribute("aria-expanded", "false");
  }
});
$("createProfileBtn").addEventListener("click", function () {
  var name = $("newProfileName").value;
  var p = createGuestProfile(name);
  if (!p) return;
  $("newProfileName").value = "";
  $("profileMenu").hidden = true;
  hideConfirm();
  hideFutConfirm();
  renderAll();
  showToast("Profil " + p.name + " dibuat — modal awal Rp5.000.000.", "success");
});
$("newProfileName").addEventListener("keydown", function (e) {
  if (e.key === "Enter") $("createProfileBtn").click();
});

$("guestEnterBtn").addEventListener("click", function () {
  var name = $("guestNameInput").value;
  var p = createGuestProfile(name);
  if (!p) return;
  $("welcomeOverlay").hidden = true;
  renderAll();
  showToast("Selamat datang, " + p.name + "! Modal awal Rp5.000.000.", "success");
});
$("guestNameInput").addEventListener("keydown", function (e) {
  if (e.key === "Enter") $("guestEnterBtn").click();
});

/* ---------------- Start ---------------- */

renderAll();
fetchPrices();
setInterval(fetchPrices, REFRESH_MS);
if (store.profiles.length === 0) {
  $("welcomeOverlay").hidden = false;
  setTimeout(function () { $("guestNameInput").focus(); }, 100);
}
