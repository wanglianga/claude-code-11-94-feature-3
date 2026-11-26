# 退役电池包收货安全放行 + 售后客服双路径与备件精确指派系统

面向拆解中心的收货/隔离/拆解/检测/放行/仓库/签收一体化应用，并在同一工程内新增
**售后客服模块**：先寄替换件后收旧件、先收旧件复检后决定换货两条可实际办结的路径，
保修/押金/实物去向持续解释，以及多案竞争备件的**带约束剪枝精确指派搜索**。

技术栈：**Vue 3 + Vite**、**FastAPI + SQLAlchemy**、**PostgreSQL**。

---

## 0. 售后客服本题需求落地索引

| 题目要求 | 实现位置 / 验证 |
| --- | --- |
| O-31 模组 5 月 8 日验收；合同保修当日 00:00 起至次年 5 月 8 日 00:00 **前**；次年 5 月 7 日申诉仍在期内 | `services/aftersales.py::warranty_window`（右端开区间 `[起, 止)`，按 +08:00 日历日）；种子 `AS-O31`；测试 `test_warranty_window_may7_inside_may8_midnight_exclusive` |
| 在保 ≠ 检测已证明责任 | 案件页保修解释横幅；`decide_liability` 强制要求已结论的检测/工程证据，仅凭“在保”定责返回 409 `liability_evidence_required` |
| 运输压痕、缺失安装温度回执由工程人员补核；备注不能替代结论 | `EngineeringCheck` + `/engineering-checks/{id}/conclude`，空结论 409 `conclusion_required`；普通联系备注不改变补核状态（有测试） |
| 先换须取得押金 + 已批准兼容备件，路径实际可办 | 押金 `paid` 是原子批准出库的前置（未付返回 `precondition_failed`，方案保留 candidate，补正后可再批）；全链路测试 `test_advance_replace_full_path_and_closure` |
| 先检须管理停机、旧件保管、付款暂缓，路径实际可办 | `AS-O36` 种子：停机 30h、旧件在途、`payment_held`；停机起止/保管转移/付款暂缓-处置接口；测试 `test_inspect_first_path` |
| 精确指派：先最大化可发件数量，再最小化整数费用，等价按稳定编号 | `app/assignment.py` 分支限界 DFS（Kuhn 最大匹配上界 + 费用下界剪枝 + 稳定编号字典序决胜）；400 组随机用例与暴力枚举一致 |
| R1 可用 S1(费1)/S2(费2)，R2 只能 S1(费1)，两件均放行 → R1→S2、R2→S1 | 固定批次 `R-DEMO`；测试 `test_r1_r2_concurrency_sample_assignment` |
| 6 需求 × 8 备件全兼容，完整一对一空间 20160，记录实际展开分支/耗时/最终代价 | 固定批次 `FULL68`；接口/界面展示 `complete_space=20160`、`branches_expanded=438`、`dfs_nodes=439`、`elapsed_ms≈1ms`、最小代价 `12`（费用表固定，暴力枚举交叉验证） |
| O-31 初始只有一台兼容件，不能超卖 | `REAL` 批次仅 `SP-701` 一条兼容件；两份候选先后批准，第二份 409 `assignment_stale`；数据库唯一约束 `uq_as_repl_spare_once`；真并发测试 `test_concurrent_approvals_only_one_wins`（行锁 `with_for_update`，两线程恰一成一败） |
| 候选不占库存 | `solve` 只生成 `candidate` 方案，备件仍 `available`（有断言） |
| 批准出库时原子核对全部序列号仍可用且需求未履行；库存/兼容依据变化使旧方案退回，不执行半份指派 | `approve_plan`：行锁锁定需求/备件/兼容边后逐项复核，任一“依据类”变化 → 方案 `stale` + 持久化原因 + 409 `assignment_stale`，不建任何替换单；费用变化/资格撤回/重复履行均有测试 |
| 寄出、客户签收、旧件回收、返修检测、押金退款各有独立状态 | `ReplacementOrder.shipment_status/signoff_status`、`OldPartReturn.status`、`ReworkInspection.status`、`Deposit.status`；测试验证寄出≠签收等独立性 |
| 旧件未实收不能成为返修库存 | `move_to_rework_stock` / `start_inspection` 硬门禁 `old_part_not_received` |
| 替换件已寄不能靠撤案恢复可用 | `withdraw_case`：已寄单保留、备件保持 `shipped/installed`；测试 `test_shipped_replacement_not_restored_by_withdraw` |
| 只修端子记录真实部件和旧件去向，不让整机序列号被重复换出 | `RepairRecord`（真实部件名/批次/数量、旧部件去向、整机去向）；端子维修序列号进入 `terminal_repaired_serials`，搜索排除、批准拦截、补库自动打标 `whole_exchange_blocked`；测试 + 演示脚本第 9 节 |
| 演示：两路径、竞争最后备件、分配后安全资格撤回、押金退款未知、回收逾期 | 案件台顶部五张演示导航卡；指派台“一键安全撤回演示”（真实执行 求解→撤回→批准被原子拒→重算）；种子 `AS-O31/O36/O41/O42` |
| 案件页显示当前保管人、停机时段、剩余承诺、下一次联系 | `Aftersales.vue` 四个 KPI 卡；后端 `case_summary` 实时计算剩余/逾期文案 |
| 收齐材料后保留原申诉和工程解释；实物及资金待办各自结清才可结案 | `original_appeal`/`engineering_explanation` 只增不改；`closure_blockers` 分项列出材料/补核/责任/停机/寄出/签收/旧件去向/检测/押金/付款阻塞；`close_case` 409 `closure_blocked`（带结构化 `details.blockers`） |

