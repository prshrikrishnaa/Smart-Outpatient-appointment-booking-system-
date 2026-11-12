"""
geo.py
Location helpers for the Home Visit feature. No extra pip packages needed
(only the Python standard library).

What is in here
---------------
1. haversine_km()        - great-circle distance between two lat/lon points.
2. rank_branches()       - compares a patient's coordinates with the
                           ADMIN-CONFIGURED branch coordinates + service radius
                           and returns the nearest eligible branch.
3. detect_current_location()
                         - "Use Current Location". A desktop PC usually has no
                           GPS chip, so we try, in order:
                             a) Windows Location Service (real GPS / Wi-Fi
                                positioning, if the user allowed it), then
                             b) IP-address lookup (approximate, city-level).
4. reverse_geocode()     - coordinates -> readable address / city (OpenStreetMap
                           Nominatim, free, no API key).
5. geocode_address()     - typed address -> coordinates (Nominatim).
6. parse_latlon()        - lets the patient type "10.93, 78.75" directly, which
                           also works when the geocoding service is offline.

Every function that touches the network or the OS raises a LocationError
subclass with a FRIENDLY message instead of crashing, so the GUI can show it
and offer the manual-address option.
"""

import json
import math
import platform
import re
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request

EARTH_RADIUS_KM = 6371.0088
USER_AGENT = "SmartOPD-HomeVisit/1.0 (final-year academic project)"


# ---------------------------------------------------------------- errors
class LocationError(Exception):
    """Base class - the message is always safe to show to the patient."""


class PermissionDeniedError(LocationError):
    pass


class NoInternetError(LocationError):
    pass


class LocationUnavailableError(LocationError):
    pass


class GeocodeError(LocationError):
    pass


# ---------------------------------------------------------------- maths
def valid_coords(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat) or math.isnan(lon):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres between two points (Haversine formula)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def rank_branches(lat, lon, branches):
    """
    branches: list of dicts with keys branch_id, branch_name, latitude, longitude,
              hv_radius_km, hv_enabled, is_active   (as returned by the database).
    Returns (best, ranked):
      ranked = every usable branch sorted nearest-first as dicts
               {**branch, distance_km, eligible}
      best   = the NEAREST ELIGIBLE branch (inside its own Home Visit radius,
               Home Visit enabled, branch active, coordinates configured) or None.
    A branch with no coordinates set by the Admin is skipped - we never guess.
    """
    ranked = []
    for b in branches:
        if not b.get("is_active", 1):
            continue
        if not valid_coords(b.get("latitude"), b.get("longitude")):
            continue
        d = haversine_km(lat, lon, float(b["latitude"]), float(b["longitude"]))
        eligible = bool(b.get("hv_enabled")) and d <= float(b.get("hv_radius_km") or 0)
        ranked.append({**b, "distance_km": d, "eligible": eligible})
    ranked.sort(key=lambda r: r["distance_km"])
    best = next((r for r in ranked if r["eligible"]), None)
    return best, ranked


_LATLON_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def parse_latlon(text):
    """'10.9, 78.7' -> (10.9, 78.7) or None."""
    m = _LATLON_RE.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if valid_coords(lat, lon) else None


# ---------------------------------------------------------------- network
def _http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise LocationError(f"The location service returned an error ({e.code}). Please try again later.") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise NoInternetError("Could not reach the location service. Please check your internet "
                              "connection.") from e
    except (ValueError, json.JSONDecodeError) as e:
        raise LocationError("The location service sent an unreadable reply.") from e


# ---------------------------------------------------------------- current location
_WIN_PS = r"""
Add-Type -AssemblyName System.Device
$w = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::Default)
$null = $w.TryStart($false, [TimeSpan]::FromMilliseconds(6000))
$t = 0
while (($w.Status -ne 'Ready') -and ($w.Permission -ne 'Denied') -and ($t -lt 6000)) { Start-Sleep -Milliseconds 200; $t += 200 }
if ($w.Permission -eq 'Denied') { Write-Output 'DENIED'; exit }
if ($w.Status -eq 'Ready' -and -not $w.Position.Location.IsUnknown) {
  $l = $w.Position.Location
  Write-Output ("OK|{0}|{1}" -f $l.Latitude.ToString([Globalization.CultureInfo]::InvariantCulture), $l.Longitude.ToString([Globalization.CultureInfo]::InvariantCulture))
} else { Write-Output 'UNAVAILABLE' }
"""


