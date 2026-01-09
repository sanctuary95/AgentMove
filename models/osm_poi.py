from __future__ import annotations

import time
import random
import requests
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Iterable, Tuple


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

RETRY_STATUS = {429, 502, 503, 504}


@dataclass
class POI:
    osm_type: str
    osm_id: int
    lat: float
    lon: float
    name: str
    category: str
    value: str
    tags: Dict[str, Any]


def _build_overpass_query(
    lat: float,
    lon: float,
    radius_m: int,
    poi_keys: List[str],
    name_query: Optional[str],
    limit: int,
    timeout_s: int,
    osm_types: List[str],  # NEW
) -> str:
    name_filter = ""
    if name_query:
        safe = name_query.replace('"', '\\"')
        name_filter = f'["name"~"(?i){safe}"]'

    # Normalize + validate types
    allowed = {"node", "way", "relation"}
    osm_types_norm = [t.strip().lower() for t in osm_types if t and t.strip()]
    osm_types_norm = [t for t in osm_types_norm if t in allowed]
    if not osm_types_norm:
        osm_types_norm = ["node", "way", "relation"]

    blocks: List[str] = []
    for k in poi_keys:
        for t in osm_types_norm:
            # Example:
            # node(around:800,40.69,-73.96)["amenity"]["name"~"(?i)foo"];
            blocks.append(f'{t}(around:{radius_m},{lat},{lon})["{k}"]{name_filter};')

    union = "\n  ".join(blocks)

    return f"""
[out:json][timeout:{timeout_s}];
(
  {union}
);
out center {limit};
""".strip()


def _post_overpass_with_retry(
    ql: str,
    endpoints: List[str] = OVERPASS_ENDPOINTS,
    max_attempts_per_endpoint: int = 3,
    base_backoff_s: float = 1.0,
    timeout_http_s: int = 60,
) -> Dict[str, Any]:
    last_exc: Optional[Exception] = None

    for ep in endpoints:
        for attempt in range(1, max_attempts_per_endpoint + 1):
            try:
                resp = requests.post(ep, data={"data": ql}, timeout=timeout_http_s)
                if resp.status_code in RETRY_STATUS:
                    sleep_s = base_backoff_s * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    time.sleep(sleep_s)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                if isinstance(e, requests.HTTPError):
                    status = getattr(e.response, "status_code", None)
                    if status is not None and status not in RETRY_STATUS:
                        break
                sleep_s = base_backoff_s * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                time.sleep(sleep_s)

    raise RuntimeError(f"All Overpass endpoints failed. Last error: {last_exc!r}")


def _parse_elements_to_pois(elements: Iterable[Dict[str, Any]], poi_keys: List[str]) -> List[POI]:
    pois: List[POI] = []
    for el in elements:
        tags = el.get("tags", {}) or {}

        if "lat" in el and "lon" in el:
            el_lat, el_lon = float(el["lat"]), float(el["lon"])
        else:
            center = el.get("center") or {}
            if "lat" not in center or "lon" not in center:
                continue
            el_lat, el_lon = float(center["lat"]), float(center["lon"])

        category = ""
        value = ""
        for k in poi_keys:
            if k in tags:
                category = k
                value = str(tags.get(k))
                break

        pois.append(
            POI(
                osm_type=str(el.get("type", "")),
                osm_id=int(el.get("id", 0)),
                lat=el_lat,
                lon=el_lon,
                name=str(tags.get("name", "")),
                category=category,
                value=value,
                tags=tags,
            )
        )
    return pois


def fetch_pois_osm_overpass(
    lat: float,
    lon: float,
    radius_m: int = 500,
    poi_keys: Optional[List[str]] = None,
    name_query: Optional[str] = None,
    limit: int = 200,
    timeout_overpass_s: int = 25,
    split_by_key: bool = False,
    osm_types: Optional[List[str]] = None,  # NEW
) -> List[POI]:
    if poi_keys is None:
        poi_keys = ["amenity", "tourism", "shop", "leisure"]

    if osm_types is None:
        osm_types = ["node", "way", "relation"]

    all_elements: List[Dict[str, Any]] = []

    if not split_by_key:
        ql = _build_overpass_query(lat, lon, radius_m, poi_keys, name_query, limit, timeout_overpass_s, osm_types)
        data = _post_overpass_with_retry(ql)
        all_elements.extend(data.get("elements", []) or [])
    else:
        for k in poi_keys:
            ql = _build_overpass_query(lat, lon, radius_m, [k], name_query, limit, timeout_overpass_s, osm_types)
            data = _post_overpass_with_retry(ql)
            all_elements.extend(data.get("elements", []) or [])

    pois = _parse_elements_to_pois(all_elements, poi_keys)

    uniq: Dict[Tuple[str, int], POI] = {}
    for p in pois:
        uniq[(p.osm_type, p.osm_id)] = p

    return list(uniq.values())


def pois_to_text(pois: List[POI], max_items: int = 80) -> str:
    """
    Turn POIs into a compact, LLM-friendly text (avoid dumping huge tags).
    """
    pois_sorted = sorted(pois, key=lambda p: (p.category, p.value, p.name))
    lines: List[str] = []
    for p in pois_sorted[:max_items]:
        nm = p.name.strip() or "[no-name]"
        lines.append(f"- name={nm} | {p.category}={p.value} | lat={p.lat:.6f} lon={p.lon:.6f}")
    if len(pois_sorted) > max_items:
        lines.append(f"... ({len(pois_sorted) - max_items} more omitted)")
    return "\n".join(lines)