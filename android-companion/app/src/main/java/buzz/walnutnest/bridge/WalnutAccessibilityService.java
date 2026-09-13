package buzz.walnutnest.bridge;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Bundle;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
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

    public boolean clickText(String text){
        for(AccessibilityNodeInfo node:findText(text)){
            AccessibilityNodeInfo current=node;
            while(current!=null){
                if(current.isClickable() && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true;
                current=current.getParent();
            }
            Rect bounds=new Rect();
            node.getBoundsInScreen(bounds);
            if(!bounds.isEmpty() && tap(bounds.exactCenterX(),bounds.exactCenterY())) return true;
        }
        return false;
    }

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
