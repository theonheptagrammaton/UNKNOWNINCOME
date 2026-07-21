# UNKNOWNINCOME — Claude Code Prompt Kitabı v2
### Faz 8–13 · aynı ritüel: plan → onay → kod → test → push → deploy → sunucu testi

Kaynak gerçek: `docs/PROJE_DOKUMANI.md` (v1.1) + `docs/PROJE_DOKUMANI-v2.md` (v2.0).
Çelişki olursa **v2 kazanır**. Kurallar `CLAUDE.md`'den her oturumda yüklenir; promptlar
bu yüzden kısadır.

---

## P-V2 — v2'ye geçiş (bir kez, kod yazmadan)

```text
UNKNOWNINCOME v2'ye geçiyoruz. Bu adımda KOD YAZMA.

1. docs/PROJE_DOKUMANI-v2.md'yi oku (v1.1'i geçersiz kılmaz, üstüne biner).
2. CLAUDE.md'yi güncelle:
   - Kural listesine 13–20'yi ekle (v2 §21). Mevcut 1–12 aynen kalır.
   - "Kaynak gerçek" satırına v2 dokümanını ekle ve çelişkide v2'nin
     kazandığını yaz.
   - Şu cümleyi aynen ekle: "devseed SENTETİKTİR ve hiçbir kabul kriterini
     kapatamaz (kural 13)."
3. docs/PROGRESS.md'ye Faz 8–13 bölümlerini ekle (kapsam + kabul kriterleri +
   boş durum kutuları). Faz 0–7 satırlarına dokunma.
4. Faz 0–7'nin kabul kriterlerini tara ve SENTETİK VERİYLE kapatılmış olanların
   listesini çıkar. Bunlar Faz 8'in iş listesidir.
5. git commit: "docs: v2 addendum + kural 13-20"; push origin main.

Rapor: değişen dosyalar + sentetikle kapatılmış kriterlerin listesi.
```

---

## FAZ 8 — Gerçeklik Teması

> Bu fazda yeni özellik yok. Ölçüm var. Rapor kod değil, **sayı** üretir.

```text
FAZ 8 — Gerçeklik Teması
docs/PROJE_DOKUMANI-v2.md §22'yi oku. Plan sun, onaydan sonra uygula.
Bu faz YENİ ÖZELLİK İÇERMEZ. Bir şey eklemek istiyorsan durup bana sor.

KAPSAM
- Likidasyon toplayıcısı (data/collectors/liquidations.py): Binance
  !forceOrder@arr WS, dedup_key UNIQUE, 5 sn/500 satır toplu yazım, kopmada
  yeniden bağlanma. BUGÜN BAŞLASIN — bu veri geriye dönük indirilemez.
  Henüz hiçbir yerde kullanılmayacak, sadece biriktirilecek.
- scripts/reality_check.py: tek komutla Faz 1-7'nin tüm kabul kriterlerini
  GERÇEK veriyle yeniden koşan ve tablo basan bir doğrulayıcı.
- scripts/reference_strategies.py: EMA9x21 kesişimi, RSI(14) aşırı satım
  dönüşü, Donchian(20) kırılımı — üçü de gerçek veride, maliyetler AÇIK,
  BUY & HOLD sütunuyla birlikte.
- Bellek profili: 72h paper koşusunda RSS örneklemesi -> düz mü, sızıntı mı.

KABUL (hepsi GERÇEK veriyle)
- data/status: gaps=0, total_missing=0.
- Gerçek 10 sembol x 4 TF tarama süresi ÖLÇÜLDÜ. 2 saati aşıyorsa
  "aşıyor" diye yaz; eşiği düşürme, kapsamı kısma.
- testnet_smoke long+short round trip PASS; venue'nun bildirdiği kaldıraç
  ve marj modu logda.
- 72 saat kesintisiz paper; RSS eğrisi düz; en az bir WS kopması ve otomatik
  yeniden bağlanma logda.
- Üç referans strateji tablosu: getiri, Sharpe, MaxDD, işlem sayısı, B&H farkı.

BEKLENTİ (önceden söylüyorum)
Referans stratejilerin B&H'i yenmesi BEKLENMİYOR. Maliyet sonrası negatif
çıkmaları normaldir ve motorun doğru çalıştığının kanıtıdır. Sonuçları
güzelleştirme, olduğu gibi yaz.

TESLİM
- docs/RAPOR-faz8-gerceklik.md: her kriter için SENTETİK sayı | GERÇEK sayı
  yan yana tablo. Sapma büyükse sebebini yaz.
- PROGRESS.md güncelle; push; tag: faz-8.
```

