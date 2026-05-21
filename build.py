from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
import re
import difflib
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = Path(__file__).parent.resolve()

# ----- Vendored LtMAO ------------------------------------------------------
LTMAO_SRC = HERE / "_vendor" / "LtMAO" / "src"
if not LTMAO_SRC.exists():
    sys.exit(f"vendored LtMAO not found at {LTMAO_SRC}")
sys.path.insert(0, str(LTMAO_SRC))

WORK_DIR = HERE
os.makedirs(WORK_DIR / "pref" / "hashes" / "cdtb_hashes", exist_ok=True)
os.chdir(WORK_DIR)

from LtMAO import pyRitoFile, hash_helper  # type: ignore
from LtMAO.hash_helper import CDTBHashes, CustomHashes, Storage  # type: ignore
from LtMAO import no_skin  # type: ignore

for _d in (CDTBHashes.local_dir, CustomHashes.local_dir,
           "./pref/hashes/extracted_hashes"):
    os.makedirs(_d, exist_ok=True)

# ----- Config --------------------------------------------------------------
DEFAULT_LEAGUE = r"C:\Riot Games\League of Legends"
DEFAULT_OUT    = str(Path.home() / "Desktop" / "Extracted")

# ----- Chroma renk paleti --------------------------------------------------
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

# ----- CDragon / Riot API --------------------------------------------------
CDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
CDRAGON_BASE     = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default"
CDRAGON_SUMMARY  = f"{CDRAGON_BASE}/v1/champion-summary.json"
CDRAGON_SKINS    = f"{CDRAGON_BASE}/v1/skins.json"

RIOT_DATA: dict = {}


def http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "RahasyaExtractionTool/0.2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_riot_data():
    global RIOT_DATA
    try:
        print("[*] Riot DataDragon yukleniyor...")
        version = http_json(CDRAGON_VERSIONS)[0]
        full = http_json(
            f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/championFull.json"
        )
        for _, info in full["data"].items():
            RIOT_DATA[info["name"].lower()] = {
                "key": info["key"], "skins": info["skins"]
            }
        print(f"[+] Riot API hazir ({version}, {len(RIOT_DATA)} champion)\n")
    except Exception as e:
        print(f"[!] Riot API alinamadi ({e})\n")


