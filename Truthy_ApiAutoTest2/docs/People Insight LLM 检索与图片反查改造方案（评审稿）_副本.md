# People Insight LLM 检索与图片反查改造方案（评审稿）



本文用于评审 `tool-service` 在正式上线前完成 LLM 人物检索、图片反查与自建数据能力的整体改造。方案以当前 `main` 分支 `21ba86b` 为代码基线，尽量保持客户端已经联调过的接口结构、任务状态机和 `SearchProviderRepo` 不变。



## 1\. 评审结论



本次改造包含两条必须完整交付的工作线，不是主功能与可选功能的关系：



|工作线|内容|实施优先级|上线要求|
|---|---|---|---|
|A\. LLM 人物检索|LLM 主检索、质量门、PDL fallback、多 backend、缓存、人物库和调用观测|第一优先|必须完成并通过验收|
|B\. 图片反查与身份图片证据|反向搜图、社交资料与头像提取、跨平台人脸比对、图片证据聚合|第二优先|必须完成并通过验收|



“LLM 优先”只表示开发顺序和资源优先级，不表示图片工作延期、降级或不上线。两条工作线可以在共享接口稳定后并行开发，最终一起进入完整回归和上线验收。



配置开关只用于开发联调、故障隔离和紧急熔断，不用于缩减正式交付范围。正式上线目标状态为：



```Plain Text
LLM People Search           enabled
Reverse Image Search       enabled
Social Profile Extraction  enabled
Face Comparison            enabled
Evidence Aggregation       enabled
```



整体策略不是让大模型自由循环，而是使用一个受约束的 Search Agent：People Search 使用线性主工具与 fallback；图片和社交证据使用有前置条件、去重和预算限制的工具队列。



## 2\. 目标与非目标



### 2\.1 目标



- 在不新增客户端主流程的前提下完成 LLM 人物搜索接入。

- LLM 找到可用候选后立即停止，不再默认调用 PDL 确认。

- LLM 无可用候选、失败或超时时，使用 PDL fallback；Pipl 保留替换入口但默认不调用。

- 用户提交图片时始终执行图片反查，不依赖姓名或社交链接搜索成功。

- 从社交 URL 中获取公开头像、简介、个人网站、邮箱和关联社交账号。

- 比较用户照片与跨平台头像，形成可追溯的人脸相似证据。

- 区分“图片公开出现”“人脸相似”“账号属于候选人”和“疑似盗图”四种不同语义。

- 将查询结果、工具观察、人物实体和任务证据分别缓存或持久化，减少第三方重复调用。

- 支持多个 LLM backend 和可替换的图片、社交、人脸 provider。

- 保留原始响应、来源、模型版本、策略版本、成本和完整调用链。

- 两条工作线均在正式上线前完成测试和验收。

    

### 2\.2 非目标



- 不实现可以无限规划和无限调用工具的通用自治 Agent。

- 不新增“打开详情、购买报告或要求 HIGH 时再调用 PDL”等当前不存在的业务流程。

- 不把 PDL、Pipl 或另一个 LLM 当作唯一真值。

- 不使用姓名相似度自动合并人物。

- 不建设可跨用户检索的人脸库，不保存可用于人脸检索的 embedding。

- 不让 LLM 直接判断两张脸是否相同、照片是否真实或是否盗图。

- P0 不引入向量数据库；先使用 MySQL 强标识索引和版本化缓存。

- 不长期维护 legacy 与 Agent 两套 provider 编排；稳定后删除 legacy 编排。

    

## 3\. 当前代码现状



本节区分代码能力、仓库默认配置和实际运行配置。前两项来自当前 `main`；发布前仍需核对 staging/production 的实际环境变量和配置中心覆盖。



### 3\.1 LLM 与 People Search



当前代码已经具备：



- 统一 `SearchProviderRepo`，输入 `SearchProviderRequest`，输出 `SearchProviderResult`。

- `FULL_NAME`、`SOCIAL_LINK` 和 `PHOTO` query type 路由。

- LLM provider 的 OpenAI\-compatible chat\-completions 调用和多 backend 顺序故障转移。

- PDL、Pipl、公共人物本地/远程查询和 people aggregate。

- Worker 外层的 `provider_result_cache` 正负缓存和 provider request 记录。

    

当前主要问题：



- `LLMPrimaryPeopleSearchProviderRepo` 在确认开关启用时，即使 LLM 已找到结果也会继续调用 PDL/Pipl confirmer。

- `AggregateSearchProviderRepo` 会顺序执行全部已启用 provider，没有成功即停。

- `llmReportHasResults` 只要 profiles、social accounts、related info 或 evidence 任意非空就认为 Found，伪造链接或无法归属的 evidence 也可能提前停止。

- LLM provider 的一次逻辑调用内部可能尝试多个 backend，但 Worker 只记录最外层 provider 调用。

- 当前 LLM 请求没有显式网页搜索工具参数，是否具备实时检索能力取决于 MaaS backend，必须实测。

    

### 3\.2 图片与社交证据



当前代码已经具备：



- `media_asset_id` 上传、COS 存储、类型和大小校验。

