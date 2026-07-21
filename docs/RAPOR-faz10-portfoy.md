# RAPOR — Faz 10: Portföy Katmanı

> **Stratejiler tek başına değil, bir portföy olarak değerlendirilir (kural 16).** v1'in
> en büyük mimari boşluğu buydu: beş strateji × %1 risk "%5 risk" sanılıyordu, oysa hepsi
> aynı yöne bakıyorsa gerçekte tek yönde %5'lik tek bir bahisti. Faz 10 riski **portföy
> düzeyinde** ölçer: getiriler korele edilir, sermaye korelasyon-farkında dağıtılır,
> aynı semboldeki bahisler netleştirilir ve portföy limitleri strateji limitlerinden
> **önce** değerlendirilir.
>
> **Kural 13 (pazarlıksız):** Sentetik veri hiçbir kabul kriterini kapatmaz. Aşağıdaki
> beş kabul kriteri **saf/birim testlerle** kanıtlandı (piyasa verisi gerektirmez);
> gerçek çok-stratejili canlı havuz sayıları operatör sunucu adımıdır.

Tarih: 2026-07-22 · Branch: `main` · Motor testleri: **303 passed** (+33 yeni Faz-10),
ruff temiz, frontend `tsc` temiz.

---

## 1. Teslim edilen kod

Yeni modül `backend/app/portfolio/` (doc §24.1):

| Bileşen | Dosya | Ne yapar |
|---|---|---|
| Korelasyon | `portfolio/correlation.py` | Strateji **getiri serileri** arası kayan 90g Pearson (equity değil — farklı sermaye normalize). Paper stratejiler de matriste. Sabit-seri NaN'ları 0'a çekilir; `max_abs_correlation` kapı girdisi. |
| Tahsis | `portfolio/allocation.py` | eşit-risk (varsayılan, kovaryans-farkında vol-hedefi) · ters-vol · **çeyrek-Kelly** (tavanlı) · manuel kilit. **Tam Kelly reddedilir.** Tek-strateji ≤ %25 kod sabiti. `correlation_gate_factor`. |
| Netleştirme | `portfolio/netting.py` | Aynı sembol bacakları → tek net pozisyon (**risk bir kez**); `attribute_pnl` imzalı-notional payına orantılı PnL atfı. |
| Limitler | `portfolio/limits.py` | Saf değerlendirici: portföy DD %12 (kill), günlük zarar %3, net sembol %35, brüt kaldıraç 3x, tek-yön %60, aktif-strateji bandı 3–8 (uyarı). Olayları döndürür; persist bota ait. |
| Orkestrasyon | `portfolio/service.py` | Havuzu kurar, korelasyon + tahsis + **korelasyon kapısı** + katkı + uyarıları hesaplar; `/api/bot/portfolio` bunu tüketir. Saf çekirdek `build_snapshot` DB'siz. |
| RiskLayer entegrasyonu | `execution/risk.py` | `PortfolioLimits` enjekte edilir; `evaluate()` portföy kapısını **strateji kapılarından önce** koşar; portföy reddi `decision.events`'e (bot `risk_events`'e persistler). |
| Motor kablolaması | `bot/engine.py` | Her duvara (paper + live) portföy limitleri geçilir; paylaşılan sembol kapanınca `_attribute_shared` → `trades.attribution`. |
| Model | `models/trading.py`, `models/risk.py` | `Trade.attribution` (JSON); yedi yeni `RISK_TYPES` (portföy olayları). |
| Config | `core/config.py` | Yedi portföy ayarı; ikisi (`portfolio_daily_loss_pct`, `portfolio_direction_concentration_pct`) yeni → §28.2 sözlüğüne eklendi (kural 19). |
| UI | `components/trade/PortfolioPanel.tsx`, `lib/api.ts` | Tahsis halkası · korelasyon ısı haritası (0.70 üstü kırmızı) · net maruziyet çubuğu (tavan çizgisi) · katkı tablosu · düz cümleli yoğunlaşma uyarıları. |

---

## 2. Matematik — nasıl ölçüyoruz

### 2.1 Tahsis: kovaryans-farkında eşit-risk (klon testinin geçtiği yer)

