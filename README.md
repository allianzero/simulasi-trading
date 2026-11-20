# SIMULASI TRADING

Game simulasi trading crypto dengan uang virtual **Rp5.000.000**.
Bahasa Indonesia, mobile-first, statis murni (HTML + CSS + JS), tanpa backend
dan tanpa API key. Semua data tersimpan di `localStorage` browser.

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
- **Spot — beli & jual:** masukkan Rupiah (beli) atau jumlah koin (jual), ada
  tombol cepat 25% / 50% / 75% / Maks, pratinjau hitungan, dan konfirmasi 2
  langkah sebelum eksekusi. Beli dibatasi saldo kas, jual dibatasi koin yang
  dimiliki.
- **Futures:** posisi Long/Short dengan leverage 1x–100x (maksimal 100x),
  harga likuidasi, PnL live + ROE, dan likuidasi otomatis (lihat rumus di bawah).
  Setiap kartu posisi terbuka menampilkan PnL live (Rupiah + persen terhadap
  margin, hijau kalau untung, merah kalau rugi) dan harga mark saat ini;
  PnL ikut berubah setiap harga diperbarui (tiap 30 detik / tombol Refresh).
  Slider leverage ramah sentuhan (jempol besar 32px, area sentuh 44px),
  chip cepat 5x / 10x / 25x / 50x / 100x, dan tombol Buka Posisi selalu
  memberi umpan balik jelas: bila margin kosong atau tidak valid, muncul
  pesan error yang diguncang + digulir ke layar, beserta toast.
- **Grafik harga koin (24 jam):** di seksi Futures, grafik harga koin yang
  dipilih dari CoinGecko `market_chart` (24 jam, IDR) dan ikut bergerak
  setiap harga live diperbarui (tiap 30 detik). Saat ada posisi futures
  terbuka untuk koin itu, grafik menampilkan garis harga entry (hijau untuk
  Long, merah untuk Short), garis harga likuidasi (merah putus-putus), dan
  garis harga mark saat ini (putus-putus). Bila CoinGecko tidak terjangkau,
  grafik memakai deret contoh sintetis dan diberi label tegas
  "Grafik contoh (offline)".
- **Akun Guest:** sampai 5 profil, masing-masing dengan data simulasi sendiri
  (kas, kepemilikan spot, posisi futures, riwayat, grafik). Tanpa password,
  tanpa daftar, tanpa server.
- **Portofolio:** saldo kas, total nilai (kas + nilai koin spot + margin
  futures + PnL mengambang), untung/rugi vs modal awal Rp5.000.000 (Rupiah +
  persen), kepemilikan per koin dengan harga beli rata-rata dan untung/rugi
  per koin.
- **Grafik** nilai total portofolio dari waktu ke waktu (canvas, data dari
  riwayat nilai yang disimpan berkala), dengan garis acuan modal awal.
- **Riwayat transaksi** yang hanya bisa dibaca (tidak ada tombol hapus per
  item), dan tombol **Reset Simulasi** (kembali ke modal Rp5.000.000, dengan
  konfirmasi dua langkah).

## Rumus Futures (sederhana — tanpa maintenance margin dan tanpa fee)

- Ukuran posisi (notional) = margin × leverage
- Harga likuidasi:
  - Long = entry × (1 − 1/leverage)
  - Short = entry × (1 + 1/leverage)
- PnL mengambang:
  - Long = (mark − entry) / entry × notional
  - Short = (entry − mark) / entry × notional
- ROE = PnL / margin × 100%

Saat harga mark menyentuh atau melewati harga likuidasi (diperiksa setiap
kali harga diperbarui — tiap 30 detik atau saat tombol Refresh ditekan),
posisi ditutup otomatis, margin hangus, dan tercatat di riwayat sebagai
LIQUIDATED. Saat posisi ditutup manual, margin + PnL kembali ke saldo kas;
PnL negatif dibatasi sampai −margin, jadi kas tidak bisa minus karena satu
posisi.

**PnL live & aturan offline:** PnL posisi TIDAK PERNAH dihitung dari harga
contoh offline (harga contoh BTC Rp1.500.000.000 jauh dari harga live
~Rp1.124.000.000 — pernah membuat posisi tes terlikuidasi). Saat harga live
putus, PnL dibekukan di nilai terakhir dari harga live dengan label
"(harga live terakhir)"; bila belum pernah ada harga live sama sekali, PnL
ditampilkan "—". Aturan yang sama berlaku untuk PnL mengambang di total
portofolio dan untuk pemeriksaan likuidasi — selama offline tidak ada posisi
yang terlikuidasi oleh harga contoh.

Contoh: margin Rp100.000, leverage 10x, Long BTC entry Rp1.000.000.000 →
notional Rp1.000.000, likuidasi Rp900.000.000. Bila harga mark naik ke
Rp1.100.000.000 → PnL +Rp100.000 (ROE +100%).

## Akun Guest

Saat pertama kali dibuka, aplikasi menampilkan layar sambutan dengan kolom
nama panggilan (opsional) dan tombol "Masuk sebagai Guest". Bila nama
dikosongkan, nama otomatis jadi "Guest" + 4 angka acak (mis. Guest-4821).
Profil baru selalu mulai dari modal awal Rp5.000.000. Ganti atau buat profil
baru dari menu profil di header (maksimal 5 profil). Tidak ada tombol hapus
profil.

Migrasi data lama: data simulasi dari versi sebelum fitur profil (format
lama tanpa profil) otomatis dipindahkan menjadi profil pertama bernama
"Guest", agar data pengguna yang sudah berjalan tidak hilang.

## Sumber harga & batasan

- Harga: `https://api.coingecko.com/api/v3/simple/price?...&vs_currencies=idr&include_24hr_change=true`
  (CoinGecko public API, gratis, tanpa key; ada batas rate API publik).
- Grafik harga koin: `https://api.coingecko.com/api/v3/coins/{id}/market_chart?vs_currency=idr&days=1`
  (gratis, tanpa key). Diambil sekali per koin lalu di-cache di memori
  (tidak disimpan ke localStorage); harga terbaru ditambahkan ke grafik
  setiap poll harga 30 detik. Bila fetch gagal, grafik memakai deret contoh
  sintetis (random walk dari harga contoh) dan diberi label tegas
  "Grafik contoh (offline)".
- **Jika fetch gagal (offline / CoinGecko tidak terjangkau):** aplikasi memakai
  harga contoh dan menampilkannya dengan label tegas
  **"HARGA CONTOH (OFFLINE)"** — harga contoh tidak pernah disajikan
  seolah-olah harga live.
- Ini uang virtual: bukan trading sungguhan, tidak ada uang asli yang terlibat,
  dan hasil simulasi bukan saran investasi.

## File

- `index.html` — struktur halaman (Spot, Futures, profil Guest, toast, layar sambutan)
- `styles.css` — tema gelap profesional ala aplikasi trading
- `app.js` — seluruh logika (harga, trading Spot, Futures, likuidasi, profil, grafik, riwayat)
- `README.md` — file ini
