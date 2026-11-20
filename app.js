"use strict";

/* ============================================================
   SIMULASI TRADING — game simulasi trading crypto (uang virtual)
   Harga live: CoinGecko public API (tanpa API key).
   Semua data tersimpan di localStorage, tanpa backend.
   ============================================================ */

var INITIAL_CASH = 5000000;
var STORAGE_KEY = "simulasi-trading-v1";
var COINGECKO_URL =
  "https://api.coingecko.com/api/v3/simple/price" +
  "?ids=bitcoin,ethereum,binancecoin,solana,ripple,dogecoin,cardano,tron" +
  "&vs_currencies=idr&include_24hr_change=true";
var REFRESH_MS = 30000;
var MAX_HISTORY = 240;

/* Daftar aset: id CoinGecko, simbol, nama, ikon */
var ASSETS = [
  { id: "bitcoin",     symbol: "BTC",  name: "Bitcoin",  icon: "\u20BF" },
  { id: "ethereum",    symbol: "ETH",  name: "Ethereum", icon: "\u039E" },
  { id: "binancecoin", symbol: "BNB",  name: "BNB",      icon: "B" },
  { id: "solana",      symbol: "SOL",  name: "Solana",   icon: "S" },
  { id: "ripple",      symbol: "XRP",  name: "XRP",      icon: "X" },
  { id: "dogecoin",    symbol: "DOGE", name: "Dogecoin", icon: "\u00D0" },
  { id: "cardano",     symbol: "ADA",  name: "Cardano",  icon: "A" },
  { id: "tron",        symbol: "TRX",  name: "Tron",     icon: "T" }
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

/* ---------------- State ---------------- */

function defaultState() {
  return { cash: INITIAL_CASH, holdings: {}, trades: [], history: [] };
}

function loadState() {
  try {
    var raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    var s = JSON.parse(raw);
    if (typeof s.cash !== "number") return defaultState();
    s.holdings = s.holdings || {};
    s.trades = s.trades || [];
    s.history = s.history || [];
    return s;
  } catch (e) {
    return defaultState();
  }
}

function saveState() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
}

var state = loadState();

/* Harga saat ini: { SYM: { idr, change } } + penanda live/offline */
var prices = {};
var pricesLive = false;
var lastUpdated = null;

/* UI state */
var selectedSymbol = "BTC";
var tradeMode = "buy"; // "buy" | "sell"

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
  return sign + idrFmt.format(Math.round(Math.abs(n))).replace("Rp", "Rp");
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

function fmtTime(ts) {
  return new Date(ts).toLocaleString("id-ID", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"
  });
}

function assetOf(symbol) {
  for (var i = 0; i < ASSETS.length; i++) {
    if (ASSETS[i].symbol === symbol) return ASSETS[i];
  }
  return null;
}

/* ---------------- Harga ---------------- */

function applyPrices(data, live) {
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
  var b = document.getElementById("priceBadge");
  b.className = "badge badge-loading";
  b.textContent = "Memuat harga…";
}

function updatePriceBadge() {
  var b = document.getElementById("priceBadge");
  var banner = document.getElementById("offlineBanner");
  if (pricesLive) {
    b.className = "badge badge-live";
    b.textContent = "● HARGA LIVE";
    banner.hidden = true;
  } else {
    b.className = "badge badge-offline";
    b.textContent = "● HARGA CONTOH (OFFLINE)";
    banner.hidden = false;
  }
}

/* ---------------- Hitung portofolio ---------------- */

function holdingValue(sym) {
  var h = state.holdings[sym];
  var p = prices[sym];
  if (!h || !p) return 0;
  return h.amount * p.idr;
}

function totalValue() {
  var total = state.cash;
  Object.keys(state.holdings).forEach(function (sym) {
    total += holdingValue(sym);
  });
  return total;
}

