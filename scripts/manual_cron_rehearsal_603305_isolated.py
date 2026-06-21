#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
603305 manual cron rehearsal - isolated runner

原则：
1. manual_triggered=true
2. not_natural_cron=true
3. not_for_sample_quality=true
4. not_for_strategy_eval=true
5. 修正 sys.path，模拟 cron 直接执行脚本时的导入环境
6. 尽量把正式 guard_outputs 写入重定向到 rehearsal 目录
7. 运行后恢复可能被模拟脚本改动的状态/日志文件
"""

from pathlib import Path
import builtins
import hashlib
import importlib
import json
import os
import shutil
import sys
import time
import traceback

KROOT = Path("/Users/wxo/Desktop/Kronos")
FORMAL_OUT = KROOT / "guard_outputs"
DAILY = KROOT / "daily_reports"
TS = time.strftime("%Y%m%d_%H%M%S")
OUT = DAILY / f"manual_cron_rehearsal_603305_{TS}"

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "redirected_guard_outputs").mkdir(parents=True, exist_ok=True)
(OUT / "restored_backups").mkdir(parents=True, exist_ok=True)
(OUT / "quarantined_formal_outputs").mkdir(parents=True, exist_ok=True)

manifest = {
    "manual_triggered": True,
    "not_natural_cron": True,
    "not_for_sample_quality": True,
    "not_for_strategy_eval": True,
    "kroot": str(KROOT),
    "formal_guard_outputs": str(FORMAL_OUT),
    "rehearsal_dir": str(OUT),
    "status": "INIT",
    "errors": [],
    "redirected_outputs": [],
    "quarantined_formal_outputs": [],
    "restored_files": [],
    "new_or_changed_tracked_files": [],
}

# 关键：模拟 python3 /Users/wxo/Desktop/Kronos/auto_report_guard_603305.py 的导入路径
if str(KROOT) not in sys.path:
    sys.path.insert(0, str(KROOT))

os.environ["KRONOS_MANUAL_REHEARSAL"] = "true"
os.environ["KRONOS_NOT_NATURAL_CRON"] = "true"
os.environ["KRONOS_NOT_FOR_SAMPLE_QUALITY"] = "true"
os.environ["KRONOS_NOT_FOR_STRATEGY_EVAL"] = "true"

def sha256_file(p: Path):
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def should_track(p: Path) -> bool:
    parts = set(p.parts)
    if "__pycache__" in parts:
        return False
    if "guard_outputs" in parts:
        return False
    if "daily_reports" in parts:
        return False
    if p.is_dir():
        return False
    # 主要保护状态、日志、数据类文件，避免 rehearsal 污染正式样本
    return p.suffix.lower() in {
        ".json", ".jsonl", ".log", ".txt", ".csv", ".md", ".state", ".pkl"
    }

def snapshot_tracked_files():
    snap = {}
    for p in KROOT.rglob("*"):
        try:
            if should_track(p):
                rel = str(p.relative_to(KROOT))
                snap[rel] = {
                    "path": str(p),
                    "sha256": sha256_file(p),
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                }
        except Exception:
            pass
    return snap

def backup_tracked_files(snap):
    backup_root = OUT / "pre_run_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    for rel, info in snap.items():
        src = Path(info["path"])
        if src.exists():
            dst = backup_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except Exception as e:
                manifest["errors"].append(f"backup_failed {src}: {repr(e)}")
    return backup_root

def restore_tracked_files(pre_snap, backup_root):
    post_snap = snapshot_tracked_files()

    # 恢复变动文件
    for rel, info in pre_snap.items():
        before_hash = info["sha256"]
        after_hash = post_snap.get(rel, {}).get("sha256")
        if before_hash != after_hash:
            src = backup_root / rel
            dst = KROOT / rel
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                manifest["restored_files"].append(rel)

    # 隔离新增 tracked 文件
    for rel in sorted(set(post_snap) - set(pre_snap)):
        src = KROOT / rel
        if src.exists():
            dst = OUT / "restored_backups" / "new_files_quarantine" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dst))
                manifest["new_or_changed_tracked_files"].append(rel)
            except Exception as e:
                manifest["errors"].append(f"quarantine_new_file_failed {src}: {repr(e)}")

def redirect_path(file):
    try:
        p = Path(file)
        rp = p.resolve()
        formal = FORMAL_OUT.resolve()
        if str(rp).startswith(str(formal) + os.sep):
            dst = OUT / "redirected_guard_outputs" / p.name
            manifest["redirected_outputs"].append(str(dst))
            return dst
    except Exception:
        pass
    return file

# 在本进程内重定向 open / Path.write_text / Path.write_bytes
_orig_open = builtins.open
def _open_redirect(file, *args, **kwargs):
    return _orig_open(redirect_path(file), *args, **kwargs)
builtins.open = _open_redirect

_orig_write_text = Path.write_text
def _write_text_redirect(self, data, *args, **kwargs):
    return _orig_write_text(Path(redirect_path(self)), data, *args, **kwargs)
Path.write_text = _write_text_redirect

_orig_write_bytes = Path.write_bytes
def _write_bytes_redirect(self, data, *args, **kwargs):
    return _orig_write_bytes(Path(redirect_path(self)), data, *args, **kwargs)
Path.write_bytes = _write_bytes_redirect

def list_formal_reports():
    if not FORMAL_OUT.exists():
        return set()
    return {p.name for p in FORMAL_OUT.glob("report_*.txt") if p.is_file()}

pre_formal_reports = list_formal_reports()
pre_snap = snapshot_tracked_files()
backup_root = backup_tracked_files(pre_snap)

try:
    manifest["status"] = "RUNNING"

    # 按正式 cron 方式模拟：
    # 等价于 python3 /Users/wxo/Desktop/Kronos/auto_report_guard_603305.py
    # 但仍在本 rehearsal 进程内运行，以便 open/path 重定向和污染隔离生效。
    import runpy

    old_argv = sys.argv[:]
    try:
        sys.argv = [str(KROOT / "auto_report_guard_603305.py")]
        runpy.run_path(str(KROOT / "auto_report_guard_603305.py"), run_name="__main__")
    finally:
        sys.argv = old_argv

    manifest["status"] = "OK"

except Exception as e:
    manifest["status"] = "ERROR"
    manifest["errors"].append(repr(e))
    (OUT / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")

finally:
    # 如果仍有正式 report 被写入，则隔离搬走，避免污染 guard_outputs
    post_formal_reports = list_formal_reports()
    new_formal = sorted(post_formal_reports - pre_formal_reports)
    for name in new_formal:
        src = FORMAL_OUT / name
        dst = OUT / "quarantined_formal_outputs" / name
        try:
            shutil.move(str(src), str(dst))
            manifest["quarantined_formal_outputs"].append(str(dst))
        except Exception as e:
            manifest["errors"].append(f"quarantine_formal_output_failed {src}: {repr(e)}")

    restore_tracked_files(pre_snap, backup_root)

    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"MANUAL_CRON_REHEARSAL_DIR={OUT}")
    print(f"STATUS={manifest['status']}")
    if manifest["errors"]:
        print("ERRORS:")
        for x in manifest["errors"]:
            print("-", x)
