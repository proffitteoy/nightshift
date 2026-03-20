package com.example.myapplication3.database;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class DatabaseDownloader {
    private static final String TAG = "DatabaseDownloader";
    private static final ExecutorService executor = Executors.newSingleThreadExecutor();
    private static final Handler handler = new Handler(Looper.getMainLooper());
    
    public interface DownloadListener {
        void onDownloadSuccess(File downloadedFile);
        void onDownloadFailed(String error);
        void onProgress(int progress);
    }
    
    public static void downloadDatabase(Context context, String downloadUrl, 
                                        String databaseName, DownloadListener listener) {
        executor.execute(() -> {
            File result = downloadFile(context, downloadUrl, databaseName, listener);
            handler.post(() -> {
                if (result != null && result.exists()) {
                    if (listener != null) {
                        listener.onDownloadSuccess(result);
                    }
                } else {
                    if (listener != null) {
                        listener.onDownloadFailed("Unknown error");
                    }
                }
            });
        });
    }
    
    private static File downloadFile(Context context, String downloadUrl, String databaseName, DownloadListener listener) {
        HttpURLConnection connection = null;
        InputStream inputStream = null;
        FileOutputStream outputStream = null;
        
        try {
            URL url = new URL(downloadUrl);
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(15000);
            // 禁用缓存，确保每次都下载最新的文件
            connection.setUseCaches(false);
            connection.setRequestProperty("Cache-Control", "no-cache, no-store, must-revalidate");
            connection.setRequestProperty("Pragma", "no-cache");
            connection.setRequestProperty("Expires", "0");
            connection.connect();
            
            int responseCode = connection.getResponseCode();
            if (responseCode != HttpURLConnection.HTTP_OK) {
                Log.e(TAG, "HTTP error: " + responseCode);
                return null;
            }
            
            int fileSize = connection.getContentLength();
            Log.i(TAG, "Downloading file: " + downloadUrl);
            Log.i(TAG, "File size: " + fileSize + " bytes");
            
            inputStream = connection.getInputStream();
            
            File tempFile = new File(context.getCacheDir(), databaseName + ".temp");
            Log.i(TAG, "Saving to temp file: " + tempFile.getAbsolutePath());
            
            outputStream = new FileOutputStream(tempFile);
            
            byte[] buffer = new byte[8192];
            int bytesRead;
            int totalBytesRead = 0;
            
            while ((bytesRead = inputStream.read(buffer)) != -1) {
                outputStream.write(buffer, 0, bytesRead);
                totalBytesRead += bytesRead;
                
                if (fileSize > 0) {
                    int progress = (int) ((totalBytesRead * 100) / fileSize);
                    final int finalProgress = progress;
                    handler.post(() -> {
                        if (listener != null) {
                            listener.onProgress(finalProgress);
                        }
                    });
                }
            }
            
            outputStream.flush();
            Log.i(TAG, "Download completed, temp file size: " + tempFile.length());
            return tempFile;
            
        } catch (Exception e) {
            Log.e(TAG, "Download failed", e);
            return null;
        } finally {
            try {
                if (inputStream != null) inputStream.close();
                if (outputStream != null) outputStream.close();
                if (connection != null) connection.disconnect();
            } catch (IOException e) {
                Log.e(TAG, "Error closing streams", e);
            }
        }
    }
}
