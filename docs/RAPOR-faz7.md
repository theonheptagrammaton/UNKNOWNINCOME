# RAPOR — Faz 7: Canlı Yürütme (kapının arkasında)

Kapsam: `docs/PROJE_DOKUMANI.md` §9.2–9.5, §13 + §15/Faz 7. Durum: **tamam** (2026-07-21),
**canlı sermaye ile açılış hariç** — o adım operatöre ait ve `docs/GO_LIVE_CHECKLIST.md`
ile kapıya bağlandı.

## Başlangıç durumu — dürüst not

Faz 7'nin backend'i bu fazdan önce `b26c464 "latest undone"` commit'inde **zaten
yazılmıştı**: adaptör, kapı, dayanıklılık, kasa, tracking. Ancak commit belirsiz
adlandırılmış, etiketlenmemiş, belgelenmemiş ve **lint'ten geçirilmemişti**; frontend
tarafı ise hiç başlanmamıştı — üç Faz-7 endpoint'i (`/bot/gate`, `/bot/tracking`,
`/bot/keys`) UI'dan tüketilmiyordu. Bu faz o işi tamamladı, denetledi ve **bir gerçek
güvenlik açığı buldu/kapattı** (aşağıda §Anahtar sızıntısı).

`b26c464` uzak depoya push edilmiş olduğundan geçmiş yeniden yazılmadı (amend yapılmadı);
düzeltmeler üstüne commit'lendi.

## Ne yapıldı

### Canlı adaptör — `execution/binance.py` (§9.2–9.4)
- `BinanceFuturesAdapter`, paper sim ile **aynı** `ExecutionAdapter` yüzeyi: bot ve risk
  duvarı moddan habersiz kalır, satırlar aynı tablolara yalnızca `mode="live"` farkıyla düşer.
