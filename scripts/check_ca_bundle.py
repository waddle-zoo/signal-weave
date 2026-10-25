"""Reject the known compromised emSign trust root (GHSA-6q48-6c7w-9gw2).

This is a targeted build/artifact regression check, not a vulnerability scanner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
from pathlib import Path

FORBIDDEN_ROOT_SHA256 = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"
# Incident roots.json includes the Sectigo/AAA cross-sign and two direct roots.
# https://emudhra.we-have-a-problem.com/roots.json
FORBIDDEN_ROOTS_SHA256 = frozenset({
    FORBIDDEN_ROOT_SHA256,
    "7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d",
    "f2edaaff3d9b701fb4d14c9f285f8c0bad90fc3bcc1fa07d47f4718edaba34a5",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
})
MIN_CERTIFI = (2026, 10, 19)


def check_bundle(path: Path, *, expected_sha256: str | None = None) -> dict:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Packaged CA bundle differs from the checked build environment")
    text = data.decode("utf-8")
    certificates = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S)
    if not certificates:
        raise ValueError("CA bundle contains no certificates")
    for certificate in certificates:
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest()
        if fingerprint in FORBIDDEN_ROOTS_SHA256:
            raise ValueError("Affected incident trust root present; rebuild with certifi>=2026.10.19")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=text)
    if context.cert_store_stats()["x509_ca"] == 0:
        raise ValueError("CA bundle contains no trusted CA certificates")
    return {"bundle_sha256": digest, "certificates": len(certificates)}


def check_installed_certifi() -> dict:
    import certifi

    version = certifi.__version__
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.post\d+)?", version)
    if match is None or tuple(map(int, match.groups())) < MIN_CERTIFI:
        raise ValueError("Build environment requires certifi>=2026.10.19; sync locked dependencies")
    return {"certifi_version": version, **check_bundle(Path(certifi.where()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", nargs="?", type=Path, help="Optional extracted native CA bundle")
    args = parser.parse_args()
    print(json.dumps(check_bundle(args.bundle) if args.bundle else check_installed_certifi()))


if __name__ == "__main__":
    main()
