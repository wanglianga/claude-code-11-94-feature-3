"""多案竞争备件的精确指派搜索（带约束剪枝的分支限界 DFS）。

目标按字典序优化：
  1. 最大化可兑现（可发件）需求数量；
  2. 在最大数量方案中最小化整数调配费用；
  3. 数量与费用仍等价时，按稳定编号决胜：
     需求按稳定编号排序，取“各需求所得备件编号”向量字典序最小者
     （未分配位置使用最大哨兵，因此靠前需求优先拿到小编号备件）。

这是**精确搜索**而非贪心：DFS 枚举“每个需求 × 每个兼容未占用备件 + 暂不分配”
的完整指派空间，并用两类合法上界剪枝：
  - 剩余二分图最大匹配数（Kuhn）作为“最多还能满足几件”的上界；
  - 各剩余需求当前可用边最小费用的最小 need 项之和作为费用下界。

搜索只接收“当前仍可用且安全资格已放行”的备件；候选方案本身不占用任何库存，
库存占用只发生在方案批准出库时的原子事务里（见 services/aftersales.py）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Edge:
    req_code: str
    supply_code: str
    cost: int


@dataclass
class AssignmentResult:
    batch: str
    assignments: list[dict[str, Any]] = field(default_factory=list)
    # [{req_code, supply_code, cost}]，按 req_code 稳定排序
    unmet: list[str] = field(default_factory=list)
    fulfilled_count: int = 0
    total_cost: int = 0
    req_count: int = 0
    supply_count: int = 0
    compatible_edge_count: int = 0
    # 搜索过程统计（题目要求记录“实际展开分支”与耗时）
    dfs_nodes: int = 0
    assign_branches: int = 0
    skip_branches: int = 0
    branches_expanded: int = 0
    elapsed_ms: float = 0.0
    complete_space: int | None = None  # 全兼容样例的完整一对一空间 P(m,n)
    tie_break: str = "stable-code-lexicographic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch,
            "assignments": self.assignments,
            "unmet": self.unmet,
            "fulfilled_count": self.fulfilled_count,
            "total_cost": self.total_cost,
            "req_count": self.req_count,
            "supply_count": self.supply_count,
            "compatible_edge_count": self.compatible_edge_count,
            "dfs_nodes": self.dfs_nodes,
            "assign_branches": self.assign_branches,
            "skip_branches": self.skip_branches,
            "branches_expanded": self.branches_expanded,
            "elapsed_ms": self.elapsed_ms,
            "complete_space": self.complete_space,
            "tie_break": self.tie_break,
        }


def solve_assignment(
    req_codes: list[str],
    supply_codes: list[str],
    edges: list[Edge] | list[tuple[str, str, int]],
    *,
    batch: str = "default",
    complete_space: int | None = None,
) -> AssignmentResult:
    """对给定需求/备件/兼容费用边执行精确指派搜索。

    编号顺序即稳定决胜顺序；调用方应保证传入列表已按稳定编号排序。
    """
    started = time.perf_counter_ns()

    reqs = sorted(req_codes)
    supplies = sorted(supply_codes)
    r_index = {c: i for i, c in enumerate(reqs)}
    s_index = {c: i for i, c in enumerate(supplies)}

    norm_edges: list[Edge] = []
    for e in edges:
        edge = e if isinstance(e, Edge) else Edge(e[0], e[1], e[2])
        if edge.req_code not in r_index or edge.supply_code not in s_index:
            raise ValueError(f"指派边引用了未知编号：{edge}")
        norm_edges.append(edge)

    n, m = len(reqs), len(supplies)
    # options[i] = [(supply_idx, cost)]，按费用、备件稳定编号排序，便于尽早得到优 incumbent
    options: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    for edge in norm_edges:
        options[r_index[edge.req_code]].append((s_index[edge.supply_code], int(edge.cost)))
    for opts in options:
        opts.sort(key=lambda x: (x[1], x[0]))

    used = [False] * m
    chosen: list[int] = [-1] * n      # 每个需求选中的 supply idx，-1 表示未分配
    chosen_cost: list[int] = [0] * n

    stats = {"nodes": 0, "assign": 0, "skip": 0}
    best: dict[str, Any] | None = None  # count/cost/sig/chosen

    def matching_upper_bound(start: int) -> int:
        """剩余需求 → 当前未占用备件 的二分图最大匹配数（Kuhn），合法数量上界。"""
        match_s: dict[int, int] = {}

        def augment(ri: int, seen: set[int]) -> bool:
            for si, _cost in options[ri]:
                if used[si] or si in seen:
                    continue
                seen.add(si)
                owner = match_s.get(si)
                if owner is None or augment(owner, seen):
                    match_s[si] = ri
                    return True
            return False

        bound = 0
        for ri in range(start, n):
            if augment(ri, set()):
                bound += 1
        return bound

    def cost_lower_bound(start: int, need: int) -> int:
        """剩余需求各自最便宜可用边的 min 费用中最小的 need 项之和（忽略备件互斥，故为下界）。"""
        if need <= 0:
            return 0
        mins: list[int] = []
        for ri in range(start, n):
            costs = [c for si, c in options[ri] if not used[si]]
            if costs:
                mins.append(min(costs))
        if len(mins) < need:
            # 可达匹配数不足 need；数量上界剪枝会先行拦截，这里给一个保守大数
            return 10**18
        mins.sort()
        return sum(mins[:need])

    def signature() -> tuple[int, ...]:
        # 未分配位置用 m（大于任何 supply idx）作哨兵 → 字典序更靠后
        return tuple(chosen[i] if chosen[i] >= 0 else m for i in range(n))

    def consider_leaf(count: int, cost: int) -> None:
        nonlocal best
        sig = signature()
        if best is None:
            best = {"count": count, "cost": cost, "sig": sig,
                    "chosen": list(chosen), "chosen_cost": list(chosen_cost)}
            return
        if count > best["count"]:
            better = True
        elif count < best["count"]:
            better = False
        elif cost < best["cost"]:
            better = True
        elif cost > best["cost"]:
            better = False
        else:
            better = sig < best["sig"]
        if better:
            best = {"count": count, "cost": cost, "sig": sig,
                    "chosen": list(chosen), "chosen_cost": list(chosen_cost)}

    def dfs(idx: int, count: int, cost: int) -> None:
        stats["nodes"] += 1

        if best is not None:
            ub = matching_upper_bound(idx)
            if count + ub < best["count"]:
                return  # 数量上界都追不上当前最优 → 整枝剪掉
            max_final = count + ub
            if max_final == best["count"]:
                need = best["count"] - count
                lb = cost_lower_bound(idx, need)
                # 仅在严格大于时剪枝；相等费用仍可能凭稳定编号 tie-break 胜出
                if cost + lb > best["cost"]:
                    return

        if idx == n:
            consider_leaf(count, cost)
            return

        # 分支 A：把当前需求指派给某个兼容且未占用的备件
        for si, edge_cost in options[idx]:
            if used[si]:
                continue
            used[si] = True
            chosen[idx] = si
            chosen_cost[idx] = edge_cost
            stats["assign"] += 1
            dfs(idx + 1, count + 1, cost + edge_cost)
            used[si] = False
            chosen[idx] = -1
            chosen_cost[idx] = 0

        # 分支 B：本需求暂不满足（允许部分发件，数量目标会惩罚该选择）
        stats["skip"] += 1
        dfs(idx + 1, count, cost)

    dfs(0, 0, 0)
    assert best is not None  # n 个需求至少有“全部跳过”这一个叶子

    assignments: list[dict[str, Any]] = []
    unmet: list[str] = []
    total_cost = 0
    for i, req in enumerate(reqs):
        si = best["chosen"][i]
        if si >= 0:
            c = best["chosen_cost"][i]
            total_cost += c
            assignments.append({"req_code": req, "supply_code": supplies[si], "cost": c})
        else:
            unmet.append(req)

    elapsed_ns = time.perf_counter_ns() - started
    return AssignmentResult(
        batch=batch,
        assignments=assignments,
        unmet=unmet,
        fulfilled_count=best["count"],
        total_cost=total_cost,
        req_count=n,
        supply_count=m,
        compatible_edge_count=len(norm_edges),
        dfs_nodes=stats["nodes"],
        assign_branches=stats["assign"],
        skip_branches=stats["skip"],
        branches_expanded=stats["assign"] + stats["skip"],
        elapsed_ms=round(elapsed_ns / 1_000_000, 4),
        complete_space=complete_space,
    )


def brute_force_optimum(
    req_codes: list[str],
    supply_codes: list[str],
    edges: list[tuple[str, str, int]],
) -> tuple[int, int, tuple[tuple[str, str], ...]]:
    """独立的暴力枚举参考实现（测试中用于交叉验证搜索最优性）。

    枚举所有“需求→不同备件”的部分/完整单射，返回 (最大数量, 最小费用, 最优配对)。
    """
    from itertools import permutations

    reqs = sorted(req_codes)
    supplies = sorted(supply_codes)
    cost_map = {(r, s): c for r, s, c in edges}
    compatible = {(r, s) for r, s, _ in edges}

    best_count = -1
    best_cost = 10**18
    best_pairs: tuple[tuple[str, str], ...] = ()

    # 对每个满足数量 k，枚举从 m 个备件中有序选 k 个分配给前 k 个……
    # 更直接：枚举备件的全排列前缀作为 reqs 顺序的分配，并用 None 集合处理部分满足。
    # 小规模参考实现：枚举每个需求的选项子集。
    def rec(i: int, used: frozenset[str], pairs: list[tuple[str, str, int]]) -> None:
        nonlocal best_count, best_cost, best_pairs
        if i == len(reqs):
            cnt = len(pairs)
            cst = sum(p[2] for p in pairs)
            key_pairs = tuple(sorted((r, s) for r, s, _ in pairs))
            if cnt > best_count or (cnt == best_count and cst < best_cost) or (
                cnt == best_count and cst == best_cost and key_pairs < best_pairs
            ):
                best_count, best_cost, best_pairs = cnt, cst, key_pairs
            return
        rec(i + 1, used, pairs)  # 不满足 reqs[i]
        for s in supplies:
            if s not in used and (reqs[i], s) in compatible:
                rec(i + 1, used | {s}, pairs + [(reqs[i], s, cost_map[(reqs[i], s)])])

    rec(0, frozenset(), [])
    return best_count, best_cost, best_pairs
