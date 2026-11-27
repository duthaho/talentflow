VERSION = "careers-v1"


def render_consent(tenant_name: str, retention_days: int | None) -> str:
    period = (
        f"for {retention_days} days"
        if retention_days is not None
        else f"for as long as needed for recruiting, then deleted under {tenant_name}'s retention policy"
    )
    return f"By applying you agree that {tenant_name} processes your application and CV {period}."
