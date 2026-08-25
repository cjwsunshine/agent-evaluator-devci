# Agent Evaluator Dev 项目说明

这是一个基于 Flask + SQLite + 原生 HTML/CSS/JavaScript 的 Agent 评测平台。平台用于管理 Agent、评测集、评测任务，并通过 DeepEval、Promptfoo、TruLens 等工具执行评测和生成报告。

> 注意：本说明只描述文件职责和功能关系，不包含任何密钥内容。

## 一、启动方式

```bash
/Users/cjw/cjw/cjwproject/agent_evaluator-dev/.venv/bin/python run.py
```

默认服务端口：`8000`

访问地址：

- 登录页：`http://127.0.0.1:8000/login`
- 主页面：`http://127.0.0.1:8000/`

## 二、核心目录结构

```text
agent_evaluator-dev/
├── app/                         # Flask 后端应用
│   ├── api/                     # API 路由
│   ├── config/                  # 系统配置
│   ├── models/                  # 数据库模型
│   ├── services/                # 业务服务层
│   └── utils/                   # 通用工具/装饰器
├── templates/                   # 前端 HTML 模板
├── static/                      # 前端 CSS/JS 静态资源
├── modules/weather_math/        # 内置 Weather Math Agent 模块
├── scripts/                     # 辅助脚本/Promptfoo provider
├── weather-math-agent/          # Weather Math Agent 独立样例工程
├── instance/                    # 运行时配置目录
├── results/                     # 评测结果输出目录
├── run.py                       # Flask 启动入口
├── requirements.txt             # Python 依赖
├── package.json                 # Node/Promptfoo 相关依赖
└── PROJECT_OVERVIEW.md          # 当前项目说明文档
```

## 三、后端入口与配置

### 1. Flask 应用入口

| 文件 | 作用 |
|---|---|
| `run.py` | 启动 Flask 应用，调用 `create_app()` |
| `app/__init__.py` | 创建 Flask app、初始化数据库、注册 API 蓝图、注册前端页面路由 |

`app/__init__.py` 主要做这些事情：

- 创建 Flask 应用
- 加载配置
- 初始化 SQLAlchemy
- 自动创建数据库表
- 注册 `/api` 蓝图
- 注册 `/` 和 `/login` 页面

### 2. 系统配置

| 文件 | 作用 |
|---|---|
| `app/config/config.py` | 统一读取环境变量、数据库配置、Promptfoo/DeepEval/TruLens 路径、Ark 模型配置 |
| `instance/system_config.json` | 系统设置页面保存后的运行时配置文件 |
| `.env` / `.env.example` | 本地环境变量配置示例和实际配置 |

`Config.get_runtime_config()` 会合并：

1. 默认配置
2. 环境变量
3. `instance/system_config.json`

系统设置页面主要保存：

- 方舟 API Key
- 方舟 Base URL
- 执行模型
- 评测模型

## 四、数据库模型

数据库模型集中在：

| 文件 | 作用 |
|---|---|
| `app/models/models.py` | 定义所有 SQLAlchemy 数据表模型 |

主要模型：

| 模型 | 作用 |
|---|---|
| `User` | 用户账号、角色 |
| `Agent` | Agent 配置，支持 API / local / script 类型 |
| `EvaluationSet` | 评测集，一组测试用例的集合 |
| `TestCase` | 单条测试用例，包含输入、期望输出、标签、指标 |
| `EvaluationTask` | 评测任务，绑定 Agent、工具和测试用例 |
| `TaskTestCase` | 任务与测试用例的执行关联，保存 Agent 输出和单例状态 |
| `EvaluationResult` | 每个工具对单条用例的评测结果、分数和日志 |
| `SystemLog` | 系统日志模型，当前使用较少 |

## 五、API 路由

所有后端接口集中在：

| 文件 | 作用 |
|---|---|
| `app/api/routes.py` | Flask Blueprint 路由，所有 `/api/...` 接口入口 |

主要 API 分组：

