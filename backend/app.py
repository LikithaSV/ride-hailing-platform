import asyncio
import datetime as dt
import json
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.config import settings
from backend.db import Base, engine
from backend.events import event_bus
from backend.models import EventLog
from backend.routes import drivers, payments, rides, trips

if settings.new_relic_enabled and os.path.exists("newrelic.ini"):
    import newrelic.agent

    newrelic.agent.initialize("newrelic.ini")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rides.router, prefix=settings.api_prefix)
app.include_router(drivers.router, prefix=settings.api_prefix)
app.include_router(trips.router, prefix=settings.api_prefix)
app.include_router(payments.router, prefix=settings.api_prefix)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": settings.app_name}


@app.get("/v1/stream")
async def stream_events(tenant_id: str = Query(..., min_length=1)):
    queue = event_bus.subscribe(tenant_id)

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    heartbeat = json.dumps(
                        {
                            "event_type": "stream.heartbeat",
                            "payload": {"tenant_id": tenant_id, "ts": dt.datetime.utcnow().isoformat()},
                        }
                    )
                    yield f"data: {heartbeat}\n\n"
                    continue
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            event_bus.unsubscribe(tenant_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
