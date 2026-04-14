# UAP 智能技能系统设计指南

> 基于"自动技能工匠"理念，让大模型自主为每个项目创建专属的建模与预测技能

---

## 1. 设计理念

### 1.1 核心思想

参考自动技能工匠的 DST 追踪机制，UAP 的技能系统让**大模型在对话过程中自动发现可复用的建模/预测模式，并将其沉淀为项目专属技能**。

### 1.2 与传统技能系统的区别

| 维度 | 传统方式 | UAP 智能技能 |
|------|----------|--------------|
| 技能来源 | 人工编写，预定义 | AI 自动生成，项目专属 |
| 技能粒度 | 通用粗粒度 | 领域细粒度，针对当前系统 |
| 更新方式 | 手动维护 | 对话中自动学习 |
| 存储位置 | 全局共享 | 每个项目独立 |

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         UAP 客户端                              │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │  前端界面   │    │  API 层     │    │   技能系统核心      │ │
│  │  (WebView)  │◄──►│  (UAPApi)   │◄──►│   (SkillCraft)      │ │
│  └─────────────┘    └─────────────┘    └─────────────────────┘ │
│                            ▲                     ▲              │
│                            │                     │              │
│  ┌─────────────────────────┴─────────────────────┴─────────┐ │
│  │                      服务层                                 │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │ │
│  │  │ ProjectService│  │PredictionService│ │ SkillService │  │ │
│  │  └──────────────┘  └──────────────┘  └────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            │                                    │
│  ┌─────────────────────────┴────────────────────────────────┐ │
│  │                      存储层 (本地)                          │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │ │
│  │  │ Projects │  │ Skills   │  │  Models  │  │  Results  │ │ │
│  │  │ (SQLite) │  │ (JSONL)  │  │ (JSON)   │  │ (JSONL)   │ │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └───────────┘ │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心数据结构

### 3.1 技能会话追踪 (SkillSession)

```python
class SkillSession:
    """技能生成会话 - DST 状态追踪"""
    
    session_id: str                    # 会话唯一ID
    project_id: str                    # 所属项目ID
    start_time: datetime              # 开始时间
    
    # DST 核心字段
    user_query: str                   # 用户原始问题
    intent: str                       # 识别的意图 (modeling/prediction/analysis)
    actions: List[ActionNode]         # 操作轨迹
    final_output: Any                 # 最终输出
    
    # 元数据
    status: SessionStatus             # active/completed/aborted
    corrections: int                  # 用户纠正次数
    tool_call_count: int              # 工具调用次数
    total_duration_ms: int            # 总耗时
    tokens_used: int                 # 消耗的 token 数
```

### 3.2 操作节点 (ActionNode)

```python
class ActionNode:
    """操作轨迹节点 - 技能生成的原子单位"""
    
    step_id: int
    type: ActionType                 # thought/tool_call/observation/correction
    tool_name: Optional[str]          # 工具名称
    
    # 输入输出
    input_params: dict               # 输入参数（脱敏后）
    output_summary: str              # 输出摘要（截断处理）
    
    # 执行信息
    duration_ms: int
    is_error: bool
    error_recovery: Optional[str]     # 错误恢复策略
```

### 3.3 项目技能 (ProjectSkill)

```python
class ProjectSkill:
    """项目专属技能 - 沉淀的知识资产"""
    
    skill_id: str                     # 技能唯一ID
    project_id: str                   # 所属项目
    
    # 技能元信息
    name: str                         # 技能名称
    description: str                  # 一句话描述
    category: SkillCategory           # modeling/prediction/analysis/visualization
    trigger_conditions: List[str]    # 触发条件
    
    # 技能内容
    skill_content: str                # 技能描述 (Markdown)
    steps: List[SkillStep]           # 执行步骤
    parameters: List[SkillParameter]  # 参数定义
    
    # 质量指标
    confidence: float                 # 置信度 0-1
    usage_count: int                 # 使用次数
    success_rate: float              # 成功率
    
    # 版本信息
    source_session_id: str           # 来源会话ID
    created_at: datetime
    updated_at: datetime
    version: int                     # 版本号
    is_auto_generated: bool          # 是否AI自动生成
```

### 3.4 技能步骤 (SkillStep)

