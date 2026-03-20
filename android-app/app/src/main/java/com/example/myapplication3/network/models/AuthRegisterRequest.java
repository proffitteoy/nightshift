package com.example.myapplication3.network.models;

import com.google.gson.annotations.SerializedName;

public class AuthRegisterRequest {
    private final String email;
    private final String password;

    @SerializedName("display_name")
    private final String displayName;

    public AuthRegisterRequest(String email, String password, String displayName) {
        this.email = email;
        this.password = password;
        this.displayName = displayName;
    }
}
