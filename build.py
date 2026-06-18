from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
import re
import difflib
import shutil
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Windows konsolunda kutu cizimleri / Turkce karakterler bozulmasin
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = "RahasyaExtractionTool/0.3"

# .exe (PyInstaller) ile script modunu ayir:
#   FROZEN ise -> pip/git calismaz; LtMAO + paketler gomulu, _vendor BUNDLE icinde.
#   Kalici dosyalar (config.json, pref/hashes, cikti) DAIMA .exe'nin yaninda durur.
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    HERE   = Path(sys.executable).parent.resolve()          # exe yani: config, pref
    BUNDLE = Path(getattr(sys, "_MEIPASS", HERE)).resolve()  # gomulu: _vendor
else:
    HERE = BUNDLE = Path(__file__).parent.resolve()

if not FROZEN:
    _REQUIRED = ["requests", "pyzstd", "xxhash"]
    _missing = [p for p in _REQUIRED if __import__("importlib").util.find_spec(p) is None]
    if _missing:
        print(f"[!] eksik paketler: {', '.join(_missing)}")
        print("[*] yukleniyor...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *_missing])
        print("[+] paketler kuruldu\n")

LTMAO_SRC = BUNDLE / "_vendor" / "LtMAO" / "src"
if not LTMAO_SRC.exists():
    if FROZEN:
        sys.exit("[!] LtMAO .exe icine paketlenmemis (build hatasi).")
    print("[!] LtMAO bulunamadi.")
    ans = input("    indirilsin mi? (e/h): ").strip().lower()
    if ans == "e":
        print("[*] LtMAO indiriliyor...")
        subprocess.check_call([
            "git", "clone", "--depth=1",
            "https://github.com/GuiSaiUwU/LtMAO",
            str(BUNDLE / "_vendor" / "LtMAO")
        ])
        print("[+] LtMAO indirildi\n")
    else:
        sys.exit("LtMAO olmadan calistirilamaz.")

sys.path.insert(0, str(LTMAO_SRC))

WORK_DIR = HERE
os.makedirs(WORK_DIR / "pref" / "hashes" / "cdtb_hashes", exist_ok=True)
os.chdir(WORK_DIR)

from LtMAO import pyRitoFile, hash_helper  # type: ignore
from LtMAO.hash_helper import CDTBHashes, CustomHashes, Storage  # type: ignore
from LtMAO import no_skin  # type: ignore
from LtMAO.pyRitoFile.helper import FNV1a  # type: ignore

for _d in (CDTBHashes.local_dir, CustomHashes.local_dir, "./pref/hashes/extracted_hashes"):
    os.makedirs(_d, exist_ok=True)

DEFAULT_LEAGUE = r"C:\Riot Games\League of Legends"
DEFAULT_OUT = str(Path.home() / "Desktop" / "Extracted")
CONFIG_PATH = HERE / "config.json"

CHROMA_COLORS = {
    "rose quartz": "#e01da4", "lapis lazuli": "#26619c",
    "tiger's eye": "#c68642", "tenfold triumph": "#b31b1b",
    "ruby": "#e01d1d", "emerald": "#29b32b", "sapphire": "#1d5ee0",
    "catseye": "#e0b31d", "obsidian": "#2d2d2d", "pearl": "#e8e8e8",
    "amethyst": "#a41de0", "turquoise": "#1de0b3", "tanzanite": "#411de0",
    "meteorite": "#70441e", "aquamarine": "#7bb5e0", "citrine": "#e0e01d",
    "peridot": "#93e01d", "sandstone": "#c8a97a", "granite": "#8c8c8c",
    "slate": "#5c6e7a", "bronze": "#cd7f32", "jasper": "#d73b3e",
    "onyx": "#353839", "beryl": "#7fffd4", "jade": "#00a36c",
    "coral": "#ff7f50", "ivory": "#fffff0", "malachite": "#0bda51",
    "sunstone": "#ff9900", "moonstone": "#9af0f0", "bloodstone": "#8a0303",
    "prestige": "#ffd700", "golden": "#ffd700", "gold": "#ffd700",
    "silver": "#c0c0c0", "platinum": "#e8f0f0", "elite": "#d4af37",
    "mythic": "#a32cc4", "event": "#ffae00",
    "red": "#e01d1d", "blue": "#1d5ee0", "green": "#29b32b",
    "purple": "#a41de0", "yellow": "#e0e01d", "orange": "#e07b1d",
    "pink": "#e01da4", "white": "#e8e8e8", "black": "#2d2d2d",
    "gray": "#888888", "grey": "#888888", "brown": "#70441e",
    "teal": "#1de0b3", "cyan": "#1de0e0", "magenta": "#e01de0",
    "lime": "#93e01d", "indigo": "#411de0", "violet": "#7b1de0",
    "scarlet": "#e0251d", "crimson": "#b31b1b", "navy": "#0a1a6b",
    "maroon": "#6b0a0a", "rose": "#e01d6b",
}

CDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
CDRAGON_BASE     = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default"
CDRAGON_SUMMARY  = f"{CDRAGON_BASE}/v1/champion-summary.json"
CDRAGON_SKINS    = f"{CDRAGON_BASE}/v1/skins.json"

RIOT_DATA: dict = {}
_SPLASH_CACHE: dict[str, bytes | None] = {}


# ----------------------------------------------------------------------------
#  HTTP (retry + backoff)
# ----------------------------------------------------------------------------
def _http_get(url: str, timeout: int = 30, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(1.2 * (i + 1))
    raise last if last else RuntimeError("http error")


def http_json(url: str):
    return json.loads(_http_get(url))


def http_bytes(url: str | None) -> bytes | None:
    if not url:
        return None
    if url in _SPLASH_CACHE:
        return _SPLASH_CACHE[url]
    try:
        data = _http_get(url)
    except Exception as e:
        print(f"      · splash indirilemedi: {e}")
        data = None
    _SPLASH_CACHE[url] = data
    return data


_CDRAGON_CACHE: dict[str, object] = {}


def _cdragon_json_cached(url: str):
    """Katalog JSON'larini bir kez indirir (extract-all 170+ kez cagirir)."""
    if url not in _CDRAGON_CACHE:
        _CDRAGON_CACHE[url] = http_json(url)
    return _CDRAGON_CACHE[url]


# ----------------------------------------------------------------------------
#  Config (kalici ayarlar)
# ----------------------------------------------------------------------------
CONFIG = {
    "league":   DEFAULT_LEAGUE,
    "out":      DEFAULT_OUT,
    "ltk":      "",     # bos = otomatik bul (AppData)
    "ltk_auto": False,  # build sonrasi LTK'ya otomatik import
}


def load_config() -> None:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k in CONFIG:
                if k in data and data[k] is not None:
                    CONFIG[k] = data[k]
        except Exception as e:
            print(f"  [!] config.json okunamadi: {e}")


def save_config() -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"  [!] config kaydedilemedi: {e}")


def _has_champions(base: str | None) -> bool:
    try:
        return bool(base) and (Path(base) / "Game" / "DATA" / "FINAL" / "Champions").exists()
    except Exception:
        return False


def detect_league_path() -> str | None:
    """League kurulum yolunu otomatik bulmaya calisir (Windows registry + yaygin
    yollar, macOS uygulama yolu)."""
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        try:
            import winreg  # type: ignore
            for hive, key, name in [
                (winreg.HKEY_CURRENT_USER, r"Software\Riot Games\League of Legends", "Path"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Riot Games\League of Legends", "Path"),
            ]:
                try:
                    with winreg.OpenKey(hive, key) as k:
                        val, _ = winreg.QueryValueEx(k, name)
                        if val:
                            candidates.append(str(val))
                except OSError:
                    pass
        except Exception:
            pass
        for d in ("C:", "D:", "E:"):
            candidates += [
                rf"{d}\Riot Games\League of Legends",
                rf"{d}\Program Files\Riot Games\League of Legends",
            ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/League of Legends.app/Contents/LoL",
            str(Path.home() / "Applications/League of Legends.app/Contents/LoL"),
        ]
    for c in candidates:
        if _has_champions(c):
            return c
    for c in candidates:
        try:
            if c and Path(c).exists():
                return c
        except Exception:
            pass
    return None


# ----------------------------------------------------------------------------
#  Riot / CDragon veri
# ----------------------------------------------------------------------------
def load_riot_data():
    global RIOT_DATA
    try:
        print("[*] Riot DataDragon yukleniyor...")
        version = http_json(CDRAGON_VERSIONS)[0]
        full = http_json(
            "https://ddragon.leagueoflegends.com/cdn/" + version + "/data/en_US/championFull.json"
        )
        for _, info in full["data"].items():
            RIOT_DATA[info["name"].lower()] = {
                "key": info["key"], "skins": info["skins"]
            }
        print(f"[+] Riot API hazir ({version}, {len(RIOT_DATA)} champion)\n")
    except Exception as e:
        print(f"[!] Riot API alinamadi ({e})\n")


def find_skin_id(champ_name: str, skin_name: str):
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    data = next((v for k, v in RIOT_DATA.items() if norm(k) == norm(champ_name)), None)
    if not data:
        return None
    official = {s["name"].lower(): s["id"] for s in data["skins"]}
    if skin_name.lower() in official:
        return official[skin_name.lower()]
    m = difflib.get_close_matches(skin_name.lower(), official.keys(), n=1, cutoff=0.5)
    return official[m[0]] if m else None


def cdragon_asset_url(asset_path: str | None) -> str | None:
    if not asset_path:
        return None
    p = asset_path.strip()
    if p.startswith("/lol-game-data/assets/"):
        p = p.removeprefix("/lol-game-data/assets/")
        return f"{CDRAGON_BASE}/{p.lower()}"
    if p.startswith("/"):
        return f"{CDRAGON_BASE}/{p.lstrip('/').lower()}"
    return f"{CDRAGON_BASE}/{p.lower()}"


def chroma_splash_url(champ_id: int, chroma_id: int) -> str:
    return f"{CDRAGON_BASE}/v1/champion-chroma-images/{champ_id}/{chroma_id}.png"


def fetch_catalog(only_key: str) -> tuple[str, dict, dict, int]:
    try:
        patch = _cdragon_json_cached(CDRAGON_VERSIONS)[0]
    except Exception:
        patch = "latest"

    try:
        summary = _cdragon_json_cached(CDRAGON_SUMMARY)
        skins   = _cdragon_json_cached(CDRAGON_SKINS)
    except Exception as e:
        sys.exit(f"[!] CDragon katalogu alinamadi (internet?): {e}")

    id_to_key = {int(c["id"]): c["alias"] for c in summary if int(c["id"]) > 0}

    target_id = None
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    for cid, key in id_to_key.items():
        if norm(key) == norm(only_key):
            target_id, only_key = cid, key
            break
    if target_id is None:
        matches = [(cid, key) for cid, key in id_to_key.items()
                   if norm(only_key) in norm(key)]
        if len(matches) == 1:
            target_id, only_key = matches[0]
        elif len(matches) > 1:
            sys.exit(f"Bircok esleme: {', '.join(k for _, k in matches)}")
        else:
            sys.exit(f"Champion bulunamadi: '{only_key}'")

    catalog: dict[str, dict[int, str]] = {only_key: {}}
    for sid_str, sinfo in skins.items():
        try:
            sid = int(sid_str)
        except Exception:
            continue
        champ_id = sid // 1000 if sid >= 1000 else sid
        skin_num = sid % 1000 if sid >= 1000 else 0
        if champ_id != target_id or skin_num == 0:
            continue
        catalog[only_key][skin_num] = sinfo.get("name") or f"{only_key} skin {skin_num}"

    chroma_meta: dict[str, dict[int, dict]] = {only_key: {}}
    try:
        champ_skins = _cdragon_json_cached(f"{CDRAGON_BASE}/v1/champions/{target_id}.json").get("skins", [])
    except Exception:
        champ_skins = []

    for s in champ_skins:
        parent_id = int(s.get("id") or 0)
        if parent_id < 1000 or parent_id // 1000 != target_id:
            continue
        parent_num  = parent_id % 1000
        parent_name = s.get("name") or f"{only_key} skin {parent_num}"
        parent_splash = s.get("splashPath") or s.get("uncenteredSplashPath")

        if parent_num not in chroma_meta[only_key]:
            chroma_meta[only_key][parent_num] = {
                "kind": "skin", "splash_path": parent_splash
            }

        for chroma in s.get("chromas") or []:
            cid_full = int(chroma["id"])
            if cid_full // 1000 != target_id:
                continue
            skin_num = cid_full % 1000
            if skin_num in catalog[only_key]:
                continue
            cname = chroma.get("name") or f"{parent_name} (Chroma {skin_num})"
            color = _extract_color(cname, chroma.get("description") or "")
            catalog[only_key][skin_num] = cname
            chroma_meta[only_key][skin_num] = {
                "parent_num": parent_num, "parent_name": parent_name,
                "color": color, "kind": "chroma", "full_id": cid_full,
                "parent_splash_path": parent_splash,
            }
        for t in (s.get("questSkinInfo") or {}).get("tiers") or []:
            tid  = int(t.get("id") or 0)
            tnum = tid % 1000
            if tid // 1000 != target_id or tnum == parent_num:
                continue
            tname = t.get("name") or f"{parent_name} Stage {tnum}"
            catalog[only_key][tnum] = tname
            chroma_meta[only_key][tnum] = {
                "parent_num": parent_num, "parent_name": parent_name,
                "color": "", "kind": "form",
                "short": str(t.get("stage") or t.get("name") or f"Stage {tnum}"),
                "splash_path": t.get("splashPath") or t.get("uncenteredSplashPath") or parent_splash,
            }

    return patch, catalog, chroma_meta, target_id


def _extract_color(name: str, desc: str = "") -> str:
    combined = (name + " " + desc).lower()
    for k in sorted(CHROMA_COLORS, key=len, reverse=True):
        if k in combined:
            return k.title()
    if "(" in name and name.endswith(")"):
        inner = name.rsplit("(", 1)[1].rstrip(")").strip()
        if inner:
            return inner
    return ""


def ansi_block(color_name: str) -> str:
    hex_c = CHROMA_COLORS.get(color_name.lower(), "")
    if not hex_c:
        return "\033[90m██\033[0m"
    h = hex_c.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m██\033[0m"


def hyperlink(text: str, url: str | None) -> str:
    if not url:
        return text
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def load_hashes(refresh: bool = False):
    """Hash'ler bir kez indirilir; sonrasinda yerelden okunur. Network sync
    (guncelleme kontrolu) yalnizca CARSAMBA gunleri (gunde bir kez) ya da
    refresh / ilk calistirma durumunda yapilir. Patch'ler Carsamba ciktigi
    icin yeterli."""
    cache  = WORK_DIR / "pref" / "hashes" / "cdtb_hashes"
    custom = WORK_DIR / "pref" / "hashes" / "custom_hashes"
    marker = WORK_DIR / "pref" / "hashes" / ".last_sync"
    if refresh and cache.exists():
        for f in cache.iterdir():
            try:
                f.unlink()
            except OSError:
                pass

    today      = datetime.now().date().isoformat()
    have_local = (custom / "hashes.game.txt").exists()
    last_sync  = ""
    try:
        last_sync = marker.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    is_wednesday = datetime.now().weekday() == 2          # 0=Pzt, 2=Carsamba
    need_sync = refresh or not have_local or (is_wednesday and last_sync != today)

    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        if need_sync:
            CDTBHashes.sync_all()
            try:
                marker.write_text(today, encoding="utf-8")
            except OSError:
                pass
        CustomHashes.read_all_hashes()
    global _BIN_TABLES
    _BIN_TABLES = None                  # tablo cache'ini tazele (yeni hash'lerle)
    src = "sync+yerel" if need_sync else "yerel (sync atlandi)"
    print(f"[+] hashler yuklendi ({src}, {len(Storage.hashtables['hashes.game.txt'])} entry)\n")


# ----------------------------------------------------------------------------
#  Skin builder
# ----------------------------------------------------------------------------
# Bin-swap edilen TUM .fantome'larda ayni imza
FANTOME_AUTHOR = "kick.com/rahasya"
FANTOME_DESC   = "kick.com/rahasya"


def fantome_meta(name: str, version: str = "1.0.0") -> str:
    return json.dumps({
        "Name": name,
        "Author": FANTOME_AUTHOR,
        "Version": version,
        "Description": FANTOME_DESC,
    }, indent=2, ensure_ascii=False)


_BIN_TABLES = None


def _bin_tables() -> tuple[dict, dict]:
    """hashes.game.txt'i bir kez tarar: (skin_bin_tablosu, animasyon_bin_tablosu).
    Cache'li - tekrar tekrar 2M entry taranmasin (hiz)."""
    global _BIN_TABLES
    if _BIN_TABLES is None:
        skins, anims = {}, {}
        for h, p in hash_helper.Storage.hashtables["hashes.game.txt"].items():
            pl = p.lower()
            if not pl.endswith(".bin") or "data/characters/" not in pl:
                continue
            if "/skins/skin" in pl and "root.bin" not in pl:
                skins[h] = p
            elif "/animations/skin" in pl:
                anims[h] = p
        _BIN_TABLES = (skins, anims)
    return _BIN_TABLES


def skin_bin_hash_table() -> dict:
    """data/characters/<champ>/skins/skinN.bin yollari."""
    return _bin_tables()[0]


def anim_bin_hash_table() -> dict:
    """data/characters/<champ>/animations/skinN.bin yollari."""
    return _bin_tables()[1]


def _bin_hash_le(path: str) -> bytes:
    """bin link hash'i (FNV) little-endian 4 byte - ham bin icinde aramak icin."""
    return struct.pack("<I", int(str(no_skin.bin_hash(path)), 16))


def _make_anim0(wad_path, char_anims: dict, char: str, num: int, skinN_raw: bytes):
    """Skin'in kullandigi animations bin'ini (skin'e ozel VFX/event bindings)
    skin0'a cevirir: AnimationGraphData entry hash'ini Skin{M} -> Skin0 yapar.
    Custom animasyon yoksa None (base skin0 anim'i kullanilir).
    char_anims: {M: chunk}  (oyun WAD'indaki animations/skinM.bin chunk'lari)."""
    if not char_anims:
        return None
    # M: bu karakterin kendi skin{num} anim bin'i varsa M=num; yoksa skinN ham
    #    veride hangi animations/skinM'i referans ediyorsa o (chroma -> parent).
    M = None
    if num in char_anims:
        M = num
    else:
        for m in char_anims:
            if m == 0:
                continue
            if _bin_hash_le(f"characters/{char}/animations/skin{m}") in skinN_raw:
                M = m
                break
    if not M:                                   # custom animasyon yok
        return None
    chunk = char_anims[M]
    with pyRitoFile.stream.BytesStream.reader(str(wad_path)) as bs:
        chunk.read_data(bs)
    try:
        raw = bytes(chunk.data)
    finally:
        chunk.free_data()
    # AnimationGraphData entry hash'ini Skin{M} -> Skin0: ham byte'larda 4-byte
    # FNV swap (pyRitoFile parse-write animasyonda kayipli olabilir)
    cap = char[:1].upper() + char[1:]
    out = bytearray(raw)
    for old, new in ((f"Characters/{cap}/Animations/Skin{M}", f"Characters/{cap}/Animations/Skin0"),
                     (f"characters/{char}/animations/skin{M}", f"characters/{char}/animations/skin0")):
        i = out.find(FNV1a(old).to_bytes(4, "little"))
        if i >= 0:
            out[i:i + 4] = FNV1a(new).to_bytes(4, "little")
            return bytes(out)
    return None


class SkinBuilder:
    def __init__(self, champions_dir: Path, output_dir: Path,
                 catalog: dict, chroma_meta: dict, champ_id: int = 0):
        self.champions_dir = champions_dir
        self.output_dir    = output_dir
        self.catalog       = catalog
        self.chroma_meta   = chroma_meta
        self.champ_id      = champ_id
        self._used_names: set[str] = set()
        self.skin_bin_hashes = skin_bin_hash_table()

    def list_skins(self, champ_key: str) -> list[dict]:
        wad_path = self._find_wad(champ_key)
        if not wad_path:
            print(f"  [!] WAD bulunamadi: {champ_key}")
            return []

        wad = pyRitoFile.wad.WAD().read(str(wad_path))
        wad.un_hash({"hashes.game.txt": self.skin_bin_hashes})

        champ_lower = champ_key.lower()
        found_nums: set[int] = set()
        for chunk in wad.chunks:
            if chunk.extension != "bin":
                continue
            parts = chunk.hash.lower().split("/")
            if (len(parts) < 5 or parts[0] != "data"
                    or parts[1] != "characters"
                    or parts[2] != champ_lower
                    or parts[3] != "skins"):
                continue
            base = parts[4][:-4]
            if base == "skin0":
                continue
            try:
                found_nums.add(int(base.removeprefix("skin")))
            except ValueError:
                pass

        names  = self.catalog.get(champ_key, {})
        cmap   = self.chroma_meta.get(champ_key, {})
        skips  = no_skin.SKIPS.get(champ_lower)
        result = []

        for num in sorted(found_nums):
            if num not in names:
                continue
            if skips == "all":
                continue
            if isinstance(skips, list) and f"skin{num}.bin" in skips:
                continue
            display = names[num]
            meta    = cmap.get(num)
            color   = ""
            kind    = "skin"
            parent_name = ""
            parent_num  = None
            if meta:
                kind        = meta.get("kind", "chroma")
                color       = meta.get("color", "")
                parent_name = meta.get("parent_name", "")
                parent_num  = meta.get("parent_num")

            if kind == "chroma" and meta:
                sid = None
                asset_id = int(meta.get("full_id") or 0)
                spl = chroma_splash_url(self.champ_id, asset_id) if asset_id else None
                if not spl:
                    spl = cdragon_asset_url(meta.get("parent_splash_path"))
            else:
                sid = find_skin_id(champ_key, display)
                asset_id = int(sid) if sid else 0
                spl = cdragon_asset_url(meta.get("splash_path") if meta else None)

            result.append({
                "num": num,
                "display": display,
                "kind": kind,
                "color": color,
                "parent_name": parent_name,
                "parent_num": parent_num,
                "skin_id": sid,
                "splash": spl,
            })
        return result

    def _unique_path(self, fname: str) -> Path:
        base = fname
        n = 2
        while fname in self._used_names:
            fname = f"{base} ({n})"
            n += 1
        self._used_names.add(fname)
        return self.output_dir / f"{fname}.fantome"

    def build_skin(self, champ_key: str, skin_info: dict) -> Path | None:
        wad_path = self._find_wad(champ_key)
        if not wad_path:
            print(f"  [!] WAD bulunamadi: {champ_key}")
            return None

        wad = pyRitoFile.wad.WAD().read(str(wad_path))
        wad.un_hash({"hashes.game.txt": {**self.skin_bin_hashes, **anim_bin_hash_table()}})

        champ_lower = champ_key.lower()
        characters: dict[str, dict] = {}
        char_anims: dict[str, dict] = {}        # char -> {M: chunk}  (animations/skinM.bin)
        for chunk in wad.chunks:
            if chunk.extension != "bin":
                continue
            parts = chunk.hash.lower().split("/")
            if (len(parts) < 5 or parts[0] != "data" or parts[1] != "characters"):
                continue
            char = parts[2]
            base = parts[4][:-4]
            if parts[3] == "animations" and base.startswith("skin"):
                try:
                    char_anims.setdefault(char, {})[int(base.removeprefix("skin"))] = chunk
                except ValueError:
                    pass
                continue
            if parts[3] != "skins":
                continue
            ent  = characters.setdefault(char, {"skin0": None, "skinN": {}})
            if base == "skin0":
                ent["skin0"] = chunk
            else:
                try:
                    ent["skinN"][int(base.removeprefix("skin"))] = chunk
                except ValueError:
                    pass

        if champ_lower not in characters or not characters[champ_lower]["skin0"]:
            print(f"  [!] {champ_key}: skin0.bin yok")
            return None

        char_s0_hashes: dict[str, tuple] = {}
        char_s0_bins:   dict[str, object] = {}
        for char, info in characters.items():
            if not info["skin0"]:
                continue
            with pyRitoFile.stream.BytesStream.reader(str(wad_path)) as bs:
                info["skin0"].read_data(bs)
            try:
                s0 = _read_bin(info["skin0"].data)
            finally:
                info["skin0"].free_data()
            scdp_h = rr_h = None
            for entry in s0.entries or []:
                if entry.type == hash_helper.Storage.bin_hashes["SkinCharacterDataProperties"]:
                    scdp_h = entry.hash
                    for f in entry.data:
                        if f.hash == hash_helper.Storage.bin_hashes["mResourceResolver"]:
                            rr_h = f.data
                            break
                elif entry.type == hash_helper.Storage.bin_hashes["ResourceResolver"]:
                    if rr_h is None:
                        rr_h = entry.hash
            if scdp_h:
                char_s0_hashes[char] = (scdp_h, rr_h)
                char_s0_bins[char]   = s0

        if champ_lower not in char_s0_hashes:
            print(f"  [!] {champ_key}: SkinCharacterDataProperties yok")
            return None

        num     = skin_info["num"]
        display = skin_info["display"]
        patched = []

        for char, info in characters.items():
            if num not in info["skinN"] or char not in char_s0_hashes:
                continue
            scdp_h, rr_h = char_s0_hashes[char]
            chunk = info["skinN"][num]
            with pyRitoFile.stream.BytesStream.reader(str(wad_path)) as bs:
                chunk.read_data(bs)
            skinN_raw = bytes(chunk.data)
            try:
                skin_bin = _read_bin(chunk.data)
            finally:
                chunk.free_data()
            try:
                # gear-tier skinler (Battle Queen vs.) -> ritobin (kayipsiz);
                # geri kalan tum skinler -> mevcut hizli pyRitoFile yolu
                if _is_gear_tier(skin_bin) and _ritobin_cli():
                    data = _patch_skin_via_ritobin(char, skinN_raw, num)
                else:
                    data = _patch_bin(char, skin_bin, char_s0_bins.get(char), scdp_h, rr_h)
            except Exception as e:
                print(f"      · skip {char}: {e}")
                continue
            patched.append((f"data/characters/{char}/skins/skin0.bin", data))
            # skin'e ozel animasyon bin'i (VFX/event bindings) - eksikse VFX buglu
            try:
                anim = _make_anim0(wad_path, char_anims.get(char), char, num, skinN_raw)
                if anim:
                    patched.append((f"data/characters/{char}/animations/skin0.bin", anim))
            except Exception as e:
                print(f"      · {char} anim bin atlandi: {e}")

        if not patched:
            print(f"  [!] {champ_key} skin{num}: patch edilecek karakter yok")
            return None

        safe = lambda s: re.sub(r'[\\/*?:"<>|]', "", s).strip()
        meta = self.chroma_meta.get(champ_key, {}).get(num)
        if meta and meta.get("kind") == "chroma":
            color = meta.get("color", "")
            label = color if color else f"Chroma {num}"
            fname = safe(f"{meta['parent_name']} - {label}")
        elif meta and meta.get("kind") == "form":
            fname = safe(f"{meta['parent_name']} - {meta.get('short', num)}")
        else:
            fname = safe(display)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._unique_path(fname)

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            zf.writestr("META/info.json", fantome_meta(display))

            # CDragon splash'ini onizleme olarak gom (LTK/cslol META/image.png okur)
            img = http_bytes(skin_info.get("splash"))
            if img:
                zf.writestr("META/image.png", img)

            for inner, data in patched:
                zf.writestr(f"WAD/{wad_path.name}/{inner}", data)

        return out_path

    def _find_wad(self, champ_key: str) -> Path | None:
        target = f"{champ_key}.wad.client".lower()
        for w in self.champions_dir.glob("*.wad.client"):
            if w.name.lower() == target:
                return w
        return None


def _read_bin(data: bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tf:
        tf.write(data)
        tmp = tf.name
    try:
        return pyRitoFile.bin.BIN().read(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _patch_bin(char_lower, skin_bin, skin0_bin, skin0_scdp, skin0_rr):
    SCDP = hash_helper.Storage.bin_hashes["SkinCharacterDataProperties"]
    MRR  = hash_helper.Storage.bin_hashes["mResourceResolver"]
    RR   = hash_helper.Storage.bin_hashes["ResourceResolver"]
    SONF = 0x2d78c328

    scdp = mrr = rr = None
    for e in skin_bin.entries:
        if e.type == SCDP:
            scdp = e
            for f in e.data:
                if f.hash == MRR:
                    mrr = f
                    break
        elif e.type == RR:
            rr = e
    if not scdp:
        raise RuntimeError("no SCDP")

    scdp.hash = skin0_scdp
    if rr and skin0_rr:
        rr.hash = skin0_rr
    if mrr and skin0_rr:
        mrr.data = skin0_rr

    for f in scdp.data or []:
        if f.type != pyRitoFile.bin.BINType.STRING or not isinstance(f.data, str):
            continue
        try:
            fh = f.hash if isinstance(f.hash, int) else int(str(f.hash), 16)
        except Exception:
            continue
        if fh == SONF and f.data.lower().startswith(char_lower + "skin"):
            f.data = f.data[:len(char_lower)]

    if skin0_bin:
        ph = {e.hash for e in skin_bin.entries}
        skin_bin.entries = list(skin_bin.entries) + [
            e for e in (skin0_bin.entries or []) if e.hash not in ph
        ]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tf:
        tmp = tf.name
    try:
        skin_bin.write(tmp)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ----------------------------------------------------------------------------
#  Gear-tier skinler (Battle Queen Katarina, Pajama Guardian Lulu, ...)
#  pyRitoFile BIN.write bunlardaki GearSkinUpgrade entry'lerini kirpiyor;
#  bu yuzden ritobin_cli ile text round-trip + gear-resource inlining yapilir.
# ----------------------------------------------------------------------------
_GEAR_TYPE = f"{FNV1a('GearSkinUpgrade'):08x}"
_RITOBIN_CLI = "__unset__"


def _ritobin_cli() -> Path | None:
    global _RITOBIN_CLI
    if _RITOBIN_CLI == "__unset__":
        for cand in (BUNDLE / "_vendor" / "LtMAO" / "res" / "tools" / "ritobin_cli.exe",
                     BUNDLE / "_vendor" / "ritobin_cli.exe",
                     HERE / "_vendor" / "LtMAO" / "res" / "tools" / "ritobin_cli.exe"):
            if cand.exists():
                _RITOBIN_CLI = cand
                break
        else:
            _RITOBIN_CLI = None
    return _RITOBIN_CLI


def _is_gear_tier(skin_bin) -> bool:
    return any(e.type == _GEAR_TYPE for e in skin_bin.entries or [])


def _find_matching_brace(text: str, start: int) -> int:
    depth = 0
    in_str = False
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_str = not in_str
        elif not in_str:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(text)


def _inline_gear_resources(text: str, char_cap: str, num: int) -> str:
    """Level-1 gear'in mVFXResourceResolver.resourceMap'ini ana ResourceResolver'a
    inline eder ve initialSubmeshToHide'dan gear submesh token'larini cikarir
    (spawn'da seviye-1 silahlar gorunsun)."""
    gm = re.search(r'mGearSkinUpgrades:\s*list\[link\]\s*=\s*\{([^}]*)\}', text, re.DOTALL)
    if not gm:
        return text
    m = re.search(r'"([^"]+)"', gm.group(1))
    if not m:
        return text
    marker = f'"{m.group(1)}" = GearSkinUpgrade'
    idx = text.find(marker)
    if idx < 0:
        return text
    bo = text.find('{', idx)
    gear_block = text[bo:_find_matching_brace(text, bo)]

    rr_idx = gear_block.find('mVFXResourceResolver: pointer = ResourceResolver')
    if rr_idx < 0:
        return text
    rr_bo = gear_block.find('{', rr_idx)
    rr_block = gear_block[rr_bo:_find_matching_brace(gear_block, rr_bo)]

    rm_idx = rr_block.find('resourceMap: map[hash,link]')
    if rm_idx < 0:
        return text
    rm_bo = rr_block.find('{', rm_idx)
    rm_close = _find_matching_brace(rr_block, rm_bo)
    gear_resources = rr_block[rm_bo + 1:rm_close - 1]

    show_tokens: set = set()
    sm = re.search(r'mCharacterSubmeshesToShow:\s*list\[hash\]\s*=\s*\{([^}]*)\}', gear_block, re.DOTALL)
    if sm:
        show_tokens = set(re.findall(r'"([^"]+)"', sm.group(1)))

    for rr_name in (f'"Characters/{char_cap}/Skins/Skin0/Resources" = ResourceResolver',
                    f'"Characters/{char_cap}/Skins/Skin{num}/Resources" = ResourceResolver'):
        rr_pos = text.find(rr_name)
        if rr_pos < 0:
            continue
        rm_marker = 'resourceMap: map[hash,link] = {'
        rm_pos = text.find(rm_marker, rr_pos)
        if rm_pos < 0:
            continue
        insert_at = rm_pos + len(rm_marker)
        text = text[:insert_at] + '\n' + gear_resources.rstrip('\n') + '\n' + text[insert_at:]
        break

    if show_tokens:
        def _strip(mt):
            kept = [t for t in mt.group(2).split() if t not in show_tokens]
            return mt.group(1) + ' '.join(kept) + mt.group(3)
        text = re.sub(r'(initialSubmeshToHide: string = ")([^"]*)(")', _strip, text)
    return text


def _patch_skin_via_ritobin(char_lower: str, skin_raw: bytes, num: int) -> bytes:
    """Gear-tier skin: ritobin_cli ile bin->text->bin (byte-kayipsiz) + entry
    rename (Skin{num}->Skin0) + gear-resource inlining."""
    cli = _ritobin_cli()
    if cli is None:
        raise RuntimeError("ritobin_cli.exe yok (gear-tier skin)")
    hashdir = WORK_DIR / "pref" / "hashes" / "cdtb_hashes"
    cap = char_lower[:1].upper() + char_lower[1:]
    with tempfile.TemporaryDirectory() as td:
        in_bin, in_txt, out_bin = Path(td) / "i.bin", Path(td) / "i.txt", Path(td) / "o.bin"
        in_bin.write_bytes(skin_raw)
        r = subprocess.run([str(cli), "-d", str(hashdir), str(in_bin), str(in_txt)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ritobin bin->txt: {r.stderr or r.stdout}")
        text = in_txt.read_text(encoding="utf-8")
        text = re.sub(rf'("Characters/{re.escape(cap)}/Skins/Skin){num}(" = SkinCharacterDataProperties)',
                      r'\g<1>0\g<2>', text)
        text = re.sub(rf'("Characters/{re.escape(cap)}/Skins/Skin){num}(/Resources" = ResourceResolver)',
                      r'\g<1>0\g<2>', text)
        text = re.sub(rf'(mResourceResolver: link = "Characters/{re.escape(cap)}/Skins/Skin){num}(/Resources")',
                      r'\g<1>0\g<2>', text)
        text = re.sub(rf'(championSkinName: string = ")\w+Skin{num}(")', rf'\g<1>{cap}\g<2>', text)
        text = _inline_gear_resources(text, cap, num)
        in_txt.write_text(text, encoding="utf-8")
        r = subprocess.run([str(cli), "-d", str(hashdir), str(in_txt), str(out_bin)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ritobin txt->bin: {r.stderr or r.stdout}")
        return out_bin.read_bytes()


# ----------------------------------------------------------------------------
#  Harici mod aktarimi: .fantome / .wad  ->  skin0 bin-swap  ->  .fantome
# ----------------------------------------------------------------------------
# WAD/<wadname>/data/characters/<champ>/skins/skinN.bin  (fantome ic yolu)
_SKIN_BIN_RE = re.compile(
    r"^(?P<pre>wad/[^/]+/)?data/characters/(?P<champ>[^/]+)/skins/skin(?P<num>\d+)\.bin$",
    re.IGNORECASE)


def _load_skin0_ref(game_wad: Path, char_lower: str, table: dict):
    """Oyun WAD'indan ilgili karakterin skin0 referansini cikarir:
    (skin0_bin, scdp_hash, rr_hash). Bulunamazsa (None, None, None)."""
    wad = pyRitoFile.wad.WAD().read(str(game_wad))
    wad.un_hash({"hashes.game.txt": table})
    target = f"data/characters/{char_lower}/skins/skin0.bin"
    chunk = next((c for c in wad.chunks
                  if c.extension == "bin" and c.hash.lower() == target), None)
    if not chunk:
        return None, None, None
    with pyRitoFile.stream.BytesStream.reader(str(game_wad)) as bs:
        chunk.read_data(bs)
    try:
        s0 = _read_bin(chunk.data)
    finally:
        chunk.free_data()
    scdp_h = rr_h = None
    for entry in s0.entries or []:
        if entry.type == hash_helper.Storage.bin_hashes["SkinCharacterDataProperties"]:
            scdp_h = entry.hash
            for f in entry.data:
                if f.hash == hash_helper.Storage.bin_hashes["mResourceResolver"]:
                    rr_h = f.data
                    break
        elif entry.type == hash_helper.Storage.bin_hashes["ResourceResolver"]:
            if rr_h is None:
                rr_h = entry.hash
    return (s0, scdp_h, rr_h) if scdp_h else (None, None, None)


def _load_game_skin_bin(game_wad: Path, char_lower: str, num: int, table: dict):
    """Oyun WAD'indan skinN.bin'i okuyup parse eder (texture-only mod fallback'i
    icin: o skin'in bin'ini cekip skin0'a swap'lariz). Bulunamazsa None."""
    wad = pyRitoFile.wad.WAD().read(str(game_wad))
    wad.un_hash({"hashes.game.txt": table})
    target = f"data/characters/{char_lower}/skins/skin{num}.bin"
    chunk = next((c for c in wad.chunks
                  if c.extension == "bin" and c.hash.lower() == target), None)
    if not chunk:
        return None
    with pyRitoFile.stream.BytesStream.reader(str(game_wad)) as bs:
        chunk.read_data(bs)
    try:
        return _read_bin(chunk.data)
    finally:
        chunk.free_data()


# assets/characters/<char>/skins/skin01/...  (texture yollarindan skin tespiti)
_ASSET_SKIN_RE = re.compile(r"assets/characters/([^/]+)/skins/skin0*(\d+)/", re.IGNORECASE)


def _game_chars_with_skin(game_wad: Path, num: int, table: dict) -> list[str]:
    """Oyun WAD'inda hem skin{num}.bin hem skin0.bin'i olan TUM karakterler.
    Bir sampiyonun golge/klon alt-karakterleri (or. zedshadow) de buraya girer;
    boylece skin sadece ana govdede degil golgelerde de uygulanir."""
    wad = pyRitoFile.wad.WAD().read(str(game_wad))
    wad.un_hash({"hashes.game.txt": table})
    chars: dict[str, set[int]] = {}
    for c in wad.chunks:
        if c.extension != "bin":
            continue
        mm = _SKIN_BIN_RE.match(str(c.hash))
        if mm:
            chars.setdefault(mm.group("champ").lower(), set()).add(int(mm.group("num")))
    return [ch for ch, nums in chars.items() if num in nums and 0 in nums]


def _find_game_wad_by_name(champions_dir: Path, wad_name: str) -> Path | None:
    """Mod WAD'inin dosya adiyla ESLESEN oyun WAD'i (or. Zed.wad.client).
    Bir WAD birden fazla karakter icerir (zed + zedshadow), hepsinin skin0'i
    bu tek dosyadadir."""
    target = wad_name.lower()
    for w in champions_dir.glob("*.wad.client"):
        if w.name.lower() == target:
            return w
    return None


def _find_game_wad_by_char(champions_dir: Path, char_lower: str) -> Path | None:
    for w in champions_dir.glob("*.wad.client"):
        if w.name.split(".", 1)[0].lower() == char_lower:
            return w
    return None


def _tmp_write(data: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        tf.write(data)
        return tf.name


def _write_wad(chunks: list[tuple[str, bytes]]) -> bytes:
    """[(hash_veya_path, data)] -> WAD bytes (no_skin yazma deseni)."""
    path = _tmp_write(b"", ".wad.client")
    try:
        wad = pyRitoFile.wad.WAD()
        wad.chunks = [pyRitoFile.wad.WADChunk.default() for _ in chunks]
        wad.write(path)
        with pyRitoFile.stream.BytesStream.updater(path) as bs:
            for i, ch in enumerate(wad.chunks):
                ch.write_data(bs, i, chunks[i][0], chunks[i][1])
                ch.free_data()
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _ref_cached(cache: dict, game_wad: Path | None, char: str, table: dict):
    key = (str(game_wad).lower() if game_wad else "", char)
    if key not in cache:
        if not game_wad:
            cache[key] = (None, None, None)
        else:
            try:
                cache[key] = _load_skin0_ref(game_wad, char, table)
            except Exception as e:
                print(f"  [!] {char}: skin0 referansi alinamadi ({e})")
                cache[key] = (None, None, None)
    return cache[key]


def _is_raw_wad_entry(arcname: str, data: bytes) -> str | None:
    """fantome icindeki HAM WAD blob'u mu? (WAD/<ad>.wad.client tek dosya).
    Evetse wad adini, degilse None doner."""
    parts = arcname.replace("\\", "/").split("/")
    if (len(parts) == 2 and parts[0].lower() == "wad"
            and (parts[1].lower().endswith(".wad.client")
                 or parts[1].lower().endswith(".wad"))
            and data[:2] == b"RW"):
        return parts[1]
    return None


def _rewrite_wad_skin0(wad_bytes: bytes, wad_name: str, champions_dir: Path,
                       table: dict, ref_cache: dict, stats: dict) -> tuple[bytes | None, str]:
    """Ham WAD icindeki skinN bin chunk'larini skin0'a cevirir, diger TUM
    chunk'lari (custom texture/mesh/anim dahil) korur. (yeni_bytes|None, champ)."""
    tmp_in = _tmp_write(wad_bytes, ".wad.client")
    try:
        wad = pyRitoFile.wad.WAD().read(tmp_in)
        # tam tablo: hem skin bin'leri hem asset (texture) yollari cozulsun
        full = hash_helper.Storage.hashtables["hashes.game.txt"]
        wad.un_hash({"hashes.game.txt": full})
        game_wad = _find_game_wad_by_name(champions_dir, wad_name)

        out_chunks: list[tuple[str, bytes]] = []
        seen_skin0: set[str] = set()
        asset_skins: dict[str, dict[int, int]] = {}   # char -> {skin_num: sayac}
        primary = ""
        with pyRitoFile.stream.BytesStream.reader(tmp_in) as bs:
            for c in wad.chunks:
                c.read_data(bs)
                data = c.data
                h = str(c.hash)
                # texture-only fallback icin asset yollarindan skin say
                am = _ASSET_SKIN_RE.search(h)
                if am:
                    ch, n = am.group(1).lower(), int(am.group(2))
                    if n > 0:
                        asset_skins.setdefault(ch, {}).setdefault(n, 0)
                        asset_skins[ch][n] += 1
                m = _SKIN_BIN_RE.match(h) if c.extension == "bin" else None
                if not m:
                    out_chunks.append((h, data))
                    c.free_data()
                    continue
                champ = m.group("champ").lower()
                num   = int(m.group("num"))
                c.free_data()
                if num == 0:
                    out_chunks.append((h, data))
                    stats["base"] += 1
                    continue
                gw = game_wad or _find_game_wad_by_char(champions_dir, champ)
                s0_bin, scdp_h, rr_h = _ref_cached(ref_cache, gw, champ, table)
                if not scdp_h:
                    if not gw:
                        print(f"  [!] {champ}: oyun WAD'i yok, skin{num} cevrilemedi")
                    out_chunks.append((h, data))
                    continue
                target = f"data/characters/{champ}/skins/skin0.bin"
                if target in seen_skin0:
                    print(f"  [!] {champ}: birden fazla skin skin0'a denk geldi, "
                          f"skin{num} atlandi")
                    out_chunks.append((h, data))
                    continue
                try:
                    skin_bin = pyRitoFile.bin.BIN().read(data, raw=True)
                    patched  = _patch_bin(champ, skin_bin, s0_bin, scdp_h, rr_h)
                except Exception as e:
                    print(f"  [!] {champ} skin{num}: patch hatasi ({e}), atlandi")
                    out_chunks.append((h, data))
                    continue
                seen_skin0.add(target)
                out_chunks.append((target, patched))
                print(f"  [+] {champ} skin{num} -> skin0   (WAD: {wad_name})")
                stats["swapped"] += 1
                stats.setdefault("_wanted", set()).add(num)
                cp = gw.name.split(".", 1)[0] if gw else champ.capitalize()
                stats.setdefault("source", (cp, num))
                if not primary:
                    primary = cp

        # texture-only mod (bin yok): asset yollarindan baskin skin'i tespit et
        wanted = stats.get("_wanted", set())
        gw_fill = game_wad
        if not wanted and asset_skins:
            agg: dict[int, int] = {}
            for counts in asset_skins.values():
                for n, cnt in counts.items():
                    agg[n] = agg.get(n, 0) + cnt
            if agg:
                wanted = {max(agg, key=agg.get)}
            if not gw_fill:
                gw_fill = _find_game_wad_by_char(champions_dir, next(iter(asset_skins)))

        # --- ana govde + alt-karakterleri (zedshadow gibi) skin0 yap ---
        # ayni skin'e sahip TUM oyun karakterlerini oyundan cekip swap'la; boylece
        # golgeler/klonlar da skin'e uyar (mod texture'lari yoksa oyunun skin'i gelir)
        if wanted and gw_fill:
            for num in sorted(wanted):
                for ch in _game_chars_with_skin(gw_fill, num, table):
                    target = f"data/characters/{ch}/skins/skin0.bin"
                    if target in seen_skin0:
                        continue
                    s0_bin, scdp_h, rr_h = _ref_cached(ref_cache, gw_fill, ch, table)
                    if not scdp_h:
                        continue
                    try:
                        game_skin = _load_game_skin_bin(gw_fill, ch, num, table)
                        if not game_skin:
                            continue
                        patched = _patch_bin(ch, game_skin, s0_bin, scdp_h, rr_h)
                    except Exception as e:
                        print(f"  [!] {ch} skin{num}: {e}")
                        continue
                    seen_skin0.add(target)
                    out_chunks.append((target, patched))
                    print(f"  [+] {ch} skin{num} -> skin0  (oyundan, alt-karakter/texture)")
                    stats["swapped"] += 1
                    cp = gw_fill.name.split(".", 1)[0]
                    stats.setdefault("source", (cp, num))
                    if not primary:
                        primary = cp

        if not seen_skin0:
            return None, ""
        return _write_wad(out_chunks), primary
    finally:
        try:
            os.unlink(tmp_in)
        except OSError:
            pass


def _fetch_skin_splash(champ_key: str, num: int) -> bytes | None:
    """Kaynak skin'in CDragon splash gorselini (onizleme icin) indirir."""
    try:
        summary = _cdragon_json_cached(CDRAGON_SUMMARY)
        cid = next((int(c["id"]) for c in summary
                    if normalize(c.get("alias", "")) == normalize(champ_key)), 0)
        if not cid:
            return None
        det = _cdragon_json_cached(f"{CDRAGON_BASE}/v1/champions/{cid}.json")
        sid = cid * 1000 + num
        skin = next((s for s in det.get("skins", []) if int(s.get("id", 0)) == sid), None)
        if not skin:
            return None
        path = skin.get("splashPath") or skin.get("uncenteredSplashPath")
        return http_bytes(cdragon_asset_url(path))
    except Exception:
        return None


def convert_external_mod(src: Path, out_dir: Path,
                         champions_dir: Path) -> tuple[Path, str] | None:
    """Harici bir mod dosyasini (.fantome veya .wad) bin-swap ile skin0'a cevirir.
    Iki fantome stili de desteklenir:
      - klasor stili:  WAD/<ad>/data/characters/.../skinN.bin  (ayri dosyalar)
      - ham WAD stili: WAD/<ad>.wad.client  (tek blob; yerinde yeniden yazilir)
    (cikti_yolu, sampiyon_adi) doner; cevirecek bir sey yoksa None."""
    if not src.exists():
        print(f"  [!] dosya yok: {src}")
        return None

    table = skin_bin_hash_table()
    ref_cache: dict = {}
    stats = {"swapped": 0, "base": 0}
    out_files: list[tuple[str, bytes]] = []
    seen_targets: set[str] = set()
    primary_champ = ""
    name = src.name.lower()

    try:
        if name.endswith(".wad.client") or name.endswith(".wad"):
            new_wad, champ = _rewrite_wad_skin0(
                src.read_bytes(), src.name, champions_dir, table, ref_cache, stats)
            if new_wad is None:
                _report_no_swap(stats)
                return None
            primary_champ = champ
            out_files.append((f"WAD/{src.name}", new_wad))

        elif name.endswith(".fantome") or name.endswith(".zip"):
            with zipfile.ZipFile(src) as zf:
                entries = [(i.filename, zf.read(i.filename))
                           for i in zf.infolist() if not i.is_dir()]
            for arcname, data in entries:
                if arcname.replace("\\", "/").lower() == "meta/info.json":
                    try:
                        orig = json.loads(data)
                        nm, ver = str(orig.get("Name") or src.stem), str(orig.get("Version") or "1.0.0")
                    except Exception:
                        nm, ver = src.stem, "1.0.0"
                    out_files.append((arcname, fantome_meta(nm, ver).encode("utf-8")))
                    continue
                wadn = _is_raw_wad_entry(arcname, data)
                if wadn:                                   # ham WAD blob
                    new_wad, champ = _rewrite_wad_skin0(
                        data, wadn, champions_dir, table, ref_cache, stats)
                    out_files.append((arcname, new_wad if new_wad is not None else data))
                    if champ and not primary_champ:
                        primary_champ = champ
                    continue
                m = _SKIN_BIN_RE.match(arcname.replace("\\", "/"))
                if m:                                       # klasor stili skin bin
                    champ = _swap_dir_skin_file(
                        arcname, data, m, champions_dir, table, ref_cache,
                        stats, seen_targets, out_files)
                    if champ and not primary_champ:
                        primary_champ = champ
                    continue
                out_files.append((arcname, data))          # diger her sey korunur
        else:
            print("  [!] desteklenmeyen dosya turu (.fantome veya .wad olmali)")
            return None
    except Exception as e:
        print(f"  [!] islenemedi: {e}")
        return None

    if stats["swapped"] == 0:
        _report_no_swap(stats)
        return None

    if not any(a.replace("\\", "/").lower() == "meta/info.json" for a, _ in out_files):
        out_files.insert(0, ("META/info.json", fantome_meta(src.stem).encode("utf-8")))

    # onizleme: modun kendi resmi varsa korunur; yoksa kaynak skin'in splash'i
    if not any(a.replace("\\", "/").lower() == "meta/image.png" for a, _ in out_files):
        source = stats.get("source")
        if source:
            img = _fetch_skin_splash(*source)
            if img:
                out_files.insert(0, ("META/image.png", img))
                print(f"  [+] onizleme eklendi: {source[0]} skin{source[1]} splash")

    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/*?:"<>|]', "", src.stem).strip() or "imported"
    out_path = out_dir / f"{safe}.fantome"
    n = 2
    while out_path.exists():
        out_path = out_dir / f"{safe} ({n}).fantome"
        n += 1

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
        for arcname, data in out_files:
            zf.writestr(arcname, data)

    print(f"\n  ✓ {stats['swapped']} skin -> skin0,  {len(out_files)} dosya paketlendi")
    print(f"  -> {out_path}")
    return out_path, primary_champ


def _swap_dir_skin_file(arcname, data, m, champions_dir, table, ref_cache,
                        stats, seen_targets, out_files) -> str:
    """Klasor-stili .fantome icindeki tek bir skinN.bin dosyasini skin0'a cevirir.
    out_files'a ekler; primary champ adi veya '' doner."""
    champ = m.group("champ").lower()
    num   = int(m.group("num"))
    norm  = arcname.replace("\\", "/")
    if num == 0:
        out_files.append((arcname, data))
        stats["base"] += 1
        return ""
    wadn = m.group("pre")[4:-1] if m.group("pre") else ""   # 'wad/<ad>/' -> '<ad>'
    gw = (_find_game_wad_by_name(champions_dir, wadn) if wadn
          else _find_game_wad_by_char(champions_dir, champ))
    s0_bin, scdp_h, rr_h = _ref_cached(ref_cache, gw, champ, table)
    if not scdp_h:
        if not gw:
            print(f"  [!] {champ}: oyun WAD'i yok, skin{num} cevrilemedi")
        out_files.append((arcname, data))
        return ""
    target = norm[:m.start("num") - 4] + "skin0.bin"
    if target.lower() in seen_targets:
        print(f"  [!] {champ}: birden fazla skin skin0'a denk geldi, skin{num} atlandi")
        out_files.append((arcname, data))
        return ""
    try:
        skin_bin = _read_bin(data)
        patched  = _patch_bin(champ, skin_bin, s0_bin, scdp_h, rr_h)
    except Exception as e:
        print(f"  [!] {champ} skin{num}: patch hatasi ({e}), atlandi")
        out_files.append((arcname, data))
        return ""
    seen_targets.add(target.lower())
    out_files.append((target, patched))
    print(f"  [+] {champ} skin{num} -> skin0")
    stats["swapped"] += 1
    champ_proper = gw.name.split(".", 1)[0] if gw else champ.capitalize()
    stats.setdefault("source", (champ_proper, num))
    return champ_proper


def _report_no_swap(stats: dict) -> None:
    if stats["base"]:
        print("  [i] Dosya zaten temel skini (skin0) hedefliyor; cevrilecek skinN yok.")
    else:
        print("  [!] Cevrilecek skin bin'i bulunamadi.")


def import_mod_mode(champions_dir: Path, out_dir: Path) -> None:
    print("\n  " + "═" * 64)
    print("   FANTOME / WAD AKTAR  ->  skin0'a cevir")
    print("  " + "═" * 64)
    print("  Harici bir .fantome veya .wad dosyasinin yolunu yapistir.")
    print("  Bin-swap ile skinN -> skin0 yapilir, sonuc /Extracted'e .fantome olur.")
    print("  (Surukle-birak da calisir; tirnak otomatik temizlenir.)")
    while True:
        raw = input("\n  Dosya yolu ('geri' = menu): ").strip()
        if raw.lower() in ("geri", "back", "b", ""):
            return
        path = Path(raw.strip().strip('"').strip("'"))
        if not path.exists():
            print(f"  [!] bulunamadi: {path}")
            continue
        result = convert_external_mod(path, out_dir, champions_dir)
        if result and CONFIG.get("ltk_auto"):
            out_path, champ = result
            maybe_ltk_import([(out_path, champ)])


# ----------------------------------------------------------------------------
#  Arama / secim yardimcilari
# ----------------------------------------------------------------------------
def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def list_champ_keys(champions_dir: Path) -> list[str]:
    # "_" iceren WAD'lar gercek sampiyon degil (Ruby_*/Strawberry_* = oyun-modu
    # yardimci karakterleri); bunlari ele.
    return sorted(
        w.name.split(".", 1)[0]
        for w in champions_dir.glob("*.wad.client")
        if w.name.count(".") == 2 and w.name.split(".", 1)[1] == "wad.client"
        and "_" not in w.name.split(".", 1)[0]
    )


def match_champion(name: str, all_champs: list[str]) -> tuple[str | None, list[str]]:
    """(champ_key, oneriler) doner. champ_key None ise oneriler doldurulur."""
    norm_q = normalize(name)
    for c in all_champs:
        if normalize(c) == norm_q:
            return c, []
    partial = [c for c in all_champs if norm_q and norm_q in normalize(c)]
    if len(partial) == 1:
        return partial[0], []
    if len(partial) > 1:
        return None, partial
    return None, difflib.get_close_matches(name, all_champs, n=3, cutoff=0.4)


def parse_champ_csv(line: str, all_champs: list[str]) -> tuple[set[str], list[str]]:
    """Virgulle ayrilmis sampiyon adlarini cozer.
    (cozulenler, cozulemeyenler-oneriyle) doner."""
    resolved: set[str] = set()
    bad: list[str] = []
    for q in (x.strip() for x in line.split(",")):
        if not q:
            continue
        champ, alts = match_champion(q, all_champs)
        if champ:
            resolved.add(champ)
        else:
            bad.append(q + (f" (belki: {', '.join(alts)})" if alts else ""))
    return resolved, bad


def parse_selection(sel: str, max_n: int) -> list[int] | None:
    sel = sel.strip()
    try:
        if "," in sel:
            return [int(x.strip())-1 for x in sel.split(",") if x.strip()]
        if "-" in sel:
            a, b = sel.split("-", 1)
            return list(range(int(a.strip())-1, int(b.strip())))
        return [int(sel)-1]
    except ValueError:
        return None


_KIND_RANK = {"skin": 0, "form": 1, "chroma": 2}
_ALL_RE = re.compile(r"(\*|\b(?:all|hepsi|hepsini|tum|tumu|tümü)\b)\s*$", re.IGNORECASE)


def _search_text(s: dict) -> str:
    parts = [s.get("display", ""), s.get("parent_name", ""), s.get("color", "")]
    return re.sub(r"[^a-z0-9]+", "", " ".join(p for p in parts if p).lower())


def search_skins(query: str, skin_list: list[dict]) -> list[tuple]:
    """Fuzzy arama. Her token, skin'in (isim + parent isim + renk) metninde
    aranir. Sonuc: once 'skin', sonra 'form', en son 'chroma'; esitlikte daha
    kisa isim once."""
    tokens = [t for t in re.sub(r"[^a-z0-9]+", " ", query.lower()).split() if t]
    if not tokens:
        return []
    matched = []
    for s in skin_list:
        hay = _search_text(s)
        if all(tok in hay for tok in tokens):
            disp = re.sub(r"[^a-z0-9]+", "", s.get("display", "").lower())
            key = (_KIND_RANK.get(s.get("kind"), 3), len(disp), len(hay))
            matched.append((key, s))
    matched.sort(key=lambda x: x[0])
    return matched


def suggest_skins(query: str, skin_list: list[dict], n: int = 4) -> list[str]:
    names: list[str] = []
    for s in skin_list:
        names.append(s["display"])
        if s.get("parent_name"):
            names.append(s["parent_name"])
    uniq = list(dict.fromkeys(names))
    out = difflib.get_close_matches(query, uniq, n=n, cutoff=0.4)
    if not out:
        # token bazli partial fallback
        q = normalize(query)
        out = [nm for nm in uniq if q and q in normalize(nm)][:n]
    return out


def _split_all_flag(query: str) -> tuple[bool, str]:
    m = _ALL_RE.search(query)
    if m:
        return True, query[:m.start()].strip()
    return False, query.strip()


def find_best(query: str, skin_list: list[dict]) -> tuple[dict | None, list[tuple], bool]:
    want_all, q = _split_all_flag(query)
    if not q:
        return None, [], want_all
    matched = search_skins(q, skin_list)
    if not matched:
        return None, [], want_all
    best = matched[0][1]
    unambiguous = len(matched) == 1 or matched[0][0] < matched[1][0]
    return (best if unambiguous else None), matched, want_all


def expand_family(base: dict, skin_list: list[dict]) -> list[dict]:
    """base skin + tum chroma/form'larini doner. base bir chroma ise once parent
    skin'e cikar."""
    if base.get("kind") != "skin" and base.get("parent_num") is not None:
        parent = next((s for s in skin_list if s.get("num") == base["parent_num"]), None)
        if parent:
            base = parent
    base_num = base.get("num")
    base_disp = base.get("display", "").lower()
    fam = [base]
    for s in skin_list:
        if s is base:
            continue
        if s.get("parent_num") == base_num or s.get("parent_name", "").lower() == base_disp:
            fam.append(s)
    seen, out = set(), []
    for s in fam:
        if s["num"] in seen:
            continue
        seen.add(s["num"])
        out.append(s)
    return out


# ----------------------------------------------------------------------------
#  LTK (League Toolkit) entegrasyonu
# ----------------------------------------------------------------------------
def ltk_dir() -> Path | None:
    """LTK kutuphane klasorunu bulur (config > AppData otomatik)."""
    p = str(CONFIG.get("ltk") or "").strip()
    if p and (Path(p) / "library.json").exists():
        return Path(p)
    appdata = os.environ.get("APPDATA")
    if appdata:
        cand = Path(appdata) / "dev.leaguetoolkit.manager"
        if (cand / "library.json").exists():
            return cand
    return None


def _ltk_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ltk-manager.exe"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return "ltk-manager.exe" in out.lower()
    except Exception:
        return False


def _ltk_watcher_enabled() -> bool:
    """LTK'nin 'Library watcher'i acik mi? (settings.json -> watcherEnabled)
    Acikken LTK, library.json degisimini gorup modlari canli hot-reload eder;
    o zaman LTK'yi kapatmadan ekleyebiliriz."""
    base = ltk_dir()
    if not base:
        return False
    try:
        s = json.loads((base / "settings.json").read_text(encoding="utf-8"))
        return bool(s.get("watcherEnabled"))
    except Exception:
        return False


def _atomic_write_json(path: Path, data) -> None:
    """JSON'u once .tmp'ye yazip os.replace ile yerine koyar. Boylece LTK'nin
    izleyicisi (notify-debouncer) tek temiz event gorur ve LTK asla yari
    yazilmis library.json okumaz (atomik degis-tokus)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def ltk_import(items: list[tuple[Path, str]]) -> tuple[int, int]:
    """(fantome_yolu, klasor_adi) listesini LTK kutuphanesine ekler:
    archives/<id>.fantome + mods/<id>/mod.config.json + library.json kaydi.
    Ayni isimli mod zaten varsa atlanir. (eklenen, atlanan) doner."""
    base = ltk_dir()
    if not base:
        return 0, len(items)
    lib_path = base / "library.json"
    (base / "archives").mkdir(exist_ok=True)
    (base / "mods").mkdir(exist_ok=True)

    slugify = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

    def read_lib() -> dict | None:
        try:
            return json.loads(lib_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [LTK] library.json okunamadi: {e}")
            return None

    # --- 1) Mevcut sluglari oku (ayni skini ikinci kez eklememek icin) ----
    lib0 = read_lib()
    if lib0 is None:
        return 0, len(items)
    existing: set[str] = set()
    for m in lib0.get("mods", []):
        cfg = base / "mods" / str(m.get("id", "")) / "mod.config.json"
        try:
            existing.add(json.loads(cfg.read_text(encoding="utf-8")).get("name", ""))
        except Exception:
            pass

    # --- 2) Dosyalari diske yaz, eklenecek kayitlari topla -----------------
    #     (library.json'a HENUZ dokunmuyoruz; LTK acikken yazma penceresini
    #      mumkun oldugunca kisa tutmak icin merge+yazma en sona birakildi.)
    pending: list[tuple[str, str]] = []   # (mod_id, folder_name)
    skipped = 0
    for fantome, folder_name in items:
        try:
            with zipfile.ZipFile(fantome) as zf:
                info = json.loads(zf.read("META/info.json"))
        except Exception as e:
            print(f"  [LTK] okunamadi, atlandi: {fantome.name} ({e})")
            skipped += 1
            continue
        display = str(info.get("Name") or fantome.stem)
        slug = slugify(fantome.stem) or slugify(display)
        if slug in existing:
            skipped += 1
            continue
        mid = str(uuid.uuid4())
        shutil.copy2(fantome, base / "archives" / f"{mid}.fantome")
        mdir = base / "mods" / mid
        mdir.mkdir(parents=True, exist_ok=True)
        author = str(info.get("Author") or "").strip()
        (mdir / "mod.config.json").write_text(json.dumps({
            "name": slug,
            "display_name": display,
            "version": str(info.get("Version") or "1.0.0"),
            "description": str(info.get("Description") or ""),
            "authors": [author] if author else [],
            "layers": [{"name": "base", "priority": 0,
                        "description": "Base layer of the mod"}],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        existing.add(slug)
        pending.append((mid, folder_name))

    if not pending:
        return 0, skipped

    # --- 3) library.json'u TAZE oku (LTK acikken arada yazmis olabilir) ----
    #     ve yeni kayitlari onun ustune ekle; boylece LTK'nin o sirada
    #     yaptigi degisiklikleri ezmeyiz.
    lib = read_lib() or lib0
    mods    = lib.setdefault("mods", [])
    folders = lib.setdefault("folders", [])
    order   = lib.setdefault("folderOrder", [])
    root = next((f for f in folders if f.get("id") == "root"), None)
    if root is None:
        root = {"id": "root", "name": "", "modIds": []}
        folders.insert(0, root)
    if "root" not in order:
        order.insert(0, "root")

    def folder_for(name: str) -> dict:
        for f in folders:
            if str(f.get("name", "")).lower() == name.lower():
                return f
        f = {"id": str(uuid.uuid4()), "name": name, "modIds": []}
        folders.append(f)
        order.append(f["id"])
        return f

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    have = {str(m.get("id")) for m in mods}
    for mid, folder_name in pending:
        if mid in have:        # teorik cakisma; atla
            continue
        mods.append({"id": mid, "installedAt": now, "format": "fantome"})
        target = folder_for(folder_name) if folder_name else root
        target.setdefault("modIds", []).append(mid)

    # --- 4) Atomik yaz: izleyici tek temiz event gorur, LTK yari okumaz ----
    try:
        shutil.copy2(lib_path, lib_path.with_suffix(".json.bak"))
    except Exception:
        pass
    _atomic_write_json(lib_path, lib)
    return len(pending), skipped


_LTK_SESSION_OK: bool | None = None  # None=henuz sorulmadi, False=bu oturum atla


def maybe_ltk_import(built: list[tuple[Path, str]]) -> None:
    """ltk_auto acik ise build edilen dosyalari LTK'ya klasorleriyle ekler."""
    global _LTK_SESSION_OK
    if not CONFIG.get("ltk_auto") or not built:
        return
    if not ltk_dir():
        print("  [LTK] kutuphane bulunamadi; Ayarlar'dan LTK klasorunu girin.")
        return

    running = _ltk_running()
    watcher = _ltk_watcher_enabled() if running else False

    # LTK acik AMA watcher kapali: eklediklerimizi gormez / ustune yazabilir.
    # En guvenlisi kapatmak; ya da LTK ayarlarindan 'Library watcher'i acmak.
    if running and not watcher:
        if _LTK_SESSION_OK is False:
            return
        if _LTK_SESSION_OK is None:
            print("  [LTK] LTK Manager acik ve 'Library watcher' KAPALI.")
            print("        Acikken eklenirse LTK degisikligi gormez ve kendi")
            print("        listesini ustune yazabilir. Iki temiz secenek:")
            print("          - LTK'yi kapat, sonra ekle  (klasik), VEYA")
            print("          - LTK ayarlarindan 'Library watcher'i ac  -> o zaman")
            print("            KAPATMADAN canli eklenir (onerilen).")
            try:
                ans = input("        Yine de simdi eklensin mi? (e/h): ").strip().lower()
            except EOFError:
                ans = "h"   # non-interaktif (GUI / CLI --import-mod): guvenli taraf
            _LTK_SESSION_OK = ans == "e"
            if not _LTK_SESSION_OK:
                print("  [LTK] bu oturumda import atlanacak (dosyalar diskte duruyor).")
                return

    added, skipped = ltk_import(built)
    folder_names = ", ".join(dict.fromkeys(f for _, f in built if f))
    print(f"  [LTK] {added} mod eklendi"
          + (f", {skipped} atlandi (zaten ekli)" if skipped else "")
          + (f"  ->  klasor: {folder_names}" if folder_names else ""))
    if added:
        if running and watcher:
            print("  [LTK] 'Library watcher' acik -> LTK'da CANLI belirdi "
                  "(kapatmaya gerek yok).")
        elif running:
            print("  [LTK] LTK'yi yeniden baslatinca listede gorunur.")
        else:
            print("  [LTK] LTK'yi acinca listede gorunur.")


# ----------------------------------------------------------------------------
#  Build orkestrasyon
# ----------------------------------------------------------------------------
def build_many(builder: SkinBuilder, champ_key: str, to_build: list[dict]) -> tuple[int, int]:
    print(f"\n  Build ediliyor ({len(to_build)} oge)...")
    ok = fail = 0
    built: list[tuple[Path, str]] = []
    for s in to_build:
        try:
            out = builder.build_skin(champ_key, s)
        except Exception as e:
            out = None
            print(f"  [!] Istisna: {s.get('display')} -> {e}")
        if out:
            block = f"  {ansi_block(s['color'].lower())}" if s["color"] else ""
            print(f"  [+] \033[92m{out.name}\033[0m{block}")
            built.append((out, champ_key))
            ok += 1
        else:
            print(f"  [!] Hata: skin{s['num']} ({s['display']})")
            fail += 1
    print(f"\n  ✓ {ok} basarili" + (f", {fail} hatali" if fail else "") +
          f"\n  -> {builder.output_dir}\n")
    maybe_ltk_import(built)
    return ok, fail


# ----------------------------------------------------------------------------
#  Interaktif UI
# ----------------------------------------------------------------------------
def pick_champion(champions_dir: Path) -> str | None:
    all_champs = list_champ_keys(champions_dir)
    while True:
        q = input("\n  Champion adi ('geri' = menu): ").strip()
        if q.lower() in ("geri", "back", "b", ""):
            return None
        champ, alts = match_champion(q, all_champs)
        if champ:
            return champ
        if alts:
            print(f"  [!] '{q}' net degil. Belki: {', '.join(alts)}")
        else:
            print(f"  [!] '{q}' bulunamadi.")


def show_skin_list(champ_key: str, skin_list: list[dict]) -> None:
    W = 64
    print(f"\n  ╔{'═'*W}╗")
    print(f"  ║  {champ_key.upper():<{W-3}}║")
    print(f"  ║  {'Ctrl+Click isim -> CDragon Splash':<{W-3}}║")
    print(f"  ╠{'═'*W}╣")

    max_n     = max((len(s["display"]) for s in skin_list), default=10)
    last_kind = None

    for i, s in enumerate(skin_list, 1):
        if last_kind and last_kind != s["kind"]:
            print(f"  ╠{'─'*W}╣")
        last_kind = s["kind"]

        name  = s["display"].ljust(max_n)
        link  = hyperlink(name, s.get("splash"))
        color = s["color"]
        block = ansi_block(color.lower()) if color else "\033[90m──\033[0m"
        if color:
            label = f"\033[93m{color}\033[0m"
        elif s["kind"] == "form":
            label = "\033[35mform\033[0m"
        else:
            label = "\033[36mskin\033[0m"
        print(f"  ║ [{i:>2}] {link} {block} {label}")

    all_n = len(skin_list) + 1
    print(f"  ╠{'═'*W}╣")
    print(f"  ║ [{all_n:>2}] Tumunu Build Et{'':<{W-20}}║")
    print(f"  ║ [ 0] Geri{'':<{W-10}}║")
    print(f"  ╚{'═'*W}╝")


def parse_skin_selection(sel: str, skin_list: list[dict]) -> list[dict] | None:
    """Skin listesinden secim parse eder. Numara (1 / 1,3 / 2-4) veya isim
    kabul eder. Eslesme yoksa/hata varsa None, kullanici iptal ederse []."""
    if not sel:
        return None
    all_n = len(skin_list) + 1
    if sel == str(all_n):
        return skin_list[:]

    if re.fullmatch(r"[0-9]+(?:\s*[,\-]\s*[0-9]+)*", sel):
        indices = parse_selection(sel, len(skin_list))
        if indices is None:
            print("  [!] Gecersiz secim.")
            return None
        out: list[dict] = []
        for idx in indices:
            if 0 <= idx < len(skin_list):
                out.append(skin_list[idx])
            else:
                print(f"  [!] {idx+1} gecersiz numara, atlandi.")
        return out

    best, matched, want_all = find_best(sel, skin_list)
    if not matched:
        sug = suggest_skins(_split_all_flag(sel)[1] or sel, skin_list)
        print(f"  [!] '{sel}' ile eslesen skin yok."
              + (f"  Belki: {', '.join(sug)}" if sug else ""))
        return None

    if want_all:
        anchor = best or matched[0][1]
        out = expand_family(anchor, skin_list)
        fam_name = anchor["display"] if anchor.get("kind") == "skin" else anchor.get("parent_name", anchor["display"])
        print(f"  -> \033[92m{fam_name}\033[0m + chromalar ({len(out)} oge)")
        return out

    if best:
        print(f"  -> Secildi: \033[92m{best['display']}\033[0m"
              + (f" ({best['color']})" if best["color"] else ""))
        if len(matched) > 1:
            others = ", ".join(m[1]["display"] for m in matched[1:4])
            print(f"     (diger eslesmeler: {others}"
                  + (" ..." if len(matched) > 4 else "") + ")")
        return [best]

    print(f"\n  '{sel}' icin birden fazla eslesme:")
    narrowed = [m[1] for m in matched]
    for i, s in enumerate(narrowed, 1):
        if s["color"]:
            extra = f" - {s['color']}"
        elif s["kind"] != "skin":
            extra = f" [{s['kind']}]"
        else:
            extra = ""
        print(f"    [{i:>2}] {s['display']}{extra}")
    sub = input("  Numara sec (1 / 1,3 / 2-4, bos=iptal): ").strip()
    if not sub:
        return []
    idxs = parse_selection(sub, len(narrowed))
    if idxs is None:
        print("  [!] Gecersiz secim.")
        return None
    out = []
    for idx in idxs:
        if 0 <= idx < len(narrowed):
            out.append(narrowed[idx])
        else:
            print(f"  [!] {idx+1} gecersiz numara, atlandi.")
    return out


def process_champion(builder: SkinBuilder, champ_key: str) -> None:
    print(f"\n  [{champ_key}] Skin listesi hazirlaniyor...")
    skin_list = builder.list_skins(champ_key)
    if not skin_list:
        print("  [!] Skin bulunamadi.")
        return

    while True:
        show_skin_list(champ_key, skin_list)
        sel = input("\n  Secim (numara: 1 / 1,3,5 / 2-6  |  isim: skin / skin chroma / skin *): ").strip()
        if sel == "0":
            break
        to_build = parse_skin_selection(sel, skin_list)
        if not to_build:
            continue
        build_many(builder, champ_key, to_build)


# ----------------------------------------------------------------------------
#  Multi-extract (coklu sampiyon/skin queue)
# ----------------------------------------------------------------------------
def select_skins_for_queue(champ_key: str, skin_list: list[dict],
                           queue: list[tuple]) -> None:
    """Bir sampiyon icin skin secimi queue'ya ekler (build etmez)."""
    while True:
        show_skin_list(champ_key, skin_list)
        in_queue = sum(1 for q in queue if q[0] == champ_key)
        print(f"\n  Queue: {len(queue)} oge ({in_queue} bu sampiyondan)")
        sel = input("  Secim (queue'ya ekle  |  0=bitir): ").strip()
        if sel == "0":
            return
        to_add = parse_skin_selection(sel, skin_list)
        if not to_add:
            continue
        added = skipped = 0
        for s in to_add:
            key = (champ_key, s["num"])
            if any((q[0], q[1]["num"]) == key for q in queue):
                skipped += 1
                continue
            queue.append((champ_key, s))
            added += 1
        msg = f"  [+] {added} eklendi"
        if skipped:
            msg += f", {skipped} zaten queue'da"
        msg += f"  |  toplam: {len(queue)}"
        print(msg)


def show_multi_queue(queue: list[tuple]) -> None:
    if not queue:
        print("    (queue bos)")
        return
    by_champ: dict[str, list[tuple]] = {}
    for i, (ck, s) in enumerate(queue, 1):
        by_champ.setdefault(ck, []).append((i, s))
    for ck, items in by_champ.items():
        print(f"    \033[96m{ck}\033[0m ({len(items)})")
        for i, s in items:
            extra = ""
            if s.get("color"):
                extra = f"  {ansi_block(s['color'].lower())} \033[93m{s['color']}\033[0m"
            elif s.get("kind") == "form":
                extra = "  \033[35m[form]\033[0m"
            print(f"      [{i:>2}] {s['display']}{extra}")


def build_multi_queue(queue: list[tuple],
                      builders_cache: dict[str, SkinBuilder]) -> tuple[int, int]:
    print(f"\n  Build ediliyor ({len(queue)} oge)...")
    ok = fail = 0
    built: list[tuple[Path, str]] = []
    for champ_key, skin_info in queue:
        builder = builders_cache.get(champ_key)
        if not builder:
            print(f"  [!] {champ_key}: builder yok, atlandi")
            fail += 1
            continue
        try:
            out = builder.build_skin(champ_key, skin_info)
        except Exception as e:
            out = None
            print(f"  [!] Istisna: {champ_key} {skin_info.get('display')} -> {e}")
        if out:
            block = f"  {ansi_block(skin_info['color'].lower())}" if skin_info.get("color") else ""
            print(f"  [+] {champ_key:>12} | \033[92m{out.name}\033[0m{block}")
            built.append((out, champ_key))
            ok += 1
        else:
            print(f"  [!] Hata: {champ_key} skin{skin_info['num']} ({skin_info.get('display')})")
            fail += 1
    print(f"\n  ✓ {ok} basarili" + (f", {fail} hatali" if fail else "") +
          f"\n  -> {CONFIG['out']}\n")
    maybe_ltk_import(built)
    return ok, fail


def split_champ_and_skin(entry: str, all_champs: list[str]) -> tuple[str | None, str]:
    """'God Fist Lee Sin' -> ('LeeSin', 'God Fist'). Champion adini metin icinde
    arar (en uzun kelime-grubu eslesmesi), kalan kelimeler skin sorgusu olur."""
    words = entry.split()
    if not words:
        return None, ""
    norm_map = {normalize(c): c for c in all_champs}
    best = None  # (start, end, champ_key)
    n = len(words)
    for i in range(n):
        for j in range(i + 1, n + 1):
            span = normalize("".join(words[i:j]))
            if span in norm_map:
                if best is None or (j - i) > (best[1] - best[0]):
                    best = (i, j, norm_map[span])
    if not best:
        return None, entry.strip()
    i, j, champ = best
    skin_q = " ".join(words[:i] + words[j:]).strip()
    return champ, skin_q


def _get_builder(champ: str, champions_dir: Path, out_dir: Path,
                 builders_cache: dict[str, SkinBuilder],
                 shared_names: set[str]) -> SkinBuilder:
    if champ not in builders_cache:
        print(f"  [{champ}] Katalog yukleniyor...")
        _, catalog, chroma_meta, champ_id = fetch_catalog(champ)
        b = SkinBuilder(champions_dir, out_dir, catalog, chroma_meta, champ_id)
        b._used_names = shared_names
        builders_cache[champ] = b
    return builders_cache[champ]


def resolve_bulk_entries(line: str, all_champs: list[str], champions_dir: Path,
                         out_dir: Path, builders_cache: dict[str, SkinBuilder],
                         shared_names: set[str]) -> tuple[list[tuple], list[str]]:
    """Virgulle ayrilmis 'Skin Adi Champion' girdilerini cozer.
    Or: 'Winter Wonder Zeri, Shockblade Zed Ruby, God Fist Lee Sin'.
    (eklenecekler, hatalar) doner; eklenecekler: list[(champ_key, skin_info)]."""
    resolved: list[tuple[str, dict]] = []
    errors: list[str] = []
    for entry in (e.strip() for e in line.split(",")):
        if not entry:
            continue
        champ, skin_q = split_champ_and_skin(entry, all_champs)
        if not champ:
            sug = ", ".join(difflib.get_close_matches(entry, all_champs, n=3, cutoff=0.4))
            errors.append(f"'{entry}': champion bulunamadi"
                          + (f" (belki: {sug})" if sug else ""))
            continue
        builder = _get_builder(champ, champions_dir, out_dir, builders_cache, shared_names)
        skin_list = builder.list_skins(champ)
        if not skin_list:
            errors.append(f"'{entry}': {champ} icin skin yok")
            continue
        if not skin_q:
            resolved.extend((champ, s) for s in skin_list)
            continue
        best, matched, want_all = find_best(skin_q, skin_list)
        if not matched:
            sug = suggest_skins(skin_q, skin_list)
            errors.append(f"'{entry}': '{skin_q}' eslesmedi"
                          + (f" (belki: {', '.join(sug)})" if sug else ""))
            continue
        if want_all:
            anchor = best or matched[0][1]
            resolved.extend((champ, s) for s in expand_family(anchor, skin_list))
        elif best:
            resolved.append((champ, best))
        else:
            pick = matched[0][1]
            resolved.append((champ, pick))
            others = ", ".join(m[1]["display"] for m in matched[1:4])
            errors.append(f"'{entry}': belirsiz, '{pick['display']}' secildi"
                          + (f" (digerleri: {others})" if others else ""))
    return resolved, errors


def _enqueue(queue: list[tuple], items: list[tuple]) -> tuple[int, int]:
    """items'i queue'ya ekler, mevcut (champ, num) ciftlerini atlar."""
    added = skipped = 0
    existing = {(q[0], q[1]["num"]) for q in queue}
    for champ_key, s in items:
        key = (champ_key, s["num"])
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        queue.append((champ_key, s))
        added += 1
    return added, skipped


def multi_extract_mode(champions_dir: Path, out_dir: Path) -> None:
    """Coklu sampiyon / skin secip tek seferde build eder."""
    queue: list[tuple[str, dict]] = []
    builders_cache: dict[str, SkinBuilder] = {}
    shared_names: set[str] = set()
    all_champs = list_champ_keys(champions_dir)

    while True:
        print("\n  " + "═" * 64)
        print(f"   MULTI-EXTRACT   ({len(queue)} oge queue'da)")
        print("  " + "═" * 64)
        show_multi_queue(queue)
        print("  " + "─" * 64)
        print("  [1] Champion ekle / skin sec")
        print("  [2] Toplu yaz (virgullu: 'Winter Wonder Zeri, God Fist Lee Sin')")
        print(f"  [3] Build et" + (f"  ({len(queue)} oge)" if queue else ""))
        print("  [4] Queue'dan sil")
        print("  [5] Queue'yu temizle")
        print("  [0] Geri")
        choice = input("  > ").strip()

        if choice == "0":
            if queue:
                ans = input(f"  Queue'da {len(queue)} oge var, kaybedilecek. Cikilsin mi? (e/h): ").strip().lower()
                if ans != "e":
                    continue
            return

        elif choice == "1":
            champ = pick_champion(champions_dir)
            if not champ:
                continue
            builder = _get_builder(champ, champions_dir, out_dir, builders_cache, shared_names)
            skin_list = builder.list_skins(champ)
            if not skin_list:
                print("  [!] Skin bulunamadi.")
                continue
            select_skins_for_queue(champ, skin_list, queue)

        elif choice == "2":
            line = input("\n  Skinler (virgulle ayir):\n  > ").strip()
            if not line:
                continue
            resolved, errors = resolve_bulk_entries(
                line, all_champs, champions_dir, out_dir, builders_cache, shared_names)
            if errors:
                print("  Uyarilar:")
                for e in errors:
                    print(f"    [!] {e}")
            added, skipped = _enqueue(queue, resolved)
            print(f"  [+] {added} eklendi"
                  + (f", {skipped} zaten queue'da" if skipped else "")
                  + f"  |  toplam: {len(queue)}")
            if added:
                ans = input("  Hemen build edilsin mi? (e/h): ").strip().lower()
                if ans == "e":
                    build_multi_queue(queue, builders_cache)
                    c2 = input("  Queue temizlensin mi? (E/h): ").strip().lower()
                    if c2 in ("", "e"):
                        queue.clear()
                        shared_names.clear()

        elif choice == "3":
            if not queue:
                print("  [!] Queue bos.")
                continue
            build_multi_queue(queue, builders_cache)
            ans = input("  Queue temizlensin mi? (E/h): ").strip().lower()
            if ans in ("", "e"):
                queue.clear()
                shared_names.clear()

        elif choice == "4":
            if not queue:
                print("  [!] Queue bos.")
                continue
            sel = input("  Silinecek numara(lar) (1 / 1,3 / 2-4): ").strip()
            idxs = parse_selection(sel, len(queue))
            if idxs is None:
                print("  [!] Gecersiz secim.")
                continue
            for idx in sorted(set(idxs), reverse=True):
                if 0 <= idx < len(queue):
                    rm = queue.pop(idx)
                    print(f"  [-] {rm[0]} - {rm[1]['display']}")

        elif choice == "5":
            if not queue:
                print("  [!] Queue zaten bos.")
                continue
            queue.clear()
            shared_names.clear()
            print("  [+] Queue temizlendi.")

        else:
            print("  [!] Gecersiz secim.")


# ----------------------------------------------------------------------------
#  Extract All (tum sampiyonlar, sampiyon basina klasor)
# ----------------------------------------------------------------------------
def run_extract_all(champions_dir: Path, out_dir: Path, only_skins: bool,
                    exclude: set[str] | None = None) -> int:
    """Tum sampiyonlari tarar, her birini kendi klasorune build eder
    (or. Extracted/Jhin/*.fantome). Var olan klasorler atlanir, yani islem
    yarida kesilirse tekrar calistirilarak kaldigi yerden devam edilir."""
    all_champs = list_champ_keys(champions_dir)
    if not all_champs:
        print("  [!] Champion WAD'i bulunamadi.")
        return 2
    if exclude:
        before = len(all_champs)
        all_champs = [c for c in all_champs if c not in exclude]
        print(f"  · {before - len(all_champs)} sampiyon haric tutuldu: "
              + ", ".join(sorted(exclude)))
        if not all_champs:
            print("  [!] Haric tutma sonrasi sampiyon kalmadi.")
            return 2

    t0 = time.time()
    total_ok = total_fail = done_skip = 0
    for i, champ in enumerate(all_champs, 1):
        champ_dir = out_dir / champ
        print(f"\n  ━━ [{i}/{len(all_champs)}] {champ} " + "━" * max(1, 44 - len(champ)))
        try:
            _, catalog, chroma_meta, champ_id = fetch_catalog(champ)
        except (SystemExit, Exception) as e:
            print(f"    [!] katalog hatasi, atlandi: {e}")
            total_fail += 1
            continue
        builder = SkinBuilder(champions_dir, champ_dir, catalog, chroma_meta, champ_id)
        try:
            skin_list = builder.list_skins(champ)
        except Exception as e:
            print(f"    [!] WAD okunamadi, atlandi: {e}")
            total_fail += 1
            continue
        if only_skins:
            skin_list = [s for s in skin_list if s.get("kind") == "skin"]
        if not skin_list:
            print("    · cikarilacak skin yok")
            continue
        existing = len(list(champ_dir.glob("*.fantome"))) if champ_dir.exists() else 0
        if existing >= len(skin_list):
            print(f"    · zaten cikarilmis ({existing} dosya), atlandi")
            done_skip += 1
            continue
        ok, fail = build_many(builder, champ, skin_list)
        total_ok += ok
        total_fail += fail

    mins = (time.time() - t0) / 60
    print(f"\n  ══ TAMAMLANDI ══  {total_ok} basarili, {total_fail} hatali"
          + (f", {done_skip} sampiyon onceden hazirdi" if done_skip else "")
          + f"  ({mins:.1f} dk)")
    print(f"  -> {out_dir}")
    print("  LTK: cikti klasorundeki .fantome'lari import et; arama kutusuna")
    print("  sampiyon adini yazinca o sampiyonun tum skinleri listelenir.\n")
    return 0 if total_fail == 0 else 1


def extract_all_mode(champions_dir: Path, out_dir: Path) -> None:
    all_champs = list_champ_keys(champions_dir)
    print(f"\n  {len(all_champs)} sampiyon bulundu. Her biri kendi klasorune yazilir:")
    print(f"    {out_dir}\\<Champion>\\<skin>.fantome")
    print("  [1] Hepsi (skin + chroma + form)")
    print("  [2] Sadece skinler (chroma haric)")
    print("  [0] Iptal")
    c = input("  > ").strip()
    if c not in ("1", "2"):
        return

    exclude: set[str] = set()
    line = input("  Haric tutulacak sampiyonlar (virgulle, bos = yok): ").strip()
    if line:
        exclude, bad = parse_champ_csv(line, all_champs)
        for b in bad:
            print(f"    [!] bulunamadi: {b}")
        if bad and not exclude:
            return
        if exclude:
            print(f"    -> haric: {', '.join(sorted(exclude))}")

    ans = input("  Bu islem uzun surer ve binlerce dosya uretir; yarida kesilirse\n"
                "  tekrar baslatinca kaldigi yerden devam eder. Baslasin mi? (e/h): ").strip().lower()
    if ans != "e":
        return
    run_extract_all(champions_dir, out_dir, only_skins=(c == "2"), exclude=exclude)


def show_settings() -> None:
    ltk_path = ltk_dir()
    ltk_show = str(ltk_path) if ltk_path else "bulunamadi (yol girin)"
    auto = "ACIK" if CONFIG.get("ltk_auto") else "KAPALI"
    print(f"\n  1. League Path : {CONFIG['league']}")
    print(f"  2. Output Path : {CONFIG['out']}")
    print(f"  3. League yolunu otomatik bul")
    print(f"  4. LTK klasoru : {ltk_show}")
    print(f"  5. LTK auto-import : {auto}  (build edilenler sampiyon klasoruyle LTK'ya eklenir)")
    print(f"  6. Geri")
    c = input("  Secim: ").strip()
    if c == "1":
        p = input("  Yeni League Path: ").strip()
        if Path(p).exists():
            CONFIG["league"] = p
            save_config()
        else:
            print("  [!] Klasor bulunamadi.")
    elif c == "2":
        p = input("  Yeni Output Path: ").strip()
        CONFIG["out"] = p
        Path(p).mkdir(parents=True, exist_ok=True)
        save_config()
    elif c == "3":
        detected = detect_league_path()
        if detected:
            CONFIG["league"] = detected
            save_config()
            print(f"  [+] Bulundu: {detected}")
        else:
            print("  [!] Otomatik bulunamadi, manuel girin.")
    elif c == "4":
        p = input("  LTK kutuphane klasoru (icinde library.json olmali): ").strip()
        if p and (Path(p) / "library.json").exists():
            CONFIG["ltk"] = p
            save_config()
            print("  [+] LTK yolu kaydedildi.")
        else:
            print("  [!] Gecersiz: library.json bulunamadi.")
    elif c == "5":
        CONFIG["ltk_auto"] = not CONFIG.get("ltk_auto")
        save_config()
        print(f"  [+] LTK auto-import: {'ACIK' if CONFIG['ltk_auto'] else 'KAPALI'}")
        if CONFIG["ltk_auto"] and not ltk_dir():
            print("  [!] LTK kutuphanesi bulunamadi — 4 ile yol girin.")


def show_how_to_use() -> None:
    C = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; D = "\033[90m"; R = "\033[0m"
    line = C + "  " + "─" * 66 + R
    print(f"\n{C}  ╔{'═' * 66}╗{R}")
    print(f"{C}  ║{R}  {Y}NASIL KULLANILIR{R}{' ' * 49}{C}║{R}")
    print(f"{C}  ╚{'═' * 66}╝{R}")

    print(f"  {Y}[1] Champion Sec & Build{R}  — tek sampiyon")
    print(f"      Sampiyon adi yaz, sonra skin listesinden sec:")
    print(f"        numara : {G}3{R}  |  {G}1,3,5{R}  |  {G}2-6{R}")
    print(f"        isim   : {G}skinname{R}  |  {G}skinname ruby{R}  |  {G}skinname *{R} {D}(tum chroma){R}")
    print(f"        {G}<son numara>{R} = tumunu build,   {G}0{R} = geri")
    print(line)

    print(f"  {Y}[2] Multi-Extract{R}  — coklu sampiyon/skin, tek seferde build")
    print(f"      {G}[1]{R} sampiyon ekle & skin sec  {D}(queue'ya atar, baska champ eklenebilir){R}")
    print(f"      {G}[2]{R} toplu yaz: tam isimleri virgulle ayir, hepsi cikar:")
    print(f"          {D}Winter Wonder Zeri, Shockblade Zed Ruby, Headhunter Nidalee, God Fist Lee Sin{R}")
    print(f"      {G}[3]{R} build et   {G}[4]{R} queue'dan sil   {G}[5]{R} temizle")
    print(line)

    print(f"  {Y}[3] Extract All{R}  — tum sampiyonlar, sampiyon basina klasor")
    print(f"      {D}Or. Extracted\\Jhin\\ icinde sadece Jhin skin+chromalari olur.{R}")
    print(f"      {D}Istemedigin sampiyonlari haric tutabilirsin: 'zed, lee sin'.{R}")
    print(f"      {D}Yarida kalirsa tekrar baslat, kaldigi yerden devam eder.{R}")
    print(line)

    print(f"  {Y}[4] Fantome/WAD Aktar{R}  — disaridan mod -> skin0'a cevir")
    print(f"      {D}Indirdigin bir .fantome/.wad'in skinN bin'ini bin-swap ile{R}")
    print(f"      {D}skin0 yapar (temel skini hedefler), /Extracted'e .fantome dokar.{R}")
    print(line)

    print(f"  {Y}[4] Ayarlar{R}  — League / cikti yolu      {Y}[5] Hash Yenile{R}")
    auto = f"{G}ACIK{R}" if CONFIG.get("ltk_auto") else f"{D}KAPALI{R}"
    print(f"      LTK auto-import: {auto} {D}— acikken build edilen her mod,{R}")
    print(f"      {D}LTK icinde sampiyon adli klasore otomatik eklenir (Ayarlar > 5).{R}")
    print(f"  {D}  Cikti klasoru: {CONFIG['out']}{R}")
    print(f"{C}  {'═' * 66}{R}")


def show_menu() -> str:
    print("\n╔═════════════════════════════════════╗")
    print("║   RAHASYA EXTRACTION TOOL  v3       ║")
    print("╠═════════════════════════════════════╣")
    print("║  [1] Champion Sec & Build           ║")
    print("║  [2] Multi-Extract (Coklu Build)    ║")
    print("║  [3] Extract All (Tum Sampiyonlar)  ║")
    print("║  [4] Fantome/WAD Aktar -> skin0     ║")
    print("║  [5] Ayarlar                        ║")
    print("║  [6] Hash Yenile                    ║")
    print("║  [7] Cikis                          ║")
    print("╚═════════════════════════════════════╝")
    return input("  > ").strip()


# ----------------------------------------------------------------------------
#  Non-interaktif CLI modu
# ----------------------------------------------------------------------------
def run_cli(args) -> int:
    champions_dir = Path(CONFIG["league"]) / "Game" / "DATA" / "FINAL" / "Champions"
    if not champions_dir.exists():
        print(f"[!] League klasoru bulunamadi: {champions_dir}")
        return 2

    all_champs = list_champ_keys(champions_dir)
    champ, alts = match_champion(args.champion, all_champs)
    if not champ:
        msg = f"[!] Champion bulunamadi: '{args.champion}'"
        if alts:
            msg += f"  Belki: {', '.join(alts)}"
        print(msg)
        return 2

    patch, catalog, chroma_meta, champ_id = fetch_catalog(champ)
    builder = SkinBuilder(champions_dir, Path(CONFIG["out"]), catalog, chroma_meta, champ_id)
    skin_list = builder.list_skins(champ)
    if not skin_list:
        print("[!] Skin bulunamadi.")
        return 1

    if args.list:
        show_skin_list(champ, skin_list)
        return 0

    if args.all_skins and not args.skin:
        ok, fail = build_many(builder, champ, skin_list)
        return 0 if fail == 0 else 1

    if not args.skin:
        print("[!] --skin <isim> veya --all gerekli (ya da --list).")
        return 2

    best, matched, want_all = find_best(args.skin, skin_list)
    if not matched:
        sug = suggest_skins(_split_all_flag(args.skin)[1] or args.skin, skin_list)
        msg = f"[!] '{args.skin}' ile eslesen skin yok."
        if sug:
            msg += f"  Belki: {', '.join(sug)}"
        print(msg)
        return 1

    if want_all or args.all_skins:
        anchor = best or matched[0][1]
        to_build = expand_family(anchor, skin_list)
    elif best:
        to_build = [best]
    else:
        opts = ", ".join(m[1]["display"] for m in matched[:6])
        print(f"[!] '{args.skin}' belirsiz, netlestir. Eslesmeler: {opts}")
        return 2

    ok, fail = build_many(builder, champ, to_build)
    return 0 if fail == 0 else 1


def main():
    os.system("")

    ap = argparse.ArgumentParser(
        description="Rahasya Extraction Tool - LoL skin/chroma -> .fantome",
        add_help=True,
    )
    ap.add_argument("--league", default=None, help="League of Legends kurulum yolu")
    ap.add_argument("--out", default=None, help="Cikti klasoru")
    ap.add_argument("--champion", default=None, help="Non-interaktif: sampiyon adi")
    ap.add_argument("--skin", default=None, help="Non-interaktif: skin/chroma adi (or. 'skinname ruby')")
    ap.add_argument("--all", dest="all_skins", action="store_true", help="Tum skinleri (veya --skin ile o ailenin tum chromalarini) cikar")
    ap.add_argument("--list", action="store_true", help="Non-interaktif: skin listesini yazdir, cikma")
    ap.add_argument("--extract-all", dest="extract_all", action="store_true",
                    help="Tum sampiyonlari sampiyon-basina klasorlere cikar (LTK toplu import icin)")
    ap.add_argument("--skins-only", dest="skins_only", action="store_true",
                    help="--extract-all ile: chromalari/formlari atla, sadece skinler")
    ap.add_argument("--exclude", default=None,
                    help="--extract-all ile: haric tutulacak sampiyonlar (or. 'zed, lee sin')")
    ap.add_argument("--ltk-import", dest="ltk_import", action="store_true",
                    help="Build edilenleri LTK'ya sampiyon klasoruyle otomatik ekle")
    ap.add_argument("--import-mod", dest="import_mod", default=None,
                    help="Harici .fantome/.wad dosyasini skin0'a cevirip /Extracted'e cikar")
    ap.add_argument("--refresh-hashes", action="store_true", help="Hash tablolarini yenile")
    args, _ = ap.parse_known_args()

    load_config()
    if args.league:
        CONFIG["league"] = args.league
    if args.out:
        CONFIG["out"] = args.out
    if args.ltk_import:
        CONFIG["ltk_auto"] = True
    if not _has_champions(CONFIG["league"]):
        detected = detect_league_path()
        if detected:
            CONFIG["league"] = detected

    headless = bool(args.champion or args.list or args.extract_all or args.import_mod)

    print("=" * 43)
    print("  Rahasya Extraction Tool  v3")
    print("  kick.com/rahasya")
    print("=" * 43)

    load_riot_data()
    load_hashes(args.refresh_hashes)

    if headless:
        if args.import_mod:
            champions_dir = Path(CONFIG["league"]) / "Game" / "DATA" / "FINAL" / "Champions"
            out_dir = Path(CONFIG["out"])
            out_dir.mkdir(parents=True, exist_ok=True)
            res = convert_external_mod(Path(args.import_mod), out_dir, champions_dir)
            if res and CONFIG.get("ltk_auto"):
                maybe_ltk_import([res])
            sys.exit(0 if res else 1)
        if args.extract_all and not args.champion:
            champions_dir = Path(CONFIG["league"]) / "Game" / "DATA" / "FINAL" / "Champions"
            if not champions_dir.exists():
                sys.exit(f"[!] League klasoru bulunamadi: {champions_dir}")
            out_dir = Path(CONFIG["out"])
            out_dir.mkdir(parents=True, exist_ok=True)
            exclude: set[str] = set()
            if args.exclude:
                exclude, bad = parse_champ_csv(args.exclude, list_champ_keys(champions_dir))
                if bad:
                    sys.exit("[!] --exclude cozulemedi: " + "; ".join(bad))
            sys.exit(run_extract_all(champions_dir, out_dir, args.skins_only, exclude))
        sys.exit(run_cli(args))

    show_how_to_use()

    while True:
        champions_dir = Path(CONFIG["league"]) / "Game" / "DATA" / "FINAL" / "Champions"
        out_dir       = Path(CONFIG["out"])
        choice        = show_menu()

        if choice == "1":
            if not champions_dir.exists():
                print(f"\n  [!] League klasoru bulunamadi: {champions_dir}")
                print("  Ayarlar'dan (4) dogru yolu girin ya da otomatik bul.\n")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            champ = pick_champion(champions_dir)
            if not champ:
                continue
            patch, catalog, chroma_meta, champ_id = fetch_catalog(champ)
            builder = SkinBuilder(champions_dir, out_dir, catalog, chroma_meta, champ_id)
            process_champion(builder, champ)

        elif choice == "2":
            if not champions_dir.exists():
                print(f"\n  [!] League klasoru bulunamadi: {champions_dir}")
                print("  Ayarlar'dan (4) dogru yolu girin ya da otomatik bul.\n")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            multi_extract_mode(champions_dir, out_dir)

        elif choice == "3":
            if not champions_dir.exists():
                print(f"\n  [!] League klasoru bulunamadi: {champions_dir}")
                print("  Ayarlar'dan (4) dogru yolu girin ya da otomatik bul.\n")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            extract_all_mode(champions_dir, out_dir)

        elif choice == "4":
            out_dir.mkdir(parents=True, exist_ok=True)
            import_mod_mode(champions_dir, out_dir)

        elif choice == "5":
            show_settings()

        elif choice == "6":
            load_hashes(refresh=True)

        elif choice == "7":
            print("\n  Cikiliyor...\n")
            break

        else:
            print("  [!] Gecersiz secim.")


if __name__ == "__main__":
    main()
