package kr.auto.titration.mobile.thermal.officialdex.radiometric;

/** Fail-closed boundary for the exact official F2 radiometric bridge. */
public final class OfficialF2RadiometricException extends Exception {
    public OfficialF2RadiometricException(String message) {
        super(message);
    }

    public OfficialF2RadiometricException(String message, Throwable cause) {
        super(message, cause);
    }
}
