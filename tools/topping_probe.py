#!/usr/bin/env python3
"""Read-only BLE inventory. Does not pair, select an input or write commands."""
import argparse
import asyncio
import json


async def probe(address, seconds):
    from bleak import BleakClient, BleakScanner
    if not address:
        results = await BleakScanner.discover(timeout=seconds, return_adv=True)
        return {"devices": [{"address": device.address, "name": advert.local_name or device.name,
                             "services": advert.service_uuids}
                            for device, advert in results.values()
                            if any(word in (advert.local_name or device.name or "").lower() for word in ("topping", "e50"))]}
    async with BleakClient(address, timeout=15) as client:
        return {"address": address, "services": [{"uuid": service.uuid, "characteristics": [
            {"uuid": char.uuid, "handle": char.handle, "properties": char.properties}
            for char in service.characteristics]} for service in client.services]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", help="BLE address from a previous scan")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--input", choices=["usb", "coaxial", "optical", "bluetooth"], required=True,
                        help="Current input, selected manually; recorded only")
    args = parser.parse_args()
    try:
        result = asyncio.run(probe(args.address, args.seconds))
        result["observed_input"] = args.input
        result["proves_input_switching"] = False
        print(json.dumps(result, indent=2))
    except (ImportError, OSError, RuntimeError) as error:
        parser.exit(1, f"Bluetooth check failed: {error}\nInstall the bluetooth extra and check BlueZ/service permissions.\n")


if __name__ == "__main__":
    main()
