import pytest


@pytest.fixture(autouse=True)
def isolate_external_services(monkeypatch):
    for name in ('DAKT_GRU_CHECKPOINT','DAKT_GRU_SHA256','DAKT_GRU_NAME','DAKT_PLACE_PROVIDER'):
        monkeypatch.delenv(name, raising=False)
    # Running tests from a configured Pi shell must not contact real devices or cloud logging.
    for name in ('DAKT_MQTT_HOST', 'DAKT_MQTT_CLIENT_ID', 'THINGSPEAK_WRITE_API_KEY', 'THINGSPEAK_CHANNEL_ID', 'DAKT_DISCOVERY_ENABLED', 'GOOGLE_PLACES_API_KEY', 'DAKT_PLACES_ENABLED', 'GROQ_API_KEY', 'GROQ_MODEL'):
        monkeypatch.delenv(name, raising=False)
