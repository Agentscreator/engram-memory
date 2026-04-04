"""Vercel ASGI entrypoint — serves the landing page only.

Self-contained — no dependency on the engram package — so
Vercel only needs starlette in requirements.txt.
"""

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
  <title>Engram — Shared Memory for AI Agents</title>
  <meta name="description" content="Give your AI agents shared, persistent memory that detects contradictions. Open source. Apache 2.0.">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
      line-height: 1.6;
      color: #1a1a1a;
      background: #ffffff;
    }
    
    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 24px;
    }
    
    /* Header */
    header {
      padding: 20px 0;
      border-bottom: 1px solid #e5e5e5;
    }
    
    .header-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    
    .logo {
      font-size: 24px;
      font-weight: 700;
      color: #059669;
      text-decoration: none;
    }
    
    .nav-links {
      display: flex;
      gap: 32px;
      align-items: center;
    }
    
    .nav-links a {
      color: #666;
      text-decoration: none;
      font-size: 15px;
      transition: color 0.2s;
    }
    
    .nav-links a:hover {
      color: #059669;
    }
    
    .github-btn {
      background: #059669;
      color: white;
      padding: 8px 20px;
      border-radius: 6px;
      font-weight: 500;
    }
    
    .github-btn:hover {
      background: #047857;
      color: white;
    }
    
    /* Hero */
    .hero {
      padding: 80px 0;
      text-align: center;
    }
    
    .badge {
      display: inline-block;
      background: #ecfdf5;
      color: #059669;
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 14px;
      font-weight: 500;
      margin-bottom: 24px;
    }
    
    h1 {
      font-size: 56px;
      font-weight: 700;
      line-height: 1.1;
      margin-bottom: 24px;
      color: #1a1a1a;
    }
    
    .subtitle {
      font-size: 20px;
      color: #666;
      max-width: 600px;
      margin: 0 auto 40px;
    }
    
    /* Install Box */
    .install-box {
      max-width: 700px;
      margin: 0 auto 16px;
      background: #f9fafb;
      border: 1px solid #e5e5e5;
      border-radius: 12px;
      padding: 24px;
    }
    
    .command-line {
      display: flex;
      align-items: center;
      gap: 12px;
      background: #1a1a1a;
      padding: 16px 20px;
      border-radius: 8px;
      margin-bottom: 16px;
    }
    
    .prompt {
      color: #10b981;
      font-family: 'Courier New', monospace;
      font-size: 16px;
    }
    
    .command {
      flex: 1;
      color: #e5e5e5;
      font-family: 'Courier New', monospace;
      font-size: 16px;
    }
    
    .copy-btn {
      background: #374151;
      color: #e5e5e5;
      border: none;
      padding: 6px 12px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 13px;
      transition: background 0.2s;
    }
    
    .copy-btn:hover {
      background: #4b5563;
    }
    
    .requirements {
      font-size: 14px;
      color: #666;
      text-align: center;
    }
    
    /* Features */
    .features {
      padding: 80px 0;
      background: #f9fafb;
    }
    
    .section-title {
      text-align: center;
      font-size: 36px;
      font-weight: 700;
      margin-bottom: 48px;
    }
    
    .features-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 32px;
    }
    
    .feature-card {
      background: white;
      padding: 32px;
      border-radius: 12px;
      border: 1px solid #e5e5e5;
    }
    
    .feature-icon {
      width: 48px;
      height: 48px;
      background: #ecfdf5;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 16px;
      font-size: 24px;
    }
    
    .feature-card h3 {
      font-size: 20px;
      margin-bottom: 12px;
      color: #1a1a1a;
    }
    
    .feature-card p {
      color: #666;
      font-size: 15px;
      line-height: 1.6;
    }
    
    /* Steps */
    .steps {
      padding: 80px 0;
    }
    
    .steps-list {
      max-width: 800px;
      margin: 0 auto;
    }
    
    .step {
      display: flex;
      gap: 24px;
      margin-bottom: 48px;
    }
    
    .step-number {
      flex-shrink: 0;
      width: 48px;
      height: 48px;
      background: #059669;
      color: white;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      font-weight: 700;
    }
    
    .step-content h3 {
      font-size: 24px;
      margin-bottom: 12px;
    }
    
    .step-content p {
      color: #666;
      font-size: 16px;
      line-height: 1.6;
    }
    
    /* Footer */
    footer {
      padding: 48px 0;
      border-top: 1px solid #e5e5e5;
      text-align: center;
    }
    
    .footer-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 24px;
    }
    
    .footer-links {
      display: flex;
      gap: 32px;
    }
    
    .footer-links a {
      color: #666;
      text-decoration: none;
      font-size: 14px;
    }
    
    .footer-links a:hover {
      color: #059669;
    }
    
    /* Responsive */
    @media (max-width: 768px) {
      h1 { font-size: 36px; }
      .subtitle { font-size: 18px; }
      .nav-links { gap: 16px; }
      .hero { padding: 48px 0; }
      .features, .steps { padding: 48px 0; }
      .section-title { font-size: 28px; }
      .step { flex-direction: column; }
      .footer-content { flex-direction: column; text-align: center; }
    }
  </style>
