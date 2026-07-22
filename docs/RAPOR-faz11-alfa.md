# RAPOR — Faz 11: Alfa Yüzeyini Genişletme

> **Yalnızca OHLCV'den çıkarılan edge dünyanın en kalabalık avlanma alanıdır (§25.1).**
> 225 indikatörün tamamı aynı beş sayının (O,H,L,C,V) türevidir; yeni bir *sayı* eklemek
> yeni bir indikatör eklemekten kat kat değerlidir. Faz 11 alfa yüzeyini OHLCV dışına
> açar: bedava taker akışı, açık pozisyon (OI), funding **değişimi** ve likidasyon akışı.
>
> **Kural (pazarlıksız, §25.4):** Yeni veri MUAFİYET DEĞİLDİR. Dört yeni primitif
> registry'ye **normal indikatör gibi** girer, keşif hattından **normal gibi** geçer ve
> Faz 9 deflasyon kapısına **normal gibi** takılır. Hiçbirine özel (gevşetilmiş) gate
> eşiği tanımlanmadı.
>
> **Kural 13 (pazarlıksız):** Sentetik veri hiçbir kabul kriterini kapatmaz. Aşağıdaki
> kriterler saf/birim/gürültü testleriyle kanıtlandı; **24 aylık gerçek yeniden-indirme
> ve canlı OI/funding/likidasyon sayıları operatör sunucu adımıdır**.

Tarih: 2026-07-22 · Branch: `main` · Motor testleri: **336 passed** (+33 yeni Faz-11),
ruff temiz.

---

## 1. Teslim edilen kod

### 1.1 Bedava katman — taker akışı (§25.2)

Binance kline yanıtı `taker_buy_base_volume` ve `number_of_trades` alanlarını zaten
gönderiyordu; ccxt onları atıyordu. Artık **opsiyonel arka OHLCV kolonları**:

| Bileşen | Dosya | Değişiklik |
|---|---|---|
| Parquet şeması | `data/parquet_store.py` | `OHLCV_TAKER_COLUMNS` opsiyonel; 6-kolon eski dosya + 8-kolon yeni yazım birleşince eski satırların taker alanı NaN kalır (hiç yoktu). `ohlcv_rows_to_frame` 6/8 genişliği taşır. |
| Adapter | `data/adapters/binance_usdm.py` | `fetch_ohlcv` artık ham `fapiPublicGetKlines`'ı çağırıp taker kolonlarını haritalar; endpoint yoksa 6-kolona düşer. |
| DuckDB | `data/duckdb_query.py` | `query_ohlcv(include_extended=True)` taker kolonlarını ekler; eski dosyada yoksa `NULL` (→ NaN) — kararlı şema. |
| Sync | `data/sync.py` (dokunulmadı; genişlik taşıyıcı) + `data/cli.py devseed` taker + sentetik OI üretir. |

