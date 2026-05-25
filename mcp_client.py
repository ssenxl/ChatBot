"""
MCP Client — manages connections to MCP servers and routes tool calls.

Architecture:
  Chatbot (this client) ──HTTP──► MCP Server (docker-mcp:8000)
                         ──stdio─► Local MCP servers (excel)

Server types in mcp_config.json:
  remote  — HTTP JSON-RPC to a running MCP server
  stdio   — spawn a local process and talk via stdin/stdout
  ssh_tunnel — SSH port-forward then treat as remote
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / 'mcp_config.json'

# Built-in mapping: intent → which server holds the relevant tools
_INTENT_SERVER_MAP: Dict[str, str] = {
    'powerbi_report': 'powerbi',
    'machine_capacity': 'database',
    'item_data': 'database',
    'knitting_plan': 'database',
    'data_analysis': 'database',
    'excel_report': 'excel',
    'export_excel': 'excel',
}

# Mock data used when a real server is unreachable (dev / staging fallback)
_MOCK_RESPONSES: Dict[str, Dict] = {
    'powerbi/get_reports': {
        'success': True,
        'data': [
            {'id': 'rpt-001', 'name': 'Sales Dashboard'},
            {'id': 'rpt-002', 'name': 'Production Overview'},
            {'id': 'rpt-003', 'name': 'Inventory Report'},
        ],
    },
    'database/query_machine_capacity': {
        'success': True,
        'data': {
            'total_machines': 12,
            'available_capacity': 78,
            'machines': [
                {'name': 'Machine-01', 'status': 'running', 'capacity': 85},
                {'name': 'Machine-02', 'status': 'running', 'capacity': 72},
                {'name': 'Machine-03', 'status': 'idle', 'capacity': 0},
                {'name': 'Machine-04', 'status': 'running', 'capacity': 91},
                {'name': 'Machine-05', 'status': 'maintenance', 'capacity': 0},
            ],
        },
    },
    'database/query_items': {
        'success': True,
        'data': {
            'total_items': 150,
            'items': [
                {'id': 'ITM-001', 'name': 'ด้ายฝ้าย 40s', 'category': 'วัตถุดิบ'},
                {'id': 'ITM-002', 'name': 'ด้ายโพลีเอสเตอร์ 30s', 'category': 'วัตถุดิบ'},
                {'id': 'ITM-003', 'name': 'ผ้าถัก Plain', 'category': 'สินค้าสำเร็จรูป'},
                {'id': 'ITM-004', 'name': 'ผ้าถัก Rib', 'category': 'สินค้าสำเร็จรูป'},
                {'id': 'ITM-005', 'name': 'ผ้าถัก Interlock', 'category': 'สินค้าสำเร็จรูป'},
            ],
        },
    },
    'database/query_knitting_plan': {
        'success': True,
        'data': {
            'plans': [
                {'date': '2026-04-30', 'machine': 'Machine-01', 'item': 'ผ้าถัก Plain', 'quantity': 500},
                {'date': '2026-04-30', 'machine': 'Machine-02', 'item': 'ผ้าถัก Rib', 'quantity': 350},
                {'date': '2026-05-01', 'machine': 'Machine-01', 'item': 'ผ้าถัก Interlock', 'quantity': 420},
                {'date': '2026-05-01', 'machine': 'Machine-04', 'item': 'ผ้าถัก Plain', 'quantity': 600},
                {'date': '2026-05-02', 'machine': 'Machine-02', 'item': 'ผ้าถัก Rib', 'quantity': 380},
            ],
        },
    },
}

# Tools that always exist regardless of server connectivity
_DEFAULT_TOOLS = [
    ('powerbi', 'get_reports', 'ดึงรายการรายงาน Power BI', {}),
    ('database', 'query_machine_capacity', 'ดึงข้อมูลกำลังการผลิตเครื่องจักร', {}),
    ('database', 'query_items', 'ดึงข้อมูล items/สินค้า', {}),
    ('database', 'query_knitting_plan', 'ดึงข้อมูลแผนการทอ', {}),
    ('excel', 'create_excel_report', 'สร้างไฟล์ Excel จากข้อมูล', {
        'type': 'object',
        'properties': {
            'data': {'type': 'array', 'description': 'ข้อมูลที่จะสร้างเป็น Excel'},
            'filename': {'type': 'string', 'description': 'ชื่อไฟล์ (ไม่รวม .xlsx)'},
        },
        'required': ['data'],
    }),
    ('excel', 'read_excel_file', 'อ่านข้อมูลจากไฟล์ Excel', {
        'type': 'object',
        'properties': {'filepath': {'type': 'string', 'description': 'พาธของไฟล์'}},
        'required': ['filepath'],
    }),
    ('excel', 'append_to_excel', 'เพิ่มข้อมูลลงในไฟล์ Excel', {
        'type': 'object',
        'properties': {
            'filepath': {'type': 'string'},
            'data': {'type': 'array'},
            'sheet_name': {'type': 'string'},
        },
        'required': ['filepath', 'data'],
    }),
    ('excel', 'list_excel_files', 'แสดงรายการไฟล์ Excel ที่มีอยู่', {}),
]


@dataclass
class MCPTool:
    name: str
    description: str
    server_name: str
    input_schema: Dict = field(default_factory=dict)


class MCPClient:
    """
    Routes tool calls to the appropriate MCP server.

    Call flow:
      call_tool('powerbi/get_reports', {})
        → looks up server 'powerbi' in self.servers
        → if connected: HTTP POST to server URL
        → if not reachable: returns mock data (dev mode)
    """

    def __init__(self, config_path: str = None):
        self._config_path = Path(config_path) if config_path else _CONFIG_PATH
        self._config: Dict = {}
        self.servers: Dict[str, Dict] = {}
        self.available_tools: Dict[str, MCPTool] = {}
        self._ssh_tunnels: Dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    async def initialize_servers(self):
        self._config = self._load_config()
        servers_cfg = self._config.get('servers', {})

        for name, cfg in servers_cfg.items():
            if not cfg.get('enabled', True):
                continue
            server_type = cfg.get('type', 'remote')
            self.servers[name] = {
                'type': server_type,
                'status': 'connecting',
                'url': cfg.get('url', ''),
                'error': None,
            }
            try:
                if server_type == 'ssh_tunnel':
                    await self._open_ssh_tunnel(name, cfg)
                elif server_type == 'stdio':
                    self._verify_stdio_script(name, cfg)
                else:
                    await self._probe_remote(name, cfg)
                self.servers[name]['status'] = 'connected'
                logger.info(f"MCP server '{name}' ready")
            except Exception as exc:
                self.servers[name]['status'] = 'unavailable'
                self.servers[name]['error'] = str(exc)
                logger.warning(f"MCP server '{name}' not reachable — mock mode: {exc}")

        self._register_tools()

    async def shutdown(self):
        for name, tunnel in self._ssh_tunnels.items():
            try:
                tunnel.stop()
                logger.info(f"SSH tunnel '{name}' closed")
            except Exception as exc:
                logger.warning(f"Error closing SSH tunnel '{name}': {exc}")
        self._ssh_tunnels.clear()

    # ------------------------------------------------------------------ #
    #  Connection helpers                                                  #
    # ------------------------------------------------------------------ #

    def _load_config(self) -> Dict:
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"mcp_config.json not found at {self._config_path}")
            return {}
        except Exception as exc:
            logger.error(f"Failed to load MCP config: {exc}")
            return {}

    async def _open_ssh_tunnel(self, name: str, cfg: Dict):
        """Open SSH port-forward tunnel; update server URL to the local port."""
        try:
            from sshtunnel import SSHTunnelForwarder
        except ImportError:
            raise RuntimeError("sshtunnel not installed — run: pip install sshtunnel")

        tunnel_cfg = self._config.get('ssh_tunnel', {})
        tunnel = SSHTunnelForwarder(
            (tunnel_cfg.get('host', cfg.get('host')), tunnel_cfg.get('ssh_port', 22)),
            ssh_username=tunnel_cfg.get('username', cfg.get('username')),
            ssh_password=tunnel_cfg.get('password', cfg.get('password')),
            remote_bind_address=('127.0.0.1', tunnel_cfg.get('remote_port', 8000)),
            local_bind_address=('127.0.0.1', tunnel_cfg.get('local_port', 0)),
        )
        tunnel.start()
        self._ssh_tunnels[name] = tunnel
        local_port = tunnel.local_bind_port
        self.servers[name]['url'] = f"http://127.0.0.1:{local_port}"
        logger.info(f"SSH tunnel '{name}' → localhost:{local_port}")

    def _verify_stdio_script(self, name: str, cfg: Dict):
        """Check that the stdio server script exists."""
        args = cfg.get('args', [])
        if args:
            script = Path(args[0])
            if not script.exists():
                raise FileNotFoundError(f"stdio script not found: {script}")

    async def _probe_remote(self, name: str, cfg: Dict):
        """Send a lightweight HTTP request to verify the remote server is reachable."""
        url = cfg.get('url', '')
        if not url:
            raise ValueError(f"No URL for server '{name}'")

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._http_get, f"{url}/health", 5)
        except Exception:
            # /health might not exist — try a JSON-RPC ping instead
            try:
                await loop.run_in_executor(
                    None,
                    self._http_post,
                    f"{url}/mcp",
                    {'jsonrpc': '2.0', 'method': 'ping', 'id': 0},
                    5,
                )
            except Exception as exc:
                raise RuntimeError(f"Remote server at {url} not reachable: {exc}")

    # ------------------------------------------------------------------ #
    #  Tool registry                                                       #
    # ------------------------------------------------------------------ #

    def _register_tools(self):
        for server_name, tool_name, description, schema in _DEFAULT_TOOLS:
            key = f"{server_name}/{tool_name}"
            if key not in self.available_tools:
                self.available_tools[key] = MCPTool(
                    name=tool_name,
                    description=description,
                    server_name=server_name,
                    input_schema=schema,
                )

    def get_all_tools(self) -> List[MCPTool]:
        return list(self.available_tools.values())

    def get_tools_for_intent(self, intent: str) -> List[MCPTool]:
        """Return tools belonging to the server mapped from the given intent."""
        intents_cfg = self._config.get('intents', {})
        target_server = intents_cfg.get(intent, {}).get('mcp_server') or _INTENT_SERVER_MAP.get(intent)
        if not target_server:
            return []
        return [t for t in self.available_tools.values() if t.server_name == target_server]

    # ------------------------------------------------------------------ #
    #  Tool execution                                                      #
    # ------------------------------------------------------------------ #

    async def call_tool(self, tool_path: str, arguments: Dict) -> Dict:
        """
        Call an MCP tool.

        tool_path format: "server_name/tool_name"
        Returns: {'success': bool, 'data': ..., 'error': str}
        """
        parts = tool_path.split('/', 1)
        if len(parts) != 2:
            return {'success': False, 'error': f"Invalid tool path '{tool_path}' — expected 'server/tool'"}

        server_name, tool_name = parts
        server_info = self.servers.get(server_name, {})

        if server_info.get('status') == 'connected':
            try:
                server_type = server_info.get('type', 'remote')
                if server_type == 'stdio':
                    return await self._call_stdio_tool(server_name, tool_name, arguments)
                else:
                    return await self._call_remote_tool(server_name, tool_name, arguments, server_info)
            except Exception as exc:
                logger.warning(f"Tool call {tool_path} failed ({exc}), falling back to mock")

        # Fallback: return mock data if available
        if tool_path in _MOCK_RESPONSES:
            logger.info(f"Mock response for {tool_path}")
            return _MOCK_RESPONSES[tool_path]

        return {'success': False, 'error': f"Tool '{tool_path}' unavailable and no mock data defined"}

    async def _call_stdio_tool(self, server_name: str, tool_name: str, arguments: Dict) -> Dict:
        """Call a local stdio MCP server by invoking its Python logic directly."""
        if server_name == 'excel':
            from mcp_servers.excel_mcp_server import excel_manager
            loop = asyncio.get_event_loop()

            if tool_name == 'create_excel_report':
                filepath = await loop.run_in_executor(
                    None,
                    excel_manager.create_excel_from_data,
                    arguments.get('data', []),
                    arguments.get('filename'),
                )
                return {'success': True, 'data': {'filepath': filepath}}

            elif tool_name == 'read_excel_file':
                result = await loop.run_in_executor(
                    None,
                    excel_manager.read_excel_data,
                    arguments.get('filepath', ''),
                )
                return result

            elif tool_name == 'append_to_excel':
                result = await loop.run_in_executor(
                    None,
                    excel_manager.append_to_excel,
                    arguments.get('filepath', ''),
                    arguments.get('data', []),
                    arguments.get('sheet_name'),
                )
                return result

            elif tool_name == 'list_excel_files':
                import os
                from datetime import datetime
                folder = excel_manager.default_folder
                files = []
                if os.path.exists(folder):
                    for fn in os.listdir(folder):
                        if fn.endswith(('.xlsx', '.xls')):
                            fp = os.path.join(folder, fn)
                            files.append({
                                'filename': fn,
                                'filepath': fp,
                                'size': os.path.getsize(fp),
                                'modified': datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(),
                            })
                return {'success': True, 'data': files}

        return {'success': False, 'error': f"Unknown stdio tool: {server_name}/{tool_name}"}

    async def _call_remote_tool(
        self, server_name: str, tool_name: str, arguments: Dict, server_info: Dict
    ) -> Dict:
        """Call a remote MCP server via HTTP JSON-RPC."""
        base_url = server_info.get('url', '').rstrip('/')
        payload = {
            'jsonrpc': '2.0',
            'method': 'tools/call',
            'params': {'name': tool_name, 'arguments': arguments},
            'id': 1,
        }
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, self._http_post, f"{base_url}/mcp", payload, 10)

        if 'result' in raw:
            return {'success': True, 'data': raw['result']}
        if 'error' in raw:
            return {'success': False, 'error': raw['error'].get('message', 'Unknown error')}
        return {'success': False, 'error': 'Unexpected response from MCP server'}

    # ------------------------------------------------------------------ #
    #  Low-level HTTP helpers (sync — run via executor)                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _http_get(url: str, timeout: int = 5) -> bytes:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    @staticmethod
    def _http_post(url: str, payload: Dict, timeout: int = 10) -> Dict:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, data=data,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))


# ------------------------------------------------------------------ #
#  Singleton                                                           #
# ------------------------------------------------------------------ #

_instance: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    global _instance
    if _instance is None:
        _instance = MCPClient()
    return _instance
