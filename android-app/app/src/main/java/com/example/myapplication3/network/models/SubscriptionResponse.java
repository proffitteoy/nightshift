package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class SubscriptionResponse {
    @SerializedName("id")
    private int id;

    @SerializedName("repo_url")
    private String repoUrl;

    @SerializedName("morning_report_enabled")
    private boolean morningReportEnabled;

    @SerializedName("code_panorama_enabled")
    private boolean codePanoramaEnabled;

    @SerializedName("recipient_email")
    private String recipientEmail;

    @SerializedName("delivery_mode")
    private String deliveryMode;

    @SerializedName("frequency")
    private String frequency;

    @SerializedName("delivery_time")
    private String deliveryTime;

    @SerializedName("update_strategy")
    private String updateStrategy;

    @SerializedName("created_at")
    private String createdAt;

    @SerializedName("updated_at")
    private String updatedAt;

    public int getId() {
        return id;
    }

    public String getRepoUrl() {
        return repoUrl;
    }

    public boolean isMorningReportEnabled() {
        return morningReportEnabled;
    }

    public boolean isCodePanoramaEnabled() {
        return codePanoramaEnabled;
    }

    public String getRecipientEmail() {
        return recipientEmail;
    }

    public String getDeliveryMode() {
        return deliveryMode;
    }

    public String getFrequency() {
        return frequency;
    }

    public String getDeliveryTime() {
        return deliveryTime;
    }

    public String getUpdateStrategy() {
        return updateStrategy;
    }

    public String getCreatedAt() {
        return createdAt;
    }

    public String getUpdatedAt() {
        return updatedAt;
    }
}
