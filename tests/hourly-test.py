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

def new_page(pw, viewport, scenario, price_state):
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport=viewport)
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
        check("offline: harga BTC = harga contoh 1,5 Miliar",
              "1.500.000.000" in page.text_content("#tradePrice"), page.text_content("#tradePrice"))
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

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    srv = start_server()
    try:
        with sync_playwright() as pw:
            if which in ("live", "all"):
                test_live(pw)
                test_mobile_live(pw)
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
    finally:
        srv.shutdown()
    failed = [r for r in results if not r["ok"]]
    print(f"\n=== RINGKASAN: {len(results)-len(failed)}/{len(results)} lolos, {len(failed)} gagal ===")
    for r in failed:
        print("GAGAL:", r["name"], "—", r["detail"])
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