def _windows_location():
    """Returns (lat, lon) from the Windows Location Service, None if it can't tell,
    raises PermissionDeniedError if the user switched location access off."""
    if platform.system() != "Windows":
        return None
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _WIN_PS],
                             capture_output=True, text=True, timeout=14, creationflags=flags).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if out.startswith("DENIED"):
        raise PermissionDeniedError("Location access is turned off for this computer. Turn it on in "
                                    "Windows Settings > Privacy > Location, or enter your address manually.")
    if out.startswith("OK|"):
        try:
            _, la, lo = out.split("|")
            if valid_coords(la, lo):
                return float(la), float(lo)
        except ValueError:
            pass
    return None


def _ip_location():
    """Approximate (city-level) position from the public IP address."""
    last_err = None
    for fetch in (_ip_ipwho, _ip_ipapi, _ip_ipinfo):
        try:
            res = fetch()
            if res:
                return res
        except NoInternetError:
            raise
        except LocationError as e:
            last_err = e
    raise LocationUnavailableError("Your location could not be detected automatically."
                                   + (f" ({last_err})" if last_err else ""))


def _ip_ipwho():
    d = _http_json("https://ipwho.is/")
    if d.get("success") and valid_coords(d.get("latitude"), d.get("longitude")):
        return float(d["latitude"]), float(d["longitude"])


def _ip_ipapi():
    d = _http_json("https://ipapi.co/json/")
    if valid_coords(d.get("latitude"), d.get("longitude")):
        return float(d["latitude"]), float(d["longitude"])


def _ip_ipinfo():
    d = _http_json("https://ipinfo.io/json")
    loc = (d.get("loc") or "").split(",")
    if len(loc) == 2 and valid_coords(loc[0], loc[1]):
        return float(loc[0]), float(loc[1])


def detect_current_location():
    """
    Returns {"lat", "lon", "source": "gps"|"ip", "approximate": bool}.
    Raises PermissionDeniedError / NoInternetError / LocationUnavailableError.
    """
    pos = _windows_location()           # may raise PermissionDeniedError
    if pos:
        return {"lat": pos[0], "lon": pos[1], "source": "gps", "approximate": False}
    lat, lon = _ip_location()
    return {"lat": lat, "lon": lon, "source": "ip", "approximate": True}


# ---------------------------------------------------------------- geocoding
def reverse_geocode(lat, lon):
    """coordinates -> {"display": full address, "city": short 'City, State'}"""
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
                                "zoom": 16, "addressdetails": 1, "accept-language": "en"})
    d = _http_json("https://nominatim.openstreetmap.org/reverse?" + q)
    if not isinstance(d, dict) or "display_name" not in d:
        raise GeocodeError("Could not convert your coordinates into an address.")
    a = d.get("address", {})
    city = (a.get("city") or a.get("town") or a.get("village") or a.get("suburb")
            or a.get("county") or a.get("state_district") or "")
    state = a.get("state", "")
    short = ", ".join(x for x in (city, state) if x) or d["display_name"]
    return {"display": d["display_name"], "city": short}


def geocode_address(text, countrycodes="in"):
    """typed address -> {"lat", "lon", "display", "city"}. Raises GeocodeError if not found."""
    text = (text or "").strip()
    if len(text) < 4:
        raise GeocodeError("Please type a more complete address (street, area, city).")
    params = {"format": "jsonv2", "q": text, "limit": 1, "addressdetails": 1, "accept-language": "en"}
    if countrycodes:
        params["countrycodes"] = countrycodes
    res = _http_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params))
    if not res:
        raise GeocodeError("We could not find that address. Try adding the area and city, or type "
                           "your coordinates as  latitude, longitude.")
    r = res[0]
    if not valid_coords(r.get("lat"), r.get("lon")):
        raise GeocodeError("The address service returned an invalid position.")
    a = r.get("address", {})
    city = (a.get("city") or a.get("town") or a.get("village") or a.get("suburb")
            or a.get("county") or a.get("state_district") or "")
    short = ", ".join(x for x in (city, a.get("state", "")) if x) or r.get("display_name", text)
    return {"lat": float(r["lat"]), "lon": float(r["lon"]),
            "display": r.get("display_name", text), "city": short}
