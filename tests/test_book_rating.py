import os
import re
import time
import json
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _click_first_that_exists(driver, xpaths, timeout_each=3):
    """Click the first element that exists in a list of XPath selectors."""
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, timeout_each).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            el.click()
            return True
        except Exception:
            continue
    return False


def _set_max_price(driver, max_price):
    """Set max price in the price filter if available."""
    try:
        inputs = driver.find_elements(By.XPATH, "//input[@aria-label and (contains(@aria-label,'Precio máximo') or contains(@aria-label,'Maximum price'))]")
        if inputs:
            inputs[0].clear()
            inputs[0].send_keys(str(int(max_price)))
            inputs[0].submit()
            time.sleep(0.5)
            return True
    except Exception:
        pass
    return False


def _apply_min_rating_filter(driver):
    """Apply min rating chip if available."""
    try:
        _click_first_that_exists(driver, [
            "//a[contains(@aria-label,'4 estrellas') or contains(@aria-label,'4 stars')]",
            "//span[contains(text(),'4 estrellas') or contains(text(),'4 stars')]/ancestor::a",
        ], timeout_each=2)
    except Exception:
        pass


def _collect_product_links(driver, max_scrolls=5, limit=50):
    """Scroll and collect /shopping/product/ links."""
    links = set()
    for _ in range(max_scrolls):
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'/shopping/product/')]")
        for a in anchors:
            href = a.get_attribute("href")
            if href and "/shopping/product/" in href:
                links.add(href.split("&sa=")[0])
        if len(links) >= limit:
            break
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(0.5)
    return list(links)


def _extract_rating_from_text(text: str):
    """Extract a numeric rating from a string if between 0 and 5."""
    if not text:
        return None
    m = re.search(r"\b(\d+(?:[.,]\d+)?)\b", text)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", "."))
        return val if 0.0 <= val <= 5.0 else None
    except ValueError:
        return None


def _read_rating_from_jsonld(driver):
    """Extract rating from JSON-LD script tags."""
    scripts = driver.find_elements(By.XPATH, "//script[@type='application/ld+json']")
    for s in scripts:
        try:
            raw = s.get_attribute("textContent") or ""
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
                payloads = data if isinstance(data, list) else [data]
            except Exception:
                m = re.search(r'"ratingValue"\s*:\s*"?(?P<val>\d+(?:[.,]\d+)?)"?', raw, flags=re.I)
                if m:
                    val = float(m.group("val").replace(",", "."))
                    if 0.0 <= val <= 5.0:
                        return val
                continue

            def dig(obj):
                if isinstance(obj, dict):
                    if "aggregateRating" in obj and isinstance(obj["aggregateRating"], dict):
                        rv = obj["aggregateRating"].get("ratingValue")
                        if rv:
                            try:
                                val = float(str(rv).replace(",", "."))
                                if 0.0 <= val <= 5.0:
                                    return val
                            except ValueError:
                                pass
                    for v in obj.values():
                        r = dig(v)
                        if r is not None:
                            return r
                elif isinstance(obj, list):
                    for it in obj:
                        r = dig(it)
                        if r is not None:
                            return r
                return None

            out = dig(payloads)
            if out is not None and 0.0 <= out <= 5.0:
                return out
        except Exception:
            continue
    return None


