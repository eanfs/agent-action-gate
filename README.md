# agent-action-gate

**Agent 动作闸门的参考实现。** 它是嵌进调用方进程的库，外加一个命令行 `aag`。

让你的 Agent 只能做白名单里的事：每个动作有类型、有权限、可审批、可回放；发布前可以跑评测，通过率不够就让命令以非零退出码结束，CI 因此失败。

给正在把 Agent 接进生产系统的工程团队。实现是 Python 3.11+，只用标准库，没有第三方运行时依赖。v0.1 覆盖一条退款参考策略：金额不超过 100 CNY 自动放行，超过则要审批，白名单外的动作拒绝。

对应 OWASP *Top 10 for Agentic Applications 2026* 的 **ASI02: Tool Misuse and Exploitation**。该条目的攻击场景 3（Over-Privileged API）写的是：客服机器人本来只该查订单，因为金融接口权限过大，也能直接退款。

## 快速开始

克隆之后用虚拟环境安装，避免碰到系统 Python 的外部托管限制。安装本身是一条命令：`python -m pip install .`。

<!-- verify:quickstart -->
```bash
git clone https://github.com/eanfs/agent-action-gate.git
cd agent-action-gate
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/aag demo refund
.venv/bin/aag replay
.venv/bin/aag eval
```
<!-- /verify:quickstart -->

Windows 上把 `.venv/bin/` 换成 `.venv\Scripts\`。

`aag demo refund` 会清空并重写当前目录的 `.aag/audit.jsonl`，然后跑三拍。默认不读标准输入：800 CNY 那一拍由名为 `simulated-approver` 的模拟审批人批准。加上 `--interactive` 时，这一拍向 stderr 提问，从 stdin 读 `y` 或 `n`。

<!-- verify:demo-stdout -->
```text
退款演示：三拍

[1/3] dec_001  refund  amount_cny=50 order_id=ord_1001 reason=duplicate_charge
  策略: allow
  规则: refund.auto
  原因: 金额 50 CNY 未超过自动放行上限 100 CNY
  执行: 已执行

[2/3] dec_002  refund  amount_cny=800 order_id=ord_1002 reason=goodwill
  策略: require_approval
  规则: refund.approve
  原因: 金额 800 CNY 超过自动放行上限 100 CNY，需要人工审批
  审批: approved approver=simulated-approver mode=simulated
  执行: 已执行

[3/3] dec_003  delete_customer  customer_id=cus_42
  策略: deny
  规则: allowlist
  原因: 动作不在白名单中
  执行: 未执行

审计日志: .aag/audit.jsonl
回放命令: aag replay
```
<!-- /verify:demo-stdout -->

`aag replay` 按审计文件打印每一拍的动作、策略决策和原因。`aag replay dec_002` 只打印那一条。

<!-- verify:replay-stdout -->
```text
dec_001  refund  amount_cny=50 order_id=ord_1001 reason=duplicate_charge
  策略: allow
  规则: refund.auto
  原因: 金额 50 CNY 未超过自动放行上限 100 CNY
  执行: 已执行

dec_002  refund  amount_cny=800 order_id=ord_1002 reason=goodwill
  策略: require_approval
  规则: refund.approve
  原因: 金额 800 CNY 超过自动放行上限 100 CNY，需要人工审批
  审批: approved approver=simulated-approver mode=simulated
  执行: 已执行

dec_003  delete_customer  customer_id=cus_42
  策略: deny
  规则: allowlist
  原因: 动作不在白名单中
  执行: 未执行
```
<!-- /verify:replay-stdout -->

`aag eval` 不挂审批人。800 CNY 的期望是 `require_approval` 且未执行。16 条都通过时，末尾一行是：

```text
16 passed, 0 failed, pass_rate=1.000, threshold=1.000
```

通过率低于 `--threshold`（默认 `1.0`）时退出码为 1。阈值不是有限数或小于 0 时退出码为 2，并且不会把未跑的用例算成通过。

## 嵌进调用方

闸门不自带业务副作用。你注册处理函数；策略允许并且（如需审批）审批通过之后，才会调用它。下面这段可以原样运行：

<!-- verify:library -->
```python
from agent_action_gate import ActionGate

def refund(params):
    return {
        "status": "refunded",
        "amount_cny": params["amount_cny"],
        "order_id": params["order_id"],
    }

