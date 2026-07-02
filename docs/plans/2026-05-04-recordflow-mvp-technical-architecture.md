# RecordFlow MVP 技术实现方案

版本：V0.1  
日期：2026-05-04  
主题：在 MVP 阶段用最小复杂度实现连续录音的增量结构化整理

## 1. 结论先行

RecordFlow 的 MVP 不应该做成一个复杂的“多智能体自治系统”。更稳的技术路线是：

> 轻量 Harness + 固定处理流水线 + 类型化结构输出 + 人工确认关键变更。

也就是说，MVP 阶段要把 Agent 当成可替换的处理器，而不是让多个 Agent 自由协商。

推荐架构：

```text
Web/App
  ↓
API 层
  ↓
Record Processing Pipeline
  ↓
Structured State Store
  ↓
Review Queue + State Page
```

Agent 数量控制在 4 个以内：

```text
Segment Agent      主题切分
Extract Agent      结构抽取
Merge Agent        增量合并
Render Agent       场景化输出
```

不要在 MVP 阶段引入“24 个角色 Agent”“自由路由”“长期后台自治执行”“复杂 Swarm 协作”。这些能力看起来先进，但会把早期验证重点从产品价值转移到框架治理。

## 2. 对当前智能体框架的判断

### 2.1 Harness Engineering：真正应该借鉴的是控制系统

Harness Engineering 的核心启发不是“让 Agent 多写代码”，而是：

- 模型不是系统，模型之外的工具、上下文、验证、权限、日志、反馈回路才决定可靠性。
- 人的工作从“直接写结果”转向“设计环境、约束、反馈和验收标准”。
- 好的 Agent 系统不是更自由，而是更可控、更可回放、更容易纠错。

对 RecordFlow 的落地启发：

```text
Prompt 不是核心资产。
Schema、Profile、Evidence、Review、Eval 才是核心资产。
```

MVP 应该先建设这些 Harness 能力：

- 固定输入输出 Schema。
- 每一步持久化中间结果。
- 每个结论绑定 Evidence。
- 高影响变更进入 Review Queue。
- 每次处理有 Trace，可以复盘为什么这样合并。
- 一组固定测试录音，用来评估不同 Prompt 和模型。

### 2.2 OpenClaw / Claw 类系统：借鉴“后台持续性”，不要照搬“全自治”

Claw 类系统强调长期运行、后台心跳、任务队列、个人工具连接和持续记忆。

这对 RecordFlow 有启发，但 MVP 不应做成 24/7 自治助手。

应该借鉴：

- 后台任务队列。
- 持久化 Workspace 记忆。
- 定期重跑低置信度内容。
- 只把需要用户判断的事项浮出水面。

不应照搬：

- 长期无人值守执行真实外部操作。
- 任意工具权限。
- 多 Agent 自由协作。
- 用户还没信任产品前就自动修改外部系统。

RecordFlow 的早期“后台能力”应限制在信息处理范围：

```text
转写完成后自动结构化
新 Record 进入后自动生成 ChangeEvent
用户确认后更新 State Page
低置信度对象进入待确认列表
```

### 2.3 LangGraph：适合后期，不是 MVP 必选

LangGraph 的强项是长流程、状态图、持久化执行、人类介入和可恢复工作流。

RecordFlow 未来如果出现以下需求，可以引入 LangGraph：

- 一个录音处理流程需要跨多小时或多天。
- 用户在流程中间审批后继续执行。
- 处理图需要复杂分支和循环。
- 多个 Agent 的执行状态需要强一致恢复。

但 MVP 可以先用更简单的方式实现：

```text
Postgres job_runs 表
  status: pending / running / failed / completed
  current_step
  input_hash
  output_refs
  error_message
```

这个设计已经能满足早期的可恢复、可重跑、可调试需求。

### 2.4 OpenAI Agents SDK / Pydantic AI：适合作为轻量执行层

如果需要一个现成 Agent SDK，优先考虑轻量、类型友好的执行层，而不是重型多 Agent 框架。

MVP 更需要：

