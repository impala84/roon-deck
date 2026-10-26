"""Validate generated profiles with the appliance's real NetworkManager parser.

Offline only: never creates an interface, changes routes or installs packages.
"""
import base64
import subprocess
import uuid

from pi_bus_time_display.remote_access import keyfile, parse_profile


def main():
    dummy = base64.b64encode(bytes(range(32))).decode()
    profile = f"""[Interface]
PrivateKey={dummy}
Address=10.20.30.2/32,fd00::2/128
DNS=192.168.1.1
[Peer]
PublicKey={dummy}
PresharedKey={dummy}
AllowedIPs=0.0.0.0/0,::/0
Endpoint=vpn.example.com:51820
"""
    for mode, subnets in (("full", ""), ("split", "192.168.1.0/24,fd00:1::/64")):
        text = keyfile(parse_profile(profile, mode, subnets), str(uuid.uuid4()))
        result = subprocess.run(["nmcli", "--offline", "connection", "modify", "connection.autoconnect", "no"],
                                input=text, text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise RuntimeError("NetworkManager rejected the generated " + mode + " profile: " + result.stderr)
        assert "type=wireguard" in result.stdout
    print("Accessory smoke: full/split IPv4+IPv6 profiles accepted by the real NetworkManager parser; no networking changed.")


if __name__ == "__main__": main()
