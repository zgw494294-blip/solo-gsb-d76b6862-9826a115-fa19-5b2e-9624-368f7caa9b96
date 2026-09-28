"""共享事件故障概率分析 API。

POST /v1/analyze
  输入：events（1~32 个独立事件，概率为 n/d 分数字符串）、
        gates（0~64 个布尔门 AND/OR/NOT）、顶层节点 top。
  输出：顶层发生概率与每个事件的 Birnbaum 重要度，
        P(top|事件=1) − P(top|事件=0)，均为约分分数字符串。

POST /v1/cut-sets
  输入格式与校验同 /v1/analyze（p 仍须合法，但不参与割集计算），
  仅接受 AND/OR 门（出现 NOT 返回 422）。
  输出：顶事件的全部最小割集；任一门去重、吸收后仍超过 5000 组
        时返回 422。

POST /v1/repair-plan
  另收覆盖全部事件 id 的 states（事件当前布尔状态）与
  repair_costs（1~10^6 的整数修复费用），其余输入与校验同上。
  只能把当前为 true 的事件修复为 false，共享引用共用一次修复；
  求令顶事件变为 false 的最优方案，依次按总成本、修复数、排序后的
  事件 id 序列取最小。顶事件原本为 false 时取空方案、零成本；
  无解时返回 possible=false。

POST /v1/diagnose
  另收 observations：1~16 个已声明事件或门 id 到严格布尔值的映射，
  表示同一时刻的读数。令 E 为全部读数同时成立；不同事件仍按原概率
  独立，同一事件的引用共享状态，AND/OR/NOT 均可观测。
  返回 evidence_probability=P(E) 与 posteriors（每个事件 id 的
  P(事件=1 且 E)/P(E)），均为约分 n/d 字符串。观测是条件证据，
  门读数不被当作相互独立的事件，也不修改先验；P(E)=0 返回 422。
  同一 ROBDD 合取观测约束后精确加权，不枚举事件状态；累计非终端
  节点超过 50000 或观测键/值非法时返回 422。

POST /v1/inspect-next
  另收 observations（0~16 个，可为空，格式同 /v1/diagnose）与
  candidates（1~16 个互异、已声明且未被观测的事件或门 id）。
  令 E 为已有读数的合取；对每个候选 X 求 E 下 X=true/false 的概率
  与对应分支的顶事件后验 q（零概率分支的 q 为 null），并以
  G(q)=2q(1-q) 衡量顶事件不确定性：收益 = G(P(top|E)) − 两分支按
  概率加权的 G(q)。返回按 id 排序的各候选分支概率、q 与收益，
  按收益最大、id 最小给出 recommended_id，分数均约分。同样复用
  ROBDD 精确计算，不枚举事件状态；P(E)=0、候选非法或累计非终端
  节点超过 50000 时返回 422。

POST /v1/likely-cause
  另收 observations（0~16 个，可为空，格式同 /v1/diagnose）。
  令 C 为顶事件发生且全部读数成立；在满足 C 的完整事件真假赋值
  A 中，按各事件独立先验乘积选 P(A) 最大者，并列时按事件 id
  字典序比较真假序列、false 优先。返回按 id 排列的 assignment、
  condition_probability=P(C) 与 assignment_posterior=P(A)/P(C)，
  分数均约分。共享引用、NOT 门与未被结构约束的事件都参与赋值及
  概率计算；复用 ROBDD 精确求最优赋值，不枚举事件状态；P(C)=0
  或累计非终端节点超过 50000 时返回 422。

POST /v1/compare-trees
  输入：共用一份 events（1~32 个独立事件，概率为 n/d 分数字符串），
        baseline 与 revised 各提供 gates（0~64 个布尔门 AND/OR/NOT）
        与顶层节点 top；两版各自沿用 /v1/analyze 的全部校验，门 id
        可同名但定义相互独立，不能跨版引用，同一事件在两版共享状态
        与先验。
  输出：设两版顶事件为 B、R，added_probability=P(¬B∧R)、
        removed_probability=P(B∧¬R)、change_probability=P(B⊕R)，
        均为约分 n/d；equivalent 仅在全部事件赋值下 B 与 R 都相同
        时为 true（零概率赋值上的差异仍算不等价）。用同一变量顺序
        与共享 ROBDD 精确计算，不枚举事件状态；两版建图及差异运算
        累计非终端节点超过 50000 时返回 422。

POST /v1/failure-count
  输入格式与校验同 /v1/analyze（events、gates、top）。
  令 T 为顶事件发生，K 为请求中全部已声明事件里取 true 的个数
  （包括未被顶层引用的事件；同一 id 的重复引用只计一次，NOT 门
  照常求值）。返回 top_probability=P(T) 与 count_distribution：
  数组下标 k 对应 P(K=k|T)，覆盖 k=0 到事件总数，均为约分 n/d
  字符串。在同一 ROBDD 上以生成函数动态规划精确计数，不枚举事件
  状态；被约简跳过的变量及到达终端后剩余的变量按各自先验计入；
  P(T)=0 或累计非终端节点超过 50000 时返回 422。

POST /v1/first-failure-time
  events 限 1~8 个，gates、top 沿用 /v1/analyze 的全部校验；另收
  steps（1~10 的转移步数）与 transitions（覆盖全部事件 id，每项
  含 fail、recover 两个 n/d 概率）。t=0 各事件按自身 p 独立生成
  初始状态；此后每步，正常（false）事件以 fail 故障，故障（true）
  事件以 recover 恢复，给定上一步状态后各事件独立转移。每步按
  共享事件状态及 AND/OR/NOT 求顶事件。返回 first_hit_distribution：
  下标 t（0~steps）对应顶事件首次在第 t 步发生的概率，以及
  no_hit_probability=全程未发生的概率，均为约分 n/d。仅对未触发
  （顶事件尚未发生）状态做概率动态规划；steps/transitions 非法、
  转移项缺失、多余或 fail/recover 非法概率时返回 422。

POST /v1/observation-conflicts
  另收 observations：1~16 个已声明事件或门 id 到严格布尔值的映射，
  表示同一时刻的一组读数。返回全部最小零概率观测组：组内读数同时
  成立的先验概率为 0，且删去组内任一项后概率大于 0；全部读数可同时
  成立时返回空组列。门读数按共享事件状态求值，NOT 照常生效；p 为
  0/1 或 1/1 造成的零概率同样识别。响应 conflicts 每组只列观测 id，
  组内按 id 排序，组间按长度及字典序排序。把 p∈{0,1} 事件的强制文字
  折叠进各观测约束后，在共享 ROBDD 上按观测子集枚举合取作精确判定，
  不枚举事件赋值；结果超过 5000 组或累计非终端节点超过 50000 时
  返回 422。

POST /v1/expand-model
  输入：events（同 /v1/analyze）、templates（1~8 个名称→模板定义）、
        root（template、bindings）。模板含 params（参数名列表）、
        gates（非空，门定义同 /v1/analyze）、instances（实例列表：
        id、template、bindings）与 top。所有名称以 ASCII 字母开头、
        后接字母数字下划线；模板内参数/门/实例名两两互异。root 的
        参数绑定事件 id；子实例参数只能绑定父模板参数；bindings
        恰好覆盖被调模板的参数。门 inputs/top 引用本地参数、本地门
        或子实例（其顶层输出）。
  输出：递归展开全部实例的扁平故障树：events 原样返回；门名为
        root/实例路径/门名（如 root.pump.fan/g1），参数引用解析为
        root 绑定的共享事件 id（保留原事件 id）；顶层节点为
        root/<root 模板 top>（top 为参数时直接为事件 id）。展开结果
        本身即为合法的 /v1/analyze 请求体。模板递归（实例调用成环）、
        绑定错误、未知引用、名称冲突、门环、引用未定义模板或展开后
        门数超过 64 时返回 422。

所有错误输入（未知引用、跨版引用、环、非法概率、节点超限等）统一返回 422。
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Callable, Dict, List, Literal, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, StrictInt
from pydantic.config import ConfigDict

from .bdd import MAX_NONTERMINAL_NODES, NodeLimitExceeded, ROBDD
from .conflicts import minimal_zero_prob_groups
from .cutsets import compute_cut_set_families
from .first_hit import first_failure_distribution, top_hit_masks
from .likely import most_likely_assignment
from .repair import best_repair

app = FastAPI(
    title="共享事件故障概率 API",
    description="基于 ROBDD 的精确故障树顶事件概率与事件重要度计算",
    version="1.0.0",
)

GateOp = Literal["AND", "OR", "NOT"]


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="唯一 ASCII 事件标识")
    p: str = Field(..., description="发生概率，n/d 形式，0<=n<=d<=10^6")


class GateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="唯一 ASCII 门标识")
    op: GateOp = Field(..., description="门算子：AND / OR / NOT")
    inputs: List[str] = Field(..., description="输入引用，可为事件或门")


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")


class AnalyzeResponse(BaseModel):
    top_probability: str
    importances: Dict[str, str]


class CutSetsResponse(BaseModel):
    cut_sets: List[List[str]]


class RepairPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")
    states: Dict[str, StrictBool] = Field(
        ..., description="每个事件的当前状态：true=发生，false=未发生"
    )
    repair_costs: Dict[str, StrictInt] = Field(
        ..., description="每个事件的修复费用，取值 1~10^6 的整数"
    )


class RepairPlanResponse(BaseModel):
    possible: bool
    repair_events: List[str]
    total_cost: Optional[int]


class DiagnoseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")
    observations: Dict[str, StrictBool] = Field(
        ...,
        min_length=1,
        max_length=16,
        description=(
            "同一时刻的读数：1~16 个已声明事件或门 id 到严格布尔值的映射"
        ),
    )


class DiagnoseResponse(BaseModel):
    evidence_probability: str
    posteriors: Dict[str, str]


class InspectNextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")
    observations: Dict[str, StrictBool] = Field(
        default_factory=dict,
        max_length=16,
        description=(
            "已有读数：0~16 个已声明事件或门 id 到严格布尔值的映射，可为空"
        ),
    )
    candidates: List[str] = Field(
        ...,
        min_length=1,
        max_length=16,
        description="待评估的候选：1~16 个互异、已声明且未被观测的事件或门 id",
    )


class InspectBranch(BaseModel):
    probability: str = Field(..., description="E 下该分支的概率，约分 n/d")
    q: Optional[str] = Field(
        ..., description="该分支下顶事件后验 P(top|E∧分支)；零概率分支为 null"
    )


class InspectCandidate(BaseModel):
    id: str
    branches: Dict[Literal["true", "false"], InspectBranch]
    gain: str = Field(..., description="观测该候选的收益，约分 n/d")


class InspectNextResponse(BaseModel):
    evidence_probability: str
    top_posterior: str = Field(..., description="P(top|E)，约分 n/d")
    candidates: List[InspectCandidate]
    recommended_id: str


class LikelyCauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")
    observations: Dict[str, StrictBool] = Field(
        default_factory=dict,
        max_length=16,
        description=(
            "已有读数：0~16 个已声明事件或门 id 到严格布尔值的映射，可为空"
        ),
    )


class LikelyCauseResponse(BaseModel):
    assignment: Dict[str, StrictBool] = Field(
        ..., description="P(A) 最大的完整事件赋值，按事件 id 字典序排列"
    )
    condition_probability: str = Field(
        ..., description="P(C)：顶事件发生且全部读数成立的概率，约分 n/d"
    )
    assignment_posterior: str = Field(
        ..., description="P(A)/P(C)，约分 n/d"
    )


class TreeVersion(BaseModel):
    """/v1/compare-trees 中一个版本的故障树：gates 与顶层节点 top。"""

    model_config = ConfigDict(extra="forbid")

    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")


class CompareTreesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    baseline: TreeVersion = Field(..., description="基线版本的 gates 与 top")
    revised: TreeVersion = Field(..., description="改版版本的 gates 与 top")


class CompareTreesResponse(BaseModel):
    added_probability: str = Field(
        ..., description="P(¬B∧R)：改版新增顶事件情形的概率，约分 n/d"
    )
    removed_probability: str = Field(
        ..., description="P(B∧¬R)：改版移除顶事件情形的概率，约分 n/d"
    )
    change_probability: str = Field(
        ..., description="P(B⊕R)：两版顶事件不一致的概率，约分 n/d"
    )
    equivalent: bool = Field(
        ...,
        description="全部事件赋值下 B 与 R 都相同时为 true；"
        "零概率赋值上的差异仍算不等价",
    )


class FailureCountResponse(BaseModel):
    top_probability: str = Field(..., description="P(T)：顶事件发生概率，约分 n/d")
    count_distribution: List[str] = Field(
        ...,
        description="下标 k 对应 P(K=k|T)：顶事件发生时全部已声明事件中"
        "恰有 k 个取 true 的条件概率，覆盖 k=0 到事件总数，约分 n/d",
    )


class TransitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fail: str = Field(
        ..., description="每步正常事件发生故障的概率，n/d 形式，0<=n<=d<=10^6"
    )
    recover: str = Field(
        ..., description="每步故障事件恢复正常的概率，n/d 形式，0<=n<=d<=10^6"
    )


class FirstFailureTimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=8)
    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")
    steps: StrictInt = Field(..., description="转移步数，取值 1~10 的整数")
    transitions: Dict[str, TransitionIn] = Field(
        ...,
        description="覆盖全部事件 id 的转移参数：每项含 fail、recover 两个 n/d 概率",
    )


class FirstFailureTimeResponse(BaseModel):
    first_hit_distribution: List[str] = Field(
        ...,
        description="下标 t（0~steps）对应顶事件首次在第 t 步发生的概率，"
        "各项为约分 n/d",
    )
    no_hit_probability: str = Field(
        ..., description="直到第 steps 步顶事件始终未发生的概率，约分 n/d"
    )


class ObservationConflictsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    gates: List[GateIn] = Field(default_factory=list, max_length=64)
    top: str = Field(..., min_length=1, description="顶层节点 id（事件或门）")
    observations: Dict[str, StrictBool] = Field(
        ...,
        min_length=1,
        max_length=16,
        description=(
            "同一时刻的读数：1~16 个已声明事件或门 id 到严格布尔值的映射"
        ),
    )


class ObservationConflictsResponse(BaseModel):
    conflicts: List[List[str]] = Field(
        ...,
        description="全部最小零概率观测组：每组只列观测 id，组内按 id 排序，"
        "组间按长度及字典序排序；全部读数可同时成立时为空",
    )


class TemplateGateIn(BaseModel):
    """模板内的门定义：id 为模板内局部名称。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="模板内唯一的局部门名")
    op: GateOp = Field(..., description="门算子：AND / OR / NOT")
    inputs: List[str] = Field(
        ..., min_length=1, description="输入引用：本地参数、本地门或子实例"
    )