- Structured Output。
- Guardrails。
- Tracing。
- Tool calling。
- 少量 handoff 或 agents-as-tools。

不需要：

- 复杂 Agent 社交关系。
- 高度动态任务规划。
- 一堆角色设定。
- 多轮 Agent 辩论。

### 2.5 AutoGen / CrewAI：暂不作为主架构

AutoGen、CrewAI 适合研究协作型、多 Agent 实验型、企业流程自动化型系统。

RecordFlow MVP 的核心任务不是“多个 Agent 协作完成开放目标”，而是“稳定地把录音转成可信状态更新”。这更像确定性流水线加少量 LLM 判断。

因此不建议早期把主链路绑死在 AutoGen 或 CrewAI 上。可以后期在以下场景中局部引入：

- 访谈调研需要多个分析视角交叉验证。
- 大客户版需要多个业务 Agent 共同生成报告。
- 企业工作流需要自动同步 CRM、项目管理、知识库。

## 3. 用户场景的真实需求

MVP 的关键不是覆盖所有高级功能，而是抓住不同人群的共同底层需求。

### 3.1 项目会议用户

表面需求：

- 会议纪要。
- 任务清单。
- 决策记录。

真实需求：

- 我现在该推进什么？
- 上次说的事情变了吗？
- 谁承诺了什么？
- 哪些问题还卡着？
- 这个决策是怎么来的？

产品重点：

```text
ChangeEvent + Task + Decision + Question + Risk
```

### 3.2 客户跟进用户

表面需求：

- 客户通话总结。
- 跟进记录。

真实需求：

- 客户真正关心什么？
- 客户有哪些异议？
- 我们承诺过什么？
- 下一次沟通应该问什么？
- 客户说过的原话在哪里？

产品重点：

```text
Requirement + Objection + Commitment + NextAction + Quote
```

### 3.3 个人口述用户

表面需求：

- 把录音变成文字。
- 整理想法。

真实需求：

- 不要让我整理。
- 帮我把反复出现的想法归到一起。
- 哪些想法可以发展成文章、方案或待办？
- 我最近一直在纠结什么？

产品重点：

```text
Idea + Insight + Topic + Task
```

### 3.4 用户访谈 / 调研人员

表面需求：

- 访谈摘要。
- 调研报告。

真实需求：

- 多个受访者之间有什么共性和差异？
- 哪些观点有原话证据？
- 哪些是假设，哪些是已经被多次验证的事实？
- 哪些问题下一轮还要追问？

产品重点：

```text
Quote + Insight + Evidence + Question + Theme
```

### 3.5 课程学习用户

表面需求：

- 课程笔记。
- 知识点总结。

真实需求：

- 这节课讲了哪些概念？
- 哪些地方我还没理解？
- 有哪些案例和步骤可以复用？
- 如何复习和实践？

产品重点：

```text
Knowledge + Question + Example + PracticeTask
```

### 3.6 所有场景的共同需求

不同场景最终都收敛到四个问题：

```text
What happened?     这次发生了什么？
What changed?      相比之前改变了什么？
What matters?      哪些内容重要？
Where is proof?    依据在哪里？
```

MVP 必须优先打透这四个问题。

## 4. MVP 总体架构

### 4.1 模块划分

```text
frontend/
  Workspace
  Record Inbox
  Record Digest
  Change Review
  State Page
  Evidence Viewer

backend/
  Workspace API
  Record API
  StateObject API
  Review API
  Ask API

pipeline/
  normalize_transcript
  segment_topics
  extract_objects
  match_candidates
  propose_changes
  render_digest
  apply_review

storage/
  postgres
  object_storage
  vector_index
  full_text_index

harness/
  schemas
  profiles
  prompts
  validators
  traces
  eval_sets
```

### 4.2 数据流

```text
用户上传录音或转写文本
  ↓
Record 创建
  ↓
转写或文本标准化
  ↓
切分 TranscriptSegment
  ↓
生成 TopicBlock
  ↓
抽取 CandidateObject
  ↓
匹配历史 StateObject
  ↓
生成 ChangeEvent
  ↓
生成 RecordDigest
  ↓
高影响变化进入 Review Queue
  ↓
用户确认后更新 State Page
```