**Sunucu testi:** RUNBOOK-faz1-veri.md'yi baştan sona koş → `status` çıktısında `gaps=0` gör · testnet anahtarını Ayarlar UI'ından gir → smoke script'i koş, çıktıyı rapora yapıştır · paper botu 72 saat açık bırak, üçüncü gün `docker stats` ve worker logunu kontrol et · referans strateji tablosunu oku ve **hayal kırıklığına uğramaya hazır ol.**

---

## FAZ 9 — İstatistiksel Dürüstlük Katmanı

```text
FAZ 9 — Deflasyon Kapısı
docs/PROJE_DOKUMANI-v2.md §23'ü oku. Plan sun, onaydan sonra uygula.

KAPSAM
- research/registry.py: append-only deney kütüğü. Her denenen hipotez bir
  satır: trial_id, scan_id, genome_hash (kanonik), symbol, tf, period,
  is_metrics, oos_metrics, stage, created_at. TARAMA ÜSTÜ ve KALICI —
  genome ailesi bazında toplam deneme sayacı buradan okunur.
- research/deflation.py:
  * expected_max_sharpe(n_trials, var_sr) -> null altında beklenen maks Sharpe
    (Bailey & Lopez de Prado 2014, Euler-Mascheroni gamma dahil)
  * deflated_sharpe(sr, sr_star, T, skew, kurtosis) -> olasılık (0-1)
  * pbo_cscv(returns_matrix, n_splits=16) -> Aşırı Uydurma Olasılığı
    (S/2 kombinasyonları, IS-en-iyisinin OOS medyan altı düşme oranı)
  Hepsi saf fonksiyon, DB'siz, bilinen referans değerlere karşı birim testli.
- discovery/pipeline: Aşama 5 ile Aşama 6 arasına "Aşama 5.5 — deflasyon
  kapısı" ekle. Eşikler: DSR >= 0.95, PBO < 0.40, OOS islem >= 30,
  OOS getiri > B&H. Bunlar CONFIG'TEN GEVŞETİLEMEZ — kod sabiti,
  değiştirmek commit gerektirir ve audit_log'a düşer.
- UI: liderlik tablosuna DSR, PBO, trials_total, B&H farkı kolonları.
  Ham Sharpe kolonuna "raw" rozeti. DSR < 0.95 olan satır soluk render.
- scripts/noise_test.py: gerçek serinin volatilitesini ve otokorelasyonunu
  eşleyen rastgele yürüyüş üretir, tam keşif hattını üzerinde koşturur.

KABUL
- NOISE TEST (bu fazın kilit kriteri): rastgele yürüyüş verisinde keşif hattı
  SIFIR aday üretir. Bir tane bile aday çıkarsa faz KAPANMAZ; kapıyı değil
  hattı düzelt.
- Aynı stratejiyi 50 kez re-opt etmek DSR'ını düşürür (deneme sayacı çalışıyor).
- Ham Sharpe'ı yüksek, DSR'ı düşük bir strateji terfi ettirilemez (test).
- Faz 8'in üç referans stratejisi kapıdan geçirildi; geçemezlerse
  "geçemedi" diye raporlandı.

TESLİM
- docs/RAPOR-faz9-deflasyon.md; PROGRESS.md; push; tag: faz-9.
```

**Sunucu testi:** `noise_test.py` koş → aday sayısı **0** olmalı · gerçek veriyle tarama koş → liderlik tablosunun **boşaldığını** gör, bu doğru davranıştır · aynı stratejiyi UI'dan 10 kez "Re-optimize" et → DSR'ının düştüğünü izle.

