package buzz.walnutnest.bridge;

import android.app.*;
import android.content.Intent;
import android.os.IBinder;

public final class BridgeService extends Service {
    private BridgeHttpServer server;
    @Override public void onCreate() { super.onCreate(); BridgeToken.getOrCreate(this); server = new BridgeHttpServer(this); server.start(); }
    @Override public int onStartCommand(Intent intent, int flags, int startId) { return START_STICKY; }
    @Override public void onDestroy() { if (server != null) server.stop(); super.onDestroy(); }
    @Override public IBinder onBind(Intent intent) { return null; }
}
