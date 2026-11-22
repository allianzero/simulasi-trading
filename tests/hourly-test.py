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

def test_lev_chips_narrow(pw):
    # Chip leverage di layar sangat sempit (320px): 5 chip dengan lebar
    # alami butuh ~298px sementara lebar konten kartu ~252px, sehingga
    # chip 100x terpotong 12px di luar layar (bodySW 332) dan tidak bisa
    # diklik penuh — overflow-x:hidden menyembunyikan sisanya.
    price_state = {"live": dict(LIVE)}
    for w in (320, 360):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": 844}, "live", price_state, touch=True)
        try:
            enter_guest(page)
            page.wait_for_timeout(600)
            m = page.evaluate("() => ({chipsRight: Math.round(document.getElementById('levChips').getBoundingClientRect().right), "
                              "vw: window.innerWidth, bodySW: document.body.scrollWidth})")
            check(f"chip leverage {w}px: baris chip di dalam viewport (kanan <= {w})",
                  m["chipsRight"] <= m["vw"], str(m))
            check(f"chip leverage {w}px: body tanpa overflow horizontal",
                  m["bodySW"] <= m["vw"], str(m))
            last = page.locator('.lev-chip[data-lev="100"]')
            box = last.bounding_box()
            check(f"chip leverage {w}px: chip 100x seluruhnya terlihat",
                  box is not None and box["x"] + box["width"] <= w + 1, str(box))
            last.click()
            check(f"chip leverage {w}px: chip 100x bisa diklik (label 100x)",
                  page.text_content("#futLevLabel") == "100x")
            page.fill("#futMarginInput", "100000")
            page.click("#futBtn")
            page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
            page.click("#futConfirmYes")
            page.wait_for_timeout(400)
            check(f"chip leverage {w}px: posisi Long 100x terbuka",
                  "100x" in page.text_content("#futPositions"))
            check(f"0 error JS (chip leverage {w}px)", len(errors) == 0, "; ".join(errors[:3]))
        finally:
            browser.close()

