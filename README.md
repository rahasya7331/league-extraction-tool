<div align="center">

# 🎴 Rahasya Extraction Tool

**League of Legends skinlerini `.fantome` mod dosyasına çeviren interaktif araç.**  
CS (cslol-manager) ile direkt kullanılabilir.

[![kick](https://img.shields.io/badge/kick-rahasya-53FC18?style=for-the-badge&logo=kick&logoColor=white)](https://kick.com/rahasya)
[![python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![license](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

</div>

---

## ✨ Özellikler

- 🎴 Tüm champion skinlerini listeler — chromalar ve formlar dahil
- 🎨 Her chromanın rengini terminal'de renkli blok olarak gösterir
- 🖼️ Skin ismine Ctrl+Click ile CDragon splash art açılır
- 📁 `.fantome` dosyaları direkt seçilen klasöre çıkar
- ⚡ Hash'ler ilk çalıştırmada indirilir, sonraki açılışlar önbellekten hızlı yüklenir
- 🔧 Eksik bağımlılıklar ve LtMAO ilk açılışta otomatik kurulur

---

## 📋 Gereksinimler

| Gereksinim | Notlar |
|---|---|
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) — kurulumda **"Add to PATH"** seçeneğini işaretle |
| **Git** | [git-scm.com](https://git-scm.com/downloads) — LtMAO otomatik kurulumu için gerekli |
| **League of Legends** | Kurulu olması yeterli, açık olmasına gerek yok |

---

## 🚀 Kurulum

### 1. Repoyu indir

```bash
git clone https://github.com/rahasya7331/league-extraction-tool
cd league-extraction-tool
```

Ya da sağ üstten **Code → Download ZIP** ile indirip bir klasöre çıkar.

### 2. Çalıştır

```bash
python build.py
```

İlk açılışta tool şunları otomatik yapar:
- `requests`, `pyzstd`, `xxhash` paketlerini pip ile kurar (zaten kuruluysa atlar)
- LtMAO'yu `_vendor/` klasörüne indirir (onay ister)
- Hash dosyalarını CDragon'dan çeker (~1-2 dk, bir kez)

Sonraki açılışlarda bunların hiçbiri tekrarlanmaz.

---

## 🎮 Kullanım

Tool açıldığında bu menü gelir:

```
╔══════════════════════════════════════╗
║   RAHASYA EXTRACTION TOOL  v2       ║
╠══════════════════════════════════════╣
║  [1] Champion Sec & Build            ║
║  [2] Ayarlar                         ║
║  [3] Hash Yenile                     ║
║  [4] Cikis                           ║
╚══════════════════════════════════════╝
```

**Adım adım:**

1. **`[1]`** → Champion adı gir (örn: `Ahri`, `Zed`, `Katarina`)
2. Skin listesi açılır — her skin yanında renk bloğu ve türü gösterilir
3. Ctrl+Click ile skin ismesine tıklayarak CDragon'dan splash art önizleyebilirsin
4. Seçim yap:

| Giriş | Anlamı |
|---|---|
| `3` | Sadece 3. skin |
| `1,3,5` | 1, 3 ve 5. skinler |
| `2-6` | 2'den 6'ya kadar hepsi |
| Son numara | Champion'ın tüm skinleri |

5. `.fantome` dosyaları seçilen klasöre kaydedilir (varsayılan: masaüstü/Extracted)

---

## 📁 Çıktı formatı

```
Extracted/
├── Foxfire Ahri.fantome
├── Star Guardian Ahri.fantome
├── Star Guardian Ahri - Ruby.fantome       ← chroma
└── Star Guardian Ahri - Sapphire.fantome   ← chroma
```

`.fantome` dosyalarını cslol-manager veya League Toolkit ile yükleyebilirsin.

---

## ⚙️ Ayarlar

League of Legends farklı bir yolda kuruluysa:

```
Menü [2] → Ayarlar → League Path'i değiştir
```

Varsayılan yol: `C:\Riot Games\League of Legends`

---

## ❓ SSS

<details>
<summary><b>Git kurulu değil, LtMAO nasıl kuracağım?</b></summary>

[git-scm.com](https://git-scm.com/downloads) adresinden Git'i kur, ardından `python build.py` çalıştır. Tool LtMAO'yu otomatik indirir.

</details>

<details>
<summary><b>Hash indirmesi çok uzun sürüyor?</b></summary>

İlk açılışta normaldir (~1-2 dakika). Bir kez indirildikten sonra önbelleğe alınır, bir daha indirilmez.

</details>

<details>
<summary><b>"Champions dir not found" hatası aldım?</b></summary>

Menü `[2]` → Ayarlar'dan League of Legends'ın kurulu olduğu klasörü doğru gir.

</details>

<details>
<summary><b>Champion seçince "Skin bulunamadı" hatası alıyorum?</b></summary>

League kurulum yolunun doğru olduğunu kontrol et. Menü `[2]` → Ayarlar → League Path'i düzenle. Yol `...\League of Legends` klasörüne işaret etmeli, içindeki alt klasörlere değil.

</details>

<details>
<summary><b>Ctrl+Click splash art açılmıyor?</b></summary>

Ctrl+Click terminal hyperlink desteği gerektirir. Windows Terminal ve modern PowerShell destekler, eski cmd.exe desteklemez. Windows Terminal kullanmanı öneririz.

</details>

<details>
<summary><b>Skin extract ettim ama oyunda çalışmıyor?</b></summary>

`.fantome` dosyasını cslol-manager veya League Toolkit üzerinden yüklemelisin. Dosyaya çift tıklamak çalıştırmaz.

</details>

<details>
<summary><b>Chromalar neden ayrı dosya olarak çıkıyor?</b></summary>

Her chroma ayrı bir bin-swap gerektirdiği için ayrı `.fantome` olarak extract edilir. Ana skini + istediğin chromayı ayrı ayrı yüklersin.

</details>

---

## 🙏 Credits & Teşekkürler

Bu proje **[bettie9/league-skin-fantome-builder](https://github.com/bettie9/league-skin-fantome-builder)** reposundan ilham alınarak geliştirilmiştir.

| Özellik | Orijinal | Bu Tool |
|---|---|---|
| İnteraktif menü (champion & skin seçimi) | ❌ | ✅ |
| Chroma renk tespiti + renkli blok gösterimi | ❌ | ✅ |
| CDragon splash art önizleme (Ctrl+Click) | ❌ | ✅ |
| Türkçe arayüz | ❌ | ✅ |
| Chroma & form skinleri ayrı `.fantome` | ❌ | ✅ |
| Tek champion odaklı, temiz çıktı klasörü | ❌ | ✅ |
| Aralık seçimi (`2-6`) | ❌ | ✅ |
| Otomatik bağımlılık kurulumu | ❌ | ✅ |
| Locale WAD filtreleme (`en_US` vb.) | ❌ | ✅ |

**Kullanılan kütüphaneler:**
- [LtMAO](https://github.com/GuiSaiUwU/LtMAO) — WAD okuma & BIN bin-swap motoru
- [CommunityDragon](https://communitydragon.org) — skin kataloğu, hash verileri & splash art
- [Riot DataDragon](https://developer.riotgames.com) — champion & skin ID'leri

---

<div align="center">

Made with ❤️ by **[kick.com/rahasya](https://kick.com/rahasya)**

</div>
