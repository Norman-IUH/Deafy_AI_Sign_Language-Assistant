package vn.edu.signassist;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

@CapacitorPlugin(name = "DeafyPairing")
public class DeafyPairingPlugin extends Plugin {
    private static final String ALIAS = "deafy-pairing-v1";

    private SharedPreferences storage() {
        return getContext().getSharedPreferences("deafy-pairing", Context.MODE_PRIVATE);
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(ALIAS)) return (SecretKey) store.getKey(ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
            KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }

    @PluginMethod
    public void save(PluginCall call) {
        String token = call.getString("token", "");
        if (token.length() > 4096) { call.reject("Mã ghép nối quá dài."); return; }
        try {
            if (token.isEmpty()) {
                if (!storage().edit().clear().commit()) throw new Exception();
            } else {
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.ENCRYPT_MODE, key());
                byte[] encrypted = cipher.doFinal(token.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                if (!storage().edit()
                    .putString("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                    .putString("token", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit()) throw new Exception();
            }
            call.resolve();
        } catch (Exception issue) { call.reject("Không lưu được mã ghép nối an toàn."); }
    }

    @PluginMethod
    public void load(PluginCall call) {
        try {
            JSObject result = new JSObject();
            String token = storage().getString("token", "");
            if (token.isEmpty()) result.put("token", "");
            else {
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128,
                    Base64.decode(storage().getString("iv", ""), Base64.NO_WRAP)));
                result.put("token", new String(cipher.doFinal(Base64.decode(token, Base64.NO_WRAP)),
                    java.nio.charset.StandardCharsets.UTF_8));
            }
            call.resolve(result);
        } catch (Exception issue) { call.reject("Không mở được mã ghép nối. Nhập lại mã của Pi."); }
    }
}