```python
class SkillStep:
    """技能执行步骤"""
    
    step_number: int                 # 步骤序号
    title: str                        # 步骤标题
    description: str                  # 详细描述
    action_type: ActionType          # 执行的行动类型
    
    # 行动细节
    tool_name: Optional[str]          # 调用的工具
    parameters: dict                  # 参数字典
    prompt_template: Optional[str]    # Prompt 模板
    
    # 条件分支
    conditions: List[str]             # 执行条件
    alternatives: List[str]           # 备选方案
    
    # 预期输出
    expected_output: str
    validation_rules: List[str]       # 验证规则
```

---

## 4. 技能分类体系

### 4.1 核心技能类别

```
Skills/
├── modeling/                      # 建模技能
│   ├── variable_extraction        # 变量提取
│   ├── relation_discovery          # 关系发现
│   ├── constraint_identification   # 约束识别
│   ├── equation_construction       # 方程构建
│   └── model_validation            # 模型验证
│
├── prediction/                     # 预测技能
│   ├── trajectory_simulation       # 轨迹模拟
│   ├── trend_forecast              # 趋势预测
│   ├── anomaly_detection           # 异常检测
│   ├── regime_transition          # 状态转换识别
│   └── uncertainty_quantification  # 不确定性量化
│
├── analysis/                      # 分析技能
│   ├── sensitivity_analysis       # 敏感性分析
│   ├── stability_analysis         # 稳定性分析
│   ├── bifurcation_analysis       # 分岔分析
│   └── correlation_analysis       # 相关性分析
│
└── visualization/                # 可视化技能
    ├── time_series_plot          # 时序图绘制
    ├── phase_portrait            # 相图绘制
    ├── attractor_visualization    # 吸引子可视化
    └── heatmap_generation        # 热力图生成
```

### 4.2 技能触发条件模板

```python
TRIGGER_TEMPLATES = {
    "variable_extraction": [
        "提取系统变量",
        "识别状态变量",
        "找出哪些因素影响系统"
    ],
    "relation_discovery": [
        "变量之间的关系",
        "因果关系",
        "变量如何相互影响"
    ],
    "trajectory_simulation": [
        "模拟系统演化",
        "预测未来状态",
        "系统会如何发展"
    ],
    "anomaly_detection": [
        "检测异常",
        "识别异常行为",
        "什么时候系统会出问题"
    ]
}
```

---

## 5. 技能生成器设计

### 5.1 生成流程

```
用户对话结束
    │
    ▼
┌─────────────────┐
│ DST 触发评估    │  检查条件:
│ (Threshold)    │  - 复杂度 >= 5 步
└────────┬────────┘  - 用户纠正 > 0
         │           - 耗时 > 30s
         ▼
┌─────────────────┐
│ 价值评估        │  LLM 判断:
│ (Value Judge)   │  - 是否可复用?
└────────┬────────┘  - 是否通用模式?
         │           - 置信度 >= 0.7?
         ▼
┌─────────────────┐
│ 技能生成        │
│ (Generator)    │  调用 LLM 生成:
└────────┬────────┘  - SKILL.md 内容
         │           - 参数脱敏
         ▼
┌─────────────────┐
│ 卡片推送前端    │  WebSocket/SSE
│ (Confirmation)  │  用户选择:
└────────┬────────┘  - 保存/编辑/忽略
         │
         ▼
┌─────────────────┐
│ 持久化存储      │
│ (Persistence)  │  skills/{project_id}/
└─────────────────┘
```

### 5.2 技能生成 Prompt 模板

```python
SKILL_GENERATION_PROMPT = """
你是复杂系统建模专家。请根据以下 Agent 执行日志，为 UAP 项目生成一份专业的技能文档。

## 项目背景
- 项目名称: {project_name}
- 系统类型: {system_type}
- 领域: {domain}

## 执行轨迹
{action_trajectory}

## 要求
1. **技能名称**: 动词短语，简洁明了 (如: Lotka-Volterra 生态系统建模)
2. **触发条件**: 一句话描述何时使用此技能
3. **前置条件**: 使用此技能前需要满足什么
4. **执行步骤**: 
   - 使用祈使句
   - 保留参数占位符 {{{{variable}}}}
   - 每步说明预期输出
5. **适用场景**: 列出此技能最适用的场景
6. **局限性**: 此技能的不足和使用限制

## 输出格式
输出标准 Markdown，包含 YAML Front Matter 元数据。
"""

SKILL_FRONT_MATTER_TEMPLATE = """
---
skill_id: {skill_id}
project_id: {project_id}
name: {name}
description: {description}
category: {category}
trigger_conditions:
  - {trigger_1}
  - {trigger_2}
confidence: {confidence}
version: 1
created_by: auto_generated
created_at: {created_at}
---
"""
```

