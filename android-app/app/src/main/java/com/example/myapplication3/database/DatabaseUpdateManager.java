package com.example.myapplication3.database;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Environment;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.channels.FileChannel;

public class DatabaseUpdateManager {
    private static final String TAG = "DatabaseUpdateManager";
    private static final String PREFS_NAME = "database_update_prefs";
    private static final String KEY_HOT_GIT_VERSION = "hot_git_version";
    private static final String KEY_GIT_SELF_VERSION = "git_self_version";
    
    private Context context;
    private SharedPreferences prefs;
    
    public DatabaseUpdateManager(Context context) {
        this.context = context.getApplicationContext();
        this.prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }
    
    public int getHotGitVersion() {
        return prefs.getInt(KEY_HOT_GIT_VERSION, 1);
    }
    
    public int getGitSelfVersion() {
        return prefs.getInt(KEY_GIT_SELF_VERSION, 1);
    }
    
    public void updateHotGitVersion(int version) {
        prefs.edit().putInt(KEY_HOT_GIT_VERSION, version).apply();
    }
    
    public void updateGitSelfVersion(int version) {
        prefs.edit().putInt(KEY_GIT_SELF_VERSION, version).apply();
    }
    
    public void updateDatabase(String databaseName, int newVersion, 
                               String downloadUrl, final UpdateCallback callback) {
        DatabaseDownloader.downloadDatabase(context, downloadUrl, databaseName, 
            new DatabaseDownloader.DownloadListener() {
                @Override
                public void onDownloadSuccess(File downloadedFile) {
                    boolean success = replaceDatabase(databaseName, downloadedFile);
                    if (success) {
                        if (databaseName.equals(DatabaseHelper.DATABASE_NAME)) {
                            updateHotGitVersion(newVersion);
                        } else if (databaseName.equals(GitSelfDatabaseHelper.DATABASE_NAME)) {
                            updateGitSelfVersion(newVersion);
                        }
                        callback.onUpdateSuccess();
                    } else {
                        callback.onUpdateFailed("Failed to replace database");
                    }
                }
                
                @Override
                public void onDownloadFailed(String error) {
                    callback.onUpdateFailed("Download failed: " + error);
                }
                
                @Override
                public void onProgress(int progress) {
                    callback.onProgress(progress);
                }
            });
    }
    
    private boolean replaceDatabase(String databaseName, File downloadedFile) {
        File databasesDir = context.getDatabasePath(databaseName).getParentFile();
        if (databasesDir == null || !databasesDir.exists()) {
            Log.e(TAG, "Database directory does not exist: " + databasesDir);
            return false;
        }
        
        Log.i(TAG, "Database directory: " + databasesDir.getAbsolutePath());
        Log.i(TAG, "Downloaded file: " + downloadedFile.getAbsolutePath() + ", size: " + downloadedFile.length());
        
        File oldDatabaseFile = new File(databasesDir, databaseName);
        File oldWalFile = new File(databasesDir, databaseName + "-wal");
        File oldShmFile = new File(databasesDir, databaseName + "-shm");
        
        Log.i(TAG, "Old database file: " + oldDatabaseFile.getAbsolutePath() + ", exists: " + oldDatabaseFile.exists() + ", size: " + (oldDatabaseFile.exists() ? oldDatabaseFile.length() : 0));
        
        try {
            if (oldDatabaseFile.exists()) {
                File backupFile = new File(databasesDir, databaseName + ".backup");
                Log.i(TAG, "Creating backup: " + backupFile.getAbsolutePath());
                copyFile(oldDatabaseFile, backupFile);
                Log.i(TAG, "Backup created successfully, size: " + backupFile.length());
            }
            
            Log.i(TAG, "Copying downloaded file to database location...");
            copyFile(downloadedFile, oldDatabaseFile);
            Log.i(TAG, "Copy completed, new database size: " + oldDatabaseFile.length());
            
            if (oldWalFile.exists()) {
                Log.i(TAG, "Deleting WAL file: " + oldWalFile.getAbsolutePath());
                oldWalFile.delete();
            }
            if (oldShmFile.exists()) {
                Log.i(TAG, "Deleting SHM file: " + oldShmFile.getAbsolutePath());
                oldShmFile.delete();
            }
            
            downloadedFile.delete();
            
            Log.i(TAG, "Database " + databaseName + " replaced successfully");
            return true;
            
        } catch (IOException e) {
            Log.e(TAG, "Failed to replace database", e);
            return false;
        }
    }
    
