"""
用户画像服务 - 管理用户画像的加载、编译和自动更新

画像更新采用多步 pipeline：
  Step 1 (信号提取): 从对话中识别反馈信号
  Step 2 (编辑规划): 将信号转化为对 profile 的精确编辑操作
  Step 3 (编辑执行): 程序化地应用编辑
  Step 4 (验证):    检查编辑结果的完整性
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from openai import AsyncOpenAI

from config import settings
from models import ChatMessage


class UserProfileService:
    """用户画像服务"""

    BASE_ROLE = "你是一个专业的学术论文阅读助手。你的任务是根据用户的知识背景和偏好，为用户量身定制论文讲解。"

    # ==================== Step 1: 信号提取 ====================

    SIGNAL_EXTRACTION_PROMPT = """你是一个用户反馈信号提取器。你的任务是从用户与论文讲解助手的对话中，识别出所有与用户偏好、知识背景相关的反馈信号。

## 你需要识别的信号类型

1. **knowledge_update** — 用户对某个知识点的掌握程度发生了变化
   - 用户说"这个我知道""不用讲""跳过" → 掌握程度上升
   - 用户说"这个没听过""这是什么" → 发现了新的不熟悉领域

2. **positive_example** — 某种讲解方式效果好
   - 用户说"懂了""原来如此""这个比喻好"
   - 特别关注：助手换了一种方式后用户才懂 → 记录有效的那种方式

3. **negative_example** — 某种讲解方式效果差
   - 用户说"没懂""看不懂""能换种方式说吗"
   - 用户直接跳过或忽略了助手的某段讲解

4. **preference_update** — 用户对讲解风格的偏好发生变化
   - 用户要求"展开讲""详细说说" → 该主题需要更高粒度
   - 用户要求"简略点""不用这么细" → 该主题粒度过高
   - 用户对某种表述方式表达好恶

5. **interest_update** — 用户的研究兴趣发生变化
   - 用户提到新的关注方向
   - 用户对某个方向表现出特别的兴趣或失去兴趣

## 重要原则

- **只提取有明确依据的信号**，不要过度推断。用户说"嗯"不代表懂了，沉默不代表不满意。
- **对照已有 profile 去重**：如果 profile 里已经记录了某个偏好，对话中只是再次体现了这个偏好，不算新信号。
- **记录具体上下文**：每个信号都要附带对话中的具体上下文，说明这个信号是从哪句话里提取的。

## 输出格式

输出一个 JSON 对象，不要包含其他文字：

```json
{
  "signals": [
    {
      "type": "信号类型（上述5种之一）",
      "description": "简要描述这个信号",
      "evidence": "对话中的原文证据（引用用户或助手的原话）",
      "context": "这个信号发生在什么讨论情境下（在讲什么内容时产生的）"
    }
  ]
}
```

如果没有发现任何值得记录的信号，返回 `{"signals": []}`。"""

    # ==================== Step 2: 编辑规划 ====================

    EDIT_PLANNING_PROMPT = """你是一个用户画像编辑规划器。你会收到一组从对话中提取的反馈信号，以及当前的用户画像。你的任务是将这些信号转化为对画像的精确编辑操作。

## 可用的编辑操作

1. **append_example** — 向示例库添加一条记录
   - `section`: "good_examples" 或 "bad_examples"
   - `content`: 要添加的示例文本（markdown 格式的一个列表项）

2. **append_item** — 向某个章节追加一条内容
   - `section`: 目标章节标识，如 "knowledge_dl"（深度学习知识表格）、"knowledge_math"（数学知识表格）、"preferences"（讲解偏好）、"forbidden"（禁区表格）、"interests"（研究兴趣）
   - `content`: 要追加的内容（表格行或列表项，匹配该章节的格式）

3. **replace_text** — 替换画像中的一段特定文字
   - `old_text`: 要被替换的原文（必须在画像中精确存在）
   - `new_text`: 替换后的文字

## 编辑原则

1. **最小化编辑**：每个信号只产生必要的编辑，不要顺便改其他东西
2. **示例库优先**：大多数信号应该转化为 append_example，除非有明确理由修改其他章节
3. **不删除已有内容**，除非信号明确表明之前的记录是错的
4. **不要修改元信息**（第六章节由系统管理）
5. 如果某些信号不足以产生有意义的编辑（例如信号太弱或太模糊），跳过它

