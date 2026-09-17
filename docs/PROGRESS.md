# WebKarne — İlerleme

## Mevcut durum
**Son güncelleme:** 17 Eylül 2026 · **Aktif sprint:** Sprint 4 (C boyutu — gizlilik/izleme, Playwright) — **başlamadı**
**Son oturumda:** Sprint 3 **kapandı**. Açık kararlar kapatıldı (PLAN K-14, K-15) ve araç **canlıya çıktı: https://webkarne.com**. Web sorgusu kötüye kullanım koruması (bekleme süresi + eşzamanlılık sınırı + Cloudflare hız sınırı), CSP'yi bozacak inline script `app.js`'e taşındı, UA `WebKarne/1.0 (+https://webkarne.com/tr/hakkinda; …)`. Kod açık: https://github.com/ysfylcnky/webkarne. Öz-ölçüm: webkarne.com e-posta **A 88,2**, aktarım **A 100**.
**Sıradaki iş:** Sprint 4 · Oturum 1 — Playwright bağımlılığı için **kullanıcı onayı**, sonra `web_privacy` toplayıcısının iskeleti + beklenen çıktının elle yazılması (üç onay durumu, K-06). Bir oturum, bir modül.

## Tamamlananlar
- **Sprint 0** — İskelet, SQLite şeması, `dns_email` toplayıcısı (A boyutu, DANE dâhil), `karne scan`.
- **Sprint 1** — Türkiye örneklemi: 14.766 alan adı, sektör etiketli (`frontier`).
- **Sprint 2** — `karne batch`: paralel, hız-sınırlı, dayanıklı tarama + sabit doğrulayıcı çözümleyiciler (K-11).
- **Sprint 3** — Sürümlü puanlama (A, B; ruleset `1.2.0`) + canlı web arayüzü (SSR/Jinja2, tr/en, sorgu → canlı tarama, Genel Bakış/boyut/bulgu/sektör, PDF) + **VPS dağıtımı** (Ubuntu 24.04, Caddy, systemd, Cloudflare; günlük yedek).

## Çalışan komutlar
- `karne scan <alan>` — tek alan adı tarar (A ve/veya B), ham sonucu saklar. `--collectors email,transport` · `--json` · `--no-store`.
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

## Bilinen eksikler
- C (gizlilik) ve D (teknoloji) boyutları yok (Sprint 4–5); arayüzde "ölçülmedi".
- Sunucuya uzaktan erişim: SSH anahtarı parolalı → kullanıcı anahtarı süreli ssh-agent'a yükler; `sudo` parolalı → sudo adımlarını kullanıcı çalıştırır.
- Geçersiz sertifikaların tam alan ayrıştırması ertelendi (`cryptography` gerektirir).
- Tasarımdaki bulgu-başına puan etkisi (`−X puan`) veri modelinde yok; terim ipucu ve canlı ilerleme çubuğu yok.
- DKIM seçici listesi Cloudflare'in `cf2024-1`'ini içermiyor (yöntem sınırlılığı; liste değişikliği `config_hash`'i değiştirir, tur arasında yapılmalı).

## Geçmiş kayıtlar
→ docs/PROGRESS-ARCHIVE.md
