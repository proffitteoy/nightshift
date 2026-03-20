package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class DailyReportResponse {
    @SerializedName("message")
    private String message;
    
    @SerializedName("report")
    private DailyReport report;
    
    @SerializedName("data_file")
    private String dataFile;

    public String getMessage() {
        return message;
    }

    public DailyReport getReport() {
        return report;
    }

    public String getDataFile() {
        return dataFile;
    }

    public static class DailyReport {
        @SerializedName("repository")
        private String repository;

        @SerializedName("report_date")
        private String reportDate;

        @SerializedName("time_range")
        private String timeRange;

        @SerializedName("stats")
        private Stats stats;

        @SerializedName("summary_text")
        private String summaryText;

        @SerializedName("todo_list")
        private List<String> todoList;

        @SerializedName("details")
        private Details details;

        @SerializedName("summary")
        private ReportSummary summary;

        @SerializedName("sections")
        private Sections sections;

        public String getRepository() {
            return repository;
        }

        public String getReportDate() {
            return reportDate;
        }

        public String getTimeRange() {
            return timeRange;
        }

        public Stats getStats() {
            return stats;
        }

        public String getSummaryText() {
            return summaryText;
        }

        public List<String> getTodoList() {
            return todoList;
        }

        public Details getDetails() {
            return details;
        }

        public ReportSummary getSummary() {
            return summary;
        }

        public Sections getSections() {
            return sections;
        }
    }

    public static class Stats {
        @SerializedName("pr_count")
        private int prCount;
        
        @SerializedName("commit_count")
        private int commitCount;

        public int getPrCount() {
            return prCount;
        }

        public int getCommitCount() {
            return commitCount;
        }
    }

    public static class Details {
        @SerializedName("top_prs")
        private List<PullRequest> topPrs;
        
        @SerializedName("top_commits")
        private List<Commit> topCommits;

        public List<PullRequest> getTopPrs() {
            return topPrs;
        }

        public List<Commit> getTopCommits() {
            return topCommits;
        }
    }

    public static class PullRequest {
        @SerializedName("number")
        private int number;
        
        @SerializedName("title")
        private String title;
        
        @SerializedName("user")
        private String user;
        
        @SerializedName("files_count")
        private int filesCount;

        public int getNumber() {
            return number;
        }

        public String getTitle() {
            return title;
        }

        public String getUser() {
            return user;
        }

        public int getFilesCount() {
            return filesCount;
        }
    }

    public static class Commit {
        @SerializedName("sha")
        private String sha;
        
        @SerializedName("author")
        private String author;
        
        @SerializedName("message")
        private String message;

        public String getSha() {
            return sha;
        }

        public String getAuthor() {
            return author;
        }

        public String getMessage() {
            return message;
        }
    }

    public static class ReportSummary {
        @SerializedName("unresolved_count")
        private int unresolvedCount;

        @SerializedName("high_risk_count")
        private int highRiskCount;

        @SerializedName("overdue_count")
        private int overdueCount;

        @SerializedName("key_conclusion")
        private String keyConclusion;

        public int getUnresolvedCount() {
            return unresolvedCount;
        }

        public int getHighRiskCount() {
            return highRiskCount;
        }

        public int getOverdueCount() {
            return overdueCount;
        }

        public String getKeyConclusion() {
            return keyConclusion;
        }
    }

    public static class Sections {
        @SerializedName("key_risk_summary")
        private KeyRiskSummary keyRiskSummary;

        @SerializedName("handover_records")
        private HandoverRecords handoverRecords;

        public KeyRiskSummary getKeyRiskSummary() {
            return keyRiskSummary;
        }

        public HandoverRecords getHandoverRecords() {
            return handoverRecords;
        }
    }

    public static class KeyRiskSummary {
        @SerializedName("text")
        private String text;

        @SerializedName("high_priority_items")
        private List<String> highPriorityItems;

        public String getText() {
            return text;
        }

        public List<String> getHighPriorityItems() {
            return highPriorityItems;
        }
    }

    public static class HandoverRecords {
        @SerializedName("top_prs")
        private List<PullRequest> topPrs;

        @SerializedName("top_commits")
        private List<Commit> topCommits;

        public List<PullRequest> getTopPrs() {
            return topPrs;
        }

        public List<Commit> getTopCommits() {
            return topCommits;
        }
    }
}
