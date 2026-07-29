package com.example.myapplication3.ui.home

import android.graphics.Typeface
import android.os.Bundle
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import android.text.method.LinkMovementMethod
import androidx.activity.OnBackPressedCallback
import androidx.core.content.ContextCompat
import androidx.core.view.setPadding
import androidx.fragment.app.Fragment
import com.example.myapplication3.MainActivity
import com.example.myapplication3.R
import com.example.myapplication3.databinding.FragmentHomeBinding
import com.example.myapplication3.network.ApiClient
import com.example.myapplication3.network.ApiErrorParser
import com.example.myapplication3.network.models.TrendingAnalysisResponse
import com.example.myapplication3.ui.MarkdownRenderer
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
import kotlin.math.max
import kotlin.math.roundToInt

class HomeFragment : Fragment() {

    private var _binding: FragmentHomeBinding? = null
    private val binding get() = checkNotNull(_binding)

    private var items: List<TrendingAnalysisResponse.ProjectAnalysis> = emptyList()
    private var selectedRepo: String? = null
    private var currentDetailRepoFullName: String? = null
    private var currentSummaryText: TextView? = null
    private var currentProgressText: TextView? = null
    private var currentAnalyzeButton: Button? = null
    private var detailBackCallback: OnBackPressedCallback? = null

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentHomeBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        ApiClient.initialize(requireContext().applicationContext)
        binding.menuButton.setOnClickListener { openDrawer() }
        binding.loadTrendingButton.setOnClickListener { loadTrendingProjects() }
        binding.swipeRefreshLayout.setOnRefreshListener { loadTrendingProjects() }
        detailBackCallback = object : OnBackPressedCallback(false) {
            override fun handleOnBackPressed() {
                selectedRepo = null
                renderContent()
            }
        }
        requireActivity().onBackPressedDispatcher.addCallback(viewLifecycleOwner, detailBackCallback!!)