def test_topbar_offline_narrow(pw):
    # Topbar offline di layar sangat sempit (320/360px): badge offline
    # "HARGA CONTOH (OFFLINE)" 198px + Refresh 99px + avatar profil 40px
    # = 352px, sementara lebar konten cuma 288px (320px) / 328px (360px).
    # .top-actions punya flex-shrink:0 sehingga tidak mengecil — tombol
    # profil jatuh di x 328-368 (di luar viewport, bodySW 368) sehingga
    # tidak terlihat dan tidak bisa diketik, padahal overflow-x:hidden
    # menyembunyikan sisanya. Saat live (badge 109px) baris muat.
    price_state = {"live": dict(LIVE)}
    for w in (320, 360):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": 844}, "offline", price_state, touch=True)
        try:
            enter_guest(page)
            page.wait_for_function(
                "() => document.getElementById('priceBadgeText').textContent.includes('CONTOH')",
                timeout=15000)
            page.wait_for_timeout(400)
            m = page.evaluate("() => ({bodySW: document.body.scrollWidth, vw: window.innerWidth, "
                              "prof: (() => { const b = document.getElementById('profileBtn').getBoundingClientRect(); return {x: Math.round(b.left), right: Math.round(b.right)}; })(), "
                              "ref: (() => { const b = document.getElementById('refreshBtn').getBoundingClientRect(); return {right: Math.round(b.right)}; })()})")
            check(f"topbar offline {w}px: body tanpa overflow horizontal",
                  m["bodySW"] <= m["vw"], str(m))
            check(f"topbar offline {w}px: tombol profil di dalam viewport (kanan <= {w})",
                  m["prof"]["right"] <= w, str(m["prof"]))
            check(f"topbar offline {w}px: tombol Refresh di dalam viewport",
                  m["ref"]["right"] <= w, str(m["ref"]))
            page.click("#profileBtn")
            check(f"topbar offline {w}px: tombol profil bisa diklik (menu terbuka)",
                  page.is_visible("#profileMenu"))
            check(f"0 error JS (topbar offline {w}px)", len(errors) == 0, "; ".join(errors[:3]))
        finally:
            browser.close()
    # Kontrol live 320px: baris tetap satu baris, tidak berubah.
    browser, ctx, page, errors = new_page(pw, {"width": 320, "height": 844}, "live", price_state, touch=True)
    try:
        enter_guest(page)
        page.wait_for_timeout(400)
        box = page.locator("#profileBtn").bounding_box()
        check("topbar live 320px: tombol profil tetap di dalam viewport",
              box is not None and box["x"] + box["width"] <= 321, str(box))
        check("0 error JS (topbar live 320px)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_position_row_no_overlap_narrow(pw):
    # Baris posisi di layar sempit (<=400px): kolom info terlalu sempit
    # untuk angka "Rp 1.120.000.000" yang tidak bisa diputus di tengah —
    # teks detail meluber keluar kotaknya dan menumpuk teks PnL
    # (terukur: tumpang tindih 78px di 320px, 38px di 360px, 8px di
    # 390px; hilang di 400px). Perbaikan: .position-row membungkus
    # di <=400px (info selebar kartu, PnL + Tutup di baris kedua).
    price_state = {"live": dict(LIVE)}
    overlap_js = """() => {
      const out = [];
      document.querySelectorAll('.position-row').forEach((row) => {
        const detail = row.querySelector('.position-detail');
        const pnl = row.querySelector('.holding-value');
        if (!detail || !pnl) return;
        const rg = document.createRange(); rg.selectNodeContents(detail);
        const db = rg.getBoundingClientRect();
        const pr = pnl.getBoundingClientRect();
        out.push({
          xOverlap: Math.round(Math.max(0, Math.min(db.right, pr.right) - Math.max(db.left, pr.left))),
          yOverlap: Math.round(Math.max(0, Math.min(db.bottom, pr.bottom) - Math.max(db.top, pr.top)))});
      });
      return out;
    }"""
    for w in (320, 360, 390, 420):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": 844}, "live", price_state, touch=True)
        try:
            enter_guest(page)
            page.wait_for_timeout(600)
            page.fill("#futMarginInput", "100000")
            page.click("#futBtn")
            page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
            page.click("#futConfirmYes")
            page.wait_for_timeout(500)
            check(f"posisi {w}px: posisi Long 10x terbuka",
                  "LONG" in page.text_content("#futPositions"))
            m = page.evaluate(overlap_js)
            check(f"posisi {w}px: PnL tidak menumpuk teks detail",
                  len(m) == 1 and (m[0]["xOverlap"] == 0 or m[0]["yOverlap"] == 0), str(m))
            btn = page.locator("#futPositions [data-pos-id]")
            box = btn.bounding_box()
            check(f"posisi {w}px: tombol Tutup di dalam viewport",
                  box is not None and box["x"] + box["width"] <= w + 1, str(box))
            btn.click()
            page.wait_for_timeout(400)
            check(f"posisi {w}px: tombol Tutup berfungsi (posisi tertutup)",
                  "Belum ada posisi" in page.text_content("#futPositions"))
            check(f"0 error JS (posisi {w}px)", len(errors) == 0, "; ".join(errors[:3]))
        finally:
            browser.close()

def test_position_row_no_overlap_desktop(pw):
    # Baris posisi di DESKTOP juga menumpuk: kartu posisi tinggal di
    # kolom samping yang lebarnya 400px (>=1024px) — setelah PnL
    # (~170px) + tombol Tutup (~55px) + gap, kolom info tinggal
    # ~115px sehingga angka "Rp1.120.000.000" yang tidak bisa diputus
    # meluber dan menumpuk teks PnL. Terbukti live 22 Nov 21:49 WIB
    # pada posisi user: "PnL +Rp146.870 (+29,37%)" menimpa nilai mark
    # "Rp1.112.281.928", dan LONG/BTC/10x jatuh ke baris sendiri.
    # Perbaikan run 42 hanya membungkus di <=400px viewport — kolom
    # samping desktop 400px mengalami hal yang sama. Perbaikan:
    # .position-row SELALU membungkus (info selebar kartu, PnL +
    # Tutup di baris kedua), di semua lebar. Harga digeser +10%
    # setelah buka posisi supaya teks PnL panjang seperti di produksi
    # ("PnL +Rp100.000 (+100,00%)", bukan "PnL Rp0 (0,00%)").
    price_state = {"live": dict(LIVE)}
    overlap_js = """() => {
      const out = [];
      document.querySelectorAll('.position-row').forEach((row) => {
        const detail = row.querySelector('.position-detail');
        const pnl = row.querySelector('.holding-value');
        if (!detail || !pnl) return;
        const rg = document.createRange(); rg.selectNodeContents(detail);
        const db = rg.getBoundingClientRect();
        const pr = pnl.getBoundingClientRect();
        out.push({
          xOverlap: Math.round(Math.max(0, Math.min(db.right, pr.right) - Math.max(db.left, pr.left))),
          yOverlap: Math.round(Math.max(0, Math.min(db.bottom, pr.bottom) - Math.max(db.top, pr.top)))});
      });
      return out;
    }"""
    headline_js = """() => {
      const out = [];
      document.querySelectorAll('.position-row').forEach((row) => {
        const badge = row.querySelector('.dir-badge');
        const strong = row.querySelector('.position-info strong');
        if (!badge || !strong) return;
        const b = badge.getBoundingClientRect(), s = strong.getBoundingClientRect();
        out.push({sameLine: Math.abs(b.top - s.top) < 2,
                  badgeTop: Math.round(b.top), strongTop: Math.round(s.top)});
      });
      return out;
    }"""
    for w in (1280, 1024, 800, 500):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": 800}, "live", price_state)
        try:
            enter_guest(page)
            page.wait_for_timeout(600)
            page.fill("#futMarginInput", "100000")
            page.click("#futBtn")
            page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
            page.click("#futConfirmYes")
            page.wait_for_timeout(500)
            price_state["live"] = dict(LIVE)
            price_state["live"]["bitcoin"] = {"idr": 1232000000, "idr_24h_change": 10.0}
            page.click("#refreshBtn")
            page.wait_for_timeout(2500)
            check(f"posisi desktop {w}px: posisi Long 10x terbuka",
                  "LONG" in page.text_content("#futPositions"))
            check(f"posisi desktop {w}px: PnL panjang tampil (+Rp100.000)",
                  "+Rp100.000" in page.text_content("#futPositions"),
                  page.text_content("#futPositions")[:200])
            m = page.evaluate(overlap_js)
            check(f"posisi desktop {w}px: PnL tidak menumpuk teks detail",
                  len(m) == 1 and (m[0]["xOverlap"] == 0 or m[0]["yOverlap"] == 0), str(m))
            h = page.evaluate(headline_js)
            check(f"posisi desktop {w}px: badge LONG + 'BTC 10x' satu baris",
                  len(h) == 1 and h[0]["sameLine"], str(h))
            btn = page.locator("#futPositions [data-pos-id]")
            box = btn.bounding_box()
            check(f"posisi desktop {w}px: tombol Tutup di dalam viewport",
                  box is not None and box["x"] + box["width"] <= w + 1, str(box))
            btn.click()
            page.wait_for_timeout(400)
            check(f"posisi desktop {w}px: tombol Tutup berfungsi (posisi tertutup)",
                  "Belum ada posisi" in page.text_content("#futPositions"))
            check(f"0 error JS (posisi desktop {w}px)", len(errors) == 0, "; ".join(errors[:3]))
        finally:
            browser.close()

def test_market_row_no_wrap_narrow(pw):
    # Baris pasar di layar sempit (<=400px): kolom harga min-width 148px
    # + ikon 40px menyisakan ~16px untuk nama/simbol di 320px sehingga
    # "BTC / IDR" membungkus jadi 3 baris ("BTC" / "/" / "IDR") di
    # semua 8 koin. Perbaikan: di <=400px ikon 32px, harga 0.8rem,
    # padding kartu 12px, simbol nowrap — nama + simbol satu baris.
    price_state = {"live": dict(LIVE)}
    market_js = """() => {
      const out = [];
      document.querySelectorAll('#marketList .market-row').forEach((row) => {
        const sym = row.querySelector('.coin-symbol');
        const name = row.querySelector('.coin-name');
        const price = row.querySelector('.coin-price');
        const linesOf = (el) => { if (!el) return 0; const r = document.createRange(); r.selectNodeContents(el); return r.getClientRects().length; };
        const sr = sym ? sym.getBoundingClientRect() : null;
        const pr = price ? price.getBoundingClientRect() : null;
        out.push({
          sym: sym ? sym.textContent.trim() : null,
          symLines: linesOf(sym), nameLines: linesOf(name),
          overlap: (sr && pr) ? Math.round(Math.max(0, Math.min(sr.right, pr.right) - Math.max(sr.left, pr.left))) : -1,
          symRight: sr ? Math.round(sr.right) : -1, priceLeft: pr ? Math.round(pr.left) : -1,
          rowH: Math.round(row.getBoundingClientRect().height)});
      });
      return out;
    }"""
    for w in (320, 360, 390, 420):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": 844}, "live", price_state, touch=True)
        try:
            enter_guest(page)
            page.wait_for_function("() => document.querySelectorAll('#marketList .market-row').length >= 8", timeout=10000)
            page.wait_for_function("() => document.getElementById('marketList').textContent.includes('1.120.000.000')", timeout=10000)
            m = page.evaluate(market_js)
            check(f"pasar {w}px: 8 baris koin tampil", len(m) == 8, str(len(m)))
            bad_sym = [x for x in m if x["symLines"] != 1]
            check(f"pasar {w}px: simbol 'XXX / IDR' satu baris (tidak membungkus)",
                  len(bad_sym) == 0, str(bad_sym))
            bad_name = [x for x in m if x["nameLines"] != 1]
            check(f"pasar {w}px: nama koin satu baris",
                  len(bad_name) == 0, str(bad_name))
            bad_ov = [x for x in m if x["overlap"] > 0]
            check(f"pasar {w}px: simbol tidak menumpuk kolom harga",
                  len(bad_ov) == 0, str(bad_ov))
            check(f"pasar {w}px: tinggi baris normal (<=80px; rusak 88-112px)",
                  all(x["rowH"] <= 80 for x in m), str([x["rowH"] for x in m]))
            check(f"0 error JS (pasar {w}px)", len(errors) == 0, "; ".join(errors[:3]))
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
        val = float(page.input_value("#amountInput").replace(",", "."))
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

def test_dust_sell_zero_holdings(pw):
    """Regresi: jual debu (<=1e-8 koin) saat holding 0 tidak boleh jadi
    trade 0 koin. Pernah: ketik 0,000000001 BTC di mode Jual tanpa
    holding -> toleransi pembulatan di computeTrade menjepit ke 0 koin
    lalu lolos (pratinjau 'Jual 0 BTC, terima Rp0'), klik Ya melempar
    TypeError (state.holdings[symbol] tidak ada) dan kotak konfirmasi
    macet terbuka. Kini ditolak 'Koin tidak cukup' sebelum konfirmasi."""
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page.click("#tabSell")
        page.fill("#amountInput", "0,000000001")
        page.wait_for_timeout(500)
        check("dust-sell: jual debu tanpa holding ditolak 'Koin tidak cukup'",
              "Koin tidak cukup" in page.text_content("#tradeError"),
              page.text_content("#tradeError"))
        check("dust-sell: pratinjau 'Jual 0 BTC' tidak muncul",
              page.is_hidden("#previewBox"),
              page.text_content("#previewBox")[:120])
        page.click("#tradeBtn")
        page.wait_for_timeout(300)
        check("dust-sell: kotak konfirmasi tidak terbuka",
              page.is_hidden("#confirmBox"))
        check("dust-sell: kas tetap Rp5.000.000, riwayat tetap kosong",
              "5.000.000" in cash_text(page) and
              "Belum ada transaksi" in page.text_content("#tradeHistory"),
              cash_text(page))
        # Jual debu DENGAN holding tetap jalan normal (bukan 0 koin):
        # beli dulu Rp1.000.000, lalu jual 0,000000001 BTC.
        page.click("#tabBuy")
        page.fill("#amountInput", "1000000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function(
            "() => document.getElementById('cashBalance').textContent.includes('4.000.000')",
            timeout=5000)
        page.click("#tabSell")
        page.fill("#amountInput", "0,000000001")
        page.wait_for_timeout(300)
        check("dust-sell: jual debu dengan holding menampilkan pratinjau",
              not page.is_hidden("#previewBox") and page.is_hidden("#tradeError"),
              page.text_content("#tradeError"))
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(500)
        check("dust-sell: jual debu dengan holding berhasil, tanpa error JS",
              "4.000.001" in cash_text(page) or "4.000.000" in cash_text(page),
              cash_text(page))
        check("0 error JS (dust-sell)", len(errors) == 0, "; ".join(errors[:3]))
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

def test_stale_confirm_tolerance(pw):
    """Regresi: geser harga MIKRO tidak boleh membatalkan konfirmasi.
    Pernah: invalidateStaleConfirms membatalkan konfirmasi bila harga
    berubah SAMA SEKALI (price !== pending.price) — geser Rp1.000 dari
    Rp1,12 Miliar (0,00009%) sudah menutup konfirmasi yang sedang dibaca
    user. Dengan fallback Binance (harga float last USDT x kurs) hampir
    tiap refresh 30 detik harganya geser sedikit sehingga konfirmasi
    praktis tidak pernah bertahan sampai user menekan "Ya". Kini ada
    toleransi 0,1%: geser <= 0,1% membiarkan konfirmasi, geser besar
    (> 0,1%) tetap membatalkan seperti test_stale_confirm."""
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
        # Geser mikro +Rp1.000 (0,00009%) -> konfirmasi TETAP
        price_state["live"] = dict(LIVE)
        price_state["live"]["bitcoin"] = {"idr": 1120001000, "idr_24h_change": 1.5}
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('tradePrice').textContent.includes('1.120.001.000')",
            timeout=10000)
        page.wait_for_timeout(500)
        check("stale-tol: konfirmasi spot TETAP setelah geser +Rp1.000 (0,00009%)",
              page.is_visible("#confirmBox"), "confirmBox hilang karena geser mikro")
        # Geser +0,05% -> konfirmasi TETAP
        price_state["live"] = dict(LIVE)
        price_state["live"]["bitcoin"] = {"idr": 1120560000, "idr_24h_change": 1.5}
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('tradePrice').textContent.includes('1.120.560.000')",
            timeout=10000)
        page.wait_for_timeout(500)
        check("stale-tol: konfirmasi spot TETAP setelah geser +0,05%",
              page.is_visible("#confirmBox"), "confirmBox hilang karena geser 0,05%")
        # Geser +2% -> konfirmasi HARUS batal (kontrol positif)
        price_state["live"] = dict(LIVE)
        price_state["live"]["bitcoin"] = {"idr": 1142400000, "idr_24h_change": 1.5}
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('tradePrice').textContent.includes('1.142.400.000')",
            timeout=10000)
        page.wait_for_timeout(500)
        check("stale-tol: konfirmasi spot BATAL setelah geser +2%",
              page.is_hidden("#confirmBox"), "confirmBox masih tampil setelah geser 2%")
        check("stale-tol: kas tetap Rp5.000.000, belum ada trade",
              "5.000.000" in cash_text(page) and
              "Belum ada transaksi" in page.text_content("#tradeHistory"),
              cash_text(page))
        # --- FUTURES: konfirmasi Long, geser mikro -> TETAP ---
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        price_state["live"] = dict(LIVE)
        price_state["live"]["bitcoin"] = {"idr": 1142401000, "idr_24h_change": 1.5}
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('futPrice').textContent.includes('1.142.401.000')",
            timeout=10000)
        page.wait_for_timeout(500)
        check("stale-tol: konfirmasi futures TETAP setelah geser +Rp1.000",
              page.is_visible("#futConfirmBox"), "futConfirmBox hilang karena geser mikro")
        # Eksekusi di harga konfirmasi — entry = harga saat konfirmasi
        # dibuat (Rp1.142.400.000), BUKAN mark baru Rp1.142.401.000;
        # PnL awal +Rp1 (0,00%) karena mark geser Rp1.000 setelah buka.
        page.click("#futConfirmYes")
        page.wait_for_timeout(500)
        pos = page.text_content("#futPositions")
        check("stale-tol: posisi Long entry harga konfirmasi Rp1.142.400.000 "
              "(mark baru Rp1.142.401.000), PnL +Rp1",
              "entry Rp" in pos and "1.142.400.000" in pos and
              "mark Rp" in pos and "1.142.401.000" in pos and "PnL +Rp" in pos,
              pos.replace("\n", " ")[:200])
        check("0 error JS (stale-tol)", len(errors) == 0, "; ".join(errors[:3]))
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

