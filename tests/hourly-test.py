#!/usr/bin/env python3
"""Uji otomatis SIMULASI TRADING (Playwright, Python).

Skenario:
  live     - CoinGecko dimock harga live (bedakan dari harga contoh)
  offline  - semua API eksternal diblokir -> harga contoh, badge OFFLINE
  binance  - CoinGecko gagal, Binance Vision dimock -> harus tetap LIVE

Jalankan: <venv>/bin/python tests/hourly-test.py [live|offline|binance|all]
  (venv: ~/workspace/custom-skills/airdrop-agent/.venv)
Server lokal: python3 -m http.server 8931 --directory ~/workspace/simulasi-trading
"""
import json, sys, threading, http.server, functools, os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8931/index.html"
DIR = os.path.expanduser("~/workspace/simulasi-trading")

# Harga live mock — sengaja beda jauh dari harga contoh (BTC contoh 1,5 Miliar)
LIVE = {
    "bitcoin":     {"idr": 1120000000, "idr_24h_change": 1.5},
    "ethereum":    {"idr": 58000000,   "idr_24h_change": -0.8},
    "binancecoin": {"idr": 15000000,   "idr_24h_change": 0.4},
    "solana":      {"idr": 3000000,    "idr_24h_change": 2.1},
    "ripple":      {"idr": 36000,      "idr_24h_change": -1.1},
    "dogecoin":    {"idr": 3200,       "idr_24h_change": 0.3},
    "cardano":     {"idr": 13000,      "idr_24h_change": -0.5},
    "tron":        {"idr": 4800,       "idr_24h_change": 0.9},
}
# Binance Vision mock: USDT x USDTIDR(16350) -> BTC ~1.002.799.128 (beda dari keduanya)
BINANCE_USDT = {
    "BTCUSDT": 61333.28, "ETHUSDT": 1728.76, "BNBUSDT": 640.50,
    "SOLUSDT": 92.10, "XRPUSDT": 1.85, "DOGEUSDT": 0.16,
    "ADAUSDT": 0.42, "TRXUSDT": 0.24, "USDTIDR": 16350.0,
}
BINANCE_CHG = {s: -1.2 for s in BINANCE_USDT}
SAMPLE_BTC = 1500000000

results = []
def check(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(detail)) if detail else ""))

def start_server():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIR)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8931), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

def mock_chart(route):
    import time
    now = int(time.time() * 1000)
    pts = [[now - (96 - i) * 900000, 1100000000 + i * 200000] for i in range(97)]
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"prices": pts}))

def new_page(pw, viewport, scenario, price_state, touch=False):
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport=viewport, has_touch=touch,
                              is_mobile=touch)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg_handler(route):
        if scenario == "offline":
            route.abort()
        elif scenario == "binance":
            route.abort()
        else:
            url = route.request.url
            if "simple/price" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(price_state["live"]))
            elif "market_chart" in url:
                mock_chart(route)
            else:
                route.abort()

    def bin_handler(route):
        if scenario == "offline":
            route.abort()
        elif scenario == "binance":
            import urllib.parse, json as js
            q = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query)
            syms = js.loads(q.get("symbols", ["[]"])[0])
            out = [{"symbol": s, "lastPrice": str(BINANCE_USDT[s]),
                    "priceChangePercent": str(BINANCE_CHG[s])} for s in syms]
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(out))
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg_handler)
    page.route("**/data-api.binance.vision/**", bin_handler)
    page.route("**/api.binance.com/**", bin_handler)
    return browser, ctx, page, errors

def enter_guest(page):
    page.goto(BASE)
    page.wait_for_selector("#welcomeOverlay:not([hidden])", timeout=10000)
    page.click("#guestEnterBtn")
    page.wait_for_function("() => document.getElementById('welcomeOverlay').hidden", timeout=5000)
    page.wait_for_function("() => !document.getElementById('profileWrap').hidden", timeout=5000)

def cash_text(page):
    return page.text_content("#cashBalance")