### 5.3 技能生成器核心代码

```python
class SkillGenerator:
    """技能生成器 - 将操作轨迹转化为技能文档"""
    
    def __init__(self, llm_client: OllamaClient):
        self.llm = llm_client
        self.sensitive_keywords = [
            "password", "token", "api_key", "secret",
            "authorization", "cookie", "key"
        ]
    
    def generate(
        self,
        session: SkillSession,
        project_info: dict
    ) -> ProjectSkill:
        """
        从 DST 会话生成技能
        
        Args:
            session: 技能会话追踪
            project_info: 项目信息
            
        Returns:
            生成的技能对象
        """
        # 1. 过滤噪音节点
        clean_actions = self._filter_noise(session.actions)
        
        # 2. 脱敏敏感参数
        sanitized_actions = [
            self._redact_sensitive(a) for a in clean_actions
        ]
        
        # 3. 构建生成 Prompt
        prompt = self._build_generation_prompt(
            session, project_info, sanitized_actions
        )
        
        # 4. 调用 LLM 生成技能内容
        skill_content = self.llm.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ])
        
        # 5. 解析生成的技能
        skill = self._parse_skill_content(skill_content, session)
        
        # 6. 计算置信度
        skill.confidence = self._calculate_confidence(session)
        
        return skill
    
    def _filter_noise(self, actions: List[ActionNode]) -> List[ActionNode]:
        """过滤纯观察节点"""
        return [a for a in actions if a.type in ["thought", "tool_call"]]
    
    def _redact_sensitive(self, action: ActionNode) -> ActionNode:
        """脱敏敏感参数"""
        for key in list(action.input_params.keys()):
            if any(s in key.lower() for s in self.sensitive_keywords):
                action.input_params[key] = "<SECRET>"
        return action
    
    def _build_generation_prompt(
        self,
        session: SkillSession,
        project_info: dict,
        actions: List[ActionNode]
    ) -> str:
        """构建技能生成 Prompt"""
        trajectory_text = "\n".join([
            f"Step {a.step_id}: [{a.type}] {a.tool_name or 'reasoning'}"
            f"\n  Input: {a.input_params}"
            f"\n  Output: {a.output_summary}"
            for a in actions
        ])
        
        return SKILL_GENERATION_PROMPT.format(
            project_name=project_info.get("name"),
            system_type=project_info.get("system_type"),
            domain=project_info.get("domain"),
            action_trajectory=trajectory_text
        )
    
    def _calculate_confidence(self, session: SkillSession) -> float:
        """基于会话元数据计算置信度"""
        score = 0.5  # 基础分
        
        # 用户纠正过 -> 说明有价值
        if session.corrections > 0:
            score += 0.2
        
        # 成功率 -> 根据最终输出判断
        if not self._has_error(session.actions):
            score += 0.15
        
        # 步骤适中 -> 太少可能不完整，太多可能太专
        if 3 <= len(session.actions) <= 10:
            score += 0.15
        
        return min(score, 1.0)
```

---

## 6. 技能管理器设计

### 6.1 核心功能