- SearchAPI Google Lens、Google Vision Web Detection、TinEye 三个反向搜图 adapter。

- 反向搜图证据进入报告和详情页的基础结构。

- AddReportPhotos 对新增图片逐张执行 provider 的独立入口。

    

当前主要问题：



- `SearchTaskWorker.runSearchProviders()` 只有在 FULL\_NAME 主查询成功后才追加 supporting PHOTO；SOCIAL\_LINK \+ PHOTO 或 People no\-result 会漏掉图片。

- `media_assets` 没有内容 SHA\-256 或感知哈希，同一图片重新上传后无法稳定复用缓存。

- `identity_match_rate` 固定为 `0`，`match_photos` 固定为空，没有跨平台人脸比较实现。

- SOCIAL\_LINK 当前主要交给 PDL/LLM 查询，后端没有通用的页面资料提取、头像获取、简介解析和关联账号发现工具。

- 反向搜图只能说明图片在哪里出现过，不能单独判断图片属于谁或是否被盗用。

- 在线搜索未发现公开来源时仍可能被映射为 `authentic`，该语义过强。

- `authenticity_photos[].source_url` 每张图片只能表达一个代表来源，其他来源没有完整暴露给客户端。

    

### 3\.3 仓库默认配置



当前 checked\-in staging/production 配置为：



- PDL 默认启用。

- LLM Search 默认关闭。

- Lens、Google Vision、TinEye 默认关闭。

- staging 默认启用 public figure，production 默认关闭。

    

这些是仓库默认值，不代表部署环境的最终状态。上线验收必须检查运行中 Worker 的有效配置，并走真实 API 链路验证。



## 4\. 总体边界



### 4\.1 Worker 与 Agent 的职责



`SearchTaskWorker` 继续负责：



- Kafka 事件和任务状态。

- 初始 clues 解析。

- Final Query Cache 的读写。

- AddReportPhotos 多图片入口。

- 最终结果装配、报告持久化和客户端返回。

    

Search Agent 负责：



- 根据全部初始 clues 构建任务上下文。

- People provider 主工具、fallback 和质量门。

- 图片、社交资料和人脸工具的有限调度。

- 工具级超时、熔断、预算和调用记录。

- 来源校验、证据聚合、实体解析和风险规则。

    

Search Agent 继续实现现有 `SearchProviderRepo`。`SearchProviderRequest.Clues` 已能携带姓名、社交链接和图片等初始信息，因此不需要修改客户端请求或公开 provider 接口。



### 4\.2 两条工作线的关系

- People Search 和图片反查独立启动，互不作为执行前提。

- 有用户图片就执行图片工作线，即使 LLM、PDL 或姓名搜索无结果。

- LLM 搜索失败不能阻止图片反查返回结果。

- 图片 provider 或人脸 provider 失败不能阻止 People Search 返回候选。

- 两条工作线最终在 Evidence Aggregator 汇合，生成同一份 `SearchReport`。

- LLM 可以使用图片工作线产生的已验证线索进行候选排序，但不能把图片工具结论改写为模型自报结论。

    

### 4\.3 总体架构

```mermaid
flowchart LR
    A[SearchTaskWorker<br/>任务 初始 clues 最终缓存] --> B{Final Query Cache}
    B -->|hit| Z[Report Persistence and Existing API]
    B -->|miss| C[SearchAgent Context<br/>姓名 URL 图片 位置]

    C --> P0[People Search Workstream]
    P0 --> P1{Entity Exact Lookup}
    P1 -->|hit| PA[People Candidates]
    P1 -->|miss| P2[LLM Search]
    P2 --> P3{Usable Quality Gate}
    P3 -->|usable| PA
    P3 -->|fallback reason| P4[PDL Fallback]
    P4 --> PA

    C --> I0[Image Reverse Workstream]
    I0 --> I1[Social Profile Extraction]
    I0 --> I2[User Images]
    I1 --> I3[Image Materializer]
    I2 --> I4[Reverse Image Search]
    I3 --> I4
    I3 --> I5[Face Comparison]

    PA --> E[Evidence Aggregator and Entity Resolver]
    PA -->|new social URLs| I1
    I1 --> E
    I4 --> E
    I5 --> E
    E --> Q[Quality and Risk Gate]
    Q --> S[Entity Evidence Tool Records]
    S --> R[SearchProviderResult]
    R --> W[SearchTaskWorker Finalize]
    W --> Z```

这里的 Agent 是受约束的执行器，不要求使用 Reasoning LLM 生成任意 action plan。P0 使用 Go 代码和配置生成确定性计划。



## 5\. 工作线 A：LLM 人物检索

### 5\.1 FULL\_NAME

```Plain Text
Worker Final Query Cache
-> Entity Store exact mapping（启用后）
-> Public Figure Local（符合现有 eligibility 时）
-> LLM Search
-> Usable Quality Gate
-> PDL fallback（仅无可用候选或失败）
-> Public Figure Remote（本地未知且 people route 无结果时）
-> 返回候选
```



规则：

