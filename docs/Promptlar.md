# UNKNOWNINCOME — Claude Code Prompt Kitabı
### Faz faz · push → deploy → sunucu testi döngüsüne göre

Kaynak gerçek: `docs/PROJE_DOKUMANI.md` v1.1 — çelişki olursa doküman kazanır. Kurallar `CLAUDE.md`'den her oturumda otomatik yüklenir; bu yüzden promptlar bilerek kısadır, kural tekrarı yoktur.

---

## Çalışma döngüsü (her fazda aynı ritüel)

1. Fazın promptunu Claude Code'a yapıştır.
2. Sunduğu **planı oku** — onayla veya düzelt. Onaysız kod yok.
3. Kod + lokal testler biter, kabul kriterleri tek tek kanıtlanır.
4. Claude Code **commit + push** eder (`main`) ve faz tag'i atar (`faz-0`, `faz-1`, …).
5. Coolify otomatik deploy alır → aşağıdaki **Sunucu Testi** listesini sen koşarsın.
6. Sorun varsa **Prompt S** ile döngüye geri sok; temizse sıradaki faza geç. Faz aralarında ara sıra **Prompt D** (denetim) çalıştırmak ucuz bir sigortadır.

**Bir kereye mahsus senin yapacakların:** GitHub reposunu aç · Coolify'da docker-compose kaynaklı uygulamayı kur (branch: `main`, auto-deploy açık) · tüm secret'ları (DB şifresi, Telegram token, borsa anahtarları) **yalnızca Coolify env'ine** gir — repoya asla.

---

## P-BAŞLANGIÇ — proje açılışı (bir kez)

```text
UNKNOWNINCOME projesini başlatıyoruz. Önce docs/PROJE_DOKUMANI.md ve CLAUDE.md'yi oku.
Bu adımda KOD YAZMA; yalnızca şunları yap:

1. git init; anlamlı bir .gitignore (Python, Node, .env*, /data, __pycache__,
   node_modules, .parquet).
2. .env.example oluştur: gereken tüm env değişkenleri placeholder'la
   (DATABASE_URL, REDIS_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
   BINANCE_API_KEY/SECRET, ENCRYPTION_KEY...). Gerçek değer yok.
3. docs/PROGRESS.md oluştur: Faz 0–7 için işaretlenebilir checklist
   (kapsam tek satır + kabul kriterleri + durum kutusu).
4. README.md: 10 satırlık proje özeti + "nasıl çalıştırılır" iskeleti.
5. git remote add origin {GITHUB_REPO_URL} — URL'yi benden iste.
6. İlk commit: "chore: bootstrap UNKNOWNINCOME repo" ve push origin main.

Bittiğinde kısa rapor ver: oluşturulan dosyalar + push sonucu.
```

**Sunucu testi:** Henüz yok — Coolify uygulamasını bu push'tan sonra bağla, ilk gerçek deploy Faz 0'da.

---

## FAZ 0 — İskelet ve Altyapı

```text
FAZ 0 — İskelet
docs/PROJE_DOKUMANI.md §3 (mimari) ve §15/Faz 0'ı oku. Plan sun, onayımdan
sonra uygula. Kapsam dışına çıkma.

KAPSAM
- §3.3'teki depo yapısını kur.
- docker-compose.yml: frontend, api, worker, redis, postgres + /data/parquet
  volume. Her servise healthcheck (Coolify bunları izleyecek).
- FastAPI: GET /api/health (versiyon + git sha döner).
- Next.js 15: /backtest ve /trade boş kabuk sayfaları — UI İngilizce,
  Sessiz Lüks hibrit karakter için temel layout + tema token'ları.
- pytest + ruff (backend), eslint (frontend); GitHub Actions CI: lint + test.

KABUL
- docker compose up --build → 5 servis ayakta; /api/health 200; iki sayfa açılır.
- pytest, ruff, eslint ve CI yeşil.

TESLİM
- Conventional commit'ler; push origin main; tag: faz-0.
- docs/PROGRESS.md güncelle. Kısa rapor: yapılanlar / riskler / sonraki adım.
```

**Sunucu testi:** Coolify deploy yeşil · `/api/health` 200 ve doğru git sha · `/backtest` ile `/trade` yükleniyor · container'lar restart döngüsünde değil.

