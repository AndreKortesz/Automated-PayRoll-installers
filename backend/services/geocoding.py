"""
Geocoding and distance calculation services
Uses Yandex Geocoder, Nominatim (OSM), and OSRM for routing
"""

import math
import asyncio
import httpx
import pandas as pd

from config import distance_cache


async def geocode_address_yandex(address: str, api_key: str) -> tuple:
    """Get coordinates from Yandex Geocoder API"""
    if not api_key:
        print(f"  ❌ Yandex API key not configured")
        return None, None
        
    try:
        async with httpx.AsyncClient() as client:
            url = "https://geocode-maps.yandex.ru/1.x/"
            params = {
                "apikey": api_key,
                "geocode": address,
                "format": "json"
            }
            print(f"  🔍 Yandex запрос: {address[:50]}...")
            response = await client.get(url, params=params, timeout=10)
            print(f"  🔍 Yandex ответ: HTTP {response.status_code}")
            if response.status_code != 200:
                print(f"  ❌ Yandex ошибка: {response.text[:200]}")
                return None, None
            data = response.json()
            
            pos = data["response"]["GeoObjectCollection"]["featureMember"]
            if pos:
                coords = pos[0]["GeoObject"]["Point"]["pos"].split()
                return float(coords[1]), float(coords[0])  # lat, lon
            print(f"  ⚠️ Yandex: нет результатов для {address[:40]}")
    except Exception as e:
        print(f"  ❌ Yandex exception: {e}")
    return None, None


async def geocode_address_nominatim(address: str) -> tuple:
    """Get coordinates from Nominatim (OpenStreetMap) - free"""
    try:
        await asyncio.sleep(1)  # Rate limiting
        async with httpx.AsyncClient() as client:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": address,
                "format": "json",
                "limit": 1
            }
            headers = {"User-Agent": "SalaryCalculator/1.0"}
            print(f"  🔍 Nominatim запрос: {address[:50]}...")
            response = await client.get(url, params=params, headers=headers, timeout=10)
            print(f"  🔍 Nominatim ответ: HTTP {response.status_code}")
            if response.status_code != 200:
                print(f"  ❌ Nominatim ошибка: {response.text[:200]}")
                return None, None
            data = response.json()
            
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
            print(f"  ⚠️ Nominatim: нет результатов для {address[:40]}")
    except Exception as e:
        print(f"  ❌ Nominatim exception: {e}")
    return None, None


async def geocode_address(address: str, api_key: str) -> tuple:
    """Get coordinates - try Yandex first, fallback to Nominatim"""
    cache_key = f"geo_{address}"
    if cache_key in distance_cache:
        return distance_cache[cache_key]
    
    lat, lon = await geocode_address_yandex(address, api_key)
    if lat and lon:
        print(f"  📍 Yandex OK: {address[:40]}... -> ({lat:.4f}, {lon:.4f})")
        distance_cache[cache_key] = (lat, lon)
        return lat, lon
    
    lat, lon = await geocode_address_nominatim(address)
    if lat and lon:
        print(f"  📍 Nominatim OK: {address[:40]}... -> ({lat:.4f}, {lon:.4f})")
        distance_cache[cache_key] = (lat, lon)
        return lat, lon
    
    print(f"  ❌ Геокодинг FAILED: {address[:50]}")
    return None, None