- LLM 候选通过 usable gate 后立即停止，不调用 PDL。

- LLM\-only 结果最高 `MEDIUM`，并携带未被结构化 people provider 确认的说明。

- PDL 只作为 fallback 数据源，不作为 LLM 正确率真值。

- Pipl 默认不进入执行计划，但保留可替换 PDL 的 adapter 和配置入口。

- Public Figure 继续是 FULL\_NAME 内部包装逻辑，不新增 `PUBLIC_FIGURE` query type。

- 远程 Wikidata/Wikipedia 不对普通姓名默认前置调用。

    

### 5\.2 SOCIAL\_LINK



```Plain Text
Worker Final Query Cache
-> canonical URL / platform + handle 精确索引
-> LLM Search
-> Usable Quality Gate
-> PDL fallback（仅无可用候选或失败）
-> 返回候选
```



社交链接属于强标识。URL 规范化需要处理 scheme、`www`、尾部 `/`、跟踪参数和平台别名，但不能删除影响账号身份的 path/query。



### 5\.3 Usable Quality Gate



LLM 返回后必须先标准化和检查，不能以“JSON 可解析且任意数组非空”作为成功。



候选至少满足：



1. 具有可展示和识别的基本身份字段，不能只有一段无结构文本。

2. 至少存在一个格式有效、能归属到候选的公开来源或强标识。

3. 查询中的 social handle、公司、地区等强约束没有与候选明确冲突。

4. 同名人物、无法归属的链接、孤立 evidence 或候选之间无法消歧时，不视为可用命中。

    

允许 PDL fallback 的原因：



```Plain Text
no_result
no_usable_candidate
source_unsupported
identity_ambiguous
invalid_candidate
timeout
rate_limited
provider_unavailable
invalid_response
```



### 5\.4 多 LLM Backend

LLM 通过 backend 列表配置，不把业务代码绑定到 endpoint、模型或供应商：

```Go
type LLMBackendConfig struct {
    Name                string
    Enabled             bool
    Priority            int
    Endpoint            string
    Model               string
    APIKeySecretRef     string
    Timeout             time.Duration
    MaxAttempts         int
    SupportsWebSearch   bool
}
```

初始 backend 使用当前配置的 Tencent Cloud MaaS compatible endpoint 和 `deepseek-v4-flash-202605`。API key 只通过 Secret/环境变量注入，不写入代码、文档、数据库或日志。

多 backend 规则：

- 按优先级执行，只有 retryable error 才切换 backend。

- 业务 no\-result 不默认切换另一个 LLM，避免重复成本和不同模型扩散错误。

- 每次 backend attempt 都单独计数、计费和记录。

- 支持随时增加、禁用或调整 backend 顺序。

- endpoint、model、prompt 或 schema 变化必须生成新的 cache/policy version。

    

## 6\. 工作线 B：图片反查与身份图片证据

本工作线包含三项完整能力：

1. Reverse Image Search：查询图片在哪些公开网页出现。

2. Social Profile Extraction：从社交 URL 获取头像、简介和关联账号。

3. Face Comparison：比较用户照片和跨平台头像是否相似。

三项能力共同支持图片风险判断，但必须保持各自语义，不合并成一个直接输出“真假”的模型调用。



### 6\.1 触发规则

- 用户提交的每张图片都是初始事实，始终进入图片工作线。

- 用户提交 SOCIAL\_LINK 时执行 Social Profile Extraction，不依赖 People Search 命中。

- People Search 新发现 canonical social URL 时，可以进入社交资料工具队列。

- Social Profile 新发现头像时，物化为内部 `ImageRef` 后进入反向搜图和人脸比较。

- 没有候选人物时，反向搜图发现的姓名、账号或来源仍可作为候选线索返回。

- AddReportPhotos 继续由 Worker 投递新图片，但进入相同图片工具和证据规则。

### 6\.2 Social Profile Extraction

输入：canonical social URL，或明确的平台 \+ handle。

标准化输出：

- 平台、canonical URL、handle 和页面存在状态。

- 公开姓名、头像、简介、公司、学校和地区。

- 公开邮箱、个人网站和简介中明确关联的其他社交 URL。

- provider、来源 URL、获取时间和原始响应引用。

    

规则：

- 定义统一 adapter，P0 选择一家商业社交数据服务作为主 provider，不把业务逻辑绑定到具体供应商。

- 页面存在只表示 `EXISTS`，不能证明该页面属于目标人物。

- 账号归属至少需要姓名、头像、公司、地区、用户名复用或个人网站直链等额外支持信号。

- LLM 可以提取简介中的候选 URL，但必须经过 URL 和来源验证。

- 新账号先 canonicalize 和去重，再进入受限工具队列。

### 6\.3 Image Materializer

用户上传图片继续使用现有 `media_asset_id -> COS object`。社交工具返回的头像通常是外部 URL，必须转换成统一内部 `ImageRef`：



- 只允许 HTTPS，执行 DNS/IP 重绑定防护，拒绝内网和 metadata endpoint。

- 限制 content type、文件大小、像素尺寸、重定向次数和超时。

