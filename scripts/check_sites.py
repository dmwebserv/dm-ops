import yaml
import requests
import ssl
import socket
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

def check_ssl_expiry(hostname):
    ctx = ssl.create_default_context()
    with socket.create_connection((hostname, 443), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert = ssock.getpeercert()
            expiry = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            return (expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days

def extract_links(html, base_url):
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html)
    links = set()
    for h in hrefs:
        if h.startswith('#') or h.startswith('mailto:') or h.startswith('tel:') or h.startswith('javascript:'):
            continue
        links.add(urljoin(base_url, h))
    return links

def check_links(base_url, html):
    broken = []
    links = extract_links(html, base_url)
    same_site = [l for l in links if urlparse(l).hostname == urlparse(base_url).hostname]
    for link in list(same_site)[:30]:  # cap to keep runtime/cost sane
        try:
            r = requests.head(link, timeout=8, allow_redirects=True)
            if r.status_code >= 400:
                r = requests.get(link, timeout=8)  # some servers reject HEAD
            if r.status_code >= 400:
                broken.append({"url": link, "status": r.status_code})
        except requests.exceptions.RequestException:
            broken.append({"url": link, "status": "unreachable"})
    return broken

def check_forms(html):
    forms = re.findall(r'<form\b', html, re.IGNORECASE)
    if not forms:
        return {"found": False, "count": 0}
    return {"found": True, "count": len(forms)}

def check_site(client):
    url = client['url']
    hostname = urlparse(url).hostname
    result = {
        "id": client['id'], "name": client['name'], "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok", "http_status": None, "response_time_ms": None,
        "ssl_days_left": None, "broken_links": [], "form_check": None,
        "errors": []
    }
    html = ""
    try:
        r = requests.get(url, timeout=15)
        result["http_status"] = r.status_code
        result["response_time_ms"] = int(r.elapsed.total_seconds() * 1000)
        html = r.text
        if r.status_code >= 500:
            result["status"] = "urgent"; result["errors"].append(f"Server error: {r.status_code}")
        elif r.status_code >= 400:
            result["status"] = "needs_review"; result["errors"].append(f"Client error: {r.status_code}")
    except requests.exceptions.RequestException as e:
        result["status"] = "urgent"; result["errors"].append(f"Site unreachable: {str(e)}")
        return result  # nothing else to check if the site itself is down

    try:
        days_left = check_ssl_expiry(hostname)
        result["ssl_days_left"] = days_left
        if days_left < 7:
            result["status"] = "urgent"; result["errors"].append(f"SSL expires in {days_left} days")
        elif days_left < 21:
            if result["status"] == "ok": result["status"] = "needs_review"
            result["errors"].append(f"SSL expires in {days_left} days")
    except Exception as e:
        result["errors"].append(f"SSL check failed: {str(e)}")

    if html:
        broken = check_links(url, html)
        result["broken_links"] = broken
        if broken:
            if result["status"] == "ok": result["status"] = "needs_review"
            result["errors"].append(f"{len(broken)} broken link(s) found")

        form_info = check_forms(html)
        result["form_check"] = form_info
        if not form_info["found"]:
            if result["status"] == "ok": result["status"] = "needs_review"
            result["errors"].append("No <form> tag detected on homepage")

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