| 功能 | API 路径 | 对应服务 |
|---|---|---|
| 登录注册 | `/api/auth/register`, `/api/auth/login` | `AuthService` |
| Agent 管理 | `/api/agents` | `AgentService` |
| 评测集/测试用例 | `/api/evaluation-sets`, `/api/test-cases` | `TestCaseService` |
| 评测任务 | `/api/tasks` | `TaskService` |
| 评测报告 | `/api/reports` | `ReportService` |
| 系统配置 | `/api/system/config` | `SystemService` |
| 评测工具元信息 | `/api/evaluation/tools` | `EvaluationEngine` |
| Weather Math Agent | `/api/weather-math/...` | `WeatherMathAgentService` |

## 六、服务层功能说明

服务层位于：`app/services/`

| 文件 | 主要职责 |
|---|---|
| `auth_service.py` | 用户注册、登录、JWT token 生成和验证 |
| `agent_service.py` | Agent 增删改查、测试连接、调用 Agent |
| `test_case_service.py` | 测试用例和评测集管理、上传、复制、删除、导入确认 |
| `task_service.py` | 创建任务、启动任务、重启任务、取消任务、删除任务、查询进度 |
| `evaluation_engine.py` | 统一评测执行引擎，封装 DeepEval / Promptfoo / TruLens 评测器 |
| `report_service.py` | 生成报告、报告列表、报告筛选项、导出报告、首页汇总 |
| `system_service.py` | 读取和保存系统配置 |
| `weather_math_agent.py` | 内置 Weather Math Agent 注册、聊天、天气、计算、DeepEval 执行 |

## 七、前端页面与对应文件

### 1. 主页面

| 文件 | 作用 |
|---|---|
| `templates/index.html` | 主工作台 HTML，包含首页、Agent 配置、评测集管理、评测任务、评测报告、系统设置、弹窗 |
| `static/js/app.js` | 主页面所有交互逻辑和 API 调用 |
| `static/css/style.css` | 全站样式，包括登录页和主工作台 |

`templates/index.html` 中的主要页面：

| 页面 | 页面 ID | 主要功能 |
|---|---|---|
| 首页概览 | `home-page` | 展示 Agent 数量、测试用例数量、任务数量、通过率 |
| Agent 配置 | `agent-config-page` | 添加、编辑、删除、测试 Agent |
| 评测集管理 | `test-cases-page` | 评测集列表、新建评测集、上传测试项、编辑/删除/复制/运行 |
| 评测任务 | `tasks-page` | 任务列表、筛选、重启、取消、删除、查看执行日志、查看报告 |
| 评测报告 | `reports-page` | 报告列表、筛选、查看详情、导出报告、查看执行日志 |
| 系统设置 | `settings-page` | 配置方舟 API Key、Base URL、执行模型、评测模型 |

### 2. 登录页

| 文件 | 作用 |
|---|---|
| `templates/login.html` | 登录/注册页面 |
| `static/js/auth.js` | 登录、注册、tab 切换、toast 提示 |
| `static/css/style.css` | 登录页样式 |

## 八、前端 JS 功能映射

主要文件：`static/js/app.js`

| 功能 | 关键函数 |
|---|---|
| 通用 API 请求 | `apiCall()` |
| Toast 提示 | `showToast()` |
| 页面导航 | `navigateTo()` |
| 首页统计 | `loadDashboardData()` |
| Agent 管理 | `loadAgents()`, `showAgentModal()`, `saveAgent()`, `editAgent()`, `deleteAgent()`, `testAgentConnection()` |
| 评测集管理 | `loadEvalSets()`, `renderEvalSetTable()`, `saveEvalSetCreate()`, `editEvalSet()`, `deleteEvalSet()`, `copyEvalSet()`, `runEvalSet()` |
| 测试用例上传 | `uploadTestCases()`, `renderUploadPreview()`, `confirmUpload()` |
| 任务管理 | `loadTasks()`, `renderTaskTable()`, `restartTask()`, `cancelTask()`, `deleteTask()`, `viewProgress()` |
| 任务进度轮询 | `pollTaskProgress()` |
| 报告列表 | `loadReports()`, `loadReportsList()`, `renderReportsList()` |
| 报告详情 | `viewReport()`, `loadReportData()`, `viewReportExecutionLog()`, `exportReport()` |
| 系统设置 | `loadSystemSettings()`, `saveSettings()` |