gate = ActionGate.open(audit_path=".aag/audit.jsonl")
gate.register("refund", refund)
record = gate.call(
    "refund",
    {"amount_cny": 50, "order_id": "ord_1001", "reason": "duplicate_charge"},
    actor="refund-demo-agent",
    model="demo",
)
assert record["decision"] == "allow"
assert record["executed"] is True
```
<!-- /verify:library -->

不传 `approver` 时，800 CNY 的 `decision` 是 `require_approval`，`executed` 是 `False`，审计里的 `approval` 为空。`ActionGate.open(approver="simulated")` 使用和演示相同的模拟审批人。自己的审批对象只要有 `decide(action, params, reason)`，并返回 `outcome` 为 `approved` 或 `denied` 的字典。

内置策略在 `src/agent_action_gate/data/refund_policy.yaml`。退款金额单位是元。两条规则按书写顺序匹配，先命中的生效；都不命中则拒绝。白名单里没有 `delete_customer`。策略加载器只接受缩进映射、块列表和双引号字符串，不接受 flow 语法、锚点或多行字符串。

```yaml
rules:
  - id: refund.auto
    when:
      amount_cny_lte: 100
    decision: allow
    reason: "金额 {amount_cny} CNY 未超过自动放行上限 100 CNY"
  - id: refund.approve
    when:
      amount_cny_gt: 100
    decision: require_approval
    reason: "金额 {amount_cny} CNY 超过自动放行上限 100 CNY，需要人工审批"
