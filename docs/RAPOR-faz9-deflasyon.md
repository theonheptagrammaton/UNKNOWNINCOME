# RAPOR — Faz 9: İstatistiksel Dürüstlük Katmanı (Deflasyon Kapısı)

> **Bu fazın işi güven değil, güvenin ölçümüdür.** Keşif hattı on binlerce hipotez
> dener ve en iyisini seçer; çoğun en iyisi büyük olasılıkla en şanslısıdır (v2 §23.1).
> Faz 9 bu şansı **ölçer** ve skordan **çıkarır**. v1.1 §6.5-5'in ertelediği çoklu-test
> borcu burada kapandı.
>
> **Kural 13 (pazarlıksız):** Sentetik veri hiçbir kabul kriterini kapatmaz. Aşağıda
> kod + testler yerelde/CI'da kanıtlandı; **gerçek 24-ay veriyle referans-strateji
> koşusu operatör sunucu adımıdır** (Faz 8'in bıraktığı yerde) ve kanıtı olmayan kutu
> ✅ işaretlenmedi.

Tarih: 2026-07-21 · Branch: `main` · Motor testleri: **267 passed** (+26 yeni Faz-9), ruff temiz, frontend `tsc` temiz.

---

## 1. Teslim edilen kod

| Bileşen | Dosya | Ne yapar |
|---|---|---|
| Deflasyon matematiği | `backend/app/research/deflation.py` | `expected_max_sharpe` (SR*₀, Bailey & LdP 2014, Euler-Mascheroni γ dahil), `deflated_sharpe` (0–1 olasılık), `pbo_cscv` (CSCV, S=16, C(16,8) blok-önhesaplı). **SciPy'sız** — `statistics.NormalDist` ile referans-kalite Z/Z⁻¹. Sert eşikler **kod sabiti** burada. |
| Sert kapı | `backend/app/research/gate.py` | `evaluate_gate` dört pazarlıksız kontrol; `sharpe_moments` (işlem-bazlı SR/çarpıklık/basıklık/T). Saf: sayıyı karara çevirir, eşik argümanı **almaz**. |
| Deney kütüğü | `backend/app/research/registry.py` + `backend/app/models/research.py` | Append-only `experiment_trials` tablosu; kanonik `genome_family_hash` (yapı: trigger+filter+exit+sembol+tf+yön, **paramdan bağımsız**); tarama üstü `trials_total` okuması. |
| Aşama 5.5 bağlama | `backend/app/discovery/deflation_gate.py` | Entry + WFO raporlarından gate girdilerini toplar (N, Var[SR], PBO kohortu, B&H), her adayı yargılar, geçemeyeni `rejected`'a düşürür. |
| Pipeline entegrasyonu | `backend/app/discovery/pipeline.py`, `wfo.py`, `leaderboard.py`, `service.py` | WFO artık OOS işlem-getirisi + tam-dönem bar-getirisi verir; Aşama 5 ile 6 arasına 5.5 girer; servis kütükten `prior_trials` okur, koşu sonrası kütüğe yazar, gate sabitlerini `audit_log`'a düşer. |
| UI | `frontend/components/discovery/LeaderboardTable.tsx`, `lib/api.ts` | Yeni kolonlar **DSR · PBO · Trials · vs B&H**; Sharpe başlığında **"raw" rozeti**; `DSR<0.95` satır soluk; açılır detayda gate kararı + red sebepleri. |
| Gürültü testi | `backend/scripts/noise_test.py` | Gerçek σ + AR(1) φ eşleyen rastgele yürüyüş üretir, izole Parquet'e yazar, **tam keşif hattını** koşturur, aday sayısını doğrular, exit-code döner. |
| Referans-gate koşucusu | `backend/scripts/reference_gate.py` | Faz 8'in üç referans stratejisini kapıdan geçirir; gerçek veri yoksa dürüst **SKIP**. |

---

## 2. Matematik — nasıl ölçüyoruz

### 2.1 Beklenen maksimum Sharpe (null altında)

```
SR*₀ = √Var[SR] · [ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ] ,  γ ≈ 0.5772
```

`N` bağımsız deneme, hepsi gerçekte sıfır edge'e sahip olsa bile, en iyisinin şans eseri
göstereceği Sharpe. **Gözlenen edge'in aşması gereken çıta budur.** `N` büyüdükçe çıta
yükselir — bu yüzden aynı stratejiyi 50 kez denemek onu terfi ettirmez, aksine zorlaştırır.

- Uygulamada `N = combos_tried + prior_family_trials`: bu taramanın seçim genişliği **+**
  o genome ailesinin kütükteki tüm-zamanlı denemesi.
- `Var[SR]` = taramadaki tüm combo'ların işlem-bazlı SR tahminlerinin varyansı.

### 2.2 Deflated Sharpe Ratio (DSR)

```
DSR = Z[ (SR − SR*₀)·√(T−1) / √(1 − γ₃·SR + ((γ₄−1)/4)·SR²) ]
```

Gözlenen (işlem-bazlı, yıllıklandırılmamış) Sharpe'ın çıtayı aşma **olasılığı**;
çarpıklık (γ₃) ve basıklık (γ₄, non-excess, normal≈3) ve örneklem uzunluğu (T=OOS işlem)
için düzeltilir. `DSR=0.95` → "bu Sharpe'ın şans olma olasılığı %5". `SR=SR*₀`'da tam 0.5.

### 2.3 PBO — Aşırı Uydurma Olasılığı (CSCV)

Getiri matrisi (T gözlem × N config, ortak zaman ekseni) S=16 bloğa bölünür; C(16,8)=12 870
IS/OOS kombinasyonunda IS-en-iyisi seçilir, OOS göreli sırası (ω) ölçülür;
`PBO = ω ≤ 0.5 olan kombinasyon oranı`. `PBO ≥ 0.5` → seçim süreci yazı-tura kadar
bilgilendirici. Blok-önhesap (Σr, Σr² per blok) sayesinde 12 870 kombinasyon O(N·S).

### 2.4 Referans-değer doğrulaması (`test_research_deflation.py`)

| Fonksiyon | Test | Beklenen | Sonuç |
|---|---|---|---|
| `expected_max_sharpe` | kapalı-form + monotonluk | N↑ ⇒ SR*↑; √Var ölçekli | ✅ |
| `deflated_sharpe` | SR=SR* | 0.5 | ✅ |
| `deflated_sharpe` | Lo (2002) normal SE | √(1+½SR²) kapalı form | ✅ |
| `pbo_cscv` | baskın config | ≈ 0 | ✅ (0.00) |
| `pbo_cscv` | iid gürültü (20 seed ort.) | ≈ 0.5 | ✅ (0.497) |
| `pbo_cscv` | anti-korele (aşırı uydurma) | → 1 | ✅ (0.98) |

---

## 3. Sert kapı (Aşama 5.5) — pazarlıksız

WFO'dan (Aşama 5) sonra yeni aşama. Bir WFO-hayatta-kalanı ancak **dört kontrolü de**
geçerse "candidate" kalır:

```
DSR < 0.95        → REDDET   (Sharpe muhtemelen şans)
PBO ≥ 0.40        → REDDET   (seçim muhtemelen aşırı uydurma)
OOS işlem < 30    → REDDET   (kanıt değil anekdot)
OOS getiri ≤ B&H  → REDDET   (sadece elde tutmayı yenmeli)
```

- **Eşikler kod sabitidir** (`deflation.py`: `DSR_MIN=0.95`, `PBO_MAX=0.40`,
  `MIN_OOS_TRADES=30`). `evaluate_gate` yalnızca **kanıt** alır, eşik argümanı **almaz**
  (`test_thresholds_cannot_be_loosened_by_argument`). Gevşetmek = kaynak değişikliği
  (commit + review).
- **Denetlenebilirlik:** her tarama, aktif gate sabitlerini `audit_log`'a
  (`action="deflation_gate.thresholds"`, `actor="system"`) yazar — eşik değişikliği
  koda girdiğinde otomatik olarak denetim izine düşer.
- **Hesaplanamayan PBO fail'dir:** bir hücrede <2 config veya blok sayısı için yetersiz
  bar ⇒ `PBO=None` ⇒ REDDET. Kapıyı test edememe, kapıyı geçmek değildir (v2 §30).

B&H karşılaştırması **elmayla elma**: stratejinin OOS ortalama fold getirisi, aynı OOS test
pencerelerindeki ortalama buy&hold getirisiyle kıyaslanır.

---

## 4. Kabul kriterleri — kanıt

### 4.1 ⭐ Gürültü testi (bu fazın kilit kriteri) — ✅ SIFIR ADAY

`scripts/noise_test.py` gerçek serinin volatilitesini ve AR(1) otokorelasyonunu eşleyen
rastgele yürüyüş üretir ve **tam keşif hattını** üzerinde koşturur.

**Broad koşu (tam 225-indikatör aday kümesi, fast-mode değil):**

```
Faz 9 — noise test · 2 symbol × 1h · 1200 bars · seed 5
  matched stats: σ=0.01000  φ=+0.000
  pipeline: 640 combos tried, 50 finalists, 0 candidate(s) after gate
  ✓ PASS — zero candidates from noise.
    rejected accbands+ht_trendmode+donchian:
       DSR 0.000 < 0.95 · PBO 0.439 ≥ 0.4 · OOS trades 1 < 30 · OOS 0.0134 ≤ B&H 0.0697
    …
```

Dört kapı da ateşliyor. CI koruması: `tests/test_noise_pipeline.py` (fast-mode, gerçek
üreticiyi kullanır → script ile CI birbirinden sapamaz). **Bir tane bile aday çıksaydı
faz kapanmazdı — kapı değil hat düzeltilirdi.**

### 4.2 50× re-opt DSR'ı düşürür (deneme sayacı çalışıyor) — ✅

- `test_research_registry.py`: aynı stratejiyi 50 kez kütüğe yazınca `trials_total → 50`.
- `test_deflation_gate.py::test_reopt_lowers_dsr_and_flips_candidate`: `N ∈ {10,100,1000,
  10000,50000}` için DSR **monoton azalır**; az denemede geçen aday, çok denemede reddedilir.

### 4.3 Liderlik tablosu kolonları + "raw" rozeti + soluk satır — ✅

Her satır: ham Sharpe (**raw** rozetli) · DSR · PBO · trials_total · vs B&H. `DSR<0.95`
satır `opacity-45` ile soluk. Açılır detayda gate kararı ve red sebepleri.
`test_noise_pipeline.py::test_noise_gate_fields_present_on_every_row` her satırda alanların
varlığını doğrular; frontend `tsc` temiz.

### 4.4 Yüksek ham Sharpe / düşük DSR terfi edemez — ✅

`test_high_raw_sharpe_low_dsr_cannot_promote`: işlem-bazlı ham Sharpe 0.5 (80 işlem, sağlıklı)
ama 40 000 deneme karşısında SR*₀ daha yüksek → DSR çöker → **REDDET** (PBO/işlem/B&H geçse bile).

### 4.5 Faz 8'in üç referans stratejisi kapıdan — ⏳ operatör adımı, ✅ mekanizma hazır

`scripts/reference_gate.py` EMA9×21 · RSI(14) · Donchian(20) stratejilerini kapıdan geçirir.
**Gerçek veri deposu bu makinede yok** → koşu dürüst **SKIP** verir (rule #13; Faz 8 ile
tutarlı — gerçek sayılar operatör sunucu adımı):

```
Faz 9 — three reference strategies vs the deflation gate (§23.6)
  ══ BTCUSDT · 1h ══  SKIP: no real data (0 bars) — operator step (rule #13)
```

**Önceden söylenen sonuç (v2 §22.3):** üçü de kapıdan **geçemeyecek**. Basit TA maliyet
sonrası buy&hold'u yenmez → en azından "OOS getiri ≤ B&H" tek başına reddeder; düşük DSR
genellikle ekler. Operatör 24-ay backfill sonrası tek komutla çalıştırır; çıktı bu rapora
eklenir, ⏳ satırı gerçek sayılarla ✅ olur (geçen olursa "geçti" de dürüstçe yazılır).

---

## 5. Tasarım kararları ve gerekçeleri

- **SciPy eklenmedi.** DSR yalnızca normal Z/Z⁻¹ ister; Python 3.13 `statistics.NormalDist`
  bunu referans-kalitede verir. Bağımlılık yüzeyi büyütülmedi.
- **Pipeline DB'siz kaldı.** `prior_trials` düz bir `dict` argümanı olarak girer;
  varsayılan boş → hat testleri/CI DB'siz koşar. Kalıcılık yalnızca serviste.
- **DSR frekans-tutarlı.** SR, çarpıklık, basıklık, T hepsi **işlem-bazlı** OOS getirilerinden;
  `min_oos_trades ≥ 30` ile aynı seri. Yıllıklandırılmış Sharpe UI'da yalnızca "raw" olarak.
- **N tanımı.** `N = combos_tried + prior_family` — bu taramanın seçim genişliği artı ailenin
  tüm-zamanlı geçmişi; ikisi de dürüst çoklu-test bedelidir.
- **PBO hesaplanamazsa REDDET.** Muhafazakâr; v2 §30'un "liderlik tablon boşalacak, gevşetme"
  ilkesiyle uyumlu.

## 6. Yeni config parametresi — yok

Kapı eşikleri **kod sabiti** olduğundan yeni operatör ayarı eklenmedi; §28.3 sözlüğü zaten
`dsr_threshold`/`pbo_threshold`/`min_oos_trades`'i açıklıyor (kural 19 karşılandı — ayar
eklenmedi, dolayısıyla sözlüğe ekleme gerekmedi).

## 7. Sınırlar (v2 §31)

Deflated Sharpe, PBO ve WFO aşırı uydurma olasılığını **ölçer ve azaltır; ortadan
kaldırmaz.** Kapıdan geçmiş bir strateji kârlı değil, **gürültü olma olasılığı ölçülmüş**
bir stratejidir. İlk gerçek-veri taramasında liderlik tablosunun boşalması beklenir
(§30) — bu kapının çalıştığının kanıtıdır, gevşetme sebebi değil.

---

*UNKNOWNINCOME — Faz 9 raporu. v2 §23 ile birlikte okunur.*
