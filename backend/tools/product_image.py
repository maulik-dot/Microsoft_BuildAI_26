"""
Product image fetcher.

Pulls the main product photo (og:image / main <img>) from the retailer product
pages the agent visited, for cards that don't already carry an image. Uses a real
headless browser on purpose: retailer pages are JS-rendered and inject og:image
client-side, so plain HTTP (httpx) returns nothing. Best-effort and non-fatal —
a card without a resolvable image simply keeps its placeholder.
"""

import asyncio

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")

# og:image first, then common retailer main-image selectors, then the largest
# loaded image as a last resort.
_IMG_JS = """() => {
  const ok = (u) => (typeof u === 'string' && u.startsWith('http')) ? u : '';
  const meta = document.querySelector(
    'meta[property="og:image"],meta[name="og:image"],meta[property="og:image:url"],meta[name="twitter:image"],link[rel="image_src"]');
  if (meta) { const v = ok(meta.getAttribute('content') || meta.getAttribute('href')); if (v) return v; }
  const sels = ['#landingImage','#imgTagWrapperId img','img._396cs4','img._2r_T1I',
                'img.pdp-image','.pdp-e-i-head img','.ProductImage img','.product-img img',
                '[data-testid="product-image"] img','picture img'];
  for (const s of sels) { const e = document.querySelector(s); if (e) { const v = ok(e.currentSrc || e.src); if (v) return v; } }
  const imgs = [...document.images].filter(i => {
    const w = i.naturalWidth, h = i.naturalHeight;
    if (w < 300 || h < 300) return false;
    const ar = w / h;                 // reject banners / wide strips / tall rails
    return ar > 0.6 && ar < 1.7;
  });
  imgs.sort((a, b) => b.naturalWidth * b.naturalHeight - a.naturalWidth * a.naturalHeight);
  return imgs.length ? ok(imgs[0].currentSrc || imgs[0].src) : '';
}"""


async def _extract_one(ctx, url: str) -> str:
    pg = await ctx.new_page()
    try:
        await pg.goto(url, wait_until="load", timeout=15000)
        await pg.wait_for_timeout(1200)   # let lazy images / injected meta settle
        img = await pg.evaluate(_IMG_JS)
        return img if isinstance(img, str) and img.startswith("http") else ""
    except Exception:
        return ""
    finally:
        try:
            await pg.close()
        except Exception:
            pass


async def fetch_product_images(cards: list, overall_timeout: float = 20.0) -> None:
    """
    Fill card['image'] in place for product cards that lack one, using their captured
    retailer URLs (external_links, then official_url). Concurrent, time-boxed, and
    swallows all errors — never blocks or fails the response.
    """
    targets = []
    for c in cards:
        if not isinstance(c, dict) or c.get("type") != "product" or c.get("image"):
            continue
        urls = [l.get("url") for l in (c.get("external_links") or []) if l.get("url")]
        if c.get("official_url"):
            urls.append(c["official_url"])
        if urls:
            targets.append((c, urls))
    if not targets:
        return

    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=[
                "--no-sandbox",                 # required when running as root in a container
                "--disable-dev-shm-usage",      # avoid /dev/shm crashes on small-shm hosts
                "--disable-blink-features=AutomationControlled",
            ])
            try:
                ctx = await browser.new_context(
                    user_agent=_UA, viewport={"width": 1280, "height": 900})

                async def fill(card, urls):
                    for u in urls[:3]:          # try each retailer link until one yields an image
                        img = await _extract_one(ctx, u)
                        if img:
                            card["image"] = img
                            return

                await asyncio.gather(*[fill(c, u) for c, u in targets])
            finally:
                await browser.close()

    try:
        await asyncio.wait_for(run(), timeout=overall_timeout)
    except Exception:
        pass
