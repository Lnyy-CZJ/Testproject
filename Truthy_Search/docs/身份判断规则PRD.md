# 身份判断规则 PRD

## 1. 文档目的

本文档固化 Search Tool 当前已上线的候选人身份判断规则，供查看报告、人工复核与后续规则变更时使用。

- 文档版本：v1.1（现行规则快照）
- 整理日期：2026-08-10
- 当前生效字段 Schema：`field-schema-20260810-074857-5a7530`
- 规则实现位置：`analysis_service.py` 中 `_candidate_identity_rule`
- 适用范围：完成 Candidate Detail 的候选人；每个候选人先判定，再汇总为 Query 级结果。

本文描述的是**当前实际运行逻辑**，不代表推荐的未来规则方案。

## 2. 目标与边界

### 2.1 目标

根据基准人物与接口返回候选人的强身份线索，将候选人归为：

- `HIT`：确认是基准人物；
- `NOT_HIT`：确认不是基准人物；
- `SUSPECTED`：证据不足，身份存疑；
- `PENDING_REVIEW`：因详情失败或缺少基准数据，未能自动完成判断，等待人工处理。

同一 Query 可以存在多个 `HIT`。系统会从中选出唯一的“主命中”，用于 Query 级命中率、命中资料完整度和准确度等正式指标。

### 2.2 当前不参与自动身份终判的字段

以下信息可能展示在候选人详情、Excel 或报告中，但**不会参与当前自动身份判断**：

- 候选排名、`rank_score`、接口的 `is_top_result` / `is_best_match`；
- 全名、年龄、教育、工作、地址、简介等 Profile / Summary 字段；
- Insights、网页链接、照片来源或照片真实性；
- PDL 是否调用、模型置信度、第三方 Provider 及成本信息。

因此，正确姓名、职业资料高度一致或排名第一，不能单独让系统自动判为 `HIT`。

## 3. 当前生效的身份证据字段

当前 Schema 中已启用且 `identity_enabled=true` 的字段仅有以下两项：

| 证据类别 | 字段键 | 数据来源 | 处理方式 | 用途 |
|---|---|---|---|---|
| Social 链接 | `social_urls` | `ui_sections.social.data.profiles[*].url` | URL 规范化后做集合比对 | Social 强绑定、同平台冲突识别 |
| 照片身份相似度 | `photos_identity_match_rate` | `ui_sections.photos.data.identity_match_rate` | 统一转成 0–100 分 | Social 无结论时的兜底判断 |

说明：代码层面允许将 `summary_social_links` 配置为身份字段，但它**不在当前生效 Schema 的身份字段中**，因此目前不参与自动身份判断。Schema 变更只影响之后新建的处理记录；历史处理记录使用各自保存的 Schema 快照。

## 4. 数据预处理规则

### 4.1 Social URL 规范化

进入比对前，Social URL 按以下规则规范化：

- 仅接受 `http` / `https` 且包含有效主机名的 URL；
- 移除 `www.`；
- `x.com` 统一为 `twitter.com`，`fb.com` 统一为 `facebook.com`；
- 移除末尾 `/` 和 `#fragment`；
- 移除 `utm_*`、`fbclid`、`gclid`、`mc_cid`、`mc_eid` 等追踪参数；
- Twitter/X、Facebook、Instagram、LinkedIn、TikTok 的账号路径不区分大小写；
- 其余平台保留路径大小写与有效查询参数，避免擅自改变账号语义。

`summary_social_links` 若未来启用，可接受 URL 字符串，或 `{ "platform": "...", "url": "..." }` 对象；缺失 `url` 的对象不参与比对。

若任一参与身份判断的 Social URL 格式非法，整组 Social 证据会被视为“不可比较”，并在证据中写入 `social_rule_error`，随后继续尝试照片规则；不会抛出导致整个 Process 失败的异常。

### 4.2 照片相似度规范化

`photos_identity_match_rate` 解析规则如下：

- `0–1` 的数值会乘以 100，例如 `0.8` 视为 `80`；
- `0–100` 的数值直接使用；
- 非数值、布尔值、NaN、无穷大或超出范围的值视为缺失；
- 缺失、`not_performed` 等状态本身不是“照片不匹配”。是否被当作缺失或 `0`，取决于接口最终写入该字段的值。

## 5. 自动身份判断规则

### 5.1 判定优先级

规则按下表由上到下执行，命中第一条后立即结束：

| 优先级 | 条件 | 结果 | 原因码 | 说明 |
|---:|---|---|---|---|
| 1 | 基准 Social URL 与返回 Social URL 的规范化集合存在交集 | `HIT` | `SOCIAL_MATCH` | 任意一条完全一致的规范化 URL 即可命中；同平台其他账号仅作为证据记录，不否决命中 |
| 2 | 不存在 Social 精确命中，且返回 Social 中存在与任一基准 URL **同平台但 URL 不同**的链接 | `NOT_HIT` | `SOCIAL_CONFLICT` | 只在没有任何精确账号绑定时，才将同平台不同账号视为冲突 |
| 3 | 无 Social 冲突、无 Social 命中，且照片相似度 `>= 80` | `HIT` | `PHOTO_MATCH` | 照片作为 Social 无结论时的兜底强证据 |
| 4 | 返回 Social URL 为空，且照片相似度缺失 | `SUSPECTED` | `NO_STRONG_FIELD` | 没有可用于自动终判的强证据 |
| 5 | 照片相似度存在且 `< 80` | `NOT_HIT` | `PHOTO_BELOW_THRESHOLD` | 不论基准 Social 是否配置，只要未被前面规则终止即适用 |
| 6 | 其他情况 | `NOT_HIT` | `NO_STRONG_FIELD` | 例如：仅返回了无法与基准交集匹配的跨平台 Social URL，且没有有效照片分数 |

