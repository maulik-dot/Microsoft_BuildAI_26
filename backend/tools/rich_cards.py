import asyncio
import re
import json
import os
import httpx
from backend.tools.planner import _call_llm

CACHE_FILE = os.path.join(os.path.dirname(__file__), "../memory/entity_cache.json")

def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_cache(cache: dict):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

def _parse_json(raw: str):
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except Exception:
        # Fallback parsing
        try:
            cleaned = re.sub(r'^.*?({|\[)', r'\1', raw, flags=re.DOTALL)
            cleaned = re.sub(r'(}|\])[^}\]]*?$', r'\1', cleaned, flags=re.DOTALL)
            return json.loads(cleaned.strip())
        except Exception:
            return [] if raw.startswith("[") else {}

async def detect_entities(query: str, result_text: str) -> list[dict]:
    """Use LLM to detect if query/result mentions products, places, media, or profiles."""
    prompt = f"""You are an entity detector. Read the query and the browser snippet.
Identify if the user is asking about or the result describes specific, identifiable entities (e.g., a product, place, movie, book, person, landmark, gadget).
If yes, return a JSON list of objects, each representing an entity to enrich.

QUERY: "{query}"
RESULT SNIPPET:
{result_text[:1500]}

Rules:
- Identify up to 4 distinct entities.
- Do NOT treat online stores, retailers, marketplaces, or search engines (e.g. Amazon, Flipkart, Croma, Myntra, AJIO, Reliance Digital, Google, YouTube) as entities — they are sellers/sources, not the thing itself. Only the actual product/place/movie/book/person counts.
- For each entity, specify:
  * "name": official name (e.g. "iPhone 16 Pro", "Eiffel Tower", "Inception")
  * "type": one of ["product", "place", "media", "profile"]
  * "query": a good search query to find its details (e.g. "iPhone 16 Pro official site", "Eiffel Tower maps")

Return the result ONLY as a JSON code block wrapped in ```json ... ```. If no entity is found, return an empty list `[]` inside the block."""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _call_llm, prompt, "verification")
    parsed = _parse_json(raw)
    if not isinstance(parsed, list):
        return []
    # Belt-and-suspenders: drop any retailer/marketplace/source the LLM slipped in.
    return [e for e in parsed
            if isinstance(e, dict) and e.get("name") and not _is_retailer_name(e["name"])]

async def fetch_wikipedia_summary(entity_name: str) -> dict:
    """Query Wikipedia Rest API for summary details and official image."""
    formatted_name = entity_name.strip().replace(" ", "_")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{formatted_name}"
    headers = {"User-Agent": "VayuResearchAgent/1.0 (contact: maulikmahey@example.com)"}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=headers, timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                return {
                    "image": data.get("thumbnail", {}).get("source", ""),
                    "description": data.get("extract", ""),
                    "official_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                }
        except Exception:
            pass
    return {}

async def extract_llm_details_batch(entities: list[dict], result_text: str) -> dict:
    """Use LLM to extract structured pricing/details for all entities in a single batch call."""
    if not entities:
        return {}
        
    prompt = f"""You are a structured data extractor. You are given a list of entities and a markdown browser report containing information about them.
    
ENTITIES TO EXTRACT:
{json.dumps(entities, indent=2)}

RESEARCH REPORT:
{result_text[:4000]}

For each entity, extract its details from the report.

STRICT URL RULE — this is critical:
- All URL/link fields (official_url, external_links[].url, image) MUST be copied VERBATIM from the RESEARCH REPORT text above.
- If a URL is not literally present in the report, leave it as "" (or omit external_links). Do NOT invent, guess, or fill it from general knowledge.
- NEVER output a generic/company/reference URL (e.g. wikipedia.org, apple.com or any brand homepage) in place of a real retailer product-page link — a missing link is better than a wrong one.
- For a price-comparison query the value is the per-retailer product links (Amazon/Flipkart/Croma/etc.); only include a retailer in external_links if its actual product URL appears in the report.

For NON-URL fields only (description, brand, year, genre, etc.) you may use general knowledge if the report is silent.

Format the response as a JSON object where the keys are the exact entity names, and the values are objects with these fields depending on the entity's type:

For product:
- title: entity name
- brand: brand name (e.g. "Apple")
- description: short 1-2 sentence description
- price: price (e.g. "₹79,900" or "$999")
- rating: numeric rating (e.g. 4.6)
- image: primary image URL found in report (if present, otherwise keep empty)
- official_url: official page URL
- external_links: list of objects with "label" and "url" (e.g. Amazon, Flipkart, etc. found in report)

For place:
- title: entity name
- description: short description
- address: address/location details
- hours: opening hours if mentioned
- rating: numeric rating (e.g. 4.8)
- image: primary image URL found in report (if present, otherwise keep empty)
- official_url: official page URL
- external_links: list of objects with "label" and "url" (e.g. Google Maps)

For media (movie/book):
- title: entity name
- description: summary
- year: release year
- genre: genre details
- image: primary image URL found in report (if present, otherwise keep empty)
- official_url: official link
- external_links: list of objects with "label" and "url" (e.g. IMDb, Goodreads)

For profile (person):
- title: entity name
- description: short bio
- occupation: occupation
- image: primary image URL found in report (if present, otherwise keep empty)
- official_url: homepage/social link
- external_links: list of objects with "label" and "url"

Return the result ONLY as a JSON code block wrapped in ```json ... ```. Do not add any other text outside the JSON block."""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _call_llm, prompt, "verification")
    parsed = _parse_json(raw)
    return parsed if isinstance(parsed, dict) else {}

