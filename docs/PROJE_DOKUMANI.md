# UNKNOWNINCOME — Otonom Backtest & Trading Sistemi
## Proje Dokümanı v1.1

| | |
|---|---|
| **Proje sahibi** | Eray Pişkin / SixNodes |
| **Durum** | Geliştirme öncesi kapsam dokümanı |
| **Çalışma adı** | UNKNOWNINCOME (yer tutucu — istenirse değiştirilir) |
| **Tarih** | Temmuz 2026 |
| **Bağlı dosya** | `CLAUDE.md` (repo köküne konacak Claude Code hafıza dosyası) |

> **Açık kararlar hakkında:** Bu dokümanda iki büyük karar bilinçli olarak açık bırakılmıştır — *ilk canlı piyasa cephesi* (§9.2) ve *kendini geliştirme mekanizması* (§8.3). Her ikisi için karar matrisi, öneri ve geliştirmeyi bloklamayan bir varsayılan tanımlanmıştır. Tüm açık kararların özeti §16'dadır. Karar verildiğinde ilgili bölümdeki tek satır güncellenir; mimari değişmez.

> **v1.1 değişiklik özeti:** Yön long+short'a genişledi → Binance **USDT-M perpetual futures** (funding maliyeti backtest'e, likidasyon tamponu risk katmanına eklendi; kaldıraç sert tavan 10x / güvenli varsayılan 5x). Strateji mantığı **üç katmandan** düzenlenebilir (UI · JSON/YAML · Python plugin, hot-reload). **Live/Paper/Off** mod şalteri: global + strateji bazlı, sinyal onayı yok. Sembol evreni **dinamik likidite filtresi + tarihli snapshot**. UI: **İngilizce**, hibrit karakter, **responsive + Telegram kumanda**. Sistem **kesin olarak tek kullanıcılı**.

---

## 0. Özet

UNKNOWNINCOME, iki yüzü olan tek bir sistemdir:

1. **Backtest Lab (Sayfa 1):** Minimum 6 ay (önerilen 12–24 ay) geçmiş fiyat verisi üzerinde, 200+ teknik indikatörü hem tek tek hem kombinasyon halinde tarayan; "son dönemde hangi indikatörler birlikte en iyi sonucu verdi" sorusunu ölçülebilir metriklerle cevaplayan; hem tam otomatik keşif hem manuel indikatör seçimi sunan bir laboratuvar.
2. **Trade Deck (Sayfa 2):** Backtest Lab'in doğruladığı stratejileri önce **paper trading** modunda, sonra kontrollü bir terfi kapısından geçerek gerçek parayla işleten; her kararını (neden girdi, hangi sinyal, hangi strateji versiyonu) şeffaf şekilde gösteren; kendini periyodik olarak yeniden optimize eden bir bot kokpiti.

Çekirdek motor **varlık sınıfından bağımsızdır**: OHLCV (açılış-yüksek-düşük-kapanış-hacim) verisi üretebilen her enstrüman — kripto, hisse, endeks, fon — aynı motordan geçer. Piyasaya özel olan yalnızca iki ince katmandır: veri adaptörü ve emir adaptörü. Sistem **long ve short** yönde çalışır; kripto tarafında bunun doğal aracı USDT-M perpetual futures'tır.

---

## 1. Vizyon ve Kapsam

### 1.1 Amaç
Teknik analiz tabanlı stratejilerin keşfini, doğrulanmasını ve yürütülmesini tek bir kapalı döngüde birleştirmek: **veri → indikatör → backtest → keşif → doğrulama → paper → canlı → geri besleme.**

### 1.2 Kapsam içi (v1)
- Çoklu zaman dilimi taraması: varsayılan 15m / 1h / 4h / 1d; **derin tarama modu** ile 1m / 5m (isteğe bağlı, hesap yükü uyarılı).
- 200+ indikatörlü registry + custom indikatör eklenti mimarisi.
- Otomatik keşif pipeline'ı (tekli tarama → korelasyon eleme → kombinasyon → parametre optimizasyonu → walk-forward doğrulama → liderlik tablosu).
- Manuel backtest modu (indikatör + parametre + kural seçimi elde).
- Strateji genome'u, sürümleme ve şeffaf karar günlüğü.
- Paper trading motoru + risk katmanı + kill switch.
- Canlı yürütme (terfi kapısının arkasında, Faz 7).
- **Long + short** işlem — Binance USDT-M perpetual futures; kaldıraç sert tavanı 10x, güvenli varsayılan 5x (§9.4).
- **Üç katmanlı strateji düzenleme:** UI kural kurucu · JSON/YAML · Python plugin — restart gerektirmez (§8.6).
- Global + strateji bazlı **Live / Paper / Off** mod şalteri (§9.6).
- **Dinamik sembol evreni:** likidite filtresi + tarihli evren snapshot'ları (§4.5).
- **Telegram uzaktan kumanda** (§10.3).

### 1.3 Kapsam dışı (v1)
- Opsiyon stratejileri (v2 adayı). *(v1.1: perpetual futures ve sınırlı kaldıraç kapsama alındı — §9.4.)*
- Haber/duygu analizi, on-chain veri, order book mikroyapısı (v2+ adayı).
- Yüksek frekanslı işlem (saniye altı) — mimari buna göre tasarlanmamıştır.
- Çok kullanıcılı SaaS katmanı — **kesin karar (v1.1): sistem tamamen kişiseldir.** Çok kullanıcı hazırlığı yapılmaz; auth ve şema buna göre sade tutulur.

### 1.4 Başarı kriterleri (sistem düzeyinde — kâr vaadi değil)
- Standart tarama (10 sembol × 4 TF × tüm indikatörler, tekli aşama) < 2 saat.
- Aynı config + seed ile her backtest **bit-for-bit tekrarlanabilir**.
- Paper bot 7 gün kesintisiz koşar; her sinyal gerekçesiyle loglanır.
- Canlı emir yolu, terfi kapısı geçilmeden **teknik olarak çalıştırılamaz** (testle kanıtlı).

---

## 2. Pazarlıksız İlkeler

Bu ilkeler dokümanın geri kalanının üzerinde durduğu zemindir. Claude Code promptuna da aynen girer (§17).

1. **Lookahead bias yasak.** Sinyal bar kapanışında üretilir; emir bir sonraki bar açılışında (veya kapanış + slippage) simüle edilir. Geleceği görmüş bir backtest, yalan söyleyen bir backtesttir.
2. **Maliyetler her zaman açık.** Komisyon + slippage + funding (perpetual) varsayılan olarak modellenir; kapatmak bilinçli bir UI eylemi ve raporda kırmızı etikettir.
3. **Walk-forward + out-of-sample zorunlu.** Hiçbir strateji, sadece geçmişe mükemmel uyduğu için terfi edemez. Geçmişe kusursuz oturan strateji genellikle geleceğin ilk ayında ölür — sistemin tasarımı bu gerçeği kabul eder.
4. **Tam şeffaflık.** Her sinyal: strateji versiyonu + tetikleyen kurallar + o andaki indikatör değerleri anlık görüntüsüyle kayıt altına alınır.
5. **Önce paper, sonra canlı.** Terfi kapısı (§9.5) sayısal ve yapılandırılabilirdir; his ile geçilmez.
6. **Kill switch her katmanda.** UI butonu, API endpoint'i, dosya bayrağı, Telegram `/kill` komutu.
7. **UTC her yerde.** Saklama ve hesap UTC; UI gösterimi Europe/Istanbul.
8. **Tekrarlanabilirlik.** Her koşu: config hash + rastgelelik seed'i + kod versiyonu ile etiketlenir.
9. **Çekirdek asset-agnostic.** Piyasa özel kod yalnızca `data/` ve `execution/` adaptörlerinde yaşar.
10. **Yazılım eğitim ve kişisel kullanım içindir; yatırım tavsiyesi değildir.** (§19)

