package V2;

import android.content.res.AssetManager;
import java.io.IOException;
import java.io.InputStream;

final class AssetOpenBridge {
    private AssetOpenBridge() { }

    interface AssetOpener {
        InputStream open(String path) throws IOException;
    }

    static InputStream open(final AssetManager assets, String path) {
        return open(new AssetOpener() {
            @Override public InputStream open(String assetPath) throws IOException {
                return assets.open(assetPath);
            }
        }, path);
    }

    static InputStream open(AssetOpener opener, String path) {
        try {
            return opener.open(path);
        } catch (IOException exception) {
            return throwUnchecked(exception);
        }
    }

    @SuppressWarnings("unchecked")
    private static <T, E extends Throwable> T throwUnchecked(Throwable throwable) throws E {
        throw (E) throwable;
    }
}
