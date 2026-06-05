from backend.tools.browser import run_deep_task
from backend.tools.planner import plan_task
from backend.models.schemas import TravelRequest
from backend.memory.agent_memory import update


async def run_travel_booking(request: TravelRequest, step_callback=None, task_id: str = "") -> dict:
    budget_str = f"under ₹{int(request.budget)}" if request.budget else "best value"
    nights = f", check-out {request.return_date}" if request.return_date else ""

    plan = plan_task(
        f"Find flights from {request.from_city} to {request.to_city} on {request.departure_date} and hotels in {request.to_city}, budget {budget_str}",
        "travel"
    )

    task = plan + f"""⚠️ IMPORTANT: Do NOT use Google Flights or MakeMyTrip. Go directly to ixigo.com — it loads faster and has less bot detection.

Find the best travel options for this trip:
- From: {request.from_city} → To: {request.to_city}
- Departure: {request.departure_date} | Return: {request.return_date or 'one-way'}
- Budget: {budget_str}

=== FLIGHTS ===
1. Go to https://www.ixigo.com/flights
2. Enter From={request.from_city}, To={request.to_city}, Date={request.departure_date}
3. Wait 3-5 seconds for results — scroll down slowly to load all options
4. Apply "Non-stop" filter if available
5. Expand each flight card to read: departure time, arrival time, duration, stops
6. Collect top 5 cheapest + top 2 fastest flights
7. If all prices exceed budget, check flexible dates (±2 days)

Each flight:
| Airline | Price | Departs | Arrives | Duration | Stops |

=== HOTELS ===
1. Go to https://www.ixigo.com/hotels
2. Search: City={request.to_city}, Check-in={request.departure_date}{nights}
3. Sort by Price: Low to High
4. Scroll through 20+ results
5. Click each hotel card for: name, price/night, rating, area, amenities

Each hotel:
| Hotel | ₹/night | Rating | Area | Highlights |

=== FINAL SUMMARY ===
RECOMMENDED COMBO: [cheapest flight] + [best value hotel]
TOTAL COST: ₹X
SAVINGS TIP: [any cheaper alternatives or date tips found]"""

    result = await run_deep_task(task, task_type="travel", task_id=task_id, max_steps=25)
    update("travel", result, success=bool(result))
    return {
        "summary": result,
        "from": request.from_city,
        "to": request.to_city,
        "dates": f"{request.departure_date} → {request.return_date or 'one-way'}",
    }