---

## FAZ 1 — Veri Katmanı

```text
FAZ 1 — Veri Katmanı
docs/PROJE_DOKUMANI.md §4 ve §15/Faz 1'i oku. Plan sun, onaydan sonra uygula.

KAPSAM
- ccxt ile Binance USDT-M perpetual OHLCV + funding rate geçmişi indirici.
- Parquet store (/data/parquet/{market}/{symbol}/{tf}.parquet) + DuckDB sorgu
  katmanı; funding ayrı parquet seti.
- Gap tespiti + onarımı; candle_sync_state tablosu; worker'da sync cron
  (her TF kapanışında artımlı çekim).
- Dinamik evren kurucu (§4.5): 30g medyan hacim + spread filtresi, stablecoin
  ve kaldıraçlı token eleme, top-30, haftalık yenileme, universe_snapshots
  tablosuna TARİHLİ snapshot.
- API: POST /api/data/sync, GET /api/data/status (sembol × TF doluluk + gap).

KABUL
- Evren kurucu top-30 + tarihli snapshot üretir.
- 10 sembol × 6 TF × 24 ay + funding serileri yüklü; bütünlük testi gap=0.
- Tipik DuckDB aralık sorgusu < 1 sn (test ile ölç).

TESLİM
- push origin main; tag: faz-1; PROGRESS.md güncel; kısa rapor.
```

**Sunucu testi:** `/api/data/sync` tetikle → worker logunda ilerleme · `/api/data/status` doluluk gösteriyor · parquet volume boyutu büyüyor · birkaç saat sonra cron'un artımlı çektiğini logdan doğrula.

---

## FAZ 2 — İndikatör Registry

```text
FAZ 2 — İndikatör Registry
docs/PROJE_DOKUMANI.md §5 ve §15/Faz 2'yi oku. Plan sun, onaydan sonra uygula.

KAPSAM
- TA-Lib + pandas-ta birleşik registry (200+), §5.3 metadata şemasıyla;
  kategori/parametre aralıkları dahil. indicator_defs tablosuna persist.
- Sinyal primitifleri (§5.4): threshold_cross, line_cross, slope, band_touch,
  regime, pattern — hepsi lookahead-güvenli (bar kapanışı esaslı, testli).
- Hesap motoru + Parquet cache: (symbol, tf, indicator_id, params_hash).
- Custom eklenti yükleyici: indicators/custom/ klasörü, örnek bir custom
  indikatörle birlikte.
- API: GET /api/indicators, GET /api/indicators/{id},
  POST /api/indicators/compute (debug/önizleme amaçlı).

KABUL
- Tüm registry örnek sembolde hatasız hesaplanır (toplu smoke test).
- En az 10 çekirdek indikatör bilinen referans değerlerle birim testinden geçer.
- Cache isabet/ıskalama loglanır; ikinci hesap cache'ten gelir (test).

TESLİM
- push origin main; tag: faz-2; PROGRESS.md; kısa rapor.
```

**Sunucu testi:** `GET /api/indicators` 200+ kayıt dönüyor · `POST /api/indicators/compute` ile BTC/USDT 1h RSI önizlemesi mantıklı değerler veriyor · aynı isteği tekrarla → logda cache hit.

---

## FAZ 3 — Backtest Çekirdeği + Backtest Lab v1 (manuel mod)

```text
FAZ 3 — Backtest Çekirdeği + UI v1
docs/PROJE_DOKUMANI.md §6 ve §15/Faz 3'ü oku. Plan sun, onaydan sonra uygula.

KAPSAM
- vectorbt sarmalayıcısı: sinyal → pozisyon → equity; komisyon + slippage +
  funding varsayılan AÇIK (§6.2); long ve short destekli.
- §6.3 tam metrik seti + §6.4 bileşik skor; backtest_runs tablosu
  (config_hash + seed ile).
- API: POST /api/backtest/run (async, arq), GET /api/backtest/runs/{id}.
- Backtest Lab UI — manuel mod: sembol/TF seçimi, kategorili indikatör seçici,
  parametre formu, kural kurucu (sinyal primitifleri), maliyet ayarları;
  koşu detayı: equity eğrisi, drawdown, işlem listesi, aylık ısı haritası,
  mum grafiği üzerinde giriş/çıkış işaretleri (lightweight-charts).

KABUL
- EMA9×EMA21 referans stratejisi elle hesaplanmış sonuçla eşleşir (test).
- Lookahead testi: sinyaller 1 bar kaydırılınca sonuç DEĞİŞMELİ (test).
- Aynı config+seed → bit-for-bit aynı sonuç (test).
- UI'dan uçtan uca bir koşu yapılıp rapor görüntülenir.

TESLİM
- push origin main; tag: faz-3; PROGRESS.md; kısa rapor.
```