### 指派算法说明（为什么不是贪心）

贪心按固定顺序先给 R1 分配最便宜的 S1，会让只能用 S1 的 R2 无件可分。本实现枚举
“每个需求 × 每个兼容未占用备件 + 暂不分配”的完整空间，以字典序目标
`(-满足数量, 总费用, 稳定编号向量)` 选全局最优，并用合法上界安全剪枝：

- 剩余子问题二分图**最大匹配数**（Kuhn）→ 数量上界；
- 各剩余需求当前最便宜可用边费用的最小 `need` 项之和 → 费用下界（忽略互斥，只会低估）；
- 仅当上界追不平当前最优数量、或费用下界严格超过最优费用时剪枝，**不影响最优性**。

已用 400 组随机小实例与独立暴力枚举 `itertools` 参考实现逐一核对
`(最大数量, 最小费用)` 完全一致。未选择费用容量网络方案；题目允许二选一，本方案在
6×8 规模下可直接给出“实际展开分支数”，且便于逐项检查兼容条件。

---

## 1. 电池业务能力与规则落地（基线保留）

| 需求点 | 实现位置/行为 |
| --- | --- |
| 每包唯一序列号；重复扫码只返回原收货单 | `services/receiving.py::receive_pack`，响应 `duplicated=true` |
| 收货单显示隔离位、责任班组、未完成前置项 | `pending_preconditions` |
| 整批隔离 vs 单包隔离 | `freeze_batch` / `quarantine_pack` |
| 双方见证扫码建立包→模组父子关系 | `link_module`，两名见证者必须不同 |
| 重贴标签保留旧号、操作者、时间，两人确认 | `label_history` + 两阶段换标 |
| 无法确认父子关系的模组隔离待核 | `register_unknown_module`，绝不自动归号 |
| BMS 正常不能抵消碰撞/浸水历史 | `safety.echelon_blockers` 硬门禁 |
| 校准过期/绝缘失败/热事件未结案禁止梯次利用 | 同上 |
| 8 种状态互不混淆 | `enums.PackStatus` |
| 退回补检后旧放行单失效 | `_void_active_approvals` |
| 仓库只能按已批准去向拣货，沿父子链重校验 | `warehouse.pick` |
| 买家拒收只能退回隔离待复核 | `sign_off(rejected)` |
| 装车货物不能删除，只能召回/退运 | `recall_or_return` |
| 数量差额未解释阻止结清 | `close_batch`（409 `reconciliation_blocked`） |
| 全链路留痕 | `audit_logs` + `/api/audit/logs` |

样例 **L-7** 种子与双策略对比仿真保持不变（「L-7 场景」页或 `demo_l7.py`）。

---

## 2. 测试账号（种子数据，无密码，登录后请求带 `X-Username` 头）

| 账号 | 姓名 | 角色 | 说明 |
| --- | --- | --- | --- |
| `u_admin` | 管理员 | admin | 拥有全部售后/电池操作权限，**演示推荐** |
| `u_service` | 冯售后 | service | 售后客服：案件、联系、承诺、押金、撤案、结案 |
| `u_engineer` | 蒋工程 | engineer | 工程补核、责任结论、返修检测、端子维修 |
| `u_finance` | 钱财务 | finance | 押金收取/退款查询/扣除、付款暂缓处置 |
| `u_receiver` | 王接收 | receiver | 收货一班 |
| `u_dismantler` / `u_dismantler2` | 李拆解 / 赵拆解 | dismantler | 双见证 |
| `u_safety` | 陈安全 | safety | 安全工程师（也可撤回备件安全资格） |
| `u_warehouse` | 孙仓储 | warehouse | 收旧件、寄替换件、拣货、补库、批准指派 |
| `u_downstream` | 周买家 | downstream | 下游签收 |

