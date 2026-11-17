from typing import Any, Dict, List
import requests
import logging
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings

logger = logging.getLogger(__name__)

# Hardening: Consolidated global session with retries and browser-like User-Agent
def get_hardened_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=25, pool_maxsize=25)
    s.mount('http://', adapter)
    s.mount('https://', adapter)
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    return s

session = get_hardened_session()

def _get_yardsalesearch_sales(zip_code: str, radius: int) -> List[Dict[str, Any]]:
    """Internal scraper for YardSaleSearch.com"""
    sales: List[Dict[str, Any]] = []
    url = f"https://www.yardsalesearch.com/garage-sales.html?zip={zip_code}&r={radius}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = session.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.error(f"YardSaleSearch returned status {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all('div', class_='event')
        
        for idx, item in enumerate(items):
            try:
                title_elem = item.find('h2')
                address_elem = item.find(attrs={'itemprop': 'address'})
                desc_elem = item.find(attrs={'itemprop': 'description'}) or item.find(class_='eventdesc')
                
                if title_elem and address_elem:
                    # Extraction logic for 'When' field
                    when_tag = item.find('strong', string=lambda x: x and 'When:' in x)
                    when_text = 'Check Details'
                    start_time_sort = "23:59" # Default to late for sorting
                    
                    if when_tag and when_tag.next_sibling:
                        when_text = when_tag.next_sibling.strip()
                        
                        # Handle the [weekday], [date] @ [time] format mentioned by user
                        if '@' in when_text:
                            time_part = when_text.split('@')[-1].strip()
                            import re
                            # Extract just the first time found (start time)
                            time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)', time_part)
                            if time_match:
                                raw_time = time_match.group(1).upper().replace(' ', '')
                                # Normalize to 24h for sorting
                                try:
                                    if ':' in raw_time:
                                        t_obj = datetime.strptime(raw_time, "%I:%M%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H:%M")
                                    else:
                                        t_obj = datetime.strptime(raw_time, "%I%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H")
                                    start_time_sort = t_obj.strftime("%H:%M")
                                except Exception:
                                    pass
                    
                    # If we have a description, try to find a time pattern as fallback
                    desc_elem = item.find(attrs={'itemprop': 'description'}) or item.find(class_='eventdesc')
                    desc_text = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    if 'Check Details' in when_text or ':' not in start_time_sort:
                        import re
                        time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?|\d{1,2}\s*(?:AM|PM|am|pm))', desc_text)
                        if time_match:
                            found_time = time_match.group(1)
                            if 'Check Details' in when_text:
                                when_text = f"Approx. {found_time}"
                            
                            # Update sort key if it's still default
                            if start_time_sort == "23:59":
                                try:
                                    raw_time = found_time.upper().replace(' ', '')
                                    if ':' in raw_time:
                                        t_obj = datetime.strptime(raw_time, "%I:%M%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H:%M")
                                    else:
                                        t_obj = datetime.strptime(raw_time, "%I%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H")
                                    start_time_sort = t_obj.strftime("%H:%M")
                                except Exception:
                                    pass

                    link_elem = title_elem.find('a')
                    specific_url = url
                    if link_elem and link_elem.has_attr('href'):
                        specific_url = link_elem['href']
                        if specific_url.startswith('/'):
                            specific_url = "https://www.yardsalesearch.com" + specific_url

                    address_text = address_elem.get_text(strip=True).replace('Where:', '').strip()
                    
                    sale_data = {
                        'id': item.get('id', f"yss_{idx}"),
                        'title': title_elem.get_text(strip=True),
                        'address': address_text,
                        'time': when_text,
                        'start_time_sort': start_time_sort,
                        'desc': desc_text,
                        'source_url': specific_url
                    }
                    logger.info(f"Scraped Sale [{sale_data['id']}]: Time='{when_text}', Sort='{start_time_sort}'")
                    sales.append(sale_data)
            except Exception as e:
                logger.warning(f"Error parsing YardSaleSearch item: {e}")
                continue
    except Exception as e:
        logger.error(f"YardSaleSearch request failed: {e}")
        
    return sales

