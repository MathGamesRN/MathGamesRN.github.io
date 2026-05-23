"""
find_game_thumbnails.py

Reads game titles from a JS file (e.g. games.js), searches DuckDuckGo Images
for each game using Selenium, clicks each thumbnail image to open the full-size
lightbox preview, then downloads images that are:
  - Roughly 16:9 aspect ratio (±15% tolerance)
  - Resolution greater than 480p (height > 480px)
  - Any image format (jpg, png, webp, gif, etc.)

Usage:
    python find_game_thumbnails.py --js games.js [--out-dir downloaded_thumbs] [--max-per-game 3]

Requirements:
    pip install selenium pillow requests webdriver-manager
"""

import argparse
import io
import re
import time
import sys
import urllib.parse
from pathlib import Path

import requests
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

# ── Config ────────────────────────────────────────────────────────────────────
ASPECT_RATIO_TARGET    = 16 / 9
ASPECT_RATIO_TOLERANCE = 0.15
MIN_HEIGHT = 480

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── Parse game titles from JS ─────────────────────────────────────────────────

def parse_game_titles(js_path: str) -> list[str]:
    text = Path(js_path).read_text(encoding="utf-8")
    titles = re.findall(r'title\s*:\s*"([^"]+)"', text)
    if not titles:
        titles = re.findall(r"title\s*:\s*'([^']+)'", text)
    return titles


# ── Selenium ──────────────────────────────────────────────────────────────────

def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
    except ImportError:
        return webdriver.Chrome(options=opts)


def get_fullsize_urls(driver: webdriver.Chrome, query: str, max_clicks: int = 30) -> list[str]:
    """
    Load DDG image search, click each thumbnail <img> directly to open the
    lightbox, then grab the full-size image URL from the preview panel.
    """
    encoded = urllib.parse.quote_plus(query)
    driver.get(f"https://duckduckgo.com/?q={encoded}&iax=images&ia=images")
    time.sleep(3)

    # Grab thumbnail imgs — Bing-served ones are the grid tiles
    thumbs = driver.find_elements(By.CSS_SELECTOR, "img[src*='bing.net'], img[src*='duckduckgo.com/iu']")

    if not thumbs:
        thumbs = driver.find_elements(By.CSS_SELECTOR, "li img, .tile img, .tile--img img")

    if not thumbs:
        thumbs = [img for img in driver.find_elements(By.TAG_NAME, "img")
                  if not (img.get_attribute("src") or "").endswith(".ico")]

    print(f"   Found {len(thumbs)} thumbnail(s) to click")

    full_urls = []

    for thumb in thumbs[:max_clicks]:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", thumb)
            time.sleep(0.3)
            thumb.click()
            time.sleep(1.5)  # wait for lightbox to load

            url = None

            # Look for the full-size image in the detail/lightbox panel
            for selector in [
                "img.detail__media__img",
                "img.js-detail-img",
                "[data-testid='detail-image'] img",
                ".detail img",
                ".modal img",
            ]:
                for el in driver.find_elements(By.CSS_SELECTOR, selector):
                    src = el.get_attribute("src") or ""
                    if (src.startswith("http")
                            and "duckduckgo.com" not in src
                            and "bing.net/th" not in src
                            and not src.endswith(".ico")):
                        url = src
                        break
                if url:
                    break

            # Fallback: any img that appeared that isn't a thumbnail
            if not url:
                for img in driver.find_elements(By.TAG_NAME, "img"):
                    src = img.get_attribute("src") or ""
                    if (src.startswith("http")
                            and "bing.net/th" not in src
                            and "duckduckgo.com" not in src
                            and not src.endswith(".ico")):
                        url = src
                        break

            if url:
                full_urls.append(url)

        except Exception:
            continue

    return full_urls


# ── Image fetching & validation ───────────────────────────────────────────────

def fetch_image_data(url: str, timeout: int = 12) -> bytes | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type and not re.search(
            r"\.(jpg|jpeg|png|webp|gif|bmp)(\?|$)", url, re.I
        ):
            return None
        return resp.content
    except Exception:
        return None


def get_image_size(data: bytes) -> tuple[int, int] | None:
    try:
        return Image.open(io.BytesIO(data)).size
    except Exception:
        return None


def is_valid(width: int, height: int) -> bool:
    if height <= MIN_HEIGHT:
        return False
    return abs((width / height) - ASPECT_RATIO_TARGET) <= ASPECT_RATIO_TOLERANCE


def guess_ext(url: str, data: bytes) -> str:
    m = re.search(r"\.(jpg|jpeg|png|webp|gif|bmp)(\?|$)", url, re.I)
    if m:
        ext = m.group(1).lower()
        return "jpg" if ext == "jpeg" else ext
    if data[:4] == b"\x89PNG":           return "png"
    if data[:3] == b"\xff\xd8\xff":      return "jpg"
    if b"WEBP" in data[:12]:             return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"): return "gif"
    return "jpg"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Find & download 16:9 >480p game images from DDG")
    parser.add_argument("--js", required=True, help="Path to JS file with GAMES array")
    parser.add_argument("--out-dir", default="downloaded_thumbs", help="Folder to save images")
    parser.add_argument("--max-per-game", type=int, default=3, help="Max images per game")
    parser.add_argument("--max-clicks", type=int, default=30, help="Max tiles to click per game")
    parser.add_argument("--debug", action="store_true", help="Print rejection reasons")
    args = parser.parse_args()

    titles = parse_game_titles(args.js)
    if not titles:
        print("ERROR: No titles found in JS file.", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(titles)} game(s)\n")
    driver = build_driver()
    total_saved = 0

    try:
        for title in titles:
            print(f"▶  {title}")
            full_urls = get_fullsize_urls(driver, f"{title} game screenshot", args.max_clicks)
            print(f"   {len(full_urls)} full-size URL(s) extracted")

            saved = 0
            for url in full_urls:
                if saved >= args.max_per_game:
                    break

                data = fetch_image_data(url)
                if not data:
                    if args.debug:
                        print(f"   [SKIP] fetch failed: {url[:90]}")
                    continue

                size = get_image_size(data)
                if not size:
                    if args.debug:
                        print(f"   [SKIP] unreadable image: {url[:90]}")
                    continue

                w, h = size
                ratio = w / h
                if not is_valid(w, h):
                    if args.debug:
                        reason = f"height {h}<=480" if h <= MIN_HEIGHT else f"ratio {ratio:.3f} off 16:9"
                        print(f"   [FAIL] {w}×{h} — {reason}: {url[:90]}")
                    continue

                safe_title = re.sub(r'[^\w\-]', '_', title)
                ext = guess_ext(url, data)
                filename = out_dir / f"{safe_title}_{saved + 1}.{ext}"
                filename.write_bytes(data)

                print(f"   ✔ {w}×{h} (ratio {ratio:.3f})  →  {filename.name}")
                saved += 1
                total_saved += 1

            if saved == 0:
                print("   ✘ No qualifying images found")

            time.sleep(2)

    finally:
        driver.quit()

    print(f"\nDone. {total_saved} image(s) saved to '{args.out_dir}/'")


if __name__ == "__main__":
    main()