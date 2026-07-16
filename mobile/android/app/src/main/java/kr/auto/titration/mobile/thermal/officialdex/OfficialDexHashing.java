package kr.auto.titration.mobile.thermal.officialdex;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;

public final class OfficialDexHashing {
    private OfficialDexHashing() {
    }

    public static String sha256(File file) throws IOException {
        try (InputStream input = new FileInputStream(file)) {
            return sha256(input);
        }
    }

    public static String sha256(InputStream input) throws IOException {
        MessageDigest digest = newSha256();
        byte[] buffer = new byte[64 * 1024];
        try (DigestInputStream digestInput = new DigestInputStream(input, digest)) {
            while (digestInput.read(buffer) != -1) {
                // DigestInputStream updates the digest as bytes are read.
            }
        }
        return toHex(digest.digest());
    }

    public static boolean constantTimeEquals(String expectedLowerHex, String actualLowerHex) {
        if (expectedLowerHex == null || actualLowerHex == null) {
            return false;
        }
        byte[] expected = expectedLowerHex.toLowerCase(Locale.US).getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        byte[] actual = actualLowerHex.toLowerCase(Locale.US).getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        return MessageDigest.isEqual(expected, actual);
    }

    private static MessageDigest newSha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 digest is unavailable", e);
        }
    }

    private static String toHex(byte[] bytes) {
        char[] output = new char[bytes.length * 2];
        char[] alphabet = "0123456789abcdef".toCharArray();
        for (int i = 0; i < bytes.length; i++) {
            int value = bytes[i] & 0xff;
            output[i * 2] = alphabet[value >>> 4];
            output[i * 2 + 1] = alphabet[value & 0x0f];
        }
        return new String(output);
    }
}
