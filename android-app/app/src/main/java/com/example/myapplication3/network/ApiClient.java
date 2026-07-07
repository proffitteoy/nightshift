package com.example.myapplication3.network;

import android.content.pm.ApplicationInfo;
import android.content.Context;
import android.os.SystemClock;
import android.util.Log;

import java.util.Map;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;
import retrofit2.converter.gson.GsonConverterFactory;

public class ApiClient {
    private static final String TAG = "ApiClient";
    public static final String BASE_URL = "http://154.219.110.18:8000/";
    private static final long BACKEND_WARMUP_INTERVAL_MS = 15_000L;
    private static Context appContext = null;
    private static Retrofit retrofit = null;
    private static ApiService apiService = null;
    private static volatile long lastWarmupAtMs = 0L;

    public static synchronized void initialize(Context context) {
        if (appContext == null) {
            appContext = context.getApplicationContext();
        }
    }

    public static String getShowcaseAtlasUrl() {
        return BASE_URL + "showcase/atlas/";
    }

    public static ApiService getApiService() {
        if (appContext == null) {
            throw new IllegalStateException("ApiClient.initialize(context) must be called before getApiService()");
        }
        if (apiService == null) {
            retrofit = createRetrofit();
            apiService = retrofit.create(ApiService.class);
        }
        return apiService;
    }

    public static void warmUpBackend() {
        if (appContext == null) {
            return;
        }
        long now = SystemClock.elapsedRealtime();
        if (now - lastWarmupAtMs < BACKEND_WARMUP_INTERVAL_MS) {
            return;
        }
        lastWarmupAtMs = now;
        getApiService().getHealth().enqueue(new Callback<Map<String, Object>>() {
            @Override
            public void onResponse(Call<Map<String, Object>> call, Response<Map<String, Object>> response) {
                if (!response.isSuccessful()) {
                    Log.w(TAG, "Backend warmup returned HTTP " + response.code());
                }
            }

            @Override
            public void onFailure(Call<Map<String, Object>> call, Throwable t) {
                Log.w(TAG, "Backend warmup failed: " + t.getMessage());
            }
        });
    }

    private static Retrofit createRetrofit() {
        boolean debugLoggingEnabled =
                (appContext.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        HttpLoggingInterceptor loggingInterceptor = new HttpLoggingInterceptor();
        loggingInterceptor.setLevel(
                debugLoggingEnabled ? HttpLoggingInterceptor.Level.BASIC : HttpLoggingInterceptor.Level.NONE
        );

        OkHttpClient client = new OkHttpClient.Builder()
                .addInterceptor(new AuthInterceptor(appContext))
                .addInterceptor(loggingInterceptor)
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(180, TimeUnit.SECONDS)
                .writeTimeout(60, TimeUnit.SECONDS)
                .build();

        return new Retrofit.Builder()
                .baseUrl(BASE_URL)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create())
                .build();
    }
}
