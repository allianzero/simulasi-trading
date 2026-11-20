# SIMULASI TRADING

Game simulasi trading crypto dengan uang virtual **Rp5.000.000**.
Bahasa Indonesia, mobile-first, statis murni (HTML + CSS + JS), tanpa backend
dan tanpa API key. Semua data (saldo, kepemilikan, riwayat, grafik) tersimpan
di `localStorage` browser.

## Cara menjalankan lokal

```bash
cd ~/workspace/simulasi-trading
python3 -m http.server 8000
```

Lalu buka http://localhost:8000 di browser.

## Fitur

- **Harga live (IDR)** dari CoinGecko public API (tanpa key), auto-refresh tiap
  30 detik + tombol Refresh. Menampilkan harga per koin dan perubahan 24 jam.
- **Aset:** BTC, ETH, BNB, SOL, XRP, DOGE, ADA, TRX.
- **Beli & jual:** masukkan Rupiah (beli) atau jumlah koin (jual), ada tombol
  cepat 25% / 50% / 75% / Maks, pratinjau hitungan, dan konfirmasi sebelum
  eksekusi. Beli dibatasi saldo kas, jual dibatasi koin yang dimiliki.
- **Portofolio:** saldo kas, total nilai, untung/rugi vs modal awal
  Rp5.000.000 (Rupiah + persen), kepemilikan per koin dengan harga beli
  rata-rata dan untung/rugi per koin.
- **Grafik** nilai total portofolio dari waktu ke waktu (canvas, data dari
  riwayat nilai yang disimpan berkala).
- **Riwayat transaksi** dengan hapus per item, dan tombol **Reset Simulasi**
  (kembali ke modal Rp5.000.000, dengan konfirmasi).

## Sumber harga & batasan

- Harga: `https://api.coingecko.com/api/v3/simple/price?...&vs_currencies=idr&include_24hr_change=true`
  (CoinGecko public API, gratis, tanpa key; ada batas rate API publik).
- **Jika fetch gagal (offline / CoinGecko tidak terjangkau):** aplikasi memakai
  harga contoh dan menampilkannya dengan label tegas
  **"HARGA CONTOH (OFFLINE)"** — harga contoh tidak pernah disajikan
  seolah-olah harga live.
- Ini uang virtual: bukan trading sungguhan, tidak ada uang asli yang terlibat,
  dan hasil simulasi bukan saran investasi.

## File

- `index.html` — struktur halaman
- `styles.css` — tema gelap ala aplikasi trading
- `app.js` — seluruh logika (harga, trading, portofolio, grafik, riwayat)
- `README.md` — file ini