    private void copyFile(File source, File destination) throws IOException {
        FileChannel sourceChannel = null;
        FileChannel destChannel = null;
        
        try {
            sourceChannel = new FileInputStream(source).getChannel();
            destChannel = new FileOutputStream(destination).getChannel();
            destChannel.transferFrom(sourceChannel, 0, sourceChannel.size());
        } finally {
            if (sourceChannel != null) {
                sourceChannel.close();
            }
            if (destChannel != null) {
                destChannel.close();
            }
        }
    }
    
    public void checkAndUpdateDatabases(final UpdateCallback callback) {
        String hotGitUrl = DatabaseConfig.HotGit.DOWNLOAD_URL;
        String gitSelfUrl = DatabaseConfig.GitSelf.DOWNLOAD_URL;
        
        int currentHotGitVersion = getHotGitVersion();
        int currentGitSelfVersion = getGitSelfVersion();
        
        int serverHotGitVersion = DatabaseConfig.HotGit.CURRENT_VERSION;
        int serverGitSelfVersion = DatabaseConfig.GitSelf.CURRENT_VERSION;
        
        if (serverHotGitVersion > currentHotGitVersion) {
            updateDatabase(DatabaseHelper.DATABASE_NAME, serverHotGitVersion, hotGitUrl, callback);
        } else if (serverGitSelfVersion > currentGitSelfVersion) {
            updateDatabase(GitSelfDatabaseHelper.DATABASE_NAME, serverGitSelfVersion, gitSelfUrl, callback);
        } else {
            callback.onNoUpdateNeeded();
        }
    }
    
    public void forceUpdateDatabases(final UpdateCallback callback) {
        String hotGitUrl = DatabaseConfig.HotGit.DOWNLOAD_URL;
        
        // 强制更新，使用当前版本号+1，确保总是替换数据库
        int serverHotGitVersion = getHotGitVersion() + 1;
        
        // 只更新Hot_Git数据库，Git_Self数据库存储在用户手机本地，不需要从网络下载
        updateDatabase(DatabaseHelper.DATABASE_NAME, serverHotGitVersion, hotGitUrl, 
            new UpdateCallback() {
                @Override
                public void onUpdateSuccess() {
                    callback.onUpdateSuccess();
                }
                
                @Override
                public void onUpdateFailed(String error) {
                    callback.onUpdateFailed(error);
                }
                
                @Override
                public void onProgress(int progress) {
                    callback.onProgress(progress);
                }
                
                @Override
                public void onNoUpdateNeeded() {
                    // 强制更新时，即使版本号相同也应该更新
                    // 直接下载并替换数据库
                    DatabaseDownloader.downloadDatabase(context, hotGitUrl, DatabaseHelper.DATABASE_NAME, 
                        new DatabaseDownloader.DownloadListener() {
                            @Override
                            public void onDownloadSuccess(File downloadedFile) {
                                boolean success = replaceDatabase(DatabaseHelper.DATABASE_NAME, downloadedFile);
                                if (success) {
                                    updateHotGitVersion(serverHotGitVersion);
                                    callback.onUpdateSuccess();
                                } else {
                                    callback.onUpdateFailed("Failed to replace Hot_Git database");
                                }
                            }
                            
                            @Override
                            public void onDownloadFailed(String error) {
                                callback.onUpdateFailed("Download failed: " + error);
                            }
                            
                            @Override
                            public void onProgress(int progress) {
                                callback.onProgress(progress);
                            }
                        });
                }
            });
    }
    
    public interface UpdateCallback {
        void onUpdateSuccess();
        void onUpdateFailed(String error);
        void onProgress(int progress);
        void onNoUpdateNeeded();
    }
}
