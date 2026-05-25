"""
Test script to verify MCP server connection to docker-mcp
"""
import asyncio
import sys
from mcp_client import get_mcp_client

async def test_connection():
    """Test connection to remote MCP server"""
    print("=" * 60)
    print("Testing MCP Server Connection to docker-mcp")
    print("=" * 60)
    
    # Get MCP client
    mcp_client = get_mcp_client()
    
    # Initialize servers
    print("\n[1/3] Initializing MCP servers...")
    await mcp_client.initialize_servers()
    
    # Check server status
    print("\n[2/3] Checking server status...")
    for server_name, server_info in mcp_client.servers.items():
        print(f"\nServer: {server_name}")
        print(f"  Type: {server_info.get('type', 'unknown')}")
        print(f"  Status: {server_info.get('status', 'unknown')}")
        if server_info.get('type') == 'remote':
            print(f"  URL: {server_info.get('url', 'N/A')}")
            if server_info.get('error'):
                print(f"  Error: {server_info.get('error')}")
    
    # List available tools
    print("\n[3/3] Available tools:")
    for tool_key, tool in mcp_client.available_tools.items():
        print(f"  - {tool_key}: {tool.description}")
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)
    
    # Shutdown
    await mcp_client.shutdown()

if __name__ == "__main__":
    asyncio.run(test_connection())