**Sunucu testi:** `/backtest`'ten EMA cross koşusu başlat → ilerleme → rapor ekranı tam render · maliyetleri kapatınca raporda kırmızı "maliyetsiz" etiketi · aynı koşuyu tekrarla → birebir aynı metrikler.

---

## FAZ 4 — Otomatik Keşif Pipeline'ı

```text
FAZ 4 — Otomatik Keşif
docs/PROJE_DOKUMANI.md §7, §6.5 ve §15/Faz 4'ü oku. Plan sun, onaydan sonra
uygula.

KAPSAM
- Aşama 0–6 pipeline'ı (§7): tekli tarama → korelasyon eleme (|ρ|>0.85) →
  rol tabanlı kombinasyon (tetikleyici+filtre+çıkış, kategori kısıtlı) →
  Optuna parametre araması → WFO doğrulama (§6.5) → liderlik tablosu.
- WFO motoru: kayan pencere (varsayılan 90g eğitim / 30g test / 30g adım),
  parametre platosu kontrolü, Monte Carlo işlem karıştırma.
- Backtest tarihinde geçerli evren snapshot'ı kullanılır (§4.5 —
  survivorship bias testi yaz).
- backtesting.py ile finalist çapraz doğrulaması; iki motor uyuşmazlığında
  alarm kaydı.
- discovery_scans tablosu (progress + stage); "hızlı mod" (küçük evren/kısa
  dönem, geliştirme için).
- API: POST /api/discovery/scan, GET /api/discovery/scans/{id},
  GET /api/discovery/leaderboard.
- UI: tarama kurucu (otomatik mod), canlı ilerleme, sıralanabilir liderlik
  tablosu (denenen kombinasyon sayısı görünür), koşu detayına geçiş,
  "Stratejiye dönüştür" butonu (Faz 5'te bağlanacak, şimdilik disabled).

KABUL
- Hızlı mod taraması uçtan uca biter; 10 sembol × 4 TF standart tarama
  < 2 saat (worker'da ölçüm logu).
- Aynı seed → aynı liderlik sıralaması (test).
- Survivorship testi: geçmiş tarihli backtest, o günün evrenini kullanır.
- Motor uyuşmazlığı senaryosu alarm üretir (test).

TESLİM
- push origin main; tag: faz-4; PROGRESS.md; kısa rapor.
```

**Sunucu testi:** Hızlı mod tarama başlat (3 sembol × 2 TF) → progress akıyor → liderlik doluyor · aynı taramayı aynı seed'le tekrarla → aynı sıralama · worker RAM/CPU'yu Coolify metriklerinden izle (taşma yoksa standart taramayı dene).

---

## FAZ 5 — Strateji Motoru + Paper Trading + Trade Deck

