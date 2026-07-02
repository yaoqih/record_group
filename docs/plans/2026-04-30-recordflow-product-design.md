# RecordFlow 产品文档

版本：V0.1  
日期：2026-04-30  
定位：连续录音的增量信息工作台

## 1. 一句话定位

RecordFlow 不是一个单纯的“录音转文字”工具，而是一个把连续录音转成可维护、可追溯、可更新的结构化工作空间的产品。

它解决的问题不是“有没有文字稿”，而是：

> 用户在多次录音之后，能不能持续知道事情现在变成了什么样。

## 2. 核心洞察

传统录音转写产品通常把每段录音处理成一篇孤立文本。这个模式在短录音里可用，但在真实工作和生活中很快失效：

- 项目会议会连续发生，单篇纪要无法维护项目状态。
- 客户沟通会反复推进，用户关心的是需求、异议、承诺和下一步。
- 个人口述常常是碎片化的，用户需要被整理成主题、草稿和待办。
- 访谈调研不是只要一份文字稿，而是要观点、证据、共性和差异。
- 课程学习不是只要转写，而是要知识点、案例、术语和复习材料。

更合理的产品假设是：

> 录音是一种连续的信息流，产品应该维护“状态”，而不是只生成“文档”。

## 3. 产品名称与概念

暂定名称：RecordFlow

核心概念：

- Record：每一次录音或导入的转写文本。
- Flow：连续进入的信息流。
- Workspace：围绕一个项目、客户、主题、课程或调研对象形成的工作空间。
- State Page：系统持续维护的当前状态页。
- Evidence Anchor：每条结构化结论都绑定原始音频片段或转写片段。

产品的最终体验应当是：

> 用户不断把录音丢进去，系统不断把事情整理好，并告诉用户本次新增了什么、更新了什么、冲突了什么、下一步要做什么。

## 4. 目标用户

RecordFlow 的目标用户不是只需要偶尔转写的人，而是持续通过语音产生信息的人。

典型用户包括：

1. 项目负责人
   - 需要从多次会议中维护任务、决策、风险和待解决问题。

2. 销售、客户成功、咨询顾问
   - 需要从多次客户沟通中维护客户需求、异议、预算、承诺和跟进动作。

3. 创作者、研究者、产品经理
   - 需要把零散口述、讨论和灵感沉淀成主题笔记、文章草稿、产品想法或研究材料。

4. 访谈调研人员
   - 需要把多位受访者的内容整理成观点、证据、标签、共性差异和可引用原话。

5. 学习者和培训组织者
   - 需要把课程、讲座、培训录音整理成知识点、案例、定义、复习卡片和行动建议。

## 5. 产品原则

### 5.1 一个信息底座，多种场景视图

不要为会议、客户、个人口述、访谈、课程分别做五套系统。所有场景底层都进入同一套信息模型，再通过场景 Profile 呈现不同视图。

### 5.2 增量优先，而不是全文优先

每次新录音进入后，系统首先回答：

- 本次新增了什么？
- 哪些已有信息被更新？
- 哪些内容重复？
- 哪些内容存在冲突？
- 哪些事情需要用户处理？

全文转写仍然保留，但不是产品中心。

### 5.3 所有结论必须可追溯

每条任务、决策、客户需求、访谈观点、知识点都需要能回到原始音频或转写片段。

这是产品可信度的基础。

### 5.4 Agent 不自由发挥，只承担窄职责

多智能体架构不应该做成一群不可控的自动聊天 Agent。RecordFlow 应采用固定流水线，每个 Agent 只负责一个清晰任务，并输出结构化结果。

## 6. 核心场景

### 6.1 连续会议与项目推进

用户把每次会议录音上传到同一个项目 Workspace。

系统输出：

- 本次会议摘要
- 相比上次的变化
- 新增任务
- 更新任务
- 新增决策
- 风险和阻塞
- 未决问题
- 可回听证据片段

项目 State Page 持续维护：

- 当前目标
- 关键决策
- 任务看板
- 风险列表
- 未决问题
- 重要时间线

### 6.2 客户沟通与销售跟进

用户把多次客户通话、拜访、微信语音或会议录音放入客户 Workspace。

