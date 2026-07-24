import asyncio
import os
from playwright.async_api import async_playwright
from app import BFI_URL, build_alert, inspect_page, send_telegram, validate_config

async def main() -> None:
    validate_config()
    if os.getenv("SEND_TEST_MESSAGE", "false").lower() == "true":
        await send_telegram("✅ BFI 刷票机器人测试成功。GitHub Actions 已能向你发送 Telegram 通知。")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(locale="en-GB", timezone_id="Europe/London")
        page = await context.new_page()
        try:
            result = await inspect_page(page)
            print(f"Checked {BFI_URL} | available={result['available']} | controls={len(result['evidence']['candidates'])}")
            if result["available"]:
                await send_telegram(build_alert(result))
        finally:
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