---

## FAZ 10 — Portföy Katmanı

```text
FAZ 10 — Portföy Katmanı
docs/PROJE_DOKUMANI-v2.md §24'ü oku. Plan sun, onaydan sonra uygula.

KAPSAM
Yeni modül backend/app/portfolio/:
- correlation.py: strateji GETİRİ serileri arası kayan 90g Pearson matrisi
  (equity seviyesi değil - farklı sermaye normalize edilir). Paper stratejiler
  de matriste.
- allocation.py: eşit-risk (varsayılan) | ters-vol | çeyrek-Kelly (tavanlı) |
  manuel kilit. Tam Kelly YASAK. Tavanlar: strateji <= %25, sembol net <= %35,
  brüt kaldıraç <= 3x.
- netting.py: aynı sembolde birden çok strateji -> TEK pozisyon, risk BİR KEZ
  sayılır, PnL orantılı atfedilir (trades.attribution json).
- limits.py: portföy günlük zarar %3, portföy DD %12 (strateji %15'ten sıkı),
  net sembol %35, brüt kaldıraç 3x, tek yön yoğunlaşması %60, aktif strateji
  sayısı 3-8 uyarı bandı.
- Korelasyon kapısı: canlı havuza girecek strateji mevcut biriyle |p| > 0.70
  ise tahsisi korelasyonla orantılı kısılır (varsayılan) veya reddedilir.

RiskLayer entegrasyonu: portföy limitleri strateji limitlerinden ÖNCE
değerlendirilir. Portföy reddi de risk_events'e düşer, gerekçesiyle.

UI: /trade'e "Portfolio" paneli — tahsis halkası, korelasyon ısı haritası
(0.70 üstü kırmızı), net maruziyet çubuğu (tavan çizgisi görünür), katkı
tablosu, düz cümleli yoğunlaşma uyarıları.

KABUL
- KLON TESTİ: birebir aynı iki strateji canlıya alınır; TOPLAM tahsisleri
  tek stratejinin tahsisine EŞİT olur (iki katı değil). Test şart.
- İki strateji aynı sembol+yönde sinyal -> borsada tek pozisyon, risk bir kez,
  PnL orantılı atıf (test).
- Portföy DD limiti, hiçbir strateji kendi limitini aşmamışken tetiklenebilir
  (test).
- Brüt kaldıraç 3x'i aşacak emir reddedilir + risk_events (test).
- Korelasyonu 0.85 olan yeni strateji tahsis kısıtı veya redle karşılanır (test).

TESLİM
- docs/RAPOR-faz10-portfoy.md; PROGRESS.md; push; tag: faz-10.
```

**Sunucu testi:** Aynı stratejiden iki kopya oluştur, ikisini de paper'a al → Portfolio panelinde toplam tahsisin tek stratejininki kadar olduğunu gör · ikisi aynı anda sinyal versin → portföyde tek pozisyon, karar günlüğünde orantılı atıf · Settings'ten portföy DD'yi geçici olarak %1'e çek → tetiklendiğini gör, sonra geri al.

---

## FAZ 11 — Alfa Yüzeyini Genişletme

