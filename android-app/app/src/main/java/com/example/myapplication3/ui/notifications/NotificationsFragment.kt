package com.example.myapplication3.ui.notifications

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Patterns
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.TimePicker
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.example.myapplication3.MainActivity
import com.example.myapplication3.R
import com.example.myapplication3.auth.SessionStore
import com.example.myapplication3.databinding.FragmentNotificationsBinding
import com.example.myapplication3.network.ApiClient
import com.example.myapplication3.network.ApiErrorParser
import com.example.myapplication3.network.models.AuthChangePasswordRequest
import com.example.myapplication3.network.models.AuthLoginRequest
import com.example.myapplication3.network.models.AuthRegisterRequest
import com.example.myapplication3.network.models.AuthTokenResponse
import com.example.myapplication3.network.models.GitHubOAuthPollResponse
import com.example.myapplication3.network.models.GitHubOAuthStartResponse
import com.example.myapplication3.network.models.RepoSyncSummary
import com.example.myapplication3.network.models.RuntimeConfigResponse
import com.example.myapplication3.network.models.SubscriptionResponse
import com.example.myapplication3.network.models.UserProfileResponse
import com.example.myapplication3.notifications.NotificationScheduler
import com.example.myapplication3.ui.CurrentRepoStore
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import okhttp3.ResponseBody
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

class NotificationsFragment : Fragment() {

    private enum class AuthMode {
        LOGIN,
        REGISTER,
    }

    private companion object {
        const val DELIVERY_MODE_INSTANT = "instant"
        const val DELIVERY_MODE_SCHEDULED = "scheduled"
        const val DEFAULT_TIMEOUT_SECONDS = "25"
        const val DEFAULT_MAX_RETRIES = "1"
        val TIMESTAMP_FORMATTER: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss", Locale.US)
    }

    private var _binding: FragmentNotificationsBinding? = null
    private val binding get() = checkNotNull(_binding)
    private val bindingOrNull get() = _binding