def _extract_image_from_text(entity_name: str, text: str) -> str:
    # Look for image URLs in text (markdown images or raw URLs)
    matches = re.findall(r'https?://[^\s\)]+?\.(?:png|jpe?g|webp|gif)', text, re.IGNORECASE)
    if matches:
        return matches[0]
    return ""

async def clean_result_text(query: str, result_text: str, cards: list[dict]) -> str:
    """Clean the raw browser text by removing ugly raw lists/URLs that are already rendered as cards."""
    # Serialize cards for the LLM
    cards_json = json.dumps(cards, indent=2)

    prompt = f"""You are a professional, senior copywriter for Vayu, an AI browser assistant.
We have just completed a web search and extracted/validated structured entity cards for these products/entities:
{cards_json}

The user's original query was: "{query}"

Here is the raw browser report containing notes about the search session:
---
{result_text}
---

Your task:
Rewrite the browser report into a clean, professional summary that will be displayed BELOW the image and link cards.
Generate a response in this EXACT format (do not repeat the product images or specifications, as they are already displayed in the cards above):

1. Introduction:
   - A friendly message starting with: "I have successfully searched for [Query] on [Sources]. Below is the comparison of the best options found." (E.g. "I have successfully searched for Nike shoes under 3000 rupees on both Amazon.in and Flipkart.com. Below is the comparison of the best options found.")

2. Comparison Table:
   - A markdown comparison table listing the products:
     | Source | Product Name | Price | Rating | Direct Link |
     |---|---|---|---|---|
     | [Source/Store (e.g. Flipkart, Amazon.in)] | [Product Name] | [Price] | [Rating (e.g. N/A or 4.2)] | [View on [Store]]([Direct link URL]) |

3. BEST VALUE Section:
   - "BEST VALUE: The [Product Name] on [Store] at [Price] is the best value because [Reason from report]."

4. Note / Research Logs Section:
   - "Note: [State any login/captcha obstacles bypassed, search engines used, or navigation details from the browser report]."

CRITICAL RULES:
- Do NOT output any raw URLs as plain text; they must only be in markdown links like `[View on Store](url)`.
- Use the exact keys, names, prices, ratings, and URLs from the validated cards JSON.
- Output ONLY the final markdown. Do NOT wrap it in HTML, markdown codeblocks (like ```markdown), or add any conversational intro/outro text (e.g. "Here is the response:")."""

    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _call_llm, prompt, "verification")
        return raw.strip()
    except Exception as e:
        print(f"[ENRICH] Failed to clean response text: {e}")
        return result_text

# ── Retailer product-link capture (from the agent's real navigation) ─────────