## 九、Agent 管理功能对应文件

| 层级 | 文件 | 作用 |
|---|---|---|
| 前端页面 | `templates/index.html` | Agent 配置页面和 Agent 弹窗 |
| 前端逻辑 | `static/js/app.js` | Agent 列表渲染、保存、编辑、删除、测试连接 |
| API 路由 | `app/api/routes.py` | `/api/agents...` 路由 |
| 服务层 | `app/services/agent_service.py` | Agent 数据管理和实际调用逻辑 |
| 数据模型 | `app/models/models.py` | `Agent` 模型 |

Agent 调用方式：

| 类型 | 说明 |
|---|---|
| `api` | 通过 HTTP API 调用外部 Agent |
| `local` | 调用本地模块内置 Agent |
| `script` | 脚本型 Agent，Web 创建暂时受限 |

## 十、评测集管理功能对应文件

| 层级 | 文件 | 作用 |
|---|---|---|
| 前端页面 | `templates/index.html` | 评测集列表、新建评测集、上传弹窗 |
| 前端逻辑 | `static/js/app.js` | 评测集筛选、创建、编辑、删除、复制、上传、运行 |
| API 路由 | `app/api/routes.py` | `/api/evaluation-sets...`, `/api/test-cases...` |
| 服务层 | `app/services/test_case_service.py` | 评测集和测试用例管理 |
| 数据模型 | `app/models/models.py` | `EvaluationSet`, `TestCase` |

评测集由多个 `TestCase` 组成，并可绑定：

- Agent
- 评测工具
- 评测指标

## 十一、评测任务功能对应文件

| 层级 | 文件 | 作用 |
|---|---|---|
| 前端页面 | `templates/index.html` | 评测任务列表和进度弹窗 |
| 前端逻辑 | `static/js/app.js` | 任务筛选、重启、取消、删除、查看进度 |
| API 路由 | `app/api/routes.py` | `/api/tasks...` |
| 服务层 | `app/services/task_service.py` | 任务创建、执行、重启、取消、删除、状态查询 |
| 执行引擎 | `app/services/evaluation_engine.py` | 实际执行评测工具 |
| 数据模型 | `app/models/models.py` | `EvaluationTask`, `TaskTestCase`, `EvaluationResult` |

任务执行流程：

1. 创建 `EvaluationTask`
2. 创建多个 `TaskTestCase`
3. 后台线程执行 `EvaluationEngine.run_evaluation()`
4. 调用 Agent 获取输出
5. 调用评测工具打分
6. 保存 `EvaluationResult`
7. 更新任务状态和进度

## 十二、评测工具与评测引擎

核心文件：`app/services/evaluation_engine.py`

| 类 | 作用 |
|---|---|
| `EvaluationEngine` | 任务评测总调度器 |
| `BaseEvaluator` | 评测器基类 |
| `DeepEvalEvaluator` | DeepEval 评测器 |
| `PromptfooEvaluator` | Promptfoo 评测器，通过外部 promptfoo 命令执行 |
| `TruLensEvaluator` | TruLens 指标适配，目前为启发式占位评分 |

支持工具：

| 工具 | 适合评测内容 |
|---|---|
| DeepEval | 回答相关性、任务完成度、目标准确性等 LLM 质量指标 |
| Promptfoo | 断言通过率、包含检查、LLM rubric 等 Prompt/输出断言 |
| TruLens | 上下文相关性、事实一致性、回答相关性等指标 |

Promptfoo 相关文件：

| 文件 | 作用 |
|---|---|
| `scripts/promptfoo_agent_provider.py` | Promptfoo 执行时调用平台 Agent 的 provider 脚本 |
| `promptfooconfig.js` | Promptfoo 配置示例/默认配置 |
| `results/promptfoo/` | Promptfoo 输出结果目录 |

## 十三、报告功能对应文件

| 层级 | 文件 | 作用 |
|---|---|---|
| 前端页面 | `templates/index.html` | 报告列表、报告详情、执行日志弹窗 |
| 前端逻辑 | `static/js/app.js` | 报告筛选、查看详情、导出、日志查看 |
| API 路由 | `app/api/routes.py` | `/api/reports...` |
| 服务层 | `app/services/report_service.py` | 生成报告、聚合报告列表、导出报告、首页汇总 |
| 数据模型 | `app/models/models.py` | `EvaluationTask`, `TaskTestCase`, `EvaluationResult` |