系统输出：

- 客户背景
- 明确需求
- 隐含需求
- 预算与时间窗口
- 关键异议
- 已做承诺
- 下一步动作
- 下次沟通建议问题

客户 State Page 持续维护：

- 客户画像
- 决策链
- 需求列表
- 异议列表
- 方案匹配点
- 跟进时间线

### 6.3 个人口述与创作整理

用户随时录音，把想法、反思、灵感、待办丢进个人 Workspace。

系统输出：

- 新想法
- 可合并到旧主题的补充
- 可执行待办
- 可发展成文章或方案的素材
- 冲突或反复出现的观点

个人 State Page 持续维护：

- 主题库
- 想法池
- 待办清单
- 草稿素材
- 最近反复出现的问题

### 6.4 访谈与用户研究

用户把不同受访者录音放入同一个调研 Workspace。

系统输出：

- 受访者画像
- 核心观点
- 代表性原话
- 需求和痛点
- 行为证据
- 与其他受访者的共性和差异
- 值得追问的问题

调研 State Page 持续维护：

- 主题聚类
- 观点矩阵
- 证据库
- 代表性引用
- 未验证假设

### 6.5 课程、培训与学习整理

用户把课程、培训、讲座录音放入学习 Workspace。

系统输出：

- 知识点
- 定义
- 案例
- 操作步骤
- 易混淆点
- 复习问题
- 行动建议

学习 State Page 持续维护：

- 知识地图
- 术语表
- 案例库
- 复习卡片
- 待实践清单

## 7. 统一信息模型

RecordFlow 的底层不按场景建模，而按通用信息对象建模。

### 7.1 基础对象

```text
Workspace
  Record
    TranscriptSegment
      EvidenceAnchor

StateObject
  ChangeEvent
```

### 7.2 通用结构化对象

所有场景都可以映射到以下对象类型：

| 对象 | 含义 | 示例 |
| --- | --- | --- |
| Fact | 已表达的事实 | 客户目前使用本地部署系统 |
| Decision | 已形成的决定 | 下周先做小范围试点 |
| Task | 需要执行的事项 | 王工周五前提供接口文档 |
| Question | 未解决问题 | 数据权限由谁审批 |
| Risk | 风险或阻塞 | 历史数据质量不稳定 |
| Requirement | 需求 | 希望支持批量导入录音 |
| Objection | 异议 | 客户担心部署成本过高 |
| Idea | 想法 | 可以把录音整理成主题状态页 |
| Insight | 洞察 | 用户真正需要的是状态更新 |
| Knowledge | 知识点 | 增量合并需要保留变更历史 |
| Quote | 可引用原话 | 绑定具体说话人和时间戳 |
| TimelineEvent | 时间线事件 | 4 月 30 日完成方案评审 |
| Entity | 人、组织、产品等实体 | 李工、A 公司、RecordFlow |

### 7.3 对象实现规则

上表不能只停留在“对象枚举”。每类对象都需要明确四件事：

- 如何从录音片段中被识别出来。
- 需要保存哪些关键字段。
- 如何和历史对象匹配。
- 新录音进入后如何增量更新。

所有对象共用一个外壳字段，再根据对象类型保存专属字段。

```text
StateObject
  id
  type
  title
  summary
  status
  confidence
  workspace_id
  topic_ids
  evidence[]
  created_at
  updated_at
  payload
```

其中 `payload` 保存类型专属信息。例如 Task 有负责人和截止时间，Requirement 有需求主体和优先级，Quote 有说话人和原文。

