#!/usr/bin/env python3
"""Test proxy list for connectivity. Reports working proxies."""

import json
import socket
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import socks


TIMEOUT = 5  # seconds
TEST_HOST = "httpbin.org"
TEST_PORT = 443
MAX_WORKERS = 50


def test_proxy(proxy_url):
    """Test if a proxy can establish a TCP connection to TEST_HOST:TEST_PORT.

    Returns (proxy_url, latency_ms) on success, (proxy_url, None) on failure.
    """
    parsed = urlparse(proxy_url)
    protocol = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port

    # Map protocol to socks type
    if protocol in ("socks5",):
        proxy_type = socks.SOCKS5
    elif protocol in ("socks4",):
        proxy_type = socks.SOCKS4
    elif protocol in ("http", "https"):
        proxy_type = socks.HTTP
    else:
        return proxy_url, None

    try:
        s = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.set_proxy(proxy_type, host, port)
        start = time.monotonic()
        s.connect((TEST_HOST, TEST_PORT))
        latency = (time.monotonic() - start) * 1000
        s.close()
        return proxy_url, round(latency)
    except Exception:
        return proxy_url, None


def main():
    with open("proxies.json") as f:
        proxies = json.load(f)

    proxy_urls = [p["proxy"] for p in proxies]
    total = len(proxy_urls)
    print(f"Testing {total} proxies with {MAX_WORKERS} workers (timeout={TIMEOUT}s)...")
    print(f"Target: {TEST_HOST}:{TEST_PORT}\n")

    working = []
    failed = 0
    tested = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(test_proxy, url): url for url in proxy_urls}
        for future in as_completed(futures):
            tested += 1
            proxy_url, latency = future.result()
            if latency is not None:
                working.append((proxy_url, latency))
                status = f"\033[32mOK\033[0m {latency:>5}ms"
            else:
                failed += 1
                status = f"\033[31mFAIL\033[0m"
            # Progress line
            sys.stdout.write(f"\r[{tested}/{total}] {status} {proxy_url:<45}")
            sys.stdout.flush()

    print(f"\n\n{'='*60}")
    print(f"Results: {len(working)} working / {failed} failed / {total} total")
    print(f"{'='*60}\n")

    if working:
        # Sort by latency
        working.sort(key=lambda x: x[1])
        print("Working proxies (sorted by latency):\n")
        for url, lat in working:
            print(f"  {lat:>5}ms  {url}")

        # Save working proxies
        working_list = [{"proxy": url, "latency_ms": lat} for url, lat in working]
        with open("proxies_working.json", "w") as f:
            json.dump(working_list, f, indent=2)
        print(f"\nSaved {len(working)} working proxies to proxies_working.json")
    else:
        print("No working proxies found.")


if __name__ == "__main__":
    main()