### 4.3 MVP 技术栈建议

优先选择简单、稳定、可替换的技术栈：

```text
前端：Next.js 或 React
后端：FastAPI 或 Node.js API
数据库：Postgres
向量：pgvector
任务队列：Celery / RQ / BullMQ
文件存储：本地文件或 S3 兼容对象存储
LLM 调用：统一 ModelClient 封装
结构校验：Pydantic / Zod
可观测：run_traces 表 + JSON 日志
```

MVP 不建议一开始拆微服务。一个单体后端加异步任务队列足够。

## 5. 核心数据模型

### 5.1 Workspace

```json
{
  "id": "ws_001",
  "name": "RecordFlow 产品讨论",
  "profile": "project_meeting",
  "description": "围绕 RecordFlow 的产品和技术设计讨论",
  "created_at": "2026-05-04T10:00:00Z"
}
```

### 5.2 Record

```json
{
  "id": "rec_001",
  "workspace_id": "ws_001",
  "source_type": "text",
  "title": "第 3 次产品讨论",
  "recorded_at": "2026-05-04T10:00:00Z",
  "status": "processed"
}
```

### 5.3 TranscriptSegment

```json
{
  "id": "seg_001",
  "record_id": "rec_001",
  "speaker": "user",
  "start_time": "00:01:12",
  "end_time": "00:01:45",
  "text": "每一类结构如何增量式更新还缺少具体细节。",
  "confidence": 0.93
}
```

### 5.4 TopicBlock

```json
{
  "id": "topic_block_001",
  "record_id": "rec_001",
  "topic": "结构化对象增量更新",
  "summary": "讨论如何让 Fact、Task、Decision 等对象具备可实现的更新规则。",
  "segment_ids": ["seg_001", "seg_002"],
  "importance": "high"
}
```

### 5.5 StateObject

```json
{
  "id": "obj_001",
  "workspace_id": "ws_001",
  "type": "Task",
  "title": "补充对象级增量更新规则",
  "status": "open",
  "payload": {
    "owner": "AI 助手",
    "action": "更新产品文档",
    "due_date": null
  },
  "evidence_ids": ["ev_001"],
  "version": 2
}
```

### 5.6 ChangeEvent

```json
{
  "id": "chg_001",
  "workspace_id": "ws_001",
  "record_id": "rec_001",
  "change_type": "update",
  "target_object_id": "obj_001",
  "summary": "任务范围从补充对象枚举扩展为补充对象实现规则、场景组合和多层输出。",
  "requires_review": true,
  "evidence_ids": ["ev_001", "ev_002"]
}
```

### 5.7 EvidenceAnchor

```json
{
  "id": "ev_001",
  "record_id": "rec_001",
  "segment_id": "seg_001",
  "start_time": "00:01:12",
  "end_time": "00:01:45",
  "quote": "每一类结构如何增量式更新还缺少具体细节。"
}
```

## 6. Agent 设计

### 6.1 Segment Agent

职责：

- 把转写文本切成主题块。
- 识别主题边界、讨论阶段、上下文转折。

输入：

```text
TranscriptSegment[]
Workspace Profile
```

输出：

```text
TopicBlock[]
```

复杂度控制：

- 不做历史合并。
- 不抽取任务。
- 只负责“这次录音内部结构”。

### 6.2 Extract Agent

职责：

- 从 TopicBlock 中抽取 CandidateObject。
- 输出严格 JSON。
- 每个对象必须引用 evidence_segment_ids。

输入：

```text
TopicBlock
SceneProfile
ObjectSchemas
```

输出：

```text
CandidateObject[]
```

复杂度控制：

- 一次只处理一个 TopicBlock。
- 不直接修改 StateObject。
- 不判断是否和历史重复。

### 6.3 Merge Agent

职责：

- 将 CandidateObject 与历史 StateObject 对齐。
- 判断 create、update、duplicate、conflict、close、clarify。
- 生成 ChangeEvent。

输入：

```text
CandidateObject
TopK similar StateObject
MergePolicy
```

