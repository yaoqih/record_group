# RecordFlow Digest / State / Harness 设计方案

版本：V0.2  
日期：2026-05-05  
目标：把单次录音处理从“抽几个对象”升级为“高信息量 Record Digest + 可增量维护 State Objects”，同时保持 MVP 架构简洁。

## 1. 结论

RecordFlow 当前不应直接引入重型多智能体框架。更适合的路线是：

```text
固定流水线
  +
Skill Registry
  +
Harness Trace
  +
类型化输出
  +
Review Queue
```

也就是把 Agent 能力做成可替换的处理技能，而不是让多个 Agent 自由协作。

推荐主链路：

```text
ASR Evidence
  ↓
Record Digest Plan
  ↓
Chunk Notes
  ↓
Hierarchical Record Digest
  ↓
Candidate State Objects
  ↓
Change Events
  ↓
State Object Index
  ↓
Review Queue
```

## 2. 框架选择

### 2.1 Claude / Agent Skills

适合借鉴：

- 把复杂能力封装成可发现、可版本化、可复用的 Skill。
- Skill 里面放 prompt、schema、示例、验证规则和少量工具代码。
- 运行时按任务选择 Skill，而不是把所有规则塞进一个巨型 prompt。

RecordFlow 的对应设计：

```text
record_digest_skill
  digest_plan_schema
  chunk_note_schema
  merge_rules
  output_templates

state_object_skill
  object_specs
  matching_rules
  merge_rules
  review_rules

edit_patch_skill
  patch_ops
  validation_rules
```

### 2.2 OpenAI Agents SDK / Guardrails / Tracing

适合借鉴：

- typed output。
- guardrails。
- tracing。
- tool 调用边界。

RecordFlow 的对应设计：

```text
每一步输入输出都有 schema
每个对象必须绑定 evidence
每次处理写 trace
高风险变化不直接应用，进入 review
```

### 2.3 LangGraph

适合后期：

- 长流程 checkpoint。
- human-in-the-loop。
- 复杂分支恢复。
- 多步骤状态机。

MVP 暂不引入。现在用 `jobs` 表和可重跑步骤足够。等出现“用户审批后继续多步执行”的强需求，再考虑迁移。

### 2.4 Pydantic AI / Typed Agent

适合借鉴：

- 强类型输出。
- schema-first agent。
- 失败时重试或降级。

RecordFlow 当前已经是 dataclass + schema 风格。MVP 先保持轻量，避免新增框架依赖。

## 3. Record Digest：自顶向下生成

Record Digest 不是普通摘要。它是单次录音的信息包，负责让用户理解“这次会议到底发生了什么”。

### 3.1 为什么自顶向下

长录音直接让模型总结会出现三个问题：

- 输入很长，输出能力不足，容易压成空泛摘要。
- 模型会过早丢弃细节，后面无法恢复。
- 章节结构不稳定，不利于编辑和增量回放。

更好的方式是先生成章节计划，再分块填充：

```text
全文统计
  ↓
生成 DigestPlan
  ↓
按章节映射 chunk
  ↓
生成 ChunkNote
  ↓
合并成 DigestSection
  ↓
生成 RecordDigest
```

### 3.2 层级数量

根据转写长度控制层级：

| 文本规模 | 推荐结构 |
| --- | --- |
| 0-6k 字符 | one_line + sections |
| 6k-24k 字符 | one_line + chapters + sections |
| 24k+ 字符 | one_line + parts + chapters + sections |

MVP 先实现前两档。超长录音可以通过多次 Record 或后续 async job 分批处理。

### 3.3 DigestPlan

`DigestPlan` 是自顶向下结构，先于摘要内容产生：

```json
{
  "engine": "top_down_digest_v1",
  "strategy": "top_down_sections",
  "levels": ["chapter", "section"],
  "source_stats": {
    "character_count": 19804,
    "topic_block_count": 46,
    "candidate_count": 12
  },
  "outline": [
    {
      "id": "outline_chapter_001",
      "level": "chapter",
      "title": "会议开场与议程",
      "children": []
    }
  ]
}
```

### 3.4 ChunkNote

每个 chunk 不直接写最终摘要，而是产出高密度 notes：

