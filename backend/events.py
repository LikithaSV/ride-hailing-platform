import asyncio
import json
from collections import defaultdict


class EventBus:
    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, tenant_id: str):
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._queues[tenant_id].append(queue)
        return queue

    def unsubscribe(self, tenant_id: str, queue: asyncio.Queue):
        queues = self._queues.get(tenant_id, [])
        if queue in queues:
            queues.remove(queue)

    async def publish(self, tenant_id: str, event_type: str, payload: dict):
        data = json.dumps({"event_type": event_type, "payload": payload})
        for queue in list(self._queues.get(tenant_id, [])):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await queue.put(data)


event_bus = EventBus()
