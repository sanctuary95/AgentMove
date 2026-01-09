import os
import json
import asyncio
import argparse
from typing import List, Optional

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

from models.llm_api import LLMWrapper


def _parse_poi_keys(poi_keys: Optional[str]) -> Optional[List[str]]:
    if poi_keys is None:
        return None
    poi_keys = poi_keys.strip()
    if not poi_keys:
        return None
    return [x.strip() for x in poi_keys.split(",") if x.strip()]


def _build_prompt(lat: float, lon: float, tool_result: dict, max_pois_for_llm: int) -> str:
    top = tool_result.get("category_counts_top", []) or []
    pois = (tool_result.get("pois", []) or [])[:max_pois_for_llm]

    payload = {
        "center": tool_result.get("center"),
        "radius_m": tool_result.get("radius_m"),
        "count": tool_result.get("count"),
        "category_counts_top": top[:15],
        "pois": pois,
    }

    return f"""You are an information extraction system.
You MUST follow the output schema. Do NOT ask questions. Do NOT add explanations.

TASK: Infer the urban functional profile around (lat={lat}, lon={lon}) using the POI JSON.

OUTPUT FORMAT (JSON only):
{{
  "summary": "2-4 sentences",
  "functional_signals": [
    {{"label": "commercial|residential|education|leisure|transport|healthcare|other", "evidence": ["...","..."]}}
  ],
  "representative_pois": [
    {{"name": "...", "category": "...", "value": "..."}}
  ]
}}

POI JSON:
{json.dumps(payload, ensure_ascii=False)}
"""


async def _fetch_pois_via_mcp(
    repo_root: str,
    lat: float,
    lon: float,
    radius_m: int,
    poi_keys: Optional[List[str]],
    name_query: Optional[str],
    limit: int,
    timeout_overpass_s: int,
    split_by_key: bool,
    compact: bool,
    include_tags: bool,
) -> dict:
    server = StdioServerParameters(
        command="python",
        args=["-m", "mcp_servers.osm_poi_server"],
        env={"PYTHONPATH": repo_root},
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            args = {
                "lat": lat,
                "lon": lon,
                "radius_m": radius_m,
                "limit": limit,
                "timeout_overpass_s": timeout_overpass_s,
                "split_by_key": split_by_key,
                "compact": compact,
                "include_tags": include_tags,
            }
            if poi_keys is not None:
                args["poi_keys"] = poi_keys
            if name_query is not None:
                args["name_query"] = name_query

            result = await session.call_tool("get_nearby_pois", args)

            text = result.content[0].text
            return json.loads(text)


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


async def main():
    parser = argparse.ArgumentParser(description="AgentMove: MCP(Overpass POI) + LLM summarization runner")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (WGS84)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (WGS84)")
    parser.add_argument("--radius-m", type=int, default=800, help="Search radius in meters (default: 800)")
    parser.add_argument(
        "--poi-keys",
        type=str,
        default=None,
        help='Comma-separated OSM keys, e.g. "amenity,tourism,shop,leisure". Default: server default.',
    )
    parser.add_argument("--name-query", type=str, default=None, help="Optional name regex query (case-insensitive)")
    parser.add_argument("--limit", type=int, default=80, help="Max elements to request from Overpass output (default: 80)")
    parser.add_argument("--timeout-overpass-s", type=int, default=60, help="Overpass server timeout in seconds (default: 60)")
    parser.add_argument("--split-by-key", action="store_true", help="Split Overpass queries by key (more stable, slower)")
    parser.add_argument("--no-split-by-key", action="store_true", help="Do not split queries by key (faster, less stable)")
    parser.add_argument("--compact", action="store_true", help="Return compact POI fields from MCP server (recommended)")
    parser.add_argument("--full", action="store_true", help="Return full POI fields from MCP server")
    parser.add_argument("--include-tags", action="store_true", help="Include OSM tags (large payload)")
    parser.add_argument("--max-pois-for-llm", type=int, default=60, help="Max POIs to include in LLM prompt (default: 60)")
    parser.add_argument("--model-name", type=str, default="GPT-OSS 20B", help='LLMWrapper model_name (default: "GPT-OSS 20B")')
    parser.add_argument("--platform", type=str, default="TogetherAI", help='LLMWrapper platform (default: "TogetherAI")')

    # NEW: output file(s)
    parser.add_argument(
        "--poi-out",
        type=str,
        default=None,
        help='Write the MCP POI result JSON to this path (e.g., "outputs/pois.json")',
    )
    parser.add_argument(
        "--llm-out",
        type=str,
        default=None,
        help='Write the LLM summary text to this path (e.g., "outputs/summary.txt")',
    )

    args = parser.parse_args()

    split_by_key = True
    if args.no_split_by_key:
        split_by_key = False
    if args.split_by_key:
        split_by_key = True

    compact = True
    if args.full:
        compact = False
    if args.compact:
        compact = True

    poi_keys = _parse_poi_keys(args.poi_keys)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    tool_result = await _fetch_pois_via_mcp(
        repo_root=repo_root,
        lat=args.lat,
        lon=args.lon,
        radius_m=args.radius_m,
        poi_keys=poi_keys,
        name_query=args.name_query,
        limit=args.limit,
        timeout_overpass_s=args.timeout_overpass_s,
        split_by_key=split_by_key,
        compact=compact,
        include_tags=args.include_tags,
    )

    # NEW: write POI json if requested
    if args.poi_out:
        _write_json(args.poi_out, tool_result)

    prompt = _build_prompt(args.lat, args.lon, tool_result, max_pois_for_llm=args.max_pois_for_llm)

    llm = LLMWrapper(model_name=args.model_name, platform=args.platform)
    out = llm.get_response(prompt)

    # print to stdout as before
    print(out)

    # NEW: write llm output if requested
    if args.llm_out:
        _write_text(args.llm_out, out)


if __name__ == "__main__":
    asyncio.run(main())