function snapshotPortfolio() {
  var v = totalValue();
  var last = state.history[state.history.length - 1];
  /* Simpan snapshot baru bila nilai berubah atau sudah >60 detik. */
  if (last && last.v === v && Date.now() - last.t < 60000) return;
  state.history.push({ t: Date.now(), v: Math.round(v) });
  if (state.history.length > MAX_HISTORY) {
    state.history = state.history.slice(-MAX_HISTORY);
  }
  saveState();
}

/* ---------------- Render ---------------- */

function $(id) { return document.getElementById(id); }

function renderAll() {
  renderMarket();
  renderPortfolio();
  renderHoldings();
  renderHistory();
  renderTradePanel();
  drawChart();
}

function renderMarket() {
  var list = $("marketList");
  list.innerHTML = "";
  ASSETS.forEach(function (a) {
    var p = prices[a.symbol];
    var row = document.createElement("button");
    row.type = "button";
    row.className = "market-row" + (a.symbol === selectedSymbol ? " selected" : "");
    var changeCls = p && p.change >= 0 ? "up" : "down";
    var changeTxt = p ? fmtPct(p.change) : "—";
    row.innerHTML =
      '<span class="coin-icon">' + a.icon + "</span>" +
      '<span class="coin-info">' +
        '<span class="coin-name">' + a.name + "</span>" +
        '<span class="coin-symbol">' + a.symbol + " / IDR</span>" +
      "</span>" +
      '<span class="coin-price">' +
        '<span class="price">' + (p ? fmtIDR(p.idr) : "—") + "</span>" +
        '<span class="change ' + changeCls + '">' + changeTxt + "</span>" +
      "</span>";
    row.addEventListener("click", function () {
      selectedSymbol = a.symbol;
      hideConfirm();
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
}

function renderHoldings() {
  var list = $("holdingsList");
  list.innerHTML = "";
  var syms = Object.keys(state.holdings).filter(function (s) {
    return state.holdings[s].amount > 0;
  });
  if (syms.length === 0) {
    list.innerHTML = "<p class=\"muted\">Belum ada koin. Pilih koin di pasar lalu beli untuk mulai.</p>";
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
      '<span class="coin-icon">' + (a ? a.icon : "?") + "</span>" +
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

function renderHistory() {
  var list = $("tradeHistory");
  list.innerHTML = "";
  if (state.trades.length === 0) {
    list.innerHTML = "<p class=\"muted\">Belum ada transaksi.</p>";
    return;
  }
  var sorted = state.trades.slice().sort(function (a, b) { return b.t - a.t; });
  sorted.forEach(function (tr) {
    var row = document.createElement("div");
    row.className = "history-row";
    var isBuy = tr.type === "buy";
    row.innerHTML =
      '<span class="history-info">' +
        '<span class="trade-type ' + (isBuy ? "up" : "down") + '">' +
          (isBuy ? "BELI " : "JUAL ") + tr.symbol + "</span>" +
        '<span class="history-detail">' + fmtTime(tr.t) + " &middot; " +
          fmtCoin(tr.amount) + " " + tr.symbol + " @ " + fmtIDR(tr.price) + "</span>" +
      "</span>" +
      '<span class="holding-value"><span class="value">' +
        (isBuy ? "−" : "+") + fmtIDR(tr.total) + "</span></span>" +
      '<button type="button" class="btn-delete" title="Hapus transaksi ini" aria-label="Hapus transaksi">&times;</button>';
    row.querySelector(".btn-delete").addEventListener("click", function () {
      state.trades = state.trades.filter(function (x) { return x.id !== tr.id; });
      saveState();
      renderHistory();
    });
    list.appendChild(row);
  });
}

/* ---------------- Grafik ---------------- */

function drawChart() {
  var canvas = $("chart");
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var w = canvas.clientWidth || 800;
  var h = 200;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  /* Garis acuan modal awal */
  var hist = state.history;
  if (hist.length === 0) {
    ctx.fillStyle = "#8b93a7";
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
  var pad = (max - min) * 0.15 || 1;
  min -= pad; max += pad;

  var left = 8, right = w - 8, top = 12, bottom = h - 24;
  function x(i) {
    return hist.length === 1 ? (left + right) / 2
      : left + (i / (hist.length - 1)) * (right - left);
  }
  function y(v) { return bottom - ((v - min) / (max - min)) * (bottom - top); }

  /* Garis modal awal (putus-putus) */
  ctx.strokeStyle = "rgba(240,185,11,0.5)";
  ctx.setLineDash([5, 5]);
  ctx.beginPath();
  ctx.moveTo(left, y(INITIAL_CASH));
  ctx.lineTo(right, y(INITIAL_CASH));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#f0b90b";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Modal awal " + fmtIDR(INITIAL_CASH), left + 2, y(INITIAL_CASH) - 4);

  /* Area + garis nilai portofolio */
  var lastV = hist[hist.length - 1].v;
  var up = lastV >= INITIAL_CASH;
  var color = up ? "#16c784" : "#ea3943";
  ctx.beginPath();
  hist.forEach(function (p, i) {
    if (i === 0) ctx.moveTo(x(i), y(p.v)); else ctx.lineTo(x(i), y(p.v));
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.lineTo(x(hist.length - 1), bottom);
  ctx.lineTo(x(0), bottom);
  ctx.closePath();
  var grad = ctx.createLinearGradient(0, top, 0, bottom);
  grad.addColorStop(0, up ? "rgba(22,199,132,0.25)" : "rgba(234,57,67,0.25)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = grad;
  ctx.fill();

  /* Titik terakhir + label nilai */
  ctx.beginPath();
  ctx.arc(x(hist.length - 1), y(lastV), 4, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.fillStyle = "#e8ecf3";
  ctx.font = "bold 12px Inter, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(fmtIDR(lastV), right - 2, Math.max(14, y(lastV) - 8));
}

/* ---------------- Trading ---------------- */

function currentPrice() {
  var p = prices[selectedSymbol];
  return p ? p.idr : null;
}

function renderTradePanel() {
  var a = assetOf(selectedSymbol);
  var p = currentPrice();
  $("tradeIcon").textContent = a ? a.icon : "?";
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
  var a = assetOf(selectedSymbol);
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
  } else {
    state.cash += res.total;
    var hs = state.holdings[selectedSymbol];
    hs.amount -= res.coins;
    if (hs.amount <= 1e-12) delete state.holdings[selectedSymbol];
    state.trades.push({
      id: id, t: now, type: "sell", symbol: selectedSymbol,
      amount: res.coins, price: res.price, total: res.total
    });
  }
  snapshotPortfolio();
  saveState();
  $("amountInput").value = "";
  hideConfirm();
  renderAll();
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
  var a = assetOf(selectedSymbol);
  $("confirmText").innerHTML = tradeMode === "buy"
    ? "Beli <strong>" + fmtCoin(res.coins) + " " + selectedSymbol + "</strong> seharga <strong>" +
      fmtIDR(res.amount) + "</strong> (harga " + fmtIDR(res.price) + " / " + selectedSymbol + ")?"
    : "Jual <strong>" + fmtCoin(res.coins) + " " + selectedSymbol + "</strong> dan terima <strong>" +
      fmtIDR(res.total) + "</strong> (harga " + fmtIDR(res.price) + " / " + selectedSymbol + ")?";
  $("confirmYes").dataset.pending = "1";
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

$("resetBtn").addEventListener("click", function () {
  if (!confirm("Reset simulasi? Modal kembali ke Rp5.000.000 dan semua riwayat transaksi dihapus.")) return;
  state = defaultState();
  saveState();
  window._pendingTrade = null;
  hideConfirm();
  $("amountInput").value = "";
  renderAll();
});

$("refreshBtn").addEventListener("click", function () { fetchPrices(); });

window.addEventListener("resize", drawChart);

/* ---------------- Start ---------------- */

renderAll();
fetchPrices();
setInterval(fetchPrices, REFRESH_MS);
