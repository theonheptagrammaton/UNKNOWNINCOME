# RAPOR — Faz 6: Kendini Geliştirme v1 (WFO re-opt)

Kapsam: `docs/PROJE_DOKUMANI.md` §8.3–8.5 + §15/Faz 6. Durum: **tamam** (2026-07-20).

## Ne yapıldı

### Üretici arayüzü — modüler kendini-geliştirme dikişi (§8.3)
- **`strategy/generator.py`**: `StrategyGenerator` protokolü (`kind`, `propose(GenerationRequest)
  → GenerationResult | None`) + registry. §8.3'ün mimarisi **Üretici → Doğrulayıcı (§6.5) →
  Terfi kapısı (§9.5)**; sistemin geri kalanı bir `StrategyGenerator`'la konuşur, somut mekanizmayla
  değil. "Karar değişince yalnızca üretici değişir."
- **v1 kayıtlı**: `WalkForwardReoptimizer` (`wfo_reopt`). **v2/v3 tanımlı ama boş**:
  `GeneticGenerator` / `RLGenerator` registry'de kayıtlı ama `propose` → `NotImplementedError`
  (sessizce no-op olamazlar). Doküman: "arayüz boş ama tanımlı kalsın" — bugünü bloklamaz.

### WFO re-opt v1 — parametre yenileme + doğrulama (§8.3, §6.5)
- **`strategy/reoptimize.py`**: kurallar sabit, **yalnızca parametreler oynar** (düşük karmaşıklık /
  yüksek açıklanabilirlik — §8.3'ün zorunlu temeli).
  - `tunable_param_space(config)` registry `ParamSpec`'lerini okur → discovery'nin taradığı **aynı uzay**.
  - `reoptimize_params` = seed'li Optuna TPE, `n_jobs=1` — `discovery/optimize.py` ile **birebir**,
    aynı seed → aynı parametre (rule #6). `test_reoptimization_is_deterministic`.
  - `walk_forward_genome` = genome-düzeyi §6.5: `discovery/wfo`'nun `rolling_windows` + `monte_carlo`
    + plato primitifleri **yeniden kullanılır** → re-opt skoru = discovery/backtest skoru.
  - Tümü saf/senkron CPU (DB yok) → Parquet fixture'ıyla birim testli.

### Bozulma tetikleyicileri (§8.5)
- **`strategy/health.py`**: iki tetik — (1) son 30 işlem kayan **PF < 1.0**; (2) gerçekleşen
  drawdown, doğrulama raporunun **Monte Carlo %95 alt bandını** (`p95_max_drawdown`) kırarsa. Saf
  okuma → typed verdict. `test_strategy_health.py` (PF, min-işlem eşiği, MC bandı, sağlıklı).
- **Bot entegrasyonu**: motor bir işlem **kapandığında** izler; degrade → strateji **PAUSE** (mode
  off) + re-opt **kuyruğa** (`reopt_enqueue`, worker arq wire eder; testte None) + Telegram bildirim.

### Orkestrasyon + insan onaylı terfi (§8.5)
- **`strategy/regen.py`**: `regenerate` = producer → validator → `service.add_version(activate=False,
  status="pending_approval")`. **Aktif işaretçi oynamaz** → koşan/paused versiyon yerinde kalır, öneri
  onay kuyruğunda bekler. `pause_for_degradation` = auto-pause + audit + bildirim.
- **`service.approve_version`**: aktif işaretçiyi çevirir (hot-reload) → statü `paper` → mode `paper`
  ("onaylanınca paper'da devreye girer"). `reject_version`: pending → `retired`, aktif dokunulmaz.
- **`pending_approval`** yeni statü; `bot/engine._load_active` bu statüyü atlar (defense-in-depth) —
  aktif işaretçi bir buga rağmen pending'e işaret etse bile işlem üretmez.

### Rejim etiketleme (§8.4)
- **`strategy/regime.py`**: **saf-numpy** ADX (Wilder) + ATR **yüzdelik** → `trend/range × low/high`.
  TA-Lib bağımlılığı yok, deterministik, birim testli. Yüzdelik (mutlak ATR değil) → asset/fiyat-agnostik.
- Her versiyona `regime` etiketi (yeni nullable kolon; create/re-opt'ta best-effort). Bot havuz kapısı
  `KEY_REGIME_LOCK`: `off` (varsayılan, opt-in) · `auto` (canlı rejime uyan) · manuel kilit. **Etiketsiz
  versiyon her zaman uygun** → kapı havuzu asla açlığa düşürmez. `test_regime_gate_filters_pool`.

### Zamanlayıcı + test kancası
- **`strategy/scheduler.py`** `run_scheduled_reopt`: her koşan stratejiyi yeniden optimize eder,
  zaten pending önerisi olanı atlar (çift üretmez). Cron gövdesi importable → kısaltılmış aralıkla
  test. Prod: **haftalık cron (Paz 03:00 UTC)** + `reopt_strategy_job` (degrade kuyruğu).
- **`POST /api/bot/debug/degrade`** (prod'da 404): bozulmayı zorlar → uçtan uca pause + pending + bildirim.

### UI (Trade Deck)
- **Approval queue** kartları: rapor özeti (OOS skoru, MC %95 maxDD, survived §6.5), **parametre diff**,
  **Approve → paper** / **Reject**. Boşken sessiz.
- Strateji kartında **rejim etiketi** + **Re-optimize** ve **Simulate degrade** düğmeleri. Settings'te
  **rejim kilidi** şalteri (off/auto/trend/range/…). Status şeridi "Regime" = aktif kilit modu.

## Kabul kriterleri — kanıt

| Kriter | Kanıt |
|---|---|
| Bozulma simülasyonu → strateji otomatik pause | `test_degradation_pauses_and_drops_pending_version` (mode off) + HTTP `test_debug_degrade_pauses_and_queues_pending` |
| Yeni versiyon raporuyla onaya düşer | pending `wfo_report` (OOS+MC+plato) taşır; `GET /strategies/pending` diff'li kuyruk; approve→paper / reject→retired testli |
| **Onaylanmamış versiyon asla işlem üretmez** | `test_unapproved_version_never_trades` — `activate=False` işaretçi oynatmaz + `pending_approval` statü guard (defense-in-depth) |
| Zamanlayıcı çalışır (kısaltılmış) | `test_scheduler_produces_pending_versions` (üretir + çift üretmez); prod haftalık cron |
| Üretici arayüzü modüler, v2/v3 tanımlı-boş | `test_generator_registry_seam` (wfo_reopt callable; genetic/rl → NotImplementedError; bilinmeyen → KeyError) |
| Re-opt deterministik (rule #6) | `test_reoptimization_is_deterministic` (aynı seed → aynı parametre) |
| Rejim kapısı havuzu filtreler | `test_regime_gate_filters_pool` + `test_unlabelled_and_off_lock_always_run` |

Toplam: **pytest 184/184** (29 yeni), ruff temiz, `next build` başarılı (/trade 7.37 kB),
tsc + eslint temiz.

## Açık kararlar (kullanıcı onaylı, §16 varsayılanlarıyla uyumlu)
1. **Üretici modüler arayüz arkasında** — v1 = WFO re-opt (zorunlu temel); genetic (v2) / RL (v3)
   tanımlı-boş. Mekanizma değişince tek nokta değişir.
2. **Onaylanmamış versiyon teknik olarak işlem yolundan dışlanır** — `activate=False` (aktif işaretçi
   oynamaz) + motor statü guard'ı; testle kanıtlı.
3. **Rejim kapısı varsayılan `off` (opt-in)** — koşan paper botunu/soak'ı bozmaz; "manuel kilit her
   zaman mümkün" (§8.4). `auto` + manuel kilit mevcut ve testli.
4. **Re-opt: degrade → worker job (kuyruk), haftalık → cron, manuel → senkron API.** Genetik üretici
   (v2) ve gerçek haftalık cron tetiği operatör/gelecek fazına bırakıldı.

## Yerel doğrulama (operatör)
```bash
python -m app.data.cli devseed --symbols BTCUSDT --tf 1h --bars 600   # SENTETİK
docker compose up --build                                            # 5 servis + bot loop
# /trade → strateji kartında "Simulate degrade" → strateji PAUSE + Approval queue'da yeni versiyon
#          (rapor + parametre diff) → "Approve → paper" → paper'da devreye girer
# Settings → Regime gate şalteri (off/auto/manuel) → status şeridinde "Regime"
```
Not: `devseed` verisi SENTETİKTİR. `debug/degrade` yalnızca `APP_ENV != production` iken açıktır.
Haftalık cron (Paz 03:00 UTC) + degrade kuyruğu worker'da; Telegram bildirimi token yapılandırılınca.