| 对象 | 识别线索 | 核心字段 | 历史匹配键 | 增量更新规则 |
| --- | --- | --- | --- | --- |
| Fact | 明确陈述、背景说明、客观状态 | subject、predicate、value、scope、valid_time | subject + predicate + scope | 同一主语同一属性出现新值时，判断为 update 或 conflict |
| Decision | “决定”“确定”“先这样”“就按这个” | decision、reason、participants、effective_time、reversible | decision_topic + participants + time_scope | 新决策可能 supersede 旧决策，旧决策不删除，标记被替代 |
| Task | “谁去做什么”“什么时候交付” | action、owner、due_date、status、deliverable、priority | action + owner + deliverable | 更新负责人、截止时间、状态；出现完成表达时 close |
| Question | “还不确定”“需要确认”“谁负责” | question、owner、blocking_level、answer_status | normalized_question + topic | 有回答时 close 或 clarify；继续追问时追加上下文 |
| Risk | “担心”“可能影响”“卡点”“不稳定” | risk_event、impact、probability、mitigation、owner | risk_event + affected_area | 风险升级/降级时 update；已有措施时 clarify |
| Requirement | “希望”“需要”“必须支持” | requester、need、scenario、priority、acceptance_hint | requester + need + scenario | 需求细化时 clarify；范围扩大/缩小时 update |
| Objection | “担心”“不能接受”“成本太高” | objector、objection、reason、severity、response | objector + objection_topic | 保留历史，不覆盖；新的回应追加到 response_history |
| Idea | “可以试试”“我有个想法” | idea、motivation、related_topics、maturity | idea_topic + intent | 相似想法合并成主题，新的表达作为补充版本 |
| Insight | 从多条事实或观点中归纳出的洞察 | insight、supporting_objects、scope、confidence | insight_topic + scope | 新证据增强或削弱洞察；低证据时标记 tentative |
| Knowledge | 定义、方法、步骤、原则 | concept、definition、steps、examples | concept + domain | 新解释补充 examples/steps；冲突定义进入 review |
| Quote | 值得保留的原话 | speaker、quote_text、start_time、end_time、tags | record_id + time_range | 不改写原文，只更新标签和引用用途 |
| TimelineEvent | 已发生或计划发生的时间事件 | event、time、actor、related_objects | event + time + actor | 时间变化时 update；事件完成时 close 或 mark_done |
| Entity | 人、组织、产品、地点等实体 | name、entity_type、aliases、attributes、relations | canonical_name + entity_type | 合并别名，更新属性和关系；冲突属性保留证据 |

### 7.4 类型间关系

单个对象很难表达真实录音里的完整含义，系统需要维护对象之间的关系。

常见关系包括：

| 关系 | 含义 | 示例 |
| --- | --- | --- |
| supports | 一个对象支持另一个对象 | Quote 支持 Requirement |
| blocks | 一个对象阻塞另一个对象 | Risk 阻塞 Task |
| answers | 一个对象回答一个问题 | Fact 回答 Question |
| creates | 一个对象产生另一个对象 | Decision 产生 Task |
| supersedes | 一个对象替代另一个对象 | 新 Decision 替代旧 Decision |
| clarifies | 一个对象澄清另一个对象 | Fact 澄清 Requirement |
| belongs_to | 一个对象归属某主题 | Task 属于产品设计主题 |

这层关系是“结构化整理”真正可用的关键。否则系统只能得到一堆孤立条目，无法回答“这个任务为什么出现”“这个风险影响哪个决策”“这个需求由哪句原话支持”。

### 7.5 StateObject 字段

```json
{
  "id": "obj_001",
  "type": "Task",
  "title": "整理第一版产品文档",
  "summary": "输出 RecordFlow 的产品定位、架构和 MVP 边界",
  "status": "open",
  "confidence": 0.86,
  "workspace_id": "ws_recordflow",
  "topic_ids": ["topic_product_design"],
  "owners": ["用户", "AI 助手"],
  "due_date": null,
  "evidence": [
    {
      "record_id": "rec_001",
      "segment_id": "seg_018",
      "start_time": "00:12:31",
      "end_time": "00:13:05"
    }
  ],
  "created_at": "2026-04-30T10:00:00+08:00",
  "updated_at": "2026-04-30T10:00:00+08:00"
}
```

## 8. 场景 Profile

场景差异不写死在代码里，而通过 Profile 配置表达。

```json
{
  "scene": "customer_followup",
  "display_name": "客户跟进",
  "focus_objects": [
    "Requirement",
    "Objection",
    "Decision",
    "Task",
    "TimelineEvent",
    "Quote"
  ],
  "merge_policy": {
    "Requirement": "merge_by_topic_and_intent",
    "Objection": "keep_history",
    "Task": "merge_by_owner_action_due_date",
    "Decision": "append_and_mark_latest"
  },
  "default_outputs": [
    "本次沟通摘要",
    "客户需求变化",
    "异议和风险",
    "下一步动作",
    "下次沟通建议"
  ]
}
```

