---
name: ir-pdf-downloader
description: Download static PDF files (annual reports, quarterly results) from ANY company's Investor Relations (IR) website using Python requests with proper headers. Works with Cloudflare-protected sites by targeting direct PDF URLs.
---

# IR PDF Downloader (Generic)

从**任何公司**的 IR（投资者关系）网站下载静态 PDF 文件（年报、季报）。支持 Wayback Machine CDX 搜索、SEC EDGAR 查找，以及任意 IR 域名的直接下载。

> 之前只支持 ir.jd.com，现在支持**任意公司的 IR 网站**。

---

## 这个工具 vs sec-finance — 何时用哪个？

| 场景 | 工具 |
|------|------|
| 已有 PDF 的**静态 URL**（年报/季报直链） | **ir-pdf-downloader** |
| 需要从 **SEC EDGAR** 获取公司财务数据（XBRL、20-F、6-K） | **sec-finance** |
| 不知道 PDF URL，需要**搜索发现** | **ir-pdf-downloader** + `find_ir_pdf.py` |
| 需要 XBRL 数值数据（收入、利润、资产负债表等） | **sec-finance** |
| IR 页面是 JS 动态渲染，但知道 PDF 静态 URL | **ir-pdf-downloader** |

---

## 快速开始

```bash
pip3 install requests

# ── 方法 1: 直接下载已知 PDF URL ──
python3 scripts/download_ir_pdf.py "https://ir.jd.com/static-files/..."

# ── 方法 2: 搜索 + 下载（任意 IR 域名）──
python3 scripts/download_ir_pdf.py --search-domain ir.baidu.com --download-found

# ── 方法 3: 找 PDF URL，再用脚本下载 ──
python3 scripts/find_ir_pdf.py --company Alibaba --year 2024

# ── 方法 4: 批量下载（CSV/JSON）──
python3 scripts/download_ir_pdf.py --input companies.csv

# ── 查看已知 IR 域名 ──
python3 scripts/download_ir_pdf.py --list-known-ir
```

---

## 工作流程：如何获取任意公司的年报

```
┌─────────────────────────────────────────────────────────┐
│  Step 1: 知道 PDF URL？                                    │
│   YES → 直接用 download_ir_pdf.py 下载                      │
│   NO  → Step 2                                            │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Step 2: 用 find_ir_pdf.py 搜索 PDF URL                    │
│                                                         │
│   find_ir_pdf.py --company Alibaba                      │
│   find_ir_pdf.py --domain ir.baidu.com --year 2024      │
│   find_ir_pdf.py --domain ir.pddgroup.com                │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Step 3: 找到 URL → 下载                                   │
│                                                         │
│   download_ir_pdf.py --search-domain ir.baidu.com \      │
│       --download-found --download-year 2024             │
└─────────────────────────────────────────────────────────┘
```

---

## 找 PDF URL 的方法

### 方法 1: Wayback Machine CDX（推荐，通用）

```bash
# 用脚本搜索（最简单）
python3 scripts/find_ir_pdf.py --domain ir.baidu.com --year 2024

# 或直接用 CDX API
curl "https://web.archive.org/cdx/search/cdx?url=*ir.baidu.com*/*.pdf&output=json&limit=50&fl=original,timestamp&filter=statuscode:200&filter=mimetype:application/pdf&collapse=original"
```

### 方法 2: SEC EDGAR（美股上市公司）

SEC 要求在美国上市的中国公司提交 20-F（年报）和 6-K（季报），PDF 附件可直接下载：

```bash
# 用 find_ir_pdf.py 查 SEC EDGAR
python3 scripts/find_ir_pdf.py --company Alibaba --sources edgar

# 手动查 CIK
# https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001577552&type=20-F
```

### 方法 3: Google 搜索

```
site:ir.{company}.com filetype:pdf annual report
site:ir.alibabagroup.com filetype:pdf
```

### 方法 4: 直接探测 IR 域名

```bash
# 常见 URL 模式
https://ir.company.com/en-US/assets/pdf/annual-report/2024-Annual-Report.pdf
https://ir.company.com/assets/pdf/annual-report-2024.pdf
```

---

## 已知中国股票 IR 域名速查

| 公司 | IR 域名 | 常见 URL 模式 |
|------|---------|--------------|
| JD.com | `ir.jd.com` | `/static-files/{uuid}.pdf` |
| Alibaba | `ir.alibabagroup.com` | `/en-US/assets/pdf/annual-report/*.pdf` |
| Baidu | `ir.baidu.com` | `/static-files/{uuid}.pdf` |
| Tencent | `ir.tencent.com` | `/static-files/{uuid}.pdf` |
| PDD Holdings | `ir.pddgroup.com` | `/static-files/{uuid}.pdf` |
| NetEase | `ir.163.com` | `/static-files/{uuid}.pdf` |
| Meituan | `ir.meituan.com` | `/static-files/{uuid}.pdf` |
| Xiaomi | `ir.xiaomi.com` | `/static-files/{uuid}.pdf` |
| NIO | `ir.nio.cn` | `/static-files/{uuid}.pdf` |
| Li Auto | `ir.lixiang.com` | `/static-files/{uuid}.pdf` |
| Bilibili | `ir.bilibili.com` | `/static-files/{uuid}.pdf` |
| Trip.com | `ir.trip.com` | `/static-files/{uuid}.pdf` |
| Ke Holdings | `ir.ke.com` | `/static-files/{uuid}.pdf` |
| XPeng | `ir.xpeng.com` | `/static-files/{uuid}.pdf` |
| ByteDance | `ir.bytedance.com` | `/static-files/{uuid}.pdf` |