- **Isolated marj + one-way** ilk emirden önce sembol bazında set edilir, cross'a asla
  çevrilmez (kural #11). "No need to change" (-4059/-4046) hataları idempotent kabul edilir.
- **Kaldıraç** risk duvarının onayladığı değerdir — 10x tavanı ve likidasyon tamponu
  derating'i duvarda uygulanmış olarak gelir; adaptör yalnızca venue'ya yazar.
- **Testnet varsayılan** (`set_sandbox_mode`); mainnet ikinci ve bilinçli bir config şalteri.
- Pozisyon/bakiye **borsadan** okunur (mutabakatın doğruluk kaynağı); lokal ayna yalnızca
  kapanışta realized PnL atfetmek için tutulur ve restart'ta borsadan yeniden tohumlanır.

### Dayanıklılık — `execution/resilience.py` (§9.2)
- Geçici hata sınıfı (network/timeout/ratelimit/DDoS/unavailable) **üstel backoff** ile
  retry edilir; kalıcı hata (bad request) retry edilmez.
- **Devre kesici**: ardışık `threshold` hatadan sonra açılır, `cooldown` boyunca hızlı
  başarısız olur, tek başarı kapatır. Açık kesici = "borsaya ulaşılamıyor" → bot o tick
  emir göndermez (bloklamaz, yarım state bırakmaz).
- Saat ve sleep enjekte edilebilir → deterministik birim testi.

### Terfi kapısı — `bot/promotion.py` (§9.5)
Sayısal, his değil: ≥30 gün, ≥30 işlem, PF ≥ 1,3, MaxDD ≤ %10 (hepsi config) **artı**
altyapı hazırlığı (`live_trading_enabled` + şifreli anahtar mevcut). Sicil geçse bile
yapılandırılmamış bir venue'ya yol açılmaz.

**Ret her katmanda** (`assert_can_go_live`), kabul kriterinin özü:

| Katman | Nerede |
|---|---|
| Kapı fonksiyonu | `assert_can_go_live` → `GateNotMet` |
| Mod modülü | `mode.set_global_mode` kalıcılaştırmadan önce reddeder |
| Strateji servisi | `service` strateji şalterini reddeder |
| HTTP API | `POST /bot/mode`, `POST /strategies/{id}/mode` → 422 + gerekçe |
| Bot motoru | kapı kapalıyken canlı duvarı **hiç inşa etmez** (teknik kapanış) |
| UI | LIVE düğmesi disabled + tooltip'te gerekçe |

Tek katman yeterdi; hepsinin olması **kasıt**. `test_promotion_gate.py` her katmanı ayrı
ayrı kanıtlar (10 test).

### Anahtar kasası — `core/secrets.py` + `core/logging.py` (§13, kural #7)
- **Fernet** ile şifreli saklama; ana anahtar yalnızca env'de (`SECRETS_KEY`), DB'de
  yalnızca şifreli metin + `····last4` maskesi + testnet bayrağı.
- Ana anahtar yoksa kasa **düz metin fallback yapmaz**, hata verir — sessiz düşüş yok.
- Düz metin API sınırını asla geçmez; çözme yalnızca sunucuda, adaptör kurulmadan hemen önce.

#### Anahtar sızıntısı — bu fazda bulunan gerçek açık
Redaksiyon filtresi yalnızca `record.msg` ve `record.args`'ı temizliyordu. **Exception
traceback'i filtrelerden sonra render edildiği için taranmıyordu** — `logger.exception(...)`
ile loglanan, mesajında `apiKey=…` taşıyan bir ccxt hatası loglara **düz metin** düşüyordu.
Kabul kriteri açıkça "loglar **ve hata mesajları** taranır" dediği için bu gerçek bir
kabul ihlaliydi.

Kapatılan dört vektör: `msg` · `args` · **exception traceback** (`exc_text` önceden
render edilip temizlenir, formatter cache'lenmiş değeri kullanır) · `stack_info`, artı
**str olmayan `msg`** (`logger.error(exc)` — sonradan `str()` ile render edilirdi).
İki regresyon testi eklendi; açık, düzeltmeden önce bir probe ile üretilip doğrulandı
(`LEAKED: True` → `LEAKED: False`, traceback korunur, anahtar `····redacted····` olur).

### Canlı-paper sapma — `bot/tracking.py`
Aynı genome, aynı sinyaller → **getiriler** izlemeli (seviye değil; farklı sermaye
normalize edilir). Metrik: per-tick getiri farkının standart sapması (tracking error) +
kümülatif getiri farkı + korelasyon. Saf fonksiyon → birim testli.

### Frontend (bu fazın asıl eksiği)
- `lib/api.ts`: `fetchGate` / `fetchTracking` / `fetchKeys` / `saveKeys` + tipler.
- **`GatePanel.tsx`** — "Live readiness": kapı açık/kapalı rozeti, altyapı durumu,
  karşılanmayan eşiklerin **birebir listesi**, strateji bazlı metrik tablosu.
- **`TrackingPanel.tsx`** — "Live vs paper": tracking error, kümülatif fark, korelasyon;
  15 sn'de bir yenilenir; yeterli örtüşen veri yoksa bunu açıkça söyler.
- **`SettingsPanel.tsx`** — maskeli API anahtarı girişi: `type=password` alanlar,
  kayıttan sonra input'lar temizlenir, geri **yalnızca maske** okunur; testnet/mainnet
  şalteri ve mainnet için kırmızı uyarı.
- **`TradeDeck.tsx`** — LIVE düğmesi artık kapıya bağlı: kapı kapalıyken disabled ve
  tooltip **gerekçeyi** söyler (sunucunun reddine tıklatıp öğrenmek yerine). Eski
  "LIVE disabled until Phase 7" metni kaldırıldı; durum satırı artık
  `off in config / gate closed / gate open` gösterir.
- Not: UI katmanı **kilit değil kolaylıktır** — API ve bot motoru kapıyı bağımsız uygular.

### Testnet duman testi — `backend/scripts/testnet_smoke.py`
Birim testler adaptörün mantığını sahte borsaya karşı kanıtlar; **gerçek venue'nun
isolated/one-way/leverage çağrılarımızı kabul ettiğini ve mikro emri doldurduğunu**
kanıtlayamaz. Script tam olarak bunu yapar: bakiye → mikro **long** aç/pozisyon oku/kapat
→ mikro **short** aç/oku/kapat → venue'nun bildirdiği kaldıraç ve marj modunu loglar.
Anahtarlar yalnızca env'den okunur, `testnet=True` sabittir (bilerek konfigüre edilemez),
10x üstü kaldıraç reddedilir.

## Kabul kriterleri — kanıt

| Kriter | Durum | Kanıt |
|---|---|---|
| Gate sağlanmadan LIVE her katmanda reddedilir | ✅ | `test_promotion_gate.py` — 10 test: kapı fn, mod modülü, strateji servisi, HTTP API (422), **motor canlı duvarı hiç kurmaz**; UI'da disabled + gerekçe |
| Likidasyon tamponu derating'i çalışır | ✅ | `test_execution_risk.py::test_liquidation_buffer_auto_delevers` |
| Kaldıraç/marj modu doğru set edilir | ✅ birim · ⏳ venue | `test_execution_binance.py::test_open_long_sets_isolated_oneway_and_leverage` (sahte borsa, çağrı sırası + one-way tam bir kez). **Gerçek testnet log kanıtı bekliyor** — aşağı bakın |
| Anahtar sızıntı testi: log + hata mesajlarında iz yok | ✅ | `test_secrets.py` 8 test; traceback + non-str msg vektörleri **bu fazda bulunup kapatıldı** |
| Testnet'te mikro long/short açılıp kapanır | ⏳ | `scripts/testnet_smoke.py` hazır; **çalıştırmak operatörün testnet anahtarlarını gerektirir** |

### Dürüst eksik
**Gerçek testnet round-trip'i henüz koşulmadı.** Binance testnet anahtarı bende yok ve
uydurma bir çıktı üretmek bu fazın amacına aykırı olurdu. Script hazır; anahtarlar
girildiğinde tek komutla koşar ve çıktısı bu rapora eklenmelidir:

```
export BINANCE_TESTNET_API_KEY=... BINANCE_TESTNET_API_SECRET=...
cd backend && python -m scripts.testnet_smoke --symbol BTCUSDT --qty 0.001 --leverage 5
```

Bu koşu yapılana kadar Faz 7 "kod tamam, **venue doğrulaması bekliyor**" sayılmalıdır.
Kontrol listesinin §4'ü bu adımı zorunlu tutar.

## Doğrulama

- **pytest 223/223 yeşil** (Faz 6 sonu 221 → +2 yeni sızıntı regresyonu).
- **ruff temiz** — Faz-7 backend'inden devralınan 8 lint hatası (E501 ×7, UP047) da
  düzeltildi; `call_resilient` PEP 695 tip parametresine geçirildi.
- **`next build` başarılı** — tip kontrolü + eslint temiz; `/trade` 7,37 kB → **9,07 kB**.

## Kararlar

1. **Kapı çok katmanlı bırakıldı** (tek katman yeterken beş). Canlı emir yolu için
   savunma derinliği maliyetten önemli.
2. **UI kilit değil kolaylık** olarak konumlandı: sunucu bağımsız reddeder; UI yalnızca
   kullanıcıyı reddedilecek bir tıklamadan korur ve gerekçeyi gösterir.
3. **Geçmiş yeniden yazılmadı** — `b26c464` push edilmişti; düzeltmeler üstüne commit'lendi.
4. **Testnet round-trip sahteleştirilmedi.** Kanıtı olmayan kabul kriteri, kanıtlanmış
   gibi işaretlenmedi.
5. Mainnet hâlâ ikinci bir bilinçli config şalterinin arkasında; smoke script'i mainnet'e
   hiç bakmıyor.

## Sıradaki adım (operatör)

1. Testnet anahtarlarını üret → Ayarlar UI'ından gir → `scripts/testnet_smoke.py` koş.
2. Çıktıyı bu rapora ekle; kabul tablosundaki ⏳ satırları ✅ yap.
3. `docs/GO_LIVE_CHECKLIST.md`'yi baştan sona işaretle.
4. Ancak ondan sonra mikro sermaye ile mainnet.
