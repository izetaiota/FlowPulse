# RBAC 菜单权限管理方案（Casbin 版）

> 状态：设计定稿，未实施。按阶段推进，每阶段完成后在对应条目标 ✅。
> 关联：`docs/WECHAT_WEREAD_RSS_PLAN.md`（模块计划）、`src/flowpulse/core/auth.py`（现有单账号鉴权）。

## 1. 背景与目标

当前 Web 端为单账号鉴权（`fp_users` 单行 + HMAC Token），菜单数据驱动（`fp_app_menus`）但所有登录用户可见相同菜单。目标：

- 多用户 + 角色（RBAC1，支持角色继承）
- 菜单按角色过滤（服务端下发，前端只渲染）
- 接口按权限码校验（deny-by-default，前端隐藏只是体验、后端才是闸门）
- 授权引擎统一走 **pycasbin**，策略存储与现有双模式存储对齐（PG / 文件）

## 2. 技术选型与关键决策

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 授权引擎 | pycasbin（RBAC1 模型） | 用户角色继承（`g` 支持传递），策略与代码解耦 |
| 匹配方式 | **权限码匹配**（`sub, obj` 两元模型，obj=权限码），不做 URL 路径匹配 | 权限码随菜单树管理、与路由解耦；URL 变更不影响策略；可读可审计 |
| 策略存储 | PG 模式：自写 SQLAlchemy 适配器 → `fp_casbin_rule` 表（复用现有 engine/sessionmaker，表名延续 fp_ 前缀；官方 casbin-sqlalchemy-adapter 表名不可定制）；文件模式：casbin 内置 FileAdapter → `data/auth/policy.csv` | 与项目双模式哲学一致；适配器约 60 行，避免多一个依赖 |
| 用户-角色关系 | 存 casbin `g` 策略（不建 fp_user_roles 表） | 授权关系单一事实来源；用户管理页直接写 g 策略 |
| 角色元数据 | 新建 `fp_roles` 表（code/name/remark/status） | casbin 策略存不了显示名与状态 |
| Token | 维持现有 HMAC 薄 token（只签 username） | 权限每请求由 enforcer 解析，撤权即时生效；避免"权限进 token 导致旧 token 带旧权限"的经典坑 |
| 超管 | 内置角色 `admin`，策略 `p, admin, *`（matcher 支持通配） | 无需给超管逐条绑码 |
| 密码 | 沿用现有 PBKDF2 哈希 | 已实现，不重复造 |

## 3. 授权模型

`conf/rbac_model.conf`（随包分发，路径 `src/flowpulse/conf/rbac_model.conf`，亦可字符串内嵌）：

```ini
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
```

- 请求：`enforcer.enforce(username, "weread:subscription:list")`
- 策略示例：

```csv
p, admin, *
p, editor, weread:subscription:list
p, editor, weread:subscription:save
g, zhangsan, editor      # 用户挂角色
g, editor, viewer        # 角色继承（editor 继承 viewer 全部权限）
```

### 权限码规范

`{module}:{resource}:{action}`，全小写 ASCII。目录节点（type=dir）不挂码；页面/按钮节点挂码；**无码的菜单节点默认"登录即可见"**。

首批权限码（实施阶段 2 随路由逐个补全）：

```
weread:subscription:list / save / delete / sync
weread:article:list, weread:rss:read
xhs:note:search / detail, xhs:job:list / create
transcribe:task:list / create / retry
admin:user:list / save, admin:role:list / save, admin:menu:list / save
```

## 4. 数据库变更（Alembic 0004）

