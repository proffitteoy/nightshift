package com.example.myapplication3;

import android.app.Application;
import android.util.Log;

import com.example.myapplication3.auth.SessionStore;
import com.example.myapplication3.database.DatabaseHelper;
import com.example.myapplication3.database.DatabaseUpdateManager;
import com.example.myapplication3.database.GitSelfDatabaseHelper;
import com.example.myapplication3.network.ApiClient;
import com.example.myapplication3.network.models.UserProfileResponse;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class MyApplication extends Application {
    private static final String TAG = "MyApplication";
    private static MyApplication instance;
    private DatabaseUpdateManager updateManager;

    @Override
    public void onCreate() {
        super.onCreate();

        instance = this;
        runStartupStep("database manager init", () -> updateManager = new DatabaseUpdateManager(this));
        runStartupStep("session init", () -> {
            SessionStore.initialize(this);
            SessionStore.hasActiveSession(this);
        });
        runStartupStep("api init", () -> {
            ApiClient.initialize(this);
            ApiClient.warmUpBackend();
            refreshAuthSessionIfNeeded();
        });
        runStartupStep("startup database update", () -> {
            if (updateManager == null) {
                return;
            }
            if (isNetworkAvailable()) {
                checkDatabaseUpdates();
            } else {
                Log.i(TAG, "Network not available, skipping database update");
            }
        });
    }

    private boolean isNetworkAvailable() {
        try {
            android.net.ConnectivityManager connectivityManager =
                (android.net.ConnectivityManager) getSystemService(android.content.Context.CONNECTIVITY_SERVICE);
            if (connectivityManager != null) {
                android.net.NetworkCapabilities networkCapabilities =
                    connectivityManager.getNetworkCapabilities(connectivityManager.getActiveNetwork());
                return networkCapabilities != null && (
                    networkCapabilities.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) ||
                    networkCapabilities.hasTransport(android.net.NetworkCapabilities.TRANSPORT_CELLULAR) ||
                    networkCapabilities.hasTransport(android.net.NetworkCapabilities.TRANSPORT_ETHERNET)
                );
            }
        } catch (Throwable throwable) {
            Log.w(TAG, "Failed to check network availability", throwable);
        }
        return false;
    }

    private void checkDatabaseUpdates() {
        if (updateManager == null) {
            return;
        }
        new Thread(() -> {
            updateManager.forceUpdateDatabases(new DatabaseUpdateManager.UpdateCallback() {
                @Override
                public void onUpdateSuccess() {
                    Log.i(TAG, "Database updated successfully");
                    restartDatabaseHelpers();
                }

                @Override
                public void onUpdateFailed(String error) {
                    Log.e(TAG, "Database update failed: " + error);
                }

                @Override
                public void onProgress(int progress) {
                }

                @Override
                public void onNoUpdateNeeded() {
                    Log.i(TAG, "No database update needed");
                }
            });
        }).start();
    }

    private void refreshAuthSessionIfNeeded() {
        if (!SessionStore.hasActiveSession(this)) {
            return;
        }
        ApiClient.getApiService().getMe().enqueue(new Callback<UserProfileResponse>() {
            @Override
            public void onResponse(Call<UserProfileResponse> call, Response<UserProfileResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    SessionStore.saveUser(MyApplication.this, response.body());
                    return;
                }
                if (response.code() == 401) {
                    SessionStore.clear(MyApplication.this);
                }
            }

            @Override
            public void onFailure(Call<UserProfileResponse> call, Throwable t) {
                Log.w(TAG, "Auth session refresh failed: " + t.getMessage());
            }
        });
    }

    private void restartDatabaseHelpers() {
        DatabaseHelper.resetInstance();
        GitSelfDatabaseHelper.resetInstance();
    }

    public static MyApplication getInstance() {
        return instance;
    }

    private void runStartupStep(String label, Runnable action) {
        try {
            action.run();
        } catch (Throwable throwable) {
            Log.e(TAG, "Startup step failed: " + label, throwable);
        }
    }
}
