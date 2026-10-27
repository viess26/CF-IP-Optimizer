# CF-IP-Optimizer

基于 GitHub Actions 的 Cloudflare IPv4 连接测试、结果导出和排行榜项目。

## 功能
- 从 Cloudflare 官方 IPv4 地址范围页面获取网段
- 对公开网段中的有限候选地址进行抽样
- 多轮 TCP 443 连接测试，统计发送/接收次数、失败比例和延迟
- 生成 `result.csv`、`result.txt` 和 `index.html`
- GitHub Actions 每 6 小时安排运行，也可手动运行

## 快速开始
1. 将整个项目文件上传到 GitHub 仓库，保留 `.github/workflows/optimizer.yml` 路径。
2. 打开仓库 `Actions`，启用工作流（如果 GitHub 提示）。
3. 进入 `Cloudflare IP Optimizer`，点击 `Run workflow`。
4. 成功后查看 `result.csv`、`result.txt` 和 `index.html`。

## 可选：启用 HTTPS 和下载测试
如果你拥有并控制一个通过 Cloudflare 代理的域名，可以编辑 `config.json`：
- `test_host`：填写你自己的域名
- `test_path`：填写允许匿名 GET 请求的测试路径，例如 `/`

测试会连接候选 IP，同时保留 TLS SNI 和 HTTP Host。下载速度会受响应内容大小、网络和服务配置影响。请只测试自己控制或获准测试的域名。未设置 `test_host` 时，HTTPS 状态和下载速度显示为空/N/A。

## 重要限制
- 结果来自 GitHub 托管运行器，不代表你的家用网络或手机网络。
- TCP 443 成功不等于 HTTPS、WebSocket 或 VLESS 服务可用。
- 本项目不会生成代理节点，也不会替代服务端配置。
- 项目只对有限数量的候选 IP 抽样测试，不是全网扫描。
- 测试结果会随时间和网络位置变化。
