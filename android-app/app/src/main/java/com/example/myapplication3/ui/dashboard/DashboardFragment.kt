package com.example.myapplication3.ui.dashboard

import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.ConsoleMessage
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.example.myapplication3.MainActivity
import com.example.myapplication3.R
import com.example.myapplication3.auth.SessionStore
import com.example.myapplication3.databinding.FragmentDashboardBinding
import com.example.myapplication3.network.ApiClient
import java.util.Locale

class DashboardFragment : Fragment() {

    private var _binding: FragmentDashboardBinding? = null
    private val binding get() = checkNotNull(_binding)

    private val workspaceUrl: String
        get() = ApiClient.getShowcaseAtlasUrl()

    private var mainFrameError = false

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentDashboardBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        ApiClient.initialize(requireContext().applicationContext)
        SessionStore.initialize(requireContext().applicationContext)

        binding.menuButton.setOnClickListener { openDrawer() }
        binding.buttonRefreshWorkspace.setOnClickListener { refreshWorkspace() }
        binding.buttonOpenExternal.setOnClickListener { openInBrowser() }
        binding.buttonRetryWorkspace.setOnClickListener { loadWorkspace(forceReload = true) }
        binding.workspaceUrlHint.text = getString(R.string.dashboard_workspace_url, workspaceUrl)

        configureWebView()

