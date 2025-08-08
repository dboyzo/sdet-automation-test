import os
import time
import pytest
from datetime import datetime
from urllib.parse import quote_plus

import allure
from allure_commons.types import AttachmentType

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from selenium.webdriver.common.by import By

# Chrome
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChService
from webdriver_manager.chrome import ChromeDriverManager

# Firefox
from selenium.webdriver.firefox.options import Options as FFOptions
from selenium.webdriver.firefox.service import Service as FFService
from webdriver_manager.firefox import GeckoDriverManager

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ======================================================================
# CLI options
# ======================================================================
def pytest_addoption(parser):
    parser.addoption("--headless", action="store", default="False", help="True/False")
    parser.addoption("--browser", action="store", default="firefox", help="firefox|chrome")


# ======================================================================
# Drivers
# ======================================================================
def _build_chrome(headless: bool):
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0 Safari/537.36"
    )
    # carga rápida (no espera recursos pesados)
    opts.page_load_strategy = "eager"

    driver = webdriver.Chrome(service=ChService(ChromeDriverManager().install()), options=opts)
    try:
        # ocultar navigator.webdriver
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
    except Exception:
        pass
    return driver


def _build_firefox(headless: bool):
    opts = FFOptions()
    if headless:
        opts.add_argument("-headless")
    # reducir señales de automatización
    opts.set_preference("dom.webdriver.enabled", False)
    opts.set_preference("useAutomationExtension", False)
    opts.set_preference(
        "general.useragent.override",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
    )
    driver = webdriver.Firefox(service=FFService(GeckoDriverManager().install()), options=opts)
    driver.set_window_size(1440, 900)
    return driver


# ======================================================================
# Browser fixture con fallback
# ======================================================================
@pytest.fixture(scope="session")
def browser(request):
    headless = str(request.config.getoption("--headless")).lower() == "true"
    which = (request.config.getoption("--browser") or "firefox").lower().strip()

    driver = None
    try:
        if which == "chrome":
            print("🧭 Lanzando Chrome…")
            driver = _build_chrome(headless)
        else:
            print("🧭 Lanzando Firefox…")
            driver = _build_firefox(headless)
    except (SessionNotCreatedException, WebDriverException) as e:
        # Fallback
        print(f"⚠️  No se pudo iniciar {which} ({e.__class__.__name__}). Haciendo fallback a Chrome…")
        driver = _build_chrome(headless)

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(0)
    yield driver
    driver.quit()


# ======================================================================
# CAPTCHA helper
# ======================================================================
def _captcha_present(driver):
    try:
        if driver.find_elements(By.XPATH, "//iframe[contains(@src,'recaptcha')]"):
            return True
        # textos comunes
        if driver.find_elements(By.XPATH, "//*[contains(.,'I am not a robot') or contains(.,'No soy un robot')]"):
            return True
        if driver.find_elements(By.XPATH, "//*[contains(.,'verify') and contains(.,'human')]"):
            return True
    except Exception:
        pass
    return False


def _wait_if_captcha(driver, timeout=120):
    """
    Si aparece reCAPTCHA, espera hasta 'timeout' a que el usuario lo resuelva manualmente.
    """
    start = time.time()
    if _captcha_present(driver):
        print("⚠️  reCAPTCHA detectado. Márcalo manualmente… (tienes hasta {}s)".format(timeout))
    while time.time() - start < timeout:
        if not _captcha_present(driver):
            print("✅ reCAPTCHA superado.")
            return
        time.sleep(2)
    # No forzamos fallo aquí: dejamos que el siguiente wait decida.


# ======================================================================
# Navegación a Google Shopping
# ======================================================================
@pytest.fixture()
def go_to_google_shopping(browser):
    book = os.getenv("BOOK_NAME", "Harry Potter")
    q = quote_plus(f"book {book}")

    # EN/US Shopping (más estable). Forzamos udm=14, pero Google puede mutar a 28.
    url = f"https://www.google.com/search?q={q}&tbm=shop&hl=en&gl=us&pws=0&udm=14"
    print(f"➡️  Navigating to: {url}")
    browser.get(url)

    # Reaplicar si Google elimina tbm=shop
    if "tbm=shop" not in browser.current_url:
        print("⚠️  Re-adding tbm=shop…")
        browser.get(url)

    # Manejo de CAPTCHA (espera manual)
    _wait_if_captcha(browser, timeout=180)

    # Intentos de verificación de que Shopping cargó
    for attempt in range(1, 4):
        try:
            WebDriverWait(browser, 30).until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        # cualquier contenedor de resultados o link de producto de shopping
                        "//div[@id='search']//div[@data-hveid or @data-docid or @data-id]"
                        " | //a[contains(@href,'/shopping/product/')]",
                    )
                )
            )
            print("✅ Shopping loaded")
            return browser
        except Exception:
            print(f"↻ Reintento {attempt}/3 (recargando Shopping)…")
            browser.get(url)
            _wait_if_captcha(browser, timeout=180)

    pytest.skip("No se pudo cargar Google Shopping (bloqueo o CAPTCHA no resuelto).")


# ======================================================================
# Screenshot en fallos + Allure
# ======================================================================
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item):
    """
    Adjunta screenshot al fallo (fase 'call') si hay un driver disponible.
    """
    outcome = yield
    report = outcome.get_result()

    if report.when != "call":
        return

    if report.failed:
        driver = item.funcargs.get("browser")
        if not driver:
            return
        try:
            os.makedirs("screenshots", exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = os.path.join("screenshots", f"FAIL_{item.name}_{ts}.png")
            driver.save_screenshot(path)
            with open(path, "rb") as f:
                allure.attach(f.read(), name=f"Screenshot_{ts}", attachment_type=AttachmentType.PNG)
            print(f"🖼️  Screenshot guardado: {path}")
        except Exception as e:
            print(f"⚠️  No se pudo adjuntar screenshot: {e}")
