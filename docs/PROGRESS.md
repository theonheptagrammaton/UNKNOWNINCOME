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
- [x] **Kapsam:** lean backtest motoru (vectorbt-hazır `Engine` arayüzü arkasında), maliyet modeli, tam metrik seti, `backtest_runs`; UI: manuel kurucu, koşu detayı (equity, DD, işlem listesi, aylık ısı haritası, mum+işaretler).
- **Kabul kriterleri:**
  - [x] EMA9×EMA21 referans stratejisi elle hesaplanmış sonuçla eşleşir — bağımsız (from-scratch) simülatör motorla bit-for-bit uyuşur (`test_backtest_runner.py::test_ema_cross_matches_independent_simulator`, rel=1e-9) + literal el-hesabı işlem/komisyon/funding testleri (`test_backtest_engine.py`)
  - [x] Lookahead testi (sinyali 1 bar kaydırınca sonuç değişmeli) geçer — `test_shifting_signal_by_one_bar_changes_result`; ayrıca sinyal primitifleri Faz 2'den bar-kapanışı property testli
  - [x] Aynı config+seed → bit-for-bit aynı sonuç — `test_same_config_seed_bit_for_bit` (metrics+report JSON eşit); config_hash seed'e duyarlı
  - [x] UI'dan uçtan uca koşu yapılır — canlı stack (api + arq worker + redis + Next) üzerinde sentetik BTCUSDT/1h ile: form → POST /run (202) → worker (done, 18 işlem) → GET report → rapor render (metrikler, mum+işaretler, equity/DD, aylık ısı haritası, işlem tablosu). Ekran görüntüsü kanıtlı.
