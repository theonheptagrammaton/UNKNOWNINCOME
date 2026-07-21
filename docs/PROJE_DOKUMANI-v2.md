# UNKNOWNINCOME — Proje Dokümanı v2.0
## Ek Cilt: Gerçeklik, Dürüstlük, Portföy

| | |
|---|---|
| **Proje sahibi** | Eray Pişkin |
| **Durum** | Faz 7 kod tamam · venue doğrulaması bekliyor |
| **Tarih** | Temmuz 2026 |
| **İlişki** | Bu doküman **v1.1'i geçersiz kılmaz, üstüne biner.** v1.1'in §0–§19'u aynen geçerlidir. Bu cilt §20–§30'u, kural 13–20'yi ve Faz 8–14'ü ekler. Çelişki olursa **v2 kazanır**. |
| **Bağlı dosyalar** | `PROJE_DOKUMANI.md` (v1.1) · `CLAUDE.md` · `PROMPTLAR-v2.md` · `PROGRESS.md` |

---

## 20. v2'nin varlık sebebi — dürüst teşhis

### 20.1 Sistem kötü değil. Sistem **ölçülmemiş**.

Faz 0–7 raporlarının tamamı yeşil. 223 test geçiyor, lint temiz, beş servis sağlıklı,
kill switch dört kanaldan çalışıyor, anahtar sızıntısı bulunup kapatıldı. Bu ciddi bir
mühendislik işi ve küçümsenmemeli.

Ama her rapor aynı dipnotu taşıyor:

> `devseed` verisi **SENTETİKTİR** (güçlü döngüsel seri) — metrikler abartılıdır,
> sadece uçtan-uca akışı göstermek içindir.

Envanteri çıkaralım:

| Kabul kriteri | Durum | Neye karşı doğrulandı |
|---|---|---|
| 10 sembol × 6 TF × 24 ay gerçek veri | `[~]` | **hiç yüklenmedi** |
| 10×4 tarama < 2 saat | `[~]` | sentetik seride 8 saniye |
| Paper bot 72 saat kesintisiz | `[~]` | 50 döngü birim testi |
| Testnet mikro long/short round trip | `[ ]` | **hiç koşulmadı** |
| Backtest metrikleri | ✓ mekanik | sentetik döngüsel seri |

**Yani sistem bugüne kadar tek bir gerçek mum görmedi.**

"Kötü hâlâ iyi değil" cümlesi bu yüzden bir gözlem değil, bir varsayım. Sistemin iyi mi
kötü mü olduğunu kimse bilmiyor — ölçülmedi. Sentetik döngüsel seride her ortalama-dönüş
stratejisi kazanır; gerçek piyasada aynı strateji komisyonda ölür. Elindeki yeşil
metrikler bir yetenek kanıtı değil, boruların tıkalı olmadığının kanıtı.

**v2'nin ilk fazı bu yüzden kod yazmaz. Ölçer.**

### 20.2 "Kusursuz strateji" — kavramsal düzeltme

Talebin şuydu: *"asıl odak en kusursuz stratejiyi bulup onunla trade yapacak bir sistem."*

Kusursuz strateji yoktur. Sebebi teknik değil, yapısal:

1. **Piyasa durağan değildir.** Bir stratejinin sömürdüğü örüntü, piyasanın belli bir
   rejimindeki katılımcı davranışıdır. Rejim değişince örüntü değişir.
2. **Piyasa rakiplidir.** Kârlı bir örüntü keşfedildiğinde sömürülür; sömürüldükçe
   kalabalıklaşır; kalabalıklaştıkça kâr kapanır. Edge kendi başarısıyla ölür.
3. **Bulduğun her strateji zaten geçmişte kazanmış olandır.** Geleceği değil, geçmişi
   optimize ediyorsun. Bu yapısal bir gecikmedir, daha iyi kod düzeltmez.

Aranan şey bu yüzden yanlış tanımlanmıştır. Doğru hedef:

> **Kusursuz strateji değil, kusursuz süreç.**
>
> Küçük ve bozulan edge'leri bulan, istatistiksel olarak dürüst şekilde eleyen,
> güvene göre boyutlandıran, bozulduğunda hızla öldüren ve yerine yenisini koyan
> bir **portföy işletmesi**.

Bu ulaşılabilir. Ve sen %70'indesin — v1'de eksik olan, tek stratejiden portföye geçiş.

### 20.3 v1'in beş yapısal boşluğu

| # | Boşluk | Neden önemli |
|---|---|---|
| 1 | **Çoklu test düzeltmesi yok** | `combos_tried` gösteriliyor ama skoru düzeltmiyor. v1.1 §6.5-5 bunu zaten "v2" diye işaretlemiş. Binlerce deneme yapıp en iyisini seçmek, gürültüden şampiyon üretmektir. |
| 2 | **Portföy katmanı yok** | Her şey tek strateji. `max_concurrent_positions=5` var ama "bu 5 pozisyon aynı bahis mi?" sorusu sorulmuyor. Beş strateji aynı anda BTC long ise elinde 5 strateji değil 1 pozisyon var. |
| 3 | **Kapasite bilinmiyor** | 1.000$'da %200 yapan strateji 100.000$'da −%5 yapabilir. Hiçbir yerde "bu edge kaç dolara kadar taşır" ölçülmüyor. |
| 4 | **Alfa yüzeyi dar** | Yalnızca OHLCV + funding. Fiyattan çıkarılabilecek edge'ler en kalabalık olanlardır. Üstelik indirdiğin kline verisindeki **taker alış hacmi** kullanılmadan çöpe gidiyor. |
| 5 | **Kendini geliştirme sadece parametre oynatıyor** | WFO re-opt kuralları sabit tutar. Genetik/RL "tanımlı ama boş". Ama daha çok arama = daha çok aşırı uydurma; boşluk mekanizmada değil, **seviyede**: gelişme portföy düzeyinde olmalı. |

