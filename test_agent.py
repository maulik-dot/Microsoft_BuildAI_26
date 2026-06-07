import asyncio
import sys
import os

# Add current dir to path so backend imports work
sys.path.insert(0, os.path.abspath("."))

from backend.models.schemas import PriceMonitorRequest
from backend.agents.price_monitor.crew import check_price

async def main():
    print("Setting up test request...")
    req = PriceMonitorRequest(
        product_name="Sony WH-1000XM5 headphones black",
        target_price=24000,
        platforms=["amazon"]
    )
    print("Starting agent... (This will open a browser and navigate)")
    res = await check_price(req)
    print("\n\n=== TEST RESULT ===")
    print(res["summary"])
    
if __name__ == "__main__":
    asyncio.run(main())