        loadTrendingProjects()
    }

    private fun openDrawer() {
        (activity as? MainActivity)?.openDrawer()
    }

    private fun loadTrendingProjects() {
        showLoading(true)
        val apiService = try {
            ApiClient.initialize(requireContext().applicationContext)
            ApiClient.getApiService()
        } catch (t: Throwable) {
            showLoading(false)
            showToast(getString(R.string.common_network_error, t.message ?: "unknown"))
            items = emptyList()
            selectedRepo = null
            renderContent()
            return
        }

        apiService.getTrendingAnalysis().enqueue(object : Callback<TrendingAnalysisResponse> {
            override fun onResponse(
                call: Call<TrendingAnalysisResponse>,
                response: Response<TrendingAnalysisResponse>,
            ) {
                showLoading(false)
                if (response.isSuccessful && response.body() != null) {
                    items = response.body()?.data.orEmpty()
                    if (selectedRepo != null && items.none { it.repoFullName == selectedRepo }) {
                        selectedRepo = null
                    }
                    renderContent()
                } else {
                    showToast(ApiErrorParser.parse(response, getString(R.string.home_empty)))
                    items = emptyList()
                    selectedRepo = null
                    renderContent()
                }
            }

            override fun onFailure(call: Call<TrendingAnalysisResponse>, t: Throwable) {
                showLoading(false)
                showToast(getString(R.string.common_network_error, t.message ?: "unknown"))
                items = emptyList()
                selectedRepo = null
                renderContent()
            }
        })
    }

    private fun renderContent() {
        binding.contentContainer.removeAllViews()

        if (items.isEmpty()) {
            binding.contentContainer.addView(createEmptyText(getString(R.string.home_empty)))
            return
        }

        val current = items.firstOrNull { it.repoFullName == selectedRepo }
        detailBackCallback?.isEnabled = current != null
        if (current != null) {
            binding.swipeRefreshLayout.isEnabled = false
            renderDetail(current)
        } else {
            binding.swipeRefreshLayout.isEnabled = true
            renderList()
        }
    }

    private fun renderList() {
        clearCurrentDetailViews()
        items.forEachIndexed { index, project ->
            binding.contentContainer.addView(createProjectCard(project, index))
        }
    }

    private fun renderDetail(project: TrendingAnalysisResponse.ProjectAnalysis) {
        val repoFullName = project.repoFullName?.trim().orEmpty()

        val card = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            background = ContextCompat.getDrawable(requireContext(), R.drawable.bg_panel)
            elevation = dp(2).toFloat()
            setPadding(dp(12))
            layoutParams = createLayoutParams(top = 10)
        }

        val repoTitle = TextView(requireContext()).apply {
            text = project.repoFullName?.ifBlank { getString(R.string.home_repo_fallback) }
                ?: getString(R.string.home_repo_fallback)
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_text))
            textSize = 17f
            setTypeface(null, Typeface.BOLD)
        }

        val summaryTitle = TextView(requireContext()).apply {
            text = getString(R.string.home_detail_title)
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_muted))
            textSize = 12f
            layoutParams = createLayoutParams(top = 10)
        }

        val summaryText = TextView(requireContext()).apply {
            val state = getDetailAnalysisState(repoFullName)
            text = MarkdownRenderer.toSpanned(state.text.ifBlank { buildProjectDetailFallback(project) })
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_text))
            textSize = 14f
            setLineSpacing(0f, 1.3f)
            linksClickable = true
            isFocusable = false
            isFocusableInTouchMode = false
            movementMethod = LinkMovementMethod.getInstance()
            layoutParams = createLayoutParams(top = 6)
        }

        val progressText = TextView(requireContext()).apply {
            val state = getDetailAnalysisState(repoFullName)
            text = state.progressText
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_muted))
            textSize = 12f
            visibility = if (state.progressText.isBlank()) View.GONE else View.VISIBLE
            layoutParams = createLayoutParams(top = 6)
        }

        val analyzeButton = Button(requireContext()).apply {
            text = getString(R.string.home_detail_action_analyze)
            isEnabled = !getDetailAnalysisState(repoFullName).running
            setOnClickListener { startDetailWorkflowAnalysis(project, summaryText, progressText, this) }
            layoutParams = createLayoutParams(top = 10)
        }

        currentDetailRepoFullName = repoFullName
        currentSummaryText = summaryText
        currentProgressText = progressText
        currentAnalyzeButton = analyzeButton

        card.addView(repoTitle)
        card.addView(summaryTitle)
        card.addView(analyzeButton)
        card.addView(progressText)
        card.addView(summaryText)

        binding.contentContainer.addView(card)
    }

    private fun startDetailWorkflowAnalysis(
        project: TrendingAnalysisResponse.ProjectAnalysis,
        summaryText: TextView,
        progressText: TextView,
        analyzeButton: Button,
    ) {
        val repoFullName = project.repoFullName?.trim().orEmpty()
        val fallback = buildProjectDetailFallback(project)
        if (repoFullName.isBlank()) {
            summaryText.text = MarkdownRenderer.toSpanned(fallback)
            return
        }

        val repoUrl = resolveTrendingRepoUrl(project)
        if (repoUrl.isBlank()) {
            summaryText.text = MarkdownRenderer.toSpanned(fallback)
            return
        }

        val state = getDetailAnalysisState(repoFullName)
        state.call?.cancel()
        state.text = getString(R.string.home_detail_summary_loading)
        state.progressText = getString(R.string.home_detail_analysis_progress_waiting)
        state.running = true
        state.currentStage = ""
        updateDetailText(repoFullName, summaryText, state.text)
        updateDetailProgress(repoFullName, progressText, state.progressText)
        analyzeButton.isEnabled = false

        val workflowInput = "综合分析 $repoUrl"
        val payload = JSONObject().put("user_input", workflowInput).toString()
            .toRequestBody("application/json; charset=utf-8".toMediaType())
        val request = Request.Builder()
            .url(ApiClient.BASE_URL + "api/project/deep-analysis/stream")
            .post(payload)
            .build()

        state.call = ApiClient.getHttpClient().newCall(request)
        state.call?.enqueue(object : OkHttpCallback {
            override fun onResponse(call: OkHttpCall, response: OkHttpResponse) {
                response.use {
                    if (!response.isSuccessful) {
                        val error = response.body?.string().orEmpty().ifBlank { "HTTP ${response.code}" }
                        state.text = fallback
                        state.progressText = getString(R.string.home_detail_analysis_failed)
                        state.running = false
                        state.call = null
                        updateDetailText(repoFullName, summaryText, state.text)
                        updateDetailProgress(repoFullName, progressText, state.progressText)
                        updateAnalyzeButton(repoFullName, analyzeButton, true)
                        showToastOnUiThread(getString(R.string.common_network_error, error))
                        return
                    }

                    val source = response.body?.source()
                    if (source == null) {
                        state.text = fallback
                        state.progressText = getString(R.string.home_detail_analysis_failed)
                        state.running = false
                        state.call = null
                        updateDetailText(repoFullName, summaryText, state.text)
                        updateDetailProgress(repoFullName, progressText, state.progressText)
                        updateAnalyzeButton(repoFullName, analyzeButton, true)
                        return
                    }

                    val builder = StringBuilder()
                    while (!source.exhausted()) {
                        val line = source.readUtf8Line() ?: continue
                        if (!line.startsWith("data:")) continue

                        val rawJson = line.removePrefix("data:").trim()
                        if (rawJson.isBlank()) continue

                        val event = JSONObject(rawJson)
                        when (event.optString("type")) {
                            "done" -> {
                                val finalText = builder.toString().ifBlank { fallback }
                                state.text = finalText
                                state.progressText = getString(R.string.home_detail_analysis_progress, 100)
                                state.running = false
                                state.call = null
                                updateDetailText(repoFullName, summaryText, state.text)
                                updateDetailProgress(repoFullName, progressText, state.progressText)
                                updateAnalyzeButton(repoFullName, analyzeButton, true)
                                return
                            }
                            "error" -> {
                                val message = event.optString("message", getString(R.string.report_error_latest, "workflow stream failed"))
                                state.text = fallback
                                state.progressText = getString(R.string.home_detail_analysis_failed)
                                state.running = false
                                state.call = null
                                updateDetailText(repoFullName, summaryText, state.text)
                                updateDetailProgress(repoFullName, progressText, state.progressText)
                                updateAnalyzeButton(repoFullName, analyzeButton, true)
                                showToastOnUiThread(message)
                                return
                            }
                        }

                        parseWorkflowProgress(event)?.let { progress ->
                            state.progressText = getString(R.string.home_detail_analysis_progress, progress)
                            updateDetailProgress(repoFullName, progressText, state.progressText)
                        }

                        val stage = event.optString("stage")
                        val content = event.optString("content")
                        if (stage.isNotBlank() && stage != state.currentStage) {
                            state.currentStage = stage
                            builder.append("\n\n【").append(stage).append("】\n")
                        }
                        if (content.isNotBlank()) builder.append(content)

                        val displayText = builder.toString().ifBlank { getString(R.string.home_detail_summary_loading) }
                        state.text = displayText
                        updateDetailText(repoFullName, summaryText, state.text)
                    }

                    val finalText = builder.toString().ifBlank { fallback }
                    state.text = finalText
                    state.progressText = getString(R.string.home_detail_analysis_progress, 100)
                    state.running = false
                    state.call = null
                    updateDetailText(repoFullName, summaryText, state.text)
                    updateDetailProgress(repoFullName, progressText, state.progressText)
                    updateAnalyzeButton(repoFullName, analyzeButton, true)
                }
            }

            override fun onFailure(call: OkHttpCall, e: IOException) {
                if (call.isCanceled()) return
                state.text = fallback
                state.progressText = getString(R.string.home_detail_analysis_failed)
                state.running = false
                state.call = null
                updateDetailText(repoFullName, summaryText, state.text)
                updateDetailProgress(repoFullName, progressText, state.progressText)
                updateAnalyzeButton(repoFullName, analyzeButton, true)
                showToastOnUiThread(getString(R.string.common_network_error, e.message ?: "unknown"))
            }
        })
    }

    private fun updateDetailText(repoFullName: String, summaryText: TextView, text: String) {
        activity?.runOnUiThread {
            if (selectedRepo == repoFullName) {
                val currentBinding = _binding ?: return@runOnUiThread
                val scrollY = currentBinding.homeScrollView.scrollY
                val target = if (currentDetailRepoFullName == repoFullName) {
                    currentSummaryText ?: summaryText
                } else {
                    summaryText
                }
                target.text = MarkdownRenderer.toSpanned(text)
                currentBinding.homeScrollView.post {
                    currentBinding.homeScrollView.scrollTo(0, scrollY)
                }
            }
        }
    }

    private fun updateDetailProgress(repoFullName: String, progressText: TextView, text: String) {
        activity?.runOnUiThread {
            if (selectedRepo == repoFullName) {
                val currentBinding = _binding ?: return@runOnUiThread
                val scrollY = currentBinding.homeScrollView.scrollY
                val target = if (currentDetailRepoFullName == repoFullName) {
                    currentProgressText ?: progressText
                } else {
                    progressText
                }
                target.visibility = View.VISIBLE
                target.text = text
                currentBinding.homeScrollView.post {
                    currentBinding.homeScrollView.scrollTo(0, scrollY)
                }
            }
        }
    }

    private fun updateAnalyzeButton(repoFullName: String, analyzeButton: Button, enabled: Boolean) {
        activity?.runOnUiThread {
            if (selectedRepo == repoFullName) {
                val target = if (currentDetailRepoFullName == repoFullName) {
                    currentAnalyzeButton ?: analyzeButton
                } else {
                    analyzeButton
                }
                target.isEnabled = enabled
            }
        }
    }

    private fun clearCurrentDetailViews() {
        currentDetailRepoFullName = null
        currentSummaryText = null
        currentProgressText = null
        currentAnalyzeButton = null
    }

    private fun parseWorkflowProgress(event: JSONObject): Int? {
        if (!event.has("progress") || event.isNull("progress")) {
            return null
        }

        val raw = event.opt("progress")
        val number = when (raw) {
            is Number -> raw.toDouble()
            is String -> raw.trim().removeSuffix("%").toDoubleOrNull()
            else -> null
        } ?: return null

        val percent = if (number <= 1.0) number * 100.0 else number
        return percent.roundToInt().coerceIn(0, 100)
    }

    private fun showToastOnUiThread(message: String) {
        activity?.runOnUiThread {
            showToast(message)
        }
    }

    private fun resolveTrendingRepoUrl(project: TrendingAnalysisResponse.ProjectAnalysis): String {
        val link = project.link?.trim().orEmpty()
        if (link.isNotBlank()) return link

        val repoFullName = project.repoFullName?.trim().orEmpty()
        return if (repoFullName.count { it == '/' } == 1) {
            "https://github.com/$repoFullName"
        } else {
            ""
        }
    }

    private fun createProjectCard(project: TrendingAnalysisResponse.ProjectAnalysis, index: Int): View {
        val card = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            background = ContextCompat.getDrawable(requireContext(), R.drawable.bg_panel)
            elevation = dp(2).toFloat()
            setPadding(dp(12))
            layoutParams = createLayoutParams(bottom = 10)
            isClickable = true
            isFocusable = true
            setOnClickListener {
                selectedRepo = project.repoFullName
                renderContent()
            }
        }

        val title = TextView(requireContext()).apply {
            text = project.repoFullName?.ifBlank { getString(R.string.home_repo_fallback) }
                ?: getString(R.string.home_repo_fallback)
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_brand_dark))
            textSize = 16f
            setTypeface(null, Typeface.BOLD)
        }

        val summary = TextView(requireContext()).apply {
            text = buildProjectListSummary(project)
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_text))
            textSize = 13f
            setLineSpacing(0f, 1.2f)
            layoutParams = createLayoutParams(top = 6)
        }

        val stars = TextView(requireContext()).apply {
            text = getString(R.string.home_stars, project.starsTotal)
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_muted))
            textSize = 12f
            layoutParams = createLayoutParams(top = 8)
        }

        val trend = createTrendBars(project.trend7d.orEmpty(), index)

        card.addView(title)
        card.addView(summary)
        card.addView(stars)
        card.addView(trend)
        return card
    }

    private fun createTrendBars(trend: List<Int>, index: Int): View {
        return TrendChartView(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(48),
            ).apply {
                topMargin = dp(12)
            }
            val colors = listOf(
                R.color.ns_success,
                R.color.ns_brand,
                R.color.ns_danger,
                R.color.purple_500,
            )
            setData(trend, colors[index % colors.size])
        }
    }

    private fun createEmptyText(text: String): View {
        return TextView(requireContext()).apply {
            this.text = text
            textSize = 14f
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_muted))
            gravity = Gravity.CENTER
            setPadding(dp(24))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }
    }

    private fun buildProjectListSummary(project: TrendingAnalysisResponse.ProjectAnalysis): String {
        val summary = project.projectSummary?.trim().orEmpty()
        if (summary.isNotEmpty()) {
            return summary
        }

        val description = project.description?.trim().orEmpty()
        if (description.isNotEmpty()) {
            return description
        }

        val repo = project.repoFullName?.ifBlank { getString(R.string.home_repo_fallback) }
            ?: getString(R.string.home_repo_fallback)
        return getString(R.string.home_summary_fallback, repo, project.starsTotal)
    }

    private fun buildProjectDetailFallback(project: TrendingAnalysisResponse.ProjectAnalysis): String {
        val repo = project.repoFullName?.ifBlank { getString(R.string.home_repo_fallback) }
            ?: getString(R.string.home_repo_fallback)
        val language = project.language?.trim().orEmpty()
        val description = project.description?.trim().orEmpty()
        val trend = project.trend7d.orEmpty()
        val start = trend.firstOrNull() ?: project.starsTotal
        val end = trend.lastOrNull() ?: project.starsTotal
        val delta = end - start

        val paragraphOne = buildString {
            append(repo)
            if (language.isNotEmpty()) {
                append(" 是一个以 ")
                append(language)
                append(" 为主的开源项目。")
            } else {
                append(" 是一个近期值得关注的开源项目。")
            }
            if (description.isNotEmpty()) {
                append(description)
            } else {
                append("当前公开描述有限，但从热点榜单表现看，项目仍处于持续被关注状态。")
            }
        }

        val paragraphTwo = buildString {
            append("近 7 日星标从 ")
            append(start)
            append(" 变化到 ")
            append(end)
            append("，净变化 ")
            append(if (delta >= 0) "+$delta" else delta.toString())
            append("。")
            append("详情阅读时更适合继续观察它的版本迭代节奏、核心场景是否稳定，以及后续是否出现新的集成或生态信号。")
        }

        return "$paragraphOne\n\n$paragraphTwo"
    }

    private fun showLoading(loading: Boolean) {
        binding.progressBar.visibility = if (loading) View.VISIBLE else View.GONE
        binding.swipeRefreshLayout.isRefreshing = false
    }

    private fun showToast(message: String) {
        Toast.makeText(requireContext(), message, Toast.LENGTH_SHORT).show()
    }

    private fun createLayoutParams(
        top: Int = 0,
        bottom: Int = 0,
    ): LinearLayout.LayoutParams {
        return LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply {
            topMargin = dp(top)
            bottomMargin = dp(bottom)
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()

    override fun onDestroyView() {
        super.onDestroyView()
        clearCurrentDetailViews()
        _binding = null
    }

    private data class DetailAnalysisState(
        var text: String = "",
        var progressText: String = "",
        var running: Boolean = false,
        var call: OkHttpCall? = null,
        var currentStage: String = "",
    )

    companion object {
        private val detailAnalysisStates = mutableMapOf<String, DetailAnalysisState>()

        private fun getDetailAnalysisState(repoFullName: String): DetailAnalysisState {
            return detailAnalysisStates.getOrPut(repoFullName) { DetailAnalysisState() }
        }
    }
}
