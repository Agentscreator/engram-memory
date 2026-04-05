"""Vercel ASGI entrypoint — landing page with workspace memory graph search."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route


def _render_landing() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Engram — Shared memory for your team's agents</title>
  <meta name="description" content="Shared memory for your team's agents. Works with any MCP-compatible IDE. Zero setup. All data encrypted, never shared, always yours.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.29.2/cytoscape.min.js"></script>
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

    :root {
      --bg-primary: #050a0e;
      --bg-secondary: #0a1118;
      --bg-card: rgba(13, 23, 33, 0.7);
      --bg-card-hover: rgba(16, 28, 40, 0.8);
      --border-subtle: rgba(52, 211, 153, 0.08);
      --border-glow: rgba(52, 211, 153, 0.2);
      --emerald-50: #ecfdf5;
      --emerald-100: #d1fae5;
      --emerald-200: #a7f3d0;
      --emerald-300: #6ee7b7;
      --emerald-400: #34d399;
      --emerald-500: #10b981;
      --emerald-600: #059669;
      --emerald-700: #047857;
      --emerald-800: #065f46;
      --emerald-900: #064e3b;
      --text-primary: #f0fdf4;
      --text-secondary: rgba(209, 250, 229, 0.6);
      --text-muted: rgba(167, 243, 208, 0.35);
    }

    html { scroll-behavior: smooth; }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      line-height: 1.6;
      color: var(--text-primary);
      background: var(--bg-primary);
      min-height: 100vh;
      overflow-x: hidden;
      -webkit-font-smoothing: antialiased;
    }

    .container { max-width: 900px; margin: 0 auto; padding: 0 28px; }

    /* ── Animated background ─────────────────────────────────── */
    #neural-bg {
      position: fixed; top: 0; left: 0; width: 100%; height: 100%;
      z-index: 0; pointer-events: none;
    }
    .bg-glow {
      position: fixed; border-radius: 50%; filter: blur(120px); opacity: 0.12;
      pointer-events: none; z-index: 0;
    }
    .bg-glow-1 { width: 600px; height: 600px; background: var(--emerald-600); top: -200px; left: -100px; }
    .bg-glow-2 { width: 500px; height: 500px; background: #0891b2; bottom: -150px; right: -100px; }
    .bg-glow-3 { width: 400px; height: 400px; background: var(--emerald-500); top: 50%; left: 50%; transform: translate(-50%, -50%); opacity: 0.06; }

    /* ── Header ──────────────────────────────────────────────── */
    header {
      padding: 20px 0;
      background: rgba(5, 10, 14, 0.6);
      backdrop-filter: blur(20px) saturate(1.5);
      border-bottom: 1px solid var(--border-subtle);
      position: sticky; top: 0; z-index: 100;
    }
    .header-content { display: flex; justify-content: space-between; align-items: center; }
    .logo {
      font-size: 24px; font-weight: 700; color: var(--emerald-400);
      text-decoration: none; letter-spacing: -0.03em;
      display: flex; align-items: center; gap: 10px;
    }
    .logo-dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--emerald-400);
      box-shadow: 0 0 12px var(--emerald-400), 0 0 24px rgba(52, 211, 153, 0.3);
      animation: pulse-dot 3s ease-in-out infinite;
    }
    @keyframes pulse-dot {
      0%, 100% { opacity: 1; box-shadow: 0 0 12px var(--emerald-400), 0 0 24px rgba(52, 211, 153, 0.3); }
      50% { opacity: 0.6; box-shadow: 0 0 6px var(--emerald-400), 0 0 12px rgba(52, 211, 153, 0.15); }
    }
    .nav-links { display: flex; gap: 28px; align-items: center; }
    .nav-links a {
      color: var(--text-secondary); text-decoration: none;
      font-size: 14px; font-weight: 500; letter-spacing: 0.01em;
      transition: color 0.25s;
    }
    .nav-links a:hover { color: var(--emerald-400); }

    /* ── Hero ────────────────────────────────────────────────── */
    .hero {
      padding: 120px 0 100px; text-align: center;
      position: relative; z-index: 1;
    }
    .hero-badge {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 6px 16px 6px 10px;
      background: rgba(52, 211, 153, 0.08);
      border: 1px solid rgba(52, 211, 153, 0.15);
      border-radius: 100px; font-size: 13px; font-weight: 500;
      color: var(--emerald-300); margin-bottom: 32px;
      letter-spacing: 0.02em;
    }
    .hero-badge-dot {
      width: 6px; height: 6px; border-radius: 50%;
      background: var(--emerald-400);
      box-shadow: 0 0 8px var(--emerald-400);
    }
    h1 {
      font-size: 64px; font-weight: 800; line-height: 1.08;
      letter-spacing: -0.04em; margin-bottom: 24px;
      background: linear-gradient(135deg, var(--emerald-100) 0%, var(--emerald-400) 50%, #6ee7b7 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .subtitle {
      font-size: 19px; color: var(--text-secondary);
      max-width: 560px; margin: 0 auto 48px;
      line-height: 1.7; font-weight: 400;
    }
    .hero-cta {
      display: inline-flex; align-items: center; gap: 10px;
      padding: 14px 32px; border-radius: 12px;
      background: linear-gradient(135deg, var(--emerald-600), var(--emerald-700));
      color: white; font-size: 15px; font-weight: 600;
      text-decoration: none; border: none; cursor: pointer;
      transition: transform 0.2s, box-shadow 0.3s;
      box-shadow: 0 4px 24px rgba(5, 150, 105, 0.3), inset 0 1px 0 rgba(255,255,255,0.1);
    }
    .hero-cta:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 40px rgba(5, 150, 105, 0.4), inset 0 1px 0 rgba(255,255,255,0.1);
    }
    .hero-cta svg { opacity: 0.7; }

    /* ── Sections ────────────────────────────────────────────── */
    .section { position: relative; z-index: 1; padding: 40px 0; }

    /* ── Cards ───────────────────────────────────────────────── */
    .card {
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      border-radius: 20px;
      padding: 48px;
      margin-bottom: 40px;
      border: 1px solid var(--border-subtle);
      transition: border-color 0.4s, box-shadow 0.4s;
    }
    .card:hover {
      border-color: var(--border-glow);
      box-shadow: 0 0 60px rgba(52, 211, 153, 0.04);
    }
    .section-label {
      font-size: 12px; font-weight: 600; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--emerald-500);
      margin-bottom: 12px;
    }
    .section-title {
      font-size: 32px; font-weight: 700; margin-bottom: 16px;
      color: var(--text-primary); letter-spacing: -0.02em;
      text-align: left;
    }
    .section-desc {
      font-size: 16px; color: var(--text-secondary);
      line-height: 1.7; margin-bottom: 36px; max-width: 600px;
    }

    /* ── Install steps ───────────────────────────────────────── */
    .install-steps { display: flex; flex-direction: column; gap: 28px; }
    .install-step {
      display: flex; gap: 20px; align-items: flex-start;
    }
    .step-num {
      width: 32px; height: 32px; border-radius: 10px;
      background: rgba(52, 211, 153, 0.1);
      border: 1px solid rgba(52, 211, 153, 0.2);
      display: flex; align-items: center; justify-content: center;
      font-size: 14px; font-weight: 700; color: var(--emerald-400);
      flex-shrink: 0; margin-top: 2px;
    }
    .step-content { flex: 1; }
    .step-title { font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; }

    /* ── Code blocks ─────────────────────────────────────────── */
    .code-block {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(52, 211, 153, 0.12);
      padding: 16px 20px; border-radius: 12px;
      font-family: 'JetBrains Mono', 'SF Mono', monospace;
      font-size: 14px; color: var(--emerald-300);
      position: relative; overflow-x: auto;
      transition: border-color 0.3s, box-shadow 0.3s;
    }
    /* ── Copy button animation ───────────────────────────────── */
    .copy-btn {
      position: absolute; top: 10px; right: 10px;
      background: rgba(52, 211, 153, 0.1);
      border: 1px solid rgba(52, 211, 153, 0.2);
      color: var(--emerald-400); padding: 5px 12px;
      border-radius: 6px; cursor: pointer;
      font-size: 11px; font-weight: 600; font-family: 'Inter', sans-serif;
      letter-spacing: 0.03em;
      transition: background 0.2s, border-color 0.2s, color 0.2s, box-shadow 0.3s, transform 0.15s;
    }
    .copy-btn:hover { background: rgba(52, 211, 153, 0.2); border-color: rgba(52, 211, 153, 0.35); }
    .copy-btn.copied {
      background: rgba(52, 211, 153, 0.25);
      border-color: var(--emerald-400);
      color: var(--emerald-300);
      box-shadow: 0 0 16px rgba(52, 211, 153, 0.2);
      transform: scale(1.05);
    }

    /* ── Platform tabs ───────────────────────────────────────── */
    .platform-tabs { display: flex; gap: 2px; margin-bottom: 2px; }
    .tab {
      padding: 8px 18px; border: none;
      background: rgba(255,255,255,0.04);
      color: var(--text-muted);
      font-size: 13px; font-weight: 500; cursor: pointer;
      font-family: inherit; transition: all 0.25s;
      border-radius: 8px 8px 0 0;
    }
    .tab.active { background: rgba(0, 0, 0, 0.4); color: var(--emerald-400); }
    .tab:not(.active):hover { color: var(--text-secondary); background: rgba(255,255,255,0.06); }
    .platform-tabs + .code-block,
    .platform-tabs ~ .code-block { border-radius: 0 12px 12px 12px; }

    .ide-note {
      font-size: 13px; color: var(--text-muted); margin-top: 24px;
      text-align: center; line-height: 1.6;
    }
    .ide-note span { color: var(--text-secondary); }

    /* ── Feature grid ────────────────────────────────────────── */
    .feature-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .feature-item {
      padding: 28px;
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      transition: border-color 0.3s, background 0.3s;
    }
    .feature-item:hover { border-color: var(--border-glow); background: rgba(255,255,255,0.035); }
    .feature-icon {
      width: 40px; height: 40px; border-radius: 12px;
      background: rgba(52, 211, 153, 0.08);
      border: 1px solid rgba(52, 211, 153, 0.12);
      display: flex; align-items: center; justify-content: center;
      font-size: 18px; margin-bottom: 16px;
    }
    .feature-item h3 { font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
    .feature-item p { font-size: 14px; color: var(--text-secondary); line-height: 1.6; margin: 0; }

    /* ── Privacy section ─────────────────────────────────────── */
    .privacy-grid { display: grid; gap: 1px; background: var(--border-subtle); border-radius: 16px; overflow: hidden; }
    .privacy-item {
      display: flex; gap: 20px; align-items: flex-start;
      padding: 24px 28px;
      background: var(--bg-secondary);
      transition: background 0.3s;
    }
    .privacy-item:hover { background: rgba(16, 28, 40, 0.9); }
    .privacy-icon {
      width: 36px; height: 36px; border-radius: 10px;
      background: rgba(52, 211, 153, 0.06);
      display: flex; align-items: center; justify-content: center;
      font-size: 16px; flex-shrink: 0;
    }
    .privacy-item h3 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
    .privacy-item p { font-size: 13px; color: var(--text-secondary); line-height: 1.6; margin: 0; }

    /* ── Tools ────────────────────────────────────────────────── */
    .tools-grid { display: grid; gap: 12px; }
    .tool-item {
      display: flex; align-items: center; gap: 20px;
      padding: 20px 24px;
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      transition: border-color 0.3s;
    }
    .tool-item:hover { border-color: var(--border-glow); }
    .tool-item code {
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px; font-weight: 500; color: var(--emerald-400);
      background: rgba(52, 211, 153, 0.08);
      padding: 4px 10px; border-radius: 6px;
      white-space: nowrap;
    }
    .tool-item p { font-size: 14px; color: var(--text-secondary); margin: 0; }

    /* ── Graph search ────────────────────────────────────────── */
    .search-form { display: flex; flex-direction: column; gap: 12px; }
    .search-row { display: flex; gap: 12px; }
    .search-input {
      flex: 1; padding: 14px 18px;
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      font-size: 14px; font-family: inherit;
      color: var(--text-primary);
      transition: border-color 0.25s, box-shadow 0.25s;
    }
    .search-input:focus {
      outline: none; border-color: var(--emerald-500);
      box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.1);
    }
    .search-input::placeholder { color: var(--text-muted); }
    .search-btn {
      padding: 14px 28px;
      background: linear-gradient(135deg, var(--emerald-600), var(--emerald-700));
      color: white; border: none; border-radius: 12px;
      font-size: 14px; font-weight: 600; cursor: pointer;
      white-space: nowrap; transition: transform 0.2s, box-shadow 0.3s;
      box-shadow: 0 2px 16px rgba(5, 150, 105, 0.25);
      display: inline-flex; align-items: center;
    }
    .search-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 24px rgba(5, 150, 105, 0.35); }
    .search-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

    #graph-section { display: none; }
    #graph-error { display: none; color: #f87171; font-size: 14px; font-weight: 500; text-align: center; padding: 16px; }
    #graph-loading { display: none; text-align: center; padding: 24px; color: var(--emerald-400); font-weight: 500; }

    #cy {
      width: 100%; height: 520px;
      border-radius: 16px;
      border: 1px solid var(--border-subtle);
      background: rgba(0, 0, 0, 0.25);
    }
    .graph-stats { display: flex; gap: 32px; justify-content: center; margin-top: 20px; flex-wrap: wrap; }
    .stat { text-align: center; }
    .stat-num { font-size: 32px; font-weight: 700; color: var(--emerald-400); }
    .stat-label { font-size: 12px; color: var(--text-muted); font-weight: 500; letter-spacing: 0.05em; text-transform: uppercase; margin-top: 2px; }

    .graph-legend { display: flex; gap: 24px; justify-content: center; margin-top: 16px; flex-wrap: wrap; }
    .legend-item { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); }
    .legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }

    .fact-detail {
      display: none; margin-top: 20px; padding: 20px;
      background: rgba(0,0,0,0.3); border-radius: 14px;
      border-left: 3px solid var(--emerald-500);
    }
    .fact-detail h4 { font-size: 13px; font-weight: 600; color: var(--emerald-400); margin-bottom: 8px; }
    .fact-detail p { font-size: 14px; color: var(--text-secondary); margin: 0; line-height: 1.6; }
    .fact-meta { font-size: 12px; color: var(--text-muted); margin-top: 10px; }

    .graph-search-row { display: flex; gap: 8px; margin-top: 16px; }
    .graph-search-input {
      flex: 1; padding: 10px 14px;
      background: rgba(0,0,0,0.3);
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
      font-size: 13px; font-family: inherit; color: var(--text-primary);
    }
    .graph-search-input:focus { outline: none; border-color: var(--emerald-500); }
    .graph-search-input::placeholder { color: var(--text-muted); }

    /* ── Graph hero section ──────────────────────────────────── */
    .graph-hero {
      position: relative; z-index: 1;
      padding: 80px 0;
      margin: 40px 0;
      background: linear-gradient(180deg, rgba(52, 211, 153, 0.03) 0%, transparent 100%);
      border-top: 1px solid var(--border-subtle);
      border-bottom: 1px solid var(--border-subtle);
    }
    .graph-hero-header { text-align: center; margin-bottom: 48px; }
    .graph-hero-title {
      font-size: 40px; font-weight: 800; letter-spacing: -0.03em;
      background: linear-gradient(135deg, var(--emerald-100) 0%, var(--emerald-400) 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text; margin-bottom: 16px;
    }
    .graph-hero-desc {
      font-size: 17px; color: var(--text-secondary);
      max-width: 520px; margin: 0 auto; line-height: 1.7;
    }
    .graph-card {
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      border-radius: 20px;
      padding: 40px;
      border: 1px solid var(--border-glow);
      box-shadow: 0 0 80px rgba(52, 211, 153, 0.04), 0 4px 32px rgba(0,0,0,0.2);
    }

    /* ── Loading spinner ─────────────────────────────────────── */
    .loading-spinner {
      width: 20px; height: 20px;
      border: 2px solid var(--border-subtle);
      border-top-color: var(--emerald-400);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      display: inline-block; vertical-align: middle;
      margin-right: 10px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Scroll animations ───────────────────────────────────── */
    .reveal {
      opacity: 0; transform: translateY(30px);
      transition: opacity 0.7s cubic-bezier(0.16, 1, 0.3, 1), transform 0.7s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .reveal.visible { opacity: 1; transform: translateY(0); }

    /* ── Footer ──────────────────────────────────────────────── */
    footer {
      padding: 60px 0 40px; text-align: center;
      position: relative; z-index: 1;
      border-top: 1px solid var(--border-subtle);
    }
    .footer-links { display: flex; gap: 28px; justify-content: center; align-items: center; margin-bottom: 16px; }
    .footer-logo { font-size: 18px; font-weight: 700; color: var(--emerald-400); letter-spacing: -0.02em; }
    .footer-links a { color: var(--text-muted); text-decoration: none; font-size: 13px; font-weight: 500; transition: color 0.25s; }
    .footer-links a:hover { color: var(--emerald-400); }
    .footer-tagline { font-size: 13px; color: var(--text-muted); font-style: italic; }

    /* ── Toast ────────────────────────────────────────────────── */
    .copy-toast {
      position: fixed; bottom: 32px; left: 50%;
      transform: translateX(-50%) translateY(20px);
      background: var(--bg-secondary);
      border: 1px solid var(--border-glow);
      color: var(--emerald-300);
      padding: 12px 24px; border-radius: 12px;
      font-size: 14px; font-weight: 500;
      display: flex; align-items: center; gap: 8px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.4);
      opacity: 0; pointer-events: none;
      transition: opacity 0.3s ease, transform 0.3s ease;
      z-index: 1000;
    }
    .copy-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

    /* ── Responsive ──────────────────────────────────────────── */
    @media (max-width: 768px) {
      h1 { font-size: 38px; }
      .subtitle { font-size: 16px; }
      .hero { padding: 80px 0 60px; }
      .card { padding: 32px 24px; }
      .section-title { font-size: 24px; }
      .feature-grid { grid-template-columns: 1fr; }
      .search-row { flex-direction: column; }
      #cy { height: 380px; }
      .platform-tabs { flex-wrap: wrap; }
      .install-step { flex-direction: column; gap: 12px; }
      .graph-hero { padding: 48px 0; }
      .graph-hero-title { font-size: 28px; }
      .graph-card { padding: 24px; }
    }
  </style>
</head>
<body>

<canvas id="neural-bg"></canvas>
<div class="bg-glow bg-glow-1"></div>
<div class="bg-glow bg-glow-2"></div>
<div class="bg-glow bg-glow-3"></div>

<header>
  <div class="container">
    <div class="header-content">
      <a href="/" class="logo"><span class="logo-dot"></span>engram</a>
      <nav class="nav-links">
        <a href="#install">Install</a>
        <a href="#dashboard">Dashboard</a>
        <a href="#privacy">Privacy</a>
        <a href="https://github.com/Agentscreator/Engram" target="_blank">GitHub</a>
      </nav>
    </div>
  </div>
</header>

<section class="hero">
  <div class="container">
    <div class="hero-badge"><span class="hero-badge-dot"></span>MCP-compatible · Open source</div>
    <h1>Shared memory for<br>your team's agents</h1>
    <p class="subtitle">
      One agent discovers something. Every other agent knows it instantly.
      Encrypted, private, and never shared. One command to install.
    </p>
    <a href="#install" class="hero-cta">
      Get started
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </a>
  </div>
</section>

<div class="container">

  <!-- What it does -->
  <div class="card reveal">
    <div class="feature-grid">
      <div class="feature-item">
        <div class="feature-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v8l4-2"/><circle cx="12" cy="14" r="8"/></svg></div>
        <h3>Commit discoveries</h3>
        <p>When an agent finds a hidden side effect, a failed approach, or an undocumented constraint — it commits that fact to shared memory.</p>
      </div>
      <div class="feature-item">
        <div class="feature-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg></div>
        <h3>Query before working</h3>
        <p>Every agent queries team memory before starting work. No duplicated effort, no rediscovering what someone already found.</p>
      </div>
      <div class="feature-item">
        <div class="feature-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg></div>
        <h3>Detect contradictions</h3>
        <p>When two agents develop incompatible beliefs, Engram detects the contradiction and surfaces it for review.</p>
      </div>
      <div class="feature-item">
        <div class="feature-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4m0 4a4 4 0 100 8 4 4 0 000-8z"/><path d="M12 16v4"/><path d="M4.93 4.93l2.83 2.83"/><path d="M16.24 16.24l2.83 2.83"/><path d="M4 12H2"/><path d="M22 12h-2"/><path d="M4.93 19.07l2.83-2.83"/><path d="M16.24 7.76l2.83-2.83"/></svg></div>
        <h3>Forget on purpose</h3>
        <p>Ephemeral facts auto-expire unless proven useful. Old context stops crowding out what matters now.</p>
      </div>
    </div>
  </div>

  <!-- Install -->
  <div class="card reveal" id="install">
    <div class="section-label">Get started</div>
    <div class="section-title">One command. Zero config.</div>
    <div class="section-desc">Install Engram, restart your IDE, and ask your agent to set up your team. That's it.</div>

    <div class="install-steps">
      <div class="install-step">
        <div class="step-num">1</div>
        <div class="step-content">
          <div class="step-title">Run the installer</div>
          <div class="platform-tabs">
            <button class="tab active" onclick="switchTab('mac')">macOS / Linux</button>
            <button class="tab" onclick="switchTab('ps')">PowerShell</button>
            <button class="tab" onclick="switchTab('cmd')">CMD</button>
          </div>
          <div class="code-block" id="tab-mac">
            <button class="copy-btn" onclick="copyCode('install-mac')">Copy</button>
            <div id="install-mac">curl -fsSL https://engram.app/install | sh</div>
          </div>
          <div class="code-block" id="tab-ps" style="display:none;">
            <button class="copy-btn" onclick="copyCode('install-ps')">Copy</button>
            <div id="install-ps">irm https://engram.app/install.ps1 | iex</div>
          </div>
          <div class="code-block" id="tab-cmd" style="display:none;">
            <button class="copy-btn" onclick="copyCode('install-cmd')">Copy</button>
            <div id="install-cmd">curl -fsSL https://engram.app/install.cmd -o install.cmd &amp;&amp; install.cmd &amp;&amp; del install.cmd</div>
          </div>
        </div>
      </div>
      <div class="install-step">
        <div class="step-num">2</div>
        <div class="step-content">
          <div class="step-title">Restart your IDE</div>
        </div>
      </div>
      <div class="install-step">
        <div class="step-num">3</div>
        <div class="step-content">
          <div class="step-title">Ask your agent</div>
          <div class="code-block">
            <button class="copy-btn" onclick="copyCode('setup-prompt')">Copy</button>
            <div id="setup-prompt">"Set up Engram for my team"</div>
          </div>
        </div>
      </div>
    </div>
    <p class="ide-note">
      <span>Claude Code · Claude Desktop · Cursor · Windsurf · VS Code</span><br>
      and any MCP-compatible IDE
    </p>
  </div>

  <!-- Memory graph — full-width breakout -->
</div>
<section class="graph-hero reveal" id="dashboard">
  <div class="container">
    <div class="graph-hero-header">
      <div class="section-label">Dashboard</div>
      <h2 class="graph-hero-title">View your memory graph</h2>
      <p class="graph-hero-desc">
        See everything your agents know — facts, conflicts, and lineage chains.
        Enter your workspace credentials to explore your team's shared memory in real time.
      </p>
    </div>

    <div class="graph-card">
      <div class="search-form">
        <div class="search-row">
          <input class="search-input" id="engram-id-input" placeholder="Workspace ID  (ENG-XXXX-XXXX)" autocomplete="off" spellcheck="false" />
        </div>
        <div class="search-row">
          <input class="search-input" id="invite-key-input" placeholder="Invite key  (ek_live_...)" autocomplete="off" spellcheck="false" type="password" />
          <button class="search-btn" id="search-btn" onclick="loadGraph()">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style="margin-right:6px;"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5"/><path d="M11 11l3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            View Graph
          </button>
        </div>
      </div>
      <div id="graph-error"></div>
      <div id="graph-loading">
        <div class="loading-spinner"></div>
        Loading your memory graph…
      </div>

      <div id="graph-section">
        <div class="graph-stats" id="graph-stats"></div>
        <div class="graph-legend" id="graph-legend">
          <span class="legend-item"><span class="legend-dot" style="background:var(--emerald-500)"></span>Active fact</span>
          <span class="legend-item"><span class="legend-dot" style="background:#64748b"></span>Retired fact</span>
          <span class="legend-item"><span class="legend-dot" style="background:#f59e0b"></span>Conflict</span>
        </div>
        <div class="graph-search-row">
          <input class="graph-search-input" id="fact-search" placeholder="Filter facts…" oninput="filterGraph(this.value)" />
        </div>
        <div id="cy" style="margin-top:12px;"></div>
        <div class="fact-detail" id="fact-detail">
          <h4 id="detail-scope"></h4>
          <p id="detail-content"></p>
          <div class="fact-meta" id="detail-meta"></div>
        </div>
      </div>
    </div>
  </div>
</section>
<div class="container">

  <!-- Privacy -->
  <div class="card reveal" id="privacy">
    <div class="section-label">Privacy</div>
    <div class="section-title">Your data is yours. Period.</div>
    <div class="section-desc">Privacy isn't a feature we added. It's the foundation everything is built on.</div>

    <div class="privacy-grid">
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg></div>
        <div>
          <h3>Encrypted everywhere</h3>
          <p>All data encrypted in transit and at rest. Invite keys use encrypted payloads — teammates never see raw credentials.</p>
        </div>
      </div>
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg></div>
        <div>
          <h3>Fully isolated</h3>
          <p>Every workspace is completely isolated. No cross-workspace access, no shared tables, no data leakage between teams.</p>
        </div>
      </div>
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M4.93 4.93l14.14 14.14"/></svg></div>
        <div>
          <h3>Never read, never analyzed</h3>
          <p>We don't read your facts. We don't analyze your memory. We don't train on your data. We don't sell it. No analytics pipeline touches your content.</p>
        </div>
      </div>
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg></div>
        <div>
          <h3>Never redistributed</h3>
          <p>Your team's knowledge never leaves your workspace. Never shared with other users, teams, or third parties. Not now, not ever.</p>
        </div>
      </div>
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></div>
        <div>
          <h3>You control everything</h3>
          <p>Delete your workspace and everything is gone. Anonymous mode strips names. Anonymous agents randomize IDs. You decide what's visible.</p>
        </div>
      </div>
    </div>
  </div>

  <!-- Tools -->
  <div class="card reveal">
    <div class="section-label">MCP Tools</div>
    <div class="section-title">Four tools. That's it.</div>
    <div class="section-desc">Your agents use these automatically. No configuration needed.</div>

    <div class="tools-grid">
      <div class="tool-item"><code>engram_commit</code><p>Persist a verified discovery to shared memory</p></div>
      <div class="tool-item"><code>engram_query</code><p>Pull what your team's agents already know</p></div>
      <div class="tool-item"><code>engram_conflicts</code><p>Surface contradictions between agents' beliefs</p></div>
      <div class="tool-item"><code>engram_resolve</code><p>Settle a disagreement with a decision or merge</p></div>
    </div>
  </div>

</div>

<footer>
  <div class="container">
    <div class="footer-links">
      <span class="footer-logo">engram</span>
      <a href="https://github.com/Agentscreator/Engram" target="_blank">GitHub</a>
      <a href="https://github.com/Agentscreator/Engram/blob/main/LICENSE" target="_blank">Apache 2.0</a>
    </div>
    <p class="footer-tagline">An engram is the physical trace a memory leaves in the brain</p>
  </div>
</footer>

<div class="copy-toast" id="copy-toast">
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="7.5" stroke="#34d399" stroke-width="1"/>
    <path d="M5 8.5L7 10.5L11 6" stroke="#34d399" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
  <span>Copied to clipboard</span>
</div>

<script>
// ── Neural network background ──────────────────────────────────────
(function() {
  const canvas = document.getElementById('neural-bg');
  const ctx = canvas.getContext('2d');
  let w, h, nodes = [], mouse = { x: -1000, y: -1000 };

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  const NODE_COUNT = Math.min(60, Math.floor(window.innerWidth / 25));
  for (let i = 0; i < NODE_COUNT; i++) {
    nodes.push({
      x: Math.random() * w, y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
      r: Math.random() * 1.5 + 0.5,
    });
  }

  document.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });

  function draw() {
    ctx.clearRect(0, 0, w, h);
    nodes.forEach(n => {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > w) n.vx *= -1;
      if (n.y < 0 || n.y > h) n.vy *= -1;
    });
    // Edges
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 180) {
          const alpha = (1 - dist / 180) * 0.08;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.strokeStyle = `rgba(52, 211, 153, ${alpha})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
      // Mouse interaction
      const mdx = nodes[i].x - mouse.x;
      const mdy = nodes[i].y - mouse.y;
      const mdist = Math.sqrt(mdx * mdx + mdy * mdy);
      if (mdist < 200) {
        const alpha = (1 - mdist / 200) * 0.2;
        ctx.beginPath();
        ctx.moveTo(nodes[i].x, nodes[i].y);
        ctx.lineTo(mouse.x, mouse.y);
        ctx.strokeStyle = `rgba(52, 211, 153, ${alpha})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }
    }
    // Nodes
    nodes.forEach(n => {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(52, 211, 153, 0.25)';
      ctx.fill();
    });
    requestAnimationFrame(draw);
  }
  draw();
})();

// ── Scroll reveal ──────────────────────────────────────────────────
const observer = new IntersectionObserver((entries) => {
  entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('visible'); });
}, { threshold: 0.08 });
document.querySelectorAll('.reveal').forEach(el => observer.observe(el));

// ── Platform tab switcher ──────────────────────────────────────────
function switchTab(platform) {
  ['mac','ps','cmd'].forEach(p => {
    document.getElementById('tab-' + p).style.display = p === platform ? '' : 'none';
  });
  document.querySelectorAll('.platform-tabs .tab').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick').includes("'" + platform + "'"));
  });
}
(function() {
  const ua = navigator.userAgent || navigator.platform || '';
  if (/Win/i.test(ua)) switchTab('ps');
})();

// ── Copy helper ────────────────────────────────────────────────────
let toastTimeout;
function copyCode(id) {
  const text = document.getElementById(id).textContent.trim();
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    const original = btn.textContent;
    btn.textContent = '✓ Copied';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = original; btn.classList.remove('copied'); }, 2000);
    const toast = document.getElementById('copy-toast');
    clearTimeout(toastTimeout);
    toast.classList.add('show');
    toastTimeout = setTimeout(() => toast.classList.remove('show'), 2500);
    // Flash the parent code block border
    const block = document.getElementById(id).closest('.code-block');
    if (block) {
      block.style.borderColor = 'rgba(52, 211, 153, 0.5)';
      block.style.boxShadow = '0 0 20px rgba(52, 211, 153, 0.1)';
      setTimeout(() => { block.style.borderColor = ''; block.style.boxShadow = ''; }, 800);
    }
  });
}

// ── Graph state ────────────────────────────────────────────────────
let cy = null;
let allElements = null;

async function loadGraph() {
  const engramId  = document.getElementById('engram-id-input').value.trim();
  const inviteKey = document.getElementById('invite-key-input').value.trim();
  const errEl  = document.getElementById('graph-error');
  const loadEl = document.getElementById('graph-loading');
  const secEl  = document.getElementById('graph-section');
  const btn    = document.getElementById('search-btn');

  errEl.style.display  = 'none';
  secEl.style.display  = 'none';
  loadEl.style.display = 'block';
  btn.disabled = true;

  try {
    const resp = await fetch('/workspace/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ engram_id: engramId, invite_key: inviteKey }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      errEl.textContent = data.error || 'Authentication failed. Check your workspace ID and invite key.';
      errEl.style.display = 'block';
      return;
    }
    renderGraph(data);
    secEl.style.display = 'block';
  } catch (e) {
    errEl.textContent = 'Connection error. Please try again.';
    errEl.style.display = 'block';
  } finally {
    loadEl.style.display = 'none';
    btn.disabled = false;
  }
}

function renderGraph(data) {
  const { facts, conflicts, agents } = data;
  const active = facts.filter(f => !f.valid_until).length;
  const retired = facts.filter(f => f.valid_until).length;
  const open = conflicts.filter(c => c.status === 'open').length;
  document.getElementById('graph-stats').innerHTML = `
    <div class="stat"><div class="stat-num">${active}</div><div class="stat-label">Active facts</div></div>
    <div class="stat"><div class="stat-num">${retired}</div><div class="stat-label">Retired</div></div>
    <div class="stat"><div class="stat-num">${open}</div><div class="stat-label">Conflicts</div></div>
    <div class="stat"><div class="stat-num">${(agents||[]).length}</div><div class="stat-label">Agents</div></div>
  `;

  const elements = [];
  const scopeColors = {};
  const PALETTE = ['#10b981','#06b6d4','#8b5cf6','#ec4899','#f59e0b','#22c55e','#3b82f6'];
  let palIdx = 0;
  const scopeColor = (scope) => {
    if (!scopeColors[scope]) scopeColors[scope] = PALETTE[palIdx++ % PALETTE.length];
    return scopeColors[scope];
  };

  facts.forEach(f => {
    const ret = !!f.valid_until;
    elements.push({ data: {
      id: f.id, label: f.scope || 'general',
      content: f.content, scope: f.scope,
      fact_type: f.fact_type, committed_at: f.committed_at,
      durability: f.durability, retired: ret,
      color: ret ? '#64748b' : scopeColor(f.scope || 'general'),
      size: ret ? 18 : (f.confidence || 0.9) * 36 + 12,
    }});
  });

  facts.filter(f => f.supersedes_fact_id).forEach(f => {
    elements.push({ data: {
      id: `lin-${f.id}`, source: f.supersedes_fact_id, target: f.id,
      kind: 'lineage', label: 'supersedes',
    }});
  });

  conflicts.forEach(c => {
    if (c.status === 'open') {
      elements.push({ data: {
        id: `con-${c.id}`, source: c.fact_a_id, target: c.fact_b_id,
        kind: 'conflict', label: 'conflict',
        explanation: c.explanation, severity: c.severity,
      }});
    }
  });

  allElements = elements;
  if (cy) cy.destroy();
  cy = cytoscape({
    container: document.getElementById('cy'),
    elements,
    style: [
      { selector: 'node', style: {
        'background-color': 'data(color)', 'label': 'data(label)',
        'font-size': '10px', 'color': '#94a3b8',
        'text-valign': 'bottom', 'text-margin-y': '5px',
        'width': 'data(size)', 'height': 'data(size)',
        'border-width': 1.5, 'border-color': 'rgba(255,255,255,0.1)',
      }},
      { selector: 'node[retired = true]', style: { 'opacity': 0.35, 'border-style': 'dashed' }},
      { selector: 'edge[kind = "lineage"]', style: {
        'line-color': '#10b981', 'target-arrow-color': '#10b981',
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
        'width': 1, 'opacity': 0.4,
      }},
      { selector: 'edge[kind = "conflict"]', style: {
        'line-color': '#ef4444', 'line-style': 'dashed',
        'width': 2, 'opacity': 0.7, 'curve-style': 'bezier',
        'label': '×', 'font-size': '12px', 'text-rotation': 'autorotate',
      }},
      { selector: ':selected', style: { 'border-color': '#34d399', 'border-width': 2.5 }},
    ],
    layout: {
      name: facts.length < 30 ? 'cose' : 'random',
      animate: facts.length < 80, randomize: false,
      nodeRepulsion: 8000, idealEdgeLength: 120, padding: 24,
    },
  });

  cy.on('tap', 'node', evt => {
    const d = evt.target.data();
    document.getElementById('detail-scope').textContent = `${d.scope || 'general'}  ·  ${d.fact_type || 'observation'}`;
    document.getElementById('detail-content').textContent = d.content || '';
    const ts = d.committed_at ? new Date(d.committed_at).toLocaleString() : '';
    document.getElementById('detail-meta').textContent = `${d.retired ? 'Retired' : 'Active'}  ·  ${d.durability || 'durable'}  ·  ${ts}`;
    document.getElementById('fact-detail').style.display = 'block';
  });
  cy.on('tap', evt => {
    if (evt.target === cy) document.getElementById('fact-detail').style.display = 'none';
  });
}

function filterGraph(query) {
  if (!cy || !allElements) return;
  const q = query.toLowerCase();
  if (!q) { cy.elements().style('opacity', 1); return; }
  cy.nodes().forEach(n => {
    const matches = (n.data('content') || '').toLowerCase().includes(q) || (n.data('scope') || '').toLowerCase().includes(q);
    n.style('opacity', matches ? 1 : 0.08);
  });
  cy.edges().style('opacity', 0.03);
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('invite-key-input').addEventListener('keydown', e => { if (e.key === 'Enter') loadGraph(); });
  document.getElementById('engram-id-input').addEventListener('keydown', e => { if (e.key === 'Enter') loadGraph(); });
});
</script>
</body>
</html>"""


async def landing(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_landing())


app = Starlette(routes=[Route("/{path:path}", landing, methods=["GET"])])