```text
FAZ 11 — Alfa Yüzeyi
docs/PROJE_DOKUMANI-v2.md §25'i oku. Plan sun, onaydan sonra uygula.

KAPSAM
- Kline şemasına taker_buy_base_volume ve number_of_trades ekle. BU ALANLAR
  ZATEN BİNANCE YANITINDA VAR VE ŞU AN ATILIYOR. 24 aylık geçmiş bu iki kolon
  için yeniden indirilir (mevcut parquet'lerde yoklar).
- data/collectors/open_interest.py: 5 dk poll, OHLCV ile aynı gap disiplini.
- Funding: seviye değil DEĞİŞİM ve kendi tarihsel yüzdeliği türetilir.
- Likidasyon toplayıcısı (Faz 8'de başlamıştı) artık sorgulanabilir hale gelir.
- Yeni sinyal primitifleri (§5.4'e ek, registry'ye normal indikatör gibi girer):
  * flow_imbalance(window, threshold, dir)
  * oi_divergence(price_dir, oi_dir)
  * funding_extreme(percentile, dir)
  * liq_cascade(window, usd_threshold)

KURAL: Yeni veri MUAFİYET DEĞİLDİR. Bu primitiflerle üretilen stratejiler
Faz 9 deflasyon kapısından aynen geçer. Hiçbirine özel eşik tanımlama.

KABUL
- taker_buy_base_volume + number_of_trades parquet şemasında, 24 ay dolu.
- OI toplayıcısı 5 dk'da bir yazıyor, gap taraması çalışıyor.
- Likidasyon toplayıcısı systemd altında, kopmada yeniden bağlanıyor,
  dedup_key çift kaydı engelliyor.
- Dört primitif birim testli VE lookahead-güvenli (Faz 2 property test deseni:
  gelecekteki barları değiştir, geçmiş sabit kalsın).
- Yeni primitiflerle koşulan tarama noise_test.py'den geçiyor (kural 15).

TESLİM
- docs/RAPOR-faz11-alfa.md; PROGRESS.md; push; tag: faz-11.
```

**Sunucu testi:** Backfill'i yeniden koş (yeni kolonlar için) → `status` gaps=0 · Backtest Lab'de yeni primitifleri gör ve manuel bir strateji kur · noise_test'i yeni primitifler açıkken tekrar koş → yine 0 aday.

---

## FAZ 12 — Yürütme Kalitesi ve Kapasite

```text
FAZ 12 — Yürütme + Kapasite
docs/PROJE_DOKUMANI-v2.md §26'yı oku. Plan sun, onaydan sonra uygula.

KAPSAM
- execution/slippage_model.py: her gerçek dolumda beklenen vs gerçekleşen
  fiyat kaydedilir. Kova: (sembol, tf, emir_büyüklüğü_dilimi, vol_dilimi).
  N>=50 dolumdan sonra backtest ÖĞRENİLMİŞ modeli kullanır.
  Öğrenilmiş model varsayımdan KÖTÜYSE geçmiş backtestler yeniden koşulur ve
  liderlik tablosu güncellenir. Acı verir; yap.
- Kapasite: katilim_orani = emir_büyüklüğü / bar_hacmi. Tavan %1.
  Her strateji kartında "yaklaşık $X'e kadar taşır" tahmini.
  Tavanı aşan emir reddedilir + risk_events.
- Limit emir yolu: giriş için limit, T saniye dolmazsa market fallback.
  VARSAYILAN KAPALI, opt-in, raporda ayrı etiket. Sebep: dolmayan limit
  emirler genellikle fiyatın aleyhine gittiği durumlardır - backtest'te
  modellenmesi zor bir yanlılık kaynağı.

KABUL
- 50+ gerçek dolum sonrası öğrenilmiş model devrede; sabit varsayımla farkı
  raporlandı.
- Katılım oranı %1'i aşan emir reddediliyor (test).
- Limit emir timeout -> market fallback çalışıyor (test).
- Canlı-paper tracking error, öğrenilmiş model devreye girdikten sonra
  DARALDI (önce/sonra ölçümü raporda).

TESLİM
- docs/RAPOR-faz12-yurutme.md; PROGRESS.md; push; tag: faz-12.
```

**Sunucu testi:** Testnet'te 50+ mikro dolum biriktir → slippage modelinin varsayımdan saptığını gör · TrackingPanel'de tracking error'ın daraldığını izle · bir stratejinin kapasite tahminini oku ve sermayenle karşılaştır.

---

## FAZ 13 — Kendini Geliştirme v2

