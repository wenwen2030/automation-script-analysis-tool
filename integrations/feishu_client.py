"""飞书 API 公共客户端 — 统一 token 获取和 HTTP 请求"""

import json
import time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from ..config import FEISHU_APP_ID, FEISHU_APP_SECRET

# Token 缓存
_token_cache = {"token": None, "expire": 0}


def get_tenant_token():
    """获取飞书 tenant_access_token(带缓存,过期自动刷新)

    Returns:
        token 字符串, 或 None(获取失败)
    """
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expire"]:
        return _token_cache["token"]

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    body = json.dumps({"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("code") == 0:
            token = data["tenant_access_token"]
            _token_cache["token"] = token
            _token_cache["expire"] = now + data.get("expire", 7200) - 60
            return token
    except (URLError, OSError):
        pass
    return None


def feishu_request(method, url, body=None, token=None):
    """发送飞书 API 请求

    Args:
        method: HTTP 方法("GET", "POST", "PUT", "PATCH", "DELETE")
        url: 完整的 API URL
        body: 请求体(dict,会自动 json 序列化)
        token: 可选,指定 token;不传则自动获取

    Returns:
        响应 JSON(dict), 或 None(请求失败)
    """
    if token is None:
        token = get_tenant_token()
    if not token:
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError, HTTPError):
        return None
