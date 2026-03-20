package com.example.myapplication3.notifications

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.example.myapplication3.R
import java.util.Calendar

object NotificationScheduler {
    const val CHANNEL_ID = "ns_subscriptions_channel"
    const val ACTION_SUBSCRIPTION_REMINDER = "com.example.myapplication3.notifications.ACTION_SUBSCRIPTION_REMINDER"
    private const val TAG = "NotificationScheduler"
    private const val MAX_TITLE_LENGTH = 80
    private const val MAX_MESSAGE_LENGTH = 180

    fun scheduleDailyNotification(
        context: Context,
        subscriptionId: Int,
        hour: Int,
        minute: Int,
        title: String,
        message: String,
    ): Boolean {
        return try {
            ensureChannel(context)
            val safeTitle = sanitizeNotificationText(title, MAX_TITLE_LENGTH)
            val safeMessage = sanitizeNotificationText(message, MAX_MESSAGE_LENGTH)

            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val intent = Intent(context, NotificationReceiver::class.java).apply {
                action = ACTION_SUBSCRIPTION_REMINDER
                setPackage(context.packageName)
                putExtra(NotificationReceiver.EXTRA_SUBSCRIPTION_ID, subscriptionId)
                putExtra(NotificationReceiver.EXTRA_TITLE, safeTitle)
                putExtra(NotificationReceiver.EXTRA_MESSAGE, safeMessage)
                putExtra(NotificationReceiver.EXTRA_HOUR, hour)
                putExtra(NotificationReceiver.EXTRA_MINUTE, minute)
            }

            val pending = PendingIntent.getBroadcast(
                context,
                subscriptionId,
                intent,
                pendingIntentFlags(),
            )

            val now = Calendar.getInstance()
            val trigger = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, hour)
                set(Calendar.MINUTE, minute)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
                if (before(now)) {
                    add(Calendar.DAY_OF_YEAR, 1)
                }
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !alarmManager.canScheduleExactAlarms()) {
                alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, trigger.timeInMillis, pending)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, trigger.timeInMillis, pending)
            } else {
                alarmManager.setExact(AlarmManager.RTC_WAKEUP, trigger.timeInMillis, pending)
            }
            true
        } catch (throwable: Throwable) {
            logFailure("schedule", subscriptionId, throwable)
            false
        }
    }

    @SuppressLint("MissingPermission")
    fun showNotificationNow(
        context: Context,
        subscriptionId: Int,
        title: String,
        message: String,
    ): Boolean {
        return try {
            if (!hasNotificationPermission(context)) {
                return false
            }
            if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
                return false
            }
            ensureChannel(context)
            val builder = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(sanitizeNotificationText(title, MAX_TITLE_LENGTH))
                .setContentText(sanitizeNotificationText(message, MAX_MESSAGE_LENGTH))
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setAutoCancel(true)

            NotificationManagerCompat.from(context).notify(subscriptionId, builder.build())
            true
        } catch (throwable: Throwable) {
            logFailure("show", subscriptionId, throwable)
            false
        }
    }

    fun cancelScheduledNotification(context: Context, subscriptionId: Int): Boolean {
        return try {
            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val intent = Intent(context, NotificationReceiver::class.java).apply {
                action = ACTION_SUBSCRIPTION_REMINDER
                setPackage(context.packageName)
            }
            val pending = PendingIntent.getBroadcast(context, subscriptionId, intent, pendingIntentFlags())
            alarmManager.cancel(pending)
            pending.cancel()
            true
        } catch (throwable: Throwable) {
            logFailure("cancel", subscriptionId, throwable)
            false
        }
    }

    private fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "订阅通知",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = "订阅定时提醒"
            }
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    private fun pendingIntentFlags(): Int {
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            flags = flags or PendingIntent.FLAG_IMMUTABLE
        }
        return flags
    }

    private fun logFailure(action: String, subscriptionId: Int, throwable: Throwable) {
        Log.w(TAG, "notification $action failed: subscriptionId=$subscriptionId", throwable)
    }

    private fun hasNotificationPermission(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return true
        }
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun sanitizeNotificationText(value: String, maxLength: Int): String {
        return value.trim()
            .replace(Regex("[\\p{Cntrl}&&[^\\n\\t]]"), "")
            .take(maxLength)
            .ifBlank { "NightShift" }
    }
}
