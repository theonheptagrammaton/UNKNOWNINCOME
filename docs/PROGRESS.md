# UNKNOWNINCOME — İlerleme Takibi (PROGRESS)

Fazlar ve kabul kriterleri: `docs/PROJE_DOKUMANI.md` §15. Kabul kriterleri geçilmeden sonraki faza başlanmaz.

**Durum lejantı:** `[ ]` başlamadı · `[~]` devam ediyor · `[x]` tamamlandı (kabul kriterleri kanıtlı)

---

## Faz 0 — İskelet ve Altyapı
- [x] **Kapsam:** Depo yapısı (§3.3), docker-compose (5 servis), FastAPI + Next.js merhaba-dünya, pytest + lint CI, `/api/health`.
- **Kabul kriterleri:**
  - [x] `docker compose up --build` ile 5 servisin tamamı ayakta ve **healthy** (postgres · redis · api · worker · frontend)
  - [x] `/api/health` 200 döner (version + git sha)
  - [x] Testler yeşil: pytest 2/2, ruff temiz, eslint temiz, `next build` başarılı; GitHub Actions CI (lint + test) tanımlı
- **Durum:** `[x]` Tamamlandı (2026-07-17). Kanıt: `docker compose up --build` → 5/5 healthy; `/api/health`→200; `/backtest` & `/trade`→200 (kendine özgü içerikle render); worker sağlığı Redis heartbeat ile doğrulandı. Not: worker healthcheck deseni = Redis heartbeat; api/frontend healthcheck'leri IPv4 (`127.0.0.1`) kullanır (konteyner-içi IPv6 `localhost` çözümü sorunundan kaçınmak için).

## Faz 1 — Veri Katmanı
- [x] **Kapsam:** ccxt/Binance USDT-M OHLCV + funding indirici, Parquet store + DuckDB, gap tespit/onarım, sync cron, `candle_sync_state`, dinamik evren + tarihli snapshot (§4.5).
- **Kabul kriterleri:**
  - [x] Evren kurucu top-30 listesi + tarihli snapshot üretir (`build_universe` testli; canlı Binance smoke ile doğrulandı)
  - [~] 10 sembol × 6 TF × 24 ay + funding serileri yüklü — mekanizma + CLI hazır; **gerçek yükleme operatör adımı** (plan B → `docs/RUNBOOK-faz1-veri.md`)
  - [x] Bütünlük testi gap=0 (backfill+repair testi; sentetik seride gap=0 kanıtlı, operatör `status` ile gerçek veride teyit eder)
  - [x] Tipik DuckDB aralık sorgusu < 1 sn (300k satırda testle ölçüldü)
- **Durum:** `[x]` Kod tamam, CI yeşil (pytest 23/23, ruff temiz), 5 servis healthy, canlı ccxt adaptörü doğrulandı (792 market, gerçek OHLCV+funding). Gerçek 24-ay backfill sunucuda `docs/RUNBOOK-faz1-veri.md` ile çalıştırılır (kullanıcı onaylı plan B).

## Faz 2 — İndikatör Registry
- [x] **Kapsam:** TA-Lib + pandas-ta birleşik registry (**225 benzersiz indikatör**), sinyal primitifleri (§5.4), hesap + Parquet cache, custom eklenti yükleyici.
- **Kabul kriterleri:**
  - [x] Tüm indikatörler örnek sembolde hatasız hesaplanır — toplu smoke test 225/225 (`test_indicators_smoke.py`)
  - [x] ≥ 10 çekirdek indikatör bilinen referans değerlerle birim testinden geçer — 11 talib (SMA/EMA/WMA/RSI/ATR/ROC/MOM/WILLR/OBV/STDDEV/BBANDS) + custom zscore, bağımsız numpy/pandas referansına karşı (`test_indicators_reference.py`)
  - [x] Cache isabeti loglanır — MISS→dosya yazımı, ikinci hesap HIT (kaynak dispatcher çağrılmaz), yeni bar cache'i bozar (`test_indicator_cache.py`)
