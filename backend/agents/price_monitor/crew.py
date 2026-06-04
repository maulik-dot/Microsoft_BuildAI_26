from backend.tools.browser import run_parallel_tasks
from backend.models.schemas import PriceMonitorRequest
from backend.memory.agent_memory import get_context, update

DEEP_PROMPT = """You are a thorough price research agent. Find the best price for a product on {url}.

PRODUCT: {product}
TARGET PRICE: ₹{target}

INSTRUCTIONS:

1. Go to https://{url}
2. Search for "{product}" in the search bar
3. On the results page:
   - Look for EXACT product match (not accessories, cases, or similar items)
   - Check multiple listings — there may be different sellers/variants
   - SCROLL down to see all variants (storage, color, etc.)
4. Click on the main product listing
5. On the product detail page extract:
   - Exact current price
   - Original MRP / strikethrough price
   - Discount percentage
   - Any active coupon codes or bank offers visible on page
   - EMI options (lowest EMI)
   - Seller name and seller rating
   - Delivery date and cost
   - Stock availability
   - Product URL
6. Check if there are other sellers for the same product (look for "Other sellers" or "Sold by")
   - Extract prices from top 3 sellers
7. Look for any "Price drop alert" or "Notify me" feature
8. Is the current price at or below ₹{target}? Answer YES or NO clearly.

FORMAT your response as:
PRODUCT: [exact name + specs]
CURRENT PRICE: ₹X (was ₹Y, save Z%)
BEST SELLER: [name] | Rating: X
ACTIVE OFFERS: [coupon/bank offer details]
OTHER SELLERS: seller1 ₹X | seller2 ₹X
DELIVERY: [date] [cost]
TARGET MET: YES/NO
RECOMMENDATION: [Buy now / Wait for sale / Check other platforms]
URL: [link]"""


async def check_price(request: PriceMonitorRequest, step_callback=None) -> dict:
    platforms = request.platforms or ["flipkart", "amazon"]
    platform_urls = {"amazon": "amazon.in", "flipkart": "flipkart.com"}

    memory_ctx = get_context("price_monitor")

    tasks = []
    for p in platforms:
        url = platform_urls.get(p, p)
        prompt = memory_ctx + "\n\n" + DEEP_PROMPT.format(
            url=url,
            product=request.product_name,
            target=int(request.target_price),
        )
        tasks.append(prompt)

    results = await run_parallel_tasks(tasks, max_steps=20)

    sections = []
    for i, r in enumerate(results):
        if r:
            sections.append(f"## {platforms[i].upper()}\n\n{r}")

    combined = "\n\n---\n\n".join(sections)

    # Add verdict
    target_met = "YES" in combined.upper() and "TARGET MET: YES" in combined.upper()
    verdict = f"\n\n## VERDICT\n{'✅ TARGET PRICE MET — Good time to buy!' if target_met else '⏳ Target price not yet reached — monitoring continues.'}"
    combined += verdict

    update("price_monitor", combined, success=bool(combined))
    return {
        "product": request.product_name,
        "target_price": request.target_price,
        "summary": combined,
    }
