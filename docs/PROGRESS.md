# WebKarne — İlerleme

## Mevcut durum
**Son güncelleme:** 17 Eylül 2026 · **Aktif sprint:** Sprint 4 (C boyutu — gizlilik/izleme, Playwright) — **Oturum 2 bitti**
**Son oturumda:** Onay arayüzü gözlemi + **reddet (rejected)** durumu (`web_privacy` 0.2.0). Kararlar PLAN **K-16 eki**'nde: 40 Türk sitesinde headless ~%30 engellendi (e-ticarette yığılı) → **pencereli, ekran dışı Chromium** (UA sahtelenmez); CMP imzaları + TR/EN etiket kuralları `[web_privacy.consent]`'te (OneTrust, Cookiebot, Didomi, yerli **Efilli**…); yalnız ilk katmandaki **görünür** reddet (yalnızca-zorunlu dâhil, ayrı kural kimliği) bir kez tıklanır → 15 sn gözlem → ana sayfa bir kez yeniden yüklenir → 15 sn gözlem; istekler `t_ms`+faz, çerez/storage faz başına anlık görüntü. Canlı beklentiler (vodafone: OneTrust'ta metin içi "Reddet"; yapıkredi: özel banner; akbank: Efilli, shadow DOM, div düğmeler) panelden bağımsız gözlemle yazıldı, ilk koşuda geçti.
**Sıradaki iş:** Sprint 4 · Oturum 3 — **kabul (accepted)** durumu (aynı protokol, banner'ın kendi kabul düğmesi) + önceden işaretli kutu gözlemi. Bir oturum, bir modül.

## Tamamlananlar
- **Sprint 0** — İskelet, SQLite şeması, `dns_email` toplayıcısı (A boyutu, DANE dâhil), `karne scan`.
- **Sprint 1** — Türkiye örneklemi: 14.766 alan adı, sektör etiketli (`frontier`).
- **Sprint 2** — `karne batch`: paralel, hız-sınırlı, dayanıklı tarama + sabit doğrulayıcı çözümleyiciler (K-11).
- **Sprint 3** — Sürümlü puanlama (A, B; ruleset `1.2.0`) + canlı web arayüzü (SSR/Jinja2, tr/en, sorgu → canlı tarama, Genel Bakış/boyut/bulgu/sektör, PDF) + **VPS dağıtımı** (Ubuntu 24.04, Caddy, systemd, Cloudflare; günlük yedek).

## Çalışan komutlar
- `karne scan <alan>` — tek alan adı tarar (A ve/veya B), ham sonucu saklar. `--collectors email,transport` · `--json` · `--no-store`.
- `karne scan <alan> --collectors privacy` — C boyutu, gerçek Chromium, yalnız yerelde (`uv sync --group analysis --group privacy` + `uv run playwright install chromium`).
- `karne frontier --list-id <id>` — Tranco + `.tr`'den örneklemi kurar.
- `karne batch --run-label <YYYY-MM>` — tüm frame'i tarar; dayanıklı/resume.
- `karne rescore --dimension email|transport` — ham veriden sürümlü puan/bulgu (ham veriye dokunmaz).
- `scripts/monthly_round.ps1 [-RunLabel YYYY-MM]` — aylık tur (yerelde, elle; K-14).
- `scripts/db_snapshot.py <src> <dst>` — tutarlı DB kopyası. Sunucu güncelleme: `sudo bash ~/webkarne/deploy/deploy.sh` (bkz. `docs/DEPLOY.md`).

## Veri durumu
- **Yerel DB (kanonik):** `data/karne.db` (~723 MB). **Alan adı:** 14.768. **Taramalar:** 29.575 — `2026-09` A-turu · `2026-10` A+B turu · ad-hoc.
- **Puanlar:** `2026-10` artık e-posta **ve** aktarım puanlı (e-posta: A 2 · B 71 · C 752 · D 2.829 · F 10.523 · I 591).
- **Sunucu DB (türetilmiş):** 2026-09-17 kopyası + web sorguları (`run_label` NULL); teze girmez (K-14).

## Açık kararlar
- Aylık tur **Kasım'ın ilk haftası** başlar (K-09) — betik hazır, elle çalıştırılacak.
- STARTTLS kapsam dışı (§4); bileşik not F boyutunda (K-15).
- İzleyici veri seti (host → şirket/ülke) seçimi ertelendi (K-16); C'nin batch/web'e bağlanması ayrı karar.
- webkarne.com'un kendisi: Google Fonts (yurt dışı üçüncü taraf) ve CSP'nin engellediği, işlevsiz Cloudflare Web Analytics — ne yapılacağı kararı kullanıcıda.

## Bilinen eksikler
- C boyutu `untouched` + `rejected`; `accepted` yok, puanlaması yok; D yok (Sprint 5); arayüzde "ölçülmedi".
- C sınırlılıkları: pencereli modda bile hepsiburada, pegasus, yemeksepeti, arçelik, beko, THY engelliyor; Chromium sistem resolver'ını kullanır (K-11 değil); storage anahtarları yalnız üst çerçeveden; kapalı shadow DOM ve ikinci katman görülmez; bir durum ~60–80 sn (alan adı başına ~2,5 dk).
- `web/reports.latest_scan_id` toplayıcıya bakmıyor: yerel DB'deki yalnız-C taraması sunucuya kopyalanırsa A/B'yi gizler — kopyadan/web bağlamadan önce çözülmeli.
- Yeni `[web_privacy]` bölümü tüm taramaların `config_hash`'ini değiştirdi (Kasım turu tutarlı kalır).
- Sunucuya uzaktan erişim: SSH anahtarı parolalı → kullanıcı anahtarı süreli ssh-agent'a yükler; `sudo` parolalı → sudo adımlarını kullanıcı çalıştırır.
- Geçersiz sertifikaların tam alan ayrıştırması ertelendi (`cryptography` gerektirir).
- Tasarımdaki bulgu-başına puan etkisi (`−X puan`) veri modelinde yok; terim ipucu ve canlı ilerleme çubuğu yok.
- DKIM seçici listesi Cloudflare'in `cf2024-1`'ini içermiyor (yöntem sınırlılığı; liste değişikliği `config_hash`'i değiştirir, tur arasında yapılmalı).

## Geçmiş kayıtlar
→ docs/PROGRESS-ARCHIVE.md