---

## 3. Sistem Mimarisi

### 3.1 Servis diyagramı

```
┌──────────────┐  REST + WS  ┌───────────────┐   iş kuyruğu   ┌────────────────┐
│  Next.js UI  │◄───────────►│  FastAPI API   │◄──────────────►│  arq Worker(s)  │
│ /backtest    │             │ auth · CRUD ·  │     Redis      │ veri sync ·     │
│ /trade       │             │ ws yayını      │                │ tarama · WFO ·  │
└──────────────┘             └──────┬────────┘                │ bot döngüsü     │
                                    │                          └───────┬────────┘
                             ┌──────▼───────┐                 ┌────────▼────────┐
                             │  PostgreSQL   │                 │ Parquet + DuckDB│
                             │ (uygulama     │                 │ (mum verisi +   │
                             │  durumu)      │                 │  indikatör cache│
                             └──────────────┘                 └────────┬────────┘
                                                                       │
                                                    ┌──────────────────▼──────────────────┐
                                                    │        Piyasa Adaptörleri            │
                                                    │  ccxt/Binance · Alpaca/IBKR · BIST   │
                                                    │  (veri adaptörü + emir adaptörü)     │
                                                    └─────────────────────────────────────┘
```

### 3.2 Teknoloji kararları (kesinleşmiş)

| Katman | Seçim | Gerekçe |
|---|---|---|
| Backend | Python 3.11+ / FastAPI | Backtest ekosisteminin ana dili; async API |
| İş kuyruğu | arq + Redis | Hafif, async-native (alternatif: Celery) |
| Uygulama DB | PostgreSQL | Strateji/işlem/log durumu |
| Piyasa verisi | Parquet dosyaları + DuckDB sorgu katmanı | §4.3'te matris |
| Backtest motoru | vectorbt (kütle tarama) + backtesting.py (finalist doğrulama) | §6.1'de matris |
| İndikatörler | TA-Lib + pandas-ta birleşimi, tek registry arkasında | §5 |
| Optimizasyon | Optuna (Bayesian/TPE) | Grid'den akıllı arama |
| Frontend | Next.js 15 + TypeScript + Tailwind | Mevcut yetkinlik ve hız |
| Grafikler | TradingView `lightweight-charts` (açık kaynak) | Mum + equity için endüstri standardı görünüm |
| Canlı veri | ccxt (REST + WebSocket) | Tek kütüphane, 100+ borsa — gelecek adaptörler bedava |
| İlk piyasa | Binance USDT-M perpetual futures | Long+short gerekliliğinin doğal adresi |
| UI dili | İngilizce | Kod + arayüz tek dil |
| Deployment | Docker Compose → Coolify / VDS | Mevcut altyapı düzeni |

### 3.3 Depo yapısı

```
UNKNOWNINCOME/
├── docker-compose.yml
├── CLAUDE.md                      # Claude Code hafıza dosyası (ayrı verildi)
├── docs/
│   └── PROJE_DOKUMANI.md          # bu doküman
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI girişi
│   │   ├── api/                   # REST + WS endpoint'leri
│   │   ├── core/                  # config, güvenlik, logging, kill switch
│   │   ├── data/                  # veri adaptörleri + parquet store + sync
│   │   ├── indicators/            # registry + hesap + custom/ eklentiler
│   │   ├── backtest/              # motor sarmalayıcıları, metrikler, maliyet modeli
│   │   ├── discovery/             # otomatik keşif pipeline (Aşama 0–6)
│   │   ├── strategy/              # genome, sürümleme, kendini geliştirme
│   │   ├── execution/             # paper sim + canlı adaptörler + risk katmanı
│   │   ├── models/                # SQLAlchemy modelleri
│   │   └── workers/               # arq görevleri
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── app/
│   │   ├── backtest/              # Sayfa 1 — Backtest Lab
│   │   └── trade/                 # Sayfa 2 — Trade Deck
│   ├── components/
│   └── lib/
└── infra/                         # Coolify notları, cron tanımları
```

---

## 4. Veri Katmanı

### 4.1 Kaynaklar (piyasaya göre)

| Piyasa | Geçmiş veri | Canlı veri | Not |
|---|---|---|---|
| Kripto | ccxt → Binance USDT-M REST — tam OHLCV **+ funding rate geçmişi** (ücretsiz) | Binance Futures WebSocket | En zahmetsiz kaynak; 7/24; long+short doğal |
| ABD hisse | Alpaca (IEX ücretsiz / SIP ücretli), yfinance (günlük, yedek) | Alpaca WS | Seans saatleri; split/temettü düzeltmesi gerekir |
| BIST | Ücretli sağlayıcılar (Matriks, Finnet vb.); ücretsiz kaynak zayıf | Aracı kurum API'si üzerinden | §9.2'deki matrise bakınız |

### 4.2 Veri hacmi gerçeği

Sembol başına mum sayısı (kripto, 7/24):

| TF | 6 ay | 24 ay |
|---|---|---|
| 1m | ~259.000 | ~1.040.000 |
| 5m | ~51.800 | ~207.000 |
| 15m | ~17.300 | ~69.000 |
| 1h | ~4.320 | ~17.300 |
| 4h | ~1.080 | ~4.320 |
| 1d | ~180 | ~730 |

**Dürüst not:** 6 ay talep edilen minimumdur ve motor bunu destekler; ancak walk-forward doğrulama için dar bir penceredir (yalnızca ~3 katman çıkar). Lookback parametriktir; kripto tarafında 12–24 ay veri Binance'ten ücretsiz çekilebildiği için **öneri 24 aydır.** 1m/5m "derin tarama" modu, RAM ve süre uyarısıyla açılır.

### 4.3 Depolama kararı

| Kriter | **Parquet + DuckDB (öneri)** | TimescaleDB (alternatif) |
|---|---|---|
| Kurulum | Ek servis yok; dosya tabanlı | Ekstra DB servisi + yönetim |
| Vektörel okuma (backtest) | Çok yüksek — doğrudan pandas'a | Yüksek |
| Eşzamanlı yazma | Tek yazar için yeterli | Güçlü |
| Yedekleme | Dosya kopyala | pg_dump |
| Ne zaman diğeri? | — | Çok kullanıcılı / yoğun gerçek zamanlı yazma senaryosunda |

Dosya düzeni: `/data/parquet/{market}/{symbol}/{tf}.parquet` + PostgreSQL'de `candle_sync_state` meta tablosu (ilk/son mum, boşluk kaydı).

### 4.4 Bütünlük kuralları
- Her sync sonrası **gap taraması**: eksik mum aralıkları tespit edilir, yeniden çekilir, kapanmayanlar `gaps` alanına işlenir ve UI'da görünür.
- Hisse verisinde split/temettü düzeltmesi adaptör sorumluluğundadır (çekirdek düzeltilmiş veri varsayar).
- Tüm timestamp'ler UTC, mum açılış zamanıyla indekslenir.

