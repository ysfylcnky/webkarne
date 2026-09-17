# WebKarne — İlerleme

## Mevcut durum
**Son güncelleme:** 17 Eylül 2026 · **Aktif sprint:** Sprint 4 (C boyutu — gizlilik/izleme, Playwright) — **Oturum 1 bitti**
**Son oturumda:** `web_privacy` toplayıcısının iskeleti + **dokunmadan (untouched)** onay durumu. Kararlar PLAN **K-16**'da: Playwright ayrı `privacy` grubunda (sunucuya kurulmaz), tek scan içinde `states{}` (reddet/kabul şimdilik `not_run`), ayrı ölçüm-sonucu durumları (loaded/http_error/blocked/timeout/dns_error/navigation_error/browser_error), çerez/storage **değeri yok**, istekler tam URL (2048'de kesilir), taraf ayrımı ve izleyici eşleştirme analiz katmanında, UA = Chromium UA + WebKarne eki. Yalnız `karne scan --collectors privacy`; batch reddeder, web görmez. Beklenen çıktı (webkarne.com, mumifashion.com) canlıda doğrulandı; webkarne.com'da CSP'nin engellediği Cloudflare Web Analytics beacon'ı bu sayede bulundu.
**Sıradaki iş:** Sprint 4 · Oturum 2 — onay banner'ı gözlemi + **reddet** durumu (yalnız banner'ın kendi reddet düğmesi; K-06/K-07). Bir oturum, bir modül.

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
- C boyutu yalnız `untouched` durumunda, puanlaması yok; D yok (Sprint 5); arayüzde "ölçülmedi".
- C sınırlılıkları: headless UA `HeadlessChrome` içeriyor (bot algısı olası); Chromium sistem resolver'ını kullanır (K-11 değil); storage anahtarları yalnız üst çerçeveden.
- `web/reports.latest_scan_id` toplayıcıya bakmıyor: yerel DB'deki yalnız-C taraması sunucuya kopyalanırsa A/B'yi gizler — kopyadan/web bağlamadan önce çözülmeli.
- Yeni `[web_privacy]` bölümü tüm taramaların `config_hash`'ini değiştirdi (Kasım turu tutarlı kalır).
- Sunucuya uzaktan erişim: SSH anahtarı parolalı → kullanıcı anahtarı süreli ssh-agent'a yükler; `sudo` parolalı → sudo adımlarını kullanıcı çalıştırır.
- Geçersiz sertifikaların tam alan ayrıştırması ertelendi (`cryptography` gerektirir).
- Tasarımdaki bulgu-başına puan etkisi (`−X puan`) veri modelinde yok; terim ipucu ve canlı ilerleme çubuğu yok.
- DKIM seçici listesi Cloudflare'in `cf2024-1`'ini içermiyor (yöntem sınırlılığı; liste değişikliği `config_hash`'i değiştirir, tur arasında yapılmalı).

## Geçmiş kayıtlar
→ docs/PROGRESS-ARCHIVE.md