- 临时保存到任务 scope 的受控对象存储。

- 保存原始 URL、provider、candidate、observed time 和 expire time。

- 计算 SHA\-256；按需要异步计算 pHash。

- 相同内容只物化一次，过期和删除遵守数据授权要求。

Face Comparison 和 Reverse Image Search 接收 `ImageRef`，不直接接收任意互联网 URL。



### 6\.4 Reverse Image Search

```Plain Text
Image exact cache（SHA-256）
-> Similar image candidate cache（pHash，仅召回）
-> Google Lens primary
-> Google Vision fallback（无可用来源或 provider 失败）
-> TinEye（同图、素材图或来源时间分析场景）
-> 保存全部有效公开来源
```



标准化状态：



- `FOUND_ONLINE`：至少一个可访问、可归属到该图片的公开来源。

- `NO_PUBLIC_MATCH`：provider 成功执行，但没有发现公开匹配。

- `UNKNOWN`：provider 未配置、失败、超时、响应不可用或证据无法归属。

    

规则：



- 不默认同时调用 Lens、Vision、TinEye。

- `FOUND_ONLINE` 只表示图片在公开网页出现过，不证明人物身份、原始来源或盗图。

- `NO_PUBLIC_MATCH` 不能映射为 `authentic`，搜索不到不等于照片真实。

- pHash 只用于近似图片召回，不能直接作为身份确认或缓存等价依据。

- 内部保存全部来源，不只保留第一条。

    

### 6\.5 Face Comparison



典型比较：



```Plain Text
用户照片 <-> LinkedIn 头像
用户照片 <-> Instagram 头像
LinkedIn 头像 <-> Instagram 头像
```



标准化输出：



- `similarity_score`。

- `face_detected`、图片质量和失败原因。

- `MATCH` / `POSSIBLE_MATCH` / `MISMATCH` / `INSUFFICIENT_QUALITY`。

- 左右图片来源、image reference、provider/model/threshold version。

    

规则：



- 使用可替换的专用 Face Comparison provider，不让 LLM 判断人脸。

- 只做任务内一对一比较，不建立人脸检索库。

- 不同 provider 的分数不能直接比较，阈值必须版本化并用标注样本校准。

- 质量不足或 provider 失败只表示缺少证据，不表示人物不一致。

- `MATCH` 是身份支持证据之一，不能覆盖姓名、账号和来源的明确冲突。

    

### 6\.6 图片风险结论



- `LIKELY_SAME_PERSON`：人脸、姓名、账号或资料中的多个信号支持同一人物。

- `CORROBORATED`：两个独立来源，或强标识与来源共同支持。

- `CONFLICTED`：人脸、姓名、公司、地区、账号归属或来源时间存在明确冲突。

- `INSUFFICIENT_EVIDENCE`：工具失败、质量不足或只有弱信号。

- `POSSIBLE_STOLEN_PHOTO`：反向搜图来源指向另一个可识别身份，并且存在人脸、账号或来源时间等独立冲突证据。

    

不能只因为 `FOUND_ONLINE` 就输出 `POSSIBLE_STOLEN_PHOTO`。P0 不输出 `AUTHENTIC_PERSON` 或“真人认证”结论。



### 6\.7 有限工具队列



图片工作线允许根据新事实继续执行工具，但不是无限循环：



- 最大扩展深度：建议初始值 2。

- 最大社交账号数：建议初始值 10。

- 最大图片数：建议初始值 12。

- 最大人脸比较数：建议初始值 8。

- URL、图片内容和图片对全部去重。

- 没有新事实时立即停止。

- 达到任务外部调用、成本或 deadline 时停止。

- 任一工具失败返回部分结果，不使整个任务失败。

    

这些限制用于控制成本和错误扩散，不代表对应能力不交付。



## 7\. 共享缓存与自建数据能力



### 7\.1 缓存归属



```Plain Text
Worker Final Query Cache
-> Agent Entity Exact Lookup
-> Agent Tool Observation Cache
-> External Tool / Backend
-> Agent 返回 SearchProviderResult
-> Worker 写 Final Query Cache
```



- Final Query Cache 继续由 `SearchTaskWorker.runSingleSearchProvider()` 独占读写 `provider_result_cache`。

- Search Agent 不增加第二套最终结果缓存。

- 单工具结果使用独立 Tool Observation Cache，不与 `provider_result_cache` 混存。

- Entity Store 解决“不同查询是否指向同一人物”，不能代替查询缓存。

- Raw Snapshot 继续保存第三方原始响应，便于审计和复现。

    

### 7\.2 缓存键



- Final Query Cache：规范化后的全部初始 clues \+ Agent policy/evidence schema version。

- LLM：规范化请求 \+ backend/model \+ prompt/schema version。

- Social Profile：canonical URL/handle \+ provider \+ extractor schema version \+ scope。

- Reverse Image：content SHA\-256 \+ provider/backend \+ result schema version \+ scope。

- Face Comparison：排序后的两张 SHA\-256 \+ provider/model \+ threshold version \+ user/task scope。

    