_RETAILERS = {
    "amazon.":          "Amazon",
    "flipkart.":        "Flipkart",
    "croma.com":        "Croma",
    "reliancedigital.": "Reliance Digital",
    "tatacliq.":        "Tata CLiQ",
    "vijaysales.":      "Vijay Sales",
    "myntra.":          "Myntra",
    "ajio.":            "AJIO",
    "snapdeal.":        "Snapdeal",
    "nykaa.":           "Nykaa",
    "meesho.":          "Meesho",
}
# Path fragments that mark an actual product/details page (not search / home).
_PRODUCT_PATH_HINTS = ("/dp/", "/gp/product/", "/p/", "/product/", "/prod/", "/itm", "/buy")

# Names that are sellers/sources, never product entities → never get their own card.
_NON_ENTITY_NAMES = {v.lower() for v in _RETAILERS.values()} | {
    "google", "google shopping", "youtube", "wikipedia", "reddit", "quora",
    "bing", "jiomart", "paytm mall", "shopclues",
}
_RETAILER_KEYWORDS = tuple(sorted(
    {v.lower() for v in _RETAILERS.values()} | {"jiomart", "shopclues", "paytm"},
    key=len, reverse=True))


def _is_retailer_name(name: str) -> bool:
    """True for store/marketplace/source names (Amazon, Flipkart, Croma…), not products."""
    n = re.sub(r"\.(co\.in|com|in)$", "", (name or "").strip().lower()).strip()
    if not n:
        return True
    if n in _NON_ENTITY_NAMES:
        return True
    for kw in _RETAILER_KEYWORDS:
        if n == kw or n.startswith(kw + " ") or n.endswith(" " + kw):
            return True
    return False


def _is_product_url(url: str) -> bool:
    u = (url or "").lower()
    if not u.startswith("http"):
        return False
    if any(s in u for s in ("google.", "bing.", "duckduckgo.", "/search", "/s?", "?k=")):
        return False
    return any(h in u for h in _PRODUCT_PATH_HINTS)


def _tokens(s: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 1}


def collect_retailer_links(task_id: str) -> list[dict]:
    """
    Pull the retailer PRODUCT-page URLs the agent actually visited out of the step
    log. Returns one {label, url, title} per retailer — real, navigated URLs, which
    are far more reliable than re-extracting links from the report prose.
    """
    if not task_id:
        return []
    try:
        from backend.tools.browser import get_steps
        steps = get_steps(task_id)
    except Exception:
        return []
    picked: dict[str, dict] = {}
    for step in steps:
        url = (step.get("url") or "").strip()
        if not _is_product_url(url):
            continue
        low = url.lower()
        for frag, label in _RETAILERS.items():
            if frag in low:
                picked.setdefault(label, {"label": label, "url": url,
                                          "title": step.get("title") or ""})
                break
    return list(picked.values())


def _finalize_product_cards(cards: list[dict], task_id: str) -> None:
    """
    Post-process product cards in place:
      • drop a Wikipedia page masquerading as official_url (products want retailer links),
      • graft on the retailer product URLs the agent actually visited, matched to the
        right card and deduped by URL.
    """
    product_cards = [c for c in cards if c.get("type") == "product"]
    if not product_cards:
        return

    # A Wikipedia article is never a product's "official site".
    for c in product_cards:
        if "wikipedia.org" in (c.get("official_url") or "").lower():
            c["official_url"] = ""

    links = collect_retailer_links(task_id)
    if not links:
        return
    single = len(product_cards) == 1
    for card in product_cards:
        ctoks = _tokens(card.get("title"))
        card.setdefault("external_links", [])
        seen = {(l.get("url") or "").split("?")[0] for l in card["external_links"]}
        for link in links:
            base = (link["url"] or "").split("?")[0]
            if not base or base in seen:
                continue
            ltoks = _tokens(link.get("title")) | _tokens(link["url"])
            # attach when it's the only product card, or the titles clearly overlap
            if single or len(ctoks & ltoks) >= 2:
                card["external_links"].append({"label": link["label"], "url": link["url"]})
                seen.add(base)


