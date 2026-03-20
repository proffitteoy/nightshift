package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class GitHubOAuthPollResponse {
    @SerializedName("status")
    private String status;

    @SerializedName("message")
    private String message;

    @SerializedName("auth")
    private AuthTokenResponse auth;

    public String getStatus() {
        return status;
    }

    public String getMessage() {
        return message;
    }

    public AuthTokenResponse getAuth() {
        return auth;
    }
}