        val restoredState = savedInstanceState?.getBundle(KEY_WEB_VIEW_STATE)
        if (restoredState != null) {
            binding.workspaceWebView.restoreState(restoredState)
            showLoading(false)
            setStatus(getString(R.string.dashboard_status_restored))
        } else {
            loadWorkspace(forceReload = true)
        }
    }

    override fun onResume() {
        super.onResume()
        binding.workspaceWebView.onResume()
    }

    override fun onPause() {
        binding.workspaceWebView.onPause()
        super.onPause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        val webViewState = Bundle()
        binding.workspaceWebView.saveState(webViewState)
        outState.putBundle(KEY_WEB_VIEW_STATE, webViewState)
    }

    override fun onDestroyView() {
        binding.workspaceWebView.apply {
            stopLoading()
            loadUrl(ABOUT_BLANK)
            destroy()
        }
        _binding = null
        super.onDestroyView()
    }

    private fun openDrawer() {
        (activity as? MainActivity)?.openDrawer()
    }

    private fun configureWebView() {
        binding.workspaceWebView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            javaScriptCanOpenWindowsAutomatically = true
            loadsImagesAutomatically = true
            useWideViewPort = true
            loadWithOverviewMode = true
            cacheMode = WebSettings.LOAD_DEFAULT
            builtInZoomControls = false
            displayZoomControls = false
            setSupportMultipleWindows(false)
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                safeBrowsingEnabled = true
            }
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(binding.workspaceWebView, true)
        }
        applyCompatibilityProfile()

        binding.workspaceWebView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                if (newProgress in 1..99) {
                    showLoading(true)
                    setStatus(getString(R.string.dashboard_status_loading_progress, newProgress))
                } else if (newProgress >= 100 && !mainFrameError) {
                    showLoading(false)
                }
            }

            override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                return super.onConsoleMessage(consoleMessage)
            }
        }

        binding.workspaceWebView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                mainFrameError = false
                hideError()
                showLoading(true)
                setStatus(getString(R.string.dashboard_status_loading))
                super.onPageStarted(view, url, favicon)
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                if (!mainFrameError) {
                    showLoading(false)
                    setStatus(getString(R.string.dashboard_status_ready))
                }
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?,
            ) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame != true) return

                val description = error?.description?.toString()?.trim().orEmpty()
                showLoadFailure(
                    if (description.isNotEmpty()) {
                        getString(R.string.dashboard_error_with_detail, description)
                    } else {
                        getString(R.string.dashboard_error_body)
                    },
                )
            }

            override fun onReceivedHttpError(
                view: WebView?,
                request: WebResourceRequest?,
                errorResponse: WebResourceResponse?,
            ) {
                super.onReceivedHttpError(view, request, errorResponse)
                if (request?.isForMainFrame != true) return

                val detail = getString(
                    R.string.dashboard_error_http,
                    errorResponse?.statusCode ?: 0,
                )
                showLoadFailure(detail)
            }

            override fun onRenderProcessGone(
                view: WebView?,
                detail: RenderProcessGoneDetail?,
            ): Boolean {
                showLoadFailure(getString(R.string.dashboard_error_renderer_gone))
                return true
            }
        }
    }

    private fun loadWorkspace(forceReload: Boolean) {
        hideError()
        mainFrameError = false
        showLoading(true)
        setStatus(getString(R.string.dashboard_status_loading))
        ApiClient.warmUpBackend()

        val token = sessionAccessToken()
        clearWorkspaceCookieIfNeeded(token)
        if (forceReload) {
            val requestHeaders = buildWorkspaceRequestHeaders(token)
            if (requestHeaders.isEmpty()) {
                binding.workspaceWebView.loadUrl(workspaceUrl)
            } else {
                binding.workspaceWebView.loadUrl(workspaceUrl, requestHeaders)
            }
        } else {
            binding.workspaceWebView.reload()
        }
    }

    private fun refreshWorkspace() {
        if (binding.workspaceWebView.url.isNullOrBlank()) {
            loadWorkspace(forceReload = true)
        } else {
            hideError()
            mainFrameError = false
            showLoading(true)
            setStatus(getString(R.string.dashboard_status_refreshing))
            binding.workspaceWebView.reload()
        }
    }

    private fun openInBrowser() {
        val token = sessionAccessToken()
        val targetUri = if (token.isNullOrBlank()) {
            Uri.parse(workspaceUrl)
        } else {
            Uri.parse(workspaceUrl)
                .buildUpon()
                .appendQueryParameter("access_token", token)
                .build()
        }
        val intent = Intent(Intent.ACTION_VIEW, targetUri)
        try {
            startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(requireContext(), R.string.dashboard_browser_unavailable, Toast.LENGTH_SHORT).show()
        }
    }

    private fun applyCompatibilityProfile() {
        if (!isVivoCompatibilityDevice()) {
            return
        }
        binding.workspaceWebView.setLayerType(View.LAYER_TYPE_SOFTWARE, null)
        binding.workspaceNote.text = getString(R.string.dashboard_workspace_note_vivo)
    }

    private fun showLoadFailure(message: String) {
        mainFrameError = true
        showLoading(false)
        binding.workspaceWebView.visibility = View.INVISIBLE
        binding.errorState.visibility = View.VISIBLE
        binding.errorMessage.text = message
        setStatus(getString(R.string.dashboard_status_error))
    }

    private fun hideError() {
        binding.errorState.visibility = View.GONE
        binding.workspaceWebView.visibility = View.VISIBLE
    }

    private fun showLoading(loading: Boolean) {
        binding.workspaceProgress.visibility = if (loading) View.VISIBLE else View.GONE
    }

    private fun setStatus(text: String) {
        binding.workspaceStatus.text = text
    }

    private fun sessionAccessToken(): String? {
        val safeContext = context ?: return null
        return SessionStore.getAccessToken(safeContext)?.trim()?.takeIf { it.isNotEmpty() }
    }

    private fun buildWorkspaceRequestHeaders(token: String?): Map<String, String> {
        if (token.isNullOrBlank()) {
            return emptyMap()
        }
        return mapOf("Authorization" to "Bearer $token")
    }

    private fun clearWorkspaceCookieIfNeeded(token: String?) {
        if (!token.isNullOrBlank()) {
            return
        }
        val cookieManager = CookieManager.getInstance()
        cookieManager.setAcceptCookie(true)
        cookieManager.setCookie(
            ApiClient.BASE_URL,
            "nightshift_access_token=; Max-Age=0; Path=/; SameSite=Lax",
        )
        cookieManager.flush()
    }

    private fun isVivoCompatibilityDevice(): Boolean {
        return Build.VERSION.SDK_INT <= Build.VERSION_CODES.R &&
            Build.MANUFACTURER.trim().lowercase(Locale.US) == "vivo"
    }

    companion object {
        private const val KEY_WEB_VIEW_STATE = "dashboard_web_view_state"
        private const val ABOUT_BLANK = "about:blank"
    }
}