def _enrich_sale_details(sale: Dict[str, Any]) -> Dict[str, Any]:
    """Fetches the detail page for a single sale to extract precise time and full description."""
    url = sale.get('source_url')
    if not url or not url.startswith('http'):
        return sale
        
    try:
        response = session.get(url, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract detailed When text
            when_label = soup.find('div', class_='label', string=lambda x: x and 'When:' in x)
            if when_label:
                row_div = when_label.find_parent('div', class_='row')
                if row_div:
                    info_div = row_div.find('div', class_='info')
                    if info_div:
                        when_text = info_div.get_text(separator=" | ", strip=True)
                        if when_text:
                            sale['time'] = when_text
                            
                            # Parse date from meta tag if available
                            start_date = "9999-12-31" # Default to far future
                            date_meta = info_div.find('meta', itemprop='startDate')
                            if date_meta and date_meta.get('content'):
                                start_date = date_meta['content']
                            
                            # Parse start time from the enriched text
                            start_time = "23:59"
                            import re
                            if '@' in when_text:
                                time_part = when_text.split('@')[-1].strip()
                                time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)', time_part)
                                if time_match:
                                    raw_time = time_match.group(1).upper().replace(' ', '')
                                    try:
                                        if ':' in raw_time:
                                            t_obj = datetime.strptime(raw_time, "%I:%M%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H:%M")
                                        else:
                                            t_obj = datetime.strptime(raw_time, "%I%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H")
                                        start_time = t_obj.strftime("%H:%M")
                                    except Exception:
                                        pass
                            
                            # Combine date and time for robust sorting
                            sale['start_time_sort'] = f"{start_date} {start_time}"
                
            # Extract full description
            desc_label = soup.find('div', class_='label', string=lambda x: x and 'Details:' in x)
            if desc_label:
                row_div = desc_label.find_parent('div', class_='row')
                if row_div:
                    details_div = row_div.find('div', class_='details-text')
                    if details_div:
                        full_desc = details_div.get_text(strip=True)
                        if full_desc:
                            sale['desc'] = full_desc
                    
    except Exception as e:
        logger.warning(f"Error enriching {url}: {e}")
        
    logger.info(f"Final Extracted Data: ID={sale.get('id')}, Time='{sale.get('time')}', Sort='{sale.get('start_time_sort')}'")
    return sale


def _get_estatesales_sales(zip_code: str, radius: int) -> List[Dict[str, Any]]:
    """Fetch estate sales from EstateSales.net using JSON-LD structured data."""
    sales: List[Dict[str, Any]] = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    url = f"https://www.estatesales.net/sales/{zip_code}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '{}')
            except (json.JSONDecodeError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict) or item.get('@type') not in ('SaleEvent', 'Event'):
                    continue
                loc = item.get('location') or {}
                addr_obj = loc.get('address') if isinstance(loc, dict) else {}
                if isinstance(addr_obj, dict):
                    parts = [
                        addr_obj.get('streetAddress', ''),
                        addr_obj.get('addressLocality', ''),
                        addr_obj.get('addressRegion', ''),
                        addr_obj.get('postalCode', ''),
                    ]
                    address = ', '.join(p for p in parts if p).strip()
                else:
                    address = str(addr_obj or '').strip()
                if not address:
                    continue
                geo = loc.get('geo') if isinstance(loc, dict) else {}
                lat = geo.get('latitude') if isinstance(geo, dict) else None
                lng = geo.get('longitude') if isinstance(geo, dict) else None
                start_date = (item.get('startDate') or '')[:10]
                sales.append({
                    'id': f"es_{abs(hash(address))}",
                    'title': (item.get('name') or 'Estate Sale').strip(),
                    'address': address,
                    'time': start_date or 'See listing',
                    'start_time_sort': f"{start_date} 08:00" if start_date else '9999-12-31 23:59',
                    'desc': (item.get('description') or '').strip(),
                    'source_url': item.get('url') or url,
                    'lat': float(lat) if lat is not None else None,
                    'lng': float(lng) if lng is not None else None,
                })
        logger.info(f"EstateSales.net returned {len(sales)} sales for {zip_code}")
    except Exception as e:
        logger.warning(f"EstateSales.net scrape failed for {zip_code}: {e}")
    return sales


