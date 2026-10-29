# SPDX-License-Identifier: Apache-2.0
"""Load a default-deny action policy and authorize one call."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from agent_action_gate.yaml_lite import YamlError, loads


class PolicyError(ValueError):
    """The policy file is missing or invalid."""


_TOP_KEYS = {"version", "currency", "actions"}
_ACTION_KEYS = {"description", "reversible", "idempotency", "params", "rules"}
_PARAM_KEYS = {"type", "minimum", "maximum", "min_length", "max_length", "pattern"}
_RULE_KEYS = {"id", "when", "decision", "reason"}
_DECISIONS = {"allow", "require_approval", "deny"}
_WHEN_SUFFIXES = ("_lte", "_gt", "_eq")


class Policy:
    def __init__(self, version: int, currency: str, actions: dict):
        self.version = version
        self.currency = currency
        self.actions = actions

    def authorize(self, action, params) -> dict:
        if not isinstance(action, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action):
            return _denied("schema", "动作名不合法", None)
        spec = self.actions.get(action)
        if spec is None:
            return _denied("allowlist", "动作不在白名单中", None)
        errors = _validate_params(spec, params)
        if errors:
            return _denied("schema", "参数不符合声明: " + "; ".join(errors), spec["reversible"])
        assert isinstance(params, dict)
        for rule in spec["rules"]:
            if _when_matches(rule["when"], params):
                return {
                    "decision": rule["decision"],
                    "rule": rule["id"],
                    "reason": _render_reason(rule["reason"], params),
                    "reversible": spec["reversible"],
                    "idempotency_key": _idempotency_key(action, spec, params),
                }
        return _denied("default_deny", "没有匹配的允许规则", spec["reversible"])


def load_policy(path: str | None = None) -> Policy:
    if path is None:
        source = "built-in"
        try:
            text = files("agent_action_gate").joinpath("data", "refund_policy.yaml").read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            raise PolicyError("内置策略文件缺失") from exc
    else:
        source = path
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise PolicyError(f"无法读取策略文件: {path}") from exc
    try:
        document = loads(text)
    except YamlError as exc:
        raise PolicyError(f"策略无法解析 ({source}): {exc}") from exc
    return _validate_document(document)


def _validate_document(document) -> Policy:
    if not isinstance(document, dict):
        raise PolicyError("策略根节点必须是映射")
    unknown = set(document) - _TOP_KEYS
    if unknown:
        raise PolicyError("策略含未知字段: " + ", ".join(sorted(unknown)))
    if document.get("version") != 1:
        raise PolicyError("只支持 version: 1")
    currency = document.get("currency")
    if not isinstance(currency, str) or not currency:
        raise PolicyError("currency 必须是非空字符串")
    actions = document.get("actions")
    if not isinstance(actions, dict) or not actions:
        raise PolicyError("actions 必须是非空映射")
    compiled = {}
    for name, spec in actions.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise PolicyError(f"非法动作名: {name}")
        compiled[name] = _compile_action(name, spec)
    return Policy(1, currency, compiled)


def _compile_action(name: str, spec) -> dict:
    if not isinstance(spec, dict):
        raise PolicyError(f"{name}: 动作必须是映射")
    unknown = set(spec) - _ACTION_KEYS
    if unknown:
        raise PolicyError(f"{name}: 未知字段 " + ", ".join(sorted(unknown)))
    if not isinstance(spec.get("reversible"), bool):
        raise PolicyError(f"{name}: reversible 必须是布尔值")
    description = spec.get("description", "")
    if not isinstance(description, str):
        raise PolicyError(f"{name}: description 必须是字符串")
    params = spec.get("params")
    if not isinstance(params, dict) or not params:
        raise PolicyError(f"{name}: params 必须是非空映射")
    compiled_params = {}
    for param_name, rule in params.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", param_name):
            raise PolicyError(f"{name}.{param_name}: 非法参数名")
        compiled_params[param_name] = _compile_param(f"{name}.{param_name}", rule)
    idempotency = spec.get("idempotency", [])
    if not isinstance(idempotency, list) or not all(isinstance(item, str) for item in idempotency):
        raise PolicyError(f"{name}: idempotency 必须是字符串列表")
    missing = [item for item in idempotency if item not in compiled_params]
    if missing:
        raise PolicyError(f"{name}: idempotency 引用了未声明参数 " + ", ".join(missing))
    rules = spec.get("rules")
    if not isinstance(rules, list) or not rules:
        raise PolicyError(f"{name}: rules 必须是非空列表")
    compiled_rules = [
        _compile_rule(name, rule, compiled_params, index) for index, rule in enumerate(rules, 1)
    ]
    return {
        "description": description,
        "reversible": spec["reversible"],
        "idempotency": list(idempotency),
        "params": compiled_params,
        "rules": compiled_rules,
    }


def _compile_param(label: str, rule) -> dict:
    if not isinstance(rule, dict):
        raise PolicyError(f"{label}: 参数声明必须是映射")
    unknown = set(rule) - _PARAM_KEYS
    if unknown:
        raise PolicyError(f"{label}: 未知字段 " + ", ".join(sorted(unknown)))
    kind = rule.get("type")
    if kind not in {"integer", "string"}:
        raise PolicyError(f"{label}: type 只能是 integer 或 string")
    compiled = {"type": kind, "pattern": None}
    if kind == "integer":
        for key in ("minimum", "maximum"):
            if key in rule and not _is_int(rule[key]):
                raise PolicyError(f"{label}: {key} 必须是整数")
        compiled["minimum"] = rule.get("minimum")
        compiled["maximum"] = rule.get("maximum")
        if "min_length" in rule or "max_length" in rule or "pattern" in rule:
            raise PolicyError(f"{label}: 整数参数不能声明字符串约束")
    else:
        for key in ("min_length", "max_length"):
            if key in rule and (not _is_int(rule[key]) or rule[key] < 0):
                raise PolicyError(f"{label}: {key} 必须是非负整数")
        compiled["min_length"] = rule.get("min_length")
        compiled["max_length"] = rule.get("max_length")
        pattern = rule.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise PolicyError(f"{label}: pattern 必须是字符串")
            try:
                compiled["pattern"] = re.compile(pattern)
            except re.error as exc:
                raise PolicyError(f"{label}: pattern 无法编译") from exc
        if "minimum" in rule or "maximum" in rule:
            raise PolicyError(f"{label}: 字符串参数不能声明数值约束")
    return compiled


def _compile_rule(action: str, rule, params: dict, index: int) -> dict:
    label = f"{action} rule {index}"
    if not isinstance(rule, dict):
        raise PolicyError(f"{label}: 规则必须是映射")
    unknown = set(rule) - _RULE_KEYS
    if unknown:
        raise PolicyError(f"{label}: 未知字段 " + ", ".join(sorted(unknown)))
    rule_id = rule.get("id")
    if not isinstance(rule_id, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", rule_id):
        raise PolicyError(f"{label}: id 不合法")
    decision = rule.get("decision")
    if decision not in _DECISIONS:
        raise PolicyError(f"{label}: decision 不合法")
    reason = rule.get("reason")
    if not isinstance(reason, str) or not reason:
        raise PolicyError(f"{label}: reason 必须是非空字符串")
    when = rule.get("when")
    if not isinstance(when, dict) or not when:
        raise PolicyError(f"{label}: when 必须是非空映射")
    compiled_when = {}
    for key, expected in when.items():
        field, op = _split_when(key)
        if field not in params:
            raise PolicyError(f"{label}: when 引用了未声明参数 {field}")
        if op in {"lte", "gt"}:
            if params[field]["type"] != "integer" or not _is_int(expected):
                raise PolicyError(f"{label}: {key} 只能比较整数参数")
        compiled_when[key] = expected
    return {"id": rule_id, "decision": decision, "reason": reason, "when": compiled_when}


def _split_when(key: str) -> tuple[str, str]:
    for suffix, op in (("_lte", "lte"), ("_gt", "gt"), ("_eq", "eq")):
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)], op
    raise PolicyError(f"when 条件不支持: {key}")


def _validate_params(spec: dict, params) -> list[str]:
    if not isinstance(params, dict):
        return ["调用参数必须是对象"]
    errors: list[str] = []
    extra = sorted(set(params) - set(spec["params"]))
    if extra:
        errors.append("参数含未声明字段: " + ", ".join(extra))
    for name, rule in spec["params"].items():
        if name not in params:
            errors.append(f"缺少参数 {name}")
            continue
        errors.extend(_check_value(name, rule, params[name]))
    return errors


def _check_value(name: str, rule: dict, value) -> list[str]:
    if rule["type"] == "integer":
        if not _is_int(value):
            return [f"参数 {name} 必须是整数"]
        errors = []
        if rule["minimum"] is not None and value < rule["minimum"]:
            errors.append(f"参数 {name} 小于最小值 {rule['minimum']}")
        if rule["maximum"] is not None and value > rule["maximum"]:
            errors.append(f"参数 {name} 大于最大值 {rule['maximum']}")
        return errors
    if not isinstance(value, str):
        return [f"参数 {name} 必须是字符串"]
    errors = []
    if rule["min_length"] is not None and len(value) < rule["min_length"]:
        errors.append(f"参数 {name} 短于最小长度 {rule['min_length']}")
    if rule["max_length"] is not None and len(value) > rule["max_length"]:
        errors.append(f"参数 {name} 超过最大长度 {rule['max_length']}")
    if rule["pattern"] is not None and rule["pattern"].fullmatch(value) is None:
        errors.append(f"参数 {name} 不符合 pattern")
    return errors


def _when_matches(when: dict, params: dict) -> bool:
    for key, expected in when.items():
        field, op = _split_when(key)
        actual = params.get(field)
        if op == "lte":
            if not _is_int(actual) or actual > expected:
                return False
        elif op == "gt":
            if not _is_int(actual) or actual <= expected:
                return False
        elif actual != expected:
            return False
    return True


def _render_reason(template: str, params: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in params and isinstance(params[key], (str, int)) and not isinstance(params[key], bool):
            return str(params[key])
        return match.group(0)

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, template)


def _idempotency_key(action: str, spec: dict, params: dict) -> str | None:
    fields = spec["idempotency"]
    if not fields or any(name not in params for name in fields):
        return None
    return ":".join([action, *[str(params[name]) for name in fields]])


def _denied(rule: str, reason: str, reversible: bool | None) -> dict:
    return {
        "decision": "deny",
        "rule": rule,
        "reason": reason,
        "reversible": reversible,
        "idempotency_key": None,
    }


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