def test_offline_confirm_cancelled(pw):
    """Regresi: konfirmasi trade/futures yang dibuka saat LIVE harus
    DIBATALKAN begitu harga jatuh offline — walau harga contoh
    kebetulan SAMA dengan harga live. Pernah: TRX live Rp4.500 ==
    contoh Rp4.500, jadi invalidateStaleConfirms (toleransi 0,1%)
    tidak membatalkan; posisi Long + beli spot tereksekusi saat badge
    sudah OFFLINE. Kini konfirmasi dibatalkan + toast, tanpa eksekusi."""
    live = dict(LIVE)
    live["tron"] = {"idr": 4500, "idr_24h_change": 0.9}
    price_state = {"live": live}
    browser, ctx, page, errors = new_page(
        pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        page.click('.market-row[data-symbol="TRX"]')
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.fill("#amountInput", "100000")
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        check("offline-confirm: kedua konfirmasi terbuka saat live",
              page.is_visible("#futConfirmBox") and page.is_visible("#confirmBox"))
        # Putuskan semua API -> refresh -> harga contoh (TRX contoh Rp4.500 == live)
        page.route("**/api.coingecko.com/**", lambda r: r.abort())
        page.route("**/data-api.binance.vision/**", lambda r: r.abort())
        page.route("**/api.binance.com/**", lambda r: r.abort())
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent.includes('OFFLINE')",
            timeout=15000)
        check("offline-confirm: konfirmasi futures DIBATALKAN saat offline",
              page.is_hidden("#futConfirmBox"), "futConfirmBox masih tampil")
        check("offline-confirm: konfirmasi spot DIBATALKAN saat offline",
              page.is_hidden("#confirmBox"), "confirmBox masih tampil")
        check("offline-confirm: toast menjelaskan konfirmasi dibatalkan",
              "konfirmasi dibatalkan" in page.text_content("#toast"),
              page.text_content("#toast"))
        check("offline-confirm: belum ada posisi futures + kas tetap Rp5.000.000",
              "Belum ada posisi futures" in page.text_content("#futPositions") and
              "5.000.000" in cash_text(page),
              cash_text(page))
        check("0 error JS (offline-confirm)", len(errors) == 0, "; ".join(errors[:3]))
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
                  val not in ("", "0") and "e" not in val and float(val.replace(",", ".")) > 0,
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

