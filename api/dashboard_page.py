"""Dashboard — login-gated memory graph with billing management."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route


def _render_dashboard() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Dashboard — Engram</title>
  <meta name="description" content="View and manage your team's shared memory — facts, conflicts, agents, and lineage.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" onload="this.onload=null;this.rel='stylesheet'">
  <noscript><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"></noscript>
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
    :root {
      --bg: #080808; --bg2: #0f0f0f; --bg-card: rgba(255,255,255,0.03);
      --border: rgba(255,255,255,0.07); --border-glow: rgba(52,211,153,0.3);
      --em4: #34d399; --em5: #10b981; --em6: #059669; --em7: #047857;
      --t1: #ffffff; --t2: rgba(255,255,255,0.6); --tm: rgba(255,255,255,0.35);
      --red: #f87171; --yellow: #fbbf24; --blue: #38bdf8;
    }
    html { scroll-behavior: smooth; }
    body { font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: var(--t1);
      background: var(--bg); min-height: 100vh; -webkit-font-smoothing: antialiased;
      position: relative; }
    body::before { content: ''; position: fixed; inset: 0; z-index: -1; pointer-events: none;
      background: radial-gradient(ellipse at 15% 0%, rgba(52,211,153,0.04) 0%, transparent 55%),
                  radial-gradient(ellipse at 85% 100%, rgba(6,182,212,0.025) 0%, transparent 55%);
      animation: ambientShift 12s ease-in-out infinite alternate; }
    .container { max-width: 1100px; margin: 0 auto; padding: 0 28px; }

    /* Header */
    header { padding: 14px 0; background: rgba(5,10,14,0.9); backdrop-filter: blur(20px);
      border-bottom: 1px solid rgba(255,255,255,0.04); position: sticky; top: 0; z-index: 100; }
    .header-content { display: flex; justify-content: space-between; align-items: center; }
    .logo { font-size: 18px; font-weight: 700; color: var(--em4); text-decoration: none;
      letter-spacing: -0.03em; display: flex; align-items: center; gap: 8px; }
    .logo-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--em4);
      box-shadow: 0 0 8px var(--em4);
      animation: pulse-dot 3s ease-in-out infinite; }
    .header-right { display: flex; align-items: center; gap: 16px; }
    .user-email { font-size: 13px; color: var(--t2); }
    .btn-sm { padding: 7px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;
      cursor: pointer; font-family: inherit; border: none; transition: opacity 0.2s; }
    .btn-ghost { background: rgba(255,255,255,0.05); border: 1px solid var(--border); color: var(--t2); }
    .btn-ghost:hover { border-color: var(--border-glow); color: var(--t1); }
    .btn-primary { background: linear-gradient(135deg, var(--em6), var(--em7)); color: white;
      box-shadow: 0 2px 12px rgba(5,150,105,0.25); }
    .btn-primary:hover { opacity: 0.9; }
    .btn-danger { background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3);
      color: var(--red); }
    .btn-danger:hover { background: rgba(239,68,68,0.25); }

    /* ── AUTH SCREEN ────────────────────────────────────────────── */
    #auth-screen {
      display: none; position: fixed; inset: 0; z-index: 50;
      background: var(--bg); overflow-y: auto;
    }
    .auth-layout {
      display: grid; grid-template-columns: 1fr 1fr; min-height: 100vh;
    }

    /* Left branding panel */
    .auth-brand {
      display: flex; flex-direction: column; justify-content: center;
      padding: 60px 64px; position: relative; overflow: hidden;
      background: linear-gradient(160deg, rgba(5,150,105,0.06) 0%, transparent 60%);
      border-right: 1px solid var(--border);
    }
    .auth-brand-glow {
      position: absolute; border-radius: 50%; filter: blur(80px); pointer-events: none;
    }
    .auth-brand-glow-1 {
      width: 400px; height: 400px; background: var(--em6);
      opacity: 0.07; top: -100px; left: -100px;
    }
    .auth-brand-glow-2 {
      width: 300px; height: 300px; background: #0891b2;
      opacity: 0.06; bottom: -60px; right: 40px;
    }
    .auth-brand-logo {
      font-size: 22px; font-weight: 700; color: var(--em4); letter-spacing: -0.03em;
      display: flex; align-items: center; gap: 9px; margin-bottom: 56px;
      text-decoration: none;
    }
    .auth-brand-logo-dot {
      width: 8px; height: 8px; border-radius: 50%; background: var(--em4);
      box-shadow: 0 0 14px var(--em4), 0 0 28px rgba(52,211,153,0.25);
      animation: pulse-dot 3s ease-in-out infinite;
    }
    @keyframes pulse-dot {
      0%,100% { box-shadow: 0 0 14px var(--em4), 0 0 28px rgba(52,211,153,0.25); }
      50%      { box-shadow: 0 0 6px var(--em4),  0 0 12px rgba(52,211,153,0.1); }
    }
    .auth-brand-heading {
      font-size: 38px; font-weight: 800; letter-spacing: -0.03em;
      line-height: 1.15; color: var(--t1); margin-bottom: 18px;
    }
    .auth-brand-heading span { color: var(--em4); }
    .auth-brand-sub {
      font-size: 16px; color: var(--t2); line-height: 1.65; margin-bottom: 48px;
    }
    .auth-features { display: flex; flex-direction: column; gap: 18px; }
    .auth-feature { display: flex; align-items: flex-start; gap: 14px; }
    .auth-feature-icon {
      width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
      background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.12);
      display: flex; align-items: center; justify-content: center;
      font-size: 16px; margin-top: 1px;
    }
    .auth-feature-text strong { display: block; font-size: 14px; font-weight: 600; color: var(--t1); }
    .auth-feature-text span { font-size: 13px; color: var(--t2); }

    /* Right form panel */
    .auth-form-panel {
      display: flex; align-items: center; justify-content: center;
      padding: 60px 64px;
    }
    .auth-form-inner { width: 100%; max-width: 400px; }
    .auth-form-heading { font-size: 26px; font-weight: 800; letter-spacing: -0.02em;
      color: var(--t1); margin-bottom: 6px; }
    .auth-form-sub { font-size: 14px; color: var(--t2); margin-bottom: 32px; }

    /* Tab switcher */
    .auth-tab-wrap {
      display: flex; background: rgba(0,0,0,0.25);
      border: 1px solid var(--border); border-radius: 12px; padding: 4px;
      margin-bottom: 28px; position: relative;
    }
    .auth-tab-slider {
      position: absolute; top: 4px; left: 4px; height: calc(100% - 8px);
      width: calc(50% - 4px); background: rgba(52,211,153,0.1);
      border: 1px solid rgba(52,211,153,0.18); border-radius: 9px;
      transition: transform 0.22s cubic-bezier(0.4,0,0.2,1);
    }
    .auth-tab-slider.right { transform: translateX(calc(100% + 4px)); }
    .auth-tab {
      flex: 1; padding: 9px 0; background: none; border: none;
      color: var(--tm); font-size: 14px; font-weight: 600; cursor: pointer;
      font-family: inherit; transition: color 0.2s; position: relative; z-index: 1;
      border-radius: 8px;
    }
    .auth-tab.active { color: var(--em4); }

    /* Fields */
    .auth-field { margin-bottom: 18px; }
    .auth-field label {
      display: block; font-size: 13px; font-weight: 500; color: var(--t2);
      margin-bottom: 7px;
    }
    .auth-field-wrap { position: relative; }
    .auth-field input {
      width: 100%; padding: 13px 16px; background: rgba(255,255,255,0.04);
      border: 1px solid rgba(52,211,153,0.1); border-radius: 11px; font-size: 14px;
      font-family: inherit; color: var(--t1);
      transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
    }
    .auth-field input:focus {
      outline: none; background: rgba(255,255,255,0.06);
      border-color: var(--em5); box-shadow: 0 0 0 3px rgba(16,185,129,0.12);
    }
    .auth-field input::placeholder { color: rgba(167,243,208,0.25); }
    .auth-field input.has-toggle { padding-right: 48px; }
    .pw-toggle {
      position: absolute; right: 14px; top: 50%; transform: translateY(-50%);
      background: none; border: none; cursor: pointer; color: var(--tm);
      padding: 4px; display: flex; align-items: center;
      transition: color 0.2s;
    }
    .pw-toggle:hover { color: var(--em4); }

    /* Submit button */
    .auth-submit-btn {
      width: 100%; padding: 14px; margin-top: 8px;
      background: linear-gradient(135deg, var(--em5) 0%, var(--em7) 100%);
      color: white; border: none; border-radius: 11px; font-size: 15px; font-weight: 700;
      cursor: pointer; font-family: inherit; letter-spacing: -0.01em;
      box-shadow: 0 4px 20px rgba(16,185,129,0.25), 0 1px 3px rgba(0,0,0,0.3);
      transition: transform 0.15s, box-shadow 0.15s, opacity 0.2s;
      display: flex; align-items: center; justify-content: center; gap: 8px;
    }
    .auth-submit-btn:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 6px 28px rgba(16,185,129,0.35), 0 2px 6px rgba(0,0,0,0.3);
    }
    .auth-submit-btn:active:not(:disabled) { transform: translateY(0); }
    .auth-submit-btn:disabled { opacity: 0.45; cursor: not-allowed; }
    .spinner {
      width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3);
      border-top-color: white; border-radius: 50%;
      animation: spin 0.65s linear infinite; display: none;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Error / success message */
    .auth-msg {
      display: none; margin-top: 14px; padding: 11px 14px; border-radius: 9px;
      font-size: 13px; font-weight: 500; animation: slideDown 0.2s ease;
    }
    @keyframes slideDown { from { opacity:0; transform:translateY(-6px); } to { opacity:1; transform:translateY(0); } }
    .auth-msg.error { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2); color: #fca5a5; }
    .auth-msg.success { background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.2); color: var(--em4); }

    .auth-divider {
      display: flex; align-items: center; gap: 12px;
      margin: 22px 0; color: var(--tm); font-size: 12px;
    }
    .auth-divider::before, .auth-divider::after {
      content: ''; flex: 1; height: 1px; background: var(--border);
    }
    .auth-switch {
      text-align: center; font-size: 13px; color: var(--t2); margin-top: 20px;
    }
    .auth-switch button {
      background: none; border: none; color: var(--em4); font-weight: 600;
      cursor: pointer; font-family: inherit; font-size: 13px;
      padding: 0; transition: opacity 0.2s;
    }
    .auth-switch button:hover { opacity: 0.8; }

    /* Mobile auth logo (shown only when brand panel is hidden) */
    .auth-mobile-logo {
      display: none; align-items: center; gap: 9px;
      font-size: 20px; font-weight: 700; color: var(--em4); letter-spacing: -0.03em;
      text-decoration: none; margin-bottom: 36px; justify-content: center;
    }
    .auth-mobile-logo-dot {
      width: 7px; height: 7px; border-radius: 50%; background: var(--em4);
      box-shadow: 0 0 10px var(--em4), 0 0 20px rgba(52,211,153,0.2);
    }

    /* Modal field inputs */
    .field { margin-bottom: 16px; }
    .field label {
      display: block; font-size: 13px; font-weight: 500; color: var(--t2); margin-bottom: 7px;
    }
    .field input {
      width: 100%; padding: 12px 14px; background: rgba(255,255,255,0.04);
      border: 1px solid rgba(52,211,153,0.1); border-radius: 10px; font-size: 14px;
      font-family: inherit; color: var(--t1);
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .field input:focus {
      outline: none; background: rgba(255,255,255,0.06);
      border-color: var(--em5); box-shadow: 0 0 0 3px rgba(16,185,129,0.12);
    }
    .field input::placeholder { color: rgba(167,243,208,0.25); }

    @media (max-width: 900px) {
      .auth-layout { grid-template-columns: 1fr; }
      .auth-brand { display: none; }
      .auth-form-panel {
        padding: 48px 28px; min-height: 100vh;
        align-items: flex-start; padding-top: 64px;
      }
      .auth-mobile-logo { display: flex; }
      .auth-form-heading { font-size: 22px; }
    }

    /* ── WORKSPACE LIST ─────────────────────────────────────────── */
    #ws-list-screen { display: none; padding: 40px 0; }
    .screen-header { display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 28px; }
    .screen-title { font-size: 22px; font-weight: 700; color: var(--t1); }
    .ws-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
    .ws-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px;
      padding: 24px; cursor: pointer; transition: border-color 0.2s, transform 0.15s;
      position: relative; }
    .ws-card:hover { border-color: var(--border-glow); transform: translateY(-2px); }
    .ws-card.paused { border-color: rgba(239,68,68,0.3); }
    .ws-name { font-size: 16px; font-weight: 700; color: var(--t1); margin-bottom: 4px;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ws-id { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 500;
      color: var(--tm); margin-bottom: 12px; }
    .ws-id-main { font-family: 'JetBrains Mono', monospace; font-size: 15px; font-weight: 600;
      color: var(--em4); margin-bottom: 12px; }
    .ws-rename-btn { padding: 5px 12px; border-radius: 7px; font-size: 12px; font-weight: 600;
      background: rgba(255,255,255,0.04); border: 1px solid var(--border); color: var(--t2);
      cursor: pointer; font-family: inherit; transition: background 0.2s, color 0.2s; }
    .ws-rename-btn:hover { background: rgba(99,102,241,0.12); border-color: rgba(99,102,241,0.3);
      color: #818cf8; }
    .ws-badges { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .badge { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
      padding: 3px 10px; border-radius: 6px; }
    .badge-active { background: rgba(52,211,153,0.1); color: var(--em4); }
    .badge-paused { background: rgba(239,68,68,0.15); color: var(--red); }
    .badge-pro { background: rgba(56,189,248,0.1); color: var(--blue); }
    .badge-free { background: rgba(167,243,208,0.08); color: var(--tm); }
    .ws-usage-bar { height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px;
      overflow: hidden; margin-bottom: 8px; }
    .ws-usage-fill { height: 100%; border-radius: 2px; background: var(--em5);
      transition: width 0.4s; }
    .ws-usage-fill.near { background: var(--yellow); }
    .ws-usage-fill.over { background: var(--red); }
    .ws-usage-label { font-size: 12px; color: var(--tm); }

    /* Connect workspace modal */
    .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
      z-index: 200; align-items: center; justify-content: center; }
    .modal-overlay.open { display: flex; }
    .modal { background: var(--bg2); border: 1px solid var(--border); border-radius: 20px;
      padding: 36px; width: 100%; max-width: 480px; }
    .modal h3 { font-size: 18px; font-weight: 700; margin-bottom: 8px; }
    .modal .subtitle { font-size: 13px; color: var(--t2); margin-bottom: 24px; }
    .modal-actions { display: flex; gap: 10px; margin-top: 20px; }
    .modal-actions button { flex: 1; }

    /* PIN input */
    .pin-row { display: flex; gap: 10px; justify-content: center; margin: 20px 0; }
    .pin-digit {
      width: 52px; height: 60px; border-radius: 12px; border: 1px solid rgba(52,211,153,0.15);
      background: rgba(255,255,255,0.04); color: var(--t1); font-size: 26px; font-weight: 700;
      text-align: center; font-family: 'JetBrains Mono', monospace;
      transition: border-color 0.2s, box-shadow 0.2s;
      -webkit-appearance: none; appearance: none;
    }
    .pin-digit:focus {
      outline: none; border-color: var(--em5); box-shadow: 0 0 0 3px rgba(16,185,129,0.12);
    }

    /* Invite key display */
    .invite-key-box {
      background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 10px;
      padding: 14px 16px; font-family: 'JetBrains Mono', monospace; font-size: 12px;
      color: var(--em4); word-break: break-all; line-height: 1.6;
      position: relative; margin: 16px 0;
    }
    .copy-btn {
      margin-top: 8px; width: 100%; padding: 10px; border-radius: 9px;
      background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.18);
      color: var(--em4); font-size: 13px; font-weight: 600; cursor: pointer;
      font-family: inherit; transition: background 0.2s;
    }
    .copy-btn:hover { background: rgba(52,211,153,0.15); }
    .copy-btn.copied { background: rgba(52,211,153,0.2); border-color: rgba(52,211,153,0.4); color: #34d399; }

    /* Workspace list action buttons */
    .ws-list-actions { display: flex; gap: 10px; }
    .ws-card-footer { display: flex; justify-content: space-between; align-items: center;
      margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
    .ws-key-btn { padding: 6px 14px; border-radius: 7px; font-size: 12px; font-weight: 600;
      background: rgba(52,211,153,0.07); border: 1px solid rgba(52,211,153,0.15); color: var(--em4);
      cursor: pointer; font-family: inherit; transition: background 0.2s; }
    .ws-key-btn:hover { background: rgba(52,211,153,0.14); }
    .ws-delete-btn { padding: 5px 10px; border-radius: 7px; font-size: 12px; font-weight: 600;
      background: rgba(239,68,68,0.07); border: 1px solid rgba(239,68,68,0.2); color: var(--red);
      cursor: pointer; font-family: inherit; transition: background 0.2s; }
    .ws-delete-btn:hover { background: rgba(239,68,68,0.15); }
    .ws-delete-corner { position: absolute; top: 12px; right: 12px; width: 28px; height: 28px;
      border-radius: 7px; background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2);
      color: var(--red); cursor: pointer; line-height: 1;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.15s, border-color 0.15s; z-index: 2; }
    .ws-delete-corner:hover { background: rgba(239,68,68,0.2); border-color: rgba(239,68,68,0.4); }

    /* ── WORKSPACE DETAIL ───────────────────────────────────────── */
    #ws-detail-screen { display: none; }
    .detail-header { padding: 24px 0 0; display: flex; align-items: center; gap: 16px;
      margin-bottom: 0; }
    .back-btn { background: none; border: none; color: var(--t2); cursor: pointer;
      font-family: inherit; font-size: 13px; font-weight: 500; padding: 0;
      display: flex; align-items: center; gap: 6px; transition: color 0.2s; }
    .back-btn:hover { color: var(--em4); }
    .detail-ws-id { font-family: 'JetBrains Mono', monospace; font-size: 13px;
      color: var(--tm); margin-top: 2px; }
    .detail-ws-name { font-size: 18px; font-weight: 700; color: var(--t1); line-height: 1.2; }
    .detail-name-wrap { display: flex; flex-direction: column; gap: 2px; }
    .rename-btn { background: rgba(255,255,255,0.04); border: 1px solid var(--border); color: var(--t2);
      cursor: pointer; font-size: 12px; font-weight: 600; font-family: inherit;
      padding: 4px 10px; border-radius: 6px; transition: background 0.15s, color 0.15s; line-height: 1; }
    .rename-btn:hover { background: rgba(99,102,241,0.12); border-color: rgba(99,102,241,0.3); color: #818cf8; }
    .rename-form { display: none; align-items: center; gap: 8px; flex-wrap: wrap; }
    .rename-form.visible { display: flex; }
    .rename-input { background: var(--bg-card); border: 1px solid var(--border-glow); border-radius: 8px;
      color: var(--t1); font-size: 15px; font-family: inherit; padding: 6px 10px;
      outline: none; min-width: 200px; }
    .rename-save { padding: 6px 14px; background: var(--em5); color: #000; border: none;
      border-radius: 7px; font-size: 13px; font-weight: 600; font-family: inherit; cursor: pointer; }
    .rename-cancel { padding: 6px 10px; background: none; border: 1px solid var(--border);
      border-radius: 7px; font-size: 13px; color: var(--t2); font-family: inherit; cursor: pointer; }

    /* Paused banner */
    .paused-banner { margin: 16px 0; padding: 16px 20px; background: rgba(239,68,68,0.08);
      border: 1px solid rgba(239,68,68,0.25); border-radius: 12px;
      display: flex; justify-content: space-between; align-items: center; gap: 16px; }
    .paused-banner-text { font-size: 14px; color: var(--red); }
    .paused-banner-text strong { display: block; margin-bottom: 2px; }
    .paused-banner-text span { font-size: 13px; opacity: 0.8; }

    /* Conflict indicator */
    .stats-row { padding: 20px 0 8px; }
    .conflict-indicator { display: flex; align-items: baseline; gap: 10px; }
    .conflict-count { font-size: 36px; font-weight: 700; color: var(--red);
      letter-spacing: -0.02em; line-height: 1; font-variant-numeric: tabular-nums; }
    .conflict-label { font-size: 14px; font-weight: 500; color: rgba(248,113,113,0.6);
      letter-spacing: -0.01em; }

    /* Tabs */
    .tabs { display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,0.06);
      margin-top: 4px; }
    .tab-btn { padding: 14px 20px; background: none; border: none;
      border-bottom: 2px solid transparent; color: rgba(255,255,255,0.3); font-size: 13px;
      font-weight: 600; cursor: pointer; font-family: inherit;
      transition: color 0.2s, border-color 0.2s; letter-spacing: -0.01em; }
    .tab-btn.active { color: var(--t1); border-bottom-color: var(--em4); }
    .tab-btn:hover:not(.active) { color: rgba(255,255,255,0.5); }
    .tab-panel { display: none; padding: 28px 0; }
    .tab-panel.active { display: block; animation: fadePanel 0.35s ease; }
    @keyframes fadePanel { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

    /* Graph */
    .graph-controls { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; }
    .graph-filter { flex: 1; padding: 11px 16px; background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; font-size: 13px;
      font-family: inherit; color: var(--t1);
      transition: border-color 0.2s, box-shadow 0.2s; }
    .graph-filter:focus { outline: none; border-color: rgba(52,211,153,0.3);
      box-shadow: 0 0 0 3px rgba(52,211,153,0.06); }
    .graph-filter::placeholder { color: rgba(255,255,255,0.2); }
    .graph-wrap { position: relative; border-radius: 16px; overflow: hidden;
      border: 1px solid rgba(255,255,255,0.04); background: rgba(0,0,0,0.2); }
    .graph-wrap::before { content: ''; position: absolute; inset: 0; z-index: 0; pointer-events: none;
      background: radial-gradient(ellipse at 25% 40%, rgba(52,211,153,0.03) 0%, transparent 60%),
                  radial-gradient(ellipse at 75% 60%, rgba(6,182,212,0.02) 0%, transparent 50%); }
    #cy { width: 100%; height: 520px; position: relative; z-index: 1; }
    #graph-particles { position: absolute; inset: 0; z-index: 0; pointer-events: none; }
    .graph-legend { display: flex; gap: 20px; margin-top: 14px; flex-wrap: wrap; }
    .legend-item { display: flex; align-items: center; gap: 6px; font-size: 11px;
      color: rgba(255,255,255,0.35); font-weight: 500; }
    .legend-dot { width: 8px; height: 8px; border-radius: 50%; }
    .node-detail { display: none; margin-top: 16px; padding: 20px 24px;
      background: rgba(255,255,255,0.02);
      border-radius: 12px; border-left: 2px solid var(--em5);
      animation: slideDetail 0.25s ease; }
    @keyframes slideDetail { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: translateX(0); } }
    .node-detail h4 { font-size: 12px; font-weight: 600; color: var(--em4); margin-bottom: 6px;
      letter-spacing: 0.02em; text-transform: uppercase; }
    .node-detail p { font-size: 14px; color: var(--t2); line-height: 1.6; }
    .node-detail .meta { font-size: 12px; color: var(--tm); margin-top: 8px; }

    /* Conflicts */
    .conflict-list { display: flex; flex-direction: column; gap: 10px; }
    .conflict-card { padding: 20px 24px; background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.04); border-radius: 12px;
      transition: border-color 0.2s; }
    .conflict-card:hover { border-color: rgba(255,255,255,0.08); }
    .conflict-card.resolved { opacity: 0.5; }
    .conflict-question { font-size: 15px; color: var(--t1); line-height: 1.5;
      margin-bottom: 14px; font-weight: 500; }
    .conflict-actions { display: flex; gap: 8px; margin-bottom: 12px; }
    .btn-yes { padding: 8px 18px; border-radius: 8px; font-size: 13px; font-weight: 600;
      background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2);
      color: var(--em4); cursor: pointer; font-family: inherit; transition: all 0.15s; }
    .btn-yes:hover { background: rgba(52,211,153,0.18); }
    .btn-no { padding: 8px 18px; border-radius: 8px; font-size: 13px; font-weight: 600;
      background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
      color: var(--t2); cursor: pointer; font-family: inherit; transition: all 0.15s; }
    .btn-no:hover { background: rgba(255,255,255,0.06); }
    .conflict-resolved-note { font-size: 12px; color: var(--tm); margin-bottom: 8px; }
    .conflict-details { margin-top: 4px; }
    .conflict-details summary { font-size: 12px; color: var(--tm); cursor: pointer;
      padding: 4px 0; transition: color 0.15s; }
    .conflict-details summary:hover { color: var(--t2); }
    .conflict-details[open] summary { margin-bottom: 10px; }
    .conflict-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .conflict-fact { padding: 12px; background: rgba(0,0,0,0.15); border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.03);
      font-size: 13px; color: var(--t2); line-height: 1.5; }
    .conflict-fact-label { font-size: 11px; font-weight: 600; color: var(--tm);
      margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.04em; }
    .conflict-date { font-size: 12px; color: var(--tm); margin-top: 10px; }
    .empty-state { text-align: center; padding: 60px 20px; color: rgba(255,255,255,0.25); font-size: 14px; }

    /* Facts */
    .facts-toolbar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
    .facts-search { flex: 1; min-width: 200px; padding: 11px 16px; background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; font-size: 13px;
      font-family: inherit; color: var(--t1); transition: border-color 0.2s; }
    .facts-search:focus { outline: none; border-color: rgba(52,211,153,0.3); }
    .facts-search::placeholder { color: rgba(255,255,255,0.2); }
    .filter-btn { padding: 8px 14px; background: transparent;
      border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; color: rgba(255,255,255,0.3);
      font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; transition: all 0.2s; }
    .filter-btn.active { background: rgba(52,211,153,0.08); border-color: rgba(52,211,153,0.15); color: var(--em4); }
    .filter-btn:hover:not(.active) { color: rgba(255,255,255,0.5); border-color: rgba(255,255,255,0.1); }
    .fact-table { border: 1px solid rgba(255,255,255,0.04); border-radius: 12px; overflow: hidden;
      background: rgba(255,255,255,0.01); }
    .fact-row { display: grid; grid-template-columns: 1fr 120px 80px 100px;
      gap: 16px; padding: 13px 20px; border-bottom: 1px solid rgba(255,255,255,0.03);
      align-items: center; font-size: 13px; transition: background 0.15s; }
    .fact-row:hover:not(.fact-row-header) { background: rgba(255,255,255,0.02); }
    .fact-row:last-child { border-bottom: none; }
    .fact-row-header { color: rgba(255,255,255,0.25); font-weight: 600; font-size: 11px;
      letter-spacing: 0.04em; text-transform: uppercase; background: rgba(0,0,0,0.15);
      border-bottom: 1px solid rgba(255,255,255,0.04); }
    .fact-row-header:hover { background: rgba(0,0,0,0.15); }
    .fact-content { color: var(--t2); line-height: 1.5; }
    .fact-scope { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--em4);
      background: rgba(52,211,153,0.06); padding: 2px 8px; border-radius: 4px; display: inline-block; }
    .fact-type { color: var(--tm); font-size: 12px; }
    .fact-date { color: var(--tm); font-size: 12px; font-variant-numeric: tabular-nums; }
    .fact-retired { opacity: 0.35; }

    /* Agents */
    .agents-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
    .agent-card { padding: 22px; background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.04); border-radius: 12px;
      transition: border-color 0.2s; }
    .agent-card:hover { border-color: rgba(255,255,255,0.08); }
    .agent-id { font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--em4); margin-bottom: 4px; }
    .agent-engineer { font-size: 13px; color: var(--t2); margin-bottom: 14px; }
    .agent-stats { display: flex; gap: 20px; }
    .agent-stat-label { font-size: 11px; color: var(--tm); text-transform: uppercase; letter-spacing: 0.04em; }
    .agent-stat-val { font-size: 18px; font-weight: 700; color: var(--t1); font-variant-numeric: tabular-nums; }

    /* Billing tab */
    .billing-section { display: flex; flex-direction: column; gap: 16px; }
    .billing-card { background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 14px; padding: 24px; }
    .billing-card h3 { font-size: 15px; font-weight: 700; color: var(--t1); margin-bottom: 16px; }
    .usage-bar-lg { height: 6px; background: rgba(255,255,255,0.04); border-radius: 3px;
      overflow: hidden; margin: 12px 0; }
    .usage-fill-lg { height: 100%; border-radius: 3px; background: var(--em5); transition: width 0.6s ease; }
    .usage-fill-lg.near { background: var(--yellow); }
    .usage-fill-lg.over { background: var(--red); }
    .usage-numbers { display: flex; justify-content: space-between; font-size: 13px;
      color: var(--tm); margin-bottom: 4px; }
    .billing-row { display: flex; justify-content: space-between; align-items: center;
      padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 14px; }
    .billing-row:last-child { border-bottom: none; }
    .billing-row .label { color: var(--t2); }
    .billing-row .value { font-weight: 600; color: var(--t1); font-family: 'JetBrains Mono', monospace; }
    .billing-row .value.green { color: var(--em4); }
    .billing-row .value.red { color: var(--red); }
    .pricing-note { font-size: 12px; color: var(--tm); margin-top: 12px; line-height: 1.6; }
    /* Plan badge */
    .plan-badge { display: inline-block; padding: 3px 10px; border-radius: 20px;
      font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
    .plan-badge-free { background: rgba(255,255,255,0.06); color: var(--t2); }
    .plan-badge-builder { background: rgba(52,211,153,0.12); color: var(--em4); }
    .plan-badge-team { background: rgba(96,165,250,0.12); color: #60a5fa; }
    .plan-badge-scale { background: rgba(167,139,250,0.12); color: #a78bfa; }
    /* Plan grid */
    .plan-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; }
    @media (max-width: 700px) { .plan-grid { grid-template-columns: repeat(2,1fr); } }
    .plan-card { padding: 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05);
      background: rgba(255,255,255,0.015); display: flex; flex-direction: column; gap: 6px; }
    .plan-card-current { border-color: var(--em5); background: rgba(16,185,129,0.05); }
    .plan-card-name { font-size: 13px; font-weight: 700; color: var(--t1); }
    .plan-card-price { font-size: 22px; font-weight: 800; color: var(--t1); line-height: 1; }
    .plan-card-price span { font-size: 12px; font-weight: 400; color: var(--tm); }
    .plan-card-commits { font-size: 12px; color: var(--t2); font-family: 'JetBrains Mono', monospace; }
    .plan-card-feature { font-size: 11px; margin-top: 2px; }
    .plan-card-feature.yes { color: var(--em4); }
    .plan-card-feature.no { color: rgba(255,255,255,0.2); }
    .plan-card-label { font-size: 11px; color: var(--em4); font-weight: 600;
      margin-top: auto; padding-top: 8px; }
    .plan-upgrade-btn { width: 100%; margin-top: auto; padding: 7px 0 !important;
      font-size: 12px !important; }

    @media (max-width: 768px) {
      .container { padding: 0 16px; }

      /* Header */
      header { padding: 12px 0; }
      .user-email { display: none; }
      .btn-sm { padding: 7px 13px; font-size: 12px; }

      /* Workspace list */
      .ws-grid { grid-template-columns: 1fr; gap: 12px; }
      .screen-title { font-size: 18px; }

      /* Workspace detail */
      .detail-header { flex-wrap: wrap; gap: 10px; padding-top: 16px; }
      .detail-ws-id { font-size: 11px; }
      .detail-ws-name { font-size: 15px; }
      .back-btn { font-size: 12px; }

      /* Conflict indicator */
      .stats-row { padding: 16px 0 4px; }
      .conflict-count { font-size: 28px; }
      .conflict-label { font-size: 13px; }

      /* Tabs — horizontally scrollable, no wrapping */
      .tabs {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        flex-wrap: nowrap;
      }
      .tabs::-webkit-scrollbar { display: none; }
      .tab-btn {
        padding: 12px 16px;
        font-size: 13px;
        flex-shrink: 0;
        min-height: 44px;
        white-space: nowrap;
      }

      /* Graph */
      .graph-controls { padding: 12px 0 0; }
      .graph-filter { font-size: 13px; padding: 10px 14px; }
      #cy { height: 340px; }

      /* Facts */
      .facts-toolbar { flex-wrap: wrap; gap: 8px; }
      .facts-search { flex: 1 1 100%; font-size: 13px; }
      .filter-btn { font-size: 12px; padding: 6px 12px; }
      .fact-row { grid-template-columns: 1fr; gap: 4px; padding: 12px 14px; }
      .fact-row-header { display: none; }
      .fact-content { font-size: 13px; }
      .fact-scope, .fact-type, .fact-date { font-size: 11px; }

      /* Conflicts */
      .conflict-facts { grid-template-columns: 1fr; }
      .conflict-card { padding: 16px; }

      /* Agents */
      .agents-grid { grid-template-columns: 1fr; }

      /* Modal — bottom sheet on mobile */
      .modal-overlay { align-items: flex-end; }
      .modal {
        border-radius: 20px 20px 0 0;
        padding: 28px 24px calc(28px + env(safe-area-inset-bottom));
        max-width: 100%;
        width: 100%;
      }

      /* Paused banner */
      .paused-banner { flex-direction: column; gap: 12px; }

      /* Conflicts */
      .conflict-facts { grid-template-columns: 1fr; }
    }

    @media (max-width: 480px) {
      .auth-form-panel { padding: 48px 20px; }
      .auth-mobile-logo { margin-bottom: 28px; }
      .pin-digit { width: 46px; height: 54px; font-size: 22px; }
    }
  </style>
</head>
<body>

<header>
  <div class="container">
    <div class="header-content">
      <a href="/" class="logo"><span class="logo-dot"></span>engram</a>
      <div class="header-right" id="header-right">
        <a href="/" class="btn-sm btn-ghost">← Home</a>
      </div>
    </div>
  </div>
</header>

<!-- ── AUTH SCREEN ───────────────────────────────────────────────── -->
<div id="auth-screen">
  <div class="auth-layout">

    <!-- Left: branding -->
    <div class="auth-brand">
      <div class="auth-brand-glow auth-brand-glow-1"></div>
      <div class="auth-brand-glow auth-brand-glow-2"></div>
      <a href="/" class="auth-brand-logo">
        <span class="auth-brand-logo-dot"></span>engram
      </a>
      <h1 class="auth-brand-heading">Shared memory<br>for your <span>AI team</span></h1>
      <p class="auth-brand-sub">Every agent on your team sees the same verified facts,<br>conflicts, and decisions — in real time.</p>
      <div class="auth-features">
        <div class="auth-feature">
          <div class="auth-feature-icon">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="var(--em4)" stroke-width="1.8">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/>
            </svg>
          </div>
          <div class="auth-feature-text">
            <strong>Zero setup</strong>
            <span>One invite key. Works with any MCP-compatible IDE.</span>
          </div>
        </div>
        <div class="auth-feature">
          <div class="auth-feature-icon">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="var(--em4)" stroke-width="1.8">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <div class="auth-feature-text">
            <strong>Private by default</strong>
            <span>All data encrypted. Never shared, always yours.</span>
          </div>
        </div>
        <div class="auth-feature">
          <div class="auth-feature-icon">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="var(--em4)" stroke-width="1.8">
              <circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/>
              <path stroke-linecap="round" d="M12 7v4m0 0l-5.5 6M12 11l5.5 6"/>
            </svg>
          </div>
          <div class="auth-feature-text">
            <strong>Conflict detection</strong>
            <span>Automatically flags contradictions across agents.</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: form -->
    <div class="auth-form-panel">
      <div class="auth-form-inner">
        <a href="/" class="auth-mobile-logo">
          <span class="auth-mobile-logo-dot"></span>engram
        </a>
        <h2 class="auth-form-heading" id="auth-heading">Welcome back</h2>
        <p class="auth-form-sub" id="auth-subheading">Sign in to your Engram account</p>

        <div class="auth-tab-wrap">
          <div class="auth-tab-slider" id="auth-tab-slider"></div>
          <button class="auth-tab active" id="tab-login" onclick="switchAuthTab('login')">Sign in</button>
          <button class="auth-tab" id="tab-signup" onclick="switchAuthTab('signup')">Create account</button>
        </div>

        <div class="auth-field">
          <label for="auth-email">Email address</label>
          <input type="email" id="auth-email" placeholder="you@example.com" autocomplete="email" />
        </div>
        <div class="auth-field">
          <label for="auth-password">Password</label>
          <div class="auth-field-wrap">
            <input type="password" id="auth-password" placeholder="••••••••"
              autocomplete="current-password" class="has-toggle" />
            <button class="pw-toggle" type="button" onclick="togglePassword()" title="Show/hide password" aria-label="Toggle password visibility">
              <svg id="pw-eye" width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
                <path stroke-linecap="round" stroke-linejoin="round"
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                <path stroke-linecap="round" stroke-linejoin="round"
                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
              </svg>
            </button>
          </div>
        </div>

        <button class="auth-submit-btn" id="auth-submit-btn" onclick="submitAuth()">
          <div class="spinner" id="auth-spinner"></div>
          <span id="auth-btn-label">Sign in</span>
        </button>

        <div class="auth-msg error" id="auth-error"></div>
        <div class="auth-msg success" id="auth-success"></div>

        <div class="auth-switch">
          <span id="auth-switch-text">Don't have an account?</span>
          <button onclick="switchAuthTab(authMode === 'login' ? 'signup' : 'login')" id="auth-switch-btn">Create one</button>
        </div>
      </div>
    </div>

  </div>
</div>

<!-- ── WORKSPACE LIST SCREEN ─────────────────────────────────────── -->
<div id="ws-list-screen">
  <div class="container">
    <div class="screen-header">
      <div class="screen-title">Your Workspaces</div>
      <div class="ws-list-actions">
        <button class="btn-sm btn-ghost" onclick="openConnectModal()">Connect existing</button>
        <button class="btn-sm btn-primary" onclick="openCreateModal()">+ New workspace</button>
      </div>
    </div>
    <div class="ws-grid" id="ws-grid">
      <div class="empty-state" style="grid-column:1/-1">
        No workspaces yet.<br>
        <span style="font-size:13px">Click <strong>+ New workspace</strong> to create one, or connect an existing workspace with an invite key.</span>
      </div>
    </div>
  </div>
</div>

<!-- ── WORKSPACE DETAIL SCREEN ───────────────────────────────────── -->
<div id="ws-detail-screen">
  <div class="container">
    <div class="detail-header">
      <button class="back-btn" onclick="goBackToList()">← All workspaces</button>
      <div class="detail-name-wrap">
        <div style="display:flex;align-items:center;gap:6px">
          <span class="detail-ws-name" id="detail-ws-name"></span>
          <button class="rename-btn" id="rename-btn" onclick="startRename()">Rename</button>
        </div>
        <span class="detail-ws-id" id="detail-ws-id"></span>
        <div class="rename-form" id="rename-form">
          <input class="rename-input" id="rename-input" maxlength="80" placeholder="Workspace name…" />
          <button class="rename-save" onclick="saveRename()">Save</button>
          <button class="rename-cancel" onclick="cancelRename()">Cancel</button>
          <span id="rename-error" style="font-size:12px;color:var(--red);display:none"></span>
        </div>
      </div>
      <div style="margin-left:auto;display:flex;gap:8px">
        <span id="detail-plan-badge" class="badge"></span>
        <span id="detail-status-badge" class="badge"></span>
      </div>
    </div>

    <!-- Paused banner -->
    <div class="paused-banner" id="paused-banner" style="display:none">
      <div class="paused-banner-text">
        <strong>Workspace paused — free tier limit reached</strong>
        <span>Your workspace has exceeded the 500 commits/month free tier limit. Upgrade your plan to resume.</span>
      </div>
      <button class="btn-sm btn-primary" onclick="startCheckout()">Add payment method</button>
    </div>

    <div class="stats-row" id="stats-row"></div>

    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('conflicts', event)">Conflicts <span id="conflict-badge"></span></button>
      <button class="tab-btn" onclick="switchTab('facts', event)">Facts</button>
      <button class="tab-btn" onclick="switchTab('billing', event)">Billing</button>
    </div>

    <!-- Conflicts -->
    <div class="tab-panel active" id="panel-conflicts">
      <div class="conflict-list" id="conflict-list"></div>
    </div>

    <!-- Facts -->
    <div class="tab-panel" id="panel-facts">
      <div class="facts-toolbar">
        <input class="facts-search" id="facts-search" placeholder="Search facts…" oninput="filterFacts()" />
        <button class="filter-btn active" onclick="setFactFilter('all', this)">All</button>
        <button class="filter-btn" onclick="setFactFilter('active', this)">Active</button>
        <button class="filter-btn" onclick="setFactFilter('retired', this)">Retired</button>
      </div>
      <div class="fact-table">
        <div class="fact-row fact-row-header">
          <div>Content</div><div>Scope</div><div>Type</div><div>Date</div>
        </div>
        <div id="facts-list"></div>
      </div>
    </div>

    <!-- Billing -->
    <div class="tab-panel" id="panel-billing">
      <div class="billing-section" id="billing-section"></div>
    </div>
  </div>
</div>

<!-- ── DELETE WORKSPACE MODAL ───────────────────────────────────── -->
<div class="modal-overlay" id="delete-modal">
  <div class="modal" style="max-width:400px;">
    <h3 style="color:var(--red);">Delete workspace?</h3>
    <p class="subtitle" id="delete-modal-subtitle" style="margin-bottom:16px;"></p>
    <p style="font-size:13px;color:var(--tm);margin-bottom:20px;">
      This removes it from your account. If you created this workspace and are the last member,
      all facts and history will be permanently deleted.
    </p>
    <div id="delete-modal-error" style="display:none;color:var(--red);font-size:13px;margin-bottom:12px;"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end;">
      <button class="ws-rename-btn" onclick="closeDeleteModal()">Cancel</button>
      <button onclick="confirmDelete()"
        style="padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;font-family:inherit;
               background:var(--red);color:#fff;border:none;cursor:pointer;">
        Delete
      </button>
    </div>
  </div>
</div>

<!-- ── DELETE ACCOUNT MODAL ─────────────────────────────────────── -->
<div class="modal-overlay" id="delete-account-modal">
  <div class="modal" style="max-width:420px;">
    <h3 style="color:var(--red);">Delete your account?</h3>
    <p class="subtitle" style="margin-bottom:16px;">This is permanent and cannot be undone.</p>
    <p style="font-size:13px;color:var(--tm);margin-bottom:20px;">
      Your account, all workspaces you created, and all their facts and history will be permanently deleted.
      Workspaces you share with others will remove you as a member only.
    </p>
    <div id="delete-account-error" style="display:none;color:var(--red);font-size:13px;margin-bottom:12px;"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end;">
      <button class="ws-rename-btn" onclick="closeDeleteAccountModal()">Cancel</button>
      <button onclick="confirmDeleteAccount()"
        style="padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;font-family:inherit;
               background:var(--red);color:#fff;border:none;cursor:pointer;">
        Delete my account
      </button>
    </div>
  </div>
</div>

<!-- ── CONNECT WORKSPACE MODAL ──────────────────────────────────── -->
<div class="modal-overlay" id="connect-modal">
  <div class="modal">
    <h3>Connect a Workspace</h3>
    <p class="subtitle">Enter your workspace ID and invite key to link it to your account.</p>
    <div class="field">
      <label>Workspace ID</label>
      <input id="connect-id" placeholder="ENG-XXXX-XXXX" autocomplete="off" spellcheck="false" />
    </div>
    <div class="field">
      <label>Invite Key</label>
      <input id="connect-key" placeholder="ek_live_…" type="password" autocomplete="off" spellcheck="false" />
    </div>
    <div class="auth-msg error" id="connect-error"></div>
    <div class="modal-actions">
      <button class="btn-sm btn-ghost" onclick="closeConnectModal()">Cancel</button>
      <button class="btn-sm btn-primary" onclick="connectWorkspace()">Connect</button>
    </div>
  </div>
</div>

<!-- ── CREATE WORKSPACE MODAL ───────────────────────────────────── -->
<div class="modal-overlay" id="create-modal">
  <div class="modal">
    <div id="create-step-pin">
      <h3>Create a workspace</h3>
      <p class="subtitle">Give your workspace a name, then set a PIN to protect your invite key.</p>
      <div class="field" style="margin-bottom:20px">
        <label style="font-size:13px;font-weight:600;color:var(--t2);display:block;margin-bottom:8px">Workspace name</label>
        <input id="create-ws-name" type="text" maxlength="80" placeholder="e.g. My Team's Workspace"
          autocomplete="off"
          style="width:100%;box-sizing:border-box;background:rgba(255,255,255,0.04);border:1px solid rgba(52,211,153,0.15);
                 border-radius:10px;color:var(--t1);font-size:15px;font-family:inherit;padding:10px 14px;outline:none;
                 transition:border-color 0.2s;" />
      </div>
      <p class="subtitle" style="margin-bottom:4px">Set a 4-digit PIN to protect your invite key</p>
      <div class="pin-row">
        <input class="pin-digit" id="cp0" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="cp1" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="cp2" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="cp3" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
      </div>
      <p class="subtitle" style="margin-top:0;margin-bottom:8px">Confirm PIN</p>
      <div class="pin-row">
        <input class="pin-digit" id="cp4" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="cp5" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="cp6" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="cp7" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
      </div>
      <div class="auth-msg error" id="create-error"></div>
      <div class="modal-actions">
        <button class="btn-sm btn-ghost" onclick="closeCreateModal()">Cancel</button>
        <button class="btn-sm btn-primary" id="create-btn" onclick="submitCreateWorkspace()">Create workspace</button>
      </div>
    </div>
    <div id="create-step-done" style="display:none">
      <h3>Workspace created</h3>
      <p class="subtitle">Your invite key is shown below. Copy it now — you can always retrieve it again with your PIN.</p>
      <div class="invite-key-box" id="create-invite-key-box"></div>
      <button class="copy-btn" onclick="copyCreatedKey()">Copy invite key</button>
      <p style="font-size:12px;color:var(--tm);margin-top:12px;line-height:1.6">
        Add this key to your MCP config under <code style="background:rgba(52,211,153,0.08);padding:1px 5px;border-radius:4px">"Authorization": "Bearer &lt;key&gt;"</code> — or paste it when prompted by your IDE.
      </p>
      <div class="modal-actions" style="margin-top:16px">
        <button class="btn-sm btn-primary" onclick="closeCreateModal()">Done</button>
      </div>
    </div>
  </div>
</div>

<!-- ── VIEW INVITE KEY MODAL ────────────────────────────────────── -->
<div class="modal-overlay" id="key-modal">
  <div class="modal">
    <div id="key-step-pin">
      <h3>View invite key</h3>
      <p class="subtitle" id="key-modal-subtitle">Enter your 4-digit PIN to reveal the invite key for <span id="key-modal-ws-id" style="color:var(--em4);font-family:'JetBrains Mono',monospace"></span>.</p>
      <div class="pin-row">
        <input class="pin-digit" id="kp0" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="kp1" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="kp2" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
        <input class="pin-digit" id="kp3" type="tel" maxlength="1" inputmode="numeric" pattern="[0-9]" />
      </div>
      <div class="auth-msg error" id="key-error"></div>
      <div class="modal-actions">
        <button class="btn-sm btn-ghost" onclick="closeKeyModal()">Cancel</button>
        <button class="btn-sm btn-primary" id="key-btn" onclick="submitRevealKey()">Reveal</button>
      </div>
    </div>
    <div id="key-step-done" style="display:none">
      <h3>Invite key</h3>
      <p class="subtitle">Share this key with teammates to give them access to the workspace.</p>
      <div class="invite-key-box" id="reveal-invite-key-box"></div>
      <button class="copy-btn" onclick="copyRevealedKey()">Copy invite key</button>
      <div class="modal-actions" style="margin-top:16px">
        <button class="btn-sm btn-ghost" onclick="closeKeyModal()">Close</button>
        <button class="btn-sm" onclick="showResetConfirm()"
          style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);color:#f87171;">
          Reset key
        </button>
      </div>
    </div>
    <div id="key-step-reset" style="display:none">
      <h3>Reset invite key?</h3>
      <p class="subtitle">This will permanently revoke the current key. Anyone using it will lose access immediately. A new key will be generated — you'll need to share it with your team.</p>
      <div class="auth-msg error" id="reset-key-error"></div>
      <div class="modal-actions" style="margin-top:20px">
        <button class="btn-sm btn-ghost" onclick="cancelResetKey()">Cancel</button>
        <button class="btn-sm" id="reset-key-btn" onclick="submitResetKey()"
          style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#f87171;font-weight:700;">
          Yes, reset key
        </button>
      </div>
    </div>
    <div id="key-step-reset-done" style="display:none">
      <h3>New invite key</h3>
      <p class="subtitle">The old key has been revoked. Share this new key with your team.</p>
      <div class="invite-key-box" id="new-invite-key-box"></div>
      <button class="copy-btn" onclick="copyNewKey()">Copy invite key</button>
      <div class="modal-actions" style="margin-top:16px">
        <button class="btn-sm btn-primary" onclick="closeKeyModal()">Done</button>
      </div>
    </div>
  </div>
</div>

<script>
// ── State ───────────────────────────────────────────────────────────
let SESSION = null;        // { user_id, email, workspaces }
let CURRENT_WS = null;     // { engram_id, ... }
let WS_DATA = null;        // { facts, conflicts, agents }
let BILLING = null;        // billing status
let cy = null;
let factFilter = 'all';
let authMode = 'login';

// ── Boot ────────────────────────────────────────────────────────────
async function boot() {
  // Check URL params for post-stripe-redirect
  const p = new URLSearchParams(window.location.search);
  const billingResult = p.get('billing');
  const wsId = p.get('id');
  // Clean URL
  if (billingResult || wsId) {
    window.history.replaceState({}, '', '/dashboard');
  }

  try {
    const r = await fetch('/auth/me', { credentials: 'include' });
    if (!r.ok) { showAuthScreen(); return; }
    SESSION = await r.json();
    updateHeader();
    showWsListScreen(SESSION.workspaces);

    // If returning from billing success, open that workspace's billing tab
    if (billingResult === 'success' && wsId) {
      const ws = SESSION.workspaces.find(w => w.engram_id === wsId);
      if (ws) { await openWorkspace(wsId, 'billing'); }
    }
  } catch(e) {
    showAuthScreen();
  }
}

function updateHeader() {
  if (!SESSION) return;
  document.getElementById('header-right').innerHTML = `
    <span class="user-email">${esc(SESSION.email)}</span>
    <button class="btn-sm btn-ghost" onclick="logout()">Sign out</button>
    <button class="btn-sm" onclick="openDeleteAccountModal()"
      style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);color:var(--red);">
      Delete account
    </button>
  `;
}

// ── Auth ────────────────────────────────────────────────────────────
function showAuthScreen() {
  document.getElementById('auth-screen').style.display = 'block';
  document.getElementById('ws-list-screen').style.display = 'none';
  document.getElementById('ws-detail-screen').style.display = 'none';
}

function switchAuthTab(mode) {
  authMode = mode;
  document.getElementById('tab-login').classList.toggle('active', mode === 'login');
  document.getElementById('tab-signup').classList.toggle('active', mode === 'signup');
  document.getElementById('auth-tab-slider').classList.toggle('right', mode === 'signup');
  const isLogin = mode === 'login';
  document.getElementById('auth-heading').textContent = isLogin ? 'Welcome back' : 'Create an account';
  document.getElementById('auth-subheading').textContent = isLogin ? 'Sign in to your Engram account' : 'Start sharing memory with your AI team';
  document.getElementById('auth-btn-label').textContent = isLogin ? 'Sign in' : 'Create account';
  document.getElementById('auth-switch-text').textContent = isLogin ? "Don't have an account?" : 'Already have an account?';
  document.getElementById('auth-switch-btn').textContent = isLogin ? 'Create one' : 'Sign in';
  document.getElementById('auth-error').style.display = 'none';
  document.getElementById('auth-success').style.display = 'none';
  // Reset password field autocomplete attribute
  document.getElementById('auth-password').autocomplete = isLogin ? 'current-password' : 'new-password';
}

function togglePassword() {
  const input = document.getElementById('auth-password');
  const isHidden = input.type === 'password';
  input.type = isHidden ? 'text' : 'password';
  const svg = document.getElementById('pw-eye');
  svg.innerHTML = isHidden
    ? '<path stroke-linecap="round" stroke-linejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>'
    : '<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>';
}

async function submitAuth() {
  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  const errEl = document.getElementById('auth-error');
  const btn = document.getElementById('auth-submit-btn');
  const spinner = document.getElementById('auth-spinner');
  const label = document.getElementById('auth-btn-label');
  errEl.style.display = 'none';
  btn.disabled = true;
  spinner.style.display = 'block';
  label.style.opacity = '0.6';

  const endpoint = authMode === 'login' ? '/auth/login' : '/auth/signup';
  try {
    const r = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    });
    const d = await r.json();
    if (!r.ok) {
      errEl.textContent = d.error || 'Authentication failed. Please try again.';
      errEl.style.display = 'block';
      return;
    }
    const meR = await fetch('/auth/me', { credentials: 'include' });
    SESSION = await meR.json();
    updateHeader();
    document.getElementById('auth-screen').style.display = 'none';
    showWsListScreen(SESSION.workspaces);
  } catch(e) {
    errEl.textContent = 'Connection error — please try again.';
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    spinner.style.display = 'none';
    label.style.opacity = '1';
  }
}

async function logout() {
  await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
  SESSION = null;
  document.getElementById('header-right').innerHTML = `<a href="/" class="btn-sm btn-ghost">← Home</a>`;
  showAuthScreen();
}

// ── Workspace list ──────────────────────────────────────────────────
function showWsListScreen(workspaces) {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('ws-list-screen').style.display = 'block';
  document.getElementById('ws-detail-screen').style.display = 'none';
  renderWsGrid(workspaces || []);
}

function renderWsGrid(workspaces) {
  const el = document.getElementById('ws-grid');
  if (!workspaces.length) {
    el.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
      No workspaces yet.<br>
      <span style="font-size:13px">Click <strong>+ New workspace</strong> to create one, or connect an existing workspace with an invite key.</span>
    </div>`;
    return;
  }
  el.innerHTML = workspaces.map(ws => {
    const isPaused = ws.paused;
    const plan = ws.plan || 'free';
    const wsId = esc(ws.engram_id);
    const wsName = ws.display_name ? esc(ws.display_name) : '';
    return `<div class="ws-card ${isPaused ? 'paused' : ''}">
      <button class="ws-delete-corner" title="Delete workspace"
        onclick="event.stopPropagation();openDeleteModal('${wsId}', '${wsName || wsId}')">
        <svg width="13" height="14" viewBox="0 0 13 14" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 3.5h11M4.5 3.5V2.5a1 1 0 011-1h2a1 1 0 011 1v1M5.5 6.5v4M7.5 6.5v4M2 3.5l.7 7.5a1 1 0 001 .9h5.6a1 1 0 001-.9L11 3.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div onclick="openWorkspace('${wsId}')" style="cursor:pointer">
        ${wsName
          ? `<div class="ws-name" style="padding-right:28px;">${wsName}</div><div class="ws-id">${wsId}</div>`
          : `<div class="ws-id-main" style="padding-right:28px;">${wsId}</div>`}
        <div class="ws-badges">
          <span class="badge ${isPaused ? 'badge-paused' : 'badge-active'}">${isPaused ? 'Paused' : 'Active'}</span>
          <span class="badge badge-${plan === 'pro' ? 'pro' : 'free'}">${plan}</span>
        </div>
      </div>
      <div class="ws-card-footer">
        <button class="ws-rename-btn" onclick="event.stopPropagation();openWorkspaceAndRename('${wsId}')">
          ${wsName ? 'Rename' : '+ Name this workspace'}
        </button>
        <button class="ws-key-btn" onclick="event.stopPropagation();openKeyModal('${wsId}')">View invite key</button>
      </div>
    </div>`;
  }).join('');
}

// ── Delete workspace modal ──────────────────────────────────────────
let _deleteWsId = null;
function openDeleteModal(wsId, wsLabel) {
  _deleteWsId = wsId;
  document.getElementById('delete-modal-subtitle').textContent =
    `Are you sure you want to delete "${wsLabel}"?`;
  document.getElementById('delete-modal-error').style.display = 'none';
  document.getElementById('delete-modal').classList.add('open');
}
function closeDeleteModal() {
  _deleteWsId = null;
  document.getElementById('delete-modal').classList.remove('open');
}
async function confirmDelete() {
  if (!_deleteWsId) return;
  const errEl = document.getElementById('delete-modal-error');
  errEl.style.display = 'none';
  try {
    const r = await fetch('/auth/leave-workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ engram_id: _deleteWsId }),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Delete failed.'; errEl.style.display = 'block'; return; }
    const deletedId = _deleteWsId;
    closeDeleteModal();
    SESSION.workspaces = (SESSION.workspaces || []).filter(w => w.engram_id !== deletedId);
    renderWsGrid(SESSION.workspaces);
  } catch(e) {
    errEl.textContent = 'Connection error — please try again.';
    errEl.style.display = 'block';
  }
}

// ── Delete account modal ────────────────────────────────────────────
function openDeleteAccountModal() {
  document.getElementById('delete-account-error').style.display = 'none';
  document.getElementById('delete-account-modal').classList.add('open');
}
function closeDeleteAccountModal() {
  document.getElementById('delete-account-modal').classList.remove('open');
}
async function confirmDeleteAccount() {
  const errEl = document.getElementById('delete-account-error');
  errEl.style.display = 'none';
  try {
    const r = await fetch('/auth/delete-account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Delete failed.'; errEl.style.display = 'block'; return; }
    SESSION = null;
    closeDeleteAccountModal();
    showAuthScreen();
  } catch(e) {
    errEl.textContent = 'Connection error — please try again.';
    errEl.style.display = 'block';
  }
}

// ── Connect workspace modal ─────────────────────────────────────────
function openConnectModal() {
  document.getElementById('connect-modal').classList.add('open');
}
function closeConnectModal() {
  document.getElementById('connect-modal').classList.remove('open');
  document.getElementById('connect-id').value = '';
  document.getElementById('connect-key').value = '';
  document.getElementById('connect-error').style.display = 'none';
}
async function connectWorkspace() {
  const engram_id = document.getElementById('connect-id').value.trim();
  const invite_key = document.getElementById('connect-key').value.trim();
  const errEl = document.getElementById('connect-error');
  errEl.style.display = 'none';
  try {
    const r = await fetch('/auth/connect-workspace', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ engram_id, invite_key }),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Failed'; errEl.style.display = 'block'; return; }
    closeConnectModal();
    // Refresh session
    const meR = await fetch('/auth/me', { credentials: 'include' });
    SESSION = await meR.json();
    showWsListScreen(SESSION.workspaces);
  } catch(e) {
    errEl.textContent = 'Connection error';
    errEl.style.display = 'block';
  }
}

// ── PIN digit helpers ───────────────────────────────────────────────
function wirePinDigits(ids) {
  ids.forEach((id, i) => {
    const el = document.getElementById(id);
    el.addEventListener('input', () => {
      el.value = el.value.replace(/\D/g, '').slice(0, 1);
      if (el.value && i < ids.length - 1) document.getElementById(ids[i + 1]).focus();
    });
    el.addEventListener('keydown', e => {
      if (e.key === 'Backspace' && !el.value && i > 0) document.getElementById(ids[i - 1]).focus();
    });
  });
}
function getPinValue(ids) {
  return ids.map(id => document.getElementById(id).value).join('');
}
function clearPinDigits(ids) {
  ids.map(id => document.getElementById(id)).forEach(el => { el.value = ''; });
}

// ── Create workspace modal ──────────────────────────────────────────
const CREATE_PIN_IDS = ['cp0','cp1','cp2','cp3'];
const CREATE_CONFIRM_IDS = ['cp4','cp5','cp6','cp7'];
let _createdInviteKey = null;

function openCreateModal() {
  clearPinDigits([...CREATE_PIN_IDS, ...CREATE_CONFIRM_IDS]);
  document.getElementById('create-error').style.display = 'none';
  document.getElementById('create-step-pin').style.display = 'block';
  document.getElementById('create-step-done').style.display = 'none';
  document.getElementById('create-modal').classList.add('open');
  wirePinDigits(CREATE_PIN_IDS);
  wirePinDigits(CREATE_CONFIRM_IDS);
  setTimeout(() => document.getElementById('create-ws-name').focus(), 50);
}
function closeCreateModal() {
  document.getElementById('create-modal').classList.remove('open');
  _createdInviteKey = null;
  clearPinDigits([...CREATE_PIN_IDS, ...CREATE_CONFIRM_IDS]);
  document.getElementById('create-ws-name').value = '';
}
async function submitCreateWorkspace() {
  const pin = getPinValue(CREATE_PIN_IDS);
  const confirm = getPinValue(CREATE_CONFIRM_IDS);
  const errEl = document.getElementById('create-error');
  errEl.style.display = 'none';
  if (pin.length !== 4) { errEl.textContent = 'Enter all 4 PIN digits'; errEl.style.display = 'block'; return; }
  if (pin !== confirm) { errEl.textContent = 'PINs do not match'; errEl.style.display = 'block'; return; }
  const btn = document.getElementById('create-btn');
  btn.disabled = true;
  btn.textContent = 'Creating…';
  try {
    const wsName = (document.getElementById('create-ws-name').value || '').trim();
    const r = await fetch('/auth/create-workspace', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ pin, display_name: wsName || undefined }),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Failed to create workspace'; errEl.style.display = 'block'; return; }
    _createdInviteKey = d.invite_key;
    document.getElementById('create-invite-key-box').textContent = d.invite_key;
    document.getElementById('create-step-pin').style.display = 'none';
    document.getElementById('create-step-done').style.display = 'block';
    // Refresh workspace list
    const meR = await fetch('/auth/me', { credentials: 'include' });
    SESSION = await meR.json();
    showWsListScreen(SESSION.workspaces);
  } catch(e) {
    errEl.textContent = 'Connection error'; errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create workspace';
  }
}
function copyCreatedKey() {
  if (_createdInviteKey) {
    navigator.clipboard.writeText(_createdInviteKey);
    _flashCopyBtn(event.target);
  }
}
function _flashCopyBtn(btn) {
  if (!btn) return;
  const orig = btn.textContent;
  btn.textContent = 'Copied!';
  btn.classList.add('copied');
  setTimeout(() => { btn.textContent = orig; btn.classList.remove('copied'); }, 2000);
}

// ── View invite key modal ───────────────────────────────────────────
const KEY_PIN_IDS = ['kp0','kp1','kp2','kp3'];
let _keyModalWsId = null;
let _revealedKey = null;

function openKeyModal(engram_id) {
  _keyModalWsId = engram_id;
  _revealedKey = null;
  clearPinDigits(KEY_PIN_IDS);
  document.getElementById('key-error').style.display = 'none';
  document.getElementById('key-modal-ws-id').textContent = engram_id;
  document.getElementById('key-step-pin').style.display = 'block';
  document.getElementById('key-step-done').style.display = 'none';
  document.getElementById('key-modal').classList.add('open');
  wirePinDigits(KEY_PIN_IDS);
  setTimeout(() => document.getElementById('kp0').focus(), 50);
}
function closeKeyModal() {
  document.getElementById('key-modal').classList.remove('open');
  _keyModalWsId = null; _revealedKey = null; _newKey = null;
  clearPinDigits(KEY_PIN_IDS);
  ['key-step-reset','key-step-reset-done'].forEach(id =>
    document.getElementById(id).style.display = 'none');
}
async function submitRevealKey() {
  const pin = getPinValue(KEY_PIN_IDS);
  const errEl = document.getElementById('key-error');
  errEl.style.display = 'none';
  if (pin.length !== 4) { errEl.textContent = 'Enter all 4 PIN digits'; errEl.style.display = 'block'; return; }
  const btn = document.getElementById('key-btn');
  btn.disabled = true;
  btn.textContent = 'Checking…';
  try {
    const r = await fetch('/auth/invite-key', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ engram_id: _keyModalWsId, pin }),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Incorrect PIN'; errEl.style.display = 'block'; return; }
    _revealedKey = d.invite_key;
    document.getElementById('reveal-invite-key-box').textContent = d.invite_key;
    document.getElementById('key-step-pin').style.display = 'none';
    document.getElementById('key-step-done').style.display = 'block';
  } catch(e) {
    errEl.textContent = 'Connection error'; errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Reveal';
  }
}
function copyRevealedKey() {
  if (_revealedKey) {
    navigator.clipboard.writeText(_revealedKey);
    _flashCopyBtn(event.target);
  }
}

let _newKey = null;
function showResetConfirm() {
  document.getElementById('key-step-done').style.display = 'none';
  document.getElementById('reset-key-error').style.display = 'none';
  document.getElementById('key-step-reset').style.display = 'block';
}
function cancelResetKey() {
  document.getElementById('key-step-reset').style.display = 'none';
  document.getElementById('key-step-done').style.display = 'block';
}
async function submitResetKey() {
  const btn = document.getElementById('reset-key-btn');
  const errEl = document.getElementById('reset-key-error');
  errEl.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Resetting…';
  try {
    const pin = getPinValue(KEY_PIN_IDS);
    const r = await fetch('/auth/reset-invite-key', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ engram_id: _keyModalWsId, pin }),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Reset failed'; errEl.style.display = 'block'; return; }
    _newKey = d.invite_key;
    document.getElementById('new-invite-key-box').textContent = d.invite_key;
    document.getElementById('key-step-reset').style.display = 'none';
    document.getElementById('key-step-reset-done').style.display = 'block';
  } catch(e) {
    errEl.textContent = 'Connection error'; errEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Yes, reset key';
  }
}
function copyNewKey() {
  if (_newKey) { navigator.clipboard.writeText(_newKey); _flashCopyBtn(event.target); }
}

// ── Open workspace detail ───────────────────────────────────────────
async function openWorkspace(engram_id, initialTab) {
  CURRENT_WS = (SESSION.workspaces || []).find(w => w.engram_id === engram_id);
  document.getElementById('ws-list-screen').style.display = 'none';
  document.getElementById('ws-detail-screen').style.display = 'block';
  document.getElementById('detail-ws-id').textContent = engram_id;
  document.getElementById('detail-ws-name').textContent = CURRENT_WS?.display_name || engram_id;
  cancelRename();

  const plan = CURRENT_WS?.plan || 'free';
  const isPaused = CURRENT_WS?.paused || false;
  document.getElementById('detail-plan-badge').className = `badge ${plan === 'pro' ? 'badge-pro' : 'badge-free'}`;
  document.getElementById('detail-plan-badge').textContent = plan;
  document.getElementById('detail-status-badge').className = `badge ${isPaused ? 'badge-paused' : 'badge-active'}`;
  document.getElementById('detail-status-badge').textContent = isPaused ? 'Paused' : 'Active';
  document.getElementById('paused-banner').style.display = isPaused ? 'flex' : 'none';

  await loadWorkspaceData(engram_id);

  if (initialTab) {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    const idx = ['conflicts','facts','billing'].indexOf(initialTab);
    if (idx >= 0 && tabBtns[idx]) tabBtns[idx].classList.add('active');
    const panelEl = document.getElementById('panel-' + initialTab);
    if (panelEl) panelEl.classList.add('active');
    if (initialTab === 'billing') await loadBilling(engram_id);
  }
}

async function openWorkspaceAndRename(engram_id) {
  await openWorkspace(engram_id);
  startRename();
}

// ── Rename workspace ────────────────────────────────────────────────
function startRename() {
  const current = CURRENT_WS?.display_name || '';
  document.getElementById('rename-input').value = current;
  document.getElementById('rename-form').classList.add('visible');
  document.getElementById('rename-btn').style.display = 'none';
  document.getElementById('rename-error').style.display = 'none';
  document.getElementById('rename-input').focus();
}

function cancelRename() {
  document.getElementById('rename-form').classList.remove('visible');
  document.getElementById('rename-btn').style.display = '';
  document.getElementById('rename-error').style.display = 'none';
}

async function saveRename() {
  const newName = document.getElementById('rename-input').value.trim();
  const errEl = document.getElementById('rename-error');
  if (!newName) { errEl.textContent = 'Name cannot be empty.'; errEl.style.display = 'block'; return; }
  try {
    const r = await fetch('/auth/rename-workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ engram_id: CURRENT_WS.engram_id, display_name: newName }),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Rename failed.'; errEl.style.display = 'block'; return; }
    // Update local state and UI
    CURRENT_WS.display_name = newName;
    const ws = (SESSION.workspaces || []).find(w => w.engram_id === CURRENT_WS.engram_id);
    if (ws) ws.display_name = newName;
    document.getElementById('detail-ws-name').textContent = newName;
    cancelRename();
    renderWsGrid(SESSION.workspaces || []);
  } catch(e) {
    errEl.textContent = 'Connection error — please try again.';
    errEl.style.display = 'block';
  }
}

async function loadWorkspaceData(engram_id) {
  // Fetch workspace data — we use a session-authenticated endpoint
  // The workspace/search endpoint needs invite_key; we use billing/status which uses session cookie
  try {
    const r = await fetch(`/workspace/session?engram_id=${encodeURIComponent(engram_id)}`, {
      credentials: 'include',
    });
    if (r.ok) {
      WS_DATA = await r.json();
      renderDetail();
      return;
    }
  } catch(e) {}
  // If session endpoint not available, show connect prompt with invite key input
  showInviteKeyPrompt(engram_id);
}

function showInviteKeyPrompt(engram_id) {
  // Workspace not yet linked to this account — show a clear connect prompt
  document.getElementById('stats-row').innerHTML = '';
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.remove('active');
    p.innerHTML = '';
  });
  document.querySelector('.tabs').style.display = 'none';
  document.getElementById('panel-conflicts').innerHTML = `
    <div style="padding:64px 0;text-align:center;color:var(--t2)">
      <div style="font-size:18px;font-weight:700;color:var(--t1);margin-bottom:10px">
        Connect this workspace to your account
      </div>
      <div style="font-size:14px;max-width:420px;margin:0 auto 28px;line-height:1.7">
        To view workspace memories, link it using your invite key.
        You only need to do this once per workspace.
      </div>
      <div style="display:flex;gap:10px;max-width:500px;margin:0 auto">
        <input id="quick-key" placeholder="ek_live_…" type="password"
          style="flex:1;padding:12px 16px;background:rgba(0,0,0,0.3);border:1px solid var(--border);
          border-radius:11px;font-size:14px;font-family:inherit;color:var(--t1);" />
        <button class="btn-sm btn-primary" style="padding:12px 22px" onclick="loadWithKey('${esc(engram_id)}')">Connect</button>
      </div>
      <div id="quick-key-err" style="color:var(--red);font-size:13px;margin-top:12px;display:none"></div>
    </div>`;
  document.getElementById('panel-conflicts').classList.add('active');
}

async function loadWithKey(engram_id) {
  const key = document.getElementById('quick-key').value.trim();
  const errEl = document.getElementById('quick-key-err');
  errEl.style.display = 'none';
  try {
    // First link the workspace to the account via the connect endpoint
    const linkR = await fetch('/auth/connect-workspace', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ engram_id, invite_key: key }),
    });
    if (!linkR.ok) {
      // Fallback: key might already be linked — try direct search
      const d = await linkR.json();
      if (!d.error?.includes('already')) {
        errEl.textContent = d.error || 'Invalid invite key';
        errEl.style.display = 'block';
        return;
      }
    }
    // Now fetch via session (workspace is now linked)
    const r = await fetch('/workspace/search', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ engram_id, invite_key: key }),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.error || 'Failed'; errEl.style.display = 'block'; return; }
    WS_DATA = d;
    // Restore tabs and render
    document.querySelector('.tabs').style.display = '';
    document.querySelectorAll('.tab-panel').forEach((p,i) => {
      p.innerHTML = '';
      p.classList.remove('active');
    });
    // Rebuild panel content (was cleared by showInviteKeyPrompt)
    document.getElementById('panel-conflicts').innerHTML = '<div class="conflict-list" id="conflict-list"></div>';
    document.getElementById('panel-facts').innerHTML = `
      <div class="facts-toolbar">
        <input class="facts-search" id="facts-search" placeholder="Search facts…" oninput="filterFacts()" />
        <button class="filter-btn active" onclick="setFactFilter('all', this)">All</button>
        <button class="filter-btn" onclick="setFactFilter('active', this)">Active</button>
        <button class="filter-btn" onclick="setFactFilter('retired', this)">Retired</button>
      </div>
      <div class="fact-table">
        <div class="fact-row fact-row-header"><div>Content</div><div>Scope</div><div>Type</div><div>Date</div></div>
        <div id="facts-list"></div>
      </div>`;
    document.getElementById('panel-billing').innerHTML = '<div class="billing-section" id="billing-section"></div>';
    document.getElementById('panel-conflicts').classList.add('active');
    // Refresh session workspaces so the list shows the newly linked workspace
    const meR = await fetch('/auth/me', { credentials: 'include' });
    if (meR.ok) SESSION = await meR.json();
    renderDetail();
  } catch(e) {
    errEl.textContent = 'Connection error';
    errEl.style.display = 'block';
  }
}

function goBackToList() {
  WS_DATA = null; CURRENT_WS = null; BILLING = null; cy = null;
  document.getElementById('ws-detail-screen').style.display = 'none';
  showWsListScreen(SESSION.workspaces);
}

// ── Detail render ───────────────────────────────────────────────────
function renderDetail() {
  if (!WS_DATA) return;
  const { facts, conflicts, agents } = WS_DATA;
  // Deduplicate by fact pair before counting, same as renderConflicts.
  const pairSeen = new Set();
  const openC = (conflicts||[]).filter(c => {
    if (c.status !== 'open') return false;
    const key = [c.fact_a_id, c.fact_b_id].sort().join('|');
    if (pairSeen.has(key)) return false;
    pairSeen.add(key);
    return true;
  }).length;

  if (openC > 0) {
    document.getElementById('stats-row').innerHTML = `
      <div class="conflict-indicator">
        <span class="conflict-count" data-target="${openC}">0</span>
        <span class="conflict-label">open confusion${openC !== 1 ? 's' : ''}</span>
      </div>`;
    // Animate counter
    const el = document.querySelector('.conflict-count[data-target]');
    if (el) {
      const target = parseInt(el.dataset.target);
      const duration = 600;
      const start = performance.now();
      function tick(now) {
        const p = Math.min((now - start) / duration, 1);
        const ease = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(target * ease);
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }
  } else {
    document.getElementById('stats-row').innerHTML = '';
  }

  const badge = document.getElementById('conflict-badge');
  badge.textContent = openC > 0 ? '(' + openC + ')' : '';

  renderConflicts();
  renderFacts();
}

// ── Graph ───────────────────────────────────────────────────────────
let _cyScript = null;
function _loadCytoscape() {
  if (typeof cytoscape !== 'undefined') return Promise.resolve();
  if (_cyScript) return _cyScript;
  _cyScript = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.29.2/cytoscape.min.js';
    s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
  return _cyScript;
}

// Ambient floating particles behind the graph
function initParticles() {
  const canvas = document.getElementById('graph-particles');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let w, h, particles = [];
  function resize() {
    const r = canvas.parentElement.getBoundingClientRect();
    w = canvas.width = r.width; h = canvas.height = r.height;
  }
  resize(); window.addEventListener('resize', resize);
  for (let i = 0; i < 35; i++) {
    particles.push({
      x: Math.random()*w, y: Math.random()*h,
      vx: (Math.random()-0.5)*0.2, vy: (Math.random()-0.5)*0.2,
      r: Math.random()*1.2+0.3, a: Math.random()*0.2+0.05,
      hue: [153,180,200][Math.floor(Math.random()*3)]
    });
  }
  function draw() {
    ctx.clearRect(0,0,w,h);
    particles.forEach(p => {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0) p.x = w; if (p.x > w) p.x = 0;
      if (p.y < 0) p.y = h; if (p.y > h) p.y = 0;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI*2);
      ctx.fillStyle = `hsla(${p.hue},60%,65%,${p.a})`;
      ctx.fill();
    });
    // Draw faint connections between nearby particles
    for (let i = 0; i < particles.length; i++) {
      for (let j = i+1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx*dx + dy*dy);
        if (dist < 80) {
          ctx.beginPath(); ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(52,211,153,${0.04*(1-dist/80)})`;
          ctx.lineWidth = 0.5; ctx.stroke();
        }
      }
    }
    requestAnimationFrame(draw);
  }
  draw();
}

async function renderGraph() {
  if (!WS_DATA) return;
  await _loadCytoscape();
  initParticles();
  const { facts, conflicts } = WS_DATA;
  const els = [], sc = {};
  const PAL = ['#34d399','#22d3ee','#a78bfa','#f472b6','#fbbf24','#4ade80','#60a5fa','#2dd4bf'];
  let pi = 0;
  const sColor = s => { if (!sc[s]) sc[s] = PAL[pi++ % PAL.length]; return sc[s]; };

  // Lighten a hex color by mixing toward white — used for the star gradient centre
  function starCore(hex) {
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    const mix = 0.72;
    const lr = Math.round(r+(255-r)*mix), lg = Math.round(g+(255-g)*mix), lb = Math.round(b+(255-b)*mix);
    return '#'+[lr,lg,lb].map(v=>v.toString(16).padStart(2,'0')).join('');
  }

  (facts||[]).forEach(f => {
    const ret = !!f.valid_until;
    const col = ret ? '#64748b' : sColor(f.scope||'general');
    els.push({data:{id:f.id, label:'', content:f.content, scope:f.scope,
      fact_type:f.fact_type, committed_at:f.committed_at, durability:f.durability, retired:ret,
      color: col, coreColor: ret ? '#94a3b8' : starCore(col),
      size: ret ? 16 : Math.max(20, (f.confidence||0.9)*32+12)}});
  });

  // Same-scope edges — pull related facts together into clusters
  const byScope = {};
  (facts||[]).filter(f=>!f.valid_until).forEach(f => {
    const s = f.scope||'general';
    (byScope[s] = byScope[s]||[]).push(f.id);
  });
  const edgeSet = new Set();
  Object.entries(byScope).forEach(([s, ids]) => {
    // Fully connect groups ≤ 6, star-connect larger ones
    if (ids.length <= 6) {
      for (let i=0; i<ids.length; i++)
        for (let j=i+1; j<ids.length; j++) {
          const k = ids[i]+'|'+ids[j];
          if (!edgeSet.has(k)) { edgeSet.add(k); els.push({data:{id:'s-'+k, source:ids[i], target:ids[j], kind:'scope', color: sColor(s)}}); }
        }
    } else {
      // Star: connect everything to the first node
      for (let i=1; i<ids.length; i++) {
        const k = ids[0]+'|'+ids[i];
        if (!edgeSet.has(k)) { edgeSet.add(k); els.push({data:{id:'s-'+k, source:ids[0], target:ids[i], kind:'scope', color: sColor(s)}}); }
      }
    }
  });

  (facts||[]).filter(f=>f.supersedes_fact_id).forEach(f => {
    els.push({data:{id:'l-'+f.id, source:f.supersedes_fact_id, target:f.id, kind:'lineage'}});
  });
  (conflicts||[]).filter(c=>c.status==='open').forEach(c => {
    els.push({data:{id:'c-'+c.id, source:c.fact_a_id, target:c.fact_b_id, kind:'conflict'}});
  });

  if (cy) cy.destroy();
  cy = cytoscape({
    container: document.getElementById('cy'), elements: els,
    style: [
      {selector:'node', style:{
        'background-fill': 'radial-gradient',
        'background-gradient-stop-colors': 'data(coreColor) data(color)',
        'background-gradient-stop-positions': '20% 100%',
        'background-opacity': 1,
        'label': '',
        'width':'data(size)',
        'height':'data(size)',
        'border-width': 0,
        'overlay-opacity': 0,
        'shadow-blur': 28,
        'shadow-color':'data(color)',
        'shadow-opacity': 0.75,
        'shadow-offset-x': 0,
        'shadow-offset-y': 0,
        'transition-property': 'shadow-opacity, shadow-blur, width, height, opacity',
        'transition-duration': '0.35s',
      }},
      {selector:'node:active', style:{'overlay-opacity': 0}},
      {selector:'node[retired = true]', style:{
        'opacity': 0.28,
        'shadow-opacity': 0.08,
      }},
      {selector:'edge[kind="scope"]', style:{
        'line-color':'data(color)',
        'curve-style':'bezier',
        'width': 1,
        'opacity': 0.28,
        'line-style': 'solid',
        'overlay-opacity': 0,
        'transition-property': 'opacity',
        'transition-duration': '0.3s',
      }},
      {selector:'edge[kind="lineage"]', style:{
        'line-color':'#a78bfa',
        'target-arrow-color':'#a78bfa',
        'target-arrow-shape':'triangle',
        'curve-style':'bezier',
        'width': 1.5,
        'opacity': 0.5,
        'line-style':'dotted',
        'transition-property': 'opacity',
        'transition-duration': '0.3s',
      }},
      {selector:'edge[kind="conflict"]', style:{
        'line-color':'#f87171',
        'line-style':'solid',
        'width': 1.8,
        'opacity': 0.65,
        'curve-style':'bezier',
        'transition-property': 'opacity',
        'transition-duration': '0.3s',
      }},
      {selector:':selected', style:{
        'shadow-blur': 48,
        'shadow-opacity': 1,
        'width': 'mapData(size, 16, 52, 26, 62)',
        'height': 'mapData(size, 16, 52, 26, 62)',
      }},
      {selector:'node.hover-neighbor', style:{
        'shadow-blur': 36,
        'shadow-opacity': 0.9,
      }},
      {selector:'node.dimmed', style:{'opacity':0.07}},
      {selector:'edge.dimmed', style:{'opacity':0.03}},
      {selector:'edge.hover-edge', style:{'opacity':0.7, 'width':1.8}},
    ],
    layout:{
      name: (facts||[]).length < 60 ? 'cose' : 'random',
      animate: true,
      animationDuration: 900,
      animationEasing: 'ease-out-cubic',
      randomize: false,
      nodeRepulsion: 8500,
      idealEdgeLength: e => e.data('kind') === 'scope' ? 65 : 150,
      edgeElasticity: e => e.data('kind') === 'scope' ? 0.55 : 0.25,
      padding: 36,
      nodeOverlap: 16,
      gravity: 0.25,
    },
    wheelSensitivity: 0.3,
    minZoom: 0.3,
    maxZoom: 3,
  });

  // Hover glow effect
  cy.on('mouseover','node', e => {
    const n = e.target;
    n.style({'shadow-blur':52, 'shadow-opacity':1});
    n.neighborhood('node').addClass('hover-neighbor');
    n.connectedEdges().addClass('hover-edge');
    cy.elements().not(n).not(n.neighborhood()).not(n.connectedEdges()).addClass('dimmed');
  });
  cy.on('mouseout','node', e => {
    const n = e.target;
    n.style({'shadow-blur':28, 'shadow-opacity':0.75});
    cy.elements().removeClass('hover-neighbor').removeClass('dimmed').removeClass('hover-edge');
  });

  // Click detail panel
  cy.on('tap','node', e => {
    const d = e.target.data();
    document.getElementById('nd-scope').textContent = (d.scope||'general')+' · '+(d.fact_type||'observation');
    document.getElementById('nd-content').textContent = d.content||'';
    const ts = d.committed_at ? new Date(d.committed_at).toLocaleString() : '';
    document.getElementById('nd-meta').textContent = (d.retired?'⊘ Retired':'● Active')+' · '+(d.durability||'durable')+' · '+ts;
    const panel = document.getElementById('node-detail');
    panel.style.display = 'block';
    panel.style.animation = 'none';
    panel.offsetHeight; // reflow
    panel.style.animation = 'slideDetail 0.3s ease';
  });
  cy.on('tap', e => { if(e.target===cy) document.getElementById('node-detail').style.display='none'; });

  // Star shimmer — gently pulse shadow opacity to simulate twinkling
  let breathPhase = 0;
  function breathe() {
    breathPhase += 0.018;
    cy.nodes('[retired != true]').forEach((n, i) => {
      const glow = 0.6 + Math.sin(breathPhase + i * 0.55) * 0.18;
      const blur = 24 + Math.sin(breathPhase + i * 0.55) * 6;
      n.style({'shadow-opacity': glow, 'shadow-blur': blur});
    });
    requestAnimationFrame(breathe);
  }
  breathe();
}

function filterGraph(q) {
  if (!cy) return;
  q = q.toLowerCase();
  if (!q) {
    cy.elements().removeClass('dimmed');
    cy.nodes().style('opacity', n => n.data('retired') ? 0.25 : 0.85);
    cy.edges().style('opacity', e => e.data('kind')==='conflict' ? 0.6 : 0.35);
    return;
  }
  cy.nodes().forEach(n => {
    const m = (n.data('content')||'').toLowerCase().includes(q)||(n.data('scope')||'').toLowerCase().includes(q);
    if (m) {
      n.removeClass('dimmed');
      n.style({'opacity':1, 'border-color':'rgba(52,211,153,0.4)', 'border-width':2.5});
    } else {
      n.addClass('dimmed');
    }
  });
  cy.edges().addClass('dimmed');
}

// ── Conflicts ───────────────────────────────────────────────────────
function renderConflicts() {
  if (!WS_DATA) return;
  const { conflicts, facts } = WS_DATA;
  const el = document.getElementById('conflict-list');

  // Deduplicate by fact pair — keep one per (fact_a_id, fact_b_id), preferring open over resolved.
  const pairMap = new Map();
  for (const c of conflicts) {
    const key = [c.fact_a_id, c.fact_b_id].sort().join('|');
    const existing = pairMap.get(key);
    if (!existing || (c.status === 'open' && existing.status !== 'open')) {
      pairMap.set(key, c);
    }
  }
  const deduped = [...pairMap.values()];
  const openConflicts = deduped.filter(c => c.status === 'open');

  if (!openConflicts.length) { el.innerHTML = '<div class="empty-state">No confusions detected — your agents are aligned.</div>'; return; }
  const factMap = {};
  (facts||[]).forEach(f => factMap[f.id] = f);
  const sorted = [...openConflicts].sort((a,b) => new Date(b.detected_at) - new Date(a.detected_at));
  el.innerHTML = sorted.map(c => {
    const fa = factMap[c.fact_a_id], fb = factMap[c.fact_b_id];
    const isOpen = c.status === 'open';
    const ts = c.detected_at ? new Date(c.detected_at).toLocaleString() : '';
    const faContent = fa ? fa.content : (c.fact_a_content || 'Fact not found');
    const fbContent = fb ? fb.content : (c.fact_b_content || 'Fact not found');
    const faScope = fa ? fa.scope : (c.fact_a_scope || '?');
    const fbScope = fb ? fb.scope : (c.fact_b_scope || '?');
    const faTime = fa && fa.committed_at ? new Date(fa.committed_at).toLocaleString() : '';
    const fbTime = fb && fb.committed_at ? new Date(fb.committed_at).toLocaleString() : '';
    return `<div class="conflict-card${isOpen ? '' : ' resolved'}">
      <div class="conflict-question">${c.explanation ? esc(c.explanation) : 'Conflicting information detected'}</div>
      ${isOpen ? `<div class="conflict-actions">
        <button class="btn-yes" onclick="resolveConflict('${c.id}','keep_a')">Keep fact A</button>
        <button class="btn-yes" onclick="resolveConflict('${c.id}','keep_b')" style="background:rgba(96,165,250,0.1);border-color:rgba(96,165,250,0.2);color:#60a5fa;">Keep fact B</button>
        <button class="btn-no" onclick="resolveConflict('${c.id}','dismiss')">Dismiss</button>
      </div>` : `<div class="conflict-resolved-note">Resolved · ${c.resolution_type || 'dismissed'}</div>`}
      <details class="conflict-details">
        <summary>View details</summary>
        <div class="conflict-facts">
          <div class="conflict-fact"><div class="conflict-fact-label">Fact A · ${esc(faScope)}${faTime ? ' · ' + faTime : ''}</div>${esc(faContent)}</div>
          <div class="conflict-fact"><div class="conflict-fact-label">Fact B · ${esc(fbScope)}${fbTime ? ' · ' + fbTime : ''}</div>${esc(fbContent)}</div>
        </div>
        <div class="conflict-date">Detected ${ts}</div>
      </details>
    </div>`;
  }).join('');
}

async function resolveConflict(conflictId, answer) {
  if (!CURRENT_WS) return;
  let resolution_type, resolution, winning_claim_id;
  if (answer === 'keep_a') {
    resolution_type = 'winner';
    resolution = 'Fact A kept as correct via dashboard';
    const c = WS_DATA && WS_DATA.conflicts.find(x => x.id === conflictId);
    winning_claim_id = c ? c.fact_a_id : undefined;
  } else if (answer === 'keep_b') {
    resolution_type = 'winner';
    resolution = 'Fact B kept as correct via dashboard';
    const c = WS_DATA && WS_DATA.conflicts.find(x => x.id === conflictId);
    winning_claim_id = c ? c.fact_b_id : undefined;
  } else {
    resolution_type = 'dismissed';
    resolution = 'Dismissed as false positive via dashboard';
  }
  try {
    const args = { conflict_id: conflictId, resolution_type, resolution };
    if (winning_claim_id) args.winning_claim_id = winning_claim_id;
    await fetch('/mcp', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        jsonrpc: '2.0', id: Date.now(), method: 'tools/call',
        params: { name: 'engram_resolve', arguments: args }
      })
    });
    // Mark all conflicts with the same fact pair as resolved locally.
    if (WS_DATA) {
      const resolved = WS_DATA.conflicts.find(x => x.id === conflictId);
      if (resolved) {
        const pairKey = [resolved.fact_a_id, resolved.fact_b_id].sort().join('|');
        if (resolution_type === 'dismissed') {
          WS_DATA.conflicts = WS_DATA.conflicts.filter(x => {
            const k = [x.fact_a_id, x.fact_b_id].sort().join('|');
            return k !== pairKey;
          });
        } else {
          WS_DATA.conflicts.forEach(x => {
            const k = [x.fact_a_id, x.fact_b_id].sort().join('|');
            if (k === pairKey) { x.status = 'resolved'; x.resolution_type = resolution_type; }
          });
        }
      }
    }
    renderConflicts();
    renderDetail();
  } catch(e) { console.error('Resolve failed:', e); }
}

// ── Facts ────────────────────────────────────────────────────────────
function renderFacts() {
  if (!WS_DATA) return;
  const el = document.getElementById('facts-list');
  const q = (document.getElementById('facts-search').value||'').toLowerCase();
  let list = WS_DATA.facts || [];
  if (factFilter === 'active') list = list.filter(f => !f.valid_until);
  if (factFilter === 'retired') list = list.filter(f => f.valid_until);
  if (q) list = list.filter(f => (f.content||'').toLowerCase().includes(q)||(f.scope||'').toLowerCase().includes(q));
  if (!list.length) { el.innerHTML = '<div class="empty-state" style="padding:40px">No facts found</div>'; return; }
  el.innerHTML = list.map(f => {
    const ret = f.valid_until ? ' fact-retired' : '';
    const dt = f.committed_at ? new Date(f.committed_at).toLocaleString() : '';
    return `<div class="fact-row${ret}">
      <div class="fact-content">${esc(f.content)}</div>
      <div><span class="fact-scope">${esc(f.scope||'general')}</span></div>
      <div class="fact-type">${f.fact_type||'obs'}</div>
      <div class="fact-date">${dt}</div>
    </div>`;
  }).join('');
}

function filterFacts() { renderFacts(); }
function setFactFilter(f, btn) {
  factFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderFacts();
}

// ── Agents ───────────────────────────────────────────────────────────
function renderAgents() {
  if (!WS_DATA) return;
  const el = document.getElementById('agents-grid');
  if (!WS_DATA.agents.length) { el.innerHTML = '<div class="empty-state">No agents registered</div>'; return; }
  el.innerHTML = WS_DATA.agents.map(a => {
    const seen = a.last_seen ? new Date(a.last_seen).toLocaleDateString() : 'never';
    return `<div class="agent-card">
      <div class="agent-id">${esc(a.agent_id)}</div>
      <div class="agent-engineer">${a.engineer ? esc(a.engineer) : 'Anonymous'}</div>
      <div class="agent-stats">
        <div><div class="agent-stat-val">${a.total_commits||0}</div><div class="agent-stat-label">Commits</div></div>
        <div><div class="agent-stat-val" style="font-size:14px;">${seen}</div><div class="agent-stat-label">Last seen</div></div>
      </div>
    </div>`;
  }).join('');
}

// ── Billing ──────────────────────────────────────────────────────────
async function loadBilling(engram_id) {
  const el = document.getElementById('billing-section');
  el.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const r = await fetch(`/billing/status?engram_id=${encodeURIComponent(engram_id)}`, { credentials: 'include' });
    if (!r.ok) { el.innerHTML = '<div class="empty-state">Could not load billing info</div>'; return; }
    BILLING = await r.json();
    renderBilling(BILLING);
  } catch(e) {
    el.innerHTML = '<div class="empty-state">Could not load billing info</div>';
  }
}

function renderBilling(b) {
  const el = document.getElementById('billing-section');
  const plan = b.plan || 'free';
  const planName = b.plan_name || 'Free';
  const used = b.commits_this_month || 0;
  const limit = b.commit_limit || 500;
  const pct = Math.min(100, used / limit * 100);
  const fillClass = pct >= 100 ? 'over' : pct >= 80 ? 'near' : '';
  const isPaused = b.paused;
  const hasSubscription = b.has_subscription;
  const badgeClass = `plan-badge plan-badge-${plan}`;

  const planDefs = [
    { key:'free',    name:'Free',    price:'$0',  hours:'1 hr/day',  desc:'On-demand scanning'              },
    { key:'builder', name:'Builder', price:'$12', hours:'4 hrs/day', desc:'Nightly scan + morning briefing' },
    { key:'team',    name:'Team',    price:'$39', hours:'8 hrs/day', desc:'Real-time file watching'         },
    { key:'scale',   name:'Scale',   price:'$99', hours:'24 hrs/day',desc:'Always-on, org-wide'             },
  ];

  el.innerHTML = `
    <div class="billing-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <h3 style="margin:0">Commit Usage</h3>
        <span class="${badgeClass}">${planName}</span>
      </div>
      <div class="usage-numbers">
        <span><strong style="color:var(--t1)">${used.toLocaleString()}</strong> commits used this month</span>
        <span>${limit.toLocaleString()} limit</span>
      </div>
      <div class="usage-bar-lg"><div class="usage-fill-lg ${fillClass}" style="width:${pct.toFixed(1)}%"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--tm)">
        <span>${pct.toFixed(1)}% of monthly limit</span>
        <span>LLM suggestions: <strong style="color:var(--em4)">included</strong></span>
      </div>
      ${isPaused ? `<div style="margin-top:14px;padding:12px 14px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.15);border-radius:8px;color:var(--red);font-size:13px">
        Workspace paused — limit reached or payment issue. Upgrade or check billing below.
      </div>` : ''}
    </div>

    <div class="billing-card">
      <h3>Plans</h3>
      <div class="plan-grid">
        ${planDefs.map(p => {
          const isDisabled = p.key !== 'free' && p.key !== plan;
          return `
          <div class="plan-card ${p.key === plan ? 'plan-card-current' : ''}" style="${isDisabled ? 'opacity:0.45;pointer-events:none;filter:grayscale(0.4)' : ''}">
            <div class="plan-card-name">${p.name}</div>
            <div class="plan-card-price">${p.price}<span>/mo</span></div>
            <div class="plan-card-commits">${p.hours} active</div>
            <div class="plan-card-feature yes">✓ ${p.desc}</div>
            <div class="plan-card-feature yes">✓ Conflict detection</div>
            ${p.key === plan
              ? '<div class="plan-card-label">Current plan</div>'
              : p.key !== 'free'
                ? `<button class="btn-sm btn-primary plan-upgrade-btn" disabled style="opacity:0.5;cursor:not-allowed">Upgrade</button>`
                : '<div class="plan-card-feature no" style="margin-top:auto;padding-top:8px">—</div>'}
          </div>`;
        }).join('')}
      </div>
      <p class="pricing-note" style="margin-top:14px;padding:10px 14px;background:rgba(251,191,36,0.06);border:1px solid rgba(251,191,36,0.15);border-radius:8px;color:rgba(251,191,36,0.8)">
        ⏸ Paid plans are coming soon — upgrades are temporarily disabled while we finish testing.
      </p>
    </div>

    ${hasSubscription ? `
    <div class="billing-card" style="padding:16px 24px">
      <button class="btn-sm btn-ghost" onclick="openPortal()">Manage subscription in Stripe portal →</button>
    </div>` : ''}`;
}

async function startCheckout(plan) {
  if (!CURRENT_WS) return;
  try {
    const r = await fetch('/billing/checkout', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ engram_id: CURRENT_WS.engram_id, plan: plan || 'builder' }),
    });
    const d = await r.json();
    if (!r.ok) { alert(d.error || 'Checkout failed'); return; }
    window.location.href = d.checkout_url;
  } catch(e) { alert('Connection error'); }
}

async function openPortal() {
  if (!CURRENT_WS) return;
  try {
    const r = await fetch(`/billing/portal?engram_id=${encodeURIComponent(CURRENT_WS.engram_id)}`, { credentials: 'include' });
    const d = await r.json();
    if (!r.ok) { alert(d.error || 'Portal error'); return; }
    window.open(d.portal_url, '_blank');
  } catch(e) { alert('Connection error'); }
}

// ── Tabs ─────────────────────────────────────────────────────────────
function switchTab(name, event) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  if (event && event.target) event.target.classList.add('active');
  const panel = document.getElementById('panel-' + name);
  if (panel) panel.classList.add('active');
  if (name === 'billing' && CURRENT_WS && !BILLING) loadBilling(CURRENT_WS.engram_id);
}

function esc(s) { const d = document.createElement('div'); d.textContent = String(s||''); return d.innerHTML; }

// ── Enter key / boot ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  ['auth-email','auth-password'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if(e.key==='Enter') submitAuth(); });
  });
  ['connect-id','connect-key'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if(e.key==='Enter') connectWorkspace(); });
  });
  document.getElementById('connect-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('connect-modal')) closeConnectModal();
  });
  document.getElementById('create-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('create-modal')) closeCreateModal();
  });
  document.getElementById('key-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('key-modal')) closeKeyModal();
  });
  boot();
});
</script>
</body>
</html>"""


async def dashboard(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_dashboard())


app = Starlette(routes=[Route("/{path:path}", dashboard, methods=["GET"])])