## 输出格式

```json
{
  "edits": [
    {
      "operation": "append_example | append_item | replace_text",
      "section": "目标章节（append 操作需要）",
      "content": "要添加的内容（append 操作需要）",
      "old_text": "原文（replace 操作需要）",
      "new_text": "新文（replace 操作需要）",
      "reason": "为什么做这个编辑（对应哪个信号）"
    }
  ],
  "changelog_summary": "一两句话概述所有变更（人类可读，用于 changelog）"
}
```

如果所有信号都不足以产生编辑，返回 `{"edits": [], "changelog_summary": ""}`。"""

    # ==================== Profile 结构标记 ====================

    SECTION_MARKERS = {
        "knowledge_dl": "### 1.1 深度学习",
        "knowledge_math": "### 1.2 数学与理论",
        "knowledge_eng": "### 1.3 工程能力",
        "preferences": "## 二、讲解偏好",
        "forbidden": "## 三、禁区",
        "interests": "## 四、当前研究兴趣",
        "good_examples": "### 5.1 好的讲解方式",
        "bad_examples": "### 5.2 不好的讲解方式",
        "meta": "## 六、元信息",
    }

    def __init__(self):
        self._profile_cache: Optional[str] = None
        self._system_prompt_cache: Optional[str] = None

    @property
    def profile_path(self) -> Path:
        return settings.user_profile_dir / "profile.md"

    @property
    def changelog_path(self) -> Path:
        return settings.user_profile_dir / "changelog.md"

    @property
    def pending_updates_path(self) -> Path:
        return settings.user_profile_dir / "pending_updates.json"

    # ==================== Profile 加载与编译 ====================

    def load_profile(self) -> str:
        if not self.profile_path.exists():
            return ""
        with open(self.profile_path, "r", encoding="utf-8") as f:
            return f.read()

    def compile_system_prompt(self) -> str:
        profile_content = self.load_profile()
        if not profile_content:
            return self.BASE_ROLE

        profile_for_prompt = self._strip_meta_section(profile_content)

        return f"""{self.BASE_ROLE}

以下是该用户的详细画像，你必须严格遵循其中的所有要求：

---
{profile_for_prompt}
---

请根据以上画像来调整你的讲解方式。"""

    def _strip_meta_section(self, content: str) -> str:
        marker = "## 六、元信息"
        idx = content.find(marker)
        if idx != -1:
            return content[:idx].rstrip()
        return content

    def has_profile(self) -> bool:
        return self.profile_path.exists()

    def invalidate_cache(self):
        self._profile_cache = None
        self._system_prompt_cache = None

    # ==================== 多步 Pipeline ====================

    async def analyze_conversation(
        self,
        messages: List[ChatMessage],
        paper_title: str = "",
        paper_summary: str = "",
    ) -> Optional[dict]:
        """
        多步 pipeline 分析对话，生成画像更新建议。

        Step 1: 信号提取 — 从对话中识别反馈信号
        Step 2: 编辑规划 — 将信号转化为精确编辑操作
        Step 3: 编辑执行 — 程序化应用编辑
        Step 4: 验证    — 检查结果完整性
        """
        if len(messages) < 2:
            return None

        current_profile = self.load_profile()
        if not current_profile:
            return None

        client = AsyncOpenAI(
            api_key=settings.llm.api_key,
            base_url=settings.llm.api_base,
        )
        analysis_model = settings.profile_analysis.model
        analysis_temp = settings.profile_analysis.temperature
        analysis_max_tokens = settings.profile_analysis.max_tokens

        # --- Step 1: 信号提取 ---
        print("[ProfilePipeline] Step 1: 提取反馈信号...")
        signals = await self._step1_extract_signals(
            client, analysis_model, analysis_temp, analysis_max_tokens,
            messages, current_profile, paper_title, paper_summary,
        )
        if not signals:
            print("[ProfilePipeline] 未发现反馈信号，跳过更新。")
            return None
        print(f"[ProfilePipeline] 发现 {len(signals)} 个信号。")

        # --- Step 2: 编辑规划 ---
        print("[ProfilePipeline] Step 2: 规划编辑操作...")
        edit_plan = await self._step2_plan_edits(
            client, analysis_model, analysis_temp, analysis_max_tokens,
            signals, current_profile,
        )
        if not edit_plan or not edit_plan.get("edits"):
            print("[ProfilePipeline] 信号不足以产生编辑，跳过更新。")
            return None
        print(f"[ProfilePipeline] 规划了 {len(edit_plan['edits'])} 个编辑操作。")

        # --- Step 3: 编辑执行 ---
        print("[ProfilePipeline] Step 3: 执行编辑...")
        new_profile = self._step3_apply_edits(current_profile, edit_plan["edits"])

        # --- Step 4: 验证 ---
        print("[ProfilePipeline] Step 4: 验证编辑结果...")
        is_valid, issues = self._step4_verify(current_profile, new_profile, edit_plan["edits"])
        if not is_valid:
            print(f"[ProfilePipeline] 验证失败: {issues}")
            return None
        print("[ProfilePipeline] 验证通过。")

        pending = {
            "timestamp": datetime.now().isoformat(),
            "paper_title": paper_title,
            "signals": signals,
            "edits": edit_plan["edits"],
            "summary": edit_plan.get("changelog_summary", ""),
            "new_profile_content": new_profile,
        }
        self._save_pending_updates(pending)
        return pending

    # --- Step 1 实现 ---

    async def _step1_extract_signals(
        self,
        client: AsyncOpenAI,
        model: str,
        temperature: float,
        max_tokens: int,
        messages: List[ChatMessage],
        current_profile: str,
        paper_title: str,
        paper_summary: str,
    ) -> Optional[list]:
        conversation_text = self._format_conversation(messages)

        user_message = f"""## 当前用户画像

