package hik.common.yyrj.uicommon.widget

import android.animation.TypeEvaluator
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.PointF
import android.util.AttributeSet
import android.util.Size
import android.view.Gravity
import android.view.MotionEvent
import android.view.TextureView
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator

/** Floating visible-light preview widget recovered from the official Viewer 2.6.0 DEX. */
class FloatTextureView constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : TextureView(context, attrs, defStyleAttr) {
    private var lastRawX = 0f
    private var lastRawY = 0f
    private var parentWidth = 0
    private var parentHeight = 0
    private var onGravityChangedListener: ((Int) -> Unit)? = null

    constructor(context: Context, attrs: AttributeSet?) : this(context, attrs, 0)

    fun d(gravity: Int, animate: Boolean = false) {
        updateParentBounds()
        val (targetX, targetY) = officialFloatTexturePosition(
            gravity = gravity,
            availableWidth = parentWidth,
            availableHeight = parentHeight,
            childWidth = width,
            childHeight = height,
        )
        moveTo(targetX, targetY, animate)
    }

    fun f(gravity: Int, animate: Boolean, parentSize: Size, size: Size) {
        updateParentBounds()
        val (targetX, targetY) = officialFloatTexturePosition(
            gravity = gravity,
            availableWidth = parentSize.width,
            availableHeight = parentSize.height,
            childWidth = size.width,
            childHeight = size.height,
        )
        moveTo(targetX, targetY, animate)
    }

    fun getOnGravityChangedListener(): ((Int) -> Unit)? = onGravityChangedListener

    fun setOnGravityChangedListener(listener: ((Int) -> Unit)?) {
        onGravityChangedListener = listener
    }

    override fun onTouchEvent(event: MotionEvent?): Boolean {
        val rawX = event?.rawX ?: 0f
        val rawY = event?.rawY ?: 0f
        return when (event?.action) {
            MotionEvent.ACTION_DOWN -> {
                lastRawX = rawX
                lastRawY = rawY
                updateParentBounds()
                true
            }

            MotionEvent.ACTION_MOVE -> {
                moveBy(rawX - lastRawX, rawY - lastRawY)
                lastRawX = rawX
                lastRawY = rawY
                true
            }

            MotionEvent.ACTION_UP -> {
                val gravity = currentGravity()
                d(gravity, true)
                onGravityChangedListener?.invoke(gravity)
                true
            }

            else -> super.onTouchEvent(event)
        }
    }

    private fun currentGravity(): Int {
        val horizontal = if (x + width / 2f < parentWidth / 2f) Gravity.START else Gravity.END
        val vertical = if (y + height / 2f < parentHeight / 2f) Gravity.TOP else Gravity.BOTTOM
        return horizontal or vertical
    }

    private fun moveBy(deltaX: Float, deltaY: Float) {
        var targetX = x + deltaX
        var targetY = y + deltaY
        if (targetX < 0f) targetX = 0f
        val maxX = (parentWidth - width).toFloat()
        if (targetX > maxX) targetX = maxX
        if (targetY < 0f) targetY = 0f
        val maxY = (parentHeight - height).toFloat()
        if (targetY > maxY) targetY = maxY
        x = targetX
        y = targetY
    }

    private fun updateParentBounds() {
        val parentView = parent as ViewGroup
        parentWidth = parentView.width
        parentHeight = parentView.height
    }

    private fun moveTo(targetX: Float, targetY: Float, animate: Boolean) {
        if (!animate) {
            x = targetX
            y = targetY
            return
        }
        ValueAnimator.ofObject(
            TypeEvaluator<PointF> { fraction, start, end ->
                PointF(
                    start.x + (end.x - start.x) * fraction,
                    start.y + (end.y - start.y) * fraction,
                )
            },
            PointF(x, y),
            PointF(targetX, targetY),
        ).apply {
            interpolator = AccelerateDecelerateInterpolator()
            duration = 300L
            addUpdateListener { animator ->
                val point = animator.animatedValue as PointF
                x = point.x
                y = point.y
            }
            start()
        }
    }

}

internal fun officialFloatTexturePosition(
    gravity: Int,
    availableWidth: Int,
    availableHeight: Int,
    childWidth: Int,
    childHeight: Int,
): Pair<Float, Float> = when (gravity) {
    Gravity.START or Gravity.TOP -> 0f to 0f
    Gravity.END or Gravity.TOP -> (availableWidth - childWidth).toFloat() to 0f
    Gravity.START or Gravity.BOTTOM -> 0f to (availableHeight - childHeight).toFloat()
    Gravity.END or Gravity.BOTTOM ->
        (availableWidth - childWidth).toFloat() to (availableHeight - childHeight).toFloat()
    else -> 0f to 0f
}
