package com.example.myapplication3.notifications

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class NotificationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        try {
            if (intent.action != NotificationScheduler.ACTION_SUBSCRIPTION_REMINDER) {
                Log.w(TAG, "ignored unexpected notification action")
                return
            }

            val id = intent.getIntExtra(EXTRA_SUBSCRIPTION_ID, 0)
            val title = intent.getStringExtra(EXTRA_TITLE)?.trim()?.take(80).orEmpty()
                .ifBlank { "NightShift" }
            val message = intent.getStringExtra(EXTRA_MESSAGE)?.trim()?.take(180).orEmpty()
                .ifBlank { "NightShift subscription update" }
            val hour = intent.getIntExtra(EXTRA_HOUR, -1)
            val minute = intent.getIntExtra(EXTRA_MINUTE, -1)

            if (id > 0) {
                NotificationScheduler.showNotificationNow(context, id, title, message)
            }

            if (id > 0 && hour in 0..23 && minute in 0..59) {
                NotificationScheduler.scheduleDailyNotification(context, id, hour, minute, title, message)
            }
        } catch (throwable: Throwable) {
            Log.w(TAG, "notification receiver failed", throwable)
        }
    }

    companion object {
        private const val TAG = "NotificationReceiver"
        const val EXTRA_SUBSCRIPTION_ID = "extra_subscription_id"
        const val EXTRA_TITLE = "extra_title"
        const val EXTRA_MESSAGE = "extra_message"
        const val EXTRA_HOUR = "extra_hour"
        const val EXTRA_MINUTE = "extra_minute"
    }
}
