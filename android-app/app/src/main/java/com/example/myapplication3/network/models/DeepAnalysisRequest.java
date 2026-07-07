package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class DeepAnalysisRequest {
    @SerializedName("user_input")
    private String userInput;

    public DeepAnalysisRequest(String userInput) {
        this.userInput = userInput;
    }

    public String getUserInput() {
        return userInput;
    }
}
