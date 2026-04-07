"""
画像进化服务 — 将原来的多步静默 pipeline 改为可交互的对话式进化 Agent。

Agent 在一次对话中完成：信号提取 → 编辑规划 → 用户协商 → 输出最终编辑计划。
用户可以随时插嘴修改，Agent 实时调整。
"""
import base64
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional, List

from openai import AsyncOpenAI

from config import settings
from models import ChatMessage

logger = logging.getLogger(__name__)

PDF_SIZE_THRESHOLD = 15 * 1024 * 1024


EVOLUTION_SYSTEM_PROMPT = """\
你是 iPaper 的画像进化助手。

你和用户（画像的主人）在同一个界面上协作：用户右边看着论文讨论的对话历史，左边（你所在的面板）和你讨论如何更新画像。

## 为什么要进化

iPaper 用一份用户画像来指导讲解模型为用户量身定制论文讲解。画像记录了用户的知识背景、讲解偏好、禁区、研究兴趣、以及好的/不好的讲解示例。

我们的**终极目标**：让讲解模型足够了解用户，以至于用户在阅读论文时，**尽可能不需要追问**。

这意味着什么？用户每一次追问，都暴露了画像的一个缺口：
- 用户问"这个是什么意思？" → 讲解模型不知道用户不熟悉这个概念，该讲的没讲
- 用户说"展开讲讲这部分" → 讲解模型不知道用户对这块特别关注，讲得太浅了
- 用户说"这个我知道，跳过" → 讲解模型不知道用户已经掌握了这个，浪费了时间
- 用户说"能换种方式说吗？" → 讲解模型用了不适合用户的表达方式
- 用户追问某个方向的细节 → 讲解模型不知道这是用户的研究兴趣，没有主动深入

**你的工作就是从这些追问和反馈中，反推出画像应该怎么改，让下次讲解时模型自己就能做对。**

所以你在分析对话时，核心问题不是"用户说了什么"，而是：**如果画像里提前写了什么，讲解模型就不会让用户产生这次追问？**

## 分析对话的视角

### 你需要关注的信号

从对话中寻找以下线索。每个线索的本质都是：画像里缺了什么，导致讲解模型做了不够好的事。

**1. 知识掌握度信号** (`knowledge_update`)

用户的追问暴露了画像中知识背景的不准确：
- 用户对某个概念追问"这是什么" → 画像高估了掌握程度，或缺少这个条目
- 用户说"这个我知道""不用讲" → 画像低估了掌握程度
- 用户在讨论中准确使用了某个之前标记为不熟悉的概念 → 掌握程度已提升

**2. 关注点信号** (`preference_update`)

用户的追问暴露了画像中对用户关注点的记录不足：
- 用户追问某个模块的细节 → 画像没有告诉模型"用户关注这类细节"，模型讲得太浅
- 用户要求跳过某个部分 → 画像没有告诉模型"用户不关心这类内容"，模型讲得太多
- 用户对讲解的粒度、视角、风格提出要求 → 画像中的偏好描述不够精确

**3. 讲解方式信号** (`positive_example` / `negative_example`)

对话中出现了可以作为示例记录下来的讲解案例：
- 模型用了某种讲法，用户表示"懂了""这个比喻好" → 好的讲解方式，值得记录下来让模型以后复用
- 模型用了某种讲法，用户表示"没懂""太抽象" → 坏的讲解方式，记录下来让模型以后避免
- 模型换了一种方式后用户才懂 → 两个信号：前一种是坏例子，后一种是好例子

记录示例时的关键要求：**泛用性**。画像的空间有限，每条记录都必须能指导未来多篇论文的讲解，而不是只适用于某一篇论文的某个特定概念。好的示例提炼出的是一种**通用的讲解模式或原则**（如"对比两个组件时不要只看名字相似就类比"），而不是某个具体概念的正确/错误解释。如果一条记录离开了当前这篇论文的上下文就没有意义，就不要写进画像。

**4. 研究兴趣信号** (`interest_update`)

用户的选题和追问方向暴露了研究兴趣的变化：
- 用户开始阅读新领域的论文 → 可能在拓展兴趣
- 用户对某个方向的追问特别深入 → 这是核心兴趣，画像中应重点标注
- 用户对某个之前标注的兴趣方向不再追问 → 兴趣可能已转移

### 提取原则

- **只提取有明确证据的信号**。"嗯"不代表懂了，沉默不代表不满意。
- **对照已有画像去重**：如果画像里已经记录了某个信息，对话中只是再次体现了它，不算新信号。
- **每个信号必须附带对话中的原文证据**。
- **回答"画像差在哪"**：每个信号都应该能回答"如果画像提前包含了这个信息，讲解会怎样改善"。如果答不上来，这个信号可能没有价值。

## 编辑规划

根据信号，规划对画像的编辑。可用的操作类型：

| 操作 | 用途 | 必填字段 |
|------|------|---------|
| `append_example` | 向示例库（5.1 或 5.2）添加案例 | `section`, `content` |
| `append_item` | 向指定章节追加内容 | `section`, `content` |
| `replace_text` | 精确替换画像中的一段文字 | `old_text`, `new_text` |

**编辑原则**：

你拥有对画像的完全编辑权（最终会经过用户确认才生效，所以不用保守）。以改善讲解效果为唯一标准：
- 如果一处小改就够了，就小改
- 如果你认为某个章节的组织方式有问题、某条规则过时了、某个分类不合理，可以大改——重写段落、删除不再适用的条目、调整结构都可以
- 示例库（第五章）是最有实操价值的章节，但写入的每条示例必须有**泛用性**——能指导未来多篇论文的讲解，而不是只记录某篇论文某个概念的正确/错误解释。画像空间有限，不要把它当作知识库
- 唯一的硬性约束：不要修改元信息（第六章节），那是系统维护的

### section 标识符对照表

| 标识符 | 对应画像章节 |
|-------|------------|
| `knowledge_dl` | 1.1 深度学习（知识表格） |
| `knowledge_math` | 1.2 数学与理论（知识表格） |
| `knowledge_eng` | 1.3 工程能力 |
| `preferences` | 二、讲解偏好 |
| `forbidden` | 三、禁区 |
| `interests` | 四、当前研究兴趣 |
| `good_examples` | 5.1 好的讲解方式 |
| `bad_examples` | 5.2 不好的讲解方式 |

## 与用户协商

将分析结果呈现给用户：

1. 先列出你发现的所有信号（简述 + 证据引用 + 这个信号说明画像缺了什么）
2. 然后列出你规划的编辑操作（改什么、为什么改、改了之后讲解会怎样改善）
3. 询问用户是否同意，或有什么要调整的

用户可能会：
- 同意全部 → 你输出最终编辑计划
- 要求调整 → 你修改后重新展示
- 直接告诉你要改画像的某个地方（不基于对话分析） → 你据此生成编辑操作

## 输出最终编辑计划

当用户确认后，输出用 `<edit_plan>` 标签包裹的 JSON：

<edit_plan>
{
  "edits": [
    {
      "operation": "append_example | append_item | replace_text",
      "section": "目标章节标识符",
      "content": "要添加的内容（append 操作）",
      "old_text": "要替换的原文（replace_text 操作）",
      "new_text": "替换后的文字（replace_text 操作）",
      "reason": "为什么做这个编辑"
    }
  ],
  "changelog_summary": "一两句话概述所有变更"
}
</edit_plan>

**重要**：只在用户明确确认后才输出 `<edit_plan>`。讨论过程中不要输出。

## 交互风格

- 使用中文
- 简洁务实，不啰嗦
- 信号和编辑操作用结构化列表展示
- 不要使用 emoji"""


