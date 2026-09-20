package buzz.walnutnest.bridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import org.json.JSONObject;

public final class GadgetbridgeReceiver extends BroadcastReceiver {
    private static volatile JSONObject lastEvent;
    private static volatile long eventCount;
    @Override public void onReceive(Context context, Intent intent) {
        JSONObject event = new JSONObject();
        try {
            event.put("action", intent == null ? "" : String.valueOf(intent.getAction()));
            event.put("received_at_ms", System.currentTimeMillis());
            if (intent != null && intent.getExtras() != null) {
                JSONObject extras = new JSONObject();
                for (String key : intent.getExtras().keySet()) extras.put(key, String.valueOf(intent.getExtras().get(key)));
                event.put("extras", extras);
            }
        } catch (Exception ignored) {}
        lastEvent = event; eventCount++;
    }
    static JSONObject lastEvent() {
        JSONObject out = new JSONObject();
        try { out.put("count", eventCount); out.put("event", lastEvent == null ? JSONObject.NULL : lastEvent); } catch (Exception ignored) {}
        return out;
    }
}