```text
FAZ 13 — Kendini Geliştirme v2 (portföy düzeyi)
docs/PROJE_DOKUMANI-v2.md §27'yi oku. Plan sun, onaydan sonra uygula.

ÖNEMLİ SAPMA: v1.1 §8.3 v2 için GENETİK ALGORİTMA öneriyordu. Bu öneri
v2'de DEĞİŞTİRİLDİ. Genetik arama aynı beş sayı üzerinde daha fazla kombinasyon
dener; Faz 9 kapısı bunları zaten eleyecektir - net sonuç, çok daha fazla hesap
harcayıp aynı sayıda aday bulmaktır. Gelişme SEVİYE değiştirir: parametreden
portföye.

KAPSAM (mevcut StrategyGenerator arayüzü DEĞİŞMEZ, üç yeni uygulama)
- ScheduledRetirement: her stratejinin yarı ömrü (varsayılan 90 gün). Dolduğunda
  strateji BOZULMASA BİLE tahsisi yarıya iner ve taze OOS veriyle doğrulamadan
  geçerek yerini yeniden hak etmek zorunda kalır.
- AllocationLearner (haftalık): her stratejinin son 30 günlük gerçekleşen
  performansını doğrulama raporundaki beklentiyle karşılaştırır. Tutturanın
  tahsisi artar, sapanın azalır. Tek adımda değişim <= %20 (ani rotasyon yasak).
- HypothesisGenerator (opsiyonel araştırma rayı): rastgele kombinasyon yerine
  yapılandırılmış hipotez (ör. yüksek funding + azalan OI = zorlanmış long
  konumlanması). Kaynak: literatür/gözlem/operatör girdisi. Her hipotez deney
  kütüğüne düşer ve AYNI kapıdan geçer.
- Rejim artık filtre değil TAHSİS GİRDİSİ: strateji x rejim performans tablosu;
  aktif rejimde iyi olana tahsis kayar; geçişler yumuşatılır; ETİKETSİZ strateji
  nötr muamele görür (v1 davranışı korunur, havuz asla açlığa düşmez).

KABUL
- Yarı ömrü dolan strateji, bozulma tetiklenmeden tahsis kaybeder (test).
- ERKEN UYARI TESTİ: yavaşça bozulan bir strateji, §8.5 bozulma tetikleyicisi
  ateşlenmeden ÖNCE tahsis kaybetmeye başlar (test).
- Tahsis değişimi tek adımda %20'yi aşamaz (test).
- Rejim değişimi tahsisi kaydırır; etiketsiz strateji etkilenmez (test).
- Üç yeni üretici de aynı Doğrulayıcı -> Terfi kapısı zincirinden geçer
  (v1 §8.3 mimarisi korundu, testle kanıtlı).

TESLİM
- docs/RAPOR-faz13-gelisim.md; PROGRESS.md; push; tag: faz-13.
```

**Sunucu testi:** Bir stratejinin yarı ömrünü geçici olarak 1 güne çek → tahsisinin düştüğünü ve yeniden doğrulama istediğini gör · "Simulate degrade"i yavaş versiyonuyla çalıştır → tahsis kaybının bozulma alarmından **önce** başladığını izle · rejim kilidini `auto`ya al → tahsis kaymasını Portfolio panelinde gör.

---

## PROMPT N — Doğal dil katmanı (her fazda, ayrı faz değil)

Kural 19'un uygulaması. Her fazın sonunda **aynı oturumda** koştur:

```text
Bu fazda eklediğin her yeni config parametresi ve her yeni "reason" tipi için:

1. docs/PROJE_DOKUMANI-v2.md §28.2'deki uygun kuşak tablosuna satır ekle:
   ayar adı | ne yapar | yükseltirsen ne olur | düşürürsen ne olur.
   Cümleler düz Türkçe olsun, jargon yok, her biri tek satır.
2. Yeni reason tipleri için §28.3'teki çevirmen fonksiyonuna case ekle:
   JSON -> tek cümlelik Türkçe/İngilizce açıklama.
3. UI'da bu ayarın yanına bir "?" tooltip'i koy; içeriği §28.2'deki satır olsun.
   Tek kaynak: tablo ile tooltip aynı metni okusun, kopyala-yapıştır olmasın.

Açıklaması olmayan ayar merge edilmez (kural 19). Eksik varsa şimdi tamamla.
```