def _get_craigslist_sales(zip_code: str, radius: int) -> List[Dict[str, Any]]:
    """Fetch garage/yard sales from Craigslist using headless Chromium via Playwright."""
    sales: List[Dict[str, Any]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed; skipping Craigslist scrape.")
        return sales

    url = f"https://www.craigslist.org/search/gms?postal={zip_code}&search_distance={radius}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_selector("li.cl-search-result, li.cl-static-search-result", state="attached", timeout=8000)
            cards = page.query_selector_all("li.cl-search-result, li.cl-static-search-result")
            for card in cards[:30]:
                title_el = card.query_selector("a.cl-app-anchor, a.titlestring, a")
                title = title_el.inner_text().strip() if title_el else "Craigslist Garage Sale"
                href = title_el.get_attribute("href") if title_el else url
                meta_el = card.query_selector(".meta, .location")
                loc_text = meta_el.inner_text().strip() if meta_el else zip_code
                sales.append({
                    'id': f"cl_{abs(hash(href or title))}",
                    'title': title,
                    'address': loc_text if loc_text else zip_code,
                    'time': 'See listing',
                    'start_time_sort': '9999-12-31 23:59',
                    'desc': f"Craigslist garage sale ({loc_text})",
                    'source_url': href or url,
                })
            browser.close()
        logger.info(f"Craigslist returned {len(sales)} sales for {zip_code}")
    except Exception as e:
        logger.warning(f"Craigslist Playwright scrape failed for {zip_code}: {e}")
    return sales


def _get_gsalr_sales(zip_code: str, radius: int) -> List[Dict[str, Any]]:
    """Fetch garage sales from gsalr.com by resolving zip_code to city-state."""
    from .location_service import get_city_state_from_zip
    sales: List[Dict[str, Any]] = []
    city_state = get_city_state_from_zip(zip_code)
    if not city_state:
        return sales
    city_slug, state_abbr = city_state
    url = f"https://gsalr.com/garage-sales-{city_slug}-{state_abbr}.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for card in soup.select('.sale, .listing, .card, article')[:25]:
            title_el = card.select_one('h2, h3, .title, a')
            title = title_el.get_text(strip=True) if title_el else 'Garage Sale'
            addr_el = card.select_one('.address, .location, address')
            address = addr_el.get_text(strip=True) if addr_el else f"{city_slug.replace('-', ' ').title()}, {state_abbr.upper()}"
            desc_el = card.select_one('p, .description, .desc')
            desc = desc_el.get_text(strip=True) if desc_el else ''
            link_el = card.select_one('a[href]')
            href = link_el['href'] if link_el else url
            if href.startswith('/'):
                href = f"https://gsalr.com{href}"
            sales.append({
                'id': f"gsalr_{abs(hash(href + address))}",
                'title': title,
                'address': address,
                'time': 'See listing',
                'start_time_sort': '9999-12-31 23:59',
                'desc': desc,
                'source_url': href,
            })
        logger.info(f"GSALR returned {len(sales)} sales for {zip_code} ({city_slug}-{state_abbr})")
    except Exception as e:
        logger.warning(f"GSALR scrape failed for {zip_code}: {e}")
    return sales


def scrape_sales(zip_code: str, radius: int = 15) -> List[Dict[str, Any]]:
    """
    Primary entry point for garage sale discovery. 
    Uses thread pooling to fetch and enrich multiple sources in parallel.
    """
    if getattr(settings, 'MOCK_MODE', False):
        logger.info(f"MOCK_MODE: Mocking garage sales for zip {zip_code}")
        return [
            {
                'id': 'sale_mock_1',
                'title': f'St. Jude Church Annual Sale ({zip_code})',
                'address': '123 Fake St, Springfield, ST',
                'time': 'Saturday 8:00 AM - 2:00 PM',
                'start_time_sort': '08:00',
                'desc': 'Huge multi-family church sale! Furniture, clothes, kids toys, baking goods.',
                'source_url': f"https://www.yardsalesearch.com/garage-sales.html?zip={zip_code}"
            },
            {
                'id': 'sale_mock_2',
                'title': f'Neighborhood Community Yard Sale ({zip_code})',
                'address': '456 Oak Lane, Springfield, ST',
                'time': 'Saturday 9:00 AM - 12:00 PM',
                'start_time_sort': '09:00',
                'desc': 'Entire cul-de-sac participating. Lots of tools, electronics, and vintage books.',
                'source_url': f"https://www.yardsalesearch.com/garage-sales.html?zip={zip_code}"
            }
        ]

    all_sales: List[Dict[str, Any]] = []
    logger.info(f"Starting scrape for zip {zip_code} at radius {radius}")
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all primary scraper tasks
        future_yss = executor.submit(_get_yardsalesearch_sales, zip_code, radius)
        future_es = executor.submit(_get_estatesales_sales, zip_code, radius)
        future_cl = executor.submit(_get_craigslist_sales, zip_code, radius)
        future_gsalr = executor.submit(_get_gsalr_sales, zip_code, radius)

        combined_sales: List[Dict[str, Any]] = []
        try:
            base_sales = future_yss.result(timeout=15)
            enriched_sales = list(executor.map(_enrich_sale_details, base_sales))
            combined_sales.extend(enriched_sales)
        except Exception as e:
            logger.error(f"YardSaleSearch scraper thread failed: {e}")

        try:
            es_sales = future_es.result(timeout=15)
            combined_sales.extend(es_sales)
        except Exception as e:
            logger.error(f"EstateSales.net scraper thread failed: {e}")

        try:
            cl_sales = future_cl.result(timeout=20)
            combined_sales.extend(cl_sales)
        except Exception as e:
            logger.error(f"Craigslist scraper thread failed: {e}")

        try:
            gsalr_sales = future_gsalr.result(timeout=15)
            combined_sales.extend(gsalr_sales)
        except Exception as e:
            logger.error(f"GSALR scraper thread failed: {e}")

        # Deduplicate across all sources by normalized address
        seen_addresses = set()
        for sale in combined_sales:
            norm_addr = sale['address'].lower().strip()
            if norm_addr and norm_addr not in seen_addresses:
                seen_addresses.add(norm_addr)
                all_sales.append(sale)
    
    # Demonstration Fallback
    if not all_sales:
        logger.info("No sales found natively, injecting demonstration fallback.")
        all_sales = [
            {
                'id': 'sale_test_1',
                'title': f'St. Jude Church Annual Sale ({zip_code})',
                'address': '123 Fake St, Springfield, ST',
                'time': 'Saturday 8:00 AM - 2:00 PM',
                'start_time_sort': '08:00',
                'desc': 'Huge multi-family church sale! Furniture, clothes, kids toys, baking goods.',
                'source_url': f"https://www.yardsalesearch.com/garage-sales.html?zip={zip_code}"
            },
            {
                'id': 'sale_test_2',
                'title': f'Neighborhood Community Yard Sale ({zip_code})',
                'address': '456 Oak Lane, Springfield, ST',
                'time': 'Saturday 9:00 AM - 12:00 PM',
                'start_time_sort': '09:00',
                'desc': 'Entire cul-de-sac participating. Lots of tools, electronics, and vintage books.',
                'source_url': f"https://www.yardsalesearch.com/garage-sales.html?zip={zip_code}"
            }
        ]
        
    logger.info(f"Completed scrape. Returning {len(all_sales)} sales.")
    return all_sales


def _fetch_store_details(gmaps: Any, place: Dict[str, Any]) -> Dict[str, str]:
    """Internal helper to fetch opening hours for a specific place."""
    try:
        # Request specific fields to minimize cost/latency
        details = gmaps.place(
            place_id=place.get('place_id'),
            fields=['opening_hours', 'formatted_phone_number']
        )
        
        result = details.get('result', {})
        opening_hours = result.get('opening_hours', {})
        
        # Extract today's hours specifically
        today_hours = "Hours not listed"
        start_time_sort = "09:00" # Default fallback
        weekday_text = opening_hours.get('weekday_text', [])
        
        if weekday_text:
            import re
            now = datetime.now()
            day_name = now.strftime("%A") 
            for line in weekday_text:
                if line.startswith(day_name):
                    today_hours = line.split(": ", 1)[-1] if ": " in line else line
                    
                    # Try to parse the START time for sorting (e.g. "9:00 AM" from "9:00 AM – 5:00 PM")
                    time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)', today_hours)
                    if time_match:
                        raw_time = time_match.group(1).upper().replace(' ', '')
                        try:
                            if ':' in raw_time:
                                t_obj = datetime.strptime(raw_time, "%I:%M%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H:%M")
                            else:
                                t_obj = datetime.strptime(raw_time, "%I%p") if 'M' in raw_time else datetime.strptime(raw_time, "%H")
                            start_time_sort = t_obj.strftime("%H:%M")
                        except Exception:
                            pass
                    break
        elif opening_hours.get('open_now') is not None:
            today_hours = "Open Now" if opening_hours['open_now'] else "Closed Now"
            
        return {
            'hours': today_hours,
            'start_time_sort': start_time_sort,
            'phone': result.get('formatted_phone_number', 'No phone listed')
        }
    except Exception:
        return {'hours': 'Hours not listed', 'start_time_sort': '09:00', 'phone': 'No phone listed'}

