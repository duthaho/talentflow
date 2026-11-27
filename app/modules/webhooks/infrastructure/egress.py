"""Pinned-address, proxy-free HTTP sender. No second DNS lookup or redirects."""

import asyncio
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import dns.asyncresolver
import dns.exception


class EgressError(ValueError):
    def __init__(self, code: str, rule: str):
        self.code = code
        super().__init__(rule)


FORBIDDEN_ALLOWLIST = (
    "127.0.0.0/8",
    "0.0.0.0/8",
    "169.254.0.0/16",
    "::1/128",
    "::/128",
    "fe80::/10",
    "fd00:ec2::254/128",
    "::/96",
    "fec0::/10",
)


def parse_allowlist(value: str):
    try:
        networks = tuple(
            ipaddress.ip_network(x.strip(), strict=True) for x in value.split(",") if x.strip()
        )
        denied = tuple(map(ipaddress.ip_network, FORBIDDEN_ALLOWLIST))
        for network in networks:
            if any(network.version == d.version and network.overlaps(d) for d in denied):
                raise ValueError
            # Embedded IPv4 networks must never bypass IPv4 checks through an allowlist.
            if network.version == 6 and any(
                network.overlaps(ipaddress.ip_network(x))
                for x in ("::ffff:0:0/96", "64:ff9b::/96", "2002::/16")
            ):
                raise ValueError
        return networks
    except ValueError:
        raise ValueError("Invalid webhook private-network allowlist") from None


async def resolve(host: str, port: int) -> list[str]:
    # Async DNS avoids uncancellable libc resolver threads extending asyncio.run's
    # shutdown past the attempt deadline. Both A and AAAA must finish or fail closed.
    resolver = dns.asyncresolver.Resolver()

    async def addresses(record_type):
        try:
            answer = await resolver.resolve(host, record_type, lifetime=2, search=False)
            return [item.address for item in answer]
        except dns.resolver.NoAnswer:
            return []
        except dns.exception.DNSException:
            raise OSError("DNS resolution failed") from None

    records = await asyncio.gather(addresses("A"), addresses("AAAA"))
    return list(dict.fromkeys(records[0] + records[1]))


@dataclass(frozen=True)
class Target:
    url: str
    host: str
    port: int
    ip: str
    tls: bool
    path: str
    authority: str


class EgressGuard:
    def __init__(self, *, allow_http=False, allowlist=(), resolver=resolve):
        self.allow_http = allow_http
        self.allowlist = allowlist
        self.resolver = resolver

    def allowed(self, address) -> bool:
        if isinstance(address, ipaddress.IPv6Address):
            if address in ipaddress.ip_network("::/96") or address in ipaddress.ip_network(
                "fec0::/10"
            ):
                return False
            embedded = address.ipv4_mapped or address.sixtofour
            if address in ipaddress.ip_network("64:ff9b::/96"):
                embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
            if embedded is not None and not self.allowed(embedded):
                return False
        if address.is_multicast:
            return False
        return address.is_global or any(
            address.version == n.version and address in n for n in self.allowlist
        )

    async def check(self, url: str) -> Target:
        try:
            if (
                len(url) > 2048
                or any(ord(c) <= 32 or ord(c) == 127 for c in url)
                or "\\" in url
                or "#" in url
            ):
                raise ValueError
            parts = urlsplit(url)
            if parts.scheme not in ("https", "http") or (
                parts.scheme == "http" and not self.allow_http
            ):
                raise ValueError
            if not parts.hostname or parts.username is not None or parts.password is not None:
                raise ValueError
            host = parts.hostname.encode("idna").decode().lower()
            if "%" in host or host.endswith("."):
                raise ValueError
            if host == "localhost" or host.endswith(
                (".localhost", ".local", ".internal", ".home.arpa")
            ):
                raise ValueError
            port = (
                parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
            )
            if not 1 <= port <= 65535:
                raise ValueError
            try:
                literal = ipaddress.ip_address(host)
            except ValueError:
                # libc accepts numeric shorthand, octal and hexadecimal IPv4.
                if re.fullmatch(r"[0-9.]+", host) or re.fullmatch(
                    r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host
                ):
                    raise ValueError from None
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
                    raise ValueError from None
                literal = None
            else:
                if literal.version == 4 and str(literal) != host:
                    raise ValueError
                if literal.version == 6 and not parts.netloc.startswith("["):
                    raise ValueError
        except (ValueError, UnicodeError):
            raise EgressError(
                "invalid_url",
                "URL must use an allowed scheme, hostname and canonical address; no credentials, fragment or controls",
            ) from None
        try:
            addresses = (
                [str(literal)]
                if literal is not None
                else await asyncio.wait_for(self.resolver(host, port), 2)
            )
            if not addresses:
                raise OSError
        except (OSError, TimeoutError):
            raise EgressError("dns_error", "Hostname resolution failed") from None
        parsed = [ipaddress.ip_address(ip) for ip in addresses]
        if not all(self.allowed(ip) for ip in parsed):
            raise EgressError("blocked_address", "Every resolved address must be permitted")
        private_port = all(
            any(ip.version == n.version and ip in n for n in self.allowlist) for ip in parsed
        )
        if (
            port not in ((443, 8443) if parts.scheme == "https" else (80, 8080))
            and not private_port
        ):
            raise EgressError("invalid_url", "Target port is not permitted")
        authority = f"[{host}]" if ":" in host else host
        if parts.port is not None:
            authority += f":{port}"
        normalized = urlunsplit((parts.scheme, authority, parts.path or "/", parts.query, ""))
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        try:
            path.encode("ascii")
        except UnicodeError:
            raise EgressError("invalid_url", "URL path must be percent encoded") from None
        return Target(
            normalized, host, port, str(parsed[0]), parts.scheme == "https", path, authority
        )