```json
{
  "chunk_index": 0,
  "heading_hint": "会议开场与议程",
  "key_points": [],
  "decisions": [],
  "tasks": [],
  "questions": [],
  "risks": [],
  "requirements": [],
  "quotes": [],
  "uncertainties": [],
  "evidence_segment_ids": []
}
```

### 3.5 DigestSection

章节内容必须具体，但不能脱离证据：

```json
{
  "title": "会议开场与议程",
  "summary": "本段说明会议目标、流程、时间安排以及需要在会议中形成的远程控制概念决策。",
  "key_points": [
    "会议预计持续约 40 分钟。",
    "议程包括回顾上次会议、三个展示、形成远程控制概念决策。"
  ],
  "decisions": [],
  "open_questions": [],
  "evidence_segment_ids": ["seg_001", "seg_002"]
}
```

### 3.6 修改方式

Digest 修改不做全文重写，而走 patch：

| 操作 | 含义 |
| --- | --- |
| append | 给章节补充要点 |
| replace | 替换某一条 summary/key_point |
| split | 拆分章节 |
| merge | 合并章节 |
| move | 移动条目到别的章节 |
| link_evidence | 绑定或修正证据 |
| mark_conflict | 标记冲突或不确定 |

用户可以自然语言修改：

```text
这里不是决定，只是一个讨论方向。
把成本风险展开一下。
这个章节应该拆成材料选择和交互设计两部分。
```

系统内部转成 `DigestPatch`，避免整篇重写。

## 4. State Objects：当前状态索引

State Objects 不是另一份摘要，而是 Workspace 的长期状态索引。

它们回答的是：

```text
现在有哪些任务？
现在有哪些决策？
当前风险是什么？
客户需求变了吗？
哪些问题还没解决？
```

### 4.1 和 Digest 的关系

```text
Record Digest
  解释本次录音

State Objects
  维护跨多次录音后的当前状态

Change Events
  记录本次录音如何改变当前状态
```

Digest 里的章节可读性更强，State Objects 查询性更强。二者都绑定 Evidence。

### 4.2 CRUD 语义

MVP 的 StateObject 操作：

| 操作 | 行为 |
| --- | --- |
| create | 新增对象 |
| update | 更新字段，version + 1 |
| close | 状态改为 closed |
| reopen | 状态改回 open |
| archive | 软删除，状态改为 archived |
| clarify | 追加说明或证据 |

不做硬删除。所有变化都通过 ChangeEvent 留痕。

### 4.3 查询语义

State Objects 是索引，所以查询比展示更重要：

```text
workspace_id
type
status
title keyword
payload.owner
payload.due_date
payload.scenario
payload.entity_type
```

MVP API：

```text
GET /workspaces/{workspace_id}/state
GET /workspaces/{workspace_id}/state/objects?type=Task&status=open
PATCH /state/objects/{object_id}
POST /state/objects/{object_id}/close
POST /state/objects/{object_id}/archive
```

### 4.4 和现有体系融合

现有 `StateObject`、`ChangeEvent` 可以保留。需要补充的是：

- Digest 内部增加 `plan`、`sections`、`evidence_index`。
- StateObject 增加统一 CRUD 方法。
- API 增加对象级更新和查询。
- ChangeEvent 记录用户修改和系统修改。

MVP 不新增复杂表。先把扩展字段放在已有 dataclass / JSON payload 中。

## 5. Skill Registry

为了后续提高上限，建议在代码里引入轻量 Skill 概念。

```text
ProcessingSkill
  name
  version
  input_contract
  output_contract
  run()
  validate()
```

MVP 先不做动态加载，只做模块内注册：

```text
record_digest_v1
state_extract_v1
state_merge_v1
state_edit_v1
```

好处：

- 后续可以替换某个 skill，不改主流水线。
- 可以给每个 skill 做 eval。
- 可以记录每个 skill 的输入、输出和耗时。
- 可以把 rule-based 和 LLM-based 实现并存。

## 6. Harness Trace

每次处理应该能回答：

```text
用了哪个 skill？
输入是什么？
输出是什么？
哪些 evidence 被引用？
哪些结果进入 review？
失败在哪里？
```

