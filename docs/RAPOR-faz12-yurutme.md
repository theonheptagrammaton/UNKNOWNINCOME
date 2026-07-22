# RAPOR — Faz 12: Yürütme Kalitesi ve Kapasite

> **Slippage'i öğren, varsayma (§26.1).** Bugüne kadar slippage bir *varsayımdı* — sabit
> 5 bps ya da 0.05×ATR. Bu bir ölçüm değildi. Faz 12 her gerçek dolumu bir ölçüme
> çevirir: beklenen fiyat vs gerçekleşen fiyat, kova bazında biriktirilir ve N≥50 dolumdan
> sonra backtest **öğrenilmiş** modeli kullanır. Öğrenilmiş model varsayımdan kötüyse
> geçmiş backtestler yeniden koşulur — acı verir; doğrudur.
>
> **Kural 13 (pazarlıksız):** Öğrenilmiş model **yalnız gerçek (canlı) dolumlardan**
> öğrenir; paper dolum simüledir, modele kendi varsayımını öğretir. Aşağıdaki kriterlerin
> makinesi + birim testleri tamam; **50+ gerçek canlı dolum ve canlı-paper tracking-error
> daralması operatör sunucu adımıdır** (Faz 8–11 ile aynı sınır).

Tarih: 2026-07-22 · Branch: `main` · Motor testleri: **361 passed** (+25 yeni Faz-12),
ruff temiz, frontend `tsc --noEmit` temiz.

---

## 1. Teslim edilen kod

### 1.1 Öğrenilmiş slippage modeli (§26.1)

| Bileşen | Dosya | Ne yapar |
|---|---|---|
| Çekirdek model | `execution/slippage_model.py` | Kova `(sembol, TF, emir_notional_dilimi, vol_dilimi)`; `learn()` kova başına **medyan** adverse slippage bps + örnek sayısı; kova `samples ≥ min_samples` (50) olunca **güvenilir**. `materialize()/load_model()` → `{data_dir}/slippage_model.json` (sync-okunur artifact, Faz 11 deseni). |
| Ham kayıt | `models/trading.py::SlippageObservation` | Her dolumda beklenen vs gerçekleşen fiyat + notional + ATR + `mode`. Yalnız `mode=="live"` satırlar modeli besler. |
| Bot kaydı | `bot/engine.py::_record_slippage` | Her dolumdan sonra gözlem yazılır (paper satırları saklanır ama modele girmez, kural 13). |
| Backtest entegrasyonu | `backtest/config.py` + `backtest/engine.py` + `backtest/runner.py` | `slippage_model="learned"` → runner öğrenilmiş modelden **bar-bazlı bps serisi** kurar (güvenilir kova → ölçüm, soğuk kova → 5 bps varsayım fallback); motor saf/deterministik kalır. `cost_breakdown.slippage_source ∈ {fixed_bps, atr, learned}` (kural 14 şeffaflık). |
| Uzlaştırıcı | `execution/slippage_reconcile.py` | `rebuild_slippage_model` (canlı dolumlardan öğren + materyalize); `reconcile_slippage` öğrenilmiş kova varsayımdan **kötüyse** `risk_event(slippage_worse)` + bildirim + etkilenen `(sembol,TF)` için yeniden-koşu **seam**'ini (`rerun`) çağırır. |
| Worker cron | `workers/main.py::reconcile_slippage_job` | Günlük 04:00 UTC — modeli tazeler, kötüleşmeyi işaretler. |

**Slippage neden yeniden-koşuyu tetikler:** öğrenilmiş bir kova sabit varsayımdan pahalıysa,
geçmiş backtestler o dolumları **eksik maliyetlendirmiştir** → liderlik tablosu bayattır.
Tetikleyici otomatik (cron + `risk_event`), gerçek yeniden-koşu operatör adımıdır (Faz 8–11
sınırı; `rerun` seam'i worker'a takılır).

### 1.2 Kapasite ve katılım (§26.2)

| Bileşen | Dosya | Ne yapar |
|---|---|---|
| Saf matematik | `execution/capacity.py` | `participation = emir_qty / bar_hacmi`; `exceeds_cap` (tavan %1); `capacity_usd` / `capacity_from_samples` — "kapasite = katılım tavanına dayanmadan taşınabilen maksimum sermaye". |
| Risk geçidi | `execution/risk.py` | `TradeIntent.bar_volume` + `RiskLimits.participation_cap_pct=1.0`. Tavanı aşan emir **reddedilir** + `risk_event(capacity)` (katılım %, tavan, qty, hacim). Bilinmeyen hacim ⇒ geçit atlanır (sessizce %0 sayılmaz). |
| Bot besleme | `bot/engine.py` | `intent.bar_volume` sinyal barının taban hacminden doldurulur. |
| Strateji kartı | `api/strategies.py::_capacity` + `frontend/.../StrategyPanel.tsx` | Son ≤20 dolumun (qty, bar_hacmi) medyan katılımından "**carries up to $X**" tahmini; gerçek dolum yoksa gösterilmez (best-effort, kart asla 500 vermez). |

### 1.3 Limit emir yolu (§26.3) — varsayılan KAPALI, opt-in

| Bileşen | Dosya | Ne yapar |
|---|---|---|
| Emir alanları | `execution/base.py` | `order_type="limit"`, `limit_price`, `timeout_s`. |
| Çözücü + router | `execution/limit.py` | `resolve_limit` (saf): fiyat limite değdiyse **maker**, `T` sn dolduysa **market fallback**, aksi **REST**. `LimitOrderRouter` resting emirleri taşır; `submit`/`poll` maker dolumu (limitte, slippage 0, maker ücreti) ya da timeout→market (taker) üretir. |
| Backtest kalemi | `backtest/engine.py` | `limit_entry_enabled` → giriş sinyalinin kapanışında maker limit; dolum barının aralığı limite değerse **maker**, fiyat kaçtıysa **taker fallback** (adverse selection). `cost_breakdown`: `maker_commission`/`taker_commission`/`maker_entries`/`taker_entries` + `limit_entry=True` etiketi. |