**Not:** Kural 13 gereği 24 aylık geçmiş bu iki kolon için **operatör tarafından yeniden
indirilir** (eski parquet'lerde yoklar). Şema ve indirici hazır; sayı operatör adımı.

### 1.2 Açık pozisyon (OI) toplayıcısı (§25.3)

`data/collectors/open_interest.py` — 5 dk REST poll, OHLCV ile **aynı gap disiplini**:

- `oi_row` (saf): ccxt `fetch_open_interest` → 5 dk ızgaraya hizalı Parquet satırı;
  `open_interest_value` yoksa NaN.
- `scan_gaps`: OI serisindeki iç boşluklar `find_gaps(OI_TF)` ile (OHLCV'yle birebir kural).
- `run_oi_collector`: enjekte edilebilir `fetch`/`sleep`/`now_ms` — dirençli; **bir sembol
  hata verirse loglanır ve atlanır**, döngü diğerlerini pollamaya devam eder.
- Parquet: `open_interest.parquet` `[ts, open_interest, open_interest_value]`.
- Worker startup'ında (`OPEN_INTEREST_COLLECTOR_ENABLED`) **veya** `python -m
  app.data.collectors.open_interest`.

### 1.3 Funding: seviye değil DEĞİŞİM + kendi tarihsel yüzdeliği (§25.3)

Yeni koleksiyon değil — mevcut `funding.parquet`'ten türetme. `funding_extreme` primitifi
native (seyrek, 8h) funding serisinde Δfunding'i **genişleyen (expanding) yüzdelik** ile
sıralar (yalnız ≤t → lookahead-güvenli, ucuz), sonra bar ızgarasına backward-as-of hizalar.

### 1.4 Likidasyon sorgulanabilir + primitif verisi (§25.3)

Faz 8'in likidasyon toplayıcısı (systemd/reconnect/`dedup_key UNIQUE`) **korundu**. Faz 11
onu sorgulanabilir + kullanılabilir yaptı (`data/alpha.py`):

- `query_liquidations` (async) — ham olayları okur ("artık sorgulanabilir").
- `aggregate_liquidations` (async) — olayları **dakikalık notional** kovalarına katlar
  (`liquidations.parquet`), dedup sayesinde idempotent (keep-last).
- `liq_notional_aligned` (sync/DuckDB) — dakikalık kovaları hedef bar ızgarasına toplar;
  **compute yolunda canlı DB sürücüsü yok** (tüm alfa yüzeyiyle tutarlı).
- Worker cron'u (`aggregate_liquidations_job`, 5 dk) son 6 saati yeniden hesaplar.

> **Sürücü kararı:** Ortamda senkron Postgres sürücüsü yok (yalnız `asyncpg`). Plan'da
> açıkça sunduğum alternatif — likidasyonları periyodik parquet'e toplayıp DuckDB ile
> okumak — uygulandı; bu, indikatör katmanını DB bağımlılığından da arındırır.

### 1.5 Dört sinyal primitifi (`indicators/custom/`, §25.4)

Bağlam `compute_indicator`'da `ohlcv.attrs`'e (market/symbol/tf) yazılır; yardımcı
`custom/_alpha.py` (loader `_`-önekini atlar) aux serileri lookahead-güvenli getirir.
Primitifler önce açık `df` kolonunu kullanır (birim testler depo istemez), üretimde
`_alpha`'ya düşer.

| Primitif | Kategori→Rol | Girdi | Çıktı | Parametreler (numerik, Optuna tarar) |
|---|---|---|---|---|
| `flow_imbalance` | momentum→trigger | taker_buy, volume | window-ort. `(2·taker−vol)/vol` | window · threshold · dir |
| `oi_divergence` | volume→filter | close, open_interest | {−1,0,+1} fiyat–OI ayrışma | price_dir · oi_dir |
| `funding_extreme` | statistic→filter | funding_rate | Δfunding uç yüzdelik işareti | percentile · dir |
| `liq_cascade` | momentum→trigger | liq notional/bar | trailing-window net (eşikli) | window · usd_threshold |

`dir`/`price_dir`/`oi_dir` sayısal kategorik olarak kodlandı (ParamSpec sayısal). Hiçbiri
`OSCILLATOR_LEVELS`'e eklenmedi → hepsi genel `slope` yolundan geçer (özel eşik yok).

---

## 2. Kabul kriterleri — tek tek kanıt

| # | Kriter (§25.5) | Durum | Kanıt |
|---|---|---|---|
| 1 | `taker_buy_base_volume` + `number_of_trades` Parquet şemasında; 24 ay yeniden indirilir | ✅ kod · veri operatör adımı | `test_kline_taker_columns.py` (6 test): şema, geriye dönük NaN okuma, legacy+extended merge, sync taşıma |
| 2 | OI toplayıcısı 5 dk yazıyor; gap taraması OHLCV disiplininde | ✅ | `test_open_interest_collector.py` (4 test): 5 dk ızgara yazımı, atlanan poll → gap, hatalı sembol atlanır |
| 3 | Likidasyon toplayıcısı systemd/reconnect/`dedup_key UNIQUE` | ✅ (Faz 8, korundu) + sorgulanabilir | `test_liquidation_collector.py` (Faz 8) + `test_alpha_query.py` (6 test): sorgu + dakikalık toplama + hizalama |
| 4 | Dört primitif birim testli **ve lookahead-güvenli** (Faz 2 property test deseni) | ✅ | `test_alpha_primitives.py` (17 test): doğruluk + "geleceği değiştir, geçmiş sabit" property testi × 4 |
| 5 | Yeni primitiflerle koşulan tarama gürültü testinden geçiyor (kural 15) | ✅ | `test_noise_pipeline.py::test_alpha_primitives_over_noise_yield_zero_candidates` — **0 aday**; gate primitif-kombinlerini aktif reddetti |

### 2.1 Gürültü testi çıktısı (kural 15)

`python -m scripts.noise_test --alpha` — dört primitif + gürültü OI/funding/likidasyon:

```
Faz 11 alpha primitives — noise test · 2 symbol(s) × 1h · 1500 bars · seed 42
  pipeline: 16 combos tried, 6 finalists, 0 candidate(s) after gate
  ✓ PASS — zero candidates from noise.
    rejected liq_cascade+funding_extreme+atr:   DSR 0.258 < 0.95 · OOS trades 9 < 30
    rejected flow_imbalance+funding_extreme+bbands: DSR 0.000 < 0.95
```

Gürültüden aday çıkmadı; primitifler gerçekten kombine edildi ve **aynı** Faz 9 kapısında
reddedildi — yeni veri muafiyet değil.

---

## 3. Yeni config parametreleri (kural 19)

Aynı commit'te `docs/PROJE_DOKUMANI-v2.md` §28.2 **Kuşak 6**'ya üç satırla yazıldı ve
`.env.example`'a eklendi:

- `open_interest_collector_enabled` (kapalı) — OI 5 dk toplayıcısını worker'da başlatır.
- `open_interest_poll_seconds` (300) — OI çekim sıklığı (5 dk ızgara).

---

## 4. Sınırlar ve operatör adımları

- **Gerçek sayı yok (kural 13):** 24 aylık taker yeniden-indirme, canlı OI/funding
  toplama ve likidasyon birikimi operatör sunucu adımıdır. Bu fazda kod + sentetik/birim
  + gürültü kanıtı tamamlandı.
- **liq_cascade gürültü testinde:** izole store'a gürültü likidasyon barları da yazıldı,
  böylece dördü de gürültü üzerinde çalıştı.
- **Cache notu:** `compute_indicator` OHLCV tazeliğine göre cache'ler; OI/funding/liq
  bağımsız güncellenirse toplu keşif bağlamında sorun değil (veri önce backfill, sonra
  taranır).
- **Frontend'e dokunulmadı** (§25 UI istemiyor).

---

## 5. Dosya özeti

**Yeni:** `data/collectors/open_interest.py` · `data/alpha.py` ·
`indicators/custom/{_alpha,flow_imbalance,oi_divergence,funding_extreme,liq_cascade}.py` ·
`tests/{test_kline_taker_columns,test_open_interest_collector,test_alpha_primitives,test_alpha_query}.py`

**Değişen:** `data/parquet_store.py` · `data/duckdb_query.py` · `data/timeframes.py` ·
`data/adapters/{base,binance_usdm}.py` · `data/cli.py` · `indicators/compute.py` ·
`indicators/registry.py` · `core/config.py` · `workers/main.py` · `scripts/noise_test.py` ·
`tests/{test_noise_pipeline,test_indicator_registry}.py` · `.env.example` ·
`docs/PROJE_DOKUMANI-v2.md` (§28.2 Kuşak 6)
