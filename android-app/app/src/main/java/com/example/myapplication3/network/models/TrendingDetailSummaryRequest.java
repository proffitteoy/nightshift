package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

import java.util.List;

public class TrendingDetailSummaryRequest {
    @SerializedName("repo_full_name")
    private final String repoFullName;

    @SerializedName("description")
    private final String description;

    @SerializedName("project_summary")
    private final String projectSummary;

    @SerializedName("language")
    private final String language;

    @SerializedName("stars_total")
    private final int starsTotal;

    @SerializedName("trend_7d")
    private final List<Integer> trend7d;

    @SerializedName("link")
    private final String link;

    public TrendingDetailSummaryRequest(
            String repoFullName,
            String description,
            String projectSummary,
            String language,
            int starsTotal,
            List<Integer> trend7d,
            String link
    ) {
        this.repoFullName = repoFullName;
        this.description = description;
        this.projectSummary = projectSummary;
        this.language = language;
        this.starsTotal = starsTotal;
        this.trend7d = trend7d;
        this.link = link;
    }
}