用户上传图片和人脸比较结果默认 `USER_PRIVATE`，未经授权不跨用户复用。公开社交资料只有在合同允许时才能进入 `GLOBAL_PUBLIC` scope。



### 7\.3 建议存储



|层级|存储|内容|
|---|---|---|
|Final Query Cache|MySQL `provider_result_cache`，可选 Redis 热缓存|最终 `SearchProviderResult` 正负缓存|
|Tool Observation Cache|MySQL 独立表或 Redis 独立 namespace|单工具、backend、模型和输入版本结果|
|Entity Store|MySQL|人物、强标识、字段、来源和 TTL|
|Task Evidence|MySQL|本次任务的事实、发现关系、比较和风险信号|
|Raw Snapshot|COS|provider 原始响应和必要图片快照|



初始 TTL 建议：



- Final Query 正缓存 7 至 30 天，负缓存 6 至 24 小时。

- Social Profile 公开资料 1 至 7 天，按平台更新频率和合同调整。

- Reverse Image 结果 7 至 30 天；来源可访问性可以更短周期复查。

- Face Comparison 缓存不得超过两张输入图片中更短的保留期限，并保持 user/task scope。

- Entity Store 按字段设置 observed time 和 expire time，不使用整个人物统一永久 TTL。

- Raw Snapshot 按 provider 合同、隐私和审计要求留存。

    

TTL 是评审初始值，必须支持按 provider、scope、正负结果和版本独立配置。



P0 建议的数据结构：



- `person_entities`：人物主实体、状态和置信度。

- `person_identifiers`：PDL/Pipl ID、canonical social URL、Wikidata/官方 ID 和 scope。

- `person_facts`：字段值、来源、支持状态和 TTL。

- `person_sources`：provider、source URL、response reference、model/policy version。

- `query_entity_mappings`：query fingerprint 到 person 的已验证映射。

- `media_assets.content_sha256`：用户上传图片的内容 hash。

- `image_fingerprints`：SHA\-256、pHash、media asset、来源和 TTL。

- `search_evidence_facts`：任务事实和 `parent_evidence_id` 发现关系。

- `image_face_comparisons`：图片对、模型、阈值、分数和状态。

- `agent_tool_calls`：每次真实工具/backend attempt。

    

### 7\.4 人物库读写



人物库能力本次需要完整实现，但启用顺序仍遵循安全边界：



1. 先写入并验证强标识合并、scope、删除和冲突处理。

2. 再开放 provider ID、canonical social URL、Wikidata/官方 ID、图片 SHA\-256 的精确读取。

3. 姓名只做召回，不自动合并。

4. 读取可以独立熔断，但正式实现和验收不能省略。

    

内部来源状态：



```Plain Text
DISCOVERED   provider 给出候选，来源尚未检查
SUPPORTED    至少一个独立公开来源支持
CORROBORATED 两个独立来源，或强标识与来源共同支持
CONFLICTED   身份或关键字段冲突
```



## 8\. 配置与 Provider 可替换性



目标配置示意：



```YAML
provider:
  search_mode: agent
  search_agent:
    policy_version: people_image_v1
    timeout_ms: 65000
    people_max_tool_steps: 2
    max_external_calls_per_task: 10
    max_backend_attempts_per_tool: 2
    task_cost_budget: 1.0
    entity_store_read_enabled: true
    entity_store_write_enabled: true

    people:
      FULL_NAME:
        primary: llm_search
        fallback: people_data_labs
      SOCIAL_LINK:
        primary: llm_search
        fallback: people_data_labs

    image_evidence:
      enabled: true
      max_expansion_depth: 2
      max_social_accounts: 10
      max_images: 12
      max_face_comparisons: 8
      social_profile:
        enabled: true
        primary: social_profile_primary
      reverse_image:
        enabled: true
        primary: searchapi_google_lens
        fallback: google_vision
        tineye_mode: explicit_only
      face_comparison:
        enabled: true
        primary: face_comparison_primary
```



数值需要根据 benchmark 和 provider 计费校准。正式上线验收时，People 与 Image Evidence 均应为 enabled。



需要的开关：



- `SEARCH_PROVIDER_MODE=legacy|agent`：迁移期回退，稳定后删除。

- `SEARCH_AGENT_PDL_FALLBACK_ENABLED`。

- `SEARCH_AGENT_ENTITY_STORE_READ_ENABLED` / `WRITE_ENABLED`。

- `SEARCH_AGENT_SOCIAL_PROFILE_ENABLED`。

- `SEARCH_AGENT_REVERSE_IMAGE_ENABLED`。

- `SEARCH_AGENT_FACE_COMPARISON_ENABLED`。

- 原有每个 provider 的 enabled、endpoint、model 和 Secret 配置。

    

功能级开关在正式上线后继续作为 kill switch，但默认开启。关闭某个工具时其他工作线继续返回部分结果。



## 9\. 客户端与接口影响



### 9\.1 保持不变



- 不新增任务创建接口。

- 不修改 Kafka 任务消息、任务状态和候选列表主流程。

- Search Agent 继续返回现有 `SearchProviderResult` / `SearchReport`。

