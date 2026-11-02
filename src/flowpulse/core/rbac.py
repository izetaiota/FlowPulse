"""RBAC 权限引擎（Casbin 版）：模型/适配器/装配/鉴权依赖。

设计见 docs/RBAC_CASBIN_PLAN.md：
- RBAC1 模型（角色继承），权限码匹配（sub=obj 两元），admin 通配 *
- 策略存储：PG 走 fp_casbin_rule（自写 SQLAlchemy 适配器），文件走 policy.csv
- 用户-角色存 casbin g 策略；角色元数据存 fp_roles / roles.json
- Token 仍只签 username；权限每请求由 enforcer 解析，撤权即时生效
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

RBAC_MODEL_TEXT = """
[request_definition]
r = sub, obj

[policy_definition]
p = sub, obj

[role_definition]
g = _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub) && (p.obj == r.obj || p.obj == "*")
"""

ADMIN_ROLE = "admin"


# ---- SQLAlchemy 适配器（fp_casbin_rule 表） ----


class CasbinSqlAdapter:
    """读写 fp_casbin_rule 表；len<=2 的 ptype 走 g 逻辑，其余走 p 逻辑。"""

    def __init__(self, sessionmaker_: sessionmaker[Session]):
        from flowpulse.db.models import CasbinRuleRow

        self._sessionmaker = sessionmaker_
        self._row_class = CasbinRuleRow

    def load_policy(self, model: Any) -> None:
        with self._sessionmaker() as session:
            rows = session.execute(select(self._row_class)).scalars().all()
            for row in rows:
                values = [row.v0, row.v1, row.v2, row.v3, row.v4, row.v5][: self._field_count(row.ptype)]
                line = f"{row.ptype}, {', '.join(v for v in values if v)}"
                model.load_policy_line(line, model)

    def save_policy(self, model: Any) -> None:
        with self._sessionmaker() as session:
            session.execute(sa_delete(self._row_class))
            for sec in ("p", "g"):
                if sec not in model.model.keys():
                    continue
                for key, ast in model.model[sec].items():
                    ptype = sec + key
                    for rule in ast.policy:
                        row = self._row_class(ptype=ptype)
                        for i, value in enumerate(rule[:6]):
                            setattr(row, f"v{i}", str(value))
                        session.add(row)
            session.commit()

    def add_policy(self, sec: str, ptype: str, rule: list[str]) -> None:
        row = self._row_class(ptype=ptype)
        for i, value in enumerate(rule[:6]):
            setattr(row, f"v{i}", str(value))
        with self._sessionmaker() as session:
            session.add(row)
            session.commit()

    def remove_policy(self, sec: str, ptype: str, rule: list[str]) -> None:
        conditions = [self._row_class.ptype == ptype]
        for i, value in enumerate(rule[:6]):
            conditions.append(getattr(self._row_class, f"v{i}") == str(value))
        with self._sessionmaker() as session:
            session.execute(sa_delete(self._row_class).where(*conditions))
            session.commit()

    def remove_filtered_policy(self, sec: str, ptype: str, field_index: int, *field_values: str) -> None:
        conditions = [self._row_class.ptype == ptype]
        for i, value in enumerate(field_values):
            col = getattr(self._row_class, f"v{field_index + i}")
            conditions.append(col == str(value))
        with self._sessionmaker() as session:
            session.execute(sa_delete(self._row_class).where(*conditions))
            session.commit()

    @staticmethod
    def _field_count(ptype: str) -> int:
        return 2 if ptype.startswith("g") else 2  # 本模型 p 和 g 都是两元


# ---- Enforcer 装配 ----


def build_enforcer(db_sessionmaker: sessionmaker[Session] | None, data_dir: Path) -> Any:
    import casbin

    model = casbin.Model()
    model.load_model_from_text(RBAC_MODEL_TEXT)
    if db_sessionmaker is not None:
        adapter = CasbinSqlAdapter(db_sessionmaker)
    else:
        policy_path = data_dir / "auth" / "policy.csv"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        if not policy_path.exists():
            policy_path.write_text(
                f"p, {ADMIN_ROLE}, *\n", encoding="utf-8"
            )
        adapter = casbin.persist.adapters.FileAdapter(str(policy_path))
    enforcer = casbin.SyncedEnforcer(model, adapter)
    enforcer.load_policy()
    return enforcer


# ---- 鉴权依赖 ----


@dataclass
class CurrentUser:
    username: str
    roles: list[str] = field(default_factory=list)
    perms: list[str] = field(default_factory=list)
    enforcer: Any = None

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles


def resolve_user(enforcer: Any, username: str) -> CurrentUser:
    roles = enforcer.get_roles_for_user(username)
    perms_set: set[str] = set()
    for role in [username, *roles]:
        for policy in enforcer.get_permissions_for_user(role):
            if len(policy) >= 2:
                if policy[1] == "*":
                    # 通配角色：展开为菜单树全部非空 perm（延迟展开由调用方做）
                    perms_set.add("*")
                else:
                    perms_set.add(policy[1])
    # 角色继承：get_roles_for_user 只返回直接角色，通配通过 g 传递已含
    return CurrentUser(username=username, roles=roles, perms=sorted(perms_set), enforcer=enforcer)


def require_perm(code: str):
    """FastAPI 依赖工厂：校验当前用户是否有指定权限码（admin 角色短路）。"""

    def dep(user: CurrentUser | None = None) -> CurrentUser:
        if user is None:
            raise HTTPException(status_code=401, detail="未登录")
        if user.is_admin or "*" in user.perms:
            return user
        if user.enforcer is not None and user.enforcer.enforce(user.username, code):
            return user
        raise HTTPException(status_code=403, detail=f"无权限：{code}")

    return dep
