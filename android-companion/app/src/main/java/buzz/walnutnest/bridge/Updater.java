package buzz.walnutnest.bridge;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.provider.Settings;
import androidx.core.content.FileProvider;
import org.json.JSONObject;
import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

final class Updater {
    private static final String META_URL = "https://github.com/elowen1221/termux-mcp/releases/download/android-companion-latest/update.json";
    private Updater(){}

    interface Callback {
        void onStatus(String message);
        void onReady(String versionName, File apk);
        void onError(String message);
    }

    static void checkAndDownload(Activity activity, Callback callback) {
        new Thread(() -> {
            try {
                callback.onStatus("Checking for updates…");
                JSONObject meta = new JSONObject(readText(META_URL));
                long latestCode = meta.getLong("version_code");
                String latestName = meta.getString("version_name");
                String apkUrl = meta.getString("apk_url");
                String expectedSha = meta.getString("sha256").toLowerCase(Locale.ROOT);

                PackageInfo info = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0);
                long currentCode = android.os.Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
                if (latestCode <= currentCode) {
                    callback.onStatus("Already up to date (" + info.versionName + ")");
                    return;
                }

                callback.onStatus("Downloading " + latestName + "…");
                File dir = new File(activity.getCacheDir(), "updates");
                if (!dir.exists() && !dir.mkdirs()) throw new IllegalStateException("cannot create update cache");
                File apk = new File(dir, "walnut-android-bridge-" + latestName + ".apk");
                download(apkUrl, apk);
                String actualSha = sha256(apk);
                if (!expectedSha.equals(actualSha)) {
                    apk.delete();
                    throw new SecurityException("update checksum mismatch");
                }
                callback.onReady(latestName, apk);
            } catch (Throwable t) {
                callback.onError(t.getClass().getSimpleName() + ": " + String.valueOf(t.getMessage()));
            }
        }).start();
    }

    static void install(Activity activity, File apk) {
        if (android.os.Build.VERSION.SDK_INT >= 26 && !activity.getPackageManager().canRequestPackageInstalls()) {
            Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName()));
            activity.startActivity(settings);
            return;
        }
        Uri uri = FileProvider.getUriForFile(activity, activity.getPackageName() + ".files", apk);
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(uri, "application/vnd.android.package-archive");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.startActivity(intent);
    }

    private static String readText(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(8000); c.setReadTimeout(8000); c.setInstanceFollowRedirects(true);
        try (InputStream in = new BufferedInputStream(c.getInputStream())) {
            byte[] bytes = in.readAllBytes();
            return new String(bytes, StandardCharsets.UTF_8);
        } finally { c.disconnect(); }
    }

    private static void download(String url, File target) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(10000); c.setReadTimeout(20000); c.setInstanceFollowRedirects(true);
        try (InputStream in = new BufferedInputStream(c.getInputStream()); FileOutputStream out = new FileOutputStream(target)) {
            byte[] buf = new byte[8192]; int n;
            while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
        } finally { c.disconnect(); }
    }

    private static String sha256(File file) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new BufferedInputStream(new java.io.FileInputStream(file))) {
            byte[] buf = new byte[8192]; int n;
            while ((n = in.read(buf)) != -1) md.update(buf, 0, n);
        }
        StringBuilder sb = new StringBuilder();
        for (byte b : md.digest()) sb.append(String.format(Locale.ROOT, "%02x", b));
        return sb.toString();
    }
}