def test_focus_kept_on_refresh(pw):
    """Regresi: fokus keyboard TIDAK hilang saat daftar dibangun ulang.
    Pernah: renderMarket()/renderPositions()/renderProfileUI() memakai
    innerHTML = "" lalu membangun ulang semua baris di tiap renderAll()
    (tiap refresh harga 30 detik) — fokus di baris pasar / tombol Tutup
    posisi / item profil jatuh ke <body>, pengguna keyboard kehilangan
    posisinya tiap 30 detik. Elemen statis (amountInput) tidak kena
    karena tidak dibangun ulang."""
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", {"live": dict(LIVE)})
    try:
        enter_guest(page)
        page.wait_for_function("() => document.querySelectorAll('.market-row').length === 8", timeout=10000)
        # 1. Baris pasar ETH tetap fokus setelah renderAll()
        page.evaluate("() => document.querySelectorAll('.market-row')[1].focus()")
        check("focus-refresh: fokus awal di baris ETH",
              page.evaluate("() => document.activeElement && document.activeElement.textContent.includes('Ethereum')"))
        page.evaluate("() => renderAll()")
        check("focus-refresh: baris ETH tetap fokus setelah renderAll()",
              page.evaluate("() => { const a = document.activeElement; return !!(a && a.classList.contains('market-row') && a.textContent.includes('Ethereum')); }"),
              page.evaluate("() => document.activeElement && document.activeElement.tagName"))
        # 2. Refresh harga sungguhan (fetchPrices) juga tidak menghilangkan fokus
        page.evaluate("() => document.querySelectorAll('.market-row')[3].focus()")
        page.evaluate("() => fetchPrices()")
        page.wait_for_timeout(1500)
        check("focus-refresh: baris SOL tetap fokus setelah fetchPrices()",
              page.evaluate("() => { const a = document.activeElement; return !!(a && a.classList.contains('market-row') && a.textContent.includes('Solana')); }"),
              page.evaluate("() => document.activeElement && document.activeElement.tagName"))
        # 3. Tombol Tutup posisi tetap fokus setelah renderAll()
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_function("() => document.querySelectorAll('#futPositions .position-row').length === 1", timeout=5000)
        page.evaluate("() => document.querySelector('#futPositions [data-pos-id]').focus()")
        page.evaluate("() => renderAll()")
        check("focus-refresh: tombol Tutup tetap fokus setelah renderAll()",
              page.evaluate("() => { const a = document.activeElement; return !!(a && a.textContent.trim() === 'Tutup'); }"),
              page.evaluate("() => document.activeElement && document.activeElement.tagName"))
        # 4. Posisi yang ditutup TIDAK memindahkan fokus ke tombol Tutup lain
        page.fill("#futMarginInput", "100000")
        page.click("#futBtn")
        page.wait_for_selector("#futConfirmBox:not([hidden])", timeout=5000)
        page.click("#futConfirmYes")
        page.wait_for_function("() => document.querySelectorAll('#futPositions .position-row').length === 2", timeout=5000)
        page.evaluate("() => document.querySelectorAll('#futPositions [data-pos-id]')[0].focus()")
        page.evaluate("() => closeFutures(window.__futuresPnl[0].id, 'manual')")
        page.wait_for_function("() => document.querySelectorAll('#futPositions .position-row').length === 1", timeout=5000)
        check("focus-refresh: tutup posisi sendiri TIDAK memindahkan fokus ke Tutup posisi lain",
              page.evaluate("() => { const a = document.activeElement; return !(a && a.textContent && a.textContent.trim() === 'Tutup'); }"),
              page.evaluate("() => document.activeElement && document.activeElement.tagName"))
        # 5. Item profil di menu tetap fokus setelah renderAll()
        page.click("#profileBtn")
        page.wait_for_selector("#profileMenu:not([hidden])", timeout=5000)
        page.evaluate("() => document.querySelector('.profile-item').focus()")
        page.evaluate("() => renderAll()")
        check("focus-refresh: item profil tetap fokus setelah renderAll()",
              page.evaluate("() => { const a = document.activeElement; return !!(a && a.classList.contains('profile-item')); }"),
              page.evaluate("() => document.activeElement && document.activeElement.tagName"))
        # 6. Kontrol: amountInput (elemen statis) tetap fokus
        page.evaluate("() => document.getElementById('amountInput').focus()")
        page.evaluate("() => renderAll()")
        check("focus-refresh: amountInput tetap fokus setelah renderAll()",
              page.evaluate("document.activeElement && document.activeElement.id") == "amountInput")
        check("0 error JS (focus-refresh)", len(errors) == 0, "; ".join(errors[:3]))
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