- People Search 的客户端请求和响应结构保持不变。

    

### 9\.2 图片结果



- `identity_match_rate` 从固定 `0` 改为经过校准的人脸比较汇总结果。

- `match_photos` 从固定空数组改为真实图片对和比较证据。

- `authenticity_photos[].status` 支持 `found_online`、`no_public_match`、`unknown`。

- 不再把在线反查无结果返回为 `authentic`。

- 首页或人工维护样例中的 `authentic` 不受在线反查语义影响。

    

当前每张 `authenticity_photos` 只有一个 `source_url`。为了完整展示全部反查来源，建议做向后兼容扩展：



```JSON
{
  "image_url": "...",
  "status": "found_online",
  "source_url": "https://primary.example/page",
  "sources": [
    {
      "source_url": "https://primary.example/page",
      "provider": "searchapi_google_lens",
      "title": "Primary source"
    }
  ]
}
```



保留 `source_url` 作为代表来源，旧客户端可以继续读取；新客户端读取可选 `sources`。这是本方案唯一建议的客户端结构扩展，需要在实现前确认。



## 10\. 调用预算与可观测性



逻辑工具步骤和真实外部请求必须分别计数。一次 LLM Tool 可能尝试多个 backend，一张图片也可能执行 Lens 后再 fallback Vision。



每次真实 tool/backend attempt 记录：



- `agent_run_id` / `tool_call_id` / `attempt_no`。

- `task_id` / `query_id` / `query_fingerprint`。

- route、policy version、tool、backend、model。

- cache tier、cache hit、开始时间和 duration。

- status、fallback reason、candidate count。

- token usage、billable units 和 estimated cost。

- source support status 和 selected as final。

- request/response reference。

    

现有 `provider_requests` 继续作为 Worker 外层摘要；新增 `agent_tool_calls` 保存 Agent 内部真实调用，避免把多次 attempt 只塞进 aggregate payload。



核心指标：



- 各 query type 的 Final Query Cache 和 Tool Cache 命中率。

- 每次任务的真实第三方调用数、成本和 P50/P95 延迟。

- LLM usable 命中后的 PDL 调用率，目标为 0。

- fallback 触发率和成功率。

- Wrong\-person、来源不支持和账号错误扩展比例。

- Reverse Image 三种状态和每张图片来源数量。

- Face Comparison 状态、低质量率和阈值版本。

- `POSSIBLE_STOLEN_PHOTO` 数量、人工复核通过率和误报率。

- 各预算停止原因和部分结果比例。

    

## 11\. 正确率验证与发布门槛



### 11\.1 LLM benchmark



把现有 100 个名字整理为版本化数据集，覆盖：



- 知名人物、普通人物、常见同名和唯一姓名。

- 中文、英文和跨语言姓名。

- 姓名、姓名 \+ 地区、姓名 \+ 公司、SOCIAL\_LINK。

- 明确应当无结果的 negative cases。

    

核心指标：



- Top\-1 identity accuracy。

- Top\-3 recall。

- Wrong\-person false positive rate。

- No\-result precision/recall。

- Citation reachability 和 citation support rate。

- Field\-level precision。

- 成本和 P95 延迟。

    

每次 endpoint、model、prompt、schema、policy 或来源验证变化都必须重跑。



### 11\.2 图片与社交 benchmark



准备至少三组标注样本：



- Social Profile：正确/错误账号、私密/不存在页面、关联账号、同名账号和跨语言资料。

- Face Comparison：同一人、不同人、低清、侧脸、遮挡、多脸和无脸图片对。

- Reverse Image：已知公开来源、重复转载、裁剪/压缩、素材图和无可用来源图片。

    

核心指标：



- 社交账号归属 precision/recall 和错误扩展率。

- Face Comparison false match、false non\-match 和 insufficient\-quality rate。

- Reverse Image 有效来源召回率、无关来源比例、可访问率和多来源保留率。

- `POSSIBLE_STOLEN_PHOTO` 误报率。

- 平均扩展深度、调用数、成本和 P95 延迟。

    

“没有搜到”不能构成照片真实的 ground truth，因此不得统计所谓 authenticity accuracy。



### 11\.3 上线阻断条件



- 任一工作线未实现或未完成端到端测试。

- LLM Wrong\-person 超过评审确认门槛。

- 无来源支持的 LLM 结果被标为 verified/HIGH。

- 图片反查仍把 no\-result 映射为 `authentic`。

- 用户图片在 People no\-result 或 SOCIAL\_LINK 场景未执行。

- Face Comparison false match 或盗图风险误报超过门槛。

- 实际第三方调用数无法核算或预算不能停止执行。

- 高敏图片、人脸和社交数据的授权、删除或合同边界未确认。

- 任一 provider 失败导致整个任务失败而不是返回部分结果。

    

## 12\. 实施计划



实施优先级不改变上线范围。



### 阶段 0：共享基础



- 确认 Agent/Worker 边界、最终缓存归属和数据 schema。

- 新增调用级记录和预算框架。

- 固化 People、Social、Face、Reverse Image benchmark。

