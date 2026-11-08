"""Discrete original-LSX input commands for a configured Broadlink IR remote.

KEF's published NEC bytes are transmitted MSB-first (confirmed against captured
original remotes and physically tested with AUX on an original LSX).
Reference: https://assets.kef.com/pdf_doc/LSX/LSX-IRcode-INT.pdf
"""
import base64

INPUT_CODES = {"wifi": 0x30, "bluetooth": 0x2A, "aux": 0x02, "optical": 0x0A}


def input_command(source):
    if source not in INPUT_CODES: raise ValueError("Choose a supported KEF input")
    code = INPUT_CODES[source]
    timings = [9000, 4500]
    for byte in (0x01, 0xFE, code, code ^ 0xFF):
        for bit in range(7, -1, -1):
            timings.extend((560, 1690 if byte & (1 << bit) else 560))
    timings.extend((560, 40000, 9000, 2250, 560))
    body = bytearray()
    for duration in timings:
        ticks = round(duration * 269 / 8192)
        body.extend(bytes((ticks,)) if ticks < 256 else b"\x00" + ticks.to_bytes(2, "big"))
    body.extend(b"\x0d\x05")
    packet = b"\x26\x00" + len(body).to_bytes(2, "little") + body
    packet += b"\x00" * (-len(packet) % 16)
    return "b64:" + base64.b64encode(packet).decode("ascii")