### 5.2 Social 冲突的精确定义

Social 冲突不是“任意返回链接不在基准中”，而是同时满足：

1. 返回 URL 不在基准 URL 的规范化集合中；且
2. 返回 URL 与任一基准 URL 属于同一社交平台。

当前平台映射包含：

| URL 域名 | 比对平台 |
|---|---|
| `x.com`、`twitter.com` | `twitter` |
| `facebook.com`、`fb.com` | `facebook` |
| `instagram.com` | `instagram` |
| `linkedin.com` | `linkedin` |
| `tiktok.com` | `tiktok` |
| `youtube.com`、`youtu.be` | `youtube` |
| 其他域名 | 以规范化后的主机名作为平台 |

例如，基准中有 `twitter.com/realbencarson`，返回中同时有 `twitter.com/realbencarson` 与 `twitter.com/secretarycarson`：前者是精确匹配，后者会记录为同平台冲突。按照当前优先级，结果为 `HIT / SOCIAL_MATCH`。

## 6. 前置条件与自动判定来源

候选人处理时按以下顺序决定是否运行自动规则：

| 前置情况 | 候选人结果 | `classification_source` | 是否已最终复核 |
|---|---|---|---|
| Candidate Detail 失败 | `PENDING_REVIEW / NO_STRONG_FIELD`，证据为详情错误 | `SUGGESTED` | 否 |
| 未找到该 Query 对应的基准人物字段 | `PENDING_REVIEW / NO_STRONG_FIELD`，证据为缺少基准数据 | `SUGGESTED` | 否 |
| Detail 成功且基准数据存在 | 执行第 5 节自动规则 | `RULE` | 是 |

自动规则产生的 `HIT`、`NOT_HIT`、`SUSPECTED` 都会立即写入复核时间，属于规则终判；`PENDING_REVIEW` 不属于终判。

每条自动规则会将以下 JSON 证据保存至 `reviews.evidence`：

```json
{
  "matched_social_urls": ["规范化后相同的 URL"],
  "conflicting_social_urls": ["同平台但不同的返回 URL"],
  "photo_identity_match_rate": 80.0,
  "social_rule_error": null
}
```

## 7. Query 级身份状态与主命中

### 7.1 Query 身份状态

| 状态 | 判定条件 | 含义 |
|---|---|---|
| `HIT_CONFIRMED` | 存在最终 `HIT` 且被选为主命中 | 已确认找到了目标人物 |
| `NO_HIT_CONFIRMED` | 有详情成功的候选人，且没有待复核候选人，也没有主命中 | 已完成判断但未命中目标人物；可能包含 `NOT_HIT` 或 `SUSPECTED` |
| `NO_CANDIDATES` | 没有候选人 | 检索未返回可判断对象 |
| `PENDING` | 其他情况 | 仍有候选人待人工归类或详情未完成 |

### 7.2 主命中选择

若同一 Query 有多个最终 `HIT`，全部保留为候选人级 `HIT`，但只选择一个 `is_primary_hit=true` 进入 Query/整体正式指标。选择顺序固定为：

1. `rank_score` 高者优先；
2. `rank_score` 相同时，`candidate_rank` 小者优先；
3. 仍相同时，候选人内部主键字典序小者优先。

## 8. 人工复核与覆写

人工可在候选人详情页或 Query 身份归类页，将候选人改为 `HIT`、`NOT_HIT` 或 `SUSPECTED`，并使用以下原因码：

| 原因码 | 使用场景 |
|---|---|
| `SOCIAL_MATCH` | Social 链接可证明同一人 |
| `SOCIAL_CONFLICT` | Social 链接可证明不是同一人 |
| `PHOTO_MATCH` | 照片相似度或人工照片核验支持命中 |
| `PHOTO_BELOW_THRESHOLD` | 照片相似度低于阈值或人工照片核验不支持命中 |
| `NO_STRONG_FIELD` | 没有足够强的自动证据 |
| `MANUAL` | 人工依据其他可说明证据作出判断 |

人工保存后：

- `classification_source` 改为 `MANUAL`；
- 可填写证据、复核人和复核说明；
- 同 Query 的主命中会按第 7.2 节重新计算；
- 关联的已生成报告会标记为 `STALE`，需要重新生成。

限制：Candidate Detail 失败的候选人不能被人工直接标为 `HIT`。在“确认无命中”时，所有详情成功候选人都必须明确为 `NOT_HIT` 或 `SUSPECTED`。

## 9. 当前规则的已知边界

以下是当前实现的客观边界，供报告解读与后续迭代参考：

1. **精确链接命中优先。** 返回资料中只要包含一条基准精确 Social URL，即会判为 `HIT`；同平台其他账号不会降级或否决该结论。因此，接口错误聚合了他人账号时可能造成假阳性，需要在候选详情中查看证据列表。
2. **照片未执行与照片低分需区分解读。** 规则只读取数值字段；接口把未执行写成空值时通常会落入证据不足，把未执行写成 `0` 时会落入照片低于阈值。
3. **Profile 一致不能自动纠偏。** 姓名、职业、教育、年龄等未纳入身份规则，因此无法抵消没有精确 Social 命中的冲突或照片低分。
4. **基准 Social 不完整会影响结论。** 缺少基准 URL 时，无法形成 Social 命中，也可能无法识别同平台冲突。

## 10. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.1 | 2026-08-10 | 精确 Social URL 命中优先；同平台其他账号不再否决 `HIT` |
| v1.0 | 2026-08-10 | 按当前生效 Schema 与运行代码整理身份判断规则快照 |