### 8.1 内置 Profile

| Profile | 关注重点 | 默认输出 |
| --- | --- | --- |
| project_meeting | 决策、任务、风险、未决问题 | 会议纪要、项目状态页、任务看板 |
| customer_followup | 需求、异议、预算、承诺、下一步 | 客户摘要、跟进记录、下次问题 |
| personal_capture | 想法、主题、待办、草稿素材 | 个人笔记、想法池、待办 |
| user_research | 观点、痛点、证据、引用、假设 | 调研分析、观点矩阵、引用库 |
| learning_notes | 知识点、定义、案例、复习问题 | 学习笔记、知识地图、复习卡片 |

### 8.2 场景结构组合

每个场景不是简单筛选几个对象，而是把通用对象组织成一个稳定的业务结构。

| 场景 | 主结构 | 核心对象 | 辅助对象 | 输出组织方式 |
| --- | --- | --- | --- | --- |
| 项目会议 | 项目状态页 | Decision、Task、Question、Risk、TimelineEvent | Fact、Quote、Entity | 按目标、决策、任务、风险、问题、时间线组织 |
| 客户跟进 | 客户档案与推进状态 | Requirement、Objection、Task、Decision、TimelineEvent | Fact、Quote、Entity、Risk | 按客户背景、需求、异议、承诺、下一步组织 |
| 个人口述 | 主题知识库 | Idea、Insight、Task、Question | Fact、Quote、TimelineEvent | 按主题、想法、草稿、待办、反复问题组织 |
| 用户访谈 | 调研证据库 | Quote、Insight、Requirement、Question | Fact、Entity、TimelineEvent | 按受访者、主题、观点、证据、假设组织 |
| 课程学习 | 知识地图 | Knowledge、Question、Task、Quote | Fact、Insight、TimelineEvent | 按概念、定义、步骤、案例、复习问题组织 |

### 8.3 场景状态页模板

场景 Profile 至少应定义三层内容：

```text
SceneProfile
  extraction_focus      本场景优先抽什么
  state_page_template   状态页如何组织
  merge_policy          各对象如何增量合并
  review_policy         哪些变化需要用户确认
  output_templates      每次录音后输出哪些文档
```

以项目会议为例：

```json
{
  "scene": "project_meeting",
  "state_page_template": [
    {
      "section": "当前目标",
      "objects": ["Fact", "Decision", "Insight"]
    },
    {
      "section": "关键决策",
      "objects": ["Decision"],
      "group_by": "topic"
    },
    {
      "section": "任务看板",
      "objects": ["Task"],
      "group_by": "status"
    },
    {
      "section": "风险与阻塞",
      "objects": ["Risk"],
      "group_by": "impact"
    },
    {
      "section": "未决问题",
      "objects": ["Question"],
      "group_by": "owner"
    },
    {
      "section": "时间线",
      "objects": ["TimelineEvent"],
      "group_by": "time"
    }
  ],
  "review_policy": {
    "Decision": "always_review",
    "Task.due_date_changed": "review",
    "Risk.impact_high": "review",
    "Fact": "auto_accept_if_confidence_high"
  }
}
```

### 8.4 对象到场景的映射方式

同一个对象在不同场景里的角色不同。

例如 `Quote`：

- 在项目会议里，Quote 是决策或争议的证据。
- 在客户跟进里，Quote 是客户需求和异议的原始表达。
- 在用户访谈里，Quote 是报告中的代表性原话。
- 在课程学习里，Quote 是老师对概念的关键表述。

因此对象本身保持通用，场景只定义它的用途：

```json
{
  "object_type": "Quote",
  "scene_usage": {
    "project_meeting": ["decision_evidence", "conflict_evidence"],
    "customer_followup": ["requirement_voice", "objection_voice"],
    "user_research": ["representative_quote", "evidence"],
    "learning_notes": ["definition_source", "example_source"]
  }
}
```

## 9. 多智能体架构

