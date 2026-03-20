package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class RepoSubscriptionRequest {
    @SerializedName("repo_url")
    private String repoUrl;

    public RepoSubscriptionRequest(String repoUrl) {
        this.repoUrl = repoUrl;
    }

    public String getRepoUrl() {
        return repoUrl;
    }

    public void setRepoUrl(String repoUrl) {
        this.repoUrl = repoUrl;
    }
}