输出：

```text
ChangeEvent
```

复杂度控制：

- 先用确定性检索找候选，再让 LLM 判断。
- 不让 LLM 在全库里自由搜索。
- 高影响变化只生成建议，不自动写入 State Page。

### 6.4 Render Agent

职责：

- 生成 RecordDigest。
- 生成 StatePagePatch。
- 根据不同 Profile 输出不同视图。

输入：

```text
TopicBlock[]
CandidateObject[]
ChangeEvent[]
CurrentStatePage
SceneProfile
```

输出：

```text
RecordDigest
StatePagePatch
```

复杂度控制：

- 只基于结构化对象和证据渲染。
- 不重新从全文自由发挥。
- 渲染结果标记哪些内容来自事实，哪些来自归纳。

## 7. Harness 设计

### 7.1 为什么 RecordFlow 需要 Harness

RecordFlow 的风险不是模型不会写摘要，而是：

- 把没有证据的内容写成事实。
- 把两个相似任务错误合并。
- 把客户异议覆盖掉。
- 把旧决策删除，导致历史不可追溯。
- 每次模型输出格式不一致，后端无法稳定消费。

Harness 要解决的是这些系统性问题。

### 7.2 MVP Harness 组成

```text
Profile Registry
  每个场景的抽取重点、状态页模板、合并策略。

Schema Registry
  StateObject、ChangeEvent、RecordDigest 的 JSON Schema。

Prompt Registry
  每个 Agent 的版本化 Prompt。

Validator
  校验 LLM 输出结构、证据引用、字段合法性。

Trace Store
  记录每次处理的输入、输出、模型、Prompt 版本、耗时和错误。

Review Policy
  决定哪些变化自动接受，哪些变化需要用户确认。

Eval Set
  固定样例集，用于测试 Prompt、模型和合并策略。
```

### 7.3 关键约束

每个 LLM 步骤都必须满足：

- 有明确输入。
- 有 JSON Schema 输出。
- 有 validator。
- 有 trace。
- 可重跑。
- 可回放。
- 不直接产生不可追溯的最终状态。

## 8. 增量合并实现

### 8.1 不要让 LLM 从零判断一切

增量合并应分三步：

```text
确定性候选召回
  ↓
LLM 判断关系
  ↓
规则执行更新
```

### 8.2 候选召回

对每个 CandidateObject，先用规则缩小范围：

```text
workspace_id 相同
type 相同或可兼容
topic 相近
status 未关闭或近期关闭
```

再用相似度召回：

```text
title embedding
summary embedding
payload normalized key
full-text search
```

只把 Top 5-10 个候选交给 Merge Agent。

### 8.3 LLM 合并判断

Merge Agent 只回答一个有限问题：

```text
这个 CandidateObject 和这些历史对象是什么关系？

可选：
- create
- update
- duplicate
- conflict
- close
- clarify
- supersede
```

输出必须包含：

```json
{
  "relation": "update",
  "target_object_id": "obj_001",
  "field_changes": {
    "due_date": {
      "from": "周五",
      "to": "周三下班前"
    }
  },
  "confidence": 0.82,
  "requires_review": true,
  "reason": "新录音明确修改了截止时间",
  "evidence_ids": ["ev_001"]
}
```

### 8.4 规则执行

真正修改 StateObject 的逻辑由代码执行，不由 LLM 直接执行。

```text
LLM 负责判断。
代码负责写入。
用户负责确认高风险变化。
```

## 9. Review Queue 设计

MVP 必须有 Review Queue。否则用户会不信任自动更新。

### 9.1 自动接受

可以自动接受：

- 高置信度 Quote。
- 普通 Fact。
- TimelineEvent。
- 低影响补充说明。

### 9.2 需要确认

必须进入 Review Queue：

- Decision 新增或替代。
- Task owner、due_date、status 变化。
- Requirement 范围变化。
- Risk 升级。
- conflict。
- 低置信度 Insight。

### 9.3 Review 操作

用户只需要三个动作：

```text
接受
编辑后接受
忽略
```