RecordFlow 的 Agent 应该是“流水线式多智能体”，不是“开放式自治多智能体”。

### 9.1 Agent 划分

```text
Ingestion Agent
  接收录音、转写文本、已有文档，统一成 Record。

Transcript Agent
  负责转写清洗、断句、说话人、时间戳和低置信度标记。

Segment Agent
  按主题、语义转折和任务边界切分 TranscriptSegment。

Extract Agent
  从片段中抽取 Fact、Task、Decision、Question、Risk 等结构化对象。

Merge Agent
  将新对象与已有 StateObject 对齐，判断新增、更新、重复、冲突或关闭。

Evidence Agent
  给所有结构化对象绑定原始片段，并标记置信度和不确定性。

Render Agent
  根据场景 Profile 生成用户可读输出。
```

### 9.2 编排方式

```text
Record 输入
  ↓
标准化与转写
  ↓
主题切分
  ↓
结构抽取
  ↓
证据绑定
  ↓
增量合并
  ↓
状态页更新
  ↓
场景化输出
```

### 9.3 为什么这样设计

这种方式有三个好处：

1. 可控
   - 每个 Agent 的输入输出都清晰，可以测试和回放。

2. 可扩展
   - 新增场景主要新增 Profile，不需要重写流水线。

3. 可信
   - 所有结果都能追溯到原始证据，不把大模型生成内容当作事实本身。

## 10. 增量合并机制

增量合并是 RecordFlow 的核心能力。

每次新录音进入后，系统不只是生成一篇摘要，而是生成一组 ChangeEvent。

### 10.1 变更类型

| 类型 | 含义 |
| --- | --- |
| create | 新增对象 |
| update | 更新已有对象 |
| duplicate | 与已有对象重复 |
| conflict | 与已有对象存在冲突 |
| close | 关闭任务或问题 |
| supersede | 新结论替代旧结论 |
| clarify | 对旧信息进行澄清 |

### 10.2 合并流程

```text
新片段
  ↓
抽取候选对象
  ↓
检索相似 StateObject
  ↓
判断关系：新增 / 更新 / 重复 / 冲突
  ↓
生成 ChangeEvent
  ↓
更新 State Page
  ↓
保留可回滚历史
```

### 10.3 示例

第一次会议：

```text
任务：周五前整理产品文档。
```

第二次会议：

```text
产品文档不用周五，提前到周三下班前给第一版。
```

系统不应新增两个任务，而应生成：

```json
{
  "change_type": "update",
  "target_object": "整理产品文档",
  "field_changes": {
    "due_date": {
      "from": "周五",
      "to": "周三下班前"
    }
  },
  "reason": "新录音明确修改了截止时间",
  "evidence": ["rec_002#seg_014"]
}
```

### 10.4 分类型增量更新策略

不同对象的更新方式不能完全相同。系统需要区分“覆盖型”“追加型”“状态型”“证据型”和“归纳型”。

| 更新策略 | 适用对象 | 处理方式 |
| --- | --- | --- |
| 覆盖型更新 | Fact、Requirement、TimelineEvent | 新信息明确修正旧字段时，更新当前值，同时保留旧值和证据 |
| 追加型更新 | Objection、Quote、Idea | 不覆盖旧内容，而是追加新表达、新证据或新版本 |
| 状态型更新 | Task、Question、Risk | 根据新录音改变状态，例如 open、in_progress、blocked、closed |
| 替代型更新 | Decision、Knowledge | 新结论替代旧结论时，用 supersede 关系连接两者 |
| 归纳型更新 | Insight | 根据新增证据增强、削弱、拆分或合并洞察 |

### 10.5 增量更新决策表

Merge Agent 对每个候选对象执行以下判断：

| 判断问题 | 是 | 否 |
| --- | --- | --- |
| 是否能匹配到同一主题下的历史对象？ | 进入更新判断 | 创建新对象 |
| 是否只是重复表达？ | 标记 duplicate，增加证据 | 继续判断 |
| 是否补充了新字段或新证据？ | clarify 或 update | 继续判断 |
| 是否修改关键字段？ | update，必要时进入用户确认 | 继续判断 |
| 是否与历史信息冲突？ | conflict，进入用户确认 | 继续判断 |
| 是否让任务/问题/风险结束？ | close | 保持当前状态 |

