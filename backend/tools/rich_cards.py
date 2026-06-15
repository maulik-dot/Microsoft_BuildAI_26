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
    prompt = f"""You are an entity detector. Read the query and the research snippet.
Identify if the user is asking about or the result describes specific, identifiable entities (e.g., a product, place, movie, book, person, landmark, gadget).
If yes, return a JSON list of objects, each representing an entity to enrich.

QUERY: "{query}"
RESULT SNIPPET:
{result_text[:1500]}

Rules:
- Identify up to 4 distinct entities.
- For each entity, specify:
  * "name": official name (e.g. "iPhone 16 Pro", "Eiffel Tower", "Inception")
  * "type": one of ["product", "place", "media", "profile"]
  * "query": a good search query to find its details (e.g. "iPhone 16 Pro official site", "Eiffel Tower maps")

Return the result ONLY as a JSON code block wrapped in ```json ... ```. If no entity is found, return an empty list `[]` inside the block."""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _call_llm, prompt, "verification")
    parsed = _parse_json(raw)
    return parsed if isinstance(parsed, list) else []

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
        
    prompt = f"""You are a structured data extractor. You are given a list of entities and a markdown research report containing information about them.
    
ENTITIES TO EXTRACT:
{json.dumps(entities, indent=2)}

RESEARCH REPORT:
{result_text[:4000]}

For each entity, extract its details from the report. If not found in the report, use general knowledge or keep empty.
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

async def enrich_response(query: str, res: dict) -> dict:
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
            res["result"] = {
                "answer": result_text,
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
        _save_cache(cache)
        res["result"] = {
            "answer": result_text,
            "cards": all_cards
        }
        
    return res
