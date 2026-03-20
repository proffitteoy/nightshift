package com.example.myapplication3.ui

import android.content.Context

object CurrentRepoStore {
    private const val PREFS_NAME = "nightshift_current_repo"
    private const val KEY_REPO_URL = "repo_url"

    fun getSelectedRepoUrl(context: Context): String? {
        val value = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_REPO_URL, null)
            ?.trim()
            .orEmpty()
        return value.ifBlank { null }
    }

    fun setSelectedRepoUrl(context: Context, repoUrl: String) {
        val normalized = repoUrl.trim()
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_REPO_URL, normalized)
            .apply()
    }

    fun clearSelectedRepoUrl(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_REPO_URL)
            .apply()
    }
}
