from backend.tools.browser import run_parallel_tasks
from backend.tools.planner import plan_task
from backend.models.schemas import PriceMonitorRequest
from backend.memory.agent_memory import update

TASK_TEMPLATE = """Check the price of "{product}" on {url}. Target: ₹{target}.

SEARCH INSTRUCTIONS:
1. Go to https://{url}
2. Search for "{product}" — find the EXACT product, not accessories
3. On the product page extract:
   - Current price (exact)
   - Original MRP + discount %
   - All active offers (bank cashback, coupon codes — read the "Offers" section fully)
   - EMI options (lowest monthly)
   - Seller name + seller rating
   - Delivery date + cost
   - Stock status
   - Product URL
4. Check "Other Sellers" section — list top 3 with prices
5. Check if any variant (color/storage) is cheaper
6. Is current price ≤ ₹{target}? State TARGET MET: YES or NO

HANDLE OBSTACLES:
- If login popup appears, close it and continue
- If price is behind login, try scrolling — it usually shows anyway
- Check multiple sellers for the same listing

FORMAT:
PRODUCT: [exact name + variant]
CURRENT PRICE: ₹X (was ₹Y, save Z%)
ACTIVE OFFERS: [list all offers found]
OTHER SELLERS: [seller] ₹X | [seller] ₹X
DELIVERY: [date] | [cost]
EMI: ₹X/month (Xm)
TARGET MET: YES / NO
RECOMMENDATION: Buy now / Wait / Check other platform
URL: [link]"""


async def check_price(request: PriceMonitorRequest, step_callback=None) -> dict:
    platforms = request.platforms or ["flipkart", "amazon"]
    platform_urls = {"amazon": "amazon.in", "flipkart": "flipkart.com"}

    tasks = []
    for p in platforms:
        url = platform_urls.get(p, p)
        plan = plan_task(
            f"Find current price of {request.product_name} on {url}, target ₹{int(request.target_price)}",
            "price_monitor"
        )
        task = plan + TASK_TEMPLATE.format(
            url=url,
            product=request.product_name,
            target=int(request.target_price),
        )
        tasks.append(task)

    results = await run_parallel_tasks(tasks, task_type="price_monitor", max_steps=20)

    sections = [f"## {platforms[i].upper()}\n\n{r}" for i, r in enumerate(results) if r]
    combined = "\n\n---\n\n".join(sections)

    target_met = "TARGET MET: YES" in combined.upper()
    combined += f"\n\n## VERDICT\n{'✅ Target price met — good time to buy!' if target_met else '⏳ Target not reached yet — monitoring continues.'}"

    update("price_monitor", combined, success=bool(combined))
    return {"product": request.product_name, "target_price": request.target_price, "summary": combined}
