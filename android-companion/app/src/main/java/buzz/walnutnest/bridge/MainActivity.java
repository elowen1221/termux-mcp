package buzz.walnutnest.bridge;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.database.Cursor;
import java.io.InputStream;
import java.io.OutputStream;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.ImageView;
import java.io.File;
import android.content.ContentValues;
import android.provider.MediaStore;
import android.os.Environment;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final int PICK_STICKERS=4101, PICK_DROP=4102;
    private static final int INK=Color.rgb(41,40,36), MUTED=Color.rgb(119,115,107), LEAF=Color.rgb(102,116,94);
    private TextView bridgeState;
    private LinearLayout recentDrops;
    private TextView recentSummary;
    private final java.util.ArrayList<DropItem> recentItems=new java.util.ArrayList<>();
    private static final class DropItem { String name,bucket,key; Uri uri; DropItem(String n,String b,Uri u,String k){name=n;bucket=b;uri=u;key=k;} }
    private static final class ExportedDrop { String name,key; Uri uri; ExportedDrop(String n,String k,Uri u){name=n;key=k;uri=u;} }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll=new ScrollView(this); scroll.setFillViewport(true); scroll.setBackgroundColor(Color.rgb(247,245,239));
        LinearLayout page=new LinearLayout(this); page.setOrientation(LinearLayout.VERTICAL); page.setPadding(dp(24),dp(30),dp(24),dp(36));

        TextView eyebrow=text("WALNUT · ANDROID",12,MUTED); eyebrow.setLetterSpacing(.16f); page.addView(eyebrow);
        TextView title=text("Bridge",34,INK); title.setTypeface(Typeface.DEFAULT,Typeface.BOLD); page.addView(title,lp(-1,-2,0,4));
        TextView subtitle=text("a tiny pair of eyes and hands for Termux-MCP",15,MUTED); page.addView(subtitle,lp(-1,-2,0,24));

        LinearLayout statusCard=card();
        TextView statusLabel=text("DEVICE BRIDGE",11,MUTED); statusLabel.setLetterSpacing(.12f); statusCard.addView(statusLabel);
        bridgeState=text("",20,INK); bridgeState.setTypeface(Typeface.DEFAULT,Typeface.BOLD); statusCard.addView(bridgeState,lp(-1,-2,0,5));
        TextView local=text("local only · 127.0.0.1:8766",13,MUTED); statusCard.addView(local);
        Button grant=button("Accessibility settings",false); grant.setOnClickListener(v->startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))); statusCard.addView(grant,lp(-1,dp(48),14,0));
        page.addView(statusCard,lp(-1,-2,0,14));

        LinearLayout updateCard=card();
        TextView updateLabel=text("UPDATES",11,MUTED); updateLabel.setLetterSpacing(.12f); updateCard.addView(updateLabel);
        TextView version=text("Walnut Bridge · v"+appVersion(),19,INK); version.setTypeface(Typeface.DEFAULT,Typeface.BOLD); updateCard.addView(version,lp(-1,-2,0,5));
        TextView updateStatus=text("Ready to check for a newer build.",13,MUTED); updateCard.addView(updateStatus);
        Button update=button("Check for update",true); update.setOnClickListener(v->{
            update.setEnabled(false);
            Updater.checkAndDownload(this,new Updater.Callback(){
                @Override public void onStatus(String message){runOnUiThread(()->{updateStatus.setText(message);if(message.startsWith("Already"))update.setEnabled(true);});}
                @Override public void onReady(String name,File apk){runOnUiThread(()->{updateStatus.setText(name+" downloaded · checksum + signature verified");update.setEnabled(true);Updater.install(MainActivity.this,apk);});}
                @Override public void onError(String message){runOnUiThread(()->{updateStatus.setText("Couldn’t update · "+message);update.setEnabled(true);});}
            });
        }); updateCard.addView(update,lp(-1,dp(48),14,0));
        page.addView(updateCard,lp(-1,-2,0,14));

        LinearLayout dropCard=card();
        TextView dropLabel=text("DROP TO WALNUT",11,MUTED); dropLabel.setLetterSpacing(.12f); dropCard.addView(dropLabel);
        TextView dropTitle=text("Send pictures to Termux",19,INK); dropTitle.setTypeface(Typeface.DEFAULT,Typeface.BOLD); dropCard.addView(dropTitle,lp(-1,-2,0,5));
        TextView dropHint=text("Sticker inbox keeps new reactions separate until they are reviewed and tagged.",13,MUTED); dropCard.addView(dropHint);
        Button stickers=button("Add stickers",true); stickers.setOnClickListener(v->pickImages(PICK_STICKERS)); dropCard.addView(stickers,lp(-1,dp(48),14,0));
        Button pictures=button("Drop pictures",false); pictures.setOnClickListener(v->pickImages(PICK_DROP)); dropCard.addView(pictures,lp(-1,dp(46),8,0));
        TextView recentLabel=text("RECENTLY DROPPED",11,MUTED); recentLabel.setLetterSpacing(.10f); dropCard.addView(recentLabel,lp(-1,-2,18,0));
        recentSummary=text("Nothing dropped from this screen yet.",13,MUTED); dropCard.addView(recentSummary,lp(-1,-2,5,0));
        recentDrops=new LinearLayout(this); recentDrops.setOrientation(LinearLayout.VERTICAL); dropCard.addView(recentDrops,lp(-1,-2,4,0));
        loadRecentDrops(); renderRecentDrops();
        page.addView(dropCard,lp(-1,-2,0,14));

        LinearLayout pairing=card();
        TextView pairLabel=text("PAIRING",11,MUTED); pairLabel.setLetterSpacing(.12f); pairing.addView(pairLabel);
        TextView pairTitle=text("Private handshake",19,INK); pairTitle.setTypeface(Typeface.DEFAULT,Typeface.BOLD); pairing.addView(pairTitle,lp(-1,-2,0,5));
        TextView pairHint=text("The token stays on this phone. Reveal it only when pairing Termux.",13,MUTED); pairing.addView(pairHint);
        TextView token=text(maskedToken(),14,INK); token.setTypeface(Typeface.MONOSPACE); token.setTextIsSelectable(false); pairing.addView(token,lp(-1,-2,14,2));
        Button reveal=button("Reveal token",false); reveal.setOnClickListener(new View.OnClickListener(){boolean shown=false; public void onClick(View v){shown=!shown;token.setText(shown?BridgeToken.getOrCreate(MainActivity.this):maskedToken());token.setTextIsSelectable(shown);reveal.setText(shown?"Hide token":"Reveal token");}}); pairing.addView(reveal,lp(-1,dp(46),10,0));
        Button copy=button("Copy token",false); copy.setOnClickListener(v->{ClipboardManager cm=(ClipboardManager)getSystemService(Context.CLIPBOARD_SERVICE);cm.setPrimaryClip(ClipData.newPlainText("Walnut Android Bridge token",BridgeToken.getOrCreate(this)));Toast.makeText(this,"Copied · paste only into Termux",Toast.LENGTH_SHORT).show();}); pairing.addView(copy,lp(-1,dp(46),8,0));
        Button rotate=button("Rotate token",false); rotate.setOnClickListener(v->{BridgeToken.rotate(this);token.setText(maskedToken());Toast.makeText(this,"Fresh token created · old token retired",Toast.LENGTH_LONG).show();}); pairing.addView(rotate,lp(-1,dp(46),8,0));
        page.addView(pairing,lp(-1,-2,0,20));

        TextView footer=text("◌  one small bridge, quietly awake",12,MUTED); footer.setGravity(Gravity.CENTER); page.addView(footer,lp(-1,-2,0,0));
        scroll.addView(page); setContentView(scroll); refreshStatus();
    }

    private void pickImages(int requestCode){
        Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT); i.setType("image/*"); i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true); i.addCategory(Intent.CATEGORY_OPENABLE); startActivityForResult(i,requestCode);
    }
    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
        super.onActivityResult(requestCode,resultCode,data);
        if(resultCode!=RESULT_OK||data==null||(requestCode!=PICK_STICKERS&&requestCode!=PICK_DROP))return;
        java.util.ArrayList<Uri> uris=new java.util.ArrayList<>();
        if(data.getClipData()!=null){for(int i=0;i<data.getClipData().getItemCount();i++)uris.add(data.getClipData().getItemAt(i).getUri());} else if(data.getData()!=null)uris.add(data.getData());
        String bucket=requestCode==PICK_STICKERS?"stickers":"pictures"; int ok=0; java.util.ArrayList<ExportedDrop> done=new java.util.ArrayList<>();
        for(Uri uri:uris){ExportedDrop d=exportDrop(uri,bucket);if(d!=null){ok++;done.add(d);}}
        rememberRecentDrops(done,bucket); showRecentDrops(ok,uris.size(),bucket);
        Toast.makeText(this,"Dropped "+ok+" / "+uris.size()+" picture(s) · WalnutDrop",Toast.LENGTH_LONG).show();
    }
    private void showRecentDrops(int ok,int total,String bucket){
        recentSummary.setText(ok==total?("✓ "+ok+" picture"+(ok==1?"":"s")+" delivered · "+bucket):("⚠ "+ok+" / "+total+" delivered · "+bucket)); renderRecentDrops();
    }
    private void rememberRecentDrops(java.util.ArrayList<ExportedDrop> drops,String bucket){
        for(ExportedDrop d:drops){recentItems.add(0,new DropItem(d.name,bucket,d.uri,d.key));}
        while(recentItems.size()>12)recentItems.remove(recentItems.size()-1); saveRecentDrops();
    }
    private void renderRecentDrops(){
        if(recentDrops==null)return; recentDrops.removeAllViews();
        if(recentItems.isEmpty()){recentSummary.setText("Nothing dropped from this screen yet.");return;}
        for(DropItem item:recentItems){
            LinearLayout row=new LinearLayout(this); row.setOrientation(LinearLayout.HORIZONTAL); row.setGravity(Gravity.CENTER_VERTICAL);
            ImageView thumb=new ImageView(this); thumb.setScaleType(ImageView.ScaleType.CENTER_CROP); thumb.setImageDrawable(null); row.addView(thumb,new LinearLayout.LayoutParams(dp(54),dp(54)));
            LinearLayout words=new LinearLayout(this); words.setOrientation(LinearLayout.VERTICAL);
            TextView label=text(item.name,13,INK); label.setMaxLines(1); label.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE); words.addView(label);
            String ready=readyName(item.key); TextView state=text(ready==null?"✓ 已投递 · 等待桉桉整理":"✓ 已收录 · "+ready,12,ready==null?MUTED:LEAF); words.addView(state,lp(-1,-2,3,0));
            LinearLayout.LayoutParams q=new LinearLayout.LayoutParams(0,dp(54),1); q.leftMargin=dp(10); row.addView(words,q); recentDrops.addView(row,lp(-1,dp(58),4,0));
        }
    }
    private void saveRecentDrops(){
        JSONArray a=new JSONArray(); try{for(DropItem x:recentItems){JSONObject j=new JSONObject();j.put("name",x.name);j.put("bucket",x.bucket);j.put("uri",x.uri.toString());j.put("key",x.key);a.put(j);}getSharedPreferences("walnut_drop",MODE_PRIVATE).edit().putString("recent",a.toString()).apply();}catch(Exception ignored){}
    }
    private void loadRecentDrops(){
        recentItems.clear(); try{JSONArray a=new JSONArray(getSharedPreferences("walnut_drop",MODE_PRIVATE).getString("recent","[]"));for(int i=0;i<a.length();i++){JSONObject j=a.getJSONObject(i);recentItems.add(new DropItem(j.optString("name","picture"),j.optString("bucket","stickers"),Uri.parse(j.optString("uri")),j.optString("key",j.optString("name","picture"))));}}catch(Exception ignored){}
    }
    private String readyName(String key){ return getSharedPreferences("walnut_drop",MODE_PRIVATE).getString("ready_"+key,null); }
    private void syncDropReceipts(){
        Uri collection=MediaStore.Files.getContentUri("external");
        String rel=Environment.DIRECTORY_DOCUMENTS+"/WalnutDrop/";
        try(Cursor c=getContentResolver().query(collection,new String[]{MediaStore.MediaColumns._ID},MediaStore.MediaColumns.RELATIVE_PATH+"=? AND "+MediaStore.MediaColumns.DISPLAY_NAME+"=?",new String[]{rel,"receipts.json"},MediaStore.MediaColumns.DATE_MODIFIED+" DESC")){
            if(c==null||!c.moveToFirst())return; Uri u=Uri.withAppendedPath(collection,String.valueOf(c.getLong(0)));
            try(InputStream in=getContentResolver().openInputStream(u)){if(in==null)return; byte[] raw=new byte[65536]; int n=in.read(raw); if(n<=0)return; JSONObject root=new JSONObject(new String(raw,0,n,java.nio.charset.StandardCharsets.UTF_8)); JSONObject ready=root.optJSONObject("ready"); if(ready==null)return; android.content.SharedPreferences.Editor e=getSharedPreferences("walnut_drop",MODE_PRIVATE).edit(); java.util.Iterator<String> keys=ready.keys(); while(keys.hasNext()){String k=keys.next(); e.putString("ready_"+k,ready.optString(k,"已收录"));} e.apply();}
        }catch(Throwable ignored){}
    }
    static void markDropReady(Context context,String key,String name){ if(key==null||key.isEmpty())return; context.getSharedPreferences("walnut_drop",MODE_PRIVATE).edit().putString("ready_"+key,name==null||name.isEmpty()?"已收录":name).apply(); }
    private String displayName(Uri uri){
        String name="picture"; Cursor c=getContentResolver().query(uri,null,null,null,null); if(c!=null){try{if(c.moveToFirst()){int n=c.getColumnIndex(OpenableColumns.DISPLAY_NAME);if(n>=0&&c.getString(n)!=null)name=c.getString(n);}}finally{c.close();}} return name;
    }
    private ExportedDrop exportDrop(Uri uri,String bucket){
        try{
            String original=displayName(uri); String safe=original.replaceAll("[^A-Za-z0-9._-]","_");
            String key=java.util.UUID.randomUUID().toString().replace("-",""); String exported="walnut_"+key+"_"+safe;
            ContentValues values=new ContentValues(); values.put(MediaStore.MediaColumns.DISPLAY_NAME,exported);
            String mime=getContentResolver().getType(uri); values.put(MediaStore.MediaColumns.MIME_TYPE,mime==null?"image/jpeg":mime);
            values.put(MediaStore.MediaColumns.RELATIVE_PATH,Environment.DIRECTORY_PICTURES+"/WalnutDrop/"+bucket); values.put(MediaStore.MediaColumns.IS_PENDING,1);
            Uri dest=getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,values); if(dest==null)return null;
            boolean copied=false; try(InputStream in=getContentResolver().openInputStream(uri);OutputStream os=getContentResolver().openOutputStream(dest)){if(in==null||os==null)return null;byte[] buf=new byte[65536];int n;while((n=in.read(buf))>0)os.write(buf,0,n);copied=true;} finally {if(!copied)getContentResolver().delete(dest,null,null);}
            ContentValues ready=new ContentValues(); ready.put(MediaStore.MediaColumns.IS_PENDING,0); getContentResolver().update(dest,ready,null,null);
            return new ExportedDrop(original,key,dest);
        }catch(Exception e){return null;}
    }

    @Override protected void onResume(){super.onResume();syncDropReceipts();if(recentDrops!=null)renderRecentDrops();if(bridgeState!=null)refreshStatus();Updater.resumePendingInstall(this);}
    private void refreshStatus(){String s=BridgeState.status(this);boolean ready="ready".equalsIgnoreCase(s)||WalnutAccessibilityService.get()!=null;bridgeState.setText(ready?"●  Connected":"○  Waiting for access");bridgeState.setTextColor(ready?LEAF:INK);}
    private String appVersion(){try{return getPackageManager().getPackageInfo(getPackageName(),0).versionName;}catch(Exception ignored){return "?";}}
    private String maskedToken(){String t=BridgeToken.getOrCreate(this);return "•••• •••• ••••  ·  "+(t.length()>4?t.substring(t.length()-4):"••••");}
    private TextView text(String s,float size,int color){TextView v=new TextView(this);v.setText(s);v.setTextSize(size);v.setTextColor(color);v.setLineSpacing(0,1.12f);return v;}
    private LinearLayout card(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);v.setPadding(dp(20),dp(19),dp(20),dp(18));GradientDrawable g=new GradientDrawable();g.setColor(Color.rgb(255,254,250));g.setCornerRadius(dp(22));g.setStroke(dp(1),Color.rgb(230,225,215));v.setBackground(g);return v;}
    private Button button(String s,boolean primary){Button b=new Button(this);b.setText(s);b.setAllCaps(false);b.setTextSize(14);b.setGravity(Gravity.CENTER);GradientDrawable g=new GradientDrawable();g.setCornerRadius(dp(16));g.setColor(primary?LEAF:Color.rgb(247,245,239));g.setStroke(dp(1),primary?LEAF:Color.rgb(230,225,215));b.setTextColor(primary?Color.WHITE:INK);b.setBackground(g);return b;}
    private LinearLayout.LayoutParams lp(int w,int h,int top,int bottom){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(w,h);p.topMargin=dp(top);p.bottomMargin=dp(bottom);return p;}
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
}