---

## 21. Pazarlıksız İlkeler — Ek (13–20)

v1.1 §2'deki 1–12 aynen geçerlidir. Bunlar üstüne biner.

13. **Sentetik veriyle kabul kriteri kapatılamaz.** `devseed` bir geliştirme kolaylığıdır,
    bir kanıt değildir. Her kabul kriteri gerçek piyasa verisiyle tekrar doğrulanır.
    *Sentetik veride kazanan bir strateji, kendi yazdığın sınavdan geçmiştir.*

14. **Ham metrik tek başına terfi ettirmez.** Her sıralamada ham Sharpe'ın yanında
    **düzeltilmiş** (deflated) değeri görünür; terfi kararı düzeltilmiş değere bakar.
    Ham metrik UI'da "ham" etiketi taşır.

15. **Gürültü testi zorunlu ve tekrarlıdır.** Keşif hattı düzenli olarak **rastgele
    yürüyüş** verisine karşı koşulur. Gürültüden aday çıkıyorsa hat bozuktur ve
    kullanılmaz. Bu, sistemin kendi kendine yalan söylemediğini kanıtlayan tek testtir.

16. **Risk portföy düzeyinde ölçülür.** Hiçbir stratejinin riski tek başına değerlendirilmez.
    Pozisyonlar sembol bazında netleştirilir; korelasyon bir tahsis girdisidir.

17. **Kapasite bilinmeden ölçek büyütülmez.** Her stratejinin doyum büyüklüğü tahmin edilir;
    tahmin yoksa büyütme yasaktır.

18. **Her strateji ölümlüdür.** Her stratejinin tanımlı bir **yarı ömrü** vardır ve
    tahsisini periyodik olarak yeniden hak etmek zorundadır. Bozulmayı beklemek geç kalmaktır.

19. **Her ayar doğal dil açıklamasıyla doğar.** Yeni bir config parametresi eklenirken
    aynı commit'te §28 sözlüğüne şu üç satır yazılır: *ne yapar · yükseltirsen ne olur ·
    düşürürsen ne olur*. Açıklaması olmayan ayar merge edilmez.

20. **Canlı sapma ölçülmekle kalmaz, kapatılır.** Tracking error eşiği aşarsa panel
    kırmızıya dönmez — sistem otomatik olarak Paper'a düşer ve bildirim gönderir.

---

## 22. Faz 8 — Gerçeklik Teması

> **Bu fazda tek satır yeni özellik yazılmaz.** Var olan sistemin gerçek dünyada ne
> yaptığı ölçülür. Bu fazın çıktısı kod değil, **sayılardır**.

### 22.1 Kapsam

1. **Gerçek veri yüklemesi.** `RUNBOOK-faz1-veri.md` sunucuda baştan sona koşulur.
   10 sembol × 6 TF × 24 ay + funding. `status` çıktısında `gaps=0`.
2. **Gerçek tarama ölçümü.** 10 sembol × 4 TF standart tarama gerçek veriyle koşulur.
   Kabul kriteri "< 2 saat" ilk kez gerçekten ölçülür. Aşama süreleri kaydedilir.
3. **Testnet round trip.** `scripts/testnet_smoke.py` gerçek testnet anahtarıyla koşulur;
   çıktı `RAPOR-faz7.md`'ye eklenir, ⏳ satırları ✅ olur.
4. **72 saatlik paper soak.** Gerçek canlı fiyat akışıyla, kesintisiz. Bellek sızıntısı,
   bağlantı kopması, yeniden bağlanma davranışı gözlenir.
5. **Referans strateji karşılaştırması.** Üç bilinen basit strateji (EMA9×21 kesişimi,
   RSI aşırı satım dönüşü, Donchian kırılımı) gerçek veriyle koşulur ve **buy & hold**
   ile karşılaştırılır. Bu, motorun kalibrasyon çubuğudur.

### 22.2 Kabul kriterleri

- [ ] `data/status` gerçek veride `gaps=0`, `total_missing=0`.
- [ ] Gerçek 10×4 tarama süresi ölçüldü ve raporlandı (2 saati aşıyorsa **aşıyor** diye yazılır,
      eşik düşürülmez).
- [ ] Testnet long+short round trip PASS, venue'nun bildirdiği kaldıraç/marj modu loglandı.
- [ ] 72 saat kesintisiz paper koşusu; RSS bellek eğrisi düz; kopma sonrası otomatik yeniden bağlanma loglandı.
- [ ] Üç referans strateji gerçek veri sonuçları tabloda; **buy & hold sütunuyla birlikte**.
- [ ] `RAPOR-faz8-gerceklik.md` yazıldı: sentetik sayılar ile gerçek sayılar yan yana.

### 22.3 Beklenen sonuç — önceden söyleniyor

Üç referans stratejinin gerçek veride buy & hold'u yenmesi **beklenmiyor**. Muhtemelen
üçü de komisyon + funding sonrası negatif çıkacak. Bu bir başarısızlık değil, kalibrasyondur:
motorun doğru çalıştığının kanıtıdır. Basit TA stratejilerinin maliyet sonrası kaybetmesi
literatürün beklentisidir; onları kazandıran bir motor, yalan söyleyen bir motordur.

