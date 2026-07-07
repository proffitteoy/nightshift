package com.example.myapplication3.ui.chat

import android.graphics.Typeface
import android.os.Bundle
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.core.view.setPadding
import androidx.fragment.app.Fragment
import com.example.myapplication3.MainActivity
import com.example.myapplication3.R
import com.example.myapplication3.databinding.FragmentChatBinding
import com.example.myapplication3.network.ApiClient
import com.example.myapplication3.network.models.DeepAnalysisRequest
import com.example.myapplication3.network.models.DeepAnalysisResponse
import com.example.myapplication3.network.ApiErrorParser
import com.example.myapplication3.network.models.DailyReportResponse
import com.example.myapplication3.network.models.RepoSubscriptionRequest
import com.example.myapplication3.network.models.ReportQaResponse
import com.example.myapplication3.ui.CurrentRepoStore
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import kotlin.math.roundToInt

class ChatFragment : Fragment() {

    private var _binding: FragmentChatBinding? = null
    private val binding get() = checkNotNull(_binding)

    private var currentReport: DailyReportResponse.DailyReport? = null
    private var currentReportKey: String = ""
    private var currentReportRepoUrl: String = ""
    private val qaMessages = mutableListOf<QaMessage>()
    private var qaPending = false
    private var deepAnalysisPending = false

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentChatBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        binding.menuButton.setOnClickListener { openDrawer() }
        binding.buttonGenerateReport.setOnClickListener { generateReportFromSelectedRepo() }
        binding.buttonLoadLatestReport.setOnClickListener { startDeepAnalysis() }
        binding.buttonSendQa.setOnClickListener { sendQaQuestion() }

        bindSection(binding.sectionRiskHeader, binding.sectionRiskContent, binding.sectionRiskArrow, true)
        bindSection(binding.sectionHandoverHeader, binding.sectionHandoverContent, binding.sectionHandoverArrow, false)
        bindSection(binding.sectionQaHeader, binding.sectionQaContent, binding.sectionQaArrow, true)

