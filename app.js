"use strict";

/* ============================================================
   SIMULASI TRADING — game simulasi trading crypto (uang virtual)
   Harga live: CoinGecko public API (tanpa API key), cadangan
   Binance Vision (data-api.binance.vision, tanpa API key).
   Semua data tersimpan di localStorage, tanpa backend.
   - Spot: beli/jual 8 koin.
   - Futures: Long/Short, leverage 1x-100x, likuidasi sederhana
     (tanpa maintenance margin, tanpa fee).
   - Akun Guest: sampai 5 profil, data per profil terpisah.
   ============================================================ */

var INITIAL_CASH = 5000000;
var STORAGE_KEY = "simulasi-trading-v2";      /* format berprofil */
var STORAGE_KEY_V1 = "simulasi-trading-v1";   /* format lama (tanpa profil) */
var LASTLIVE_KEY = "simulasi-trading-lastlive-v1"; /* harga live terakhir (beku) */
var COINGECKO_URL =
  "https://api.coingecko.com/api/v3/simple/price" +
  "?ids=bitcoin,ethereum,binancecoin,solana,ripple,dogecoin,cardano,tron" +
  "&vs_currencies=idr&include_24hr_change=true";
/* Cadangan harga: Binance Vision (mirror publik data pasar Binance,
   tanpa API key, tidak diblokir geo seperti api.binance.com).
   Harga USDT per koin x kurs USDT/IDR = harga Rupiah. */
var BINANCE_VISION_URL =
  "https://data-api.binance.vision/api/v3/ticker/24hr?symbols=" +
  encodeURIComponent(JSON.stringify([
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "USDTIDR"
  ]));
var BINANCE_SYMBOL = {
  BTC: "BTCUSDT", ETH: "ETHUSDT", BNB: "BNBUSDT", SOL: "SOLUSDT",
  XRP: "XRPUSDT", DOGE: "DOGEUSDT", ADA: "ADAUSDT", TRX: "TRXUSDT"
};
var REFRESH_MS = 30000;
var MAX_HISTORY = 240;
/* Batas riwayat trade per profil (pola yang sama seperti MAX_HISTORY
   untuk snapshot portofolio): riwayat trade TIDAK PERNAH dibatasi,
   sehingga renderHistory() me-render SEMUA baris di tiap renderAll()
   (tiap refresh harga 30 detik + tiap interaksi) dan localStorage
   membengkak tanpa batas. Pernah: 600 trade → 600 baris di DOM,
   renderAll() 98,6 ms (median) dan store 59 KB, terus membesar.
   200 entri terakhir cukup untuk simulator (riwayat tetap hanya-baca,
   tanpa tombol hapus — yang terbuang otomatis hanya entri tertua). */
var MAX_TRADES = 200;
var MAX_PROFILES = 5;
var MAX_LEVERAGE = 100;
/* Nomor urut fetch harga (lihat fetchPrices) — naik tiap fetch dimulai. */
var priceFetchSeq = 0;

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
        var trimmedTrades = false;
        s.profiles.forEach(function (p) {
          p.holdings = p.holdings || {};
          p.trades = p.trades || [];
          /* Pangkas riwayat lama yang tersimpan sebelum batas ini ada. */
          if (p.trades.length > MAX_TRADES) {
            p.trades = p.trades.slice(-MAX_TRADES);
            trimmedTrades = true;
          }
          p.history = p.history || [];
          p.futures = p.futures || [];
          if (typeof p.cash !== "number") p.cash = INITIAL_CASH;
        });
        /* Pemangkasan HARUS tersimpan saat load: tanpa ini batas 200
           hanya hidup di memori dan localStorage tetap menyimpan
           250+ entri sampai ada saveStore() berikutnya. Dulu itu
           tertutup secara kebetulan — snapshot pertama pasca-reload
           selalu append (riwayat masih kosong) lalu saveStore();
           sejak profil baru langsung punya titik grafik, snapshot
           pasca-reload bisa no-op (titik segar, nilai sama) sehingga
           pemangkasan tidak pernah tersimpan. */
        if (trimmedTrades) {
          try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); } catch (e) {}
        }
        /* activeProfileId BASI (menunjuk profil yang tidak ada —
           mis. localStorage disunting/rusak): jangan biarkan state
           null sementara profil valid masih ada. Tanpa ini layar
           sambutan tidak tampil (profiles.length > 0) DAN tombol
           profil tersembunyi (state null) sehingga user jalan buntu
           tanpa jalan masuk — kas tampil Rp5.000.000 default padahal
           profilnya punya data. Pulih ke profil pertama; bila tidak
           ada profil sama sekali, null (overlay sambutan tampil
           seperti biasa). */
        var hasActive = false;
        s.profiles.forEach(function (p) { if (p.id === s.activeProfileId) hasActive = true; });
        if (!hasActive) {
          s.activeProfileId = s.profiles.length ? s.profiles[0].id : null;
        }
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
/* Harga live TERAKHIR yang pernah diterima, per simbol — dipakai
   sebagai harga mark "beku" untuk hitung PnL saat offline, supaya
   PnL tidak pernah dihitung dari harga contoh. Disimpan juga di
   localStorage (lihat loadLastLivePrices) agar tetap ada setelah
   reload halaman saat offline — tanpa ini, tutup posisi setelah
   reload memakai harga entry dan PnL jadi 0 (rugi/untung hilang). */
var lastLivePrices = {};
function loadLastLivePrices() {
  try {
    var raw = localStorage.getItem(LASTLIVE_KEY);
    if (!raw) return;
    var s = JSON.parse(raw);
    if (!s || typeof s !== "object") return;
    Object.keys(s).forEach(function (sym) {
      var d = s[sym];
      if (d && isFinite(d.idr) && d.idr > 0) {
        lastLivePrices[sym] = { idr: d.idr, change: isFinite(d.change) ? d.change : 0 };
      }
    });
  } catch (e) { /* data rusak — abaikan, mulai dari kosong */ }
}
function saveLastLivePrices() {
  try { localStorage.setItem(LASTLIVE_KEY, JSON.stringify(lastLivePrices)); } catch (e) {}
}
loadLastLivePrices();
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
  /* < 1 satoshi (mis. 0,0000000089 BTC dari beli Rp10) butuh 12
     desimal — dengan 8 desimal tampil "0" sehingga riwayat jual
     terbaca "0 BTC" padahal ada koin yang terjual. */
  var dec = n >= 1000 ? 2 : n >= 1 ? 4 : n >= 0.01 ? 6 : n >= 1e-8 ? 8 : 12;
  return n.toLocaleString("id-ID", {
    minimumFractionDigits: 0, maximumFractionDigits: dec
  });
}

/* Jumlah koin untuk diisi ke input jual (tombol cepat): string
   desimal biasa, desimal secukupnya. toFixed(8) membulatkan
   holding mikro (< 1 satoshi, mis. beli Rp10 BTC = 0,0000000089
   BTC) jadi 0 sehingga tombol cepat 25%/50% mengisi "0" dan tidak
   terjadi apa-apa; Number(...) juga menampilkan "1e-8" (notasi
   ilmiah) untuk 75%/100%. Nilai yang dikembalikan tidak pernah 0
   bila koinnya > 0, dan tidak pernah notasi ilmiah.
   Format desimal memakai KOMA ("1,125"), bukan titik — persis
   seperti tampilan holding aplikasi. Titik desimal ("1.125") dibaca
   parseAmount sebagai ribuan Indonesia (1125 koin) sehingga tombol
   cepat 75% dari holding 1,5 koin mengisi "1.125" lalu pratinjau
   menolak "Koin tidak cukup" padahal koinnya cukup. */
function fmtInputCoins(coins) {
  if (!(coins > 0) || !isFinite(coins)) return "";
  var dec = 8;
  var s = coins.toFixed(dec);
  while (Number(s) === 0 && dec < 18) { dec++; s = coins.toFixed(dec); }
  return s.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "").replace(".", ",");
}

/* Baca angka yang diketik user dengan FORMAT INDONESIA — aplikasi
   ini menampilkan semua angka sebagai "Rp1.000.000" / "0,00089286"
   (titik = pemisah ribuan, koma = desimal), jadi user wajar
   mengetik persis seperti itu. Sebelumnya input memakai
   type="number" + parseFloat mentah, sehingga:
   - "1.000.000" dibaca jadi Rp1 (browser menelan titik kedua,
     parseFloat berhenti di titik pertama) — beli Rp1.000.000
     diam-diam jadi beli Rp1;
   - "0,00089286" dibaca jadi 89286 koin (koma dibuang) — jual
     selalu gagal "Koin tidak cukup" padahal angkanya sama dengan
     yang ditampilkan;
   - margin "100.000" dibaca jadi Rp100 — notional Rp1.000, bukan
     Rp1.000.000.
   Aturan: ada koma -> format Indonesia (buang titik ribuan, koma
   jadi titik desimal). Tanpa koma, "1.000.000" / "100.000" dibaca
   sebagai ribuan HANYA bila kelompok pertamanya bukan 0 — supaya
   desimal mikro seperti "0.000000002" (dari tombol cepat jual)
   tetap dibaca sebagai desimal, bukan 2 koin. Selain itu
   parseFloat biasa ("1000000", "0.0005"). Bukan angka -> NaN. */
function parseAmount(str) {
  if (typeof str !== "string") return NaN;
  var s = str.trim().replace(/\s/g, "");
  if (!s) return NaN;
  /* Awalan "Rp" ditoleransi — aplikasi sendiri menampilkan semua
     angka sebagai "Rp1.000.000", jadi user wajar mengetik atau
     menempel persis seperti itu ("Rp1.000.000", "Rp 100.000").
     Tanpa ini parseAmount mengembalikan NaN dan pratinjau diam-diam
     hilang tanpa pesan apa-apa (bukan error, bukan pratinjau). */
  s = s.replace(/^rp/i, "");
  if (s.indexOf(",") >= 0) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (/^([1-9]\d{0,2})(\.\d{3})+$/.test(s)) {
    s = s.replace(/\./g, "");
  }
  if (!/^\d+(\.\d+)?$/.test(s)) return NaN;
  var n = parseFloat(s);
  return isFinite(n) ? n : NaN;
}

/* Angka ringkas untuk sumbu grafik, mis. Rp5,2 jt / Rp1,13 M.
   Satuan dipilih SEKALI dari nilai maks sumbu (axisUnit) lalu
   dipakai semua label sumbu itu (fmtCompactAxis). fmtCompact()
   yang lama memilih satuan PER LABEL — pada grafik BTC ~Rp1,12
   Miliar, garis grid bawah (Rp998,77 jt, < 1e9) memakai "jt"
   sementara garis di atasnya (Rp1,04 M, > 1e9) memakai "M":
   satu sumbu, dua satuan. Kini: "Rp0,99 M" di bawah, "Rp1,15 M"
   di atas — satu satuan di seluruh sumbu. */
