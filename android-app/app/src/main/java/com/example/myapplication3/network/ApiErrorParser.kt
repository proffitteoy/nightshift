package com.example.myapplication3.network

import org.json.JSONArray
import org.json.JSONObject
import retrofit2.Response

object ApiErrorParser {
    fun parse(response: Response<*>, fallback: String): String {
        val suffix = "HTTP ${response.code()}"
        val body = runCatching { response.errorBody()?.string() }.getOrNull().orEmpty()
        if (body.isBlank()) {
            return "$fallback ($suffix)"
        }

        return runCatching {
            val json = JSONObject(body)
            when {
                json.has("error") -> {
                    json.optJSONObject("error")?.optString("message").orEmpty().ifBlank { "$fallback ($suffix)" }
                }
                json.has("detail") && json.opt("detail") is JSONObject -> {
                    json.optJSONObject("detail")?.optString("message").orEmpty().ifBlank { "$fallback ($suffix)" }
                }
                json.has("detail") && json.opt("detail") is JSONArray -> {
                    val details = json.optJSONArray("detail")
                    val firstMessage = buildList {
                        if (details != null) {
                            for (index in 0 until details.length()) {
                                val item = details.opt(index)
                                when (item) {
                                    is JSONObject -> {
                                        val message = item.optString("msg").ifBlank {
                                            item.optString("message")
                                        }.trim()
                                        if (message.isNotEmpty()) {
                                            add(message)
                                        }
                                    }
                                    else -> {
                                        val message = item?.toString()?.trim().orEmpty()
                                        if (message.isNotEmpty()) {
                                            add(message)
                                        }
                                    }
                                }
                            }
                        }
                    }.firstOrNull()
                    firstMessage?.ifBlank { "$fallback ($suffix)" } ?: "$fallback ($suffix)"
                }
                json.has("detail") -> json.optString("detail").ifBlank { "$fallback ($suffix)" }
                json.has("message") -> json.optString("message").ifBlank { "$fallback ($suffix)" }
                else -> "$fallback ($suffix)"
            }
        }.getOrElse {
            "$fallback ($suffix)"
        }
    }
}
