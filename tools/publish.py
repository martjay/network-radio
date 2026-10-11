"""Publish the repository and its release asset to GitHub.

Uses the GitHub REST API directly so no `gh` login or stored git credential is
needed - the token is supplied via the GITHUB_TOKEN environment variable and
never written to disk.

    set GITHUB_TOKEN=ghp_xxx
    python tools/publish.py              # push + release
    python tools/publish.py --push-only  # push commits only
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

OWNER = "martjay"
REPO = "network-radio"
TAG = "v1.0.0"
ASSET = os.path.join("dist", "Broadcast-1.0.0-win64.zip")
API = "https://api.github.com"
UA = "BroadcastPublisher/1.0"


def token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    tok = tok.strip()
    if not tok:
        print("ERROR: set GITHUB_TOKEN first.")
        print("       Create one at https://github.com/settings/tokens (scope: repo)")
        sys.exit(2)
    return tok


def api(method: str, path: str, tok: str, payload=None, raw: bytes | None = None,
        content_type: str = "application/json"):
    url = path if path.startswith("http") else f"{API}{path}"
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {tok}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"message": body[:400]}
    except urllib.error.URLError as exc:
        return 0, {"message": str(exc)}


def run(cmd: list[str], check: bool = True, secret: str = "") -> int:
    shown = [c.replace(secret, "***") if secret else c for c in cmd]
    print(f"  $ {' '.join(shown)}")
    # git writes UTF-8, but a Windows console may default to a legacy code page.
    # Decode explicitly so non-ASCII output cannot abort the push.
    p = subprocess.run(cmd, capture_output=True)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    if secret:
        out = out.replace(secret, "***")
    for line in out.strip().splitlines()[-12:]:
        print(f"      {line}")
    if check and p.returncode != 0:
        raise SystemExit(f"command failed ({p.returncode})")
    return p.returncode


def push(tok: str) -> None:
    print("\n=== pushing to GitHub ===")
    url = f"https://x-access-token:{tok}@github.com/{OWNER}/{REPO}.git"
    # The token goes into a one-shot remote, never into .git/config, and is
    # redacted from all command output.
    run(["git", "push", url, "main:main", "--force"], secret=tok)
    run(["git", "push", url, "--tags"], check=False, secret=tok)
    print("  pushed.")


def ensure_release(tok: str) -> int:
    print("\n=== creating release ===")
    status, data = api("GET", f"/repos/{OWNER}/{REPO}/releases/tags/{TAG}", tok)
    if status == 200:
        print(f"  release {TAG} already exists (id={data['id']})")
        return data["id"]

    body = (
        "## BROADCAST 1.0.0 — 网络收音机\n\n"
        "Windows 免安装版。解压后运行 `Broadcast.exe`，**无需安装 Python**。\n\n"
        "### 下载\n"
        "`Broadcast-1.0.0-win64.zip` （约 70 MB，解压后 171 MB）\n\n"
        "### 特性\n"
        "- **820 个电台 / 74 个国家 / 15 个类型**，每条流都经过实际解码验证，无失效链接\n"
        "- 96 个中文电台：RTHK 1–8、臺北電台、警察廣播電台、河南戏曲广播等\n"
        "- 支持 MP3 / AAC / AAC+ / HLS\n"
        "- **代理**：自动跟随系统代理，也可手动配置 HTTP/HTTPS/SOCKS5（含认证）\n"
        "- **录制**：默认直接复制原始流，不二次编码；文件首尾帧对齐，可无损解码\n"
        "- 40 段实时频谱分析 + 电平表\n"
        "- 收藏 / 最近播放 / 常听电台 / 自建电台，支持连接测试\n\n"
        "### 使用说明\n"
        "- 部分境外电台需在 **设置 → 网络代理** 中启用代理\n"
        "- 录制与 HLS 电台需要系统已安装 [ffmpeg](https://ffmpeg.org/)（未安装时其余功能正常）\n\n"
        "### 快捷键\n"
        "`Space` 播放/暂停 · `Ctrl+←/→` 换台 · `Ctrl+R` 录制 · `Ctrl+D` 收藏 · "
        "`Ctrl+F` 搜索 · `Ctrl+N` 添加电台 · `F11` 最大化\n\n"
        "---\n\n"
        "作者 QQ：**398511660**\n"
    )
    status, data = api("POST", f"/repos/{OWNER}/{REPO}/releases", tok, {
        "tag_name": TAG,
        "target_commitish": "main",
        "name": "BROADCAST 1.0.0 — 网络收音机",
        "body": body,
        "draft": False,
        "prerelease": False,
    })
    if status not in (200, 201):
        raise SystemExit(f"release creation failed: {status} {data.get('message')}")
    print(f"  created release {TAG} (id={data['id']})")
    return data["id"]


def upload(tok: str, release_id: int) -> None:
    print("\n=== uploading asset ===")
    if not os.path.isfile(ASSET):
        raise SystemExit(f"asset not found: {ASSET} (run build_exe.bat first)")
    size = os.path.getsize(ASSET)
    name = os.path.basename(ASSET)
    print(f"  {name}  {size/1048576:.1f} MB")

    status, data = api("GET", f"/repos/{OWNER}/{REPO}/releases/{release_id}/assets", tok)
    if status == 200:
        for a in data:
            if a["name"] == name:
                print(f"  replacing existing asset (id={a['id']})")
                api("DELETE", f"/repos/{OWNER}/{REPO}/releases/assets/{a['id']}", tok)

    with open(ASSET, "rb") as fh:
        blob = fh.read()
    status, data = api(
        "POST",
        f"https://uploads.github.com/repos/{OWNER}/{REPO}/releases/{release_id}/assets?name={name}",
        tok, raw=blob, content_type="application/zip",
    )
    if status not in (200, 201):
        raise SystemExit(f"upload failed: {status} {data.get('message')}")
    print(f"  uploaded: {data.get('browser_download_url')}")


def main() -> int:
    tok = token()

    status, who = api("GET", "/user", tok)
    if status != 200:
        print(f"ERROR: token rejected ({status}): {who.get('message')}")
        return 2
    print(f"authenticated as: {who.get('login')}")

    status, repo = api("GET", f"/repos/{OWNER}/{REPO}", tok)
    if status != 200:
        print(f"ERROR: cannot access {OWNER}/{REPO}: {repo.get('message')}")
        return 2
    print(f"repository: {repo['full_name']}  (push={repo.get('permissions', {}).get('push')})")

    push(tok)
    if "--push-only" in sys.argv:
        return 0

    release_id = ensure_release(tok)
    upload(tok, release_id)

    status, repo = api("GET", f"/repos/{OWNER}/{REPO}", tok)
    print("\n=== done ===")
    print(f"  repo    {repo['html_url']}")
    print(f"  release {repo['html_url']}/releases/tag/{TAG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
