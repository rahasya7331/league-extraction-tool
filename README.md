<div align="center">

# 🎴 Rahasya Extraction Tool

**League of Legends skinlerini `.fantome` mod dosyasına çeviren interaktif araç.**


</div>

***

## ✨ Özellikler

- 🎴 Tüm champion skinlerini listeler — chromalar ve formlar dahil
- 🎨 Her chromanın rengini terminal'de renkli blok olarak gösterir
- 🔗 Skin ismine Ctrl+Click ile LolValue sayfası açılır
- 📁 `.fantome` dosyaları direkt seçilen klasöre çıkar, alt klasör açılmaz
- ⚡ Hash'ler ilk çalıştırmada indirilir, sonraki açılışlar önbellekten hızlı yüklenir

***

## 📋 Gereksinimler

| Gereksinim | Notlar |
|---|---|
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) — kurulumda **"Add to PATH"** seçeneğini işaretle |
| **League of Legends** | Kurulu olması yeterli, açık olmasına gerek yok |

***

## 🚀 Kurulum

### 1. Repoyu indir

```bash
git clone https://github.com/rahasya/RahasyaExtractionTool
cd RahasyaExtractionTool
```

### 2. LtMAO'yu kur (tek seferlik)

```bash
git clone --depth=1 https://github.com/GuiSaiUwU/LtMAO _vendor/LtMAO
```

### 3. Çalıştır

```bash
python build.py
```

> İlk açılışta hash dosyaları indirilir (~1-2 dk). Sonraki açılışlarda önbellekten yüklenir, çok daha hızlı başlar.

***

## 🎮 Kullanım

Tool açıldığında bu menü gelir:

```
╔══════════════════════════════════════════╗
║   RAHASYA EXTRACTION TOOL  v2           ║
╠══════════════════════════════════════════╣
║  [1] Champion Seç & Build               ║
║  [2] Ayarlar                            ║
║  [3] Hash Yenile                        ║
║  [4] Çıkış                              ║
╚══════════════════════════════════════════╝
```

**Adım adım:**

1. **`[1]`** → Champion adı gir (örn: `Ahri`, `Zed`, `Elise`)
2. Skin listesi açılır, her skin yanında renk bloğu ve türü gösterilir
3. Seçim yap:

| Giriş | Anlamı |
|---|---|
| `3` | Sadece 3. skin |
| `1,3,5` | 1, 3 ve 5. skinler |
| `2-6` | 2'den 6'ya kadar hepsi |
| Son numara | Champion'ın tüm skinleri |

4. `.fantome` dosyaları masaüstüne kaydedilir:

```
C:\Users\<KullanıcıAdın>\Desktop\Extracted\
```

***

## 📁 Çıktı formatı

```
Extracted/
├── Foxfire Ahri.fantome
├── Star Guardian Ahri.fantome
├── Star Guardian Ahri - Ruby.fantome       ← chroma
└── Star Guardian Ahri - Sapphire.fantome   ← chroma
```

`.fantome` dosyalarını [**cslol-manager**] veya [**League Toolkit**] ile yükleyebilirsin.

***

## ⚙️ Ayarlar

League of Legends farklı bir yolda kuruluysa:

```
Menü [2] → Ayarlar → League Path'i değiştir
```

Varsayılan yol:
```
C:\Riot Games\League of Legends
```

***

## ❓ SSS

<details>
<summary><b>Hash indirmesi çok uzun sürüyor?</b></summary>

İlk açılışta normaldir. Bir kez indirildikten sonra önbelleğe alınır, bir daha indirilmez.

</details>

<details>
<summary><b>"Champions dir not found" hatası aldım?</b></summary>

Menü `[2]` → Ayarlar'dan League of Legends'ın kurulu olduğu klasörü doğru gir.

</details>

<details>
<summary><b>Skin extract ettim ama oyunda çalışmıyor?</b></summary>

`.fantome` dosyasını tercih ettiğin mod manager (cslol, League Toolkit vb.) üzerinden yüklemelisin. Direkt dosyaya çift tıklamak çalıştırmaz.

</details>

<details>
<summary><b>Chromalar neden ayrı dosya olarak çıkıyor?</b></summary>

Her chroma ayrı bir bin-swap gerektirdiği için ayrı `.fantome` olarak extract edilir. Ana skini + istediğin chromayı ayrı ayrı yüklersin.

</details>

***

## 🙏 Credits & Teşekkürler

Bu proje **[bettie9/league-skin-fantome-builder](https://github.com/bettie9/league-skin-fantome-builder)** reposundan ilham alınarak geliştirilmiştir. Orijinal bin-swap mantığı temel alınmış, üzerine interaktif arayüz ve ek özellikler eklenmiştir.

| Özellik | Orijinal | Bu Tool |
|---|---|---|
| İnteraktif menü (champion & skin seçimi) | ❌ | ✅ |
| Chroma renk tespiti + renkli blok gösterimi | ❌ | ✅ |
| LolValue linki (Ctrl+Click) | ❌ | ✅ |
| Türkçe arayüz | ❌ | ✅ |
| Chroma & form skinleri ayrı `.fantome` | ❌ | ✅ |
| Tek champion odaklı, temiz çıktı klasörü | ❌ | ✅ |
| Aralık seçimi (`2-6`) | ❌ | ✅ |

**Kullanılan kütüphaneler:**
- [LtMAO](https://github.com/GuiSaiUwU/LtMAO) — WAD okuma & BIN bin-swap motoru
- [CommunityDragon](https://communitydragon.org) — skin kataloğu & hash verileri
- [Riot DataDragon](https://developer.riotgames.com) — champion & skin ID'leri

***

<div align="center">


</div>