function axisUnit(maxV) {
  var abs = Math.abs(maxV);
  if (abs >= 1e9) return " M";
  if (abs >= 1e6) return " jt";
  if (abs >= 1e3) return " rb";
  return "";
}
function fmtCompactAxis(n, unit) {
  if (!isFinite(n)) return "—";
  if (!unit) return fmtIDR(n);
  var scaled = unit === " M" ? n / 1e9 : unit === " jt" ? n / 1e6 : n / 1e3;
  /* Nilai di bawah 1 satuan (mis. Rp998,77 jt pada sumbu "M")
     butuh 2 desimal: tanpa ini 0,99877 dibulatkan jadi "Rp1 M"
     — sama persis dengan label Rp1.000.000.000 dan menyesatkan. */
  var minDec = Math.abs(scaled) < 1 ? 2 : 0;
  return "Rp" + scaled.toLocaleString("id-ID",
    { minimumFractionDigits: minDec, maximumFractionDigits: 2 }) + unit;
}
function fmtCompact(n) {
  return fmtCompactAxis(n, axisUnit(n));
}

function fmtTime(ts) {
  return new Date(ts).toLocaleString("id-ID", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"
  });
}

function fmtClock(ts) {
  return new Date(ts).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

/* Label waktu sumbu X: sertakan tanggal bila rentang melewati
   pergantian hari — jam saja ambigu: riwayat portofolio bisa
   merentang berhari-hari (label "23.10" -> "01.05" tanpa tanggal
   tampak seperti waktu mundur), dan label kanan grafik harga 24 jam
   ("19.33") tidak menyebut hari apa padahal titik kirinya kemarin.
   Bila satu hari yang sama, jam saja cukup. */
function spansDays(t0, t1) {
  return new Date(t0).toDateString() !== new Date(t1).toDateString();
}
function fmtAxisTime(ts, withDate) {
  return withDate ? fmtTime(ts) : fmtClock(ts);
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

/* Fokus keyboard di dalam daftar yang dibangun ulang — renderMarket(),
   renderPositions(), dan renderProfileUI() menghapus semua baris
   (innerHTML = "") lalu membangunnya lagi di tiap renderAll() (tiap
   refresh harga 30 detik). Tanpa ini, elemen yang sedang difokuskan
   ikut dihancurkan sehingga fokus jatuh ke <body> dan pengguna
   keyboard kehilangan posisinya tiap 30 detik — pernah: fokus di
   baris pasar ETH / tombol Tutup posisi / item profil hilang setelah
   renderAll(), padahal elemen statis seperti amountInput tetap fokus.
   Tangkap identitas (atribut data-*) elemen yang difokuskan SEBELUM
   daftar dibersihkan, lalu kembalikan fokus ke elemen baru yang sama
   SESUDAH daftar dibangun — hanya bila elemen itu masih ada (posisi
   yang terlikuidasi / tertutup TIDAK difokuskan ulang ke tombol lain,
   karena itu bisa menutup posisi yang salah). preventScroll: true
   supaya pengembalian fokus tidak menggeser halaman. */
function focusedKey(listEl, selector, attr) {
  var el = document.activeElement;
  if (!el || !listEl.contains(el)) return null;
  var row = el.closest ? el.closest(selector) : null;
  return row ? row.getAttribute(attr) : null;
}
function refocusKey(listEl, selector, attr, key) {
  if (!key) return;
  var el = listEl.querySelector(selector + "[" + attr + '="' + key + '"]');
  if (el) el.focus({ preventScroll: true });
}

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
  /* Simpan salinan harga live terakhir — hanya saat live, tidak
     pernah dari harga contoh offline. */
  if (live) {
    lastLivePrices = {};
    Object.keys(prices).forEach(function (sym) {
      lastLivePrices[sym] = { idr: prices[sym].idr, change: prices[sym].change };
    });
    saveLastLivePrices();
  }
  lastUpdated = Date.now();
  /* Batalkan konfirmasi trade/futures yang harganya sudah basi
     (lihat invalidateStaleConfirms) — sebelum render ulang. */
  invalidateStaleConfirms();
  updatePriceBadge();
  checkLiquidations();
  appendPricePoint();
  /* Grafik koin terpilih DICOBA LAGI tiap refresh harga — termasuk
     bila grafiknya sudah live: guard kesegaran di fetchPriceChart
     (live 10 menit, cadangan 60 detik) yang memutuskan perlu
     fetch ulang atau tidak. Tanpa ini grafik 24 jam TIDAK PERNAH
     di-fetch ulang selama halaman dibiarkan terbuka (dulu hanya
     dipanggil bila grafik belum live): deretnya tidak bergeser,
     titik live hanya ditempel di ujung, dan begitu cap 400 titik
     tercapai grafik tinggal ~3 jam terakhir padahal labelnya
     tetap "24 jam terakhir". */
  fetchPriceChart(selectedSymbol);
  snapshotPortfolio();
  renderAll();
}

/* Ambil JSON dengan batas waktu; gagal (timeout/HTTP/bukan JSON)
   dilempar sebagai Error agar pemanggil bisa mencoba sumber lain. */
async function fetchJsonTimeout(url, ms) {
  var controller = new AbortController();
  var timer = setTimeout(function () { controller.abort(); }, ms);
  try {
    var res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/* Harga cadangan dari Binance Vision: harga USDT tiap koin dikali
   kurs USDT/IDR. Dipakai hanya bila CoinGecko gagal, sebelum jatuh
   ke harga contoh — supaya harga live tetap tersedia dan posisi
   tidak pernah dibuka di harga contoh. */
async function fetchPricesBinance() {
  var arr = await fetchJsonTimeout(BINANCE_VISION_URL, 10000);
  if (!Array.isArray(arr) || !arr.length) {
    throw new Error("Respons Binance kosong");
  }
  var bySym = {};
  arr.forEach(function (t) { if (t && t.symbol) bySym[t.symbol] = t; });
  var usdtIdr = bySym["USDTIDR"] && parseFloat(bySym["USDTIDR"].lastPrice);
  if (!isFinite(usdtIdr) || usdtIdr <= 0) {
    throw new Error("Kurs USDT/IDR Binance tidak tersedia");
  }
  var data = {};
  var ok = 0;
  ASSETS.forEach(function (a) {
    var t = bySym[BINANCE_SYMBOL[a.symbol]];
    var last = t && parseFloat(t.lastPrice);
    if (isFinite(last) && last > 0) {
      data[a.id] = {
        idr: last * usdtIdr,
        idr_24h_change: parseFloat(t.priceChangePercent) || 0
      };
      ok++;
    }
  });
  if (ok < ASSETS.length) {
    throw new Error("Harga Binance tidak lengkap (" + ok + "/" + ASSETS.length + ")");
  }
  return data;
}

/* Respons harga live harus LENGKAP (8 koin, semua idr angka > 0).
   Pernah: CoinGecko mengembalikan sebagian koin saja (mis. SOL hilang)
   lalu applyPrices tetap mengklaim HARGA LIVE — koin yang hilang
   dinilai Rp0 (total portofolio anjlok palsu dan snapshot grafik ikut
   mencatat nilai palsu) dan pemeriksaan likuidasi posisinya dilewati.
   Respons tidak lengkap = gagal: coba Binance, lalu harga contoh. */
function isCompletePriceData(data) {
  if (!data || typeof data !== "object") return false;
  for (var i = 0; i < ASSETS.length; i++) {
    var d = data[ASSETS[i].id];
    if (!d || typeof d.idr !== "number" || !isFinite(d.idr) || d.idr <= 0) return false;
  }
  return true;
}

async function fetchPrices() {
  /* Nomor urut fetch — hanya fetch TERBARU yang boleh menerapkan
     hasilnya. Tanpa ini, dua fetch yang tumpang tindih (interval 30 detik
     vs timeout 10+10 detik, atau klik Refresh saat fetch lama masih jalan)
     bisa membuat hasil basi menimpa harga live yang lebih baru — termasuk
     harga contoh yang menimpa harga live dan bisa melikuidasi posisi
     Short secara keliru. */
  var mySeq = ++priceFetchSeq;
  setBadgeLoading();
  try {
    var data = await fetchJsonTimeout(COINGECKO_URL, 10000);
    if (!isCompletePriceData(data)) {
      throw new Error("Respons CoinGecko tidak lengkap");
    }
    if (mySeq === priceFetchSeq) applyPrices(data, true);
    return;
  } catch (e) {
    /* CoinGecko gagal — coba sumber cadangan Binance. */
  }
  try {
    var bin = await fetchPricesBinance();
    if (mySeq === priceFetchSeq) applyPrices(bin, true);
    return;
  } catch (e2) {
    /* Kedua sumber live gagal — baru jatuh ke harga contoh. */
  }
  /* Fallback terakhir: harga contoh, DIBERI LABEL OFFLINE di UI.
     Hanya bila tidak ada fetch yang lebih baru sedang berjalan. */
  if (mySeq !== priceFetchSeq) return;
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

/* Bila kotak konfirmasi trade/futures sedang terbuka dan harga koin
   yang dipilih sudah berubah sejak pratinjau dibuat, batalkan
   konfirmasi itu — eksekusi tidak boleh memakai harga lama yang
   sudah tidak berlaku di pasar. Pernah: beli dieksekusi
   @ Rp1.120.000.000 padahal harga sudah Rp1.100.000.000, dan posisi
   Long langsung −18,18% begitu dibuka karena entry memakai harga
   lama. Dipanggil dari applyPrices() tiap harga diperbarui; bila
   harga TIDAK berubah, konfirmasi dibiarkan (tidak mengganggu
   user yang konfirmasinya masih berlaku).
   TOLERANSI 0,1%: perubahan yang lebih kecil dari itu TIDAK
   membatalkan konfirmasi. Tanpa toleransi, SETIAP geser harga —
   bahkan Rp1.000 dari Rp1,12 Miliar (0,00009%) — menutup konfirmasi
   yang sedang dibaca user; dengan fallback Binance (harga float
   dari last USDT x kurs) hampir tiap refresh 30 detik harganya
   geser sedikit sehingga konfirmasi praktis tidak pernah bertahan
   sampai user sempat menekan "Ya". Geser <= 0,1% mengubah harga
   eksekusi paling banyak 0,1% — jauh dari kasus asli di atas. */
function priceMovedSignificantly(oldPrice, newPrice) {
  if (!oldPrice || !newPrice) return true;
  return Math.abs(newPrice - oldPrice) / oldPrice > 0.001;
}

function invalidateStaleConfirms() {
  /* Harga tidak live lagi (offline — CoinGecko + Binance gagal,
     harga contoh dipakai): batalkan SEMUA konfirmasi yang sedang
     terbuka, apa pun pergerakan harganya. Tanpa ini, konfirmasi
     yang dibuka saat live bisa dieksekusi saat badge sudah OFFLINE
     bila harga contoh kebetulan sama dengan harga live (toleransi
     0,1% di bawah tidak menangkapnya — pernah: TRX live Rp4.500
     == contoh Rp4.500, posisi Long + beli spot tereksekusi saat
     offline). Trade/futures hanya boleh saat harga live. */
  if (!pricesLive) {
    var hadTrade = window._pendingTrade && !$("confirmBox").hidden;
    var hadFut = window._pendingFut && !$("futConfirmBox").hidden;
    if (hadTrade || hadFut) {
      hideConfirm();
      hideFutConfirm();
      showToast("Harga live tidak tersedia — konfirmasi dibatalkan. Tekan Refresh untuk mencoba lagi.", "error");
    }
    return;
  }
  var price = currentPrice();
  if (price == null) return;
  if (window._pendingTrade && !$("confirmBox").hidden &&
      window._pendingTrade.symbol === selectedSymbol &&
      priceMovedSignificantly(window._pendingTrade.price, price)) {
    window._pendingTrade = null;
    hideConfirm();
    showToast("Harga " + selectedSymbol + " berubah — silakan periksa dan konfirmasi ulang.", "error");
  }
  if (window._pendingFut && !$("futConfirmBox").hidden &&
      window._pendingFut.symbol === selectedSymbol &&
      priceMovedSignificantly(window._pendingFut.entry, price)) {
    window._pendingFut = null;
    hideFutConfirm();
    showToast("Harga " + selectedSymbol + " berubah — silakan periksa dan konfirmasi ulang.", "error");
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

/* Harga mark untuk hitung PnL posisi futures — TIDAK PERNAH memakai
   harga contoh offline (harga contoh jauh dari harga live dan pernah
   membuat posisi terlikuidasi). Saat live: harga live saat ini.
   Saat offline: harga live TERAKHIR yang pernah diterima (beku,
   frozen: true). Bila belum pernah ada harga live sama sekali:
   null (PnL ditampilkan "—"). */
function pnlMark(symbol) {
  if (pricesLive) {
    var p = prices[symbol];
    return p ? { price: p.idr, frozen: false } : null;
  }
  var lp = lastLivePrices[symbol];
  return lp ? { price: lp.idr, frozen: true } : null;
}

/* Harga mark untuk menilai holding spot — pola yang sama seperti
   pnlMark(): saat live pakai harga live saat ini, saat offline pakai
   harga live TERAKHIR (beku), TIDAK PERNAH harga contoh. Sebelumnya
   holdingValue() memakai prices[] mentah sehingga saat offline total
   portofolio + nilai holding melonjak palsu (BTC Rp1,5 Miliar vs live
   ~Rp1,12 Miliar: total Rp5.339.286 padahal seharusnya Rp5.000.000). */
function spotMark(symbol) {
  if (pricesLive) {
    var p = prices[symbol];
    return p ? { price: p.idr, frozen: false } : null;
  }
  var lp = lastLivePrices[symbol];
  return lp ? { price: lp.idr, frozen: true } : null;
}

/* Periksa semua posisi terbuka setiap kali harga diperbarui.
   Bila harga mark menyentuh/melewati harga likuidasi, posisi
   ditutup otomatis dan margin hangus. */
function checkLiquidations() {
  if (!state || !state.futures.length) return;
  var doomed = [];
  state.futures.forEach(function (pos) {
    var m = pnlMark(pos.symbol);
    if (!m) return;
    var mark = m.price;
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
  if (!h) return 0;
  /* Nilai dari harga live / harga live terakhir (beku); bila belum
     pernah ada harga live, jangan dinilai sama sekali (0) daripada
     memakai harga contoh. */
  var m = spotMark(sym);
  if (!m) return 0;
  return h.amount * m.price;
}

function futuresFloatPnl() {
  var total = 0;
  state.futures.forEach(function (pos) {
    var m = pnlMark(pos.symbol);
    if (m) total += Math.max(futPnl(pos, m.price), -pos.margin);
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
  /* JANGAN rekam snapshot saat harga contoh offline: nilai koin
     dihitung dari harga contoh (BTC Rp1,5 Miliar vs live ~Rp1,12
     Miliar) sehingga grafik portofolio mencatat lonjakan palsu yang
     tersimpan permanen di riwayat. Grafik cukup berhenti (beku)
     sampai harga live kembali — sama seperti grafik harga 24 jam
     yang tidak menambah titik saat offline. */
  if (!pricesLive) return;
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
    window.__chartLabels = null;
    /* Hook grafik portofolio juga direset: tanpa ini, ganti ke profil
       ber-riwayat kosong membiarkan __portfolioChart berisi titik
       profil sebelumnya (basi) padahal kanvas menampilkan
       "Belum ada data." — hook harus mencerminkan yang digambar. */
    window.__portfolioChart = null;
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
  /* Sumbu X berbasis WAKTU, bukan urutan titik: titik dipetakan dari
     stempel waktunya (t pertama -> kiri, t terakhir -> kanan).
     Sebelumnya x(i) memakai indeks — lompatan nilai setelah jeda
     panjang tanpa snapshot (mis. offline berjam-jam lalu harga live
     kembali) digambar dalam SATU langkah indeks (~2px dari 240 titik)
     sehingga tampak seperti dinding tegak di ujung kanan, padahal
     nilainya berubah selama berjam-jam. Dengan sumbu waktu, garis
     membentang selebar jeda sebenarnya. Bila semua stempel sama
     (atau hanya 1 titik), kembali ke pemetaan indeks seperti dulu. */
  var tFirst = hist[0].t, tLast = hist[hist.length - 1].t;
  var timeAxis = hist.length > 1 && tLast > tFirst;
  function x(i) {
    if (hist.length === 1) return (left + right) / 2;
    if (timeAxis) return left + ((hist[i].t - tFirst) / (tLast - tFirst)) * (right - left);
    return left + (i / (hist.length - 1)) * (right - left);
  }
  function y(v) { return bottom - ((v - min) / (max - min)) * (bottom - top); }

  /* Garis grid horizontal + label sumbu — satu satuan untuk seluruh
     sumbu (dipilih dari nilai maks), bukan per label. */
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.textAlign = "left";
  var gridLines = 4;
  var yUnit = axisUnit(max);
  var yLabels = [];
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
    var yLab = fmtCompactAxis(gv, yUnit);
    yLabels.push(yLab);
    ctx.fillText(yLab, 4, gy + 3);
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
  /* Label nilai terakhir (kanan, di atas titik) bisa menumpuk pill
     "Modal awal" bila nilainya ~ modal awal (profil baru: baseY == ly)
     dan kanvas sempit — di 320px pill x 66–191 vs label x 163–250.
     Bila bertabrakan: geser label nilai ke bawah titik; kalau tidak
     muat, geser pill ke bawah garisnya; terakhir, pill ke pojok atas. */
  var lastV = hist[hist.length - 1].v;
  var ly = y(lastV);
  ctx.font = "bold 12px 'IBM Plex Mono', monospace";
  var lastTw = ctx.measureText(fmtIDR(lastV)).width;
  ctx.font = "10px Inter, sans-serif";
  var pillTop = Math.max(2, baseY - 18);
  var lastBase = Math.max(14, ly - 10);
  var pillRect = { x0: left + 4, x1: left + 4 + tw + 12, y0: pillTop, y1: pillTop + 15 };
  var lastRect = { x0: right - 2 - lastTw, x1: right - 2, y0: lastBase - 12, y1: lastBase };
  function rectsHit(a, b) {
    return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  }
  if (rectsHit(pillRect, lastRect)) {
    var pillBelow = { x0: pillRect.x0, x1: pillRect.x1, y0: baseY + 4, y1: baseY + 19 };
    var lastBelow = { x0: lastRect.x0, x1: lastRect.x1, y0: ly + 10, y1: ly + 22 };
    if (ly + 22 <= h - 20 && !rectsHit(pillRect, lastBelow)) {
      lastBase = ly + 22;
    } else if (baseY + 19 <= bottom && !rectsHit(pillBelow, lastRect)) {
      pillTop = baseY + 4;
    } else {
      pillTop = 2;
    }
  }
  ctx.fillStyle = "rgba(240,185,11,0.16)";
  roundRectPath(ctx, left + 4, pillTop, tw + 12, 15, 7);
  ctx.fill();
  ctx.fillStyle = "#f0b90b";
  ctx.fillText(label, left + 10, pillTop + 11);

  /* Garis nilai portofolio — dihaluskan (kurva) + isi gradien */
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

  /* Label waktu sumbu X (awal & akhir): sertakan tanggal bila
     riwayat merentang lebih dari satu hari kalender. Bila riwayat
     baru satu titik (profil baru: hanya titik "sekarang"), awal dan
     akhir adalah waktu yang sama — gambar SATU label saja, di tengah
     di bawah titiknya; dua label akan tampil sebagai waktu yang sama
     di kedua ujung ("00.45" ... "00.45"). */
  var xDate = spansDays(hist[0].t, hist[hist.length - 1].t);
  var xLabels = [fmtAxisTime(hist[0].t, xDate)];
  ctx.fillStyle = "#5e6673";
  ctx.font = "10px 'IBM Plex Mono', monospace";
  if (hist.length === 1) {
    ctx.textAlign = "center";
    ctx.fillText(xLabels[0], x(0), h - 8);
  } else {
    xLabels.push(fmtAxisTime(hist[hist.length - 1].t, xDate));
    ctx.textAlign = "left";
    ctx.fillText(xLabels[0], left, h - 8);
    ctx.textAlign = "right";
    ctx.fillText(xLabels[1], right, h - 8);
  }

  /* Titik terakhir + label nilai */
  var lx = x(hist.length - 1);
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
  ctx.fillText(fmtIDR(lastV), right - 2, lastBase);

  /* Hook untuk pengujian otomatis (bukan bagian UI). */
  window.__chartLabels = {
    pill: { x0: left + 4, x1: left + 4 + tw + 12, y0: pillTop, y1: pillTop + 15 },
    last: { x0: right - 2 - lastTw, x1: right - 2, y0: lastBase - 12, y1: lastBase }
  };
  /* Hook koordinat titik grafik portofolio (bukan bagian UI). */
  window.__portfolioChart = {
    points: hist.map(function (p, i) { return { t: p.t, v: p.v, x: x(i), y: y(p.v) }; }),
    w: w, h: h,
    yLabels: yLabels,
    xLabels: xLabels
  };
}

/* ---------------- Grafik harga koin ---------------- */

/* Riwayat harga per koin — HANYA di memori, TIDAK disimpan ke
   localStorage, jadi skema penyimpanan/profil tidak berubah.
   priceHistory[symbol] = { points: [{t, v}], live: bool,
   estimated: bool, loading: bool, fetchedAt: ms|null }.
   Sumber: CoinGecko market_chart 24 jam (gratis, tanpa API key).
   Bila market_chart gagal padahal harga live tersedia (misal
   rate limit 429), deret cadangan DIJANGKAR pada harga live saat
   ini / harga live terakhir — BUKAN pada harga contoh (BTC
   Rp1,5 Miliar) — dan diberi label "estimasi" di UI. Hanya bila
   tidak ada harga live sama sekali deret contoh dari harga contoh
   dipakai, SELALU berlabel offline di UI. Grafik yang bukan live
   dicoba ulang tiap 60 detik (bukan 10 menit) supaya data asli
   pulih sendiri begitu rate limit reda. */
var priceHistory = {};

function chartUrlFor(assetId) {
  return "https://api.coingecko.com/api/v3/coins/" + assetId +
    "/market_chart?vs_currency=idr&days=1";
}

/* Random deterministik (mulberry32) agar deret contoh stabil
   selama satu kali muat halaman. */
function seededRandom(seed) {
  var a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    var t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* Deret contoh 24 jam: random walk dari harga 24 jam lalu
   (dihitung dari harga jangkar + perubahan 24 jam) menuju harga
   jangkar saat ini. Jangkar (anchor) BUKAN harga pasar — hanya
   pengisi grafik saat data 24 jam tidak tersedia. Bila anchor
   diberikan (harga live / harga live terakhir), deret berakhir
   tepat di harga itu sehingga garis mark tidak terpisah jauh
   dari grafik; bila tidak ada anchor, dipakai harga contoh dan
   grafik selalu berlabel offline. */
function syntheticSeries(symbol, anchor) {
  var s = anchor || SAMPLE_PRICES[symbol];
  if (!s) return [];
  var now = Date.now();
  var start = s.idr / (1 + s.change / 100);
  var n = 97; /* tiap 15 menit selama 24 jam */
  var rnd = seededRandom(symbol.charCodeAt(0) * 7919 + symbol.charCodeAt(1) * 104729);
  var pts = [];
  var drift = (s.idr - start) / (n - 1);
  var vol = Math.abs(s.idr) * 0.004;
  var v = start;
  for (var i = 0; i < n; i++) {
    var target = start + drift * i;
    v += (target - v) * 0.25 + (rnd() - 0.5) * vol;
    pts.push({ t: now - (n - 1 - i) * 15 * 60 * 1000, v: Math.max(v, s.idr * 0.5) });
  }
  pts[n - 1].v = s.idr;
  return pts;
}

/* Ambil grafik 24 jam untuk satu koin. Di-cache per koin di memori
   (tidak di-fetch ulang bila datanya masih segar < 10 menit). */
async function fetchPriceChart(symbol) {
  var a = assetOf(symbol);
  if (!a) return;
  var h = priceHistory[symbol];
  if (h && h.loading) return;
  /* Grafik live segar 10 menit; grafik cadangan (bukan live) hanya
     60 detik — supaya dicoba ulang begitu rate limit reda. */
  var freshMs = (h && h.live) ? 10 * 60 * 1000 : 60 * 1000;
  if (h && h.fetchedAt && Date.now() - h.fetchedAt < freshMs && h.points.length > 10) {
    drawPriceChart();
    return;
  }
  if (!h) {
    h = { points: [], live: false, estimated: false, loading: false, fetchedAt: null };
    priceHistory[symbol] = h;
  }
  h.loading = true;
  drawPriceChart();
  var controller = new AbortController();
  var timer = setTimeout(function () { controller.abort(); }, 10000);
  try {
    var res = await fetch(chartUrlFor(a.id), { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error("HTTP " + res.status);
    var data = await res.json();
    var pts = (data.prices || []).filter(function (p) {
      return Array.isArray(p) && isFinite(p[0]) && isFinite(p[1]) && p[1] > 0;
    }).map(function (p) { return { t: p[0], v: p[1] }; });
    if (pts.length < 2) throw new Error("Data grafik kosong");
    h.points = pts;
    h.live = true;
    h.fetchedAt = Date.now();
  } catch (e) {
    clearTimeout(timer);
    /* market_chart gagal — bila sudah ada deret LIVE 24 jam (>10
       titik), PERTAHANKAN deret itu: refetch berkala yang kena 429 /
       timeout tidak boleh mengganti data asli CoinGecko dengan deret
       sintetis. appendPricePoint() tetap menempel harga live di ujung,
       dan fetch dicoba lagi setelah jendela 10 menit (fetchedAt =
       sekarang, h.live tetap true). Deret sintetis hanya bila belum
       ada deret live sama sekali. */
    if (h.live && h.points.length > 10) {
      h.estimated = false;
      h.fetchedAt = Date.now();
    } else {
      /* market_chart gagal — JANGAN jangkar deret pada harga contoh
         bila harga live tersedia: pakai harga live saat ini, atau
         harga live terakhir yang tersimpan. Hanya bila keduanya tidak
         ada, jatuh ke harga contoh (deret offline). */
      var anchor = null;
      if (pricesLive && prices[symbol]) anchor = prices[symbol];
      else if (lastLivePrices[symbol]) anchor = lastLivePrices[symbol];
      h.points = syntheticSeries(symbol, anchor);
      h.live = false;
      h.estimated = !!anchor;
      /* Tanpa jangkar (belum ada harga live sama sekali — misal
         market_chart gagal sebelum fetch harga pertama selesai),
         jangan kunci deret contoh selama 60 detik: biarkan
         applyPrices mencoba lagi begitu harga live tiba. */
      h.fetchedAt = anchor ? Date.now() : null;
    }
  }
  h.loading = false;
  drawPriceChart();
}

/* Tambahkan harga live terbaru ke grafik setiap kali harga
   diperbarui (poll 30 detik). Hanya saat harga live — saat
   offline deret contoh tetap apa adanya. */
function appendPricePoint() {
  if (!pricesLive) return;
  var h = priceHistory[selectedSymbol];
  if (!h || !h.points.length) return;
  var p = currentPrice();
  if (p == null) return;
  var last = h.points[h.points.length - 1];
  if (Date.now() - last.t < 20000 && Math.abs(last.v - p) < p * 0.0001) return;
  h.points.push({ t: Date.now(), v: p });
  if (h.points.length > 400) h.points = h.points.slice(-400);
}

function drawPriceChart() {
  var canvas = $("priceChart");
  var note = $("priceChartNote");
  var symEl = $("priceChartSymbol");
  if (!canvas) return;
  var a = assetOf(selectedSymbol);
  if (symEl) symEl.textContent = selectedSymbol;
  var h = priceHistory[selectedSymbol];
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var w = canvas.clientWidth || 800;
  var hh = canvas.clientHeight || 200;
  canvas.width = w * dpr;
  canvas.height = hh * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, hh);

  /* Garis horizontal: entry + likuidasi tiap posisi terbuka koin
     ini, plus harga mark saat ini. Harga mark JANGAN dari
     currentPrice() mentah — saat offline itu harga contoh (BTC
     Rp1,5 Miliar) sehingga garis Mark melonjak ke harga contoh dan
     merusak skala sumbu grafik. Pakai pnlMark(): harga live saat
     live, harga live terakhir (beku) saat offline, null bila belum
     pernah ada harga live (garis tidak digambar). */
  var markInfo = pnlMark(selectedSymbol);
  var mark = markInfo ? markInfo.price : null;
  var openPositions = state
    ? state.futures.filter(function (pos) { return pos.symbol === selectedSymbol; })
    : [];
  var lines = [];
  openPositions.forEach(function (pos) {
    var liq = futLiqPrice(pos.entry, pos.direction, pos.leverage);
    lines.push({ type: "entry", price: pos.entry,
      label: "Entry " + pos.direction.toUpperCase() + " " + pos.leverage + "x " + fmtIDR(pos.entry),
      color: pos.direction === "long" ? "#0ecb81" : "#f6465d", dashed: false });
    lines.push({ type: "liq", price: liq,
      label: "Likuidasi " + fmtIDR(liq),
      color: "#f6465d", dashed: true });
  });
  /* Garis mark tidak digambar bila berimpit dengan garis entry
     (harga mark = harga entry saat posisi baru dibuka) agar label
     tidak saling menumpuk. */
  var hasEntryAtMark = mark != null && openPositions.some(function (pos) {
    return Math.abs(pos.entry - mark) < mark * 0.0001;
  });
  if (mark != null && !hasEntryAtMark) {
    lines.push({ type: "mark", price: mark,
      label: "Mark " + fmtIDR(mark) +
        (markInfo && markInfo.frozen ? " (harga live terakhir)" : ""),
      color: "#eaecef", dashed: true });
  }

  /* Hook untuk pengujian otomatis (bukan bagian UI). */
  window.__priceChart = {
    symbol: selectedSymbol,
    points: h ? h.points.length : 0,
    live: !!(h && h.live),
    estimated: !!(h && h.estimated),
    loading: !!(h && h.loading),
    lines: lines.map(function (l) { return { type: l.type, price: l.price }; })
  };

  /* Saat memuat ulang (fetch berkala tiap 10 menit) grafik lama
     TETAP ditampilkan — hanya bila belum ada titik sama sekali
     tampil "Memuat grafik…". Tanpa ini tiap fetch ulang berkala
     mengosongkan kanvas sejenak (kedip) walau datanya sudah ada. */
  if (!h || (h.loading && !h.points.length)) {
    if (note) note.textContent = "Memuat grafik harga " + selectedSymbol + "…";
    ctx.fillStyle = "#848e9c";
    ctx.font = "13px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Memuat grafik…", w / 2, hh / 2);
    return;
  }
  var pts = h.points;
  if (note) {
    note.textContent = h.live
      ? "Grafik harga " + (a ? a.name : selectedSymbol) + " 24 jam terakhir dari CoinGecko — diperbarui tiap 30 detik."
      : h.estimated
        ? "Grafik estimasi — data 24 jam tidak tersedia, dijangkar pada harga live" +
          (pricesLive ? " saat ini." : " terakhir.")
        : "Grafik contoh (offline) — harga bukan harga pasar sebenarnya.";
  }
  if (!pts.length) {
    ctx.fillStyle = "#848e9c";
    ctx.font = "13px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Belum ada data grafik.", w / 2, hh / 2);
    return;
  }

  /* Skala sumbu HANYA dari deret harga 24 jam (+ mark = harga saat
     ini). Garis entry/likuidasi JANGAN ikut: liq Long 1x = Rp0 dan
     liq Short 1x = 2x entry meregangkan sumbu sampai Rp-0,17 M ..
     Rp2,58 M sehingga garis harga 24 jam (rentang ~Rp1,10-1,12 M)
     terjepit jadi pita datar di tepi grafik. Posisi lama yang
     entry-nya jauh di luar rentang 24 jam pun tidak boleh meregangkan
     sumbu. Garis di luar rentang dipotong di tepi plot (lihat bawah). */
  var values = pts.map(function (p) { return p.v; });
  if (mark != null) values.push(mark);
  var min = Math.min.apply(null, values);
  var max = Math.max.apply(null, values);
  if (max === min) { max = min + 1; }
  var pad = Math.max((max - min) * 0.15, Math.abs(max) * 0.01, 1);
  min -= pad; max += pad;

  var left = 62, right = w - 10, top = 14, bottom = hh - 26;
  function x(t) {
    var t0 = pts[0].t, t1 = pts[pts.length - 1].t;
    if (t1 === t0) return (left + right) / 2;
    return left + ((t - t0) / (t1 - t0)) * (right - left);
  }
  function y(v) { return bottom - ((v - min) / (max - min)) * (bottom - top); }

  /* Grid horizontal + label sumbu — satu satuan untuk seluruh
     sumbu (dipilih dari nilai maks), bukan per label. */
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.textAlign = "left";
  var yUnit = axisUnit(max);
  var yLabels = [];
  for (var g = 0; g <= 4; g++) {
    var gv = min + (max - min) * (g / 4);
    var gy = y(gv);
    ctx.strokeStyle = "rgba(132, 142, 156, 0.13)";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left, gy); ctx.lineTo(right, gy); ctx.stroke();
    ctx.fillStyle = "#5e6673";
    var yLab = fmtCompactAxis(gv, yUnit);
    yLabels.push(yLab);
    ctx.fillText(yLab, 4, gy + 3);
  }
  /* Hook label sumbu Y untuk pengujian otomatis (bukan bagian UI). */
  if (window.__priceChart) {
    window.__priceChart.yLabels = yLabels;
    window.__priceChart.yMin = min;
    window.__priceChart.yMax = max;
  }

  /* Garis harga + isi gradien — digambar SEBELUM garis entry /
     likuidasi / mark + labelnya, supaya garis harga tidak menimpa
     pill label (bug: label "Entry LONG 10x Rp1.080.542.121"
     tertutup sebagian garis harga oranye). */
  var drawSeq = 0, priceSeq = 0, labelSeq = 0;
  var up = pts[pts.length - 1].v >= pts[0].v;
  var color = (a && a.color) || (up ? "#0ecb81" : "#f6465d");
  ctx.beginPath();
  ctx.moveTo(x(pts[0].t), y(pts[0].v));
  for (var i = 1; i < pts.length; i++) {
    var mx = (x(pts[i - 1].t) + x(pts[i].t)) / 2;
    var my = (y(pts[i - 1].v) + y(pts[i].v)) / 2;
    ctx.quadraticCurveTo(x(pts[i - 1].t), y(pts[i - 1].v), mx, my);
  }
  ctx.lineTo(x(pts[pts.length - 1].t), y(pts[pts.length - 1].v));
  priceSeq = ++drawSeq; /* urutan gambar: garis harga dulu */
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.stroke();
  ctx.lineTo(x(pts[pts.length - 1].t), bottom);
  ctx.lineTo(x(pts[0].t), bottom);
  ctx.closePath();
  var grad = ctx.createLinearGradient(0, top, 0, bottom);
  grad.addColorStop(0, up ? "rgba(14,203,129,0.25)" : "rgba(246,70,93,0.25)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = grad;
  ctx.fill();

  /* Garis entry / likuidasi / mark + labelnya (label digeser bila
     dua garis berdekatan agar tidak saling menumpuk). Garis + label
     ini digambar SETELAH garis harga supaya garis harga tidak
     menimpa pill label. */
  var usedLabelY = [];
  lines.forEach(function (l) {
    var ly = y(l.price);
    /* Garis di luar rentang sumbu dipotong di tepi plot, bukan
       digambar di luar kanvas — label tetap menampilkan harga
       sebenarnya, jadi info entry/likuidasi tidak hilang. */
    if (ly < top) ly = top;
    if (ly > bottom) ly = bottom;
    ctx.strokeStyle = l.color;
    ctx.globalAlpha = l.type === "mark" ? 0.55 : 0.85;
    ctx.setLineDash(l.dashed ? [5, 4] : []);
    ctx.lineWidth = 1.25;
    ctx.beginPath(); ctx.moveTo(left, ly); ctx.lineTo(right, ly); ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    var labelY = Math.max(2, ly - 18);
    var guard = 0, down = false;
    while (usedLabelY.some(function (uy) { return Math.abs(uy - labelY) < 15; }) && guard < 16) {
      if (!down && labelY > 2) {
        /* Geser ke atas seperti biasa; bila sudah mentok di tepi atas
           (labelY = 2, mis. dua garis likuidasi Short 1x yang sama-sama
           terpotong di tepi) dan masih bertabrakan, arah dibalik ke
           bawah supaya label tidak menumpuk di satu titik. */
        labelY = Math.max(2, labelY - 16);
        if (labelY <= 2) down = true;
      } else {
        /* Tepi atas penuh: geser ke bawah, tetap di atas label sumbu X
           (batas bawah = bottom - 15). Sekali ke bawah, tetap ke bawah
           (tanpa ini label berosilasi 2 <-> 18 tanpa pernah bebas). */
        labelY = Math.min(bottom - 15, labelY + 16);
      }
      guard++;
    }
    usedLabelY.push(labelY);
    ctx.font = "10px Inter, sans-serif";
    var tw = ctx.measureText(l.label).width;
    ctx.fillStyle = "rgba(11, 14, 17, 0.78)";
    roundRectPath(ctx, left + 4, labelY, tw + 12, 15, 7);
    ctx.fill();
    ctx.fillStyle = l.color;
    if (!labelSeq) labelSeq = ++drawSeq; /* urutan gambar: label garis */
    ctx.fillText(l.label, left + 10, labelY + 11);
  });

  /* Hook urutan gambar untuk pengujian otomatis: garis harga harus
     digambar SEBELUM label garis entry/likuidasi/mark. */
  if (window.__priceChart) {
    window.__priceChart.order = { price: priceSeq, firstLabel: labelSeq };
  }

  /* Label waktu: sertakan tanggal di kedua ujung bila deret
     melewati pergantian hari (deret 24 jam selalu begitu — titik
     awal kemarin, titik akhir hari ini; sebelumnya label kanan
     hanya jam, "19.33", tanpa menyebut hari apa). */
  var xDate = spansDays(pts[0].t, pts[pts.length - 1].t);
  var xLabels = [fmtAxisTime(pts[0].t, xDate), fmtAxisTime(pts[pts.length - 1].t, xDate)];
  ctx.fillStyle = "#5e6673";
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.textAlign = "left";
  ctx.fillText(xLabels[0], left, hh - 8);
  ctx.textAlign = "right";
  ctx.fillText(xLabels[1], right, hh - 8);
  /* Hook label waktu sumbu X untuk pengujian otomatis (bukan bagian UI). */
  if (window.__priceChart) window.__priceChart.xLabels = xLabels;
  var lastV = pts[pts.length - 1].v;
  var lx = x(pts[pts.length - 1].t), ly2 = y(lastV);
  ctx.beginPath(); ctx.arc(lx, ly2, 5.5, 0, Math.PI * 2);
  ctx.fillStyle = "#eaecef"; ctx.fill();
  ctx.beginPath(); ctx.arc(lx, ly2, 3.5, 0, Math.PI * 2);
  ctx.fillStyle = color; ctx.fill();
  ctx.fillStyle = "#eaecef";
  ctx.font = "bold 12px 'IBM Plex Mono', monospace";
  ctx.textAlign = "right";
  /* Label harga terakhir: coba beberapa posisi (di atas / di bawah
     titik) dan pakai yang pertama tidak bertabrakan dengan label
     garis entry/likuidasi. */
  var lastLabelY = Math.max(14, ly2 - 10);
  var lastLabelCandidates = [ly2 - 10, ly2 + 24, ly2 - 26, ly2 + 40, ly2 - 42];
  for (var ci = 0; ci < lastLabelCandidates.length; ci++) {
    var cand = lastLabelCandidates[ci];
    if (cand < 12 || cand > hh - 8) continue;
    var clash = usedLabelY.some(function (uy) {
      return cand - 11 < uy + 18 && cand + 4 > uy - 3;
    });
    lastLabelY = cand;
    if (!clash) break;
  }
  ctx.fillText(fmtIDR(lastV), right - 2, lastLabelY);
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
  drawPriceChart();
}

function renderMarket() {
  var list = $("marketList");
  /* Tangkap baris pasar yang sedang difokuskan (lihat focusedKey):
     daftar dibangun ulang di bawah, fokus harus dikembalikan ke
     baris koin yang sama. */
  var focusedSym = focusedKey(list, ".market-row", "data-symbol");
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
    row.setAttribute("data-symbol", a.symbol);
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
      /* Ganti koin = konteks trade BARU (lihat clearTradeContext):
         konfirmasi pending, input jumlah/margin, dan error milik koin
         lama tidak boleh terbawa. Pernah: jual 0,0005 BTC lalu ketuk
         baris ETH — input "0.0005" terbawa dan langsung muncul error
         menyesatkan "Koin tidak cukup. Kamu punya 0 ETH.", padahal
         user baru ganti koin; _pendingTrade/_pendingFut koin lama
         juga tetap set (kotak tersembunyi tapi pending-nya hidup).
         Sama polanya dengan ganti profil dan ganti tab Beli/Jual. */
      clearTradeContext();
      renderAll();
      fetchPriceChart(selectedSymbol);
      /* JANGAN focus() ke input jumlah di sini: di HP (390px) panel
         Spot ada jauh di bawah daftar pasar, sehingga focus()
         menarik halaman dari scrollY 0 -> ~1414 dan membuka
         keyboard — user yang cuma mau ganti koin tiba-tiba
         "dilempar" ke panel trade. Ganti koin cukup mengganti
         koinnya; user mengetuk input sendiri bila mau mengetik. */
    });
    list.appendChild(row);
  });
  /* Kembalikan fokus ke baris koin yang sama (bila tadi difokuskan). */
  refocusKey(list, ".market-row", "data-symbol", focusedSym);
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
  /* Saat offline, total + PnL dihitung dari harga live terakhir yang
     dibekukan (bukan harga contoh) — beri tahu user supaya tidak
     dikira harga live. */
  var hasHoldings = Object.keys(state.holdings).some(function (s) {
    return state.holdings[s].amount > 0;
  });
  var frozenNote = (!pricesLive && (hasHoldings || state.futures.length))
    ? " Nilai dihitung dari harga live terakhir (beku), bukan harga contoh."
    : "";
  if (state.futures.length) {
    fs.textContent = "Termasuk margin futures " + fmtIDR(futuresMarginTotal()) +
      " + PnL mengambang " + fmtSignedIDR(futuresFloatPnl()) + "." + frozenNote;
    fs.hidden = false;
  } else if (frozenNote) {
    fs.textContent = "Nilai portofolio dihitung dari harga live terakhir (beku), bukan harga contoh.";
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
    var m = spotMark(sym);
    var cur = m ? h.amount * m.price : null;
    var cost = h.amount * h.avgPrice;
    var pnl = cur === null ? null : cur - cost;
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
        '<span class="value">' + (cur === null ? "—" : fmtIDR(cur)) + "</span>" +
        '<span class="change ' + (pnl === null ? "" : pnl >= 0 ? "up" : "down") + '">' +
          (pnl === null ? "—" : fmtSignedIDR(pnl)) + "</span>" +
        (m && m.frozen ? '<span class="pnl-frozen">(harga live terakhir)</span>' : "") +
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
  $("tradeIcon").textContent = a ? a.icon : "?";
  $("tradeIcon").setAttribute("style", iconStyle(a));
  $("tradeName").textContent = a ? a.name : "—";
  $("tradeSymbol").textContent = selectedSymbol;
  /* Harga di panel JANGAN dari currentPrice() mentah — saat offline
     itu harga contoh (BTC Rp1,5 Miliar) sehingga panel menampilkan
     harga contoh sebagai "Harga saat ini", padahal holding di bawah
     memakai harga live terakhir yang dibekukan. Pakai spotMark():
     harga live saat live, harga live terakhir (beku) saat offline,
     "—" bila belum pernah ada harga live. */
  var sm = spotMark(selectedSymbol);
  $("tradePrice").textContent = sm
    ? fmtIDR(sm.price) + " / " + selectedSymbol + (sm.frozen ? " (harga live terakhir)" : "")
    : "—";

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
  var h = state ? state.holdings[sym] : null;
  return h ? h.amount : 0;
}

function showError(msg) {
  var el = $("tradeError");
  if (msg) { el.textContent = msg; el.hidden = false; }
  else { el.hidden = true; }
}

function hideConfirm() {
  /* Menutup kotak konfirmasi = MEMBATALKAN pending-nya. Pending
     milik konteks yang baru saja ditutup (ganti tab Beli/Jual,
     ketik ulang jumlah, tombol cepat) tidak boleh tetap hidup:
     pernah konfirmasi beli dibuka lalu ganti tab Jual — kotak
     tersembunyi tapi _pendingTrade tetap set, dan begitu juga di
     semua situs hideConfirm()/hideFutConfirm() lain. Hari ini
     pending basi tidak bisa dieksekusi lewat UI (kotak hanya
     dibuka ulang oleh tradeBtn/futBtn yang selalu menimpa pending
     baru), tapi invarian "kotak tersembunyi ⟺ tidak ada pending"
     harus benar di semua pemanggil. Aman bagi confirmYes dan
     invalidateStaleConfirms: keduanya menolkan pending sebelum /
     sesudah memanggil ini, dan executeTrade memakai argumen res,
     bukan window._pendingTrade. */
  window._pendingTrade = null;
  $("confirmBox").hidden = true;
  $("previewBox").hidden = true;
}

/* ---------------- Panel Futures ---------------- */

function renderFuturesPanel() {
  var a = assetOf(selectedSymbol);
  $("futIcon").textContent = a ? a.icon : "?";
  $("futIcon").setAttribute("style", iconStyle(a));
  $("futName").textContent = a ? a.name : "—";
  $("futSymbol").textContent = selectedSymbol;
  /* "Harga mark" di panel JANGAN dari currentPrice() mentah — saat
     offline itu harga contoh (BTC Rp1,5 Miliar) sehingga panel
     menampilkan mark contoh, padahal kartu posisi di seksi yang
     sama menampilkan mark beku Rp1,12 Miliar (harga live terakhir):
     dua angka bertentangan dalam satu kartu, dan "mark" adalah
     angka yang dipakai hitung PnL/likuidasi. Pakai pnlMark() —
     pola yang sama seperti garis Mark di grafik 24 jam. */
  var fm = pnlMark(selectedSymbol);
  $("futPrice").textContent = fm
    ? fmtIDR(fm.price) + " / " + selectedSymbol + (fm.frozen ? " (harga live terakhir)" : "")
    : "—";

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
  if (msg) {
    /* Guncang + gulir HANYA bila pesannya BARU (belum tampil).
       Tanpa ini, updateFutPreview() yang dipanggil tiap renderAll
       (refresh harga tiap 30 detik) dan tiap ketik di input margin
       mengulang shake + scrollIntoView untuk pesan yang SAMA
       sehingga halaman HP ketarik ke bawah tiap 30 detik walau user
       sedang membaca bagian lain (pernah: scrollY 0 -> 2004 oleh
       satu renderAll saat offline). Pesan yang sudah tampil cukup
       dipertahankan tanpa guncangan/scroll ulang. */
    var isNew = el.hidden || el.textContent !== msg;
    el.textContent = msg; el.hidden = false;
    if (isNew) {
      /* Guncang + gulir ke pesan agar di HP jelas terlihat bahwa
         tombol ditekan tapi ada yang kurang (bukan tombol mati). */
      el.classList.remove("shake");
      void el.offsetWidth;
      el.classList.add("shake");
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  } else { el.hidden = true; }
}

function hideFutConfirm() {
  /* Sama seperti hideConfirm: menutup kotak konfirmasi futures =
     membatalkan pending-nya (ganti arah Long/Short, ganti leverage
     via slider/chip, ketik ulang margin). Aman bagi futConfirmYes
     dan invalidateStaleConfirms (lihat hideConfirm). */
  window._pendingFut = null;
  $("futConfirmBox").hidden = true;
  $("futPreview").hidden = true;
}

function renderPositions() {
  var list = $("futPositions");
  /* Tangkap tombol Tutup yang sedang difokuskan (lihat focusedKey):
     daftar dibangun ulang di bawah, fokus harus dikembalikan ke
     tombol Tutup posisi yang sama. */
  var focusedPos = focusedKey(list, "button", "data-pos-id");
  list.innerHTML = "";
  if (!state.futures.length) {
    list.innerHTML = "<p class=\"empty-note\">Belum ada posisi futures.</p>";
    window.__futuresPnl = [];
    return;
  }
  /* Hook untuk pengujian otomatis (bukan bagian UI). */
  var hook = [];
  state.futures.forEach(function (pos) {
    var m = pnlMark(pos.symbol);
    var liq = futLiqPrice(pos.entry, pos.direction, pos.leverage);
    var pnlHtml, markHtml;
    if (m) {
      /* PnL live, dibatasi maksimal −margin (aturan yang sama
         seperti saat posisi ditutup). */
      var pnl = Math.max(futPnl(pos, m.price), -pos.margin);
      var roe = pos.margin ? pnl / pos.margin * 100 : 0;
      var cls = pnl >= 0 ? "up" : "down";
      pnlHtml =
        '<span class="pos-pnl ' + cls + '">PnL ' + fmtSignedIDR(pnl) +
        " (" + fmtPct(roe) + ")</span>" +
        (m.frozen ? '<span class="pnl-frozen">(harga live terakhir)</span>' : "");
      markHtml = fmtIDR(m.price) + (m.frozen ? " (harga live terakhir)" : "");
      hook.push({ id: pos.id, symbol: pos.symbol, direction: pos.direction,
        leverage: pos.leverage, margin: pos.margin, entry: pos.entry,
        mark: m.price, frozen: m.frozen, pnl: pnl, roe: roe });
    } else {
      /* Belum pernah ada harga live — PnL tidak dihitung sama sekali,
         jangan pakai harga contoh. */
      pnlHtml = '<span class="pos-pnl">PnL —</span>';
      markHtml = "—";
      hook.push({ id: pos.id, symbol: pos.symbol, direction: pos.direction,
        leverage: pos.leverage, margin: pos.margin, entry: pos.entry,
        mark: null, frozen: false, pnl: null, roe: null });
    }
    var row = document.createElement("div");
    row.className = "position-row";
    row.innerHTML =
      '<span class="position-info">' +
        '<span><span class="dir-badge ' +
          (pos.direction === "long" ? "dir-long" : "dir-short") + '">' +
          pos.direction.toUpperCase() + "</span>" +
          '<strong>' + pos.symbol + " " + pos.leverage + "x</strong></span>" +
        '<span class="position-detail">' +
          "entry " + fmtIDR(pos.entry) + " &middot; mark " + markHtml +
          " &middot; likuidasi " + fmtIDR(liq) + "<br>" +
          "margin " + fmtIDR(pos.margin) + " &middot; notional " + fmtIDR(futNotional(pos.margin, pos.leverage)) +
        "</span>" +
      "</span>" +
      '<span class="holding-value">' + pnlHtml + "</span>" +
      '<button type="button" class="btn btn-danger btn-small" data-pos-id="' + pos.id + '">Tutup</button>';
    row.querySelector("[data-pos-id]").addEventListener("click", function () {
      closeFutures(pos.id, "manual");
    });
    list.appendChild(row);
  });
  window.__futuresPnl = hook;
  /* Kembalikan fokus ke tombol Tutup posisi yang sama (bila tadi
     difokuskan dan posisinya masih ada). */
  refocusKey(list, "button", "data-pos-id", focusedPos);
}

/* ---------------- Profil (Guest) ---------------- */

function renderProfileUI() {
  var wrap = $("profileWrap");
  if (!state) { wrap.hidden = true; return; }
  wrap.hidden = false;
  $("profileAvatar").textContent = (state.name || "G").charAt(0).toUpperCase();
  $("profileName").textContent = state.name;
  var list = $("profileList");
  /* Tangkap item profil yang sedang difokuskan (lihat focusedKey):
     daftar dibangun ulang di bawah, fokus harus dikembalikan ke
     item profil yang sama. */
  var focusedProfile = focusedKey(list, ".profile-item", "data-profile-id");
  list.innerHTML = "";
  store.profiles.forEach(function (p) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "profile-item" + (p.id === store.activeProfileId ? " active" : "");
    btn.setAttribute("data-profile-id", p.id);
    /* Nama profil JANGAN pernah lewat innerHTML: nama diketik user dan
       bisa berisi markup ("<b>TEST</b>" pernah tampil tebal di menu,
       "<img src=x>" pernah jadi elemen <img> sungguhan). Bangun DOM
       dengan textContent supaya nama selalu tampil sebagai teks biasa. */
    var av = document.createElement("span");
    av.className = "profile-avatar";
    av.style.cssText = "width:26px;height:26px;font-size:0.8rem";
    av.textContent = (p.name || "G").charAt(0).toUpperCase();
    btn.appendChild(av);
    var nm = document.createElement("span");
    nm.textContent = p.name;
    btn.appendChild(nm);
    if (p.id === store.activeProfileId) {
      var chk = document.createElement("span");
      chk.className = "check";
      chk.textContent = "\u2713";
      btn.appendChild(chk);
    }
    btn.addEventListener("click", function () { switchProfile(p.id); });
    list.appendChild(btn);
  });
  /* Kembalikan fokus ke item profil yang sama (bila tadi difokuskan). */
  refocusKey(list, ".profile-item", "data-profile-id", focusedProfile);
  $("createProfileBtn").disabled = store.profiles.length >= MAX_PROFILES;
  $("profileNote").textContent = store.profiles.length >= MAX_PROFILES
    ? "Maksimal 5 profil tercapai. Data tiap profil tersimpan terpisah di perangkat ini."
    : "Maksimal 5 profil. Data tiap profil tersimpan terpisah di perangkat ini.";
}

/* ---------------- Trading Spot ---------------- */

/* Pratinjau hitungan dari input saat ini; mengembalikan objek
   { ok, amount, coins, total, msg } atau null bila input kosong. */
function computeTrade() {
  /* Belum masuk Guest (state null — layar sambutan masih tampil):
     panel trade di belakang overlay tetap bisa difokus lewat keyboard
     (Tab), dan tanpa guard ini updatePreview/computeTrade membaca
     state.cash -> TypeError di console tiap ketikan. Tolak dengan
     sopan; begitu Guest masuk, state ada dan trade jalan normal. */
  if (!state) {
    return { ok: false, msg: "Masuk sebagai Guest dulu untuk mulai trading." };
  }
  /* Input kosong tetap DIAM (null) — SEBELUM pemeriksaan harga /
     offline. Tanpa ini, panel yang baru dibuka (belum ada ketikan
     apa pun) sudah menampilkan error merah "Harga belum tersedia" /
     "Harga live tidak tersedia" begitu halaman dimuat atau saat
     offline, dan showFutError() menarik halaman ke bawah lewat
     scrollIntoView untuk pesan "baru" itu (pernah: halaman HP
     terbuka langsung di scrollY 2003 saat offline, tanpa user
     mengetik apa pun). Blokir offline tetap berlaku begitu user
     mengetik jumlah — pemeriksaan di bawah tidak berubah. */
  if ($("amountInput").value.trim() === "") return null;
  /* parseAmount, bukan parseFloat mentah — user mengetik format
     Indonesia ("1.000.000" / "0,00089286") seperti yang ditampilkan
     aplikasi; parseFloat membaca "1.000.000" jadi Rp1. */
  var raw = parseAmount($("amountInput").value);
  var price = currentPrice();
  if (!price) return { ok: false, msg: "Harga belum tersedia — tekan Refresh." };
  /* JANGAN PERNAH beli/jual spot di harga contoh offline: harga
     contoh jauh dari harga live (BTC Rp1,5 Miliar vs live ~Rp1,12
     Miliar) sehingga beli offline langsung rugi ~25% begitu harga
     live kembali — sama alasannya dengan blokir buka posisi
     futures saat offline. Spot hanya boleh saat harga live
     (CoinGecko/Binance). */
  if (!pricesLive) {
    return { ok: false, msg: "Harga live tidak tersedia — beli/jual spot hanya bisa saat harga live (bukan harga contoh). Tekan Refresh untuk mencoba lagi." };
  }
  /* Input tidak kosong tapi tidak bisa dibaca sebagai angka ("Rp" saja,
     "abc", "1.2.3", "0"): jangan diam — pratinjau hilang tanpa pesan
     membuat input terasa mati, dan tombol Beli/Jual malah bilang
     "Masukkan jumlah dulu." padahal user sudah mengetik sesuatu.
     Input kosong sudah dikembalikan null di atas (sebelum pemeriksaan
     harga/offline) sehingga tidak sampai ke sini. */
  if (!isFinite(raw) || raw <= 0) {
    return { ok: false, msg: tradeMode === "buy"
      ? "Jumlah tidak valid — contoh: Rp100.000."
      : "Jumlah tidak valid — contoh: 0,0005 BTC." };
  }

  if (tradeMode === "buy") {
    var coins = raw / price;
    if (raw > state.cash) {
      return { ok: false, msg: "Saldo kas tidak cukup. Kas tersedia: " + fmtIDR(state.cash) + "." };
    }
    return { ok: true, amount: raw, coins: coins, total: raw, price: price };
  } else {
    var owned = holdingsAmount(selectedSymbol);
    /* Toleransi pembulatan: jumlah koin dari tombol cepat 100%
       (toFixed(8)) atau yang diketik dari tampilan holding bisa
       membulat sedikit DI ATAS holding sebenarnya (mis. beli
       Rp1.000.000 @ Rp1.120.000.000 = 0,000892857142… BTC, tampil
       0,00089286 — selisih 2,9e-9) sehingga jual "Maks" ditolak
       "Koin tidak cukup" padahal angkanya sama. Bila selisihnya
       hanya pembulatan (<= 1e-8 koin + noise float), jepit ke
       holding yang dimiliki. HANYA bila memang punya koinnya:
       tanpa guard ini, jual debu (mis. 0,000000001 BTC) saat
       holding 0 dijepit jadi 0 koin lalu lolos sebagai trade valid
       ("Jual 0 BTC, terima Rp0") dan executeTrade melempar
       TypeError karena state.holdings[symbol] tidak ada — kotak
       konfirmasi macet terbuka tanpa pesan apa pun. */
    var eps = Math.max(1e-8, owned * 1e-9);
    if (owned > 0 && raw > owned && raw - owned <= eps) raw = owned;
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

/* Catat satu entri riwayat trade. Hanya 200 entri terakhir yang
   disimpan (MAX_TRADES) — tanpa batas, renderHistory() me-render
   semua baris di tiap renderAll() dan localStorage membengkak. */
function recordTrade(tr) {
  if (!state) return;
  state.trades.push(tr);
  if (state.trades.length > MAX_TRADES) {
    state.trades = state.trades.slice(-MAX_TRADES);
  }
}

function executeTrade(res) {
  /* Validasi ulang saat eksekusi: konfirmasi bisa dibuka lalu
     eksekusinya ditunda sementara user memakai kas di panel lain
     (mis. buka posisi futures setelah konfirmasi beli dibuka, atau
     sebaliknya) — tanpa ini kas bisa MINUS. Pernah: konfirmasi beli
     Rp4.950.000 + konfirmasi futures margin Rp100.000, futures
     dikonfirmasi dulu (kas Rp4.900.000), lalu beli dikonfirmasi →
     kas −Rp50.000. */
  if (tradeMode === "buy" && res.amount > state.cash) {
    hideConfirm();
    showError("Saldo kas tidak cukup. Kas tersedia: " + fmtIDR(state.cash) + ".");
    showToast("Saldo kas tidak cukup — trade dibatalkan.", "error");
    renderAll();
    return;
  }
  if (tradeMode === "sell") {
    var ownedNow = holdingsAmount(selectedSymbol);
    var epsNow = Math.max(1e-8, ownedNow * 1e-9);
    if (res.coins > ownedNow && res.coins - ownedNow <= epsNow) {
      res.coins = ownedNow;
      res.amount = ownedNow;
      res.total = ownedNow * res.price;
    } else if (res.coins > ownedNow) {
      hideConfirm();
      showError("Koin tidak cukup. Kamu punya " + fmtCoin(ownedNow) + " " + selectedSymbol + ".");
      showToast("Koin tidak cukup — trade dibatalkan.", "error");
      renderAll();
      return;
    }
    /* Jangan pernah eksekusi jual 0 koin / tanpa holding (lapis
       kedua dari guard di computeTrade): tanpa ini pending berisi
       coins 0 lolos ke bawah dan `hs.amount` melempar TypeError
       karena state.holdings[symbol] tidak ada. */
    if (res.coins <= 0 || !state.holdings[selectedSymbol]) {
      hideConfirm();
      showError("Kamu belum punya " + selectedSymbol + " untuk dijual.");
      showToast("Kamu belum punya " + selectedSymbol + " untuk dijual.", "error");
      renderAll();
      return;
    }
  }
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
    recordTrade({
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
    recordTrade({
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
  /* Sama seperti computeTrade: belum masuk Guest (state null) -> tolak
     dengan sopan, jangan baca state.cash dan melempar TypeError. */
  if (!state) {
    return { ok: false, msg: "Masuk sebagai Guest dulu untuk membuka posisi." };
  }
  /* Margin kosong tetap DIAM (null) — SEBELUM pemeriksaan harga /
     offline, alasan yang sama seperti computeTrade: tanpa ini panel
     futures menampilkan error merah + menarik halaman ke bawah
     (scrollIntoView) begitu halaman dimuat atau saat offline,
     padahal user belum mengetik apa pun. Blokir offline tetap
     berlaku begitu user mengetik margin. */
  if ($("futMarginInput").value.trim() === "") return null;
  /* parseAmount, bukan parseFloat mentah — "100.000" harus dibaca
     Rp100.000, bukan Rp100 (lihat parseAmount). */
  var margin = parseAmount($("futMarginInput").value);
  var entry = currentPrice();
  if (!entry) return { ok: false, msg: "Harga belum tersedia — tekan Refresh." };
  /* JANGAN PERNAH buka posisi di harga contoh offline: harga contoh
     jauh dari harga live dan pernah membuat posisi terlikuidasi.
     Posisi hanya boleh dibuka saat harga live (CoinGecko/Binance). */
  if (!pricesLive) {
    return { ok: false, msg: "Harga live tidak tersedia — posisi futures hanya bisa dibuka saat harga live (bukan harga contoh). Tekan Refresh untuk mencoba lagi." };
  }
  /* Sama seperti computeTrade: input margin tidak kosong tapi tidak
     bisa dibaca sebagai angka ("Rp" saja, "abc") jangan diam — beri
     tahu user. Margin kosong sudah dikembalikan null di atas
     (sebelum pemeriksaan harga/offline) sehingga tidak sampai ke sini. */
  if (!isFinite(margin) || margin <= 0) {
    return { ok: false, msg: "Margin tidak valid — contoh: Rp100.000." };
  }
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
  /* Validasi ulang saat eksekusi: margin bisa melebihi kas bila kas
     dipakai di panel lain setelah konfirmasi dibuka (mis. beli spot
     dulu) — tanpa ini kas bisa MINUS (lihat executeTrade). */
  if (res.margin > state.cash) {
    hideFutConfirm();
    showFutError("Margin melebihi saldo kas. Kas tersedia: " + fmtIDR(state.cash) + ".");
    showToast("Margin melebihi saldo kas — posisi dibatalkan.", "error");
    renderAll();
    return;
  }
  var now = Date.now();
  var id = "f" + now + Math.floor(Math.random() * 1000);
  state.cash -= res.margin;
  state.futures.push({
    id: id, symbol: selectedSymbol, direction: futDirection,
    leverage: res.leverage, margin: res.margin, entry: res.entry,
    openedAt: now
  });
  recordTrade({
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
  var m = pnlMark(pos.symbol);
  var mark = m ? m.price : pos.entry;
  var pnl = futPnl(pos, mark);
  var pnlCapped = Math.max(pnl, -pos.margin);
  var returned = reason === "liquidated" ? 0 : pos.margin + pnlCapped;
  state.cash += returned;
  state.futures.splice(idx, 1);
  recordTrade({
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
  /* Belum masuk Guest (state null): tidak ada yang bisa direset. */
  if (!state) return;
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

/* Ganti/buat profil = konteks trade BARU: input jumlah + margin, error,
   dan konfirmasi pending milik profil lama tidak boleh terbawa.
   Pernah: ketik jual 0,0005 BTC di profil A (punya BTC) lalu buat
   profil B — input "0.0005" terbawa dan renderAll() di B langsung
   menampilkan error "Koin tidak cukup. Kamu punya 0 BTC." di profil
   baru yang belum melakukan apa-apa; _pendingTrade dari A juga tetap
   set (kotak konfirmasi tersembunyi tapi pending-nya hidup). Sama
   alasannya dengan disarmReset() dan pengosongan input saat ganti
   tab Beli/Jual: status panel trade milik konteks lama.
   Dipakai juga saat ganti koin lewat baris pasar — koin baru =
   konteks baru dengan alasan yang sama. */
function clearTradeContext() {
  window._pendingTrade = null;
  window._pendingFut = null;
  $("amountInput").value = "";
  $("futMarginInput").value = "";
  showError(null);
  showFutError(null);
  hideConfirm();
  hideFutConfirm();
}

function switchProfile(id) {
  if (id === store.activeProfileId) { $("profileMenu").hidden = true; return; }
  var p = null;
  store.profiles.forEach(function (x) { if (x.id === id) p = x; });
  if (!p) return;
  /* Ganti profil MEMBATALKAN status armed tombol Reset: status armed
     itu milik profil yang sedang aktif — tanpa ini, klik-1 Reset di
     profil A lalu pindah ke profil B membuat SATU klik Reset di B
     langsung menghapus data B (langkah konfirmasi "terpakai" di
     profil lain). Pernah: arm di A, pindah ke B, satu klik Reset →
     kas B kembali Rp5.000.000 dan riwayat B hilang. */
  disarmReset();
  clearTradeContext();
  store.activeProfileId = p.id;
  state = p;
  saveStore();
  /* Profil yang jadi aktif langsung punya titik grafik portofolio
     bila harga live sudah ada (lihat createGuestProfile): tanpa ini
     profil ber-riwayat kosong — mis. dibuat saat offline — tetap
     "Belum ada data" sampai refresh harga berikutnya. Guard
     !pricesLive di snapshotPortfolio() mencegah snapshot dari harga
     contoh; bila riwayat sudah ada dan nilainya belum berubah dalam
     60 detik, pemanggilan ini no-op. */
  snapshotPortfolio();
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
  /* Sama seperti switchProfile: profil baru = konteks baru, status
     armed tombol Reset dari profil lama tidak boleh terbawa. */
  disarmReset();
  /* Dan konteks trade-nya juga baru (lihat clearTradeContext):
     input + error + pending milik profil lama tidak boleh terbawa. */
  clearTradeContext();
  var p = createProfile(name);
  store.profiles.push(p);
  store.activeProfileId = p.id;
  state = p;
  saveStore();
  /* Profil baru langsung punya titik grafik portofolio bila harga
     live sudah dimuat: fetch harga di boot jalan sebelum state ada
     (layar sambutan), jadi snapshotPortfolio() di applyPrices tidak
     merekam apa-apa dan grafik menampilkan "Belum ada data" sampai
     refresh harga berikutnya (30 detik) atau tombol Refresh. Guard
     !pricesLive di snapshotPortfolio() mencegah snapshot dari harga
     contoh offline; bila fetch masih berjalan, applyPrices yang
     menyusul tetap snapshot karena state kini sudah ada. */
  snapshotPortfolio();
  return p;
}

/* ---------------- Event wiring ---------------- */

/* Ganti mode Beli/Jual: satuan input BERUBAH (Rupiah <-> koin), jadi
   angka lama harus dibersihkan. Pernah: ketik Rp1.000.000 di mode Beli,
   lalu ketuk tab Jual — input tetap "1000000" tapi kini dibaca sebagai
   1.000.000 BTC sehingga muncul error menyesatkan "Koin tidak cukup.
   Kamu punya 0 BTC." (dan sebaliknya: 0,0005 BTC di mode Jual dibaca
   sebagai Rp0,0005 di mode Beli). */
$("tabBuy").addEventListener("click", function () {
  tradeMode = "buy"; hideConfirm();
  $("amountInput").value = "";
  renderTradePanel();
});
$("tabSell").addEventListener("click", function () {
  tradeMode = "sell"; hideConfirm();
  $("amountInput").value = "";
  renderTradePanel();
});
$("amountInput").addEventListener("input", function () {
  hideConfirm(); updatePreview();
});
/* Enter di input jumlah = klik tombol Beli/Jual (alur keyboard yang
   paling wajar — sama seperti Enter di input nama profil). Pernah:
   ketik jumlah lalu tekan Enter tidak terjadi apa-apa, user harus
   menggerakkan mouse ke tombol. Handler klik yang sama dipakai
   ulang, jadi input kosong tetap menampilkan "Masukkan jumlah
   dulu." seperti biasa. */
$("amountInput").addEventListener("keydown", function (e) {
  if (e.key === "Enter") $("tradeBtn").click();
});

$("quickRow").addEventListener("click", function (e) {
  var btn = e.target.closest("[data-pct]");
  if (!btn) return;
  /* Belum masuk Guest (state null): tombol cepat membaca state.cash
     -> TypeError. Sama alasannya dengan guard di computeTrade. */
  if (!state) return;
  var pct = parseFloat(btn.getAttribute("data-pct")) / 100;
  var price = currentPrice();
  if (!price) {
    /* Harga belum tersedia (mis. tombol ditekan sesaat setelah halaman
       dimuat): jangan diam — beri tahu seperti computeTrade. */
    showError("Harga belum tersedia — tekan Refresh.");
    showToast("Harga belum tersedia — tekan Refresh.", "error");
    return;
  }
  if (tradeMode === "buy") {
    var rupiah = Math.floor(state.cash * pct);
    /* Kas habis (atau terlalu kecil sehingga bagiannya jadi Rp0):
       tombol cepat sebelumnya diam-diam mengisi "0" tanpa pratinjau
       dan tanpa pesan apa pun, sehingga tombol terasa mati. Beri tahu
       user kenapa tidak ada yang bisa dibeli (umpan balik ganda:
       teks merah + toast, pola yang sama seperti tombol Buka Long
       dengan margin kosong). */
    if (rupiah <= 0) {
      $("amountInput").value = "";
      showError("Jumlah terlalu kecil — kas tersedia: " + fmtIDR(state.cash) + ".");
      showToast("Jumlah terlalu kecil — kas tersedia: " + fmtIDR(state.cash) + ".", "error");
      hideConfirm();
      return;
    }
    $("amountInput").value = rupiah;
  } else {
    var coins = holdingsAmount(selectedSymbol) * pct;
    /* Belum punya koinnya: tombol cepat sebelumnya mengisi "" tanpa
       pratinjau dan tanpa pesan apa pun, sehingga tombol terasa mati.
       Beri tahu user kenapa tidak ada yang bisa dijual. */
    if (!(coins > 0) || !isFinite(coins)) {
      $("amountInput").value = "";
      showError("Kamu belum punya " + selectedSymbol + " untuk dijual.");
      showToast("Kamu belum punya " + selectedSymbol + " untuk dijual.", "error");
      hideConfirm();
      return;
    }
    /* JANGAN Number(coins.toFixed(8)): holding mikro (< 1 satoshi)
       dibulatkan jadi 0 sehingga tombol 25%/50% mengisi "0" dan
       tidak terjadi apa-apa; untuk 75%/100% tampil "1e-8" (notasi
       ilmiah). fmtInputCoins memakai desimal secukupnya. */
    $("amountInput").value = fmtInputCoins(coins);
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
  /* Simpan simbolnya — invalidateStaleConfirms membandingkan harga
     pending dengan harga koin yang sama saat refresh. */
  window._pendingTrade.symbol = selectedSymbol;
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
/* "change" sebagai cadangan: sebagian browser HP hanya menembakkan
   event ini saat jempol slider dilepas. setLeverage idempotent. */
$("futLeverage").addEventListener("change", function () {
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
/* Enter di input margin = klik tombol Buka Long/Short (alur keyboard
   yang sama seperti input jumlah spot di atas). Pernah: ketik margin
   lalu tekan Enter tidak terjadi apa-apa. Margin kosong tetap
   menampilkan "Masukkan margin dulu." seperti biasa. */
$("futMarginInput").addEventListener("keydown", function (e) {
  if (e.key === "Enter") $("futBtn").click();
});

$("futBtn").addEventListener("click", function () {
  var res = computeFutures();
  if (!res) {
    /* Margin kosong: beri umpan balik ganda (teks merah + toast)
       agar tombol tidak terasa "mati" saat ditekan. */
    showFutError("Masukkan margin dulu — contoh: Rp100.000.");
    showToast("Masukkan margin dulu — contoh: Rp100.000.", "error");
    return;
  }
  if (!res.ok) { showFutError(res.msg); showToast(res.msg, "error"); return; }
  showFutError(null);
  var dirTxt = futDirection === "long" ? "Long" : "Short";
  $("futConfirmText").innerHTML =
    "Buka posisi <strong>" + dirTxt + " " + selectedSymbol + " " + res.leverage + "x</strong> " +
    "dengan margin <strong>" + fmtIDR(res.margin) + "</strong>?<br>" +
    "Entry " + fmtIDR(res.entry) + " &middot; notional " + fmtIDR(res.notional) +
    " &middot; likuidasi <strong>" + fmtIDR(res.liq) + "</strong>.";
  $("futConfirmBox").hidden = false;
  window._pendingFut = res;
  /* Simpan simbolnya — invalidateStaleConfirms membandingkan entry
     pending dengan harga koin yang sama saat refresh. */
  window._pendingFut.symbol = selectedSymbol;
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

window.addEventListener("resize", function () { drawChart(); drawPriceChart(); });

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
  /* Abaikan aktivasi kedua: Enter kedua di input nama masih sampai
     ke input (fokus tidak pindah saat menu menutup) sehingga tanpa
     guard ini satu Enter ganda membuat DUA profil. Pernah: double-
     Enter di Buat Profil -> 3 profil padahal maksudnya 2. */
  if ($("profileMenu").hidden) return;
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
  /* Abaikan aktivasi kedua: Enter kedua di input nama masih sampai
     ke input (fokus tidak pindah saat overlay tersembunyi) sehingga
     tanpa guard ini satu Enter ganda membuat DUA profil Guest.
     Pernah: double-Enter di layar sambutan -> profil=2. */
  if ($("welcomeOverlay").hidden) return;
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

/* Sidik data trade profil aktif — id, kas, holding, posisi futures,
   dan riwayat trade. Dipakai handler `storage` di bawah: tab lain
   menyimpan store tiap ~30 detik hanya untuk snapshot grafik
   portofolio (history), dan tanpa perbandingan ini setiap penyimpanan
   itu menghapus konteks trade tab ini (input + konfirmasi yang sedang
   dibuka) padahal kas/holding/posisinya tidak berubah. Pernah: tab B
   buka konfirmasi beli Rp1.000.000, tab A refresh harga -> snapshot
   baru tersimpan -> input B kosong dan konfirmasinya tertutup sendiri.
   Hanya bila sidiknya berubah (trade sungguhan / ganti profil /
   reset di tab lain) konteks trade dibatalkan. History sengaja TIDAK
   masuk sidik: snapshot grafik bukan data trade. */
function profileTradeFingerprint(p) {
  if (!p) return "";
  return JSON.stringify({
    id: p.id, cash: p.cash, holdings: p.holdings,
    futures: p.futures, trades: p.trades
  });
}

/* Sinkronisasi antar-tab: localStorage dipakai BERSAMA oleh semua tab
   di origin yang sama, tapi tiap tab menyimpan `store`/`state` basi di
   memori. Tanpa ini, tab yang dibuka lebih dulu lalu trade lagi akan
   menimpa localStorage dengan salinan basinya lewat saveStore() —
   trade yang dibuat di tab lain HILANG. Pernah: tab A beli BTC, tab B
   jual habis (riwayat 2 trade, tanpa holding), tab A beli ETH tanpa
   reload -> localStorage jadi [beli BTC, beli ETH] (jual B hilang) dan
   holding BTC "bangkit" lagi. Event `storage` hanya ditembakkan di tab
   LAIN (bukan tab yang mengubah), jadi tidak ada loop. Begitu tab lain
   mengubah data, tab ini memuat ulang store + state, membatalkan
   konteks trade milik state lama (pending dihitung dari holding/kas
   lama), lalu render ulang — sebelum user sempat menekan apa pun. */
window.addEventListener("storage", function (e) {
  if (e.key === STORAGE_KEY) {
    var before = profileTradeFingerprint(state);
    store = loadStore();
    state = activeProfile();
    /* Batalkan konteks trade + status armed Reset HANYA bila data
       trade profil aktif berubah di tab lain (lihat
       profileTradeFingerprint). Penyimpanan rutin berupa snapshot
       grafik portofolio (history) tidak mengubah kas/holding/posisi,
       jadi input + konfirmasi yang sedang dibuka di tab ini tetap
       utuh dan masih bisa dieksekusi. */
    if (profileTradeFingerprint(state) !== before) {
      disarmReset();
      clearTradeContext();
    }
    if (state) {
      $("welcomeOverlay").hidden = true;
    } else if (store.profiles.length === 0) {
      $("welcomeOverlay").hidden = false;
    }
    renderAll();
  } else if (e.key === LASTLIVE_KEY) {
    /* Harga live terakhir berubah di tab lain — pakai salinan baru
       untuk PnL/valuasi beku, lalu render ulang. */
    loadLastLivePrices();
    renderAll();
  }
});

renderAll();
fetchPrices();
fetchPriceChart(selectedSymbol);
setInterval(fetchPrices, REFRESH_MS);
if (store.profiles.length === 0) {
  $("welcomeOverlay").hidden = false;
  /* Fokus otomatis HANYA di perangkat ber-pointer halus (mouse/
     keyboard): di HP (touch) focus() langsung membuka keyboard
     virtual begitu halaman pertama dibuka — menutupi kartu
     sambutan sebelum user memilih mengetik. Sama alasannya dengan
     larangan focus() saat ganti koin (lihat renderMarket): user HP
     mengetuk input sendiri bila mau mengisi nama. */
  if (window.matchMedia && window.matchMedia("(pointer: fine)").matches) {
    setTimeout(function () { $("guestNameInput").focus(); }, 100);
  }
}
