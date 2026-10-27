import concurrent.futures, csv, html, ipaddress, json, socket, ssl, statistics, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

C = json.loads(Path("config.json").read_text(encoding="utf-8"))
MAX_BYTES = int(C.get("download_test_bytes", 524288))

def get_ranges():
    req = urllib.request.Request("https://www.cloudflare.com/ips-v4", headers={"User-Agent":"CF-IP-Optimizer/3.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read().decode()
    Path("ips-v4.txt").write_text(text, encoding="utf-8")
    return [ipaddress.ip_network(x.strip()) for x in text.splitlines() if x.strip()]

def sample(networks, limit):
    nets = [n for n in networks if n.version == 4 and n.num_addresses > 2]
    if not nets or limit <= 0: return []
    per = max(1, limit // len(nets))
    out = []
    for n in nets:
        count = min(per, n.num_addresses - 2)
        for i in range(count):
            offset = 1 + int((i + .5) * (n.num_addresses - 2) / count)
            out.append(str(n.network_address + offset))
            if len(out) >= limit: break
        if len(out) >= limit: break
    return list(dict.fromkeys(out))[:limit]

def tcp(ip):
    t = time.perf_counter()
    try:
        with socket.create_connection((ip, int(C.get("port",443))), timeout=float(C.get("timeout_seconds",2.5))):
            return (time.perf_counter()-t)*1000, True
    except OSError:
        return None, False

def https(ip):
    host = str(C.get("test_host","")).strip()
    if not host: return "", "", ""
    path = str(C.get("test_path","/")).strip() or "/"
    t = time.perf_counter()
    try:
        raw = socket.create_connection((ip,443), timeout=float(C.get("timeout_seconds",2.5)))
        with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as s:
            s.settimeout(float(C.get("timeout_seconds",2.5)))
            s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: CF-IP-Optimizer/3.0\r\nConnection: close\r\n\r\n").encode())
            first = s.recv(4096)
            if not first: return "", "", ""
            line = first.split(b"\r\n",1)[0].decode("latin1","replace").split()
            status = line[1] if len(line)>1 else ""
            sep = first.find(b"\r\n\r\n")
            body = len(first[sep+4:]) if sep>=0 else 0
            total = len(first)
            while total < MAX_BYTES:
                chunk = s.recv(min(65536, MAX_BYTES-total))
                if not chunk: break
                total += len(chunk); body += len(chunk)
            elapsed = time.perf_counter()-t
            return status, round(elapsed*1000,2), round(body/(1024*1024)/elapsed,3) if elapsed else 0
    except (OSError, ssl.SSLError, TimeoutError):
        return "", "", ""

def test(ip):
    rounds = max(1,int(C.get("rounds",5))); values=[]
    for _ in range(rounds):
        ms, ok = tcp(ip)
        if ok: values.append(ms)
        time.sleep(.06)
    row = {"ip":ip,"sent":rounds,"received":len(values),
           "loss_pct":round((rounds-len(values))*100/rounds,2),
           "success_rate_pct":round(len(values)*100/rounds,2),
           "avg_latency_ms":round(statistics.mean(values),2) if values else "",
           "median_latency_ms":round(statistics.median(values),2) if values else "",
           "min_latency_ms":round(min(values),2) if values else "",
           "download_MB_s":"","https_status":"","https_latency_ms":"","score":0,
           "source":"Cloudflare IPv4 range"}
    row["https_status"],row["https_latency_ms"],row["download_MB_s"] = https(ip)
    return row

def num(x):
    try: return float(x)
    except (TypeError,ValueError): return None

def score(rows):
    lats=[num(r["median_latency_ms"]) for r in rows if num(r["median_latency_ms"]) is not None]
    speeds=[num(r["download_MB_s"]) for r in rows if str(r["https_status"]).startswith("2") and num(r["download_MB_s"]) and num(r["download_MB_s"])>0]
    bestlat=min(lats) if lats else None; bestspeed=max(speeds) if speeds else None
    for r in rows:
        lat=num(r["median_latency_ms"]); sp=num(r["download_MB_s"])
        lc=bestlat/lat if bestlat and lat and lat>0 else 0
        sc=min(sp/bestspeed,1) if bestspeed and sp and sp>0 and str(r["https_status"]).startswith("2") else 0
        success=float(r["success_rate_pct"])/100
        r["score"]=round(40*lc+35*sc+25*success,2) if bestspeed else round((40*lc+25*success)*100/65,2)

def make_html(rows):
    cols=[("排名","rank"),("综合评分","score"),("IP 地址","ip"),("已发送","sent"),("已接收","received"),("丢包率(%)","loss_pct"),("平均延迟(ms)","avg_latency_ms"),("中位延迟(ms)","median_latency_ms"),("下载速度(MB/s)","download_MB_s"),("HTTPS 状态","https_status"),("HTTPS 耗时(ms)","https_latency_ms"),("数据来源","source")]
    th="".join(f"<th>{html.escape(a)}</th>" for a,b in cols); trs=[]
    for i,r in enumerate(rows,1):
        r["rank"]=i
        trs.append("<tr>"+"".join(f"<td>{html.escape(str(r.get(k,'')) or 'N/A')}</td>" for a,k in cols)+"</tr>")
    note="评分权重：TCP 延迟 40%、HTTPS 下载速度 35%、TCP 成功率 25%。" if C.get("test_host") else "未配置 HTTPS 测试，评分仅使用 TCP 延迟和成功率。"
    page=f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cloudflare IP 综合排行榜</title><style>body{{font-family:Arial,sans-serif;margin:24px;background:#f7f8fa;color:#202124}}.box{{overflow:auto;background:white}}table{{border-collapse:collapse;white-space:nowrap;width:100%}}th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#eef2f7;position:sticky;top:0}}.note{{padding:12px;background:#fff4d6}}a{{margin-right:16px}}</style></head><body><h1>Cloudflare IP 综合排行榜</h1><p>生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · 候选数：{len(rows)}</p><p class="note">{html.escape(note)}</p><p><a href="result.csv">下载 CSV</a><a href="result.txt">下载优选 IP TXT</a></p><div class="box"><table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table></div><p>GitHub 云端结果不一定代表本地网络；TCP 443 成功不代表 WebSocket/VLESS 服务可用。</p></body></html>"""
    Path("index.html").write_text(page,encoding="utf-8")

def main():
    nets=get_ranges(); ips=sample(nets,int(C.get("max_candidates",120)))
    if not ips: raise RuntimeError("No IPv4 candidates found")
    print(f"Testing {len(ips)} candidates")
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(C.get("max_workers",24))) as ex:
        rows=list(ex.map(test,ips))
    score(rows)
    rows.sort(key=lambda r:(-r["score"],num(r["median_latency_ms"]) if num(r["median_latency_ms"]) is not None else float("inf")))
    fields=["ip","score","sent","received","loss_pct","success_rate_pct","avg_latency_ms","median_latency_ms","min_latency_ms","download_MB_s","https_status","https_latency_ms","source"]
    with open("result.csv","w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    minrate=float(C.get("min_success_rate",.8)); maxlat=float(C.get("max_latency_ms",300))
    selected=[r for r in rows if num(r["median_latency_ms"]) is not None and float(r["success_rate_pct"])/100>=minrate and float(r["median_latency_ms"])<=maxlat and (not C.get("test_host") or (str(r["https_status"]).startswith("2") and num(r["download_MB_s"]) and num(r["download_MB_s"])>0))]
    Path("result.txt").write_text("".join(r["ip"]+"\n" for r in selected),encoding="utf-8")
    make_html(rows)
    print(f"Done: {len(rows)} tested; {len(selected)} passed filters.")

if __name__=="__main__": main()
