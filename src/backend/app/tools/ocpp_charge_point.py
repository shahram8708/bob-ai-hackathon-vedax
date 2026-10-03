"""OCPP 1.6-J charge point emulator used to exercise the central system end to end.

Run with: python -m app.tools.ocpp_charge_point
"""

import asyncio
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s charge-point: %(message)s")
log = logging.getLogger("charge-point")

URL = os.environ.get("CENTRAL_SYSTEM_URL", "ws://localhost:8000/api/ocpp")
IDENTITY = os.environ.get("CHARGE_POINT_ID", "APH-C04")
PASSWORD = os.environ.get("OCPP_BASIC_AUTH_PASSWORD") or None
METER_INTERVAL = float(os.environ.get("METER_INTERVAL_SECONDS", "10"))


def ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChargePoint:
    def __init__(self, ws):
        self.ws = ws
        self.pending: dict[str, asyncio.Future] = {}
        self.meter_wh = 1_000_000.0
        self.power_w = 50_000.0
        self.transaction_id: int | None = None
        self.meter_task: asyncio.Task | None = None

    async def call(self, action: str, payload: dict) -> dict:
        mid = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        await self.ws.send(json.dumps([2, mid, action, payload]))
        return await asyncio.wait_for(fut, 20)

    async def status(self, status: str, error: str = "NoError") -> None:
        await self.call("StatusNotification", {"connectorId": 1, "errorCode": error, "status": status, "timestamp": ts()})

    async def start(self, id_tag: str) -> None:
        await self.status("Preparing")
        result = await self.call("StartTransaction", {"connectorId": 1, "idTag": id_tag, "meterStart": int(self.meter_wh), "timestamp": ts()})
        if result.get("idTagInfo", {}).get("status") != "Accepted":
            log.warning("StartTransaction rejected for %s", id_tag)
            await self.status("Available")
            return
        self.transaction_id = result["transactionId"]
        await self.status("Charging")
        self.meter_task = asyncio.create_task(self.meter_loop())
        log.info("Transaction %s started for %s", self.transaction_id, id_tag)

    async def meter_loop(self) -> None:
        while self.transaction_id is not None:
            await asyncio.sleep(METER_INTERVAL)
            self.meter_wh += self.power_w * METER_INTERVAL / 3600
            await self.call(
                "MeterValues",
                {
                    "connectorId": 1,
                    "transactionId": self.transaction_id,
                    "meterValue": [
                        {
                            "timestamp": ts(),
                            "sampledValue": [
                                {"value": f"{self.meter_wh:.0f}", "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
                                {"value": f"{self.power_w:.0f}", "measurand": "Power.Active.Import", "unit": "W"},
                            ],
                        }
                    ],
                },
            )

    async def stop(self, reason: str = "Remote") -> None:
        if self.transaction_id is None:
            return
        tx, self.transaction_id = self.transaction_id, None
        if self.meter_task:
            self.meter_task.cancel()
        await self.call("StopTransaction", {"transactionId": tx, "meterStop": int(self.meter_wh), "timestamp": ts(), "reason": reason})
        await self.status("Available")
        log.info("Transaction %s stopped (%s)", tx, reason)

    async def handle(self, mid: str, action: str, payload: dict) -> None:
        response: dict = {"status": "Accepted"}
        if action == "RemoteStartTransaction":
            profile = payload.get("chargingProfile", {}).get("chargingSchedule", {}).get("chargingSchedulePeriod", [])
            if profile:
                self.power_w = float(profile[0].get("limit", self.power_w))
            asyncio.create_task(self.start(payload.get("idTag", "")))
        elif action == "RemoteStopTransaction":
            asyncio.create_task(self.stop("Remote"))
        elif action == "SetChargingProfile":
            periods = payload.get("csChargingProfiles", {}).get("chargingSchedule", {}).get("chargingSchedulePeriod", [])
            if periods:
                self.power_w = float(periods[0].get("limit", self.power_w))
        elif action == "ChangeAvailability":
            asyncio.create_task(self.status("Available" if payload.get("type") == "Operative" else "Unavailable"))
        else:
            await self.ws.send(json.dumps([4, mid, "NotImplemented", f"{action} not supported", {}]))
            return
        await self.ws.send(json.dumps([3, mid, response]))

    async def run(self) -> None:
        reader = asyncio.create_task(self.read())
        boot = await self.call("BootNotification", {"chargePointVendor": "ChargeOpt", "chargePointModel": "Emulator-60"})
        log.info("Boot: %s", boot.get("status"))
        await self.status("Available")
        while not reader.done():
            await asyncio.sleep(boot.get("interval", 60))
            await self.call("Heartbeat", {})

    async def read(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            if msg[0] == 2:
                await self.handle(msg[1], msg[2], msg[3])
            elif msg[0] in (3, 4):
                fut = self.pending.pop(msg[1], None)
                if fut and not fut.done():
                    fut.set_result(msg[2] if msg[0] == 3 else {"error": msg[2:]})


async def main() -> None:
    headers = {}
    if PASSWORD:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{IDENTITY}:{PASSWORD}".encode()).decode()
    while True:
        try:
            async with websockets.connect(f"{URL}/{IDENTITY}", subprotocols=["ocpp1.6"], additional_headers=headers) as ws:
                log.info("Connected to %s as %s", URL, IDENTITY)
                await ChargePoint(ws).run()
        except (OSError, websockets.WebSocketException) as exc:
            log.warning("Connection lost (%s); retrying in 5 s", exc)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