{current_profile}

## 论文信息

**标题**：{paper_title}
**摘要**：{paper_summary if paper_summary else '（无摘要）'}

## 对话记录

{conversation_text}"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self.SIGNAL_EXTRACTION_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            result = self._parse_json_response(response.choices[0].message.content)
            if result and result.get("signals"):
                return result["signals"]
            return None
        except Exception as e:
            print(f"[ProfilePipeline] Step 1 失败: {e}")
            return None

    # --- Step 2 实现 ---

    async def _step2_plan_edits(
        self,
        client: AsyncOpenAI,
        model: str,
        temperature: float,
        max_tokens: int,
        signals: list,
        current_profile: str,
    ) -> Optional[dict]:
        user_message = f"""## 当前用户画像

{current_profile}

## 提取到的反馈信号

```json
{json.dumps(signals, ensure_ascii=False, indent=2)}
```

请根据以上信号，规划对画像的编辑操作。"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self.EDIT_PLANNING_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._parse_json_response(response.choices[0].message.content)
        except Exception as e:
            print(f"[ProfilePipeline] Step 2 失败: {e}")
            return None

    # --- Step 3 实现 ---

    def _step3_apply_edits(self, profile: str, edits: list) -> str:
        """程序化地应用编辑操作到 profile"""
        result = profile

        for edit in edits:
            op = edit.get("operation")
            try:
                if op == "append_example":
                    result = self._apply_append_example(result, edit)
                elif op == "append_item":
                    result = self._apply_append_item(result, edit)
                elif op == "replace_text":
                    result = self._apply_replace_text(result, edit)
                else:
                    print(f"[ProfilePipeline] 未知操作类型: {op}")
            except Exception as e:
                print(f"[ProfilePipeline] 应用编辑失败 ({op}): {e}")

        return result

    def _apply_append_example(self, profile: str, edit: dict) -> str:
        section = edit.get("section", "good_examples")
        marker = self.SECTION_MARKERS.get(section)
        if not marker:
            return profile

        placeholder_good = "（暂无，将在实际使用中积累）"
        placeholder_bad = "（暂无，将在实际使用中积累）"

        if section == "good_examples" and placeholder_good in profile:
            return profile.replace(placeholder_good, edit["content"])
        elif section == "bad_examples" and placeholder_bad in profile:
            return profile.replace(placeholder_bad, edit["content"])

        idx = profile.find(marker)
        if idx == -1:
            return profile

        next_section_idx = self._find_next_section(profile, idx + len(marker))
        insert_pos = next_section_idx if next_section_idx != -1 else len(profile)

        insert_text = "\n" + edit["content"] + "\n"
        return profile[:insert_pos] + insert_text + profile[insert_pos:]

    def _apply_append_item(self, profile: str, edit: dict) -> str:
        section = edit.get("section")
        marker = self.SECTION_MARKERS.get(section)
        if not marker:
            return profile

        idx = profile.find(marker)
        if idx == -1:
            return profile

        next_section_idx = self._find_next_section(profile, idx + len(marker))
        insert_pos = next_section_idx if next_section_idx != -1 else len(profile)

        trailing = profile[idx:insert_pos].rstrip()
        insert_text = "\n" + edit["content"] + "\n"

        return profile[:idx] + trailing + insert_text + "\n" + profile[insert_pos:]

    def _apply_replace_text(self, profile: str, edit: dict) -> str:
        old_text = edit.get("old_text", "")
        new_text = edit.get("new_text", "")
        if old_text and old_text in profile:
            return profile.replace(old_text, new_text, 1)
        else:
            print(f"[ProfilePipeline] replace_text: 未找到目标文本: {old_text[:80]}...")
            return profile

    def _find_next_section(self, profile: str, start: int) -> int:
        """从 start 位置开始，找到下一个 ## 或 ### 标题的位置"""
        pattern = re.compile(r'\n##\s')
        match = pattern.search(profile, start)
        return match.start() if match else -1

    # --- Step 4 实现 ---

    def _step4_verify(self, old_profile: str, new_profile: str, edits: list) -> tuple[bool, str]:
        """验证编辑结果的完整性"""
        old_sections = set(re.findall(r'^##\s+.+$', old_profile, re.MULTILINE))
        new_sections = set(re.findall(r'^##\s+.+$', new_profile, re.MULTILINE))

        missing = old_sections - new_sections
        if missing:
            return False, f"编辑后丢失了以下章节: {missing}"

        if len(new_profile) < len(old_profile) * 0.8:
            return False, f"编辑后内容大幅缩短 ({len(old_profile)} → {len(new_profile)})"

        for edit in edits:
            op = edit.get("operation")
            if op in ("append_example", "append_item"):
                content = edit.get("content", "")
                key_fragment = content[:50] if len(content) > 50 else content
                if key_fragment and key_fragment.strip() not in new_profile:
                    return False, f"编辑内容未成功写入: {key_fragment[:60]}..."
            elif op == "replace_text":
                new_text = edit.get("new_text", "")
                if new_text and new_text not in new_profile:
                    return False, f"替换内容未成功写入: {new_text[:60]}..."

        return True, ""

    # ==================== 工具方法 ====================

    def _format_conversation(self, messages: List[ChatMessage]) -> str:
        lines = []
        for msg in messages:
            role_label = "用户" if msg.role == "user" else "助手"
            lines.append(f"**{role_label}**：{msg.content}")
        return "\n\n".join(lines)

    def _parse_json_response(self, text: str) -> Optional[dict]:
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        else:
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[ProfilePipeline] 无法解析 JSON: {text[:200]}")
            return None

    # ==================== Pending Updates 管理 ====================

    def _save_pending_updates(self, pending: dict):
        with open(self.pending_updates_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)

    def get_pending_updates(self) -> Optional[dict]:
        if not self.pending_updates_path.exists():
            return None
        with open(self.pending_updates_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def apply_pending_updates(self) -> bool:
        pending = self.get_pending_updates()
        if not pending:
            return False

        new_content = pending["new_profile_content"]
        summary = pending["summary"]
        edits = pending.get("edits", [])
        signals = pending.get("signals", [])
        paper_title = pending.get("paper_title", "未知论文")
        timestamp = pending.get("timestamp", datetime.now().isoformat())

        with open(self.profile_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        date_str = timestamp[:10]

        edits_detail = ""
        for edit in edits:
            reason = edit.get("reason", "")
            edits_detail += f"\n- {reason}"

        signals_detail = ""
        for sig in signals:
            signals_detail += f"\n- [{sig.get('type')}] {sig.get('description')}"

        changelog_entry = f"""
---

## [{date_str}] 自动更新（基于论文「{paper_title}」的对话）

**触发方式**：对话反馈自动分析

**变更摘要**：{summary}

**识别到的信号**：{signals_detail}

**执行的编辑**：{edits_detail}
"""
        with open(self.changelog_path, "a", encoding="utf-8") as f:
            f.write(changelog_entry)

        self.pending_updates_path.unlink(missing_ok=True)
        self.invalidate_cache()
        return True

    def reject_pending_updates(self) -> bool:
        if self.pending_updates_path.exists():
            self.pending_updates_path.unlink()
            return True
        return False


user_profile_service = UserProfileService()
