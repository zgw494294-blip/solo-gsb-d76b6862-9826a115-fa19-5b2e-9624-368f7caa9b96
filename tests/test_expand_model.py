"""POST /v1/expand-model：参数化模板展开为扁平故障树的语义、正确性与 422 校验。

展开结果直接作为 /v1/analyze 的请求体，并用穷举真值表交叉验证；
同时覆盖名称、绑定、递归、门环与 64 门上限等全部 422 路径。
"""

import itertools
from fractions import Fraction

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------- 穷举真值表参考实现 ----------

def brute_evaluate(events, gates, top):
    """枚举全部事件赋值，返回顶事件为真的概率 Fraction。"""
    ev_ids = sorted(events)
    probs = {eid: Fraction(events[eid]) for eid in ev_ids}
    gate = {g["id"]: (g["op"], g["inputs"]) for g in gates}

    def evaluate(state, node):
        if node in state:
            return state[node]
        op, inputs = gate[node]
        vals = [evaluate(state, i) for i in inputs]
        if op == "AND":
            return int(all(vals))
        if op == "OR":
            return int(any(vals))
        return int(not vals[0])

    total = Fraction(0)
    for bits in itertools.product((0, 1), repeat=len(ev_ids)):
        state = dict(zip(ev_ids, bits))
        if evaluate(state, top):
            w = Fraction(1)
            for eid in ev_ids:
                w *= probs[eid] if state[eid] else 1 - probs[eid]
            total += w
    return total


def f2s(f):
    return f"{f.numerator}/{f.denominator}"


def base_payload():
    return {
        "events": [
            {"id": "a", "p": "1/2"},
            {"id": "b", "p": "1/3"},
            {"id": "c", "p": "1/5"},
        ],
        "templates": {
            "Fan": {
                "params": ["x", "y"],
                "gates": [{"id": "g1", "op": "OR", "inputs": ["x", "y"]}],
                "instances": [],
                "top": "g1",
            },
            "Pump": {
                "params": ["u", "v", "w"],
                "gates": [{"id": "g2", "op": "AND", "inputs": ["fan", "w"]}],
                "instances": [
                    {"id": "fan", "template": "Fan",
                     "bindings": {"x": "u", "y": "v"}},
                ],
                "top": "g2",
            },
            "Root": {
                "params": ["p1", "p2", "p3"],
                "gates": [
                    {"id": "g3", "op": "OR", "inputs": ["p1", "pump"]},
                ],
                "instances": [
                    {"id": "pump", "template": "Pump",
                     "bindings": {"u": "p2", "v": "p3", "w": "p2"}},
                ],
                "top": "g3",
            },
        },
        "root": {
            "template": "Root",
            "bindings": {"p1": "a", "p2": "b", "p3": "c"},
        },
    }


# ---------- 正常展开 ----------

def test_basic_expansion_structure():
    r = client.post("/v1/expand-model", json=base_payload())
    assert r.status_code == 200, r.text
    body = r.json()

    # events 原样返回（顺序与内容不变）
    assert body["events"] == [
        {"id": "a", "p": "1/2"},
        {"id": "b", "p": "1/3"},
        {"id": "c", "p": "1/5"},
    ]
    # 门名 = root/实例路径/门名，按本模板先于子实例的前序排列
    assert [g["id"] for g in body["gates"]] == [
        "root/g3",
        "root.pump/g2",
        "root.pump.fan/g1",
    ]
    g3, g2, g1 = body["gates"]
    assert g3["op"] == "OR" and g3["inputs"] == ["a", "root.pump/g2"]
    assert g2["op"] == "AND" and g2["inputs"] == ["root.pump.fan/g1", "b"]
    # 形参解析为 root 绑定的共享事件 id；p2 被两处共享都解析为 b
    assert g1["op"] == "OR" and g1["inputs"] == ["b", "c"]
    assert body["top"] == "root/g3"


def test_expanded_tree_matches_bruteforce_via_analyze():
    body = client.post("/v1/expand-model", json=base_payload()).json()

    # 展开结果可直接交给 /v1/analyze
    r = client.post("/v1/analyze", json=body)
    assert r.status_code == 200, r.text
    ev_specs = {e["id"]: e["p"] for e in body["events"]}
    expected = brute_evaluate(ev_specs, body["gates"], body["top"])
    assert r.json()["top_probability"] == f2s(expected)


def test_shared_event_keeps_single_id():
    """同一父参数绑定多个子参数时，共用同一个 root 事件 id（原 id 保留）。"""
    body = client.post("/v1/expand-model", json=base_payload()).json()
    fan_inputs = body["gates"][2]["inputs"]
    # w 与 u 都绑到 p2 → 事件 b；g1 引用 b,c
    assert fan_inputs == ["b", "c"]
    all_inputs = [ref for g in body["gates"] for ref in g["inputs"]]
    assert all(ref in {"a", "b", "c", "root/g3", "root.pump/g2",
                       "root.pump.fan/g1"} for ref in all_inputs)


