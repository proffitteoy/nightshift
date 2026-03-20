package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class AuthTokenResponse {
    @SerializedName("access_token")
    private String accessToken;

    @SerializedName("token_type")
    private String tokenType;

    @SerializedName("expires_in")
    private int expiresIn;

    @SerializedName("user")
    private UserProfileResponse user;

    @SerializedName("repo_sync")
    private RepoSyncSummary repoSync;

    public String getAccessToken() {
        return accessToken;
    }

    public String getTokenType() {
        return tokenType;
    }

    public int getExpiresIn() {
        return expiresIn;
    }

    public UserProfileResponse getUser() {
        return user;
    }

    public RepoSyncSummary getRepoSync() {
        return repoSync;
    }
}
