package V2

import android.view.SurfaceHolder

/** Official X2.a.b() renderer identity. */
class c(holder: SurfaceHolder) : SurfaceHolderRenderer(holder) {
    override fun a(): Boolean = false
    override fun d(picSize: android.util.Size, filePath: String): Boolean = false
    override fun e(picSize: android.util.Size): ByteArray? = null
    override fun f(picSize: android.util.Size): com.hik.library.player.d = com.hik.library.player.d(-1, null)
}