### 10.6 用户确认队列

不是所有变化都需要用户确认。否则产品会变成新的整理负担。

默认规则：

- 高置信度的普通 Fact、Quote、TimelineEvent 可以自动接受。
- Decision、Task 截止时间变化、Risk 升级、Requirement 范围变化需要确认。
- conflict 必须确认。
- Insight 如果证据不足，只进入“建议洞察”，不直接写入正式状态页。

确认队列展示格式：

```text
本次需要你确认的 4 个变化

1. 决策变化
   旧：先做会议场景
   新：会议和客户跟进并行做原型
   证据：录音 02:14-02:43

2. 任务截止时间变化
   旧：周五前提交
   新：周三下班前提交
   证据：录音 08:10-08:25
```

## 11. 单次录音的多层次梳理

每次会议或录音处理完后，不应该只输出一篇摘要。更好的体验是输出一组从浅到深的结果，让用户可以快速看，也可以深入追溯。

### 11.1 五层输出

```text
L1 本次速览
  用 5-10 行告诉用户这次录音发生了什么。

L2 主题脉络
  按讨论主题拆分，每个主题给出结论、争议和后续动作。

L3 结构化对象
  抽取 Task、Decision、Question、Risk、Requirement 等对象。

L4 增量变化
  告诉用户相对历史状态新增、更新、关闭、冲突了什么。

L5 状态页更新
  把确认后的变化写入 Workspace 的长期状态页。
```

### 11.2 处理结果结构

每次 Record 处理完成后生成一个 `RecordDigest`。

```json
{
  "record_id": "rec_20260504_001",
  "workspace_id": "ws_recordflow",
  "scene": "project_meeting",
  "one_line_summary": "本次讨论确认 RecordFlow 应采用统一信息底座和多场景 Profile，并补充对象级增量规则。",
  "topic_blocks": [
    {
      "topic": "统一信息模型",
      "summary": "现有对象枚举需要补充识别、字段、匹配键和更新规则。",
      "decisions": ["保留通用对象模型，但增加对象实现规则表"],
      "open_questions": ["不同场景的状态页模板是否需要用户自定义"],
      "evidence": ["seg_003", "seg_004"]
    }
  ],
  "extracted_objects": ["obj_001", "obj_002"],
  "change_events": ["chg_001", "chg_002"],
  "review_items": ["review_001"],
  "state_page_patch": ["patch_001", "patch_002"]
}
```

### 11.3 主题块结构

主题块是单次录音里最重要的中间层。它连接原始转写和长期状态页。

```text
TopicBlock
  topic
  summary
  key_points
  decisions
  tasks
  questions
  risks
  requirements
  quotes
  evidence
```

主题块的作用：

- 让用户不用看全文，也能理解本次讨论结构。
- 让 Extract Agent 在明确上下文中抽取对象。
- 让 Merge Agent 按主题匹配历史对象，减少误合并。
- 让 Render Agent 可以生成不同场景的文档。

### 11.4 多层输出示例

以一次产品讨论录音为例：

```text
L1 本次速览
- 讨论了 RecordFlow 的统一信息模型。
- 明确对象枚举还不够，需要补充字段、匹配键和更新策略。
- 确认每次会议结果应有多层次梳理。

L2 主题脉络
主题：结构化对象设计
- 问题：Fact、Decision、Task 等对象缺少可实现细节。
- 结论：每类对象补充识别线索、核心字段、历史匹配键、增量更新规则。
- 后续：更新产品文档第 7、8、10、11 章。

L3 结构化对象
- Decision：保留统一信息模型，但补充对象实现规则。
- Task：更新 Markdown 产品文档。
- Question：每类场景如何组合这些对象。

L4 增量变化
- update：第 7 章从对象枚举升级为对象实现规则。
- create：新增场景结构组合矩阵。
- create：新增单次录音五层输出模型。

L5 状态页更新
- 产品架构：统一底座 + 场景 Profile + 增量合并。
- 待办：继续细化 UI 原型和数据 Schema。
```