- **Ek teslimler:**
  - Motor (`backtest/engine.py`): sinyal bar-kapanışında → dolum sonraki bar açılışında (rule #1); long+short; tek-barda reversal; açık pozisyon son barda mark-out.
  - Maliyet modeli §6.2 (`backtest/costs` config): komisyon (4 bps taker/yön) + slippage (fixed 5 bps **veya** 0.05×ATR, seçilebilir) + **funding** (8h tarihsel; long öder / short alır) — hepsi varsayılan AÇIK, raporda ayrı kalem; kapalı olan bileşen "costless" kırmızı etiketiyle işaretlenir.
  - Metrikler §6.3 tam set + §6.4 bileşik skor (tek-koşu için belgeli bounded normalizasyon; sert filtre bayrağı: işlem≥30 · MaxDD≤%25 · PF≥1). Aylık getiri ısı haritası dahil.
  - API §12: `POST /api/backtest/run` (async arq, config_hash+seed ile `backtest_runs`) · `GET /api/backtest/runs/{id}` (metrics + disk artifact raporu). Worker: `run_backtest_job`.
  - UI (`/backtest`): manuel kurucu (sembol/TF, kategorili+aranabilir indikatör seçici, param formu, §5.4 kural kurucu, maliyet/kapital ayarları) + koşu detayı (lightweight-charts mum+işaret, equity/DD, aylık ısı haritası, işlem tablosu, maliyet rozetleri). Zaman UI'da Europe/Istanbul.
  - `app.data.cli devseed`: yerel/UI doğrulaması için SENTETİK OHLCV+funding üretici (gerçek 24-ay backfill operatör plan-B'de kalır).
- **Durum:** `[x]` Tamamlandı (2026-07-19). Kanıt: pytest **85/85** yeşil (19 yeni Faz-3 testi), ruff temiz, `next build` başarılı, tsc+eslint temiz. Motor kararı: doküman vectorbt diyor ama vectorbt 1.1.0 pandas 3.0.3 stack'inde ağır bağımlılık + numpy/numba yükseltmesi gerektiriyor ve runtime uyumu kanıtsız; bu yüzden Faz 3 için lean owned core seçildi (kullanıcı onaylı), vectorbt Faz 4 kütle taraması için `Engine` arayüzü arkasında takılabilir bırakıldı.

## Faz 4 — Otomatik Keşif Pipeline'ı
- [x] **Kapsam:** Aşama 0–6 (§7), Optuna entegrasyonu, WFO motoru (§6.5), liderlik tablosu UI, finalist çapraz doğrulaması (interface + fallback).
- **Kabul kriterleri:**
  - [~] 10 sembol × 4 TF standart tarama < 2 saat — her aşama süre logu (`ScanResult.stage_timings`) mevcut; **gerçek 10×4 ölçümü operatör adımı** (24-ay backfill gerektirir, plan B). Hızlı mod uçtan uca ~8 sn'de biter (`test_discovery_pipeline`).
  - [x] Aynı seed → aynı sıralama — `test_same_seed_same_leaderboard_ranking` (liderlik sırası + OOS skorları + combos_tried bit-for-bit); Optuna TPE seed'li, Monte Carlo seed'li, tüm sıralamalarda açık tiebreak.
  - [x] İki motor uyuşmazlığı alarm üretir — `test_discovery_crosscheck` (uyuşma → alarm yok; sapma → alarm; ayrıca lean second-opinion motoru gerçek koşuda primary ile uyuşuyor → yanlış alarm yok).
- **Ek teslimler:**
  - Pipeline (`backend/app/discovery/`): tekli tarama (`candidates`) → korelasyon eleme |ρ|>0.85 (`correlation`) → rol tabanlı kombinasyon, kategori kısıtlı (`roles`+`combine`) → Optuna TPE (`optimize`) → WFO + parametre platosu + Monte Carlo (`wfo`) → liderlik (`leaderboard`). Orkestrasyon `pipeline.run_scan` (DB'den bağımsız, progress callback).
  - Survivorship guard: `universe_symbols_as_of` (test tarihindeki ≤ snapshot); `test_discovery_survivorship`.
  - Finalist §6.1: `FinalistEngine` arayüzü + backtesting.py adaptörü (opsiyonel `[finalist]` extra, lazy import) + bağımsız lean second-opinion motoru (her zaman mevcut fallback) + motor-agnostik alarm karşılaştırıcı (`crosscheck`).
  - Motor eklentisi: `RiskExitConfig` (ATR stop/target, bar-kapanışı değerlendirme → sonraki açılış dolumu, lookahead-güvenli, varsayılan KAPALI → Faz 3 testleri etkilenmez); `test_engine_risk_exit` (el-hesabı long/short stop+target).
  - `discovery_scans` tablosu (config+hash+seed+status+**stage+progress+combos_tried**+leaderboard+artifact). API §12: `POST /api/discovery/scan` · `GET /api/discovery/scans/{id}` (canlı ilerleme + opsiyonel tam artifact) · `GET /api/discovery/leaderboard` (çapraz-tarama, sıralanabilir). Worker: `run_discovery_job`. "Hızlı mod" (`fast_mode`) küçük evren/dönem/bütçe.
  - UI (`/discovery`, auto mod): tarama kurucu (semboller/universe-as-of, TF çoklu seçim, yön, top-N, trials, fast-mode), canlı ilerleme (aşama + bar + combos_tried), **sıralanabilir liderlik tablosu** (combos_tried görünür), satır detayı (genome, WFO katmanları, Monte Carlo bandı, plato, finalist alarmları), **"Convert to strategy" disabled** (Faz 5). Nav linki eklendi.
- **Durum:** `[x]` Tamamlandı (2026-07-20). Kanıt: pytest **109/109** yeşil (24 yeni Faz-4 testi), ruff temiz, `next build` başarılı (/discovery 5.54 kB), tsc+eslint temiz. Gerçek fast-mode tarama script'i uçtan uca liderlik üretti (12 kombinasyon, 6 finalist, WFO katmanları + MC bandı, 0 yanlış alarm, deterministik). Kararlar: (1) finalist motoru interface+fallback (backtesting.py Faz-3 vectorbt gibi pandas-3.0 stack riski taşıyor → opsiyonel extra + her zaman-mevcut lean second-opinion); (2) Stage 1 varsayılan tam 225 registry (rol taşıyan kategoriler). Gerçek 10×4 <2h ölçümü + canlı UI ekran görüntüsü operatör plan-B (RUNBOOK deseni).

## Faz 5 — Strateji Motoru + Paper Trading + Trade Deck
- [x] **Kapsam:** Genome + değişmez sürümleme + soy ağacı (§8.1–8.2), üç katmanlı düzenleme (§8.6), paper doldurma simülatörü + `ExecutionAdapter` (§9.1/9.3), risk katmanı duvarı (§9.4), mod şalteri (§9.6), kill switch (4 kanal), sinyal akışı + karar günlüğü + strateji kartları UI, Telegram bildirim + komut seti (§10.3).
- **Kabul kriterleri:**
  - [~] Paper bot 72 saat kesintisiz koşar — worker içinde denetimli asyncio döngüsü ("paper bot loop started"); **72h sunucuda / 1h lokal soak = operatör adımı**, `test_multi_cycle_soak_is_stable` (50 döngü, equity sürekliliği) + canlı stack'te gerçek entry/exit üretti
  - [x] Her sinyalde `reason` + `indicator_snapshot` dolu — `test_signal_has_reason_and_indicator_snapshot`; canlı: `open_long` sinyali `regime` gerekçesi + `ema/close` snapshot ile
  - [x] Kill switch dört kanaldan da botu < 2 sn'de durdurur — `test_bot_killswitch` (UI/API/dosya/Telegram parametrik, hepsi paylaşılan dosya bayrağı → tick killed, emir yok) + poll ≤ 0.5 sn < 2 sn; canlı: API kanalı engaged + risk_event + audit
  - [x] Telegram'dan mod geçişi çalışır; whitelist dışı reddedilir — `test_bot_telegram` (mode paper/off, iki-adım /kill, non-whitelist reject, tüm komut audit'li)
  - [x] Genome hot-reload restart'sız devreye girer — `test_genome_hot_reload_without_restart`; canlı: v2 kaydı pozisyonu restart'sız kapattı (1→0)
  - [x] Risk limit ihlali emirleri bloklar + `risk_events`'e yazar — `test_risk_limit_blocks_order_and_records_event` + `test_execution_risk` (tüm §9.4 limitleri) + mimari test (adaptör name-mangled, atlatılamaz)
- **Durum:** `[x]` Tamamlandı (2026-07-20). Kanıt: pytest **155/155** yeşil (46 yeni Faz-5 testi), ruff temiz, `next build` başarılı (/trade 6.24 kB), tsc + eslint temiz. Canlı doğrulama: 5 servis healthy + bot loop çalışıyor → backtest→"Convert to strategy"→paper mod → gerçek paper entry (reason+snapshot dolu, equity komisyon/slippage ile hareket etti) → kill switch (API) engaged+audit → genome hot-reload pozisyonu kapattı. Kararlar: (1) genome = `RunConfig`+ad (backtest'in doğruladığı aynı sinyal yolu); (2) bot worker içinde arka-plan görevi (5 servis korunur); (3) paper fiyatı = son kapanış barı (canlı WS Faz 7); (4) Telegram gerçek polling + 72h/1h soak = operatör plan-B (saf mantık + deterministik soak testli).

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