Yön ters-vol ağırlıklarıdır (Σw = 1); bu yön portföy volatilitesi `target_vol`'a
oturacak şekilde ölçeklenir:

```
a = g · w ,   g = target_vol / √(wᵀ Σ w) ,   Σ = D·R·D  (D = diag(vol), R = korelasyon)
```

**Neden klon testi yapı gereği geçer:** iki birebir aynı strateji (ρ = 1) Σ'yı tekilleştirir;
`√(wᵀΣw)` tek stratejininkine eşit kalır, dolayısıyla `g` aynıdır ve toplam tahsis
katlanmaz — her klon yarısını alır (50/50), toplamları tek stratejininkine **eşittir**.
Korelasyonsuz bir çift ise portföy volünü düşürdüğü için daha çok sermaye dağıtabilir
(`test_uncorrelated_pair_deploys_more_than_a_clone_pair` bunu kanıtlar → motor gerçekten
korelasyonu kullanıyor).

Tavanlar (doc §24.3 pazarlıksız, kod sabiti): tek strateji ≤ %25 tahsis. Net sembol ≤ %35
ve brüt kaldıraç ≤ 3x **çalışma-zamanı** limitidir (`limits.py`, gerçek notional'a karşı).

### 2.2 Çeyrek Kelly — tam Kelly ASLA

`f* = edge/var`, çeyreği alınır, %25 tavanı: `min(0.25, 0.25·f*)`. Negatif edge ⇒ 0.
Tam Kelly ~%50 drawdown'ları normal sayar; çeyrek Kelly büyümenin ~%94'ünü varyansın
~%25'iyle verir (doc §24.3). `method="full_kelly"` çağrısı `ValueError` ile reddedilir.

### 2.3 Netleştirme + PnL atfı

Aynı sembolün bacakları imzalı toplanır: net = |Σ imzalı|, brüt = Σ |bacak|. İki strateji
1000 + 3000 long ⇒ **tek** pozisyon, net 4000 (8000 değil — risk bir kez). PnL imzalı-notional
payına orantılı: 400 PnL → A 100, B 300 (`test_pnl_attributed_proportionally`).

### 2.4 Korelasyon kapısı

Canlı havuza giren strateji mevcut biriyle `|ρ| > 0.70` ise tahsisi
`(1−|ρ|)/(1−eşik)` ile kısılır (doc §24.2 varsayılan): ρ=0.85 ⇒ ×0.5 (yarı), ρ=1 ⇒ ×0
(klon tek slotu paylaşır), ρ≤0.70 ⇒ ×1. Kısıt (red değil) varsayılan; red operatör
seçeneği.

---

## 3. Kabul kriterleri — kanıt

Beş kriterin tamamı **piyasa verisi gerektirmeyen** saf/birim testlerle kanıtlıdır.

### 3.1 ⭐ Klon testi — ✅

`test_portfolio_allocation.py::test_clone_total_allocation_equals_single`: birebir aynı iki
strateji (ρ=1) canlıya alınınca **toplam tahsis = tek stratejinin tahsisi** (iki katı değil);
her biri yarısını alır. Vol-hedefli tahsisin doğrudan sonucu.

### 3.2 Netleştirme — ✅

`test_portfolio_netting.py`: iki strateji aynı sembol+yön → tek net pozisyon (risk bir kez),
PnL orantılı atıf. Motor kablolaması: `test_portfolio_attribution.py::
test_shared_symbol_close_writes_proportional_attribution` — paylaşılan sembol kapanınca
`trades.attribution` orantılı doldurulur; tek-strateji sembolü `None` bırakır.

### 3.3 Portföy DD, hiçbir strateji kendi limitini aşmadan — ✅

`test_portfolio_limits.py::test_portfolio_dd_trips_while_no_strategy_breaches_its_own_limit`
ve RiskLayer üzerinden `test_portfolio_gate_integration.py::test_portfolio_dd_kills_before_
strategy_dd`: equity %13 düşükken portföy %12 kapısı **kill** verir, strateji %15 kapısı
(`max_drawdown`) **ateşlemez**. Portföy limiti stratejiden önce değerlendirildiği için.

### 3.4 Brüt kaldıraç 3x'i aşan emir reddedilir + `risk_events` — ✅

`test_portfolio_gate_integration.py::test_gross_leverage_over_3x_rejected_and_emits_event`:
2.8x mevcut + 2.5k ekleme → 3.05x → RiskLayer emri **reddeder**, borsaya hiçbir emir gitmez
(`adapter.placed == []`), `gross_leverage` olayı `decision.events`'e düşer (bot bunu
`risk_events`'e persistler — mevcut `_evaluate` yolu, `test_bot_engine` kapsamında).

### 3.5 Korelasyonu 0.85 olan yeni strateji tahsis kısıtı/redle karşılanır — ✅

`test_portfolio_service.py::test_correlation_gate_cuts_allocation_for_085_pair`: ρ≈0.85
çift için korelasyon kapısı `gated=True`, `factor≈0.5` (kısıt, red değil); tahsis pozitif
ama yarıya iner. `test_portfolio_allocation.py::test_correlation_gate_factor_proportional`
katsayıyı referans değerlere karşı doğrular.

---

## 4. Tasarım kararları ve gerekçeleri

- **Portföy kapısı RiskLayer'a enjekte edilir, ayrı bir katman değil.** "Hiçbir emir duvarı
  atlayamaz" mimarisi korunur; portföy kapısı `evaluate()`'ın en başında (DD) ve açılış
  kapılarında (sembol/brüt/yön/günlük), **strateji kapılarından önce** koşar. `portfolio=None`
  ⇒ Faz-10 öncesi davranış (birim testler için).
- **Pooled equity = portföy equity'si.** Tüm stratejiler tek adaptörü paylaşır; adaptör
  sembol bazında zaten netleştirir (risk bir kez) ve equity/peak portföy düzeyindedir —
  bu yüzden portföy DD %12, strateji %15'e varmadan ateşleyebilir.
- **Yön yoğunlaşması net-yönlü/equity ölçülür**, net/(long+short) değil. Aksi halde ilk
  pozisyon "yüzde yüz tek yön" sayılır ve **her açılış bloke olurdu**. Bu, motorun toy
  genome'unu (100% notional ATR pozisyonu) portföy tavanlarıyla uyumlu küçük sabit boyuta
  çekmeyi gerektirdi (`test_bot_engine._genome`), çünkü sıkı ATR stopu leveraged notional'ı
  tavanların üstüne çıkarıyordu — bu tam da §24.3'ün "brüt 3x, strateji 10x'ten önceliklidir"
  dediği etkileşimdir.
- **SciPy yok, yeni ağır bağımlılık yok.** Kovaryans/korelasyon numpy+pandas; tahsis
  kapalı-form. Pipeline/servis DB'siz çekirdek + ince async yükleyici (Faz 9 deseni).
- **Tam Kelly kaldırılamaz.** Kod sabiti; `full_kelly` string'i `ValueError`.

## 5. Yeni config parametreleri (kural 19)

Yedi ayar; beşi §28.2'de zaten belgeliydi (`allocation_method`, `correlation_gate`,
`portfolio_max_dd_pct`, `max_symbol_exposure`, `gross_leverage_cap`). İki yeni ayar aynı
commit'te sözlüğe eklendi:

- `portfolio_daily_loss_pct` (%3) — portföy günlük zarar durdurucu.
- `portfolio_direction_concentration_pct` (%60) — net yön tavanı.

Yeni `risk_events` tipleri (§28.3 karar anlatıcısı) düz cümle çevirileriyle birlikte
belgelendi. Yapısal tavanlar (%25 / %35 / 3x) **kod sabitidir**; config yalnızca sıkabilir.

## 6. Sınırlar (v2 §31)

Portföy katmanı riski **ölçer ve sınırlar; sıfırlamaz.** Korelasyon 90g geriye bakar —
rejim değişiminde geç kalabilir; kapasite (Faz 12) henüz yok, dolayısıyla tahsis doyum
büyüklüğünü bilmez (kural 17 Faz 12'de kapanır). Gerçek çok-stratejili canlı havuz
sayıları — korelasyon matrisi, tahsis halkası, katkı tablosu — operatör sunucu adımıdır;
mekanizma hazır ve testlidir, sayılar gerçek koşuda dolar.

---

*UNKNOWNINCOME — Faz 10 raporu. v2 §24 ile birlikte okunur.*
