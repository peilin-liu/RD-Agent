# RD-Agent 架构设计与 Qlib 数据集成指南

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [核心模块详解](#3-核心模块详解)
4. [Qlib 数据全链路分析](#4-qlib-数据全链路分析)
5. [Web UI 架构](#5-web-ui-架构)
6. [如何接入你的 Qlib 数据](#6-如何接入你的-qlib-数据)
7. [配置参考](#7-配置参考)

---

## 1. 项目概述

RD-Agent 是一个基于 LLM 的自动化 R&D（研究开发）代理框架，专注于量化金融领域的因子挖掘和模型优化。核心思想是：**LLM 提出假设 → 自动生成代码 → 在 Qlib 环境中执行回测 → 收集反馈 → 迭代优化**。

### 技术栈

| 层级 | 技术 |
|------|------|
| 核心语言 | Python 3.10+ |
| LLM 集成 | OpenAI / LiteLLM / LangChain |
| 量化引擎 | Qlib（数据加载 + 回测） |
| 执行环境 | Conda / Docker |
| Web 后端 | Flask + Flask-CORS |
| Web 前端 | Vue 3 + Vite + TypeScript + Element Plus + ECharts |
| 监控 UI | Streamlit + Plotly |
| 数据格式 | HDF5 (.h5) → pandas DataFrame |
| 配置管理 | Pydantic Settings（环境变量驱动） |

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLI 入口                                  │
│                  rdagent/app/cli.py                              │
│   命令: fin_factor | fin_model | fin_quant | fin_factor_report   │
│         data_science | general_model | ui | server_ui            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────────┐
          ▼                ▼                     ▼
┌─────────────────┐ ┌──────────────┐ ┌─────────────────────┐
│  R&D Loop        │ │  R&D Loop    │ │  R&D Loop           │
│  (Factor)        │ │  (Model)     │ │  (Quant=Factor+Model)│
│  factor.py       │ │  model.py    │ │  quant.py           │
└────────┬────────┘ └──────┬───────┘ └──────────┬──────────┘
         │                 │                     │
         └─────────────────┼─────────────────────┘
                           │
         ┌─────────────────┼─────────────────────┐
         ▼                 ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    场景层 (Scenarios)                            │
│  rdagent/scenarios/qlib/experiment/                              │
│  ├── factor_experiment.py    QlibFactorScenario                  │
│  ├── model_experiment.py     QlibModelScenario                   │
│  ├── quant_experiment.py     QlibQuantScenario                   │
│  ├── factor_from_report_experiment.py                            │
│  ├── workspace.py            QlibFBWorkspace (执行qrun)          │
│  └── utils.py                数据描述/生成工具                   │
└─────────────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────────┐
         ▼                 ▼                     ▼
┌─────────────────┐ ┌──────────────┐ ┌─────────────────────┐
│  提案生成        │ │  代码生成     │ │  评估与反馈         │
│  proposal/       │ │  developer/   │ │  developer/         │
│  factor_proposal │ │  factor_coder │ │  feedback.py        │
│  model_proposal  │ │  model_coder  │ │  factor_runner.py   │
│  quant_proposal  │ │               │ │  model_runner.py    │
│  bandit.py       │ │               │ │                     │
└─────────────────┘ └──────────────┘ └─────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    执行环境 (Env)                                │
│  rdagent/utils/env.py                                            │
│  ├── QlibCondaEnv     → conda 环境                               │
│  ├── QTDockerEnv      → Docker 环境 (挂载 ~/.qlib/)              │
│  └── 执行命令: qrun conf.yaml  →  python read_exp_res.py        │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                 日志 & UI 层                                     │
│  rdagent/log/                                                    │
│  ├── storage.py          FileStorage (pickle持久化)              │
│  ├── logger.py           日志记录器                               │
│  ├── server/app.py       Flask API 服务                          │
│  ├── ui/app.py           Streamlit 监控面板                      │
│  ├── ui/storage.py       WebStorage (HTTP推送)                   │
│  └── ui/qlib_report_figure.py   回测结果图表                     │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  前端 Web UI (Vue 3)                             │
│  web/src/                                                        │
│  ├── views/Home.vue           主页                               │
│  ├── views/Playground.vue     场景选择 & 上传                    │
│  ├── views/PlaygroundPage.vue 实时实验监控                       │
│  ├── components/lineChart.vue ECharts 指标曲线                   │
│  ├── components/development.vue  开发阶段展示                    │
│  └── components/research.vue     研究阶段展示                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块详解

### 3.1 R&D 循环 (`rdagent/app/qlib_rd_loop/`)

每个 R&D 循环包含 4 个阶段：

```
┌──────────────────────────────────────────┐
│  R&D Loop (evo_n 轮迭代)                 │
│                                          │
│  ┌───────────────────────────────────┐   │
│  │ 1. 假设生成 (Hypothesis Generation)│   │
│  │    LLM 分析历史 → 提出新假设      │   │
│  │    例: "使用波动率加权动量因子"    │   │
│  ├───────────────────────────────────┤   │
│  │ 2. 实验生成 (Experiment Gen)       │   │
│  │    假设 → 具体任务列表             │   │
│  ├───────────────────────────────────┤   │
│  │ 3. 代码生成 (Coding)               │   │
│  │    CoSTEER: 生成/演化代码           │   │
│  │    → factor.py / model.py           │   │
│  ├───────────────────────────────────┤   │
│  │ 4. 执行 & 反馈 (Running/Feedback)   │   │
│  │    qrun conf.yaml → 回测            │   │
│  │    → IC/年化收益/最大回撤等指标     │   │
│  │    → HypothesisFeedback(accept/     │   │
│  │      reject)                        │   │
│  └───────────────────────────────────┘   │
│                                          │
│  3 种模式:                               │
│  - fin_factor: 纯因子挖掘                │
│  - fin_model:  纯模型优化                │
│  - fin_quant:  因子+模型联合优化         │
│     (使用 Bandit 策略选择每轮做什么)     │
└──────────────────────────────────────────┘
```

### 3.2 各模块职责

| 模块路径 | 职责 | 关键类 |
|----------|------|--------|
| `rdagent/core/scenario.py` | 场景基类，定义 R&D 背景/数据源/输出格式 | `Scenario` |
| `rdagent/core/proposal.py` | 假设、实验、反馈的基类 | `Hypothesis`, `Experiment`, `HypothesisFeedback` |
| `rdagent/core/experiment.py` | 实验工作空间基类 | `FBWorkspace`, `Task` |
| `rdagent/core/evolving_agent.py` | 演化代理框架 | `EvolvingAgent` |
| `rdagent/core/evaluation.py` | 评估框架 | |
| `rdagent/scenarios/qlib/experiment/workspace.py` | **Qlib 回测执行** | `QlibFBWorkspace` |
| `rdagent/scenarios/qlib/experiment/utils.py` | **Qlib 数据导出和描述** | `get_data_folder_intro()`, `get_file_desc()` |
| `rdagent/scenarios/qlib/proposal/*.py` | Qlib 假设生成/实验映射 | |
| `rdagent/scenarios/qlib/developer/*.py` | 因子/模型代码生成与执行 | |
| `rdagent/utils/env.py` | Docker/Conda 执行环境管理 | `QlibCondaEnv`, `QTDockerEnv` |
| `rdagent/utils/qlib.py` | Qlib 工具：ALPHA20/ALPHA158 因子库，因子验证 | `ALPHA20`, `validate_qlib_features()` |
| `rdagent/components/coder/` | 通用代码生成组件 | `CoSTEER` |

---

## 4. Qlib 数据全链路分析

这是本文档的核心部分 — 完整描述 Qlib 数据从原始数据到 Web UI 展示的全过程。

### 4.1 数据链路总览

```
~/.qlib/qlib_data/cn_data/        ← 你的 Qlib 原始数据
         │
         ▼  qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")
         │
┌────────────────────────────────────────────────────┐
│ 生成 HDF5 (generate.py)                            │
│  → daily_pv_all.h5      (全量: 2008-12-29~至今)    │
│  → daily_pv_debug.h5    (调试: 100 stocks, 2018-2019)│
│                                                     │
│  字段: $open, $close, $high, $low, $volume, $factor │
│  索引: MultiIndex(time, instrument)                  │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────┐
│ 数据文件夹 (FactorCoSTEERSettings)                  │
│  → git_ignore_folder/factor_implementation_source_data/│
│      daily_pv.h5  +  README.md                     │
│  → git_ignore_folder/factor_implementation_source_data_debug/│
│      daily_pv.h5  +  README.md                     │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼ get_data_folder_intro()
┌────────────────────────────────────────────────────┐
│ LLM 上下文生成                                      │
│  HDF5 → get_file_desc() → 文本描述                  │
│  包含: 索引结构、列名/类型、样本数据                 │
│  → 注入到 LLM prompt，指导因子/模型生成              │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────┐
│ 实验配置 (conf.yaml 由 LLM 生成)                    │
│  dataset:                                           │
│    class: DatasetH                                  │
│    kwargs:                                          │
│      handler: {...}                                 │
│      segments:                                      │
│        train: (2008-01-01, 2014-12-31)              │
│        valid: (2015-01-01, 2016-12-31)              │
│        test:  (2017-01-01, 2020-08-01)              │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼ qrun conf.yaml
┌────────────────────────────────────────────────────┐
│ Qlib 回测执行 (在 Conda/Docker 环境中)              │
│  QlibFBWorkspace.execute():                         │
│  1. qrun conf.yaml       → 训练+回测                │
│  2. python read_exp_res.py → 提取指标               │
│  3. 读取 qlib_res.csv       → 性能指标 DataFrame    │
│  4. 读取 ret.pkl            → 收益率序列             │
│                                                      │
│  输出指标 (QLIB_SELECTED_METRICS):                   │
│  - IC (Information Coefficient)                      │
│  - annualized_return (年化超额收益)                  │
│  - information_ratio (信息比率)                      │
│  - max_drawdown (最大回撤)                           │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────┐
│ 日志持久化                                          │
│  FileStorage → .pkl 文件 (按 trace 组织)            │
│  同时通过 WebStorage → HTTP POST 推送到 Flask       │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────┐
│ Web UI 展示                                         │
│  ┌─────────────┐  ┌───────────────────────────┐    │
│  │ Streamlit UI │  │ Vue 3 Web UI              │    │
│  │ 指标曲线     │  │ - PlaygroundPage: 实时监控 │    │
│  │ Hypothesis   │  │ - lineChart: ECharts 图   │    │
│  │ 回测报告图   │  │ - feedback: 反馈面板       │    │
│  └─────────────┘  └───────────────────────────┘    │
└────────────────────────────────────────────────────┘
```

### 4.2 关键代码路径

#### 步骤 1: 从 Qlib 导出数据

文件: `rdagent/scenarios/qlib/exper/generate.py`

```python
import qlib
# 初始化 Qlib —— 读取你的数据
qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")
from qlib.data import D

instruments = D.instruments()
fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]
data = D.features(instruments, fields, freq="day")

# 导出为 HDF5
data.to_hdf("./daily_pv_all.h5", key="data")
```

#### 步骤 2: 数据描述生成 (供 LLM 使用)

文件: `rdagent/scenarios/qlib/experiment/utils.py`

```python
def get_data_folder_intro(fname_reg=".*") -> str:
    """遍历 HDF5 文件 → 读列名/类型/样本 → 生成文本描述 → LLM 上下文"""
    for p in Path(FACTOR_COSTEER_SETTINGS.data_folder_debug).iterdir():
        content_l.append(get_file_desc(p))
    return "\n---\n".join(content_l)
```

#### 步骤 3: 回测执行

文件: `rdagent/scenarios/qlib/experiment/workspace.py`

```python
class QlibFBWorkspace(FBWorkspace):
    def execute(self, qlib_config_name="conf.yaml"):
        # 1. 选择执行环境 (docker/conda)
        qtde = QTDockerEnv()  # 或 QlibCondaEnv()
        qtde.prepare()

        # 2. Qlib 回测
        qtde.check_output(entry=f"qrun {qlib_config_name}")

        # 3. 提取结果
        qtde.check_output(entry="python read_exp_res.py")

        # 4. 返回指标
        return pd.read_csv(self.workspace_path / "qlib_res.csv")
```

#### 步骤 4: 日志 → Web UI

文件: `rdagent/log/ui/storage.py`

```python
class WebStorage(Storage):
    def _obj_to_json(self, obj, tag, id, timestamp):
        # 将不同类型的日志对象转换为 JSON，推送到 Flask
        # - hypothesis → research.hypothesis
        # - experiment → research.tasks
        # - runner result → feedback.metric
        # - backtest chart → feedback.return_chart (Plotly HTML)
        # - feedback → feedback.hypothesis_feedback
        requests.post(f"{self.url}/receive", json=data)
```

### 4.3 Qlib 数据要求

你的 Qlib 数据必须满足以下条件：

| 要求 | 说明 |
|------|------|
| 目录结构 | 符合 Qlib 标准格式 (`~/.qlib/qlib_data/cn_data/`) |
| 必要字段 | `$open`, `$close`, `$high`, `$low`, `$volume` |
| 可选字段 | `$factor` (标签/目标列) |
| 时间范围 | 至少覆盖 2008~2020 年（可配置） |
| 频率 | 日频 (`freq="day"`) |

---

## 5. Web UI 架构

RD-Agent 提供了 **两套 UI 系统**：

### 5.1 Flask + Vue 3 全栈 Web UI（推荐）

#### 架构总览

```
浏览器访问 http://localhost:19899
         │
         ▼
┌─────────────────────────────────────────────────┐
│               Flask Backend (:19899)            │
│         rdagent/log/server/app.py               │
│                                                 │
│  ★ /          → 返回 Vue 构建产物 index.html     │
│  ★ /<path:fn> → 返回 Vue 静态资源 (js/css/img)  │
│                                                 │
│  API 端点:                                      │
│    GET  /traces          列出历史 trace         │
│    POST /upload          上传文件 & 启动 R&D 任务│
│    POST /trace           前端轮询获取实时消息     │
│    GET  /stdout          下载执行 stdout 日志    │
│    POST /receive         WebStorage 推送消息     │
│    POST /control         控制任务 (stop)        │
│    GET  /test            调试：查看所有任务状态   │
│                                                 │
│  场景支持 (upload 接口):                        │
│    Finance Data Building       → fin_factor    │
│    Finance Model Implementation → fin_model    │
│    Finance Whole Pipeline       → fin_quant    │
│    Finance Data Building (Reports) → fin_factor_report│
│    General Model Implementation  → general_model│
│    Data Science                 → data_science │
│                                                 │
│  任务管理:                                      │
│    RDAgentTask → multiprocessing.Process        │
│    user_request_q / user_response_q (IPC)       │
│    rdagent_processes dict (trace_id → task)     │
└─────────────────────────────────────────────────┘
         │
         │  静态文件来自 Vue 构建产物
         ▼
┌─────────────────────────────────────────────────┐
│         Vue 3 前端 (构建产物)                    │
│   git_ignore_folder/static/                     │
│                                                 │
│  路由 (Hash 模式):                               │
│    /#/ue                  │
│    /#/Playground      Playground.vue            │
│    /#/PlaygroundPage  PlaygroundPage.vue        │
│                                                 │
│  核心页面功能:                                   │
│   Playground.vue:                               │
│     - Start: 选择场景 (首次使用)                 │
│     - Pick a scenario: 选择 R&D 场景类型         │
│     - View previous traces: 浏览历史 trace       │
│     - 上传文件 → 触发 R&D 任务                   │
│                                                 │
│   PlaygroundPage.vue:                           │
│     - PROCESS Tab: 实时显示 R&D 循环进度         │
│     - RESULT Tab: 显示 Hypothesis 和回测指标     │
│     - 左侧 Loop 导航: 切换不同轮次               │
│     - 实时消息流展示 (research/dev/feedback)     │
│                                                 │
│  组件:                                          │
│     lineChart.vue     ECharts 指标折线图        │
│     research.vue      假设/Hypothesis 展示      │
│     development.vue   代码生成 & 反馈展示       │
│     feedback.vue      实验反馈面板              │
│     code.vue           代码高亮展示             │
│     markdown.vue       Markdown 渲染            │
└─────────────────────────────────────────────────┘
```

#### 启动方式

有两种启动方式：**生产模式** 和 **开发模式**。

##### 方式一：生产模式（单端口，推荐）

Flask 直接服务 Vue 构建产物，只需访问一个端口。

```bash
# 步骤 1: 构建 Vue 前端
cd web
npm install                # 首次需要安装依赖
npm run build:flask        # 输出到 ../git_ignore_folder/static/

# 步骤 2: 启动 Flask 服务（自动加载 Vue 静态文件）
cd ..
rdagent server_ui --port 19899

# 步骤 3: 浏览器打开
# http://localhost:19899
```

> **原理**: `npm run build:flask` 执行 `vue-tsc && vite build --outDir ../git_ignore_folder/static`，将前端打包到 `git_ignore_folder/static/`。Flask 启动时 `UI_SETTING.static_path` 默认指向 `./git_ignore_folder/static`，通过 `send_from_directory` 直接服务这些静态文件。`/` 路由返回 `index.html`，`/<path:fn>` 返回其他资源。

##### 方式二：开发模式（双端口，支持热更新）

Vue 开发服务器 (8080) + Flask API (19899) 分开运行，前端代码修改即时生效。

```bash
# 终端 1: 启动 Flask API
rdagent server_ui --port 19899

# 终端 2: 启动 Vue 开发服务器
cd web
npm install                # 首次需要安装依赖
npm run dev                # 启动 Vite 开发服务器 (默认 :8080)

# 浏览器打开
# http://localhost:8080
```

> **原理**: Vite 开发服务器运行在 `localhost:8080`，前端通过 axios 请求 Flask API (`localhost:19899`)。Flask 已启用 CORS (`flask-cors`)，允许跨域请求。开发模式下前端代码修改会自动热更新。

#### 完整 API 接口说明

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 返回 Vue 前端入口 `index.html` |
| `GET` | `/<path:fn>` | 返回静态资源 (js/css/img/...) |
| `GET` | `/traces` | 列出所有历史 trace ID |
| `POST` | `/upload` | 上传文件，创建并启动 R&D 任务 |
| `POST` | `/trace` | 前端轮询，获取 trace 的增量消息 |
| `GET` | `/stdout?id=<trace_id>` | 下载任务的 stdout 日志文件 |
| `POST` | `/receive` | WebStorage 推送消息到前端 |
| `POST` | `/control` | 控制任务（目前支持 `stop`） |
| `POST` | `/user_interaction/submit` | 用户交互响应 (IPC) |
| `GET` | `/test` | 调试端点，查看所有任务状态 |

#### upload 接口参数

```bash
# 示例: 通过 curl 启动一个因子挖掘任务
curl -X POST http://localhost:19899/upload \
  -F "scenario=Finance Data Building" \
  -F "files=@/path/to/your/data.csv" \
  -F "loops=10"

# 支持的 scenario 值:
#   "Finance Data Building"        → fin_factor
#   "Finance Model Implementation"  → fin_model
#   "Finance Whole Pipeline"        → fin_quant
#   "Finance Data Building (Reports)" → fin_factor_report
#   "General Model Implementation"  → general_model
#   "Data Science"                  → data_science
```

#### 前端页面流转

```
Home.vue (/)
  │
  └──→ Playground.vue (/#/Playground)
        │
        ├── Start (引导页)
        ├选择场景 → 上传文件 → 启动任务)
        ├── View previous traces (浏览历史 trace 列表)
        │
        └──→ PlaygroundPage.vue (/#/PlaygroundPage)
              │
              ├── PROCESS Tab: 实时 R&D 循环监控
              │    ├── Research 阶段 (Hypothesis 生成)
              │    ├── Development 阶段 (代码生成 & 演化)
              │    └── Feedback 阶段 (回测反馈)
              │
              └── RESULT Tab: 最终结果
                   ├── 指标折线图 (IC/年化收益/信息比率/最大回撤)
                   └── Hypothesis 成功/失败标注
```

### 5.2 Streamlit 开发监控 UI

```
启动命令: rdagent ui --log-dir ./log --port 19899

功能:
  - 左侧: log 文件夹成功/失败标注)
  - Metrics 图表: IC / 年化收益 / 信息比率 / 最大回撤 (Plotly)
  - 鼠标悬停 Hypothesis 显示完整文本
  - 下载 metrics 为 CSV

核心指标 (QLIB_SELECTED_METRICS):
  IC, annualized_return, information_ratio, max_drawdown
```

### 5.3 前端消息流

```
Flask emit message → frontend poll /trace endpoint
消息类型 (tag):
  research.hypothesis       → 假设内容
  research.tasks            → 任务列表
  evolving.codes           → 演化代码
  evolving.feedbacks       → 演化反馈
  feedback.metric          → 回测指标数据
  feedback.return_chart    → 回测收益曲线 (Plotly HTML)
  feedback.hypothesis_feedback → 假设验收/拒绝
  feedback.config          → 场景配置
  END                      → 任务结束
```

---

## 6. 如何接入你的 Qlib 数据

### 6.1 前提条件

确保你的 Qlib 数据已按标准格式组织好：

```bash
~/.qlib/qlib_data/cn_data/
├── calendars/
├── features/
│   └── ...   # 日频 OHLCV 数据
└── instruments/
```

如果你已有 Qlib 格式的数据，可以直接使用。如果不是 Qlib 格式，需要先用 `qlib` 的工具转换。

### 6.2 接入步骤

#### 步骤 1: 配置数据路径

RD-Agent 的数据路径有两个关键配置：

1. **Qlib 原始数据**: `~/.qlib/qlib_data/cn_data/`
   - 在 `generate.py` 中通过 `qlib.init(provider_uri=...)` 指定
   - 在 `QlibDockerConf.extra_volumes` 中映射到 Docker 容器内

2. **因子实现数据 (HDF5)**: `git_ignore_folder/factor_implementation_source_data/`
   - 由 `FACTOR_COSTEER_SETTINGS.data_folder` 配置（env: `FACTOR_CostEER_DATA_FOLDER`）

#### 步骤 2: 修改数据生成脚本

编辑 `rdagent/scenarios/qlib/experiment/factor_data_template/generate.py`:

```python
import qlib

# 将 provider_uri 改为你的 Qlib 数据路径
qlib.init(provider_uri="~/.qlib/qlib_data/your_data")

from qlib.data import D

instruments = D.instruments()

# 如果你的数据列名不同，在这里修改
fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]

# 修改时间范围以匹配你的数据
data = D.features(instruments, fields, freq="day").swaplevel().sort_index().loc["你的起始日期":].sort_index()
data.to_hdf("./daily_pv_all.h5", key="data")

# 修改 debug 数据的时间范围和股票数量
data = (D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")
        .swaplevel().sort_index()
        .swaplevel()
        .loc[data.reset_index()["instrument"].unique()[:100]]
        .swaplevel().sort_index())
data.to_hdf("./daily_pv_debug.h5", key="data")
```

#### 步骤 3: 如果使用 Docker 环境

在 `rdagent/utils/env.py` 的 `QlibDockerConf` 中，确保数据卷映射正确：

```python
class QlibDockerConf(DockerConf):
    extra_volumes: dict = {
        "~/.qlib/": "/root/.qlib/"  # 将你的 Qlib 数据目录映射进去
    }
```

#### 步骤 4: 生成数据文件

```bash
# 在 Docker 或 Conda 环境中执行
cd rdagent/scenarios/qlib/experiment/factor_data_template/
python generate.py
# 生成: daily_pv_all.h5, daily_pv_debug.h5
```

或通过代码自动生成（首次运行时会自动调用）：

```python
from rdagent.scenarios.qlib.experiment.utils import generate_data_folder_from_qlib
generate_data_folder_from_qlib()
```

#### 步骤 5: 配置时间段

通过环境变量配置训练/验证/测试时间段：

```bash
export QLIB_MODEL_TRAIN_START="你的训练起始日期"
export QLIB_MODEL_TRAIN_END="你的训练结束日期"
export QLIB_MODEL_VALID_START="你的验证起始日期"
export QLIB_MODEL_VALID_END="你的验证结束日期"
export QLIB_MODEL_TEST_START="你的测试起始日期"
export QLIB_MODEL_TEST_END="你的测试结束日期"

# 因子模式
export QLIB_FACTOR_TRAIN_START="..."
# ... 同上

# 联合模式
export QLIB_QUANT_TRAIN_START="..."
# ... 同上
```

#### 步骤 6: 配置多市场 Region（新增功能）

RD-Agent 现在支持在 `~/rd-agent/config.json` 中配置多个市场的 Qlib 数据路径和对应的市场参数。启动 Web UI 时导航栏顶部会显示 Region 选择器。

**config.json 格式**（`~/.rd-agent/config.json`）:

```json
{
  "regions": {
    "cn": {
      "qlib_data_path": "/data/qlib_data/qlib_bin/market_daily/cn/",
      "market": "csi300",
      "benchmark": "SH000300"
    },
    "hk": {
      "qlib_data_path": "/data/qlib_data/qlib_bin/market_daily/hk/",
      "market": "hsi",
      "benchmark": "HSI"
    },
    "us": {
      "qlib_data_path": "/data/qlib_data/qlib_bin/market_daily/us/",
      "market": "sp500",
      "benchmark": "SPX"
    }
  },
  "default_region": "cn"
}
```

**字段说明**:
- `qlib_data_path`: Qlib 数据的绝对路径
- `market`: Qlib 股票池（如 `csi300`, `hsi`, `sp500`）
- `benchmark`: Qlib 基准指数（如 `SH000300`, `HSI`, `SPX`）

**Region 传递链路**:
```
导航栏选择 region → API: POST /api/region → 写入 config.json 的 default_region
                                         → sessionStorage.setItem("selectedRegion")
                                                      │
用户上传任务 → Playground读取 sessionStorage → FormData.append("region", "hk")
                                                      │
Flask /upload → kwargs["region"] = "hk" → RDAgentTask
                                                      │
fin_factor(region="hk") → os.environ["QLIB_REGION"] = "hk"
                                                      │
Runner: env_to_use["qlib_provider_uri"] = "/data/.../hk/"
        env_to_use["qlib_region"] = "hk"
        env_to_use["qlib_market"] = "hsi"
        env_to_use["qlib_benchmark"] = "HSI"
                                                      │
qrun conf.yaml → Jinja2渲染 → provider_uri, market, benchmark 全部替换
```

**CLI 也支持 `--region`**:
```bash
rdagent fin_factor --region hk
rdagent fin_model --region us
rdagent fin_quant --region cn
```

**如果 config.json 不存在**，回退到硬编码默认值 `cn` / `~/.qlib/qlib_data/cn_data` / `csi300` / `SH000300`。

#### 步骤 7: 启动 Web UI 查看数据

```bash
# 1. 构建前端 (如需要)
cd web && npm run build:flask

# 2. 启动 Flask 服务（自动加载 Vue 静态文件）
cd ..
rdagent server_ui --port 19899

# 浏览器打开 http://localhost:19899
# 在导航栏右上角选择 Region，后续所有任务使用该 Region 的数据

# 或者使用 Streamlit UI 直接看日志
rdagent ui --log-dir ./log --port 19899
```

### 6.3 只使用 Web UI 展示已有 Qlib 数据

如果你**只想用 RD-Agent 的 Web UI 来展示已有的 Qlib 回测结果**，而不运行 R&D 循环，可以这样做：

#### 方案 A: 回放已有日志

将你的回测结果构造成 RD-Agent 的日志格式（`.pkl` 文件），然后直接用 Streamlit UI 展示：

```python
from rdagent.log.storage import FileStorage
from rdagent.log import rdagent_logger
from pathlib import Path

# 创建日志目录结构
log_path = Path("./my_logs/qlib_model/my_trace")
log_path.mkdir(parents=True, exist_ok=True)

# 设置日志器
rdagent_logger.set_storages_path(str(log_path))

# 记录你的回测结果
rdagent_logger.log_object(scenario_instance, tag="scenario")
rdagent_logger.log_object(experiment_result, tag="runner result")
rdagent_logger.log_object(ret_df, tag="Quantitative Backtesting Chart")
# ...

# 然后启动 UI 查看
# rdagent ui --log-dir ./my_logs
```

#### 方案 B: 通过 Flask API 直接发送数据

直接向 Flask `/receive` 端点发送 JSON 数据：

```python
import requests
from datetime import datetime, timezone

data = {
    "id": "my_trace_id",
    "msg": {
        "tag": "feedback.metric",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "loop_id": 1,
        "content": {
            "result": your_metrics_df.to_json()  # IC, return, etc.
        }
    }
}
requests.post("http://localhost:19899/receive", json=data)
```

---

## 7. 配置参考

### 7.1 关键环境变量

```bash
# ===== LLM 配置 =====
export OPENAI_API_KEY="sk-..."
export CHAT_MODEL="gpt-4o"
export EMBEDDING_MODEL="text-embedding-3-small"

# ===== Qlib 执行环境 =====
export QLIB_MODEL_ENV_TYPE="docker"      # docker 或 conda
export QLIB_FACTOR_ENV_TYPE="conda"
export QLIB_DOCKER_IMAGE="local_qlib:latest"
export QLIB_DOCKER_MEM_LIMIT="200g"

# ===== Region 配置 (运行时自动设置，无需 export) =====
# QLIB_REGION=cn     # 由 CLI --region 或 Web UI 选择器自动设置
# 数据路径由 ~/rd-agent/config.json 的 regions.<region>.qlib_data_path 决定

# ===== 时间段 =====
export QLIB_MODEL_TRAIN_START="2008-01-01"
export QLIB_MODEL_TRAIN_END="2014-12-31"
export QLIB_MODEL_VALID_START="2015-01-01"
export QLIB_MODEL_VALID_END="2016-12-31"
export QLIB_MODEL_TEST_START="2017-01-01"
export QLIB_MODEL_TEST_END="2020-08-01"

# ===== 演化轮数 =====
export QLIB_MODEL_EVOLVING_N=10
export QLIB_FACTOR_EVOLVING_N=10
export QLIB_QUANT_EVOLVING_N=10

# ===== 数据路径 =====
export FACTOR_CoSTEER_DATA_FOLDER="git_ignore_folder/factor_implementation_source_data"
export FACTOR_CoSTEER_DATA_FOLDER_DEBUG="git_ignore_folder/factor_implementation_source_data_debug"

# ===== UI =====
export UI_DEFAULT_LOG_FOLDERS='["./log"]'
export UI_STATIC_PATH="./git_ignore_folder/static"
export UI_TRACE_FOLDER="./git_ignore_folder/traces"
```

### 7.2 配置类继承关系

```
ExtendedBaseSettings
    └── BasePropSetting
         ├── ModelBasePropSetting   (env_prefix="QLIB_MODEL_")
         ├── FactorBasePropSetting  (env_prefix="QLIB_FACTOR_")
         │    └── FactorFromReportPropSetting
         └── QuantBasePropSetting   (env_prefix="QLIB_QUANT_")

EnvConf
    ├── CondaConf
    │    └── QlibCondaConf  (默认环境名: rdagent4qlib)
    └── DockerConf
         └── QlibDockerConf (挂载 ~/.qlib/ 到容器)

CoSTEERSettings
    └── FactorCoSTEERSettings
         ├── data_folder: "git_ignore_folder/factor_implementation_source_data"
         └── data_folder_debug: "git_ignore_folder/factor_implementation_source_data_debug"
```

### 7.3 命令速查

```bash
# 因子挖掘
rdagent fin_factor

# 模型优化
rdagent fin_model

# 因子+模型联合优化 (Bandit 策略)
rdagent fin_quant

# 从研报提取因子
rdagent fin_factor_report --report_folder /path/to/reports

# 启动 Flask + Vue Web UI
rdagent server_ui --port 19899

# 启动 Streamlit 监控 UI
rdagent ui --log-dir ./log --port 19899

# 查看帮助
rdagent --help
```

---

## 附录: 目录结构速查

```
RD-Agent/
├── rdagent/                            # 核心代码
│   ├── app/                            # CLI 入口 & R&D 循环
│   │   ├── cli.py                      # Typer CLI
│   │   └── qlib_rd_loop/               # Qlib 相关的 3 种循环
│   ├── core/                           # 核心抽象 (Scenario, Hypothesis, Experiment)
│   ├── scenarios/qlib/                 # Qlib 场景实现
│   │   ├── experiment/
│   │   │   ├── workspace.py            # ★ qrun 执行入口
│   │   │   ├── utils.py               # ★ 数据描述 & HDF5 生成
│   │   │   └── factor_data_template/  # ★ generate.py (Qlib→HDF5)
│   │   ├── proposal/                   # 假设生成
│   │   └── developer/                  # 代码生成 & 执行
│   ├── components/coder/               # 通用代码生成组件
│   ├── log/
│   │   ├── storage.py                  # FileStorage
│   │   ├── server/app.py              # ★ Flask API
│   │   ├── ui/app.py                  # ★ Streamlit UI
│   │   ├── ui/storage.py              # ★ WebStorage (HTTP 推送)
│   │   └── ui/qlib_report_figure.py   # ★ 回测图表 (Plotly)
│   └── utils/
│       ├── env.py                      # ★ Docker/Conda 环境
│       └── qlib.py                     # ALPHA20/158, 因子验证
├── web/                                # Vue 3 前端
│   └── src/
│       ├── router/index.ts            # 路由: Home, Playground, PlaygroundPage
│       ├── views/                      # 页面
│       └── components/                 # UI 组件 (ECharts, code, feedback...)
├── docs/                               # 文档
└── requirements.txt                    # Python 依赖
```