登录页账号清单 `GET /api/auth/users` 为公开接口（无密码演示账号），全新浏览器也能拉到下拉。

---

## 3. 一键启动（Docker Compose）

```bash
cd /workspace/94-feature-3
docker compose up --build
```

- 前端：<http://localhost:8080>（Nginx 提供 SPA 并代理 `/api`、`/docs`）
- 后端 API：<http://localhost:8000>
- Swagger UI：<http://localhost:8000/docs>（全栈项目不强制要求，但后端自动文档仍然可用）
- 首次启动自动建表并播种 L-7 与全部售后演示数据。

> 本容器内未安装 docker CLI，因此 Compose 配置已交付但未在本容器实际执行 `docker compose up`；
> 镜像内启动命令、Nginx 代理与构建步骤均与下方本地验证一致。

---

## 4. 本地开发启动（容器内预装运行时）

### 4.1 准备数据库

```bash
# PostgreSQL 18 已在 127.0.0.1:5432 运行，管理员库/用户/密码均为 ccdev
PGPASSWORD=ccdev /opt/postgresql-18/bin/psql -h 127.0.0.1 -U ccdev -d ccdev \
  -c "CREATE DATABASE battery_demo;"   # 已存在则忽略
PGPASSWORD=ccdev /opt/postgresql-18/bin/psql -h 127.0.0.1 -U ccdev -d ccdev \
  -c "CREATE DATABASE battery_test;"   # 自动化测试库
```

### 4.2 后端

```bash
cd /workspace/94-feature-3/backend
/opt/python-3.12/bin/python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
DATABASE_URL="postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/battery_demo" \
  .venv/bin/uvicorn app.main:app --port 8000
```

启动时自动 `create_all` 并播种。Swagger UI：<http://127.0.0.1:8000/docs>。

### 4.3 前端

```bash
cd /workspace/94-feature-3/frontend
/opt/node-22/bin/npm install --registry=https://registry.npmmirror.com --cache=./.npm-cache
/opt/node-22/bin/npm run dev       # http://127.0.0.1:5173 ，/api 代理到 8000
# 或生产构建 + preview（8080，已配置 /api 代理到 127.0.0.1:8000）
/opt/node-22/bin/npm run build && /opt/node-22/bin/npm run preview
```

---

## 5. 本题验证方式

### 5.1 自动化测试：48 个用例全部通过（原 27 + 售后新增 21）

```bash
cd /workspace/94-feature-3/backend
DATABASE_URL="postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/battery_test" \
  .venv/bin/python -m pytest tests/ -q
```

售后用例 `tests/test_aftersales.py` 覆盖：保修日历边界；空工程结论/无证据定责被拒；
R1/R2 最优指派；REAL 稳定决胜；FULL68 的 20160 空间与暴力枚举最优代价；120 组随机模糊；
押金可补正前置；最后备件超卖拦截；**两线程真并发批准恰一成一败**；兼容费用变化 stale；
安全撤回一键演示；先换后旧完整结案；已寄件撤案不恢复；未寄件撤案释放；
先检后换完整路径；O-41 逾期、O-42 退款未知唯一阻塞、O-30 已结案保留；鉴权 401。

### 5.2 命令行全流程演示（实际执行并打印 PASS）

```bash
cd /workspace/94-feature-3/backend
DATABASE_URL="postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/battery_demo" \
  .venv/bin/python demo_aftersales.py
```

脚本重建库并真实跑过 9 组场景（保修边界、R1/R2、6×8 统计、竞争+超卖、先换全链路、
先检全链路、安全撤回原子退回、逾期/退款未知、撤案与端子锁），每项带 `[PASS]`。
L-7 基线演示仍为 `.venv/bin/python demo_l7.py`。

### 5.3 界面手工验证路径

1. `u_admin` 登录，顶部进入 **「售后案件台」**：
   - 顶部五张卡可直达五个演示场景；案件页顶部四个 KPI 即**当前保管人/停机时段/剩余承诺/下一次联系**；
   - `AS-O31`：查看保修“申诉在保期内”与“在保≠责任”解释 → 两项工程补核填写结论 →
     押金“确认收讫” → 到「备件指派」批准 REAL 方案 → 回案件台“确认寄出/客户签收” →
     结束停机 → 仓库实收旧件 → 开始/结论检测 → 登记端子维修 →
     发起退款（显示**退款结果未知**，结案被拦）→ 向通道查询变为已退款 → 两清结案；
   - `AS-O36`：先尝试“开始检测”被拒 → 仓库实收旧件 → 检测结论“故障成立/换货” →
     在换货框输入已预置的 `SP-801` → 精确指派并原子批准 →
     寄出/签收 → 旧件报废 → 处置付款暂缓 → 结束停机 → 结案；
   - `AS-O41` 直接显示“回收逾期/联系逾期”；`AS-O42` 结案门禁唯一阻塞为退款未知，查询后可结案。