报告不是独立表，而是基于任务和评测结果即时生成。

报告列表的逻辑：

- 按 `评测集 + Agent + 工具` 聚合
- 展示该组合下最新完成任务的报告入口

## 十四、系统设置功能对应文件

| 层级 | 文件 | 作用 |
|---|---|---|
| 前端页面 | `templates/index.html` | 系统设置页面 |
| 前端逻辑 | `static/js/app.js` | `loadSystemSettings()`, `saveSettings()` |
| API 路由 | `app/api/routes.py` | `/api/system/config` |
| 服务层 | `app/services/system_service.py` | 读取/保存系统配置 |
| 配置文件 | `instance/system_config.json` | 保存运行时配置 |
| 默认配置 | `app/config/config.py` | 配置默认值和读取逻辑 |

当前系统设置页主要显示：

- 方舟 API Key
- 方舟 Base URL
- 执行模型
- 评测模型

Promptfoo 路径配置暂时隐藏，但后端仍保留默认值和兼容逻辑。

## 十五、Weather Math Agent 相关文件

项目中有两份 Weather Math Agent：

### 1. 平台内置模块

| 文件 | 作用 |
|---|---|
| `modules/weather_math/agent.py` | Weather Math Agent 本体，支持天气查询和数学计算 |
| `app/services/weather_math_agent.py` | 平台内注册、调用、DeepEval 执行封装 |

### 2. 独立样例工程

| 文件 | 作用 |
|---|---|
| `weather-math-agent/agent.py` | 独立 Agent 实现 |
| `weather-math-agent/tests/deepeval/test_agent.py` | DeepEval 测试脚本 |
| `weather-math-agent/tests/deepeval/deepeval.conf.json` | DeepEval 配置 |
| `weather-math-agent/tests/promptfoo/promptfooconfig.yaml` | Promptfoo 测试配置 |
| `weather-math-agent/tests/promptfoo/weather_math_promptfoo_test_cases.json` | Promptfoo 测试用例 JSON |

## 十六、脚本文件说明

| 文件 | 作用 |
|---|---|
| `scripts/promptfoo_agent_provider.py` | Promptfoo 外部命令执行时调用平台 Agent |
| `scripts/promptfoo_smoke_test.py` | Promptfoo 冒烟测试脚本 |
| `scripts/local_e2e_regression.py` | 本地端到端回归脚本 |
| `run_promptfoo_test.sh` | Promptfoo 测试运行脚本 |
| `init_admin.py` | 初始化管理员用户脚本 |
| `example_agent.py` | 示例 Agent 脚本 |
| `example_test_cases.json` | 示例测试用例 |

## 十七、已清理的空目录

本次整理删除了项目中的空目录，包括：

- `agents_uploads/`
- `uploads/`
- `docs/`
- `app/core/`
- `app/templates/`
- `app/static/` 及其空子目录
- `results/deepeval/`
- `agentskill_eval/app/core/`
- `agentskill_eval/app/templates/`
- `agentskill_eval/app/static/` 及其空子目录

同时清理过程中也发现并删除了一些依赖环境中的空目录。虚拟环境和依赖目录本身没有整体删除。

## 十八、注意事项

1. `.venv/`、`.trulens-venv/`、`node_modules/` 是依赖目录，不建议手动删除，除非要重新安装依赖。
2. `.env`、`instance/system_config.json` 可能包含敏感配置，不要提交或对外展示。
3. `eval_platform.db` 是当前主数据库文件。
4. `default.sqlite`、`app/eval_platform.db` 可能是历史或备用数据库文件，删除前需要确认是否仍被使用。
5. `agentskill_eval/` 看起来像另一份旧版/并行样例工程，当前主应用主要使用根目录下的 `app/`、`templates/`、`static/`。
6. 如果后续需要重新启用上传目录，程序通常会在上传时自动创建；如果某些上传逻辑依赖目录预先存在，可手动恢复对应目录。
