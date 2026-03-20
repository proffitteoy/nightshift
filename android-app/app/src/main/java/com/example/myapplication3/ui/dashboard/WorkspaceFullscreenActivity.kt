package com.example.myapplication3.ui.dashboard

import android.os.Bundle
import android.view.View
import android.webkit.WebSettings
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import com.example.myapplication3.databinding.ActivityWorkspaceFullscreenBinding

class WorkspaceFullscreenActivity : AppCompatActivity() {

    private lateinit var binding: ActivityWorkspaceFullscreenBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityWorkspaceFullscreenBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val url = intent.getStringExtra(EXTRA_URL) ?: "about:blank"
        val webViewState = intent.getBundleExtra(EXTRA_WEBVIEW_STATE)

        binding.buttonClose.setOnClickListener { finish() }

        configureWebView()

        if (webViewState != null) {
            binding.fullscreenWebView.restoreState(webViewState)
        } else {
            binding.fullscreenWebView.loadUrl(url)
        }
    }

    private fun configureWebView() {
        binding.fullscreenWebView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            builtInZoomControls = true
            displayZoomControls = false
            useWideViewPort = true
            loadWithOverviewMode = true
            cacheMode = WebSettings.LOAD_DEFAULT
        }

        binding.fullscreenWebView.webViewClient = WebViewClient()
    }

    override fun onDestroy() {
        binding.fullscreenWebView.apply {
            stopLoading()
            loadUrl("about:blank")
            destroy()
        }
        super.onDestroy()
    }

    companion object {
        const val EXTRA_URL = "extra_workspace_url"
        const val EXTRA_WEBVIEW_STATE = "extra_webview_state"
    }

}
