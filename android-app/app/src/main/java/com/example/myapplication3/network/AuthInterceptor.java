package com.example.myapplication3.network;

import android.content.Context;

import com.example.myapplication3.auth.SessionStore;

import java.io.IOException;

import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

public class AuthInterceptor implements Interceptor {
    private final Context appContext;

    public AuthInterceptor(Context context) {
        this.appContext = context.getApplicationContext();
    }

    @Override
    public Response intercept(Chain chain) throws IOException {
        Request original = chain.request();
        Request.Builder builder = original.newBuilder();

        String token = SessionStore.getAccessToken(appContext);
        if (token != null && !token.trim().isEmpty() && original.header("Authorization") == null) {
            builder.header("Authorization", "Bearer " + token);
        }

        Response response = chain.proceed(builder.build());
        if (response.code() == 401 && token != null && !token.trim().isEmpty()) {
            SessionStore.clear(appContext);
        }
        return response;
    }
}
