# Agent 持续评测流水线

基于 [PikoCI](https://github.com/PikoCI/pikoci) 的一键式 Agent 评测流水线。Web UI 点击按钮即可运行 DeepEval + Promptfoo + TruLens 三套评测，自动汇总并生成 HTML 报告。

## 架构

```
                      ┌─────────────────┐
                      │  PikoCI Web UI  │
                      │  Trigger 按钮   │
                      └────────┬────────┘
                               │
                ┌──────────────▼──────────────┐
                │      job "evaluate"         │
                │                             │
                │  ① setup   (pip + npm)      │
                │  ② deepeval (pytest)        │──┐
                │  ③ promptfoo (CLI)          │──┼──► eval_output/<ts>/
                │  ④ trulens (python)         │──┤    ├ *_results.json
                │  ⑤ merge (summary.json)     │  │    ├ summary.json
                │  ⑥ report (HTML+Chart.js)   │  │    └ report.html
                │  ⑦ gate   (阈值门禁)        │  │
                └─────────────────────────────┘  │
                                                  ▼
                                         eval_output/history.jsonl
                                         (跨运行趋势数据)
```

每个评测工具输出统一 schema 的 JSON，`merge_results.py` 合并后由 `generate_report.py` 渲染成单文件 HTML 报告（Chart.js 通过 CDN 加载）。

---

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行 DeepEval/TruLens/报告脚本 |
| Node.js | 20+ | 运行 promptfoo CLI |
| [PikoCI](https://github.com/PikoCI/pikoci/releases) | latest | CI 编排服务 |
| ARK_API_KEY | 火山方舟 Key | DeepEval/TruLens 的 LLM-as-judge |

> Promptfoo 的 `contains` 断言不需要 API Key；但 DeepEval、TruLens 以及 promptfoo 的 `llm-rubric` 断言都通过火山方舟（Volcano Ark）调用判分模型，必须设置 `ARK_API_KEY`。

---

## 快速开始

### 1. 安装 Python/Node 依赖

```bash
pip install -r requirements.txt
npm install
```

### 2. 下载 PikoCI

```bash
# macOS (Apple Silicon)
curl -L https://github.com/PikoCI/pikoci/releases/latest/download/pikoci-darwin-arm64 -o pikoci
chmod +x pikoci

# macOS (Intel)
curl -L https://github.com/PikoCI/pikoci/releases/latest/download/pikoci-darwin-amd64 -o pikoci
chmod +x pikoci

# Linux (amd64)
curl -L https://github.com/PikoCI/pikoci/releases/latest/download/pikoci-linux-amd64 -o pikoci
chmod +x pikoci
```

### 3. 配置 ARK_API_KEY

```bash
export ARK_API_KEY="your-volcano-ark-api-key"
# 可选：覆盖默认 endpoint / model
export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/coding/v3"
export ARK_MODEL="deepseek-v4-pro"
```

> 这些环境变量会被 PikoCI worker 进程继承，并进一步传递给 DeepEval、TruLens 和 promptfoo_grader。也可以在 `instance/system_config.json` 中配置（参见 [.env.example](.env.example)）。

### 4. 启动 PikoCI 服务

先把 [pipeline.hcl](pipeline.hcl) 顶部 `variable "project_dir"` 的 `default` 改成**你本机的项目绝对路径**（worker 在临时目录执行 task，需要它来 `cd` 回项目根）：

```hcl
variable "project_dir" {
  type    = string
  default = "/your/abs/path/to/agent_evaluator-dev_ci"
}
```

然后启动：

```bash
./pikoci server \
  --db-system mem \
  --jwt-secret my-secret \
  --run-worker \
  --pipeline-name agent-eval \
  --pipeline-config pipeline.hcl
```

参数说明：
- `--db-system mem` — 内存数据库，零配置；重启后历史丢失（换为 SQLite 可持久化，见[下文](#持久化历史)）
- `--run-worker` — 同进程内启动 worker，任务直接在主机执行（默认开启）
- `--pipeline-name` / `--pipeline-config` — 启动时自动加载流水线

> Worker 必须能在主机上找到 `python3`、`node`/`npx`，并继承 `ARK_API_KEY` 环境变量。启动 PikoCI 的那个 shell 里先 `export ARK_API_KEY=...`，或写进 `.env`（已被 .gitignore）。

### 5. 在 Web UI 中触发

1. 浏览器打开 http://localhost:8080
2. 首次登录：用户名 `admin` / 密码 `admin123`（会提示修改密码）
3. 进入 **agent-eval** 流水线 → **evaluate** 作业
4. 点击 **Trigger** 按钮
5. 点击 **Trigger** 直接启动（使用 [pipeline.hcl](pipeline.hcl) 中 `variable` 块的默认值）
6. 实时查看每个 task 的日志输出

> **关于参数配置**：当前 PikoCI 发布版（v0.7.0）的手动触发不弹参数表单。可配置项（`agent_script`、`min_avg_score`、`min_pass_rate`）通过 [pipeline.hcl](pipeline.hcl) 顶部 `variable` 块的 `default` 设定；如需临时覆盖，启动服务时传 vars 文件：
> ```bash
> echo '{"agent_script":"my_agent.py","min_avg_score":70}' > vars.json
> ./pikoci server ... --vars vars.json
> ```
> 本地调试可直接 `./pikoci run -j evaluate -p pipeline.hcl --var agent_script=my_agent.py`。

### 6. 查看报告

- **Web UI**：每个 task 都有实时日志流
- **HTML 报告**：运行结束后打开
  ```bash
  open eval_output/<timestamp>/report.html
  ```
- **机器可读数据**：
  ```bash
  cat eval_output/<timestamp>/summary.json | python -m json.tool
  ```

---

## 选择评测工具与指标（点 Trigger 前）

每次触发前，可以通过 [eval_data/selection.json](eval_data/selection.json) 选择**评测哪些工具**以及**每个工具跑哪些指标**。脚本在每次运行时重新读取该文件，**改完保存即可生效，无需重启 PikoCI**。

```json
{
  "deepeval":  { "enabled": true,  "metrics": ["task_completion", "tool_correctness"] },
  "promptfoo": { "enabled": true,  "metrics": [] },
  "trulens":   { "enabled": false, "metrics": [] }
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `enabled` | `false` 跳过整个工具（该工具所有用例标记为「跳过 / 工具已关闭」） |
| `metrics` | 指标白名单。留空 `[]` 表示跑该工具的**所有**指标；非空时只跑列出的指标，其余用例标记为「跳过 / 指标 X 未勾选」 |

行为说明：
- 被跳过的用例**不会调用 Agent，也不会调用 LLM 判分**，因此可显著省时省钱。
- 跳过的用例在 HTML 报告里显示为灰色「跳过」，并注明原因；它们**不计入**通过率和平均分（分母只含实际打分的用例）。
- 整个工具被关闭时，对应工具卡片显示「已跳过」。

可用的指标名（与 [eval_data/test_cases.json](eval_data/test_cases.json) 中 `metrics` 字段对应）：

- **DeepEval**：`task_completion`、`tool_correctness`、`hallucination`、`factual_consistency`、`goal_accuracy`、`geval`、`format_compliance` 等
- **TruLens**：`answer_relevance`、`context_relevance`、`groundedness`
- **Promptfoo**：按断言类型过滤，即 `contains`、`not-contains`、`contains-any`、`similar`、`llm-rubric`、`python` 等（对应每条用例 `metrics.promptfoo_assert.type`）

> 默认配置三个工具全开、指标全跑（`enabled: true, metrics: []`）。只想验证某个工具或某类指标时，把其它工具 `enabled` 设为 `false` 或缩小 `metrics` 白名单即可；验证完改回 `[]`/`true` 恢复全量。

---

## 目录结构

```
.
├── pipeline.hcl                     # PikoCI 流水线定义（HCL）
├── requirements.txt                 # Python 依赖
├── package.json                     # Node/promptfoo 依赖
├── eval_data/
│   ├── test_cases.json              # 统一测试用例（三工具共用）
│   └── selection.json               # 评测范围选择（工具开关 + 指标白名单）
├── tests/
│   ├── conftest.py                  # pytest fixtures + JSON 输出 hook
│   └── test_agent.py                # DeepEval 参数化测试
├── scripts/
│   ├── eval_common.py               # 共享辅助（agent 加载、路径、JSON 写入）
│   ├── promptfoo_exec_provider.py   # promptfoo 独立 provider（直接调用 agent）
│   ├── gen_promptfoo_config.py      # 从 test_cases.json 生成 promptfooconfig.yaml
│   ├── convert_promptfoo_results.py # 转换 promptfoo 原生 JSON → 统一 schema
│   ├── run_trulens.py               # TruLens 独立评测入口
│   ├── merge_results.py             # 合并三工具结果 → summary.json
│   ├── generate_report.py           # Jinja2 渲染 HTML 报告
│   └── quality_gate.py              # 阈值门禁
├── templates/
│   └── report.html                  # Jinja2 报告模板（Chart.js CDN）
├── eval_output/                     # 运行时产物（gitignore）
│   ├── history.jsonl
│   └── <timestamp>/
│       ├── deepeval_results.json
│       ├── promptfoo_raw.json
│       ├── promptfoo_results.json
│       ├── trulens_results.json
│       ├── summary.json
│       └── report.html
└── example_agent.py                 # 默认被测 Agent
```

---

## 不通过 PikoCI 单独运行（本地调试）

每个脚本都可以独立执行，便于开发和调试：

```bash
# 0. 准备环境
export ARK_API_KEY=your-key
export EVAL_OUTPUT_DIR=./eval_output/manual-test
export AGENT_SCRIPT=example_agent.py
mkdir -p "$EVAL_OUTPUT_DIR"

# 1. DeepEval
python -m pytest tests/ -v

# 2. Promptfoo
python scripts/gen_promptfoo_config.py
npx promptfoo eval --config promptfooconfig.yaml \
  --output "$EVAL_OUTPUT_DIR/promptfoo_raw.json" --no-cache
python scripts/convert_promptfoo_results.py

# 3. TruLens
python scripts/run_trulens.py

# 4. 合并 + 报告
python scripts/merge_results.py
python scripts/generate_report.py
open "$EVAL_OUTPUT_DIR/report.html"

# 5. 门禁（可选）
GATE_MIN_AVG_SCORE=70 GATE_MIN_PASS_RATE=0.8 python scripts/quality_gate.py
```

---

## 切换被测 Agent

流水线默认评测 [example_agent.py](example_agent.py)。要评测自己的 Agent：

1. 把 Agent 脚本放在项目根目录（或任何 PikoCI worker 可访问的路径）
2. 脚本必须暴露以下入口之一：
   ```python
   def run(query: str, input_payload: dict | None = None) -> str | dict: ...
   # 或
   def run_agent(query: str, input_payload: dict | None = None) -> str | dict: ...
   ```
3. 返回值可以是：
   - `str`：纯文本回答
   - `dict`：`{"answer": str, "tool_calls": [...], "trace": {...}, "context": str}`（结构化字段会被 DeepEval 的 tool_correctness/plan_quality/hallucination 等指标消费）
4. 在 Trigger 表单中把 `agent_script` 改为你的脚本路径（相对项目根），或：
   ```bash
   export AGENT_SCRIPT=path/to/your_agent.py
   ```

---

## 添加测试用例

编辑 [eval_data/test_cases.json](eval_data/test_cases.json)，追加一条：

```json
{
  "id": "unique_case_id",
  "name": "可读的用例名",
  "query": "用户的问题",
  "expected": "期望包含的关键文本",
  "input_payload": null,
  "expected_payload": {
    "expected_tool_calls": [{"name": "tool_name", "arguments": {"key": "value"}}]
  },
  "metrics": {
    "deepeval": "task_completion",
    "trulens": "answer_relevance",
    "promptfoo_assert": {"type": "contains", "value": "关键词"}
  }
}
```

支持的 DeepEval 指标（在 [app/services/evaluation_engine.py](app/services/evaluation_engine.py) 中）：
- `task_completion` / `tsr_aro` — 任务完成度
- `tool_correctness` — 工具调用正确性（需要 `expected_payload.expected_tool_calls`）
- `hallucination` / `factual_consistency` — 幻觉/事实一致性（需要 `input_payload.context`）
- `goal_accuracy` — 目标准确性
- `plan_quality` / `plan_adherence` / `step_efficiency` — 规划类（需要 `agent_output_payload.trace`）
- `geval` — 自定义评分（需要 `expected_payload.criteria`）
- `format_compliance` — JSON 格式合规（需要 `expected_payload.fields`）

支持的 TruLens 指标：`answer_relevance`、`context_relevance`、`groundedness`（后两者需要 `input_payload.context`）。

Promptfoo 断言支持：`contains`、`not-contains`、`contains-any`、`similar`，以及 `llm-rubric`（调用 Ark LLM 打分）。

---

## 持久化历史

默认 `--db-system mem` 会在 PikoCI 重启后清空构建历史。但 `eval_output/history.jsonl` 是 append-only 的本地文件，HTML 报告里的趋势图从它读取，不依赖 PikoCI 的数据库。

如需让 PikoCI 本身也持久化构建记录，使用 SQLite：

```bash
./pikoci server \
  --db-system sqlite \
  --db-dsn "pikoci.db" \
  --jwt-secret my-secret \
  --run-worker \
  --pipeline-name agent-eval \
  --pipeline-config pipeline.hcl
```

详见 PikoCI 的 [Database Backends 文档](https://docs.pikoci.com/Database)。

---

## 故障排查

| 症状 | 原因 / 解决 |
|------|------------|
| setup 报 `Could not open requirements file: 'requirements.txt'` | worker 在临时目录执行 task，找不到项目文件。把 [pipeline.hcl](pipeline.hcl) 里 `variable "project_dir"` 的 default 改成本机项目绝对路径 |
| DeepEval/TruLens 步骤报 `未配置 ARK_API_KEY` | `export ARK_API_KEY=...` 后再启动 PikoCI；worker 会继承启动 shell 的环境 |
| Promptfoo 步骤 `npx: command not found` | 确认 Node 20+ 已安装且在 PATH 中；或在 pipeline.hcl 的 setup 中 `npm install -g promptfoo` |
| Promptfoo 评测已出结果却 `telemetry.shutdown() timed out` / exit 100 | 脚本已设置 `PROMPTFOO_DISABLE_TELEMETRY=1` 并在输出文件存在时容忍该退出码，无需处理 |
| Agent 加载失败 `Agent script not found` | 检查 `agent_script` 路径（相对项目根）；脚本必须存在且包含 `run()` 函数 |
| TruLens `groundedness` 全部 0 分 | 该指标要求 `input_payload.context` 字段；对应测试用例已包含上下文，不要删除 |
| HTML 报告中趋势图为空 | 首次运行没有历史；再跑 1-2 次就会出现（数据来自 `eval_output/history.jsonl`） |
| Chart.js 图表不显示 | 报告需要联网加载 CDN（`cdn.jsdelivr.net`）；离线环境请把 chart.umd.min.js 下载到本地并修改模板路径 |
| PikoCI 404/端口冲突 | 默认 8080，用 `--http-addr :9090` 修改 |
| 想跳过门禁失败 | Gate 任务内部已 `exit 0`，不会阻塞流水线；查看日志即可看到具体阈值失败原因 |

---

## 参考链接

- [PikoCI 文档](https://docs.pikoci.com/)
- [PikoCI Pipeline Reference](https://docs.pikoci.com/Pipeline/)
- [DeepEval 文档](https://docs.confident-ai.com/)
- [Promptfoo 文档](https://www.promptfoo.dev/)
- [TruLens 文档](https://www.trulens.org/)
- 本仓库 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) — 平台整体架构
- 本仓库 [scripts/verify_metrics.py](scripts/verify_metrics.py) — 所有 DeepEval/TruLens 指标的独立调用样例
