package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class UserProfileResponse {
    @SerializedName("id")
    private int id;

    @SerializedName("email")
    private String email;

    @SerializedName("display_name")
    private String displayName;

    @SerializedName("auth_source")
    private String authSource;

    @SerializedName("github_login")
    private String githubLogin;

    @SerializedName("avatar_url")
    private String avatarUrl;

    @SerializedName("github_connected")
    private boolean githubConnected;

    @SerializedName("created_at")
    private String createdAt;

    @SerializedName("updated_at")
    private String updatedAt;

    @SerializedName("last_login_at")
    private String lastLoginAt;

    public int getId() {
        return id;
    }

    public String getEmail() {
        return email;
    }

    public String getDisplayName() {
        return displayName;
    }

    public String getAuthSource() {
        return authSource;
    }

    public String getGithubLogin() {
        return githubLogin;
    }

    public String getAvatarUrl() {
        return avatarUrl;
    }

    public boolean isGithubConnected() {
        return githubConnected;
    }

    public String getCreatedAt() {
        return createdAt;
    }

    public String getUpdatedAt() {
        return updatedAt;
    }

    public String getLastLoginAt() {
        return lastLoginAt;
    }
}