- **Ek teslimler:**
  - Metadata şeması §5.3 (`IndicatorDef`: kategori, kaynak, inputs, param aralıkları, outputs, signal_templates) → `indicator_defs` tablosuna idempotent sync (uygulama lifespan'inde).
  - Sinyal primitifleri §5.4 (threshold_cross · line_cross · slope · band_touch · regime · pattern) — hepsi bar-kapanışı esaslı; lookahead-güvenliği gelecekteki barları değiştirip geçmişin sabit kaldığı property testiyle kanıtlı.
  - Cache anahtarı `(market, symbol, tf, indicator_id, params_hash)`; `_indicators/…parquet`; tazelik cached-vs-current bar kapsamıyla otomatik.
  - Custom eklenti yükleyici (`indicators/custom/`, auto-register) + örnek `zscore` indikatörü.
  - API: `GET /api/indicators` (kategori/kaynak filtresi) · `GET /api/indicators/{id}` (404) · `POST /api/indicators/compute` (önizleme, satır-kapaklı).
- **Durum:** `[x]` Tamamlandı (2026-07-18). Kanıt: pytest **66/66** yeşil (43 yeni), ruff temiz. TA-Lib 0.7.1 (prebuilt wheel, sistem C-lib gerekmez) + pandas-ta 0.4.71b0 (pandas 3.0 uyumlu fork). Kaynak dağılımı: talib=134, pandas_ta=90, custom=1. Not: pandas-ta `numba` çekerek numpy 2.5.1→2.2.6 sabitler; Faz 1 testleri etkilenmedi.

## Faz 3 — Backtest Çekirdeği + Backtest Lab v1 (manuel mod)
- [ ] **Kapsam:** vectorbt sarmalayıcı, maliyet modeli, tam metrik seti, `backtest_runs`; UI: manuel kurucu, koşu detayı (equity, DD, işlem listesi, mum+işaretler).
- **Kabul kriterleri:**
  - [ ] EMA9×EMA21 referans stratejisi elle hesaplanmış sonuçla eşleşir
  - [ ] Lookahead testi (sinyali 1 bar kaydırınca sonuç değişmeli) geçer
  - [ ] UI'dan uçtan uca koşu yapılır
- **Durum:** `[ ]` başlamadı

## Faz 4 — Otomatik Keşif Pipeline'ı
- [ ] **Kapsam:** Aşama 0–6 (§7), Optuna entegrasyonu, WFO motoru (§6.5), liderlik tablosu UI, backtesting.py finalist doğrulaması.
- **Kabul kriterleri:**
  - [ ] 10 sembol × 4 TF standart tarama < 2 saat
  - [ ] Aynı seed → aynı sıralama (bit-for-bit)
  - [ ] İki motor uyuşmazlığı alarm üretir
- **Durum:** `[ ]` başlamadı

## Faz 5 — Strateji Motoru + Paper Trading + Trade Deck
- [ ] **Kapsam:** Genome + sürümleme (§8.1), üç katmanlı düzenleme (§8.6), paper doldurma simülatörü, risk katmanı (§9.4), mod şalteri (§9.6), kill switch (4 kanal), sinyal akışı + karar günlüğü UI, Telegram bildirim + komut seti (§10.3).
- **Kabul kriterleri:**
  - [ ] Paper bot 72 saat kesintisiz koşar
  - [ ] Her sinyalde `reason` + `indicator_snapshot` dolu
  - [ ] Kill switch dört kanaldan da botu < 2 sn'de durdurur
  - [ ] Telegram'dan mod geçişi çalışır
  - [ ] Genome hot-reload restart'sız devreye girer
  - [ ] Risk limit ihlali simülasyonu emirleri bloklar
- **Durum:** `[ ]` başlamadı

## Faz 6 — Kendini Geliştirme v1
- [ ] **Kapsam:** Haftalık WFO re-opt zamanlayıcısı, bozulma tetikleyicileri (§8.5), yeni versiyon üretimi + insan onaylı terfi akışı, rejim etiketleme (§8.4).
- **Kabul kriterleri:**
  - [ ] Bozulma senaryosu simülasyonunda strateji otomatik pause olur
  - [ ] Yeni versiyon raporuyla birlikte onaya düşer
- **Durum:** `[ ]` başlamadı

## Faz 7 — Canlı Yürütme (kapının arkasında)
- [ ] **Kapsam:** Binance USDT-M futures adaptörü (isolated marj, kaldıraç tavanı, likidasyon tamponu), terfi kapısı (§9.5), mikro sermaye ile kontrollü açılış, canlı-paper sapma izleme.
- **Kabul kriterleri:**
  - [ ] Kapı eşiği sağlanmadan canlı emir yolunun çağrılamadığı testle kanıtlanır
  - [ ] İlk canlı işlemler mikro boyutta ve tam loglu gerçekleşir
- **Durum:** `[ ]` başlamadı

---

### Açık kararlar (doküman §16.2) — geliştirmeyi bloklamaz
| # | Karar | Bloklamayan varsayılan |
|---|---|---|
| 1 | İlk canlı piyasa cephesi | Binance USDT-M (testnet) |
| 2 | Kendini geliştirme mekanizması | v1: WFO re-opt |
| 3 | Piyasa verisi deposu | Parquet + DuckDB |
| 4 | Pozisyon boyutlama | ATR tabanlı |