```text
FAZ 5 — Strateji + Paper + Trade Deck
docs/PROJE_DOKUMANI.md §8, §9, §10 ve §15/Faz 5'i oku. Plan sun, onaydan
sonra uygula.

KAPSAM
- Genome + değişmez sürümleme (§8.1–8.2) + soy ağacı; liderlik tablosundan
  "Stratejiye dönüştür" akışı aktif.
- Üç katmanlı düzenleme (§8.6): UI kural kurucu, ham JSON editörü
  (içe/dışa aktarma), strategy/plugins/ Python eklenti yükleyici — hepsi
  hot-reload, her değişiklik yeni versiyon.
- Paper doldurma simülatörü (§9.1): canlı fiyat + slippage + komisyon +
  funding; ExecutionAdapter arayüzü (PaperAdapter ilk uygulama).
- Risk katmanı (§9.4): tüm limitler + likidasyon tamponu iskeleti; hiçbir
  emir katmanı atlayamaz (mimari test).
- Mod şalteri (§9.6): global + strateji bazlı Live/Paper/Off; etkin mod =
  min(global, strateji). LIVE konumu UI'da görünür ama Faz 7'ye kadar
  DEVRE DIŞI (adaptör yok) — tooltip ile açıkla.
- Kill switch 4 kanal: UI butonu, POST /api/bot/killswitch, KILLSWITCH
  dosyası, Telegram /kill (iki adımlı onay).
- Telegram bot: /status /pnl /positions /mode paper|off [strateji] /kill —
  yalnızca whitelist chat ID; tüm komutlar audit_log'a.
- Trade Deck UI (§10.2): durum şeridi, portföy, sinyal akışı (reason +
  indicator_snapshot), strateji kartları, karar günlüğü, ayarlar.

KABUL
- Paper bot 72 saat kesintisiz koşar (sunucuda doğrulanacak; lokalde 1 saat
  soak testi).
- Her sinyalde reason + indicator_snapshot dolu (test).
- Kill switch DÖRT kanaldan da botu < 2 sn'de durdurur (test).
- Telegram'dan mod geçişi çalışır; whitelist dışı chat reddedilir (test).
- Genome değişikliği hot-reload ile restart'sız devreye girer (test).
- Risk limiti ihlali simülasyonu emirleri bloklar ve risk_events'e yazar.

TESLİM
- push origin main; tag: faz-5; PROGRESS.md; kısa rapor.
```

**Sunucu testi:** Liderlikten strateji oluştur → Paper'a al → sinyaller akmaya başlasın · Telegram'dan `/status` ve `/pnl` cevap veriyor · `/kill` iki adımlı onayla botu durduruyor, UI'da yansıyor · genome'u UI'dan değiştir → restart olmadan yeni versiyon aktif · 72 saat çalışır bırak, sonra logları tara.

---

## FAZ 6 — Kendini Geliştirme v1

```text
FAZ 6 — Kendini Geliştirme (WFO re-opt)
docs/PROJE_DOKUMANI.md §8.3–8.5 ve §15/Faz 6'yı oku. Plan sun, onaydan sonra
uygula.

KAPSAM
- Üretici arayüzü (StrategyGenerator protokolü) — v1 uygulaması: haftalık
  WFO re-optimizasyon zamanlayıcısı (yeni veriyle parametre yenileme).
  Genetik/RL için arayüz boş ama tanımlı kalsın.
- Bozulma tetikleyicileri (§8.5): kayan 30 işlem PF < 1.0 veya Monte Carlo
  %95 alt bandı kırılımı → strateji otomatik PAUSE + re-opt kuyruğa +
  Telegram bildirimi.
- İnsan onaylı terfi akışı: yeni versiyon "onay bekliyor" kartı (UI +
  Telegram bildirimi); onaylanınca paper'da devreye girer.
- Rejim etiketleme (§8.4): ADX + ATR yüzdelik; stratejilere rejim etiketi;
  bot aktif rejime uyan havuzu koşturur (manuel kilit mümkün).
- Test kancası: bozulmayı simüle eden bir debug endpoint/fixture.

KABUL
- Bozulma simülasyonunda strateji pause olur, yeni versiyon raporuyla onaya
  düşer, Telegram bildirimi gider (uçtan uca test).
- Zamanlayıcı çalışır (lokalde kısaltılmış aralıkla test).
- Onaylanmamış versiyon asla işlem üretmez (test).

TESLİM
- push origin main; tag: faz-6; PROGRESS.md; kısa rapor.
```

**Sunucu testi:** Debug kancasıyla bozulma tetikle → strateji pause + Telegram uyarısı geldi · onay kartından yeni versiyonu onayla → paper'da yeni versiyon işliyor, eski retired · haftalık cron'un kayıtlı olduğunu worker logunda gör.

---

## FAZ 7 — Canlı Yürütme (kapının arkasında)

