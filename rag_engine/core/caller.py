"""
调用方身份

由 Java 网关从 JWT 解出后经请求头注入。引擎不做认证，也不认识角色：
角色语义（谁能做什么）留在有用户体系的那一层，这里只接收翻译好的结果。

传"能力"而不是角色：网关说"这个人能不能删任意文档"，引擎不需要知道
ADMIN / USER 是什么。将来加一个也能删文档的新角色，只改网关。

这层只用来判文档归属。部署上引擎不暴露端口，外部请求到不了这里。

（单独成模块而不是放 core/dependencies.py：那个模块 import 了 DocumentService，
服务层再反向 import 会成环）
"""
from fastapi import Header


class Caller:
    """一次请求的调用方身份"""

    HEADER_USER_ID = "X-User-Id"
    HEADER_CAN_DELETE_ANY = "X-Can-Delete-Any"

    def __init__(self, user_id: str | None, can_delete_any: bool):
        self.user_id = user_id
        self.can_delete_any = can_delete_any


def get_caller(
    user_id: str | None = Header(default=None, alias=Caller.HEADER_USER_ID),
    can_delete_any: str | None = Header(default=None, alias=Caller.HEADER_CAN_DELETE_ANY),
) -> Caller:
    """从请求头取身份

    FastAPI 的 Header 参数名默认会把下划线转成连字符，这里显式给 alias。
    布尔过来说是字符串，只有 "true" 才算真——缺失、拼错一律按无权限处理
    """
    return Caller(user_id=user_id, can_delete_any=can_delete_any == "true")
