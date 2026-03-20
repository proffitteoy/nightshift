package com.example.myapplication3.auth;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import com.example.myapplication3.network.models.AuthTokenResponse;
import com.example.myapplication3.network.models.UserProfileResponse;
import com.google.gson.Gson;

public final class SessionStore {
    private static final String TAG = "SessionStore";
    private static final String PREFS_NAME = "nightshift_auth_session";
    private static final String KEY_ACCESS_TOKEN = "access_token";
    private static final String KEY_TOKEN_TYPE = "token_type";
    private static final String KEY_EXPIRES_AT_MS = "expires_at_ms";
    private static final String KEY_USER_JSON = "user_json";

    private static final Gson GSON = new Gson();
    private static SharedPreferences preferences;

    private SessionStore() {
    }

    public static synchronized void initialize(Context context) {
        if (preferences != null) {
            return;
        }
        Context appContext = context.getApplicationContext();
        try {
            MasterKey masterKey = new MasterKey.Builder(appContext)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build();
            preferences = EncryptedSharedPreferences.create(
                    appContext,
                    PREFS_NAME,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            );
        } catch (Throwable throwable) {
            Log.w(TAG, "encrypted session storage unavailable, fallback to SharedPreferences", throwable);
            preferences = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        }
    }

    public static boolean hasActiveSession(Context context) {
        initialize(context);
        String token = preferences.getString(KEY_ACCESS_TOKEN, "");
        if (token == null || token.trim().isEmpty()) {
            return false;
        }

        long expiresAtMs = preferences.getLong(KEY_EXPIRES_AT_MS, 0L);
        if (expiresAtMs > 0L && System.currentTimeMillis() >= expiresAtMs) {
            clear(context);
            return false;
        }
        return true;
    }

    @Nullable
    public static String getAccessToken(Context context) {
        initialize(context);
        if (!hasActiveSession(context)) {
            return null;
        }
        String token = preferences.getString(KEY_ACCESS_TOKEN, "");
        return token == null || token.trim().isEmpty() ? null : token.trim();
    }

    @Nullable
    public static UserProfileResponse getCachedUser(Context context) {
        initialize(context);
        String userJson = preferences.getString(KEY_USER_JSON, "");
        if (userJson == null || userJson.trim().isEmpty()) {
            return null;
        }
        try {
            return GSON.fromJson(userJson, UserProfileResponse.class);
        } catch (Exception ignored) {
            return null;
        }
    }

    public static void saveSession(Context context, AuthTokenResponse session) {
        initialize(context);
        long expiresInSeconds = session != null ? session.getExpiresIn() : 0L;
        long expiresAtMs = expiresInSeconds > 0L
                ? System.currentTimeMillis() + (expiresInSeconds * 1000L)
                : 0L;
        SharedPreferences.Editor editor = preferences.edit()
                .putString(KEY_ACCESS_TOKEN, session != null ? session.getAccessToken() : "")
                .putString(KEY_TOKEN_TYPE, session != null ? session.getTokenType() : "bearer")
                .putLong(KEY_EXPIRES_AT_MS, expiresAtMs);
        if (session != null && session.getUser() != null) {
            editor.putString(KEY_USER_JSON, GSON.toJson(session.getUser()));
        } else {
            editor.remove(KEY_USER_JSON);
        }
        editor.apply();
    }

    public static void saveUser(Context context, UserProfileResponse user) {
        initialize(context);
        SharedPreferences.Editor editor = preferences.edit();
        if (user == null) {
            editor.remove(KEY_USER_JSON);
        } else {
            editor.putString(KEY_USER_JSON, GSON.toJson(user));
        }
        editor.apply();
    }

    public static void clear(Context context) {
        initialize(context);
        preferences.edit().clear().apply();
    }
}