def test_top_is_param_resolves_to_event():
    payload = base_payload()
    payload["templates"]["Root"]["top"] = "p2"
    r = client.post("/v1/expand-model", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["top"] == "b"


def test_top_chain_through_instances():
    """模板 top 为子实例时沿实例链解析到深层门或事件。"""
    payload = base_payload()
    payload["templates"]["Pump"]["top"] = "fan"   # pump 顶层即 fan 实例
    payload["templates"]["Root"]["top"] = "pump"  # root 顶层即 pump 实例
    r = client.post("/v1/expand-model", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["top"] == "root.pump.fan/g1"
    # 门的前序顺序不受影响
    assert [g["id"] for g in r.json()["gates"]] == [
        "root/g3", "root.pump/g2", "root.pump.fan/g1",
    ]


def test_not_gate_and_deep_param_passthrough():
    """NOT 门与三级实例链；形参沿链一路解析到 root 绑定的共享事件 id。"""
    payload = {
        "events": [{"id": "a", "p": "1/2"}],
        "templates": {
            "Leaf": {
                "params": ["e"],
                "gates": [{"id": "lg", "op": "OR", "inputs": ["e", "e"]}],
                "instances": [],
                "top": "lg",
            },
            "Middle": {
                "params": ["m"],
                "gates": [{"id": "ng", "op": "NOT", "inputs": ["sub"]}],
                "instances": [
                    {"id": "sub", "template": "Leaf",
                     "bindings": {"e": "m"}},
                ],
                "top": "ng",
            },
            "Root": {
                "params": ["q"],
                "gates": [{"id": "w", "op": "OR", "inputs": ["c", "q"]}],
                "instances": [
                    {"id": "c", "template": "Middle",
                     "bindings": {"m": "q"}},
                ],
                "top": "w",
            },
        },
        "root": {"template": "Root", "bindings": {"q": "a"}},
    }
    r = client.post("/v1/expand-model", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["top"] == "root/w"
    gates = {g["id"]: g for g in body["gates"]}
    assert gates["root/w"]["inputs"] == ["root.c/ng", "a"]
    assert gates["root.c/ng"] == {
        "id": "root.c/ng", "op": "NOT", "inputs": ["root.c.sub/lg"],
    }
    # 形参 e 沿 Root.q → Middle.m → Leaf.e 解析到 root 绑定的事件 a（原 id 保留）
    assert gates["root.c.sub/lg"]["inputs"] == ["a", "a"]
    # 结构：a OR (NOT a) 恒真
    assert brute_evaluate(
        {e["id"]: e["p"] for e in body["events"]},
        body["gates"], body["top"],
    ) == Fraction(1, 1)


def test_gate_limit_boundary_64_ok():
    def chain_gates(n):
        gates = [{"id": "g0", "op": "OR", "inputs": ["x", "x"]}]
        for i in range(1, n):
            gates.append({"id": f"g{i}", "op": "OR",
                          "inputs": [f"g{i-1}", "x"]})
        return gates

    payload = {
        "events": [{"id": "a", "p": "1/2"}],
        "templates": {
            "Leaf": {"params": ["x"], "gates": chain_gates(32),
                     "instances": [], "top": "g31"},
            "Root": {"params": ["x"], "gates": chain_gates(32),
                     "instances": [{"id": "sub", "template": "Leaf",
                                    "bindings": {"x": "x"}}],
                     "top": "g31"},
        },
        "root": {"template": "Root", "bindings": {"x": "a"}},
    }
    r = client.post("/v1/expand-model", json=payload)
    assert r.status_code == 200, r.text
    assert len(r.json()["gates"]) == 64


# ---------- 422 错误路径 ----------

def expect_422(payload, *needles):
    r = client.post("/v1/expand-model", json=payload)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    for needle in needles:
        assert needle in detail, (needle, detail)
    return detail


def test_unknown_root_template():
    p = base_payload()
    p["root"]["template"] = "Nope"
    expect_422(p, "root 引用了未定义模板")


def test_unknown_instance_template():
    p = base_payload()
    p["templates"]["Root"]["instances"].append(
        {"id": "extra", "template": "Nope", "bindings": {}})
    expect_422(p, "引用了未定义模板")


def test_root_binding_missing_and_extra():
    p = base_payload()
    p["root"]["bindings"].pop("p3")
    p["root"]["bindings"]["px"] = "a"
    expect_422(p, "缺少根模板", "未声明的参数")


def test_root_binding_unknown_event():
    p = base_payload()
    p["root"]["bindings"]["p1"] = "zz"
    expect_422(p, "已声明事件")


def test_instance_binding_missing_param():
    p = base_payload()
    p["templates"]["Root"]["instances"][0]["bindings"].pop("w")
    expect_422(p, "绑定缺少被调模板")


def test_instance_binding_extra_param():
    p = base_payload()
    p["templates"]["Root"]["instances"][0]["bindings"]["zz"] = "p1"
    expect_422(p, "未声明的参数")


def test_instance_binding_value_not_parent_param():
    p = base_payload()
    p["templates"]["Root"]["instances"][0]["bindings"]["u"] = "zz"
    expect_422(p, "只能引用本模板参数")


def test_self_recursion_rejected():
    p = base_payload()
    p["templates"]["Fan"]["instances"].append(
        {"id": "loop", "template": "Fan",
         "bindings": {"x": "x", "y": "y"}})
    expect_422(p, "模板递归调用成环")


def test_recursion_in_unreferenced_template_rejected():
    """未被 root 引用的模板参与递归环同样拒绝（检查全部模板）。"""
    p = base_payload()
    p["templates"]["Off1"] = {
        "params": [],
        "gates": [{"id": "g", "op": "NOT", "inputs": ["o"]}],
        "instances": [{"id": "o", "template": "Off2", "bindings": {}}],
        "top": "g",
    }
    p["templates"]["Off2"] = {
        "params": [],
        "gates": [{"id": "g", "op": "NOT", "inputs": ["o"]}],
        "instances": [{"id": "o", "template": "Off1", "bindings": {}}],
        "top": "g",
    }
    expect_422(p, "模板递归调用成环")


def test_mutual_recursion_rejected():
    p = {
        "events": [{"id": "a", "p": "1/2"}],
        "templates": {
            "B": {"params": ["x"],
                  "gates": [{"id": "g", "op": "OR", "inputs": ["x", "j"]}],
                  "instances": [{"id": "j", "template": "C",
                                 "bindings": {"x": "x"}}],
                  "top": "g"},
            "C": {"params": ["x"],
                  "gates": [{"id": "g", "op": "OR", "inputs": ["x", "k"]}],
                  "instances": [{"id": "k", "template": "B",
                                 "bindings": {"x": "x"}}],
                  "top": "g"},
        },
        "root": {"template": "B", "bindings": {"x": "a"}},
    }
    expect_422(p, "模板递归调用成环", "B → C → B")


def test_template_gate_cycle_rejected():
    p = base_payload()
    p["templates"]["Fan"]["gates"][0]["inputs"] = ["g1", "x"]
    expect_422(p, "门引用关系存在环")


def test_unknown_reference_in_inputs_and_top():
    p = base_payload()
    p["templates"]["Fan"]["gates"][0]["inputs"].append("zz")
    expect_422(p, "未知名称 'zz'")
    p = base_payload()
    p["templates"]["Fan"]["top"] = "zz"
    expect_422(p, "未知名称 'zz'")


def test_name_conflict_across_namespaces():
    p = base_payload()
    p["templates"]["Fan"]["params"] = ["g1", "y"]
    expect_422(p, "参数名与门名冲突")

    p = base_payload()
    p["templates"]["Pump"]["instances"].append(
        {"id": "g2", "template": "Fan",
         "bindings": {"x": "u", "y": "v"}})
    expect_422(p, "门名与实例名冲突")

    p = base_payload()
    p["templates"]["Pump"]["params"] = ["u", "v", "w", "fan"]
    # Root.pump 的绑定为新形参 fan 也给一个父参数值，使其恰好覆盖；
    # 仅剩 Pump 形参 fan 与其实例名 fan 冲突这一类错误
    p["templates"]["Root"]["instances"][0]["bindings"]["fan"] = "p1"
    expect_422(p, "参数名与实例名冲突")


def test_duplicate_local_names():
    p = base_payload()
    p["templates"]["Fan"]["params"] = ["x", "x", "y"]
    expect_422(p, "参数名重复")

    p = base_payload()
    p["templates"]["Fan"]["gates"].append(
        {"id": "g1", "op": "NOT", "inputs": ["x"]})
    expect_422(p, "门名重复")

    p = base_payload()
    p["templates"]["Pump"]["instances"].append(
        {"id": "fan", "template": "Fan",
         "bindings": {"x": "u", "y": "v"}})
    expect_422(p, "实例名重复")


def test_illegal_names():
    p = base_payload()
    p["templates"]["Fan"]["params"] = ["1x", "y"]
    expect_422(p, "参数名 '1x' 非法")

    p = base_payload()
    p["templates"]["Fan"]["gates"][0]["id"] = "bad-name"
    expect_422(p, "门名 'bad-name' 非法")

    p = base_payload()
    p["templates"]["A-1"] = {"params": [], "gates": [],
                             "instances": [], "top": "x"}
    r = client.post("/v1/expand-model", json=p)
    assert r.status_code == 422
    assert "模板名 'A-1' 非法" in r.json()["detail"] or \
        "templates" in r.json()["detail"]


def test_unreferenced_template_still_validated():
    p = base_payload()
    p["templates"]["Unused"] = {
        "params": [],
        "gates": [{"id": "g", "op": "OR", "inputs": ["zz", "zz"]}],
        "instances": [], "top": "g",
    }
    detail = expect_422(p, "未知名称 'zz'")
    # 同一未知引用的重复输入只报一次
    assert detail.count("未知名称 'zz'") == 1


def test_gate_arity_rules():
    p = base_payload()
    p["templates"]["Fan"]["gates"][0]["inputs"] = ["x"]
    expect_422(p, "必须有 2~8 个输入")

    p = base_payload()
    p["templates"]["Fan"]["gates"][0]["inputs"] = ["x"] * 9
    expect_422(p, "必须有 2~8 个输入")

    p = base_payload()
    p["templates"]["Fan"]["gates"][0] = {"id": "g1", "op": "NOT",
                                         "inputs": ["x", "y"]}
    expect_422(p, "NOT，必须恰好有 1 个输入")


def test_empty_gates_rejected():
    p = {
        "events": [{"id": "a", "p": "1/2"}],
        "templates": {"A": {"params": [], "gates": [],
                            "instances": [], "top": "x"}},
        "root": {"template": "A", "bindings": {}},
    }
    assert client.post("/v1/expand-model", json=p).status_code == 422


def test_event_probability_validation_reused():
    p = base_payload()
    p["events"][0]["p"] = "2/1"
    expect_422(p, "非法概率")


def test_duplicate_event_rejected():
    p = base_payload()
    p["events"].append({"id": "a", "p": "1/2"})
    expect_422(p, "事件 id 重复")


def test_over_64_gates_rejected():
    def chain_gates(n):
        gates = [{"id": "g0", "op": "OR", "inputs": ["x", "x"]}]
        for i in range(1, n):
            gates.append({"id": f"g{i}", "op": "OR",
                          "inputs": [f"g{i-1}", "x"]})
        return gates

    p = {
        "events": [{"id": "a", "p": "1/2"}],
        "templates": {
            "Leaf": {"params": ["x"], "gates": chain_gates(32),
                     "instances": [], "top": "g31"},
            "Root": {"params": ["x"], "gates": chain_gates(33),
                     "instances": [{"id": "sub", "template": "Leaf",
                                    "bindings": {"x": "x"}}],
                     "top": "g32"},
        },
        "root": {"template": "Root", "bindings": {"x": "a"}},
    }
    expect_422(p, "超过 64 个上限")


def test_template_count_bounds():
    body = {
        "events": [{"id": "a", "p": "1/2"}],
        "templates": {},
        "root": {"template": "A", "bindings": {}},
    }
    assert client.post("/v1/expand-model", json=body).status_code == 422

    body["templates"] = {
        f"T{i}": {"params": [],
                  "gates": [{"id": "g", "op": "NOT", "inputs": ["g"]}],
                  "instances": [], "top": "g"}
        for i in range(9)
    }
    body["root"]["template"] = "T0"
    assert client.post("/v1/expand-model", json=body).status_code == 422


def test_extra_fields_and_bad_types_rejected():
    p = base_payload()
    p["bogus"] = 1
    assert client.post("/v1/expand-model", json=p).status_code == 422

    p = base_payload()
    p["templates"]["Fan"]["gates"][0]["op"] = "XOR"
    assert client.post("/v1/expand-model", json=p).status_code == 422

    p = base_payload()
    p["root"] = [1, 2]
    assert client.post("/v1/expand-model", json=p).status_code == 422


def test_expanded_gate_id_colliding_with_event_rejected():
    """root/门名 恰好等于某已声明事件 id 时，展开后门 id 与事件冲突 → 422。

    模板内只引用本地名称（合法）；冲突仅在展开为全路径门名后暴露，
    由展开后沿用的门校验兜底拦截。
    """
    p = {
        "events": [{"id": "root/g", "p": "1/2"}, {"id": "a", "p": "1/2"}],
        "templates": {
            "A": {"params": ["x"],
                  "gates": [{"id": "g", "op": "OR", "inputs": ["x", "x"]}],
                  "instances": [], "top": "g"},
        },
        "root": {"template": "A", "bindings": {"x": "a"}},
    }
    # 事件 id 含 / 本身合法（沿用事件 id 规则：非空 ASCII）
    expect_422(p, "门 id 与事件 id 冲突")
