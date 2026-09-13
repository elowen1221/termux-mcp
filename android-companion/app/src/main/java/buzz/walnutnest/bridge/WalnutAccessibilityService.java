package buzz.walnutnest.bridge;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Bitmap;
import android.graphics.ColorSpace;
import android.hardware.HardwareBuffer;
import android.util.Base64;
import java.io.ByteArrayOutputStream;
import java.util.concurrent.atomic.AtomicReference;
import android.graphics.Rect;
import android.os.Bundle;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONObject;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.util.ArrayList;
import java.util.List;

public final class WalnutAccessibilityService extends AccessibilityService {
    private static volatile WalnutAccessibilityService instance;
    private BridgeHttpServer bridgeServer;

    public static WalnutAccessibilityService get(){ return instance; }

    @Override protected void onServiceConnected(){
        super.onServiceConnected();
        instance=this;
        BridgeState.mark(this,"accessibility connected",null);
        try{ bridgeServer=new BridgeHttpServer(this); bridgeServer.start(); }
        catch(Throwable error){ BridgeState.mark(this,"startup failed",error.getClass().getSimpleName()+": "+String.valueOf(error.getMessage())); }
    }

    @Override public void onDestroy(){
        if(bridgeServer!=null){ bridgeServer.stop(); bridgeServer=null; }
        if(instance==this) instance=null;
        super.onDestroy();
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event){}
    @Override public void onInterrupt(){}

    public List<AccessibilityNodeInfo> findText(String text){
        AccessibilityNodeInfo root=getRootInActiveWindow();
        ArrayList<AccessibilityNodeInfo> exact=new ArrayList<>();
        if(root==null) return exact;
        collectExactMatches(root,text,exact,0);
        return exact;
    }

    private void collectExactMatches(AccessibilityNodeInfo node,String text,List<AccessibilityNodeInfo> out,int depth){
        if(node==null || depth>40) return;
        CharSequence t=node.getText();
        CharSequence d=node.getContentDescription();
        if((t!=null && text.contentEquals(t)) || (d!=null && text.contentEquals(d))) out.add(node);
        for(int i=0;i<node.getChildCount();i++) collectExactMatches(node.getChild(i),text,out,depth+1);
    }

    public JSONObject currentContext(){
        JSONObject out=new JSONObject();
        AccessibilityNodeInfo root=getRootInActiveWindow();
        try{
            out.put("success",root!=null);
            if(root!=null){
                Rect r=new Rect(); root.getBoundsInScreen(r);
                out.put("package",String.valueOf(root.getPackageName()));
                out.put("class",String.valueOf(root.getClassName()));
                out.put("bounds",new JSONArray(new int[]{r.left,r.top,r.right,r.bottom}));
            }
        }catch(Exception ignored){}
        return out;
    }

    public JSONObject clickSelectorDetailed(String text,String viewId,String desc,int index){
        JSONObject result=new JSONObject();
        AccessibilityNodeInfo root=getRootInActiveWindow();
        ArrayList<AccessibilityNodeInfo> matches=new ArrayList<>();
        if(root!=null) collectSelectorMatches(root,text,viewId,desc,matches,0);
        try{ result.put("match_count",matches.size()); result.put("index",index); }catch(Exception ignored){}
        if(index<0 || index>=matches.size()){ try{result.put("success",false);}catch(Exception ignored){} return result; }
        AccessibilityNodeInfo node=matches.get(index);
        Rect nodeBounds=new Rect(); node.getBoundsInScreen(nodeBounds);
        try{
            result.put("matched_text",String.valueOf(node.getText()));
            result.put("matched_desc",String.valueOf(node.getContentDescription()));
            result.put("matched_id",node.getViewIdResourceName());
            result.put("matched_bounds",new JSONArray(new int[]{nodeBounds.left,nodeBounds.top,nodeBounds.right,nodeBounds.bottom}));
        }catch(Exception ignored){}
        AccessibilityNodeInfo current=node;
        while(current!=null){
            if(current.isClickable()){
                boolean ok=current.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                try{result.put("strategy","action_click");result.put("success",ok);}catch(Exception ignored){}
                if(ok) return result;
            }
            current=current.getParent();
        }
        boolean ok=!nodeBounds.isEmpty() && tap(nodeBounds.exactCenterX(),nodeBounds.exactCenterY());
        try{result.put("strategy","gesture_center");result.put("success",ok);}catch(Exception ignored){}
        return result;
    }

    private void collectSelectorMatches(AccessibilityNodeInfo node,String text,String viewId,String desc,List<AccessibilityNodeInfo> out,int depth){
        if(node==null || depth>40) return;
        boolean any=false, ok=true;
        if(text!=null && !text.isEmpty()){ any=true; CharSequence v=node.getText(); ok &= v!=null && text.contentEquals(v); }
        if(desc!=null && !desc.isEmpty()){ any=true; CharSequence v=node.getContentDescription(); ok &= v!=null && desc.contentEquals(v); }
        if(viewId!=null && !viewId.isEmpty()){ any=true; ok &= viewId.equals(node.getViewIdResourceName()); }
        if(any && ok) out.add(node);
        for(int i=0;i<node.getChildCount();i++) collectSelectorMatches(node.getChild(i),text,viewId,desc,out,depth+1);
    }

