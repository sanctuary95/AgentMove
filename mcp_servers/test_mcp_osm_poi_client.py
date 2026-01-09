import asyncio

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession


async def main():
    server = StdioServerParameters(
        command="python",
        args=["-m", "mcp_servers.osm_poi_server"],
        # ?? server ????? models ??,???????(????????)
        env={"PYTHONPATH": "."},
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # ??? initialize
            await session.initialize()

            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])

            result = await session.call_tool(
               "get_nearby_pois",
                {
                    "lat": 40.693834,
                    "lon": -73.960669,
                    "radius_m": 800,
                    "limit": 80,
                    "compact": True,
                    "include_tags": False,
                    "split_by_key": True,
                },
            )

            # result.content ??? content blocks;?? print ?????
            print(result)


if __name__ == "__main__":
    asyncio.run(main())