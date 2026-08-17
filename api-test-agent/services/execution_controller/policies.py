"""Egress、DNS、重定向和 SSRF 的纯函数策略；S1 不配置真实出口。"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class RegisteredTarget:
    """安全评审后才可配置的目标登记信息。"""

    target_id: str
    schemes: frozenset[str]
    hosts: frozenset[str]
    ports: frozenset[int]
    path_prefixes: tuple[str, ...] = ("/",)
    allowed_cidrs: tuple[str, ...] = ()


def validate_destination(url: str, target: RegisteredTarget, resolved_ips: list[str], *, host_header: str = "") -> tuple[bool, str]:
    """同时校验 URL、Host Header 和 DNS 结果，返回稳定拒绝原因。"""

    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.scheme not in target.schemes:
        return False, "EGRESS_SCHEME_OR_USERINFO_DENIED"
    host = (parsed.hostname or "").rstrip(".").lower()
    if host not in {item.rstrip(".").lower() for item in target.hosts}:
        return False, "EGRESS_HOST_DENIED"
    if host_header and host_header.split(":", 1)[0].rstrip(".").lower() != host:
        return False, "HOST_HEADER_MISMATCH"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in target.ports:
        return False, "EGRESS_PORT_DENIED"
    if not any(parsed.path.startswith(prefix) for prefix in target.path_prefixes):
        return False, "EGRESS_PATH_DENIED"
    allowed_networks = [ipaddress.ip_network(cidr, strict=False) for cidr in target.allowed_cidrs]
    if not resolved_ips:
        return False, "DNS_RESULT_EMPTY"
    for raw_ip in resolved_ips:
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError:
            return False, "DNS_RESULT_INVALID"
        if address == ipaddress.ip_address("169.254.169.254") or address == ipaddress.ip_address("fd00:ec2::254"):
            return False, "METADATA_ADDRESS_DENIED"
        blocked = address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved or address.is_private
        if blocked and not any(address in network for network in allowed_networks):
            return False, "SSRF_ADDRESS_DENIED"
    return True, "ALLOWED"


def validate_redirect(url: str, target: RegisteredTarget, resolved_ips: list[str]) -> tuple[bool, str]:
    """每次重定向重新执行完整目的地址校验。"""

    return validate_destination(url, target, resolved_ips)