MVP 先在内存 digest 里返回 `processing_trace`，后续再落表。

```json
{
  "skill": "record_digest_v1",
  "version": "0.1",
  "input_chars": 19804,
  "output_sections": 8,
  "evidence_count": 25
}
```

当前代码已经落地为：

```text
recordflow_agent/harness.py
  SkillSpec
  SkillRegistry
  SkillHarness
  HarnessEvent

recordflow_agent/pipeline.py
  process_record(..., harness=None)
```

默认注册四个处理技能：

| Skill | 职责 | MVP 实现 |
| --- | --- | --- |
| segment_topics | 把 TranscriptSegment 切成 TopicBlock | 规则函数 `segment_topics` |
| extract_objects | 从 TopicBlock 提取 CandidateObject | 规则函数或可选 LLMExtractor |
| merge_changes | 合并 CandidateObject 到 StateObject / ChangeEvent | 规则函数 `merge_changes` |
| render_digest | 生成 RecordDigest plan / sections / evidence_index | 确定性 top-down 引擎，可选 LLMDigestRenderer 改写章节 |

`process_record` 默认创建 `SkillHarness`。调用方也可以传入自定义 harness，用于测试、替换 skill 或后续 A/B eval。

每个 harness 事件会追加到 `RecordDigest.processing_trace`：

```json
{
  "kind": "skill_harness",
  "skill": "extract_objects",
  "version": "0.1",
  "status": "ok",
  "elapsed_ms": 3,
  "input": {
    "topic_block_count": 12,
    "profile": "project_meeting",
    "extractor": null
  },
  "output": {
    "candidates": 5
  },
  "error": null
}
```

这里刻意只记录摘要化输入输出，不保存全文、音频、密钥或大对象，避免 trace 反过来制造存储和隐私复杂度。

## 7. MVP 实施范围

本轮实施只做必要闭环：

1. 新增顶层 Digest 数据结构。
2. 实现 deterministic top-down Digest planner。
3. 用现有 segment/topic/evidence 生成 sections。
4. API 返回 digest 的 `plan`、`sections`、`evidence_index`。
5. 增加 StateObject 查询和 patch API。
6. StateObject patch 写 ChangeEvent 并 version + 1。
7. 用长会议样例和两次会议增量样例测试。
8. 新增轻量 Skill Registry / Harness Trace，让 pipeline 的关键步骤可替换、可观测、可测试。
9. 新增 `general_record` 通用 Profile，启用 13 类 State Object。
10. 对显式标签格式实现规则抽取：`事实：`、`决定：`、`任务：`、`问题：`、`风险：`、`需求：`、`异议：`、`想法：`、`洞察：`、`知识：`、`原话：`、`时间线：`、`实体：`。
11. 给 CandidateObject 写入 `merge_key`，让跨多次 Record 的增量合并可预测。
12. 支持 Task 更新截止时间、Risk/Question 等对象关闭，ChangeEvent 区分 `create`、`update`、`close`、`duplicate`。
13. Digest `plan` 和 section 增加 `object_counts`，便于 UI 直接展示每层结构对象分布。
14. API 增加对象状态操作：`close`、`reopen`、`archive`、`clarify`。

不做：

- 不引入 LangGraph。
- 不新增向量库。
- 不做复杂动态 skill 加载。
- 不做端到端全文 LLM 统稿；MVP 采用“确定性 outline/evidence/coverage + 可选 LLM 章节改写”，失败时自动退回确定性 Digest。
- 不做 UI 大改。
- 不做复杂实体消歧、跨语言同义归一和冲突自动裁决；这些进入 Review/Eval 后续阶段。

## 8. 成功标准

测试样例需要证明：

- 长会议能生成多章节 Digest，而不是只有一句摘要。
- Digest section 带 evidence。
- 两次会议后 Task 能更新而不是重复创建。
- 可以按 type/status 查询 StateObject。
- 可以 patch StateObject，并生成 ChangeEvent。
- 旧 ASR 和 Evidence 不被修改。
- 通用录音样例能抽取 13 类对象并持久化为 StateObject。
- 复用同一对象时按 `merge_key` 更新，不重复创建。
- 用户可通过 API close / reopen / clarify StateObject。