async def get_distance_osrm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Get driving distance in km using OSRM (free), with fallback to straight-line distance"""
    try:
        async with httpx.AsyncClient() as client:
            url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
            params = {"overview": "false"}
            response = await client.get(url, params=params, timeout=10)
            data = response.json()

            if data.get("code") == "Ok" and data.get("routes"):
                distance_meters = data["routes"][0]["distance"]
                return distance_meters / 1000
            else:
                print(f"  ⚠️ OSRM error: {data.get('code', 'unknown')} - {data.get('message', '')}")
    except httpx.TimeoutException:
        print(f"  ⚠️ OSRM timeout - using straight-line distance")
    except Exception as e:
        print(f"  ⚠️ OSRM error: {type(e).__name__}: {e}")

    # Fallback: calculate straight-line distance using Haversine formula
    # and multiply by 1.4 to approximate road distance
    R = 6371  # Earth's radius in km
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    straight_line_km = R * c

    # Road distance is typically 1.3-1.5x straight line distance
    road_distance_km = straight_line_km * 1.4
    print(f"  📏 Fallback: straight-line {straight_line_km:.1f}km × 1.4 = {road_distance_km:.1f}km")
    return road_distance_km


def is_moscow_region(address: str) -> bool:
    """Check if address is in Moscow or Moscow Oblast
    
    Logic: Consider address as Moscow/MO unless it explicitly mentions another region.
    This is because most orders are in Moscow area and addresses often don't include city name.
    """
    if not address:
        return False
    
    addr_lower = address.lower()
    
    # Explicit Moscow markers - if found, definitely Moscow
    moscow_markers = [
        "москва", "московская обл", "московской обл", "мо,", "мо ", "м.о.",
        "московский", "подмосков"
    ]
    if any(marker in addr_lower for marker in moscow_markers):
        return True
    
    # Moscow street patterns that might be confused with other cities
    # (e.g. "Севастопольский проспект" is in Moscow, not Sevastopol)
    moscow_streets = [
        "севастопольский", "крымский", "симферопольск", "ялтинск",
        "одесская", "киевское шоссе", "калининградск"
    ]
    if any(street in addr_lower for street in moscow_streets):
        return True
    
    # Explicit non-Moscow regions - if found, return False
    # But check full city names to avoid false matches with street names
    non_moscow_patterns = [
        "санкт-петербург", " спб,", " спб ", "г.спб", "г. спб",
        "ленинградская обл", "петербург",
        "краснодар", "г.сочи", "г. сочи", "новосибирск", "екатеринбург", 
        "г.казань", "г. казань", "нижний новгород", "челябинск", "самара",
        "омск", "ростов-на-дону", "г.уфа", "г. уфа", "красноярск", "пермь",
        "воронеж", "волгоград", "саратов", "тюмень", "тольятти",
        "республика крым", "г.севастополь", "г. севастополь", 
        "калининградская обл"
    ]
    
    if any(pattern in addr_lower for pattern in non_moscow_patterns):
        return False
    
    # If no explicit non-Moscow region, assume it's Moscow/MO area
    return True


async def calculate_fuel_cost(address: str, config: dict, days: int = 1) -> int:
    """Calculate fuel cost for round trip - only for Moscow and MO"""
    if not address or pd.isna(address):
        print(f"⛽ Бензин: пропуск (нет адреса)")
        return 0
    
    # Only calculate for Moscow and Moscow Oblast
    if not is_moscow_region(address):
        print(f"⛽ Бензин: пропуск (не Москва/МО): {address[:50]}")
        return 0
    
    # Add "Москва" or "Московская область" if not present for better geocoding
    addr_for_geocode = address
    if "москва" not in address.lower() and "московская" not in address.lower():
        addr_for_geocode = f"Москва, {address}"
    
    base_lat, base_lon = await geocode_address(config["base_address"], config["yandex_api_key"])
    if not base_lat:
        print(f"⛽ Бензин: не удалось геокодировать базовый адрес")
        return 0
    
    dest_lat, dest_lon = await geocode_address(addr_for_geocode, config["yandex_api_key"])
    if not dest_lat:
        print(f"⛽ Бензин: не удалось геокодировать адрес: {addr_for_geocode[:60]}")
        return 0
    
    distance = await get_distance_osrm(base_lat, base_lon, dest_lat, dest_lon)
    if distance == 0:
        print(f"⛽ Бензин: не удалось рассчитать расстояние для {address[:50]}")
        return 0
    
    cost = distance * 2 * config["fuel_coefficient"] * days
    cost = math.ceil(cost / 100) * 100
    
    result = min(cost, config["fuel_max"])
    print(f"⛽ Бензин: {address[:40]}... -> {distance:.1f} км -> {result} руб")
    return result
