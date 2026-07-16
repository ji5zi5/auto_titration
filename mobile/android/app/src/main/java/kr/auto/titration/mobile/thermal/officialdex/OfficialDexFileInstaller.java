package kr.auto.titration.mobile.thermal.officialdex;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.channels.ReadableByteChannel;
import java.util.ArrayList;
import java.util.List;

final class OfficialDexFileInstaller {
    private static final String INSTALL_DIR = "hikmicro_official_dex";

    private OfficialDexFileInstaller() {
    }

    static InstalledDexSet install(Context context) throws OfficialDexLoadException {
        File root = new File(context.getCodeCacheDir(), INSTALL_DIR);
        File dexDir = new File(root, "dex");
        File oatDir = new File(root, "oat");
        ensurePrivateDirectory(dexDir);
        ensurePrivateDirectory(oatDir);

        List<File> installed = new ArrayList<>();
        for (OfficialDexArtifacts.DexAsset asset : OfficialDexArtifacts.DEX_ASSETS) {
            File destination = new File(dexDir, asset.fileName);
            installOne(context, asset, destination);
            installed.add(destination);
        }
        return new InstalledDexSet(installed, oatDir);
    }

    private static void installOne(
        Context context,
        OfficialDexArtifacts.DexAsset asset,
        File destination
    ) throws OfficialDexLoadException {
        try {
            if (destination.exists()) {
                String existingHash = OfficialDexHashing.sha256(destination);
                if (OfficialDexHashing.constantTimeEquals(asset.sha256, existingHash) && !destination.canWrite()) {
                    return;
                }
                if (!destination.setWritable(true, true)) {
                    throw new OfficialDexLoadException("Cannot make stale official dex writable for replacement: " + destination);
                }
                if (!destination.delete()) {
                    throw new OfficialDexLoadException("Cannot delete stale official dex: " + destination);
                }
            }

            ensurePrivateDirectory(destination.getParentFile());

            try (InputStream input = context.getAssets().open(asset.assetPath);
                 FileOutputStream output = new FileOutputStream(destination, false);
                 ReadableByteChannel inChannel = Channels.newChannel(input);
                 FileChannel outChannel = output.getChannel()) {
                // Android 14+/target 35 dynamic-code hardening: the file is opened,
                // then made read-only before any bytes are written through the held fd.
                if (!destination.setReadOnly()) {
                    throw new OfficialDexLoadException("Cannot mark official dex read-only before write: " + destination);
                }
                long position = 0L;
                while (true) {
                    long transferred = outChannel.transferFrom(inChannel, position, 1024L * 1024L);
                    if (transferred <= 0L) {
                        break;
                    }
                    position += transferred;
                }
                outChannel.force(true);
            } catch (IOException e) {
                throw new OfficialDexLoadException("Missing or unreadable official dex asset: " + asset.assetPath, e);
            }

            String actualHash = OfficialDexHashing.sha256(destination);
            if (!OfficialDexHashing.constantTimeEquals(asset.sha256, actualHash)) {
                safeDelete(destination);
                throw new OfficialDexLoadException(
                    "Official dex hash mismatch for " + asset.assetPath + ": expected " + asset.sha256 + " got " + actualHash
                );
            }
            if (destination.canWrite() && !destination.setReadOnly()) {
                safeDelete(destination);
                throw new OfficialDexLoadException("Official dex remained writable after verified install: " + destination);
            }
        } catch (IOException e) {
            throw new OfficialDexLoadException("Cannot install official dex asset: " + asset.assetPath, e);
        }
    }

    private static void ensurePrivateDirectory(File directory) throws OfficialDexLoadException {
        if (directory == null) {
            throw new OfficialDexLoadException("Official dex directory is null");
        }
        if (!directory.exists() && !directory.mkdirs()) {
            throw new OfficialDexLoadException("Cannot create official dex directory: " + directory);
        }
        if (!directory.isDirectory()) {
            throw new OfficialDexLoadException("Official dex path is not a directory: " + directory);
        }
    }

    static void reset(Context context) {
        File root = new File(context.getCodeCacheDir(), INSTALL_DIR);
        deleteRecursively(root);
    }

    private static void deleteRecursively(File file) {
        if (file == null || !file.exists()) {
            return;
        }
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) {
                for (File child : children) {
                    deleteRecursively(child);
                }
            }
        }
        file.setWritable(true, true);
        file.delete();
    }

    private static void safeDelete(File file) {
        if (file != null) {
            file.setWritable(true, true);
            file.delete();
        }
    }

    static final class InstalledDexSet {
        final List<File> dexFiles;
        final File optimizedDirectory;

        InstalledDexSet(List<File> dexFiles, File optimizedDirectory) {
            this.dexFiles = dexFiles;
            this.optimizedDirectory = optimizedDirectory;
        }

        String dexPath() {
            StringBuilder builder = new StringBuilder();
            for (int i = 0; i < dexFiles.size(); i++) {
                if (i > 0) {
                    builder.append(File.pathSeparatorChar);
                }
                builder.append(dexFiles.get(i).getAbsolutePath());
            }
            return builder.toString();
        }
    }
}