    private var authMode = AuthMode.LOGIN
    private var loadingCount = 0
    private var subscriptions: List<SubscriptionResponse> = emptyList()
    private var currentRepoUrl: String? = null
    private var currentUser: UserProfileResponse? = null
    private var githubOauthPollToken: String? = null
    private var githubOauthFlowMode: String? = null
    private var githubOauthExpiresAtMs: Long = 0L
    private var githubOauthPollInFlight = false
    private val pendingReminderRequests = mutableListOf<LocalReminderRequest>()
    private val githubOauthHandler = Handler(Looper.getMainLooper())
    private val githubOauthPollRunnable = Runnable { pollGitHubOAuth() }
    private var applicationContext: Context? = null

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            val requests = pendingReminderRequests.toList()
            pendingReminderRequests.clear()
            if (!granted) {
                if (requests.isNotEmpty() && isAdded) {
                    showToast(getString(R.string.subscriptions_notification_permission_needed))
                }
                return@registerForActivityResult
            }
            val failed = requests.any { !applyLocalReminder(it, notifyOnFailure = false) }
            if (failed && isAdded) {
                showToast(getString(R.string.subscriptions_notification_setup_failed))
            }
        }

    private data class LocalReminderRequest(
        val subscriptionId: Int,
        val deliveryTime: String,
    )

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentNotificationsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onAttach(context: Context) {
        super.onAttach(context)
        applicationContext = context.applicationContext
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val safeAppContext = appContextOrNull() ?: return
        ApiClient.initialize(safeAppContext)
        SessionStore.initialize(safeAppContext)

        binding.menuButton.setOnClickListener { openDrawer() }
        binding.buttonRefreshSubscriptions.setOnClickListener { loadProtectedContent() }
        binding.buttonSaveRuntime.setOnClickListener { saveRuntimeConfig() }
        binding.buttonClearRuntime.setOnClickListener { confirmClearRuntimeConfig() }
        binding.buttonCreateSubscription.setOnClickListener { createSubscription() }
        binding.buttonAuthModeLogin.setOnClickListener { switchAuthMode(AuthMode.LOGIN) }
        binding.buttonAuthModeRegister.setOnClickListener { switchAuthMode(AuthMode.REGISTER) }
        binding.buttonAuthSubmit.setOnClickListener { submitAuth() }
        binding.buttonGithubOauth.setOnClickListener { startGitHubOAuth() }
        binding.buttonLogout.setOnClickListener { confirmLogout() }
        binding.buttonChangePassword.setOnClickListener { promptPasswordChange() }
        binding.buttonRegisterNewAccount.setOnClickListener { startRegisterNewAccount() }

        binding.createMorningCheckbox.isChecked = true
        binding.createPanoramaCheckbox.isChecked = true
        applyRuntimeDefaults()
        switchAuthMode(AuthMode.LOGIN)
        restoreSessionState()
    }

    override fun onResume() {
        super.onResume()
        if (!isAdded || _binding == null) {
            return
        }
        if (hasActiveSession()) {
            val safeAppContext = appContextOrNull() ?: return
            currentUser = SessionStore.getCachedUser(safeAppContext) ?: currentUser
            if (currentUser != null) {
                bindCurrentUser(currentUser)
                renderAuthenticatedState()
            } else {
                restoreSessionState()
            }
        } else if (currentUser != null || subscriptions.isNotEmpty()) {
            renderLoggedOutState()
        }
        if (githubOauthPollToken != null) {
            scheduleGitHubPoll(delayMs = 600L)
        }
    }

    override fun onPause() {
        super.onPause()
        githubOauthHandler.removeCallbacks(githubOauthPollRunnable)
    }

    override fun onDetach() {
        super.onDetach()
        applicationContext = null
    }

    private fun openDrawer() {
        (activity as? MainActivity)?.openDrawer()
    }

    private fun restoreSessionState() {
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }

        val safeAppContext = appContextOrNull() ?: run {
            renderLoggedOutState()
            return
        }
        currentUser = SessionStore.getCachedUser(safeAppContext)
        bindCurrentUser(currentUser)
        renderAuthenticatedState(
            statusMessage = if (currentUser == null) getString(R.string.auth_validating_session) else null,
        )
        loadProtectedContent()
        refreshCurrentUser(showStatusOnFailure = currentUser == null)
    }

    private fun switchAuthMode(mode: AuthMode) {
        val binding = bindingOrNull ?: return
        authMode = mode
        val showDisplayName = mode == AuthMode.REGISTER && !hasActiveSession()
        binding.authDisplayNameContainer.visibility = if (showDisplayName) View.VISIBLE else View.GONE
        binding.buttonAuthSubmit.text = getString(
            if (mode == AuthMode.LOGIN) R.string.auth_action_login else R.string.auth_action_register,
        )

        if (!hasActiveSession()) {
            showAuthStatus(defaultAuthHint(), isError = false)
        }
        setLoading(false)
    }

    private fun submitAuth() {
        val binding = bindingOrNull ?: return
        if (hasActiveSession()) {
            return
        }

        val email = binding.authEmailInput.text?.toString()?.trim().orEmpty()
        if (!Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
            showAuthStatus(getString(R.string.auth_error_email), isError = true)
            return
        }

        val password = binding.authPasswordInput.text?.toString()?.trim().orEmpty()
        if (password.length < 8) {
            showAuthStatus(getString(R.string.auth_error_password), isError = true)
            return
        }

        showAuthStatus(
            getString(if (authMode == AuthMode.LOGIN) R.string.auth_logging_in else R.string.auth_registering),
            isError = false,
        )
        setLoading(true)

        val requestCall = if (authMode == AuthMode.LOGIN) {
            ApiClient.getApiService().login(AuthLoginRequest(email, password))
        } else {
            val displayName = binding.authDisplayNameInput.text?.toString()?.trim().orEmpty()
            ApiClient.getApiService().register(AuthRegisterRequest(email, password, displayName))
        }

        requestCall.enqueue(object : Callback<AuthTokenResponse> {
            override fun onResponse(
                call: Call<AuthTokenResponse>,
                response: Response<AuthTokenResponse>,
            ) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                if (response.isSuccessful && response.body() != null) {
                    handleAuthSuccess(response.body()!!)
                } else {
                    showAuthStatus(
                        ApiErrorParser.parse(
                            response,
                            getString(
                                if (authMode == AuthMode.LOGIN) {
                                    R.string.auth_error_login
                                } else {
                                    R.string.auth_error_register
                                },
                                "request failed",
                            ),
                        ),
                        isError = true,
                    )
                }
            }

            override fun onFailure(call: Call<AuthTokenResponse>, t: Throwable) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                showAuthStatus(
                    getString(
                        if (authMode == AuthMode.LOGIN) R.string.auth_error_login else R.string.auth_error_register,
                        t.message ?: "unknown",
                    ),
                    isError = true,
                )
            }
        })
    }

    private fun handleAuthSuccess(
        session: AuthTokenResponse,
        successToastMessage: String? = null,
    ) {
        val safeAppContext = appContextOrNull() ?: return
        clearGitHubOauthState()
        SessionStore.saveSession(safeAppContext, session)
        currentUser = session.user
        bindCurrentUser(currentUser)
        clearAuthInputs()
        renderAuthenticatedState(session.repoSync?.message)
        resetCreateForm()
        loadProtectedContent()
        if (currentUser == null) {
            refreshCurrentUser(showStatusOnFailure = true)
        }
        showToast(
            successToastMessage?.trim().orEmpty().ifEmpty {
                getString(if (authMode == AuthMode.LOGIN) R.string.auth_login_success else R.string.auth_register_success)
            },
        )
    }

    private fun refreshCurrentUser(showStatusOnFailure: Boolean) {
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }

        ApiClient.getApiService().getMe().enqueue(object : Callback<UserProfileResponse> {
            override fun onResponse(
                call: Call<UserProfileResponse>,
                response: Response<UserProfileResponse>,
            ) {
                if (!isAdded) {
                    return
                }
                if (response.code() == 401) {
                    handleUnauthorized()
                    return
                }
                if (response.isSuccessful && response.body() != null) {
                    if (!hasActiveSession()) {
                        return
                    }
                    currentUser = response.body()
                    appContextOrNull()?.let { SessionStore.saveUser(it, currentUser) }
                    bindCurrentUser(currentUser)
                    renderAuthenticatedState()
                } else if (showStatusOnFailure) {
                    showAuthStatus(
                        ApiErrorParser.parse(response, getString(R.string.auth_error_load_me, "request failed")),
                        isError = true,
                    )
                }
            }

            override fun onFailure(call: Call<UserProfileResponse>, t: Throwable) {
                if (!isAdded || !showStatusOnFailure) {
                    return
                }
                showAuthStatus(getString(R.string.auth_error_load_me, t.message ?: "unknown"), isError = true)
            }
        })
    }

    private fun confirmLogout() {
        val safeContext = context ?: return
        MaterialAlertDialogBuilder(safeContext, R.style.AlertDialogTheme)
            .setMessage(getString(R.string.auth_logout_confirm))
            .setPositiveButton(android.R.string.ok) { _, _ -> performLogout() }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun performLogout() {
        clearSessionState(
            statusMessage = defaultAuthHint(),
            statusIsError = false,
            clearPersistedSession = true,
            clearCurrentRepoSelection = true,
        )
        showToast(getString(R.string.auth_logout_success))
    }

    private fun startRegisterNewAccount() {
        clearSessionState(
            statusMessage = getString(R.string.auth_register_hint),
            statusIsError = false,
            clearPersistedSession = true,
            clearCurrentRepoSelection = true,
        )
        switchAuthMode(AuthMode.REGISTER)
        showToast(getString(R.string.auth_logout_to_register_success))
    }

    private fun promptPasswordChange() {
        val safeContext = context ?: return
        if (!currentUser.usesPasswordAuth()) {
            showToast(getString(R.string.auth_change_password_not_supported))
            return
        }

        val dialogView = layoutInflater.inflate(R.layout.dialog_change_password, null)
        val currentInput = dialogView.findViewById<EditText>(R.id.current_password_input)
        val newInput = dialogView.findViewById<EditText>(R.id.new_password_input)
        val confirmInput = dialogView.findViewById<EditText>(R.id.confirm_password_input)

        MaterialAlertDialogBuilder(safeContext, R.style.AlertDialogTheme)
            .setTitle(R.string.auth_change_password_title)
            .setView(dialogView)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                submitPasswordChange(
                    currentPassword = currentInput.text?.toString()?.trim().orEmpty(),
                    newPassword = newInput.text?.toString()?.trim().orEmpty(),
                    confirmPassword = confirmInput.text?.toString()?.trim().orEmpty(),
                )
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun submitPasswordChange(
        currentPassword: String,
        newPassword: String,
        confirmPassword: String,
    ) {
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }
        if (currentPassword.length < 8) {
            showToast(getString(R.string.auth_change_password_error_current_required))
            return
        }
        if (newPassword.length < 8) {
            showToast(getString(R.string.auth_change_password_error_new_required))
            return
        }
        if (newPassword != confirmPassword) {
            showToast(getString(R.string.auth_change_password_error_confirm))
            return
        }

        setLoading(true)
        ApiClient.getApiService()
            .changePassword(AuthChangePasswordRequest(currentPassword, newPassword))
            .enqueue(object : Callback<Map<String, Any>> {
                override fun onResponse(
                    call: Call<Map<String, Any>>,
                    response: Response<Map<String, Any>>,
                ) {
                    setLoading(false)
                    if (!isAdded) {
                        return
                    }
                    if (response.code() == 401) {
                        handleUnauthorized()
                        return
                    }
                    if (!hasActiveSession()) {
                        return
                    }
                    if (response.isSuccessful) {
                        showToast(getString(R.string.auth_change_password_success))
                    } else {
                        showToast(
                            ApiErrorParser.parse(
                                response,
                                getString(R.string.auth_change_password_error_request, "request failed"),
                            ),
                        )
                    }
                }

                override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                    setLoading(false)
                    if (!isAdded || !hasActiveSession()) {
                        return
                    }
                    showToast(getString(R.string.auth_change_password_error_request, t.message ?: "unknown"))
                }
            })
    }

    private fun handleUnauthorized() {
        clearSessionState(
            statusMessage = getString(R.string.auth_session_expired),
            statusIsError = true,
            clearPersistedSession = true,
            clearCurrentRepoSelection = true,
        )
    }

    private fun clearSessionState(
        statusMessage: String,
        statusIsError: Boolean,
        clearPersistedSession: Boolean,
        clearCurrentRepoSelection: Boolean,
    ) {
        if (!isAdded || _binding == null) {
            return
        }

        subscriptions.forEach { cancelLocalReminder(it.id) }
        subscriptions = emptyList()
        currentUser = null
        currentRepoUrl = null
        pendingReminderRequests.clear()

        val safeAppContext = appContextOrNull()
        if (clearPersistedSession && safeAppContext != null) {
            SessionStore.clear(safeAppContext)
            clearShowcaseSessionCookie()
        }
        if (clearCurrentRepoSelection && safeAppContext != null) {
            CurrentRepoStore.clearSelectedRepoUrl(safeAppContext)
        }

        renderSubscriptions(emptyList())
        applyRuntimeDefaults()
        resetCreateForm()
        clearAuthInputs(clearEmail = false)
        clearGitHubOauthState()
        renderLoggedOutState(statusMessage, statusIsError)
    }

    private fun renderLoggedOutState(
        statusMessage: String = defaultAuthHint(),
        statusIsError: Boolean = false,
    ) {
        if (!isAdded || _binding == null) {
            return
        }

        binding.authNoteText.text = getString(R.string.auth_tab4_note)
        binding.authFormContainer.visibility = View.VISIBLE
        binding.authAccountContainer.visibility = View.GONE
        binding.authAccountName.text = ""
        binding.authAccountMeta.text = ""
        renderProtectedSections(authenticated = false)
        renderGitHubOauthButton()
        renderCurrentRepoStatus()
        showAuthStatus(statusMessage, isError = statusIsError)
        setLoading(false)
    }

    private fun renderAuthenticatedState(statusMessage: String? = null) {
        if (!isAdded || _binding == null) {
            return
        }

        binding.authNoteText.text = getString(R.string.auth_tab4_logged_in_note)
        binding.authFormContainer.visibility = View.GONE
        binding.authAccountContainer.visibility = if (currentUser == null) View.GONE else View.VISIBLE
        renderProtectedSections(authenticated = true)
        renderGitHubOauthButton()
        renderCurrentRepoStatus()
        showAuthStatus(statusMessage, isError = false)
        setLoading(false)
    }

    private fun renderProtectedSections(authenticated: Boolean) {
        val binding = bindingOrNull ?: return
        val protectedVisibility = if (authenticated) View.VISIBLE else View.GONE
        binding.buttonRefreshSubscriptions.visibility = protectedVisibility
        binding.authenticatedContent.visibility = protectedVisibility
        binding.subscriptionCreateContainer.visibility = protectedVisibility
        binding.currentRepoStatusText.visibility = protectedVisibility
        binding.subscriptionsListContainer.visibility = protectedVisibility
        binding.subscriptionsEmptyState.visibility = if (authenticated && subscriptions.isEmpty()) {
            View.VISIBLE
        } else {
            View.GONE
        }
    }

    private fun bindCurrentUser(user: UserProfileResponse?) {
        val binding = bindingOrNull ?: return
        if (user == null) {
            binding.authAccountContainer.visibility = View.GONE
            binding.authAccountName.text = ""
            binding.authAccountMeta.text = ""
            return
        }

        val displayName = user.displayName?.trim().orEmpty().ifBlank { user.email?.trim().orEmpty() }
        binding.authAccountName.text = displayName
        binding.authAccountMeta.text = buildAccountMeta(user)
        binding.buttonChangePassword.visibility = if (user.usesPasswordAuth()) View.VISIBLE else View.GONE
        binding.authAccountContainer.visibility = View.VISIBLE
    }

    private fun buildAccountMeta(user: UserProfileResponse): String {
        val authSourceLabel = when (user.authSource?.trim()?.lowercase(Locale.US)) {
            "github" -> getString(R.string.auth_source_github)
            "password" -> getString(R.string.auth_source_password)
            else -> getString(R.string.auth_source_unknown)
        }
        val githubStatus = if (user.isGithubConnected) {
            val githubLogin = user.githubLogin?.trim().orEmpty()
            if (githubLogin.isNotEmpty()) {
                getString(R.string.auth_github_connected_with_login, githubLogin)
            } else {
                getString(R.string.auth_github_connected)
            }
        } else {
            getString(R.string.auth_github_not_connected)
        }
        return getString(
            R.string.auth_account_meta_template,
            user.email?.trim().orEmpty(),
            authSourceLabel,
            githubStatus,
        )
    }

    private fun defaultAuthHint(): String {
        return getString(
            if (authMode == AuthMode.LOGIN) R.string.auth_login_hint else R.string.auth_register_hint,
        )
    }

    private fun showAuthStatus(message: String?, isError: Boolean) {
        val binding = bindingOrNull ?: return
        val safeContext = context ?: return
        val text = message?.trim().orEmpty()
        binding.authStatusText.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
        binding.authStatusText.text = text
        binding.authStatusText.setTextColor(
            ContextCompat.getColor(
                safeContext,
                if (isError) R.color.ns_danger else R.color.ns_muted,
            ),
        )
    }

    private fun clearAuthInputs(clearEmail: Boolean = true) {
        val binding = bindingOrNull ?: return
        if (clearEmail) {
            binding.authEmailInput.setText("")
        }
        binding.authPasswordInput.setText("")
        binding.authDisplayNameInput.setText("")
    }

    private fun startGitHubOAuth() {
        if (githubOauthPollInFlight) {
            showAuthStatus(getString(R.string.auth_github_waiting), isError = false)
            return
        }
        if (githubOauthPollToken != null) {
            clearGitHubOauthState()
        }

        clearGitHubOauthState()
        showAuthStatus(getString(R.string.auth_github_opening), isError = false)
        setLoading(true)
        ApiClient.getApiService().startGitHubOAuth().enqueue(object : Callback<GitHubOAuthStartResponse> {
            override fun onResponse(
                call: Call<GitHubOAuthStartResponse>,
                response: Response<GitHubOAuthStartResponse>,
            ) {
                setLoading(false)
                if (!isAdded || _binding == null) {
                    return
                }
                if (response.isSuccessful && response.body() != null) {
                    val body = response.body()!!
                    val authorizeUrl = body.authorizeUrl?.trim().orEmpty()
                    val pollToken = body.pollToken?.trim().orEmpty()
                    if (authorizeUrl.isEmpty()) {
                        showAuthStatus(getString(R.string.auth_github_failed, "missing authorize_url"), isError = true)
                        return
                    }
                    if (pollToken.isEmpty()) {
                        showAuthStatus(getString(R.string.auth_github_failed, "missing poll_token"), isError = true)
                        return
                    }
                    githubOauthPollToken = pollToken
                    githubOauthFlowMode = body.mode?.trim().orEmpty()
                    githubOauthExpiresAtMs = System.currentTimeMillis() + (body.expiresIn.toLong() * 1000L)
                    renderGitHubOauthButton()
                    if (!openExternalBrowser(authorizeUrl)) {
                        clearGitHubOauthState()
                        showAuthStatus(getString(R.string.auth_github_browser_missing), isError = true)
                        return
                    }
                    showAuthStatus(getString(R.string.auth_github_waiting), isError = false)
                    scheduleGitHubPoll(delayMs = 1500L)
                } else {
                    showAuthStatus(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.auth_github_unavailable, "request failed"),
                        ),
                        isError = true,
                    )
                }
            }

            override fun onFailure(call: Call<GitHubOAuthStartResponse>, t: Throwable) {
                setLoading(false)
                if (!isAdded || _binding == null) {
                    return
                }
                showAuthStatus(getString(R.string.auth_github_failed, t.message ?: "unknown"), isError = true)
            }
        })
    }

    private fun pollGitHubOAuth() {
        val pollToken = githubOauthPollToken?.trim().orEmpty()
        if (pollToken.isEmpty()) {
            return
        }
        if (System.currentTimeMillis() >= githubOauthExpiresAtMs) {
            clearGitHubOauthState()
            showAuthStatus(getString(R.string.auth_github_timeout), isError = true)
            return
        }
        if (githubOauthPollInFlight) {
            return
        }

        githubOauthPollInFlight = true
        renderGitHubOauthButton()
        ApiClient.getApiService().pollGitHubOAuth(pollToken).enqueue(object : Callback<GitHubOAuthPollResponse> {
            override fun onResponse(
                call: Call<GitHubOAuthPollResponse>,
                response: Response<GitHubOAuthPollResponse>,
            ) {
                githubOauthPollInFlight = false
                renderGitHubOauthButton()
                if (!isAdded || _binding == null) {
                    return
                }
                if (!response.isSuccessful || response.body() == null) {
                    if (response.code() == 404) {
                        clearGitHubOauthState()
                        showAuthStatus(
                            ApiErrorParser.parse(
                                response,
                                getString(R.string.auth_github_failed, "authorization session expired"),
                            ),
                            isError = true,
                        )
                        return
                    }
                    showAuthStatus(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.auth_github_failed, "request failed"),
                        ),
                        isError = true,
                    )
                    scheduleGitHubPoll(delayMs = 2000L)
                    return
                }

                when (response.body()!!.status?.trim()?.lowercase(Locale.US)) {
                    "pending" -> {
                        showAuthStatus(getString(R.string.auth_github_polling), isError = false)
                        scheduleGitHubPoll(delayMs = 2000L)
                    }
                    "completed" -> {
                        val completedAuth = response.body()!!.auth
                        val completedMessage = response.body()!!.message?.trim().orEmpty()
                        val flowMode = githubOauthFlowMode?.trim()?.lowercase(Locale.US)
                        if (completedAuth != null) {
                            handleAuthSuccess(
                                completedAuth,
                                successToastMessage = getString(
                                    if (flowMode == "connect") {
                                        R.string.auth_github_connected_success
                                    } else {
                                        R.string.auth_login_success
                                    },
                                ),
                            )
                            if (completedMessage.isNotEmpty()) {
                                showAuthStatus(completedMessage, isError = false)
                            } else if (completedAuth.repoSync?.message?.trim().isNullOrEmpty().not()) {
                                showAuthStatus(completedAuth.repoSync?.message, isError = false)
                            } else if (hasActiveSession() && currentUser?.isGithubConnected == true) {
                                showAuthStatus(getString(R.string.auth_github_connected_success), isError = false)
                            }
                        } else {
                            clearGitHubOauthState()
                            showAuthStatus(getString(R.string.auth_github_failed, "missing auth payload"), isError = true)
                        }
                    }
                    "failed" -> {
                        clearGitHubOauthState()
                        showAuthStatus(
                            response.body()!!.message?.trim().orEmpty().ifEmpty {
                                getString(R.string.auth_github_failed, "unknown")
                            },
                            isError = true,
                        )
                    }
                    else -> {
                        clearGitHubOauthState()
                        showAuthStatus(getString(R.string.auth_github_failed, "unexpected status"), isError = true)
                    }
                }
            }

            override fun onFailure(call: Call<GitHubOAuthPollResponse>, t: Throwable) {
                githubOauthPollInFlight = false
                renderGitHubOauthButton()
                if (!isAdded || _binding == null) {
                    return
                }
                showAuthStatus(getString(R.string.auth_github_failed, t.message ?: "unknown"), isError = true)
                scheduleGitHubPoll(delayMs = 2000L)
            }
        })
    }

    private fun scheduleGitHubPoll(delayMs: Long) {
        if (githubOauthPollToken.isNullOrBlank()) {
            return
        }
        githubOauthHandler.removeCallbacks(githubOauthPollRunnable)
        githubOauthHandler.postDelayed(githubOauthPollRunnable, delayMs)
    }

    private fun clearGitHubOauthState() {
        githubOauthHandler.removeCallbacks(githubOauthPollRunnable)
        githubOauthPollToken = null
        githubOauthFlowMode = null
        githubOauthExpiresAtMs = 0L
        githubOauthPollInFlight = false
        if (isAdded && _binding != null) {
            renderGitHubOauthButton()
        }
    }

    private fun renderGitHubOauthButton() {
        val binding = bindingOrNull ?: return
        binding.buttonGithubOauth.text = when {
            githubOauthPollToken != null -> getString(R.string.auth_github_retry_pending)
            !hasActiveSession() -> getString(R.string.auth_github_login)
            currentUser?.isGithubConnected == true -> getString(R.string.auth_github_refresh)
            else -> getString(R.string.auth_github_connect)
        }
        binding.buttonGithubOauth.isEnabled = loadingCount == 0 && !githubOauthPollInFlight
    }

    private fun openExternalBrowser(url: String): Boolean {
        val safeContext = context ?: return false
        val uri = try {
            Uri.parse(url)
        } catch (_: Throwable) {
            return false
        }
        val normalizedScheme = uri.scheme?.trim()?.lowercase(Locale.US).orEmpty()
        val normalizedHost = uri.host?.trim()?.lowercase(Locale.US).orEmpty()
        val normalizedPath = uri.encodedPath?.trim().orEmpty()
        if (normalizedScheme != "https") {
            return false
        }
        if (normalizedHost != "github.com") {
            return false
        }
        if (!normalizedPath.startsWith("/login/oauth/authorize")) {
            return false
        }

        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addCategory(Intent.CATEGORY_BROWSABLE)
        }
        val packageManager = safeContext.packageManager
        if (intent.resolveActivity(packageManager) == null) {
            return false
        }
        return try {
            startActivity(intent)
            true
        } catch (_: ActivityNotFoundException) {
            false
        } catch (_: SecurityException) {
            false
        } catch (_: Throwable) {
            false
        }
    }

    private fun loadProtectedContent() {
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }
        loadRuntimeConfig()
        loadSubscriptions()
    }

    private fun loadRuntimeConfig() {
        if (!hasActiveSession()) {
            return
        }
        setLoading(true)
        ApiClient.getApiService().getRuntimeConfig().enqueue(object : Callback<RuntimeConfigResponse> {
            override fun onResponse(
                call: Call<RuntimeConfigResponse>,
                response: Response<RuntimeConfigResponse>,
            ) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                if (response.code() == 401) {
                    handleUnauthorized()
                    return
                }
                if (!hasActiveSession()) {
                    return
                }
                if (response.isSuccessful && response.body() != null) {
                    bindRuntimeConfig(response.body())
                } else {
                    showToast(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.subscriptions_error_load_runtime, "request failed"),
                        ),
                    )
                }
            }

            override fun onFailure(call: Call<RuntimeConfigResponse>, t: Throwable) {
                setLoading(false)
                if (!isAdded || !hasActiveSession()) {
                    return
                }
                showToast(getString(R.string.subscriptions_error_load_runtime, t.message ?: "unknown"))
            }
        })
    }

    private fun loadSubscriptions() {
        if (!hasActiveSession()) {
            return
        }
        setLoading(true)
        ApiClient.getApiService().getSubscriptions().enqueue(object : Callback<List<SubscriptionResponse>> {
            override fun onResponse(
                call: Call<List<SubscriptionResponse>>,
                response: Response<List<SubscriptionResponse>>,
            ) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                if (response.code() == 401) {
                    handleUnauthorized()
                    return
                }
                if (!hasActiveSession()) {
                    return
                }
                if (response.isSuccessful) {
                    subscriptions = response.body().orEmpty()
                    currentRepoUrl = resolveCurrentRepoUrl(subscriptions)
                    renderCurrentRepoStatus()
                    renderSubscriptions(subscriptions)
                    syncLocalReminders(subscriptions)
                } else {
                    subscriptions = emptyList()
                    currentRepoUrl = null
                    renderCurrentRepoStatus()
                    renderSubscriptions(emptyList())
                    showToast(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.subscriptions_error_load_list, "request failed"),
                        ),
                    )
                }
            }

            override fun onFailure(call: Call<List<SubscriptionResponse>>, t: Throwable) {
                setLoading(false)
                if (!isAdded || !hasActiveSession()) {
                    return
                }
                subscriptions = emptyList()
                currentRepoUrl = null
                renderCurrentRepoStatus()
                renderSubscriptions(emptyList())
                showToast(getString(R.string.subscriptions_error_load_list, t.message ?: "unknown"))
            }
        })
    }

    private fun bindRuntimeConfig(config: RuntimeConfigResponse?) {
        val binding = bindingOrNull ?: return
        if (config == null) {
            return
        }

        binding.runtimeGithubTokenInput.setText("")
        binding.runtimeLlmKeyInput.setText("")
        binding.runtimeBaseUrlInput.setText(
            config.llmBaseUrl?.ifBlank { getString(R.string.subscriptions_default_base_url) }
                ?: getString(R.string.subscriptions_default_base_url),
        )
        binding.runtimeModelInput.setText(
            config.llmModel?.ifBlank { getString(R.string.subscriptions_default_model) }
                ?: getString(R.string.subscriptions_default_model),
        )
        binding.runtimeTimeoutInput.setText(formatTimeoutSeconds(config.llmTimeoutSeconds))
        binding.runtimeRetriesInput.setText(config.llmMaxRetries.toString())
        binding.runtimeEmailAccessKeyIdInput.setText("")
        binding.runtimeEmailAccessKeySecretInput.setText("")
        binding.runtimeEmailAccountNameInput.setText(config.emailAccountName?.orEmpty())
        binding.runtimeEmailRegionIdInput.setText(config.emailRegionId?.ifBlank { "cn-hangzhou" } ?: "cn-hangzhou")
        binding.runtimeEmailEndpointInput.setText(config.emailEndpoint?.ifBlank { "dm.aliyuncs.com" } ?: "dm.aliyuncs.com")
        binding.runtimeEmailFromAliasInput.setText(config.emailFromAlias?.orEmpty())
        val emailConfigured = config.isEmailAccessKeyIdConfigured && config.isEmailAccessKeySecretConfigured &&
            !config.emailAccountName.isNullOrBlank()
        binding.runtimeStatusText.text = getString(
            R.string.subscriptions_runtime_status,
            if (config.isGithubTokenConfigured) getString(R.string.subscriptions_configured) else getString(R.string.subscriptions_missing),
            if (config.isLlmApiKeyConfigured) getString(R.string.subscriptions_configured) else getString(R.string.subscriptions_missing),
            if (emailConfigured) getString(R.string.subscriptions_email_configured) else getString(R.string.subscriptions_email_missing),
            config.llmModel?.ifBlank { getString(R.string.subscriptions_default_model) }
                ?: getString(R.string.subscriptions_default_model),
            config.llmBaseUrl?.ifBlank { getString(R.string.subscriptions_default_base_url) }
                ?: getString(R.string.subscriptions_default_base_url),
            config.emailAccountName?.ifBlank { getString(R.string.subscriptions_missing) }
                ?: getString(R.string.subscriptions_missing),
        )
    }

    private fun applyRuntimeDefaults() {
        val binding = bindingOrNull ?: return
        binding.runtimeGithubTokenInput.setText("")
        binding.runtimeLlmKeyInput.setText("")
        binding.runtimeBaseUrlInput.setText(getString(R.string.subscriptions_default_base_url))
        binding.runtimeModelInput.setText(getString(R.string.subscriptions_default_model))
        binding.runtimeTimeoutInput.setText(DEFAULT_TIMEOUT_SECONDS)
        binding.runtimeRetriesInput.setText(DEFAULT_MAX_RETRIES)
        binding.runtimeEmailAccessKeyIdInput.setText("")
        binding.runtimeEmailAccessKeySecretInput.setText("")
        binding.runtimeEmailAccountNameInput.setText("")
        binding.runtimeEmailRegionIdInput.setText("cn-hangzhou")
        binding.runtimeEmailEndpointInput.setText("dm.aliyuncs.com")
        binding.runtimeEmailFromAliasInput.setText("")
        binding.runtimeStatusText.text = ""
    }

    private fun saveRuntimeConfig() {
        val binding = bindingOrNull ?: return
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }

        val payload = mutableMapOf<String, Any>(
            "llm_base_url" to binding.runtimeBaseUrlInput.text?.toString()?.trim().orEmpty()
                .ifBlank { getString(R.string.subscriptions_default_base_url) },
            "llm_model" to binding.runtimeModelInput.text?.toString()?.trim().orEmpty()
                .ifBlank { getString(R.string.subscriptions_default_model) },
            "llm_timeout_seconds" to parsePositiveDouble(binding.runtimeTimeoutInput, DEFAULT_TIMEOUT_SECONDS.toDouble()),
            "llm_max_retries" to parseNonNegativeInt(binding.runtimeRetriesInput, DEFAULT_MAX_RETRIES.toInt()),
        )

        val githubToken = binding.runtimeGithubTokenInput.text?.toString()?.trim().orEmpty()
        if (githubToken.isNotEmpty()) {
            payload["github_token"] = githubToken
        }

        val llmApiKey = binding.runtimeLlmKeyInput.text?.toString()?.trim().orEmpty()
        if (llmApiKey.isNotEmpty()) {
            payload["llm_api_key"] = llmApiKey
        }

        val emailAccessKeyId = binding.runtimeEmailAccessKeyIdInput.text?.toString()?.trim().orEmpty()
        if (emailAccessKeyId.isNotEmpty()) {
            payload["email_access_key_id"] = emailAccessKeyId
        }

        val emailAccessKeySecret = binding.runtimeEmailAccessKeySecretInput.text?.toString()?.trim().orEmpty()
        if (emailAccessKeySecret.isNotEmpty()) {
            payload["email_access_key_secret"] = emailAccessKeySecret
        }

        val emailAccountName = binding.runtimeEmailAccountNameInput.text?.toString()?.trim().orEmpty()
        if (emailAccountName.isNotEmpty()) {
            payload["email_account_name"] = emailAccountName
        }

        val emailRegionId = binding.runtimeEmailRegionIdInput.text?.toString()?.trim().orEmpty()
        if (emailRegionId.isNotEmpty()) {
            payload["email_region_id"] = emailRegionId
        }

        val emailEndpoint = binding.runtimeEmailEndpointInput.text?.toString()?.trim().orEmpty()
        if (emailEndpoint.isNotEmpty()) {
            payload["email_endpoint"] = emailEndpoint
        }

        val emailFromAlias = binding.runtimeEmailFromAliasInput.text?.toString()?.trim().orEmpty()
        if (emailFromAlias.isNotEmpty()) {
            payload["email_from_alias"] = emailFromAlias
        }

        setLoading(true)
        ApiClient.getApiService().updateRuntimeConfig(payload).enqueue(object : Callback<RuntimeConfigResponse> {
            override fun onResponse(
                call: Call<RuntimeConfigResponse>,
                response: Response<RuntimeConfigResponse>,
            ) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                if (response.code() == 401) {
                    handleUnauthorized()
                    return
                }
                if (!hasActiveSession()) {
                    return
                }
                if (response.isSuccessful && response.body() != null) {
                    bindRuntimeConfig(response.body())
                    showToast(getString(R.string.subscriptions_save_success))
                } else {
                    showToast(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.subscriptions_error_save_runtime, "request failed"),
                        ),
                    )
                }
            }

            override fun onFailure(call: Call<RuntimeConfigResponse>, t: Throwable) {
                setLoading(false)
                if (!isAdded || !hasActiveSession()) {
                    return
                }
                showToast(getString(R.string.subscriptions_error_save_runtime, t.message ?: "unknown"))
            }
        })
    }

    private fun confirmClearRuntimeConfig() {
        val safeContext = context ?: return
        MaterialAlertDialogBuilder(safeContext, R.style.AlertDialogTheme)
            .setMessage(getString(R.string.subscriptions_clear_runtime_confirm))
            .setPositiveButton(android.R.string.ok) { _, _ -> clearRuntimeConfig() }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun clearRuntimeConfig() {
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }

        setLoading(true)
        ApiClient.getApiService().clearRuntimeConfig().enqueue(object : Callback<RuntimeConfigResponse> {
            override fun onResponse(
                call: Call<RuntimeConfigResponse>,
                response: Response<RuntimeConfigResponse>,
            ) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                if (response.code() == 401) {
                    handleUnauthorized()
                    return
                }
                if (!hasActiveSession()) {
                    return
                }
                if (response.isSuccessful && response.body() != null) {
                    bindRuntimeConfig(response.body())
                    showToast(getString(R.string.subscriptions_clear_runtime_success))
                } else {
                    showToast(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.subscriptions_error_clear_runtime, "request failed"),
                        ),
                    )
                }
            }

            override fun onFailure(call: Call<RuntimeConfigResponse>, t: Throwable) {
                setLoading(false)
                if (!isAdded || !hasActiveSession()) {
                    return
                }
                showToast(getString(R.string.subscriptions_error_clear_runtime, t.message ?: "unknown"))
            }
        })
    }

    private fun createSubscription() {
        val binding = bindingOrNull ?: return
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }

        val payload = buildCreateSubscriptionPayload(
            repoUrl = binding.createRepoInput.text?.toString()?.trim().orEmpty(),
            morningEnabled = binding.createMorningCheckbox.isChecked,
            panoramaEnabled = binding.createPanoramaCheckbox.isChecked,
            recipientEmail = binding.createRecipientEmailInput.text?.toString()?.trim().orEmpty(),
        ) ?: return

        setLoading(true)
        ApiClient.getApiService().createSubscription(payload).enqueue(object : Callback<SubscriptionResponse> {
            override fun onResponse(
                call: Call<SubscriptionResponse>,
                response: Response<SubscriptionResponse>,
            ) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                if (response.code() == 401) {
                    handleUnauthorized()
                    return
                }
                if (!hasActiveSession()) {
                    return
                }
                if (response.isSuccessful && response.body() != null) {
                    syncLocalReminder(response.body()!!, promptForPermission = true)
                    resetCreateForm()
                    loadSubscriptions()
                    showToast(getString(R.string.subscriptions_create_success))
                } else {
                    showToast(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.subscriptions_error_create, "request failed"),
                        ),
                    )
                }
            }

            override fun onFailure(call: Call<SubscriptionResponse>, t: Throwable) {
                setLoading(false)
                if (!isAdded || !hasActiveSession()) {
                    return
                }
                showToast(getString(R.string.subscriptions_error_create, t.message ?: "unknown"))
            }
        })
    }

    private fun resetCreateForm() {
        val binding = bindingOrNull ?: return
        binding.createRepoInput.setText("")
        binding.createRecipientEmailInput.setText(currentUser?.email?.trim().orEmpty())
        binding.createMorningCheckbox.isChecked = true
        binding.createPanoramaCheckbox.isChecked = true
    }

    private fun renderCurrentRepoStatus() {
        val binding = bindingOrNull ?: return
        val current = currentRepoUrl ?: currentRepoStoreValue()
        binding.currentRepoStatusText.text = if (current.isNullOrBlank()) {
            getString(R.string.subscriptions_current_repo_none)
        } else {
            getString(R.string.subscriptions_current_repo_status, current)
        }
    }

    private fun renderSubscriptions(list: List<SubscriptionResponse>) {
        val binding = bindingOrNull ?: return
        binding.subscriptionsListContainer.removeAllViews()
        binding.subscriptionsEmptyState.visibility = if (hasActiveSession() && list.isEmpty()) View.VISIBLE else View.GONE

        list.forEachIndexed { index, subscription ->
            val itemView = layoutInflater.inflate(
                R.layout.item_subscription_card,
                binding.subscriptionsListContainer,
                false,
            )
            bindSubscriptionCard(itemView, subscription, index + 1)
            binding.subscriptionsListContainer.addView(itemView)
        }
    }

    private fun bindSubscriptionCard(view: View, subscription: SubscriptionResponse, displayIndex: Int) {
        val title = view.findViewById<TextView>(R.id.subscription_title)
        val meta = view.findViewById<TextView>(R.id.subscription_meta)
        val currentBadge = view.findViewById<TextView>(R.id.subscription_current_badge)
        val repoInput = view.findViewById<EditText>(R.id.edit_repo_url)
        val recipientEmailInput = view.findViewById<EditText>(R.id.edit_recipient_email_input)
        val morningCheckbox = view.findViewById<CheckBox>(R.id.edit_morning_checkbox)
        val panoramaCheckbox = view.findViewById<CheckBox>(R.id.edit_panorama_checkbox)
        val deliveryModeGroup = view.findViewById<RadioGroup>(R.id.edit_delivery_mode_group)
        val sendNowOption = view.findViewById<RadioButton>(R.id.edit_send_now_option)
        val sendScheduledOption = view.findViewById<RadioButton>(R.id.edit_send_scheduled_option)
        val scheduleTimeContainer = view.findViewById<View>(R.id.edit_schedule_time_container)
        val deliveryInput = view.findViewById<EditText>(R.id.edit_delivery_time_input)
        val sendButton = view.findViewById<Button>(R.id.button_send_subscription_email)
        val selectCurrentButton = view.findViewById<Button>(R.id.button_select_current_repo)
        val saveButton = view.findViewById<Button>(R.id.button_save_subscription)
        val deleteButton = view.findViewById<Button>(R.id.button_delete_subscription)

        val repoUrl = normalizeRepoUrl(subscription.repoUrl)
        val isCurrent = repoUrl.isNotBlank() && repoUrl == currentRepoUrl
        val deliveryMode = normalizeDeliveryMode(subscription.deliveryMode)
        val deliveryTime = subscription.deliveryTime ?: getString(R.string.subscriptions_default_delivery_time)

        title.text = getString(R.string.subscriptions_card_title, displayIndex, subscription.repoUrl ?: "")
        meta.text = buildSubscriptionMeta(subscription, deliveryMode, deliveryTime)
        currentBadge.visibility = if (isCurrent) View.VISIBLE else View.GONE
        repoInput.setText(subscription.repoUrl ?: "")
        recipientEmailInput.setText(subscription.recipientEmail ?: "")
        morningCheckbox.isChecked = subscription.isMorningReportEnabled
        panoramaCheckbox.isChecked = subscription.isCodePanoramaEnabled
        deliveryInput.setText(deliveryTime)
        configureTimeInput(deliveryInput)

        if (deliveryMode == DELIVERY_MODE_INSTANT) {
            sendNowOption.isChecked = true
        } else {
            sendScheduledOption.isChecked = true
        }
        bindDeliveryModeGroup(
            group = deliveryModeGroup,
            scheduledOption = sendScheduledOption,
            timeContainer = scheduleTimeContainer,
        )

        selectCurrentButton.text = getString(
            if (isCurrent) R.string.subscriptions_current_repo_selected_action else R.string.subscriptions_select_current_repo,
        )
        selectCurrentButton.isEnabled = !isCurrent && repoUrl.isNotBlank()
        selectCurrentButton.setOnClickListener {
            if (repoUrl.isBlank()) {
                showToast(getString(R.string.subscriptions_error_repo_required))
                return@setOnClickListener
            }
            val safeAppContext = appContextOrNull() ?: run {
                showToast(getString(R.string.subscriptions_notification_setup_failed))
                return@setOnClickListener
            }
            currentRepoUrl = repoUrl
            CurrentRepoStore.setSelectedRepoUrl(safeAppContext, repoUrl)
            renderCurrentRepoStatus()
            renderSubscriptions(subscriptions)
            showToast(getString(R.string.subscriptions_current_repo_saved))
        }

        saveButton.setOnClickListener {
            saveSubscriptionEdits(
                subscription = subscription,
                repoUrl = repoInput.text?.toString()?.trim().orEmpty(),
                morningEnabled = morningCheckbox.isChecked,
                panoramaEnabled = panoramaCheckbox.isChecked,
                recipientEmail = recipientEmailInput.text?.toString()?.trim().orEmpty(),
                deliveryMode = currentDeliveryMode(sendScheduledOption.isChecked),
                deliveryTime = deliveryInput.text?.toString()?.trim().orEmpty(),
                successMessageResId = R.string.subscriptions_update_success,
                reloadAfterSuccess = true,
            )
        }

        sendButton.setOnClickListener {
            val selectedDeliveryMode = currentDeliveryMode(sendScheduledOption.isChecked)
            saveSubscriptionEdits(
                subscription = subscription,
                repoUrl = repoInput.text?.toString()?.trim().orEmpty(),
                morningEnabled = morningCheckbox.isChecked,
                panoramaEnabled = panoramaCheckbox.isChecked,
                recipientEmail = recipientEmailInput.text?.toString()?.trim().orEmpty(),
                deliveryMode = selectedDeliveryMode,
                deliveryTime = deliveryInput.text?.toString()?.trim().orEmpty(),
                successMessageResId = null,
                reloadAfterSuccess = false,
            ) { updated ->
                if (normalizeDeliveryMode(updated.deliveryMode) == DELIVERY_MODE_INSTANT) {
                    loadSubscriptions()
                    showToast(getString(R.string.subscriptions_send_email_success_instant_mode))
                } else {
                    sendSubscriptionEmail(updated)
                }
            }
        }

        deleteButton.setOnClickListener {
            val safeContext = context ?: return@setOnClickListener
            MaterialAlertDialogBuilder(safeContext, R.style.AlertDialogTheme)
                .setMessage(getString(R.string.subscriptions_delete_confirm, displayIndex))
                .setPositiveButton(android.R.string.ok) { _, _ ->
                    setLoading(true)
                    ApiClient.getApiService().deleteSubscription(subscription.id)
                        .enqueue(object : Callback<ResponseBody> {
                            override fun onResponse(
                                call: Call<ResponseBody>,
                                response: Response<ResponseBody>,
                            ) {
                                setLoading(false)
                                if (!isAdded) {
                                    return
                                }
                                if (response.code() == 401) {
                                    handleUnauthorized()
                                    return
                                }
                                if (!hasActiveSession()) {
                                    return
                                }
                                if (response.isSuccessful) {
                                    cancelLocalReminder(subscription.id)
                                    if (currentRepoUrl == repoUrl) {
                                        appContextOrNull()?.let(CurrentRepoStore::clearSelectedRepoUrl)
                                        currentRepoUrl = null
                                    }
                                    loadSubscriptions()
                                    showToast(getString(R.string.subscriptions_delete_success))
                                } else {
                                    showToast(
                                        ApiErrorParser.parse(
                                            response,
                                            getString(R.string.subscriptions_error_delete, "request failed"),
                                        ),
                                    )
                                }
                            }

                            override fun onFailure(call: Call<ResponseBody>, t: Throwable) {
                                setLoading(false)
                                if (!isAdded || !hasActiveSession()) {
                                    return
                                }
                                showToast(getString(R.string.subscriptions_error_delete, t.message ?: "unknown"))
                            }
                        })
                }
                .setNegativeButton(android.R.string.cancel, null)
                .show()
        }
    }

    private fun buildCreateSubscriptionPayload(
        repoUrl: String,
        morningEnabled: Boolean,
        panoramaEnabled: Boolean,
        recipientEmail: String,
    ): Map<String, Any>? {
        return buildSubscriptionPayload(
            repoUrl = repoUrl,
            morningEnabled = morningEnabled,
            panoramaEnabled = panoramaEnabled,
            recipientEmail = recipientEmail,
            deliveryMode = DELIVERY_MODE_SCHEDULED,
            deliveryTime = getString(R.string.subscriptions_default_delivery_time),
        )
    }

    private fun saveSubscriptionEdits(
        subscription: SubscriptionResponse,
        repoUrl: String,
        morningEnabled: Boolean,
        panoramaEnabled: Boolean,
        recipientEmail: String,
        deliveryMode: String,
        deliveryTime: String,
        successMessageResId: Int?,
        reloadAfterSuccess: Boolean,
        afterSave: ((SubscriptionResponse) -> Unit)? = null,
    ) {
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }

        val payload = buildSubscriptionPayload(
            repoUrl = repoUrl,
            morningEnabled = morningEnabled,
            panoramaEnabled = panoramaEnabled,
            recipientEmail = recipientEmail,
            deliveryMode = deliveryMode,
            deliveryTime = deliveryTime,
        ) ?: return

        setLoading(true)
        ApiClient.getApiService().updateSubscription(subscription.id, payload)
            .enqueue(object : Callback<SubscriptionResponse> {
                override fun onResponse(
                    call: Call<SubscriptionResponse>,
                    response: Response<SubscriptionResponse>,
                ) {
                    setLoading(false)
                    if (!isAdded) {
                        return
                    }
                    if (response.code() == 401) {
                        handleUnauthorized()
                        return
                    }
                    if (!hasActiveSession()) {
                        return
                    }
                    if (response.isSuccessful && response.body() != null) {
                        val updated = response.body()!!
                        syncLocalReminder(updated, promptForPermission = true)
                        syncCurrentRepoSelection(
                            previousRepoUrl = normalizeRepoUrl(subscription.repoUrl),
                            nextRepoUrl = normalizeRepoUrl(updated.repoUrl),
                        )
                        if (afterSave != null) {
                            afterSave(updated)
                            return
                        }
                        if (reloadAfterSuccess) {
                            loadSubscriptions()
                        }
                        if (successMessageResId != null) {
                            showToast(getString(successMessageResId))
                        }
                    } else {
                        showToast(
                            ApiErrorParser.parse(
                                response,
                                getString(R.string.subscriptions_error_update, "request failed"),
                            ),
                        )
                    }
                }

                override fun onFailure(call: Call<SubscriptionResponse>, t: Throwable) {
                    setLoading(false)
                    if (!isAdded || !hasActiveSession()) {
                        return
                    }
                    showToast(getString(R.string.subscriptions_error_update, t.message ?: "unknown"))
                }
            })
    }

    private fun sendSubscriptionEmail(subscription: SubscriptionResponse) {
        if (!hasActiveSession()) {
            renderLoggedOutState()
            return
        }

        setLoading(true)
        ApiClient.getApiService().sendSubscription(subscription.id).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(
                call: Call<Map<String, Any>>,
                response: Response<Map<String, Any>>,
            ) {
                setLoading(false)
                if (!isAdded) {
                    return
                }
                if (response.code() == 401) {
                    handleUnauthorized()
                    return
                }
                if (!hasActiveSession()) {
                    return
                }
                if (response.isSuccessful) {
                    showCompanionReminder(subscription.id)
                    loadSubscriptions()
                    showToast(getString(R.string.subscriptions_send_email_success))
                } else {
                    showToast(
                        ApiErrorParser.parse(
                            response,
                            getString(R.string.subscriptions_error_send_email, "request failed"),
                        ),
                    )
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                setLoading(false)
                if (!isAdded || !hasActiveSession()) {
                    return
                }
                showToast(getString(R.string.subscriptions_error_send_email, t.message ?: "unknown"))
            }
        })
    }

    private fun showCompanionReminder(subscriptionId: Int) {
        val context = context ?: return
        if (!hasNotificationPermission()) {
            showToast(getString(R.string.subscriptions_notification_permission_needed))
            return
        }
        val shown = NotificationScheduler.showNotificationNow(
            context = context,
            subscriptionId = subscriptionId,
            title = getString(R.string.subscriptions_companion_reminder_title),
            message = getString(R.string.subscriptions_companion_reminder_message),
        )
        if (!shown) {
            showToast(getString(R.string.subscriptions_notification_show_failed))
        }
    }

    private fun syncCurrentRepoSelection(previousRepoUrl: String, nextRepoUrl: String) {
        if (currentRepoUrl != previousRepoUrl || nextRepoUrl.isBlank()) {
            return
        }
        currentRepoUrl = nextRepoUrl
        appContextOrNull()?.let { CurrentRepoStore.setSelectedRepoUrl(it, nextRepoUrl) }
    }

    private fun buildSubscriptionPayload(
        repoUrl: String,
        morningEnabled: Boolean,
        panoramaEnabled: Boolean,
        recipientEmail: String,
        deliveryMode: String,
        deliveryTime: String,
    ): Map<String, Any>? {
        val normalizedRepoUrl = repoUrl.trim()
        if (normalizedRepoUrl.isBlank()) {
            showToast(getString(R.string.subscriptions_error_repo_required))
            return null
        }

        val normalizedEmail = recipientEmail.trim()
        if (!Patterns.EMAIL_ADDRESS.matcher(normalizedEmail).matches()) {
            showToast(getString(R.string.subscriptions_error_email_required))
            return null
        }

        val normalizedTime = normalizeDeliveryTime(deliveryTime) ?: run {
            showToast(getString(R.string.subscriptions_error_time_required))
            return null
        }

        return mapOf(
            "repo_url" to normalizedRepoUrl,
            "morning_report_enabled" to morningEnabled,
            "code_panorama_enabled" to panoramaEnabled,
            "recipient_email" to normalizedEmail,
            "delivery_mode" to normalizeDeliveryMode(deliveryMode),
            "frequency" to "daily",
            "delivery_time" to normalizedTime,
            "update_strategy" to "incremental",
        )
    }

    private fun bindDeliveryModeGroup(
        group: RadioGroup,
        scheduledOption: RadioButton,
        timeContainer: View,
    ) {
        timeContainer.visibility = if (scheduledOption.isChecked) View.VISIBLE else View.GONE
        group.setOnCheckedChangeListener { _, _ ->
            timeContainer.visibility = if (scheduledOption.isChecked) View.VISIBLE else View.GONE
        }
    }

    private fun configureTimeInput(input: EditText) {
        input.isFocusable = false
        input.isClickable = true
        input.isCursorVisible = false
        input.setOnClickListener {
            showSpinnerTimePicker(input)
        }
    }

    private fun showSpinnerTimePicker(targetInput: EditText) {
        val safeContext = context ?: return
        val currentTime = normalizeDeliveryTime(targetInput.text?.toString()?.trim().orEmpty())
            ?: getString(R.string.subscriptions_default_delivery_time)
        val (hour, minute) = parseHourMinute(currentTime)
        val dialogView = layoutInflater.inflate(R.layout.dialog_spinner_time_picker, null)
        val timePicker = dialogView.findViewById<TimePicker>(R.id.spinner_time_picker)
        timePicker.setIs24HourView(true)
        timePicker.hour = hour
        timePicker.minute = minute

        MaterialAlertDialogBuilder(safeContext, R.style.AlertDialogTheme)
            .setTitle(R.string.subscriptions_time_picker_title)
            .setView(dialogView)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                targetInput.setText(formatTime(timePicker.hour, timePicker.minute))
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun currentDeliveryMode(isScheduled: Boolean): String {
        return if (isScheduled) DELIVERY_MODE_SCHEDULED else DELIVERY_MODE_INSTANT
    }

    private fun normalizeDeliveryMode(value: String?): String {
        return if (value?.trim().equals(DELIVERY_MODE_INSTANT, ignoreCase = true)) {
            DELIVERY_MODE_INSTANT
        } else {
            DELIVERY_MODE_SCHEDULED
        }
    }

    private fun normalizeDeliveryTime(value: String): String? {
        val parts = value.split(":")
        if (parts.size != 2) {
            return null
        }
        val hour = parts[0].toIntOrNull() ?: return null
        val minute = parts[1].toIntOrNull() ?: return null
        if (hour !in 0..23 || minute !in 0..59) {
            return null
        }
        return formatTime(hour, minute)
    }

    private fun parseHourMinute(value: String): Pair<Int, Int> {
        val normalized = normalizeDeliveryTime(value) ?: getString(R.string.subscriptions_default_delivery_time)
        val parts = normalized.split(":")
        return Pair(parts[0].toInt(), parts[1].toInt())
    }

    private fun formatTime(hour: Int, minute: Int): String {
        return String.format(Locale.US, "%02d:%02d", hour, minute)
    }

    private fun syncLocalReminders(list: List<SubscriptionResponse>) {
        list.forEach { subscription ->
            syncLocalReminder(subscription, promptForPermission = false)
        }
    }

    private fun syncLocalReminder(
        subscription: SubscriptionResponse,
        promptForPermission: Boolean,
    ) {
        syncLocalReminder(
            subscriptionId = subscription.id,
            deliveryMode = normalizeDeliveryMode(subscription.deliveryMode),
            deliveryTime = subscription.deliveryTime,
            promptForPermission = promptForPermission,
        )
    }

    private fun syncLocalReminder(
        subscriptionId: Int,
        deliveryMode: String,
        deliveryTime: String?,
        promptForPermission: Boolean,
    ) {
        if (subscriptionId <= 0) {
            return
        }
        if (deliveryMode != DELIVERY_MODE_SCHEDULED) {
            cancelLocalReminder(subscriptionId)
            return
        }

        val normalizedTime = normalizeDeliveryTime(deliveryTime.orEmpty()) ?: return
        val request = LocalReminderRequest(
            subscriptionId = subscriptionId,
            deliveryTime = normalizedTime,
        )

        if (hasNotificationPermission()) {
            applyLocalReminder(request)
            return
        }
        if (promptForPermission) {
            requestNotificationPermissionIfNeeded(request)
        }
    }

    private fun applyLocalReminder(request: LocalReminderRequest, notifyOnFailure: Boolean = true): Boolean {
        val context = context ?: return false
        val (hour, minute) = parseHourMinute(request.deliveryTime)
        val scheduled = NotificationScheduler.scheduleDailyNotification(
            context = context,
            subscriptionId = request.subscriptionId,
            hour = hour,
            minute = minute,
            title = getString(R.string.subscriptions_companion_reminder_title),
            message = getString(R.string.subscriptions_companion_reminder_message),
        )
        if (!scheduled && notifyOnFailure) {
            showToast(getString(R.string.subscriptions_notification_setup_failed))
        }
        return scheduled
    }

    private fun cancelLocalReminder(subscriptionId: Int) {
        val context = context ?: return
        NotificationScheduler.cancelScheduledNotification(context, subscriptionId)
    }

    private fun requestNotificationPermissionIfNeeded(request: LocalReminderRequest) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            applyLocalReminder(request)
            return
        }
        if (hasNotificationPermission()) {
            applyLocalReminder(request)
            return
        }

        pendingReminderRequests.removeAll { it.subscriptionId == request.subscriptionId }
        pendingReminderRequests.add(request)
        notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun hasNotificationPermission(): Boolean {
        val context = context ?: return false
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
    }

    private fun buildSubscriptionMeta(
        subscription: SubscriptionResponse,
        deliveryMode: String,
        deliveryTime: String,
    ): String {
        val lines = mutableListOf(
            getString(
                R.string.subscriptions_card_meta,
                formatTimestamp(subscription.createdAt),
                formatTimestamp(subscription.updatedAt),
            ),
        )

        val recipientEmail = subscription.recipientEmail?.trim().orEmpty()
        if (recipientEmail.isNotEmpty()) {
            lines.add(getString(R.string.subscriptions_meta_email, recipientEmail))
        }

        lines.add(
            if (deliveryMode == DELIVERY_MODE_INSTANT) {
                getString(R.string.subscriptions_meta_delivery_email_now)
            } else {
                getString(R.string.subscriptions_meta_delivery_email_scheduled, deliveryTime)
            },
        )

        return lines.joinToString("\n")
    }

    private fun resolveCurrentRepoUrl(list: List<SubscriptionResponse>): String? {
        val available = list.mapNotNull { normalizeRepoUrl(it.repoUrl).ifBlank { null } }
        if (available.isEmpty()) {
            appContextOrNull()?.let(CurrentRepoStore::clearSelectedRepoUrl)
            return null
        }

        val stored = currentRepoStoreValue()
        val resolved = when {
            !stored.isNullOrBlank() && available.contains(stored) -> stored
            else -> available.first()
        }
        appContextOrNull()?.let { CurrentRepoStore.setSelectedRepoUrl(it, resolved) }
        return resolved
    }

    private fun normalizeRepoUrl(value: String?): String {
        return value?.trim().orEmpty()
    }

    private fun setLoading(loading: Boolean) {
        loadingCount = (loadingCount + if (loading) 1 else -1).coerceAtLeast(0)
        val binding = bindingOrNull ?: return
        binding.progressBar.visibility = if (loadingCount > 0) View.VISIBLE else View.GONE

        val enabled = loadingCount == 0
        val sessionActive = hasActiveSession()
        binding.buttonAuthModeLogin.isEnabled = enabled && !sessionActive && authMode != AuthMode.LOGIN
        binding.buttonAuthModeRegister.isEnabled = enabled && !sessionActive && authMode != AuthMode.REGISTER
        binding.authEmailInput.isEnabled = enabled && !sessionActive
        binding.authDisplayNameInput.isEnabled = enabled && !sessionActive
        binding.authPasswordInput.isEnabled = enabled && !sessionActive
        binding.buttonAuthSubmit.isEnabled = enabled && !sessionActive
        binding.buttonLogout.isEnabled = enabled && sessionActive
        binding.buttonChangePassword.isEnabled = enabled && sessionActive && currentUser.usesPasswordAuth()
        binding.buttonRegisterNewAccount.isEnabled = enabled && sessionActive

        binding.buttonRefreshSubscriptions.isEnabled = enabled && sessionActive
        binding.buttonSaveRuntime.isEnabled = enabled && sessionActive
        binding.buttonClearRuntime.isEnabled = enabled && sessionActive
        binding.buttonCreateSubscription.isEnabled = enabled && sessionActive
        binding.runtimeEmailAccessKeyIdInput.isEnabled = enabled && sessionActive
        binding.runtimeEmailAccessKeySecretInput.isEnabled = enabled && sessionActive
        binding.runtimeEmailAccountNameInput.isEnabled = enabled && sessionActive
        binding.runtimeEmailRegionIdInput.isEnabled = enabled && sessionActive
        binding.runtimeEmailEndpointInput.isEnabled = enabled && sessionActive
        binding.runtimeEmailFromAliasInput.isEnabled = enabled && sessionActive
        renderGitHubOauthButton()
    }

    private fun parsePositiveDouble(input: EditText, fallback: Double): Double {
        val value = input.text?.toString()?.trim()?.toDoubleOrNull() ?: return fallback
        return if (value > 0) value else fallback
    }

    private fun parseNonNegativeInt(input: EditText, fallback: Int): Int {
        val value = input.text?.toString()?.trim()?.toIntOrNull() ?: return fallback
        return if (value >= 0) value else fallback
    }

    private fun formatTimeoutSeconds(value: Double?): String {
        if (value == null) {
            return DEFAULT_TIMEOUT_SECONDS
        }
        val intValue = value.toInt()
        return if (value == intValue.toDouble()) intValue.toString() else value.toString()
    }

    private fun formatTimestamp(value: String?): String {
        val normalized = value?.trim().orEmpty()
        if (normalized.isEmpty()) {
            return "unknown"
        }

        return runCatching {
            OffsetDateTime.parse(normalized)
                .atZoneSameInstant(ZoneId.systemDefault())
                .format(TIMESTAMP_FORMATTER)
        }.recoverCatching {
            LocalDateTime.parse(normalized.replace(" ", "T"))
                .atZone(ZoneId.systemDefault())
                .format(TIMESTAMP_FORMATTER)
        }.getOrElse {
            normalized.replace("T", " ").replace("Z", "")
        }
    }

    private fun hasActiveSession(): Boolean {
        val safeAppContext = appContextOrNull() ?: return false
        return SessionStore.hasActiveSession(safeAppContext)
    }

    private fun appContextOrNull(): Context? {
        return applicationContext ?: context?.applicationContext
    }

    private fun currentRepoStoreValue(): String? {
        val safeAppContext = appContextOrNull() ?: return null
        return CurrentRepoStore.getSelectedRepoUrl(safeAppContext)
    }

    private fun clearShowcaseSessionCookie() {
        val cookieManager = CookieManager.getInstance()
        cookieManager.setAcceptCookie(true)
        cookieManager.setCookie(
            ApiClient.BASE_URL,
            "nightshift_access_token=; Max-Age=0; Path=/; SameSite=Lax",
        )
        cookieManager.flush()
    }

    private fun showToast(message: String) {
        val safeContext = context ?: return
        Toast.makeText(safeContext, message, Toast.LENGTH_SHORT).show()
    }

    override fun onDestroyView() {
        githubOauthHandler.removeCallbacks(githubOauthPollRunnable)
        super.onDestroyView()
        _binding = null
    }

    private fun UserProfileResponse?.usesPasswordAuth(): Boolean {
        return this?.authSource?.trim()?.equals("password", ignoreCase = true) == true
    }
}