</head>
<body>
  <!-- Header -->
  <header>
    <div class="container">
      <div class="header-content">
        <a href="/" class="logo">engram</a>
        <nav class="nav-links">
          <a href="https://github.com/Agentscreator/Engram" target="_blank" class="github-btn">GitHub ↗</a>
        </nav>
      </div>
    </div>
  </header>

  <!-- Hero -->
  <section class="hero">
    <div class="container">
      <div class="badge">Open source · Apache 2.0</div>
      <h1>Shared memory for<br>your AI agents</h1>
      <p class="subtitle">One knowledge base for your whole team. Your agent handles setup. You own your data.</p>
      
      <div class="install-box">
        <div class="command-line">
          <span class="prompt">$</span>
          <span class="command" id="cmd">pip install engram-mcp && engram install</span>
          <button class="copy-btn" onclick="copyCommand()">Copy</button>
        </div>
        <p class="requirements">Auto-detects Claude Code, Cursor, and Windsurf. Writes the MCP config for you.</p>
      </div>
    </div>
  </section>

  <!-- Features -->
  <section class="features">
    <div class="container">
      <h2 class="section-title">Why Engram?</h2>
      <div class="features-grid">
        <div class="feature-card">
          <div class="feature-icon">🧠</div>
          <h3>Shared Memory</h3>
          <p>All your agents access the same knowledge base. No more repeating context.</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">⚡</div>
          <h3>Conflict Detection</h3>
          <p>Automatically detects contradictions between facts. Review and resolve in the dashboard.</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">🔒</div>
          <h3>You Own Your Data</h3>
          <p>Self-hosted. Your data stays on your infrastructure. No third-party APIs.</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">🚀</div>
          <h3>Zero Config</h3>
          <p>One command to install. Works with Claude Code, Cursor, Windsurf, and any MCP client.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- Steps -->
  <section class="steps">
    <div class="container">
      <h2 class="section-title">Get Started</h2>
      <div class="steps-list">
        <div class="step">
          <div class="step-number">1</div>
          <div class="step-content">
            <h3>Install & configure</h3>
            <p>Run <code>pip install engram-mcp && engram install</code> to set up Engram and configure your MCP client automatically.</p>
          </div>
        </div>
        <div class="step">
          <div class="step-number">2</div>
          <div class="step-content">
            <h3>Restart your editor & open a new chat</h3>
            <p>Your agent takes it from here — it will ask whether you're setting up a new workspace or joining one. For new workspaces, you'll need a free PostgreSQL database (neon.tech, supabase.com, or railway.app). Teammates just need the Invite Key you share with them — nothing else.</p>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Footer -->
  <footer>
    <div class="container">
      <div class="footer-content">
        <div class="footer-links">
          <span style="font-weight: 600; color: #1a1a1a;">engram</span>
          <a href="https://github.com/Agentscreator/Engram" target="_blank">GitHub</a>
          <a href="https://github.com/Agentscreator/Engram/blob/main/LICENSE" target="_blank">Apache 2.0</a>
        </div>
        <p style="color: #999; font-size: 14px;">Python 3.11+ · Works with Claude Code, Cursor, Windsurf · <a href="https://github.com/Agentscreator/Engram" target="_blank" style="color: #059669;">Read the docs ↗</a></p>
      </div>
    </div>
  </footer>

  <script>
    function copyCommand() {
      const cmd = document.getElementById('cmd').textContent;
      navigator.clipboard.writeText(cmd).then(() => {
        const btn = event.target;
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy', 2000);
      });
    }
  </script>
</body>
</html>"""


def _render_dashboard_placeholder() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dashboard — Engram</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f9fafb;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }
    .card {
      max-width: 500px;
      background: white;
      padding: 48px;
      border-radius: 12px;
      border: 1px solid #e5e5e5;
      text-align: center;
    }
    h1 {
      font-size: 24px;
      margin-bottom: 16px;
      color: #1a1a1a;
    }
    p {
      color: #666;
      line-height: 1.6;
      margin-bottom: 24px;
    }
    .code-box {
      background: #1a1a1a;
      color: #e5e5e5;
      padding: 16px;
      border-radius: 8px;
      font-family: 'Courier New', monospace;
      font-size: 14px;
      text-align: left;
      margin-bottom: 24px;
    }
    a {
      color: #059669;
      text-decoration: none;
      font-weight: 500;
    }
    a:hover {
      text-decoration: underline;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Dashboard needs a running server</h1>
    <p>Start your local Engram instance, then open the dashboard there.</p>
    <div class="code-box">
      pip install engram-mcp<br>
      engram install<br>
      engram serve --http
    </div>
    <p>Then visit <a href="http://localhost:7474/dashboard">localhost:7474/dashboard</a></p>
    <p><a href="/">← Back to home</a></p>
  </div>
</body>
</html>"""


async def landing(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_landing())


async def dashboard_placeholder(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_dashboard_placeholder())


app = Starlette(
    routes=[
        Route("/", landing, methods=["GET"]),
        Route("/dashboard", dashboard_placeholder, methods=["GET"]),
        Route("/dashboard/{path:path}", dashboard_placeholder, methods=["GET"]),
    ],
)
