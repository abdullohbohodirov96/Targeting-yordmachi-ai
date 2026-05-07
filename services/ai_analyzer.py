async def analyze_data(data: dict) -> str:
    """
    AI tahlili. Hozircha statik, kelajakda OpenAI API ulanadi.
    """
    cpl = data.get("cpl", 0)
    ctr = data.get("ctr", 0)
    
    analysis = "CPL "
    if cpl <= 0.40:
        analysis += "yaxshi. "
    else:
        analysis += "normal. "
        
    analysis += "CTR "
    if ctr >= 1.0:
        analysis += "normal. "
    else:
        analysis += "past. "
        
    analysis += "Eng yaxshi kampaniyani kuchaytirish mumkin."
    
    return analysis
