import os
from collections import defaultdict

from ..engine.backup import get_manifest, load_inventory
from ..utils.logging_utils import get_logger

LOG = get_logger()

CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
               ".heic", ".tiff", ".tif", ".raw", ".ico", ".psd"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm",
               ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
              ".opus", ".mid", ".midi"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
                  ".tex", ".pages", ".epub", ".msg", ".eml", ".csv"},
    "Spreadsheets": {".xls", ".xlsx", ".ods", ".numbers", ".tsv"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
    "Code": {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h",
             ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1",
             ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".sql", ".html",
             ".css", ".scss", ".vue", ".swift", ".kt", ".lua", ".r", ".ipynb"},
    "Installers": {".exe", ".msi", ".msix", ".apk", ".dmg", ".deb", ".rpm",
                   ".pkg", ".appimage"},
    "3D & Design": {".stl", ".obj", ".fbx", ".blend", ".dwg", ".dxf",
                    ".ai", ".fig", ".sketch", ".xcf"},
}

JUNK_PATTERNS = [
    ("~$ Office temp", lambda n: n.startswith("~$")),
    (".tmp/.temp", lambda n: n.lower().endswith((".tmp", ".temp", ".crdownload", ".part", ".partial"))),
    ("Thumbs.db", lambda n: n.lower() in ("thumbs.db", "ehthumbs.db")),
    ("desktop.ini", lambda n: n.lower() == "desktop.ini"),
    (".DS_Store", lambda n: n.lower() == ".ds_store"),
    ("Windows shortcuts", lambda n: n.lower().endswith(".lnk")),
    ("Old backups", lambda n: n.lower().endswith((".bak", ".old", ".orig", ".1", ".2"))),
    ("Log files", lambda n: n.lower().endswith((".log", ".lo_", ".log1", ".log2"))),
    ("Cache markers", lambda n: "cache" in n.lower() and n.lower().endswith((".dat", ".bin"))),
    ("iTunes junk", lambda n: n.lower() in ("_playlist.pls", "albumartwork_*")),
]