def test_live(pw):
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        check("guest: masuk, kas awal Rp5.000.000", "5.000.000" in cash_text(page), cash_text(page))
        check("badge HARGA LIVE", "HARGA LIVE" in page.text_content("#priceBadgeText"))
        check("harga BTC live mock tampil", "1.120.000.000" in page.text_content("#tradePrice"),
              page.text_content("#tradePrice"))
        check("pasar: 8 koin", page.locator("#marketList .market-row, #marketList > *").count() >= 8,
              str(page.locator("#marketList").inner_text()[:80]))
        # Spot beli
        page.fill("#amountInput", "1000000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(500)
        check("spot beli: kas jadi Rp4.000.000", "4.000.000" in cash_text(page), cash_text(page))
        check("spot beli: holding BTC muncul", "BTC" in page.text_content("#holdingsList"))
        # Spot jual
        page.click("#tabSell")
        page.fill("#amountInput", "0.0004")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(500)
        check("spot jual: kas naik", "4.448.000" in cash_text(page), cash_text(page))
        # Futures: chip 100x + slider 100
        page.click('.lev-chip[data-lev="100"]')
        check("chip 100x aktif, label 100x", page.text_content("#futLevLabel") == "100x")
        page.locator("#futLeverage").evaluate(
            "el => { el.value='100'; el.dispatchEvent(new Event('input',{bubbles:true}));"
            " el.dispatchEvent(new Event('change',{bubbles:true})); }")
        check("slider leverage 100", page.text_content("#futLevLabel") == "100x")
        page.fill("#futMarginInput", "100000")
        page.wait_for_selector("#futPreview:not([hidden])", timeout=5000)
        prev = page.text_content("#futPreview")
        check("preview futures: liq = entry x 0,99 (100x Long)",
              "1.108.800.000" in prev, prev.replace("\n", " ")[:160])
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_timeout(500)
        pos = page.text_content("#futPositions")
        check("futures Long 100x terbuka, entry = harga live mock",
              "1.120.000.000" in pos, pos.replace("\n", " ")[:200])
        check("futures: kartu posisi tampil PnL", "PnL" in pos, pos.replace("\n", " ")[:200])
        # Futures Short 5x
        page.click("#futShort")
        page.click('.lev-chip[data-lev="5"]')
        page.fill("#futMarginInput", "50000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_timeout(500)
        check("futures Short 5x terbuka (2 posisi)",
              page.locator("#futPositions .position-card, #futPositions .position-row").count() >= 2
              or "Short" in page.text_content("#futPositions"))
        # Grafik 24 jam + portofolio ter-render
        page.wait_for_timeout(1500)
        check("grafik harga 24j: catatan live (bukan contoh)",
              "contoh" not in page.text_content("#priceChartNote").lower(),
              page.text_content("#priceChartNote"))
        check("grafik portofolio: canvas ada", page.locator("#chart").count() == 1)
        # Likuidasi otomatis: jatuhkan harga BTC di bawah liq Long 100x
        price_state["live"] = dict(LIVE)
        price_state["live"]["bitcoin"] = {"idr": 1000000000, "idr_24h_change": -10.0}
        page.click("#refreshBtn")
        page.wait_for_timeout(2500)
        pos2 = page.text_content("#futPositions")
        hist = page.text_content("#tradeHistory")
        check("likuidasi otomatis: Long 100x tertutup saat mark < liq",
              "Long" not in pos2 or "Short" in pos2, pos2.replace("\n", " ")[:160])
        check("riwayat: ada baris likuidasi",
              "likuidasi" in hist.lower() or "TERLIKUIDASI" in hist, hist[:200])
        check("riwayat: tanpa tombol hapus", "Hapus" not in hist)
        # Reset (dua langkah)
        page.click("#resetBtn")
        page.wait_for_timeout(300)
        page.click("#resetBtn")
        page.wait_for_timeout(500)
        check("reset: kas kembali Rp5.000.000", "5.000.000" in cash_text(page), cash_text(page))
        check("reset: riwayat kosong", "Belum ada transaksi" in page.text_content("#tradeHistory"))
        check("0 error JS (live, desktop)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_mobile_live(pw):
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 390, "height": 844}, "live", price_state)
    try:
        enter_guest(page)
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check("mobile 390px: tanpa overflow horizontal", overflow <= 1, f"overflow {overflow}px")
        page.fill("#amountInput", "500000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        check("mobile: spot beli jalan", "4.500.000" in cash_text(page), cash_text(page))
        page.click('.lev-chip[data-lev="100"]')
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_timeout(400)
        check("mobile: futures 100x terbuka", "100x" in page.text_content("#futPositions"))
        check("0 error JS (live, mobile)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_offline(pw):
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "offline", price_state)
    try:
        enter_guest(page)
        check("offline: badge HARGA CONTOH (OFFLINE)",
              "CONTOH" in page.text_content("#priceBadgeText"), page.text_content("#priceBadgeText"))
        check("offline: banner tampil", page.locator("#offlineBanner:not([hidden])").count() == 1)
        # Daftar pasar tetap menampilkan harga contoh (berlabel OFFLINE
        # oleh badge + banner) — tapi panel trade/futures TIDAK BOLEH
        # menampilkan harga contoh sebagai "Harga saat ini"/"Harga mark":
        # belum pernah ada harga live -> panel menampilkan "—"
        # (konsisten dengan holding/PnL yang menampilkan "—").
        check("offline: daftar pasar menampilkan harga contoh 1,5 Miliar",
              "1.500.000.000" in page.text_content("#marketList"), page.text_content("#marketList")[:120])
        check("offline: panel trade/futures '—' (bukan harga contoh) bila belum pernah ada harga live",
              page.text_content("#tradePrice").strip() == "—" and
              page.text_content("#futPrice").strip() == "—",
              "trade=" + page.text_content("#tradePrice") + " fut=" + page.text_content("#futPrice"))
        # Coba buka posisi futures saat offline — HARUS DIBLOKIR (bukan entry harga contoh)
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_timeout(800)
        fut_err = page.text_content("#futError")
        fut_err_hidden = page.locator("#futError[hidden]").count() == 1
        confirm_shown = page.locator("#futConfirmBox:not([hidden])").count() == 1
        if confirm_shown:
            page.click("#futConfirmYes")
            page.wait_for_timeout(500)
        pos = page.text_content("#futPositions")
        blocked = ("Belum ada posisi" in pos) and (not fut_err_hidden)
        check("offline: buka posisi futures DIBLOKIR (tanpa harga live)",
              blocked, "futError=" + (fut_err or "(hidden)") +
              " | confirm muncul=" + str(confirm_shown) + " | posisi: " + pos[:120])
        check("0 error JS (offline)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_spot_offline_blocked(pw):
    """Regresi: beli/jual spot TIDAK BOLEH dieksekusi di harga contoh
    saat offline (pernah: beli Rp1.000.000 dieksekusi @ Rp1.500.000.000
    -> langsung rugi ~25% begitu harga live ~Rp1,12 Miliar kembali).
    Sama alasannya dengan blokir buka posisi futures saat offline."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "offline", price_state)
    try:
        enter_guest(page)
        # Beli spot saat offline — HARUS DIBLOKIR
        page.fill("#amountInput", "1000000")
        page.wait_for_timeout(500)
        err = page.text_content("#tradeError")
        err_hidden = page.locator("#tradeError[hidden]").count() == 1
        page.click("#tradeBtn")
        page.wait_for_timeout(800)
        confirm_shown = page.locator("#confirmBox:not([hidden])").count() == 1
        check("spot-offline: beli DIBLOKIR, pesan harga live tampil",
              (not err_hidden) and "Harga live tidak tersedia" in (err or "") and not confirm_shown,
              "err=" + (err or "(hidden)") + " | confirm muncul=" + str(confirm_shown))
        check("spot-offline: kas tetap Rp5.000.000 (tidak ada trade)",
              "5.000.000" in cash_text(page), cash_text(page))
        check("spot-offline: tidak ada holding BTC dari harga contoh",
              "BTC" not in page.text_content("#holdingsList"),
              page.text_content("#holdingsList")[:120])
        check("spot-offline: riwayat tetap kosong",
              "Belum ada transaksi" in page.text_content("#tradeHistory"),
              page.text_content("#tradeHistory")[:120])
        # Jual spot saat offline — juga HARUS DIBLOKIR (pesan yang sama)
        page.click("#tabSell")
        page.fill("#amountInput", "0.001")
        page.wait_for_timeout(500)
        err2 = page.text_content("#tradeError")
        page.click("#tradeBtn")
        page.wait_for_timeout(500)
        confirm2 = page.locator("#confirmBox:not([hidden])").count() == 1
        check("spot-offline: jual DIBLOKIR juga",
              "Harga live tidak tersedia" in (err2 or "") and not confirm2,
              "err=" + (err2 or "(hidden)") + " | confirm muncul=" + str(confirm2))
        check("0 error JS (spot-offline)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_binance(pw):
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "binance", price_state)
    try:
        enter_guest(page)
        page.wait_for_timeout(1500)
        badge = page.text_content("#priceBadgeText")
        price = page.text_content("#tradePrice")
        check("binance fallback: badge HARGA LIVE saat CoinGecko gagal",
              "HARGA LIVE" in badge, badge)
        check("binance fallback: harga BTC dari Binance (~Rp1.002.799.128)",
              "1.002.799.128" in price, price)
        check("0 error JS (binance fallback)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_offline_history(pw):
    """Regresi: snapshot grafik portofolio TIDAK BOLEH mencatat nilai
    harga contoh saat offline (pernah: holding BTC dinilai Rp1,5 Miliar
    -> riwayat melonjak palsu +Rp339.286 dan tersimpan permanen)."""
    mode = {"offline": False}
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if mode["offline"]:
            route.abort()
        elif "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        else:
            route.abort()

    def bn(route):
        route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", bn)
    page.route("**/api.binance.com/**", bn)
    try:
        enter_guest(page)
        page.wait_for_timeout(1200)
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(600)
        def last_hist():
            return page.evaluate("""() => {
              var s = JSON.parse(localStorage.getItem('simulasi-trading-v2') || 'null');
              if (!s) return null;
              var p = s.profiles.find(x => x.id === s.activeProfileId);
              return p ? p.history : null;
            }""")
        h1 = last_hist()
        check("offline-history: riwayat live tercatat Rp5.000.000 setelah beli",
              h1 and h1[-1]["v"] == 5000000, str(h1[-1:] if h1 else None))
        mode["offline"] = True
        page.click("#refreshBtn")
        page.wait_for_timeout(2500)
        check("offline-history: badge OFFLINE setelah refresh",
              "CONTOH" in page.text_content("#priceBadgeText"))
        h2 = last_hist()
        check("offline-history: TIDAK ada titik baru di harga contoh (riwayat beku)",
              h2 and len(h2) == len(h1) and h2[-1]["v"] == h1[-1]["v"],
              "sebelum=%s sesudah=%s" % (h1[-1:] if h1 else None, h2[-1:] if h2 else None))
        check("0 error JS (offline-history)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_spot_offline_frozen_value(pw):
    """Regresi: nilai portofolio + holding spot TIDAK BOLEH dihitung dari
    harga contoh saat offline (pernah: beli BTC Rp1.000.000 @ live
    Rp1.120.000.000 -> offline total melonjak palsu jadi Rp5.339.286
    dan holding Rp1.339.286 karena dinilai di harga contoh Rp1,5 Miliar).
    Harus beku di harga live terakhir: total Rp5.000.000, PnL Rp0."""
    mode = {"offline": False}
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if mode["offline"]:
            route.abort()
        elif "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        else:
            route.abort()

    def bn(route):
        route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", bn)
    page.route("**/api.binance.com/**", bn)
    try:
        enter_guest(page)
        page.wait_for_timeout(1200)
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(600)
        check("spot-offline-value: total live Rp5.000.000 setelah beli",
              "5.000.000" in page.text_content("#totalValue"), page.text_content("#totalValue"))
        mode["offline"] = True
        page.click("#refreshBtn")
        page.wait_for_timeout(2500)
        check("spot-offline-value: badge OFFLINE setelah refresh",
              "CONTOH" in page.text_content("#priceBadgeText"))
        check("spot-offline-value: total BEKU Rp5.000.000, bukan Rp5.339.286",
              "5.000.000" in page.text_content("#totalValue") and
              "5.339.286" not in page.text_content("#totalValue"),
              page.text_content("#totalValue"))
        check("spot-offline-value: PnL beku Rp0, bukan +Rp339.286",
              "Rp 0" in page.text_content("#totalPnl") and
              "339.286" not in page.text_content("#totalPnl"),
              page.text_content("#totalPnl"))
        hold = page.text_content("#holdingsList")
        check("spot-offline-value: holding beku Rp1.000.000 + label harga live terakhir",
              "1.000.000" in hold and "1.339.286" not in hold and
              "harga live terakhir" in hold, hold)
        fs = page.text_content("#futuresSummary")
        check("spot-offline-value: catatan nilai beku tampil",
              "harga live terakhir" in fs, fs)
        check("0 error JS (spot-offline-value)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_fetch_race(pw):
    """Regresi: fetch harga basi TIDAK BOLEH menimpa harga live yang lebih
    baru (pernah: fetch lama gagal lambat lalu menerapkan harga contoh di
    atas harga live dari fetch baru — posisi Short bisa terlikuidasi
    keliru karena mark melonjak ke harga contoh Rp1,5 Miliar)."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.route("**/api.coingecko.com/**", lambda r: r.abort())
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_timeout(1200)
        check("fetch-race: awal offline (harga contoh)",
              "CONTOH" in page.text_content("#priceBadgeText"))
        # Pasang fetch tiruan: panggilan CoinGecko ke-1 gagal LAMBAT
        # (2,5 dtk), ke-2 langsung live; Binance selalu gagal.
        page.evaluate("""() => {
          window.__origFetch = window.fetch.bind(window);
          window.__cgCalls = 0;
          var live = {bitcoin:{idr:1120000000,idr_24h_change:1.5},
            ethereum:{idr:58000000,idr_24h_change:-0.8},
            binancecoin:{idr:15000000,idr_24h_change:0.4},
            solana:{idr:3000000,idr_24h_change:2.1},
            ripple:{idr:36000,idr_24h_change:-1.1},
            dogecoin:{idr:3200,idr_24h_change:0.3},
            cardano:{idr:13000,idr_24h_change:-0.5},
            tron:{idr:4800,idr_24h_change:0.9}};
          window.fetch = function(url, opts) {
            var u = String(url);
            if (u.indexOf('simple/price') !== -1) {
              window.__cgCalls++;
              if (window.__cgCalls === 1) {
                return new Promise(function(res, rej) {
                  setTimeout(function() { rej(new Error('slow fail')); }, 2500);
                });
              }
              return Promise.resolve(new Response(JSON.stringify(live),
                {status: 200, headers: {'Content-Type': 'application/json'}}));
            }
            if (u.indexOf('binance') !== -1)
              return Promise.reject(new Error('binance off'));
            return window.__origFetch(url, opts);
          };
        }""")
        page.evaluate("() => { fetchPrices(); }")   # fetch lama (A)
        page.wait_for_timeout(300)
        page.evaluate("() => { fetchPrices(); }")   # fetch baru (B)
        page.wait_for_timeout(800)
        check("fetch-race: fetch baru menerapkan harga live dulu",
              "HARGA LIVE" in page.text_content("#priceBadgeText") and
              "1.120.000.000" in page.text_content("#tradePrice"),
              page.text_content("#priceBadgeText") + " | " + page.text_content("#tradePrice"))
        page.wait_for_timeout(3000)  # fetch lama (A) selesai -> jatuh ke contoh
        check("fetch-race: harga contoh dari fetch basi TIDAK menimpa harga live",
              "HARGA LIVE" in page.text_content("#priceBadgeText") and
              "1.120.000.000" in page.text_content("#tradePrice"),
              page.text_content("#priceBadgeText") + " | " + page.text_content("#tradePrice"))
        check("0 error JS (fetch-race)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_reload_offline_close(pw):
    """Regresi: tutup posisi futures SETELAH reload halaman saat offline
    HARUS memakai harga live terakhir yang tersimpan (beku), bukan harga
    entry. Pernah: lastLivePrices hanya di memori -> setelah reload
    pnlMark() = null -> tutup memakai entry, PnL 0, margin kembali penuh
    (rugi -Rp62.500 hilang begitu saja)."""
    mode = {"offline": False}
    price = {"live": dict(LIVE)}
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if mode["offline"]:
            route.abort()
        elif "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(price["live"]))
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_timeout(1000)
        page.click('.lev-chip[data-lev="10"]')
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_timeout(500)
        check("reload-close: posisi Long 10x terbuka", "4.900.000" in cash_text(page),
              cash_text(page))
        price["live"] = dict(LIVE)
        price["live"]["bitcoin"] = {"idr": 1050000000, "idr_24h_change": -6.25}
        page.click("#refreshBtn")
        page.wait_for_timeout(2000)
        hook_before = page.evaluate("window.__futuresPnl")
        check("reload-close: PnL -Rp62.500 sebelum reload",
              hook_before and hook_before[0]["pnl"] == -62500,
              str(hook_before))
        mode["offline"] = True
        page.reload()
        page.wait_for_timeout(2500)
        check("reload-close: badge OFFLINE setelah reload",
              "CONTOH" in page.text_content("#priceBadgeText"))
        hook_after = page.evaluate("window.__futuresPnl")
        check("reload-close: PnL beku -Rp62.500 tetap tampil setelah reload",
              hook_after and hook_after[0]["pnl"] == -62500 and hook_after[0]["frozen"]
              and hook_after[0]["mark"] == 1050000000,
              str(hook_after))
        page.locator("#futPositions [data-pos-id]").first.click()
        page.wait_for_timeout(800)
        check("reload-close: kas Rp4.937.500 (margin - rugi), bukan Rp5.000.000",
              "4.937.500" in cash_text(page), cash_text(page))
        hist = page.text_content("#tradeHistory")
        check("reload-close: riwayat tutup @ Rp1.050.000.000, PnL -Rp62.500",
              "1.050.000.000" in hist and "62.500" in hist, hist[:200])
        check("0 error JS (reload-close)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_chart_429(pw):
    """Regresi: market_chart CoinGecko 429 padahal harga simple/price LIVE.
    Pernah: grafik 24j jatuh ke deret contoh berjangkar harga contoh
    (BTC Rp1,5 Miliar, titik awal ~Rp1,46 Miliar) sementara badge
    HARGA LIVE — label "Grafik contoh (offline)" kontradiktif dan garis
    mark live terpisah jauh dari grafik. Kini deret cadangan dijangkar
    pada harga live (estimasi) dan dicoba ulang sampai data asli pulih."""
    chart_ok = {"ok": False}
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        url = route.request.url
        if "simple/price" in url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in url:
            if chart_ok["ok"]:
                mock_chart(route)
            else:
                route.fulfill(status=429, content_type="application/json",
                              body=json.dumps({"status": {"error_code": 429}}))
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function("() => window.__priceChart && window.__priceChart.estimated",
                               timeout=15000)
        check("chart-429: badge HARGA LIVE walau market_chart 429",
              "HARGA LIVE" in page.text_content("#priceBadgeText"),
              page.text_content("#priceBadgeText"))
        pts = page.evaluate("() => { const h = window.priceHistory.BTC; "
                            "return {first: h.points[0].v, last: h.points[h.points.length-1].v}; }")
        check("chart-429: deret estimasi berjangkar harga live (bukan contoh Rp1,5 M)",
              1000000000 < pts["first"] < 1200000000 and
              abs(pts["last"] - 1120000000) < 1120000000 * 0.01,
              str(pts))
        note = page.text_content("#priceChartNote")
        check("chart-429: label 'estimasi', bukan 'contoh (offline)'",
              "estimasi" in note.lower() and "contoh (offline)" not in note.lower(),
              note)
        # Rate limit reda -> grafik asli harus pulih sendiri via retry berkala.
        chart_ok["ok"] = True
        page.wait_for_function("() => window.__priceChart && window.__priceChart.live",
                               timeout=120000)
        note2 = page.text_content("#priceChartNote")
        check("chart-429: grafik live pulih setelah rate limit reda",
              "CoinGecko" in note2 and "estimasi" not in note2.lower(), note2)
        check("0 error JS (chart-429)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_chart_mark_offline(pw):
    """Regresi: garis Mark di grafik 24 jam saat offline.
    Pernah: drawPriceChart() memakai currentPrice() mentah sehingga
    saat offline garis Mark melonjak ke harga contoh (BTC
    Rp1.500.000.000) dan ikut merusak skala sumbu grafik, padahal
    deret grafiknya sendiri sudah dijangkar harga live terakhir.
    Kini garis Mark memakai pnlMark(): harga live saat live, harga
    live terakhir (beku) saat offline."""
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page.wait_for_function("() => window.__priceChart && window.__priceChart.points > 10",
                               timeout=10000)
        lines = page.evaluate("() => window.__priceChart.lines")
        mark = [l for l in lines if l["type"] == "mark"]
        check("chart-mark: garis Mark live = Rp1.120.000.000",
              len(mark) == 1 and mark[0]["price"] == 1120000000, mark)
        # Putuskan semua API lalu Refresh -> harga contoh (offline)
        page.route("**/api.coingecko.com/**", lambda r: r.abort())
        page.route("**/data-api.binance.vision/**", lambda r: r.abort())
        page.route("**/api.binance.com/**", lambda r: r.abort())
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent.includes('CONTOH')",
            timeout=15000)
        page.wait_for_timeout(500)
        lines2 = page.evaluate("() => window.__priceChart.lines")
        mark2 = [l for l in lines2 if l["type"] == "mark"]
        check("chart-mark: garis Mark offline BUKAN harga contoh Rp1.500.000.000",
              not (mark2 and mark2[0]["price"] == SAMPLE_BTC), mark2)
        check("chart-mark: garis Mark offline = harga live terakhir beku Rp1.120.000.000",
              len(mark2) == 1 and mark2[0]["price"] == 1120000000, mark2)
        check("0 error JS (chart-mark)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_sell_max(pw):
    """Regresi: tombol cepat 100% (Maks) di mode JUAL harus bisa jual semua.
    Pernah: beli Rp1.000.000 @ Rp1.120.000.000 = 0,000892857142... BTC;
    klik 100% mengisi 0.00089286 (toFixed(8) membulat ke ATAS holding)
    lalu computeTrade menolak 'Koin tidak cukup' — padahal angka yang
    ditampilkan sama dengan yang dimiliki. Kini computeTrade menjepit
    selisih pembulatan ke holding yang dimiliki."""
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('4.000.000')",
            timeout=5000)
        page.click("#tabSell")
        page.wait_for_timeout(300)
        page.click("[data-pct='100']")
        page.wait_for_timeout(300)
        val = float(page.input_value("#amountInput"))
        owned = 1000000 / 1120000000
        check("sell-max: tombol 100% mengisi jumlah koin (boleh sedikit di atas "
              "holding karena pembulatan, ditangani computeTrade)",
              0 < val <= owned + 1e-8, f"input={val} owned={owned}")
        check("sell-max: tidak ada error 'Koin tidak cukup' setelah klik 100%",
              page.is_hidden("#tradeError"), page.text_content("#tradeError"))
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('5.000.000')",
            timeout=5000)
        check("sell-max: jual 100% berhasil, kas kembali Rp5.000.000",
              "5.000.000" in cash_text(page), cash_text(page))
        check("sell-max: holding BTC habis setelah jual semua",
              "Belum ada koin" in page.text_content("#holdingsList"),
              page.text_content("#holdingsList"))
        # Ketik manual jumlah yang tampil di riwayat (0,00089286 — sedikit
        # di atas holding sebenarnya 0,000892857142...) juga harus lolos
        # berkat toleransi pembulatan di computeTrade.
        page.click("#tabBuy")
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('4.000.000')",
            timeout=5000)
        page.click("#tabSell")
        page.fill("#amountInput", "0.00089286")
        page.wait_for_timeout(300)
        check("sell-max: ketik manual 0,00089286 (sedikit di atas holding) "
              "tidak ditolak pembulatan",
              page.is_hidden("#tradeError") and
              not page.is_hidden("#previewBox"),
              page.text_content("#tradeError"))
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('5.000.000')",
            timeout=5000)
        check("sell-max: jual manual 0,00089286 berhasil, kas kembali Rp5.000.000",
              "5.000.000" in cash_text(page), cash_text(page))
        check("0 error JS (sell-max)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_tab_switch_clears_input(pw):
    """Regresi: ganti tab Beli/Jual harus mengosongkan input jumlah.
    Pernah: ketik Rp1.000.000 di mode Beli, ketuk tab Jual — input tetap
    "1000000" tapi dibaca sebagai 1.000.000 BTC sehingga muncul error
    menyesatkan 'Koin tidak cukup. Kamu punya 0 BTC.' (dan sebaliknya:
    0,0005 BTC di mode Jual dibaca sebagai Rp0,0005 di mode Beli)."""
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Beli -> Jual: angka Rupiah tidak boleh terbawa sebagai jumlah koin
        page.fill("#amountInput", "1000000")
        page.wait_for_timeout(300)
        check("tab-switch: pratinjau beli tampil sebelum ganti tab",
              not page.is_hidden("#previewBox"))
        page.click("#tabSell")
        page.wait_for_timeout(300)
        check("tab-switch: input dikosongkan saat pindah ke Jual",
              page.input_value("#amountInput") == "",
              repr(page.input_value("#amountInput")))
        check("tab-switch: tidak ada error 'Koin tidak cukup' menyesatkan "
              "setelah pindah ke Jual",
              page.is_hidden("#tradeError"), page.text_content("#tradeError"))
        check("tab-switch: pratinjau tersembunyi setelah pindah ke Jual",
              page.is_hidden("#previewBox"))
        # Jual -> Beli: angka koin tidak boleh terbawa sebagai Rupiah
        page.fill("#amountInput", "0.0005")
        page.wait_for_timeout(300)
        page.click("#tabBuy")
        page.wait_for_timeout(300)
        check("tab-switch: input dikosongkan saat pindah kembali ke Beli",
              page.input_value("#amountInput") == "",
              repr(page.input_value("#amountInput")))
        check("tab-switch: tidak ada error setelah pindah kembali ke Beli",
              page.is_hidden("#tradeError"), page.text_content("#tradeError"))
        # Alur normal tetap jalan setelah ganti-ganti tab
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('4.000.000')",
            timeout=5000)
        check("tab-switch: beli tetap berhasil setelah ganti tab",
              "4.000.000" in cash_text(page), cash_text(page))
        check("0 error JS (tab-switch)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_partial_coingecko(pw):
    """Regresi: respons CoinGecko TIDAK LENGKAP (satu koin hilang).
    Pernah: CoinGecko mengembalikan 7 dari 8 koin (SOL hilang) lalu
    applyPrices tetap mengklaim HARGA LIVE — SOL dinilai Rp0 (total
    portofolio anjlok palsu Rp5.000.000 -> Rp3.500.000, snapshot grafik
    ikut mencatat nilai palsu) dan likuidasi posisi SOL dilewati.
    Kini fetchPrices menolak respons tidak lengkap: coba Binance, lalu
    harga contoh — total beku di harga live terakhir, bukan Rp0."""
    import urllib.parse
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Beli SOL Rp1.500.000 @ Rp3.000.000 = 0,5 SOL
        page.locator("#marketList .market-row", has_text="Solana").click()
        page.wait_for_timeout(500)
        page.fill("#amountInput", "1500000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('3.500.000')",
            timeout=5000)
        # CoinGecko parsial (SOL hilang), Binance gagal -> harus OFFLINE
        partial = {k: v for k, v in LIVE.items() if k != "solana"}
        def cg_partial(route):
            url = route.request.url
            if "simple/price" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(partial))
            elif "market_chart" in url:
                mock_chart(route)
            else:
                route.abort()
        page.route("**/api.coingecko.com/**", cg_partial)
        page.route("**/data-api.binance.vision/**", lambda r: r.abort())
        page.route("**/api.binance.com/**", lambda r: r.abort())
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent.includes('CONTOH')",
            timeout=15000)
        page.wait_for_timeout(500)
        check("partial-cg: badge OFFLINE, bukan klaim HARGA LIVE palsu",
              "CONTOH" in page.text_content("#priceBadgeText"),
              page.text_content("#priceBadgeText"))
        check("partial-cg: total BEKU Rp5.000.000, bukan Rp3.500.000 (SOL = Rp0)",
              "5.000.000" in page.text_content("#totalValue"),
              page.text_content("#totalValue"))
        hold = page.text_content("#holdingsList") or ""
        check("partial-cg: holding SOL beku Rp1.500.000 + label harga live terakhir",
              "1.500.000" in hold and "harga live terakhir" in hold, hold.replace("\n", " ")[:160])
        hist = page.evaluate(
            "() => JSON.parse(localStorage.getItem('simulasi-trading-v2'))"
            ".profiles[0].history.map(h => h.v)")
        check("partial-cg: snapshot grafik TIDAK mencatat Rp3.500.000 palsu",
              3500000 not in hist, hist)
        # Binance pulih -> harga live lagi dari cadangan (SOL dari Binance)
        def bin_ok(route):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query)
            syms = json.loads(q.get("symbols", ["[]"])[0])
            out = [{"symbol": s, "lastPrice": str(BINANCE_USDT[s]),
                    "priceChangePercent": str(BINANCE_CHG[s])} for s in syms]
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(out))
        page.route("**/data-api.binance.vision/**", bin_ok)
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=15000)
        sol_row = page.locator(
            "#marketList .market-row", has_text="Solana").inner_text()
        check("partial-cg: Binance cadangan pulih, SOL live dari Binance "
              "(92,10 x 16350 = Rp1.505.835)",
              "1.505.835" in sol_row, sol_row.replace("\n", " "))
        check("0 error JS (partial-cg)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_stale_confirm(pw):
    """Regresi: konfirmasi trade/futures TIDAK BOLEH dieksekusi di harga basi.
    Pernah: konfirmasi beli dibuka @ Rp1.120.000.000, harga berubah jadi
    Rp1.100.000.000 (refresh 30 detik) sebelum klik "Ya" — eksekusi tetap
    memakai harga lama (riwayat @ Rp1.120.000.000); posisi Long yang dibuka
    begitu langsung PnL -18,18% karena entry harga lama sementara mark
    sudah Rp1.080.000.000. Kini applyPrices membatalkan konfirmasi yang
    harganya sudah berubah (kotak tertutup + toast), user konfirmasi ulang
    di harga baru. Refresh dengan harga yang SAMA tidak membatalkan."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('tradePrice').textContent.includes('1.120.000.000')",
            timeout=10000)
        # --- SPOT: konfirmasi @ Rp1.120.000.000 ---
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        check("stale-confirm: konfirmasi spot tampil @ Rp1.120.000.000",
              page.is_visible("#confirmBox") and
              "1.120.000.000" in page.text_content("#confirmText"),
              page.text_content("#confirmText"))
        # Refresh dengan harga SAMA -> konfirmasi TIDAK dibatalkan
        page.click("#refreshBtn")
        page.wait_for_timeout(1200)
        check("stale-confirm: refresh harga sama TIDAK membatalkan konfirmasi",
              page.is_visible("#confirmBox"), "confirmBox hilang padahal harga sama")
        # Harga berubah -> refresh -> konfirmasi harus BATAL, tanpa eksekusi
        price_state["live"] = dict(LIVE)
        price_state["live"]["bitcoin"] = {"idr": 1100000000, "idr_24h_change": 1.5}
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('tradePrice').textContent.includes('1.100.000.000')",
            timeout=10000)
        check("stale-confirm: konfirmasi spot BATAL setelah harga berubah",
              page.is_hidden("#confirmBox"), "confirmBox masih tampil")
        check("stale-confirm: kas tetap Rp5.000.000, belum ada trade",
              "5.000.000" in cash_text(page) and
              "Belum ada transaksi" in page.text_content("#tradeHistory"),
              cash_text(page))
        # Konfirmasi ulang di harga baru -> eksekusi di harga BARU
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        check("stale-confirm: konfirmasi ulang menampilkan harga baru Rp1.100.000.000",
              "1.100.000.000" in page.text_content("#confirmText"),
              page.text_content("#confirmText"))
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('4.000.000')",
            timeout=5000)
        hist = page.text_content("#tradeHistory")
        check("stale-confirm: beli dieksekusi @ harga BARU Rp1.100.000.000 "
              "(0,00090909 BTC), bukan harga lama",
              "1.100.000.000" in hist and "1.120.000.000" not in hist,
              hist.replace("\n", " ")[:160])
        # --- FUTURES: konfirmasi Long @ Rp1.100.000.000 ---
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        check("stale-confirm: konfirmasi futures tampil, entry Rp1.100.000.000",
              page.is_visible("#futConfirmBox") and
              "1.100.000.000" in page.text_content("#futConfirmText"),
              page.text_content("#futConfirmText"))
        price_state["live"] = dict(LIVE)
        price_state["live"]["bitcoin"] = {"idr": 1080000000, "idr_24h_change": 1.5}
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('futPrice').textContent.includes('1.080.000.000')",
            timeout=10000)
        check("stale-confirm: konfirmasi futures BATAL setelah harga berubah",
              page.is_hidden("#futConfirmBox"), "futConfirmBox masih tampil")
        check("stale-confirm: belum ada posisi futures terbuka",
              "Belum ada posisi" in page.text_content("#futPositions"),
              page.text_content("#futPositions"))
        # Buka ulang di harga baru -> entry = harga baru, PnL awal Rp0
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_timeout(500)
        pos = page.text_content("#futPositions")
        check("stale-confirm: posisi Long entry harga BARU Rp1.080.000.000, "
              "PnL awal Rp0 (bukan -18%)",
              "1.080.000.000" in pos and "Rp 0" in pos,
              pos.replace("\n", " ")[:200])
        check("0 error JS (stale-confirm)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_profile_name_escaped(pw):
    """Regresi: nama profil berisi HTML harus tampil sebagai teks biasa.
    Pernah: nama "<b>TEST</b>" tampil tebal dan "<img src=x>" jadi elemen
    <img> sungguhan di menu profil, karena renderProfileUI memakai
    innerHTML dengan p.name mentah. Sekarang item profil dibangun
    dengan DOM + textContent."""
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        page.goto(BASE)
        page.wait_for_selector("#welcomeOverlay:not([hidden])", timeout=10000)
        page.fill("#guestNameInput", "<b>TEST</b>")
        page.click("#guestEnterBtn")
        page.wait_for_function("() => document.getElementById('welcomeOverlay').hidden", timeout=5000)
        check("profile-name: header tampil literal <b>TEST</b>",
              page.text_content("#profileName") == "<b>TEST</b>", page.text_content("#profileName"))
        page.click("#profileBtn")
        page.wait_for_function("() => !document.getElementById('profileMenu').hidden", timeout=5000)
        check("profile-name: tidak ada elemen <b> di menu profil",
              not page.evaluate("() => !!document.querySelector('#profileList .profile-item b')"),
              page.evaluate("() => document.querySelector('#profileList .profile-item').innerHTML"))
        check("profile-name: item menampilkan teks literal <b>TEST</b>",
              "<b>TEST</b>" in page.evaluate("() => document.querySelector('#profileList .profile-item').textContent"))
        page.fill("#newProfileName", "<img src=x>")
        page.click("#createProfileBtn")
        page.wait_for_function("() => document.querySelectorAll('#profileList .profile-item').length === 2", timeout=5000)
        check("profile-name: tidak ada elemen <img> di menu profil",
              not page.evaluate("() => !!document.querySelector('#profileList .profile-item img')"))
        check("profile-name: item kedua menampilkan teks literal <img src=x>",
              "<img src=x>" in page.evaluate("() => document.querySelectorAll('#profileList .profile-item')[1].textContent"))
        # Ganti profil tetap jalan setelah perbaikan DOM
        page.click("#profileBtn")
        page.wait_for_function("() => !document.getElementById('profileMenu').hidden", timeout=5000)
        page.evaluate("() => document.querySelectorAll('#profileList .profile-item')[0].click()")
        page.wait_for_function("() => document.getElementById('profileName').textContent === '<b>TEST</b>'", timeout=5000)
        check("profile-name: ganti profil ke <b>TEST</b> tetap jalan",
              page.text_content("#profileName") == "<b>TEST</b>", page.text_content("#profileName"))
        check("0 error JS (profile-name)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_overlapping_confirms(pw):
    """Konfirmasi spot + futures yang tumpang tindih tidak boleh bikin kas minus.
    Buka konfirmasi BELI Rp4.950.000, lalu konfirmasi futures margin Rp100.000,
    konfirmasi futures dulu (kas 4.900.000), lalu konfirmasi spot -> harus
    DIBATALKAN (kas tetap 4.900.000, tanpa trade). Arah sebaliknya juga dicek:
    konfirmasi futures margin Rp100.000 tertahan, beli spot Rp4.950.000 dulu,
    lalu konfirmasi futures -> dibatalkan, tanpa posisi baru."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        # Arah 1: spot tertahan, futures jalan dulu, spot dibatalkan
        page.fill("#amountInput", "4950000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.fill("#futMarginInput", "100000")
        page.wait_for_selector("#futPreview:not([hidden])", timeout=5000)
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_timeout(500)
        check("overlap: kas Rp4.900.000 setelah futures dikonfirmasi", "4.900.000" in cash_text(page), cash_text(page))
        page.click("#confirmYes")
        page.wait_for_timeout(500)
        check("overlap: beli tertahan DIBATALKAN, kas tetap Rp4.900.000 (tidak -Rp50.000)",
              "4.900.000" in cash_text(page) and "-Rp" not in cash_text(page), cash_text(page))
        check("overlap: riwayat tanpa BELI Rp4.950.000",
              "4.950.000" not in page.text_content("#tradeHistory"), page.text_content("#tradeHistory")[:120])
        check("overlap: tanpa holding spot (beli batal)", "Belum ada koin" in page.text_content("#holdingsList"),
              page.text_content("#holdingsList")[:80])
        # Arah 2: futures tertahan, spot jalan dulu, futures dibatalkan
        page.click("#resetBtn")
        page.wait_for_timeout(300)
        page.click("#resetBtn")
        page.wait_for_timeout(500)
        check("overlap: reset, kas kembali Rp5.000.000", "5.000.000" in cash_text(page), cash_text(page))
        page.fill("#futMarginInput", "100000")
        page.wait_for_selector("#futPreview:not([hidden])", timeout=5000)
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.fill("#amountInput", "4950000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(500)
        check("overlap: kas Rp50.000 setelah beli Rp4.950.000", "50.000" in cash_text(page), cash_text(page))
        page.click("#futConfirmYes")
        page.wait_for_timeout(500)
        check("overlap: futures tertahan DIBATALKAN, tanpa posisi baru",
              "Belum ada posisi futures" in page.text_content("#futPositions"), page.text_content("#futPositions")[:80])
        check("overlap: kas tetap Rp50.000 (tidak minus)", "50.000" in cash_text(page) and "-Rp" not in cash_text(page),
              cash_text(page))
        check("0 error JS (overlap-confirms)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_panel_mark_offline(pw):
    """Regresi: 'Harga saat ini' (spot) + 'Harga mark' (futures) di panel
    TIDAK BOLEH menampilkan harga contoh saat offline (pernah: panel
    menampilkan Rp1.500.000.000 sebagai 'Harga mark', padahal kartu
    posisi di seksi yang sama menampilkan mark beku Rp1.120.000.000 —
    dua angka bertentangan dalam satu kartu). Harus beku di harga
    live terakhir + label '(harga live terakhir)'."""
    mode = {"offline": False}
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if mode["offline"]:
            route.abort()
        elif "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    def bn(route):
        route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", bn)
    page.route("**/api.binance.com/**", bn)
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        check("panel-mark: harga panel live Rp1.120.000.000",
              "1.120.000.000" in page.text_content("#futPrice") and
              "1.120.000.000" in page.text_content("#tradePrice"),
              page.text_content("#futPrice") + " / " + page.text_content("#tradePrice"))
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_function(
            "() => document.querySelectorAll('#futPositions .position-row').length === 1",
            timeout=5000)
        mode["offline"] = True
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA CONTOH (OFFLINE)'",
            timeout=15000)
        fut = page.text_content("#futPrice")
        trade = page.text_content("#tradePrice")
        pos = page.text_content("#futPositions")
        check("panel-mark: 'Harga mark' offline BUKAN harga contoh Rp1.500.000.000",
              "1.500.000.000" not in fut, fut)
        check("panel-mark: 'Harga mark' offline beku Rp1.120.000.000 + label",
              "1.120.000.000" in fut and "harga live terakhir" in fut, fut)
        check("panel-mark: 'Harga saat ini' offline BUKAN harga contoh Rp1.500.000.000",
              "1.500.000.000" not in trade, trade)
        check("panel-mark: 'Harga saat ini' offline beku Rp1.120.000.000 + label",
              "1.120.000.000" in trade and "harga live terakhir" in trade, trade)
        check("panel-mark: mark kartu posisi tetap sama dengan panel (Rp1.120.000.000)",
              "1.120.000.000" in pos and "1.500.000.000" not in pos, pos[:120])
        check("0 error JS (panel-mark)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_reset_armed_profile_switch(pw):
    """Status armed tombol Reset (dua langkah) tidak boleh bocor saat
    ganti profil. Pernah: klik-1 Reset di profil A (armed), pindah
    ke profil B, SATU klik Reset di B langsung menghapus data B —
    langkah konfirmasi "terpakai" di profil lain. Harus: ganti profil
    membatalkan armed; Reset di B butuh dua klik sendiri di B."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Profil A: beli Rp500.000 supaya ada data
        page.fill("#amountInput", "500000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        check("reset-armed: profil A kas Rp4.500.000 setelah beli",
              "4.500.000" in cash_text(page), cash_text(page))
        # Buat profil B + beli di B supaya efek reset terlihat
        page.click("#profileBtn")
        page.fill("#newProfileName", "ProfilB")
        page.click("#createProfileBtn")
        page.wait_for_timeout(300)
        check("reset-armed: pindah ke profil B",
              page.text_content("#profileName") == "ProfilB", page.text_content("#profileName"))
        page.fill("#amountInput", "500000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        check("reset-armed: profil B kas Rp4.500.000 + ada riwayat BELI",
              "4.500.000" in cash_text(page) and "BELI BTC" in page.text_content("#tradeHistory"),
              cash_text(page))
        # Kembali ke A, arm Reset di A
        page.click("#profileBtn")
        page.wait_for_timeout(200)
        page.locator("#profileList .profile-item").first.click()
        page.wait_for_timeout(300)
        page.click("#resetBtn")
        check("reset-armed: klik-1 di A membuat tombol armed",
              page.text_content("#resetBtn") == "Klik lagi untuk konfirmasi",
              page.text_content("#resetBtn"))
        # SEGERA pindah ke B (dalam 4 detik timer armed) — armed harus batal
        page.click("#profileBtn")
        page.wait_for_timeout(200)
        page.locator("#profileList .profile-item").nth(1).click()
        page.wait_for_timeout(300)
        check("reset-armed: ganti profil membatalkan armed",
              page.text_content("#resetBtn") == "Reset Simulasi",
              page.text_content("#resetBtn"))
        # SATU klik Reset di B tidak boleh menghapus B
        page.click("#resetBtn")
        page.wait_for_timeout(400)
        check("reset-armed: satu klik Reset di B TIDAK menghapus B",
              "4.500.000" in cash_text(page) and "BELI BTC" in page.text_content("#tradeHistory"),
              cash_text(page) + " | " + page.text_content("#tradeHistory")[:60])
        check("reset-armed: satu klik itu justru meng-arm-kan Reset di B",
              page.text_content("#resetBtn") == "Klik lagi untuk konfirmasi",
              page.text_content("#resetBtn"))
        # Klik ke-2 di B (profil yang sama) baru mereset B
        page.click("#resetBtn")
        page.wait_for_timeout(400)
        check("reset-armed: dua klik di profil yang sama mereset B",
              "5.000.000" in cash_text(page) and
              "Belum ada transaksi" in page.text_content("#tradeHistory"),
              cash_text(page))
        check("0 error JS (reset-armed)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_profile_switch_clears_trade_context(pw):
    """Ganti/buat profil harus membersihkan konteks trade profil lama.
    Pernah: ketik jual 0,0005 BTC di profil A (punya BTC) lalu buat
    profil B — input "0.0005" + margin "100000" terbawa dan renderAll()
    di B langsung menampilkan error "Koin tidak cukup. Kamu punya 0
    BTC." di profil baru yang belum melakukan apa-apa; _pendingTrade
    dari A juga tetap set. Harus: input + margin kosong, error hilang,
    pending dinolkan, kotak konfirmasi tersembunyi — di profil baru
    maupun saat kembali ke profil lama."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Profil A: beli BTC Rp1.000.000
        page.fill("#amountInput", "1000000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        check("profile-ctx: profil A kas Rp4.000.000 setelah beli",
              "4.000.000" in cash_text(page), cash_text(page))
        # Isi konteks trade A: jual 0,0005 (valid di A) + margin + konfirmasi terbuka
        page.click("#tabSell")
        page.fill("#amountInput", "0.0005")
        page.fill("#futMarginInput", "100000")
        page.wait_for_timeout(300)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        check("profile-ctx: konfirmasi jual terbuka di A + pending ada",
              page.evaluate("() => !!window._pendingTrade"))
        # Buat profil B selagi konfirmasi terbuka
        page.click("#profileBtn")
        page.fill("#newProfileName", "ProfilB")
        page.click("#createProfileBtn")
        page.wait_for_timeout(500)
        check("profile-ctx: pindah ke profil B",
              page.text_content("#profileName") == "ProfilB", page.text_content("#profileName"))
        check("profile-ctx: input jumlah kosong di B",
              page.input_value("#amountInput") == "", repr(page.input_value("#amountInput")))
        check("profile-ctx: input margin kosong di B",
              page.input_value("#futMarginInput") == "", repr(page.input_value("#futMarginInput")))
        check("profile-ctx: TIDAK ada error 'Koin tidak cukup' di B",
              page.evaluate("() => document.getElementById('tradeError').hidden"),
              page.text_content("#tradeError"))
        check("profile-ctx: pending trade dinolkan di B",
              page.evaluate("() => window._pendingTrade === null"))
        check("profile-ctx: kotak konfirmasi tersembunyi di B",
              page.evaluate("() => document.getElementById('confirmBox').hidden"))
        # Kembali ke A: data A utuh, tapi konteks trade-nya juga bersih
        page.click("#profileBtn")
        page.wait_for_timeout(200)
        page.locator("#profileList .profile-item").first.click()
        page.wait_for_timeout(300)
        check("profile-ctx: kembali ke A, kas tetap Rp4.000.000",
              "4.000.000" in cash_text(page), cash_text(page))
        check("profile-ctx: input jumlah juga kosong saat kembali ke A",
              page.input_value("#amountInput") == "", repr(page.input_value("#amountInput")))
        check("profile-ctx: TIDAK ada error saat kembali ke A",
              page.evaluate("() => document.getElementById('tradeError').hidden"),
              page.text_content("#tradeError"))
        check("0 error JS (profile-ctx)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_coin_switch_clears_trade_context(pw):
    """Regresi: ganti koin lewat baris pasar harus membersihkan konteks trade.
    Pernah: jual 0,0005 BTC (punya BTC) lalu ketuk baris ETH — input
    "0.0005" terbawa dan langsung muncul error menyesatkan "Koin tidak
    cukup. Kamu punya 0 ETH." padahal user baru ganti koin; _pendingTrade
    dan _pendingFut koin lama juga tetap set (kotak konfirmasi tersembunyi
    tapi pending-nya hidup). Sama polanya dengan ganti profil: koin baru
    = konteks trade baru (clearTradeContext)."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Beli BTC Rp1.000.000
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        check("coin-ctx: kas Rp4.000.000 setelah beli BTC",
              "4.000.000" in cash_text(page), cash_text(page))
        # Isi konteks trade BTC: jual 0,0005 (valid) + margin + konfirmasi terbuka
        page.click("#tabSell")
        page.fill("#amountInput", "0.0005")
        page.fill("#futMarginInput", "100000")
        page.wait_for_timeout(300)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        check("coin-ctx: konfirmasi jual BTC terbuka + pending ada",
              page.evaluate("() => !!window._pendingTrade"))
        # Ganti koin ke ETH lewat baris pasar
        page.locator("#marketList .market-row", has_text="Ethereum").click()
        page.wait_for_timeout(500)
        check("coin-ctx: koin berganti ke ETH",
              page.text_content("#tradeSymbol") == "ETH", page.text_content("#tradeSymbol"))
        check("coin-ctx: input jumlah kosong di ETH",
              page.input_value("#amountInput") == "", repr(page.input_value("#amountInput")))
        check("coin-ctx: input margin kosong di ETH",
              page.input_value("#futMarginInput") == "", repr(page.input_value("#futMarginInput")))
        check("coin-ctx: TIDAK ada error 'Koin tidak cukup' di ETH",
              page.evaluate("() => document.getElementById('tradeError').hidden"),
              page.text_content("#tradeError"))
        check("coin-ctx: pending trade dinolkan",
              page.evaluate("() => window._pendingTrade === null"))
        check("coin-ctx: kotak konfirmasi tersembunyi",
              page.evaluate("() => document.getElementById('confirmBox').hidden"))
        # Futures: kembali ke BTC, buka konfirmasi Long, lalu ganti ke SOL
        page.locator("#marketList .market-row", has_text="Bitcoin").click()
        page.wait_for_timeout(400)
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        check("coin-ctx: konfirmasi futures BTC terbuka + pending ada",
              page.evaluate("() => !!window._pendingFut"))
        page.locator("#marketList .market-row", has_text="Solana").click()
        page.wait_for_timeout(500)
        check("coin-ctx: pending futures dinolkan saat ganti ke SOL",
              page.evaluate("() => window._pendingFut === null"))
        check("coin-ctx: kotak konfirmasi futures tersembunyi",
              page.evaluate("() => document.getElementById('futConfirmBox').hidden"))
        check("coin-ctx: input margin kosong di SOL",
              page.input_value("#futMarginInput") == "", repr(page.input_value("#futMarginInput")))
        # Alur normal tetap jalan setelah ganti-ganti koin: beli ETH Rp500.000
        page.click("#tabBuy")
        page.wait_for_timeout(200)
        page.fill("#amountInput", "500000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('3.500.000')",
            timeout=5000)
        check("coin-ctx: beli ETH tetap berhasil setelah ganti koin",
              "3.500.000" in cash_text(page), cash_text(page))
        check("0 error JS (coin-ctx)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_micro_sell_quick(pw):
    """Tombol cepat jual pada holding mikro (< 1 satoshi) tidak boleh
    mati. Pernah: beli Rp10 BTC @ Rp1.120.000.000 -> holding
    0,0000000089 BTC; toFixed(8) membulatkan 25%/50% jadi "0"
    sehingga input "0", pratinjau sembunyi, tombol terasa mati; 75%/
    100% mengisi "1e-8" (notasi ilmiah). Harus: semua tombol cepat
    mengisi nilai desimal biasa bukan nol + pratinjau tampil, dan
    jual 25% benar-benar tereksekusi."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Beli Rp10 BTC -> holding ~8,9e-9 BTC (< 1 satoshi)
        page.fill("#amountInput", "10")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        check("micro-sell: beli Rp10 BTC, kas Rp4.999.990",
              "4.999.990" in cash_text(page), cash_text(page))
        check("micro-sell: holding tampil 0,0000000089 koin (bukan 0,00000001)",
              "0,0000000089" in page.text_content("#holdingsList"),
              page.text_content("#holdingsList").replace("\n", " ")[:120])
        page.click("#tabSell")
        page.wait_for_timeout(300)
        for pct in ("25", "50", "75", "100"):
            page.click(f"#quickRow [data-pct='{pct}']")
            page.wait_for_timeout(300)
            val = page.input_value("#amountInput")
            check(f"micro-sell: cepat {pct}% mengisi nilai desimal bukan nol, bukan '1e-8'",
                  val not in ("", "0") and "e" not in val and float(val) > 0,
                  f"input={val!r}")
            check(f"micro-sell: cepat {pct}% menampilkan pratinjau",
                  page.is_visible("#previewBox"),
                  f"input={val!r}, preview hidden")
        # Jual 25% benar-benar tereksekusi (kas naik Rp2-3). Jangan
        # wait_for_selector confirmBox: pada kode pra-perbaikan
        # konfirmasi TIDAK PERNAH muncul (input "0") sehingga tes
        # akan crash timeout, bukan gagal bersih.
        page.click("#quickRow [data-pct='25']")
        page.wait_for_timeout(300)
        page.click("#tradeBtn")
        page.wait_for_timeout(300)
        check("micro-sell: jual 25% membuka konfirmasi (bukan 'Masukkan jumlah dulu.')",
              page.is_visible("#confirmBox"),
              page.text_content("#tradeError") if page.is_visible("#tradeError") else "confirmBox tampil")
        if page.is_visible("#confirmBox"):
            page.click("#confirmYes")
            page.wait_for_timeout(400)
        check("micro-sell: jual 25% tereksekusi, kas naik jadi Rp4.999.992",
              "4.999.992" in cash_text(page), cash_text(page))
        check("micro-sell: riwayat JUAL BTC tercatat",
              "JUAL BTC" in page.text_content("#tradeHistory"),
              page.text_content("#tradeHistory")[:80])
        check("micro-sell: riwayat jual tampil 0,000000002 BTC (bukan '0 BTC')",
              "0,000000002 BTC" in page.text_content("#tradeHistory") and
              "0 BTC" not in page.text_content("#tradeHistory"),
              page.text_content("#tradeHistory")[:120])
        check("0 error JS (micro-sell)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_id_number_format(pw):
    """Input harus menerima format angka Indonesia seperti yang
    ditampilkan aplikasi ("Rp1.000.000", "0,00089286"). Pernah:
    input type="number" + parseFloat mentah membuat "1.000.000"
    dibaca Rp1 (beli Rp1.000.000 diam-diam jadi beli Rp1),
    "0,00089286" dibaca 89286 koin (jual selalu gagal "Koin tidak
    cukup"), dan margin "100.000" dibaca Rp100 (notional Rp1.000).
    Harus: ketik persis seperti tampilan -> terbaca benar; format
    polos ("1000000") dan desimal mikro ("0.000000002" dari tombol
    cepat) tetap jalan."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Beli ketik "1.000.000" (persis seperti tampilan Rupiah)
        page.fill("#amountInput", "1.000.000")
        page.wait_for_timeout(300)
        check("id-format: beli '1.000.000' pratinjau Rp1.000.000 (bukan Rp1)",
              page.is_visible("#previewBox") and "1.000.000" in page.text_content("#previewBox"),
              page.text_content("#previewBox").replace("\n", " ")[:140])
        check("id-format: beli '1.000.000' dapat 0,00089286 BTC",
              "0,00089286 BTC" in page.text_content("#previewBox"),
              page.text_content("#previewBox").replace("\n", " ")[:140])
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function("() => document.getElementById('cashBalance').textContent.includes('4.000.000')", timeout=5000)
        check("id-format: beli '1.000.000' tereksekusi, kas Rp4.000.000",
              "4.000.000" in cash_text(page), cash_text(page))
        # Jual ketik "0,00089286" (koma desimal, seperti tampilan holding)
        page.click("#tabSell")
        page.wait_for_timeout(300)
        page.fill("#amountInput", "0,00089286")
        page.wait_for_timeout(300)
        check("id-format: jual '0,00089286' pratinjau tampil, tanpa 'Koin tidak cukup'",
              page.is_visible("#previewBox") and page.is_hidden("#tradeError"),
              page.text_content("#tradeError") if page.is_visible("#tradeError") else "pratinjau tampil")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function("() => document.getElementById('cashBalance').textContent.includes('5.000.000')", timeout=5000)
        check("id-format: jual '0,00089286' tereksekusi, kas kembali Rp5.000.000",
              "5.000.000" in cash_text(page), cash_text(page))
        # Margin futures ketik "100.000"
        page.fill("#futMarginInput", "100.000")
        page.wait_for_timeout(300)
        fut_txt = page.text_content("#futPreview")
        check("id-format: margin '100.000' pratinjau margin Rp100.000 (bukan Rp100)",
              page.is_visible("#futPreview") and "Rp\u00a0100.000" in fut_txt,
              fut_txt.replace("\n", " ")[:160])
        check("id-format: margin '100.000' notional Rp1.000.000 (bukan Rp1.000)",
              "Rp\u00a01.000.000" in fut_txt, fut_txt.replace("\n", " ")[:160])
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_function("() => document.getElementById('cashBalance').textContent.includes('4.900.000')", timeout=5000)
        check("id-format: posisi Long dibuka margin Rp100.000, kas Rp4.900.000",
              "4.900.000" in cash_text(page), cash_text(page))
        # Tutup posisi, lalu desimal mikro "0.000000002" tetap dibaca
        # sebagai desimal (bukan 2 koin) — guard aturan ribuan.
        page.click("#futPositions [data-pos-id]")
        page.wait_for_function("() => document.getElementById('cashBalance').textContent.includes('5.000.000')", timeout=5000)
        page.click("#tabBuy")
        page.wait_for_timeout(300)
        page.fill("#amountInput", "10")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        page.click("#tabSell")
        page.wait_for_timeout(300)
        page.fill("#amountInput", "0.000000002")
        page.wait_for_timeout(300)
        check("id-format: jual mikro '0.000000002' pratinjau tampil (desimal, bukan 2 BTC)",
              page.is_visible("#previewBox") and "0,000000002" in page.text_content("#previewBox"),
              page.text_content("#previewBox").replace("\n", " ")[:140] if page.is_visible("#previewBox") else
              (page.text_content("#tradeError") if page.is_visible("#tradeError") else "pratinjau sembunyi"))
        check("0 error JS (id-format)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_id_rp_prefix(pw):
    """Input harus menerima awalan "Rp" seperti yang ditampilkan
    aplikasi ("Rp1.000.000" / "Rp100.000"). Pernah: ketik persis
    seperti tampilan -> parseAmount mengembalikan NaN, pratinjau
    diam-diam hilang TANPA pesan error apa pun (bukan error, bukan
    pratinjau). Harus: "Rp1.000.000", "Rp 100.000", "rp 500.000"
    terbaca benar; "Rp" saja tetap tidak valid."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Beli ketik "Rp1.000.000" (persis seperti tampilan aplikasi)
        page.fill("#amountInput", "Rp1.000.000")
        page.wait_for_timeout(300)
        check("rp-prefix: beli 'Rp1.000.000' pratinjau tampil Rp1.000.000",
              page.is_visible("#previewBox") and "1.000.000" in page.text_content("#previewBox"),
              page.text_content("#previewBox").replace("\n", " ")[:140] if page.is_visible("#previewBox") else
              (page.text_content("#tradeError") if page.is_visible("#tradeError") else "pratinjau sembunyi"))
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function("() => document.getElementById('cashBalance').textContent.includes('4.000.000')", timeout=5000)
        check("rp-prefix: beli 'Rp1.000.000' tereksekusi, kas Rp4.000.000",
              "4.000.000" in cash_text(page), cash_text(page))
        # Margin futures ketik "Rp 100.000" (spasi setelah Rp)
        page.fill("#futMarginInput", "Rp 100.000")
        page.wait_for_timeout(300)
        fut_txt = page.text_content("#futPreview")
        check("rp-prefix: margin 'Rp 100.000' pratinjau margin Rp100.000",
              page.is_visible("#futPreview") and "Rp\u00a0100.000" in fut_txt,
              fut_txt.replace("\n", " ")[:160])
        check("rp-prefix: margin 'Rp 100.000' notional Rp1.000.000",
              "Rp\u00a01.000.000" in fut_txt, fut_txt.replace("\n", " ")[:160])
        # Margin "rp 500.000" (huruf kecil) juga jalan
        page.fill("#futMarginInput", "rp 500.000")
        page.wait_for_timeout(300)
        fut_txt = page.text_content("#futPreview")
        check("rp-prefix: margin 'rp 500.000' pratinjau margin Rp500.000",
              page.is_visible("#futPreview") and "Rp\u00a0500.000" in fut_txt,
              fut_txt.replace("\n", " ")[:160])
        # "Rp" saja tetap tidak valid (bukan angka)
        page.fill("#futMarginInput", "Rp")
        page.wait_for_timeout(300)
        check("rp-prefix: margin 'Rp' saja tidak menampilkan pratinjau",
              page.is_hidden("#futPreview"),
              page.text_content("#futPreview").replace("\n", " ")[:80] if page.is_visible("#futPreview") else "pratinjau sembunyi")
        check("0 error JS (rp-prefix)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_enter_key(pw):
    """Enter di input jumlah spot / margin futures harus memicu tombol
    aksinya (Beli/Jual / Buka Long/Short). Pernah: ketik jumlah lalu
    tekan Enter tidak terjadi apa-apa — tidak ada keydown handler,
    berbeda dengan input nama profil yang sudah merespons Enter.
    Harus: Enter di #amountInput membuka konfirmasi beli; Enter di
    #futMarginInput membuka konfirmasi futures; Enter dengan input
    kosong menampilkan pesan "Masukkan ... dulu." (bukan diam)."""
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)

    def cg(route):
        if "simple/price" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(LIVE))
        elif "market_chart" in route.request.url:
            mock_chart(route)
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg)
    page.route("**/data-api.binance.vision/**", lambda r: r.abort())
    page.route("**/api.binance.com/**", lambda r: r.abort())
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Enter di input spot (jumlah valid) -> konfirmasi beli terbuka
        page.fill("#amountInput", "1000000")
        page.wait_for_timeout(300)
        check("enter-key: pratinjau beli tampil sebelum Enter",
              page.is_visible("#previewBox"))
        page.press("#amountInput", "Enter")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        check("enter-key: Enter di input spot membuka konfirmasi beli",
              page.is_visible("#confirmBox"))
        page.click("#confirmYes")
        page.wait_for_function("() => document.getElementById('cashBalance').textContent.includes('4.000.000')", timeout=5000)
        check("enter-key: beli via Enter tereksekusi, kas Rp4.000.000",
              "4.000.000" in cash_text(page), cash_text(page))
        # Enter di input margin futures -> konfirmasi futures terbuka
        page.fill("#futMarginInput", "100000")
        page.wait_for_timeout(300)
        check("enter-key: pratinjau futures tampil sebelum Enter",
              page.is_visible("#futPreview"))
        page.press("#futMarginInput", "Enter")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        check("enter-key: Enter di input margin membuka konfirmasi futures",
              page.is_visible("#futConfirmBox"))
        page.click("#futConfirmNo")
        # Enter dengan input kosong -> pesan, bukan diam
        page.fill("#amountInput", "")
        page.press("#amountInput", "Enter")
        page.wait_for_timeout(300)
        check("enter-key: Enter input spot kosong menampilkan 'Masukkan jumlah dulu.'",
              page.is_visible("#tradeError") and "Masukkan jumlah dulu." in page.text_content("#tradeError"),
              page.text_content("#tradeError") if page.is_visible("#tradeError") else "error sembunyi")
        page.fill("#futMarginInput", "")
        page.press("#futMarginInput", "Enter")
        page.wait_for_timeout(300)
        check("enter-key: Enter input margin kosong menampilkan 'Masukkan margin dulu.'",
              page.is_visible("#futError") and "Masukkan margin dulu" in page.text_content("#futError"),
              page.text_content("#futError") if page.is_visible("#futError") else "error sembunyi")
        check("0 error JS (enter-key)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_fut_error_no_repeat_scroll(pw):
    """Error futures yang sama tidak boleh mengguncang + scroll ulang.

    Pernah: showFutError() mengguncang + scrollIntoView di SETIAP
    panggilan, padahal updateFutPreview() dipanggil tiap renderAll
    (refresh harga 30 detik) dan tiap ketik di input margin. Saat
    offline dengan margin terisi, satu renderAll menarik halaman HP
    dari scrollY 0 ke 2004 dan scrollIntoView terpanggil lagi —
    user yang sedang membaca pasar ketarik ke bawah tiap 30 detik.
    Perbaikan: shake + scroll hanya bila pesannya BARU.
    """
    browser, ctx, page, errors = new_page(
        pw, {"width": 390, "height": 844}, "offline", {"live": {}})
    try:
        page.add_init_script(
            "window.__sivCount = 0;"
            "var _siv = Element.prototype.scrollIntoView;"
            "Element.prototype.scrollIntoView = function() {"
            "  window.__sivCount++; return _siv.apply(this, arguments); };")
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent.includes('CONTOH')",
            timeout=15000)
        page.fill("#futMarginInput", "100000")
        page.wait_for_selector("#futError:not([hidden])", timeout=5000)
        check("futerr: error offline tampil saat margin diisi (HP)",
              "Harga live tidak tersedia" in page.text_content("#futError"),
              page.text_content("#futError")[:90])
        page.wait_for_timeout(400)
        siv_after_fill = page.evaluate("() => window.__sivCount")
        check("futerr: error pertama mengguncang + scroll (umpan balik awal)",
              siv_after_fill >= 1 and page.evaluate(
                  "() => document.getElementById('futError').classList.contains('shake')"),
              f"siv={siv_after_fill}")
        # User scroll ke atas (lagi baca pasar), lalu render ulang
        # seperti refresh harga 30 detik.
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
        siv0 = page.evaluate("() => window.__sivCount")
        page.evaluate("() => renderAll()")
        page.wait_for_timeout(900)
        check("futerr: render ulang (refresh 30 detik) TIDAK memanggil scrollIntoView lagi",
              page.evaluate("() => window.__sivCount") == siv0,
              f"siv {siv0} -> {page.evaluate('() => window.__sivCount')}")
        check("futerr: halaman TIDAK ketarik ke bawah oleh render ulang",
              page.evaluate("() => window.scrollY") == 0,
              f"scrollY={page.evaluate('() => window.scrollY')}")
        # Ketik satu karakter lagi di margin (input event).
        page.type("#futMarginInput", "0", delay=50)
        page.wait_for_timeout(900)
        check("futerr: ketik di margin TIDAK memanggil scrollIntoView lagi",
              page.evaluate("() => window.__sivCount") == siv0,
              f"siv {siv0} -> {page.evaluate('() => window.__sivCount')}")
        check("futerr: error offline tetap tampil dengan pesan yang sama",
              page.is_visible("#futError") and
              "Harga live tidak tersedia" in page.text_content("#futError"),
              page.text_content("#futError")[:90])
        check("0 error JS (futerr)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()
    # Jalur tombol tetap memberi umpan balik: pesan BARU harus
    # mengguncang + scroll. Dicek di skenario LIVE (saat offline,
    # computeFutures selalu mengembalikan error offline sehingga
    # pesan "Masukkan margin dulu" tidak pernah muncul).
    browser2, ctx2, page2, errors2 = new_page(
        pw, {"width": 390, "height": 844}, "live", {"live": LIVE})
    try:
        page2.add_init_script(
            "window.__sivCount = 0;"
            "var _siv = Element.prototype.scrollIntoView;"
            "Element.prototype.scrollIntoView = function() {"
            "  window.__sivCount++; return _siv.apply(this, arguments); };")
        enter_guest(page2)
        page2.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page2.wait_for_timeout(400)
        siv_before = page2.evaluate("() => window.__sivCount")
        page2.click("#futBtn")
        page2.wait_for_timeout(500)
        check("futerr: klik tombol + pesan baru tetap mengguncang + scroll",
              page2.evaluate("() => window.__sivCount") > siv_before and page2.evaluate(
                  "() => document.getElementById('futError').classList.contains('shake')") and
              "Masukkan margin dulu" in page2.text_content("#futError"),
              f"siv={page2.evaluate('() => window.__sivCount')}")
        check("0 error JS (futerr-live)", len(errors2) == 0, "; ".join(errors2[:3]))
    finally:
        browser2.close()

def test_trades_cap(pw):
    """Regresi: riwayat trade dibatasi 200 entri terakhir (MAX_TRADES).
    Pernah: state.trades tak terbatas — 600 trade -> 600 baris di DOM,
    renderAll() 98,6 ms (median) di tiap refresh 30 detik, store 59 KB
    dan terus membesar tanpa batas."""
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function("() => document.getElementById('priceBadgeText').textContent.includes('HARGA LIVE')", timeout=10000)
        # Seed 250 trade (melebihi batas 200) dengan total khas per entri.
        page.evaluate("""(n) => {
          var s = JSON.parse(localStorage.getItem('simulasi-trading-v2'));
          var p = s.profiles[0];
          var now = Date.now();
          p.trades = [];
          for (var i = 0; i < n; i++) {
            p.trades.push({type: 'buy', symbol: 'BTC', amount: 0.001,
              price: 1120000000, total: 1000 + i, t: now - (n - i) * 60000});
          }
          localStorage.setItem('simulasi-trading-v2', JSON.stringify(s));
        }""", 250)
        page.reload()
        page.wait_for_function("() => !document.getElementById('profileWrap').hidden", timeout=5000)
        page.wait_for_selector(".history-row", timeout=10000)
        def stored_trades():
            return page.evaluate("""() => {
              var s = JSON.parse(localStorage.getItem('simulasi-trading-v2') || 'null');
              var p = s.profiles.find(x => x.id === s.activeProfileId);
              return p ? p.trades : null;
            }""")
        check("trades-cap: hanya 200 baris riwayat di-render dari 250 seed",
              page.locator(".history-row").count() == 200,
              str(page.locator(".history-row").count()))
        st = stored_trades()
        check("trades-cap: riwayat tersimpan dipangkas jadi 200 entri",
              st and len(st) == 200, str(len(st) if st else None))
        check("trades-cap: entri tertua yang tersisa adalah seed ke-51 (total 1050), seed awal terbuang",
              st and st[0]["total"] == 1050 and st[-1]["total"] == 1249,
              "oldest=%s newest=%s" % (st[0]["total"] if st else None, st[-1]["total"] if st else None))
        # Satu trade sungguhan: jumlah baris + entri tersimpan TETAP 200,
        # baris teratas adalah BELI yang baru.
        page.click("#tabBuy")
        page.fill("#amountInput", "10000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(800)
        check("trades-cap: setelah trade baru, baris riwayat tetap 200",
              page.locator(".history-row").count() == 200,
              str(page.locator(".history-row").count()))
        st2 = stored_trades()
        check("trades-cap: setelah trade baru, entri tersimpan tetap 200",
              st2 and len(st2) == 200, str(len(st2) if st2 else None))
        check("trades-cap: baris teratas adalah BELI baru Rp10.000",
              "BELI BTC" in page.locator(".history-row").first.inner_text() and
              "10.000" in page.locator(".history-row").first.inner_text(),
              page.locator(".history-row").first.inner_text()[:80])
        check("0 error JS (trades-cap)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_market_row_no_focus_jump(pw):
    """Regresi: ketuk baris pasar di HP TIDAK melempar fokus/scroll.
    Pernah: klik baris pasar memanggil amountInput.focus() — di HP
    (390x844) panel Spot ada jauh di bawah daftar pasar sehingga
    halaman melonjak scrollY 0 -> 1414 dan keyboard terbuka; user
    yang cuma mau ganti koin tiba-tiba "dilempar" ke panel trade."""
    browser, ctx, page, errors = new_page(pw, {"width": 390, "height": 844}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function("() => document.getElementById('priceBadgeText').textContent.includes('HARGA LIVE')", timeout=10000)
        page.wait_for_timeout(500)
        # Gulir manual sampai baris ETH terlihat (seperti user sungguhan),
        # lalu klik via JS — page.click() ikut menggulir sendiri sehingga
        # tidak bisa dipakai untuk mengukur guliran yang dibuat aplikasi.
        page.evaluate("document.querySelector('.market-row:nth-child(2)').scrollIntoView({block: 'center'})")
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.wait_for_timeout(200)
        y0 = page.evaluate("window.scrollY")
        check("market-focus: sebelum klik, halaman di posisi baris ETH",
              y0 > 0, "scrollY=" + str(y0))
        page.evaluate("document.querySelector('.market-row:nth-child(2)').click()")
        page.wait_for_timeout(600)
        check("market-focus: koin berganti ke ETH",
              page.text_content("#tradeSymbol") == "ETH",
              page.text_content("#tradeSymbol"))
        check("market-focus: fokus TIDAK pindah ke input jumlah",
              page.evaluate("document.activeElement && document.activeElement.id") != "amountInput",
              page.evaluate("document.activeElement && document.activeElement.id"))
        check("market-focus: halaman TIDAK ketarik ke bawah oleh aplikasi",
              page.evaluate("window.scrollY") == y0,
              "scrollY %s -> %s" % (y0, page.evaluate("window.scrollY")))
        check("0 error JS (market-focus)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_welcome_no_autofocus_mobile(pw):
    """Regresi: layar sambutan TIDAK auto-focus ke input nama di HP.
    Pernah: setTimeout(...guestNameInput.focus(), 100) di semua
    perangkat — di HP (touch) keyboard virtual langsung terbuka
    begitu halaman pertama dibuka, menutupi kartu sambutan sebelum
    user memilih mengetik. Di desktop (mouse/keyboard) fokus
    otomatis tetap nyaman dan dipertahankan."""
    browser, ctx, page, errors = new_page(pw, {"width": 390, "height": 844}, "live", {"live": dict(LIVE)}, touch=True)
    try:
        page.goto(BASE)
        page.wait_for_selector("#welcomeOverlay:not([hidden])", timeout=10000)
        page.wait_for_timeout(500)  # lewati setTimeout focus 100ms
        check("welcome-focus: HP touch TIDAK auto-focus ke input nama",
              page.evaluate("document.activeElement && document.activeElement.id") != "guestNameInput",
              page.evaluate("document.activeElement && document.activeElement.id"))
        check("welcome-focus: overlay sambutan tetap terlihat",
              page.evaluate("!document.getElementById('welcomeOverlay').hidden"))
        # User tetap bisa mengetuk input sendiri lalu masuk sebagai Guest
        page.click("#guestNameInput")
        page.wait_for_timeout(200)
        check("welcome-focus: ketuk manual tetap memfokuskan input nama",
              page.evaluate("document.activeElement && document.activeElement.id") == "guestNameInput")
        page.click("#guestEnterBtn")
        page.wait_for_function("() => document.getElementById('welcomeOverlay').hidden", timeout=5000)
        check("welcome-focus: masuk Guest tetap jalan setelah perbaikan",
              page.evaluate("document.getElementById('welcomeOverlay').hidden"))
        check("0 error JS (welcome-focus, mobile)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()
    # Desktop: fokus otomatis DIPERTAHANKAN (nyaman, ada keyboard fisik)
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        page.goto(BASE)
        page.wait_for_selector("#welcomeOverlay:not([hidden])", timeout=10000)
        page.wait_for_timeout(500)
        check("welcome-focus: desktop tetap auto-focus ke input nama",
              page.evaluate("document.activeElement && document.activeElement.id") == "guestNameInput",
              page.evaluate("document.activeElement && document.activeElement.id"))
        check("0 error JS (welcome-focus, desktop)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_welcome_behind_overlay(pw):
    """Regresi: interaksi panel trade SEBELUM masuk Guest tidak crash.

    Pernah: layar sambutan menutupi halaman tapi elemen di belakangnya
    tetap bisa difokus lewat keyboard (Tab) — ketik jumlah spot /
    margin, klik Beli / Buka Long / chip cepat / Reset 2x semuanya
    membaca state.cash saat state masih null -> TypeError
    "Cannot read properties of null (reading 'cash')" di console
    tiap ketikan. Perbaikan: computeTrade/computeFutures menolak
    dengan sopan bila !state, holdingsAmount/doReset/quickRow dijaga.
    """
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        page.goto(BASE)
        page.wait_for_selector("#welcomeOverlay:not([hidden])", timeout=10000)
        page.wait_for_function("() => document.getElementById('priceBadgeText').textContent.includes('HARGA LIVE')", timeout=15000)
        check("welcome-behind: overlay tampil + harga LIVE (state null)",
              page.evaluate("!document.getElementById('welcomeOverlay').hidden"))
        page.focus("#amountInput")
        page.keyboard.type("1000000", delay=10)
        page.wait_for_timeout(400)
        check("welcome-behind: ketik Rp1.000.000 di input spot tanpa error JS",
              len(errors) == 0, "; ".join(errors[:2]))
        check("welcome-behind: pesan 'Masuk sebagai Guest' tampil, bukan crash",
              page.evaluate("!document.getElementById('tradeError').hidden") and
              "Guest" in page.text_content("#tradeError"),
              page.text_content("#tradeError"))
        page.evaluate("() => document.getElementById('tradeBtn').click()")
        page.wait_for_timeout(300)
        check("welcome-behind: klik Beli tanpa error JS", len(errors) == 0, "; ".join(errors[:2]))
        page.evaluate("() => document.querySelector('#quickRow [data-pct=\"25\"]').click()")
        page.wait_for_timeout(300)
        check("welcome-behind: klik chip 25% tanpa error JS", len(errors) == 0, "; ".join(errors[:2]))
        page.focus("#futMarginInput")
        page.keyboard.type("100000", delay=10)
        page.wait_for_timeout(400)
        check("welcome-behind: ketik margin tanpa error JS", len(errors) == 0, "; ".join(errors[:2]))
        page.evaluate("() => document.getElementById('futBtn').click()")
        page.wait_for_timeout(300)
        check("welcome-behind: klik Buka Long tanpa error JS", len(errors) == 0, "; ".join(errors[:2]))
        page.evaluate("() => document.getElementById('resetBtn').click()")
        page.wait_for_timeout(200)
        page.evaluate("() => document.getElementById('resetBtn').click()")
        page.wait_for_timeout(300)
        check("welcome-behind: klik Reset 2x tanpa error JS", len(errors) == 0, "; ".join(errors[:2]))
        page.click("#guestEnterBtn")
        page.wait_for_function("() => document.getElementById('welcomeOverlay').hidden", timeout=5000)
        check("welcome-behind: masuk Guest tetap jalan, kas Rp5.000.000",
              "5.000.000" in cash_text(page), cash_text(page))
        check("0 error JS (welcome-behind)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_double_enter_profile(pw):
    """Regresi: Enter ganda di input nama TIDAK membuat 2 profil.

    Pernah: Enter kedua masih sampai ke input (fokus tidak pindah
    saat overlay/menu menutup) sehingga satu Enter ganda di layar
    sambutan membuat 2 profil Guest, dan Enter ganda di Buat Profil
    membuat profil ketiga. Perbaikan: handler guestEnterBtn abaikan
    klik bila overlay sudah tersembunyi; handler createProfileBtn
    abaikan klik bila menu sudah tertutup.
    """
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        page.goto(BASE)
        page.wait_for_selector("#welcomeOverlay:not([hidden])", timeout=10000)
        page.fill("#guestNameInput", "Bray")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        n = page.evaluate("JSON.parse(localStorage.getItem('simulasi-trading-v2')||'{}').profiles.length")
        check("double-enter: Enter ganda Guest -> 1 profil", n == 1, f"profil={n}")
        check("double-enter: overlay tersembunyi setelah masuk",
              page.evaluate("document.getElementById('welcomeOverlay').hidden"))
        page.click("#profileBtn")
        page.wait_for_selector("#newProfileName", timeout=5000)
        page.fill("#newProfileName", "Kedua")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        n = page.evaluate("JSON.parse(localStorage.getItem('simulasi-trading-v2')||'{}').profiles.length")
        check("double-enter: Enter ganda Buat Profil -> total 2 profil", n == 2, f"profil={n}")
        check("double-enter: kas profil aktif tetap Rp5.000.000",
              "5.000.000" in cash_text(page), cash_text(page))
        check("0 error JS (double-enter)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()
    # Double-click tombol Masuk Guest (konteks baru = localStorage kosong)
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        page.goto(BASE)
        page.wait_for_selector("#welcomeOverlay:not([hidden])", timeout=10000)
        page.fill("#guestNameInput", "Bray2")
        page.click("#guestEnterBtn", click_count=2)
        page.wait_for_timeout(400)
        n = page.evaluate("JSON.parse(localStorage.getItem('simulasi-trading-v2')||'{}').profiles.length")
        check("double-enter: klik ganda Masuk Guest -> 1 profil", n == 1, f"profil={n}")
        check("0 error JS (double-enter, klik ganda)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_pending_cleared_on_hide(pw):
    """Regresi: menutup kotak konfirmasi MEMBATALKAN pending-nya.
    Pernah: konfirmasi beli dibuka lalu ganti tab Beli/Jual, ketik
    ulang jumlah, atau klik tombol cepat — kotak tersembunyi tapi
    _pendingTrade tetap set; begitu juga _pendingFut saat ganti arah
    Long/Short, ganti leverage (slider/chip), atau ketik ulang
    margin. Hari ini pending basi tidak bisa dieksekusi lewat UI,
    tapi invarian "kotak tersembunyi <=> tidak ada pending" harus
    benar di semua situs hideConfirm()/hideFutConfirm()."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        def pending():
            return page.evaluate("() => ({ trade: !!window._pendingTrade, fut: !!window._pendingFut })")
        def open_trade_confirm():
            page.fill("#amountInput", "1000000")
            page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
            page.click("#tradeBtn")
            page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        def open_fut_confirm():
            page.fill("#futMarginInput", "100000")
            page.wait_for_selector("#futPreview:not([hidden])", timeout=5000)
            page.click("#futBtn")
            page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        # 1. Ganti tab Beli -> Jual
        open_trade_confirm()
        check("pending-hide: pending trade ada setelah Beli", pending()["trade"])
        page.click("#tabSell")
        page.wait_for_timeout(300)
        check("pending-hide: ganti tab Jual -> pending trade dinolkan",
              not pending()["trade"], str(pending()))
        check("pending-hide: ganti tab -> kotak konfirmasi tersembunyi",
              page.evaluate("() => document.getElementById('confirmBox').hidden"))
        # 2. Ketik ulang jumlah
        page.click("#tabBuy")
        open_trade_confirm()
        page.fill("#amountInput", "500000")
        page.wait_for_timeout(300)
        check("pending-hide: ketik ulang jumlah -> pending trade dinolkan",
              not pending()["trade"], str(pending()))
        # 3. Klik tombol cepat 25%
        open_trade_confirm()
        page.click('.quick-btn[data-pct="25"], #quickRow [data-pct="25"]')
        page.wait_for_timeout(300)
        check("pending-hide: klik tombol cepat -> pending trade dinolkan",
              not pending()["trade"], str(pending()))
        # 4. Ganti arah Long -> Short
        page.click("#futLong")
        open_fut_confirm()
        check("pending-hide: pending futures ada setelah Buka Long", pending()["fut"])
        page.click("#futShort")
        page.wait_for_timeout(300)
        check("pending-hide: ganti arah Short -> pending futures dinolkan",
              not pending()["fut"], str(pending()))
        # 5. Ubah leverage via chip
        page.click("#futLong")
        open_fut_confirm()
        page.click('.lev-chip[data-lev="25"]')
        page.wait_for_timeout(300)
        check("pending-hide: chip leverage 25x -> pending futures dinolkan",
              not pending()["fut"], str(pending()))
        # 6. Ketik ulang margin
        open_fut_confirm()
        page.fill("#futMarginInput", "50000")
        page.wait_for_timeout(300)
        check("pending-hide: ketik ulang margin -> pending futures dinolkan",
              not pending()["fut"], str(pending()))
        # Alur normal tetap jalan: konfirmasi Ya mengeksekusi trade
        open_trade_confirm()
        page.click("#confirmYes")
        page.wait_for_timeout(500)
        check("pending-hide: konfirmasi Ya tetap mengeksekusi beli",
              "4.000.000" in cash_text(page), cash_text(page))
        check("pending-hide: setelah eksekusi, pending trade null",
              not pending()["trade"], str(pending()))
        check("0 error JS (pending-hide)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def route_page(page, scenario, price_state):
    """Daftarkan mock harga yang sama seperti new_page(), untuk halaman
    TAMBAHAN dalam context yang sama. page.route() berlaku per-halaman,
    bukan per-context — tanpa ini tab kedua tidak mendapat mock dan
    jatuh ke harga contoh (fetch asli diblokir tunnel VM)."""
    import urllib.parse

    def cg_handler(route):
        if scenario in ("offline", "binance"):
            route.abort()
        else:
            url = route.request.url
            if "simple/price" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(price_state["live"]))
            elif "market_chart" in url:
                mock_chart(route)
            else:
                route.abort()

    def bin_handler(route):
        if scenario == "offline":
            route.abort()
        elif scenario == "binance":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query)
            syms = json.loads(q.get("symbols", ["[]"])[0])
            out = [{"symbol": s, "lastPrice": str(BINANCE_USDT[s]),
                    "priceChangePercent": str(BINANCE_CHG[s])} for s in syms]
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(out))
        else:
            route.abort()

    page.route("**/api.coingecko.com/**", cg_handler)
    page.route("**/data-api.binance.vision/**", bin_handler)
    page.route("**/api.binance.com/**", bin_handler)

def test_multitab_sync(pw):
    """Regresi: dua tab berbagi localStorage — tab yang trade di tab lain
    tidak boleh ditimpa oleh tab basi. Pernah: tab A beli BTC, tab B jual
    habis, tab A beli ETH tanpa reload -> localStorage jadi [beli BTC,
    beli ETH] (jual B hilang) dan holding BTC "bangkit" lagi, karena tab
    A menyimpan salinan state basi lewat saveStore(). Perbaikan: event
    `storage` memuat ulang store + state di tab lain begitu data berubah."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, pageA, errorsA = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(pageA)
        pageA.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Tab A: beli BTC Rp1.000.000
        pageA.fill("#amountInput", "1000000")
        pageA.click("#tradeBtn")
        pageA.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        pageA.click("#confirmYes")
        pageA.wait_for_function("() => document.getElementById('confirmBox').hidden", timeout=5000)
        check("multitab: tab A beli BTC, kas Rp4.000.000",
              "4.000.000" in cash_text(pageA), cash_text(pageA))
        # Tab B: tab baru di CONTEXT yang sama (localStorage bersama)
        pageB = ctx.new_page()
        errorsB = []
        pageB.on("pageerror", lambda e: errorsB.append(str(e)))
        pageB.on("console", lambda m: errorsB.append("console." + m.type + ": " + m.text)
                 if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
        route_page(pageB, "live", price_state)
        pageB.goto(BASE)
        pageB.wait_for_function("() => !document.getElementById('profileWrap').hidden", timeout=10000)
        pageB.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        check("multitab: tab B (load baru) melihat holding BTC dari A",
              "BTC" in (pageB.text_content("#holdingsList") or ""),
              pageB.text_content("#holdingsList"))
        # Tab B: jual semua BTC
        pageB.click("#tabSell")
        pageB.fill("#amountInput", "0,00089286")
        pageB.click("#tradeBtn")
        pageB.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        pageB.click("#confirmYes")
        pageB.wait_for_function("() => document.getElementById('confirmBox').hidden", timeout=5000)
        check("multitab: tab B jual habis, kas kembali Rp5.000.000",
              "5.000.000" in cash_text(pageB), cash_text(pageB))
        # Tab A harus ikut sinkron OTOMATIS (event storage) tanpa reload
        pageA.bring_to_front()
        pageA.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('5.000.000')",
            timeout=5000)
        check("multitab: tab A ikut sinkron — kas jadi Rp5.000.000 tanpa reload",
              "5.000.000" in cash_text(pageA), cash_text(pageA))
        check("multitab: tab A ikut sinkron — holding BTC hilang",
              "BTC" not in (pageA.text_content("#holdingsList") or ""),
              pageA.text_content("#holdingsList"))
        # Tab A: beli ETH Rp500.000 — jual B tidak boleh hilang
        pageA.evaluate("() => { document.querySelectorAll('.market-row')[1].click(); }")
        pageA.wait_for_function(
            "() => document.getElementById('tradeSymbol').textContent === 'ETH'", timeout=5000)
        pageA.fill("#amountInput", "500000")
        pageA.click("#tradeBtn")
        pageA.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        pageA.click("#confirmYes")
        pageA.wait_for_function("() => document.getElementById('confirmBox').hidden", timeout=5000)
        store = pageA.evaluate("() => JSON.parse(localStorage.getItem('simulasi-trading-v2'))")
        prof = store["profiles"][0]
        kinds = [(t.get("type"), t.get("symbol")) for t in prof["trades"]]
        check("multitab: setelah trade A, jual B tetap tercatat (3 trade)",
              len(prof["trades"]) == 3 and ("sell", "BTC") in kinds, str(kinds))
        check("multitab: setelah trade A, holding BTC tetap tidak ada",
              "BTC" not in prof.get("holdings", {}), str(prof.get("holdings")))
        check("multitab: setelah trade A, holding ETH ada",
              "ETH" in prof.get("holdings", {}), str(prof.get("holdings")))
        check("0 error JS (multitab, tab A)", len(errorsA) == 0, "; ".join(errorsA[:3]))
        check("0 error JS (multitab, tab B)", len(errorsB) == 0, "; ".join(errorsB[:3]))
        pageB.close()
    finally:
        browser.close()

def test_quick_zero_feedback(pw):
    """Regresi: tombol cepat memberi umpan balik saat tidak ada yang
    bisa dijual/dibeli. Pernah: mode Jual tanpa holding, klik 25% /
    Maks -> input "" tanpa pratinjau dan tanpa pesan apa pun (tombol
    terasa mati); mode Beli saat kas Rp0, klik 25% / Maks -> input
    "0" juga tanpa pratinjau dan tanpa pesan. Padahal klik tombol
    Beli/Jual dengan input kosong menampilkan "Masukkan jumlah dulu."
    — tombol cepat harus memberi tahu kenapa tidak ada yang bisa
    dibeli/dijual."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        def err_visible():
            return page.evaluate(
                "() => !document.getElementById('tradeError').hidden")
        # 1. Jual tanpa holding: 25% dan Maks harus menampilkan pesan
        page.click("#tabSell")
        page.click('#quickRow [data-pct="25"]')
        page.wait_for_timeout(300)
        check("quick-zero: Jual 25% tanpa holding -> pesan error tampil",
              err_visible(), page.text_content("#tradeError"))
        check("quick-zero: pesannya menyebut belum punya BTC",
              "belum punya BTC" in page.text_content("#tradeError"),
              page.text_content("#tradeError"))
        check("quick-zero: pratinjau tetap tersembunyi",
              page.is_hidden("#previewBox"))
        page.click('#quickRow [data-pct="100"]')
        page.wait_for_timeout(300)
        check("quick-zero: Jual Maks tanpa holding -> pesan error tampil",
              err_visible(), page.text_content("#tradeError"))
        # 2. Beli semua kas, lalu tombol cepat Beli saat kas Rp0
        page.click("#tabBuy")
        page.fill("#amountInput", "5000000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(500)
        check("quick-zero: kas habis setelah beli semua",
              "Rp\u00a00" in cash_text(page), cash_text(page))
        page.click('#quickRow [data-pct="25"]')
        page.wait_for_timeout(300)
        check("quick-zero: Beli 25% saat kas Rp0 -> pesan error tampil",
              err_visible(), page.text_content("#tradeError"))
        check("quick-zero: pesannya menyebut kas tersedia Rp0",
              "kas tersedia: Rp" in page.text_content("#tradeError") and
              "Rp\u00a00" in page.text_content("#tradeError"),
              page.text_content("#tradeError"))
        check("quick-zero: input dikosongkan (bukan '0')",
              page.input_value("#amountInput") == "",
              repr(page.input_value("#amountInput")))
        # 3. Kontrol: tombol cepat normal tetap jalan (jual 25% dari holding)
        page.click("#tabSell")
        page.click('#quickRow [data-pct="25"]')
        page.wait_for_timeout(300)
        check("quick-zero: Jual 25% dengan holding -> pratinjau tampil",
              not page.is_hidden("#previewBox"),
              page.text_content("#previewBox")[:120])
        check("quick-zero: Jual 25% dengan holding -> tanpa error",
              page.is_hidden("#tradeError"))
        check("0 error JS (quick-zero)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_invalid_input(pw):
    """Regresi: input tidak valid memberi pesan, bukan diam. Pernah:
    ketik "Rp" saja / "abc" / "1.2.3" di input jumlah spot -> pratinjau
    hilang tanpa pesan apa pun, dan klik Beli malah menampilkan
    "Masukkan jumlah dulu." yang menyesatkan (user sudah mengetik).
    Sama di input margin futures ("Rp" -> diam, klik Buka ->
    "Masukkan margin dulu."). Input kosong tetap diam (tanpa error)."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        def err():
            return page.text_content("#tradeError")
        def err_vis():
            return page.evaluate(
                "() => !document.getElementById('tradeError').hidden")
        def fut_err():
            return page.text_content("#futError")
        def fut_err_vis():
            return page.evaluate(
                "() => !document.getElementById('futError').hidden")
        # 1. Spot: "Rp" saja -> pesan "tidak valid", pratinjau tersembunyi
        page.fill("#amountInput", "Rp")
        page.wait_for_timeout(300)
        check("invalid-input: ketik 'Rp' -> pesan error tampil",
              err_vis(), err())
        check("invalid-input: pesannya menyebut tidak valid",
              "tidak valid" in err(), err())
        check("invalid-input: pratinjau tetap tersembunyi",
              page.is_hidden("#previewBox"))
        # 2. Spot: "abc" dan "1.2.3" juga berpesan
        for txt in ("abc", "1.2.3"):
            page.fill("#amountInput", txt)
            page.wait_for_timeout(200)
            check("invalid-input: ketik %r -> pesan tidak valid" % txt,
                  err_vis() and "tidak valid" in err(), err())
        # 3. Klik Beli dengan input tidak valid -> bukan "Masukkan jumlah dulu."
        page.fill("#amountInput", "abc")
        page.click("#tradeBtn")
        page.wait_for_timeout(200)
        check("invalid-input: klik Beli 'abc' -> pesan tidak valid, bukan 'Masukkan jumlah dulu.'",
              "tidak valid" in err() and "Masukkan jumlah dulu" not in err(), err())
        check("invalid-input: kotak konfirmasi tidak muncul",
              page.is_hidden("#confirmBox"))
        # 4. Kontrol: input kosong tetap diam (tanpa error)
        page.fill("#amountInput", "")
        page.wait_for_timeout(200)
        check("invalid-input: input kosong -> tanpa error",
              page.is_hidden("#tradeError"))
        # 5. Kontrol: input valid tetap jalan
        page.fill("#amountInput", "100000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        check("invalid-input: input valid '100000' -> pratinjau tampil",
              not page.is_hidden("#previewBox"))
        check("invalid-input: input valid -> tanpa error",
              page.is_hidden("#tradeError"))
        # 6. Futures: "Rp" saja di margin -> pesan "Margin tidak valid"
        page.fill("#futMarginInput", "Rp")
        page.wait_for_timeout(300)
        check("invalid-input: margin 'Rp' -> pesan error tampil",
              fut_err_vis(), fut_err())
        check("invalid-input: pesannya menyebut Margin tidak valid",
              "Margin tidak valid" in fut_err(), fut_err())
        check("invalid-input: pratinjau futures tersembunyi",
              page.is_hidden("#futPreview"))
        # 7. Klik Buka dengan margin tidak valid -> bukan "Masukkan margin dulu"
        page.click("#futBtn")
        page.wait_for_timeout(200)
        check("invalid-input: klik Buka margin 'Rp' -> pesan tidak valid",
              "Margin tidak valid" in fut_err(), fut_err())
        check("invalid-input: kotak konfirmasi futures tidak muncul",
              page.is_hidden("#futConfirmBox"))
        # 8. Kontrol futures: margin kosong diam, margin valid jalan
        page.fill("#futMarginInput", "")
        page.wait_for_timeout(200)
        check("invalid-input: margin kosong -> tanpa error",
              page.is_hidden("#futError"))
        page.fill("#futMarginInput", "100000")
        page.wait_for_selector("#futPreview:not([hidden])", timeout=5000)
        check("invalid-input: margin valid '100000' -> pratinjau tampil",
              not page.is_hidden("#futPreview"))
        check("0 error JS (invalid-input)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    srv = start_server()
    try:
        with sync_playwright() as pw:
            if which in ("live", "all"):
                test_live(pw)
                test_mobile_live(pw)
                test_sell_max(pw)
                test_tab_switch_clears_input(pw)
                test_profile_name_escaped(pw)
                test_overlapping_confirms(pw)
                test_id_number_format(pw)
                test_id_rp_prefix(pw)
                test_enter_key(pw)
            if which in ("resetarmed", "all"):
                test_reset_armed_profile_switch(pw)
            if which in ("profilectx", "all"):
                test_profile_switch_clears_trade_context(pw)
            if which in ("microsell", "all"):
                test_micro_sell_quick(pw)
            if which in ("offline", "all"):
                test_offline(pw)
                test_spot_offline_blocked(pw)
            if which in ("binance", "all"):
                test_binance(pw)
            if which in ("history", "all"):
                test_offline_history(pw)
            if which in ("value", "all"):
                test_spot_offline_frozen_value(pw)
            if which in ("race", "all"):
                test_fetch_race(pw)
            if which in ("reload", "all"):
                test_reload_offline_close(pw)
            if which in ("chart429", "all"):
                test_chart_429(pw)
            if which in ("chartmark", "all"):
                test_chart_mark_offline(pw)
            if which in ("partial", "all"):
                test_partial_coingecko(pw)
            if which in ("stale", "all"):
                test_stale_confirm(pw)
            if which in ("panelmark", "all"):
                test_panel_mark_offline(pw)
            if which in ("futerr", "all"):
                test_fut_error_no_repeat_scroll(pw)
            if which in ("tradescap", "all"):
                test_trades_cap(pw)
            if which in ("marketfocus", "all"):
                test_market_row_no_focus_jump(pw)
            if which in ("coinctx", "all"):
                test_coin_switch_clears_trade_context(pw)
            if which in ("pendinghide", "all"):
                test_pending_cleared_on_hide(pw)
            if which in ("multitab", "all"):
                test_multitab_sync(pw)
            if which in ("welcomefocus", "all"):
                test_welcome_no_autofocus_mobile(pw)
                test_welcome_behind_overlay(pw)
                test_double_enter_profile(pw)
            if which in ("quickzero", "all"):
                test_quick_zero_feedback(pw)
            if which in ("invalidinput", "all"):
                test_invalid_input(pw)
    finally:
        srv.shutdown()
    failed = [r for r in results if not r["ok"]]
    print(f"\n=== RINGKASAN: {len(results)-len(failed)}/{len(results)} lolos, {len(failed)} gagal ===")
    for r in failed:
        print("GAGAL:", r["name"], "—", r["detail"])
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
