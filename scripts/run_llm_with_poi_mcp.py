import os
import json
import asyncio

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

from models.llm_api import LLMWrapper


def _build_prompt(lat: float, lon: float, tool_result: dict) -> str:
    """
    Keep prompt short: pass stats + a compact POI list (already compact).
    """
    top = tool_result.get("category_counts_top", [])
    pois = tool_result.get("pois", [])

    # limit again for safety
    pois = pois[:60]
    payload = {
        "center": tool_result.get("center"),
        "radius_m": tool_result.get("radius_m"),
        "count": tool_result.get("count"),
        "category_counts_top": top[:15],
        "pois": pois,
    }

    return f"""You are an assistant for urban structure understanding.

Given nearby POIs around (lat={lat}, lon={lon}), do:
1) Summarize the area in 2-4 sentences.
2) Provide top functional signals (e.g., residential/commercial/education/leisure).
3) List 5 representative POIs by name (if available).
Return concise bullet points.

POI JSON:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


async def main():
    # Example coordinate (you can change)
    lat, lon = 40.693834, -73.960669

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    server = StdioServerParameters(
        command="python",
        args=["-m", "mcp_servers.osm_poi_server"],
        env={"PYTHONPATH": repo_root},
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # call MCP tool
            result = await session.call_tool(
                "get_nearby_pois",
                {
                    "lat": lat,
                    "lon": lon,
                    "radius_m": 800,
                    "limit": 80,
                    "timeout_overpass_s": 60,
                    "split_by_key": True,
                    "compact": True,
                    "include_tags": False,
                },
            )

            # MCP returns content blocks; take the first text block and parse JSON
            text = result.content[0].text
            tool_result = json.loads(text)

    prompt = _build_prompt(lat, lon, tool_result)

    # LLM call (your existing wrapper)
    llm = LLMWrapper(model_name="GPT-OSS 20B", platform="TogetherAI")
    out = llm.get_response(prompt)
    print(out)


if __name__ == "__main__":
    asyncio.run(main())