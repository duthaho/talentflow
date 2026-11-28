"""Regression checks for local Compose runtime configuration."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_keycloak_healthcheck_allows_first_start_augmentation() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())

    assert compose["services"]["keycloak"]["healthcheck"]["start_period"] == "8m"


def test_careers_proxy_and_clamd_fail_closed_configuration():
    import ipaddress

    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    web_ip = compose["services"]["web"]["networks"]["default"]["ipv4_address"]
    ipam = compose["networks"]["default"]["ipam"]["config"][0]
    subnet = ipaddress.ip_network(ipam["subnet"])
    dynamic_pool = ipaddress.ip_network(ipam.get("ip_range", ipam["subnet"]))
    assert dynamic_pool.subnet_of(subnet)
    assert ipaddress.ip_address(web_ip) in subnet
    assert ipaddress.ip_address(web_ip) not in dynamic_pool
    cidr = compose["services"]["api"]["environment"]["RATE_LIMIT_TRUSTED_PROXY_CIDRS"]
    network = ipaddress.ip_network(cidr)
    assert network.prefixlen == 32 and str(network.network_address) == web_ip
    assert ipaddress.ip_address("172.29.127.1") not in network
    configuration = Path("clamd-intake.conf").read_text()
    for directive in (
        "AlertExceedsMax yes",
        "AlertEncrypted yes",
        "MaxScanSize 20M",
        "MaxRecursion 8",
    ):
        assert directive in configuration
    assert (
        "./clamd-intake.conf:/etc/clamav/clamd.conf:ro" in compose["services"]["clamav"]["volumes"]
    )