不要在 MVP 做复杂审批流。

## 10. 多场景支持策略

用户希望“全部都要”，但 MVP 要避免每个场景做一套系统。

推荐策略：

```text
统一主链路
  +
五个轻量 Profile
  +
三个重点验证场景
```

### 10.1 五个 Profile 都保留

- 项目会议。
- 客户跟进。
- 个人口述。
- 用户访谈。
- 课程学习。

### 10.2 MVP 重点验证三个场景

优先验证：

1. 项目会议
   - 最能体现增量状态页。

2. 客户跟进
   - 最能体现 Quote、Requirement、Objection 和 NextAction。

3. 用户访谈
   - 最能体现 Evidence 和跨 Record 归纳。

个人口述和课程学习先用同一条技术链路提供轻量模板，不做过深功能。

## 11. MVP 交付边界

### 11.1 第一阶段：文本导入 MVP

先不做音频上传，直接支持转写文本导入。

目标：

- 验证结构抽取。
- 验证增量合并。
- 验证 State Page 是否有价值。
- 验证 Review Queue 是否降低不信任。

功能：

- 创建 Workspace。
- 选择 Profile。
- 粘贴一段转写文本。
- 自动生成 RecordDigest。
- 抽取 StateObject。
- 生成 ChangeEvent。
- 用户确认后更新 State Page。

### 11.2 第二阶段：音频上传

加入音频能力：

- 上传录音。
- ASR 转写。
- 说话人分离。
- 音频时间戳。
- Evidence 播放定位。

### 11.3 第三阶段：Ask Workspace

加入面向状态页的问答：

- 当前有哪些未决问题？
- 这个客户最大的异议是什么？
- 哪些任务已经延期？
- 某个决策的依据是什么？

Ask Workspace 必须优先基于 StateObject 和 Evidence，不要直接对全部转写做 RAG。

## 12. 技术路线选择

### 12.1 推荐路线

```text
自研轻量 Pipeline
  +
结构化 LLM 调用
  +
Postgres 状态存储
  +
pgvector 候选召回
  +
Review Queue
```

这是最适合 MVP 的方案。

优点：

- 复杂度最低。
- 每一步可解释。
- 后期可以换模型、换 Agent SDK。
- 不被框架抽象绑死。

### 12.2 何时引入 OpenAI Agents SDK

如果希望快速获得 tracing、handoff、guardrails，可以在 Agent 执行层引入。

但使用方式应保持克制：

```text
每个 Agent 是一个工具化处理器。
主流程仍由业务代码编排。
```

不要让 SDK 成为产品架构本身。

### 12.3 何时引入 LangGraph

当流程变成长事务，并需要断点恢复、人类介入后继续执行、复杂分支循环时，再引入 LangGraph。

MVP 先用 `job_runs` 表即可。

### 12.4 不建议早期引入完整多 Agent 框架

暂不建议把 AutoGen、CrewAI、OpenClaw 作为主依赖。

原因：

- RecordFlow 当前不是开放式任务执行器。
- 核心难点是信息结构和增量状态，不是 Agent 协作。
- 框架会带来新的抽象、调试成本和团队学习成本。
- MVP 阶段最重要的是验证用户是否真的需要 State Page。

## 13. 评估体系

### 13.1 MVP 评估集

准备 15 组样例：

```text
项目会议 3 组
客户跟进 3 组
个人口述 3 组
用户访谈 3 组
课程学习 3 组
```

每组至少 3 次连续 Record，用来测试增量合并。

### 13.2 指标

| 指标 | 含义 |
| --- | --- |
| extraction_precision | 抽取出的对象是否真的存在于录音 |
| evidence_coverage | 结构化对象是否有证据 |
| merge_accuracy | 新旧对象是否正确合并 |
| review_burden | 用户需要确认的比例是否过高 |
| state_page_usefulness | 状态页是否比读全文更有用 |
| correction_rate | 用户编辑或忽略的比例 |

### 13.3 MVP 成功线

MVP 不要求全自动正确，但要达到：

