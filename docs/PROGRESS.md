# WebKarne — İlerleme

## Mevcut durum
**Son güncelleme:** 12 Eylül 2026 · **Aktif sprint:** Sprint 3 (puanlama → canlı web arayüzü)
**Son oturumda:** B boyutu (aktarım) skorlayıcısı tamamlandı (ruleset `1.2.0`); tüm frame `2026-10` turunda email+transport ile tarandı (14.735 ok / 0 hata) ve transport puanlaması koşuldu → Türkiye geneli aktarım not dağılımı: A=935 · B=3571 · C=6991 · D=1548 · F=303 · I=1417.
**Sıradaki iş:** Web arayüzü — Jinja2 SSR base şablon + analiz kabuğu + i18n altyapısı + `/tr/stil` bileşen kataloğu. Tümü `docs/DESIGN-SYSTEM.md`'ye tabi; `karne/web/static/tokens.css` dışında ham değer yazılmaz.

## Tamamlananlar
- **Sprint 0** — İskelet, SQLite şeması, `dns_email` toplayıcısı (A boyutu, DANE dâhil), `karne scan`.
- **Sprint 1** — Türkiye örneklemi: 14.766 alan adı, sektör etiketli (`frontier`).
- **Sprint 2** — `karne batch`: paralel, hız-sınırlı, dayanıklı tarama + sabit doğrulayıcı çözümleyiciler (K-11).
- **Sprint 3 (kısmi)** — Sürümlü puanlama (`scoring.toml` + `karne rescore`): A boyutu `1.1.0`, B boyutu (TLS/HTTP toplayıcı + skorlayıcı) `1.2.0`. Bulgu #1 (e-posta karnesi) üretildi, B tüm frame'e uygulandı. **Kod commit bekliyor** (Sprint 3 sonunda, kullanıcı talimatı).

## Çalışan komutlar
- `karne scan <alan>` — tek alan adı tarar (A ve/veya B), ham sonucu saklar. `--collectors email,transport` · `--json` · `--no-store`.
- `karne frontier --list-id <id>` — Tranco + `.tr`'den örneklemi kurar, `domains` tablosuna yazar.
- `karne batch --run-label <YYYY-MM>` — tüm frame'i tarar; dayanıklı/resume. `--collectors` · `--sector` · `--limit` · `--concurrency` · `--dry-run`.
- `karne rescore --dimension email|transport` — ham veriden puan/bulgu türetir; sürümlü, yeniden çalıştırılabilir (ham veriye dokunmaz). `--run-label` · `--scan-id` · `--only-unscored` · `--dry-run`.

## Veri durumu
- **DB:** `data/karne.db` (~723 MB, gitignored). **Alan adı:** 14.768 kayıtlı.
- **Taramalar:** 29.547 — `2026-09` A-turu (14.767) · `2026-10` A+B turu (14.768) · ad-hoc (12). Tarih aralığı 10–12 Eylül 2026.
- **Ham sonuç:** 44.312 — `dns_email` 29.547 · `tls_http` 14.765.
- **Puanlar:** email `1.1.0` = 14.767 · transport `1.2.0` = 14.765. **Bulgular:** 150.952.
- **Örneklem:** Türkiye — tüm `.tr` (Tranco alt kümesi) + seçili Türk `.com`; sektör etiketli (banka, üniversite, kamu, belediye, hastane, e-ticaret, medya).

## Açık kararlar
- Aylık cron (K-09) kurulmadı — açılmadan önce tartışılacak.
- Bulgu #1 grafikleri matplotlib/pandas bağımlılığı gerektirir — eklenmeden önce sorulacak.
- Fix-hint metinleri için tr/en çeviri dosyaları henüz yok — web sprintinde başlıyor.

## Bilinen eksikler
- `2026-10` turunun e-posta verisi henüz puanlanmadı (yalnız transport puanlandı); `2026-09` A-turudur, onun transport verisi yoktur.
- Geçersiz sertifikaların tam alan ayrıştırması ertelendi (`cryptography` gerektirir).
- Ad-hoc taramalar (run_label NULL, ör. webkarne.com) tur-rescore'una girmez.
- C (gizlilik) ve D (teknoloji) boyutları henüz yok (Sprint 4–5); bileşik not yok.
- Web arayüzü henüz yok — `karne/web/` içinde yalnızca `tokens.css` var.

## Geçmiş kayıtlar
→ docs/PROGRESS-ARCHIVE.md
