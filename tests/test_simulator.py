from sensor_service.sources import SimulatorSource


def test_simulator_ranges():
    sim = SimulatorSource(seed=42)
    for _ in range(500):
        r = sim.read()
        assert 18.0 <= r.temperature_c <= 32.0
        assert 35.0 <= r.humidity_percent <= 75.0
        assert 400 <= r.co2_ppm <= 1500
        assert r.source == "simulator"
