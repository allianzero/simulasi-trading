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
            if which in ("binance", "all"):
                test_binance(pw)
            if which in ("history", "all"):
                test_offline_history(pw)
    finally:
        srv.shutdown()
    failed = [r for r in results if not r["ok"]]
    print(f"\n=== RINGKASAN: {len(results)-len(failed)}/{len(results)} lolos, {len(failed)} gagal ===")
    for r in failed:
        print("GAGAL:", r["name"], "—", r["detail"])
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
