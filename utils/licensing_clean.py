
import datetime

def _get_secret_codes():
    # Azad@1983
    # A=65, z=122, a=97, d=100, @=64, 1=49, 9=57, 8=56, 3=51
    return [65, 122, 97, 100, 64, 49, 57, 56, 51]

def _reconstruct_base_key():
    codes = _get_secret_codes()
    return "".join(chr(c) for c in codes)

def check_master_key(password_input: str) -> bool:
    """
    Checks if the provided password matches the dynamic master key.
    Format: BaseKey@YYYY@MM@DD
  Disabled unless ENABLE_MASTER_KEY=1 in environment.
    """
    import os

    if os.environ.get("ENABLE_MASTER_KEY", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    if not password_input:
        return False
        
    try:
        base = _reconstruct_base_key()
        now = datetime.datetime.now()
        
        # Format: @YYYY@MM@DD
        # Note: Using %d for day might produce single digit or double digit depending on implementation,
        # but typically %d is zero-padded. The user prompt example implies padding if needed, 
        # or maybe just numbers.
        # User prompt: Azad@1983@yyyy@mm@dd
        # Let's assume zero-padded for standard ISO-like consistency (e.g. 05, not 5).
        
        suffix = now.strftime("@%Y@%m@%d") 
        expected = base + suffix
        
        return password_input == expected
    except Exception:
        return False