@dataclass(frozen=True)
class Outcome:
    status_code: int | None = None
    error_code: str | None = None
    retry_after: str | None = None


class PinnedSender:
    def __init__(self, guard: EgressGuard):
        self.guard = guard

    async def send(self, url: str, headers: dict, body: bytes) -> Outcome:
        try:
            async with asyncio.timeout(10):
                return await self._send(url, headers, body)
        except EgressError as error:
            return Outcome(error_code=error.code)
        except TimeoutError:
            return Outcome(error_code="timeout")
        except ssl.SSLError:
            return Outcome(error_code="tls_error")
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return Outcome(error_code="connect_error")

    async def _send(self, url, headers, body):
        if len(body) > 256 * 1024:
            return Outcome(error_code="invalid_url")
        target = await self.guard.check(url)
        context = ssl.create_default_context() if target.tls else None
        if context:
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        # Numeric IP only. SNI/certificate verification and Host use the original hostname.
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                target.ip,
                target.port,
                ssl=context,
                server_hostname=target.host if context else None,
                family=socket.AF_INET6 if ":" in target.ip else socket.AF_INET,
            ),
            3,
        )
        try:
            wire_headers = {
                "Host": target.authority,
                "Content-Length": str(len(body)),
                "Connection": "close",
                **headers,
            }
            wire = (
                f"POST {target.path} HTTP/1.1\r\n"
                + "".join(f"{k}: {v}\r\n" for k, v in wire_headers.items())
                + "\r\n"
            )
            writer.write(wire.encode("ascii") + body)
            await writer.drain()
            header_block = await reader.readuntil(b"\r\n\r\n")
            lines = header_block.decode("iso-8859-1").split("\r\n")
            code = int(lines[0].split()[1])
            retry_after = None
            for line in lines[1:]:
                name, _, value = line.partition(":")
                if name.lower() == "retry-after":
                    retry_after = value.strip()
            # Bound total bytes and time even for infinite/chunked/dripping responses.
            remaining = 64 * 1024
            while remaining > 0:
                chunk = await reader.read(min(8192, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            error = (
                None if 200 <= code < 300 else ("redirect" if 300 <= code < 400 else "http_status")
            )
            return Outcome(code, error, retry_after)
        finally:
            writer.close()
            writer.transport.abort()
            # Abort guarantees socket cleanup without an unbounded TLS close_notify wait.
