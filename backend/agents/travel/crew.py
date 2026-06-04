from backend.tools.browser import run_deep_task
from backend.models.schemas import TravelRequest
from backend.memory.agent_memory import get_context, update


async def run_travel_booking(request: TravelRequest, step_callback=None) -> dict:
    budget_str = f"under ₹{int(request.budget)}" if request.budget else "best value"
    nights = ""
    if request.return_date:
        nights = f" (checking out {request.return_date})"

    task = f"""{get_context("travel")}
You are a thorough travel research agent. Find the best travel options.

TRIP DETAILS:
- From: {request.from_city}
- To: {request.to_city}
- Departure: {request.departure_date}
- Return: {request.return_date or 'one-way'}
- Budget: {budget_str}
- Preferences: {request.preferences or 'cheapest options'}

=== PHASE 1: FLIGHTS ===
1. Go to https://www.ixigo.com/flights
2. Enter: From={request.from_city}, To={request.to_city}, Date={request.departure_date}
3. Wait for results to fully load
4. SCROLL through the entire results list — do not stop at first 3
5. Check the filter panel: apply any "Non-stop" filter if available
6. For each flight option extract:
   - Airline name
   - Exact price (with any taxes shown)
   - Departure time and arrival time
   - Duration and stops
   - Baggage allowance if shown
   - Booking link
7. Collect top 5 cheapest AND top 2 fastest options
8. If prices are above budget, check the "Flexible dates" or fare calendar for cheaper dates ±2 days

=== PHASE 2: HOTELS ===
1. Go to https://www.ixigo.com/hotels
2. Search: City={request.to_city}, Check-in={request.departure_date}{nights}
3. Wait for results to fully load
4. SCROLL through at least 20 hotel results
5. For each hotel extract:
   - Hotel name and star rating
   - Price per night (and total for stay)
   - Location/area in the city
   - Guest rating (out of 10)
   - Key amenities (free breakfast, AC, wifi, etc.)
   - Booking link
6. Collect top 5 cheapest AND top 2 best-rated options

=== PHASE 3: SUMMARY ===
Present a clean comparison table:
FLIGHTS:
| # | Airline | Price | Departure | Duration | Stops |
...

HOTELS:
| # | Hotel | Price/night | Rating | Area | Amenities |
...

RECOMMENDED COMBO: [cheapest flight + best value hotel]
TOTAL ESTIMATED COST: ₹X
SAVINGS TIP: [any tip found, e.g. flexible date cheaper by ₹X]"""

    result = await run_deep_task(task, max_steps=35)
    update("travel", result, success=bool(result))
    return {
        "summary": result,
        "from": request.from_city,
        "to": request.to_city,
        "dates": f"{request.departure_date} → {request.return_date or 'one-way'}",
    }
