package com.example.myapplication3.ui

import android.text.Spanned
import android.text.SpannedString
import androidx.core.text.HtmlCompat

object MarkdownRenderer {
    fun toSpanned(markdown: String): Spanned {
        val normalized = markdown.replace("\r\n", "\n").trim()
        if (normalized.isBlank()) {
            return SpannedString("")
        }

        return HtmlCompat.fromHtml(buildMarkdownHtml(normalized), HtmlCompat.FROM_HTML_MODE_LEGACY)
    }

    private fun buildMarkdownHtml(markdown: String): String {
        val lines = markdown.split("\n")
        val html = StringBuilder()
        var inUl = false
        var inOl = false
        var inCodeBlock = false
        var inBlockquote = false

        fun closeLists() {
            if (inUl) {
                html.append("</ul>")
                inUl = false
            }
            if (inOl) {
                html.append("</ol>")
                inOl = false
            }
        }

        fun closeBlockquote() {
            if (inBlockquote) {
                html.append("</blockquote>")
                inBlockquote = false
            }
        }

        for (rawLine in lines) {
            val line = rawLine.trimEnd()
            val trimmed = line.trim()

            if (trimmed.startsWith("```")) {
                closeLists()
                closeBlockquote()
                if (inCodeBlock) {
                    html.append("</code></pre>")
                } else {
                    html.append("<pre><code>")
                }
                inCodeBlock = !inCodeBlock
                continue
            }

            if (inCodeBlock) {
                html.append(escapeHtml(rawLine)).append("\n")
                continue
            }

            if (trimmed.isEmpty()) {
                closeLists()
                closeBlockquote()
                html.append("<br>")
                continue
            }

            val headingMatch = Regex("^(#{1,6})\\s+(.*)$").matchEntire(trimmed)
            if (headingMatch != null) {
                closeLists()
                closeBlockquote()
                val level = headingMatch.groupValues[1].length
                html.append("<h").append(level).append(">")
                html.append(renderInlineMarkdown(headingMatch.groupValues[2]))
                html.append("</h").append(level).append(">")
                continue
            }

            if (trimmed.startsWith("> ")) {
                closeLists()
                if (!inBlockquote) {
                    html.append("<blockquote>")
                    inBlockquote = true
                }
                html.append(renderInlineMarkdown(trimmed.removePrefix("> ").trim())).append("<br>")
                continue
            }

            val bulletMatch = Regex("^[*+-]\\s+(.*)$").matchEntire(trimmed)
            if (bulletMatch != null) {
                closeBlockquote()
                if (inOl) {
                    html.append("</ol>")
                    inOl = false
                }
                if (!inUl) {
                    html.append("<ul>")
                    inUl = true
                }
                html.append("<li>")
                html.append(renderInlineMarkdown(bulletMatch.groupValues[1]))
                html.append("</li>")
                continue
            }

            val orderedMatch = Regex("^\\d+[.)]\\s+(.*)$").matchEntire(trimmed)
            if (orderedMatch != null) {
                closeBlockquote()
                if (inUl) {
                    html.append("</ul>")
                    inUl = false
                }
                if (!inOl) {
                    html.append("<ol>")
                    inOl = true
                }
                html.append("<li>")
                html.append(renderInlineMarkdown(orderedMatch.groupValues[1]))
                html.append("</li>")
                continue
            }

            closeLists()
            closeBlockquote()
            html.append("<p>").append(renderInlineMarkdown(trimmed)).append("</p>")
        }

        closeLists()
        closeBlockquote()
        if (inCodeBlock) {
            html.append("</code></pre>")
        }

        return html.toString()
    }

    private fun renderInlineMarkdown(text: String): String {
        var value = escapeHtml(text)

        value = Regex("`([^`]+)`").replace(value) { match ->
            "<code>${match.groupValues[1]}</code>"
        }

        value = Regex("\\*\\*(.+?)\\*\\*").replace(value) { match ->
            "<b>${match.groupValues[1]}</b>"
        }

        value = Regex("(?<!\\*)\\*(?!\\s)(.+?)(?<!\\s)\\*(?!\\*)").replace(value) { match ->
            "<i>${match.groupValues[1]}</i>"
        }

        value = Regex("\\[([^\\]]+)]\\(([^)\\s]+)\\)").replace(value) { match ->
            val label = match.groupValues[1]
            val href = match.groupValues[2]
            "<a href=\"$href\">$label</a>"
        }

        return value.replace("\n", "<br>")
    }

    private fun escapeHtml(text: String): String {
        return text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\"", "&quot;")
            .replace("'", "&#39;")
    }
}
