package buzz.walnutnest.bridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import org.json.JSONObject;

public final class GadgetbridgeReceiver extends BroadcastReceiver {
    private static volatile JSONObject lastEvent;
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
        lastEvent = event;
    }
    static JSONObject lastEvent() {
        JSONObject event = lastEvent;
        return event == null ? new JSONObject() : event;
    }
}
