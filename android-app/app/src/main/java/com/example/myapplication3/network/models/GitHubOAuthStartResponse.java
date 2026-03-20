package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class GitHubOAuthStartResponse {
    @SerializedName("authorize_url")
    private String authorizeUrl;

    @SerializedName("poll_token")
    private String pollToken;

    @SerializedName("expires_in")
    private int expiresIn;

    @SerializedName("mode")
    private String mode;

    public String getAuthorizeUrl() {
        return authorizeUrl;
    }

    public String getPollToken() {
        return pollToken;
    }

    public int getExpiresIn() {
        return expiresIn;
    }

    public String getMode() {
        return mode;
    }
}
