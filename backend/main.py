import browser_use.llm.groq.chat as _groq_chat
_groq_chat.ToolCallingModels.extend([
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant",
])

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import os
from contextlib import asynccontextmanager
from backend.api.tasks import router as tasks_router
from backend.monitoring.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    # Resolve the best working model per tier ONCE at startup (parallel probe), so
    # the request hot path never makes a blocking network probe. Non-fatal.
    try:
        from backend.tools.model_selector import resolve_models
        await resolve_models()
    except Exception as e:
        print(f"[Vayu] Model resolve failed (using optimistic defaults): {e}")
    # Pre-warm browser so first query starts instantly.
    # get_browser() only constructs the session; start() actually launches Chromium,
    # so the very first real query no longer pays the cold-start cost either.
    try:
        from backend.tools.browser import get_browser
        browser = await get_browser()
        await browser.start()
        print("[Vayu] Browser pre-warmed and ready")
    except Exception as e:
        print(f"[Vayu] Browser pre-warm failed (will start on first query): {e}")
    yield
    stop_scheduler()
    from backend.tools.browser import close_browser
    await close_browser()


app = FastAPI(
    title="Vayu",
    description="Vayu — the autonomous browser agent that moves through the internet like wind, finding anything for you.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)

# Serve frontend static files (logo, etc.)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def serve_ui():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_view():
    return HTMLResponse(f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Vayu Knowledge</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif; background: #07111f; color: #e5eefb; }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    .hero {{ display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 24px; }}
    h1 {{ margin: 0; font-size: clamp(28px, 5vw, 44px); letter-spacing: -0.03em; }}
    .sub {{ margin-top: 8px; color: #9fb1cc; max-width: 70ch; line-height: 1.5; }}
    .pill {{ display: inline-flex; align-items: center; gap: 8px; padding: 10px 14px; border: 1px solid #20304b; border-radius: 999px; background: rgba(255,255,255,0.03); color: #cfe0ff; text-decoration: none; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-top: 18px; }}
    .card {{ border: 1px solid #1c2b45; border-radius: 18px; background: linear-gradient(180deg, rgba(14,24,42,0.92), rgba(9,16,30,0.92)); padding: 18px; box-shadow: 0 16px 50px rgba(0,0,0,.22); }}
    .card h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .muted {{ color: #8fa5c6; font-size: 13px; }}
    .list {{ display: grid; gap: 10px; margin-top: 10px; }}
    .item {{ padding: 12px; border-radius: 14px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); }}
    .domain {{ font-weight: 700; margin-bottom: 4px; }}
    .flow {{ color: #dce7fb; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }}
    .tagrow {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
    .tag {{ font-size: 12px; padding: 6px 10px; border-radius: 999px; background: rgba(63, 120, 255, 0.15); border: 1px solid rgba(63, 120, 255, 0.22); color: #b9cffc; }}
    .two {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    pre {{ margin: 0; overflow: auto; white-space: pre-wrap; word-break: break-word; color: #d8e4f8; background: rgba(255,255,255,0.03); padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }}
    @media (max-width: 760px) {{ .hero, .two {{ grid-template-columns: 1fr; display: grid; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>Vayu Knowledge</h1>
        <div class="sub">Reusable web flows, page types, obstacle handling, and learned search patterns from the browser agent.</div>
      </div>
      <a class="pill" href="/tasks/knowledge" target="_blank" rel="noreferrer">View raw JSON</a>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Site Flows</h2>
        <div class="muted">What the agent has learned about specific sites.</div>
        <div id="sites" class="list"></div>
      </div>

      <div class="card">
        <h2>Web Patterns</h2>
        <div class="muted">Reusable flows across search results, detail pages, forms, filters, and more.</div>
        <div id="patterns" class="list"></div>
      </div>
    </div>

    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <h2>Obstacle Notes</h2>
        <div id="obstacles" class="list"></div>
      </div>
      <div class="card">
        <h2>Query Patterns</h2>
        <div id="queries" class="list"></div>
      </div>
    </div>
  </div>

  <script>
    const safe = (value) => (value ?? '').toString();
    const el = (html) => {{ const d = document.createElement('div'); d.innerHTML = html; return d.firstElementChild; }};

    function renderSite(domain, site) {{
      const flows = site.page_flows || {{}};
      const flowCount = Object.values(flows).reduce((n, arr) => n + (Array.isArray(arr) ? arr.length : 0), 0);
      const tags = [
        `success ${{safe(site.success_count)}}`,
        `fail ${{safe(site.fail_count)}}`,
        `avg steps ${{safe(site.avg_steps)}}`,
        `flows ${{flowCount}}`,
      ];
      return el(`
        <div class="item">
          <div class="domain">${{domain}}</div>
          <div class="flow">${{safe(site.navigation_hint || 'No navigation hint yet.')}}</div>
          <div class="tagrow">${{tags.map(t => `<span class="tag">${{t}}</span>`).join('')}}</div>
        </div>
      `);
    }}

    function renderPattern(name, bucket) {{
      const hints = (bucket.hints || []).slice(0, 3).map(h => `<div class="flow">${{safe(h)}}</div>`).join('');
      const flows = (bucket.flows || []).slice(0, 2).map(f => `<div class="flow">${{safe(f.summary || f)}}</div>`).join('');
      return el(`
        <div class="item">
          <div class="domain">${{name}}</div>
          <div class="muted">seen ${{safe(bucket.count || 0)}} times</div>
          <div style="margin-top:8px; display:grid; gap:8px;">${{hints}}${{flows}}</div>
        </div>
      `);
    }}

    function renderObstacle(item) {{
      return el(`
        <div class="item">
          <div class="domain">${{safe(item.obstacle || 'Obstacle')}}</div>
          <div class="flow">${{safe(item.context || '')}}</div>
          <div class="muted" style="margin-top:6px;">${{safe(item.date || '')}}</div>
        </div>
      `);
    }}

    async function init() {{
      const res = await fetch('/tasks/knowledge');
      const data = await res.json();

      const sites = document.getElementById('sites');
      const siteEntries = Object.entries(data.sites || {{}}).filter(([, s]) => (s.success_count || 0) > 0 || (s.navigation_hint || '').length);
      if (!siteEntries.length) sites.appendChild(el('<div class="muted">No site flows learned yet.</div>'));
      siteEntries.slice(0, 8).forEach(([domain, site]) => sites.appendChild(renderSite(domain, site)));

      const patterns = document.getElementById('patterns');
      const patternEntries = Object.entries(data.web_patterns || {{}});
      if (!patternEntries.length) patterns.appendChild(el('<div class="muted">No web patterns learned yet.</div>'));
      patternEntries.slice(0, 8).forEach(([name, bucket]) => patterns.appendChild(renderPattern(name, bucket)));

      const obstacles = document.getElementById('obstacles');
      const obstacleEntries = data.obstacle_solutions || [];
      if (!obstacleEntries.length) obstacles.appendChild(el('<div class="muted">No obstacles recorded yet.</div>'));
      obstacleEntries.slice(-8).reverse().forEach((item) => obstacles.appendChild(renderObstacle(item)));

      const queries = document.getElementById('queries');
      const queryEntries = Object.entries(data.query_patterns || {{}});
      if (!queryEntries.length) queries.appendChild(el('<div class="muted">No query patterns learned yet.</div>'));
      queryEntries.slice(0, 8).forEach(([name, list]) => {{
        queries.appendChild(el(`<div class="item"><div class="domain">${{name}}</div><pre>${{safe((list || []).join('\n'))}}</pre></div>`));
      }});
    }}

    init().catch(err => {{
      document.body.innerHTML = '<pre style="padding:20px;color:#fff;">Failed to load knowledge: ' + err + '</pre>';
    }});
  </script>
</body>
</html>
""")
