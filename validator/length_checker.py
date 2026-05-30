def check_length(text):
    if len(text) < 40 or "영양소명" not in text:
        raise ValueError(f"길이 부족 또는 영양소명 누락: {len(text)}자, {text}")