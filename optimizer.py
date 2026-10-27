#!/usr/bin/env python3
import concurrent.futures
import csv
import html
import ipaddress
import json
import socket
import ssl
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONFIG = json.loads(Path("config.json").read_text(encoding="utf-8"))
RANGES_URL = "https://www.cloudflare.com/ips-v4"
MAX_BYTES = int(CONFIG.get("download_test_bytes", 524288))


def fetch_networks():
    req = urllib.request.Request(
        RANGES_URL, headers={"User-Agent": "CF-IP-Optimizer/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        content = response.read().decode("utf-8")
    Path("ips-v4.txt").write_text(content, encoding="utf-8")
    return [ipaddress.ip_network(line.strip()) for line in content.splitlines()
            if line.strip()]


def sample_ips(networks, limit):
    """Sample a bounded number of addresses across published IPv4 ranges."""
    candidates = []
    usable = [n for n in networks if n.version == 4 and n.num_addresses > 2]
    if not usable or limit <= 0:
        return []
    per_network = max(1, limit // len(usable))
    for network in usable:
        count = min(per_network, network.num_addresses - 2)
        if count == 1:
            candidates.append(str(network.network_address + network.num_addresses // 2))
        else:
            for i in range(count):
                offset = 1 + int(i * (network.num_addresses - 2) / count)
                candidates.append(str(network.network_address + offset))
        if len(candidates) >= limit:
            break
    return list(dict.fromkeys(candidates))[:limit]


def tcp_once(ip, port, timeout):
    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return (time.perf_counter() - start) * 1000, True
    except OSError:
        return None, False


def https_test_ip(ip, host, path, timeout):
    """Connect to candidate IP while preserving TLS SNI and HTTP Host."""
    start = time.perf_counter()
    context = ssl.create_default_context()
    try:
        raw = socket.create_connection((ip, 443), timeout=timeout)
        with context.wrap_socket(raw, server_hostname=host) as conn:
            conn.settimeout(timeout)
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "User-Agent: CF-IP-Optimizer/1.0\r\n"
                "Connection: close\r\n\r\n"
            )
            conn.sendall(request.encode("ascii", errors="ignore"))
            first = conn.recv(4096)
            if not first:
                return "", "", ""
            header_end = first.find(b"\r\n")
            status_line = first[:header_end].decode("latin1", errors="replace") if header_end >= 0 else ""
            pieces = status_line.split(" ")
            status = pieces[1] if len(pieces) >= 2 else ""
            received = len(first)
            body_start = first.find(b"\r\n\r\n")
            body_bytes = len(first[body_start + 4:]) if body_start >= 0 else 0
            while received < MAX_BYTES:
                chunk = conn.recv(min(65536, MAX_BYTES - received))
                if not chunk:
                    break
                received += len(chunk)
                body_bytes += len(chunk)
            elapsed = time.perf_counter() - start
            speed = round((body_bytes / (1024 * 1024)) / elapsed, 3) if elapsed > 0 else 0
            return status, round(elapsed * 1000, 2), speed
    except (OSError, ssl.SSLError, TimeoutError):
        return "", "", ""


def test_ip(ip):
    port = int(CONFIG.get("port", 443))
    timeout = float(CONFIG.get("timeout_seconds", 2.5))
    rounds = max(1, int(CONFIG.get("rounds", 4)))
    timings = []
    for _ in range(rounds):
        ms, ok = tcp_once(ip, port, timeout)
        if ok:
            timings.append(ms)
        time.sleep(0.08)

    row = {
        "ip": ip,
        "sent": rounds,
        "received": len(timings),
        "loss_pct": round((rounds - len(timings)) / rounds * 100, 2),
        "avg_latency_ms": round(statistics.mean(timings), 2) if timings else "",
        "median_latency_ms": round(statistics.median(timings), 2) if timings else "",
        "min_latency_ms": round(min(timings), 2) if timings else "",
        "download_MB_s": "",
        "https_status": "",
        "https_latency_ms": "",
        "source": "Cloudflare IPv4 range"
    }
    host = str(CONFIG.get("test_host", "")).strip()
    path = str(CONFIG.get("test_path", "/")).strip() or "/"
    if host:
        status, latency, speed = https_test_ip(ip, host, path, timeout)
        row["https_status"] = status
        row["https_latency_ms"] = latency
        row["download_MB_s"] = speed
    return row


def render_html(rows, generated_at, https_enabled):
    columns = [
        ("IP 地址", "ip"), ("已发送", "sent"), ("已接收", "received"),
        ("丢包率(%)", "loss_pct"), ("平均延迟(ms)", "avg_latency_ms"),
        ("下载速度(MB/s)", "download_MB_s"), ("HTTPS 状态", "https_status"),
        ("HTTPS 延迟(ms)", "https_latency_ms"), ("数据来源", "source")
    ]
    header = "".join(f"<th>{html.escape(label)}</th>" for label, _ in columns)
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(str(row.get(key, '')) or 'N/A')}</td>"
            for _, key in columns
        )
        body.append(f"<tr>{cells}</tr>")
    note = (
        "HTTPS 与下载测试已启用；结果针对 config.json 中配置的域名。"
        if https_enabled else
        "尚未配置测试域名：HTTPS 状态和下载速度为 N/A。TCP 成功不代表 VLESS/WS/TLS 服务可用。"
    )
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cloudflare IP 优选排行榜</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:24px;color:#202124;background:#f7f8fa}}
h1{{font-size:1.7rem}} .meta{{color:#555}} .note{{padding:12px;background:#fff4d6;border-radius:8px}}
.wrap{{overflow:auto;background:white;border-radius:10px;margin-top:16px}} table{{border-collapse:collapse;width:100%;white-space:nowrap}}
th,td{{padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:left}} th{{background:#eef2f7;position:sticky;top:0}}
tr:hover{{background:#f5faff}} a{{color:#155eef}} .links{{margin:16px 0}}
</style></head><body>
<h1>Cloudflare IP 优选排行榜</h1>
<p class="meta">生成时间：{html.escape(generated_at)} · 测试地址数量：{len(rows)}</p>
<p class="note">{html.escape(note)}</p>
<div class="links"><a href="result.csv">下载 CSV 完整结果</a>　|　<a href="result.txt">下载筛选 IP 列表</a></div>
<div class="wrap"><table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
<p class="meta">GitHub 云端测试不一定代表你的本地网络。测试针对公开 Cloudflare IPv4 范围抽样，不保证任意 IP 适用于特定代理服务。</p>
</body></html>"""
    Path("index.html").write_text(page, encoding="utf-8")


def main():
    print("Fetching Cloudflare published IPv4 ranges...")
    networks = fetch_networks()
    ips = sample_ips(networks, int(CONFIG.get("max_candidates", 120)))
    if not ips:
        raise RuntimeError("No IPv4 candidates were generated.")
    print(f"Testing {len(ips)} candidate IPs...")
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=int(CONFIG.get("max_workers", 24))
    ) as pool:
        rows = list(pool.map(test_ip, ips))
    rows.sort(key=lambda r: (
        r["received"] == 0,
        r["loss_pct"],
        r["median_latency_ms"] if r["median_latency_ms"] != "" else float("inf")
    ))
    fields = [
        "ip", "sent", "received", "loss_pct", "avg_latency_ms",
        "median_latency_ms", "min_latency_ms", "download_MB_s",
        "https_status", "https_latency_ms", "source"
    ]
    with open("result.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    max_latency = float(CONFIG.get("max_latency_ms", 300))
    min_success = float(CONFIG.get("min_success_rate", 0.75))
    selected = [
        r for r in rows
        if r["sent"] and r["received"] / r["sent"] >= min_success
        and r["median_latency_ms"] != ""
        and r["median_latency_ms"] <= max_latency
    ]
    Path("result.txt").write_text(
        "".join(r["ip"] + "\n" for r in selected), encoding="utf-8"
    )
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    render_html(rows, generated_at, bool(str(CONFIG.get("test_host", "")).strip()))
    print(f"Done: {len(rows)} tested; {len(selected)} passed filters.")


if __name__ == "__main__":
    main()
