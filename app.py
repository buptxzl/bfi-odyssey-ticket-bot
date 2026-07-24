import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BFI_URL = os.getenv(
    "BFI_URL",
    "https://whatson.bfi.org.uk/imax/Online/default.asp?BOparam%3A%3AWScontent%3A%3AloadArticle%3A%3Apermalink=odyssey-the-film-imax-70mm-2026",
)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CHECK_MIN_SECONDS = int(os.getenv("CHECK_MIN_SECONDS", "180"))
CHECK_MAX_SECONDS = int(os.getenv("CHECK_MAX_SECONDS", "300"))
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "900"))
STARTUP_MESSAGE = os.getenv("STARTUP_MESSAGE", "true").lower() == "true"
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("bfi-ticket-bot")

POSITIVE_PATTERNS = [
    r"book\s*(now|tickets)?",
    r"buy\s*(tickets?)?",
    r"choose\s*seats?",
    r"select\s*seats?",
    r"best\s*available",
    r"add\s*to\s*basket",
]
NEGATIVE_PATTERNS = [r"sold\s*out", r"currently\s*unavailable", r"no\s*screenings"]


def validate_config() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    if CHECK_MIN_SECONDS < 60 or CHECK_MAX_SECONDS < CHECK_MIN_SECONDS:
        raise RuntimeError("Use CHECK_MIN_SECONDS >= 60 and CHECK_MAX_SECONDS >= CHECK_MIN_SECONDS")


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_signature": "", "last_alert_at": 0.0}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def send_telegram(message: str) -> None:
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


async def inspect_page(page) -> dict[str, Any]:
    await page.goto(BFI_URL, wait_until="domcontentloaded", timeout=60_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        logger.info("Page did not become fully idle; continuing with rendered content")

    await page.wait_for_timeout(2500)
    title = await page.title()
    body_text = normalize(await page.locator("body").inner_text())

    candidates: list[dict[str, str]] = []
    elements = page.locator("a, button, [role='button']")
    count = min(await elements.count(), 500)
    for index in range(count):
        element = elements.nth(index)
        try:
            text = normalize(await element.inner_text(timeout=1000))
            if not text:
                text = normalize(await element.get_attribute("aria-label") or "")
            href = await element.get_attribute("href") or ""
            combined = f"{text} {href}".lower()
            if any(re.search(pattern, combined, re.I) for pattern in POSITIVE_PATTERNS):
                candidates.append({"text": text[:160], "href": href[:500]})
        except Exception:
            continue

    # Detect screening-like date/time rows even if the booking link wording changes.
    time_matches = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", body_text)
    date_matches = re.findall(
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?\s+\d{1,2}\s+"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
        body_text,
        flags=re.I,
    )
    negative_hits = [pattern for pattern in NEGATIVE_PATTERNS if re.search(pattern, body_text, re.I)]

    # A positive booking control is the strongest signal. Date/time content alone is treated as a weaker signal.
    available = bool(candidates)
    evidence = {
        "title": title,
        "candidates": candidates[:20],
        "times": sorted(set(time_matches))[:30],
        "dates": sorted(set(date_matches))[:30],
        "negative_hits": negative_hits,
    }
    signature = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return {
        "available": available,
        "signature": signature,
        "evidence": evidence,
        "body_excerpt": body_text[:1000],
    }


def build_alert(result: dict[str, Any]) -> str:
    evidence = result["evidence"]
    controls = evidence.get("candidates", [])
    lines = [
        "🚨 BFI IMAX《The Odyssey》可能放票了",
        "",
        "检测到可购票/选座入口，请立即打开确认：",
        BFI_URL,
    ]
    if controls:
        lines.append("")
        lines.append("页面信号：")
        for item in controls[:5]:
            label = item.get("text") or "Booking link"
            lines.append(f"• {label}")
    lines += ["", "提示：监测结果可能包含页面改版或误报，以 BFI 实际库存为准。"]
    return "\n".join(lines)


async def run() -> None:
    validate_config()
    state = load_state()
    if STARTUP_MESSAGE:
        await send_telegram("✅ BFI《The Odyssey》刷票监测已启动。发现可购买入口时会立即提醒。")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            locale="en-GB",
            timezone_id="Europe/London",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        while True:
            try:
                result = await inspect_page(page)
                now = time.time()
                changed = result["signature"] != state.get("last_signature", "")
                cooldown_passed = now - float(state.get("last_alert_at", 0)) >= ALERT_COOLDOWN_SECONDS

                logger.info(
                    "Checked page | available=%s | controls=%d | negative=%s",
                    result["available"],
                    len(result["evidence"]["candidates"]),
                    result["evidence"]["negative_hits"],
                )

                if result["available"] and (changed or cooldown_passed):
                    await send_telegram(build_alert(result))
                    state["last_alert_at"] = now

                state["last_signature"] = result["signature"]
                save_state(state)
            except Exception as exc:
                logger.exception("Check failed: %s", exc)
                try:
                    await page.close()
                    page = await context.new_page()
                except Exception:
                    pass

            delay = random.randint(CHECK_MIN_SECONDS, CHECK_MAX_SECONDS)
            logger.info("Next check in %d seconds", delay)
            await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(run())
