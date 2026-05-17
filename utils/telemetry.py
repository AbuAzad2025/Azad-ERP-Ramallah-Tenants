
# Telemetry module disabled for security reasons.
# Previously sent system information (hostname, IP, platform) to an external
# service on every application startup. This has been disabled to prevent
# unintended data exfiltration.


def run_telemetry(app):
    pass