*Faz 8'in amacı iyi haber almak değil, hangi haberi aldığını bilmektir.*

---

## 23. Faz 9 — İstatistiksel Dürüstlük Katmanı

v1.1 §6.5-5'in ertelediği borç burada kapanır.

### 23.1 Problem

Keşif hattı şunu yapıyor: 225 indikatör × N sembol × M zaman dilimi tekli tarama →
korelasyon eleme → rol tabanlı kombinasyon (binlerce) → her aday için Optuna TPE
(yüzlerce deneme) → WFO. Toplam etkin deneme sayısı **on binler** mertebesinde.

On bin deneme yapıp en iyisini seçtiğinde, o "en iyi" büyük olasılıkla en şanslı olandır.
WFO + Monte Carlo + plato testi bu riski **azaltır ama ölçmez**. Ölçmek için denenen
sayının kendisi hesaba katılmalıdır.

### 23.2 Deney kütüğü — `research/registry.py`

Append-only, kalıcı, **tarama üstü** bir kayıt. Her denenen hipotez buraya düşer:

| Alan | Açıklama |
|---|---|
| `trial_id` | Benzersiz |
| `scan_id` | Hangi taramadan |
| `genome_hash` | Kanonik hash — aynı hipotez iki kez sayılmaz |
| `symbol`, `tf`, `period` | Ne üzerinde test edildi |
| `is_metrics`, `oos_metrics` | Ham metrikler |
| `stage` | Hangi aşamada elendi |
| `created_at` | UTC |

**Kritik:** `trials_total` tek bir taramanın değil, **o genome ailesinin tüm zamanlardaki**
deneme sayısıdır. Bir stratejiyi haftalarca yeniden optimize edersen deneme sayacı büyür
ve düzeltilmiş skoru düşer. Bu doğru davranıştır: aynı fikri elli kez denemek, elli farklı
fikir denemekle aynı istatistiksel bedeli ödetir.

### 23.3 Deflated Sharpe Ratio — `research/deflation.py`

Bailey & López de Prado (2014). Gözlenen Sharpe'ı **deneme sayısı, çarpıklık, basıklık ve
örneklem uzunluğu** için düzeltir.

İki adımda:

1. **Null altında beklenen maksimum Sharpe** — N bağımsız deneme yapıldığında, hepsi
   gerçekte sıfır edge'e sahip olsa bile en iyisinin beklenen Sharpe'ı:
   ```
   SR*₀ = √Var[SR] · [ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]
   γ = Euler-Mascheroni ≈ 0.5772
   ```
2. **DSR** — gözlenen Sharpe'ın bu eşiği aşma olasılığı:
   ```
   DSR = Z[ (SR − SR*₀)·√(T−1) / √(1 − γ₃·SR + ((γ₄−1)/4)·SR²) ]
   γ₃ = getiri çarpıklığı, γ₄ = basıklık, T = gözlem sayısı
   ```

**Yorum:** DSR bir olasılıktır. `DSR = 0.95` → "bu Sharpe'ın şans eseri olma olasılığı %5".
`DSR = 0.40` → **şans**.

Uygulama notu: N için etkin deneme sayısı kullanılır; korelasyonlu denemeler N'i şişirir,
bu yüzden Aşama 2 korelasyon elemesinden sonraki bağımsız küme sayısı esas alınır.

### 23.4 PBO — Aşırı Uydurma Olasılığı (CSCV)

Deneme sayısından bağımsız ikinci savunma. Combinatorially Symmetric Cross-Validation:

1. Getiri serisini S eşit dilime böl (varsayılan S=16).
2. S/2 dilimin **tüm** kombinasyonlarını IS olarak al, tümleyeni OOS olsun (C(16,8)=12.870 kombinasyon).
3. Her kombinasyonda IS'te en iyi stratejiyi seç; onun OOS sıralamasını kaydet.
4. **PBO** = IS-en-iyisinin OOS'ta medyanın altına düştüğü kombinasyonların oranı.

`PBO ≥ 0.5` → seçim süreciniz yazı-tura kadar bilgilendirici. Hat bozuk.

### 23.5 Sert kapı

Aşama 5'ten (WFO) sonra yeni ve **pazarlıksız** bir aşama:

```
Aşama 5.5 — Deflasyon kapısı
  DSR < 0.95        → REDDET
  PBO ≥ 0.40        → REDDET
  OOS işlem < 30    → REDDET
  OOS getiri ≤ B&H  → REDDET
Hiçbiri config'ten gevşetilemez. Gevşetme yalnızca kod değişikliğiyle
mümkündür ve `audit_log`'a düşer.
```

