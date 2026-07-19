# RAPOR — Faz 4: Otomatik Keşif Pipeline'ı

Kapsam: `docs/PROJE_DOKUMANI.md` §7 + §6.5 + §15/Faz 4. Durum: **tamam** (2026-07-20).

## Ne yapıldı
Yeni modül: `backend/app/discovery/` — aşamalı eleme boru hattı (§7 Aşama 0–6):

- **Aşama 0 — Evren & TF** (`service._resolve_universe` + `data/universe.universe_symbols_as_of`):
  açık semboller · `universe_as_of` tarihindeki snapshot (survivorship) · yoksa en güncel.
- **Aşama 1 — Tekli tarama** (`candidates` + `signal_synth`): her aday indikatör her
  sembol × TF'te varsayılan kuralla (şekline göre threshold/line_cross/slope/pattern)
  koşar; §6.4 bileşik skor + giriş-sinyal vektörü. Varsayılan **tam 225 registry**
  (rol taşıyan kategoriler). İndikatör cache tekrar hesabı sıfırlar.
- **Aşama 2 — Korelasyon eleme** (`correlation`): havuzlanmış sinyal serileri arası
  |ρ|>0.85 → aynı kümeden en yüksek skorlu temsilci kalır (RSI+StochRSI+WillR → tek koltuk).
- **Aşama 3 — Rol tabanlı kombinasyon** (`roles`+`combine`): tetikleyici (momentum/overlap)
  + filtre (trend/cycle/statistic/volume) + çıkış/risk (volatilite). Kategori başına ≤1
  (rol taksonomisinden düşer). Hücre başına rol-başı top-K, global top-N; `combos_tried` sayılır.
- **Aşama 4 — Optuna** (`optimize`): tetikleyici+filtre parametreleri TPE ile aranır;
  **seed'li sampler + n_jobs=1** → deterministik. Amaç: IS bileşik skoru.
- **Aşama 5 — WFO doğrulama** (`wfo`, §6.5): kayan pencere (90/30/30g varsayılan; kısa
  seride 70/30 IS/OOS'a düşer), **parametre platosu** (komşular ≥ oran×en iyi),
  **Monte Carlo** (seed'li işlem karıştırma → %95 kötü drawdown). Sağ çıkan → `candidate`.
- **Aşama 6 — Liderlik** (`leaderboard`): OOS skoruna göre sıralı; her satır genome +
  metrikler + WFO katmanları + MC bandı + plato + alarmlar; `combos_tried` tarama düzeyinde.

**Finalist çapraz doğrulama (§6.1):** `FinalistEngine` arayüzü; backtesting.py adaptörü
(opsiyonel `[finalist]` extra, lazy import) + bağımsız **lean second-opinion** motoru (her
zaman mevcut fallback); motor-agnostik alarm karşılaştırıcı (`crosscheck.compare`) — anahtar
metriklerde tolerans aşan sapma → alarm.

**Motor eklentisi:** `RiskExitConfig` (ATR stop/target) — bar kapanışında değerlendirilir,
sonraki açılışta dolar (lookahead-güvenli, rule #1), **varsayılan KAPALI** (tüm Faz-3
testleri sabit kalır). Çıkış/risk rolünün gerçek volatilite tabanlı stop/hedefi budur.

**Kalıcılık + API §12:** `discovery_scans` tablosu (config+hash+seed+status+stage+progress+
combos_tried+leaderboard+artifact_path). `POST /api/discovery/scan` (async arq) →
`run_discovery_job` → `execute_scan` (CPU işi worker thread'inde, saniyede bir canlı
progress commit) → disk artifact. `GET /scans/{id}` (canlı ilerleme + opsiyonel tam artifact)
· `GET /leaderboard` (çapraz-tarama, sıralanabilir). "Hızlı mod" küçük evren/dönem/bütçe.

**UI (`/discovery`, auto mod):** tarama kurucu (semboller/universe-as-of, TF çoklu seçim,
yön, top-N, trials, fast-mode), canlı ilerleme (aşama + bar + combos_tried), sıralanabilir
liderlik tablosu (combos_tried görünür), satır detayı (genome, WFO katmanları, MC bandı,
plato, finalist alarmları), **"Convert to strategy" disabled** (Faz 5'te bağlanacak).

## Kabul kriterleri — kanıt
| Kriter | Kanıt |
|---|---|
| 10 sembol × 4 TF standart tarama < 2 saat | Her aşama süre logu (`ScanResult.stage_timings`, worker'da loglanır). Hızlı mod uçtan uca ~8 sn (`test_discovery_pipeline`). **Gerçek 10×4 ölçümü = operatör plan-B** (24-ay backfill gerekir, RUNBOOK deseni) |
| Aynı seed → aynı sıralama | `test_same_seed_same_leaderboard_ranking` — liderlik sırası + OOS skorları (9 hane) + combos_tried eşit. Optuna TPE seed'li, MC seed'li, açık tiebreak |
| İki motor uyuşmazlığı alarm üretir | `test_discovery_crosscheck` — uyuşma → alarm yok; sapma → alarm (metrik/combo_key/tolerans dahil). Ek: lean second-opinion gerçek EMA koşusunda primary ile uyuşuyor (yanlış alarm yok) |
| Survivorship (bonus, §4.5) | `test_discovery_survivorship` — Mart taraması Ocak snapshot'ını kullanır, Haziran'ı değil |

Toplam: **pytest 109/109** (24 yeni), ruff temiz, `next build` başarılı (/discovery 5.54 kB),
tsc + eslint temiz.

## Açık kararlar (kullanıcı onaylı)
1. **Finalist motoru — interface + fallback.** Doküman §6.1 backtesting.py diyor; ancak Faz-3'te
   vectorbt aynı py3.13/pandas-3.0 stack'inde düştü. backtesting.py aynı riski taşıdığından
   opsiyonel `[finalist]` extra'ya kondu; alarm mantığı motor-agnostik + bağımsız lean
   second-opinion her zaman mevcut → çekirdek kurulum + CI yeşil kalır.
2. **Stage 1 kapsamı — varsayılan tam 225 registry.** Bütçe baskısı indikatör cache + aşama
   süre logları ile karşılanır; hızlı mod küçük alt küme kullanır.

## Yerel doğrulama (operatör)
```bash
# 1) sentetik veri (gerçek backfill = plan-B, RUNBOOK-faz1-veri.md)
python -m app.data.cli devseed --symbols BTCUSDT ETHUSDT --tf 1h --bars 1500
# 2) docker compose up --build   (veya lokal: uvicorn + arq + next start)
# 3) http://localhost:3000/discovery → fast-mode → "Run discovery scan" → liderlik
```
Not: `devseed` verisi SENTETİKTİR; metrikler abartılıdır, sadece uçtan-uca akış içindir.
`pip install -e '.[finalist]'` backtesting.py'yi ekler (kurulmazsa lean second-opinion çalışır).
```
