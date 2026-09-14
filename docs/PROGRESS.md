# WebKarne — İlerleme

## Mevcut durum
**Son güncelleme:** 14 Eylül 2026 · **Aktif sprint:** Sprint 3 (puanlama → canlı web arayüzü) — **build kapsamı tamamlandı**
**Son oturumda:** Canlı web arayüzü tamamlandı (SSR, Jinja2, vanilya JS). Ana sayfa sorgu panelleri → **her sorguda sıfırdan canlı tarama** (`query.run_live_scan`, e-posta+aktarım; hazır kayıt döndürülmez) + "taranıyor…" ekranı (fetch, JS'siz için `<noscript>` meta-refresh yedeği). Sonuç kapsamı ayrıldı: e-posta araması yalnız e-posta boyutu, alan araması yalnız web boyutları (e-posta hariç). Gerçek ekranlar: Genel Bakış, boyut (akordiyon kontroller, şiddet ikonu + hap, dört ölçüm durumu; satırlar sağ tablodaki sayımla senkron), bulgu tam sayfası (çapa şeridi + scroll-spy), **sektör karşılaştırması** (boyut-bazlı, gerçek dağılım, inline SVG histogram, kurum adı gösterilmez), statik sayfalar (metodoloji/hakkında/açık-veri + sektör yer tutucusu). PDF = tarayıcı yazdırma + print stylesheet. Tümü token tabanlı, tr/en parity.
**Sıradaki iş:** **VPS dağıtımı** (webkarne.com + VPS + DNS hazır) — Sprint 3'ün tek kalan işi, kullanıcı sunucusunda çalıştırılacak. Sonra Sprint 4 (C boyutu: gizlilik/izleme toplayıcısı, Playwright).
**Not:** Bileşik/genel not kararı hâlâ açık (`scoring.toml` + PLAN); sektör karşılaştırması bunu beklemeden boyut-bazlı yapıldı.

## Tamamlananlar
- **Sprint 0** — İskelet, SQLite şeması, `dns_email` toplayıcısı (A boyutu, DANE dâhil), `karne scan`.
- **Sprint 1** — Türkiye örneklemi: 14.766 alan adı, sektör etiketli (`frontier`).
- **Sprint 2** — `karne batch`: paralel, hız-sınırlı, dayanıklı tarama + sabit doğrulayıcı çözümleyiciler (K-11).
- **Sprint 3** — Sürümlü puanlama (A `1.1.0`, B `1.2.0`) + **canlı web arayüzü**: SSR/Jinja2, i18n (tr/en), ana sayfa sorgu → sıfırdan canlı tarama + yükleme ekranı, Genel Bakış/boyut/bulgu/sektör ekranları, statik sayfalar, vanilya JS (akordiyon/kopyala/deep-link/scroll-spy/print), sektör histogramı (inline SVG), yazdırma/PDF. **Kalan: VPS dağıtımı** (kullanıcı sunucusu).

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
- Fix-hint metinleri için tr/en çeviri dosyaları başladı (`karne/web/translations/`, katalogda gösterilen A+B bulguları); kalan bulgu metinleri gerçek ekran oturumlarında tamamlanır.
- Bağımlılık eklendi: `fastapi`, `uvicorn`, `jinja2` (web arayüzü, kullanıcı onaylı).

## Bilinen eksikler
- `2026-10` turunun e-posta verisi henüz puanlanmadı (yalnız transport puanlandı); `2026-09` A-turudur, onun transport verisi yoktur.
- Geçersiz sertifikaların tam alan ayrıştırması ertelendi (`cryptography` gerektirir).
- Ad-hoc taramalar (run_label NULL, ör. webkarne.com) tur-rescore'una girmez.
- C (gizlilik) ve D (teknoloji) boyutları henüz yok (Sprint 4–5); bileşik not yok. Boyut kartlarında "ölçülmedi" olarak dürüstçe gösterilir.
- **VPS dağıtımı yapılmadı** — arayüz yerelde çalışıyor; canlıya çıkış kullanıcı sunucusunda.
- Terim ipucu (tooltip) ve canlı ilerleme çubuğu (§8.1 progress) henüz yok; yükleme ekranı belirsiz göstergedir (sahte adım yok).
- Tasarımdaki bulgu-başına puan etkisi (`−X puan`) veri modelinde yok (`findings`'te delta sütunu yok); puanlayıcının üretmesi gerekir.
- Sektör histogramı yeni bir görselleştirme; ekran-özel tutuldu, `/tr/stil` kataloğuna eklenmedi.

## Geçmiş kayıtlar
→ docs/PROGRESS-ARCHIVE.md
