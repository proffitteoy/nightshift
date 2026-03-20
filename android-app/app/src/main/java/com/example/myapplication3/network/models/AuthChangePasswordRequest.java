package com.example.myapplication3.network.models;

public class AuthChangePasswordRequest {
    private final String current_password;
    private final String new_password;

    public AuthChangePasswordRequest(String currentPassword, String newPassword) {
        this.current_password = currentPassword;
        this.new_password = newPassword;
    }
}
