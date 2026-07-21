# RAPOR — Faz 8: Gerçeklik Teması

> **Bu fazın çıktısı kod değil, sayılardır** (v2 §22). Tek satır yeni ürün özelliği
> yazılmadı; var olan sistemin gerçek dünyada ne yaptığını ölçen araçlar yazıldı.
>
> **Kural 13 (pazarlıksız):** Sentetik veriyle hiçbir kabul kriteri kapatılamaz.
> Aşağıda **SENTETİK** sütunu yerelde/CI'da mevcut fixture'larla ölçülen; **GERÇEK**
> sütunu ise gerçek 24-ay backfill + testnet anahtarı + 72 saat gerektirdiği için
> **operatör sunucu adımıdır**. Kanıtı olmayan kutu ✅ işaretlenmedi — Faz 7'de
> testnet round-trip'ini ⏳ bıraktığımız dürüstlükle.

Tarih: 2026-07-21 · Branch: `main` · Motor testleri: **241 passed** (+9 yeni Faz-8 collector testi), ruff temiz.

---

## 1. Teslim edilen araçlar (kod)

| Araç | Dosya | Ne yapar |
|---|---|---|
| Likidasyon toplayıcısı | `backend/app/data/collectors/liquidations.py` | Binance `!forceOrder@arr` WS → `liquidations` tablosu; `dedup_key` UNIQUE; ≥500 satır **veya** ≥5 sn toplu yazım; kopmada üstel backoff ile yeniden bağlanma. **Bugün başlar, sadece biriktirir.** |
| Gerçeklik doğrulayıcı | `backend/scripts/reality_check.py` | Tek komut: Faz 1–7 kabul kriterlerini gerçek Parquet + DB'ye karşı yeniden koşar, tablo basar. Çalışamayan kontrol **SKIP/ERROR** der, asla sahte PASS. |
| Referans stratejiler | `backend/scripts/reference_strategies.py` | EMA9×21 · RSI(14) aşırı satım dönüşü · Donchian(20) kırılımı — gerçek veride, **maliyetler AÇIK**, **buy & hold** sütunuyla. |
| Bellek profili | `backend/scripts/mem_profile.py` | `ps -o rss=` ile RSS örnekler (yeni bağımlılık yok); en küçük kareler eğimiyle **düz mü / sızıntı mı** kararı. |