def test_multitab_snapshot_keeps_context(pw):
    """Regresi: snapshot grafik portofolio dari tab lain TIDAK boleh
    menghapus konteks trade tab ini. Pernah: handler `storage` selalu
    memanggil clearTradeContext() di setiap perubahan store — padahal
    tab lain menyimpan store tiap ~30 detik hanya untuk snapshot
    grafik (history), tanpa mengubah kas/holding/posisi. Akibatnya
    tab B yang sedang membuka konfirmasi beli Rp1.000.000 kehilangan
    input + konfirmasinya begitu tab A me-refresh harga. Perbaikan:
    handler `storage` hanya membatalkan konteks trade bila sidik data
    trade profil aktif (kas/holding/futures/riwayat trade) berubah;
    perubahan history saja tidak menyentuh konteks trade. Kontrol
    balik: trade SUNGGUHAN di tab lain tetap membatalkan konteks."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, pageA, errorsA = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(pageA)
        pageA.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        # Tab A beli BTC dulu — supaya perubahan harga mengubah total
        # portofolio dan snapshot berikutnya benar-benar tersimpan.
        pageA.fill("#amountInput", "1000000")
        pageA.click("#tradeBtn")
        pageA.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        pageA.click("#confirmYes")
        pageA.wait_for_function("() => document.getElementById('confirmBox').hidden", timeout=5000)
        check("multitab-snapshot: tab A beli BTC, kas Rp4.000.000",
              "4.000.000" in cash_text(pageA), cash_text(pageA))
        # Tab B di context yang sama
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
        check("multitab-snapshot: tab B ikut sinkron, kas Rp4.000.000",
              "4.000.000" in cash_text(pageB), cash_text(pageB))
        # Tab B: ketik jumlah + buka konfirmasi beli
        pageB.fill("#amountInput", "1000000")
        pageB.click("#tradeBtn")
        pageB.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        n_hist_before = pageB.evaluate(
            "() => JSON.parse(localStorage.getItem('simulasi-trading-v2')).profiles[0].history.length")
        # Tab A: harga berubah sedikit -> refresh -> snapshot baru tersimpan
        price_state["live"]["bitcoin"] = {"idr": 1121000000, "idr_24h_change": 1.6}
        pageA.evaluate("() => fetchPrices()")
        pageA.wait_for_timeout(1500)
        n_hist_after = pageB.evaluate(
            "() => JSON.parse(localStorage.getItem('simulasi-trading-v2')).profiles[0].history.length")
        check("multitab-snapshot: snapshot tab A memang tersimpan (history bertambah)",
              n_hist_after > n_hist_before, f"{n_hist_before} -> {n_hist_after}")
        check("multitab-snapshot: input tab B MASIH '1000000' setelah snapshot tab A",
              pageB.input_value("#amountInput") == "1000000",
              repr(pageB.input_value("#amountInput")))
        check("multitab-snapshot: konfirmasi tab B MASIH terbuka setelah snapshot tab A",
              not pageB.is_hidden("#confirmBox"))
        check("multitab-snapshot: pratinjau tab B MASIH tampil setelah snapshot tab A",
              not pageB.is_hidden("#previewBox"))
        # Kontrol: konfirmasi yang dipertahankan tetap bisa dieksekusi
        pageB.click("#confirmYes")
        pageB.wait_for_function("() => document.getElementById('confirmBox').hidden", timeout=5000)
        check("multitab-snapshot: konfirmasi tab B berhasil dieksekusi, kas Rp3.000.000",
              "3.000.000" in cash_text(pageB), cash_text(pageB))
        # Kontrol balik: trade SUNGGUHAN di tab lain tetap membatalkan konteks
        pageB.fill("#amountInput", "500000")
        pageB.click("#tradeBtn")
        pageB.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        pageA.bring_to_front()
        pageA.click("#tabSell")
        pageA.fill("#amountInput", "0,0004")
        pageA.click("#tradeBtn")
        pageA.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        pageA.click("#confirmYes")
        pageA.wait_for_function("() => document.getElementById('confirmBox').hidden", timeout=5000)
        pageB.wait_for_timeout(1200)  # beri waktu event storage sampai ke B
        check("multitab-snapshot: trade tab A membatalkan input tab B",
              pageB.input_value("#amountInput") == "",
              repr(pageB.input_value("#amountInput")))
        check("multitab-snapshot: trade tab A menutup konfirmasi tab B",
              pageB.is_hidden("#confirmBox"))
        check("0 error JS (multitab-snapshot, tab A)", len(errorsA) == 0, "; ".join(errorsA[:3]))
        check("0 error JS (multitab-snapshot, tab B)", len(errorsB) == 0, "; ".join(errorsB[:3]))
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

def test_quick_dot_decimal(pw):
    """Regresi: tombol cepat jual tidak boleh mengisi desimal titik yang
    parseAmount baca sebagai ribuan. Pernah: holding 1,5 XRP, klik Jual
    75% -> fmtInputCoins mengisi "1.125" (titik desimal) -> parseAmount
    membacanya sebagai ribuan Indonesia (1125 koin) -> pratinjau menolak
    "Koin tidak cukup. Kamu punya 1,5 XRP." padahal koinnya cukup.
    Harus: tombol cepat mengisi format Indonesia berkoma ("1,125")
    sehingga pratinjau tampil dan jual 75% benar-benar tereksekusi.
    Kontrol: 100% ("1,5") dan 25% ("0,375") tetap jalan; ketik
    langsung "1,125" juga terbaca 1,125 koin."""
    price_state = {"live": dict(LIVE)}
    browser, ctx, page, errors = new_page(pw, {"width": 1280, "height": 800}, "live", price_state)
    try:
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page.click(".market-row:has-text('XRP')")
        page.wait_for_timeout(300)
        # Beli Rp54.000 XRP @ Rp36.000 -> holding 1,5 XRP
        page.fill("#amountInput", "54000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        check("quick-dot: beli Rp54.000 XRP, holding 1,5 koin",
              "1,5 koin" in page.text_content("#holdingsList"),
              page.text_content("#holdingsList").replace("\n", " ")[:120])
        page.click("#tabSell")
        page.wait_for_timeout(300)
        # 75% dari 1,5 = 1,125 — titik desimal di sini = bug
        page.click("#quickRow [data-pct='75']")
        page.wait_for_timeout(300)
        val = page.input_value("#amountInput")
        check("quick-dot: cepat 75% mengisi '1,125' (koma, bukan '1.125')",
              val == "1,125", f"input={val!r}")
        check("quick-dot: cepat 75% menampilkan pratinjau (bukan 'Koin tidak cukup')",
              page.is_visible("#previewBox") and page.is_hidden("#tradeError"),
              page.text_content("#tradeError") if page.is_visible("#tradeError") else "pratinjau tampil")
        check("quick-dot: pratinjau 75% menyebut 1,125 XRP",
              "1,125 XRP" in page.text_content("#previewBox"),
              page.text_content("#previewBox").replace("\n", " ")[:140])
        # Jual 75% benar-benar tereksekusi: kas naik Rp40.500.
        # Jangan wait_for_selector confirmBox: pada kode pra-perbaikan
        # konfirmasi TIDAK PERNAH muncul (input "1.125" dibaca 1125)
        # sehingga tes akan crash timeout, bukan gagal bersih.
        page.click("#tradeBtn")
        page.wait_for_timeout(300)
        check("quick-dot: jual 75% membuka konfirmasi",
              page.is_visible("#confirmBox"),
              page.text_content("#tradeError") if page.is_visible("#tradeError") else "kotak konfirmasi tampil")
        if page.is_visible("#confirmBox"):
            page.click("#confirmYes")
            page.wait_for_function(
                "() => document.getElementById('cashBalance').textContent.includes('4.986.500')",
                timeout=5000)
        check("quick-dot: jual 75% tereksekusi, kas Rp4.986.500",
              "4.986.500" in cash_text(page), cash_text(page))
        check("quick-dot: sisa holding 0,375 XRP",
              "0,375 koin" in page.text_content("#holdingsList"),
              page.text_content("#holdingsList").replace("\n", " ")[:120])
        # Kontrol: ketik langsung "1,125" dibaca 1,125 koin (bukan 1125).
        # Sisa holding 0,375 < 1,125, jadi pakai DOGE: beli Rp8.000 DOGE
        # @ Rp3.200 -> 2,5 DOGE, lalu ketik "1,125" harus tampil pratinjau.
        page.click(".market-row:has-text('DOGE')")
        page.wait_for_timeout(300)
        page.click("#tabBuy")
        page.wait_for_timeout(300)
        page.fill("#amountInput", "8000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_timeout(400)
        page.click("#tabSell")
        page.wait_for_timeout(300)
        page.fill("#amountInput", "1,125")
        page.wait_for_timeout(300)
        check("quick-dot: ketik '1,125' pratinjau tampil (bukan 'Koin tidak cukup')",
              page.is_visible("#previewBox") and page.is_hidden("#tradeError"),
              page.text_content("#tradeError") if page.is_visible("#tradeError") else "pratinjau tampil")
        check("0 error JS (quick-dot)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_chart_refetch_10min(pw):
    """Regresi: grafik harga 24 jam HARUS di-fetch ulang setelah 10 menit.
    Pernah: applyPrices hanya memanggil fetchPriceChart bila grafik belum
    live, sehingga guard kesegaran 10 menit di fetchPriceChart tidak pernah
    tercapai untuk grafik live — halaman yang dibiarkan terbuka berjam-jam
    menampilkan deret yang tidak lagi 24 jam (titik live hanya ditempel di
    ujung, lalu cap 400 titik memotong data lama). Harus: tiap refresh harga
    mencoba fetchPriceChart (guard internal yang membatasi), dan selama
    fetch ulang berkala grafik lama TETAP tampil (tidak berkedip blank).
    Data mock diubah pada fetch ke-2 untuk membuktikan data baru dipakai."""
    import time as _time
    price_state = {"live": dict(LIVE)}
    chart_base = {"v": 1100000000}
    chart_hits = {"n": 0}
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
                          body=json.dumps(price_state["live"]))
        elif "market_chart" in url:
            chart_hits["n"] += 1
            # Fetch ulang (ke-2 dst) dibuat lambat 1,5 dtk supaya jendela
            # loading-nya bisa diamati; datanya beda dari fetch pertama.
            if chart_hits["n"] >= 2:
                _time.sleep(1.5)
            now = int(_time.time() * 1000)
            base = chart_base["v"]
            pts = [[now - (96 - i) * 900000, base + i * 200000] for i in range(97)]
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"prices": pts}))
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
        page.wait_for_function(
            "() => window.__priceChart && window.__priceChart.points > 10",
            timeout=10000)
        check("chart-refetch: market_chart di-fetch saat muat awal",
              chart_hits["n"] >= 1, f"hits={chart_hits['n']}")
        p96 = page.evaluate("() => window.priceHistory.BTC.points[96].v")
        check("chart-refetch: titik ke-97 grafik awal Rp1.119.200.000",
              abs(p96 - 1119200000) < 1, f"points[96]={p96}")
        # Tuakan grafik jadi 11 menit lalu + ubah data mock, lalu Refresh.
        chart_base["v"] = 1000000000
        page.evaluate(
            "() => { window.priceHistory.BTC.fetchedAt = Date.now() - 11*60*1000; }")
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => window.__priceChart && window.__priceChart.loading === true",
            timeout=5000)
        # Selama fetch ulang: grafik lama tetap tampil (tidak blank).
        note = page.text_content("#priceChartNote")
        pts_now = page.evaluate("() => window.__priceChart.points")
        check("chart-refetch: selama fetch ulang, catatan bukan 'Memuat grafik…'",
              "Memuat grafik" not in note, note)
        check("chart-refetch: selama fetch ulang, titik lama tetap ada",
              pts_now > 10, f"points={pts_now}")
        page.wait_for_function(
            "() => window.__priceChart && window.__priceChart.loading === false",
            timeout=10000)
        check("chart-refetch: market_chart di-fetch ulang setelah >10 menit",
              chart_hits["n"] >= 2, f"hits={chart_hits['n']}")
        p96_new = page.evaluate("() => window.priceHistory.BTC.points[96].v")
        check("chart-refetch: data baru dipakai (titik ke-97 Rp1.019.200.000)",
              abs(p96_new - 1019200000) < 1, f"points[96]={p96_new}")
        check("0 error JS (chart-refetch)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_chart_refetch_fail_keeps_live_series(pw):
    """Regresi: refetch grafik 24 jam yang GAGAL tidak boleh membuang
    deret live yang sudah ada.
    Pernah: catch di fetchPriceChart() selalu menimpa h.points dengan
    syntheticSeries() — refetch berkala tiap 10 menit yang kena 429 /
    timeout mengganti seluruh deret asli CoinGecko (24 jam data nyata)
    dengan random walk sintetis berjangkar harga live. Kini: bila
    sudah ada deret live (>10 titik), deret itu dipertahankan,
    h.live tetap true, dan fetch dijadwalkan ulang setelah jendela
    10 menit. Deret sintetis hanya bila belum ada deret live."""
    import time as _time
    price_state = {"live": dict(LIVE)}
    chart_hits = {"n": 0}
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
                          body=json.dumps(price_state["live"]))
        elif "market_chart" in url:
            chart_hits["n"] += 1
            if chart_hits["n"] >= 2:
                route.fulfill(status=429, content_type="application/json",
                              body=json.dumps({"status": {"error_code": 429}}))
                return
            now = int(_time.time() * 1000)
            pts = [[now - (96 - i) * 900000, 1100000000 + i * 200000]
                   for i in range(97)]
            pts[50][1] = 999000000  # sidik jari: lembah khas deret asli
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"prices": pts}))
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
        page.wait_for_function(
            "() => window.__priceChart && window.__priceChart.live",
            timeout=10000)
        p50 = page.evaluate("() => window.priceHistory.BTC.points[50].v")
        check("chart-refetch-fail: deret live awal punya sidik jari (titik ke-51 Rp999.000.000)",
              abs(p50 - 999000000) < 1, f"points[50]={p50}")
        # Tuakan grafik jadi 11 menit lalu, lalu picu refetch yang akan 429.
        page.evaluate(
            "() => { window.priceHistory.BTC.fetchedAt = Date.now() - 11*60*1000; }")
        page.click("#refreshBtn")
        page.wait_for_function(
            "() => window.__priceChart && window.__priceChart.loading === true",
            timeout=5000)
        page.wait_for_function(
            "() => window.__priceChart && window.__priceChart.loading === false",
            timeout=10000)
        check("chart-refetch-fail: refetch gagal terjadi (market_chart hit ke-2)",
              chart_hits["n"] >= 2, f"hits={chart_hits['n']}")
        live_after = page.evaluate("() => window.__priceChart.live")
        check("chart-refetch-fail: grafik TETAP live setelah refetch gagal",
              live_after is True, f"live={live_after}")
        p50_after = page.evaluate("() => window.priceHistory.BTC.points[50].v")
        check("chart-refetch-fail: deret live dipertahankan (sidik jari utuh, bukan sintetis)",
              abs(p50_after - 999000000) < 1, f"points[50]={p50_after}")
        note = page.text_content("#priceChartNote")
        check("chart-refetch-fail: label tetap 'CoinGecko', bukan 'estimasi'",
              "CoinGecko" in note and "estimasi" not in note.lower(), note)
        # Jendela 10 menit dihormati: fetchPriceChart langsung tidak fetch lagi.
        page.evaluate("() => { fetchPriceChart('BTC'); }")
        page.wait_for_timeout(600)
        check("chart-refetch-fail: tidak ada fetch ulang sebelum 10 menit",
              chart_hits["n"] == 2, f"hits={chart_hits['n']}")
        check("0 error JS (chart-refetch-fail)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_empty_input_stays_silent(pw):
    """Regresi: panel trade/futures DIAM saat input masih kosong —
    tanpa error merah dan tanpa halaman ketarik ke bawah.

    Pernah: computeTrade()/computeFutures() memeriksa harga/offline
    SEBELUM memeriksa input kosong, sehingga panel yang baru dibuka
    (belum ada ketikan apa pun) sudah menampilkan error merah "Harga
    belum tersedia" / "Harga live tidak tersedia" begitu halaman
    dimuat atau saat offline — dan showFutError() menarik halaman HP
    ke scrollY 2003 lewat scrollIntoView untuk pesan "baru" itu.
    Perbaikan: input kosong dikembalikan null SEBELUM pemeriksaan
    harga/offline; blokir offline + umpan balik tombol tetap berlaku
    begitu user mengetik atau menekan tombol."""
    siv_hook = (
        "window.__sivCount = 0;"
        "var _siv = Element.prototype.scrollIntoView;"
        "Element.prototype.scrollIntoView = function() {"
        "  window.__sivCount++; return _siv.apply(this, arguments); };")
    # --- OFFLINE, HP: input kosong -> diam, halaman tidak loncat ---
    browser, ctx, page, errors = new_page(
        pw, {"width": 390, "height": 844}, "offline", {"live": {}})
    try:
        page.add_init_script(siv_hook)
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent.includes('CONTOH')",
            timeout=15000)
        page.wait_for_timeout(1500)  # biarkan smooth scroll (bila ada) selesai
        check("empty-silent: offline + input kosong -> tradeError tersembunyi",
              not page.is_visible("#tradeError"),
              page.text_content("#tradeError")[:90])
        check("empty-silent: offline + margin kosong -> futError tersembunyi",
              not page.is_visible("#futError"),
              page.text_content("#futError")[:90])
        check("empty-silent: offline + input kosong -> halaman tidak ketarik ke bawah",
              page.evaluate("() => window.scrollY") == 0 and
              page.evaluate("() => window.__sivCount") == 0,
              f"scrollY={page.evaluate('() => window.scrollY')} siv={page.evaluate('() => window.__sivCount')}")
        # Kontrol: begitu ada ketikan, blokir offline TETAP tampil.
        page.fill("#amountInput", "1000000")
        page.wait_for_timeout(500)
        check("empty-silent: ketik jumlah offline -> error blokir spot tampil",
              page.is_visible("#tradeError") and
              "Harga live tidak tersedia" in page.text_content("#tradeError"),
              page.text_content("#tradeError")[:90])
        page.fill("#futMarginInput", "100000")
        page.wait_for_timeout(500)
        check("empty-silent: ketik margin offline -> error blokir futures tampil",
              page.is_visible("#futError") and
              "Harga live tidak tersedia" in page.text_content("#futError"),
              page.text_content("#futError")[:90])
        # Kontrol: kosongkan lagi + tekan tombol -> umpan balik tombol tetap ada.
        page.fill("#amountInput", "")
        page.fill("#futMarginInput", "")
        page.wait_for_timeout(500)
        page.click("#tradeBtn")
        page.wait_for_timeout(400)
        check("empty-silent: klik Beli input kosong -> 'Masukkan jumlah dulu.'",
              page.is_visible("#tradeError") and
              "Masukkan jumlah dulu." in page.text_content("#tradeError"),
              page.text_content("#tradeError")[:90])
        page.click("#futBtn")
        page.wait_for_timeout(400)
        check("empty-silent: klik Buka margin kosong -> 'Masukkan margin dulu.'",
              page.is_visible("#futError") and
              "Masukkan margin dulu" in page.text_content("#futError"),
              page.text_content("#futError")[:90])
        check("0 error JS (empty-silent offline)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()
    # --- LIVE, HP: input kosong -> diam, halaman tidak loncat ---
    browser, ctx, page, errors = new_page(
        pw, {"width": 390, "height": 844}, "live", {"live": dict(LIVE)})
    try:
        page.add_init_script(siv_hook)
        enter_guest(page)
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page.wait_for_timeout(1200)
        check("empty-silent: live + input kosong -> tradeError tersembunyi",
              not page.is_visible("#tradeError"),
              page.text_content("#tradeError")[:90])
        check("empty-silent: live + margin kosong -> futError tersembunyi",
              not page.is_visible("#futError"),
              page.text_content("#futError")[:90])
        check("empty-silent: live + input kosong -> halaman tidak ketarik ke bawah",
              page.evaluate("() => window.scrollY") == 0 and
              page.evaluate("() => window.__sivCount") == 0,
              f"scrollY={page.evaluate('() => window.scrollY')} siv={page.evaluate('() => window.__sivCount')}")
        check("0 error JS (empty-silent live)", len(errors) == 0, "; ".join(errors[:3]))
    finally:
        browser.close()

def test_stat_value_no_break_narrow(pw):
    # Nilai stat portofolio di layar sempit (<=400px): kolom grid 2 kolom
    # cuma ~123px di 320px, sementara "Rp 5.000.000" 1.2rem butuh ~139px
    # — .stat-value punya overflow-wrap: break-word sehingga angka
    # pecah di tengah ("Rp 5.000.0" / "00") dan "Rp 0 (0,00%)" jadi
    # 2 baris. Perbaikan: grid portofolio 1 kolom di <=400px (nilai
    # selebar kartu, ~262px di 320px).
    price_state = {"live": dict(LIVE)}
    stat_js = """() => {
      const out = [];
      document.querySelectorAll('.portfolio-grid .stat-value').forEach((v) => {
        const rg = document.createRange(); rg.selectNodeContents(v);
        const rects = rg.getClientRects();
        out.push({text: v.textContent.trim(), lines: rects.length,
          right: Math.round(rects[rects.length - 1].right)});
      });
      return out;
    }"""
    for w in (320, 360, 390, 420):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": 844}, "live", price_state, touch=True)
        try:
            enter_guest(page)
            page.wait_for_timeout(600)
            m = page.evaluate(stat_js)
            check(f"stat {w}px: 3 nilai stat terbaca", len(m) == 3, str(m))
            for s in m:
                check(f"stat {w}px: {s['text']!r} satu baris (tidak pecah di tengah angka)",
                      s["lines"] == 1, str(s))
                check(f"stat {w}px: {s['text']!r} di dalam viewport",
                      s["right"] <= w + 1, str(s))
            check(f"0 error JS (stat {w}px)", len(errors) == 0, "; ".join(errors[:3]))
        finally:
            browser.close()

def test_chart_labels_no_overlap_narrow(pw):
    # Label "Modal awal" grafik portofolio menumpuk label nilai terakhir
    # bila nilainya ~ modal awal (profil baru: baseY == ly) di kanvas
    # sempit — di 320px pill x 66–191 vs label x 163–250 (tumpang 28px).
    # Perbaikan: drawChart menggeser label yang bertabrakan (label nilai
    # ke bawah titik, atau pill ke bawah garis). Hook window.__chartLabels
    # memuat rect kedua label yang benar-benar digambar.
    price_state = {"live": dict(LIVE)}
    labels_js = """() => {
      const h = window.__chartLabels;
      if (!h) return null;
      const cv = document.getElementById('chart');
      return {pill: h.pill, last: h.last, w: cv.clientWidth, h: cv.clientHeight};
    }"""
    for w in (320, 360, 390, 420):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": 844}, "live", price_state, touch=True)
        try:
            enter_guest(page)
            page.click("#refreshBtn")
            try:
                page.wait_for_function("() => window.__chartLabels", timeout=10000)
            except Exception:
                pass  # hook tidak muncul -> cek di bawah GAGAL, bukan crash
            m = page.evaluate(labels_js)
            check(f"chartlabel {w}px: hook label grafik terbaca", m is not None, str(m))
            if m:
                p, l = m["pill"], m["last"]
                overlap = (min(p["x1"], l["x1"]) - max(p["x0"], l["x0"]) > 0
                           and min(p["y1"], l["y1"]) - max(p["y0"], l["y0"]) > 0)
                check(f"chartlabel {w}px: pill 'Modal awal' tidak menumpuk label nilai",
                      not overlap, str(m))
                check(f"chartlabel {w}px: kedua label di dalam kanvas",
                      p["x0"] >= 0 and p["x1"] <= m["w"] + 1 and l["x0"] >= 0 and l["x1"] <= m["w"] + 1
                      and p["y0"] >= 0 and p["y1"] <= m["h"] + 1 and l["y0"] >= 0 and l["y1"] <= m["h"] + 1,
                      str(m))
            check(f"0 error JS (chartlabel {w}px)", len(errors) == 0, "; ".join(errors[:3]))
        finally:
            browser.close()

def test_profile_menu_short_viewport(pw):
    # Menu profil di viewport pendek (HP landscape): 5 profil + form +
    # catatan ≈ 380px, sementara topbar sticky membuat menu tidak ikut
    # halaman saat di-scroll — bagian bawah (tombol Buat / catatan)
    # terpotong dan tidak bisa dijangkau. Pernah: di 700x360 tombol
    # Buat di y 341-383 (di luar layar), di 640x320 menu bawah di y 494.
    price_state = {"live": dict(LIVE)}
    for (w, h) in ((844, 390), (700, 360), (640, 320)):
        browser, ctx, page, errors = new_page(pw, {"width": w, "height": h}, "live", price_state, touch=True)
        try:
            enter_guest(page)
            for nm in ("Dua", "Tiga", "Empat", "Lima"):
                page.click("#profileBtn")
                page.wait_for_selector("#profileMenu:not([hidden])", timeout=5000)
                page.fill("#newProfileName", nm)
                page.click("#createProfileBtn")
                page.wait_for_timeout(300)
            page.click("#profileBtn")
            page.wait_for_selector("#profileMenu:not([hidden])", timeout=5000)
            page.wait_for_timeout(400)
            m = page.evaluate("() => { const r = (s) => { const el = document.querySelector(s);"
                              " if (!el) return null; const b = el.getBoundingClientRect();"
                              " return {top: Math.round(b.top), bottom: Math.round(b.bottom)}; };"
                              " const menu = document.getElementById('profileMenu');"
                              " return {vh: window.innerHeight, menu: r('#profileMenu'),"
                              " buat: r('#createProfileBtn'), note: r('#profileNote'),"
                              " scrollable: menu.scrollHeight > menu.clientHeight + 1}; }")
            check(f"menu profil 5 {w}x{h}: menu seluruhnya terlihat (bottom <= {h})",
                  m["menu"] and m["menu"]["bottom"] <= h, str(m["menu"]))
            check(f"menu profil 5 {w}x{h}: tombol Buat terlihat penuh",
                  m["buat"] and m["buat"]["bottom"] <= h, str(m["buat"]))
            # Catatan di ujung bawah isi menu: di viewport sangat pendek
            # (640x320) isinya memang tidak muat sekaligus — yang penting
            # catatan TERJANGKAU dengan menggulir menu ke bawah (menu
            # menggulir di dalam bingkainya, bukan halaman).
            page.evaluate("() => { const m = document.getElementById('profileMenu');"
                          " m.scrollTop = m.scrollHeight; }")
            page.wait_for_timeout(200)
            m2 = page.evaluate("() => { const el = document.getElementById('profileNote');"
                               " const b = el.getBoundingClientRect();"
                               " return {top: Math.round(b.top), bottom: Math.round(b.bottom)}; }")
            check(f"menu profil 5 {w}x{h}: catatan terjangkau setelah gulir menu",
                  m2 and m2["bottom"] <= h, str(m2))
            check(f"0 error JS (menu profil {w}x{h})", len(errors) == 0, "; ".join(errors[:3]))
        finally:
            browser.close()

def test_stale_active_profile_id(pw):
    """activeProfileId basi (menunjuk profil yang tidak ada — mis.
    localStorage disunting/rusak) tidak boleh membuat aplikasi jalan
    buntu. Pernah: profil valid 'Bray' (kas Rp4.000.000 + holding)
    tersimpan tapi activeProfileId 'p-hilang' -> state null, overlay
    sambutan tetap sembunyi (profiles.length > 0) DAN tombol profil
    tersembunyi, kas tampil Rp5.000.000 default, tidak ada jalan
    masuk ke profil mana pun. Harus: pulih ke profil pertama yang
    ada, datanya utuh, trade jalan."""
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
        page.goto(BASE)
        page.evaluate("""() => {
          localStorage.setItem('simulasi-trading-v2', JSON.stringify({
            version: 2, activeProfileId: 'p-hilang',
            profiles: [{ id: 'p-nyata', name: 'Bray', createdAt: 1,
              cash: 4000000, holdings: { BTC: { amount: 0.0005, avgPrice: 1000000000 } },
              trades: [], history: [], futures: [] }]
          }));
        }""")
        page.reload()
        page.wait_for_function(
            "() => document.getElementById('priceBadgeText').textContent === 'HARGA LIVE'",
            timeout=10000)
        page.wait_for_timeout(500)
        check("stale-id: tombol profil tampil (ada jalan masuk)",
              page.is_visible("#profileWrap"),
              "profileWrap hidden=%s overlay hidden=%s" % (
                  page.evaluate("() => document.getElementById('profileWrap').hidden"),
                  page.evaluate("() => document.getElementById('welcomeOverlay').hidden")))
        check("stale-id: profil valid 'Bray' dipakai",
              "Bray" in page.text_content("#profileName"),
              page.text_content("#profileName"))
        check("stale-id: kas profil Bray Rp4.000.000 tampil",
              "4.000.000" in cash_text(page), cash_text(page))
        check("stale-id: holding BTC profil Bray tampil",
              "BTC" in page.text_content("#holdingsList"),
              page.text_content("#holdingsList")[:120])
        page.fill("#amountInput", "100000")
        page.wait_for_selector("#previewBox:not([hidden])", timeout=5000)
        page.click("#tradeBtn")
        page.wait_for_selector("#confirmBox:not([hidden])", timeout=5000)
        page.click("#confirmYes")
        page.wait_for_function("() => document.getElementById('cashBalance').textContent.includes('3.900.000')", timeout=5000)
        check("stale-id: trade jalan setelah pulih (kas Rp3.900.000)",
              "3.900.000" in cash_text(page), cash_text(page))
        check("0 error JS (stale-id)", len(errors) == 0, "; ".join(errors[:3]))
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
                test_lev_chips_narrow(pw)
                test_sell_max(pw)
                test_dust_sell_zero_holdings(pw)
                test_tab_switch_clears_input(pw)
                test_profile_name_escaped(pw)
                test_overlapping_confirms(pw)
                test_id_number_format(pw)
                test_id_rp_prefix(pw)
                test_enter_key(pw)
            if which in ("posoverlap", "all"):
                test_position_row_no_overlap_narrow(pw)
            if which in ("posdesk", "all"):
                test_position_row_no_overlap_desktop(pw)
            if which in ("marketwrap", "all"):
                test_market_row_no_wrap_narrow(pw)
            if which in ("statbreak", "all"):
                test_stat_value_no_break_narrow(pw)
            if which in ("chartlabels", "all"):
                test_chart_labels_no_overlap_narrow(pw)
            if which in ("resetarmed", "all"):
                test_reset_armed_profile_switch(pw)
            if which in ("profilectx", "all"):
                test_profile_switch_clears_trade_context(pw)
            if which in ("microsell", "all"):
                test_micro_sell_quick(pw)
            if which in ("offline", "all"):
                test_offline(pw)
                test_topbar_offline_narrow(pw)
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
                test_stale_confirm_tolerance(pw)
                test_offline_confirm_cancelled(pw)
            if which in ("panelmark", "all"):
                test_panel_mark_offline(pw)
            if which in ("futerr", "all"):
                test_fut_error_no_repeat_scroll(pw)
            if which in ("tradescap", "all"):
                test_trades_cap(pw)
            if which in ("marketfocus", "all"):
                test_market_row_no_focus_jump(pw)
            if which in ("focusrefresh", "all"):
                test_focus_kept_on_refresh(pw)
            if which in ("coinctx", "all"):
                test_coin_switch_clears_trade_context(pw)
            if which in ("pendinghide", "all"):
                test_pending_cleared_on_hide(pw)
            if which in ("multitab", "all"):
                test_multitab_sync(pw)
                test_multitab_snapshot_keeps_context(pw)
            if which in ("welcomefocus", "all"):
                test_welcome_no_autofocus_mobile(pw)
                test_welcome_behind_overlay(pw)
                test_double_enter_profile(pw)
            if which in ("quickzero", "all"):
                test_quick_zero_feedback(pw)
            if which in ("invalidinput", "all"):
                test_invalid_input(pw)
            if which in ("quickdot", "all"):
                test_quick_dot_decimal(pw)
            if which in ("chartrefetch", "all"):
                test_chart_refetch_10min(pw)
                test_chart_refetch_fail_keeps_live_series(pw)
            if which in ("emptyinput", "all"):
                test_empty_input_stays_silent(pw)
            if which in ("menushort", "all"):
                test_profile_menu_short_viewport(pw)
            if which in ("staleid", "all"):
                test_stale_active_profile_id(pw)
    finally:
        srv.shutdown()
    failed = [r for r in results if not r["ok"]]
    print(f"\n=== RINGKASAN: {len(results)-len(failed)}/{len(results)} lolos, {len(failed)} gagal ===")
    for r in failed:
        print("GAGAL:", r["name"], "—", r["detail"])
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
