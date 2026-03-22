---
name: ir-pdf-downloader
description: Download static PDF files (annual reports, quarterly results) from Cloudflare-protected IR websites using Python requests with proper headers. Use when IR pages are JS-rendered and blocked, but the PDF files themselves have direct URLs.
---

# IR PDF Downloader

从 Cloudflare 保护的 IR（投资者关系）网站下载静态 PDF 文件（年报、季报）。

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

## 判断规则

| 情况 | 方法 |
|------|------|
| 静态 PDF URL 已知（年报/季报 PDF 链接） | requests + 正确 headers |
| HTML 页面被 Cloudflare 拦截（403/挑战页面） | 找 PDF 静态文件 URL |
| 页面是 JS 动态渲染（选择器下拉） | 找 PDF 静态文件 URL |
| 完全不知道 PDF URL | 用 Wayback Machine 或 SEC EDGAR |

## 判断是否成功

```python
resp = requests.get(url, headers=headers, timeout=15, stream=True)
print(resp.status_code)         # 200 = 成功
print(resp.headers["Content-Type"])  # application/pdf = 正确文件
print(len(resp.content))        # > 1MB = 完整文件
```

## 常见 IR 网站 PDF URL 格式

```python
# JD.com 年报
"https://ir.jd.com/static-files/{uuid}"

# Alibaba 年报（通常在 /en-US/assets/pdf/ 下）
"https://www.alibabagroup.com/en-US/assets/pdf/annual-report/2024-Annual-Report.pdf"

# Baidu 年报
"https://ir.baidu.com/static-files/{uuid}"
```

## 找 PDF URL 的方法

1. **Wayback Machine 快照**：`web.archive.org/cdx/search/cdx?url=ir.{company}.com/static-files/&fl=original&limit=20`
2. **Google 搜索**：`site:ir.{company}.com filetype:pdf annual report`
3. **SEC EDGAR**：年报 20-F 或 6-K 附件中有 PDF 链接
4. **IR 页面源码**：某些 IR 页面在 HTML 里直接埋了 PDF 链接（无 JS 渲染）

## 已知限制

- 此方法的前提是**已知 PDF 的静态 URL**（UUID 形式）
- 如果完全不知道 PDF URL，需要先通过 Wayback Machine 或 SEC EDGAR 找到
- requests 默认处理 SSL，不需要手动跳过验证（除非遇到证书问题）
- 如果遇到 SSL 错误，加 `verify=False`

## 完整流程示例

```python
import requests, re

def find_ir_pdf_urls(company_domain):
    """从 Wayback Machine 找某公司 IR static-files PDF URL"""
    import urllib.parse
    q = urllib.parse.quote(f"*{company_domain}*/static-files/*.pdf")
    url = f"https://web.archive.org/cdx/search/cdx?url={q}&output=json&limit=20&fl=original"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    urls = [row[0] for row in resp.json()[1:]]  # skip header row
    pdfs = [u for u in urls if ".pdf" in u.lower()]
    return pdfs

def download_ir_pdf(url, out_path, referer=None):
    """下载 IR PDF，验证是否为有效 PDF"""
    if referer is None:
        referer = "/".join(url.split("/")[:3])  # 自动从 URL 推断
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": referer,
    }
    resp = requests.get(url, headers=headers, timeout=15, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    if "pdf" not in resp.headers.get("Content-Type", "").lower():
        raise RuntimeError(f"Not a PDF: {resp.headers.get('Content-Type')}")
    data = resp.content
    if len(data) < 10000:  # 小于 10KB 很可能是错误页
        raise RuntimeError(f"File too small ({len(data)} bytes), likely error page")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Downloaded {len(data):,} bytes -> {out_path}")
    return out_path
```

## 安装

```bash
# 无需额外依赖，requests 为标准库（macOS 自带）
# 如需安装：
pip3 install requests
```

## 注意事项

- **Referer 必须正确**：指向 IR 网站根目录，否则被拦截
- **stream=True**：大文件必须用 stream 模式，否则内存爆炸
- **Content-Type 检查**：下载后立即验证，防止下载到错误页面
- **文件大小检查**：小于 10KB 的一定是错误/挑战页面
