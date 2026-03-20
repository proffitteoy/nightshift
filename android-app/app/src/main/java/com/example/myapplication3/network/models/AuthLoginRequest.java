package com.example.myapplication3.network.models;

public class AuthLoginRequest {
    private final String email;
    private final String password;

    public AuthLoginRequest(String email, String password) {
        this.email = email;
        this.password = password;
    }
}