### 4.5 Dinamik sembol evreni (v1.1)
Evren elle liste değil, **likidite filtresiyle** kurulur: Binance USDT-M perpetual'ları 30 günlük medyan hacim + spread filtresinden geçer; stablecoin pariteleri ve kaldıraçlı tokenlar elenir; ilk N sembol (varsayılan 30, config) evrene girer; haftalık yenilenir.

**Survivorship bias önlemi (pazarlıksız):** Her yenilemede evren **tarihli snapshot** olarak saklanır (`universe_snapshots`). Backtest, test ettiği tarihte geçerli olan evreni kullanır — bugünün kazananlar listesiyle geçmişi taramak, tarihi hayatta kalanlara yazdırmaktır ve sonuçları sistematik biçimde şişirir.

---

## 5. İndikatör Kütüphanesi

### 5.1 "Dünyadaki tüm indikatörler" — gerçekçi çeviri

Pratik evren: **TA-Lib** (~150 fonksiyon; ~60'ı mum formasyonu) + **pandas-ta** (~130 gösterge). Örtüşme düşüldükten sonra **200+ benzersiz sinyal kaynağı** elde edilir. Bunun ötesindeki "indikatörler" büyük oranda aynı matematiğin türevleridir. Mimari kapıyı açık tutar: `indicators/custom/` klasörüne atılan tek dosyalık Python eklentisi otomatik olarak registry'ye katılır — sonsuzluk yanılsaması yerine genişletilebilir gerçeklik.

### 5.2 Kategoriler (registry alanı)

| Kategori | Örnekler |
|---|---|
| Trend | SMA, EMA, WMA, HMA, KAMA, MACD, ADX/DMI, SuperTrend, Ichimoku, Parabolic SAR, Aroon, Vortex |
| Momentum | RSI, Stochastic, StochRSI, CCI, MFI, ROC, TSI, Williams %R, Ultimate Osc., Fisher Transform |
| Volatilite | Bollinger, ATR, Keltner, Donchian, Chaikin Vol., Mass Index, NATR |
| Hacim | OBV, VWAP, CMF, A/D, Force Index, EOM, KVO, Volume Profile (basitleştirilmiş) |
| Döngü | Hilbert Transform ailesi (HT_SINE, HT_TRENDMODE vb.) |
| Formasyon | TA-Lib'in ~60 mum formasyonu (Engulfing, Doji, Hammer, Morning Star…) |
| İstatistik | Linear Regression, StdDev, Z-Score, Correlation, Beta |

### 5.3 Registry şeması

Her indikatör tek bir metadata kaydıyla tanımlanır — otomatik tarama bu şemayı okuyarak parametre uzayını kurar:

```json
{
  "id": "rsi",
  "name": "Relative Strength Index",
  "category": "momentum",
  "source": "talib",
  "params": { "length": { "default": 14, "min": 5, "max": 50, "step": 1 } },
  "outputs": ["rsi"],
  "signal_templates": ["threshold_cross", "midline_cross", "divergence"]
}
```

### 5.4 Sinyal primitifleri (kombinasyonun dili)

İndikatörler ham seridir; strateji kurallara ihtiyaç duyar. Her indikatör çıktısı şu primitiflere sarılır, böylece herhangi ikisi-üçü gramer hatasız birleştirilebilir:

- `threshold_cross(x, level, dir)` — eşik kesişimi (ör. RSI < 30 → 30'u yukarı kesme)
- `line_cross(a, b, dir)` — iki çizgi kesişimi (ör. EMA9 × EMA21)
- `slope(x, lookback, dir)` — eğim/yön filtresi
- `band_touch(price, upper, lower, mode)` — bant teması/dönüşü (Bollinger, Keltner)
- `regime(x, rule)` — rejim filtresi (ör. ADX > 25 → trend var)
- `pattern(name)` — mum formasyonu boole sinyali

### 5.5 İndikatör cache
Hesaplanan her seri `(symbol, tf, indicator_id, params_hash)` anahtarıyla Parquet'e yazılır. Keşif taramasında aynı hesabın tekrarı sıfıra iner — taramanın 2 saatin altında kalmasının ana sırrı budur.

---

## 6. Backtest Motoru

### 6.1 Motor kararı — çift motor yaklaşımı

| Motor | Tip | Hız | Not | Roldeki yeri |
|---|---|---|---|---|
| **vectorbt (OSS)** | Vektörel | Çok yüksek | Binlerce kombinasyonu dakikalar içinde tarar; RAM'e dikkat | **Ana tarama motoru** |
| **backtesting.py** | Event-driven | Orta | Basit, okunabilir, gerçekçi emir akışı | **Finalist doğrulama** — liderlik tablosundaki adaylar burada ikinci kez koşar; iki motor uyuşmazsa alarm |
| backtrader | Event-driven | Düşük | Olgun ama yaşlanmış API | Alternatif |
| NautilusTrader | Event-driven, kurumsal | Yüksek | Dik öğrenme eğrisi; canlıya en yakın simülasyon | Faz 7+ için alternatif yürütme çekirdeği |
| freqtrade | Hazır framework | — | Kripto-only; hazır hyperopt + UI | **"Satın al vs inşa et" referansı:** yalnızca kripto + hazır çözüm yetseydi seçim buydu; çoklu piyasa + özel UI + keşif pipeline'ı gereksinimi özel inşayı gerektiriyor |

### 6.2 Maliyet modeli (varsayılan AÇIK)

| Piyasa | Komisyon varsayılanı | Slippage varsayılanı |
|---|---|---|
| Binance USDT-M futures | ≈%0,04 taker (config) | 5 bps sabit **veya** 0,05 × ATR (seçilebilir) |
| Alpaca | 0 komisyon | 3 bps |
| BIST | Aracı kuruma göre (config) | 10 bps |

Slippage modeli işlem başına raporda ayrı satırda gösterilir; "maliyetsiz" koşular kırmızı etiketle işaretlenir.

**Funding maliyeti (v1.1):** Perpetual pozisyonlara 8 saatlik **tarihsel funding oranları** uygulanır ve raporda ayrı kalem olarak gösterilir; funding'i görmezden gelen bir futures backtest'i, kirayı unutmuş bir kârlılık hesabıdır.

### 6.3 Metrik seti (her koşuda hesaplanır)

Net getiri, CAGR, Sharpe, Sortino, Calmar, Maksimum Drawdown (derinlik + süre), Kazanma oranı, Profit Factor, Expectancy (işlem başına beklenen getiri), ortalama kazanç/kayıp oranı, işlem sayısı, piyasada kalma oranı (exposure), SQN, aylık getiri ısı haritası.

### 6.4 Bileşik skor (sıralama için, ağırlıklar config'te)

```
Skor = 0.30·norm(Sharpe) + 0.25·norm(ProfitFactor) + 0.20·(1 − norm(MaxDD))
     + 0.15·norm(WinRate) + 0.10·norm(Expectancy)

Sert filtreler (skor öncesi eleme): işlem sayısı ≥ 30 · MaxDD ≤ %25 · PF ≥ 1.0
```

### 6.5 Overfitting savunma hattı (zorunlu)

1. **IS/OOS ayrımı:** Veri %70 in-sample / %30 out-of-sample; nihai skor OOS'tan gelir.
2. **Walk-forward (WFO):** Kayan pencere — varsayılan eğitim 90 gün / test 30 gün / adım 30 gün. 24 aylık veride ~21 katman; 6 ayda yalnızca ~3 (bkz. §4.2 notu).
3. **Parametre platosu testi:** En iyi parametrenin komşuları da kârlı olmalı; tek iğne deliği zirveler (ör. RSI=13 harika, 12 ve 14 felaket) reddedilir.
4. **Monte Carlo:** İşlem sırası karıştırılarak drawdown dağılımı çıkarılır; %95 kötü senaryo raporlanır.
5. **Çoklu test farkındalığı:** Binlerce kombinasyon denendiğinde şans eseri "harika" sonuçlar kaçınılmazdır; liderlik tablosu denenen toplam kombinasyon sayısını görünür tutar (ileri seviye: deflated Sharpe, v2).

---

## 7. Otomatik Keşif Pipeline'ı

Kullanıcının "hangi indikatörler beraber çalışınca son dönemde en iyi sonucu veriyor" sorusunun motorudur. 200 indikatörün üçlü kombinasyonu ~1,3 milyon ihtimaldir; kaba kuvvet yerine aşamalı eleme kullanılır:

**Aşama 0 — Evren & TF seçimi.** Sembol listesi (manuel veya likidite filtresiyle otomatik) + zaman dilimleri. Varsayılan tarama: 15m, 1h, 4h, 1d. Derin tarama: +1m, +5m (uyarılı).

**Aşama 1 — Tekli tarama.** Her indikatör, her sinyal şablonuyla, varsayılan parametrelerle tek başına koşar. Çıktı: indikatör başına TF/sembol bazında bileşik skor tablosu.

**Aşama 2 — Korelasyon eleme.** Aynı bilgiyi taşıyan indikatörler (sinyal serileri arası |ρ| > 0,85) kümelenir; her kümeden en iyi skorlu temsilci kalır. (RSI + StochRSI + Williams %R üçlüsü tek koltuğa iner.)

**Aşama 3 — Rol tabanlı kombinasyon.** Kombinasyonlar rastgele değil, rollere göre kurulur: **tetikleyici** (giriş sinyali, genelde momentum/kesişim) + **filtre** (rejim/trend onayı) + **çıkış/risk** (volatilite tabanlı stop/hedef). Kategori kısıtı: aynı kategoriden en fazla 1 indikatör. Bu, arama uzayını milyonlardan binlere indirir ve anlamsız eşleşmeleri (üç trend indikatörünün korosu) baştan engeller.

**Aşama 4 — Parametre optimizasyonu.** Aşama 3'ün ilk N adayı (varsayılan 50) Optuna ile parametre uzayında aranır (TPE, deneme bütçesi config'te).

**Aşama 5 — WFO doğrulama.** Adaylar §6.5'teki tam savunma hattından geçer. Yalnızca WFO'dan sağ çıkanlar "candidate" statüsü alır.

**Aşama 6 — Liderlik tablosu & rapor.** Sıralı sonuçlar; her satırda: kombinasyon, TF, semboller, tüm metrikler, WFO katman grafiği, denenen toplam kombinasyon sayısı. Tek tıkla "Stratejiye dönüştür".

**Manuel mod** aynı boru hattının kısa devresi: kullanıcı indikatörleri, parametreleri ve kuralları elle seçer → doğrudan backtest → aynı rapor formatı. Manuel sonuçlar da istenirse WFO'ya gönderilebilir.

---

## 8. Strateji Motoru ve Kendini Geliştirme

### 8.1 Strateji genome'u

Her strateji, insan-okur ve makine-üretir tek bir JSON'dur:

```json
{
  "name": "TrendPullback-v3",
  "universe": ["BTC/USDT", "ETH/USDT"],
  "timeframe": "4h",
  "entry":  { "all": [
      { "signal": "line_cross", "a": "ema:9", "b": "ema:21", "dir": "up" },
      { "signal": "regime", "x": "adx:14", "rule": "gt:25" } ] },
  "exit":   { "any": [
      { "signal": "line_cross", "a": "ema:9", "b": "ema:21", "dir": "down" },
      { "type": "atr_stop", "mult": 2.0 },
      { "type": "atr_target", "mult": 3.0 } ] },
  "risk":   { "per_trade_pct": 1.0, "sizing": "atr", "direction": "both", "leverage": 5 }
}
```

Genome'lar **değişmez sürümlerle** saklanır (`strategy_versions`); her yeni optimizasyon yeni versiyon üretir, soy ağacı (hangi taramadan, hangi ebeveynden) korunur. UI'da iki versiyon diff olarak karşılaştırılabilir.

### 8.2 Yaşam döngüsü

```
candidate → paper → live → retired
     ▲         │
     └── degrade tetiklenirse: pause + yeniden optimizasyon ──┘
```

### 8.3 AÇIK KARAR #2 — Kendini geliştirme mekanizması

| Kriter | **A) Walk-forward re-optimizasyon** | **B) Genetik algoritma** | **C) ML / Reinforcement Learning** |
|---|---|---|---|
| Ne yapar | Mevcut genome'ların parametrelerini takvimle (haftalık) yeni veriyle yeniden optimize eder | Genome'ları çaprazlar/mutasyona uğratır; yeni kural kombinasyonları **üretir** | Piyasa durumundan aksiyon öğrenen model eğitir |
| Karmaşıklık | Düşük | Orta | Yüksek |
| Açıklanabilirlik | Yüksek (kurallar aynı, parametreler değişir) | Orta-yüksek (üretilen kurallar okunabilir) | Düşük (kara kutu eğilimi) |
| Overfit riski | Kontrollü | Orta-yüksek → validator şart | Yüksek |
| Hesap yükü | Düşük-orta | Orta-yüksek | Yüksek (GPU ister) |
| Teslim süresi | 1–2 hafta | 3–6 hafta | Aylar |
| **Öneri** | **v1 — zorunlu temel** | **v2 — üretici katman** | v3 — opsiyonel araştırma rayı |

