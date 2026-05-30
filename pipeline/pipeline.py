for item in data:
    try:
        label = generate_nutrition_label(item)
        check_length(label)
    except ValueError as e:
        logging.error(f"재시도 필요: {e}")
        # 재시도 로직 추가 (예: 3회 시도)
        for _ in range(3):
            try:
                label = generate_nutrition_label(item)
                check_length(label)
                break
            except ValueError:
                continue