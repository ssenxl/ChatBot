import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_TENANT_ID = os.getenv('AZURE_TENANT_ID')
_CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
_CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
_USERNAME = os.getenv('PBI_USERNAME')
_PASSWORD = os.getenv('PBI_PASSWORD')
_DATASET_ID = os.getenv('DATASET_ID')
_TABLE_NAME = os.getenv('TABLE_NAME', 'BookingMaster')

_TOKEN_URL = f"https://login.microsoftonline.com/{_TENANT_ID}/oauth2/v2.0/token"
_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_QUERY_URL = f"https://api.powerbi.com/v1.0/myorg/datasets/{_DATASET_ID}/executeQueries"


def _get_access_token() -> str:
    """ขอ token ด้วย username/password (ROPC flow) — ไม่ต้องขอสิทธิ์ Admin"""
    resp = requests.post(
        _TOKEN_URL,
        data={
            'grant_type': 'password',
            'client_id': _CLIENT_ID,
            'client_secret': _CLIENT_SECRET,
            'username': _USERNAME,
            'password': _PASSWORD,
            'scope': _SCOPE,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()['access_token']


def fetch_table(table_name: str | None = None) -> dict:
    """ดึงข้อมูลจากตารางใน Power BI dataset และคืนเป็น list of dicts"""
    table = table_name or _TABLE_NAME
    token = _get_access_token()

    payload = {
        "queries": [{"query": f"EVALUATE {table}"}],
        "serializerSettings": {"includeNulls": True},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(_QUERY_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()

    result = resp.json()
    logger.debug(f"powerbi_connector raw response for '{table}': {result}")

    # ตรวจสอบ error ระดับ results
    results = result.get('results', [])
    if not results:
        raise ValueError(f"Power BI returned no results. Full response: {result}")

    tables = results[0].get('tables', [])
    if not tables:
        raise ValueError(f"Power BI returned no tables. results[0]: {results[0]}")

    table_data = tables[0]
    rows = table_data.get('rows', [])

    if not rows:
        logger.info(f"powerbi_connector: '{table}' returned 0 rows")
        return {'success': True, 'data': []}

    # Power BI คืน column name เป็น key ของ row เช่น "TableName[ColumnName]" — ตัด prefix ออก
    def _clean(col: str) -> str:
        if '[' in col and col.endswith(']'):
            return col.split('[', 1)[1][:-1]
        return col

    raw_keys = list(rows[0].keys())
    clean_keys = [_clean(k) for k in raw_keys]

    data = [dict(zip(clean_keys, row.values())) for row in rows]

    logger.info(f"powerbi_connector: fetched {len(data)} rows from '{table}'")
    return {'success': True, 'data': data}