**Uyarı korundu (§26.3):** dolmayan limit genelde fiyatın aleyhine gittiği durumdur —
backtest'te modellenmesi zor bir yanlılık. Bu yüzden **varsayılan kapalı**, opt-in, raporda
ayrı etiketli.

### 1.4 Tracking error önce/sonra (§26.4)

`bot/tracking.py::compare_tracking_error` + `load_tracking_comparison(split_ts)` — öğrenilmiş
model devreye girdiği ts'te seriyi böler; `before`/`after` tracking error + `narrowed`
(after < before). Saf fonksiyon birim testli; **gerçek daralma canlı-paper koşusuyla ölçülür
(operatör adımı)**.

### 1.5 Ayarlar (kural 19) — §28.2 Kuşak 7

`core/config.py`'a 5 knob + `RiskLimits.participation_cap_pct`. Hepsi §28.2 **Kuşak 7 —
Yürütme kalitesi ve kapasite (Faz 12)** sözlüğüne üç satırla eklendi (ne yapar · yükseltirsen
· düşürürsen): `participation_cap_pct`, `slippage_learn_min_samples`,
`slippage_reconcile_tolerance_bps`, `limit_entry_enabled`, `limit_timeout_s`, `maker_fee_bps`.

---

## 2. Kabul kriterleri (§26.4) — kanıt

### ✅ 1) 50+ gerçek dolum sonrası öğrenilmiş model devrede; sabit varsayımla farkı raporlandı

- `test_slippage_model.py` (12 test): <50 örnek → kova güvenilmez → `lookup_bps` None → varsayım
  fallback; **50'de güvenilir** → öğrenilmiş bps döner. `materialize/load` roundtrip.
  `worse_than_assumption` yalnız güvenilir + kötü kovaları işaretler.
- Backtest farkı: `test_engine_learned_series_differs_from_fixed_assumption` — öğrenilmiş 40 bps,
  sabit 5 bps → öğrenilmiş `total_slippage` **kesinlikle daha yüksek**; `slippage_source`
  raporda `"learned"` vs `"fixed_bps"`.
- `test_runner_series_uses_learned_where_trusted_else_fallback` — ısınan barlar öğrenilmiş 25 bps,
  ATR-ısınma barları 5 bps fallback.
- **Operatör adımı:** 50+ **gerçek canlı** dolum (kural 13). Cron modeli günlük tazeler.

### ✅ 2) Her strateji kartında kapasite tahmini; katılım %1'i aşan emir reddediliyor

- `test_capacity.py` (8 test): participation/cap/capacity matematiği; **participation %2.5 > %1 →
  `evaluate` reddediyor + `capacity` risk_event**; `submit` yolunda emir adaptöre **hiç ulaşmıyor**;
  bilinmeyen hacim geçidi atlamıyor; tavan altı onaylanıyor.
- Kart tahmini: `api/strategies.py::_capacity` → `StrategyOut.capacity_usd`; UI "carries up to $X"
  (`StrategyPanel.tsx`). Gerçek dolum olunca dolar; yoksa gizli.

### ✅ 3) Limit emir yolu testli; `T` sn timeout sonrası market fallback çalışıyor

- `test_limit_order.py` (7 test): `resolve_limit` REST/FILL_MAKER/FALLBACK_MARKET durumları;
  **router 5 sn sonra dolmayan limiti market'e düşürüyor** (adaptörde gerçek market dolumu, taker
  komisyonu + slippage); anında marketable limit maker olarak limitte dolar (slippage 0). Backtest
  maker/taker ayrımı `cost_breakdown`'da (maker vs taker fallback senaryoları).

### ⏳ 4) Canlı-paper tracking error, öğrenilmiş model devreye girdikten sonra DARALDI

- `test_tracking_window.py` (3 test): `compare_tracking_error` seriyi `split_ts`'te böler; after < before
  → `narrowed=True`; kısa pencere → `narrowed=None`.
- **Operatör adımı (kural 13):** gerçek daralma bir canlı-paper koşusu gerektirir. Ölçüm makinesi
  (`load_tracking_comparison`) + `/api/bot/tracking` hazır; öğrenilmiş modelin aktive olduğu ts'i
  `split_ts` olarak ver → önce/sonra rapor.

---

## 3. Testler

`test_slippage_model.py` (12) · `test_capacity.py` (8) · `test_limit_order.py` (7) ·
`test_slippage_reconcile.py` (3) · `test_tracking_window.py` (3) = **+25 yeni test**.
Toplam **361 passed**, ruff temiz. `make_wave_ohlcv` fixture hacmi gerçekçi büyüklüğe çekildi
(gerçek likit çift gibi) — böylece plumbing testleri kapasite geçidine değil dolum yoluna bakar.

## 4. Operatör adımları (kural 13 — sentetik kanıt değildir)

1. **Öğrenilmiş model:** 50+ **gerçek canlı** dolum biriktikten sonra günlük cron modeli materyalize
   eder; backtest `slippage_model="learned"` ile öğrenilmiş modeli okur. Kötüleşme `risk_event` +
   bildirim üretir; etkilenen backtestleri `rerun` seam'iyle yeniden koş.
2. **Tracking error önce/sonra:** öğrenilmiş model aktive ts'ini `split_ts` olarak
   `load_tracking_comparison`'a ver; `narrowed` raporla.

Tag: `faz-12`.
