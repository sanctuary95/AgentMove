from __future__ import annotations

from dataclasses import asdict
from collections import Counter
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from models.osm_poi import fetch_pois_osm_overpass, POI


mcp = FastMCP("AgentMove-OSM-POI")


def _poi_to_compact(p: POI) -> Dict[str, Any]:
    return {
        "osm_type": p.osm_type,
        "osm_id": p.osm_id,
        "lat": p.lat,
        "lon": p.lon,
        "name": p.name,
        "category": p.category,
        "value": p.value,
    }


def _pois_to_jsonable(pois: List[POI], compact: bool, include_tags: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in pois:
        d = _poi_to_compact(p) if compact else asdict(p)
        if not include_tags:
            d.pop("tags", None)
        out.append(d)
    return out


@mcp.tool()
def get_nearby_pois(
    lat: float,
    lon: float,
    radius_m: int = 500,
    poi_keys: Optional[List[str]] = None,
    name_query: Optional[str] = None,
    limit: int = 120,
    timeout_overpass_s: int = 25,
    split_by_key: bool = True,
    compact: bool = True,
    include_tags: bool = False,
) -> Dict[str, Any]:
    """
    OSM POI query tool (Overpass).
    Default is compact output for LLM friendliness.
    """
    pois = fetch_pois_osm_overpass(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        poi_keys=poi_keys,
        name_query=name_query,
	osm_types=["node"],
        limit=limit,
        timeout_overpass_s=timeout_overpass_s,
        split_by_key=split_by_key,
    )

    counts = Counter(f"{p.category}={p.value}" for p in pois if p.category and p.value)
    top_counts = [{"type": k, "count": v} for k, v in counts.most_common(30)]

    return {
        "center": {"lat": lat, "lon": lon},
        "radius_m": radius_m,
        "count": len(pois),
        "category_counts_top": top_counts,
        "pois": _pois_to_jsonable(pois, compact=compact, include_tags=include_tags),
    }


def main() -> None:
    # stdio server
    mcp.run()


if __name__ == "__main__":
    main()