- 确认 MaaS 搜索能力和所有 provider 的合同、成本与 Secret。

    

### 阶段 1：LLM 人物检索，第一优先



- 将现有 `LLMPrimaryPeopleSearchProviderRepo` 重构为薄 Search Agent 的 People route。

- 完成 usable gate、fallback reason 和 PDL 仅 fallback。

- 完成多 LLM backend、版本化缓存、超时和熔断。

- 保持 Public Figure 的本地优先和条件式 remote 语义。

- 完成 FULL\_NAME、SOCIAL\_LINK、缓存和 provider 故障回归。

    

验收：LLM usable 结果不调用 PDL；LLM 无可用候选正确 fallback；客户端 People API 行为兼容。



### 阶段 2：图片反查与身份图片证据，第二优先



共享接口稳定后即可与阶段 1 后半段并行：



- 修正 Worker 初始图片调度，所有用户图片独立执行。

- 完成 Social Profile adapter 和一家主 provider 接入。

- 完成 Image Materializer 和图片 SHA\-256/pHash。

- 修通 Lens/Vision/TinEye 路由、配置、fallback 和多来源保存。

- 完成一个 Face Comparison provider 接入和阈值校准。

- 完成有限工具队列、去重、证据关系和风险规则。

- 修正详情图片状态并增加向后兼容的 `sources`。

    

验收：三项图片能力均真实执行；任一入口均可工作；语义、来源、成本和客户端展示通过测试。



### 阶段 3：缓存、自建库与证据持久化



- Worker 独占 Final Query Cache。

- 增加 Tool Observation Cache 和 singleflight/分布式锁。

- 建立人物、标识、字段、来源、图片指纹和任务证据表。

- 先验证人物库写入，再开放强标识精确读取。

- 验证删除、过期、冲突、撤销合并和 scope 隔离。

    

### 阶段 4：联合验收与正式上线



- 同时启用 LLM、Social Profile、Reverse Image、Face Comparison 和 Evidence Aggregation。

- 跑完整 benchmark、接口回归、并发、防击穿、预算、故障和高敏数据测试。

- 走真实 staging API 链路验证，不只检查代码或 Secret。

- 两条工作线均满足第 11 节门槛后才允许正式上线。

    

### 阶段 5：稳定后删除 Legacy



- 稳定观察周期结束后删除 `SEARCH_PROVIDER_MODE` 和 legacy provider 构建分支。

- 删除仅服务旧编排的 `LLMPrimaryPeopleSearchProviderRepo` 和无引用 aggregate 代码。

- 保留 provider adapters、功能级 kill switch 和正常版本回滚能力。

    

## 13\. 代码改动范围



### 13\.1 Worker 与 Provider



- `app/worker/main.go` 或当前 provider builder：构建 Agent、工具注册表和模式切换。

- `app/worker/repo/llm_primary_people_search_provider.go`：重构为 LLM primary \+ usable gate \+ PDL fallback。

- `app/worker/repo/llm_search_provider.go`：增强 backend attempt、来源和 usage 记录。

- 新增或拆分 `search_agent.go`、policy、quality gate、evidence aggregator 和 execution recorder。

- `app/worker/service/search_task_worker.go`：所有初始图片独立调度；保留 Final Query Cache 和 AddReportPhotos。

- 复用并调整 Google Lens、Vision、TinEye adapters。

- 新增 Social Profile、Image Materializer 和 Face Comparison adapters。

    

### 13\.2 People Insight 输出



- `app/people_insight/service/invoke_service.go`：真实填充 `identity_match_rate`、`match_photos` 和图片状态。

- 保留全部反查来源，并输出兼容的 `source_url` \+ 可选 `sources`。

- 修正在线 no\-result 不再返回 `authentic`。

    

### 13\.3 数据与配置



- migration：实体、标识、事实、来源、query mapping、tool calls、task evidence、face comparison、image fingerprint。

- `media_assets` 增加 `content_sha256` 和指纹状态字段。

- worker 配置支持多 LLM backend、三个图片工具和独立 kill switch。

- 部署配置和 Secret 只保存引用，不把 key 写入仓库。

    

## 14\. 测试范围



- legacy/agent 路由和最终删除 legacy 的回归。

- LLM usable、不可信非空、no\-result、timeout、rate limit、invalid response 和多 backend。

- LLM 命中不调用 PDL；fallback 只调用一次 PDL。

- Public Figure 本地、people 和条件式 remote 顺序。

- FULL\_NAME、SOCIAL\_LINK、仅图片、People no\-result \+ 图片和 AddReportPhotos。

- Social Profile 页面存在、资料提取、关联账号、错误 URL、去重和 provider contract。

- Image Materializer 的 HTTPS、SSRF、重定向、类型、大小、像素、超时、TTL 和删除。

- Reverse Image 的多来源、主工具/fallback 和三种状态。

- Face Comparison 的同人、异人、低质量、无脸、多脸、失败和阈值版本。

- `NO_PUBLIC_MATCH != authentic` 和 `FOUND_ONLINE != stolen` 语义。