def find_skin_id(champ_name: str, skin_name: str):
    """Ana skin ID'sini döndür. Bulunamazsa None."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    data = next((v for k, v in RIOT_DATA.items() if norm(k) == norm(champ_name)), None)
    if not data:
        return None
    official = {s["name"].lower(): s["id"] for s in data["skins"]}
    if skin_name.lower() in official:
        return official[skin_name.lower()]
    m = difflib.get_close_matches(skin_name.lower(), official.keys(), n=1, cutoff=0.5)
    return official[m[0]] if m else None


def fetch_catalog(only_key: str) -> tuple[str, dict, dict]:
    try:
        patch = http_json(CDRAGON_VERSIONS)[0]
    except Exception:
        patch = "latest"

    summary = http_json(CDRAGON_SUMMARY)
    skins   = http_json(CDRAGON_SKINS)
    id_to_key: dict[int, str] = {
        int(c["id"]): c["alias"] for c in summary if int(c["id"]) > 0
    }

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
            sys.exit(f"Bircok esleme: {', '.join(k for _,k in matches)}")
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
        champ_skins = http_json(f"{CDRAGON_BASE}/v1/champions/{target_id}.json").get("skins", [])
    except Exception:
        champ_skins = []

    for s in champ_skins:
        parent_id  = int(s.get("id") or 0)
        if parent_id < 1000 or parent_id // 1000 != target_id:
            continue
        parent_num  = parent_id % 1000
        parent_name = s.get("name") or f"{only_key} skin {parent_num}"
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
                "color": color, "kind": "chroma",
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
            }

    return patch, catalog, chroma_meta


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


# ----- ANSI helpers --------------------------------------------------------

def ansi_block(color_name: str) -> str:
    hex_c = CHROMA_COLORS.get(color_name.lower(), "")
    if not hex_c:
        return "\033[90m██\033[0m"
    h = hex_c.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"\033[38;2;{r};{g};{b}m██\033[0m"


def hyperlink(text: str, skin_id) -> str:
    """LolValue linki — sadece gecerli (ana skin) ID varsa link olusturur."""
    if not skin_id:
        return text
    url = f"https://lolvalue.com/lol-skins/skin/{skin_id}"
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


# ----- Hash / LtMAO --------------------------------------------------------

def load_hashes(refresh: bool = False):
    cache = WORK_DIR / "pref" / "hashes" / "cdtb_hashes"
    if refresh and cache.exists():
        for f in cache.iterdir(): f.unlink()
    print("[hashes] Senkronize ediliyor...")
    CDTBHashes.sync_all()
    CustomHashes.read_all_hashes()
    print(f"[hashes] Hazir — game={len(Storage.hashtables['hashes.game.txt'])}\n")


# ----- SkinBuilder ---------------------------------------------------------

class SkinBuilder:
    def __init__(self, champions_dir: Path, output_dir: Path,
                 catalog: dict, chroma_meta: dict):
        self.champions_dir = champions_dir
        self.output_dir    = output_dir
        self.catalog       = catalog
        self.chroma_meta   = chroma_meta

        all_game = hash_helper.Storage.hashtables["hashes.game.txt"]
        self.skin_bin_hashes: dict[int, str] = {
            h: p for h, p in all_game.items()
            if p.lower().endswith(".bin")
            and "data/characters/" in p.lower()
            and "/skins/" in p.lower()
            and "root.bin" not in p.lower()
        }

    def list_skins(self, champ_key: str) -> list[dict]:
        wad_path = self._find_wad(champ_key)
        if not wad_path:
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

        result: list[dict] = []
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

            # LolValue sadece ana skin ID'lerini tanir.
            # Chroma / form icin parent skin'in display adini kullan.
            if kind in ("chroma", "form") and parent_num is not None:
                parent_display = names.get(parent_num, parent_name)
                sid = find_skin_id(champ_key, parent_display)
            else:
                sid = find_skin_id(champ_key, display)

            result.append({
                "num":         num,
                "display":     display,
                "kind":        kind,
                "color":       color,
                "parent_name": parent_name,
                "skin_id":     sid,
            })
        return result

    def build_skin(self, champ_key: str, skin_info: dict) -> Path | None:
        wad_path = self._find_wad(champ_key)
        if not wad_path:
            print(f"  [!] WAD bulunamadi: {champ_key}")
            return None

        wad = pyRitoFile.wad.WAD().read(str(wad_path))
        wad.un_hash({"hashes.game.txt": self.skin_bin_hashes})

        champ_lower = champ_key.lower()
        characters: dict[str, dict] = {}
        for chunk in wad.chunks:
            if chunk.extension != "bin":
                continue
            parts = chunk.hash.lower().split("/")
            if (len(parts) < 5 or parts[0] != "data"
                    or parts[1] != "characters"
                    or parts[3] != "skins"):
                continue
            char = parts[2]
            base = parts[4][:-4]
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
                            rr_h = f.data; break
                elif entry.type == hash_helper.Storage.bin_hashes["ResourceResolver"]:
                    if rr_h is None: rr_h = entry.hash
            if scdp_h:
                char_s0_hashes[char] = (scdp_h, rr_h)
                char_s0_bins[char]   = s0

        if champ_lower not in char_s0_hashes:
            print(f"  [!] {champ_key}: SkinCharacterDataProperties yok")
            return None

        num     = skin_info["num"]
        display = skin_info["display"]
        patched: list[tuple[str, bytes]] = []
        for char, info in characters.items():
            if num not in info["skinN"] or char not in char_s0_hashes:
                continue
            scdp_h, rr_h = char_s0_hashes[char]
            chunk = info["skinN"][num]
            with pyRitoFile.stream.BytesStream.reader(str(wad_path)) as bs:
                chunk.read_data(bs)
                try:
                    skin_bin = _read_bin(chunk.data)
                finally:
                    chunk.free_data()
            try:
                data = _patch_bin(char, skin_bin, char_s0_bins.get(char), scdp_h, rr_h)
            except RuntimeError as e:
                print(f"      · skip {char}: {e}")
                continue
            patched.append((f"data/characters/{char}/skins/skin0.bin", data))

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

        out_dir = self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{fname}.fantome"

        fantome_meta = {
            "Name":        display,
            "Author":      "kick.com/rahasya",
            "Version":     "1.0.0",
            "Description": "Extracted by kick.com/rahasya via Sunshine.",
        }
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            zf.writestr("META/info.json", json.dumps(fantome_meta, indent=2))
            for inner, data in patched:
                zf.writestr(f"WAD/{wad_path.name}/{inner}", data)

        return out_path

    def _find_wad(self, champ_key: str) -> Path | None:
        candidates = list(self.champions_dir.glob(f"{champ_key}.wad.client"))
        if not candidates:
            for w in self.champions_dir.glob("*.wad.client"):
                if w.name.split(".",1)[0].lower() == champ_key.lower():
                    candidates.append(w); break
        return candidates[0] if candidates else None


# ----- Bin helpers ---------------------------------------------------------

def _read_bin(data: bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tf:
        tf.write(data); tmp = tf.name
    try:
        return pyRitoFile.bin.BIN().read(tmp)
    finally:
        try: os.unlink(tmp)
        except OSError: pass


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
                if f.hash == MRR: mrr = f; break
        elif e.type == RR:
            rr = e
    if not scdp:
        raise RuntimeError("no SCDP")

    scdp.hash = skin0_scdp
    if rr and skin0_rr:  rr.hash  = skin0_rr
    if mrr and skin0_rr: mrr.data = skin0_rr

    for f in scdp.data or []:
        if f.type != pyRitoFile.bin.BINType.STRING: continue
        if not isinstance(f.data, str): continue
        try: fh = f.hash if isinstance(f.hash, int) else int(str(f.hash), 16)
        except: continue
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
        with open(tmp, "rb") as f: return f.read()
    finally:
        try: os.unlink(tmp)
        except OSError: pass


# ----- Interactive UI ------------------------------------------------------

CONFIG = {
    "league": DEFAULT_LEAGUE,
    "out":    DEFAULT_OUT,
}


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def get_champ_list(champions_dir: Path) -> list[str]:
    return sorted(
        w.name.split(".", 1)[0]
        for w in champions_dir.glob("*.wad.client")
        if w.name.count(".") == 2 and "_" not in w.name.split(".", 1)[0]
    )


def pick_champion(champions_dir: Path) -> str | None:
    all_champs = get_champ_list(champions_dir)
    while True:
        q = input("\n  Champion adi ('geri' = menu): ").strip()
        if q.lower() in ("geri", "back", "b", ""): return None

        norm_q = normalize(q)
        for c in all_champs:
            if normalize(c) == norm_q: return c
        partial = [c for c in all_champs if norm_q in normalize(c)]
        if len(partial) == 1: return partial[0]
        if len(partial) > 1:
            print(f"  Birden fazla esleme: {', '.join(partial)}")
            continue
        close = difflib.get_close_matches(q, all_champs, n=3, cutoff=0.4)
        print(f"  [!] '{q}' bulunamadi." + (f"  Belki: {', '.join(close)}" if close else ""))


def show_skin_list(champ_key: str, skin_list: list[dict]) -> None:
    W = 64
    print(f"\n  \u2554{'═'*W}\u2557")
    print(f"  \u2551  {champ_key.upper():<{W-3}}\u2551")
    print(f"  \u2551  {'Ctrl+Click isim -> LolValue':<{W-3}}\u2551")
    print(f"  \u2560{'═'*W}\u2563")

    max_n     = max((len(s["display"]) for s in skin_list), default=10)
    last_kind = None

    for i, s in enumerate(skin_list, 1):
        if last_kind and last_kind != s["kind"]:
            print(f"  \u2560{'─'*W}\u2563")
        last_kind = s["kind"]

        num   = f"[{i:>2}]"
        name  = s["display"].ljust(max_n)
        link  = hyperlink(name, s["skin_id"])
        color = s["color"]
        block = ansi_block(color.lower()) if color else "\033[90m──\033[0m"
        if color:
            label = f"\033[93m{color}\033[0m"
        elif s["kind"] == "form":
            label = "\033[35mform\033[0m"
        else:
            label = "\033[36mskin\033[0m"
        print(f"  \u2551 {num} {link} {block} {label}")

    all_n = len(skin_list) + 1
    print(f"  \u2560{'═'*W}\u2563")
    print(f"  \u2551 [{all_n:>2}] Tumunu Build Et{'':<{W-20}}\u2551")
    print(f"  \u2551 [ 0] Geri{'':<{W-10}}\u2551")
    print(f"  \u255a{'═'*W}\u255d")


def parse_selection(sel: str, max_n: int) -> list[int] | None:
    sel = sel.strip()
    try:
        if "," in sel:
            return [int(x.strip())-1 for x in sel.split(",") if x.strip()]
        if "-" in sel:
            a, b = sel.split("-", 1)
            return list(range(int(a.strip())-1, int(b.strip())))
        n = int(sel)
        return [n-1]
    except ValueError:
        return None


def process_champion(builder: SkinBuilder, champ_key: str) -> None:
    print(f"\n  [{champ_key}] Skin listesi hazirlaniyor...")
    skin_list = builder.list_skins(champ_key)
    if not skin_list:
        print("  [!] Skin bulunamadi.")
        return

    while True:
        show_skin_list(champ_key, skin_list)
        all_n = len(skin_list) + 1
        sel   = input("\n  Secim (ornek: 1 / 1,3,5 / 2-6): ").strip()
        if sel == "0": break

        to_build: list[dict] = []
        if sel == str(all_n):
            to_build = skin_list
        else:
            indices = parse_selection(sel, len(skin_list))
            if indices is None:
                print("  [!] Gecersiz secim."); continue
            for idx in indices:
                if 0 <= idx < len(skin_list):
                    to_build.append(skin_list[idx])
                else:
                    print(f"  [!] {idx+1} gecersiz numara, atlandi.")

        if not to_build: continue

        print(f"\n  Build ediliyor ({len(to_build)} skin)...")
        ok = fail = 0
        for s in to_build:
            out = builder.build_skin(champ_key, s)
            if out:
                color = s["color"]
                block = f"  {ansi_block(color.lower())}" if color else ""
                print(f"  [+] \033[92m{out.name}\033[0m{block}")
                ok += 1
            else:
                print(f"  [!] Hata: skin{s['num']} ({s['display']})")
                fail += 1
        out_path = Path(CONFIG["out"]) / "skins" / champ_key
        print(f"\n  \u2713 {ok} basarili" + (f", {fail} hatali" if fail else "") + f"\n  -> {out_path}\n")


def show_settings() -> None:
    print(f"\n  1. League Path : {CONFIG['league']}")
    print(f"  2. Output Path : {CONFIG['out']}")
    print(f"  3. Geri")
    c = input("  Secim: ").strip()
    if c == "1":
        p = input("  Yeni League Path: ").strip()
        if Path(p).exists(): CONFIG["league"] = p
        else: print("  [!] Klasor bulunamadi.")
    elif c == "2":
        p = input("  Yeni Output Path: ").strip()
        CONFIG["out"] = p
        Path(p).mkdir(parents=True, exist_ok=True)


def show_menu() -> str:
    print("\n\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557")
    print("\u2551   RAHASYA EXTRACTION TOOL  v2    \u2551")
    print("\u2560\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2563")
    print("\u2551  [1] Champion Sec & Build         \u2551")
    print("\u2551  [2] Ayarlar                      \u2551")
    print("\u2551  [3] Hash Yenile                  \u2551")
    print("\u2551  [4] Cikis                        \u2551")
    print("\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d")
    return input("  > ").strip()


def main():
    os.system("")  # Windows ANSI
    print("=" * 43)
    print("  Rahasya Extraction Tool  v2")
    print("  kick.com/rahasya")
    print("=" * 43)

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--league", default=None)
    ap.add_argument("--out",    default=None)
    ap.add_argument("--refresh-hashes", action="store_true")
    args, _ = ap.parse_known_args()
    if args.league: CONFIG["league"] = args.league
    if args.out:    CONFIG["out"]    = args.out

    load_riot_data()
    load_hashes(args.refresh_hashes)

    while True:
        champions_dir = Path(CONFIG["league"]) / "Game" / "DATA" / "FINAL" / "Champions"
        out_dir       = Path(CONFIG["out"])
        choice        = show_menu()

        if choice == "1":
            if not champions_dir.exists():
                print(f"\n  [!] League klasoru bulunamadi: {champions_dir}")
                print("  Ayarlar'dan (2) dogru yolu girin.\n")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            champ = pick_champion(champions_dir)
            if not champ: continue
            patch, catalog, chroma_meta = fetch_catalog(champ)
            builder = SkinBuilder(champions_dir, out_dir, catalog, chroma_meta)
            process_champion(builder, champ)

        elif choice == "2":
            show_settings()

        elif choice == "3":
            load_hashes(refresh=True)

        elif choice == "4":
            print("\n  Cikiliyor...\n")
            break
        else:
            print("  [!] Gecersiz secim.")


if __name__ == "__main__":
    main()
