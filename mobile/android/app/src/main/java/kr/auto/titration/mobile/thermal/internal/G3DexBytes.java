package kr.auto.titration.mobile.thermal.internal;

import android.util.Size;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.Arrays;

/** App-internal extraction support; kept outside official g3 package inventory. */
public final class G3DexBytes {
    private G3DexBytes() {}

    public static PreviewStreamInfo emptyStreamInfo() {
        return new PreviewStreamInfo(new PreviewInfoDataBean(), null);
    }

    public static byte[] concat(byte[] first, byte[] second) {
        byte[] out = Arrays.copyOf(first, first.length + second.length);
        System.arraycopy(second, 0, out, first.length, second.length);
        return out;
    }

    public static byte[] rotateRaw(byte[] raw, Size rotateSize) {
        int count = raw.length / 2;
        if (count != rotateSize.getWidth() * rotateSize.getHeight()) return new byte[0];
        short[][] input = new short[rotateSize.getWidth()][rotateSize.getHeight()];
        int index = 0;
        for (int x = 0; x < rotateSize.getWidth(); x++) {
            for (int y = 0; y < rotateSize.getHeight(); y++) {
                int byteIndex = index * 2;
                input[x][y] = (short) ((raw[byteIndex] & 0xff) | ((raw[byteIndex + 1] & 0xff) << 8));
                index++;
            }
        }
        short[][] output = d3.a.a.a(input);
        byte[] out = new byte[raw.length];
        int outIndex = 0;
        for (short[] row : output) {
            for (short value : row) {
                out[outIndex++] = (byte) (value & 0xff);
                out[outIndex++] = (byte) ((value >>> 8) & 0xff);
            }
        }
        return out;
    }
}
