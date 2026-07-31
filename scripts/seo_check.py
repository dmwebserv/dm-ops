import yaml
import requests
import re
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

def fetch(url, timeout=15):
    try:
        r = requests.get(url, timeout=timeout)
        return r
    except requests.exceptions.RequestException:
        return None

def get_attr(tag_html, attr_name):
    """Extract an attribute value from a single tag's HTML, regardless of
    attribute order or quote style."""
    m = re.search(rf'{attr_name}\s*=\s*["\']([^"\']*)["\']', tag_html, re.IGNORECASE)
    return m.group(1).strip() if m else None

def find_meta_content(html, match_attr, match_value):
    """Find a <meta> tag where match_attr (name or property) equals match_value,
    regardless of attribute order, and return its content value."""
    meta_tags = re.findall(r"<meta\b[^>]*>", html, re.IGNORECASE)
    for tag in meta_tags:
        attr_val = get_attr(tag, match_attr)
        if attr_val and attr_val.strip().lower() == match_value.lower():
            content = get_attr(tag, "content")
            if content is not None:
                return content
    return None

def check_seo_signals(client):
    url = client["url"]
    hostname = urlparse(url).hostname
    result = {
        "id": client["id"],
        "name": client["name"],
        "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "findings": [],
    }

    r = fetch(url)
    if r is None or r.status_code >= 400:
        result["findings"].append({"severity": "high", "area": "availability",
                                    "detail": "Homepage did not load - SEO checks skipped."})
        return result

    html = r.text

    # Title tag
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not title_match or not title_match.group(1).strip():
        result["findings"].append({"severity": "high", "area": "title",
                                    "detail": "No <title> tag found."})
    else:
        title_len = len(title_match.group(1).strip())
        if title_len < 10 or title_len > 65:
            result["findings"].append({"severity": "medium", "area": "title",
                                        "detail": f"Title tag length is {title_len} characters (ideal range: 10-65)."})

    # Meta description (order-independent)
    meta_desc = find_meta_content(html, "name", "description")
    if not meta_desc:
        result["findings"].append({"severity": "high", "area": "meta_description",
                                    "detail": "No meta description found."})
    else:
        desc_len = len(meta_desc)
        if desc_len < 50 or desc_len > 160:
            result["findings"].append({"severity": "medium", "area": "meta_description",
                                        "detail": f"Meta description is {desc_len} characters (ideal range: 50-160)."})

    # H1 structure
    h1_matches = re.findall(r"<h1[^>]*>.*?</h1>", html, re.IGNORECASE | re.DOTALL)
    if len(h1_matches) == 0:
        result["findings"].append({"severity": "high", "area": "headings",
                                    "detail": "No H1 heading found on the page."})
    elif len(h1_matches) > 1:
        result["findings"].append({"severity": "low", "area": "headings",
                                    "detail": f"{len(h1_matches)} H1 headings found - ideally there should be exactly one."})

    # Image alt text - treat alt="" (present but empty) as acceptable (valid for
    # decorative images per accessibility standards), only flag truly missing alt attr
    img_tags = re.findall(r"<img\b[^>]*>", html, re.IGNORECASE)
    missing_alt = [img for img in img_tags if get_attr(img, "alt") is None]
    if img_tags and missing_alt:
        result["findings"].append({"severity": "medium", "area": "accessibility_seo",
                                    "detail": f"{len(missing_alt)} of {len(img_tags)} images are missing an alt attribute entirely."})

    # Open Graph tags (order-independent, property=)
    og_title = find_meta_content(html, "property", "og:title")
    og_desc = find_meta_content(html, "property", "og:description")
    og_image = find_meta_content(html, "property", "og:image")
    missing_og = [name for name, val in [("og:title", og_title), ("og:description", og_desc), ("og:image", og_image)] if not val]
    if missing_og:
        result["findings"].append({"severity": "low", "area": "social_sharing",
                                    "detail": f"Missing Open Graph tags: {', '.join(missing_og)} - affects how links look when shared on social media."})

    # Viewport / mobile meta (order-independent)
    viewport = find_meta_content(html, "name", "viewport")
    if not viewport:
        result["findings"].append({"severity": "high", "area": "mobile",
                                    "detail": "No viewport meta tag found - page may not display correctly on mobile."})

    # robots.txt and sitemap.xml
    robots_r = fetch(f"https://{hostname}/robots.txt", timeout=8)
    if robots_r is None or robots_r.status_code >= 400:
        result["findings"].append({"severity": "low", "area": "crawlability",
                                    "detail": "No robots.txt found at the expected location."})

    sitemap_r = fetch(f"https://{hostname}/sitemap.xml", timeout=8)
    if sitemap_r is None or sitemap_r.status_code >= 400:
        result["findings"].append({"severity": "low", "area": "crawlability",
                                    "detail": "No sitemap.xml found at the expected location."})

    # Word count (thin content check) - strip script/style content first so JS
    # code and CSS don't inflate or distort the count
    text_only = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text_only = re.sub(r"<[^>]+>", " ", text_only)
    word_count = len(text_only.split())
    if word_count < 200:
        result["findings"].append({"severity": "medium", "area": "content",
                                    "detail": f"Homepage has approximately {word_count} words - may be too thin for strong search visibility."})

    return result

def main():
    with open("clients.yaml") as f:
        clients = yaml.safe_load(f)["clients"]

    results = [check_seo_signals(c) for c in clients]

    os.makedirs("logs/seo", exist_ok=True)
    os.makedirs("logs/seo/history", exist_ok=True)

    with open("logs/seo/latest.json", "w") as f:
        json.dump(results, f, indent=2)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(f"logs/seo/history/{date_str}.json", "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
