#!/usr/bin/env python3
"""Test proxy list for connectivity. Reports working proxies."""

import json
import socket
import time
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import socks


TIMEOUT = 8  # seconds
MAX_WORKERS = 50

# Test targets: (host, port, label)
TARGETS = [
    ("httpbin.org", 80, "http"),
    ("httpbin.org", 443, "https"),
]


def test_proxy_tcp(proxy_url, target_host, target_port):
    """Test TCP connectivity through proxy.

    Returns latency_ms on success, None on failure.
    """
    parsed = urlparse(proxy_url)
    protocol = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port

    if protocol in ("socks5",):
        proxy_type = socks.SOCKS5
    elif protocol in ("socks4",):
        proxy_type = socks.SOCKS4
    elif protocol in ("http", "https"):
        proxy_type = socks.HTTP
    else:
        return None

    try:
        s = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.set_proxy(proxy_type, host, port)
        start = time.monotonic()
        s.connect((target_host, target_port))
        latency = (time.monotonic() - start) * 1000
        s.close()
        return round(latency)
    except Exception:
        return None


def test_proxy_http_request(proxy_url):
    """Test actual HTTP request through an HTTP proxy.

    Returns latency_ms on success, None on failure.
    """
    try:
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request(
            "http://httpbin.org/ip",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        start = time.monotonic()
        resp = opener.open(req, timeout=TIMEOUT)
        resp.read()
        latency = (time.monotonic() - start) * 1000
        return round(latency)
    except Exception:
        return None


def test_one_proxy(proxy_url):
    """Test a proxy against all targets. Returns dict of results."""
    results = {}

    # TCP tests
    for host, port, label in TARGETS:
        lat = test_proxy_tcp(proxy_url, host, port)
        results[f"tcp_{label}"] = lat

    # HTTP request test (only for http proxies)
    parsed = urlparse(proxy_url)
    if parsed.scheme in ("http", "https"):
        lat = test_proxy_http_request(proxy_url)
        results["http_req"] = lat

    return proxy_url, results


def main():
    with open("proxies.json") as f:
        proxies = json.load(f)

    proxy_urls = [p["proxy"] for p in proxies]
    total = len(proxy_urls)
    print(f"Testing {total} proxies with {MAX_WORKERS} workers (timeout={TIMEOUT}s)")
    print(f"Tests: TCP to port 80, TCP to port 443, HTTP request\n")

    all_results = []
    tested = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(test_one_proxy, url): url for url in proxy_urls}
        for future in as_completed(futures):
            tested += 1
            proxy_url, results = future.result()
            any_ok = any(v is not None for v in results.values())
            all_results.append((proxy_url, results))
            tag = "\033[32mOK\033[0m" if any_ok else "\033[31mFAIL\033[0m"
            sys.stdout.write(f"\r[{tested}/{total}] {tag} {proxy_url:<50}")
            sys.stdout.flush()

    # Summarize
    working = [(url, r) for url, r in all_results if any(v is not None for v in r.values())]
    failed = total - len(working)

    print(f"\n\n{'='*70}")
    print(f"Results: {len(working)} working / {failed} failed / {total} total")
    print(f"{'='*70}\n")

    if working:
        # Sort by best latency across any test
        working.sort(key=lambda x: min((v for v in x[1].values() if v is not None), default=99999))
        print(f"{'Proxy':<50} {'TCP:80':>8} {'TCP:443':>8} {'HTTP':>8}")
        print("-" * 78)
        for url, r in working:
            tcp80 = f"{r.get('tcp_http', '-')}ms" if r.get("tcp_http") is not None else "-"
            tcp443 = f"{r.get('tcp_https', '-')}ms" if r.get("tcp_https") is not None else "-"
            http_req = f"{r.get('http_req', '-')}ms" if r.get("http_req") is not None else "-"
            print(f"  {url:<48} {tcp80:>8} {tcp443:>8} {http_req:>8}")

        # Save working proxies
        working_list = []
        for url, r in working:
            entry = {"proxy": url}
            for k, v in r.items():
                if v is not None:
                    entry[f"latency_{k}_ms"] = v
            working_list.append(entry)
        with open("proxies_working.json", "w") as f:
            json.dump(working_list, f, indent=2)
        print(f"\nSaved {len(working)} working proxies to proxies_working.json")
    else:
        print("No working proxies found.")


if __name__ == "__main__":
    main()