```python
class SkillManager:
    """技能管理器 - 负责技能的加载、执行和更新"""
    
    def __init__(
        self,
        project_store: ProjectStore,
        llm_client: OllamaClient
    ):
        self.store = project_store
        self.llm = llm_client
        self.skill_cache: Dict[str, List[ProjectSkill]] = {}
    
    # ==================== 技能加载 ====================
    
    def load_project_skills(self, project_id: str) -> List[ProjectSkill]:
        """加载项目的所有技能"""
        if project_id in self.skill_cache:
            return self.skill_cache[project_id]
        
        skills = self.store.list_skills(project_id)
        self.skill_cache[project_id] = skills
        return skills
    
    def get_relevant_skills(
        self,
        project_id: str,
        query: str
    ) -> List[ProjectSkill]:
        """根据查询获取相关技能"""
        skills = self.load_project_skills(project_id)
        
        # 1. 精确匹配触发条件
        matched = [
            s for s in skills
            if any(query in tc for tc in s.trigger_conditions)
        ]
        
        # 2. 如果没有精确匹配，使用 LLM 判断相关性
        if not matched:
            matched = self._llm_match_skills(skills, query)
        
        # 3. 按置信度排序
        matched.sort(key=lambda s: s.confidence, reverse=True)
        
        return matched
    
    # ==================== 技能执行 ====================
    
    def execute_skill(
        self,
        skill: ProjectSkill,
        context: dict
    ) -> SkillExecutionResult:
        """执行技能"""
        execution = SkillExecution(
            skill_id=skill.skill_id,
            start_time=datetime.now(),
            status="running"
        )
        
        try:
            # 1. 验证前置条件
            if not self._check_preconditions(skill, context):
                raise SkillError("前置条件不满足")
            
            # 2. 按步骤执行
            results = []
            for step in skill.steps:
                step_result = self._execute_step(step, context)
                results.append(step_result)
                
                # 3. 验证步骤输出
                if not self._validate_step(step, step_result):
                    raise SkillError(f"步骤 {step.step_number} 输出验证失败")
            
            execution.status = "completed"
            execution.results = results
            
        except Exception as e:
            execution.status = "failed"
            execution.error = str(e)
        
        finally:
            execution.end_time = datetime.now()
            self._update_skill_stats(skill, execution)
        
        return execution
    
    # ==================== 技能更新 ====================
    
    def merge_skill(
        self,
        base_skill: ProjectSkill,
        new_session: SkillSession
    ) -> ProjectSkill:
        """合并新经验到现有技能"""
        # 生成增量技能
        incremental = self.generator.generate(new_session, {})
        
        # 智能合并步骤
        merged_steps = self._smart_merge(
            base_skill.steps,
            incremental.steps
        )
        
        # 更新版本
        base_skill.steps = merged_steps
        base_skill.version += 1
        base_skill.usage_count += 1
        base_skill.updated_at = datetime.now()
        
        # 重新计算置信度
        base_skill.confidence = self._recalculate_confidence(
            base_skill, incremental
        )
        
        return base_skill
```

### 6.2 技能存储结构

```
projects/
└── {project_id}/
    ├── project.json              # 项目配置
    ├── model.json                # 系统模型
    ├── predictions/
    │   └── {timestamp}.jsonl    # 预测结果
    └── skills/                   # 项目专属技能
        ├── metadata.json         # 技能索引
        ├── modeling/
        │   ├── skill_001.md      # 技能1
        │   └── skill_002.md      # 技能2
        ├── prediction/
        │   └── skill_003.md      # 技能3
        └── analysis/
            └── skill_004.md      # 技能4
```

---

## 7. 与建模/预测的集成

### 7.1 建模技能执行器

```python
class ModelingSkillExecutor:
    """建模技能执行器"""
    
    def __init__(
        self,
        skill_manager: SkillManager,
        model_extractor: ModelExtractor
    ):
        self.skills = skill_manager
        self.extractor = model_extractor
    
def execute_modeling_skill(
        self,
        project_id: str,
        user_intent: str,
        conversation: List[dict]
    ) -> ModelingResult:
        """执行建模技能"""
        
        # 1. 加载相关技能
        relevant_skills = self.skills.get_relevant_skills(
            project_id,
            user_intent
        )
        
        modeling_skills = [
            s for s in relevant_skills
            if s.category == "modeling"
        ]
        
        # 2. 选择最佳技能或回退到通用提取
        if modeling_skills:
            skill = modeling_skills[0]
            return self._execute_with_skill(
                skill, conversation
            )
        else:
            # 回退到通用模型提取
            return self.extractor.extract_from_conversation(
                conversation, user_intent
            )
    
    def _execute_with_skill(
        self,
        skill: ProjectSkill,
        conversation: List[dict]
    ) -> ModelingResult:
        """使用特定技能执行建模"""
        context = {
            "conversation": conversation,
            "skill": skill
        }
        
        result = self.skills.execute_skill(skill, context)
        
        # 解析结果为系统模型
        return self._parse_model_result(result)
```

### 7.2 预测技能执行器