- 90% 以上的正式对象有 Evidence。
- 高影响变更必须可解释。
- 用户连续导入 3 次后，能通过 State Page 理解当前状态。
- 用户确认项数量不能超过抽取对象的 30%。

## 14. 复杂度控制原则

### 14.1 只做一条主链路

不要每个场景一条 pipeline。

```text
统一 pipeline
  +
SceneProfile
  +
不同输出模板
```

### 14.2 只让 LLM 做判断，不让 LLM 做写入

LLM 可以：

- 切分。
- 抽取。
- 判断关系。
- 生成摘要。

LLM 不可以：

- 直接改数据库。
- 删除历史状态。
- 自动覆盖高影响字段。
- 无证据生成事实。

### 14.3 先做文本，再做音频

音频上传、转写、说话人分离、播放器定位都会增加复杂度。

如果文本导入都不能证明 State Page 有价值，音频能力做得再好也没有意义。

### 14.4 先做编辑，不做自动学习

MVP 先支持用户编辑结构化结果。

不要一开始做复杂个性化学习。可以先记录用户编辑日志，为后续优化 Prompt 和 Profile 提供数据。

## 15. 推荐迭代计划

### Sprint 1：文本导入与基础状态页

- Workspace。
- Profile。
- Record 文本导入。
- Segment Agent。
- Extract Agent。
- StateObject 列表。

验收：

- 单次录音能生成 TopicBlock 和结构化对象。

### Sprint 2：增量合并与 ChangeEvent

- 历史对象检索。
- Merge Agent。
- ChangeEvent。
- Review Queue。
- State Page Patch。

验收：

- 连续三次同主题录音能显示新增、更新、重复、冲突。

### Sprint 3：场景模板与证据链

- 项目会议 Profile。
- 客户跟进 Profile。
- 用户访谈 Profile。
- Evidence Viewer。
- RecordDigest 五层输出。

验收：

- 三类核心场景都能跑通。

### Sprint 4：音频上传与回放

- 音频上传。
- ASR。
- 时间戳。
- 证据片段回放。

验收：

- 用户点击对象证据可以回到音频片段。

## 16. 最小实现形态

如果要把系统压到最小，可以先做成：

```text
一个 Web 页面
一个 API 服务
一个 Postgres
一个异步 worker
四个 Agent prompt
五个 Profile JSON
一套 JSON Schema
```

这已经足够验证核心产品命题。

## 17. 不做什么

MVP 不做：

- 多 Agent 自由聊天。
- Agent 自主规划任务树。
- Agent 自动操作外部软件。
- 多人复杂权限。
- 企业系统同步。
- 长期后台自治助手。
- 自动生成完整商业报告。
- 全量知识库 RAG。
- 复杂工作流引擎。

## 18. 最终技术判断

RecordFlow 的技术核心不是“用了多少 Agent”，而是：

```text
能不能把连续录音稳定变成可信的状态变化。
```

MVP 最应该投入的地方：

- 信息对象 Schema。
- 场景 Profile。
- Evidence 机制。
- 增量合并。
- Review Queue。
- 可回放 Trace。
- 小规模评估集。

暂时不要把复杂度投到：

- 大型多 Agent 框架。
- 开放式自治执行。
- 过多角色 Agent。
- 复杂工作流 DSL。

最合适的 MVP 架构是：

> 用产品自己的数据模型做核心，用轻量 Agent 执行层做能力补充，用 Harness 保证可靠性。

这样既能吸收当前智能体框架的先进经验，又不会在 MVP 阶段被框架复杂度拖慢。

## 19. 参考框架与资料

- OpenAI, "Harness engineering: leveraging Codex in an agent-first world", 2026-02-11.
- Martin Fowler, "Harness engineering for coding agent users", 2026-04-02.
- OpenAI Agents SDK documentation: orchestration, handoffs, tracing.
- LangGraph documentation: durable execution and human-in-the-loop workflows.
- Anthropic Engineering, "How we built our multi-agent research system", 2025-06-13.
- Microsoft AutoGen documentation.
- CrewAI documentation.
- OpenClaw public materials and NVIDIA discussion of long-running claw agents.
