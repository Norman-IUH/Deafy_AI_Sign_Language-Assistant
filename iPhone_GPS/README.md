# iPhone GPS web snapshot

Preserved legacy source from before mobile inference. This frontend uses the Pi camera preview and backend; it never loads MediaPipe or Model 2 locally. Use Settings to share GPS.

Install dependencies with npm install and build with npm run build. HTTPS root on the live Pi remains the original deployment. Preview uses port 5175. Deploy this build only to the separately managed iPhone web root after backup; Android_App/www now contains the Android-local-camera build.
