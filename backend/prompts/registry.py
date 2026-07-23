from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict


PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class PromptVersion:
    name: str
    author: str
    date: str
    reason: str
    rollback_version: str
    template_file: str


PROMPT_REGISTRY: Dict[str, PromptVersion] = {
    "email_digest_v1": PromptVersion(
        name="email_digest_v1",
        author="nightshift-backend",
        date="2026-03-07",
        reason="邮件晨报改为两段式 LLM 摘要，区分主要变更与后续建议",
        rollback_version="none",
        template_file="templates/email_digest_v1.txt",
    ),
    "trending_detail_summary_v2": PromptVersion(
        name="trending_detail_summary_v2",
        author="nightshift-backend",
        date="2026-03-07",
        reason="页面1热点详情摘要升级为两段式输出，区分列表摘要与详情解读",
        rollback_version="trending_detail_summary_v1",
        template_file="templates/trending_detail_summary_v2.txt",
    ),
    "trending_detail_summary_v1": PromptVersion(
        name="trending_detail_summary_v1",
        author="nightshift-backend",
        date="2026-03-06",
        reason="页面1热点详情摘要首版，进入详情后按项目生成中文总结",
        rollback_version="none",
        template_file="templates/trending_detail_summary_v1.txt",
    ),
    "report_qa_v2": PromptVersion(
        name="report_qa_v2",
        author="nightshift-backend",
        date="2026-03-07",
        reason="页面2晨报问答补充仓库上下文，要求围绕用户问题而非复述晨报",
        rollback_version="report_qa_v1",
        template_file="templates/report_qa_v2.txt",
    ),
    "repo_context_qa_v1": PromptVersion(
        name="repo_context_qa_v1",
        author="nightshift-backend",
        date="2026-07-23",
        reason="为外部 Agent 平台提供基于 README、目录、变更、PR 与 Commit 的仓库问答",
        rollback_version="none",
        template_file="templates/repo_context_qa_v1.txt",
    ),
    "report_qa_v1": PromptVersion(
        name="report_qa_v1",
        author="nightshift-backend",
        date="2026-03-03",
        reason="页面2晨报问答首版，基于当前晨报上下文回答追问",
        rollback_version="none",
        template_file="templates/report_qa_v1.txt",
    ),
    "report_summary_v2": PromptVersion(
        name="report_summary_v2",
        author="nightshift-backend",
        date="2026-02-25",
        reason="页面2晨报摘要增强版本，强化风险结论与可执行动作",
        rollback_version="report_summary_v1",
        template_file="templates/report_summary_v2.txt",
    ),
    "report_todo_v2": PromptVersion(
        name="report_todo_v2",
        author="nightshift-backend",
        date="2026-02-25",
        reason="页面2待办增强版本，严格限制输出格式，提升解析稳定性",
        rollback_version="report_todo_v1",
        template_file="templates/report_todo_v2.txt",
    ),
    "report_summary_v1": PromptVersion(
        name="report_summary_v1",
        author="nightshift-backend",
        date="2026-02-25",
        reason="页面2晨报摘要最小可用版本，强调可执行性",
        rollback_version="none",
        template_file="templates/report_summary_v1.txt",
    ),
    "report_todo_v1": PromptVersion(
        name="report_todo_v1",
        author="nightshift-backend",
        date="2026-02-25",
        reason="页面2待办输出最小可用版本，统一优先级前缀",
        rollback_version="none",
        template_file="templates/report_todo_v1.txt",
    ),
}


def get_prompt(prompt_name: str) -> PromptVersion:
    if prompt_name not in PROMPT_REGISTRY:
        raise KeyError(f"unknown prompt: {prompt_name}")
    return PROMPT_REGISTRY[prompt_name]


@lru_cache(maxsize=32)
def _load_template_content(template_file: str) -> str:
    template_path = PROMPTS_DIR / template_file
    return template_path.read_text(encoding="utf-8")


def render_prompt(prompt_name: str, **kwargs: object) -> str:
    prompt_version = get_prompt(prompt_name)
    content = _load_template_content(prompt_version.template_file)
    return content.format(**kwargs)