```sql
-- 1) fp_users 从单行改多用户
ALTER TABLE fp_users DROP CONSTRAINT ck_fp_users_single_row;
ALTER TABLE fp_users ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active';
ALTER TABLE fp_users ADD COLUMN created_at/updated_at ...;  -- 已有则跳过

-- 2) 菜单树扩展：节点类型 + 权限码
ALTER TABLE fp_app_menus ADD COLUMN type VARCHAR(16) NOT NULL DEFAULT 'menu';   -- dir/menu/button
ALTER TABLE fp_app_menus ADD COLUMN perm VARCHAR(128) NOT NULL DEFAULT '';

-- 3) 角色元数据
CREATE TABLE fp_roles (
  id SERIAL PRIMARY KEY,
  code VARCHAR(64) UNIQUE NOT NULL,
  name VARCHAR(64) NOT NULL,
  remark TEXT DEFAULT '',
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4) casbin 策略（自写适配器的表，标准 casbin 五列 + 自增主键）
CREATE TABLE fp_casbin_rule (
  id SERIAL PRIMARY KEY,
  ptype VARCHAR(8) NOT NULL,       -- p / g
  v0 VARCHAR(128) NOT NULL DEFAULT '',
  v1 VARCHAR(128) NOT NULL DEFAULT '',
  v2 VARCHAR(128) NOT NULL DEFAULT '',
  v3 VARCHAR(128) NOT NULL DEFAULT '',
  v4 VARCHAR(128) NOT NULL DEFAULT '',
  v5 VARCHAR(128) NOT NULL DEFAULT ''
);
CREATE INDEX ix_fp_casbin_rule_ptype ON fp_casbin_rule(ptype, v0, v1);
```

种子（幂等，随迁移或应用启动执行）：

- `p, admin, *`；现有 admin 用户 `g, admin, admin`
- `fp_roles` 插入 `(admin, 超级管理员)`
- 现有 14 条菜单按首批权限码表回填 `perm`（驾驶舱等基础页可留空 = 登录可见）

文件模式：`data/auth/policy.csv` 同样内容；`fp_roles` 退化为 `data/auth/roles.json`（延续菜单模块的双模式写法）。

## 5. 后端设计

### 5.1 Enforcer 装配（runtime）

```python
# src/flowpulse/core/rbac.py（新文件）
def build_enforcer(settings, db_sessionmaker) -> Enforcer:
    model = casbin.Model()
    model.load_model_from_text(RBAC_MODEL_TEXT)          # 模型内嵌字符串，免文件路径问题
    if db_sessionmaker is not None:
        adapter = CasbinSqlAdapter(db_sessionmaker)      # 自写适配器，读写 fp_casbin_rule
    else:
        adapter = casbin.persist.adapters.FileAdapter(
            settings.data_dir / "auth" / "policy.csv")   # 首启自动创建
    enforcer = casbin.SyncedEnforcer(model, adapter)     # Synced 版自带读写锁
    enforcer.load_policy()
    return enforcer
```

- 挂到 `Runtime`（`build_runtime` 里构造，`aclose` 里 `enforcer.close()`）
- 管理接口写策略后调 `enforcer.load_policy()` 热加载（单进程，无需 Watcher）
- 选 `SyncedEnforcer`：FastAPI 同步端点跑线程池，读写锁由它管

### 5.2 鉴权依赖（core/rbac.py）

```python
def get_current_user(request: Request) -> CurrentUser:
    """require_auth 的扩展版：username + roles + perms（每请求从 enforcer 解析）。"""

def require_perm(code: str):
    def dep(user: CurrentUser = Depends(get_current_user)):
        if "admin" in user.roles:          # 超管短路，少一次策略匹配
            return
        if not user.enforcer.enforce(user.username, code):
            raise HTTPException(403, "无权限")
    return dep
```

挂载原则：现有 `require_auth`（登录态）保留为第一道；管理类路由逐个加 `dependencies=[Depends(require_perm("admin:user:save"))]`。**新路由默认必须挂码**，代码评审 checklist。

### 5.3 接口清单

| 接口 | 权限码 | 说明 |
| --- | --- | --- |
| GET /api/auth/session | 登录 | 响应扩展 `{username, roles, perms[], menus[]}`；menus 为按角色过滤后的树 |
| GET/POST/PUT /api/admin/users | admin:user:* | 用户 CRUD + 挂角色（写 g 策略） |
| GET/POST/PUT /api/admin/roles | admin:role:* | 角色 CRUD；保存时同步 p 策略与 fp_roles |
| GET /api/menus（现有） | admin:menu:*（写操作） | 读保持登录即可；PUT/reset 挂码 |
| GET /api/admin/perm-codes | admin:role:save | 从菜单树导出全部可分配权限码（角色编辑页勾选用） |

