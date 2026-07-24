## Context

RD-Agent 的 qlib 量化训练任务（fin_factor / fin_model / fin_quant）当前通过 `region`（cn/hk/us）选择数据源，`market`（symbols 池）被 1:1 硬绑在 region 配置里。`get_region_config(region)` 返回的 `RegionInfo` 含单一 `market`，下游 factor_runner 把它注入 `qlib_market` env，YAML 模板 `{{ qlib_market }}` 替换进 qlib `instruments` 字段。

市场实际流向（已查证）：
```
main(region) → os.environ["QLIB_REGION"]
factor_runner.py:77 → ri = get_region_config(region)   # 1:1 绑定
factor_runner.py:90 → env_to_use["qlib_market"] = ri.market
conf_baseline.yaml → {{ qlib_market | default("csi300") }} → instruments
qlib → D.features(instruments=...)   # symbols 池生效
```

关键点：market→qlib 的管道（env→YAML 模板）已存在，只需在入口处打破 region→market 的 1:1 绑定。trace 历史当前完全不记录 region/market，`/trace` 与 `WebStorage._obj_to_json` 都不返回。

## Goals / Non-Goals

**Goals:**
- 创建 qlib 任务时可独立指定 `market`，与 `region` 解耦；缺省回退 region 派生值（向后兼容）。
- 一个 region 下能并发跑多个 market（环境变量隔离由 subprocess 天然保证）。
- 历史任务可查到用的哪个 market 跑的。

**Non-Goals:**
- 不改 `RegionInfo` 数据结构（market 仍是字段）。
- 不改 YAML 模板（已用 `{{ qlib_market }}`）。
- 不在本期做 market→benchmark 自动映射（benchmark 仍按 region 默认值；用户后续可在 config.json 单独配）。
- 不改非 qlib 场景（data_science / general_model / fin_factor_report 不涉及 market）。

## Decisions

### D1: 用环境变量 `QLIB_MARKET` 传递，与 `QLIB_REGION` 并列
**选择**：新增 `os.environ["QLIB_MARKET"]`，runner 读取后覆盖 region 派生值。
**替代方案**：把 market 塞进 `RDAgentTask.kwargs` 透传到 runner 构造参数 —— 需改 RDLoop 构造链多处签名，侵入大。
**理由**：现有 `QLIB_REGION` 已是 env 模式，factor_runner 已读 env；加 `QLIB_MARKET` 零结构改动，subprocess 天然隔离不同 market 并发。

### D2: market 缺省回退 region 配置
**选择**：`market = os.environ.get("QLIB_MARKET") or ri.market`。
**理由**：向后兼容；未显式传 market 时行为与现状完全一致。

### D3: 进程启动扫描 instruments 目录并缓存 market 分类
**选择**：后端进程启动时扫描每个 region 的 `qlib_data_path/instruments/*.txt`，文件名（去 `.txt`）作为该 region 可用 market 列表，缓存到进程内存单例。`/api/markets?region=xxx` 读缓存返回。前端 market 下拉候选来源即该接口。
**替代方案**：在 config.json 里手配 `markets` 列表 —— 需用户维护，易与 qlib 实际数据不一致。
**理由**：数据源单一可信（qlib 数据目录即事实），零配置；缓存避免每次请求扫盘；运行时新增 market 重启进程即生效，符合运维预期。instruments 目录为空时（如 hk/us 暂无数据）前端降级可手输。

### D5: 前端 market 控件为下拉，候选来源 `/api/markets`
**选择**：`el-select`（filterable），候选由 `/api/markets?region=xxx` 返回的缓存列表。候选为空时降级为可手输。**不**用 allow-create 全自由输入 —— 防止误填 qlib 不存在的 market。
**理由**：下拉限定在 qlib 实际有的 instruments 文件，避免用户输入不存在的 market 导致训练中途报错；候选为空降级手输兼容未下载数据的 region。

### D4: trace 元数据用 RDLoop 启动处显式 log
**选择**：在 fin_factor/fin_model/fin_quant 的 `main()` 启动后用 `logger.log_object({"region":..., "market":...}, tag="task.meta")`；`WebStorage._obj_to_json` 处理该 tag 时把 region/market 合入 trace JSON。
**替代方案**：改 `RDAgentTask` 持久化字段 —— 涉及 server/app.py 的进程管理结构。
**理由**：复用现有 FileStorage tag 机制，零存储层改动。

## Risks / Trade-offs

- **[Risk] benchmark 与 market 不匹配** → 换 csi500 但仍用 csi300 的 benchmark，回测基准错。**Mitigation**：本期文档提示用户在 config.json 同时配 benchmark；后续可加 market→benchmark 映射。
- **[Risk] qlib_data_path 不含该 market 数据** → 报错晚到训练中段。**Mitigation**：runner 启动时 log market，便于排查；非本期校验。
- **[Trade-off] env var 传递** → 单进程多 market 串行会互相覆盖 env。**Mitigation**：并发场景天然用 subprocess 隔离；串行场景同一进程内换 market 需重启进程（与现状 region 切换一致）。