### 11.5 为什么需要多层次结果

多层输出可以同时满足三类使用方式：

- 用户很忙时，只看 L1 和 L4。
- 用户要理解上下文时，看 L2。
- 用户要协作和执行时，看 L3 和 L5。
- 用户不信任 AI 结论时，点开证据查看原文和音频。

## 12. 产品界面

### 12.1 主界面布局

```text
左侧：Workspace 列表
  项目
  客户
  个人主题
  调研
  课程

中间：录音时间线
  每次录音
  本次摘要
  本次变化
  可回听片段

右侧：State Page
  当前状态
  任务
  决策
  问题
  风险
 证据
```

### 12.2 关键页面

1. Inbox
   - 上传录音、导入转写文本、粘贴聊天记录。

2. Workspace Home
   - 展示一个主题的当前状态，而不是展示文件列表。

3. Change Review
   - 展示本次录音带来的增量变化，用户可以接受、编辑或忽略。

4. Evidence View
   - 点击任意结论，回到音频时间点和原文片段。

5. Ask Workspace
   - 用户可以问：“这个客户现在最大异议是什么？”“上次决定谁来做？”“哪些问题还没解决？”

## 13. MVP 范围

第一版应尽量小，但必须体现核心差异。

### 13.1 必做

- 创建 Workspace。
- 上传录音或导入转写文本。
- 选择场景 Profile。
- 生成本次摘要。
- 生成本次增量变化。
- 抽取结构化对象。
- 维护 State Page。
- 每条结构化对象绑定原文证据。
- 支持用户编辑结构化结果。

### 13.2 暂不做

- 复杂权限系统。
- 大规模企业知识库集成。
- 自动生成精美长文报告。
- 全自动 CRM 双向同步。
- 完整移动端。
- 过度复杂的 Agent 自主规划。

### 13.3 MVP 成功标准

用户连续导入 3 次同一主题录音后，能明显感受到：

- 不需要重新读长文字稿。
- 能看到本次相对之前的变化。
- 能知道当前任务、问题、决策是什么。
- 能点回原始片段确认依据。

## 14. 商业化方向

### 14.1 个人版

适合创作者、研究者、学生、自由职业者。

收费点：

- 录音时长
- Workspace 数量
- 高级场景模板
- 长期记忆容量

### 14.2 团队版

适合项目团队、咨询团队、销售团队、产品团队。

收费点：

- 成员数
- 团队 Workspace
- 协作评论
- 权限控制
- 企业模板
- 数据保留策略

### 14.3 行业版

适合咨询、调研、教育培训、客户成功等高频录音场景。

收费点：

- 行业 Profile
- 专用输出格式
- 私有部署
- 合规审计
- 系统集成

## 15. 竞争差异

RecordFlow 不应该和普通转写工具正面比“谁的文字稿更好看”，而应强调新的产品范式。

| 产品类型 | 中心 | 问题 |
| --- | --- | --- |
| 录音转写工具 | 全文文本 | 多次录音后仍然混乱 |
| AI 会议纪要 | 单次会议摘要 | 难以维护长期状态 |
| 笔记软件 | 用户手动整理 | 录音信息进入成本高 |
| CRM/项目管理工具 | 手动字段 | 口头沟通无法自然沉淀 |
| RecordFlow | 增量状态页 | 把语音信息流变成可维护状态 |

核心差异：

- 连续录音优先。
- 增量变化优先。
- 统一结构底座。
- 多场景 Profile。
- 证据可追溯。

## 16. 风险与对策

### 16.1 大模型幻觉

风险：系统生成不存在的结论或过度概括。

对策：

- 所有结构化对象必须绑定证据。
- 标记置信度。
- 对无证据内容使用“推测”标签。
- 关键变更进入用户确认队列。

### 16.2 场景膨胀

风险：每个场景都新增一套逻辑，产品变复杂。

对策：

- 坚持统一信息模型。
- 场景差异通过 Profile 表达。
- 只有高频、稳定、可复用的能力才进入主流程。

### 16.3 用户不愿整理

风险：如果每次都需要用户大量校对，产品会失去价值。

对策：

