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
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;

public final class MainActivity extends Activity {
    private static final int INK=Color.rgb(41,40,36), MUTED=Color.rgb(119,115,107), LEAF=Color.rgb(102,116,94);
    private TextView bridgeState;

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

    @Override protected void onResume(){super.onResume();if(bridgeState!=null)refreshStatus();Updater.resumePendingInstall(this);}
    private void refreshStatus(){String s=BridgeState.status(this);boolean ready="ready".equalsIgnoreCase(s)||WalnutAccessibilityService.get()!=null;bridgeState.setText(ready?"●  Connected":"○  Waiting for access");bridgeState.setTextColor(ready?LEAF:INK);}
    private String appVersion(){try{return getPackageManager().getPackageInfo(getPackageName(),0).versionName;}catch(Exception ignored){return "?";}}
    private String maskedToken(){String t=BridgeToken.getOrCreate(this);return "•••• •••• ••••  ·  "+(t.length()>4?t.substring(t.length()-4):"••••");}
    private TextView text(String s,float size,int color){TextView v=new TextView(this);v.setText(s);v.setTextSize(size);v.setTextColor(color);v.setLineSpacing(0,1.12f);return v;}
    private LinearLayout card(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);v.setPadding(dp(20),dp(19),dp(20),dp(18));GradientDrawable g=new GradientDrawable();g.setColor(Color.rgb(255,254,250));g.setCornerRadius(dp(22));g.setStroke(dp(1),Color.rgb(230,225,215));v.setBackground(g);return v;}
    private Button button(String s,boolean primary){Button b=new Button(this);b.setText(s);b.setAllCaps(false);b.setTextSize(14);b.setGravity(Gravity.CENTER);GradientDrawable g=new GradientDrawable();g.setCornerRadius(dp(16));g.setColor(primary?LEAF:Color.rgb(247,245,239));g.setStroke(dp(1),primary?LEAF:Color.rgb(230,225,215));b.setTextColor(primary?Color.WHITE:INK);b.setBackground(g);return b;}
    private LinearLayout.LayoutParams lp(int w,int h,int top,int bottom){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(w,h);p.topMargin=dp(top);p.bottomMargin=dp(bottom);return p;}
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
}
