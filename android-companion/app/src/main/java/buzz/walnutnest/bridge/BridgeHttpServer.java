package buzz.walnutnest.bridge;

import android.content.Context;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class BridgeHttpServer {
    static final int PORT = 8766;
    private final Context context;
    private final ExecutorService pool = Executors.newCachedThreadPool();
    private volatile boolean running;
    private ServerSocket socket;

    BridgeHttpServer(Context context) { this.context = context.getApplicationContext(); }
    void start() {
        if (running) return;
        running = true;
        pool.execute(() -> {
            try {
                socket = new ServerSocket();
                socket.bind(new InetSocketAddress(InetAddress.getLoopbackAddress(), PORT));
                while (running) pool.execute(new Client(socket.accept()));
            } catch (IOException ignored) { running = false; }
        });
    }
    void stop() { running = false; try { if (socket != null) socket.close(); } catch (IOException ignored) {} pool.shutdownNow(); }

    private final class Client implements Runnable {
        private final Socket client;
        Client(Socket client) { this.client = client; }
        @Override public void run() {
            try (Socket c = client; BufferedReader in = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8)); OutputStream out = c.getOutputStream()) {
                String first = in.readLine(); if (first == null) return;
                String[] request = first.split(" "); String path = request.length > 1 ? request[1] : "/";
                String token = null; int contentLength = 0; String line;
                while ((line = in.readLine()) != null && !line.isEmpty()) {
                    int colon = line.indexOf(':'); if (colon < 0) continue;
                    String key=line.substring(0,colon).trim().toLowerCase(Locale.ROOT); String value=line.substring(colon+1).trim(); if(key.equals("x-walnut-token")) token=value; if(key.equals("content-length")) contentLength=Integer.parseInt(value);
                }
                char[] bodyChars=new char[Math.max(0,contentLength)]; int read=0; while(read<bodyChars.length){int n=in.read(bodyChars,read,bodyChars.length-read);if(n<0)break;read+=n;} JSONObject body=read>0?new JSONObject(new String(bodyChars,0,read)):new JSONObject();
                if (!BridgeToken.matches(context, token)) { respond(out, 401, json(false, "unauthorized")); return; }
                WalnutAccessibilityService service = WalnutAccessibilityService.get();
                if (path.equals("/v1/status")) {
                    JSONObject data = new JSONObject(); data.put("accessibility", service != null); data.put("version", "0.1.0"); data.put("port", PORT);
                    respond(out, 200, envelope(true, null, data));
                } else if (path.equals("/v1/ui")) {
                    if(service==null||service.getRootInActiveWindow()==null){respond(out,409,json(false,"accessibility service unavailable"));return;}
                    int depth=Math.max(1,Math.min(12,body.optInt("max_depth",6))); respond(out,200,envelope(true,null,NodeTree.compact(service.getRootInActiveWindow(),0,depth)));
                } else if (path.equals("/v1/click")) {
                    String text=body.optString("text",""); boolean ok=!text.isEmpty()&&service!=null&&service.clickText(text); respond(out,ok?200:404,json(ok,ok?null:"node not found or not clickable"));
                } else if (path.equals("/v1/type")) {
                    boolean ok=service!=null&&service.setFocusedText(body.optString("text","")); respond(out,ok?200:409,json(ok,ok?null:"focused editable node unavailable"));
                } else if (path.equals("/v1/swipe")) {
                    boolean ok=service!=null&&service.swipe((float)body.optDouble("x1"),(float)body.optDouble("y1"),(float)body.optDouble("x2"),(float)body.optDouble("y2"),body.optLong("duration",300)); respond(out,ok?200:409,json(ok,ok?null:"gesture unavailable"));
                } else if (path.equals("/v1/back")) {
                    boolean ok = service != null && service.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK);
                    respond(out, ok ? 200 : 409, json(ok, ok ? null : "accessibility service unavailable"));
                } else respond(out, 404, json(false, "not_found"));
            } catch (Exception ignored) {}
        }
    }
    private static JSONObject envelope(boolean ok, String error, Object data) throws Exception { JSONObject j=new JSONObject(); j.put("ok",ok); if(error!=null)j.put("error",error); if(data!=null)j.put("data",data); return j; }
    private static JSONObject json(boolean ok, String error) throws Exception { return envelope(ok,error,null); }
    private static void respond(OutputStream out, int status, JSONObject body) throws IOException { byte[] b=body.toString().getBytes(StandardCharsets.UTF_8); String h="HTTP/1.1 "+status+"\r\nContent-Type: application/json\r\nContent-Length: "+b.length+"\r\nConnection: close\r\n\r\n"; out.write(h.getBytes(StandardCharsets.US_ASCII)); out.write(b); out.flush(); }
}
