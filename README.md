# CF-IP-Optimizer V3

## 功能
- 抽样测试 Cloudflare 官方 IPv4 地址范围
- 多轮 TCP 443 连接测试，统计成功率、失败率与延迟
- 可选 HTTPS 请求和下载速度测量
- 生成 `result.csv`、`result.txt` 和 `index.html`
- GitHub Actions 每 6 小时安排运行，也可手动触发

## 综合评分
当存在有效 HTTPS 下载数据时，评分由 TCP 延迟 40%、下载速度 35%、TCP 成功率 25% 组成。若本次没有有效下载数据，则根据 TCP 延迟与成功率重新归一化。分数是本轮候选 IP 的相对比较值。

## 使用
上传项目文件并保留 `.github/workflows/optimizer.yml` 路径，然后进入 GitHub 仓库 Actions，手动运行 `Cloudflare IP Optimizer`。完成后查看三个结果文件。

默认测试目标是 `speed.cloudflare.com`。若 HTTPS 测试没有有效结果，可在 `config.json` 中将 `test_host` 和 `test_path` 改成自己控制且允许匿名 GET 的 HTTPS 服务。只测试自己控制或获准测试的服务。

## 限制
- GitHub 云端结果不代表你电脑或手机的实际网络。
- TCP 连接失败率不等同于 ICMP 丢包率。
- HTTP 200 不保证代理、WebSocket 或 VLESS 配置可用。
- 只对有限候选地址抽样，不是全网扫描。
