## Why

当前 qlib 训练任务中 `market`（symbols 池，如 `csi300`/`csi500`/`csi800`）被硬绑在 `region`（`cn`/`hk`/`us`）的 1:1 映射里（`rdagent/core/region_config.py:68` 的 `get_region_config(region)` 一次只返回一个 RegionInfo，含单一 `market`）。要做不同 symbols 池的训练，用户必须反复改 `~/.rd-agent/config.json` 里 region 下的 `market` 字段，且无法并发跑多个 market —— 而不同 symbols 池的训练特征本就不同，需要分别调参。这限制了量化金融实验的并行迭代效率。同时历史任务不记录 market，跑完查不到用的哪个池。

## What Changes

- **新增 `market` 独立入参**：创建 qlib 类分析任务（`fin_factor` / `fin_model` / `fin_quant`）时可显式指定 `market`，与 `region` 解耦。`market` 缺省时回退到 region 配置里的默认 market，保持向后兼容。
- **市场覆盖 region 派生值**：当 `market` 显式提供时，覆盖该 region 配置中的 `market` 字段；`benchmark` 等其它字段仍按 region 走。
- **历史任务显示 market**：任务 trace 元数据持久化 `region` 与 `market`；`/trace` 接口返回；前端 PlaygroundPage 展示该任务用的 market。
- **前端暴露 market 下拉**：Playground.vue 上传表单新增 market 下拉选择（与 loops、duration 并列），候选来自进程启动时扫描 qlib `instruments` 目录缓存的 market 分类；region 切换刷新候选；候选为空时降级可手输。
- **进程启动扫描并缓存 market 分类**：后端进程启动时扫描每个 region 的 `qlib_data_path/instruments/*.txt`，文件名（去 `.txt`）作为可用 market 列表缓存到进程内存，作为前端下拉与 `/api/markets` 接口的唯一数据来源（替代原方案在 config.json 配 `markets` 列表）。
- **BREAKING**：无。market 为可选参数，缺省走原 region 派生路径。

## Capabilities

### New Capabilities
- `task-market`: 任务创建时独立指定 qlib market（symbols 池），与 region 解耦；任务历史可追溯所用 market。

### Modified Capabilities
<!-- 无现有 spec，留空 -->

## Impact

- **后端入口**：`rdagent/app/qlib_rd_loop/{factor,model,quant}.py` 的 `main()` 签名新增 `market` 参数；新增 `QLIB_MARKET` 环境变量与 `QLIB_REGION` 并列。
- **Runner**：`rdagent/scenarios/qlib/developer/factor_runner.py:77-90` 读取 market 覆盖逻辑，注入 `qlib_market` env 供 YAML 模板替换。
- **配置层**：`rdagent/core/region_config.py` 新增进程启动扫描 `qlib_data_path/instruments/*.txt` 并缓存 market 分类的逻辑；`RegionInfo` 不变。
- **API**：`rdagent/log/server/app.py` 进程启动时扫描并缓存 market 分类；新增 `/api/markets` GET 端点读缓存返回；`/upload` 端点接受 `market` form 字段并写入 kwargs；`/trace` 端点返回 trace 元数据中的 region/market。
- **存储/日志**：`rdagent/log/ui/storage.py` 在 trace 元数据序列化时带上 region/market；RDLoop 启动处显式 log region/market。
- **前端**：`web/src/views/Playground.vue` 新增 market 下拉（候选来自 `/api/markets`）；`web/src/views/PlaygroundPage.vue` 历史视图展示 market。
- **YAML 模板**：`rdagent/scenarios/qlib/experiment/factor_template/conf_baseline.yaml` 已用 `{{ qlib_market }}`，无需改动。