- 默认给出可用状态。
- 只让用户处理高影响变更。
- 编辑行为反向优化 Workspace 规则。

### 16.4 隐私与合规

风险：录音内容可能涉及商业、个人或敏感信息。

对策：

- Workspace 级权限。
- 可删除原始音频。
- 敏感信息标记。
- 企业版支持私有化或本地化部署。

## 17. 技术实现建议

### 17.1 模块

```text
api/
  上传、Workspace、Record、StateObject、ChangeEvent

pipeline/
  转写、切分、抽取、合并、渲染

profiles/
  会议、客户、个人、访谈、课程

storage/
  原始音频、转写文本、结构化对象、证据锚点

ui/
  Inbox、Timeline、State Page、Change Review、Evidence View
```

### 17.2 数据存储

建议组合：

- 关系数据库：存 Workspace、Record、StateObject、ChangeEvent。
- 对象存储：存音频文件。
- 向量索引：用于相似片段和相似对象检索。
- 全文索引：用于关键词搜索和证据定位。

### 17.3 LLM 输出约束

所有 Agent 输出必须使用 JSON Schema 约束，避免自由文本直接进入状态页。

关键字段包括：

- object_type
- title
- summary
- status
- evidence_segment_ids
- confidence
- uncertainty_reason
- suggested_change_type

## 18. 典型用户流程

### 18.1 第一次使用

1. 用户创建 Workspace：“RecordFlow 产品讨论”。
2. 选择 Profile：“项目会议”。
3. 上传第一段录音。
4. 系统生成摘要、任务、决策、问题。
5. 用户确认关键结构化结果。
6. 系统生成第一版 State Page。

### 18.2 第二次录音

1. 用户继续上传第二段录音。
2. 系统自动识别这是同一 Workspace 的新增 Record。
3. 系统生成“本次变化”。
4. 用户看到：
   - 新增了两个任务。
   - 一个旧任务截止时间变化。
   - 一个旧问题已经被回答。
   - 一个新风险出现。
5. State Page 自动更新。

### 18.3 回溯查询

用户问：

```text
“我们为什么决定先做会议场景？”
```

系统回答：

```text
因为会议场景最容易体现连续录音的增量价值：用户不是只需要一篇转写稿，而是需要持续维护任务、决策、风险和未决问题。

证据：
- 2026-04-29 录音 00:03:12-00:04:20
- 2026-04-30 录音 00:11:08-00:11:46
```

## 19. 路线图

### V0：文本导入原型

- 支持粘贴转写文本。
- 支持 Workspace。
- 支持 Profile。
- 支持结构化抽取。
- 支持 State Page。
- 支持增量变化。

目标：验证“增量状态页”是否成立。

### V1：录音上传版本

- 接入转写服务。
- 支持音频证据回放。
- 支持低置信度片段标记。
- 支持用户编辑结构化结果。

目标：形成完整录音工作流。

### V2：团队协作版本

- 支持多人 Workspace。
- 支持任务负责人。
- 支持评论和确认。
- 支持导出会议纪要、客户跟进记录、调研报告。

目标：进入真实团队工作流。

### V3：生态集成版本

- 集成日历、飞书、企业微信、Notion、CRM、项目管理工具。
- 支持行业 Profile 市场。
- 支持模板化输出。

目标：让 RecordFlow 成为语音信息进入业务系统的入口。

## 20. 最小可行产品定义

最小可行产品可以被压缩成一句话：

> 用户把同一主题的多段录音或转写文本连续导入后，系统自动维护一个带证据的状态页，并展示每次新增、更新、冲突和待处理事项。

只要这个体验成立，产品就有继续扩展的基础。

## 21. 结论

RecordFlow 的创新点不是“用 AI 写更漂亮的纪要”，而是把录音从一次性文件变成连续信息流。

它的产品核心是：

- 统一信息底座
- 多场景 Profile
- 增量合并
- 状态页
- 证据锚点

这个方向足够通用，可以覆盖会议、客户、个人、访谈、课程等场景；同时又足够清晰，不需要为每个场景堆一套复杂系统。

真正应该坚持的产品判断是：

> 录音的终点不应该是文字稿，而应该是可持续更新的现实状态。
