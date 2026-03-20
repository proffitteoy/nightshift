package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class RuntimeConfigResponse {
    @SerializedName("github_token_configured")
    private boolean githubTokenConfigured;

    @SerializedName("llm_api_key_configured")
    private boolean llmApiKeyConfigured;

    @SerializedName("llm_base_url")
    private String llmBaseUrl;

    @SerializedName("llm_model")
    private String llmModel;

    @SerializedName("llm_timeout_seconds")
    private double llmTimeoutSeconds;

    @SerializedName("llm_max_retries")
    private int llmMaxRetries;

    @SerializedName("email_access_key_id_configured")
    private boolean emailAccessKeyIdConfigured;

    @SerializedName("email_access_key_secret_configured")
    private boolean emailAccessKeySecretConfigured;

    @SerializedName("email_account_name")
    private String emailAccountName;

    @SerializedName("email_region_id")
    private String emailRegionId;

    @SerializedName("email_endpoint")
    private String emailEndpoint;

    @SerializedName("email_from_alias")
    private String emailFromAlias;

    public boolean isGithubTokenConfigured() {
        return githubTokenConfigured;
    }

    public boolean isLlmApiKeyConfigured() {
        return llmApiKeyConfigured;
    }

    public String getLlmBaseUrl() {
        return llmBaseUrl;
    }

    public String getLlmModel() {
        return llmModel;
    }

    public double getLlmTimeoutSeconds() {
        return llmTimeoutSeconds;
    }

    public int getLlmMaxRetries() {
        return llmMaxRetries;
    }

    public boolean isEmailAccessKeyIdConfigured() {
        return emailAccessKeyIdConfigured;
    }

    public boolean isEmailAccessKeySecretConfigured() {
        return emailAccessKeySecretConfigured;
    }

    public String getEmailAccountName() {
        return emailAccountName;
    }

    public String getEmailRegionId() {
        return emailRegionId;
    }

    public String getEmailEndpoint() {
        return emailEndpoint;
    }

    public String getEmailFromAlias() {
        return emailFromAlias;
    }
}
