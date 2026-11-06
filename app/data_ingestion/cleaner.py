from typing import Dict, Any, List, Optional, Tuple

class DataCleaner:
    """
    Validates, normalizes, and cleans raw timing, driver, and stint data
    from FastF1 / OpenF1 before database insertion.
    """
    
    COMPOUND_MAP = {
        "SOFT": "SOFT",
        "MEDIUM": "MEDIUM",
        "HARD": "HARD",
        "INTERMEDIATE": "INTER",
        "INTER": "INTER",
        "WET": "WET",
    }

    # Driver number to 3-letter code mapping (2024-2026 grid)
    DRIVER_NUM_MAP = {
        1: ("VER", "Max Verstappen"),
        4: ("NOR", "Lando Norris"),
        16: ("LEC", "Charles Leclerc"),
        44: ("HAM", "Lewis Hamilton"),
        55: ("SAI", "Carlos Sainz Jr."),
        63: ("RUS", "George Russell"),
        81: ("PIA", "Oscar Piastri"),
        11: ("PER", "Sergio Perez"),
        14: ("ALO", "Fernando Alonso"),
        18: ("STR", "Lance Stroll"),
        10: ("GAS", "Pierre Gasly"),
        31: ("OCO", "Esteban Ocon"),
        23: ("ALB", "Alex Albon"),
        2:  ("SAR", "Logan Sargeant"),
        22: ("TSU", "Yuki Tsunoda"),
        3:  ("RIC", "Daniel Ricciardo"),
        30: ("LAW", "Liam Lawson"),
        27: ("HUL", "Nico Hulkenberg"),
        20: ("MAG", "Kevin Magnussen"),
        77: ("BOT", "Valtteri Bottas"),
        24: ("ZHO", "Guanyu Zhou"),
        38: ("BEA", "Oliver Bearman"),
        43: ("COL", "Franco Colapinto"),
        12: ("ANT", "Kimi Antonelli"),
        6:  ("HAD", "Isack Hadjar"),
        5:  ("BOR", "Gabriel Bortoleto"),
        7:  ("LIN", "Arvid Lindblad"),
    }

    @classmethod
    def clean_compound(cls, raw_compound: Optional[str]) -> str:
        if not raw_compound:
            return "MEDIUM"
        norm = str(raw_compound).upper().strip()
        return cls.COMPOUND_MAP.get(norm, "MEDIUM")

    @classmethod
    def resolve_driver(cls, driver_number: Optional[int], name_acronym: Optional[str] = None, full_name: Optional[str] = None) -> Tuple[str, str]:
        """
        Resolves driver 3-letter code and full name.
        """
        if name_acronym and len(str(name_acronym).strip()) == 3:
            code = str(name_acronym).upper().strip()
            name = full_name or code
            return code, name
            
        if driver_number and int(driver_number) in cls.DRIVER_NUM_MAP:
            return cls.DRIVER_NUM_MAP[int(driver_number)]
            
        code = (name_acronym or f"D{driver_number or 99}")[:3].upper()
        name = full_name or f"Driver {driver_number or code}"
        return code, name

    @classmethod
    def clean_lap_rows(cls, raw_laps: List[Dict[str, Any]], driver_map: Dict[int, str]) -> List[Dict[str, Any]]:
        """
        Cleans and structures lap records.
        """
        cleaned = []
        for lap in raw_laps:
            driver_num = lap.get("driver_number")
            code = driver_map.get(driver_num)
            if not code:
                code, _ = cls.resolve_driver(driver_num)
            
            lap_no = lap.get("lap_number")
            if not lap_no or int(lap_no) < 1:
                continue
                
            lap_duration = lap.get("lap_duration")
            # In OpenF1 or FastF1, lap_duration can be float seconds or None
            lap_time_s = float(lap_duration) if lap_duration is not None and float(lap_duration) > 0 else None
            
            s1 = lap.get("duration_sector_1")
            s2 = lap.get("duration_sector_2")
            s3 = lap.get("duration_sector_3")
            
            s1_s = float(s1) if s1 is not None and float(s1) > 0 else None
            s2_s = float(s2) if s2 is not None and float(s2) > 0 else None
            s3_s = float(s3) if s3 is not None and float(s3) > 0 else None
            
            is_pit = bool(lap.get("is_pit_out_lap", False))
            
            cleaned.append({
                "driver_code": code,
                "driver_number": driver_num,
                "lap_no": int(lap_no),
                "lap_time_s": lap_time_s,
                "sector1_s": s1_s,
                "sector2_s": s2_s,
                "sector3_s": s3_s,
                "tyre_age_laps": 1,  # Calculated in importer
                "position": None,
                "is_pit_lap": is_pit
            })
        return cleaned

    @classmethod
    def clean_stint_rows(cls, raw_stints: List[Dict[str, Any]], driver_map: Dict[int, str]) -> List[Dict[str, Any]]:
        """
        Cleans tyre stint records.
        """
        cleaned = []
        for s in raw_stints:
            driver_num = s.get("driver_number")
            code = driver_map.get(driver_num)
            if not code:
                code, _ = cls.resolve_driver(driver_num)
                
            stint_no = s.get("stint_number") or 1
            start_lap = s.get("lap_start") or 1
            end_lap = s.get("lap_end") or start_lap
            compound = cls.clean_compound(s.get("compound"))
            
            if end_lap < start_lap:
                end_lap = start_lap
                
            cleaned.append({
                "driver_code": code,
                "driver_number": driver_num,
                "stint_no": int(stint_no),
                "compound": compound,
                "start_lap": int(start_lap),
                "end_lap": int(end_lap)
            })
        return cleaned

    @classmethod
    def clean_pit_rows(cls, raw_pits: List[Dict[str, Any]], driver_map: Dict[int, str]) -> List[Dict[str, Any]]:
        """
        Cleans pit stop execution records.
        """
        cleaned = []
        driver_stop_counts: Dict[str, int] = {}
        for p in raw_pits:
            driver_num = p.get("driver_number")
            code = driver_map.get(driver_num)
            if not code:
                code, _ = cls.resolve_driver(driver_num)
                
            lap_no = p.get("lap_number") or 1
            dur = p.get("pit_duration") or p.get("lane_duration")
            stat = p.get("stop_duration")  # Stationary wheel gun time
            
            dur_s = float(dur) if dur is not None and float(dur) > 0 else 22.0
            stat_s = float(stat) if stat is not None and float(stat) > 0 else None
            
            # Sanitize: stationary time cannot exceed pit lane duration
            if stat_s is not None and dur_s is not None and stat_s > dur_s:
                dur_s = stat_s + 18.0
            
            driver_stop_counts[code] = driver_stop_counts.get(code, 0) + 1
            
            cleaned.append({
                "driver_code": code,
                "driver_number": driver_num,
                "stop_no": driver_stop_counts[code],
                "lap_no": int(lap_no),
                "pit_duration_s": round(dur_s, 2) if dur_s else None,
                "stationary_time_s": round(stat_s, 2) if stat_s else None
            })
        return cleaned
