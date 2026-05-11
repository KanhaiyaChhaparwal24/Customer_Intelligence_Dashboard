import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

# Ensure backend package modules are importable when running from repo root
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
from services.sync_service import sync_all


if __name__ == '__main__':
    result = asyncio.run(sync_all())
    print(json.dumps(result, indent=2))
