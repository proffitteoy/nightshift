package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class RepoSyncSummary {
    @SerializedName("added_count")
    private int addedCount;

    @SerializedName("skipped_existing_count")
    private int skippedExistingCount;

    @SerializedName("public_repo_count")
    private int publicRepoCount;

    @SerializedName("private_repo_count")
    private int privateRepoCount;

    @SerializedName("message")
    private String message;

    public int getAddedCount() {
        return addedCount;
    }

    public int getSkippedExistingCount() {
        return skippedExistingCount;
    }

    public int getPublicRepoCount() {
        return publicRepoCount;
    }

    public int getPrivateRepoCount() {
        return privateRepoCount;
    }

    public String getMessage() {
        return message;
    }
}