class TemplateInstanceIn(BaseModel):
    """模板内的子实例：以另一模板为结构，bindings 把该模板参数绑到父参数。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="模板内唯一的局部实例名")
    template: str = Field(..., min_length=1, description="调用的模板名称")
    bindings: Dict[str, str] = Field(
        ...,
        description="被调模板参数名 → 父模板参数名；必须恰好覆盖被调模板参数",
    )


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: List[str] = Field(
        default_factory=list, description="形参名列表（可为空），仅由 root 绑定事件"
    )
    gates: List[TemplateGateIn] = Field(..., min_length=1, description="非空门列表")
    instances: List[TemplateInstanceIn] = Field(
        default_factory=list, description="子实例列表（可为空）"
    )
    top: str = Field(
        ..., min_length=1, description="顶层引用：本地参数、本地门或子实例"
    )


class RootInstanceIn(BaseModel):
    """根实例：参数绑定到全局事件 id。"""

    model_config = ConfigDict(extra="forbid")

    template: str = Field(..., min_length=1, description="根模板名称")
    bindings: Dict[str, str] = Field(
        ...,
        description="根模板参数名 → 事件 id；必须恰好覆盖根模板参数",
    )


class ExpandModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: List[EventIn] = Field(..., min_length=1, max_length=32)
    templates: Dict[str, TemplateIn] = Field(
        ..., min_length=1, max_length=8, description="1~8 个模板名称→模板定义"
    )
    root: RootInstanceIn = Field(..., description="根实例：模板名与事件绑定")


class ExpandModelResponse(BaseModel):
    events: List[EventIn] = Field(..., description="原 events，原样返回")
    gates: List[GateIn] = Field(
        ..., description="展开后的全部门，门名为 root/实例路径/门名"
    )
    top: str = Field(..., description="展开后的顶层节点 id（事件 id 或全路径门名）")


def _bad_request(reason: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": reason})


def _parse_probability(raw: str) -> Fraction:
    """解析 n/d 形式的概率：必须严格为非负整数/正整数，且 n<=d<=10^6。"""
    parts = raw.split("/")
    if len(parts) != 2:
        raise ValueError(f"非法概率 {raw!r}：必须为 n/d 形式")
    ns, ds = parts
    if not ns or not ds:
        raise ValueError(f"非法概率 {raw!r}：分子或分母为空")
    # 严格十进制整数：拒绝符号、空白、前导 + 等
    if not (ns.isdigit() and ds.isdigit()):
        raise ValueError(f"非法概率 {raw!r}：分子分母必须为非负十进制整数")
    n, d = int(ns), int(ds)
    if d == 0:
        raise ValueError(f"非法概率 {raw!r}：分母不能为 0")
    if n > d:
        raise ValueError(f"非法概率 {raw!r}：分子不能大于分母")
    if d > 1_000_000:
        raise ValueError(f"非法概率 {raw!r}：分母不能超过 10^6")
    return Fraction(n, d)


def _is_ascii_nonempty(s: str) -> bool:
    return len(s) > 0 and s.isascii()


def _validate_events(events: List[EventIn]) -> Dict[str, Fraction]:
    """事件 id 与概率的静态校验，返回事件概率表。"""
    probs: Dict[str, Fraction] = {}
    for ev in events:
        if not _is_ascii_nonempty(ev.id):
            raise ValueError(f"非法事件 id {ev.id!r}：必须为非空 ASCII 字符串")
        if ev.id in probs:
            raise ValueError(f"事件 id 重复：{ev.id!r}")
        probs[ev.id] = _parse_probability(ev.p)
    return probs


def _validate_gates(
    probs: Dict[str, Fraction],
    gates: List[GateIn],
    top: str,
) -> "tuple[Dict[str, GateOp], Dict[str, List[str]]]":
    """门与顶层节点的全部静态校验，返回 (门算子表, 门输入表)。

    id 冲突/重复、元数错误、未知引用、环等均抛 ValueError；引用只能
    指向 probs 中的事件或本门列表内的门（对 /v1/compare-trees 而言
    即同一版本内的门，跨版引用由调用方先行拦截）。
    """
    # ---- 门：id、算子输入元数、重复 ----
    gate_ops: Dict[str, GateOp] = {}
    gate_inputs: Dict[str, List[str]] = {}
    for gate in gates:
        if not _is_ascii_nonempty(gate.id):
            raise ValueError(f"非法门 id {gate.id!r}：必须为非空 ASCII 字符串")
        if gate.id in probs:
            raise ValueError(f"门 id 与事件 id 冲突：{gate.id!r}")
        if gate.id in gate_ops:
            raise ValueError(f"门 id 重复：{gate.id!r}")
        n_inputs = len(gate.inputs)
        if gate.op == "NOT":
            if n_inputs != 1:
                raise ValueError(
                    f"门 {gate.id!r} 为 NOT，必须恰好有 1 个输入，实际 {n_inputs} 个"
                )
        elif n_inputs < 2 or n_inputs > 8:
            raise ValueError(
                f"门 {gate.id!r} 为 {gate.op}，必须有 2~8 个输入，实际 {n_inputs} 个"
            )
        gate_ops[gate.id] = gate.op
        gate_inputs[gate.id] = list(gate.inputs)

    known_ids = set(probs) | set(gate_ops)

    # ---- 引用完整性（门输入与顶层节点）----
    for gid, inputs in gate_inputs.items():
        for ref in inputs:
            if ref not in known_ids:
                raise ValueError(f"门 {gid!r} 引用了未知节点：{ref!r}")
    if top not in known_ids:
        raise ValueError(f"顶层节点引用了未知 id：{top!r}")

    # ---- 环检测：门依赖图上的 DFS 三色标记 ----
    # 0=未访问, 1=在当前递归栈中, 2=已完成
    color: Dict[str, int] = {gid: 0 for gid in gate_ops}

    def dfs(node_id: str) -> None:
        if node_id not in color:  # 事件节点是叶子
            return
        if color[node_id] == 1:
            raise ValueError(f"门的引用关系存在环（涉及门 {node_id!r}）")
        if color[node_id] == 2:
            return
        color[node_id] = 1
        for child in gate_inputs[node_id]:
            dfs(child)
        color[node_id] = 2

    for gid in gate_ops:
        dfs(gid)

    return gate_ops, gate_inputs


def _validate_payload(
    payload: AnalyzeRequest,
) -> "tuple[Dict[str, Fraction], Dict[str, GateOp], Dict[str, List[str]]]":
    """事件与门的全部静态校验，返回 (事件概率表, 门算子表, 门输入表)。

    非法概率、id 冲突/重复、元数错误、未知引用、环等均抛 ValueError。
    """
    probs = _validate_events(payload.events)
    gate_ops, gate_inputs = _validate_gates(probs, payload.gates, payload.top)
    return probs, gate_ops, gate_inputs


def _make_evaluator(
    bdd: ROBDD,
    event_nodes: Dict[str, int],
    gate_ops: Dict[str, GateOp],
    gate_inputs: Dict[str, List[str]],
) -> Tuple[Callable[[str], int], Dict[str, int]]:
    """返回 (按 id 求值门的函数, 已建门节点表)，在共享 ROBDD 上求值。

    同一事件的多处引用共用同一个基础变量节点；NOT 门以 BDD 取反求值。
    已建门节点表归属单次调用：/v1/compare-trees 两版各自求值时同名
    门的定义互不影响，但全部节点都落在同一唯一表中。
    """
    built: Dict[str, int] = {}

    def eval_node(node_id: str) -> int:
        if node_id in event_nodes:
            return event_nodes[node_id]
        if node_id in built:
            return built[node_id]
        op = gate_ops[node_id]
        inputs = gate_inputs[node_id]
        if op == "NOT":
            result = bdd.negate(eval_node(inputs[0]))
        else:
            result = eval_node(inputs[0])
            for ref in inputs[1:]:
                nxt = eval_node(ref)
                if op == "AND":
                    result = bdd.and_(result, nxt)
                else:
                    result = bdd.or_(result, nxt)
        built[node_id] = result
        return result

    return eval_node, built


def build_tree_robdd(
    probs: Dict[str, Fraction],
    gate_ops: Dict[str, GateOp],
    gate_inputs: Dict[str, List[str]],
    top: str,
    also: Tuple[str, ...] = (),
) -> Tuple[List[str], ROBDD, int, Dict[str, int]]:
    """按事件 id 字典序为变量顺序构建故障树的 ROBDD。

    返回 (字典序事件 id 列表, ROBDD, 顶层节点 id, 节点表)。同一事件
    的多处引用共用同一个基础变量节点；NOT 门以 BDD 取反求值。
    also 中列出的额外门 id（必须已通过引用/环校验）也一并求值并
    收入节点表，供观测等场景按门 id 取其 BDD 节点。
    """
    sorted_events = sorted(probs)
    var_index = {eid: i for i, eid in enumerate(sorted_events)}

    bdd = ROBDD(
        n_vars=len(sorted_events), limit=MAX_NONTERMINAL_NODES
    )

    # 事件变量对应只含自身判定的基础节点
    event_nodes = {
        eid: bdd.mk(var_index[eid], 0, 1) for eid in sorted_events
    }

    eval_node, built = _make_evaluator(bdd, event_nodes, gate_ops, gate_inputs)
    top_node = eval_node(top)
    for node_id in also:
        eval_node(node_id)
    node_map: Dict[str, int] = {**event_nodes, **built}
    return sorted_events, bdd, top_node, node_map


def analyze_logic(payload: AnalyzeRequest) -> AnalyzeResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)

    sorted_events, bdd, top_node, _ = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top
    )
    prob_list = [probs[eid] for eid in sorted_events]
    top_prob, importance = bdd.root_probability(top_node, prob_list)

    def frac_string(value: Fraction) -> str:
        # 统一输出约分后的 n/d（整数时分母为 1）
        return f"{value.numerator}/{value.denominator}"

    return AnalyzeResponse(
        top_probability=frac_string(top_prob),
        importances={eid: frac_string(importance[i])
                     for i, eid in enumerate(sorted_events)},
    )


def cut_sets_logic(payload: AnalyzeRequest) -> CutSetsResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)

    # 割集仅适用于单调结构：NOT 会破坏“组内事件同时发生则顶事件
    # 必然发生”的语义，凡出现 NOT 门一律拒绝
    for gid, op in gate_ops.items():
        if op == "NOT":
            raise ValueError(
                f"门 {gid!r} 为 NOT：最小割集仅支持 AND/OR 单调结构，"
                f"含取反的概率分析请使用 /v1/analyze"
            )

    sorted_events = sorted(probs)
    families = compute_cut_set_families(sorted_events, gate_ops, gate_inputs)
    if payload.top in probs:
        top_masks = {1 << sorted_events.index(payload.top)}
    else:
        top_masks = families[payload.top]

    # 位序即事件 id 字典序，展开后组内天然有序
    cut_lists = [
        [eid for i, eid in enumerate(sorted_events) if mask >> i & 1]
        for mask in top_masks
    ]
    # 组间：先按割集长度，再按事件 id 字典序
    cut_lists.sort(key=lambda ids: (len(ids), ids))
    return CutSetsResponse(cut_sets=cut_lists)


def _check_cover(
    values: Dict[str, object], event_ids: List[str], field: str
) -> List[str]:
    """检查 field 的键集合恰好覆盖全部事件 id，返回收集到的错误信息。"""
    errors: List[str] = []
    missing = [eid for eid in event_ids if eid not in values]
    extra = [k for k in values if k not in event_ids]
    if missing:
        errors.append(
            f"{field} 缺少事件的对应项：{', '.join(repr(e) for e in missing)}"
        )
    if extra:
        errors.append(
            f"{field} 出现了不属于任何事件的键："
            f"{', '.join(repr(e) for e in extra)}"
        )
    return errors


def repair_plan_logic(payload: RepairPlanRequest) -> RepairPlanResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)
    sorted_events = sorted(probs)

    # states 与 repair_costs 必须恰好覆盖全部事件 id；多项错误一并返回
    errors = _check_cover(payload.states, sorted_events, "states")
    errors += _check_cover(
        payload.repair_costs, sorted_events, "repair_costs"
    )
    if errors:
        raise ValueError("；".join(errors))

    # 修复费用：1~10^6 的整数
    bad_costs = [
        f"{eid!r}={payload.repair_costs[eid]}"
        for eid in sorted_events
        if not 1 <= payload.repair_costs[eid] <= 1_000_000
    ]
    if bad_costs:
        raise ValueError(
            "repair_costs 的取值必须为 1~10^6 的整数，非法项："
            + ", ".join(bad_costs)
        )

    sorted_events, bdd, top_node, _ = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top
    )

    fixed_false_mask = 0
    for i, eid in enumerate(sorted_events):
        if payload.states[eid] is False:
            fixed_false_mask |= 1 << i
    costs = [payload.repair_costs[eid] for eid in sorted_events]

    plan = best_repair(bdd, top_node, fixed_false_mask, costs)
    if plan is None:
        return RepairPlanResponse(
            possible=False, repair_events=[], total_cost=None
        )
    total_cost, mask = plan
    repair_events = [
        eid for i, eid in enumerate(sorted_events) if mask >> i & 1
    ]
    return RepairPlanResponse(
        possible=True, repair_events=repair_events, total_cost=total_cost
    )


def diagnose_logic(payload: DiagnoseRequest) -> DiagnoseResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)
    sorted_events = sorted(probs)

    # 观测键必须指向已声明的事件或门（门读数只是结构约束，不是相互
    # 独立的新事件；非法键多项时一并报错）
    known_ids = set(probs) | set(gate_ops)
    unknown = [k for k in payload.observations if k not in known_ids]
    if unknown:
        raise ValueError(
            "observations 引用了未声明的事件或门 id："
            + ", ".join(repr(k) for k in unknown)
        )

    # 被观测的门（即便 top 不可达）也要构建到同一 ROBDD 中
    observed_gates = tuple(
        k for k in payload.observations if k in gate_ops
    )
    _, bdd, _, node_map = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top, also=observed_gates
    )

    # 在同一 ROBDD 上把各观测约束（node == 布尔读数）合取：
    # 读 1 即门/事件本身，读 0 即其 BDD 取反；同一事件/门的多处
    # 引用共享同一 BDD 节点，天然共享状态
    evidence = 1
    for obs_id, value in payload.observations.items():
        lit = node_map[obs_id]
        constraint = lit if value else bdd.negate(lit)
        evidence = bdd.and_(evidence, constraint)
        if evidence == 0:
            # 短路：结构上已不可同时满足，无需继续合取
            break

    prob_list = [probs[eid] for eid in sorted_events]
    evidence_prob, joint = bdd.joint_probabilities(evidence, prob_list)

    if evidence_prob == 0:
        if evidence == 0:
            raise ValueError(
                "观测相互矛盾：给定的事件/门读数不可能在同一时刻"
                "同时成立（结构约束的合取恒为假），evidence_probability=0"
            )
        raise ValueError(
            "观测的联合概率为 0：尽管结构上可满足，但按各事件的独立"
            "先验概率，任一使全部读数成立的事件状态概率都为 0"
            "（例如读数要求概率为 0 的事件发生），evidence_probability=0"
        )

    def frac_string(value: Fraction) -> str:
        return f"{value.numerator}/{value.denominator}"

    return DiagnoseResponse(
        evidence_probability=frac_string(evidence_prob),
        posteriors={
            eid: frac_string(joint[i] / evidence_prob)
            for i, eid in enumerate(sorted_events)
        },
    )


def inspect_next_logic(payload: InspectNextRequest) -> InspectNextResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)
    sorted_events = sorted(probs)
    known_ids = set(probs) | set(gate_ops)

    # 观测键必须指向已声明的事件或门（同 /v1/diagnose）
    unknown = [k for k in payload.observations if k not in known_ids]
    if unknown:
        raise ValueError(
            "observations 引用了未声明的事件或门 id："
            + ", ".join(repr(k) for k in unknown)
        )

    # 候选校验：互异、已声明、未被观测；多项问题一并返回
    cand_errors: List[str] = []
    seen: set = set()
    dup: List[str] = []
    for cid in payload.candidates:
        if cid in seen and cid not in dup:
            dup.append(cid)
        seen.add(cid)
    if dup:
        cand_errors.append(
            "candidates 中存在重复的 id："
            + ", ".join(repr(c) for c in dup)
        )
    unknown_c = list(
        dict.fromkeys(c for c in payload.candidates if c not in known_ids)
    )
    if unknown_c:
        cand_errors.append(
            "candidates 引用了未声明的事件或门 id："
            + ", ".join(repr(c) for c in unknown_c)
        )
    observed_c = list(
        dict.fromkeys(
            c for c in payload.candidates if c in payload.observations
        )
    )
    if observed_c:
        cand_errors.append(
            "candidates 必须未被观测，以下 id 已出现在 observations 中："
            + ", ".join(repr(c) for c in observed_c)
        )
    if cand_errors:
        raise ValueError("；".join(cand_errors))

    # 被观测/被候选的门（即便 top 不可达）也构建到同一 ROBDD 中
    extra_gates = tuple(
        k
        for k in list(payload.observations) + list(dict.fromkeys(payload.candidates))
        if k in gate_ops
    )
    _, bdd, top_node, node_map = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top, also=extra_gates
    )

    # 证据 E：各观测约束的合取（同 /v1/diagnose）
    evidence = 1
    for obs_id, value in payload.observations.items():
        lit = node_map[obs_id]
        constraint = lit if value else bdd.negate(lit)
        evidence = bdd.and_(evidence, constraint)
        if evidence == 0:
            break

    prob_list = [probs[eid] for eid in sorted_events]
    node_prob = bdd.node_probabilities(prob_list)
    evidence_prob = node_prob[evidence]

    if evidence_prob == 0:
        if evidence == 0:
            raise ValueError(
                "观测相互矛盾：给定的事件/门读数不可能在同一时刻"
                "同时成立（结构约束的合取恒为假），evidence_probability=0"
            )
        raise ValueError(
            "观测的联合概率为 0：尽管结构上可满足，但按各事件的独立"
            "先验概率，任一使全部读数成立的事件状态概率都为 0"
            "（例如读数要求概率为 0 的事件发生），evidence_probability=0"
        )

    # 先把全部分支合取构建完，再一次遍历读出所有根的概率：
    #   E∧top、每个候选的 E∧X 与 E∧X∧top；
    # 假分支用减法精确得到：P(E∧¬X)=P(E)−P(E∧X)，
    #   P(E∧¬X∧top)=P(E∧top)−P(E∧X∧top)，无需再建取反合取
    top_and_e = bdd.and_(top_node, evidence)
    branch_nodes: Dict[str, Tuple[int, int]] = {}
    for cid in dict.fromkeys(payload.candidates):
        e_and_x = bdd.and_(evidence, node_map[cid])
        e_and_x_top = bdd.and_(e_and_x, top_node)
        branch_nodes[cid] = (e_and_x, e_and_x_top)
    node_prob = bdd.node_probabilities(prob_list)

    top_and_e_prob = node_prob[top_and_e]
    q_e = top_and_e_prob / evidence_prob  # P(top|E)

    def g_uncertainty(q: Fraction) -> Fraction:
        return 2 * q * (1 - q)

    def frac_string(value: Fraction) -> str:
        return f"{value.numerator}/{value.denominator}"

    results: List[InspectCandidate] = []
    for cid in sorted(branch_nodes):
        e_and_x, e_and_x_top = branch_nodes[cid]
        p_ex = node_prob[e_and_x]          # P(E ∧ X)
        p_ext = node_prob[e_and_x_top]     # P(E ∧ X ∧ top)
        p_true = p_ex / evidence_prob
        p_false = 1 - p_true
        # 零概率分支的后验无定义，记 null；其加权收益贡献为 0
        q_true = (p_ext / p_ex) if p_ex > 0 else None
        rest = evidence_prob - p_ex        # P(E ∧ ¬X)
        q_false = (
            (top_and_e_prob - p_ext) / rest if rest > 0 else None
        )
        gain = g_uncertainty(q_e)
        if q_true is not None:
            gain -= p_true * g_uncertainty(q_true)
        if q_false is not None:
            gain -= p_false * g_uncertainty(q_false)
        results.append(
            InspectCandidate(
                id=cid,
                branches={
                    "true": InspectBranch(
                        probability=frac_string(p_true),
                        q=frac_string(q_true) if q_true is not None else None,
                    ),
                    "false": InspectBranch(
                        probability=frac_string(p_false),
                        q=frac_string(q_false)
                        if q_false is not None
                        else None,
                    ),
                },
                gain=frac_string(gain),
            )
        )

    # 收益最大者优先，并列取 id 最小（results 已按 id 升序，严格更大才替换）
    best = results[0]
    best_gain = Fraction(best.gain)
    for cand in results[1:]:
        cand_gain = Fraction(cand.gain)
        if cand_gain > best_gain:
            best, best_gain = cand, cand_gain

    return InspectNextResponse(
        evidence_probability=frac_string(evidence_prob),
        top_posterior=frac_string(q_e),
        candidates=results,
        recommended_id=best.id,
    )


def likely_cause_logic(payload: LikelyCauseRequest) -> LikelyCauseResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)
    sorted_events = sorted(probs)

    # 观测键必须指向已声明的事件或门（同 /v1/diagnose）
    known_ids = set(probs) | set(gate_ops)
    unknown = [k for k in payload.observations if k not in known_ids]
    if unknown:
        raise ValueError(
            "observations 引用了未声明的事件或门 id："
            + ", ".join(repr(k) for k in unknown)
        )

    # 被观测的门（即便 top 不可达）也要构建到同一 ROBDD 中
    observed_gates = tuple(
        k for k in payload.observations if k in gate_ops
    )
    _, bdd, top_node, node_map = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top, also=observed_gates
    )

    # 条件 C：顶事件发生且全部读数成立（同一 ROBDD 上的合取）
    condition = top_node
    for obs_id, value in payload.observations.items():
        lit = node_map[obs_id]
        constraint = lit if value else bdd.negate(lit)
        condition = bdd.and_(condition, constraint)
        if condition == 0:
            # 短路：结构上已不可同时满足，无需继续合取
            break

    prob_list = [probs[eid] for eid in sorted_events]
    node_prob = bdd.node_probabilities(prob_list)
    condition_prob = node_prob[condition]

    if condition_prob == 0:
        if condition == 0:
            raise ValueError(
                "顶事件与观测相互矛盾：顶事件发生且全部读数同时成立在"
                "结构上不可能（结构约束的合取恒为假），"
                "condition_probability=0"
            )
        raise ValueError(
            "顶事件发生且全部读数同时成立的联合概率为 0：尽管结构上"
            "可满足，但按各事件的独立先验概率，任一满足条件的事件状态"
            "概率都为 0（例如读数要求概率为 0 的事件发生），"
            "condition_probability=0"
        )

    # 在满足 C 的完整赋值中取独立先验乘积最大者（ROBDD 动态规划，
    # 不枚举事件状态）；未被结构约束的事件按自由变量取较可能一侧
    best_weight, assignment = most_likely_assignment(
        bdd, condition, prob_list
    )

    def frac_string(value: Fraction) -> str:
        return f"{value.numerator}/{value.denominator}"

    return LikelyCauseResponse(
        assignment={
            eid: assignment[i] for i, eid in enumerate(sorted_events)
        },
        condition_probability=frac_string(condition_prob),
        assignment_posterior=frac_string(best_weight / condition_prob),
    )


def _validate_version_gates(
    probs: Dict[str, Fraction],
    version: TreeVersion,
    other: TreeVersion,
    label: str,
) -> "tuple[Dict[str, GateOp], Dict[str, List[str]]]":
    """校验 /v1/compare-trees 一个版本的 gates/top，返回 (门算子表, 门输入表)。

    两版门 id 可同名但定义相互独立：引用只能指向共享事件或本版本的
    门；指向另一版本独有的门 id 属于跨版引用，先行拦截并单独说明，
    其余校验（元数、未知引用、环等）与 /v1/analyze 完全一致。
    """
    own_gate_ids = {g.id for g in version.gates}
    other_gate_ids = {g.id for g in other.gates}

    def is_cross_ref(ref: str) -> bool:
        return (
            ref not in probs
            and ref not in own_gate_ids
            and ref in other_gate_ids
        )

    cross = sorted(
        {ref for g in version.gates for ref in g.inputs if is_cross_ref(ref)}
        | ({version.top} if is_cross_ref(version.top) else set())
    )
    if cross:
        raise ValueError(
            f"{label} 跨版引用了另一版本的门："
            + ", ".join(repr(c) for c in cross)
            + "；两版门 id 可同名但定义相互独立，不能跨版引用"
        )
    return _validate_gates(probs, version.gates, version.top)


def compare_trees_logic(payload: CompareTreesRequest) -> CompareTreesResponse:
    # 事件共用一份：id、概率校验一次，两版共享状态与先验
    probs = _validate_events(payload.events)
    base_ops, base_inputs = _validate_version_gates(
        probs, payload.baseline, payload.revised, "baseline"
    )
    rev_ops, rev_inputs = _validate_version_gates(
        probs, payload.revised, payload.baseline, "revised"
    )

    sorted_events = sorted(probs)
    var_index = {eid: i for i, eid in enumerate(sorted_events)}

    # 两版共用同一变量顺序与同一 ROBDD（同一唯一表），节点限额对
    # 两版建图及后续差异运算累计生效
    bdd = ROBDD(n_vars=len(sorted_events), limit=MAX_NONTERMINAL_NODES)
    event_nodes = {
        eid: bdd.mk(var_index[eid], 0, 1) for eid in sorted_events
    }

    base_eval, _ = _make_evaluator(bdd, event_nodes, base_ops, base_inputs)
    rev_eval, _ = _make_evaluator(bdd, event_nodes, rev_ops, rev_inputs)
    base_top = base_eval(payload.baseline.top)
    rev_top = rev_eval(payload.revised.top)

    # ROBDD 规范化：根节点相同 ⟺ 全部事件赋值下两版顶事件取值都相同
    # （零概率赋值上的差异同样体现为不同节点，仍算不等价）
    equivalent = base_top == rev_top

    # 差异运算：added = ¬B∧R，removed = B∧¬R，change = B⊕R（两者之并）
    added = bdd.and_(bdd.negate(base_top), rev_top)
    removed = bdd.and_(base_top, bdd.negate(rev_top))
    change = bdd.or_(added, removed)

    # 对唯一表做一次自底向上加权，同时读出三个差异根的概率
    prob_list = [probs[eid] for eid in sorted_events]
    node_prob = bdd.node_probabilities(prob_list)

    def frac_string(value: Fraction) -> str:
        # 统一输出约分后的 n/d（整数时分母为 1）
        return f"{value.numerator}/{value.denominator}"

    return CompareTreesResponse(
        added_probability=frac_string(node_prob[added]),
        removed_probability=frac_string(node_prob[removed]),
        change_probability=frac_string(node_prob[change]),
        equivalent=equivalent,
    )


def failure_count_logic(payload: AnalyzeRequest) -> FailureCountResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)

    sorted_events, bdd, top_node, _ = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top
    )
    prob_list = [probs[eid] for eid in sorted_events]
    # joint[k] = P(K=k 且 T)；K 计入全部已声明事件（含顶层未引用的），
    # 同一 id 的重复引用对应同一变量，只计一次
    joint = bdd.count_distribution(top_node, prob_list)
    top_prob = sum(joint, Fraction(0))  # P(T) = Σ_k P(K=k 且 T)

    if top_prob == 0:
        if top_node == 0:
            raise ValueError(
                "顶事件在结构上不可能发生：顶事件的 BDD 恒为假，"
                "top_probability=0，无法计算条件分布 P(K=k|T)"
            )
        raise ValueError(
            "顶事件发生的概率为 0：尽管结构上可满足，但按各事件的独立"
            "先验概率，任一使顶事件发生的事件状态概率都为 0"
            "（例如顶事件要求概率为 0 的事件发生），top_probability=0，"
            "无法计算条件分布 P(K=k|T)"
        )

    def frac_string(value: Fraction) -> str:
        # 统一输出约分后的 n/d（整数时分母为 1）
        return f"{value.numerator}/{value.denominator}"

    return FailureCountResponse(
        top_probability=frac_string(top_prob),
        count_distribution=[frac_string(c / top_prob) for c in joint],
    )


def first_failure_time_logic(
    payload: FirstFailureTimeRequest,
) -> FirstFailureTimeResponse:
    # events 限 1~8 个；gates/top 沿用 analyze 的全部静态校验
    probs, gate_ops, gate_inputs = _validate_payload(payload)
    sorted_events = sorted(probs)

    # steps：1~10 的整数（类型错误如字符串、布尔、浮点由 pydantic 拦截）
    if not 1 <= payload.steps <= 10:
        raise ValueError(
            f"steps 必须为 1~10 的整数，实际为 {payload.steps}"
        )

    # transitions 必须恰好覆盖全部事件 id：缺失项与多余项一并报错
    cover_errors = _check_cover(payload.transitions, sorted_events, "transitions")
    if cover_errors:
        raise ValueError("；".join(cover_errors))

    # fail/recover 沿用 n/d 概率原规则解析（0<=n<=d<=10^6）
    fail_probs: Dict[str, Fraction] = {}
    recover_probs: Dict[str, Fraction] = {}
    bad: List[str] = []
    for eid in sorted_events:
        tr = payload.transitions[eid]
        for field_name, target in (
            ("fail", fail_probs),
            ("recover", recover_probs),
        ):
            try:
                target[eid] = _parse_probability(getattr(tr, field_name))
            except ValueError as exc:
                bad.append(f"事件 {eid!r} 的 transitions.{field_name}：{exc}")
    if bad:
        raise ValueError("；".join(bad))

    # 顶事件 ROBDD（沿用 50000 非终端节点限额）；事件状态只有 2^n≤256 种，
    # 枚举全部完整状态求出顶事件为真的状态集合，再交状态空间动态规划
    _, bdd, top_node, _ = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top
    )
    hit_masks = top_hit_masks(bdd, top_node, len(sorted_events))

    first_hit, no_hit = first_failure_distribution(
        init_probs=[probs[eid] for eid in sorted_events],
        fail_probs=[fail_probs[eid] for eid in sorted_events],
        recover_probs=[recover_probs[eid] for eid in sorted_events],
        hit_masks=hit_masks,
        steps=payload.steps,
    )

    def frac_string(value: Fraction) -> str:
        # 统一输出约分后的 n/d（整数时分母为 1）
        return f"{value.numerator}/{value.denominator}"

    return FirstFailureTimeResponse(
        first_hit_distribution=[frac_string(v) for v in first_hit],
        no_hit_probability=frac_string(no_hit),
    )


def observation_conflicts_logic(
    payload: ObservationConflictsRequest,
) -> ObservationConflictsResponse:
    probs, gate_ops, gate_inputs = _validate_payload(payload)
    sorted_events = sorted(probs)

    # 观测键必须指向已声明的事件或门（同 /v1/diagnose）
    known_ids = set(probs) | set(gate_ops)
    unknown = [k for k in payload.observations if k not in known_ids]
    if unknown:
        raise ValueError(
            "observations 引用了未声明的事件或门 id："
            + ", ".join(repr(k) for k in unknown)
        )

    # 被观测的门（即便 top 不可达）也要构建到同一 ROBDD 中
    observed_gates = tuple(
        k for k in payload.observations if k in gate_ops
    )
    _, bdd, _, node_map = build_tree_robdd(
        probs, gate_ops, gate_inputs, payload.top, also=observed_gates
    )

    # 观测按 id 字典序排列；读 1 取节点本身，读 0 取其 BDD 取反，
    # 同一事件/门的多处引用共享同一 BDD 节点，天然共享状态
    obs_ids = sorted(payload.observations)
    constraints = [
        node_map[oid] if payload.observations[oid] else bdd.negate(node_map[oid])
        for oid in obs_ids
    ]

    prob_list = [probs[eid] for eid in sorted_events]
    groups = minimal_zero_prob_groups(bdd, constraints, prob_list)

    # 位掩码展开为观测 id 列表（下标序即 id 字典序，组内天然有序）；
    # 组间先按组长度、再按 id 序列字典序排序
    conflicts = [
        [obs_ids[i] for i in range(len(obs_ids)) if mask >> i & 1]
        for mask in groups
    ]
    conflicts.sort(key=lambda ids: (len(ids), ids))
    return ObservationConflictsResponse(conflicts=conflicts)


# ---------- /v1/expand-model：参数化模板实例展开 ----------

# 所有名称（模板名、参数名、门名、实例名）：ASCII 字母开头，后接字母数字下划线
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

# 展开后门数上限与 /v1/analyze 的门列表上限一致
MAX_EXPANDED_GATES = 64


def _validate_templates_static(
    templates: Dict[str, TemplateIn],
) -> None:
    """对全部模板做不依赖展开的静态校验，任一问题收集后统一抛 ValueError。

    覆盖：模板名合法性与重复、模板内参数/门/实例名的合法性与两两互异、
    门元数（沿用门校验：AND/OR 2~8、NOT 1）、门输入与 top 的引用完整性
    （只能引用本地参数/门/子实例）、模板内门环、子实例绑定是否恰好覆盖
    被调模板参数且只能引用父模板参数、实例是否引用未定义模板。
    """
    errors: List[str] = []
    seen_errors: set = set()

    def report(msg: str) -> None:
        if msg not in seen_errors:  # 同一位置重复引用产生的重复错误只报一次
            seen_errors.add(msg)
            errors.append(msg)

    # ---- 模板名合法性与重复（dict 键天然不重复，仅检查格式）----
    for tname in templates:
        if not _NAME_RE.fullmatch(tname):
            report(
                f"模板名 {tname!r} 非法：必须以 ASCII 字母开头，"
                "其后只能是字母、数字或下划线"
            )

    for tname, tpl in templates.items():
        where = f"模板 {tname!r}"
        bad_names: set = set()

        def _check_local_name(name: str, kind: str) -> None:
            if not _NAME_RE.fullmatch(name) and (kind, name) not in bad_names:
                # 同一非法名称（如重复出现）只报一次
                bad_names.add((kind, name))
                report(
                    f"{where} 的{kind}名 {name!r} 非法：必须以 ASCII 字母开头，"
                    "其后只能是字母、数字或下划线"
                )

        # ---- 参数名合法性 + 列表内重复 ----
        seen_params: set = set()
        for p in tpl.params:
            _check_local_name(p, "参数")
            if p in seen_params:
                report(f"{where} 的参数名重复：{p!r}")
            seen_params.add(p)

        # ---- 门名合法性 + 列表内重复 + 元数 ----
        gate_ops: Dict[str, GateOp] = {}
        gate_inputs: Dict[str, List[str]] = {}
        for gate in tpl.gates:
            _check_local_name(gate.id, "门")
            if gate.id in gate_ops:
                report(f"{where} 的门名重复：{gate.id!r}")
            n_inputs = len(gate.inputs)
            if gate.op == "NOT":
                if n_inputs != 1:
                    report(
                        f"{where} 的门 {gate.id!r} 为 NOT，必须恰好有 1 个输入，"
                        f"实际 {n_inputs} 个"
                    )
            elif n_inputs < 2 or n_inputs > 8:
                report(
                    f"{where} 的门 {gate.id!r} 为 {gate.op}，必须有 2~8 个输入，"
                    f"实际 {n_inputs} 个"
                )
            gate_ops[gate.id] = gate.op
            gate_inputs[gate.id] = list(gate.inputs)

        # ---- 实例名合法性 + 列表内重复 ----
        instance_ids: set = set()
        for inst in tpl.instances:
            _check_local_name(inst.id, "实例")
            if inst.id in instance_ids:
                report(f"{where} 的实例名重复：{inst.id!r}")
            instance_ids.add(inst.id)

        # ---- 三类名称两两互异（不同命名空间也不许同名）----
        for shared in seen_params & gate_ops.keys():
            report(f"{where} 的参数名与门名冲突：{shared!r}")
        for shared in seen_params & instance_ids:
            report(f"{where} 的参数名与实例名冲突：{shared!r}")
        for shared in gate_ops.keys() & instance_ids:
            report(f"{where} 的门名与实例名冲突：{shared!r}")

        local_known = seen_params | gate_ops.keys() | instance_ids

        # ---- 门输入与 top：只能引用本地参数、本地门或子实例 ----
        def check_ref(ref: str, site: str) -> None:
            if ref not in local_known:
                report(
                    f"{where} 的{site}引用了未知名称 {ref!r}：必须是本模板的"
                    "参数、门或子实例名"
                )

        for gate in tpl.gates:
            for ref in gate.inputs:
                check_ref(ref, f"门 {gate.id!r} 输入")
        check_ref(tpl.top, "top ")

        # ---- 模板内门环：仅门→门的依赖参与成环（参数为叶子、实例为叶子）----
        color: Dict[str, int] = {gid: 0 for gid in gate_ops}

        def dfs_gate(gid: str) -> None:
            if gid not in color:  # 参数或子实例：叶子
                return
            if color[gid] == 1:
                report(f"{where} 的门引用关系存在环（涉及门 {gid!r}）")
                return
            if color[gid] == 2:
                return
            color[gid] = 1
            for child in gate_inputs[gid]:
                dfs_gate(child)
            color[gid] = 2

        for gid in gate_ops:
            dfs_gate(gid)

        # ---- 子实例：模板存在性与 bindings 覆盖/取值 ----
        for inst in tpl.instances:
            if inst.template not in templates:
                report(
                    f"{where} 的实例 {inst.id!r} 引用了未定义模板："
                    f"{inst.template!r}"
                )
                continue
            callee_params = set(templates[inst.template].params)
            bound = set(inst.bindings)
            missing = callee_params - bound
            extra = bound - callee_params
            if missing:
                report(
                    f"{where} 的实例 {inst.id!r} 绑定缺少被调模板 "
                    f"{inst.template!r} 的参数："
                    + ", ".join(repr(p) for p in sorted(missing))
                )
            if extra:
                report(
                    f"{where} 的实例 {inst.id!r} 绑定出现了被调模板 "
                    f"{inst.template!r} 未声明的参数："
                    + ", ".join(repr(p) for p in sorted(extra))
                )
            bad_values = sorted(
                {v for v in inst.bindings.values() if v not in seen_params}
            )
            if bad_values:
                report(
                    f"{where} 的实例 {inst.id!r} 绑定只能引用本模板参数，"
                    "非法引用：" + ", ".join(repr(v) for v in bad_values)
                )

    if errors:
        raise ValueError("；".join(errors))


def _check_template_recursion(templates: Dict[str, TemplateIn]) -> None:
    """在实例调用图上检测模板递归（含自调用），成环则抛 ValueError。

    从全部模板各自出发做 DFS（调用图是有限图，重复访问直接复用结果），
    故未被 root 引用的模板若参与递归环同样报错；root 未定义的情形由
    调用方先行拦截。
    """
    color: Dict[str, int] = {}  # 0=未访问, 1=在栈中, 2=完成

    def dfs(tname: str, stack: List[str]) -> None:
        state = color.get(tname, 0)
        if state == 1:
            cycle = stack[stack.index(tname):] + [tname]
            raise ValueError(
                "模板递归调用成环：" + " → ".join(cycle)
                + "；实例展开不允许递归"
            )
        if state == 2:
            return
        color[tname] = 1
        for inst in templates[tname].instances:
            if inst.template in templates:  # 引用未定义模板已在静态校验中报错
                dfs(inst.template, stack + [tname])
        color[tname] = 2

    for tname in templates:
        dfs(tname, [])


def expand_model_logic(payload: ExpandModelRequest) -> ExpandModelResponse:
    """把参数化模板的 root 实例递归展开为扁平的 gates/top。"""
    # 事件与事件概率沿用 /v1/analyze 的校验（id、重复、n/d 概率）
    probs = _validate_events(payload.events)

    errors: List[str] = []

    # 全部模板的静态校验（不依赖展开；未被 root 引用的模板同样检查）
    try:
        _validate_templates_static(payload.templates)
    except ValueError as exc:
        errors.append(str(exc))

    # root 模板存在性与绑定（恰好覆盖根模板参数，值只能是已声明事件 id）
    if payload.root.template not in payload.templates:
        errors.append(f"root 引用了未定义模板：{payload.root.template!r}")
    else:
        root_params = set(payload.templates[payload.root.template].params)
        bound = set(payload.root.bindings)
        missing = root_params - bound
        extra = bound - root_params
        if missing:
            errors.append(
                "root 绑定缺少根模板 "
                f"{payload.root.template!r} 的参数："
                + ", ".join(repr(p) for p in sorted(missing))
            )
        if extra:
            errors.append(
                "root 绑定出现了根模板 "
                f"{payload.root.template!r} 未声明的参数："
                + ", ".join(repr(p) for p in sorted(extra))
            )
        bad_events = sorted(
            {v for v in payload.root.bindings.values() if v not in probs}
        )
        if bad_events:
            errors.append(
                "root 绑定只能引用已声明事件 id，非法引用："
                + ", ".join(repr(v) for v in bad_events)
            )
    if errors:
        raise ValueError("；".join(errors))

    # 模板递归检测（全部模板的实例调用成环，含自调用、未被 root 引用的）
    _check_template_recursion(payload.templates)

    root_tpl = payload.root.template
    root_bindings = dict(payload.root.bindings)
    out_gates: List[GateIn] = []

    def child_param_map(inst: TemplateInstanceIn, param_map: Dict[str, str]):
        return {
            callee_param: param_map[inst.bindings[callee_param]]
            for callee_param in payload.templates[inst.template].params
        }

    def top_reference(
        tname: str,
        path: str,
        param_map: Dict[str, str],
    ) -> str:
        """沿 top 链解析模板 tname 顶层引用的全局 id（不展开门）。"""
        tpl = payload.templates[tname]
        top = tpl.top
        if top in param_map:  # 顶层直接是参数 → root 绑定的事件 id
            return param_map[top]
        inst_by_id = {inst.id: inst for inst in tpl.instances}
        if top in inst_by_id:  # 顶层是子实例 → 继续沿子实例的 top 链
            inst = inst_by_id[top]
            return top_reference(
                inst.template, f"{path}.{inst.id}", child_param_map(inst, param_map)
            )
        return f"{path}/{top}"  # 顶层是本地门 → 全路径门名

    def instantiate(
        tname: str,
        path: str,
        param_map: Dict[str, str],
    ) -> str:
        """在实例路径 path 处展开模板 tname，返回其 top 解析后的全局引用。

        param_map：本模板形参 → 全局事件 id（root 直接绑事件；子实例经
        父级 param_map 传递，天然实现共享事件保留原 id）。
        门按「本模板门先于子实例深层门」的前序加入。
        """
        tpl = payload.templates[tname]
        child_tops: Dict[str, str] = {}
        for inst in tpl.instances:
            child_tops[inst.id] = top_reference(
                inst.template, f"{path}.{inst.id}", child_param_map(inst, param_map)
            )

        def resolve(ref: str) -> str:
            if ref in param_map:          # 本地参数 → 全局共享事件 id
                return param_map[ref]
            if ref in child_tops:         # 子实例 → 该实例 top 的全局引用
                return child_tops[ref]
            return f"{path}/{ref}"        # 本地门 → 全路径门名

        # 本模板门先加入（对子实例的引用直接指向其确定的 top 全局 id）
        for gate in tpl.gates:
            out_gates.append(
                GateIn(
                    id=f"{path}/{gate.id}",
                    op=gate.op,
                    inputs=[resolve(ref) for ref in gate.inputs],
                )
            )
            if len(out_gates) > MAX_EXPANDED_GATES:
                raise ValueError(
                    f"展开后的门数超过 {MAX_EXPANDED_GATES} 个上限："
                    f"展开到路径 {path!r} 的门 {gate.id!r} 时已有 "
                    f"{len(out_gates)} 个门"
                )

        # 再递归展开子实例；门环与引用完整性统一交给展开后的
        # _validate_gates 复核（前序排序不影响判定）
        for inst in tpl.instances:
            instantiate(
                inst.template, f"{path}.{inst.id}", child_param_map(inst, param_map)
            )
        return resolve(tpl.top)

    top_ref = instantiate(root_tpl, "root", root_bindings)

    # 展开结果沿用门的全部校验：元数、未知引用、门环，以及全路径门名与
    # 事件 id 冲突等结构问题（静态校验已保证大部分，这里做最终兜底）
    _validate_gates(probs, out_gates, top_ref)

    return ExpandModelResponse(
        events=list(payload.events), gates=out_gates, top=top_ref
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求结构错误同样返回 422，并给出可直接阅读的中文原因。"""
    errs = exc.errors()
    messages = []
    for err in errs:
        loc = [p for p in err.get("loc", []) if p != "body"]
        where = ".".join(str(p) for p in loc) or "请求体"
        msg = err.get("msg", "参数无效")
        messages.append(f"{where}: {msg}")
    return JSONResponse(
        status_code=422,
        content={"detail": "；".join(messages)},
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return analyze_logic(payload)
    except NodeLimitExceeded as exc:
        # 构建中累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 非法概率、未知引用、环、元数错误等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/cut-sets", response_model=CutSetsResponse)
async def cut_sets(payload: AnalyzeRequest) -> CutSetsResponse:
    try:
        return cut_sets_logic(payload)
    except ValueError as exc:
        # 非法概率、未知引用、环、NOT 门、割集超限等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/repair-plan", response_model=RepairPlanResponse)
async def repair_plan(payload: RepairPlanRequest) -> RepairPlanResponse:
    try:
        return repair_plan_logic(payload)
    except NodeLimitExceeded as exc:
        # 构建中累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 未知引用、环、元数错误、状态/费用缺项、费用越界等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/diagnose", response_model=DiagnoseResponse)
async def diagnose(payload: DiagnoseRequest) -> DiagnoseResponse:
    try:
        return diagnose_logic(payload)
    except NodeLimitExceeded as exc:
        # 树构建或合取观测约束时累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 未知引用、环、非法观测键、观测矛盾或联合概率为 0 等语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/inspect-next", response_model=InspectNextResponse)
async def inspect_next(payload: InspectNextRequest) -> InspectNextResponse:
    try:
        return inspect_next_logic(payload)
    except NodeLimitExceeded as exc:
        # 树构建、合取观测约束或构建候选分支时累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 未知引用、环、非法观测键/候选、观测矛盾或联合概率为 0 等语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/likely-cause", response_model=LikelyCauseResponse)
async def likely_cause(payload: LikelyCauseRequest) -> LikelyCauseResponse:
    try:
        return likely_cause_logic(payload)
    except NodeLimitExceeded as exc:
        # 树构建或合取观测约束时累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 未知引用、环、非法观测键、条件矛盾或联合概率为 0 等语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/compare-trees", response_model=CompareTreesResponse)
async def compare_trees(payload: CompareTreesRequest) -> CompareTreesResponse:
    try:
        return compare_trees_logic(payload)
    except NodeLimitExceeded as exc:
        # 两版建图及差异运算累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 非法概率、未知引用、跨版引用、环、元数错误等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/failure-count", response_model=FailureCountResponse)
async def failure_count(payload: AnalyzeRequest) -> FailureCountResponse:
    try:
        return failure_count_logic(payload)
    except NodeLimitExceeded as exc:
        # 构建中累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 未知引用、环、非法概率、top_probability=0 等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post(
    "/v1/first-failure-time", response_model=FirstFailureTimeResponse
)
async def first_failure_time(
    payload: FirstFailureTimeRequest,
) -> FirstFailureTimeResponse:
    try:
        return first_failure_time_logic(payload)
    except NodeLimitExceeded as exc:
        # 构建中累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 事件超限、steps 越界、transitions 缺项/多余、fail/recover
        # 非法概率、未知引用、环等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post(
    "/v1/observation-conflicts", response_model=ObservationConflictsResponse
)
async def observation_conflicts(
    payload: ObservationConflictsRequest,
) -> ObservationConflictsResponse:
    try:
        return observation_conflicts_logic(payload)
    except NodeLimitExceeded as exc:
        # 树构建、强制文字折叠或子集合取枚举时累计非终端节点超过限制
        return _bad_request(str(exc))  # type: ignore[return-value]
    except ValueError as exc:
        # 未知引用、环、非法观测键/值、组数超限等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]


@app.post("/v1/expand-model", response_model=ExpandModelResponse)
async def expand_model(payload: ExpandModelRequest) -> ExpandModelResponse:
    try:
        return expand_model_logic(payload)
    except ValueError as exc:
        # 非法事件/概率、名称冲突、绑定错误、未知引用、门环、模板递归、
        # 引用未定义模板或展开后门数超过 64 等全部语义错误
        return _bad_request(str(exc))  # type: ignore[return-value]