**Önerilen hibrit mimari (karar ne olursa olsun geçerli):** sistem üç bağımsız parçaya ayrılır — **Üretici** (yeni genome/parametre öneren şey: v1'de tarama+WFO re-opt, v2'de genetik, v3'te RL) → **Doğrulayıcı** (§6.5 savunma hattı, değişmez) → **Terfi kapısı** (§9.5). Üretici modüler bir arayüzün arkasındadır; karar değiştiğinde yalnızca üretici değişir. *Bu sayede "net değil" bugün geliştirmeyi bloklamaz.*

### 8.4 Rejim farkındalığı
Basit ama etkili katman: ADX + ATR yüzdelik dilimiyle piyasa **trend / yatay** ve **düşük / yüksek volatilite** olarak etiketlenir. Stratejiler uygun rejim etiketiyle saklanır; bot, aktif rejime uyan strateji havuzunu çalıştırır. (Tüm zaman dilimlerinde "motor kendisi seçsin" kararının uygulaması: rejim + TF, keşif skorlarına göre motor tarafından seçilir; manuel kilit her zaman mümkündür.)

### 8.5 Bozulma tetikleyicileri (canlı/paper izleme)
- Son 30 işlemde kayan Profit Factor < 1,0 **veya**
- Canlı equity, backtest beklenti bandının %95 Monte Carlo alt sınırını kırarsa
→ strateji otomatik **pause**, yeniden optimizasyon kuyruğa alınır, kullanıcıya bildirim gider. Terfi kararı (yeni versiyonun paper'a/canlıya dönüşü) varsayılan olarak **insan onaylıdır** (config ile tam otomatiğe alınabilir).

### 8.6 Strateji düzenleme katmanları — üçü birden (v1.1)

| Katman | Ne için | Nasıl |
|---|---|---|
| UI kural kurucu | Hızlı değişiklik, no-code | Sinyal primitifleri form olarak; kaydet → yeni versiyon |
| JSON/YAML | Hassas ve hacimli düzenleme | UI'da ham genome editörü + dosyadan içe/dışa aktarma |
| Python plugin | Tam esneklik | `backend/app/strategy/plugins/` içine `StrategyPlugin` arayüzünü uygulayan dosya; registry'ye yeni sinyal/karar tipi olarak katılır |

Üç katman da **aynı genome'a** yazar; genome'lar DB'de yaşar ve **hot-reload** ile restart'sız devreye girer (plugin dosyaları watcher ile yüklenir). Kaynağı ne olursa olsun her değişiklik **yeni bir değişmez versiyon** üretir — sessiz düzenleme diye bir şey yoktur. Sonuç: algoritmayı değiştirmek hiçbir zaman sistemi yeniden inşa etmek anlamına gelmez.

---

## 9. Trade Bot ve Emir Yürütme

### 9.1 Paper trading motoru (Faz 5 — kesinleşmiş başlangıç modu)
- Canlı fiyat akışını dinler; emirleri **dahili doldurma simülatörüyle** gerçekleştirir: bir sonraki tick/bar fiyatı + slippage modeli + komisyon.
- Paper ve canlı adaptör **aynı arayüzü** uygular (`place / cancel / positions / balance`); moddan bağımsız tek bot kodu.
- Paper sonuçları canlıyla aynı tablolara `mode=paper` etiketiyle yazılır — karşılaştırma bedavaya gelir.

### 9.2 AÇIK KARAR #1 — İlk canlı piyasa cephesi

| Kriter | **Binance (kripto)** | **Alpaca / IBKR (ABD hisse)** | **BIST** |
|---|---|---|---|
| API olgunluğu | Mükemmel; REST+WS; **resmi testnet** | Alpaca: mükemmel, yerleşik paper hesap; IBKR: çok güçlü ama karmaşık | Bireysel algo-API erişimi kısıtlı; bilinen pratik seçenek Deniz Yatırım **AlgoLab** (şartlar değişkendir, başlamadan teyit edilmeli) |
| Geçmiş veri | Ücretsiz ve tam | Alpaca IEX ücretsiz / SIP ücretli | Ücretli sağlayıcılar (Matriks, Finnet) |
| İşlem saati | 7/24 | Seans + uzatılmış | Seans (TSİ gündüz) |
| Maliyet | Spot ~%0,1 | Alpaca komisyonsuz | Aracıya göre + vergiler |
| TR'den erişim | Var | Var (W-8BEN vb. evrak) | Doğal |
| Bot geliştirme kolaylığı | **En kolay** | Kolay | En zor |
| **Öneri** | **Geliştirme + paper + ilk canlı cephe** | Faz 7 sonrası 2. adaptör | İstenirse 3. adaptör; önce API şartları doğrulanır |

**Bloklamayan varsayılan:** Karar kesinleşene kadar tüm geliştirme ve paper trading **Binance verisi/testnet'i** üzerinden yürür — bu, mimariyi hiçbir cepheye kilitlemez (adapter pattern) ve en hızlı yoldur. Kesin karar yalnızca Faz 7'nin (canlı emir) hangi adaptörle açılacağını belirler.

*v1.1 notu:* Long+short kararı bu matriste ibreyi fiilen **Binance USDT-M**'e çevirir — perpetual'da short, long kadar doğaldır; hisse tarafında short, borç alma/uygunluk mekaniği ve ek maliyet gerektirir; BIST'te açığa satış kısıtları ayrıca değerlendirilmelidir.

### 9.3 Emir adaptörü arayüzü

```python
class ExecutionAdapter(Protocol):
    def place_order(self, o: OrderRequest) -> OrderResult: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_positions(self) -> list[Position]: ...
    def get_balance(self) -> Balance: ...
```

Uygulamalar: `PaperAdapter` (Faz 5), `BinanceAdapter` (Faz 7), `AlpacaAdapter` / `BISTAdapter` (talebe göre).

### 9.4 Risk katmanı (bot ile adaptör arasında zorunlu duvar)

Hiçbir emir bu katmanı atlayamaz. Varsayılanlar (tümü config):

| Parametre | Varsayılan |
|---|---|
| İşlem başına risk | Equity'nin %1'i |
| Pozisyon boyutlama | ATR tabanlı (alternatifler: sabit oransal, Kelly/2 üst sınırlı) — *Açık Karar #4* |
| Maks. eşzamanlı pozisyon | 5 |
| Maks. günlük zarar | %3 → bot o gün durur |
| Maks. toplam drawdown | %15 → kill switch |
| Ardışık zarar soğuması | 4 zarar → 12 saat bekleme |
| Fiyat sapma koruması | Emir fiyatı son fiyattan >%1 sapıyorsa reddet |
| Kaldıraç | Sert tavan **10x** · güvenli varsayılan **5x** · strateji bazında tavana kadar |
| Marj | Isolated (varsayılan) · one-way pozisyon modu |
| Likidasyon tamponu | Likidasyon fiyatı girişe **≥ 3×ATR** uzakta olmalı; değilse kaldıraç o işlem için otomatik düşürülür |

**Kaldıraç hakkında dürüst not:** 10x'te yaklaşık %10'luk ters hareket (bakım marjı düşülmeden) likidasyon bölgesidir. Tavanı kullanmak kullanıcının hakkı; likidasyon tamponunun pazarlıksız olması ise hesabın hayatta kalma şartıdır.

**Kill switch:** UI'daki tek buton + `POST /api/bot/killswitch` + diskteki `KILLSWITCH` dosya bayrağı + Telegram `/kill` komutu (resmî dördüncü kanal — §10.3). Tetiklenince: tüm açık emirler iptal, yeni emir yolu kapalı, pozisyonlar için "kapat / tut" kararı kullanıcıya sorulur.

### 9.5 Paper → Canlı terfi kapısı (sayısal, his değil)

Varsayılan eşikler (config): paper'da **≥ 30 gün** ve **≥ 30 işlem**, Profit Factor **≥ 1,3**, MaxDD **≤ %10**, canlı-fiyat-paper sonuçlarının backtest beklentisinden sapması bant içinde. Kapı geçilmeden canlı adaptöre giden kod yolu **teknik olarak kapalıdır** ve bu bir testle kanıtlanır (Faz 7 kabul kriteri).

### 9.6 Mod şalteri — Live / Paper / Off (v1.1)
Sinyal başına onay yoktur; kontrol **üç konumlu şalterdedir** ve anlıktır:
- **Global ana şalter** + **strateji bazlı şalter** birlikte çalışır; etkin mod ikisinin düşüğüdür (Off < Paper < Live). Global Paper'dayken hiçbir strateji Live işleyemez.
- Aktifleştirme bilinçli bir kullanıcı eylemidir; şalter Live'dayken bot tam otonom işler.
- Her mod geçişi `audit_log`a yazılır ve Telegram bildirimi üretir; UI'dan, API'den ve Telegram `/mode` komutundan değiştirilebilir.

---

## 10. UI / UX — İki Sayfa

Tasarım dili: **Sessiz Lüks** sistemi devralınır — siyah/grafit zemin, yoğun negatif alan, grotesk tipografi, dekorsuz veri sunumu. Grafikler `lightweight-charts`; renk yalnızca anlam taşıdığında kullanılır (kâr/zarar, mod durumu, uyarılar). **Karakter (v1.1): hibrit** — kabuk minimal, panel içleri veri-yoğun; lüks, verinin azlığında değil gürültünün yokluğundadır. **Arayüz dili İngilizce**dir (kod + UI tek dil) ve tüm sayfalar **responsive** tasarlanır.

### 10.1 Sayfa 1 — Backtest Lab (`/backtest`)

| Panel | İçerik |
|---|---|
| Tarama kurucu | Evren (sembol) seçimi, TF seçimi, mod: **Otomatik keşif / Manuel** |
| Manuel mod | Kategorili + aranabilir indikatör seçici, parametre alanları, kural kurucu (sinyal primitifleri, sürükle-bırak yerine sade form), maliyet ayarları |
| İş kuyruğu | Koşan/kuyruktaki taramalar, ilerleme, iptal |
| Liderlik tablosu | Sıralanabilir sonuç tablosu (tüm metrikler + bileşik skor + denenen kombinasyon sayısı), filtreler |
| Koşu detayı | Equity eğrisi, drawdown grafiği, işlem listesi, aylık ısı haritası, WFO katman görünümü, mum grafiği üzerinde giriş/çıkış işaretleri + indikatör overlay |
| Karşılaştırma | 2–4 koşuyu yan yana |
| Aksiyonlar | "Stratejiye dönüştür" → Trade Deck'e candidate olarak düşer |

### 10.2 Sayfa 2 — Trade Deck (`/trade`)

| Panel | İçerik |
|---|---|
| Durum şeridi | **LIVE / PAPER / OFF** global mod şalteri (görmezden gelinemeyecek büyüklükte), equity, günlük PnL, aktif rejim etiketi, **KILL SWITCH** |
| Portföy | Açık pozisyonlar, bekleyen emirler, exposure |
| Sinyal akışı | Her sinyal: zaman, sembol, yön, strateji versiyonu, **gerekçe** (tetiklenen kurallar + o anki indikatör değerleri) |
| Strateji kartları | Versiyon, statü (candidate/paper/live), sağlık göstergeleri (kayan PF, DD), WFO özeti, strateji mod şalteri (Live/Paper/Off), versiyon diff |
| Karar günlüğü | Botun aldığı/almadığı her aksiyonun denetlenebilir kaydı (reddedilen sinyaller risk katmanı gerekçesiyle birlikte) |
| Ayarlar | Risk limitleri, terfi kapısı eşikleri, API anahtarları (maskeli), bildirimler |

### 10.3 Telegram — bildirim + uzaktan kumanda (v1.1'de kesinleşti)
**Bildirimler:** sinyal, dolum, risk olayı, bozulma tetikleyicisi, mod geçişi, kill switch.
**Komut seti (Trade Deck'in cepteki gölgesi):** `/status` · `/pnl` · `/positions` · `/mode live|paper|off [strateji]` · `/kill`
**Güvenlik:** komutlar yalnızca whitelist'teki tek chat ID'den kabul edilir; `/kill` ve `/mode live` iki adımlı onay ister; tüm komutlar `audit_log`a düşer.

---

## 11. Veritabanı Şeması (özet)

Piyasa verisi Parquet'te; PostgreSQL yalnızca uygulama durumunu tutar:

| Tablo | Ana alanlar |
|---|---|
| `symbols` | market, symbol, base, quote, active |
| `candle_sync_state` | symbol, tf, first_ts, last_ts, gaps(json) |
| `indicator_defs` | id, metadata(json) — registry'nin kalıcı hali |
| `backtest_runs` | config(json), config_hash, seed, status, metrics(json), artifact_path |
| `discovery_scans` | config(json), status, progress, stage, leaderboard(json) |
| `strategies` | name, created_from_run_id |
| `strategy_versions` | strategy_id, version, genome(json), wfo_report(json), status, parent_version_id |
| `signals` | strategy_version_id, ts, symbol, tf, direction, reason(json), indicator_snapshot(json) |
| `orders` / `trades` | mode(paper/live), signal_id, side, qty, entry/exit fiyat+zaman, fees, pnl, status |
| `equity_snapshots` | ts, mode, equity, exposure |
| `risk_events` | ts, type(daily_loss/killswitch/cooldown/price_guard…), detail(json) |
| `settings` | key, value (hassas alanlar şifreli) |
| `audit_log` | ts, actor, action, detail |

---

## 12. API Sözleşmesi (özet)

```
GET  /api/health
# Veri
POST /api/data/sync            GET /api/data/status
# İndikatörler
GET  /api/indicators           GET /api/indicators/{id}
# Backtest & keşif
POST /api/backtest/run         GET  /api/backtest/runs/{id}
POST /api/discovery/scan       GET  /api/discovery/scans/{id}
GET  /api/discovery/leaderboard
# Stratejiler
POST /api/strategies/from-run  GET  /api/strategies
POST /api/strategies/{id}/promote|pause|retire
GET  /api/strategies/{id}/versions
# Bot
POST /api/bot/start|stop       POST /api/bot/killswitch
GET  /api/portfolio            GET  /api/signals?since=
# Canlı yayın
WS   /ws/live   (fiyat, sinyal, dolum, equity, risk olayları)
```

---

## 13. Güvenlik

1. **Borsa API anahtarları:** *yalnızca* işlem + okuma yetkili, **çekim (withdraw) yetkisi kapalı** anahtarlar kullanılır — pazarlıksız. Borsa tarafında IP whitelist (VDS IP'si) açılır.
2. Anahtarlar diske **şifreli** yazılır (Fernet; ana anahtar yalnızca env'de), frontend'e asla gitmez, loglara asla sızmaz (log filtresi testle doğrulanır).
3. UI tek kullanıcılıdır: token/basic-auth + Coolify/Traefik üzerinden HTTPS zorunlu.
4. Tüm mutasyon endpoint'leri `audit_log`a yazar; kill switch ve terfi olayları ayrıca bildirim üretir.
5. Repo'da secret bulunmaz; `.env.example` şablonu tutulur.

---

## 14. Deployment (VDS · Docker · Coolify)

`docker-compose.yml` servisleri:

| Servis | Görev | Not |
|---|---|---|
| `frontend` | Next.js | |
| `api` | FastAPI | |
| `worker` | arq consumer | Tarama/WFO burada koşar — CPU yoğun |
| `redis` | Kuyruk + cache | |
| `postgres` | Uygulama DB | Volume |
| — | `/data/parquet` volume | Mum verisi + indikatör cache |

**Zamanlanmış işler** (worker cron): TF kapanışlarında veri sync · gece otomatik keşif taraması (opsiyonel) · haftalık WFO re-optimizasyonu · günlük Parquet/DB yedeği.

**Kaynak notu:** Standart tarama için 2 vCPU / 4–8 GB yeterli; **derin tarama (1m/5m)** ve geniş evrenler için 4+ vCPU / 16 GB önerilir. vectorbt bellek iştahlıdır; worker'da sembol-parti (batch) işleme zorunludur.

---

## 15. Yol Haritası — Fazlar ve Kabul Kriterleri

Her faz, Claude Code'a tek başına verilebilecek bir iş paketidir. Kabul kriterleri geçilmeden sonraki faza başlanmaz.

### Faz 0 — İskelet ve Altyapı
Kapsam: Depo yapısı (§3.3), docker-compose (5 servis), FastAPI + Next.js merhaba-dünya, pytest + lint CI, `/api/health`.
**Kabul:** `docker compose up` ile tüm servisler ayakta; health 200; testler yeşil.

### Faz 1 — Veri Katmanı
Kapsam: ccxt/Binance USDT-M OHLCV **+ funding rate** indirici, Parquet store + DuckDB sorgu katmanı, gap tespiti/onarımı, sync cron, `candle_sync_state`, **dinamik evren kurucu + tarihli snapshot** (§4.5).
**Kabul:** Evren kurucu top-30 listesi + tarihli snapshot üretir; 10 sembol × 6 TF × 24 ay + funding serileri yüklü; bütünlük testi gap=0; tipik DuckDB sorgusu < 1 sn.

### Faz 2 — İndikatör Registry
Kapsam: TA-Lib + pandas-ta birleşik registry (200+), sinyal primitifleri (§5.4), hesap + Parquet cache, custom eklenti yükleyici.
**Kabul:** Tüm indikatörler örnek sembolde hatasız hesaplanır; en az 10 çekirdek indikatör bilinen referans değerlerle birim testinden geçer; cache isabeti loglanır.

### Faz 3 — Backtest Çekirdeği + Backtest Lab v1 (manuel mod)
Kapsam: vectorbt sarmalayıcı, maliyet modeli, tam metrik seti, `backtest_runs`; UI: manuel kurucu, koşu detayı (equity, DD, işlem listesi, mum+işaretler).
**Kabul:** EMA9×EMA21 referans stratejisi elle hesaplanmış sonuçla eşleşir; lookahead testi (sinyali 1 bar kaydırınca sonuç değişmeli) geçer; UI'dan uçtan uca koşu yapılır.

### Faz 4 — Otomatik Keşif Pipeline'ı
Kapsam: Aşama 0–6 (§7), Optuna entegrasyonu, WFO motoru (§6.5), liderlik tablosu UI, backtesting.py finalist doğrulaması.
**Kabul:** 10 sembol × 4 TF standart tarama < 2 saat; aynı seed → aynı sıralama; iki motor uyuşmazlığı alarm üretir.

### Faz 5 — Strateji Motoru + Paper Trading + Trade Deck
Kapsam: Genome + sürümleme (§8.1), üç katmanlı düzenleme (§8.6), paper doldurma simülatörü, risk katmanı (§9.4), mod şalteri (§9.6), kill switch (4 kanal), sinyal akışı + karar günlüğü UI, Telegram bildirim + komut seti (§10.3).
**Kabul:** Paper bot 72 saat kesintisiz koşar; her sinyalde reason + indicator_snapshot dolu; kill switch dört kanaldan da botu < 2 sn'de durdurur; Telegram'dan mod geçişi çalışır; genome hot-reload restart'sız devreye girer; risk limit ihlali simülasyonu emirleri bloklar.

### Faz 6 — Kendini Geliştirme v1
Kapsam: Haftalık WFO re-opt zamanlayıcısı, bozulma tetikleyicileri (§8.5), yeni versiyon üretimi + insan onaylı terfi akışı, rejim etiketleme (§8.4).
**Kabul:** Bozulma senaryosu simülasyonunda strateji otomatik pause olur, yeni versiyon raporuyla birlikte onaya düşer.

### Faz 7 — Canlı Yürütme (kapının arkasında)
Kapsam: Binance **USDT-M futures** adaptörü (veya kesinleşen cephe) — isolated marj, kaldıraç tavanı ve likidasyon tamponu uygulanmış; terfi kapısı (§9.5); mikro sermaye ile kontrollü açılış; canlı-paper sapma izleme.
**Kabul:** Kapı eşiği sağlanmadan canlı emir yolunun çağrılamadığı **testle kanıtlanır**; ilk canlı işlemler mikro boyutta ve tam loglu gerçekleşir.

**Süre gerçekçiliği (Claude Code destekli, yarı zamanlı tempo):** Faz 0–3 ≈ 2–3 hafta · Faz 4–5 ≈ 3–4 hafta · Faz 6–7 ≈ 2–3 hafta. Toplam **≈ 2–2,5 ay**. Daha kısa vaat eden herkes ya tam zamanlı çalışıyordur ya da yalan söylüyordur.

---

## 16. Kararlar Panosu

### 16.1 v1.1'de kapanan kararlar
Yön: **long + short** (Binance USDT-M perpetual futures) · Kaldıraç: **sert tavan 10x, güvenli varsayılan 5x**, isolated marj + likidasyon tamponu (§9.4) · Otonomi: sinyal onayı yok, **global + strateji bazlı Live/Paper/Off şalteri** (§9.6) · Strateji düzenleme: **üç katman + hot-reload** (§8.6) · Sembol evreni: **dinamik likidite filtresi + tarihli snapshot** (§4.5) · UI dili: **İngilizce** · UI karakteri: **hibrit** (minimal kabuk, yoğun panel) · Mobil: **responsive + Telegram kumanda** (§10.3) · Bildirim: **Telegram** · Niyet: **tamamen kişisel araç** (çok kullanıcı hazırlığı yok).

### 16.2 Hâlâ açık kararlar

Geliştirme bu varsayılanlarla **bloklanmadan** ilerler; karar netleşince ilgili bölümde tek nokta değişir.

| # | Karar | Seçenekler | Bloklamayan varsayılan | Bölüm |
|---|---|---|---|---|
| 1 | İlk canlı piyasa cephesi | Binance / Alpaca-IBKR / BIST | Geliştirme + paper: **Binance USDT-M (testnet)** — long+short kararı ibreyi buraya çevirdi | §9.2 |
| 2 | Kendini geliştirme mekanizması | WFO re-opt / Genetik / ML-RL | **v1: WFO re-opt**; üretici arayüzü modüler | §8.3 |
| 3 | Piyasa verisi deposu | Parquet+DuckDB / TimescaleDB | **Parquet + DuckDB** | §4.3 |
| 4 | Pozisyon boyutlama | ATR / sabit oransal / Kelly-capped | **ATR tabanlı** | §9.4 |

---

## 17. Claude Code — Kullanım Kılavuzu ve Promptlar

### 17.1 Kurulum düzeni
1. Boş depo aç, `docs/PROJE_DOKUMANI.md` olarak bu dosyayı, köke de ekteki `CLAUDE.md` dosyasını koy. (Claude Code, kökteki `CLAUDE.md`'yi her oturumda otomatik hafıza olarak okur.)
2. Claude Code'u proje kökünde başlat; güncel kurulum/kullanım detayları için: https://docs.claude.com/en/docs/claude-code/overview
3. İlk mesaj olarak **Master Prompt**'u (17.2) `FAZ 0` ile ver. Sonraki fazlarda yalnızca **Faz Prompt Şablonu**'nu (17.3) kullanmak yeterlidir — bağlamın kalanı `CLAUDE.md` + dokümandan gelir.
4. Faz aralarında **Denetim Promptu**'nu (17.4) çalıştırmak, ucuz bir sigorta poliçesidir.

### 17.2 MASTER PROMPT

```text
Sen UNKNOWNINCOME projesinin baş mühendisisin. Görevin docs/PROJE_DOKUMANI.md'de tanımlanan
otonom backtest + trading sistemini faz faz inşa etmek. Önce o dokümanı ve kökteki
CLAUDE.md'yi oku.

BAĞLAM
- Stack: Python 3.11+ / FastAPI / arq + Redis / PostgreSQL; piyasa verisi Parquet + DuckDB.
- Frontend: Next.js 15 + TypeScript + Tailwind + lightweight-charts.
- Deployment: Docker Compose (Coolify/VDS). Her servis konteynerize.
- Tek kullanıcılı sistem; mimari çok-piyasalı (adapter pattern). İlk veri/emir
  adaptörü: Binance USDT-M perpetual futures (ccxt) — long + short, isolated marj,
  paper trading öncelikli. UI dili İngilizce.

PAZARLIKSIZ KURALLAR
1. Lookahead bias yasak: sinyal bar kapanışında üretilir, dolum bir sonraki bar
   açılışında simüle edilir. Her indikatör/sinyal hesabında bunu koru ve test et.
2. Komisyon + slippage + funding (perpetual) her backtest'te varsayılan olarak AÇIK.
3. Bir strateji walk-forward + out-of-sample doğrulamasından geçmeden "candidate"
   statüsünün üstüne çıkamaz.
4. Canlı emir kod yolu, terfi kapısı (doküman §9.5) ve kill switch kontrolünden
   geçmeden ÇALIŞAMAZ; bunu birim testiyle kanıtla.
5. Tüm timestamp'ler UTC; UI gösterimi Europe/Istanbul.
6. Her backtest/tarama config hash + seed ile bit-for-bit tekrarlanabilir olmalı.
7. API anahtarları koda, loga, frontend'e asla sızmaz; anahtarlar withdraw
   yetkisiz varsayılır; log filtresi testle doğrulanır.
8. Çekirdek motor asset-agnostic kalır; piyasa özel kod yalnızca data/ ve
   execution/ adaptörlerinde yaşar.
9. Python'da type hint zorunlu; metrikler, maliyet modeli ve sinyal primitifleri
   pytest ile test edilir.
10. Açık kararlarda (doküman §16) tanımlı varsayılanı uygula; alternatifi
    arayüz (interface) arkasında değiştirilebilir bırak. Dokümanda cevabı olmayan
    mimari sorularda durup bana sor.
11. Kaldıraç: sert tavan 10x, güvenli varsayılan 5x; likidasyon fiyatı girişe
    ≥ 3×ATR mesafede değilse kaldıracı o işlem için otomatik düşür.
12. Dinamik sembol evreni tarihli snapshot'larla saklanır; her backtest, test
    ettiği tarihte geçerli evreni kullanır (survivorship bias yasağı).

ÇALIŞMA DİSİPLİNİ
- Şu an FAZ {N} üzerindesin. Önce docs/PROJE_DOKUMANI.md §15'teki faz kapsamını
  ve kabul kriterlerini oku, kısa bir uygulama planı sun, onayımdan sonra kodla.
- Faz sonunda: testleri koştur, kabul kriterlerini tek tek kanıtla, kısa bir
  "yapılanlar / riskler / sonraki adım" raporu yaz.
- Kabul kriterleri geçmeden sonraki faza başlama. Kapsam dışına çıkma; "hazır
  gelmişken" özelliği icat etme.
```

### 17.3 Faz Prompt Şablonu

```text
FAZ {N} — {Faz adı}
docs/PROJE_DOKUMANI.md §15 Faz {N} kapsamını uygula. Master prompt'taki tüm
kurallar geçerli.
Ek bağlam / değişiklik: {varsa yaz, yoksa "yok"}
Önce plan sun, onaydan sonra uygula. Bitince kabul kriterlerini kanıtla.
```

### 17.4 Denetim Promptu (faz aralarında)

```text
Denetçi şapkanı tak; kod yazma, yalnızca raporla. backend/backtest/,
backend/indicators/ ve backend/discovery/ altını şu açılardan denetle:
1) Lookahead bias: eksik shift'ler, aynı barda sinyal+dolum, geleceğe bakan
   rolling pencereler.
2) Survivorship bias: sembol evreni bugünkü listeyle mi kuruluyor?
3) Maliyet modelinin atlandığı kod yolları.
4) Tekrarlanabilirlik kırıkları: seed'siz rastgelelik, zaman/dil ortamına bağlı
   davranış.
5) Sızıntı: API anahtarının loga/hata mesajına düşebileceği yollar.
Her bulgu için: dosya:satır, açıklama, önerilen düzeltme. Bulgu yoksa "temiz" de
ve nasıl doğruladığını yaz.
```

---

## 18. Kısa Sözlük

**OHLCV:** Açılış-Yüksek-Düşük-Kapanış-Hacim mum verisi. · **Lookahead bias:** Backtest'in, karar anında henüz var olmayan bilgiyi kullanması. · **Walk-forward (WFO):** Kayan pencerelerle "geçmişte optimize et, hemen sonraki görülmemiş dönemde test et" döngüsü. · **Out-of-sample (OOS):** Optimizasyonda hiç kullanılmamış veri dilimi. · **Profit Factor:** Brüt kâr / brüt zarar. · **Expectancy:** İşlem başına beklenen ortalama getiri. · **Drawdown:** Zirveden dibe düşüş. · **Slippage:** Beklenen fiyat ile gerçekleşen dolum fiyatı farkı. · **Paper trading:** Gerçek fiyatlarla, sahte parayla işlem simülasyonu. · **Rejim:** Piyasanın trend/yatay, sakin/oynak gibi durum etiketi.

---

## 19. Yasal ve Risk Notu

Bu yazılım kişisel araştırma ve eğitim amaçlıdır; **yatırım tavsiyesi değildir ve vermez.** Geçmiş performans — walk-forward'dan geçmiş olsa bile — gelecekteki getiriyi garanti etmez. Gerçek sermayeyle işlem, tamamen kullanıcının kararı ve riskidir; sistemin tüm risk katmanları kaybı sınırlamaya yardım eder, imkânsız kılmaz. Kullanılan borsa/aracı kurum API'lerinin kullanım şartlarına ve yerel mevzuata uyum kullanıcı sorumluluğundadır. Kaldıraçlı perpetual futures işlemleri kayıpları kaldıraç oranında büyütür; likidasyon, ilgili pozisyon teminatının tamamen kaybı anlamına gelir.

---

*UNKNOWNINCOME Proje Dokümanı v1.1 — sonu.*