    public JSONObject clickTextDetailed(String text){
        JSONObject result=new JSONObject();
        try{ result.put("query",text); }catch(Exception ignored){}
        List<AccessibilityNodeInfo> matches=findText(text);
        try{ result.put("match_count",matches.size()); }catch(Exception ignored){}
        for(AccessibilityNodeInfo node:matches){
            Rect nodeBounds=new Rect();
            node.getBoundsInScreen(nodeBounds);
            try{
                result.put("matched_text",String.valueOf(node.getText()));
                result.put("matched_desc",String.valueOf(node.getContentDescription()));
                result.put("matched_class",String.valueOf(node.getClassName()));
                result.put("matched_bounds",new JSONArray(new int[]{nodeBounds.left,nodeBounds.top,nodeBounds.right,nodeBounds.bottom}));
            }catch(Exception ignored){}

            AccessibilityNodeInfo current=node;
            while(current!=null){
                if(current.isClickable()) {
                    Rect targetBounds=new Rect(); current.getBoundsInScreen(targetBounds);
                    boolean ok=current.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                    try{
                        result.put("strategy","action_click");
                        result.put("target_bounds",new JSONArray(new int[]{targetBounds.left,targetBounds.top,targetBounds.right,targetBounds.bottom}));
                        result.put("success",ok);
                    }catch(Exception ignored){}
                    if(ok) return result;
                }
                current=current.getParent();
            }
            if(!nodeBounds.isEmpty()) {
                boolean ok=tap(nodeBounds.exactCenterX(),nodeBounds.exactCenterY());
                try{
                    result.put("strategy","gesture_center");
                    result.put("target_bounds",new JSONArray(new int[]{nodeBounds.left,nodeBounds.top,nodeBounds.right,nodeBounds.bottom}));
                    result.put("success",ok);
                }catch(Exception ignored){}
                if(ok) return result;
            }
        }
        try{ if(!result.has("success")) result.put("success",false); }catch(Exception ignored){}
        return result;
    }

    public boolean clickText(String text){ return clickTextDetailed(text).optBoolean("success",false); }

    public boolean tap(float x,float y){
        Path path=new Path();
        path.moveTo(x,y);
        GestureDescription.StrokeDescription stroke=new GestureDescription.StrokeDescription(path,0,80);
        CountDownLatch done=new CountDownLatch(1);
        AtomicBoolean completed=new AtomicBoolean(false);
        boolean accepted=dispatchGesture(
            new GestureDescription.Builder().addStroke(stroke).build(),
            new GestureResultCallback(){
                @Override public void onCompleted(GestureDescription gestureDescription){ completed.set(true); done.countDown(); }
                @Override public void onCancelled(GestureDescription gestureDescription){ done.countDown(); }
            },
            null
        );
        if(!accepted) return false;
        try{ return done.await(1500,TimeUnit.MILLISECONDS) && completed.get(); }
        catch(InterruptedException e){ Thread.currentThread().interrupt(); return false; }
    }

    public JSONObject screenshotPngBase64(){
        JSONObject result=new JSONObject();
        if(android.os.Build.VERSION.SDK_INT<30){
            try{result.put("success",false);result.put("error","screenshot requires Android 11+");}catch(Exception ignored){}
            return result;
        }
        CountDownLatch done=new CountDownLatch(1);
        AtomicReference<String> encoded=new AtomicReference<>();
        AtomicReference<String> error=new AtomicReference<>();
        try{
            takeScreenshot(android.view.Display.DEFAULT_DISPLAY,getMainExecutor(),new TakeScreenshotCallback(){
                @Override public void onSuccess(ScreenshotResult shot){
                    HardwareBuffer buffer=shot.getHardwareBuffer();
                    try{
                        ColorSpace colorSpace=shot.getColorSpace();
                        Bitmap hardware=Bitmap.wrapHardwareBuffer(buffer,colorSpace);
                        if(hardware==null){error.set("could not wrap screenshot buffer");return;}
                        Bitmap software=hardware.copy(Bitmap.Config.ARGB_8888,false);
                        if(software==null){error.set("could not copy screenshot bitmap");return;}
                        ByteArrayOutputStream out=new ByteArrayOutputStream();
                        if(!software.compress(Bitmap.CompressFormat.PNG,100,out)){error.set("PNG compression failed");return;}
                        encoded.set(Base64.encodeToString(out.toByteArray(),Base64.NO_WRAP));
                    }catch(Throwable t){error.set(t.getClass().getSimpleName()+": "+String.valueOf(t.getMessage()));}
                    finally{try{buffer.close();}catch(Throwable ignored){} done.countDown();}
                }
                @Override public void onFailure(int errorCode){error.set("takeScreenshot failed: "+errorCode);done.countDown();}
            });
            if(!done.await(2500,TimeUnit.MILLISECONDS)){error.set("screenshot timed out");}
        }catch(Throwable t){error.set(t.getClass().getSimpleName()+": "+String.valueOf(t.getMessage()));}
        try{
            if(encoded.get()!=null){result.put("success",true);result.put("format","png");result.put("base64",encoded.get());}
            else{result.put("success",false);result.put("error",error.get()==null?"screenshot unavailable":error.get());}
        }catch(Exception ignored){}
        return result;
    }

    public boolean setFocusedText(String text){
        AccessibilityNodeInfo root=getRootInActiveWindow();
        if(root==null) return false;
        AccessibilityNodeInfo focused=root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if(focused==null) return false;
        Bundle args=new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,text);
        return focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,args);
    }

    public boolean swipe(float x1,float y1,float x2,float y2,long durationMs){
        Path path=new Path();
        path.moveTo(x1,y1);
        path.lineTo(x2,y2);
        GestureDescription.StrokeDescription stroke=new GestureDescription.StrokeDescription(path,0,Math.max(1,durationMs));
        return dispatchGesture(new GestureDescription.Builder().addStroke(stroke).build(),null,null);
    }
}
