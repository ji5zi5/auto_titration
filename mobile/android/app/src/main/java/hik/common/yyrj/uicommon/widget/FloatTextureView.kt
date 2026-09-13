package hik.common.yyrj.uicommon.widget

import android.animation.TypeEvaluator
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.PointF
import android.util.AttributeSet
import android.util.Size
import android.view.MotionEvent
import android.view.TextureView
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator

class FloatTextureView constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : TextureView(context, attrs, defStyleAttr) {
    private var a: Float = 0f
    private var b: Float = 0f
    private var c: Int = 0
    private var d: Int = 0
    private var e: ((Int) -> Unit)? = null

    constructor(context: Context, attrs: AttributeSet?) : this(context, attrs, 0)

    @JvmName("b")
    private fun gravity(): Int {
        val horizontal = if (x + width / 2f >= c / 2f) 8388613 else 8388611
        val vertical = if (y + height / 2f >= d / 2f) 80 else 48
        return vertical or horizontal
    }

    private fun c(deltaX: Float, deltaY: Float) {
        var targetX = x + deltaX
        var targetY = y + deltaY
        if (targetX < 0f) targetX = 0f
        if (targetX > c - width) targetX = (c - width).toFloat()
        if (targetY < 0f) targetY = 0f
        if (targetY > d - height) targetY = (d - height).toFloat()
        x = targetX
        y = targetY
    }

    fun d(gravity: Int, animate: Boolean) {
        g()
        var targetX = 0f
        val targetY = when (gravity) {
            8388661 -> {
                targetX = (c - width).toFloat()
                0f
            }
            8388691 -> (d - height).toFloat()
            8388693 -> {
                targetX = (c - width).toFloat()
                (d - height).toFloat()
            }
            else -> 0f
        }
        if (animate) h(targetX, targetY) else {
            x = targetX
            y = targetY
        }
    }

    fun f(gravity: Int, animate: Boolean, parentSize: Size, size: Size) {
        g()
        var targetX = 0f
        val targetY = when (gravity) {
            8388661 -> {
                targetX = (parentSize.width - size.width).toFloat()
                0f
            }
            8388691 -> (parentSize.height - size.height).toFloat()
            8388693 -> {
                targetX = (parentSize.width - size.width).toFloat()
                (parentSize.height - size.height).toFloat()
            }
            else -> 0f
        }
        if (animate) h(targetX, targetY) else {
            x = targetX
            y = targetY
        }
    }

    fun getOnGravityChangedListener(): ((Int) -> Unit)? = e

    fun setOnGravityChangedListener(listener: ((Int) -> Unit)?) {
        e = listener
    }

    private fun g() {
        val parentView = parent as ViewGroup
        c = parentView.width
        d = parentView.height
    }

    private fun h(targetX: Float, targetY: Float) {
        val start = PointF(x, y)
        val end = PointF(targetX, targetY)
        ValueAnimator.ofObject(`FloatTextureView$b`(this), start, end).apply {
            interpolator = AccelerateDecelerateInterpolator()
            duration = 300L
            addUpdateListener(q(this@FloatTextureView))
            start()
        }
    }

    override fun onTouchEvent(event: MotionEvent?): Boolean {
        val rawX = event?.rawX ?: 0f
        val rawY = event?.rawY ?: 0f
        return when (event?.action) {
            MotionEvent.ACTION_DOWN -> {
                a = rawX
                b = rawY
                g()
                true
            }
            MotionEvent.ACTION_MOVE -> {
                c(rawX - a, rawY - b)
                a = rawX
                b = rawY
                true
            }
            MotionEvent.ACTION_UP -> {
                val targetGravity = gravity()
                d(targetGravity, true)
                e?.invoke(targetGravity)
                performClick()
                true
            }
            else -> super.onTouchEvent(event)
        }
    }

    override fun performClick(): Boolean {
        return super.performClick()
    }

    companion object {
        @JvmField
        val f: `FloatTextureView$a` = `FloatTextureView$a`()

        @JvmStatic
        fun a(view: FloatTextureView, animator: ValueAnimator) {
            i(view, animator)
        }

        @JvmStatic
        fun e(view: FloatTextureView, gravity: Int, animate: Boolean, mask: Int, unused: Any?) {
            view.d(gravity, if (mask and 2 != 0) false else animate)
        }

        private fun i(view: FloatTextureView, animator: ValueAnimator) {
            val point = animator.animatedValue as PointF
            view.x = point.x
            view.y = point.y
        }
    }
}

class `FloatTextureView$a` internal constructor()

class `FloatTextureView$b`(private val a: FloatTextureView) : TypeEvaluator<PointF> {
    fun a(fraction: Float, start: PointF, end: PointF): PointF = PointF(
        start.x + (end.x - start.x) * fraction,
        start.y + (end.y - start.y) * fraction,
    )

    override fun evaluate(fraction: Float, startValue: PointF, endValue: PointF): PointF =
        a(fraction, startValue, endValue)
}

private class q(private val a: FloatTextureView) : ValueAnimator.AnimatorUpdateListener {
    override fun onAnimationUpdate(animation: ValueAnimator) {
        FloatTextureView.a(a, animation)
    }
}