---

## 核心方法

**关键发现：** 大多数 IR 网站的 HTML 页面有 Cloudflare + JS 动态渲染，但**静态 PDF 文件可以绕过**。只需正确 headers（User-Agent + Referer），无需 SSL 跳过。

```python
import requests

url = "https://ir.jd.com/static-files/a8463094-68bf-40ad-9185-ed9f16ce564e"
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
    "Referer": "https://ir.jd.com/",  # 关键！指向 IR 根域
    "Accept": "*/*",
}
resp = requests.get(url, headers=headers, timeout=15)
# Referer 会自动从 URL 推断（v2.0+），无需手动指定
```

---

## 脚本功能

### `download_ir_pdf.py` — 下载器

| 参数 | 说明 |
|------|------|
| `url [url ...]` | 下载一个或多个 PDF |
| `--list FILE` | 从文本文件读取 URL 列表（每行一个） |
| `--input FILE` | 从 CSV/JSON 批量下载（columns: company, url, out_dir） |
| `--search-domain DOMAIN` | 用 Wayback Machine CDX 搜索域名下的所有 PDF |
| `--search-wb DOMAIN` | `--search-domain` 的别名 |
| `--download-found` | 配合 `--search-domain`，下载搜索到的所有 PDF |
| `--download-year YEAR` | 只下载指定年份的 PDF（如 `--download-year 2024`） |
| `--list-known-ir` | 列出已知中国股票 IR 域名 |
| `--output DIR` | 输出目录（默认：`./downloads/`） |
| `--referer URL` | 自定义 Referer（默认：自动从 URL 推断） |
| `--timeout SEC` | 请求超时（默认 30s） |
| `--retries N` | 重试次数（默认 3） |
| `--delay SEC` | 批量下载间隔（默认 1.0s） |
| `--verbose` | 调试模式 |

### `find_ir_pdf.py` — 搜索器

| 参数 | 说明 |
|------|------|
| `--company NAME` | 按公司名搜索（支持 JD, Alibaba, Baidu 等） |
| `--domain DOMAIN` | 直接指定 IR 域名搜索 |
| `--year YEAR` | 只返回指定年份的 PDF |
| `--sources` | 指定来源：`wayback`, `edgar`, `direct`（默认全部） |
| `--format json\|text` | 输出格式（默认 text） |
| `--output FILE` | 结果写入 JSON 文件 |

---

## 批量下载示例

### CSV 格式 (`companies.csv`):
```csv
company,url,out_dir
JD.com,https://ir.jd.com/static-files/...,./jd_reports
Alibaba,https://ir.alibabagroup.com/en-US/assets/pdf/...,./alibaba_reports
Baidu,https://ir.baidu.com/static-files/...,./baidu_reports
```

### JSON 格式 (`companies.json`):
```json
[
  {"company": "JD.com", "url": "https://ir.jd.com/static-files/...", "out_dir": "./jd"},
  {"company": "Alibaba", "url": "https://ir.alibabagroup.com/...", "out_dir": "./alibaba"}
]
```

```bash
python3 scripts/download_ir_pdf.py --input companies.csv --delay 1.5
```

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
| `HTTP 403 Forbidden` | Referer 错误或缺失 | 确保 Referer 指向 IR 根域；v2.0+ 自动推断 |
| `HTTP 404 Not Found` | PDF URL 不存在 | 用 `--search-domain` 重新查找 |
| `File too small (<10KB)` | 下载到 Cloudflare 挑战页 | 检查 URL 是否正确 |
| `Invalid PDF magic bytes` | 下载的不是 PDF | 同上 |
| `No PDFs found (Wayback)` | 该域名没有被 Wayback 快照 | 尝试 `--sources edgar` 或 Google 搜索 |
| `CIK not found` | 公司不在 SEC EDGAR | 可能是港股/非美股，用 Wayback 或 Google |

---

## 判断规则

| 情况 | 方法 |
|------|------|
| 已知 PDF URL（任意公司） | `download_ir_pdf.py <url>` |
| 不知道 URL，但知道 IR 域名 | `download_ir_pdf.py --search-domain ir.x.com --download-found` |
| 不知道 URL，知道公司名 | `find_ir_pdf.py --company Alibaba` |
| 美股上市中国公司（20-F/6-K） | `find_ir_pdf.py --company Alibaba --sources edgar` |
| 完全不知道任何信息 | Google: `site:ir.company.com filetype:pdf annual report` |
| 需要财务数字（XBRL） | `sec-finance` |

---

## 安装

```bash
pip3 install requests
```

## 已知限制

- PDF URL 必须已知（用 `find_ir_pdf.py` 或 Wayback/SEC 找到）
- 如果公司不在 Wayback Machine 有 PDF 快照，且不在 SEC 提交 20-F/6-K，则需手动 Google
- SSL 错误：requests 默认处理，不需要 `verify=False`
