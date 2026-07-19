package com.example.myapplication3.ui.chat

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
import com.example.myapplication3.network.ApiErrorParser
import com.example.myapplication3.network.models.DailyReportResponse
import com.example.myapplication3.network.models.RepoSubscriptionRequest
import com.example.myapplication3.network.models.ReportQaResponse
import com.example.myapplication3.ui.CurrentRepoStore
import okhttp3.Call as OkHttpCall
import okhttp3.Callback as OkHttpCallback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response as OkHttpResponse
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.io.IOException
import kotlin.math.roundToInt

class ChatFragment : Fragment() {

    private var _binding: FragmentChatBinding? = null
    private val binding get() = checkNotNull(_binding)

    private var currentReport: DailyReportResponse.DailyReport? = null
    private var currentReportKey: String = ""
    private var currentReportRepoUrl: String = ""
    private val reportQaMessages = mutableListOf<QaMessage>()
    private var reportQaPending = false

    private val deepAnalysisMessages = mutableListOf<QaMessage>()
    private var deepAnalysisPending = false
    private var deepAnalysisStreamCall: OkHttpCall? = null

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
        binding.buttonCloseDeepAnalysis.setOnClickListener { hideDeepAnalysisPanel() }
        binding.buttonSendDeepQuestion.setOnClickListener { sendDeepAnalysisQuestion() }

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
        renderReportQaMessages()
        scrollToBottom()
    }

    private fun showEmptyState() {
        binding.reportContentContainer.visibility = View.GONE
        binding.emptyStateText.visibility = View.VISIBLE
        binding.emptyStateText.text = getString(R.string.report_empty)
        currentReport = null
        currentReportKey = ""
        currentReportRepoUrl = ""
        reportQaMessages.clear()
        reportQaPending = false
        binding.qaInput.setText("")
        hideDeepAnalysisPanel(clearConversation = true)
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
        reportQaMessages.clear()
        reportQaMessages.add(
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
        reportQaPending = false
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

        reportQaMessages.add(QaMessage(role = ROLE_USER, text = question))
        reportQaPending = true
        binding.qaInput.setText("")
        renderReportQaMessages()

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
                reportQaPending = false
                if (response.isSuccessful && response.body() != null) {
                    val body = response.body()
                    reportQaMessages.add(
                        QaMessage(
                            role = ROLE_ASSISTANT,
                            text = body?.answer?.ifBlank { "当前没有返回可展示的回答。" } ?: "当前没有返回可展示的回答。",
                            source = body?.source ?: SOURCE_RULES,
                        ),
                    )
                } else {
                    reportQaMessages.add(
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
                renderReportQaMessages()
            }

            override fun onFailure(call: Call<ReportQaResponse>, t: Throwable) {
                reportQaPending = false
                reportQaMessages.add(
                    QaMessage(
                        role = ROLE_ASSISTANT,
                        text = getString(R.string.report_qa_failure, t.message ?: "unknown"),
                        source = SOURCE_RULES,
                    ),
                )
                renderReportQaMessages()
            }
        })
    }

    private fun renderReportQaMessages() {
        binding.qaMessagesContainer.removeAllViews()
        reportQaMessages.forEach { binding.qaMessagesContainer.addView(createMessageView(it)) }
        if (reportQaPending) {
            binding.qaMessagesContainer.addView(
                createMessageView(
                    QaMessage(
                        role = ROLE_ASSISTANT,
                        text = getString(R.string.report_qa_loading),
                        source = SOURCE_RULES,
                        pending = true,
                    ),
                ),
            )
        }
        binding.buttonSendQa.isEnabled = !reportQaPending
        scrollToBottom()
    }

    private fun createMessageView(message: QaMessage): View {
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
            text = if (message.role == ROLE_USER) getString(R.string.report_user_role) else getString(R.string.report_ai_role)
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
        binding.buttonSendDeepQuestion.isEnabled = !loading && !deepAnalysisPending
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

    private fun startDeepAnalysis() {
        if (deepAnalysisPending) {
            showToast(getString(R.string.workflow_chat_pending))
            return
        }

        val repoUrl = CurrentRepoStore.getSelectedRepoUrl(requireContext()).orEmpty()
        if (repoUrl.isBlank()) {
            showToast(getString(R.string.report_error_missing_selected_repo))
            return
        }

        beginDeepAnalysisSession(repoUrl)
        val userInput = getString(R.string.workflow_initial_user_message, repoUrl)
        val workflowInput = buildDeepWorkflowInput(userInput, includeHistory = false)
        runDeepAnalysis(userInput, workflowInput)
    }

    private fun beginDeepAnalysisSession(repoUrl: String) {
        deepAnalysisPending = false
        deepAnalysisStreamCall?.cancel()
        deepAnalysisStreamCall = null
        deepAnalysisMessages.clear()
        deepAnalysisMessages.add(
            QaMessage(
                role = ROLE_ASSISTANT,
                text = getString(R.string.workflow_chat_seed),
                source = WORKFLOW_SOURCE,
            ),
        )
        binding.deepAnalysisRepoText.text = getString(R.string.report_selected_repo, repoUrl)
        binding.deepQuestionInput.setText("")
        binding.deepAnalysisPanel.visibility = View.VISIBLE
        renderDeepAnalysisMessages()
    }

    private fun hideDeepAnalysisPanel(clearConversation: Boolean = false) {
        binding.deepAnalysisPanel.visibility = View.GONE
        if (clearConversation) {
            deepAnalysisMessages.clear()
            deepAnalysisPending = false
            deepAnalysisStreamCall?.cancel()
            deepAnalysisStreamCall = null
            binding.deepQuestionInput.setText("")
        }
    }

    private fun sendDeepAnalysisQuestion() {
        val question = binding.deepQuestionInput.text?.toString()?.trim().orEmpty()
        if (question.isBlank()) {
            showToast(getString(R.string.report_error_empty_question))
            return
        }
        if (deepAnalysisPending) {
            showToast(getString(R.string.workflow_chat_pending))
            return
        }
        if (deepAnalysisMessages.isEmpty()) {
            val repoUrl = CurrentRepoStore.getSelectedRepoUrl(requireContext()).orEmpty()
            if (repoUrl.isBlank()) {
                showToast(getString(R.string.report_error_missing_selected_repo))
                return
            }
            beginDeepAnalysisSession(repoUrl)
        }

        binding.deepQuestionInput.setText("")
        val workflowInput = buildDeepWorkflowInput(question, includeHistory = true)
        runDeepAnalysis(question, workflowInput)
    }

    private fun buildDeepWorkflowInput(latestQuestion: String, includeHistory: Boolean): String {
        val repoUrl = CurrentRepoStore.getSelectedRepoUrl(requireContext()).orEmpty().ifBlank {
            currentReportRepoUrl
        }
        if (!includeHistory) {
            return latestQuestion
        }

        val history = deepAnalysisMessages
            .filter { !it.pending }
            .takeLast(MAX_HISTORY_MESSAGES)
            .joinToString("\n") { message ->
                val role = if (message.role == ROLE_USER) "用户" else "AI"
                "$role：${message.text}"
            }

        return buildString {
            append("请继续以大模型对话方式回答晨报交接深度分析追问。")
            if (repoUrl.isNotBlank()) {
                append("\n当前仓库：").append(repoUrl)
            }
            if (history.isNotBlank()) {
                append("\n\n已有对话：\n").append(history)
            }
            append("\n\n用户新问题：").append(latestQuestion)
        }
    }

    private fun runDeepAnalysis(visibleUserMessage: String, workflowInput: String) {
        deepAnalysisPending = true
        setLoading(true)
        deepAnalysisMessages.add(QaMessage(role = ROLE_USER, text = visibleUserMessage))
        deepAnalysisMessages.add(
            QaMessage(
                role = ROLE_ASSISTANT,
                text = getString(R.string.workflow_chat_starting),
                source = WORKFLOW_SOURCE,
                pending = true,
            ),
        )
        renderDeepAnalysisMessages()

        val payload = JSONObject()
            .put("user_input", workflowInput)
            .toString()
            .toRequestBody("application/json; charset=utf-8".toMediaType())
        val request = Request.Builder()
            .url(ApiClient.BASE_URL + "api/project/deep-analysis/stream")
            .post(payload)
            .build()

        deepAnalysisStreamCall?.cancel()
        deepAnalysisStreamCall = ApiClient.getHttpClient().newCall(request)
        deepAnalysisStreamCall?.enqueue(object : OkHttpCallback {
            override fun onResponse(call: OkHttpCall, response: OkHttpResponse) {
                response.use {
                    if (!response.isSuccessful) {
                        val error = response.body?.string().orEmpty().ifBlank { "HTTP ${response.code}" }
                        activity?.runOnUiThread { finishDeepAnalysisWithError(error) }
                        return
                    }

                    val source = response.body?.source()
                    if (source == null) {
                        activity?.runOnUiThread { finishDeepAnalysisWithError("empty stream response") }
                        return
                    }

                    val builder = StringBuilder()
                    while (!source.exhausted()) {
                        val line = source.readUtf8Line() ?: continue
                        if (!line.startsWith("data:")) {
                            continue
                        }

                        val rawJson = line.removePrefix("data:").trim()
                        if (rawJson.isBlank()) {
                            continue
                        }

                        val event = JSONObject(rawJson)
                        val type = event.optString("type")
                        if (type == "done") {
                            activity?.runOnUiThread { finishDeepAnalysis(builder.toString()) }
                            return
                        }
                        if (type == "error") {
                            val message = event.optString("message", "workflow stream failed")
                            activity?.runOnUiThread { finishDeepAnalysisWithError(message) }
                            return
                        }

                        val stage = event.optString("stage")
                        val content = event.optString("content")
                        if (stage.isNotBlank()) {
                            builder.append("\n\n【").append(stage).append("】\n")
                        }
                        if (content.isNotBlank()) {
                            builder.append(content)
                        }

                        val displayText = builder.toString().ifBlank {
                            getString(R.string.workflow_chat_waiting)
                        }
                        activity?.runOnUiThread {
                            updateDeepAnalysisMessage(displayText, pending = true)
                        }
                    }

                    activity?.runOnUiThread { finishDeepAnalysis(builder.toString()) }
                }
            }

            override fun onFailure(call: OkHttpCall, e: IOException) {
                if (call.isCanceled()) {
                    return
                }
                activity?.runOnUiThread {
                    finishDeepAnalysisWithError(e.message ?: "unknown")
                }
            }
        })
    }

    private fun renderDeepAnalysisMessages() {
        binding.deepAnalysisMessagesContainer.removeAllViews()
        deepAnalysisMessages.forEach { binding.deepAnalysisMessagesContainer.addView(createMessageView(it)) }
        binding.buttonSendDeepQuestion.isEnabled = !deepAnalysisPending
        scrollToBottom()
    }

    private fun updateDeepAnalysisMessage(text: String, pending: Boolean) {
        val index = deepAnalysisMessages.indexOfLast { it.role == ROLE_ASSISTANT && it.source == WORKFLOW_SOURCE }
        if (index >= 0) {
            deepAnalysisMessages[index] = deepAnalysisMessages[index].copy(text = text, pending = pending)
        } else {
            deepAnalysisMessages.add(
                QaMessage(
                    role = ROLE_ASSISTANT,
                    text = text,
                    source = WORKFLOW_SOURCE,
                    pending = pending,
                ),
            )
        }
        renderDeepAnalysisMessages()
    }

    private fun finishDeepAnalysis(text: String) {
        deepAnalysisPending = false
        deepAnalysisStreamCall = null
        setLoading(false)
        updateDeepAnalysisMessage(
            text.ifBlank { getString(R.string.workflow_chat_empty_result) },
            pending = false,
        )
    }

    private fun finishDeepAnalysisWithError(message: String) {
        deepAnalysisPending = false
        deepAnalysisStreamCall = null
        setLoading(false)
        updateDeepAnalysisMessage(
            getString(R.string.report_error_latest, message),
            pending = false,
        )
        showToast(getString(R.string.report_error_latest, message))
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
        deepAnalysisStreamCall?.cancel()
        deepAnalysisStreamCall = null
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
        private const val WORKFLOW_SOURCE = "workflow"
        private const val MAX_HISTORY_MESSAGES = 8
    }
}
