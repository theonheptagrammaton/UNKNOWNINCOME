# UNKNOWNINCOME — İlerleme Takibi (PROGRESS)

Fazlar ve kabul kriterleri: `docs/PROJE_DOKUMANI.md` §15. Kabul kriterleri geçilmeden sonraki faza başlanmaz.

**Durum lejantı:** `[ ]` başlamadı · `[~]` devam ediyor · `[x]` tamamlandı (kabul kriterleri kanıtlı)

---

## Faz 0 — İskelet ve Altyapı
- [~] **Kapsam:** Depo yapısı (§3.3), docker-compose (5 servis), FastAPI + Next.js merhaba-dünya, pytest + lint CI, `/api/health`.
- **Kabul kriterleri:**
  - [ ] `docker compose up` ile tüm servisler ayakta
  - [ ] `/api/health` 200 döner
  - [ ] Testler yeşil (pytest + lint CI)
- **Durum:** `[~]` Repo bootstrap edildi (git, .gitignore, .env.example, docs, README). Servis iskeleti bekliyor.

## Faz 1 — Veri Katmanı
- [ ] **Kapsam:** ccxt/Binance USDT-M OHLCV + funding indirici, Parquet store + DuckDB, gap tespit/onarım, sync cron, `candle_sync_state`, dinamik evren + tarihli snapshot (§4.5).
- **Kabul kriterleri:**
  - [ ] Evren kurucu top-30 listesi + tarihli snapshot üretir
  - [ ] 10 sembol × 6 TF × 24 ay + funding serileri yüklü
  - [ ] Bütünlük testi gap=0
  - [ ] Tipik DuckDB sorgusu < 1 sn
- **Durum:** `[ ]` başlamadı

## Faz 2 — İndikatör Registry
- [ ] **Kapsam:** TA-Lib + pandas-ta birleşik registry (200+), sinyal primitifleri (§5.4), hesap + Parquet cache, custom eklenti yükleyici.
- **Kabul kriterleri:**
  - [ ] Tüm indikatörler örnek sembolde hatasız hesaplanır
  - [ ] ≥ 10 çekirdek indikatör bilinen referans değerlerle birim testinden geçer
  - [ ] Cache isabeti loglanır
- **Durum:** `[ ]` başlamadı

## Faz 3 — Backtest Çekirdeği + Backtest Lab v1 (manuel mod)
- [ ] **Kapsam:** vectorbt sarmalayıcı, maliyet modeli, tam metrik seti, `backtest_runs`; UI: manuel kurucu, koşu detayı (equity, DD, işlem listesi, mum+işaretler).
- **Kabul kriterleri:**
  - [ ] EMA9×EMA21 referans stratejisi elle hesaplanmış sonuçla eşleşir
  - [ ] Lookahead testi (sinyali 1 bar kaydırınca sonuç değişmeli) geçer
  - [ ] UI'dan uçtan uca koşu yapılır
- **Durum:** `[ ]` başlamadı

## Faz 4 — Otomatik Keşif Pipeline'ı
- [ ] **Kapsam:** Aşama 0–6 (§7), Optuna entegrasyonu, WFO motoru (§6.5), liderlik tablosu UI, backtesting.py finalist doğrulaması.
- **Kabul kriterleri:**
  - [ ] 10 sembol × 4 TF standart tarama < 2 saat
  - [ ] Aynı seed → aynı sıralama (bit-for-bit)
  - [ ] İki motor uyuşmazlığı alarm üretir
- **Durum:** `[ ]` başlamadı

## Faz 5 — Strateji Motoru + Paper Trading + Trade Deck
- [ ] **Kapsam:** Genome + sürümleme (§8.1), üç katmanlı düzenleme (§8.6), paper doldurma simülatörü, risk katmanı (§9.4), mod şalteri (§9.6), kill switch (4 kanal), sinyal akışı + karar günlüğü UI, Telegram bildirim + komut seti (§10.3).
- **Kabul kriterleri:**
  - [ ] Paper bot 72 saat kesintisiz koşar
  - [ ] Her sinyalde `reason` + `indicator_snapshot` dolu
  - [ ] Kill switch dört kanaldan da botu < 2 sn'de durdurur
  - [ ] Telegram'dan mod geçişi çalışır
  - [ ] Genome hot-reload restart'sız devreye girer
  - [ ] Risk limit ihlali simülasyonu emirleri bloklar
- **Durum:** `[ ]` başlamadı

## Faz 6 — Kendini Geliştirme v1
- [ ] **Kapsam:** Haftalık WFO re-opt zamanlayıcısı, bozulma tetikleyicileri (§8.5), yeni versiyon üretimi + insan onaylı terfi akışı, rejim etiketleme (§8.4).
- **Kabul kriterleri:**
  - [ ] Bozulma senaryosu simülasyonunda strateji otomatik pause olur
  - [ ] Yeni versiyon raporuyla birlikte onaya düşer
- **Durum:** `[ ]` başlamadı

## Faz 7 — Canlı Yürütme (kapının arkasında)
- [ ] **Kapsam:** Binance USDT-M futures adaptörü (isolated marj, kaldıraç tavanı, likidasyon tamponu), terfi kapısı (§9.5), mikro sermaye ile kontrollü açılış, canlı-paper sapma izleme.
- **Kabul kriterleri:**
  - [ ] Kapı eşiği sağlanmadan canlı emir yolunun çağrılamadığı testle kanıtlanır
  - [ ] İlk canlı işlemler mikro boyutta ve tam loglu gerçekleşir
- **Durum:** `[ ]` başlamadı

---

### Açık kararlar (doküman §16.2) — geliştirmeyi bloklamaz
| # | Karar | Bloklamayan varsayılan |
|---|---|---|
| 1 | İlk canlı piyasa cephesi | Binance USDT-M (testnet) |
| 2 | Kendini geliştirme mekanizması | v1: WFO re-opt |
| 3 | Piyasa verisi deposu | Parquet + DuckDB |
| 4 | Pozisyon boyutlama | ATR tabanlı |
