# RAPOR — Faz 3: Backtest Çekirdeği + Backtest Lab v1

Kapsam: `docs/PROJE_DOKUMANI.md` §6 + §15/Faz 3. Durum: **tamam** (2026-07-19).

## Ne yapıldı
- **Lean backtest motoru** (`backend/app/backtest/engine.py`) — sinyal bar
  kapanışında, dolum sonraki bar açılışında (pazarlıksız rule #1). Long + short,
  tek-barda reversal, açık pozisyon son barda mark-out. Saf aritmetik →
  deterministik (rule #6). `Engine` Protocol'ü vectorbt/backtesting.py'yi Faz 4'te
  aynı dikişten takmaya hazır bırakır.
- **Maliyet modeli §6.2** (varsayılan AÇIK): komisyon (4 bps taker/yön) +
  slippage (fixed 5 bps **veya** 0.05×ATR) + **funding** (8h tarihsel; long öder,
  short alır). Her biri raporda ayrı kalem; kapalı bileşen "costless" kırmızı
  etiketi. Funding okuyucu: `duckdb_query.query_funding`.
- **Metrikler §6.3** tam set + **§6.4 bileşik skor** (tek-koşu için belgeli
  bounded normalizasyon; sert filtre bayrağı işlem≥30 · MaxDD≤%25 · PF≥1). Aylık
  getiri ısı haritası dahil.
- **Kalıcılık + API §12**: `backtest_runs` tablosu (config + config_hash + seed +
  status + metrics + artifact_path). `POST /api/backtest/run` (async arq) →
  `run_backtest_job` worker → disk artifact (report.json). `GET /api/backtest/runs/{id}`
  metrics + raporu döner.
- **Backtest Lab UI** (`/backtest`, manuel mod): sembol/TF, kategorili+aranabilir
  indikatör seçici, param formu, §5.4 kural kurucu, maliyet/kapital ayarları;
  koşu detayı lightweight-charts ile mum+giriş/çıkış işaretleri, equity/drawdown,
  aylık ısı haritası, işlem tablosu, maliyet rozetleri. Zaman Europe/Istanbul.

## Kabul kriterleri — kanıt
| Kriter | Kanıt |
|---|---|
| EMA9×EMA21 = el hesabı | `test_ema_cross_matches_independent_simulator` (bağımsız simülatör ≡ motor, rel=1e-9) + literal işlem/komisyon/funding testleri |
| Lookahead: sinyal 1 bar kayınca sonuç değişir | `test_shifting_signal_by_one_bar_changes_result` |
| Aynı config+seed → bit-for-bit | `test_same_config_seed_bit_for_bit` (metrics+report JSON eşit) |
| UI'dan uçtan uca koşu + rapor | Canlı stack: form → POST /run (202) → worker (done, 18 işlem) → GET → rapor render (ekran görüntüsü kanıtlı) |

Toplam: **pytest 85/85**, ruff temiz, `next build` başarılı, tsc + eslint temiz.

## Motor kararı (doküman'dan sapma — kullanıcı onaylı)
Doküman §6.1 vectorbt'yi ana tarama motoru olarak veriyor. Ancak yerel stack
Python 3.13.9 · pandas 3.0.3 · numpy 2.2.6; kurulabilen tek sürüm vectorbt 1.1.0
ağır bağımlılık ağacı (matplotlib/scipy/scikit-learn/plotly/ipython) çekiyor ve
numpy→2.4.6 + numba→0.66 yükseltiyor (Faz 2 pinlerini bozar), pandas 3.0 runtime
uyumu kanıtsız, funding'i de native modellemiyor. Bu yüzden **Faz 3 için lean
owned core** seçildi; vectorbt Faz 4 kütle taraması için `Engine` arayüzü
arkasında takılabilir bırakıldı.

## Yerel doğrulama (operatör)
```bash
# 1) sentetik veri (gerçek 24-ay backfill = plan-B, RUNBOOK-faz1-veri.md)
python -m app.data.cli devseed --symbols BTCUSDT --tf 1h --bars 1500
# 2) docker compose up --build   (veya lokal: uvicorn + arq + next start)
# 3) http://localhost:3000/backtest → "Run backtest" → rapor
```
Not: `devseed` verisi SENTETİKTİR (güçlü döngüsel seri) — metrikler abartılıdır,
sadece uçtan-uca akışı göstermek içindir.
