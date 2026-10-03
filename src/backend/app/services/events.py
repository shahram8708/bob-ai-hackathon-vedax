import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

log = logging.getLogger("chargeopt.events")


@dataclass(eq=False)
class Client:
    socket: WebSocket
    user_id: int
    role: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=200))


class EventHub:
    def __init__(self) -> None:
        self._clients: set[Client] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def register(self, client: Client) -> None:
        self._clients.add(client)

    def unregister(self, client: Client) -> None:
        self._clients.discard(client)

    def publish(self, topic: str, payload: dict | None = None) -> None:
        if self._loop is None or not self._clients:
            return
        message = json.dumps({"topic": topic, "payload": payload or {}}, default=str)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._fan_out(message)
        else:
            self._loop.call_soon_threadsafe(self._fan_out, message)

    def _fan_out(self, message: str) -> None:
        for client in list(self._clients):
            try:
                client.queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("Dropping slow websocket client %s", client.user_id)
                self._clients.discard(client)


hub = EventHub()