```text
FAZ 7 — Canlı Yürütme
docs/PROJE_DOKUMANI.md §9.2–9.5 ve §15/Faz 7'yi oku. Plan sun, onaydan sonra
uygula. Bu fazda temkin bir erdem değil, gerekliliktir.

KAPSAM
- BinanceFuturesAdapter (ccxt, USDT-M): isolated marj, one-way mod; kaldıraç
  sert tavan 10x / strateji varsayılanı 5x; likidasyon tamponu (giriş ile
  likidasyon fiyatı arası < 3×ATR ise kaldıracı o işlem için otomatik düşür,
  risk_events'e logla). Önce TESTNET, config ile mainnet.
- Terfi kapısı (§9.5): eşikler config'te; sağlanmadan global/strateji mod
  şalteri LIVE'a ALINAMAZ — hem UI hem API katmanında reddedilir.
- Fiyat sapma koruması, borsa hata/ratelimit dayanıklılığı (retry + circuit
  breaker), emir-durum mutabakatı (borsa ile lokal state senkronu).
- Canlı-paper sapma izleme paneli (tracking error).
- API anahtarları: Fernet ile şifreli saklama, log filtresi testi; anahtar
  girişi yalnızca Ayarlar UI'ından (maskeli).

KABUL
- Gate sağlanmadan LIVE moda geçiş her katmanda reddedilir — TESTLE KANITLA.
- Testnet'te mikro long ve short emirleri açılıp kapanır; kaldıraç ve marj
  modu doğru set edilir (log kanıtı).
- Likidasyon tamponu derating'i test senaryosunda çalışır.
- Anahtar sızıntı testi: loglar ve hata mesajları taranır, anahtar izi yok.

TESLİM
- push origin main; tag: faz-7; PROGRESS.md; kısa rapor + "canlıya geçiş
  öncesi kontrol listesi" (docs/GO_LIVE_CHECKLIST.md) üret.
```

**Sunucu testi:** Testnet anahtarlarıyla: gate koşulları sağlanmadan `/mode live` hem UI hem Telegram'dan reddediliyor · test config'iyle gate'i düşür → mikro testnet emri açılıp kapanıyor, Telegram bildirimleri geliyor · GO_LIVE_CHECKLIST.md'yi oku; mainnet kararı tamamen sana ait — kapı sayısal, sorumluluk kişisel.

---

## PROMPT S — Sunucu geri bildirimi (hata döngüsü)

Deploy sonrası bir şey kırıldığında bunu doldurup yapıştır:

```text
SUNUCU TEST RAPORU — FAZ {N}
Ortam: Coolify/VDS · commit: {git sha veya tag}
Belirti: {ne bekliyordum, ne oldu — adım adım}
Loglar / hata çıktısı:
---
{ilgili log satırlarını yapıştır}
---
Görev: kök nedeni bul ve açıkla, düzelt, bu hatayı yakalayan bir regresyon
testi ekle, lokalde doğrula, commit + push et. Faz kapsamı dışına çıkma;
başka bir şeyi "iyileştirme".
```

---

## PROMPT D — Denetim (faz aralarında, kod yazmaz)

```text
Denetçi şapkanı tak; kod yazma, yalnızca raporla. backend/backtest/,
backend/indicators/, backend/discovery/ ve backend/execution/ altını denetle:
1) Lookahead bias: eksik shift'ler, aynı barda sinyal+dolum, geleceğe bakan
   rolling pencereler.
2) Survivorship bias: backtest'ler tarihli evren snapshot'ı mı kullanıyor?
3) Maliyet modelinin (komisyon/slippage/funding) atlandığı kod yolları.
4) Tekrarlanabilirlik: seed'siz rastgelelik, ortam bağımlı davranış.
5) Sızıntı: API anahtarının loga/hata mesajına düşebileceği yollar.
6) Risk katmanını bypass eden emir yolu var mı?
Her bulgu için: dosya:satır, açıklama, önerilen düzeltme. Bulgu yoksa "temiz"
de ve nasıl doğruladığını yaz.
```

---

## PROMPT O — Yeni oturum devri

```text
Yeni oturum. CLAUDE.md, docs/PROGRESS.md ve son 5 commit'i (git log) oku.
Durumu en fazla 5 satırda özetle: hangi fazdayız, ne bitti, ne yarım.
Sonra kaldığımız yerden devam önerini sun. Onayımı almadan kod yazma.
```

---

*UNKNOWNINCOME Prompt Kitabı v1.0 — docs/ altına `PROMPTLAR.md` olarak koy; PROGRESS.md ile birlikte projenin seyir defteridir.*
