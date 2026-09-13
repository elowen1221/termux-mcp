package buzz.walnutnest.bridge;

import android.content.Context;
import android.content.SharedPreferences;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

final class BridgeToken {
    private static final String PREFS = "bridge_auth";
    private static final String KEY = "token";
    private BridgeToken() {}

    static String getOrCreate(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String existing = prefs.getString(KEY, null);
        if (existing != null && !existing.isEmpty()) return existing;
        byte[] bytes = new byte[32]; new SecureRandom().nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        prefs.edit().putString(KEY, token).apply();
        return token;
    }

    static boolean matches(Context context, String candidate) {
        if (candidate == null) return false;
        byte[] a = getOrCreate(context).getBytes(java.nio.charset.StandardCharsets.UTF_8);
        byte[] b = candidate.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        return MessageDigest.isEqual(a, b);
    }
}
