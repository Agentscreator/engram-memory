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
  <title>Engram — Shared Memory for Your AI Agents</title>
  <meta name="description" content="Engram is a shared memory ledger for your team. When one agent learns a fact, every other agent knows it instantly. If they contradict each other, Engram catches it before they break your code.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" onload="this.onload=null;this.rel='stylesheet'">
  <noscript><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"></noscript>
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
    .logo-memory {
      font-size: 13px; font-weight: 400; color: rgba(52, 211, 153, 0.5);
      letter-spacing: 0.12em; text-transform: uppercase;
      align-self: flex-end; margin-bottom: 2px; margin-left: 2px;
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
    .footer-logo { font-size: 18px; font-weight: 700; color: var(--emerald-400); letter-spacing: -0.02em; display: inline-flex; align-items: baseline; gap: 6px; }
    .footer-logo-memory { font-size: 10px; font-weight: 400; color: rgba(52, 211, 153, 0.45); letter-spacing: 0.12em; text-transform: uppercase; }
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

    /* ── Hamburger ───────────────────────────────────────────── */
    .hamburger {
      display: none; flex-direction: column; gap: 5px;
      cursor: pointer; padding: 8px; border: none; background: none;
      -webkit-tap-highlight-color: transparent;
    }
    .hamburger span {
      width: 22px; height: 2px; background: var(--text-secondary);
      border-radius: 2px; transition: all 0.25s ease; display: block;
    }
    .hamburger.open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
    .hamburger.open span:nth-child(2) { opacity: 0; transform: scaleX(0); }
    .hamburger.open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }

    .nav-mobile {
      display: none; border-top: 1px solid var(--border-subtle); padding: 8px 0;
    }
    .nav-mobile.open { display: block; }
    .nav-mobile a {
      display: block; padding: 14px 0; color: var(--text-secondary);
      text-decoration: none; font-size: 15px; font-weight: 500;
      border-bottom: 1px solid rgba(52,211,153,0.05);
      transition: color 0.2s;
    }
    .nav-mobile a:last-child { border-bottom: none; }
    .nav-mobile a:hover { color: var(--emerald-400); }

    /* ── Responsive ──────────────────────────────────────────── */
    @media (max-width: 768px) {
      h1 { font-size: 42px; }
      .card { padding: 32px 24px; }
      .section-title { font-size: 26px; }
      .feature-grid { grid-template-columns: 1fr; }
      .search-row { flex-direction: column; }
      #cy { height: 380px; }
      .platform-tabs { flex-wrap: wrap; }
      .install-step { flex-direction: column; gap: 12px; }
      .graph-hero { padding: 48px 0; }
      .graph-hero-title { font-size: 28px; }
      .graph-card { padding: 24px; }
      .privacy-item { padding: 20px; gap: 14px; }
    }

    @media (max-width: 640px) {
      .nav-links { display: none; }
      .hamburger { display: flex; }

      .container { padding: 0 20px; }

      h1 { font-size: 34px; letter-spacing: -0.03em; }
      .hero { padding: 64px 0 48px; }
      .hero-badge { font-size: 12px; padding: 5px 13px 5px 9px; margin-bottom: 24px; }
      .subtitle { font-size: 16px; margin-bottom: 36px; }
      .hero-cta {
        width: 100%; justify-content: center;
        padding: 15px 24px; font-size: 15px;
        border-radius: 14px;
      }

      .card { padding: 24px 18px; border-radius: 16px; margin-bottom: 24px; }
      .section-title { font-size: 22px; }
      .section-desc { font-size: 15px; }

      .code-block { font-size: 12px; padding: 14px 52px 14px 14px; }
      .copy-btn { padding: 4px 9px; font-size: 10px; top: 8px; right: 8px; }

      .tab { padding: 8px 13px; font-size: 12px; }

      .step-num { width: 28px; height: 28px; font-size: 13px; }
      .step-title { font-size: 14px; }
      .ide-note { font-size: 12px; }

      .feature-grid { gap: 12px; }
      .feature-item { padding: 20px; }
      .feature-item h3 { font-size: 14px; }

      .privacy-item { flex-direction: column; gap: 10px; padding: 18px; }
      .privacy-icon { width: 32px; height: 32px; font-size: 14px; }

      .graph-hero { padding: 48px 0; margin: 24px 0; }
      .graph-hero-title { font-size: 26px; }
      .graph-hero-desc { font-size: 15px; }
      .graph-card { padding: 20px 16px; }
      #cy { height: 300px; }
      .graph-stats { gap: 20px; }
      .stat-num { font-size: 26px; }
      .graph-legend { gap: 16px; }

      footer { padding: 40px 0 28px; }
      .footer-links { flex-wrap: wrap; gap: 16px 24px; }
      .footer-logo { width: 100%; text-align: center; }
    }

    @media (max-width: 380px) {
      h1 { font-size: 28px; }
      .hero { padding: 52px 0 36px; }
      .card { padding: 20px 16px; }
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
      <a href="/" class="logo"><span class="logo-dot"></span>engram<span class="logo-memory">memory</span></a>
      <nav class="nav-links">
        <a href="#install">Install</a>
        <a href="/dashboard">Dashboard</a>
        <a href="#privacy">Privacy</a>
        <a href="https://github.com/Agentscreator/Engram" target="_blank">GitHub</a>
        <a href="https://discord.gg/xnQDXrAq" target="_blank">Discord</a>
      </nav>
      <button class="hamburger" id="hamburger" onclick="toggleMenu()" aria-label="Open menu" aria-expanded="false">
        <span></span><span></span><span></span>
      </button>
    </div>
    <nav class="nav-mobile" id="nav-mobile" aria-hidden="true">
      <a href="#install" onclick="toggleMenu()">Install</a>
      <a href="/dashboard" onclick="toggleMenu()">Dashboard</a>
      <a href="#privacy" onclick="toggleMenu()">Privacy</a>
      <a href="https://github.com/Agentscreator/Engram" target="_blank">GitHub ↗</a>
      <a href="https://discord.gg/xnQDXrAq" target="_blank">Discord ↗</a>
    </nav>
  </div>
</header>

<section class="hero">
  <div class="container">
    <div class="hero-badge"><span class="hero-badge-dot"></span>MCP-compatible · Open source</div>
    <h1>Shared Memory for Your AI Agents.</h1>
    <p class="subtitle">
      Engram is "Git for AI memory." It syncs knowledge across agents instantly and flags logic conflicts before they ship. By anchoring every decision to a verified fact, it creates a permanent audit trail that connects agent output to human responsibility.
    </p>
    <a href="#install" class="hero-cta">
      Get started
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </a>
  </div>
</section>

<div class="container">

  <!-- Install -->
  <div class="card reveal" id="install">
    <div class="install-steps">
      <div class="install-step">
        <div class="step-num">1</div>
        <div class="step-content">
          <div class="step-title">Create an account</div>
          <a href="/dashboard" class="btn-step-cta" style="display:inline-block;margin-top:12px;
            padding:9px 20px;background:rgba(52,211,153,0.1);border:1px solid rgba(52,211,153,0.25);
            border-radius:9px;color:var(--em4);font-size:13px;font-weight:600;text-decoration:none;
            transition:background 0.2s;" onmouseover="this.style.background='rgba(52,211,153,0.18)'"
            onmouseout="this.style.background='rgba(52,211,153,0.1)'">
            Sign up at engram-memory.com →
          </a>
        </div>
      </div>
      <div class="install-step">
        <div class="step-num">2</div>
        <div class="step-content">
          <div class="step-title">Run the installer</div>
          <div class="platform-tabs">
            <button class="tab active" onclick="switchTab('mac')">macOS / Linux</button>
            <button class="tab" onclick="switchTab('ps')">PowerShell</button>
            <button class="tab" onclick="switchTab('cmd')">CMD</button>
          </div>
          <div class="code-block" id="tab-mac">
            <button class="copy-btn" onclick="copyCode('install-mac', event)">Copy</button>
            <div id="install-mac">curl -fsSL https://engram-memory.com/install | sh</div>
          </div>
          <div class="code-block" id="tab-ps" style="display:none;">
            <button class="copy-btn" onclick="copyCode('install-ps', event)">Copy</button>
            <div id="install-ps">irm https://engram-memory.com/install.ps1 | iex</div>
          </div>
          <div class="code-block" id="tab-cmd" style="display:none;">
            <button class="copy-btn" onclick="copyCode('install-cmd', event)">Copy</button>
            <div id="install-cmd">curl -fsSL https://engram-memory.com/install.cmd -o install.cmd &amp;&amp; install.cmd &amp;&amp; del install.cmd</div>
          </div>
        </div>
      </div>
      <div class="install-step">
        <div class="step-num">3</div>
        <div class="step-content">
          <div class="step-title">Restart your IDE</div>
        </div>
      </div>
      <div class="install-step">
        <div class="step-num">4</div>
        <div class="step-content">
          <div class="step-title">Ask your agent</div>
          <div class="code-block">
            <button class="copy-btn" onclick="copyCode('setup-prompt', event)">Copy</button>
            <div id="setup-prompt">"Set up Engram for my agents"</div>
          </div>
        </div>
      </div>
      <div class="install-step">
        <div class="step-num">5</div>
        <div class="step-content">
          <div class="step-title">Manage memory from your terminal</div>
          <div class="step-desc" style="margin-top:8px;font-size:14px;color:var(--t2);line-height:1.6;">
            Type <code style="font-family:'JetBrains Mono',monospace;font-size:13px;background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.18);padding:2px 7px;border-radius:5px;color:var(--em4);">engram</code> in any terminal to open the interactive shell.
            Review open conflicts, search workspace memory, stream live facts, and resolve contradictions — all without leaving your editor.
          </div>
          <div class="code-block" style="margin-top:14px;">
            <button class="copy-btn" onclick="copyCode('engram-cmd', event)">Copy</button>
            <div id="engram-cmd">engram</div>
          </div>
        </div>
      </div>
    </div>
    <p class="ide-note">
      <span>Claude Code · Claude Desktop · Cursor · VS Code · Windsurf · Kiro · Zed · Amazon Q · Trae · JetBrains · Cline · Roo Code · OpenCode</span><br>
      and any MCP-compatible IDE
    </p>
  </div>

  <!-- Dashboard CTA -->
</div>
<section class="graph-hero reveal" id="dashboard">
  <div class="container" style="text-align:center;">
    <div class="section-label">Dashboard</div>
    <h2 class="graph-hero-title">View your memory graph</h2>
    <p class="graph-hero-desc">
      See everything your agents know. Browse facts, resolve conflicts, track agents, and explore lineage chains — all in one place.
    </p>
    <a href="/dashboard" class="hero-cta" style="margin-top:32px;">
      Open Dashboard
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10m0 0L9 4m4 4L9 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </a>
  </div>
</section>
<div class="container">

  <!-- Privacy -->
  <div class="card reveal" id="privacy">
    <div class="section-label">Privacy</div>
    <div class="section-title">Your data is yours. Period.</div>

    <div class="privacy-grid">
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg></div>
        <div>
          <h3>Encrypted and isolated</h3>
          <p>All data encrypted in transit and at rest. Every workspace is fully isolated — no cross-team access.</p>
        </div>
      </div>
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M4.93 4.93l14.14 14.14"/></svg></div>
        <div>
          <h3>Never read, never sold</h3>
          <p>We don't read, analyze, train on, or redistribute your data. No analytics pipeline touches your content.</p>
        </div>
      </div>
      <div class="privacy-item">
        <div class="privacy-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--emerald-400)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg></div>
        <div>
          <h3>You control everything</h3>
          <p>Delete your workspace and it's gone. Anonymous mode strips names. You decide what's visible.</p>
        </div>
      </div>
    </div>
  </div>

</div>

<footer>
  <div class="container">
    <div class="footer-links">
      <span class="footer-logo">engram<span class="footer-logo-memory">memory</span></span>
      <a href="https://github.com/Agentscreator/Engram" target="_blank">GitHub</a>
      <a href="https://github.com/Agentscreator/Engram/blob/main/LICENSE" target="_blank">Apache 2.0</a>
      <a href="https://discord.gg/xnQDXrAq" target="_blank">Discord</a>
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
function copyCode(id, evt) {
  const btn = (evt && evt.currentTarget) || document.querySelector('#' + id).closest('.code-block').querySelector('.copy-btn');
  const text = document.getElementById(id).textContent.trim();
  navigator.clipboard.writeText(text).then(() => {
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
  }).catch(() => {
    // Fallback for browsers that block clipboard API (e.g. non-HTTPS)
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select(); document.execCommand('copy');
    document.body.removeChild(ta);
    const original = btn.textContent;
    btn.textContent = '✓ Copied';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = original; btn.classList.remove('copied'); }, 2000);
    const toast = document.getElementById('copy-toast');
    clearTimeout(toastTimeout);
    toast.classList.add('show');
    toastTimeout = setTimeout(() => toast.classList.remove('show'), 2500);
  });
}

// ── Hamburger menu ─────────────────────────────────────────────────
function toggleMenu() {
  const btn = document.getElementById('hamburger');
  const nav = document.getElementById('nav-mobile');
  const open = btn.classList.toggle('open');
  nav.classList.toggle('open', open);
  btn.setAttribute('aria-expanded', open);
  nav.setAttribute('aria-hidden', !open);
}
// Close on outside click
document.addEventListener('click', e => {
  const btn = document.getElementById('hamburger');
  const nav = document.getElementById('nav-mobile');
  if (nav.classList.contains('open') && !btn.contains(e.target) && !nav.contains(e.target)) {
    btn.classList.remove('open');
    nav.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
    nav.setAttribute('aria-hidden', 'true');
  }
});

</script>
</body>
</html>"""


async def landing(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_landing())


app = Starlette(routes=[Route("/{path:path}", landing, methods=["GET"])])
