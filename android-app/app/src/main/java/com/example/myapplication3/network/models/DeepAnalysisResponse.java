package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class DeepAnalysisResponse {
    @SerializedName("code")
    private int code;

    @SerializedName("message")
    private String message;

    @SerializedName("content")
    private String content;

    public int getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }

    public String getContent() {
        return content;
    }
}
