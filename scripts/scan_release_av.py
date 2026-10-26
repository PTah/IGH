# -*- coding: utf-8 -*-
"""Загрузка релизного артефакта в VirusTotal; отчёт в dist/ и текст для Gitea.

  set VIRUSTOTAL_API_KEY=...
  python scripts/scan_release_av.py --file dist/IGH-0.5.0-online.zip

Мультисканер (virustest.gov.ru) — веб без публичного API; скрипт печатает
инструкцию и пишет заготовку отчёта рядом.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VT_API = "https://www.virustotal.com/api/v3"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def vt_request(method: str, url: str, api_key: str, data: bytes | None = None, ctype: str | None = None):
    headers = {"x-apikey": api_key, "Accept": "application/json"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"VirusTotal HTTP {e.code}: {body[:800]}") from e


def vt_upload(path: Path, api_key: str) -> dict:
    # large upload URL if >32MB
    size = path.stat().st_size
    if size >= 32 * 1024 * 1024:
        meta = vt_request("GET", f"{VT_API}/files/upload_url", api_key)
        upload_url = meta["data"]
    else:
        upload_url = f"{VT_API}/files"

    boundary = "----IGHBoundary7MA4YWxkTrZu0gW"
    filename = path.name
    file_bytes = path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return vt_request(
        "POST",
        upload_url,
        api_key,
        data=body,
        ctype=f"multipart/form-data; boundary={boundary}",
    )


def vt_wait_analysis(analysis_id: str, api_key: str, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = vt_request("GET", f"{VT_API}/analyses/{analysis_id}", api_key)
        status = (data.get("data") or {}).get("attributes", {}).get("status")
        print(f"  VT analysis status: {status}", flush=True)
        if status == "completed":
            return data
        time.sleep(8)
    raise SystemExit("VirusTotal: timeout waiting for analysis")


def summarize_vt(file_report: dict, sha: str) -> tuple[str, dict]:
    attrs = (file_report.get("data") or {}).get("attributes") or {}
    stats = attrs.get("last_analysis_stats") or {}
    malicious = int(stats.get("malicious") or 0)
    suspicious = int(stats.get("suspicious") or 0)
    undetected = int(stats.get("undetected") or 0)
    harmless = int(stats.get("harmless") or 0)
    engines = malicious + suspicious + undetected + harmless + int(stats.get("timeout") or 0)
    link = f"https://www.virustotal.com/gui/file/{sha}"
    lines = [
        f"VirusTotal: {malicious} malicious / {suspicious} suspicious / {engines} engines",
        f"SHA-256: {sha}",
        f"Report: {link}",
    ]
    if malicious == 0 and suspicious == 0:
        lines.append("Verdict: clean (no malicious/suspicious detections).")
    else:
        lines.append("Verdict: review detections on VirusTotal.")
    return "\n".join(lines) + "\n", {
        "sha256": sha,
        "stats": stats,
        "link": link,
        "malicious": malicious,
        "suspicious": suspicious,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, type=Path, help="zip or exe to scan")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="where to write reports (default: next to file)",
    )
    args = ap.parse_args()
    path = args.file.resolve()
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    out_dir = (args.out_dir or path.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sha = sha256_file(path)
    print(f"file={path.name} size={path.stat().st_size} sha256={sha}", flush=True)

    api_key = (
        os.environ.get("VIRUSTOTAL_API_KEY")
        or os.environ.get("VT_API_KEY")
        or ""
    ).strip()
    conf = Path.home() / "CursorRules" / "local" / "virustotal.conf"
    if not api_key and conf.exists():
        for line in conf.read_text(encoding="utf-8").splitlines():
            if line.startswith("VIRUSTOTAL_API_KEY="):
                api_key = line.split("=", 1)[1].strip()

    report_md = out_dir / f"{path.stem}-av-scan.md"
    report_json = out_dir / f"{path.stem}-av-scan.json"
    payload: dict = {
        "file": path.name,
        "sha256": sha,
        "size": path.stat().st_size,
        "virustotal": None,
        "multiscanner": {
            "service": "https://virustest.gov.ru/",
            "note": "Нет публичного API; загрузить вручную тот же файл и вставить ссылку/вердикт.",
            "status": "manual",
        },
    }

    md_parts = [
        f"# AV scan: `{path.name}`",
        "",
        f"- SHA-256: `{sha}`",
        f"- Size: {path.stat().st_size} bytes",
        "",
    ]

    if not api_key:
        md_parts += [
            "## VirusTotal",
            "",
            "API key not set (`VIRUSTOTAL_API_KEY` or `%USERPROFILE%\\CursorRules\\local\\virustotal.conf`).",
            f"Upload manually: https://www.virustotal.com/gui/home/upload — search hash `{sha}` after upload.",
            "",
        ]
        print("WARN: no VirusTotal API key — skipping upload", flush=True)
    else:
        print("VirusTotal: lookup by hash…", flush=True)
        try:
            existing = vt_request("GET", f"{VT_API}/files/{sha}", api_key)
            text, summary = summarize_vt(existing, sha)
            print(text, flush=True)
            payload["virustotal"] = summary
            md_parts += ["## VirusTotal", "", text, ""]
        except SystemExit as e:
            if "404" not in str(e) and "NotFound" not in str(e):
                # try upload on any miss
                pass
            print("VirusTotal: not known yet — uploading…", flush=True)
            up = vt_upload(path, api_key)
            analysis_id = (up.get("data") or {}).get("id")
            if not analysis_id:
                raise SystemExit(f"unexpected upload response: {up}")
            print(f"  analysis id={analysis_id}", flush=True)
            vt_wait_analysis(analysis_id, api_key)
            report = vt_request("GET", f"{VT_API}/files/{sha}", api_key)
            text, summary = summarize_vt(report, sha)
            print(text, flush=True)
            payload["virustotal"] = summary
            md_parts += ["## VirusTotal", "", text, ""]

    md_parts += [
        "## Мультисканер (virustest.gov.ru)",
        "",
        "Публичного API нет. Загрузите тот же файл на https://virustest.gov.ru/",
        f"(лимит без регистрации ~256 МБ; наш файл {path.stat().st_size / 1e6:.1f} МБ).",
        "После проверки допишите вердикт и ссылку в этот файл / в описание релиза Gitea.",
        "",
    ]

    report_md.write_text("\n".join(md_parts), encoding="utf-8")
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {report_md}", flush=True)
    print(f"wrote {report_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
