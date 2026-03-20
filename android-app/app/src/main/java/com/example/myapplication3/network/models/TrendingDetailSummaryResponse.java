package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class TrendingDetailSummaryResponse {
    @SerializedName("repo_full_name")
    private String repoFullName;

    @SerializedName("summary")
    private String summary;

    @SerializedName("source")
    private String source;

    public String getRepoFullName() {
        return repoFullName;
    }

    public String getSummary() {
        return summary;
    }

    public String getSource() {
        return source;
    }
}
