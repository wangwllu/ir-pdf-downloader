---
name: ir-pdf-downloader
description: Download static PDF files (annual reports, quarterly results) from Cloudflare-protected IR websites using Python requests with proper headers. Use when IR pages are JS-rendered and blocked, but the PDF files themselves have direct URLs.
---

# IR PDF Downloader

从 Cloudflare 保护的 IR（投资者关系）网站下载静态 PDF 文件（年报、季报）。

---

## 这个工具 vs sec-finance 工具 — 何时用哪个？

| 场景 | 工具 |
|------|------|
| 已有 PDF 的**静态 URL**（年报/季报直链） | **ir-pdf-downloader** |
| 需要从 **SEC EDGAR** 获取公司财务数据（XBRL、20-F、6-K） | **sec-finance** |
| IR 页面是 JS 动态渲染，但知道 PDF UUID 形式的静态 URL | **ir-pdf-downloader** |
| 不知道 PDF URL，需要通过 SEC filings 找 PDF 链接 | **sec-finance** |
| 年报是静态 PDF 文件（非 XBRL），且已知 URL | **ir-pdf-downloader** |
| 需要 XBRL 数值数据（收入、利润、资产负债表等） | **sec-finance** |

**简单说：** 有 PDF 直链 → ir-pdf-downloader；有 CIK/公司名，想拿财务数字 → sec-finance。

---

## 快速开始

```bash
# 安装依赖
pip3 install requests

# 下载单个 PDF
python3 scripts/download_ir_pdf.py "https://ir.jd.com/static-files/a8463094-68bf-40ad-9185-ed9f16ce564e"

# 批量下载（文件每行一个 URL）
python3 scripts/download_ir_pdf.py --list urls.txt

# 调试模式
python3 scripts/download_ir_pdf.py --verbose "https://ir.jd.com/static-files/..."

# 搜索 Wayback Machine 上某域名的所有 PDF
python3 scripts/download_ir_pdf.py --search-wb ir.jd.com

# 搜索 + 自动下载
python3 scripts/download_ir_pdf.py --search-wb ir.jd.com --download-found
```

---

## 核心方法

**关键发现：** ir.jd.com 等 IR 网站的 HTML 页面有 Cloudflare + JS 动态渲染，但**静态 PDF 文件可以绕过**——只需正确 headers（User-Agent + Referer），无需 SSL 跳过。

```python
import requests

url = "https://ir.jd.com/static-files/a8463094-68bf-40ad-9185-ed9f16ce564e"
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://ir.jd.com/",
    "Accept": "*/*",
}
resp = requests.get(url, headers=headers, timeout=15, stream=True)
if resp.status_code == 200 and "pdf" in resp.headers.get("Content-Type", ""):
    data = resp.content
    with open("annual_report.pdf", "wb") as f:
        f.write(data)
    print(f"Downloaded {len(data):,} bytes")
```

---

## 判断规则

| 情况 | 方法 |
|------|------|
| 静态 PDF URL 已知（年报/季报 PDF 链接） | `ir-pdf-downloader` |
| HTML 页面被 Cloudflare 拦截（403/挑战页面） | 找 PDF 静态文件 URL，然后用 `ir-pdf-downloader` |
| 页面是 JS 动态渲染（选择器下拉） | 找 PDF 静态文件 URL，然后用 `ir-pdf-downloader` |
| 完全不知道 PDF URL | 用 `--search-wb`（Wayback Machine）或 SEC EDGAR |
| 需要财务数字（XBRL） | `sec-finance` |

---

## 找 PDF URL 的方法

### 1. Wayback Machine CDX（推荐，用于未知 URL）

```bash
# 搜索某公司 IR static-files 下的 PDF
curl "https://web.archive.org/cdx/search/cdx?url=*ir.jd.com*/static-files/*.pdf&output=json&limit=20&fl=original"
```

或用脚本：
```bash
python3 scripts/download_ir_pdf.py --search-wb ir.jd.com
```

### 2. Google 搜索

```
site:ir.{company}.com filetype:pdf annual report
```

### 3. SEC EDGAR

年报 20-F 或 6-K 附件中有 PDF 链接。用 `sec-finance` 工具查。

### 4. IR 页面源码

某些 IR 页面在 HTML 里直接埋了 PDF 链接（无 JS 渲染）。

---

## 常见 IR 网站 PDF URL 格式

```python
# JD.com 年报
"https://ir.jd.com/static-files/{uuid}"

# Alibaba 年报（通常在 /en-US/assets/pdf/ 下）
"https://www.alibabagroup.com/en-US/assets/pdf/annual-report/2024-Annual-Report.pdf"

# Baidu 年报
"https://ir.baidu.com/static-files/{uuid}"

# Tencent 年报
"https://www.tencent.com/en-us/ir/annual-reports.shtml"  # JS 页面，需找 PDF 直链
```

---

## 脚本功能说明

`scripts/download_ir_pdf.py` 提供以下功能：

| 参数 | 说明 |
|------|------|
| `url [url ...]` | 下载一个或多个 PDF |
| `--list FILE` | 从文本文件读取 URL 列表（每行一个） |
| `--search-wb DOMAIN` | 用 Wayback Machine CDX API 搜索域名下的 PDF URL |
| `--download-found` | 配合 `--search-wb`，下载搜索到的所有 PDF |
| `--output DIR` | 输出目录（默认：`./downloads/`） |
| `--referer URL` | 自定义 Referer header |
| `--timeout SEC` | 请求超时（默认 30s） |
| `--retries N` | 重试次数（默认 3） |
| `--delay SEC` | 批量下载间隔（默认 1.0s） |
| `--verbose` | 调试模式，显示详细日志 |

---

## 验证下载结果

下载后自动验证：
1. **文件大小** — 小于 10KB 判定为错误/挑战页面
2. **PDF Magic Bytes** — 检查文件开头是否为 `%PDF-`

如验证失败，文件会被删除并重试。

---

## 常见错误与解决

| 错误 | 原因 | 解决 |
|------|------|------|
| `HTTP 403 Forbidden` | Referer 错误或缺失 | 确保 Referer 指向 IR 根域，如 `https://ir.jd.com/` |
| `HTTP 404 Not Found` | PDF URL 不存在 | 用 `--search-wb` 重新查找，或换其他来源 |
| `File too small (<10KB)` | 下载到 Cloudflare 挑战页 | 检查 URL 是否正确，尝试加 Referer |
| `Invalid PDF magic bytes` | 下载的不是 PDF | 同上，可能是错误页面 |
| `Connection error` | 网络问题 | 检查网络，或加 `--timeout` |
| `No PDFs found` | Wayback Machine 没有快照 | 尝试其他方法（SEC EDGAR、Google） |

---

## 已知限制

- 此方法的前提是**已知 PDF 的静态 URL**（UUID 形式）
- 如果完全不知道 PDF URL，需要先通过 `--search-wb` 或 SEC EDGAR 找到
- requests 默认处理 SSL，不需要手动跳过验证
- 如果遇到 SSL 错误，可以加 `verify=False`（脚本暂不支持，可修改源码）

## 安装

```bash
pip3 install requests
```