async def _fetch_card_images(cards: list) -> None:
    """Best-effort: fill product-card images from their retailer URLs. Never raises."""
    try:
        from backend.tools.product_image import fetch_product_images
        await fetch_product_images(cards)
    except Exception:
        pass


async def enrich_response(query: str, res: dict, task_id: str = "") -> dict:
    """Enrich the agent response dict if it has an answer string."""
    if not res or "result" not in res or not isinstance(res["result"], str):
        return res
        
    result_text = res["result"]
    
    # Run entity detection (asynchronously)
    entities = await detect_entities(query, result_text)
    if not entities:
        return res
        
    cache = _load_cache()
    
    # Check cache first
    cached_cards = []
    uncached_entities = []
    
    for ent in entities:
        name = ent["name"]
        if name in cache:
            cached_cards.append(cache[name])
        else:
            uncached_entities.append(ent)
            
    if not uncached_entities:
        # All entities were cached! Return immediately
        if cached_cards:
            _finalize_product_cards(cached_cards, task_id)
            await _fetch_card_images(cached_cards)
            cleaned_text = await clean_result_text(query, result_text, cached_cards)
            res["result"] = {
                "answer": cleaned_text,
                "cards": cached_cards
            }
        return res
        
    # Enrich uncached entities
    new_cards = []
    try:
        # Run Wikipedia summaries and LLM batch details extraction in parallel
        wiki_tasks = [fetch_wikipedia_summary(ent["name"]) for ent in uncached_entities]
        llm_task = extract_llm_details_batch(uncached_entities, result_text)
        
        # We can gather Wikipedia tasks and the LLM task together
        gathered_results = await asyncio.wait_for(
            asyncio.gather(*wiki_tasks, llm_task, return_exceptions=True),
            timeout=10.0
        )
        
        # Split wiki results and llm result
        wiki_results = gathered_results[:-1]
        llm_results_batch = gathered_results[-1]
        if isinstance(llm_results_batch, Exception) or not isinstance(llm_results_batch, dict):
            print(f"[ENRICH] LLM batch extraction failed: {llm_results_batch}")
            llm_results_batch = {}
            
        for i, ent in enumerate(uncached_entities):
            name = ent["name"]
            ent_type = ent["type"]
            
            wiki_res = wiki_results[i]
            if isinstance(wiki_res, Exception) or not wiki_res:
                wiki_res = {}
                
            llm_data = llm_results_batch.get(name) or {}
            
            # If both are empty, don't create a card
            if not wiki_res and not llm_data:
                continue
                
            # Merge and populate card
            card = {
                "type": ent_type,
                "title": llm_data.get("title") or name,
                "description": llm_data.get("description") or wiki_res.get("description") or "",
                "image": llm_data.get("image") or wiki_res.get("image") or _extract_image_from_text(name, result_text) or "",
                "official_url": wiki_res.get("official_url") or llm_data.get("official_url") or "",
                "external_links": llm_data.get("external_links") or [],
            }
            
            if ent_type == "product":
                card["price"] = llm_data.get("price") or ""
                card["rating"] = llm_data.get("rating") or None
                card["brand"] = llm_data.get("brand") or ""
            elif ent_type == "place":
                card["address"] = llm_data.get("address") or ""
                card["hours"] = llm_data.get("hours") or ""
                card["rating"] = llm_data.get("rating") or None
            elif ent_type == "media":
                card["year"] = llm_data.get("year") or ""
                card["genre"] = llm_data.get("genre") or ""
            elif ent_type == "profile":
                card["occupation"] = llm_data.get("occupation") or ""
                
            cache[name] = card
            new_cards.append(card)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ENRICH ERROR] Batch enrichment failed: {e}")
        
    all_cards = cached_cards + new_cards
    if all_cards:
        # Attach the agent's real visited product URLs, then fetch product images for
        # cards still missing one — before caching, so repeat queries return the
        # fully-enriched card (links + image) instantly.
        _finalize_product_cards(all_cards, task_id)
        await _fetch_card_images(all_cards)
        _save_cache(cache)
        cleaned_text = await clean_result_text(query, result_text, all_cards)
        res["result"] = {
            "answer": cleaned_text,
            "cards": all_cards
        }
        
    return res
