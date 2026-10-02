import hashlib
import ipaddress
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _parse_networks(raw: str):
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if not part or part.lower() == "none":
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.error("Ignoring invalid TRUSTED_PROXIES entry: %r", part)
    return nets


TRUSTED_NETWORKS = _parse_networks(settings.TRUSTED_PROXIES)
KEY_HASHES = {
    h.strip().lower() for h in settings.API_KEY_HASHES.split(",") if h.strip()
}


def _is_trusted(ip) -> bool:
    return any(ip in net for net in TRUSTED_NETWORKS)


def _bucket_form(ip) -> str:
    """Normalize so one attacker can't rotate addresses to get fresh buckets."""
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        # A single customer typically owns a whole /64, so bucket by /64
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def client_ip(peer: str | None, forwarded_for: str | None) -> str:
    """
    Resolve the real client IP.

    X-Forwarded-For is only honored when the direct TCP peer is a trusted proxy.
    We then walk the header from the RIGHT (the part our own proxies appended)
    and stop at the first address that is not a trusted proxy. Anything to the
    left of that point is client-supplied and is never used.
    """
    try:
        peer_ip = ipaddress.ip_address(peer)
    except (ValueError, TypeError):
        return "unknown"

    if not forwarded_for or not _is_trusted(peer_ip):
        return _bucket_form(peer_ip)

    candidate = peer_ip
    for part in reversed([p.strip() for p in forwarded_for.split(",")]):
        if not _is_trusted(candidate):
            break
        try:
            candidate = ipaddress.ip_address(part)
        except ValueError:
            break
    return _bucket_form(candidate)


def key_identity(api_key: str) -> str | None:
    """
    Returns a stable bucket id for a VALID key, or None if the key is unknown.
    Only a hash prefix is used as the id, so raw keys never reach Redis or logs.
    """
    if not api_key or len(api_key) > 256:
        return None
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    if digest in KEY_HASHES:
        return f"key:{digest[:16]}"
    return None