Sebep: v1.1'in `SAVE_IF_OVER_RETURN` mantığı Moon Dev'in hatasını tekrarlar — düşük eşik
gürültüyü kaydeder. Kapıyı geçmek için kapıyı alçaltmak, kapıyı kaldırmaktır
(`GO_LIVE_CHECKLIST.md`'nin kendi cümlesi).

### 23.6 Kabul kriterleri

- [ ] **Gürültü testi (en önemli kriter):** Aynı istatistiksel özelliklere sahip (aynı
      volatilite, aynı otokorelasyon) **rastgele yürüyüş** serisi üretilir; tam keşif
      hattı bunun üzerinde koşturulur. Sonuç: **sıfır aday.** Bir tane bile aday çıkarsa
      faz kapanmaz.
- [ ] Aynı stratejiyi 50 kez yeniden optimize etmek DSR'ını düşürür (deneme sayacı çalışıyor).
- [ ] Liderlik tablosunda her satır: ham Sharpe · DSR · PBO · trials_total · B&H farkı.
- [ ] Ham Sharpe'ı yüksek ama DSR'ı düşük bir stratejinin terfi ettirilemediği testle kanıtlı.
- [ ] Faz 8'in üç referans stratejisi bu kapıdan geçirilir; geçemezlerse **geçemedikleri yazılır**.

---

## 24. Faz 10 — Portföy Katmanı

v1'in en büyük mimari boşluğu. "Kusursuz strateji" sorusunun gerçek cevabı burada.

### 24.1 Yeni modül: `backend/app/portfolio/`

```
portfolio/
├── correlation.py     # strateji getiri korelasyon matrisi
├── allocation.py      # sermaye tahsisi
├── netting.py         # sembol bazında pozisyon netleştirme
├── limits.py          # portföy düzeyi risk limitleri
└── service.py         # orkestrasyon
```

### 24.2 Korelasyon matrisi

Stratejilerin **getiri serileri** arasında (equity seviyesi değil — farklı sermaye normalize edilir)
kayan 90 günlük Pearson korelasyonu. Paper'daki stratejiler de matrise girer.

**Korelasyon kapısı:** Yeni bir strateji canlı havuza girerken, mevcut canlı stratejilerden
herhangi biriyle `|ρ| > 0.70` ise:
- ya reddedilir,
- ya da tahsisi korelasyonla orantılı olarak kısılır (varsayılan davranış).

*İki strateji %95 korele ise elinde iki strateji yok, bir stratejinin iki kopyası var —
ve iki katı riskini taşıyorsun.*

### 24.3 Tahsis motoru

| Yöntem | Ne yapar | Ne zaman |
|---|---|---|
| **Eşit risk (varsayılan)** | Her stratejiye eşit **volatilite bütçesi**; oynak strateji daha az sermaye alır | Başlangıç |
| Ters volatilite | Ağırlık ∝ 1/σ | Basit alternatif |
| **Çeyrek Kelly (tavanlı)** | f* = edge/varyans, ¼'ü alınır, strateji başına maks %25 | Güven arttıkça |
| Manuel kilit | Operatör sabitler | Her zaman mümkün |

**Pazarlıksız tavanlar:** tek strateji ≤ %25 · tek sembol ≤ %35 net maruziyet ·
brüt kaldıraç ≤ 3x (strateji bazlı 10x tavanından bağımsız ve ondan öncelikli).

Tam Kelly asla kullanılmaz. Tam Kelly matematiksel olarak büyüme-optimaldir ve pratikte
%50 drawdown'ları normal kabul eder. Çeyrek Kelly beklenen büyümenin ~%94'ünü, varyansın
~%25'iyle verir.

### 24.4 Netleştirme

İki strateji aynı anda BTCUSDT long açarsa:
- Borsada **tek** pozisyon vardır (one-way mod zaten bunu dayatıyor).
- Risk **bir kez** sayılır, iki kez değil.
- PnL atfı stratejilere orantılı dağıtılır (`trades` tablosuna `attribution` json alanı).

Bu yapılmazsa risk katmanı yalan söyler: beş strateji × %1 risk = %5 risk sanılır,
gerçekte tek yönde %5'lik tek bir bahistir.

### 24.5 Portföy düzeyi limitler (`limits.py`)

| Limit | Varsayılan | Aşılırsa |
|---|---|---|
| Portföy günlük zarar | %3 | Tüm yeni girişler durur |
| Portföy toplam DD | %12 | Kill switch (strateji bazlı %15'ten sıkı) |
| Net sembol maruziyeti | Equity'nin %35'i | Yeni giriş reddedilir |
| Brüt kaldıraç | 3x | Yeni giriş reddedilir |
| Tek yön yoğunlaşması | Net long/short ≤ %60 | Uyarı + yeni aynı-yön girişi kısıtlanır |
| Aktif strateji sayısı | 3–8 | <3 ise uyarı (çeşitlendirme yok), >8 ise uyarı (izlenemez) |

### 24.6 UI — yeni panel: Portfolio

| Bileşen | İçerik |
|---|---|
| Tahsis halkası | Her stratejinin sermaye payı, hedef vs gerçekleşen |
| Korelasyon ısı haritası | Canlı + paper stratejiler; 0.70 üstü kırmızı |
| Net maruziyet çubuğu | Sembol bazında net long/short, tavan çizgisi görünür |
| Katkı tablosu | Her stratejinin portföy getirisine ve riskine katkısı |
| Yoğunlaşma uyarıları | Düz Türkçe/İngilizce cümle: "Portföyünün %58'i tek yönde." |

### 24.7 Kabul kriterleri

- [ ] **Klon testi:** Birebir aynı iki strateji canlıya alınır. Toplam tahsisleri, tek
      stratejinin tahsisine **eşit** olur (iki katı değil). Testle kanıtlı.
- [ ] İki strateji aynı sembolde aynı yönde sinyal üretir → borsada tek pozisyon,
      risk bir kez sayılır, PnL orantılı atfedilir.
- [ ] Portföy DD limiti, hiçbir strateji kendi limitini aşmamışken tetiklenebilir (testle).
- [ ] Korelasyonu 0.85 olan yeni strateji, tahsis kısıtıyla veya reddiyle karşılanır.
- [ ] Brüt kaldıraç 3x'i aşacak emir reddedilir ve `risk_events`'e düşer.

---

## 25. Faz 11 — Alfa Yüzeyini Genişletme

v1.1 §1.3 bunları "v2+ adayı" diye kapsam dışına almıştı. v2 anı geldi.

### 25.1 Neden

Yalnızca OHLCV'den çıkarılan edge'ler dünyanın en kalabalık avlanma alanıdır. 225
indikatörün tamamı aynı beş sayının (O,H,L,C,V) türevleridir. Yeni bir sayı eklemek,
yeni bir indikatör eklemekten kat kat değerlidir.

### 25.2 Bedava olan ve kullanılmayan: taker akışı

Binance kline yanıtı zaten şu alanları içerir ve şu an **atılıyor**:

- `taker_buy_base_volume` — o mumdaki agresif alış hacmi
- `number_of_trades` — işlem sayısı

Bunlardan türetilebilecekler:
```
flow_imbalance = (2·taker_buy − volume) / volume        # −1..+1
avg_trade_size = volume / number_of_trades              # kurumsal vs perakende
```

**Bu, yeni veri indirmeden elde edilen yeni bir bilgi katmanıdır.** Faz 11'in ilk işi
budur ve maliyeti sıfırdır — sadece indirici bu iki kolonu Parquet'e yazmayı bırakmayacak.

### 25.3 Yeni veri kaynakları

| Kaynak | Maliyet | Ne katar |
|---|---|---|
| **Taker akış dengesizliği** | Sıfır (mevcut kline'da) | Agresif taraf kim |
| **Açık pozisyon (OI)** | Ücretsiz REST, 5 dk | Fiyat ↑ + OI ↑ = yeni para; fiyat ↑ + OI ↓ = short kapanışı. Aynı hareket, farklı anlam. |
| **Funding vade yapısı** | Zaten var, kullanılmıyor | Funding **seviyesi** değil **değişimi** ve uç noktaları — konumlanma göstergesi |
| **Likidasyon akışı** | Ücretsiz WS (`!forceOrder@arr`) | Zorunlu satış = geçici fiyat baskısı. Geriye dönük toplanamaz — **bugün başlat.** |

> **Uyarı (Faz 8'in dersi):** Likidasyon verisi geçmişe dönük indirilemez. Bugün toplamaya
> başlamazsan bir yıl sonra bir yıllık boşluğun olur. Faz 11'i beklemeden, **Faz 8 sırasında**
> likidasyon toplayıcısını çalıştır — kullanmasan bile biriktir.

### 25.4 Yeni sinyal primitifleri (§5.4'e ek)

```
flow_imbalance(window, threshold, dir)   # taker akış dengesizliği eşiği
oi_divergence(price_dir, oi_dir)         # fiyat–OI ayrışması
funding_extreme(percentile, dir)         # funding'in kendi tarihsel yüzdeliğinde uç
liq_cascade(window, usd_threshold)       # pencerede likidasyon yığılması
```

Bunlar registry'ye **normal indikatör gibi** girer, keşif hattından **normal gibi** geçer
ve Faz 9 deflasyon kapısına **normal gibi** takılır. Yeni veri, muafiyet değildir.

### 25.5 Kabul kriterleri

- [ ] `taker_buy_base_volume` ve `number_of_trades` Parquet şemasında; 24 aylık geçmiş
      için yeniden indirildi (bu kolonlar eski dosyalarda yok).
- [ ] OI toplayıcısı 5 dakikada bir yazıyor; gap taraması OHLCV'yle aynı disiplinde.
- [ ] Likidasyon WS toplayıcısı systemd altında; kopma sonrası otomatik yeniden bağlanma;
      `dedup_key UNIQUE` çift kayıt engelliyor.
- [ ] Dört yeni primitif birim testli ve **lookahead-güvenli** (Faz 2 property test deseni).
- [ ] Yeni primitiflerle koşulan tarama gürültü testinden geçiyor (kural 15).

---

## 26. Faz 12 — Yürütme Kalitesi ve Kapasite

### 26.1 Slippage'i öğren, varsayma

Şu an: sabit 5 bps veya 0.05×ATR. Bu bir **varsayım**, ölçüm değil.

`execution/slippage_model.py`:
- Her gerçek dolumda beklenen fiyat ile gerçekleşen fiyat kaydedilir.
- Kova bazında model: `(sembol, TF, emir_büyüklüğü_dilimi, volatilite_dilimi)`.
- N≥50 dolum biriktikten sonra backtest bu **öğrenilmiş** modeli kullanır.
- Öğrenilmiş model varsayımdan **kötüyse**, geçmiş backtestler yeniden koşulur ve
  liderlik tablosu güncellenir. Acı verir; doğrudur.

### 26.2 Kapasite tahmini

Her strateji için: sinyal barındaki hacmin ne kadarını almaya çalışıyorsun?

```
katilim_orani = emir_buyuklugu / bar_hacmi
```

- Tavan: **%1** (üstünde kendi fiyatını itiyorsun; backtest bunu modellemiyor).
- Kapasite = katılım tavanına dayanmadan taşınabilen maksimum sermaye.
- UI'da her strateji kartında: *"Bu strateji yaklaşık $X'e kadar taşır."*

### 26.3 Limit emir desteği

Taker komisyonu (4 bps) her gidiş-dönüşte 8 bps. Maker tarafında bu negatif olabilir.
- Giriş için limit emir; `T` saniye dolmazsa market'e düş.
- Backtest'te maker/taker ayrımı ayrı kalem.
- **Uyarı:** limit emirlerin dolmama riski backtest'te modellenmesi zor bir yanlılık
  kaynağıdır — dolmayan emirler genellikle fiyatın aleyhine gittiği durumlardır.
  Bu yüzden limit emir varsayılan **kapalı**, opt-in ve raporda ayrı etiketli.

### 26.4 Kabul kriterleri

- [ ] 50+ gerçek dolum sonrası öğrenilmiş slippage modeli devrede; sabit varsayımla farkı raporlanıyor.
- [ ] Her strateji kartında kapasite tahmini; katılım oranı %1'i aşan emir reddediliyor.
- [ ] Limit emir yolu testli; `T` saniye timeout sonrası market fallback çalışıyor.
- [ ] Canlı-paper tracking error, öğrenilmiş model devreye girdikten sonra **daraldı** (ölçüldü).

---

## 27. Faz 13 — Kendini Geliştirme v2 (portföy düzeyinde)

### 27.1 Neden genetik algoritma değil

v1.1 §8.3 v2 için genetik algoritma öneriyordu. **Bu öneri v2'de değiştirilmiştir.**

Genetik arama, aynı beş sayı üzerinde daha fazla kombinasyon dener. Faz 9 kapısı bunları
zaten eleyecektir — yani sonuç, çok daha fazla hesap harcayıp aynı sayıda aday bulmaktır.
Arama uzayını büyütmek, istatistiksel bedeli büyütür.

**Gelişme mekanizması seviye değiştirmelidir: parametreden portföye.**

```
v1: Bir stratejinin parametrelerini yenile.
v2: Portföyün strateji bileşimini ve sermaye dağılımını sürekli yenile.
```

### 27.2 Üç yeni üretici

`StrategyGenerator` registry'sine (v1 §8.3 arayüzü değişmeden) eklenir:

**1. `ScheduledRetirement` — zorunlu emeklilik**
Her stratejinin bir **yarı ömrü** vardır (varsayılan 90 gün). Yarı ömrü dolduğunda strateji
bozulmasa bile tahsisi yarıya iner ve yerini yeniden hak etmek için taze OOS veriyle
doğrulamadan geçmek zorundadır. *Bozulmayı beklemek, alarmı yangından sonra çalmaktır.*

**2. `AllocationLearner` — tahsis öğrenicisi**
Haftalık: her stratejinin son 30 günlük gerçekleşen performansını, doğrulama raporundaki
beklentiyle karşılaştırır. Beklentiyi tutturanların tahsisi artar, sapanların azalır.
Tahsis değişimi tek seferde ≤ %20 (ani rotasyon yasak).

**3. `HypothesisGenerator` — yapılandırılmış hipotez (opsiyonel, araştırma rayı)**
Rastgele kombinasyon yerine, piyasa yapısından gelen hipotezler:
*"Yüksek funding + azalan OI = zorlanmış long konumlanması"* gibi. Kaynak: literatür,
gözlem, operatör girdisi. Her hipotez deney kütüğüne düşer ve aynı kapıdan geçer.

### 27.3 Rejim artık bir filtre değil, bir tahsis girdisi

v1'de rejim etiketi havuzu filtreliyordu (opt-in, varsayılan kapalı). v2'de:
- Her stratejinin **rejim bazında** geçmiş performansı tutulur.
- Aktif rejim tespit edildiğinde tahsis, o rejimde iyi performans gösterenlere kayar.
- Rejim geçişleri yumuşatılır (ani rejim değişiminde tahsis kademeli kayar).
- Rejim etiketi olmayan strateji nötr muamele görür (asla açlığa düşmez — v1 davranışı korunur).

### 27.4 Kabul kriterleri

- [ ] Yarı ömrü dolan strateji, bozulma tetiklenmeden tahsis kaybeder (testle).
- [ ] **Erken uyarı testi:** Performansı yavaşça bozulan bir strateji, §8.5 bozulma
      tetikleyicisi ateşlenmeden **önce** tahsis kaybetmeye başlar.
- [ ] Tahsis değişimi tek adımda %20'yi aşamaz.
- [ ] Rejim değişimi tahsisi kaydırır; etiketsiz strateji etkilenmez.
- [ ] Tüm yeni üreticiler aynı Doğrulayıcı → Terfi kapısı zincirinden geçer (v1 §8.3 mimarisi korundu).

---

## 28. Operatör Yüzeyi — Ne görürsün, ne değiştirirsin

> Kural 19'un uygulaması. Bu bölüm **canlı bir sözlüktür**: yeni bir ayar eklendiğinde
> aynı commit'te buraya üç satır yazılır.

### 28.1 Her gün göreceklerin

| Görünüm | Ne söyler |
|---|---|
| **Günlük brifing** | Tek paragraf, düz cümlelerle: dün ne oldu, ne değişti, senden ne bekleniyor. Örnek: *"Dün 4 işlem, net −%0,3. TrendPullback-v3 tahsisini %18'den %14'e düşürdüm çünkü son 30 işlemde beklentinin altında. Onayını bekleyen 1 yeni versiyon var."* |
| **Portföy sağlığı** | Tahsis dağılımı · korelasyon ısı haritası · net maruziyet · yoğunlaşma uyarıları |
| **Strateji kartı** | Yaş · kalan yarı ömür · DSR · PBO · kayan PF · tahsis payı · kapasite tahmini · rejim etiketi |
| **Karar akışı** | Her sinyal ve her **red**, tek cümlelik gerekçeyle. Örnek: *"BTCUSDT long reddedildi: net sembol maruziyeti %35 tavanında."* |
| **Deney günlüğü** | Bugün kaç hipotez denendi, kaçı kapıyı geçti, toplam deneme sayacı nerede |
| **Canlı vs paper** | Tracking error · kümülatif fark · korelasyon; eşik aşılırsa otomatik Paper'a düşüş bildirimi |

### 28.2 Değiştirebileceklerin

Dört kuşağa ayrılmıştır. **Birinci kuşağa dokunmak için sebep gerekir.**

#### Kuşak 1 — Güvenlik (dokunma)

| Ayar | Ne yapar | Yükseltirsen | Düşürürsen |
|---|---|---|---|
| `max_total_drawdown_pct` (%15) | Kill switch eşiği | Daha derin batışa izin verirsin | Daha erken durursun; gürültüde de durabilirsin |
| `portfolio_max_dd_pct` (%12) | Portföy kill eşiği | Aynı, portföy düzeyinde | Aynı, daha temkinli |
| `portfolio_daily_loss_pct` (%3) | Portföy günlük zarar durdurucu | Portföy günde daha çok kaybedebilir, geç durur | Erken durur; oynak günde de girişleri keser |
| `portfolio_direction_concentration_pct` (%60) | Net yön (long/short) tavanı | Portföy tek yöne daha çok yaslanabilir | Daha dengeli yön, daha az tek-yön bahsi |
| `liquidation_buffer_atr` (3) | Likidasyon tamponu | Daha güvenli, daha küçük pozisyon | **Likidasyon riski** — 3'ün altına inme |
| `leverage_hard_cap` (10x) | Sert kaldıraç tavanı | Likidasyon mesafesi kısalır | Daha güvenli, getiri düşer |
| `gross_leverage_cap` (3x) | Portföy brüt kaldıracı | Toplam maruziyet artar | Daha az iş, daha az risk |

#### Kuşak 2 — Sermaye ve boyutlandırma

| Ayar | Ne yapar | Yükseltirsen | Düşürürsen |
|---|---|---|---|
| `per_trade_pct` (%1) | İşlem başına risk | Daha büyük kazanç ve kayıp; DD limitine daha hızlı varırsın | Daha yavaş her şey; hayatta kalma süresi uzar |
| `allocation_method` (eşit risk) | Sermaye dağıtımı | Kelly'ye geçmek getiriyi ve varyansı büyütür | Eşit risk en tahmin edilebilir olandır |
| `max_strategy_allocation` (%25) | Tek stratejiye tavan | Yoğunlaşma artar | Daha çok çeşitlendirme gerekir |
| `max_symbol_exposure` (%35) | Tek sembole net tavan | BTC'ye daha çok yaslanırsın | Daha dağınık, daha sakin |

#### Kuşak 3 — Keşif ve kalite

| Ayar | Ne yapar | Yükseltirsen | Düşürürsen |
|---|---|---|---|
| `dsr_threshold` (0.95) | Deflasyon kapısı | Neredeyse hiçbir strateji geçemez | **Gürültü içeri sızar.** 0.90'ın altına inme |
| `pbo_threshold` (0.40) | Aşırı uydurma tavanı | Daha çok aday, daha çok yalancı | Daha az aday, daha güvenilir |
| `min_oos_trades` (30) | Minimum OOS işlem | Daha güvenilir istatistik, daha az aday | 4 işlemlik %80 getiri veri değil anekdottur |
| `optuna_trials` (100) | Parametre arama bütçesi | Daha iyi parametre **ve** daha yüksek deneme sayacı → düşük DSR | Daha kaba arama, daha dürüst skor |
| `correlation_gate` (0.70) | Yeni strateji korelasyon kapısı | Benzer stratejiler birikir | Havuz daralır, çeşitlendirme artar |

#### Kuşak 4 — Ritim

| Ayar | Ne yapar | Yükseltirsen | Düşürürsen |
|---|---|---|---|
| `strategy_half_life_days` (90) | Zorunlu emeklilik süresi | Stratejiler daha uzun yaşar; bayat edge riski | Daha sık yenilenme; daha çok hesap |
| `reopt_schedule` (haftalık) | Yeniden optimizasyon sıklığı | Daha az müdahale | Daha sık müdahale → deneme sayacı şişer |
| `allocation_max_step` (%20) | Tahsis değişim hızı | Daha çevik, daha oynak | Daha yavaş tepki, daha istikrarlı |
| `auto_approve` (kapalı) | İnsan onayı | **Açmak = sistemi tamamen serbest bırakmak.** Faz 13 üç ay sorunsuz koşmadan açma | Her değişiklik senin onayından geçer |

#### Kuşak 5 — Veri toplama (Faz 8)

| Ayar | Ne yapar | Yükseltirsen | Düşürürsen |
|---|---|---|---|
| `liquidation_collector_enabled` (kapalı) | `!forceOrder@arr` likidasyon WS toplayıcısını worker'da başlatır | Açarsan bugünden itibaren likidasyon verisi birikir (**geriye dönük indirilemez**, erken aç) | Kapalıysa hiç toplanmaz; sonradan o boşluk asla doldurulamaz |
| `liquidation_batch_rows` (500) | Kaç olay biriktikten sonra toplu yazılır | Daha büyük parti, daha az DB yazımı, kopmada daha çok risk | Daha sık yazım, daha az bellek, daha çok DB trafiği |
| `liquidation_batch_seconds` (5) | En geç kaç saniyede bir toplu yazılır | Yazımlar seyrekleşir; düşük hacimde tampon uzun bekler | Daha taze veri, daha sık küçük yazım |

### 28.3 Karar anlatıcısı

`reason` alanı bugün JSON. UI ve Telegram için düz cümleye çevrilir:

```
{"signal":"line_cross","a":"ema:9","b":"ema:21","dir":"up"}
→ "EMA9, EMA21'i yukarı kesti."

{"blocked":"symbol_exposure","current":0.35,"cap":0.35}
→ "Reddedildi: BTCUSDT maruziyetin zaten tavanda (%35)."

{"allocation_change":-0.04,"cause":"underperformance"}
→ "Tahsisi %4 düşürdüm: son 30 işlem doğrulama beklentisinin altında."
```

Faz 10 portföy kapısının ürettiği `risk_events` tipleri (doc §24.5) da düz cümleye çevrilir:

```
{"type":"gross_leverage","gross_leverage":3.05,"cap":3.0}
→ "Reddedildi: portföy brüt kaldıracı 3x tavanını aşacaktı (3.05x)."

{"type":"portfolio_drawdown","drawdown_pct":-12.4,"limit_pct":12.0}
→ "Kill switch: portföy %12 düşüş tavanını geçti (−%12.4)."

{"type":"direction_concentration","net_directional_pct":68,"cap_pct":60,"side":"long"}
→ "Yeni long kısıtlandı: portföyün %68'i zaten net long (tavan %60)."

{"type":"correlation_gate","rho":0.85,"factor":0.5}
→ "Tahsisi yarıya indirdim: mevcut bir stratejiyle %85 korele."
```

Her yeni `reason` tipi, çevirmen fonksiyonuyla **aynı commit'te** doğar (kural 19).

---

## 29. Yol Haritası v2 — özet

| Faz | Ad | Süre | Bloklayıcı mı |
|---|---|---|---|
| **8** | Gerçeklik teması | 1 hafta | **Evet** — diğer her şey buna bağlı |
| **9** | İstatistiksel dürüstlük | 1,5 hafta | **Evet** |
| **10** | Portföy katmanı | 2 hafta | **Evet** |
| **11** | Alfa yüzeyi | 2 hafta | Hayır (ama likidasyon toplayıcısı Faz 8'de başlar) |
| **12** | Yürütme + kapasite | 1,5 hafta | Hayır |
| **13** | Kendini geliştirme v2 | 2 hafta | Hayır |

**Toplam ≈ 10 hafta**, yarı zamanlı tempoda. Faz 8–10 çekirdektir ve sırayla yapılır;
11–13 sonra ve istenen sırayla.

**Sıra pazarlıksızdır.** Faz 9'suz Faz 10 anlamsızdır (gürültüden portföy kurmuş olursun);
Faz 8'siz Faz 9 anlamsızdır (neyi düzelttiğini bilmezsin).

---

## 30. Beklenti yönetimi — bu iş bittiğinde ne olacak

Dürüstlük burada en çok işe yarar.

**Olacaklar:**
- Sistem kendi başına çalışır: veri çeker, strateji arar, doğrular, boyutlandırır, işler,
  bozulanı emekli eder, sana günde bir paragraf yazar.
- Ürettiği her sayının arkasında denenen hipotez sayısı vardır. Kendi kendini kandırmaz.
- Kaybettiğinde **neden** kaybettiğini söyleyebilir.

**Olmayacaklar:**
- Sürekli kazanan bir strateji bulmayacak. Böyle bir şey yok.
- Bulduğu stratejilerin çoğu OOS'ta ölecek. Bu bir hata değil, filtrenin çalıştığının kanıtıdır.
- Deflasyon kapısı devreye girdiğinde **liderlik tablon boşalacak.** İlk tepkin kapıyı
  gevşetmek olacak. Gevşetme.
- Kâr garantisi vermeyecek; hiçbir sistem vermez.

**Gerçekçi başarı tanımı:** 6 ay sonunda, canlı sermayeyle çalışan 3–5 düşük korelasyonlu
strateji; portföy drawdown'ı %12'nin altında; her ay en az bir strateji emekli olup yerine
yenisi geliyor; ve sen sisteme her gün bakmak zorunda değilsin.

Bu, "kusursuz strateji"den daha az heyecan verici ve gerçekte var olan tek versiyondur.

---

## 31. Yasal ve Risk Notu

v1.1 §19 aynen geçerlidir ve bu ciltle güçlendirilir:

Bu yazılım kişisel araştırma ve eğitim amaçlıdır; **yatırım tavsiyesi değildir ve vermez.**
Deflated Sharpe, PBO ve walk-forward doğrulaması aşırı uydurma olasılığını *ölçer ve azaltır*;
**ortadan kaldırmaz.** Kapıdan geçmiş bir strateji, kârlı bir strateji değil, gürültü olma
olasılığı ölçülmüş bir stratejidir. Portföy katmanı riski *dağıtır*, yok etmez — korelasyonlar
kriz anlarında 1'e yaklaşır ve çeşitlendirme tam ihtiyaç duyulduğunda zayıflar.

Kaldıraçlı perpetual futures işlemleri kayıpları kaldıraç oranında büyütür; likidasyon,
ilgili pozisyon teminatının tamamen kaybı demektir. Gerçek sermayeyle işlem tamamen
kullanıcının kararı ve riskidir.

---

*UNKNOWNINCOME Proje Dokümanı v2.0 — sonu. v1.1 ile birlikte okunur.*
