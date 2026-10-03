import asyncio
import base64
import hmac

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.deps import user_from_token
from app.core.config import get_settings
from app.core.security import SESSION_COOKIE
from app.db.session import SessionLocal
from app.services.events import Client, hub
from app.services.ocpp.central import serve

router = APIRouter()


def _authenticate(token: str | None):
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        return (user.id, user.role_code) if user else None
    finally:
        db.close()


@router.websocket("/ws")
async def events(socket: WebSocket):
    token = socket.cookies.get(SESSION_COOKIE)
    identity = await asyncio.to_thread(_authenticate, token)
    if identity is None:
        await socket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await socket.accept()
    client = Client(socket=socket, user_id=identity[0], role=identity[1])
    hub.register(client)

    async def pump() -> None:
        while True:
            message = await client.queue.get()
            await socket.send_text(message)

    sender = asyncio.create_task(pump())
    try:
        await socket.send_json({"topic": "hello", "payload": {}})
        while True:
            message = await socket.receive_text()
            if message == "ping":
                await socket.send_text('{"topic":"pong","payload":{}}')
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        hub.unregister(client)


@router.websocket("/ocpp/{identity}")
async def ocpp(socket: WebSocket, identity: str):
    requested = socket.headers.get("sec-websocket-protocol", "")
    if "ocpp1.6" not in [p.strip() for p in requested.split(",")]:
        await socket.close(code=status.WS_1002_PROTOCOL_ERROR)
        return
    secret = get_settings().ocpp_basic_auth_password
    if secret:
        header = socket.headers.get("authorization", "")
        try:
            user, _, password = base64.b64decode(header.removeprefix("Basic ").strip()).decode().partition(":")
        except ValueError:
            user, password = "", ""
        if user != identity or not hmac.compare_digest(password, secret):
            await socket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    await socket.accept(subprotocol="ocpp1.6")
    try:
        await serve(identity, socket)
    except WebSocketDisconnect:
        pass