```python
class PredictionSkillExecutor:
    """预测技能执行器"""
    
    def __init__(
        self,
        skill_manager: SkillManager,
        prediction_engine: PredictionEngine
    ):
        self.skills = skill_manager
        self.engine = prediction_engine
    
    def execute_prediction_skill(
        self,
        project: Project,
        skill_name: str = None
    ) -> PredictionResult:
        """执行预测技能"""
        
        # 1. 获取预测技能
        if skill_name:
            skill = self._get_skill_by_name(project.id, skill_name)
        else:
            # 选择最适合当前模型的预测技能
            skill = self._select_best_prediction_skill(project)
        
        if not skill:
            # 回退到默认预测
            return self.engine.predict(project)
        
        # 2. 准备初始状态
        initial_state = self._prepare_initial_state(project, skill)
        
        # 3. 执行预测
        context = {
            "project": project,
            "initial_state": initial_state,
            "skill": skill
        }
        
        result = self.skills.execute_skill(skill, context)
        
        # 4. 处理预测结果
        return self._process_prediction_result(result)
```

---

## 8. 前端交互设计

### 8.1 技能卡片通知

当技能生成后，通过 WebSocket 向前端推送技能卡片：

```javascript
// 前端接收技能卡片
window.pywebview.api.onSkillGenerated((skillCard) => {
    showSkillCardNotification(skillCard);
});

function showSkillCardNotification(card) {
    const notification = document.createElement('div');
    notification.className = 'skill-card-notification';
    notification.innerHTML = `
        <div class="skill-card">
            <div class="card-header">
                <span class="badge">${card.category}</span>
                <span class="confidence">置信度 ${(card.confidence * 100).toFixed(0)}%</span>
            </div>
            <h3>${card.title}</h3>
            <p>${card.description}</p>
            <div class="steps-preview">
                ${card.steps.slice(0, 3).map(s => `<li>${s.title}</li>`).join('')}
            </div>
            <div class="card-actions">
                <button class="btn-save" data-action="save">保存技能</button>
                <button class="btn-edit" data-action="edit">编辑后保存</button>
                <button class="btn-ignore" data-action="ignore">忽略</button>
            </div>
        </div>
    `;
    document.body.appendChild(notification);
}
```

### 8.2 技能管理面板

```
┌─────────────────────────────────────────────────────────────┐
│  技能管理                                          [关闭]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  筛选: [全部 ▼]  搜索: [____________]                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 📊 Lotka-Volterra 生态系统建模                         ││
│  │ 建模类 | 置信度 92% | 使用 15 次                       ││
│  │ 自动生成 | 2026-04-14                                  ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 📈 捕食者-猎物动态预测                                  ││
│  │ 预测类 | 置信度 85% | 使用 8 次                        ││
│  │ 自动生成 | 2026-04-13                                  ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  [ + 从对话中创建 ]  [ + 手动添加 ]                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. 实现计划

| 阶段 | 任务 | 工时 | 优先级 |
|------|------|------|--------|
| **Phase 1** | 技能核心数据结构与存储 | 0.5d | P0 |
| **Phase 2** | SkillSession DST 追踪埋点 | 0.5d | P0 |
| **Phase 3** | 技能触发器与生成器 | 1.0d | P0 |
| **Phase 4** | 技能管理器 (加载/执行) | 1.0d | P1 |
| **Phase 5** | 建模技能执行器集成 | 0.5d | P1 |
| **Phase 6** | 预测技能执行器集成 | 0.5d | P1 |
| **Phase 7** | 前端技能卡片通知 | 0.5d | P2 |
| **Phase 8** | 技能管理面板 UI | 0.5d | P2 |

---

## 10. Git Commit Message (后续开发用)

```
feat: 实现UAP智能技能系统

### 核心组件
- src/uap/skill/session.py         # SkillSession DST追踪
- src/uap/skill/generator.py        # 技能生成器
- src/uap/skill/manager.py          # 技能管理器
- src/uap/skill/executor.py         # 技能执行器
- src/uap/skill/models.py           # 技能数据模型

### 功能实现
- SkillGenerator: 从对话轨迹自动生成技能文档
- SkillManager: 技能加载、执行、版本管理
- 建模/预测技能执行器与现有服务层集成
- 前端技能卡片通知与WebSocket推送

### 设计文档
- docs/设计指南/UAP技能系统设计指南.md
```

---

*文档版本: 1.0*
*创建时间: 2026-04-14*
*参考: 自动技能工匠设计指南*
