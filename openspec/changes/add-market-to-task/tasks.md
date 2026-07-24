## 1. 配置层

- [x] 1.1 在 `rdagent/core/region_config.py` 新增 `MarketCache` 单例类：`scan_region(region)` 扫描该 region 的 `qlib_data_path/instruments/*.txt`，文件名去 `.txt` 得到 market 列表；目录不存在或空返回空列表。
- [x] 1.2 新增 `scan_all_regions()` 函数：遍历 `get_available_regions()`，对每个 region 调 `scan_region`，结果存入进程内 dict 缓存 `{region: [market,...]}`。
- [x] 1.3 新增 `get_cached_markets(region)` 读缓存返回 market 列表（不扫盘）。缓存未初始化时返回空列表。

## 2. 后端入口

- [x] 2.1 `rdagent/app/qlib_rd_loop/factor.py` 的 `main()` 新增 `market: Optional[str] = None` 参数；设 `os.environ["QLIB_MARKET"] = market or ""`；启动后 `logger.log_object({"region":..., "market":...}, tag="task.meta")`。
- [x] 2.2 `rdagent/app/qlib_rd_loop/model.py` 同样加 `market` 参数 + env + task.meta log。
- [x] 2.3 `rdagent/app/qlib_rd_loop/quant.py` 同样加 `market` 参数 + env + task.meta log。

## 3. Runner 覆盖逻辑

- [x] 3.1 `rdagent/scenarios/qlib/developer/factor_runner.py:77-90` 读取 `QLIB_MARKET` env，覆盖 `ri.market`：`market = os.environ.get("QLIB_MARKET") or ri.market`；`env_to_use["qlib_market"] = market`。
- [x] 3.2 检查 model_runner / quant_runner 是否有同样的 region 读取点，若有则同样加覆盖（grep `QLIB_REGION`）。

## 4. API 端点

- [x] 4.1 `rdagent/log/server/app.py` `/upload` 端点（行 391-492）：新增 `market = request.form.get("market")`；fin_factor/fin_model/fin_quant 的 `kwargs["market"] = market`。
- [x] 4.2 `rdagent/log/server/app.py` 进程启动时（`create_app` 或模块初始化处）调 `scan_all_regions()` 初始化缓存；新增 `/api/markets` GET 端点接 `region` query，返回 `get_cached_markets(region)`。
- [x] 4.3 `/trace` 端点返回值含 trace 元数据中的 region/market（依赖 5.x 的 trace 元数据序列化）。

## 5. 存储/日志层

- [x] 5.1 `rdagent/log/ui/storage.py` `_obj_to_json` 处理 `task.meta` tag：把 region/market 合入对应 trace 的 JSON 消息。
- [x] 5.2 确认 `rdagent/log/storage.py` 的 FileStorage 对 `task.meta` tag 的 pkl 读写不丢字段；如需新增 tag 处理分支则补。
- [x] 5.3 旧任务无 task.meta 时降级：trace 返回中 market 缺失或空，不报错。

## 6. 前端

- [x] 6.1 `web/src/views/Playground.vue` 在 loops/duration 旁新增 market `el-select` 下拉（filterable），仅 fin_factor/fin_model/fin_quant 场景显示；候选为空时降级为可手输文本。
- [x] 6.2 region 切换时调 `/api/markets?region=xxx` 刷新候选；market 值持久化到 sessionStorage（key `selectedMarket`）。
- [x] 6.3 上传 formdata 增加 `market` 字段。
- [x] 6.4 `web/src/views/PlaygroundPage.vue` 历史/trace 视图展示 market 标签（与 region 并列展示）。

## 7. 验证

- [x] 7.1 启动验证：进程启动后 `/api/markets?region=cn` 返回 cn 的 instruments 文件名列表（如 `["all","csi300","csi500",...]`）；hk/us 无数据时返回空数组。
- [x] 7.2 手动验证：创建 fin_factor 任务分别用 market=csi300 与 csi500，确认 YAML 替换正确、qlib 加载对应 instruments。
- [x] 7.3 验证历史：完成任务后 `/trace` 返回含 market；PlaygroundPage 展示 market。
- [x] 7.4 回归：不传 market 时行为与变更前一致（region 默认 market）。
- [x] 7.5 验证旧任务：变更前已存在的 trace 查看不报错。