def _read_rating_in_current_view(driver):
    """
    Lee rating en la página actual priorizando JSON-LD (aggregateRating.ratingValue).
    Si no, prueba metas / aria-labels / textos y también 'store ratings' en páginas de ofertas.
    """
    # 1) JSON-LD
    r = _read_rating_from_jsonld(driver)
    if r is not None:
        return r

    # 2) Metas clásicas
    patterns_meta = [
        "//meta[@itemprop='ratingValue']",
        "//meta[@property='og:rating' or @name='rating']",
    ]
    for xp in patterns_meta:
        for el in driver.find_elements(By.XPATH, xp):
            val = el.get_attribute("content") or el.get_attribute("value")
            rr = _extract_rating_from_text(val or "")
            if rr is not None:
                return rr

    # 3) aria-labels/textos visibles (product rating)
    patterns = [
        "//span[@aria-label and (contains(.,'out of 5') or contains(.,'de 5') or contains(.,'stars') or contains(.,'estrellas'))]",
        "//div[@aria-label and (contains(.,'out of 5') or contains(.,'de 5') or contains(.,'stars') or contains(.,'estrellas'))]",
        "//*[@role='img' and @aria-label and (contains(.,'star') or contains(.,'estrella'))]",
        "//span[contains(@class,'Rsc7Yb') and @aria-label]",
        "//span[contains(@class,'QIrs8') and @aria-label]",
        "//*[contains(translate(normalize-space(.),'RATING','rating'),'rating') and not(self::script)]",
    ]
    for xp in patterns:
        for el in driver.find_elements(By.XPATH, xp):
            label = (el.get_attribute("aria-label") or el.get_attribute("content") or el.text or "").strip()
            rr = _extract_rating_from_text(label)
            if rr is not None:
                return rr

    # 4) STORE RATING (páginas /offers): textos tipo "Store rating", "Seller rating", "Calificación de la tienda"
    store_patterns = [
        "//*[contains(translate(., 'STORE', 'store'),'store rating') or contains(translate(., 'SELLER', 'seller'),'seller rating') or contains(.,'Calificación de la tienda')]",
        # chips/atributos con "out of 5" cerca de vendedor
        "//*[contains(.,'out of 5') or contains(.,'de 5')][ancestor::*[contains(.,'Seller') or contains(.,'Store') or contains(.,'Tienda')]]",
    ]
    for xp in store_patterns:
        for el in driver.find_elements(By.XPATH, xp):
            text = (el.get_attribute("aria-label") or el.text or "").strip()
            rr = _extract_rating_from_text(text)
            if rr is not None:
                return rr

    # 5) Fallback regex sobre el HTML completo
    try:
        html = driver.page_source
        m = re.search(r'"ratingValue"\s*:\s*"?(?P<val>\d+(?:[.,]\d+)?)"?', html, flags=re.I)
        if m:
            val = float(m.group("val").replace(",", "."))
            if 0.0 <= val <= 5.0:
                return val
    except Exception:
        pass

    return None



def _get_second_rated_by_visiting_products(driver, max_products=50, min_rating=4.0):
    """
    Visita hasta N fichas internas, lee rating y devuelve
    el **segundo rating que cumple** >= min_rating.
    Ignora valores fuera de rango/ruido.
    """
    links = _collect_product_links(driver, max_scrolls=12, limit=max_products * 2)
    print(f"🔗 Enlaces shopping detectados: {len(links)}")
    qualified = []
    seen = 0

    if not links:
        return None

    list_url = driver.current_url
    for idx, href in enumerate(links[:max_products], start=1):
        print(f"→ Visitando producto #{idx}: {href}")
        try:
            driver.get(href)
        except Exception:
            driver.get(href)

        time.sleep(0.9)
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//*")))
        except Exception:
            pass

        r = _read_rating_in_current_view(driver)
        print(f"   rating leído: {r}")
        seen += 1

        # aceptamos solo ratings plausibles y >= umbral
        if r is not None and 0.0 <= r <= 5.0 and r >= float(min_rating):
            qualified.append(r)
            print(f"   ✅ califica (≥ {min_rating}). Acumulados: {len(qualified)}")
            if len(qualified) == 2:
                # volver a la lista y entregar el segundo calificado
                try:
                    driver.get(list_url)
                except Exception:
                    pass
                return qualified[1]

        # regresar a la lista para el siguiente
        try:
            driver.get(list_url)
        except Exception:
            pass

    print(f"❌ No se alcanzaron 2 ratings ≥ {min_rating}. Hallados: {qualified} (vistos: {seen})")
    return None




# ------------------------------------------------------------
# Test principal
# ------------------------------------------------------------

def test_book_rating(go_to_google_shopping):
    driver = go_to_google_shopping

    max_price = float(os.getenv("MAX_PRICE", "1000"))
    min_rating = float(os.getenv("MIN_RATING", "4.0"))

    # Ordenar High→Low si está disponible
    _click_first_that_exists(driver, [
        "//button[@aria-label='Ordenar por']",
        "//button[@aria-label='Sort by']",
        "//span[normalize-space()='Ordenar por']/ancestor::button",
        "//span[normalize-space()='Sort by']/ancestor::button",
    ], timeout_each=3)
    _click_first_that_exists(driver, [
        "//div[@role='menu']//span[normalize-space()='Precio: de mayor a menor']",
        "//div[@role='menu']//span[normalize-space()='Price: High to Low']",
    ], timeout_each=3)
    time.sleep(0.6)

    # Precio máximo
    _set_max_price(driver, max_price)
    time.sleep(0.6)

    # Chip ≥ 4★
    _apply_min_rating_filter(driver)

    # Scroll inicial
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight*0.3);")
    time.sleep(0.5)

    # Obtener segundo rating
    second_rating = _get_second_rated_by_visiting_products(driver, max_products=50, min_rating=min_rating)

    assert second_rating is not None, "No se encontró un segundo producto con rating visible visitando fichas."
    assert second_rating >= min_rating, f"El segundo producto tiene rating {second_rating}, menor a {min_rating}"
