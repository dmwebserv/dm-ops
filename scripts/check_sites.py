import yaml
import requests
import ssl
import socket
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

def check_ssl_expiry(hostname):
    ctx = ssl.create_default_context()
    with socket.create_connection((hostname, 443), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert = ssock.getpeercert()
            expiry = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            days_left = (expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
            return days_left

def check_site(client):
    url = client['url']
    hostname = urlparse(url).hostname
    result = {
        "id": client['id'],
        "name": client['name'],
        "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "unknown",
        "http_status": None,
        "response_time_ms": None,
        "ssl_days_left": None,
        "errors": []
    }
    try:
        r = requests.get(url, timeout=15)
        result["http_status"] = r.status_code
        result["response_time_ms"] = int(r.elapsed.total_seconds() * 1000)
        if r.status_code >= 500:
            result["status"] = "urgent"
            result["errors"].append(f"Server error: {r.status_code}")
        elif r.status_code >= 400:
            result["status"] = "needs_review"
            result["errors"].append(f"Client error: {r.status_code}")
        else:
            result["status"] = "ok"
    except requests.exceptions.RequestException as e:
        result["status"] = "urgent"
        result["errors"].append(f"Site unreachable: {str(e)}")

    try:
        days_left = check_ssl_expiry(hostname)
        result["ssl_days_left"] = days_left
        if days_left < 7:
            result["status"] = "urgent"
            result["errors"].append(f"SSL expires in {days_left} days")
        elif days_left < 21:
            if result["status"] == "ok":
                result["status"] = "needs_review"
            result["errors"].append(f"SSL expires in {days_left} days")
    except Exception as e:
        result["errors"].append(f"SSL check failed: {str(e)}")

    return result

def main():
    with open('clients.yaml') as f:
        data = yaml.safe_load(f)

    results = [check_site(c) for c in data['clients']]

    with open('logs/latest.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