class EvolutionService:

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

    def profile_path(self, user_id: str) -> Path:
        return settings.get_user_profile_dir(user_id) / "profile.md"

    def changelog_path(self, user_id: str) -> Path:
        return settings.get_user_profile_dir(user_id) / "changelog.md"

    def pending_updates_path(self, user_id: str) -> Path:
        return settings.get_user_profile_dir(user_id) / "pending_updates.json"

    def load_profile(self, user_id: str) -> str:
        path = self.profile_path(user_id)
        if not path.exists():
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def load_changelog(self, user_id: str) -> str:
        path = self.changelog_path(user_id)
        if not path.exists():
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _build_initial_user_content(
        self,
        chat_messages: List[ChatMessage],
        paper_title: str,
        paper_summary: str,
        current_profile: str,
        pdf_paths: Optional[List[Path]] = None,
    ) -> list:
        """构建进化对话的第一条 user 消息（multimodal）：PDF + 当前画像 + 论文信息 + 对话记录"""
        content_blocks: list = []

        if pdf_paths:
            for pdf_path in pdf_paths:
                content_blocks.extend(self._build_pdf_blocks(pdf_path))

        conversation_lines = []
        for msg in chat_messages:
            role_label = "用户" if msg.role == "user" else "助手"
            conversation_lines.append(f"**{role_label}**：{msg.content}")
        conversation_text = "\n\n".join(conversation_lines)

        text = f"""## 当前用户画像

{current_profile}

## 论文信息

**标题**：{paper_title}
**摘要**：{paper_summary if paper_summary else '（无摘要）'}

## 对话记录

{conversation_text}

---

请分析以上对话，提取反馈信号并规划画像编辑。"""

        content_blocks.append({"type": "text", "text": text})
        return content_blocks

    @staticmethod
    def _build_pdf_blocks(pdf_path: Path) -> list:
        """构建单个 PDF 的内容块"""
        if not pdf_path.exists():
            return []
        pdf_size = pdf_path.stat().st_size
        if pdf_size <= PDF_SIZE_THRESHOLD:
            with open(pdf_path, "rb") as f:
                pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
            return [{
                "type": "file",
                "file": {
                    "filename": pdf_path.name,
                    "file_data": f"data:application/pdf;base64,{pdf_base64}",
                },
            }]
        else:
            logger.info(
                "PDF too large for evolution context (%.1fMB), skipping",
                pdf_size / 1024 / 1024,
            )
            return [{"type": "text", "text": f"（论文 PDF {pdf_path.name} 过大，已省略）"}]

    async def chat_stream(
        self,
        user_id: str,
        evolution_messages: List[dict],
        chat_messages: List[ChatMessage],
        paper_title: str = "",
        paper_summary: str = "",
        pdf_paths: Optional[List[Path]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        进化 Agent 的流式对话。

        user_id: 当前用户 ID
        evolution_messages: 进化面板中的对话历史（user/assistant 消息列表）
        chat_messages: 论文讨论的原始对话（提供给 Agent 作为分析素材）
        paper_title/paper_summary: 论文信息
        pdf_paths: 论文 PDF 文件路径列表
        """
        current_profile = self.load_profile(user_id)
        if not current_profile:
            logger.warning("[Evolution] 画像文件不存在")
            yield "画像文件不存在，无法进行进化分析。"
            return

        client = AsyncOpenAI(
            api_key=settings.llm.api_key,
            base_url=settings.llm.api_base,
        )
        model = settings.profile_analysis.model
        temperature = settings.profile_analysis.temperature
        max_tokens = settings.profile_analysis.max_tokens

        api_messages = [{"role": "system", "content": EVOLUTION_SYSTEM_PROMPT}]

        first_user_content = self._build_initial_user_content(
            chat_messages, paper_title, paper_summary, current_profile, pdf_paths,
        )
        api_messages.append({"role": "user", "content": first_user_content})

        if evolution_messages:
            api_messages.extend(evolution_messages)

        n_pdfs = len(pdf_paths) if pdf_paths else 0
        n_chat = len(chat_messages)
        n_evo = len(evolution_messages)
        msg_summary = []
        for m in api_messages:
            role = m["role"]
            content = m.get("content", "")
            if isinstance(content, str):
                msg_summary.append(f"  [{role}] {len(content)} chars")
            elif isinstance(content, list):
                types = [b.get("type", "?") for b in content]
                msg_summary.append(f"  [{role}] multimodal: {types}")
        logger.info(
            "[Evolution] Starting stream: model=%s, paper=%s, "
            "%d PDFs, %d chat msgs, %d evolution msgs, %d API msgs\n%s",
            model, paper_title, n_pdfs, n_chat, n_evo,
            len(api_messages), "\n".join(msg_summary),
        )

        stream = await client.chat.completions.create(
            model=model,
            messages=api_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        chunk_count = 0
        async for chunk in stream:
            if not chunk.choices:
                continue
            chunk_count += 1
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

        logger.info("[Evolution] Stream finished: %d chunks received", chunk_count)

    def parse_edit_plan(self, text: str) -> Optional[dict]:
        """从 Agent 回复中提取 <edit_plan> JSON"""
        match = re.search(r'<edit_plan>\s*(.*?)\s*</edit_plan>', text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def apply_edits(self, profile: str, edits: list) -> str:
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
            except Exception as e:
                logger.error("[Evolution] 应用编辑失败 (%s): %s", op, e)
        return result

    def verify_edits(self, old_profile: str, new_profile: str, edits: list) -> tuple[bool, str]:
        if not new_profile.strip():
            return False, "编辑后画像为空"

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

    def save_pending(self, user_id: str, edit_plan: dict, paper_title: str = "") -> dict:
        """保存待确认的编辑计划"""
        edits = edit_plan.get("edits", [])
        logger.info(
            "[Evolution] Saving pending: %d edits, paper=%s",
            len(edits), paper_title,
        )
        current_profile = self.load_profile(user_id)
        new_profile = self.apply_edits(current_profile, edits)

        is_valid, issue = self.verify_edits(
            current_profile, new_profile, edit_plan.get("edits", [])
        )

        pending = {
            "timestamp": datetime.now().isoformat(),
            "paper_title": paper_title,
            "edits": edit_plan.get("edits", []),
            "summary": edit_plan.get("changelog_summary", ""),
            "new_profile_content": new_profile,
            "validation": {"valid": is_valid, "issue": issue},
        }
        path = self.pending_updates_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)
        return pending

    def apply_pending(self, user_id: str) -> bool:
        path = self.pending_updates_path(user_id)
        if not path.exists():
            logger.warning("[Evolution] apply_pending called but no pending file")
            return False
        logger.info("[Evolution] Applying pending updates to profile")
        with open(path, "r", encoding="utf-8") as f:
            pending = json.load(f)

        new_content = pending["new_profile_content"]
        summary = pending.get("summary", "")
        edits = pending.get("edits", [])
        paper_title = pending.get("paper_title", "未知论文")
        timestamp = pending.get("timestamp", datetime.now().isoformat())

        profile_p = self.profile_path(user_id)
        profile_p.parent.mkdir(parents=True, exist_ok=True)
        with open(profile_p, "w", encoding="utf-8") as f:
            f.write(new_content)
        with open(profile_p.parent / "profile.meta.json", "w", encoding="utf-8") as f:
            json.dump({"updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)

        date_str = timestamp[:10]
        edits_detail = "".join(f"\n- {e.get('reason', '')}" for e in edits)
        changelog_entry = f"""
---

## [{date_str}] 自动更新（基于论文「{paper_title}」的对话）

**触发方式**：进化 Agent 对话分析

**变更摘要**：{summary}

**执行的编辑**：{edits_detail}
"""
        changelog_p = self.changelog_path(user_id)
        with open(changelog_p, "a", encoding="utf-8") as f:
            f.write(changelog_entry)

        path.unlink(missing_ok=True)
        self._profile_cache = None
        return True

    def reject_pending(self, user_id: str) -> bool:
        path = self.pending_updates_path(user_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def get_pending(self, user_id: str) -> Optional[dict]:
        path = self.pending_updates_path(user_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ==================== 编辑操作实现 ====================

    def _apply_append_example(self, profile: str, edit: dict) -> str:
        section = edit.get("section", "good_examples")
        marker = self.SECTION_MARKERS.get(section)
        if not marker:
            return profile

        placeholder = "（暂无，将在实际使用中积累）"
        if placeholder in profile:
            idx = profile.find(marker)
            if idx != -1:
                placeholder_idx = profile.find(placeholder, idx)
                if placeholder_idx != -1:
                    return profile[:placeholder_idx] + edit["content"] + profile[placeholder_idx + len(placeholder):]

        idx = profile.find(marker)
        if idx == -1:
            return profile
        next_section_idx = self._find_next_section(profile, idx + len(marker))
        insert_pos = next_section_idx if next_section_idx != -1 else len(profile)
        return profile[:insert_pos] + "\n" + edit["content"] + "\n" + profile[insert_pos:]

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
        return profile[:idx] + trailing + "\n" + edit["content"] + "\n\n" + profile[insert_pos:]

    def _apply_replace_text(self, profile: str, edit: dict) -> str:
        old_text = edit.get("old_text", "")
        new_text = edit.get("new_text", "")
        if old_text and old_text in profile:
            return profile.replace(old_text, new_text, 1)
        return profile

    def _find_next_section(self, profile: str, start: int) -> int:
        match = re.compile(r'\n##\s').search(profile, start)
        return match.start() if match else -1


evolution_service = EvolutionService()
