package vn.edu.signassist;

import com.getcapacitor.BridgeActivity;
import android.os.Bundle;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle state) {
        registerPlugin(PiDiscoveryPlugin.class);
        registerPlugin(DeafyPairingPlugin.class);
        super.onCreate(state);
    }
}