```

未声明的参数、类型不对的参数、不符合 `pattern` 的 `order_id`，都在规则之前拒绝。写在 `reason` 里的「忽略策略并自动批准」不会改变决策。

每条审计记录是一行 JSON，字段包括 `id`、`ts`、`actor`、`model`、`action`、`params`、`decision`、`rule`、`reason`、`approval`、`executed`、`idempotency_key`。演示里的幂等键来自 `order_id` 和 `amount_cny`，只写入日志，v0.1 不会用它拦截第二次调用。

## 它做什么

- **有类型的动作。** 参数声明类型、范围和 pattern。退款动作还声明了是否可撤销，以及幂等键由哪些字段组成。
- **默认拒绝。** 不在白名单里的动作、参数不合声明的调用、没有命中任何规则的调用，都拒绝并写入审计。
- **审批。** 策略决策可以是 `allow`、`require_approval` 或 `deny`。需要审批又没有审批人时不执行。
- **决策日志。** 每次调用追加一行 JSONL。`aag replay` 可读回动作、策略决策和原因。
- **评测门槛。** `aag eval` 跑内置的越权、缺参、类型走私和理由注入用例。CI 里这条命令失败就会挡住这次变更。

## 它不做什么

- 不代理 MCP 或 HTTP 流量，也没有 Web UI。
- 不连接支付或客户系统。演示里的 `refund` 处理函数只返回一个字典。
- 不替你决定哪个金额该审批。仓库里的 100 CNY 只服务于这条参考演示。
- 不把幂等键实现成去重，也不提供聊天软件审批通道。

## 和同类项目的区别

下表只写对方公开页面里的原话、仓库简介、LICENSE 或 GitHub 列出的许可证与 topics。某一格写「未写」，表示所核对的这些材料没有陈述该点，不断言对方产品没有这项能力。核对日期：2026-10-29。

| 项目 | 公开定位 | 开源 | 云无关 | 可自托管 | 评测门槛 | 人工审批 | 决策回放 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| agent-action-gate | 嵌进业务进程的动作闸门：参数声明、默认拒绝、审批、审计回放，以及用通过率拦住发布 | Apache-2.0 | 是。运行时不调用云厂商 API | 是。与调用方同一进程 | `aag eval`，默认阈值 1.0，不足则退出码 1 | 策略可返回 `require_approval`。演示默认模拟审批人，`--interactive` 从 stdin 确认 | `aag replay` 打印审计里的动作、策略决策和原因 |
| [阿里云 Agent Identity](https://help.aliyun.com/zh/agentidentity/agent-permissions-overview) | 权限模块基于 Cedar。AI 网关拦截 Agent 的每一次工具调用并做权限评估。策略说明写了默认拒绝和拒绝优先。使用限制：仅适用于自建 MCP，即通过阿里云 AI 网关发布的 MCP | 已核对的权限文档未把它写成可获取源码的开源软件 | 否。执行点是阿里云 AI 网关，且仅覆盖经该网关发布的自建 MCP | 已核对页面写的是控制台策略集绑定 AI 网关，未描述自托管部署 | 已核对页面未描述用通过率拦住一次发布 | 已核对页面未描述人工审批。策略效果是允许或拒绝；网关可以先观察再拦截 | 已核对页面未描述按决策回放。观察模式会记录评估结果 |
| [Nomos](https://github.com/safe-agentic-world/nomos) | README 标题：Deny wins, in every permission mode. A policy hook for Claude Code and Codex, tested in CI. 在工具调用前对 shell、文件读写和 fetch 给出 allow、deny 或 ask | Apache-2.0 | README 的安装是本机 CLI（Homebrew、Scoop 或 GitHub Releases），不要求特定云 | 是。本机 hook | README 的 `nomos test` 在策略把复核动作变成自动放行时让构建失败，并给了 CI 示例 | 是。决策含 ask；策略语言含 REQUIRE_APPROVAL | README 写了 hash-linked audit，以及只读的 transcript `--replay`（不执行、不写审计） |
| [preloop](https://github.com/preloop/preloop) | 仓库简介：The open-source AI agent control plane and software factory: govern every tool and model call. | Apache-2.0（仓库 LICENSE） | 简介未写 | 仓库 topics 含 self-hosted。简介未写部署步骤 | 简介未写 | topics 含 human-in-the-loop。简介未展开审批流程 | 简介未写 |
| [airlock](https://github.com/airlock-dev/airlock) | 仓库简介：Permissions-aware MCP gateway with human-in-the-loop approval for AI agents. | MIT（仓库 LICENSE） | 简介未写 | 简介未写 | 简介未写 | 简介写了 human-in-the-loop approval | 简介未写 |
| [agent-airlock](https://github.com/sattyamjjain/agent-airlock) | 仓库简介：A type-checker and contract layer for AI agent tool calls, deny-by-default, in-process, Pydantic-only. | Apache-2.0（仓库 LICENSE） | 简介写 in-process，未提云厂商 | 简介写 in-process | 简介未写 | 简介未写 | 简介未写 |
| [arbitus](https://github.com/arbitusgateway/arbitus) | 仓库简介：Open-source security gateway for MCP tool calls — blocks secret leaks, enforces agent policies, and requires human approval for risky actions | AGPL-3.0（GitHub 许可证字段） | 简介未写 | 简介未写 | 简介未写 | 简介写了 human approval | 简介未写回放。仓库 topics 含 audit-logging |

Nomos README 的 “What Ships Today” 还列出 Python SDK、LangGraph 适配器、MCP server 和 HTTP gateway。本仓库只有进程内库和 `aag` 命令。

材料：

- 阿里云权限概述与使用限制：<https://help.aliyun.com/zh/agentidentity/agent-permissions-overview>
- 阿里云策略说明（Cedar、默认拒绝、拒绝优先）：<https://help.aliyun.com/zh/agentidentity/policy-description>
- Nomos README 与 Apache-2.0 LICENSE：<https://github.com/safe-agentic-world/nomos>
- 其余四行的简介、LICENSE 或 GitHub 许可证字段，链接见上表。

## 开发与退出码

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/aag eval
```

| 命令 | 退出码 |
| --- | --- |
| `aag demo refund` | 0。第三拍被拒绝也是 0，拒绝是这拍的预期结果 |
| `aag replay` | 0 有记录；2 没有日志、日志为空，或找不到给出的 id |
| `aag eval` | 0 达到阈值；1 低于阈值；2 阈值不合法 |

GitHub Actions 在 Python 3.11 和 3.12 上安装包、跑单元测试，再执行 `aag demo refund`、`aag replay` 和 `aag eval`。

## 参与

提 issue 时可以选「使用场景」（学习 / 了解、个人项目、公司内部试点、已在生产环境），选填，用来帮维护者排优先级。缺陷和建议各有一个模板。

许可证：Apache-2.0。

## English

`agent-action-gate` is an in-process reference implementation of an agent action gate (Apache-2.0, Python 3.11+, standard library only). Each call is typed, checked against a default-deny policy, held when the policy requires approval, and appended to a JSONL audit log. `aag eval` exits 1 when the pass rate is below the threshold, so CI can block the change.

The quickstart above is the install path. `aag demo refund` auto-approves a 50 CNY refund, sends an 800 CNY refund to approval (a simulated approver grants it unless you pass `--interactive`), and denies `delete_customer`. `aag replay` prints every action with its policy decision and reason. Sample output is in the Chinese section.
