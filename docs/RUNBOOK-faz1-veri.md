# RUNBOOK — Faz 1 Veri Yükleme (Sunucu)

Bu dosya **senin sunucuda elle yapacağın** adımları anlatır. Kod + testler hazır
ve yeşil; burada yaptığın tek şey **gerçek 24 aylık veriyi Binance'ten çekmek**
(plan B). Her komut kopyala-yapıştır; ne yaptığını yanında açıkladım.

> Konum: repo kökü (`docker-compose.yml`'in olduğu dizin). Tüm komutlar orada çalışır.

---

## 0) Ön koşullar (bir kez)

- Sunucuda **Docker + Docker Compose** kurulu.
- Repo klonlanmış, `main` güncel.
- **Disk:** 10 sembol × 6 TF × 24 ay ≈ **~1–2 GB** (çoğu 1m verisi). `df -h` ile boş alanı gör.
- **Ağ:** Sunucudan **Binance USDT-M API'ye erişim** şart (aşağıda test var). Bazı
  bölgelerden (ör. ABD) coğrafi engel olabilir.
- **Binance API anahtarı GEREKMEZ** — yalnızca public veri çekiyoruz. (Anahtarlar
  Faz 7 canlı emir içindir.)

## 1) `.env` hazırla (bir kez)

```bash
cp .env.example .env
```

Faz 1 için değiştirmen **zorunlu değil** — varsayılanlar çalışır. İstersen
`POSTGRES_PASSWORD` ve `SECRET_KEY`/`ENCRYPTION_KEY` alanlarını gerçek değerlerle
doldur (üretim hijyeni). `BINANCE_*` alanlarını **boş bırakabilirsin**.

Piyasa verisi `/data/parquet` içinde `parquet_data` adlı Docker volume'unda durur —
konteyner silinse de veri kalır.

## 2) Servisleri başlat

```bash
export GIT_SHA=$(git rev-parse --short HEAD)   # /api/health'te görünür (opsiyonel)
docker compose up --build -d
docker compose ps                              # 5 servis de "healthy" olmalı
```

Beklenen: `postgres · redis · api · worker · frontend` → hepsi `healthy`.
DB tabloları (`symbols`, `candle_sync_state`, `universe_snapshots`) API açılışında
otomatik oluşur.

## 3) Binance erişimini doğrula (coğrafi engel kontrolü)

İlk komut olarak **evren kurucuyu** çalıştır — bu zaten Binance'e gider, yani
erişim testini de yapar:

```bash
docker compose run --rm api python -m app.data.cli universe
```

- **Başarılıysa:** `universe 2026-07-18: 30 symbols` ve sembol listesi basar,
  `universe_snapshots` tablosuna **tarihli snapshot** yazar (survivorship guard).
- **Hata verirse** (`Connection`/`451`/`403` gibi): Binance sunucundan **engelli**.
  Çözüm: VPN/proxy ya da erişimi olan bir sunucu bölgesi. (Testnet **işe yaramaz** —
  o yalnız canlı emir içindir, geçmiş veri mainnet public'ten gelir.)

## 4) 24 aylık geçmişi indir (asıl adım)

Evren kurulduysa, **evrenin ilk 10 sembolü** için tam yükleme:

```bash
docker compose run --rm api python -m app.data.cli backfill --months 24
```

Bu ne yapar:
- Varsayılan **son universe snapshot'ının top-10 sembolü** × **6 TF**
  (1m,5m,15m,1h,4h,1d) × **24 ay** OHLCV + **funding** geçmişini çeker.
- Her sembol×TF sonrası **gap taraması + onarımı** yapar, `candle_sync_state`'i günceller.
- İlerledikçe satır satır durum basar: `BTCUSDT 1h: rows=17300 missing=0`.

**Belirli sembolleri** vermek istersen:

```bash
docker compose run --rm api python -m app.data.cli backfill \
  --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT \
  --timeframes 1m 5m 15m 1h 4h 1d \
  --months 24
```

Notlar:
- **Süre:** ~30–90 dk (çoğu 1m; ccxt hız limitine uyar).
- **Sürdürülebilir:** kesilirse **aynı komutu tekrar çalıştır** — artımlı devam eder,
  var olanı yeniden indirmez.
- **Funding** varsayılan açık; kapatmak için `--no-funding` ekle.
- **RAM:** 1m derin yükleme bellek ister; semboller sırayla işlenir.

## 5) Bütünlüğü doğrula (kabul kriteri: gap=0)

```bash
docker compose run --rm api python -m app.data.cli status
```

Her satırda **`gaps=0`** görmelisin. `missing` sütunu da 0 olmalı. Ayrıca HTTP ile:

```bash
curl -s http://localhost:8000/api/data/status | python3 -m json.tool
```

`summary.total_missing == 0` → bütünlük tamam. (Bir borsanın listeleme öncesi
gerçekten var olmayan barları varsa, o aralık `gaps`'te kalıcı işaretlenir; bu bir
hata değil, verinin gerçeği.)

## 6) Otomatik güncelleme (kurulum gerektirmez)

`worker` konteyneri zaten cron çalıştırır:
- **Artımlı sync**: her 5 dakikada bir aktif evrenin yeni kapanmış barlarını çeker.
- **Evren yenileme**: haftalık (Pazartesi 00:05 UTC) yeni `universe_snapshots` yazar.

Yani ilk yüklemeden sonra veri kendini güncel tutar; ekstra bir şey yapmana gerek yok.

---

## Sorun giderme

| Belirti | Sebep / Çözüm |
|---|---|
| `universe`/`backfill` bağlantı hatası, `451`/`403` | Binance sunucudan coğrafi engelli → VPN/proxy ya da başka bölge. |
| `418`/`429` (rate limit) | ccxt hız limitine uyar; yine olursa birkaç dk bekle, backfill'i tekrar çalıştır (artımlı sürdürür). |
| İşlem kesildi / sunucu yeniden başladı | `backfill` komutunu tekrar çalıştır — kaldığı yerden devam eder. |
| Disk doluyor | `docker system df -v` ile `parquet_data` volume boyutunu izle; gerekirse TF sayısını/ayı azalt. |
| `status`'ta bazı `gaps` kalıyor | Aynı `backfill`'i tekrar çalıştır; kapanmayan aralık gerçekten borsada yoksa kalıcıdır (normal). |

## Veri nerede? Yedek

- Volume: **`parquet_data`** → konteyner içinde `/data/parquet/binance_usdm/{SYMBOL}/{tf}.parquet`.
- Uygulama durumu (sync state, evren snapshot'ları): **PostgreSQL** (`postgres_data` volume).
- Yedek: iki volume'u kopyala (`docker run --rm -v unknownincome_parquet_data:/d -v $PWD:/b alpine tar czf /b/parquet.tgz /d`).