- `POSSIBLE_STOLEN_PHOTO` 必须具备独立冲突证据。

- 任一工具失败返回部分结果。

- Final Query Cache、Tool Cache、Entity Store 的命中顺序、scope 和版本隔离。

- 并发 singleflight、防击穿和所有预算停止条件。

- `agent_tool_calls`、父证据、原始响应和成本记录完整性。

- 现有 `CreateIntentTask` 到 `ListTaskCandidates` / `GetTaskCandidateDetail` 的完整真实链路。

- 客户端旧字段兼容和可选 `sources` 扩展。

    

## 15\. 主要风险与控制



|风险|控制|
|---|---|
|LLM 幻觉或伪造来源|Usable gate、来源验证、MEDIUM 上限、benchmark 和人工抽样|
|LLM 命中后仍重复调用 PDL|明确 fallback reason，增加调用次数断言和线上指标|
|多 backend 或多图片导致成本失控|分别限制 tool step、backend attempt、外部调用、深度、数量、deadline 和成本|
|错误社交账号持续扩散|canonical URL 去重、账号归属 gate、最大深度/账号数、无新事实停止|
|商业社交 provider 不稳定或锁定|统一 adapter、真实样本横评、保留替换入口和原始响应|
|外部头像造成 SSRF 或恶意文件|受控 Image Materializer、IP/DNS 防护和文件限制|
|Face false match 导致错人|标注集校准、阈值版本化、优先控制 false match、多证据聚合|
|反向搜图被误当身份或盗图证明|状态分离，盗图提示必须有独立冲突证据|
|no\-result 被误标为 authentic|修改服务端状态、增加语义测试和客户端回归|
|人物库错误长期传播|强标识合并、先验证后读、冲突状态、可撤销 merge|
|双重最终缓存|Final Query Cache 只由 Worker 管理，Tool Cache 独立 namespace|
|图片和人脸高敏数据风险|不建人脸库、不跨用户复用、TTL、删除、授权和合同审查|
|客户端不识别新图片状态|上线前同步状态枚举，保留结构兼容和代表 `source_url`|
|Provider 部分失败拖垮任务|工具独立超时、熔断和部分结果返回|



## 16\. 评审前需要准备



- 当前 LLM MaaS endpoint、model、Secret 和联网搜索能力验证结果。

- Lens、Google Vision、TinEye 的账号、配额、计费和有效运行配置。

- 候选商业社交数据 provider 的试用账号和同样本对比结果；当前候选包括 SocialCrawl、Scrape Creators 和 Social Fetch，最终选择以真实测试为准。

- 候选 Face Comparison provider 的账号、阈值说明和数据处理条款。

- 100 条 People benchmark 和图片/社交/人脸标注集。

- 图片、人脸、公开邮箱和社交数据的授权、保留、删除和跨境结论。

- 客户端对 `no_public_match`、`unknown` 和可选 `sources` 的确认。

- Wrong\-person、Face false match、盗图误报、成本和 P95 延迟的阻断门槛。

    

## 17\. 评审需要确认的问题



1. LLM usable gate 和 PDL fallback reasons 是否接受？

2. LLM\-only 结果最高 `MEDIUM` 是否符合产品表达？

3. 初始 Tencent Cloud MaaS backend 是否具备可验证的实时网页检索能力？

4. P0 选择哪一家 Social Profile provider 和 Face Comparison provider？

5. TinEye 是否只用于同图、素材图和来源时间分析？

6. `POSSIBLE_STOLEN_PHOTO` 的最小独立冲突证据是什么，是否需要人工复核？

7. `identity_match_rate` 的聚合方法和 Face false match 阻断门槛是什么？

8. 客户端是否接受新增图片状态和可选 `sources`？

9. 人物库哪些数据允许 `GLOBAL_PUBLIC`，哪些必须 `USER_PRIVATE`？

10. 图片、人脸和社交数据的保留周期、删除 SLA 和跨境边界是什么？

11. 每任务外部调用数、成本、扩展深度、账号数和图片数的初始预算是多少？

12. Legacy 稳定观察周期和删除负责人是谁？

    

## 18\. 推荐评审结论



建议“有条件通过”并按本方案开工，条件是第 17 节关键产品、供应商、阈值和合规问题在对应模块对外启用前确认。



需要明确写入评审结论：



- 本次正式上线范围同时包含 LLM 人物检索和图片反查与身份图片证据。

- LLM 是第一开发优先级，图片工作线是第二开发优先级，两者必须在上线前全部完成。

- 两条工作线独立执行、独立失败、共享缓存和证据基础设施，最终统一生成报告。

- Agent 使用确定性 People route 和有限证据队列，不使用无边界自由循环。

- LLM usable 后不调用 PDL；PDL 只做 fallback。

- 用户图片不依赖 People Search 成功，始终执行反向搜图。

- Social Profile、Reverse Image、Face Comparison 全部属于本次交付，不是后续可选项。

- 正式上线时两条工作线默认开启，功能开关只作为故障隔离能力。

- 任何一条工作线未完成或未达到发布门槛，都不能以“后续再开”作为本次上线方案。