        binding.reportRepoInput.setText(DEFAULT_REPO_URL)
        refreshSelectedRepoIndicator()
        showEmptyState()
    }

    override fun onResume() {
        super.onResume()
        refreshSelectedRepoIndicator()
    }

    private fun openDrawer() {
        (activity as? MainActivity)?.openDrawer()
    }

    private fun generateReportFromSelectedRepo() {
        val repoUrl = CurrentRepoStore.getSelectedRepoUrl(requireContext()).orEmpty()
        if (repoUrl.isBlank()) {
            showToast(getString(R.string.report_error_missing_selected_repo))
            return
        }

        currentReportRepoUrl = repoUrl
        refreshSelectedRepoIndicator()
        requestReport(repoUrl, getString(R.string.report_loading_generate))
    }

    private fun generateReportFromInputUrl() {
        val repoUrl = binding.reportRepoInput.text?.toString()?.trim().orEmpty().ifBlank { DEFAULT_REPO_URL }
        binding.reportRepoInput.setText(repoUrl)
        currentReportRepoUrl = repoUrl
        requestReport(repoUrl, getString(R.string.report_loading_latest))
    }

    private fun requestReport(repoUrl: String, loadingMessage: String) {
        setLoading(true, loadingMessage)
        ApiClient.getApiService().generateDailyReport(RepoSubscriptionRequest(repoUrl))
            .enqueue(object : Callback<DailyReportResponse> {
                override fun onResponse(
                    call: Call<DailyReportResponse>,
                    response: Response<DailyReportResponse>,
                ) {
                    setLoading(false)
                    if (response.isSuccessful) {
                        renderReport(response.body()?.report)
                    } else {
                        showErrorState(ApiErrorParser.parse(response, getString(R.string.report_error_generate, "request failed")))
                    }
                }

                override fun onFailure(call: Call<DailyReportResponse>, t: Throwable) {
                    setLoading(false)
                    showErrorState(getString(R.string.report_error_generate, t.message ?: "unknown"))
                }
            })
    }

    private fun renderReport(report: DailyReportResponse.DailyReport?) {
        currentReport = report
        if (report == null) {
            showEmptyState()
            return
        }

        if (currentReportRepoUrl.isBlank()) {
            currentReportRepoUrl = resolveRepoUrlFromReport(report)
        }

        binding.emptyStateText.visibility = View.GONE
        binding.reportContentContainer.visibility = View.VISIBLE
        binding.reportMetaText.text = getString(
            R.string.report_meta,
            report.repository ?: getString(R.string.home_repo_fallback),
            report.timeRange ?: "",
        )

        val summary = report.summary
        binding.summaryUnresolvedValue.text = summary?.unresolvedCount?.toString() ?: "0"
        binding.summaryHighRiskValue.text = summary?.highRiskCount?.toString() ?: "0"
        binding.summaryOverdueValue.text = summary?.overdueCount?.toString() ?: "0"
        binding.summaryConclusionValue.text = summary?.keyConclusion?.ifBlank { report.summaryText.orEmpty() }
            ?: report.summaryText.orEmpty()

        val keyRisk = report.sections?.keyRiskSummary
        binding.keyRiskText.text = keyRisk?.text?.ifBlank { report.summaryText.orEmpty() } ?: report.summaryText.orEmpty()
        binding.keyRiskItems.text = buildLabeledBlock(
            getString(R.string.report_high_priority),
            keyRisk?.highPriorityItems.orEmpty(),
        )

        val handover = report.sections?.handoverRecords
        binding.handoverPrsText.text = buildLabeledBlock(
            getString(R.string.report_top_prs),
            handover?.topPrs.orEmpty().map { "PR #${it.number} ${it.title} (${it.user})" },
        )
        binding.handoverCommitsText.text = buildLabeledBlock(
            getString(R.string.report_top_commits),
            handover?.topCommits.orEmpty().map { "${it.sha} ${it.author}: ${it.message}" },
        )

        resetQaStateIfNeeded(report)
        renderQaMessages()
        scrollToBottom()
    }

    private fun showEmptyState() {
        binding.reportContentContainer.visibility = View.GONE
        binding.emptyStateText.visibility = View.VISIBLE
        binding.emptyStateText.text = getString(R.string.report_empty)
        currentReport = null
        currentReportKey = ""
        currentReportRepoUrl = ""
        qaMessages.clear()
        qaPending = false
        binding.qaInput.setText("")
    }

    private fun showErrorState(message: String) {
        binding.reportContentContainer.visibility = View.GONE
        binding.emptyStateText.visibility = View.VISIBLE
        binding.emptyStateText.text = message
        showToast(message)
    }

    private fun resetQaStateIfNeeded(report: DailyReportResponse.DailyReport) {
        val key = listOf(
            report.repository.orEmpty(),
            report.reportDate.orEmpty(),
            report.summaryText.orEmpty(),
            currentReportRepoUrl,
        ).joinToString("|")

        if (key == currentReportKey) {
            return
        }

        currentReportKey = key
        qaMessages.clear()
        qaMessages.add(
            QaMessage(
                role = ROLE_ASSISTANT,
                text = getString(
                    R.string.report_qa_seed,
                    report.repository?.ifBlank { getString(R.string.home_repo_fallback) }
                        ?: getString(R.string.home_repo_fallback),
                ),
                source = SOURCE_RULES,
            ),
        )
        qaPending = false
        binding.qaInput.setText("")
    }

    private fun sendQaQuestion() {
        val report = currentReport ?: run {
            showToast(getString(R.string.report_error_missing_report))
            return
        }

        val question = binding.qaInput.text?.toString()?.trim().orEmpty()
        if (question.isBlank()) {
            showToast(getString(R.string.report_error_empty_question))
            return
        }

        qaMessages.add(QaMessage(role = ROLE_USER, text = question))
        qaPending = true
        binding.qaInput.setText("")
        renderQaMessages()

        val payload = mutableMapOf<String, Any>(
            "report" to report,
            "question" to question,
        )
        val repoUrl = currentReportRepoUrl.ifBlank { resolveRepoUrlFromReport(report) }
        if (repoUrl.isNotBlank()) {
            payload["repo_url"] = repoUrl
        }

        ApiClient.getApiService().askReportQuestion(payload).enqueue(object : Callback<ReportQaResponse> {
            override fun onResponse(
                call: Call<ReportQaResponse>,
                response: Response<ReportQaResponse>,
            ) {
                qaPending = false
                if (response.isSuccessful && response.body() != null) {
                    val body = response.body()
                    qaMessages.add(
                        QaMessage(
                            role = ROLE_ASSISTANT,
                            text = body?.answer?.ifBlank { "当前没有返回可展示的回答。" } ?: "当前没有返回可展示的回答。",
                            source = body?.source ?: SOURCE_RULES,
                        ),
                    )
                } else {
                    qaMessages.add(
                        QaMessage(
                            role = ROLE_ASSISTANT,
                            text = getString(
                                R.string.report_qa_failure,
                                ApiErrorParser.parse(response, "request failed"),
                            ),
                            source = SOURCE_RULES,
                        ),
                    )
                }
                renderQaMessages()
            }

            override fun onFailure(call: Call<ReportQaResponse>, t: Throwable) {
                qaPending = false
                qaMessages.add(
                    QaMessage(
                        role = ROLE_ASSISTANT,
                        text = getString(R.string.report_qa_failure, t.message ?: "unknown"),
                        source = SOURCE_RULES,
                    ),
                )
                renderQaMessages()
            }
        })
    }

    private fun renderQaMessages() {
        binding.qaMessagesContainer.removeAllViews()
        qaMessages.forEach { binding.qaMessagesContainer.addView(createQaMessageView(it)) }
        if (qaPending) {
            binding.qaMessagesContainer.addView(
                createQaMessageView(
                    QaMessage(
                        role = ROLE_ASSISTANT,
                        text = getString(R.string.report_qa_loading),
                        source = SOURCE_RULES,
                        pending = true,
                    ),
                ),
            )
        }
        binding.buttonSendQa.isEnabled = !qaPending
        scrollToBottom()
    }

    private fun createQaMessageView(message: QaMessage): View {
        val container = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            background = ContextCompat.getDrawable(
                requireContext(),
                if (message.role == ROLE_USER) R.drawable.bg_message_user else R.drawable.bg_message_assistant,
            )
            alpha = if (message.pending) 0.72f else 1f
            setPadding(dp(10))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                topMargin = dp(8)
            }
        }

        val metaRow = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }

        val roleLabel = TextView(requireContext()).apply {
            text = if (message.role == ROLE_USER) {
                getString(R.string.report_user_role)
            } else {
                getString(R.string.report_ai_role)
            }
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_muted))
            textSize = 12f
        }

        metaRow.addView(roleLabel)

        if (message.role == ROLE_ASSISTANT) {
            val sourceLabel = TextView(requireContext()).apply {
                text = getString(R.string.report_source_format, message.source ?: SOURCE_RULES)
                setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_brand_dark))
                textSize = 12f
                setPadding(dp(8), dp(2), dp(8), dp(2))
                background = ContextCompat.getDrawable(requireContext(), R.drawable.bg_soft_panel)
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                ).apply {
                    marginStart = dp(8)
                }
            }
            metaRow.addView(sourceLabel)
        }

        val content = TextView(requireContext()).apply {
            text = message.text
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_text))
            textSize = 13f
            setLineSpacing(0f, 1.2f)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                topMargin = dp(6)
            }
        }

        container.addView(metaRow)
        container.addView(content)
        return container
    }

    private fun buildLabeledBlock(label: String, items: List<String>): String {
        val body = if (items.isEmpty()) getString(R.string.report_none) else items.joinToString("\n")
        return "$label\n$body"
    }

    private fun bindSection(header: View, content: View, arrow: TextView, expanded: Boolean) {
        setSectionExpanded(content, arrow, expanded)
        header.setOnClickListener {
            setSectionExpanded(content, arrow, content.visibility != View.VISIBLE)
        }
    }

    private fun setSectionExpanded(content: View, arrow: TextView, expanded: Boolean) {
        content.visibility = if (expanded) View.VISIBLE else View.GONE
        arrow.text = if (expanded) "▼" else "▲"
    }

    private fun setLoading(loading: Boolean, message: String? = null) {
        binding.progressBar.visibility = if (loading) View.VISIBLE else View.GONE
        binding.buttonGenerateReport.isEnabled = !loading && !deepAnalysisPending
        binding.buttonLoadLatestReport.isEnabled = !loading && !deepAnalysisPending
        if (loading && !message.isNullOrBlank()) {
            binding.emptyStateText.text = message
            binding.emptyStateText.visibility = View.VISIBLE
        }
    }

    private fun refreshSelectedRepoIndicator() {
        val repoUrl = CurrentRepoStore.getSelectedRepoUrl(requireContext())
        binding.reportSelectedRepoText.text = if (repoUrl.isNullOrBlank()) {
            getString(R.string.report_selected_repo_none)
        } else {
            getString(R.string.report_selected_repo, repoUrl)
        }
    }

    private fun resolveRepoUrlFromReport(report: DailyReportResponse.DailyReport): String {
        val repository = report.repository?.trim().orEmpty()
        return if (repository.count { it == '/' } == 1) {
            "https://github.com/$repository"
        } else {
            ""
        }
    }


    /**
     * 点击"深度分析"按钮：自动用当前订阅仓库的 URL 拼接输入，
     * 发送给讯飞工作流进行 AI 深度分析。
     */
    private fun startDeepAnalysis() {
        val repoUrl = CurrentRepoStore.getSelectedRepoUrl(requireContext()).orEmpty()
        if (repoUrl.isBlank()) {
            showToast(getString(R.string.report_error_missing_selected_repo))
            return
        }

        val userInput = "分析 $repoUrl"
        startDeepAnalysis(userInput)
    }

    private fun startDeepAnalysis(userInput: String) {
        deepAnalysisPending = true
        setLoading(true, getString(R.string.report_loading_latest))

        val request = DeepAnalysisRequest(userInput)
        ApiClient.getApiService().deepAnalysis(request)
            .enqueue(object : Callback<DeepAnalysisResponse> {
                override fun onResponse(
                    call: Call<DeepAnalysisResponse>,
                    response: Response<DeepAnalysisResponse>,
                ) {
                    deepAnalysisPending = false
                    setLoading(false)
                    if (response.isSuccessful && response.body() != null) {
                        val body = response.body()!!
                        val resultText = body.content.ifBlank { body.message.ifBlank { "分析完成，但未返回内容" } }
                        // 将结果追加到 QA 区域显示
                        qaMessages.add(QaMessage(role = ROLE_USER, text = userInput))
                        qaMessages.add(QaMessage(role = ROLE_ASSISTANT, text = resultText, source = "workflow"))
                        renderQaMessages()
                        scrollToBottom()
                    } else {
                        showErrorState(getString(R.string.report_error_latest, ApiErrorParser.parse(response, "request failed")))
                    }
                }

                override fun onFailure(call: Call<DeepAnalysisResponse>, t: Throwable) {
                    deepAnalysisPending = false
                    setLoading(false)
                    showErrorState(getString(R.string.report_error_latest, t.message ?: "unknown"))
                }
            })
    }

    private fun scrollToBottom() {
        binding.scrollView.post { binding.scrollView.fullScroll(View.FOCUS_DOWN) }
    }

    private fun showToast(message: String) {
        Toast.makeText(requireContext(), message, Toast.LENGTH_SHORT).show()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    private data class QaMessage(
        val role: String,
        val text: String,
        val source: String? = null,
        val pending: Boolean = false,
    )

    companion object {
        private const val DEFAULT_REPO_URL = "https://github.com/psf/requests"
        private const val ROLE_USER = "user"
        private const val ROLE_ASSISTANT = "assistant"
        private const val SOURCE_RULES = "rules"
    }
}
