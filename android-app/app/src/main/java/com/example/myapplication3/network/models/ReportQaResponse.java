package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class ReportQaResponse {
    @SerializedName("answer")
    private String answer;

    @SerializedName("source")
    private String source;

    public String getAnswer() {
        return answer;
    }

    public String getSource() {
        return source;
    }
}