---

## PROMPT B — Günlük brifing (Faz 10 sonrası bir kez)

```text
Günlük operatör brifingi ekle (v2 §28.1).

- bot/briefing.py: saf fonksiyon, son 24 saatin durumunu TEK PARAGRAF düz
  cümleye çevirir. Girdi: trades, equity_snapshots, risk_events, tahsis
  değişimleri, bekleyen onaylar. Çıktı: string.
- Ton: sakin, sayısal, abartısız. Örnek:
  "Dün 4 işlem, net -%0,3. TrendPullback-v3 tahsisini %18'den %14'e düşürdüm
   çünkü son 30 işlem doğrulama beklentisinin altında kaldı. Onayını bekleyen
   1 yeni versiyon var. Portföy DD %4,1 - limitin (%12) içinde."
- Her sabah 09:00 Europe/Istanbul: Telegram'a gönder.
- /trade sayfasının en üstünde de göster.
- Telegram komut seti: /brief ekle.
- Birim test: bilinen bir durum -> beklenen cümle parçaları.

Bu bir özellik değil, sistemin sana rapor verme biçimi. Uzun yazmasın;
bir paragraf, dört cümleyi geçmesin.
```

---

## PROMPT D2 — Denetim v2 (faz aralarında)

v1'in Prompt D'si geçerli, üstüne bunlar:

```text
Denetçi şapkanı tak; kod yazma, yalnızca raporla.

v1 denetim maddelerine ek olarak:
6) SENTETİK SIZINTI: devseed verisiyle kapatılmış, gerçek veriyle
   doğrulanmamış kabul kriteri var mı? (kural 13)
7) DEFLASYON ATLAMASI: ham metriğin deflasyon kapısına uğramadan terfi
   kararına ulaşabildiği kod yolu var mı? (kural 14)
8) PORTFÖY ATLAMASI: RiskLayer'a portföy limitlerine uğramadan varan emir
   yolu var mı? (kural 16)
9) DENEME SAYACI KAÇAĞI: deney kütüğüne düşmeyen bir optimizasyon/deneme
   çağrısı var mı? Kaçak varsa DSR sistematik olarak fazla iyimser olur.
10) NETLEŞTİRME HATASI: aynı sembolde iki strateji riski iki kez sayan bir
    kod yolu var mı?
11) AÇIKLAMASIZ AYAR: §28.2'de karşılığı olmayan config parametresi var mı?
    (kural 19)

Her bulgu: dosya:satır, açıklama, önerilen düzeltme. Bulgu yoksa "temiz" de
ve nasıl doğruladığını yaz.
```

---

## PROMPT S2 — Sunucu geri bildirimi

v1'in Prompt S'i aynen geçerli. Tek ek:

```text
Sunucuda şu davranışı gördüm: {tarif}
Log/çıktı: {yapıştır}

Düzeltmeden önce şunu söyle: bu bir KOD hatası mı, yoksa gerçek verinin
sentetik veriden farklı davranmasından kaynaklanan bir VARSAYIM hatası mı?
İkincisiyse hangi varsayım yanlıştı ve dokümanın hangi satırı güncellenmeli?
```

---

## Faz sırası — pazarlıksız

```
8 → 9 → 10   (çekirdek, sırayla)
        ├── 11  (alfa yüzeyi)
        ├── 12  (yürütme)
        └── 13  (gelişim v2)
```

**Faz 9'suz Faz 10 anlamsızdır** — gürültüden portföy kurmuş olursun.
**Faz 8'siz Faz 9 anlamsızdır** — neyi düzelttiğini bilmezsin.

11–13 arasındaki sıra serbesttir. Ama likidasyon toplayıcısı **Faz 8'de** başlar;
o veri geriye dönük indirilemez ve beklediğin her gün kalıcı bir boşluktur.

---

*UNKNOWNINCOME Prompt Kitabı v2 — sonu. v1 kitabıyla birlikte kullanılır.*