2. 顶部进入 **「备件指派」**：
   - 切换 `R1/R2 并发样例` → 运行搜索，查看 R1→S2、R2→S1 与分支/耗时；
   - 切换 `6×8 全兼容` → 搜索，查看 **20160** 完整空间、实际展开分支 **438**、DFS 节点、耗时与代价 **12**；
   - `REAL` → 搜索/批准，验证 O-31 得到 SP-701；可补库 `SP-705` 并新增 `D-O32→SP-705` 边后重算两案全满足；
   - 点击“一键真实执行：求解→撤回 SS-1 资格→批准旧方案→重算”，查看旧方案 stale 原因与零半份单据；
   - 在备件表对任意序列号“撤回资格/恢复”，或手动批准历史候选，观察原子复核结果。
3. 基线页面（收货/拆解/检测台/安全审批/仓库/下游/L-7/审计）保持原有操作路径不变。

---

## 6. 本工作区实际执行过的验证结论（2026-11-26）

- ✅ `pytest tests/ -q`：**48 passed**（真实 PostgreSQL 18 `battery_test`，非 SQLite）。
- ✅ `demo_aftersales.py`：9 组场景全部 `[PASS]`；实测 R1→S2/R2→S1、6×8 展开分支 438、
  DFS 节点 439、耗时约 1.3 ms、最小代价 12、空间 20160；并发/超卖/安全撤回/结案门禁均符合预期。
- ✅ 真实 uvicorn + HTTP 端到端脚本（27 项断言）全部 PASS：含未付押金 `precondition_failed`
  且方案仍 candidate、付押金后批准、重复批准被拒、寄出/签收、旧件门禁、退款未知→查询→结案、
  安全撤回演示接口、O-41/O-42 种子状态、演示重置。
- ✅ 前端 `npm run build` 构建成功（新增 `Aftersales`（27.9 kB）与 `Assignment`（12.3 kB）两个 chunk）。
- ✅ `vite preview`（8080）首页与 SPA 深路径回退均 200；`/api/auth/users` 与
  `/api/aftersales/cases` 经 preview 代理到 8000 实测返回正常（10 个账号）。
- ✅ 400 组（开发期）+ 测试内 120 组随机指派实例与暴力枚举最优解一致。
- ⚠️ 未做真实浏览器像素级点击（容器内无 Chromium/Playwright）；模板已通过生产构建编译、
  处理函数引用已逐一核对，运行时由 48 个后端/接口测试与 HTTP E2E 覆盖。
- ⚠️ 当前容器未安装 docker CLI，`docker compose up --build` 未在本容器实际执行；配置保持可一键启动。

---

## 7. 目录结构

```
94-feature-3/
├── docker-compose.yml
├── README.md
├── backend/
│   ├── Dockerfile / entrypoint.sh
│   ├── requirements.txt
│   ├── demo_l7.py                 # 基线 L-7 演示
│   ├── demo_aftersales.py         # 售后九场景命令行演示（本题）
│   ├── app/
│   │   ├── main.py                # FastAPI 入口（异常 details 透传、注册 aftersales 路由）
│   │   ├── models.py              # 含 as_* 售后表（案件/补核/押金/备件/需求/兼容边/方案/五类状态单/维修）
│   │   ├── assignment.py          # 精确指派搜索引擎（分支限界）+ 暴力参考实现
│   │   ├── seed.py                # 账号/L-7 + 调用售后种子
│   │   ├── seed_aftersales.py     # O-31/O-32/O-36/O-41/O-42/O-30 + REAL/R/6x8/SAFE 固定数据
│   │   ├── aftersales_serializers.py
│   │   ├── services/aftersales.py # 两路径状态机、原子批准、结案门禁
│   │   └── routers/aftersales.py  # /api/aftersales/* 与演示/重置接口
│   └── tests/test_aftersales.py   # 21 个售后用例（全套件 48）
└── frontend/
    ├── Dockerfile / nginx.conf    # /api 与 /docs 反代 + SPA fallback
    └── src/views/
        ├── Aftersales.vue         # 售后案件台（KPI/两路径全部操作/结案门禁/五场景导航）
        ├── Assignment.vue         # 指派工作台（20160 统计/方案批准/安全撤回演示）
        └── …基线 8 个视图
```