菜单过滤规则（GET /api/menus 或 session 内）：取用户 perms → 保留 `perm 为空` 或 `perm ∈ perms` 的节点 → 目录节点只要仍有可见子节点就保留，否则丢弃。

## 6. 前端设计

- `stores/auth.ts`：state 增加 `roles/perms`；`loadSession` 一次拿全
- `stores/menu.ts`：改从 session 接口的过滤后菜单取数（保留 FALLBACK_MENUS 兜底，但兜底只在接口失败时用）
- `directives/perm.ts`：注册 `v-perm="'xhs:job:create'"`，无权限移除元素（`app.directive`，main.ts 注册）
- 新页面（系统设置下或独立"权限管理"分组）：
  - 用户管理：列表 + 新增/编辑（用户名、初始密码、状态）+ 角色多选
  - 角色管理：列表 + 编辑抽屉（基本信息 + **菜单权限树勾选**，树数据来自菜单接口，勾选写 p 策略；支持继承展示）
  - 菜单管理：现有页加 `type`（目录/页面/按钮）与 `perm` 两列
- 顶栏退出旁显示当前用户角色徽标

## 7. 实施阶段

- [ ] **阶段 0：依赖与引擎接入**（半天）
  pyproject 加 `pycasbin`；`core/rbac.py`（模型文本、CasbinSqlAdapter、build_enforcer、get_current_user、require_perm）；runtime 装配 + 单测（内存适配器验证 g 继承与 `*` 通配）。
  验收：单测覆盖 matcher 语义（通配/继承/拒绝），不影响现有行为。

- [ ] **阶段 1：数据库迁移与种子**（半天）
  Alembic 0004 + 种子 + 文件模式 policy.csv 初始化；`fp_users` 多行化后回归现有登录/改密测试。
  验收：`alembic upgrade head` 幂等；admin 登录行为不变；14 条菜单权限码回填。

- [ ] **阶段 2：后端权限层落地**（1 天）
  session 接口扩展（roles/perms/menus 过滤）；管理接口（users/roles/perm-codes）；现有路由挂首批权限码；admin 角色全通。
  验收：非 admin 用户按码放行/403 的 API 测试全绿；撤掉角色后立即失去权限（不重登）。

- [ ] **阶段 3：前端管理界面**（1 天）
  v-perm 指令、menu/auth store 改造、用户/角色/菜单三页面、登录页不动。
  验收：双角色真机走查（超管见全部；受限用户菜单过滤、按钮隐藏、直调 API 403）。

- [ ] **阶段 4：收尾**（半天）
  全量测试、README 权限章节（角色初始化/改密/新增权限码流程）、文档勾选更新、提交。

## 8. 风险与注意事项

- **`SyncedEnforcer` 与 FastAPI 线程池**：同步端点在线程池执行，Synced 版自带的锁足够；不要在 async 端点里直接调用（会阻塞事件循环）——项目业务端点均为同步 def，现状契合
- **策略表命名**：自写适配器是为了 `fp_casbin_rule` 前缀一致性；若后续想换官方 casbin-sqlalchemy-adapter，表名会变 `casbin_rule`，迁移时 `INSERT SELECT` 即可
- **policy.csv 并发写**：文件模式仅本地单进程使用，写操作全部经 enforcer（其内部串行化），不加额外锁
- **权限码唯一性**：菜单管理页保存时校验 perm 码全库唯一（重复会导致勾选语义混乱）
- **角色删除**：先校验无用户挂载（`enforcer.get_users_for_role`），有则拒绝
- **撤权即时性**：权限不进 token，改角色下一次请求即生效；仅登录态本身仍由 7 天 token 控制（如需"改角色立刻踢下线"，后续可加 token 版本号，本方案不做）
- **默认密码**：新增用户给随机初始密码或管理员代设，首次登录强制改密（阶段 3 可选增强）
