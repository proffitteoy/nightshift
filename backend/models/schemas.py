from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.security import (
    normalize_display_name,
    normalize_email,
    normalize_email_endpoint,
    normalize_github_repo_url,
    normalize_llm_base_url,
    normalize_llm_model_name,
    normalize_repo_full_name,
    normalize_runtime_region,
    normalize_runtime_secret,
    sanitize_untrusted_text,
)


INPUT_MODEL_CONFIG = ConfigDict(extra="forbid")


class GitHubTokenRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    token: str = Field(..., min_length=1)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        return normalize_runtime_secret(value, field_name="token", max_length=255)


class LLMRuntimeConfigRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    api_key: str = Field(..., min_length=1)
    base_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4/", min_length=1)
    model: str = Field(default="glm-4-flash", min_length=1)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    top_p: Optional[float] = Field(default=None, ge=0, le=1)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32000)
    timeout_seconds: Optional[float] = Field(default=None, ge=1, le=120)
    max_retries: Optional[int] = Field(default=None, ge=0, le=5)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        return normalize_runtime_secret(value, field_name="api_key")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return normalize_llm_base_url(value)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        return normalize_llm_model_name(value)


class AuthRegisterRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=60)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_display_name(value, allow_empty=True)
        return normalized or None


class AuthLoginRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class AuthChangePasswordRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    current_password: str = Field(..., min_length=8, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)


class RepoSubscriptionRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: str) -> str:
        return normalize_github_repo_url(value)


class RepoReportRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: str) -> str:
        return normalize_github_repo_url(value)


class ReportQuestionRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    report: "DailyReport"
    question: str = Field(..., min_length=1, max_length=400)
    repo_url: Optional[str] = None

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=400)

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return normalize_github_repo_url(value)


class CodePanoramaRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repo_url: str
    depth: int = Field(default=2, ge=1, le=5)
    entry_hint: Optional[str] = Field(default=None, max_length=120)

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: str) -> str:
        return normalize_github_repo_url(value)

    @field_validator("entry_hint")
    @classmethod
    def validate_entry_hint(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = sanitize_untrusted_text(value, max_length=120, allow_empty=True)
        return normalized or None


SubscriptionFrequency = Literal["daily", "weekly", "weekday"]
UpdateStrategy = Literal["incremental", "full"]
DeliveryMode = Literal["instant", "scheduled"]


class SubscriptionCreateRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repo_url: str
    morning_report_enabled: bool = True
    code_panorama_enabled: bool = True
    recipient_email: str = ""
    delivery_mode: DeliveryMode = "scheduled"
    frequency: SubscriptionFrequency = "daily"
    delivery_time: str = "09:00"
    update_strategy: UpdateStrategy = "incremental"

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: str) -> str:
        return normalize_github_repo_url(value)

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient_email(cls, value: str) -> str:
        return normalize_email(value, allow_empty=True)

    @field_validator("delivery_time")
    @classmethod
    def validate_delivery_time(cls, value: str) -> str:
        return _normalize_delivery_time(value)


class SubscriptionUpdateRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repo_url: Optional[str] = None
    morning_report_enabled: Optional[bool] = None
    code_panorama_enabled: Optional[bool] = None
    recipient_email: Optional[str] = None
    delivery_mode: Optional[DeliveryMode] = None
    frequency: Optional[SubscriptionFrequency] = None
    delivery_time: Optional[str] = None
    update_strategy: Optional[UpdateStrategy] = None

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return normalize_github_repo_url(value)

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return normalize_email(value, allow_empty=True)

    @field_validator("delivery_time")
    @classmethod
    def validate_delivery_time(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _normalize_delivery_time(value)


class RuntimeConfigUpdateRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    github_token: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    llm_temperature: Optional[float] = Field(default=None, ge=0, le=2)
    llm_top_p: Optional[float] = Field(default=None, ge=0, le=1)
    llm_max_tokens: Optional[int] = Field(default=None, ge=1, le=32000)
    llm_timeout_seconds: Optional[float] = Field(default=None, ge=1, le=120)
    llm_max_retries: Optional[int] = Field(default=None, ge=0, le=5)
    email_access_key_id: Optional[str] = None
    email_access_key_secret: Optional[str] = None
    email_account_name: Optional[str] = None
    email_region_id: Optional[str] = None
    email_endpoint: Optional[str] = None
    email_address_type: Optional[int] = Field(default=None, ge=0, le=1)
    email_reply_to_address: Optional[bool] = None
    email_from_alias: Optional[str] = None
    email_connect_timeout_ms: Optional[int] = Field(default=None, ge=1, le=60000)
    email_read_timeout_ms: Optional[int] = Field(default=None, ge=1, le=120000)

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_runtime_secret(value, field_name="github_token", allow_empty=True, max_length=255)
        return normalized or None

    @field_validator("llm_api_key")
    @classmethod
    def validate_llm_api_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_runtime_secret(value, field_name="llm_api_key", allow_empty=True)
        return normalized or None

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_llm_base_url(value, allow_empty=True)
        return normalized or None

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_llm_model_name(value, allow_empty=True)
        return normalized or None

    @field_validator("email_access_key_id")
    @classmethod
    def validate_email_access_key_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_runtime_secret(value, field_name="email_access_key_id", allow_empty=True)
        return normalized or None

    @field_validator("email_access_key_secret")
    @classmethod
    def validate_email_access_key_secret(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_runtime_secret(value, field_name="email_access_key_secret", allow_empty=True)
        return normalized or None

    @field_validator("email_account_name")
    @classmethod
    def validate_email_account_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_email(value, allow_empty=True)
        return normalized or None

    @field_validator("email_region_id")
    @classmethod
    def validate_email_region_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_runtime_region(value, allow_empty=True)
        return normalized or None

    @field_validator("email_endpoint")
    @classmethod
    def validate_email_endpoint(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = normalize_email_endpoint(value, allow_empty=True)
        return normalized or None

    @field_validator("email_from_alias")
    @classmethod
    def validate_email_from_alias(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = sanitize_untrusted_text(value, max_length=60, allow_empty=True)
        return normalized or None


class RuntimeConfigResponse(BaseModel):
    github_token_configured: bool
    llm_api_key_configured: bool
    llm_base_url: str
    llm_model: str
    llm_temperature: Optional[float] = None
    llm_top_p: Optional[float] = None
    llm_max_tokens: Optional[int] = None
    llm_timeout_seconds: float = 25.0
    llm_max_retries: int = 1
    email_access_key_id_configured: bool = False
    email_access_key_secret_configured: bool = False
    email_account_name: str = ""
    email_region_id: str = "cn-hangzhou"
    email_endpoint: str = "dm.aliyuncs.com"
    email_address_type: int = 1
    email_reply_to_address: bool = False
    email_from_alias: str = ""
    email_connect_timeout_ms: int = 5000
    email_read_timeout_ms: int = 10000


class RepoSyncSummary(BaseModel):
    added_count: int = 0
    skipped_existing_count: int = 0
    public_repo_count: int = 0
    private_repo_count: int = 0
    message: str = ""


class UserProfileResponse(BaseModel):
    id: int
    email: str
    display_name: str
    auth_source: str
    github_login: str = ""
    avatar_url: str = ""
    github_connected: bool = False
    created_at: str
    updated_at: str
    last_login_at: Optional[str] = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfileResponse
    repo_sync: Optional[RepoSyncSummary] = None


OAuthFlowMode = Literal["login", "connect"]
OAuthSessionStatus = Literal["pending", "completed", "failed"]


class GitHubOAuthStartResponse(BaseModel):
    authorize_url: str
    poll_token: str
    expires_in: int
    mode: OAuthFlowMode


class GitHubOAuthPollResponse(BaseModel):
    status: OAuthSessionStatus
    message: str = ""
    auth: Optional[AuthTokenResponse] = None


def _normalize_delivery_time(value: str) -> str:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("delivery_time must use HH:MM format")
    hour, minute = parts
    if not (hour.isdigit() and minute.isdigit()):
        raise ValueError("delivery_time must use HH:MM format")
    hour_i = int(hour)
    minute_i = int(minute)
    if hour_i < 0 or hour_i > 23 or minute_i < 0 or minute_i > 59:
        raise ValueError("delivery_time must be a valid 24h time")
    return f"{hour_i:02d}:{minute_i:02d}"
class RootResponse(BaseModel):
    message: str


class MessageResponse(BaseModel):
    message: str


class ProjectSubscribeResponse(BaseModel):
    message: str
    data_file: str


class TrendingItem(BaseModel):
    # 允许保留历史字段，确保页面兼容。
    model_config = ConfigDict(extra="allow")

    repo_full_name: str
    description: str = ""
    project_summary: str = ""
    stars_total: int = 0
    trend_7d: List[int] = Field(default_factory=lambda: [0, 0, 0, 0, 0, 0, 0], min_length=7, max_length=7)


class TrendingAnalysisResponse(BaseModel):
    message: str
    file_path: str
    data: List[TrendingItem]


class TrendingDetailSummaryRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repo_full_name: str = Field(..., min_length=1)
    description: str = ""
    project_summary: str = ""
    language: str = ""
    stars_total: int = 0
    trend_7d: List[int] = Field(default_factory=list)
    link: str = ""

    @field_validator("repo_full_name")
    @classmethod
    def validate_repo_full_name(cls, value: str) -> str:
        return normalize_repo_full_name(value)

    @field_validator("description", "project_summary", "language")
    @classmethod
    def validate_summary_fields(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=500, allow_empty=True)

    @field_validator("link")
    @classmethod
    def validate_link(cls, value: str) -> str:
        return normalize_github_repo_url(value, allow_empty=True)

    @field_validator("trend_7d")
    @classmethod
    def validate_trend_7d(cls, value: List[int]) -> List[int]:
        if len(value) > 7:
            raise ValueError("trend_7d cannot exceed 7 points")
        return [int(item) for item in value]


class TrendingDetailSummaryResponse(BaseModel):
    repo_full_name: str
    summary: str
    source: Literal["llm", "rules"]


class DailyReportStats(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    pr_count: int = 0
    commit_count: int = 0


class DailyReportPullRequest(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    number: int = 0
    title: str = ""
    user: str = ""
    files_count: int = 0

    @field_validator("title", "user")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=200, allow_empty=True)


class DailyReportCommit(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    sha: str = ""
    author: str = ""
    message: str = ""

    @field_validator("author")
    @classmethod
    def validate_author(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=120, allow_empty=True)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=300, allow_empty=True)


class DailyReportDetails(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    top_prs: List[DailyReportPullRequest] = Field(default_factory=list)
    top_commits: List[DailyReportCommit] = Field(default_factory=list)

    @field_validator("top_prs")
    @classmethod
    def validate_top_prs(cls, value: List[DailyReportPullRequest]) -> List[DailyReportPullRequest]:
        if len(value) > 10:
            raise ValueError("top_prs cannot exceed 10 items")
        return value

    @field_validator("top_commits")
    @classmethod
    def validate_top_commits(cls, value: List[DailyReportCommit]) -> List[DailyReportCommit]:
        if len(value) > 10:
            raise ValueError("top_commits cannot exceed 10 items")
        return value


class ReportSummary(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    unresolved_count: int = 0
    high_risk_count: int = 0
    overdue_count: int = 0
    key_conclusion: str = ""

    @field_validator("key_conclusion")
    @classmethod
    def validate_key_conclusion(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=300, allow_empty=True)


class ReportKeyRiskSummary(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    text: str = ""
    high_priority_items: List[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=4000, allow_empty=True)

    @field_validator("high_priority_items")
    @classmethod
    def validate_high_priority_items(cls, value: List[str]) -> List[str]:
        if len(value) > 20:
            raise ValueError("high_priority_items cannot exceed 20 items")
        return [sanitize_untrusted_text(item, max_length=300, allow_empty=True) for item in value if str(item).strip()]


class ReportHandoverRecords(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    top_prs: List[DailyReportPullRequest] = Field(default_factory=list)
    top_commits: List[DailyReportCommit] = Field(default_factory=list)


class ReportOnboardingSummary(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repository: str = "unknown"
    entry_context: str = ""
    next_actions: List[str] = Field(default_factory=list)

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        normalized = sanitize_untrusted_text(value, max_length=200, allow_empty=True)
        return normalized or "unknown"

    @field_validator("entry_context")
    @classmethod
    def validate_entry_context(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=300, allow_empty=True)

    @field_validator("next_actions")
    @classmethod
    def validate_next_actions(cls, value: List[str]) -> List[str]:
        if len(value) > 20:
            raise ValueError("next_actions cannot exceed 20 items")
        return [sanitize_untrusted_text(item, max_length=300, allow_empty=True) for item in value if str(item).strip()]


class RiskTrendPoint(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    day: str
    high_risk_count: int


class TaskPriorityDistribution(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    high: int = 0
    medium: int = 0
    low: int = 0


class ReportCharts(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    risk_trend: List[RiskTrendPoint] = Field(default_factory=list)
    task_priority_distribution: TaskPriorityDistribution = Field(default_factory=TaskPriorityDistribution)


class ReportSections(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    key_risk_summary: ReportKeyRiskSummary = Field(default_factory=ReportKeyRiskSummary)
    handover_records: ReportHandoverRecords = Field(default_factory=ReportHandoverRecords)
    onboarding_summary: ReportOnboardingSummary = Field(default_factory=ReportOnboardingSummary)
    charts: ReportCharts = Field(default_factory=ReportCharts)


class DailyReport(BaseModel):
    model_config = INPUT_MODEL_CONFIG
    repository: str = "unknown"
    report_date: str
    time_range: str = ""
    stats: DailyReportStats = Field(default_factory=DailyReportStats)
    summary_text: str = ""
    todo_list: List[str] = Field(default_factory=list)
    details: DailyReportDetails = Field(default_factory=DailyReportDetails)
    summary: ReportSummary = Field(default_factory=ReportSummary)
    sections: ReportSections = Field(default_factory=ReportSections)

    @field_validator("repository")
    @classmethod
    def validate_report_repository(cls, value: str) -> str:
        normalized = sanitize_untrusted_text(value, max_length=200, allow_empty=True)
        return normalized or "unknown"

    @field_validator("time_range")
    @classmethod
    def validate_time_range(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=200, allow_empty=True)

    @field_validator("summary_text")
    @classmethod
    def validate_summary_text(cls, value: str) -> str:
        return sanitize_untrusted_text(value, max_length=4000, allow_empty=True)

    @field_validator("todo_list")
    @classmethod
    def validate_todo_list(cls, value: List[str]) -> List[str]:
        if len(value) > 20:
            raise ValueError("todo_list cannot exceed 20 items")
        return [sanitize_untrusted_text(item, max_length=300, allow_empty=True) for item in value if str(item).strip()]


class ReportByUserResponse(BaseModel):
    message: str
    report: DailyReport
    data_file: str


class ReportQaResponse(BaseModel):
    answer: str
    source: Literal["llm", "rules"]


class CodePanoramaNode(BaseModel):
    id: str
    file_path: str
    function_name: str
    summary: str
    signature: str
    line_start: int
    line_end: int


class CodePanoramaEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    type: str


class CodePanoramaMeta(BaseModel):
    source_repo: str
    language: str
    commit_sha: str
    generated_at: str
    drilldown_supported: bool = True


class CodePanoramaResponse(BaseModel):
    nodes: List[CodePanoramaNode]
    edges: List[CodePanoramaEdge]
    meta: CodePanoramaMeta


class SubscriptionResponse(BaseModel):
    id: int
    repo_url: str
    morning_report_enabled: bool
    code_panorama_enabled: bool
    recipient_email: str = ""
    delivery_mode: DeliveryMode = "scheduled"
    frequency: SubscriptionFrequency
    delivery_time: str
    update_strategy: UpdateStrategy
    created_at: str
    updated_at: str


class SubscriptionDeleteResponse(BaseModel):
    deleted: bool


class ApiErrorDetail(BaseModel):
    code: str
    message: str




class DeepAnalysisRequest(BaseModel):
    """用户提交仓库地址或问题，触发工作流深度分析。"""
    user_input: str = Field(..., min_length=1, max_length=2000, description="用户输入，可以是 GitHub URL 或自然语言问题")


class DeepAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: int = 0
    message: str = ""
    content: str = ""


class ApiErrorResponse(BaseModel):
    success: bool = False
    error: ApiErrorDetail