def categorize(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "Other"


def analyze(gemini_key: str = "", provider="gemini", model=None):
    inventory = load_inventory()
    manifest = get_manifest()
    if not inventory and not manifest:
        raise RuntimeError("No inventory or manifest found - run a backup first.")

    items = inventory or [
        {"Path": f["path"], "Name": os.path.basename(f["path"]),
         "Size": f["size"], "Hashes": {"MD5": f["md5"]} if f["md5"] else {},
         "MimeType": f.get("mime", ""), "ModTime": f.get("modtime", "")}
        for f in manifest
    ]

    total_size = 0
    total_count = len(items)
    by_cat = defaultdict(lambda: {"count": 0, "size": 0})
    by_ext = defaultdict(lambda: {"count": 0, "size": 0})
    by_year = defaultdict(lambda: {"count": 0, "size": 0})
    hashes = defaultdict(list)
    junk = defaultdict(list)
    empty = []
    top = []
    other_paths = []

    for item in items:
        path = item.get("Path") or item.get("Name") or ""
        name = os.path.basename(path)
        size = item.get("Size", 0) or 0
        total_size += size
        cat = categorize(name)
        by_cat[cat]["count"] += 1
        by_cat[cat]["size"] += size
        ext = os.path.splitext(name)[1].lower() or "(no ext)"
        by_ext[ext]["count"] += 1
        by_ext[ext]["size"] += size
        year = "unknown"
        mt = item.get("ModTime", "")
        if len(mt) >= 4:
            year = mt[:4]
        by_year[year]["count"] += 1
        by_year[year]["size"] += size

        md5 = (item.get("Hashes") or {}).get("MD5") or (item.get("Hashes") or {}).get("md5")
        if md5 and size > 0:
            hashes[md5].append(path)
        if size == 0:
            empty.append(path)
        if cat == "Other" and size > 0:
            other_paths.append(path)
        for label, fn in JUNK_PATTERNS:
            try:
                if fn(name):
                    junk[label].append(path)
                    break
            except Exception:
                pass
        top.append({"path": path, "size": size})

    top.sort(key=lambda x: x["size"], reverse=True)
    top_files = top[:50]

    ai_classified = 0
    if gemini_key:
        from ..ai import llm
        if other_paths:
            mapping = llm.ai_categorize(gemini_key,
                                        [os.path.basename(p) for p in other_paths],
                                        provider=provider, model=model)
            for name, cat in mapping.items():
                if cat == "Other":
                    continue
                path = next((p for p in other_paths
                             if os.path.basename(p) == name), None)
                if not path:
                    continue
                item = next((it for it in items
                             if (it.get("Path") or it.get("Name") or "") == path),
                            None)
                if not item:
                    continue
                size = item.get("Size", 0) or 0
                by_cat[cat]["count"] += 1
                by_cat[cat]["size"] += size
                by_cat["Other"]["count"] -= 1
                by_cat["Other"]["size"] -= size
                ai_classified += 1

    duplicates = [{"md5": h, "paths": paths, "size": _size_of_dup(paths, hashes, items),
                   "wasted": _wasted(paths, items)}
                  for h, paths in hashes.items() if len(paths) > 1]
    duplicates.sort(key=lambda d: d["wasted"], reverse=True)
    dup_wasted = sum(d["wasted"] for d in duplicates)

    junk_size = 0
    for paths in junk.values():
        for p in paths:
            junk_size += _find_size(p, items)

    return {
        "count": total_count,
        "size": total_size,
        "categories": dict(by_cat),
        "extensions": dict(sorted(by_ext.items(), key=lambda kv: kv[1]["size"], reverse=True)[:15]),
        "years": dict(by_year),
        "top_files": top_files,
        "duplicates": duplicates,
        "dup_count": len(duplicates),
        "dup_wasted": dup_wasted,
        "junk": {k: v for k, v in junk.items() if v},
        "junk_size": junk_size,
        "empty_files": empty,
        "ai_classified": ai_classified,
    }


def _size_of_dup(paths, _hashes, items):
    by_path = {}
    for item in items:
        by_path[item.get("Path") or item.get("Name") or ""] = item.get("Size", 0) or 0
    return by_path.get(paths[0], 0)


def _wasted(paths, items):
    size = _size_of_dup(paths, None, items)
    return size * (len(paths) - 1)


def _find_size(path, items):
    for item in items:
        if (item.get("Path") or item.get("Name") or "") == path:
            return item.get("Size", 0) or 0
    return 0


def organization_plan(gemini_key: str = "", provider="gemini", model=None):
    manifest = get_manifest()
    if not manifest:
        raise RuntimeError("No manifest - run a backup first.")
    plan = []
    for f in manifest:
        name = os.path.basename(f["path"])
        cat = categorize(name)
        year = "unknown"
        if len(f.get("modtime", "")) >= 4:
            year = f["modtime"][:4]
        plan.append({
            "source": f["path"],
            "category": cat,
            "year": year,
            "target": f"Organized/{cat}/{year}/{name}",
        })
    if gemini_key:
        from ..ai import llm
        files = [{"source": e["source"], "name": os.path.basename(e["source"]),
                  "category": e["category"], "year": e["year"]} for e in plan]
        targets = llm.ai_organization_plan(gemini_key, files,
                                           provider=provider, model=model)
        for entry in plan:
            if entry["source"] in targets:
                entry["target"] = targets[entry["source"]]
    return plan


def quality_check(gemini_key: str = "", analysis=None, verify=None,
                  provider="gemini", model=None):
    """AI review of the drive analysis. Returns a list of findings."""
    if not gemini_key:
        return []
    if analysis is None:
        analysis = analyze(gemini_key, provider=provider, model=model)
    from ..ai import llm
    return llm.ai_quality_check(gemini_key, analysis, verify,
                                provider=provider, model=model)