# 自定义因子使用指南

RD-Agent 在 loop 中弹出选因子面板时，顶部有两个 tab：

- **Alpha158**：qlib 内置 158 个因子，源自 `web/src/constants/qlib.js` 的 `ALPHA158` 常量。
- **Custom**：用户自定义因子，从 `~/.rd-agent/factors.json` 读取（只读，手工维护）。

切到 Custom tab 时，前端调 `GET /custom_factors` 拉取该文件内容并渲染成可点击标签，点击即加入 configured features 列表，与 Alpha158 因子走同一条注入链路（`base_features` → `conf_baseline_factors_model.yaml` 的 `feature` 字段 → qrun 训练）。

## 1. factors.json 文件格式

路径：`~/.rd-agent/factors.json`

JSON 对象，键为因子名（英文标识符，下划线分隔），值为 qlib 表达式字符串。

```json
{
  "my_mom_20": "Ref($close, 20)/$close - 1",
  "my_vol_ratio": "Std($volume, 10)/Std($volume, 60)",
  "my_ma_cross": "Mean($close, 5)/Mean($close, 20) - 1",
  "my_high_low_corr": "Corr($high, $low, 20)",
  "my_close_to_vwap": "$close/$vwap - 1"
}
```

约束：
- 必须是 JSON 对象（`{}`），非数组、非标量。
- 因子名建议只用字母、数字、下划线，避免与 Alpha158 同名（同名时在 configured features 里会冲突）。
- 表达式必须能用 qlib 算子解析。提交后后端 `validate_qlib_features` 会校验，不合法会在面板报 `feature_validation_msg`。
- 文件不存在或为空对象 `{}` 时，Custom tab 提示 "No custom factors..."。

## 2. 可用字段（以 `$` 前缀访问）

qlib 的股票 bar 数据字段（CN/US 市场通用）：

| 字段 | 含义 |
|------|------|
| `$open` | 开盘价 |
| `$close` | 收盘价 |
| `$high` | 最高价 |
| `$low` | 最低价 |
| `$volume` | 成交量（股） |
| `$money` | 成交额（元） |
| `$vwap` | 成交量加权均价 |
| `$factor` | 复权因子 |
| `$change` | 涨跌幅 |

表达式里直接写 `$close`、`$open` 即可，qlib 会自动按 instrument + 日期对齐。

## 3. 支持的算子

算子分三类：**滚动统计（Rolling）**、**双序列滚动（Pair Rolling）**、**逐元素与逻辑（Element-wise & Logic）**。下表列出 qlib 0.9.x 注册可用、在因子表达式中可直接调用的算子。

### 3.1 滚动统计算子（单序列，窗口 N）

形如 `Op($field, N)`，对过去 N 个交易日（含当日）的 `$field` 序列做统计。

| 算子 | 签名 | 含义 |
|------|------|------|
| `Ref` | `Ref(feature, N)` | 取 N 天前的值（`Ref($close, 5)` = 5 个交易日前的收盘价）。N 为正向前看，负向后看。 |
| `Mean` | `Mean(feature, N)` | N 日均值（MA） |
| `Sum` | `Sum(feature, N)` | N 日累加和 |
| `Std` | `Std(feature, N)` | N 日标准差 |
| `Var` | `Var(feature, N)` | N 日方差 |
| `Max` | `Max(feature, N)` | N 日最大值 |
| `Min` | `Min(feature, N)` | N 日最小值 |
| `Med` | `Med(feature, N)` | N 日中位数 |
| `Mad` | `Mad(feature, N)` | N 日平均绝对偏差（Mean Absolute Deviation） |
| `Rank` | `Rank(feature, N)` | N 日内当前值的百分位排名（0~1） |
| `Count` | `Count(feature, N)` | N 日内满足（非 NaN）的计数 |
| `Delta` | `Delta(feature, N)` | 当前值减 N 天前的值：`feature - Ref(feature, N)` |
| `Slope` | `Slope(feature, N)` | N 日线性回归斜率 |
| `Rsquare` | `Rsquare(feature, N)` | N 日线性回归的 R² |
| `Resi` | `Resi(feature, N)` | N 日线性回归残差（当前值与拟合线的差） |
| `WMA` | `WMA(feature, N)` | 加权移动平均（近期权重高） |
| `EMA` | `EMA(feature, N)` | 指数移动平均 |
| `Quantile` | `Quantile(feature, N, qscore)` | N 日内分位数，`qscore` 为分位点（如 0.25/0.5/0.75） |
| `Skew` | `Skew(feature, N)` | N 日偏度 |
| `Kurt` | `Kurt(feature, N)` | N 日峰度 |
| `IdxMax` | `IdxMax(feature, N)` | N 日内最大值出现的位置（距今天数） |
| `IdxMin` | `IdxMin(feature, N)` | N 日内最小值出现的位置（距今天数） |

### 3.2 双序列滚动算子（Pair Rolling）

形如 `Op(feature_left, feature_right, N)`，对两个序列在过去 N 日内做联合统计。

| 算子 | 签名 | 含义 |
|------|------|------|
| `Corr` | `Corr(left, right, N)` | N 日皮尔逊相关系数 |
| `Cov` | `Cov(left, right, N)` | N 日协方差 |

### 3.3 逐元素算子与逻辑算子

逐元素作用于当日值（不滚动），或比较两个序列当日值。

