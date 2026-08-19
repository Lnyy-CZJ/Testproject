from __future__ import annotations

import json
import hmac
import os
import uuid
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.parse import urlparse

from trackevents_core import analyze_log_text


def normalize_base_path(value: str | None) -> str:
    """将工具基础路径转换为可安全参与路由匹配的标准格式。

    参数说明:
        value: 环境变量或调用方传入的 URL 路径前缀。空值表示根路径。

    返回值:
        不带末尾斜杠的路径；根路径模式返回空字符串。

    异常说明:
        ValueError: 路径包含查询参数、父目录、重复斜杠等危险结构时抛出。
    """
    raw_path = (value or "").strip()
    if not raw_path or raw_path == "/":
        return ""
    if any(marker in raw_path for marker in ("?", "#", "..", "://")):
        raise ValueError(f"TRACKEVENTS_BASE_PATH 不是有效路径: {raw_path}")
    normalized = raw_path if raw_path.startswith("/") else f"/{raw_path}"
    normalized = normalized.rstrip("/")
    if "//" in normalized:
        raise ValueError(f"TRACKEVENTS_BASE_PATH 不能包含重复斜杠: {raw_path}")
    return normalized


HOST = os.environ.get("TRACKEVENTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("TRACKEVENTS_PORT", "8000"))
BASE_PATH = normalize_base_path(os.environ.get("TRACKEVENTS_BASE_PATH"))
PLATFORM_HOME_URL = os.environ.get("PLATFORM_HOME_URL", "").strip()
PLATFORM_API_URL = os.environ.get("PLATFORM_API_URL", "").rstrip("/")
PLATFORM_CLIENT_TOKEN_FILE = os.environ.get("PLATFORM_CLIENT_TOKEN_FILE", "")
DEFAULT_LOG_PATH = Path(__file__).with_name("default.log")
FAVICON_PATH = Path(__file__).with_name("favicon.svg")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/svg+xml" href="__FAVICON_URL__">
  <title>埋点测试工具</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #667085;
      --line: #d9dee7;
      --brand: #1463ff;
      --ok: #0f8f5f;
      --bad: #c73333;
      --warn: #a16207;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 650;
      letter-spacing: 0;
    }
    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 20px 24px 32px;
    }
    .layout {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 15px;
      font-weight: 650;
    }
    .common-check-panel {
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }
    .common-check-panel h2 {
      margin-bottom: 4px;
    }
    .common-param-cell {
      min-width: max-content;
      white-space: nowrap;
    }
    .common-param-row {
      white-space: nowrap;
      margin: 2px 0;
    }
    .common-param-missing {
      color: var(--bad);
    }
    label {
      display: block;
      margin: 14px 0 6px;
      color: var(--muted);
      font-size: 13px;
    }
    input[type="file"], textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    input[type="file"] { padding: 9px; }
    textarea {
      min-height: 160px;
      resize: vertical;
      padding: 10px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
    }
    button {
      width: 100%;
      height: 40px;
      border: 0;
      border-radius: 6px;
      background: var(--brand);
      color: #fff;
      font-weight: 650;
      cursor: pointer;
      margin-top: 14px;
    }
    button.secondary {
      background: #eef2f7;
      color: var(--text);
      border: 1px solid var(--line);
    }
    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 12px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
    }
    .metric b {
      display: block;
      font-size: 24px;
      line-height: 1.1;
    }
    .metric span {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .tabs {
      display: flex;
      gap: 8px;
      margin: 16px 0 12px;
      flex-wrap: wrap;
    }
    .tabs button {
      width: auto;
      height: 34px;
      margin: 0;
      padding: 0 12px;
      background: #eef2f7;
      color: var(--text);
      border: 1px solid var(--line);
    }
    .tabs button.active {
      background: var(--brand);
      color: #fff;
      border-color: var(--brand);
    }
    .filter-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }
    .filter-bar select {
      min-width: 220px;
      height: 36px;
      padding: 0 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    .filter-bar button {
      width: auto;
      height: 36px;
      margin: 0;
      padding: 0 12px;
    }
    table {
      width: max-content;
      min-width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-weight: 650;
      background: #fbfcfe;
      position: sticky;
      top: 0;
    }
    .table-wrap {
      max-height: 560px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .status {
      display: inline-flex;
      min-width: 44px;
      justify-content: center;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 650;
    }
    .pass { background: #e8f7ef; color: var(--ok); }
    .fail { background: #fdecec; color: var(--bad); }
    .warn { background: #fff7dc; color: var(--warn); }
    .empty {
      padding: 48px 16px;
      text-align: center;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fbfcfe;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .business-param-cell {
      min-width: max-content;
      white-space: nowrap;
    }
    .business-param-row {
      white-space: nowrap;
    }
    .issues {
      margin: 0;
      padding-left: 18px;
    }
    .issues li { margin: 3px 0; }
    .hint {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    @media (max-width: 900px) {
      header { padding: 14px 16px; }
      main { padding: 16px; }
      .layout { grid-template-columns: 1fr; }
      .summary { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
    }

    /* 桌面工程工作台视觉层：与平台首页共享语义 token，不改变原有业务结构。 */
    :root {
      --color-canvas: #f5f5f7;
      --color-surface: #ffffff;
      --color-surface-subtle: #fbfbfd;
      --color-text-primary: #1d1d1f;
      --color-text-secondary: #6e6e73;
      --color-text-tertiary: #86868b;
      --color-divider: rgba(0, 0, 0, .12);
      --color-accent: #0071e3;
      --color-accent-hover: #0077ed;
      --color-success: #248a3d;
      --color-success-bg: #eaf6ed;
      --color-warning: #8a4a00;
      --color-warning-bg: #fff5e6;
      --color-danger: #d70015;
      --color-danger-bg: #fff0f1;
      --radius-control: 10px;
      --radius-container: 16px;
      --focus-ring: 0 0 0 3px rgba(0, 113, 227, .24);
    }
    html {
      min-width: 1080px;
      background: var(--color-canvas);
    }
    body {
      color: var(--color-text-primary);
      background: var(--color-canvas);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
        "PingFang SC", "Microsoft YaHei", sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    .app-header {
      height: 64px;
      padding: 0;
      border-bottom: 1px solid var(--color-divider);
      background: rgba(251, 251, 253, .88);
      backdrop-filter: saturate(180%) blur(18px);
      -webkit-backdrop-filter: saturate(180%) blur(18px);
    }
    .app-header-content {
      width: min(1360px, calc(100% - 64px));
      height: 100%;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .platform-brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
      font-weight: 650;
    }
    .platform-mark {
      display: grid;
      width: 28px;
      height: 28px;
      place-items: center;
      border-radius: 8px;
      color: #fff;
      background: var(--color-accent);
      font-size: 14px;
      font-weight: 700;
    }
    .header-context {
      margin-left: 14px;
      padding-left: 14px;
      border-left: 1px solid var(--color-divider);
      color: var(--color-text-secondary);
      font-size: 13px;
    }
    .header-home-link {
      color: var(--color-accent);
      font-size: 13px;
      font-weight: 550;
      text-decoration: none;
    }
    main {
      width: min(1360px, calc(100% - 64px));
      max-width: none;
      margin: 0 auto;
      padding: 32px 0 48px;
    }
    .page-heading {
      margin-bottom: 24px;
    }
    .page-heading h1 {
      margin: 0;
      font-size: 32px;
      font-weight: 650;
      letter-spacing: -.025em;
      line-height: 1.2;
    }
    .page-heading p {
      margin: 8px 0 0;
      color: var(--color-text-secondary);
      font-size: 14px;
    }
    .layout {
      grid-template-columns: 344px minmax(0, 1fr);
      gap: 20px;
    }
    .panel {
      padding: 20px;
      border: 1px solid var(--color-divider);
      border-radius: var(--radius-container);
      background: var(--color-surface);
    }
    .input-panel {
      position: sticky;
      top: 20px;
    }
    .panel h2 {
      margin: 0 0 4px;
      font-size: 17px;
      letter-spacing: -.01em;
    }
    .panel-intro {
      margin: 0 0 20px;
      color: var(--color-text-secondary);
      font-size: 12px;
      line-height: 1.5;
    }
    .field-group {
      margin-top: 18px;
    }
    .field-group:first-of-type {
      margin-top: 0;
    }
    label {
      margin: 0 0 7px;
      color: var(--color-text-primary);
      font-weight: 600;
    }
    input[type="file"], textarea {
      border: 1px solid var(--color-divider);
      border-radius: var(--radius-control);
      background: var(--color-surface);
      color: var(--color-text-primary);
      transition: border-color 150ms ease, box-shadow 150ms ease;
    }
    input[type="file"] {
      padding: 8px;
      color: var(--color-text-secondary);
      font-size: 12px;
    }
    input[type="file"]::file-selector-button {
      margin-right: 10px;
      padding: 6px 9px;
      border: 0;
      border-radius: 7px;
      color: var(--color-accent);
      background: #edf5ff;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }
    textarea {
      min-height: 126px;
      border-radius: var(--radius-control);
    }
    #expectedCounts {
      min-height: 154px;
    }
    input[type="file"]:focus-visible,
    textarea:focus-visible,
    select:focus-visible,
    button:focus-visible,
    a:focus-visible {
      outline: none;
      box-shadow: var(--focus-ring);
    }
    textarea[aria-invalid="true"] {
      border-color: var(--color-danger);
    }
    .field-error {
      margin: 7px 0 0;
      color: var(--color-danger);
      font-size: 12px;
    }
    .field-error:empty {
      display: none;
    }
    .action-stack {
      margin-top: 20px;
      display: grid;
      gap: 8px;
    }
    button {
      margin: 0;
      border-radius: var(--radius-control);
      background: var(--color-accent);
    }
    button:hover:not(:disabled) {
      background: var(--color-accent-hover);
    }
    button.secondary {
      border: 1px solid var(--color-divider);
      color: var(--color-text-primary);
      background: var(--color-surface);
    }
    button.secondary:hover:not(:disabled) {
      background: var(--color-surface-subtle);
    }
    .results-panel {
      min-height: 610px;
    }
    .run-summary {
      margin-bottom: 16px;
      padding: 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      border: 1px solid var(--color-divider);
      border-radius: 12px;
      background: var(--color-surface-subtle);
    }
    .run-summary-copy {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .run-summary-icon {
      display: grid;
      width: 34px;
      height: 34px;
      flex: none;
      place-items: center;
      border-radius: 50%;
      font-size: 16px;
      font-weight: 750;
    }
    .run-summary.pass-state .run-summary-icon {
      color: var(--color-success);
      background: var(--color-success-bg);
    }
    .run-summary.fail-state .run-summary-icon {
      color: var(--color-danger);
      background: var(--color-danger-bg);
    }
    .run-summary h2 {
      margin: 0 0 3px;
      font-size: 17px;
    }
    .run-summary p {
      margin: 0;
      color: var(--color-text-secondary);
      font-size: 12px;
    }
    .problem-count {
      color: var(--color-text-secondary);
      font-size: 13px;
      white-space: nowrap;
    }
    .problem-count strong {
      color: var(--color-text-primary);
      font-size: 20px;
    }
    .summary {
      gap: 10px;
    }
    .metric {
      border-color: var(--color-divider);
      border-radius: var(--radius-control);
      background: var(--color-surface);
    }
    .metric b {
      font-size: 21px;
    }
    .metric span,
    .hint {
      color: var(--color-text-secondary);
    }
    .tabs {
      gap: 4px;
      margin: 20px 0 12px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--color-divider);
    }
    .tabs button {
      border: 0;
      color: var(--color-text-secondary);
      background: transparent;
    }
    .tabs button.active {
      border-color: transparent;
      color: var(--color-accent);
      background: #edf5ff;
    }
    .filter-bar select {
      border-color: var(--color-divider);
      border-radius: var(--radius-control);
      color: var(--color-text-primary);
      background: var(--color-surface);
    }
    th, td {
      border-bottom-color: var(--color-divider);
    }
    th {
      color: var(--color-text-secondary);
      background: var(--color-surface-subtle);
    }
    .table-wrap {
      border-color: var(--color-divider);
      border-radius: var(--radius-control);
    }
    .pass { background: var(--color-success-bg); color: var(--color-success); }
    .fail { background: var(--color-danger-bg); color: var(--color-danger); }
    .warn { background: var(--color-warning-bg); color: var(--color-warning); }
    .common-param-missing { color: var(--color-danger); }
    .empty {
      min-height: 566px;
      padding: 48px 24px;
      display: grid;
      place-content: center;
      border: 1px dashed var(--color-divider);
      border-radius: 12px;
      color: var(--color-text-secondary);
      background: var(--color-surface-subtle);
    }
    .empty h2 {
      margin-bottom: 7px;
      color: var(--color-text-primary);
      font-size: 18px;
    }
    .empty p {
      max-width: 420px;
      margin: 0;
      font-size: 13px;
    }
    .error-state {
      min-height: 566px;
      padding: 48px 24px;
      display: grid;
      place-content: center;
      text-align: center;
      border: 1px solid rgba(215, 0, 21, .2);
      border-radius: 12px;
      background: var(--color-danger-bg);
    }
    .error-state h2 {
      margin: 0 0 7px;
      color: var(--color-danger);
      font-size: 18px;
    }
    .error-state p {
      max-width: 480px;
      margin: 0;
      color: #7d111b;
      font-size: 13px;
    }
    .loading-state {
      padding: 4px;
    }
    .loading-heading,
    .skeleton {
      border-radius: 8px;
      background: linear-gradient(90deg, #ececef 25%, #f6f6f8 50%, #ececef 75%);
      background-size: 200% 100%;
      animation: loading 1.3s ease-in-out infinite;
    }
    .loading-heading {
      width: 34%;
      height: 26px;
      margin: 14px 0 24px;
    }
    .loading-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }
    .skeleton {
      height: 76px;
    }
    .skeleton-table {
      height: 340px;
      margin-top: 22px;
    }
    @keyframes loading {
      to { background-position: -200% 0; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation: none !important;
        transition: none !important;
        scroll-behavior: auto !important;
      }
    }
  </style>
</head>
<body>
  <header class="app-header">
    <div class="app-header-content">
      <div class="platform-brand">
        <span class="platform-mark" aria-hidden="true">T</span>
        <span>测试开发平台</span>
        <span class="header-context">质量分析 · 埋点分析</span>
      </div>
      __PLATFORM_HOME_LINK__
    </div>
  </header>
  <main>
    <div class="page-heading">
      <h1>埋点测试工具</h1>
      <p>解析 TrackEvents 日志，核对事件次数、字段与公共参数。</p>
    </div>
    <div class="layout">
      <section class="panel input-panel" aria-labelledby="input-title">
        <h2 id="input-title">运行配置</h2>
        <p class="panel-intro">粘贴内容优先于上传文件，均为空时使用 default.log 示例。</p>
        <div class="field-group">
          <label for="logFile">上传 log 文件</label>
          <input id="logFile" type="file" accept=".log,.txt,text/plain">
        </div>
        <div class="field-group">
          <label for="logText">粘贴 log 文本</label>
          <textarea id="logText" spellcheck="false" placeholder="粘贴 TrackEvents log 文本"></textarea>
        </div>
        <div class="field-group">
          <label for="expectedCounts">预期触发次数，可选</label>
          <textarea id="expectedCounts" spellcheck="false" aria-describedby="expectedCountsHint expectedCountsError" aria-invalid="false">{
  "app_foreground": 1,
  "app_page_stay": 3,
  "lead_leave_dialogview": 1,
  "lead_leave_leave_click": 1,
  "lead_page_exit": 1
}</textarea>
          <p id="expectedCountsHint" class="hint">支持 JSON，或一行一个 Action；行末数字表示次数。</p>
          <p id="expectedCountsError" class="field-error" role="alert"></p>
        </div>
        <div class="action-stack">
          <button id="analyzeBtn">开始解析</button>
          <button id="downloadBtn" class="secondary" disabled>下载 Markdown 报告</button>
        </div>
        <p class="hint">仅解析 method=TrackEvents。</p>
      </section>
      <section class="panel results-panel" aria-label="测试结果">
        <div id="result" aria-live="polite" aria-busy="false">
          <div class="empty">
            <div>
              <h2>准备运行</h2>
              <p>上传或粘贴日志，也可以直接解析 default.log 示例。</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  </main>
  <script>
    // 平台模式写请求使用双提交 CSRF Cookie；独立模式空值保持兼容。
    function readCookie(name) {
      const prefix = name + '=';
      const item = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith(prefix));
      return item ? decodeURIComponent(item.slice(prefix.length)) : '';
    }
    const fileInput = document.getElementById('logFile');
    const logTextInput = document.getElementById('logText');
    const expectedInput = document.getElementById('expectedCounts');
    const expectedError = document.getElementById('expectedCountsError');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const resultEl = document.getElementById('result');
    let latestReport = '';

    // 每次运行前先清理字段错误，避免过期反馈干扰下一次输入。
    analyzeBtn.addEventListener('click', async () => {
      expectedInput.setAttribute('aria-invalid', 'false');
      expectedError.textContent = '';
      const file = fileInput.files[0];
      const pastedLog = logTextInput.value;
      const hasPastedLog = pastedLog.trim().length > 0;
      let expectedCounts = {};
      const expectedText = expectedInput.value.trim();
      if (expectedText) {
        try {
          expectedCounts = parseExpectedCounts(expectedText);
        } catch (error) {
          expectedInput.setAttribute('aria-invalid', 'true');
          expectedError.textContent = '格式错误：' + error.message;
          expectedInput.focus();
          return;
        }
      }
      analyzeBtn.disabled = true;
      analyzeBtn.textContent = hasPastedLog ? '解析粘贴内容中...' : (file ? '解析上传文件中...' : '解析 default.log 中...');
      resultEl.setAttribute('aria-busy', 'true');
      renderLoading();
      try {
        const logText = hasPastedLog ? pastedLog : (file ? await file.text() : '');
        const response = await fetch('__ANALYZE_URL__', {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': readCookie('tp_csrf')},
          body: JSON.stringify({log_text: logText, expected_counts: expectedCounts})
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || '解析失败');
        latestReport = payload.markdown_report || '';
        downloadBtn.disabled = !latestReport;
        renderResult(payload);
      } catch (error) {
        renderError(error.message);
      } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = '开始解析';
        resultEl.setAttribute('aria-busy', 'false');
      }
    });

    expectedInput.addEventListener('input', () => {
      if (expectedInput.getAttribute('aria-invalid') === 'true') {
        expectedInput.setAttribute('aria-invalid', 'false');
        expectedError.textContent = '';
      }
    });

    /** 展示稳定的加载骨架，并通过 aria-busy 向辅助技术同步状态。 */
    function renderLoading() {
      resultEl.innerHTML = `
        <div class="loading-state" aria-label="正在解析日志">
          <div class="loading-heading"></div>
          <div class="loading-grid">
            <div class="skeleton"></div><div class="skeleton"></div>
            <div class="skeleton"></div><div class="skeleton"></div>
          </div>
          <div class="skeleton skeleton-table"></div>
        </div>
      `;
    }

    /** 将运行失败与输入格式错误区分，保留可操作的重试方向。 */
    function renderError(message) {
      const detail = /[\u4e00-\u9fff]/.test(String(message || ''))
        ? message
        : '服务暂时不可用，请检查输入内容后重试。';
      resultEl.innerHTML = `
        <div class="error-state" role="alert">
          <div>
            <h2>本次解析未完成</h2>
            <p>${escapeHtml(detail)}</p>
          </div>
        </div>
      `;
    }

    function parseExpectedCounts(text) {
      if (text.startsWith('{')) {
        let parsed;
        try {
          parsed = JSON.parse(text);
        } catch {
          throw new Error('JSON 格式不完整，请检查引号、逗号和括号');
        }
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
          throw new Error('JSON 必须是对象格式');
        }
        if (Object.values(parsed).some(value => !Number.isInteger(Number(value)))) {
          throw new Error('每个预期触发次数都必须是整数');
        }
        return parsed;
      }

      const counts = {};
      text.split(/\r?\n/).forEach((line, index) => {
        const value = line.trim();
        if (!value) return;
        const match = value.match(/^(.+?)(\d+)?$/);
        const action = match ? match[1].trim() : '';
        if (!action) throw new Error(`第 ${index + 1} 行缺少 Action`);
        counts[action] = match[2] ? Number(match[2]) : 1;
      });
      return counts;
    }

    downloadBtn.addEventListener('click', () => {
      const blob = new Blob([latestReport], {type: 'text/markdown;charset=utf-8'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'trackevents-report.md';
      a.click();
      URL.revokeObjectURL(url);
    });

    function renderResult(data) {
      const s = data.summary;
      const problemCount = s.failed_event_count + s.failed_response_count + s.failed_count_check_count;
      const hasProblems = problemCount > 0;
      resultEl.innerHTML = `
        <div class="run-summary ${hasProblems ? 'fail-state' : 'pass-state'}">
          <div class="run-summary-copy">
            <span class="run-summary-icon" aria-hidden="true">${hasProblems ? '!' : '✓'}</span>
            <div>
              <h2>${hasProblems ? '发现需要处理的问题' : '本次检查通过'}</h2>
              <p>${hasProblems ? '失败项已优先展示，请先核对事件与公共参数。' : '事件次数、响应与字段校验均未发现问题。'}</p>
            </div>
          </div>
          <span class="problem-count"><strong>${problemCount}</strong> 个问题</span>
        </div>
        <div class="summary">
          ${metric(s.request_count, 'TrackEvents 请求')}
          ${metric(s.response_count, 'TrackEvents 响应')}
          ${metric(s.event_count, '事件总数')}
          ${metric(problemCount, '问题数')}
        </div>
        <div class="tabs" role="tablist" aria-label="结果视图">
          <button id="tab-counts" class="active" role="tab" aria-selected="true" aria-controls="tabPanel" data-tab="counts">事件统计</button>
          <button id="tab-events" role="tab" aria-selected="false" aria-controls="tabPanel" data-tab="events">事件明细</button>
          <button id="tab-responses" role="tab" aria-selected="false" aria-controls="tabPanel" data-tab="responses">响应校验</button>
          <button id="tab-report" role="tab" aria-selected="false" aria-controls="tabPanel" data-tab="report">报告文本</button>
        </div>
        <div id="tabPanel" role="tabpanel" aria-labelledby="tab-counts" tabindex="0"></div>
        <div id="commonParamsPanel"></div>
      `;
      const tabButtons = [...document.querySelectorAll('.tabs button')];
      const activateTab = (btn) => {
        tabButtons.forEach(item => {
          item.classList.toggle('active', item === btn);
          item.setAttribute('aria-selected', String(item === btn));
        });
        document.getElementById('tabPanel').setAttribute('aria-labelledby', btn.id);
        renderTab(btn.dataset.tab, data);
      };
      tabButtons.forEach((btn, index) => {
        btn.addEventListener('click', () => {
          activateTab(btn);
        });
        // 结果页签支持左右方向键，减少键盘用户的重复 Tab 操作。
        btn.addEventListener('keydown', event => {
          if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
          event.preventDefault();
          const offset = event.key === 'ArrowRight' ? 1 : -1;
          const nextButton = tabButtons[(index + offset + tabButtons.length) % tabButtons.length];
          nextButton.focus();
          activateTab(nextButton);
        });
      });
      renderTab('counts', data);
      renderCommonParams(data);
    }

    function renderTab(tab, data) {
      const panel = document.getElementById('tabPanel');
      if (tab === 'counts') {
        const rows = (data.event_stats || []).map(item => {
          const check = (data.count_checks || []).find(checkItem => checkItem.event_name === item.event_name);
          const status = check ? check.status : '';
          const expected = check ? check.expected : '未配置';
          return `<tr><td class="mono">${escapeHtml(item.module || '')}</td><td class="mono">${escapeHtml(item.event_name)}</td><td>${item.count}</td><td>${expected}</td><td>${statusBadge(status)}</td></tr>`;
        }).join('');
        panel.innerHTML = table(['module', 'Action', '实际次数', '预期次数', '校验'], rows || '<tr><td colspan="5">未识别到事件</td></tr>');
        return;
      }
      if (tab === 'events') {
        renderEventDetails(data);
        return;
      }
      if (tab === 'responses') {
        const rows = data.response_checks.map(item => `
          <tr>
            <td>#${item.request_index}</td>
            <td>${item.request_event_count}</td>
            <td>${item.accepted_count ?? ''}</td>
            <td>${String(item.success)}</td>
            <td>${statusBadge(item.status)}</td>
            <td>${issueList(item.errors, [])}</td>
          </tr>
        `).join('');
        panel.innerHTML = table(['请求', '事件数', 'accepted_count', 'success', '结果', '问题'], rows || '<tr><td colspan="6">无响应</td></tr>');
        return;
      }
      panel.innerHTML = `<textarea readonly style="min-height:520px">${escapeHtml(data.markdown_report || '')}</textarea>`;
    }

    function renderEventDetails(data, selectedModule = '', selectedAction = '') {
      const panel = document.getElementById('tabPanel');
      const modules = [...new Set((data.events || []).map(item => item.module).filter(Boolean))];
      const actions = [...new Set((data.events || []).map(item => item.event_name).filter(Boolean))];
      const filteredEvents = (data.events || []).filter(item =>
        (!selectedModule || item.module === selectedModule)
        && (!selectedAction || item.event_name === selectedAction)
      );
      const moduleOptions = ['<option value="">全部 module</option>']
        .concat(modules.map(module => `<option value="${escapeHtml(module)}"${module === selectedModule ? ' selected' : ''}>${escapeHtml(module)}</option>`))
        .join('');
      const actionOptions = ['<option value="">全部 Action</option>']
        .concat(actions.map(action => `<option value="${escapeHtml(action)}"${action === selectedAction ? ' selected' : ''}>${escapeHtml(action)}</option>`))
        .join('');
      const rows = filteredEvents.map(item => `
          <tr>
            <td>#${item.request_index}.${item.event_index}</td>
            <td class="mono">${escapeHtml(item.module || '')}</td>
            <td class="mono">${escapeHtml(item.event_name || '')}</td>
            <td class="mono">${formatRequiredParams(item.required_params)}</td>
            <td class="mono business-param-cell">${formatBusinessParams(item.business_params)}</td>
            <td>${statusBadge(item.status)}</td>
            <td class="mono">${escapeHtml(item.event_id || '')}</td>
            <td>${issueList(item.errors, item.warnings, item.extra_params)}</td>
          </tr>
        `).join('');
      panel.innerHTML = `
        <div class="filter-bar">
          <label for="moduleFilter" style="margin:0">module</label>
          <select id="moduleFilter">${moduleOptions}</select>
          <label for="actionFilter" style="margin:0">Action</label>
          <select id="actionFilter">${actionOptions}</select>
          <button id="clearActionFilter" class="secondary">清除</button>
          <span class="hint">显示 ${filteredEvents.length} / ${(data.events || []).length} 条</span>
        </div>
        ${table(['位置', 'module', 'Action', '业务子参 Key', '业务子参值', '结果', 'event_id', '问题'], rows || '<tr><td colspan="8">无符合条件的事件</td></tr>')}
      `;
      const applyFilters = () => {
        renderEventDetails(
          data,
          document.getElementById('moduleFilter').value,
          document.getElementById('actionFilter').value,
        );
      };
      document.getElementById('moduleFilter').addEventListener('change', applyFilters);
      document.getElementById('actionFilter').addEventListener('change', applyFilters);
      document.getElementById('clearActionFilter').addEventListener('click', () => {
        renderEventDetails(data);
      });
    }

    function renderCommonParams(data) {
      const panel = document.getElementById('commonParamsPanel');
      // 失败项优先排序，保持原始数据不变，只调整结果阅读顺序。
      const failedFirst = items => [...(items || [])].sort((left, right) =>
        Number(right.status === 'fail') - Number(left.status === 'fail')
      );
      const summaryRows = failedFirst(data.common_param_summary).map(item => `
        <tr>
          <td class="mono">${escapeHtml(item.key)}</td>
          <td>${item.required ? '是' : '否'}</td>
          <td>${item.allow_empty ? '是' : '否'}</td>
          <td>${item.present_count}</td>
          <td>${item.missing_count}</td>
          <td>${item.empty_count}</td>
          <td>${statusBadge(item.status)}</td>
        </tr>
      `).join('');
      const detailRows = failedFirst(data.common_param_events).map(item => `
        <tr>
          <td>#${item.request_index}.${item.event_index}</td>
          <td class="mono">${escapeHtml(item.module || '')}</td>
          <td class="mono">${escapeHtml(item.event_name || '')}</td>
          <td class="mono">${escapeHtml(item.event_id || '')}</td>
          <td class="mono common-param-cell">${formatCommonValues(item.values)}</td>
          <td class="mono">${formatParamList(item.missing_required)}</td>
          <td class="mono">${formatParamList(item.empty_not_allowed)}</td>
          <td>${statusBadge(item.status)}</td>
        </tr>
      `).join('');
      panel.innerHTML = `
        <section class="common-check-panel">
          <h2>埋点公参检查</h2>
          <p class="hint">根据“需求埋点list（维护最新版）”中的公参定义，对所有已识别事件检查公参是否填写，并展示实际数据。</p>
          ${table(['公参 Key', '必填', '允许为空', '已填写事件数', '缺失事件数', '空值事件数', '结果'], summaryRows || '<tr><td colspan="7">暂无公参检查结果</td></tr>')}
          <h2 style="margin-top:16px">公参事件明细</h2>
          ${table(['位置', 'module', 'Action', 'event_id', '公参实际值', '缺失必填公参', '不允许为空但为空', '结果'], detailRows || '<tr><td colspan="8">暂无事件</td></tr>')}
        </section>
      `;
    }

    function metric(value, label) {
      return `<div class="metric"><b>${value}</b><span>${label}</span></div>`;
    }
    function table(headers, rows) {
      return `<div class="table-wrap"><table><thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }
    function statusBadge(status) {
      if (!status) return '<span class="status warn">仅统计</span>';
      const text = status === 'pass' ? '通过' : '失败';
      return `<span class="status ${status}">${text}</span>`;
    }
    function issueList(errors, warnings, extraParams) {
      const items = [];
      (errors || []).forEach(item => items.push(`<li class="fail-text">${escapeHtml(item)}</li>`));
      (warnings || []).forEach(item => items.push(`<li class="warn-text">${escapeHtml(item)}</li>`));
      if (extraParams && Object.keys(extraParams).length > 0) {
        const values = Object.entries(extraParams)
          .map(([key, value]) => `<div class="business-param-row">"${escapeHtml(key)}": ${escapeHtml(JSON.stringify(value))}</div>`)
          .join('');
        items.push(`<li class="warn-text">疑似多传字段值：${values}</li>`);
      }
      return items.length ? `<ul class="issues">${items.join('')}</ul>` : '';
    }
    function formatRequiredParams(params) {
      if (!params || params.length === 0) return '无';
      return params.map(item => escapeHtml(item)).join(', ');
    }
    function formatBusinessParams(params) {
      if (!params || Object.keys(params).length === 0) return '无';
      return Object.entries(params)
        .map(([key, value]) => `<div class="business-param-row">"${escapeHtml(key)}": ${escapeHtml(JSON.stringify(value))}</div>`)
        .join('');
    }
    function formatCommonValues(values) {
      if (!values || Object.keys(values).length === 0) return '无';
      return Object.entries(values)
        .map(([key, value]) => value === null
          ? `<div class="common-param-row common-param-missing">"${escapeHtml(key)}": 未填写</div>`
          : `<div class="common-param-row">"${escapeHtml(key)}": ${escapeHtml(JSON.stringify(value))}</div>`)
        .join('');
    }
    function formatParamList(params) {
      if (!params || params.length === 0) return '无';
      return params.map(item => escapeHtml(item)).join(', ');
    }
    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }
  </script>
</body>
</html>
"""


def route_path(path: str, base_path: str = BASE_PATH) -> str:
    """拼接经过校验的工具基础路径和应用内部路由。"""
    normalized_base = normalize_base_path(base_path)
    if not path.startswith("/"):
        raise ValueError(f"应用路由必须以 / 开头: {path}")
    return f"{normalized_base}{path}" if normalized_base else path


def render_html(
    base_path: str = BASE_PATH,
    platform_home_url: str = PLATFORM_HOME_URL,
) -> str:
    """生成与当前部署前缀一致的页面，避免资源和 API 请求跳到根路径。"""
    home_link = ""
    if platform_home_url:
        safe_home_url = escape(platform_home_url, quote=True)
        home_link = (
            f'<a class="header-home-link" href="{safe_home_url}">'
            "返回平台首页</a>"
        )
    return (
        HTML_TEMPLATE.replace("__FAVICON_URL__", route_path("/favicon.svg", base_path))
        .replace("__ANALYZE_URL__", route_path("/api/analyze", base_path))
        .replace("__PLATFORM_HOME_LINK__", home_link)
    )


# 保留根路径渲染结果，兼容现有页面内容测试和独立运行调用方。
HTML = render_html("")


def _client_token() -> str:
    """读取只读工具 Client Token；缺失时审计上报安全降级。"""

    if not PLATFORM_CLIENT_TOKEN_FILE:
        return ""
    try:
        return Path(PLATFORM_CLIENT_TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _report_audit(headers: object, outcome: str, error_code: str | None = None) -> None:
    """最大尽力上报埋点分析审计，平台异常不改变已完成的分析结果。"""

    token = _client_token()
    if not PLATFORM_API_URL or not token:
        return
    payload = json.dumps({
        "event_id": f"evt_{uuid.uuid4().hex}",
        "action": "tool.analysis.submit",
        "resource_type": "trackevents_analysis",
        "outcome": outcome,
        "error_code": error_code,
        "actor_user_id": headers.get("X-Platform-User-ID"),
        "actor_username": headers.get("X-Platform-Username"),
        "metadata": {},
    }).encode("utf-8")
    audit_request = urlrequest.Request(
        f"{PLATFORM_API_URL}/internal/tools/trackevents/audit-events",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(audit_request, timeout=1):
            pass
    except Exception:
        return


class TrackEventsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        base_path = self.server.base_path
        if base_path and path == base_path:
            self._redirect(f"{base_path}/")
            return
        if path in {route_path("/", base_path), route_path("/index.html", base_path)}:
            self._send_text(self.server.page_html, "text/html; charset=utf-8")
            return
        if path == route_path("/favicon.svg", base_path):
            self._send_text(FAVICON_PATH.read_text("utf-8"), "image/svg+xml")
            return
        if path == route_path("/health", base_path):
            self._send_json({
                "service": "trackevents", "status": "ok",
                "version": os.getenv("APP_VERSION", "unknown"),
                "revision": os.getenv("APP_REVISION", "unknown"),
                "dirty": os.getenv("APP_BUILD_DIRTY", "true").lower() == "true",
                "runtime_environment": os.getenv("PLATFORM_RUNTIME_ENV", "unknown"),
            })
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != route_path("/api/analyze", self.server.base_path):
            self.send_error(404)
            return
        if PLATFORM_API_URL and not self._valid_csrf():
            self._send_json({"error": "请求安全校验失败"}, status=403)
            _report_audit(self.headers, "denied", "CSRF_INVALID")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            log_text = resolve_log_text(payload.get("log_text", ""), DEFAULT_LOG_PATH)
            expected_counts = payload.get("expected_counts") or {}
            if not isinstance(expected_counts, dict):
                raise ValueError("expected_counts 必须是 JSON 对象")
            normalized_counts = {str(key): int(value) for key, value in expected_counts.items()}
            result = analyze_log_text(log_text, normalized_counts)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            _report_audit(self.headers, "failed", "ANALYSIS_FAILED")
            return
        self._send_json(result)
        _report_audit(self.headers, "success")

    def _valid_csrf(self) -> bool:
        """比较 Cookie 与 Header 中的 CSRF Token，不记录任何 Token 值。"""

        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        cookie = cookies.get("tp_csrf")
        header = self.headers.get("X-CSRF-Token", "")
        return bool(cookie and header and hmac.compare_digest(cookie.value, header))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_text(self, text: str, content_type: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        """将缺少末尾斜杠的工具入口重定向到标准页面地址。"""
        self.send_response(308)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def resolve_log_text(log_text: str, default_log_path: Path = DEFAULT_LOG_PATH) -> str:
    if log_text:
        return log_text
    if not default_log_path.exists():
        raise FileNotFoundError(f"未上传 log，且默认文件不存在: {default_log_path}")
    return default_log_path.read_text(encoding="utf-8")


def create_server(
    host: str,
    port: int,
    base_path: str = BASE_PATH,
    platform_home_url: str = PLATFORM_HOME_URL,
) -> ThreadingHTTPServer:
    """创建配置了部署前缀的 HTTP 服务实例，供运行入口和测试共同使用。"""
    normalized_base = normalize_base_path(base_path)
    server = ThreadingHTTPServer((host, port), TrackEventsHandler)
    server.base_path = normalized_base
    server.page_html = render_html(normalized_base, platform_home_url)
    return server


def run_server(host: str = HOST, port: int = PORT) -> None:
    server = create_server(host, port)
    entry_path = f"{BASE_PATH}/" if BASE_PATH else "/"
    print(f"埋点测试工具已启动: http://{host}:{port}{entry_path}")
    print("按 Ctrl+C 停止服务")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
