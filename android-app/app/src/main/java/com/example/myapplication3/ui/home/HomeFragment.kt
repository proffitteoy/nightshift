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
import androidx.core.content.ContextCompat
import androidx.core.view.setPadding
import androidx.fragment.app.Fragment
import com.example.myapplication3.MainActivity
import com.example.myapplication3.R
import com.example.myapplication3.databinding.FragmentHomeBinding
import com.example.myapplication3.network.ApiClient
import com.example.myapplication3.network.ApiErrorParser
import com.example.myapplication3.network.models.TrendingAnalysisResponse
import com.example.myapplication3.network.models.TrendingDetailSummaryRequest
import com.example.myapplication3.network.models.TrendingDetailSummaryResponse
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import kotlin.math.max
import kotlin.math.roundToInt

class HomeFragment : Fragment() {

    private var _binding: FragmentHomeBinding? = null
    private val binding get() = checkNotNull(_binding)

    private var items: List<TrendingAnalysisResponse.ProjectAnalysis> = emptyList()
    private var selectedRepo: String? = null
    private val detailSummaryCache = mutableMapOf<String, String>()
    private val detailSummaryLoadingRepos = mutableSetOf<String>()

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
            detailSummaryCache.clear()
            detailSummaryLoadingRepos.clear()
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
                    detailSummaryCache.clear()
                    detailSummaryLoadingRepos.clear()
                    if (selectedRepo != null && items.none { it.repoFullName == selectedRepo }) {
                        selectedRepo = null
                    }
                    renderContent()
                } else {
                    showToast(ApiErrorParser.parse(response, getString(R.string.home_empty)))
                    items = emptyList()
                    selectedRepo = null
                    detailSummaryCache.clear()
                    detailSummaryLoadingRepos.clear()
                    renderContent()
                }
            }

            override fun onFailure(call: Call<TrendingAnalysisResponse>, t: Throwable) {
                showLoading(false)
                showToast(getString(R.string.common_network_error, t.message ?: "unknown"))
                items = emptyList()
                selectedRepo = null
                detailSummaryCache.clear()
                detailSummaryLoadingRepos.clear()
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
        if (current != null) {
            renderDetail(current)
        } else {
            renderList()
        }
    }

    private fun renderList() {
        items.forEachIndexed { index, project ->
            binding.contentContainer.addView(createProjectCard(project, index))
        }
    }

    private fun renderDetail(project: TrendingAnalysisResponse.ProjectAnalysis) {
        val repoFullName = project.repoFullName?.trim().orEmpty()

        val backButton = Button(requireContext()).apply {
            text = getString(R.string.home_back)
            setOnClickListener {
                selectedRepo = null
                renderContent()
            }
        }

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
            text = detailSummaryCache[repoFullName] ?: buildProjectDetailFallback(project)
            setTextColor(ContextCompat.getColor(requireContext(), R.color.ns_text))
            textSize = 14f
            setLineSpacing(0f, 1.3f)
            layoutParams = createLayoutParams(top = 6)
        }

        card.addView(repoTitle)
        card.addView(summaryTitle)
        card.addView(summaryText)

        binding.contentContainer.addView(backButton)
        binding.contentContainer.addView(card)

        loadDetailSummary(project, summaryText)
    }

    private fun loadDetailSummary(project: TrendingAnalysisResponse.ProjectAnalysis, summaryText: TextView) {
        val repoFullName = project.repoFullName?.trim().orEmpty()
        val fallback = buildProjectDetailFallback(project)
        if (repoFullName.isBlank()) {
            summaryText.text = fallback
            return
        }

        detailSummaryCache[repoFullName]?.let {
            summaryText.text = it
            return
        }

        if (detailSummaryLoadingRepos.contains(repoFullName)) {
            return
        }

        detailSummaryLoadingRepos.add(repoFullName)

        val request = TrendingDetailSummaryRequest(
            repoFullName,
            project.description.orEmpty(),
            project.projectSummary.orEmpty(),
            project.language.orEmpty(),
            project.starsTotal,
            project.trend7d.orEmpty(),
            project.link.orEmpty(),
        )

        ApiClient.getApiService().getTrendingDetailSummary(request)
            .enqueue(object : Callback<TrendingDetailSummaryResponse> {
                override fun onResponse(
                    call: Call<TrendingDetailSummaryResponse>,
                response: Response<TrendingDetailSummaryResponse>,
            ) {
                detailSummaryLoadingRepos.remove(repoFullName)
                val body = response.body()
                val detailText = if (response.isSuccessful && body != null) {
                    body.summary?.trim().orEmpty().ifBlank { fallback }
                } else {
                    fallback
                }
                val source = body?.source?.trim().orEmpty()
                if (response.isSuccessful && source.equals("llm", ignoreCase = true) && detailText.isNotBlank()) {
                    detailSummaryCache[repoFullName] = detailText
                } else {
                    detailSummaryCache.remove(repoFullName)
                }
                if (selectedRepo == repoFullName) {
                    summaryText.text = detailText
                }
            }

            override fun onFailure(call: Call<TrendingDetailSummaryResponse>, t: Throwable) {
                detailSummaryLoadingRepos.remove(repoFullName)
                detailSummaryCache.remove(repoFullName)
                if (selectedRepo == repoFullName) {
                    summaryText.text = fallback
                }
            }
        })
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
        _binding = null
    }
}