**算术与数学**：

| 算子 | 签名 | 含义 |
|------|------|------|
| `Add` | `Add(left, right)` | 左 + 右 |
| `Sub` | `Sub(left, right)` | 左 - 右 |
| `Mul` | `Mul(left, right)` | 左 × 右 |
| `Div` | `Div(left, right)` | 左 ÷ 右 |
| `Power` | `Power(left, right)` | 左的右次幂 |
| `Log` | `Log(feature)` | 自然对数 ln |
| `Abs` | `Abs(feature)` | 绝对值 |
| `Sign` | `Sign(feature)` | 符号函数（-1/0/1） |

**比较**：

| 算子 | 签名 | 含义 |
|------|------|------|
| `Gt` | `Gt(left, right)` | 左 > 右 |
| `Ge` | `Ge(left, right)` | 左 ≥ 右 |
| `Lt` | `Lt(left, right)` | 左 < 右 |
| `Le` | `Le(left, right)` | 左 ≤ 右 |
| `Eq` | `Eq(left, right)` | 左 = 右 |
| `Ne` | `Ne(left, right)` | 左 ≠ 右 |
| `Greater` | `Greater(left, right)` | 取较大值（逐元素 max） |
| `Less` | `Less(left, right)` | 取较小值（逐元素 min） |

**逻辑**：

| 算子 | 签名 | 含义 |
|------|------|------|
| `And` | `And(left, right)` | 逻辑与 |
| `Or` | `Or(left, right)` | 逻辑或 |
| `Not` | `Not(feature)` | 逻辑非 |
| `If` | `If(cond, left, right)` | 条件 cond 为真取 left，否则取 right |

**其他**：

| 算子 | 签名 | 含义 |
|------|------|------|
| `Mask` | `Mask(feature, instrument)` | 用指定 instrument 的值遮蔽当前 instrument（跨标的引用，少用） |
| `ChangeInstrument` | `ChangeInstrument(instrument, feature)` | 切换到指定 instrument 取值（跨标的引用，少用） |

## 4. 表达式语法要点

- **运算符优先级**：可直接用 `+ - * /`、比较符 `> < >= <= == !=`、逻辑符 `& | !`，qlib 会自动转成对应的 `Add`/`Sub`/`Gt`/`And` 等算子。例如 `$close > $open` 等价于 `Gt($close, $open)`。
- **混合写法**：`Mean($close, 5)/$close - 1` 这种混合表达式合法——`Mean($close, 5)` 返回序列，`/$close` 逐元素除，`- 1` 逐元素减。
- **常量**：数字直接写，如 `1`、`1e-12`（Alpha158 里用 `+1e-12` 防除零）。
- **括号**：可任意嵌套，`($high - $low)/$open` 需括号保证先减后除。
- **NaN 处理**：qlib 算子通常自动跳 NaN，但除法遇 0 仍可能产出 inf，建议加 `+1e-12` 兜底（参考 Alpha158 的 `KMID2` 等）。

## 5. 常见因子写法示例

```json
{
  "my_km": "($close - $open)/$open",
  "my_range": "($high - $low)/$close",
  "my_roc5": "Ref($close, 5)/$close - 1",
  "my_ma5_ratio": "Mean($close, 5)/$close",
  "my_vol_std_ratio": "Std($volume, 10)/Std($volume, 60)",
  "my_ma_cross": "Mean($close, 5)/Mean($close, 20) - 1",
  "my_momentum_20": "Ref($close, 20)/Ref($close, 60) - 1",
  "my_high_low_corr_20": "Corr($high, $low, 20)",
  "my_close_vwap_dev": "$close/$vwap - 1",
  "my_rsi_like": "Mean(Greater($close - Ref($close, 1), 0), 14)/Mean(Abs($close - Ref($close, 1)), 14)",
  "my_boll_pos": "($close - Mean($close, 20))/(Std($close, 20) + 1e-12)",
  "my_rank_close_20": "Rank($close, 20)"
}
```

## 6. 验证与排错

提交 configured features 后，后端 `validate_qlib_features`（`rdagent/utils/qlib.py:320`）会把表达式送进 qlib 真实计算一次，捕获异常。常见错误：

| 报错 | 原因 |
|------|------|
| `name 'XxxOp' is not defined` | 算子名拼错或不在本表的注册算子里 |
| `operands could not be broadcast together` | 两个序列长度不一致（通常是 `Ref` 窗口 N 与另一个序列不匹配，确认两边都加了合适的 `Ref`/`Mean`） |
| `division by zero` | 除数为 0，加 `+1e-12` 兜底 |
| `KeyError: '$xxx'` | 字段名拼错，确认用本表第 2 节列出的 `$close`/`$open` 等标准字段 |

错误信息会回显到面板的 `feature_validation_msg` 区域，定位到具体因子名后回 `factors.json` 修正即可。

## 7. 参考来源

- 算子实现：qlib 源码 `qlib/data/ops.py`（本地 `python -c "import qlib.data.ops as o; print(o.__file__)"` 可定位）。
- Alpha158 默认因子：`web/src/constants/qlib.js` 的 `ALPHA158` 对象（158 个表达式可直接参考写法）。
- 注入链路：`rdagent/components/workflow/rd_loop.py:75` `_init_base_features` → `rdagent/scenarios/qlib/developer/model_runner.py:83` 注入 yaml → qrun 训练。
