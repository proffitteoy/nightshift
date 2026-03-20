package com.example.myapplication3.ui.home

import android.content.Context
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PointF
import android.graphics.Shader
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat
import kotlin.math.max
import kotlin.math.min

class TrendChartView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var data: List<Int> = emptyList()
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val fillPath = Path()
    private val linePath = Path()
    private var color: Int = 0

    init {
        fillPaint.style = Paint.Style.FILL
        linePaint.style = Paint.Style.STROKE
        linePaint.strokeWidth = 6f
        linePaint.strokeCap = Paint.Cap.ROUND
        linePaint.strokeJoin = Paint.Join.ROUND
    }

    fun setData(newData: List<Int>, colorResId: Int) {
        this.data = newData
        this.color = ContextCompat.getColor(context, colorResId)
        linePaint.color = color
        updateGradient()
        invalidate()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        updateGradient()
    }

    private fun updateGradient() {
        if (width > 0 && height > 0 && color != 0) {
            fillPaint.shader = LinearGradient(
                0f, 0f, 0f, height.toFloat(),
                color, 0x00FFFFFF and color,
                Shader.TileMode.CLAMP
            )
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        // 如果数据全相同或不足，补点模拟数据以展示效果（或者处理空数据）
        val values = if (data.size < 2) listOf(1, 3, 2, 5, 4, 6, 4) else data

        if (width == 0 || height == 0) return

        val maxValue = values.maxOrNull()?.toFloat() ?: 1f
        val minValue = values.minOrNull()?.toFloat() ?: 0f

        // 计算差值，如果差值太小（比如全相等），手动给一点 buffer 避免除以 0
        val diff = max(maxValue - minValue, 1f)
        
        val stepX = width.toFloat() / (values.size - 1)
        val points = values.mapIndexed { index, value ->
            val x = index * stepX
            // 关键：基于差值缩放，让起伏更明显，并留出上下 20% 的边距
            val normalized = (value - minValue) / diff
            val y = height - (normalized * (height - 40)) - 20
            PointF(x, y)
        }

        linePath.reset()
        fillPath.reset()

        // 使用贝塞尔曲线实现平滑
        linePath.moveTo(points[0].x, points[0].y)
        fillPath.moveTo(points[0].x, height.toFloat())
        fillPath.lineTo(points[0].x, points[0].y)

        for (i in 0 until points.size - 1) {
            val p1 = points[i]
            val p2 = points[i + 1]
            val controlX = (p1.x + p2.x) / 2
            
            linePath.cubicTo(controlX, p1.y, controlX, p2.y, p2.x, p2.y)
            fillPath.cubicTo(controlX, p1.y, controlX, p2.y, p2.x, p2.y)
        }

        fillPath.lineTo(width.toFloat(), height.toFloat())
        fillPath.close()

        // 1. 绘制渐变填充
        fillPaint.alpha = 150
        canvas.drawPath(fillPath, fillPaint)

        // 2. 绘制顶部加粗平滑线
        canvas.drawPath(linePath, linePaint)
    }
}
