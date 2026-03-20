package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class TrendingAnalysisResponse {
    @SerializedName("message")
    private String message;
    
    @SerializedName("file_path")
    private String filePath;
    
    @SerializedName("data")
    private List<ProjectAnalysis> data;

    public String getMessage() {
        return message;
    }

    public String getFilePath() {
        return filePath;
    }

    public List<ProjectAnalysis> getData() {
        return data;
    }

    public static class ProjectAnalysis {
        @SerializedName("repo_full_name")
        private String repoFullName;

        @SerializedName("description")
        private String description;

        @SerializedName("stars_total")
        private int starsTotal;

        @SerializedName("project_summary")
        private String projectSummary;

        @SerializedName("language")
        private String language;

        @SerializedName("link")
        private String link;

        @SerializedName("trend_7d")
        private List<Integer> trend7d;

        public String getRepoFullName() {
            return repoFullName;
        }

        public String getDescription() {
            return description;
        }

        public int getStarsTotal() {
            return starsTotal;
        }

        public String getProjectSummary() {
            return projectSummary;
        }

        public String getLanguage() {
            return language;
        }

        public String getLink() {
            return link;
        }

        public List<Integer> getTrend7d() {
            return trend7d;
        }
    }
}