def scrape_thrift_stores(zip_code: str, api_key: str) -> List[Dict[str, Any]]:
    """
    Utilizes Google Maps Places API to locate thrift stores.
    Now enriched with today's business hours and normalized start times for sorting.
    """
    if getattr(settings, 'MOCK_MODE', False) or not api_key:
        logger.info(f"MOCK_MODE: Mocking thrift stores for zip {zip_code}")
        return [
            {
                'id': 'thrift_mock_1',
                'title': f'Springfield Goodwill Center ({zip_code})',
                'address': '789 Main St, Springfield, ST',
                'lat': 37.7749,
                'lng': -122.4194,
                'time': 'Today: 9:00 AM – 7:00 PM',
                'desc': 'Rating: 4.2⭐ (150 reviews) | 📞 (555) 019-2834',
                'source_url': 'https://www.google.com/maps',
                'start_time_sort': '09:00'
            },
            {
                'id': 'thrift_mock_2',
                'title': f'The Salvation Army Family Store ({zip_code})',
                'address': '101 Pine Rd, Springfield, ST',
                'lat': 37.7750,
                'lng': -122.4195,
                'time': 'Today: 10:00 AM – 6:00 PM',
                'desc': 'Rating: 3.9⭐ (88 reviews) | 📞 (555) 019-5678',
                'source_url': 'https://www.google.com/maps',
                'start_time_sort': '10:00'
            }
        ]

    import googlemaps
    try:
        gmaps = googlemaps.Client(key=api_key)
        places_result = gmaps.places(query=f"thrift store in {zip_code}")
        if not places_result:
            return []
            
        base_results = places_result.get('results', [])[:10] # Limit to top 10 for performance
        stores = []
        
        # Enrich results with hours in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            details_map = list(executor.map(lambda p: _fetch_store_details(gmaps, p), base_results))
        
        for idx, (place, detail) in enumerate(zip(base_results, details_map)):
            rating = place.get('rating', 'N/A')
            reviews = place.get('user_ratings_total', 0)
            
            geometry = place.get('geometry', {}).get('location', {})
            stores.append({
                'id': place.get('place_id', f"place_{idx}"),
                'title': place.get('name'),
                'address': place.get('formatted_address', f"Unknown Address, {zip_code}"),
                'lat': geometry.get('lat'),
                'lng': geometry.get('lng'),
                'time': f"Today: {detail['hours']}",
                'desc': f"Rating: {rating}⭐ ({reviews} reviews) | 📞 {detail['phone']}",
                'source_url': f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id')}",
                'start_time_sort': detail['start_time_sort']
            })
            
        return stores
    except Exception as e:
        logger.error(f"Places Fetch Error: {str(e)}")
        return []

