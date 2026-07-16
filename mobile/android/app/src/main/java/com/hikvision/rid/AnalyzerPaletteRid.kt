package com.hikvision.rid

import android.graphics.PointF

/** Exact native RID singleton boundary reached by PreviewManagerII.n0. */
class AnalyzerPaletteRid private constructor() {
    external fun calculateRidResult(measurePoints: FloatArray, width: Int, height: Int): MutableList<PointF>?
    external fun changeRIDMode(mode: Int)
    external fun initRID(width: Int, height: Int): Int

    companion object {
        @JvmField
        val a: AnalyzerPaletteRid = AnalyzerPaletteRid()

        init {
            System.loadLibrary("analyzer_rid")
        }
    }
}
