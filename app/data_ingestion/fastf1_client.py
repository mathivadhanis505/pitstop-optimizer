import os
import json
import logging
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("f1_ingestion.client")

# Setup local disk cache
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".fastf1_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OPENF1_CACHE_DIR = CACHE_DIR / "openf1"
OPENF1_CACHE_DIR.mkdir(parents=True, exist_ok=True)

try:
    import fastf1
    # Use Cache.enable_cache or configure
    if hasattr(fastf1, "Cache") and hasattr(fastf1.Cache, "enable_cache"):
        fastf1.Cache.enable_cache(str(CACHE_DIR))
    elif hasattr(fastf1, "configure"):
        fastf1.configure(cache_dir=str(CACHE_DIR))
    FASTF1_AVAILABLE = True
except Exception as e:
    logger.warning(f"FastF1 cache initialization error: {e}")
    FASTF1_AVAILABLE = False


class FastF1Client:
    """
    Robust Formula 1 client that integrates FastF1 with OpenF1 API fallback,
    providing local disk caching to prevent redundant network downloads.
    """
    OPENF1_BASE = "https://api.openf1.org/v1"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def _get_cached_json(self, cache_file: Path) -> Optional[Any]:
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _save_cached_json(self, cache_file: Path, data: Any):
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Failed to cache data to {cache_file}: {e}")

    def get_schedule(self, year: int) -> List[Dict[str, Any]]:
        """
        Retrieves the race schedule for a specific season.
        """
        cache_file = OPENF1_CACHE_DIR / f"schedule_{year}.json"
        cached = self._get_cached_json(cache_file)
        if cached is not None:
            return cached

        # Attempt OpenF1 sessions
        try:
            url = f"{self.OPENF1_BASE}/sessions?year={year}&session_name=Race"
            res = requests.get(url, timeout=self.timeout)
            if res.ok:
                sessions = res.json()
                schedule = []
                # Sort by date
                sessions = sorted(sessions, key=lambda s: s.get("date_start", ""))
                for idx, s in enumerate(sessions, 1):
                    schedule.append({
                        "round_no": idx,
                        "session_key": s.get("session_key"),
                        "meeting_key": s.get("meeting_key"),
                        "country": s.get("country_name"),
                        "circuit": s.get("circuit_short_name"),
                        "date": s.get("date_start", "")[:10],
                        "year": year
                    })
                if schedule:
                    self._save_cached_json(cache_file, schedule)
                    return schedule
        except Exception as e:
            logger.warning(f"OpenF1 schedule fetch failed for {year}: {e}")

        # Fallback to FastF1 schedule
        if FASTF1_AVAILABLE:
            try:
                sched = fastf1.get_event_schedule(year)
                out = []
                for _, row in sched.iterrows():
                    rnd = row.get("RoundNumber", 0)
                    if rnd > 0:
                        out.append({
                            "round_no": int(rnd),
                            "session_key": None,
                            "country": str(row.get("Country", "")),
                            "circuit": str(row.get("Location", "")),
                            "date": str(row.get("EventDate", ""))[:10],
                            "year": year
                        })
                if out:
                    self._save_cached_json(cache_file, out)
                    return out
            except Exception as e:
                logger.warning(f"FastF1 schedule fetch failed: {e}")

        return []

    def get_race_session(self, year: int, round_no: int) -> Dict[str, Any]:
        """
        Fetches race results, laps, stints, pit stops, and weather for a round.
        """
        cache_file = OPENF1_CACHE_DIR / f"race_{year}_r{round_no}.json"
        cached = self._get_cached_json(cache_file)
        if cached is not None:
            return cached

        # 1. Resolve session key
        schedule = self.get_schedule(year)
        matching = [s for s in schedule if s["round_no"] == round_no]
        session_key = matching[0].get("session_key") if matching else None

        data: Dict[str, Any] = {
            "year": year,
            "round_no": round_no,
            "session_key": session_key,
            "results": [],
            "laps": [],
            "stints": [],
            "pit_stops": [],
            "weather": {}
        }

        if session_key:
            # Fetch OpenF1 drivers & results
            try:
                d_res = requests.get(f"{self.OPENF1_BASE}/drivers?session_key={session_key}", timeout=self.timeout)
                if d_res.ok:
                    data["results"] = d_res.json()
            except Exception as e:
                logger.warning(f"Drivers fetch error: {e}")

            # Fetch OpenF1 stints
            try:
                st_res = requests.get(f"{self.OPENF1_BASE}/stints?session_key={session_key}", timeout=self.timeout)
                if st_res.ok:
                    data["stints"] = st_res.json()
            except Exception as e:
                logger.warning(f"Stints fetch error: {e}")

            # Fetch OpenF1 pit stops
            try:
                p_res = requests.get(f"{self.OPENF1_BASE}/pit?session_key={session_key}", timeout=self.timeout)
                if p_res.ok:
                    data["pit_stops"] = p_res.json()
            except Exception as e:
                logger.warning(f"Pit stops fetch error: {e}")

            # Fetch OpenF1 laps
            try:
                l_res = requests.get(f"{self.OPENF1_BASE}/laps?session_key={session_key}", timeout=self.timeout)
                if l_res.ok:
                    data["laps"] = l_res.json()
            except Exception as e:
                logger.warning(f"Laps fetch error: {e}")

            # Fetch OpenF1 weather
            try:
                w_res = requests.get(f"{self.OPENF1_BASE}/weather?session_key={session_key}", timeout=self.timeout)
                if w_res.ok and w_res.json():
                    w_list = w_res.json()
                    # compute average temperatures
                    track_temps = [w["track_temperature"] for w in w_list if w.get("track_temperature") is not None]
                    air_temps = [w["air_temperature"] for w in w_list if w.get("air_temperature") is not None]
                    humidity = [w["humidity"] for w in w_list if w.get("humidity") is not None]
                    rainfall = any(w.get("rainfall", 0) > 0 for w in w_list)
                    data["weather"] = {
                        "track_temp_c": round(sum(track_temps)/len(track_temps), 1) if track_temps else 30.0,
                        "air_temp_c": round(sum(air_temps)/len(air_temps), 1) if air_temps else 25.0,
                        "humidity_pct": int(sum(humidity)/len(humidity)) if humidity else 45,
                        "is_wet": rainfall
                    }
            except Exception as e:
                logger.warning(f"Weather fetch error: {e}")

        # If data is populated, save to cache
        if data.get("laps") or data.get("results"):
            self._save_cached_json(cache_file, data)

        return data

