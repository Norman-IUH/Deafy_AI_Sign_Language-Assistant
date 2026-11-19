package vn.edu.signassist;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.net.Inet4Address;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.LinkedHashSet;

@CapacitorPlugin(name = "PiDiscovery")
public class PiDiscoveryPlugin extends Plugin {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ArrayDeque<NsdServiceInfo> queue = new ArrayDeque<>();
    private final LinkedHashSet<String> origins = new LinkedHashSet<>();
    private NsdManager manager;
    private NsdManager.DiscoveryListener listener;
    private WifiManager.MulticastLock lock;
    private PluginCall pending;
    private boolean resolving;
    private int generation;
    private final Runnable timeout = () -> finish(null);

    @PluginMethod
    public void discover(PluginCall call) {
        handler.post(() -> {
            if (pending != null) { call.reject("Đang tìm Raspberry Pi."); return; }
            pending = call; origins.clear(); queue.clear(); resolving = false;
            final int run = ++generation;
            manager = (NsdManager) getContext().getSystemService(Context.NSD_SERVICE);
            listener = new NsdManager.DiscoveryListener() {
                public void onDiscoveryStarted(String type) {}
                public void onDiscoveryStopped(String type) {}
                public void onServiceLost(NsdServiceInfo service) {}
                public void onStartDiscoveryFailed(String type, int code) { handler.post(() -> { if (run == generation) finish("Không bắt đầu được tìm Pi: " + code); }); }
                public void onStopDiscoveryFailed(String type, int code) {}
                public void onServiceFound(NsdServiceInfo service) {
                    handler.post(() -> {
                        if (run != generation || pending == null || queue.size() >= 8) return;
                        if (service.getServiceType().equals("_deafy._tcp.")) { queue.add(service); resolveNext(run); }
                    });
                }
            };
            try {
                WifiManager wifi = (WifiManager) getContext().getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                lock = wifi.createMulticastLock("deafy-discovery"); lock.setReferenceCounted(false); lock.acquire();
                manager.discoverServices("_deafy._tcp.", NsdManager.PROTOCOL_DNS_SD, listener);
                handler.postDelayed(timeout, 5000);
            } catch (RuntimeException issue) { finish("Không thể tìm Pi trên Wi-Fi. Kiểm tra quyền mạng."); }
        });
    }

    @SuppressWarnings("deprecation")
    private void resolveNext(int run) {
        if (resolving || queue.isEmpty() || pending == null || run != generation) return;
        resolving = true;
        manager.resolveService(queue.remove(), new NsdManager.ResolveListener() {
            public void onResolveFailed(NsdServiceInfo service, int code) {
                handler.post(() -> { if (run == generation) { resolving = false; resolveNext(run); } });
            }
            public void onServiceResolved(NsdServiceInfo service) {
                handler.post(() -> {
                    if (run != generation || pending == null) return;
                    byte[] app = service.getAttributes().get("app");
                    if (app != null && new String(app, StandardCharsets.UTF_8).equals("DAKT-Nc") &&
                            service.getHost() instanceof Inet4Address && service.getPort() > 0 && service.getPort() <= 65535) {
                        origins.add("http://" + service.getHost().getHostAddress() + ":" + service.getPort());
                    }
                    resolving = false; resolveNext(run);
                });
            }
        });
    }

    private void finish(String error) {
        PluginCall call = pending; pending = null; generation++;
        handler.removeCallbacks(timeout);
        if (manager != null && listener != null) {
            try { manager.stopServiceDiscovery(listener); } catch (RuntimeException ignored) {}
        }
        listener = null; queue.clear(); resolving = false;
        if (lock != null && lock.isHeld()) lock.release();
        lock = null;
        if (call != null) {
            if (error != null) call.reject(error);
            else { JSArray values = new JSArray(); for (String origin : origins) values.put(origin);
                JSObject result = new JSObject(); result.put("origins", values); call.resolve(result); }
        }
    }

    @Override
    protected void handleOnDestroy() { handler.post(() -> finish("Ứng dụng đã dừng tìm Pi.")); }
}
