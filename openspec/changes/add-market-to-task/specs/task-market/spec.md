## ADDED Requirements

### Requirement: 任务创建时独立指定 market
系统 SHALL 允许在创建 qlib 类分析任务（fin_factor / fin_model / fin_quant）时显式传入 `market` 参数，与 `region` 解耦。`market` 缺省时 MUST 回退到该 region 配置中的默认 market。

#### Scenario: 显式指定 market
- **WHEN** 用户创建 fin_factor 任务并传入 `region="cn"` 和 `market="csi500"`
- **THEN** 系统使用 csi500 作为 qlib instruments（symbols 池），而非 cn region 默认的 csi300

#### Scenario: market 缺省回退 region
- **WHEN** 用户创建 fin_factor 任务只传 `region="cn"` 不传 `market`
- **THEN** 系统使用 cn region 配置中的默认 market（csi300），行为与变更前一致

#### Scenario: 非 qlib 场景不传 market
- **WHEN** 用户创建 data_science 或 general_model 任务
- **THEN** 系统不接受也不处理 market 参数（该参数对非 qlib 场景无意义）

### Requirement: market 覆盖 region 派生值
系统 MUST 在 runner 层用显式传入的 market 覆盖 region 配置派生的 market 值，注入 qlib 调用环境变量 `qlib_market`。其它 region 派生字段（如 `qlib_data_path`、`benchmark`）仍按 region 走。

#### Scenario: market 覆盖注入
- **WHEN** 任务以 `region="cn"`、`market="csi500"` 启动，factor_runner 读取环境变量
- **THEN** 注入 subprocess 的 `qlib_market` env 为 `csi500`，而 `qlib_data_path` 仍为 cn region 的数据路径

### Requirement: 任务历史显示 market
系统 SHALL 在任务 trace 元数据中持久化所用 `region` 与 `market`，并通过 `/trace` 接口返回，使历史任务可追溯所用 market。

#### Scenario: 历史任务追溯 market
- **WHEN** 用户查看已完成的 fin_factor 任务历史
- **THEN** trace 元数据中包含该任务启动时的 `region` 和 `market` 字段，前端 PlaygroundPage 展示

#### Scenario: 旧任务无 market 元数据
- **WHEN** 用户查看变更前已存在的旧任务历史
- **THEN** 系统不报错，market 字段缺失或为空，展示时降级为 region 默认 market 或留空

### Requirement: 前端 market 选择器
系统 SHALL 在 Playground 上传表单为 fin_factor / fin_model / fin_quant 场景提供 market 下拉选择控件（与 loops、duration 并列），下拉候选数据来源为进程启动时缓存的全局 market 分类（见「进程启动扫描并缓存 market 分类」Requirement）。region 切换时下拉候选刷新为该 region 对应的缓存 market 列表。region 下扫描到的 instruments 目录为空时（如 hk/us 暂无数据），下拉降级为可手输，避免阻塞创建任务。

#### Scenario: 选择 market 创建任务
- **WHEN** 用户在 Playground 创建 fin_factor 任务，region 选 cn，从 market 下拉选择 csi500，填 loops 与 duration 后提交
- **THEN** 上传请求 formdata 含 market=csi500，任务以 csi500 作为 qlib instruments 启动

#### Scenario: 切换 region 刷新 market 候选
- **WHEN** 用户在 Playground 切换 region 从 cn 到 us
- **THEN** market 下拉候选刷新为进程缓存里 us region 对应的 market 列表

#### Scenario: region 无 instruments 数据时降级手输
- **WHEN** 用户切换到 hk region，进程扫描 hk 的 instruments 目录为空
- **THEN** market 下拉降级为可手输文本框，用户可自行输入 market 字符串后提交

### Requirement: 进程启动扫描并缓存 market 分类
系统 SHALL 在后端进程启动时扫描每个已配置 region 的 `qlib_data_path` 下 `instruments` 目录，把其中所有 `.txt` 文件名（去掉 `.txt` 后缀）作为该 region 的可用 market 列表，缓存到进程内存。该缓存作为前端 market 下拉候选与 `/api/markets` 接口的唯一数据来源。运行时 `instruments` 目录变化不自动刷新（重启进程生效）。

#### Scenario: 启动时扫描 cn instruments 目录
- **WHEN** 后端进程启动，cn region 的 qlib_data_path 为 `/data/qlib_data/qlib_bin/market_daily/cn/`
- **THEN** 进程扫描 `/data/qlib_data/qlib_bin/market_daily/cn/instruments/` 下所有 `.txt`，得到 market 列表如 `["all", "csi300", "csi500", "csi800", "csi_dividend", ...]` 并缓存

#### Scenario: region 的 instruments 目录不存在或为空
- **WHEN** 后端进程启动，hk region 的 instruments 目录不存在或无 `.txt` 文件
- **THEN** 该 region 缓存为空列表，`/api/markets?region=hk` 返回空数组，前端降级为可手输

#### Scenario: 缓存进程内单例
- **WHEN** 多次调用 `/api/markets?region=cn`
- **THEN** 均从进程内存缓存读取，不重复扫描文件系统
