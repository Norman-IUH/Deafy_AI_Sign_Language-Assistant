# Deafy v1.0 release candidate

Pi supports opt-in continuous draft assembly on its existing Model 2. Android RC8 adds the two draft modes without changing the checkpoint, label order or camera handedness logic. Single sign mode stays the default; gesture events do not send a question or trigger playback. The legacy iPhone web continues to serve GPS.

Use [Pi setup](../setup/pi.md) and [APK setup](../setup/android.md). The Android artifact is debug-signed for local acceptance; no release signing, public repository or v1.0.0 tag is authorized by this candidate.

Local acceptance APK: `Deafy-v1.0.0-rc8-debug.apk` (versionCode 9), SHA-256 `88d578d0aa36bdfa7a6c9862fa298956934cab0358be91067cd0660e9631e6ba`.

Rollback: back up important drafts first. Keep the RC7 debug APK; Android may reject an in-place downgrade, and uninstalling to reinstall it deletes local app data. For Pi restore the previous frontend files from the deployment backup manifest, then reload. Restart only the affected service if needed; do not replace the checkpoint, SQLite data, network profile or credentials. See the [testing and acceptance gates](TEST_REPORT.md).

GitHub: the workspace copy has no Git history. Prepare a new private repository after confirming team and asset rights. If a previous clone or repository exists, separately scan all branches and tags before transferring history. Revoke and replace credentials previously shared; if committed, rotate first and coordinate history remediation with the repository owners.
