#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Создать/обновить релиз на home Gitea и залить zip из dist/.

  python scripts/publish_gitea_release.py
  python scripts/publish_gitea_release.py --version 0.3.9
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
CONF = Path.home() / "CursorRules" / "local" / "jdoe-gitea.conf"
OWNER = "jdoe"
REPO = "IGH"


def load_conf() -> dict[str, str]:
    if not CONF.exists():
        raise SystemExit(f"missing {CONF}")
    cfg: dict[str, str] = {}
    for line in CONF.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


def api(cfg: dict[str, str], method: str, path: str, data: bytes | None = None, ctype: str | None = None):
    base = cfg["GiteaApiUrl"].rstrip("/")
    token = base64.b64encode(
        f"{cfg['GiteaApiUser']}:{cfg['GiteaApiPassword']}".encode("ascii")
    ).decode("ascii")
    headers = {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(
        f"{base}/api/v1{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {path}: {body}") from e


def upload_asset(cfg: dict[str, str], release_id: int, file_path: Path) -> None:
    import subprocess as sp

    base = cfg["GiteaApiUrl"].rstrip("/")
    token = base64.b64encode(
        f"{cfg['GiteaApiUser']}:{cfg['GiteaApiPassword']}".encode("ascii")
    ).decode("ascii")
    name = file_path.name
    url = (
        f"{base}/api/v1/repos/{OWNER}/{REPO}/releases/{release_id}/assets"
        f"?name={urllib.request.quote(name)}"
    )
    print(f"upload {name} ({file_path.stat().st_size / 1e6:.1f} MB)…", flush=True)
    r = sp.run(
        [
            "curl",
            "-sS",
            "-f",
            "-X",
            "POST",
            "-H",
            f"Authorization: Basic {token}",
            "-H",
            "Accept: application/json",
            "-F",
            f"attachment=@{file_path}",
            url,
        ],
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"curl upload failed: {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=(ROOT / "VERSION").read_text(encoding="utf-8").strip())
    args = ap.parse_args()
    ver = args.version
    tag = f"v{ver}"
    commit = subprocess.check_output(
        ["git", "rev-parse", f"{tag}^{{commit}}"], text=True, cwd=ROOT
    ).strip()
    files = [
        DIST / f"IGH-{ver}-online.zip",
        DIST / f"IGH-{ver}-offline-medium.zip",
        DIST / f"IGH-{ver}-offline-full.zip",
    ]
    for f in files:
        if not f.exists():
            raise SystemExit(f"missing {f}")

    cfg = load_conf()
    body = (
        f"Релиз **{ver}**\n\n"
        "- Маршрут по дням: Лафкин/Мак-Кензи/Уэйн/Покипси появляются вовремя (не «прыжком» через несколько дней)\n"
        "- Стрелки дней стабильно центрируют карту; автоход без дёрганья масштаба (гистерезис)\n"
        "- Море: Гибралтарский пролив; «Мариетта» вокруг Вен/Балтики без наползания на сушу\n"
        "- Километраж участков + пройденный путь; анимация автохода\n\n"
        "Распакуйте zip **целиком** (папка `map/` обязательна).\n\n"
        "Артефакты: online / offline-medium / offline-full.\n"
    )
    av_md = DIST / f"IGH-{ver}-online-av-scan.md"
    if av_md.exists():
        body += "\n## Проверка антивирусами\n\n" + av_md.read_text(encoding="utf-8") + "\n"

    payload = {
        "tag_name": tag,
        "target_commitish": commit,
        "name": f"IGH {ver} — online / medium / full",
        "body": body,
        "draft": False,
        "prerelease": False,
    }

    existing = api(cfg, "GET", f"/repos/{OWNER}/{REPO}/releases?limit=30")
    for rel in existing:
        if rel.get("tag_name") == tag:
            print(f"delete old release id={rel['id']}", flush=True)
            api(cfg, "DELETE", f"/repos/{OWNER}/{REPO}/releases/{rel['id']}")

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    rel = api(
        cfg,
        "POST",
        f"/repos/{OWNER}/{REPO}/releases",
        data=data,
        ctype="application/json; charset=utf-8",
    )
    rid = rel["id"]
    print(f"created id={rid} {rel.get('html_url')}", flush=True)
    for f in files:
        upload_asset(cfg, rid, f)
    for extra in (
        DIST / f"IGH-{ver}-online-av-scan.md",
        DIST / f"IGH-{ver}-online-av-scan.json",
    ):
        if extra.exists():
            upload_asset(cfg, rid, extra)
    check = api(cfg, "GET", f"/repos/{OWNER}/{REPO}/releases/{rid}")
    print("OK", check.get("html_url"), "assets=", len(check.get("assets") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