Yeni ayarlar (§28 sözlüğüne aynı commit'te yazıldı, kural 19): `liquidation_collector_enabled`,
`liquidation_batch_rows`, `liquidation_batch_seconds`.

---

## 2. Kabul kriterleri — SENTETİK | GERÇEK yan yana

| # | Kriter (§22.2) | SENTETİK (yerel/CI) | GERÇEK (operatör/sunucu) | Durum |
|---|---|---|---|---|
| 1 | `data/status` gaps=0, total_missing=0 | ✅ Faz 1 backfill+repair testinde sentetik seride gaps=0 (`test_sync`) | ⏳ 24-ay backfill sunucuda; `reality_check` "Faz 1 data/status" satırı | **Operatör** |
| 2 | Gerçek 10×4 tarama süresi ölçüldü (>2h ise "aşıyor") | ✅ fast-mode uçtan uca ~8 sn (`test_discovery_pipeline`); tam 225-registry aşama süreleri `stage_timings`'te | ⏳ gerçek 10×4 ölçümü `reality_check --with-scan` | **Operatör** |
| 3 | Testnet long+short round trip PASS + kaldıraç/marj logu | ✅ adaptör mantığı sahte borsaya karşı testli (`test_execution_binance`) | ⏳ `scripts/testnet_smoke.py` gerçek anahtarla (Faz 7'den beri ⏳) | **Operatör** |
| 4 | 72 saat kesintisiz paper; RSS düz; kopma+reconnect logu | ✅ 50-döngü soak kararlı (`test_multi_cycle_soak_is_stable`); WS drop→reconnect **liquidation collector'da testli** (`test_loop_reconnects_after_drop_and_is_logged`) | ⏳ 72h `mem_profile --pid <worker> --hours 72` → RSS eğrisi | **Operatör** |
| 5 | Üç referans strateji tablosu + **B&H sütunu** | ✅ Aşağıda (SENTETİK sine-wave veri — **TA'yı yapay olarak şımartır**) | ⏳ gerçek veride `reference_strategies` — B&H'i yenmesi **beklenmiyor** | **Operatör** |
| 6 | `RAPOR-faz8-gerceklik.md` yazıldı | — | Bu dosya | ✅ |

**Neden bu kadar ⏳?** Faz 8'in doğası bu. Kriterlerin çoğu tanımı gereği gerçek veri,
gerçek anahtar veya 72 saat gerçek zaman ister. Kod + ölçüm araçları hazır ve testli;
sayıları üreten koşu operatörde (Faz 1/4/5/7'de kurulan RUNBOOK/plan-B deseni). Sahte
sayı yazmak kural 13'ü çiğnerdi.

---

## 3. Referans stratejiler — SENTETİK koşu (kalibrasyon çubuğu)

Aşağıdaki tablo **sentetik sine+drift fixture** üzerindedir (2000 bar, 1h). **Bu veri
TA stratejilerini yapay olarak şımartır** (mükemmel döngüsel ortalama-dönüş), bu yüzden
sayılar saçma derecede pozitiftir ve **strateji kalitesi hakkında HİÇBİR ŞEY kanıtlamaz**
(kural 13). Değeri yalnızca motorun uçtan uca çalıştığını göstermektir: maliyetler
uygulanıyor, B&H hesaplanıyor, işlem sayıları makul, Donchian gerçek işlem üretiyor.

```
══ BTCUSDT · 1h (SYNTHETIC) ═══════════════════════════════════
  bars=2000  range=2026-04-29→2026-07-21  costs=ON
  strategy                  return    sharpe     maxDD   trades      vs B&H
  ─────────────────────────────────────────────────────────────────────────
  ema_cross               +509.73%     17.15   +12.84%       14    +546.05%
  rsi_reversal             -80.98%    -17.43   +82.15%        7     -44.65%
  donchian_breakout       +436.53%     16.39   +14.18%       18    +472.85%
  buy_hold                 -36.32%     -2.47   +58.30%        1           —
```

> **GERÇEK veride beklenti (v2 §22.3, önceden söyleniyor):** Üçünün de gerçek Binance
> verisinde buy & hold'u yenmesi **beklenmiyor**; muhtemelen üçü de komisyon + funding
> sonrası **negatif** ve B&H'in gerisinde çıkacak. Bu bir başarısızlık değil,
> kalibrasyondur. Basit TA'yı maliyet sonrası kazandıran motor, yalan söyleyen motordur.
> Operatör koşusunun çıktısı buraya olduğu gibi yapıştırılacak — güzelleştirilmeden.

**Operatör komutu (gerçek veri yüklendikten sonra):**
```bash
cd backend && python -m scripts.reference_strategies --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --tf 1h
```

### Karar notları (motor davranışı, dürüstlük için)
- **Boyutlandırma:** referans koşu `sizing="fixed", size_pct=1.0, leverage=1.0` kullanır
  ki strateji getirisi B&H ile aynı zeminde olsun. Canlı duvarın ATR-risk boyutlaması
  ayrı testlidir (`test_sizing`); bu çubuğun ölçtüğü o değil.
- **Donchian yapısı:** `line_cross(close, dcu)` yapısal olarak asla tetiklenmez
  (close ≤ high ≤ dcu). Bunun yerine Turtle tarzı kullanıldı: giriş = high 20-bar üst
  kanala değince (yeni N-bar yükseği), çıkış = low 20-bar alt kanala değince. İkisi de
  yalnızca bar-kapanışına kadarki veriyi kullanır → lookahead-güvenli (kural 1).
- **RSI dönüşü:** giriş RSI 30'u yukarı keserken, çıkış 50'yi yukarı keserken
  (nötr'e dönüş) — tanınabilir ortalama-dönüş şekli.

---

## 4. Likidasyon toplayıcısı — bugün başlar

> **Uyarı (v2 §22/§25):** Likidasyon verisi **geriye dönük indirilemez**. Bugün
> toplamaya başlamazsan bir yıl sonra bir yıllık boşluğun olur.

- **Akış:** `!forceOrder@arr` (tüm-piyasa, sembol listesi gerekmez).
- **Depo:** Postgres `liquidations` tablosu, `dedup_key` UNIQUE (`symbol|T|side|ap|z`).
- **Toplu yazım:** ≥500 satır **veya** ≥5 sn; `INSERT … ON CONFLICT (dedup_key) DO NOTHING`
  → reconnect replay'i çift kayıt üretmez (testli).
- **Dayanıklılık:** kopmada üstel backoff (1→2→…→60 sn tavan), her kopma **ve** her
  yeniden bağlanma loglanır (testli: `test_loop_reconnects_after_drop_and_is_logged`).
- **Bugün kullanılmıyor** — Faz 11 `liq_cascade` primitifi için sadece biriktiriyor.

**Nasıl başlatılır (ikisinden biri):**
```bash
# A) worker içinde (önerilen): .env → LIQUIDATION_COLLECTOR_ENABLED=true, worker restart
# B) tek başına / systemd:
cd backend && python -m app.data.collectors.liquidations
```

Testler (`tests/test_liquidation_collector.py`, 9/9 yeşil): parse alan eşlemesi ·
`forceOrder` olmayan mesaj reddi · satır-sayısı flush · zaman flush · **UNIQUE dedup**
(aynı olay 3× → 1 satır) · **drop→reconnect loglu**.

---

## 5. Bellek profili — yöntem

72 saatlik paper soak sırasında worker'ın RSS'i `mem_profile.py` ile örneklenir
(`ps -o rss=`, dakikada bir). Bitişte en küçük kareler eğimi + çeyrek-karşılaştırma:
eğim > ~%2/saat **ve** son çeyrek ilk çeyrekten belirgin yüksekse **LEAK SUSPECTED**,
aksi halde **FLAT**. Yerelde araç kendi kendine doğrulandı (kısa koşu → FLAT).

**Operatör komutu:**
```bash
cd backend && python -m scripts.mem_profile --pid $(pgrep -f 'arq app.workers') --hours 72 --out rss_soak.csv
# ara/son analiz:
python -m scripts.mem_profile --analyze rss_soak.csv
```

---

## 6. Operatör runbook — GERÇEK sütununu doldurmak için

Sırayla, sunucuda:

1. **Backfill** (`docs/RUNBOOK-faz1-veri.md`): 10 sembol × 6 TF × 24 ay + funding.
   ```bash
   cd backend && python -m app.data.cli backfill --months 24 && python -m app.data.cli status
   ```
2. **Likidasyon toplayıcısını AÇ** (en erken — geriye dönük indirilemez):
   `.env → LIQUIDATION_COLLECTOR_ENABLED=true`, worker restart.
3. **Gerçeklik doğrulayıcı:**
   ```bash
   python -m scripts.reality_check --with-scan            # 10×4 tarama süresi dahil
   ```
4. **Testnet round trip** (Faz 7 ⏳ kapanır):
   ```bash
   export BINANCE_TESTNET_API_KEY=… BINANCE_TESTNET_API_SECRET=…
   python -m scripts.testnet_smoke --symbol BTCUSDT --qty 0.001 --leverage 5
   ```
5. **72h paper soak + RSS:** worker'ı 72h koştur, `mem_profile` ile örnekle; en az bir
   WS kopması + reconnect logda görünmeli.
6. **Referans stratejiler:** yukarıdaki komut; çıktıyı bu rapora **olduğu gibi** yapıştır.

Her adımın gerçek sayısı geldikçe §2 tablosundaki ⏳ → ✅ (veya "aşıyor") olur ve
SENTETİK sütununun yanına yazılır. **Sapma büyükse sebebi bu bölüme not düşülür.**

---

## 7. Yerelde kanıtlanan vs. operatöre kalan

**Kanıtlandı (yerel/CI):** dört aracın da uçtan uca çalışması; likidasyon collector'ın
parse/dedup/batch/reconnect davranışı (9 test); `reality_check`'in Parquet tabanlı
kontrollerinin PASS'i ve Faz 5–7 mantık paketinin yeşil re-run'ı; ruff temiz; **241 test yeşil**.

**Operatöre kalan (gerçek sayılar):** 24-ay backfill gaps=0 · gerçek 10×4 tarama süresi ·
testnet round trip · 72h RSS eğrisi + gerçek WS kopması · üç referans stratejinin gerçek
veri tablosu. Bunlar ⏳; sahte sayı yazılmadı (kural 13).

*Faz 8'in amacı iyi haber almak değil, hangi haberi aldığını bilmektir.*
